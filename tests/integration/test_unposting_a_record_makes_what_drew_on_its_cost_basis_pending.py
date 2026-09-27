"""Unposting a record makes every disposal that drew on its cost basis pending.

Unposting destroys the record's posting, and the posting's split is the
record's cost basis. A disposal that stated that cost basis's guid would then
state a guid the book no longer holds. The unpost is not refused for it: the
user may not know yet which cost basis the disposal draws on instead, and is
not made to choose one before the unpost can go through. Each such disposal
is written `cost_basis_split_guid: $pending$`, the command lists them, and an
edit states the cost basis each draws on when the user knows.

The books keep a second cost basis on the same side, so each disposal made
pending has one to wait for: `usd_collected_off_an_invoice_and_still_held.txt`
with 1,000.00 USD more bought at 1.40, and
`usd_owed_on_a_card_that_paid_a_bill.txt` with 500.00 USD more drawn on the
card at 1.38.
"""

import re

from click.testing import CliRunner

from tests.conftest import _run

FIXTURES = 'tests/fixtures/'
RATES = FIXTURES + 'usd_at_the_rates_the_statement_lines_records_were_posted_at.yaml'
COLLECTED = FIXTURES + 'usd_collected_off_an_invoice_and_still_held.txt'
OWED_ON_THE_CARD = FIXTURES + 'usd_owed_on_a_card_that_paid_a_bill.txt'

DOLLARS_BOUGHT = ('2026-08-20 * "Dollars bought"\n'
                  '\tcurrency.mnemonic: "USD"\n'
                  '\tAssets:Wise USD 1000.00 USD\n'
                  '\tAssets:Chequing -1400.00 CAD\n'
                  '\t\taccount.commodity.mnemonic: "CAD"\n'
                  '\t\tvalue: "-1000.00"\n')

CARD_ADVANCE = ('2026-08-20 * "Cash advance"\n'
                '\tcurrency.mnemonic: "USD"\n'
                '\tLiabilities:Credit Card USD -500.00 USD\n'
                '\tAssets:Chequing 690.00 CAD\n'
                '\t\taccount.commodity.mnemonic: "CAD"\n'
                '\t\tvalue: "500.00"\n')


def _ledger(tmp_path, name, text):
    path = tmp_path / f'{name}.txt'
    path.write_text(text)
    return str(path)


def _book(tmp_path, *ledgers):
    book = tmp_path / 'book.gnucash'
    for number, ledger in enumerate(ledgers):
        made = _run(CliRunner(), 'import', *(['--new'] if number == 0 else []), str(book),
                    ledger, '--include-business-objects', '--fx-rates', RATES)
        assert made.exit_code == 0 and 'Errors:       0' in made.output, made.output
    return book


def _listing(book):
    costs = _run(CliRunner(), 'fx-balances', str(book), '--verify-costs')
    assert costs.exit_code == 0 and 'warning' not in costs.output, costs.output
    integrity = _run(CliRunner(), '--verify-integrity', str(book))
    assert integrity.exit_code == 0, integrity.output
    return costs.output


def _costs(book):
    """`fx-balances --verify-costs` after the unpost.

    Not `--verify-integrity`: the unpost leaves the payment that collected the
    invoice orphaned, dollars held that no cost basis stands for until the
    invoice is posted again and the payment linked to it, which is the state
    `unpost-invoices` warns about whatever it makes pending.
    """
    costs = _run(CliRunner(), 'fx-balances', str(book), '--verify-costs')
    assert costs.exit_code == 0 and 'warning' not in costs.output, costs.output
    return costs.output


def _guid_on(book, account):
    listed = _costs(book)
    found = re.search(rf'([0-9a-f]{{32}})\s+{re.escape(account)}\s', listed)
    assert found, listed
    return found.group(1)


def _imported(book, ledger):
    done = _run(CliRunner(), 'import', str(book), ledger)
    assert done.exit_code == 0 and 'Errors:       0' in done.output, done.output


