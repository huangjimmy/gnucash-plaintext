"""An overpayment opens a liability cost basis on the receivable and an asset cost basis on the bank.

`fx_invoice_usd_overpaid_into_usd_bank.txt`: INV-USD-OVER bills 100.00 USD,
posted on 2026-01-05 at 1.40, which opens the invoice's asset cost basis of
100.00 USD. It is paid 200.00 USD into Assets:Bank:USD on 2026-02-25, the
rates file giving 1.37 that day:

	Assets:Bank:USD                   200.00 USD     bank: 0 → +200
	Assets:Accounts Receivable USD   -200.00 USD     A/R: +100 → −100

The first 100.00 settles the invoice. The other 100.00 does not belong to
the company yet: on the receivable it goes below zero and opens a liability
cost basis of 100.00 USD, and on the bank it opens an asset cost basis of
100.00 USD, each at the payment's 1.37.

Dollars leaving the bank are dollars held, so a sale of them draws on an
asset cost basis: the bank's or the invoice's, by its guid or pending.
Stating the liability cost basis the overpayment opened draws dollars held
from a cost basis of dollars owed and is refused, and stating none is refused
because the book keeps a cost basis the sale must choose.
"""

import re
from pathlib import Path

from click.testing import CliRunner

from tests.conftest import _run

FIXTURES = 'tests/fixtures/'
OVERPAID = FIXTURES + 'fx_invoice_usd_overpaid_into_usd_bank.txt'
RATES = FIXTURES + 'fx_rates_usd_dated.yaml'

INVOICE = r'2026-01-05\s+([0-9a-f]{32})\s+Assets:Accounts Receivable USD\s+'
CREDIT = r'2026-02-25\s+([0-9a-f]{32})\s+Assets:Accounts Receivable USD\s+'
BANK = r'2026-02-25\s+([0-9a-f]{32})\s+Assets:Bank:USD\s+'


def _book(tmp_path):
    book = tmp_path / 'book.gnucash'
    made = _run(CliRunner(), 'import', '--new', str(book), OVERPAID,
                '--include-business-objects', '--fx-rates', RATES)
    assert made.exit_code == 0 and 'Errors:       0' in made.output, made.output
    return book


def _listing(book):
    costs = _run(CliRunner(), 'fx-balances', str(book), '--verify-costs')
    assert costs.exit_code == 0 and 'warning' not in costs.output, costs.output
    integrity = _run(CliRunner(), '--verify-integrity', str(book))
    assert integrity.exit_code == 0, integrity.output
    return costs.output


def _guid(book, row):
    listed = _listing(book)
    found = re.search(row, listed)
    assert found, listed
    return found.group(1)


def _sale(tmp_path, pick, amount='80.00', cad='110.00'):
    ledger = tmp_path / 'sale.txt'
    ledger.write_text(f'2026-03-01 * "Sell {amount} USD"\n'
                      '\tguid: "0a540000000000000000000000000003"\n'
                      '\tcurrency.mnemonic: "USD"\n'
                      f'\tAssets:Bank:USD -{amount} USD\n'
                      + (f'\t\tcost_basis_split_guid: {pick}\n' if pick else '')
                      + f'\tAssets:Bank {cad} CAD\n'
                      '\t\taccount.commodity.mnemonic: "CAD"\n'
                      f'\t\tvalue: "{amount}"\n')
    return str(ledger)


def _import(book, ledger):
    return _run(CliRunner(), 'import', str(book), ledger)


