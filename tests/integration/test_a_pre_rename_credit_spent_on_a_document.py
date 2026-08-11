"""Spending a pre-rename credit on a document leaves it holding nothing.

A book written by the shipped release carries `cost_basis_available`. Reading
the balance goes through `cost_basis_metadata`, so the figure survives — but
*clearing* it is a separate act, and a settlement has to be cleared: the
currency has been spent on the document.

Cleared by the new name alone, a credit applied whole keeps the old key on the
split that spent it. Inert in the book, since a split in a document's lot is no
basis — but the key is not one the export knows to drop, and the export
promotes it to `cost_basis_balance:`. Rebuild that file and the settlement is a
basis with a stated, authoritative balance: the book offers currency it has
already spent, and `--verify-costs` cannot object, the figure being no larger
than what the split brought in.
"""

from click.testing import CliRunner

from cli.main import cli

RATES = 'tests/fixtures/fx_rates_usd_dated.yaml'

BIGGER_INVOICE = (
    'invoice "INV-USD-BIGGER"\n'
    '\tcustomer_id: "C-US"\n'
    '\tcurrency: USD\n'
    '\tdate_opened: 2026-03-01\n'
    '\tauto_apply_credit: true\n'
    '\tentry:\n'
    '\t\tdate: 2026-03-01\n'
    '\t\tdescription: "More consulting"\n'
    '\t\taction: "Hours"\n'
    '\t\taccount: "Income:Sales"\n'
    '\t\tquantity: 1\n'
    '\t\tprice: 250\n'
    '\t\ttaxable: false\n'
    '\t\ttax_included: false\n'
    '\tposted:\n'
    '\t\tdate: 2026-03-01\n'
    '\t\tdue: 2026-04-01\n'
    '\t\tar_account: "Assets:Accounts Receivable USD"\n'
    '\t\tmemo: "Invoice INV-USD-BIGGER"\n'
    '\t\taccumulate: true\n')


def _the_credit_carries_the_old_key(book):
    """Rewrite the 100.00 USD credit's balance under its pre-rename name.

    Returns the guid of the split it rewrote, which is the same split the
    engine hands the document when the credit is applied whole.
    """
    from gnucash import Query, Transaction

    from infrastructure.gnucash.kvp import get_custom_metadata, set_custom_metadata
    from repositories.gnucash_repository import GnuCashRepository, SessionMode

    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.NORMAL)
    try:
        query = Query()
        query.search_for('Trans')
        query.set_book(repo.book)
        touched = []
        for raw in query.run():
            transaction = Transaction(instance=raw)
            for split in transaction.GetSplitList():
                held = dict(get_custom_metadata(split))
                if 'cost_basis_balance' not in held:
                    continue
                if str(split.GetAmount()) != '-10000/100':
                    continue
                held['cost_basis_available'] = held.pop('cost_basis_balance')
                transaction.BeginEdit()
                set_custom_metadata(split, held)
                transaction.CommitEdit()
                touched.append(split.GetGUID().to_string())
        query.destroy()
        assert len(touched) == 1, f'expected one credit basis, touched {touched}'
        repo.save()
    finally:
        repo.close()
    return touched[0]


def _what_that_split_holds(book, guid):
    """The named split's custom metadata, read back off disk.

    Read from the book rather than from an export: the payment transaction
    carries two −100.00 USD splits on the same account — the first invoice's
    settlement and the credit — so nothing in the text tells them apart, and
    an assertion that picks by position asserts about the wrong one.
    """
    from gnucash import Query, Transaction

    from infrastructure.gnucash.kvp import get_custom_metadata
    from repositories.gnucash_repository import GnuCashRepository, SessionMode

    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        query = Query()
        query.search_for('Trans')
        query.set_book(repo.book)
        for raw in query.run():
            for split in Transaction(instance=raw).GetSplitList():
                if split.GetGUID().to_string() == guid:
                    return dict(get_custom_metadata(split))
        query.destroy()
    finally:
        repo.close()
    raise AssertionError(f'split {guid} is no longer in the book')


class TestWhatTheSettlementHolds:
    def test_the_old_key_is_cleared_with_the_new_one(self, tmp_path):
        """The whole credit went into the invoice, so it carries nothing."""
        runner = CliRunner()
        book = tmp_path / 'book.gnucash'
        result = runner.invoke(cli, [
            'import', '--new', str(book),
            'tests/fixtures/fx_invoice_usd_overpaid_into_usd_bank.txt',
            '--include-business-objects', '--fx-rates', RATES])
        assert result.exit_code == 0, result.output
        credit = _the_credit_carries_the_old_key(book)

        bigger = tmp_path / 'bigger.txt'
        bigger.write_text(BIGGER_INVOICE)
        result = runner.invoke(cli, ['import', str(book), str(bigger),
                                     '--include-business-objects',
                                     '--fx-rates', RATES])
        assert result.exit_code == 0, result.output

        held = _what_that_split_holds(book, credit)
        assert held.get('applied_from_credit') == 'true', held
        assert 'cost_basis_cost' not in held, held
        assert 'cost_basis_balance' not in held, held
        assert 'cost_basis_available' not in held, held

    def test_the_clear_survives_the_document_being_unposted(self, tmp_path):
        """Loose again, it still records no balance for what it spent.

        This is where a stale figure would start being read. In the document's
        lot the split is no basis, so nothing consults it and `fx-balances`
        does not list it — measured: after the unpost the listing shows only
        the first invoice's 100.00, whichever spelling the split carries. What
        changes is what the split says, and the split is what a later division
        or settlement of that credit reads.

        So the balance has to go when the currency is spent. Nothing later
        removes it, and by the time anything reads it the document it was
        spent on is gone from the split's story.
        """
        runner = CliRunner()
        book = tmp_path / 'book.gnucash'
        assert runner.invoke(cli, [
            'import', '--new', str(book),
            'tests/fixtures/fx_invoice_usd_overpaid_into_usd_bank.txt',
            '--include-business-objects', '--fx-rates', RATES]).exit_code == 0
        credit = _the_credit_carries_the_old_key(book)

        bigger = tmp_path / 'bigger.txt'
        bigger.write_text(BIGGER_INVOICE)
        assert runner.invoke(cli, ['import', str(book), str(bigger),
                                   '--include-business-objects',
                                   '--fx-rates', RATES]).exit_code == 0

        unposted = runner.invoke(cli, ['unpost-invoices', str(book),
                                       'INV-USD-BIGGER'])
        assert unposted.exit_code == 0, unposted.output

        held = _what_that_split_holds(book, credit)
        assert 'cost_basis_available' not in held, held
        assert 'cost_basis_balance' not in held, held