def _sale(pick):
    return ('2026-09-01 * "Sell one dollar"\n'
            '\tguid: "0a540000000000000000000000000001"\n'
            '\tcurrency.mnemonic: "USD"\n'
            '\tAssets:Wise USD -1.00 USD\n'
            f'\t\tcost_basis_split_guid: {pick}\n'
            '\tAssets:Chequing 1.40 CAD\n'
            '\t\taccount.commodity.mnemonic: "CAD"\n'
            '\t\tvalue: "1.00"\n')


def _repayment(pick):
    return ('2026-09-01 * "Card part paid back"\n'
            '\tguid: "0a540000000000000000000000000002"\n'
            '\tcurrency.mnemonic: "USD"\n'
            '\tLiabilities:Credit Card USD 100.00 USD\n'
            f'\t\tcost_basis_split_guid: {pick}\n'
            '\tAssets:Chequing -138.00 CAD\n'
            '\t\taccount.commodity.mnemonic: "CAD"\n'
            '\t\tvalue: "-100.00"\n')


def _edited(book, ledger):
    """The user stating the cost basis a pending disposal draws on, by an edit in place."""
    done = _run(CliRunner(), 'import', '--strategy', 'update', str(book), ledger)
    assert done.exit_code == 0 and 'Errors:       0' in done.output, done.output


class TestAnInvoiceUnposted:
    def _book_with_a_sale_on_the_invoice(self, tmp_path):
        book = _book(tmp_path, COLLECTED, _ledger(tmp_path, 'bought', DOLLARS_BOUGHT))
        invoice = _guid_on(book, 'Assets:Accounts Receivable USD')
        _imported(book, _ledger(tmp_path, 'sale', _sale(f'"{invoice}"')))
        return book

    def test_the_user_then_states_the_purchase_s_cost_basis_on_the_sale(self, tmp_path):
        book = self._book_with_a_sale_on_the_invoice(tmp_path)
        _run(CliRunner(), 'unpost-invoices', str(book), 'INV-USD-1')
        bought = _guid_on(book, 'Assets:Wise USD')

        _edited(book, _ledger(tmp_path, 'restated', _sale(f'"{bought}"')))

        listed = _costs(book)
        assert 'pending their cost basis' not in listed, listed
        assert re.search(rf'{bought}\s+Assets:Wise USD\s+1\.4 CAD/USD\s+1,000\.00 USD\s+'
                         r'999\.00 USD\s+asset', listed), listed

    def test_the_unpost_is_accepted_and_lists_the_sale_made_pending(self, tmp_path):
        book = self._book_with_a_sale_on_the_invoice(tmp_path)

        done = _run(CliRunner(), 'unpost-invoices', str(book), 'INV-USD-1')

        assert done.exit_code == 0, done.output
        assert re.search(r'INV-USD-1 \([0-9a-f]{32}\): unposted', done.output), done.output
        assert ('1 disposal(s) drew on its cost basis and are now pending their cost '
                'basis') in done.output, done.output
        assert "2026-09-01 'Sell one dollar' (1.00 USD)" in done.output, done.output

    def test_an_import_unposting_the_invoice_makes_the_sale_pending_and_says_so(self, tmp_path):
        """The invoice imported again with `posted: none`.

        The import unposts it, which destroys its cost basis as
        `unpost-invoices` does, so the sale that drew on it is made pending,
        and the run says how many were.
        """
        from pathlib import Path

        book = self._book_with_a_sale_on_the_invoice(tmp_path)
        text = Path(COLLECTED).read_text()
        posted = ('\tposted:\n'
                  '\t\tdate: 2026-07-31\n'
                  '\t\tdue: 2026-08-30\n'
                  '\t\tar_account: "Assets:Accounts Receivable USD"\n'
                  '\t\tmemo: "Invoice INV-USD-1"\n'
                  '\t\taccumulate: true\n'
                  '\tpayment:\n'
                  '\t\tdate: 2026-08-13\n'
                  '\t\tamount: 2720\n'
                  '\t\taccount: "Assets:Wise USD"\n'
                  '\t\tmemo: "Collected INV-USD-1"\n')
        assert posted in text
        edited = _ledger(tmp_path, 'edited', text.replace(posted, '\tposted: none\n'))

        done = _run(CliRunner(), 'import', str(book), edited,
                    '--include-business-objects', '--fx-rates', RATES)

        assert done.exit_code == 0, done.output
        assert ("⚠ invoice 'INV-USD-1': unposting it destroys its cost basis, so 1 "
                'disposal(s) that drew on it are now pending their cost basis') \
            in done.output, done.output
        assert "2026-09-01 'Sell one dollar' (1.00 USD)" in done.output, done.output
        assert '1 disposal(s) pending their cost basis: 1.00 USD.' in _costs(book)

    def test_the_book_s_own_export_imported_again_leaves_the_sale_where_it_is(self, tmp_path):
        """Nothing in the export differs from the book, so the invoice is not
        rebuilt, and the sale keeps the invoice's cost basis."""
        book = self._book_with_a_sale_on_the_invoice(tmp_path)
        invoice = _guid_on(book, 'Assets:Accounts Receivable USD')
        out = tmp_path / 'out.txt'
        assert _run(CliRunner(), 'export', str(book), str(out),
                    '--include-business-objects').exit_code == 0

        done = _run(CliRunner(), 'import', str(book), str(out),
                    '--include-business-objects', '--fx-rates', RATES)

        assert done.exit_code == 0, done.output
        assert 'invoice "INV-USD-1": unchanged' in done.output, done.output
        assert 'pending' not in done.output, done.output
        listed = _costs(book)
        assert 'pending their cost basis' not in listed, listed
        assert re.search(rf'{invoice}\s+Assets:Accounts Receivable USD\s+.*\s+asset',
                         listed), listed

    def test_the_sale_is_pending_and_the_invoice_s_cost_basis_is_gone(self, tmp_path):
        book = self._book_with_a_sale_on_the_invoice(tmp_path)

        _run(CliRunner(), 'unpost-invoices', str(book), 'INV-USD-1')

        listed = _costs(book)
        assert 'Invoice INV-USD-1' not in listed, listed
        assert '1 disposal(s) pending their cost basis: 1.00 USD.' in listed, listed