class TestThePayment:
    def test_the_invoice_s_asset_cost_basis_stays_at_1_40(self, tmp_path):
        listed = _listing(_book(tmp_path))

        assert re.search(INVOICE + r'1\.4 CAD/USD\s+100\.00 USD\s+100\.00 USD\s+asset',
                         listed), listed

    def test_the_receivable_opens_a_liability_cost_basis_of_100_at_1_37(self, tmp_path):
        listed = _listing(_book(tmp_path))

        assert re.search(CREDIT + r'1\.37 CAD/USD\s+100\.00 USD\s+100\.00 USD\s+liability',
                         listed), listed

    def test_before_the_payment_the_book_holds_the_invoice_alone(self, tmp_path):
        """Checked on 2026-02-01, the receivable holds the 100.00 invoiced.

        The payment's split on the receivable is dated after that day, so it is
        left out of what the receivable held, as the credit it opens is left
        out of the cost bases, and the book is consistent on that day.
        """
        book = _book(tmp_path)

        checked = _run(CliRunner(), 'verify-integrity', str(book), '--as-of', '2026-02-01')

        assert checked.exit_code == 0, checked.output
        assert 'The book is consistent and balanced.' in checked.output, checked.output

    def test_the_bank_opens_an_asset_cost_basis_of_100_at_1_37(self, tmp_path):
        listed = _listing(_book(tmp_path))

        assert re.search(BANK + r'1\.37 CAD/USD\s+100\.00 USD\s+100\.00 USD\s+asset',
                         listed), listed


class TestABookAnEarlierReleaseWrote:
    """The bank's split carrying no cost basis keys, as the release before
    Q-054 left an overpayment: it read the customer's credit as the cost of
    the dollars the overpayment brought into the bank, and opened no cost
    basis on the bank's split.

    Nothing rewrites them on its own: the book holds no record of what they
    cost beyond what its splits say, and this tool states none it was not
    given. `--verify-costs` says what no longer holds, and the book's own
    export imported into a new book is read under these rules.
    """

    def _as_an_earlier_release_left_it(self, tmp_path):
        from infrastructure.gnucash.kvp import get_custom_metadata, set_custom_metadata
        from repositories.gnucash_repository import GnuCashRepository, SessionMode
        from services.foreign_currency import (
            COST_BASIS_BALANCE_KEY,
            COST_BASIS_BROUGHT_IN_KEY,
            COST_BASIS_COST_KEY,
        )

        book = _book(tmp_path)
        payment = _payment_guid(book, tmp_path)
        repo = GnuCashRepository(str(book))
        repo.open(mode=SessionMode.NORMAL)
        try:
            transaction = next(each for each in _transactions(repo.book)
                               if each.GetGUID().to_string() == payment)
            transaction.BeginEdit()
            for split in transaction.GetSplitList():
                if split.GetAccount().GetName() != 'USD':
                    continue
                kept = {key: value for key, value in get_custom_metadata(split).items()
                        if key not in (COST_BASIS_BALANCE_KEY, COST_BASIS_BROUGHT_IN_KEY,
                                       COST_BASIS_COST_KEY)}
                set_custom_metadata(split, kept)
            transaction.CommitEdit()
            repo.save()
        finally:
            repo.close()
        return book

    def test_the_bank_s_dollars_past_the_invoice_have_no_cost_basis(self, tmp_path):
        """Held, and no cost basis stands for them, as for any dollars a book
        received stating no Canadian figure; nothing opens one unasked."""
        book = self._as_an_earlier_release_left_it(tmp_path)

        costs = _run(CliRunner(), 'fx-balances', str(book), '--verify-costs')

        assert costs.exit_code == 0, costs.output
        assert 'Total USD cost basis balance: 100.00 USD held, 100.00 USD owed' in \
            costs.output, costs.output
        assert 'Total USD held in accounts: 200.00 USD' in costs.output, costs.output

    def test_its_export_imported_into_a_new_book_is_consistent(self, tmp_path):
        book = self._as_an_earlier_release_left_it(tmp_path)
        out = tmp_path / 'out.txt'
        assert _run(CliRunner(), 'export', str(book), str(out),
                    '--include-business-objects').exit_code == 0
        rebuilt = tmp_path / 'rebuilt.gnucash'

        made = _run(CliRunner(), 'import', '--new', str(rebuilt), str(out),
                    '--include-business-objects', '--fx-rates', RATES)

        assert made.exit_code == 0 and 'Errors:       0' in made.output, made.output
        listed = _listing(rebuilt)
        assert re.search(CREDIT + r'1\.37 CAD/USD\s+100\.00 USD\s+100\.00 USD\s+liability',
                         listed), listed
        assert re.search(BANK + r'1\.37 CAD/USD\s+100\.00 USD\s+100\.00 USD\s+asset',
                         listed), listed


def _transactions(book):
    from gnucash import Query, Transaction

    query = Query()
    query.search_for('Trans')
    query.set_book(book)
    found = [Transaction(instance=raw) for raw in query.run()]
    query.destroy()
    return found


class TestASaleOfTheDollarsHeld:
    def test_stating_the_bank_s_asset_cost_basis_draws_it_down(self, tmp_path):
        book = _book(tmp_path)
        bank = _guid(book, BANK)

        done = _import(book, _sale(tmp_path, f'"{bank}"'))

        assert 'Errors:       0' in done.output, done.output
        assert re.search(BANK + r'1\.37 CAD/USD\s+100\.00 USD\s+20\.00 USD\s+asset',
                         _listing(book)), _listing(book)

    def test_50_sold_for_65_cad_leaves_50_on_the_bank_s_asset_cost_basis(self, tmp_path):
        book = _book(tmp_path)
        bank = _guid(book, BANK)
        ledger = tmp_path / 'sale.txt'
        ledger.write_text('2026-03-01 * "Sell 50.00 USD"\n'
                          '\tcurrency.mnemonic: "USD"\n'
                          '\tAssets:Bank:USD -50.00 USD\n'
                          f'\t\tcost_basis_split_guid: "{bank}"\n'
                          '\tAssets:Bank 65.00 CAD\n'
                          '\t\taccount.commodity.mnemonic: "CAD"\n'
                          '\t\tvalue: "50.00"\n')

        done = _import(book, str(ledger))

        assert 'Errors:       0' in done.output, done.output
        listed = _listing(book)
        assert re.search(BANK + r'1\.37 CAD/USD\s+100\.00 USD\s+50\.00 USD\s+asset', listed), listed
        assert re.search(CREDIT + r'1\.37 CAD/USD\s+100\.00 USD\s+100\.00 USD\s+liability',
                         listed), listed

    def test_all_100_of_the_bank_s_asset_cost_basis_may_be_sold(self, tmp_path):
        book = _book(tmp_path)
        bank = _guid(book, BANK)

        done = _import(book, _sale(tmp_path, f'"{bank}"', '100.00', '137.00'))

        assert 'Errors:       0' in done.output, done.output
        assert re.search(BANK + r'1\.37 CAD/USD\s+100\.00 USD\s+0\.00 USD\s+asset',
                         _listing(book)), _listing(book)

    def test_100_01_stating_the_bank_s_asset_cost_basis_is_refused(self, tmp_path):
        book = _book(tmp_path)
        bank = _guid(book, BANK)

        done = _import(book, _sale(tmp_path, f'"{bank}"', '100.01', '137.01'))

        assert 'Errors:       1' in done.output, done.output
        assert (f'100.01 USD against cost basis {bank} exceeds its cost basis balance '
                f'by 0.01 USD') in done.output, done.output

    def test_stating_the_invoice_s_asset_cost_basis_draws_it_down(self, tmp_path):
        book = _book(tmp_path)
        invoice = _guid(book, INVOICE)

        done = _import(book, _sale(tmp_path, f'"{invoice}"'))

        assert 'Errors:       0' in done.output, done.output
        assert re.search(INVOICE + r'1\.4 CAD/USD\s+100\.00 USD\s+20\.00 USD\s+asset',
                         _listing(book)), _listing(book)

    def test_pending_its_cost_basis_it_is_counted_pending(self, tmp_path):
        book = _book(tmp_path)

        done = _import(book, _sale(tmp_path, '$pending$'))

        assert 'Errors:       0' in done.output, done.output
        listed = _listing(book)
        assert '1 disposal(s) pending their cost basis: 80.00 USD.' in listed, listed

    def test_a_sale_stating_a_guid_after_a_pending_one_takes_only_what_the_bank_holds(
            self, tmp_path):
        """150.00 USD sold pending, then 80.00 stating the bank's cost basis.

        The bank holds 50.00 after the pending sale, so the second disposes of
        50.00 and takes the bank 30.00 below zero, which opens a cost basis of
        dollars owed. The cost bases of dollars held keep the 150.00 the
        pending sale needs: a disposal takes no more than its account holds.
        """
        book = _book(tmp_path)
        bank = _guid(book, BANK)
        assert 'Errors:       0' in _import(
            book, _sale(tmp_path, '$pending$', amount='150.00', cad='205.50')).output
        second = tmp_path / 'second.txt'
        second.write_text(Path(_sale(tmp_path, f'"{bank}"')).read_text()
                          .replace('0a540000000000000000000000000003',
                                   '0a540000000000000000000000000006')
                          .replace('2026-03-01', '2026-03-02'))

        done = _import(book, str(second))

        assert 'Errors:       0' in done.output, done.output
        costs = _run(CliRunner(), 'fx-balances', str(book), '--verify-costs').output
        assert re.search(BANK + r'1\.37 CAD/USD\s+100\.00 USD\s+50\.00 USD\s+asset',
                         costs), costs
        assert 'Total USD cost basis balance: 150.00 USD held' in costs, costs

    def test_pending_in_a_transaction_stating_no_cad_figure_is_refused(self, tmp_path):
        """10.00 USD out of the bank for a fee kept in US dollars, the whole entry in USD.

        A pending disposal is subtracted from the cost bases at the Canadian dollar
        figure its transaction records for it, and this one records none.
        """
        book = _book(tmp_path)
        ledger = tmp_path / 'fee.txt'
        ledger.write_text(
            '2026-01-01 open Expenses\n'
            '\ttype: Expense\n'
            '\tcommodity.namespace: "CURRENCY"\n'
            '\tcommodity.mnemonic: "CAD"\n'
            '2026-01-01 open Expenses:Fees USD\n'
            '\ttype: Expense\n'
            '\tcommodity.namespace: "CURRENCY"\n'
            '\tcommodity.mnemonic: "USD"\n'
            '\n'
            '2026-03-01 * "Wire fee"\n'
            '\tcurrency.mnemonic: "USD"\n'
            '\tAssets:Bank:USD -10.00 USD\n'
            '\t\tcost_basis_split_guid: $pending$\n'
            '\tExpenses:Fees USD 10.00 USD\n')

        done = _import(book, str(ledger))

        assert 'Errors:       1' in done.output, done.output
        assert ('the split on Assets:Bank:USD has `cost_basis_split_guid: $pending$`, but its '
                'transaction does not record what it disposes of in CAD') in done.output, \
            done.output

    def test_stating_the_liability_cost_basis_is_refused_as_the_other_side(self, tmp_path):
        book = _book(tmp_path)
        credit = _guid(book, CREDIT)

        done = _import(book, _sale(tmp_path, f'"{credit}"'))

        assert 'Errors:       1' in done.output, done.output
        assert (f"cost_basis_split_guid '{credit}' is a cost basis of USD the book owed, "
                f"but this split spends USD the book held") in done.output, done.output

    def test_selling_part_of_the_customer_s_credit_is_refused(self, tmp_path):
        """`fx_sell_part_of_a_credit.txt`: 80.00 USD sold out of the bank against the credit.

        The credit is owed to the customer, and the sale spends dollars the
        book holds, so it is refused as drawing on the other side, and nothing
        of it reaches the book.
        """
        book = _book(tmp_path)
        credit = _guid(book, CREDIT)
        ledger = tmp_path / 'sale.txt'
        ledger.write_text(Path(FIXTURES + 'fx_sell_part_of_a_credit.txt')
                          .read_text().replace('{basis}', credit))

        done = _import(book, str(ledger))

        assert 'Errors:       1' in done.output, done.output
        assert (f"Sell 80 USD of the credit: cost_basis_split_guid '{credit}' is a cost "
                "basis of USD the book owed, but this split spends USD the book held") \
            in done.output, done.output
        listed = _listing(book)
        assert re.search(CREDIT + r'1\.37 CAD/USD\s+100\.00 USD\s+100\.00 USD\s+liability',
                         listed), listed
        assert re.search(BANK + r'1\.37 CAD/USD\s+100\.00 USD\s+100\.00 USD\s+asset',
                         listed), listed

    def test_a_book_holding_a_sale_that_draws_on_the_credit_is_reported(self, tmp_path):
        """A book an earlier release wrote, whose sale of the bank's dollars states the credit.

        That release let the sale draw on the customer's credit. Its export
        states the credit's guid on the sale, which this release refuses, so
        `--verify-costs` reports it as drawing on the other side.
        """
        from infrastructure.gnucash.kvp import get_custom_metadata, set_custom_metadata
        from repositories.gnucash_repository import GnuCashRepository, SessionMode
        from services.foreign_currency import (
            COST_BASIS_SPLIT_KEY,
            iter_splits,
            split_commodity,
        )

        book = _book(tmp_path)
        bank = _guid(book, BANK)
        credit = _guid(book, CREDIT)
        assert 'Errors:       0' in _import(book, _sale(tmp_path, f'"{bank}"')).output
        repo = GnuCashRepository(str(book))
        repo.open(mode=SessionMode.NORMAL)
        try:
            sale = next(split for split in iter_splits(repo.book)
                        if split.GetParent().GetGUID().to_string()
                        == '0a540000000000000000000000000003'
                        and split_commodity(split) == 'USD')
            transaction = sale.GetParent()
            transaction.BeginEdit()
            set_custom_metadata(sale, {**get_custom_metadata(sale),
                                       COST_BASIS_SPLIT_KEY: credit})
            transaction.CommitEdit()
            repo.save()
        finally:
            repo.close()

        costs = _run(CliRunner(), 'fx-balances', str(book), '--verify-costs')

        assert (f"cost_basis_split_guid '{credit}' is a cost basis of USD the book owed, "
                'but this split spends USD the book held') in costs.output, costs.output

    def test_stating_no_cost_basis_is_refused(self, tmp_path):
        book = _book(tmp_path)

        done = _import(book, _sale(tmp_path, None))

        assert 'Errors:       1' in done.output, done.output
        assert ('A sale requires a consumption of one or more cost bases, but no split '
                'says which.') in done.output, done.output