class TestABillUnposted:
    def _book_with_a_repayment_on_the_bill(self, tmp_path):
        book = _book(tmp_path, OWED_ON_THE_CARD, _ledger(tmp_path, 'advance', CARD_ADVANCE))
        bill = _guid_on(book, 'Liabilities:Accounts Payable USD')
        _imported(book, _ledger(tmp_path, 'repay', _repayment(f'"{bill}"')))
        return book

    def test_the_user_then_states_the_cash_advance_s_cost_basis_on_it(self, tmp_path):
        book = self._book_with_a_repayment_on_the_bill(tmp_path)
        _run(CliRunner(), 'unpost-bills', str(book), 'BILL-USD-1')
        advance = _guid_on(book, 'Liabilities:Credit Card USD')

        _edited(book, _ledger(tmp_path, 'restated', _repayment(f'"{advance}"')))

        listed = _costs(book)
        assert 'pending their cost basis' not in listed, listed
        assert re.search(rf'{advance}\s+Liabilities:Credit Card USD\s+1\.38 CAD/USD\s+'
                         r'500\.00 USD\s+400\.00 USD\s+liability', listed), listed

    def test_the_unpost_is_accepted_and_lists_the_repayment_made_pending(self, tmp_path):
        book = self._book_with_a_repayment_on_the_bill(tmp_path)

        done = _run(CliRunner(), 'unpost-bills', str(book), 'BILL-USD-1')

        assert done.exit_code == 0, done.output
        assert re.search(r'BILL-USD-1 \([0-9a-f]{32}\): unposted', done.output), done.output
        assert "2026-09-01 'Card part paid back' (100.00 USD)" in done.output, done.output

    def test_the_repayment_is_pending(self, tmp_path):
        book = self._book_with_a_repayment_on_the_bill(tmp_path)

        _run(CliRunner(), 'unpost-bills', str(book), 'BILL-USD-1')

        listed = _costs(book)
        assert 'Bill BILL-USD-1' not in listed, listed
        assert '1 disposal(s) pending their cost basis: 100.00 USD.' in listed, listed