class TestARepaymentOfDollarsOwed:
    """30.00 USD repaid onto a card owing 50.00, stating the customer's credit.

    Any cost basis of dollars owed may be drawn on by a repayment, the
    customer's credit among them.
    """

    def _repaid(self, tmp_path):
        book = _book(tmp_path)
        credit = _guid(book, CREDIT)
        ledger = tmp_path / 'card.txt'
        ledger.write_text(
            '2026-01-01 open Liabilities\n'
            '\ttype: Liability\n'
            '\tcommodity.namespace: "CURRENCY"\n'
            '\tcommodity.mnemonic: "CAD"\n'
            '2026-01-01 open Liabilities:Card USD\n'
            '\ttype: Credit Card\n'
            '\tcommodity.namespace: "CURRENCY"\n'
            '\tcommodity.mnemonic: "USD"\n'
            '2026-01-01 open Expenses\n'
            '\ttype: Expense\n'
            '\tcommodity.namespace: "CURRENCY"\n'
            '\tcommodity.mnemonic: "CAD"\n'
            '2026-01-01 open Expenses:Supplies\n'
            '\ttype: Expense\n'
            '\tcommodity.namespace: "CURRENCY"\n'
            '\tcommodity.mnemonic: "CAD"\n'
            '\n'
            '2026-03-02 * "Supplies on the card"\n'
            '\tguid: "0a540000000000000000000000000004"\n'
            '\tcurrency.mnemonic: "USD"\n'
            '\tLiabilities:Card USD -50.00 USD\n'
            '\tExpenses:Supplies 68.50 CAD\n'
            '\t\taccount.commodity.mnemonic: "CAD"\n'
            '\t\tvalue: "50.00"\n'
            '\n'
            '2026-03-03 * "Repay 30.00 USD of the card"\n'
            '\tguid: "0a540000000000000000000000000005"\n'
            '\tcurrency.mnemonic: "USD"\n'
            '\tLiabilities:Card USD 30.00 USD\n'
            f'\t\tcost_basis_split_guid: "{credit}"\n'
            '\tAssets:Bank -41.10 CAD\n'
            '\t\taccount.commodity.mnemonic: "CAD"\n'
            '\t\tvalue: "-30.00"\n')
        done = _import(book, str(ledger))
        assert 'Errors:       0' in done.output, done.output
        return book, credit

    def _the_repayments_pick(self, book, tmp_path):
        out = tmp_path / 'out.txt'
        assert _run(CliRunner(), 'export', str(book), str(out),
                    '--include-business-objects').exit_code == 0
        block = re.search(r'"Repay 30\.00 USD of the card"[^\n]*\n(?:\t[^\n]*\n)*',
                          out.read_text()).group(0)
        stated = re.search(r'cost_basis_split_guid: "?([0-9a-f]{32})', block)
        return (stated.group(1) if stated else None), out.read_text()

    def _spend(self, tmp_path, book, price):
        from tests.integration.test_applied_credit_carries_its_basis import SECOND_INVOICE

        second = tmp_path / 'second.txt'
        second.write_text(SECOND_INVOICE.replace('\t\tprice: 40\n', f'\t\tprice: {price}\n'))
        spent = _run(CliRunner(), 'import', str(book), str(second),
                     '--include-business-objects', '--fx-rates', RATES)
        assert spent.exit_code == 0, spent.output

    def test_it_draws_the_credit_down(self, tmp_path):
        """It is no invoice waiting to be collected, so the refusal for selling
        an uncollected invoice's dollars is not asked of it, and the credit
        falls from 100.00 to 70.00."""
        book, _credit = self._repaid(tmp_path)

        listed = _run(CliRunner(), 'fx-balances', str(book)).output
        assert re.search(CREDIT + r'1\.37 CAD/USD\s+100\.00 USD\s+70\.00 USD\s+liability',
                         listed), listed

    def test_spending_part_of_the_credit_points_it_at_what_is_left(self, tmp_path):
        """40.00 of the credit spent on another invoice divides it, and the
        repayment then states the split holding the rest."""
        book, credit = self._repaid(tmp_path)

        self._spend(tmp_path, book, 40)

        stated, text = self._the_repayments_pick(book, tmp_path)
        assert stated and stated != credit, text
        assert re.search(rf'guid: "{stated}"\n(?:\t\t[^\n]*\n)*', text), text

    def test_spending_all_of_the_credit_leaves_it_stating_none_in_the_export(self, tmp_path):
        """100.00 spent takes the whole credit, which is then that invoice's
        settlement and no cost basis, so the export writes the repayment
        stating none."""
        book, _credit = self._repaid(tmp_path)

        self._spend(tmp_path, book, 100)

        stated, text = self._the_repayments_pick(book, tmp_path)
        assert stated is None, text


class TestThePaymentTakenOff:
    """`unapply-payment INV-USD-OVER --to Assets:Bank` at the payment day's 1.37.

    The settlement moves to the Canadian dollar bank, restated at 137.00 CAD,
    and the invoice is open again. Nothing is destroyed: the invoice's asset
    cost basis stands for an invoice not collected, the credit's liability
    cost basis for the 100.00 still owed back, and the bank's 200.00 is now
    all brought in, 100.00 bought with the 137.00 CAD and 100.00 with the
    overpayment, at 1.37. The bank's cost basis changed, so it opens whole at
    200.00, and a sale that drew on it is made pending: which cost basis it
    draws on now is the user's to state, which they then do.
    """

    def _unapplied(self, book):
        done = _run(CliRunner(), 'unapply-payment', str(book), 'INV-USD-OVER',
                    '--to', 'Assets:Bank', '--fx-rates', RATES)
        assert done.exit_code == 0, done.output
        return done.output

    def test_the_bank_s_asset_cost_basis_opens_whole_at_200(self, tmp_path):
        book = _book(tmp_path)

        self._unapplied(book)

        listed = _listing(book)
        assert re.search(BANK + r'1\.37 CAD/USD\s+200\.00 USD\s+200\.00 USD\s+asset',
                         listed), listed
        assert re.search(CREDIT + r'1\.37 CAD/USD\s+100\.00 USD\s+100\.00 USD\s+liability',
                         listed), listed
        assert re.search(INVOICE + r'1\.4 CAD/USD\s+100\.00 USD\s+100\.00 USD\s+asset',
                         listed), listed

    def test_a_sale_that_drew_on_it_is_made_pending(self, tmp_path):
        book = _book(tmp_path)
        bank = _guid(book, BANK)
        assert 'Errors:       0' in _import(book, _sale(tmp_path, f'"{bank}"')).output

        said = self._unapplied(book)

        assert "2026-03-01 'Sell 80.00 USD' (80.00 USD)" in said, said
        listed = _listing(book)
        assert '1 disposal(s) pending their cost basis: 80.00 USD.' in listed, listed
        assert re.search(BANK + r'1\.37 CAD/USD\s+200\.00 USD\s+200\.00 USD\s+asset',
                         listed), listed

    def test_the_user_then_states_the_bank_s_cost_basis_on_the_sale(self, tmp_path):
        book = _book(tmp_path)
        bank = _guid(book, BANK)
        _import(book, _sale(tmp_path, f'"{bank}"'))
        self._unapplied(book)

        done = _run(CliRunner(), 'import', '--strategy', 'update', str(book),
                    _sale(tmp_path, f'"{bank}"'))

        assert 'Errors:       0' in done.output, done.output
        listed = _listing(book)
        assert 'pending their cost basis' not in listed, listed
        assert re.search(BANK + r'1\.37 CAD/USD\s+200\.00 USD\s+120\.00 USD\s+asset',
                         listed), listed


def _payment_guid(book, tmp_path):
    exported = tmp_path / 'exported.txt'
    assert _run(CliRunner(), 'export', str(book), str(exported)).exit_code == 0
    found = re.search(r'\n2026-02-25 \* "US Customer"\n\tguid: "([0-9a-f]{32})"',
                      exported.read_text())
    assert found, exported.read_text()
    return found.group(1)


class TestThePaymentDeleted:
    """The 200.00 USD payment deleted: the money never came.

    `delete-transactions` takes the payment away, and with it the bank's and
    the credit's cost bases. The invoice is open again, 100.00 USD held at
    its 1.40. The sale of 80.00 USD that drew on the bank's cost basis is made
    pending. The bank has nothing in it, so the sale took it from 0 to −80.00:
    the user clears the sale's pick, and the sale opens a liability cost basis
    of 80.00 at the 110.00 CAD it records, 1.375.
    """

    def _deleted(self, tmp_path):
        book = _book(tmp_path)
        bank = _guid(book, BANK)
        assert 'Errors:       0' in _import(book, _sale(tmp_path, f'"{bank}"')).output
        payment = _payment_guid(book, tmp_path)
        done = _run(CliRunner(), 'delete-transactions', str(book), '--by-guid', payment)
        assert done.exit_code == 0, done.output
        return book, done.output

    def test_the_sale_is_listed_as_made_pending(self, tmp_path):
        _book_, said = self._deleted(tmp_path)

        assert "2026-03-01 'Sell 80.00 USD' (80.00 USD)" in said, said

    def test_an_edit_stating_no_pick_leaves_the_sale_pending(self, tmp_path):
        """A sale block with no `cost_basis_split_guid:` line says nothing about it."""
        book, _said = self._deleted(tmp_path)

        done = _run(CliRunner(), 'import', '--strategy', 'update', str(book),
                    _sale(tmp_path, None))

        assert 'Errors:       0' in done.output, done.output
        costs = _run(CliRunner(), 'fx-balances', str(book), '--verify-costs').output
        assert '1 disposal(s) pending their cost basis: 80.00 USD.' in costs, costs

    def test_a_side_left_short_of_what_is_pending_is_reported_once(self, tmp_path):
        """150.00 USD sold pending, then the payment deleted with the bank's cost basis.

        The dollars held are left the invoice's 100.00 against the 150.00
        pending. `--verify-costs` says so once, for the side, and the balance
        sheet still takes the sale off.
        """
        book = _book(tmp_path)
        assert 'Errors:       0' in _import(
            book, _sale(tmp_path, '$pending$', amount='150.00', cad='205.50')).output
        payment = _payment_guid(book, tmp_path)
        assert _run(CliRunner(), 'delete-transactions', str(book),
                    '--by-guid', payment).exit_code == 0

        costs = _run(CliRunner(), 'fx-balances', str(book), '--verify-costs')

        reported = ('the disposals pending their cost basis of USD the book held dispose '
                    'of 150.00 USD, and the cost bases of USD the book held have 100.00 '
                    'USD left')
        assert costs.output.count(reported) == 1, costs.output
        assert '1 disposal(s) pending their cost basis: 150.00 USD.' in costs.output, \
            costs.output

    def test_the_user_clears_the_pick_and_the_sale_opens_a_liability_cost_basis(self, tmp_path):
        book, _said = self._deleted(tmp_path)

        done = _run(CliRunner(), 'import', '--strategy', 'update', str(book),
                    _sale(tmp_path, '$None$'))

        assert 'Errors:       0' in done.output, done.output
        listed = _listing(book)
        assert 'pending their cost basis' not in listed, listed
        assert re.search(INVOICE + r'1\.4 CAD/USD\s+100\.00 USD\s+100\.00 USD\s+asset',
                         listed), listed
        assert re.search(r'2026-03-01\s+[0-9a-f]{32}\s+Assets:Bank:USD\s+1\.375 CAD/USD\s+'
                         r'80\.00 USD\s+80\.00 USD\s+liability', listed), listed
        assert 'Total USD cost basis balance: 100.00 USD held, 80.00 USD owed' in listed, listed


class TestTheInvoiceUnpostedAndPostedAgain:
    """INV-USD-OVER unposted, and then posted again by importing it again.

    The sale of 80.00 USD drew on the invoice's cost basis. Unposting destroys
    the invoice's posting, so the sale is made pending. The user posts the
    invoice again by importing the same file, which links the payment to it
    again, and then states the invoice's new cost basis on the sale.
    """

    def _unposted_and_posted_again(self, tmp_path):
        book = _book(tmp_path)
        invoice = _guid(book, INVOICE)
        assert 'Errors:       0' in _import(book, _sale(tmp_path, f'"{invoice}"')).output
        unposted = _run(CliRunner(), 'unpost-invoices', str(book), 'INV-USD-OVER')
        assert unposted.exit_code == 0, unposted.output
        assert "2026-03-01 'Sell 80.00 USD' (80.00 USD)" in unposted.output, unposted.output
        again = _run(CliRunner(), 'import', str(book), OVERPAID,
                     '--include-business-objects', '--fx-rates', RATES)
        assert again.exit_code == 0 and 'Errors:       0' in again.output, again.output
        return book

    def test_the_user_states_the_invoice_s_new_cost_basis_on_the_sale(self, tmp_path):
        book = self._unposted_and_posted_again(tmp_path)
        costs = _run(CliRunner(), 'fx-balances', str(book), '--verify-costs').output
        found = re.search(INVOICE, costs)
        assert found, costs

        done = _run(CliRunner(), 'import', '--strategy', 'update', str(book),
                    _sale(tmp_path, f'"{found.group(1)}"'))

        assert 'Errors:       0' in done.output, done.output
        listed = _listing(book)
        assert 'pending their cost basis' not in listed, listed
        assert re.search(INVOICE + r'1\.4 CAD/USD\s+100\.00 USD\s+20\.00 USD\s+asset',
                         listed), listed
        assert re.search(BANK + r'1\.37 CAD/USD\s+100\.00 USD\s+100\.00 USD\s+asset',
                         listed), listed
        assert re.search(CREDIT + r'1\.37 CAD/USD\s+100\.00 USD\s+100\.00 USD\s+liability',
                         listed), listed
