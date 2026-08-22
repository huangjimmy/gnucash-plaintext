"""A rebuild puts the invoice back on the transactions it already had.

Editing a posted invoice unposts it, and `gncInvoiceUnpost` destroys the
posting transaction while leaving every payment transaction where it is —
the money did move through the bank, whatever happens to the invoice.
Two things follow, and both are about *identity* rather than about figures,
so a test on balances is evidence for neither:

- **the posting comes back as itself.** An export is the whole book, so the
  posting transaction is in the ledger's transaction section under its own
  guid and is created before the invoices are read; `posted_txn_guid:`
  then names a transaction this book has, and the invoice is linked to it
  rather than posted afresh.
- **the payment comes back as itself.** A `payment:` block naming
  `txn_guid:` retargets the transaction the book already holds —
  `_retarget_counter_split_to_lot` edits it in place, keeping its
  description, its notes, its split memos and its guid — instead of
  applying a second payment for money that moved once.

Where either identity is not kept, nothing in the figures says so: the
balances are the same either way. What changes is that anything pointing at
those transactions — a bank feed's own record, a reconciliation, a
statement line, another ledger — now points at nothing.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner
from gnucash import Query, Transaction

from cli.main import cli
from infrastructure.gnucash.utils import get_account_full_name
from repositories.gnucash_repository import GnuCashRepository, SessionMode

SOURCE = str(Path('tests/fixtures') / 'a_payment_named_with_account.txt')


def _bank_transactions(book):
    """`{guid: (description, [amounts])}` for every transaction touching the
    bank — the payments, which an unpost leaves behind."""
    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        query = Query()
        query.search_for('Trans')
        query.set_book(repo.book)
        found = {}
        for raw in query.run():
            transaction = Transaction(instance=raw)
            amounts = []
            touches_bank = False
            for split in transaction.GetSplitList():
                account = split.GetAccount()
                if account is None:
                    continue
                if get_account_full_name(account) == 'Assets:Bank':
                    touches_bank = True
                amounts.append(str(split.GetAmount()))
            if touches_bank:
                found[transaction.GetGUID().to_string()] = (
                    transaction.GetDescription(), sorted(amounts))
        query.destroy()
        return found
    finally:
        repo.close()


def _exported(book, tmp_path, name):
    out = tmp_path / name
    result = CliRunner().invoke(cli, [
        'export', str(book), str(out), '--include-business-objects'])
    assert result.exit_code == 0, result.output
    return out


@pytest.fixture
def a_paid_invoice(tmp_path):
    book = tmp_path / 'book.gnucash'
    made = CliRunner().invoke(cli, ['import', '--new', str(book), SOURCE,
                                    '--include-business-objects'])
    assert made.exit_code == 0, made.output
    return book


class TestEditingAPostedInvoice:
    """`unpost-invoices`, then import the edited ledger — the one way a
    posted invoice is changed, since it takes a `payment:` block and
    nothing else while it stands."""

    def _rebuilt(self, book, tmp_path):
        exported = _exported(book, tmp_path, 'ledger.txt')
        edited = tmp_path / 'edited.txt'
        text = exported.read_text()
        assert 'due: 2026-01-31' in text, text
        edited.write_text(text.replace('due: 2026-01-31', 'due: 2026-03-31'))

        runner = CliRunner()
        refused = runner.invoke(cli, [
            'import', str(book), str(edited), '--include-business-objects'])
        assert refused.exit_code != 0, refused.output
        assert 'unpost-invoices' in refused.output, refused.output

        unposted = runner.invoke(cli, ['unpost-invoices', str(book),
                                       'INV-SPELL'])
        assert unposted.exit_code == 0, unposted.output

        result = runner.invoke(cli, [
            'import', str(book), str(edited), '--include-business-objects'])
        assert result.exit_code == 0, result.output
        return result

    def test_the_payment_is_the_same_transaction_afterwards(
            self, a_paid_invoice, tmp_path):
        """Not a second one for money that moved once, and not a new guid
        for the one that did."""
        before = _bank_transactions(a_paid_invoice)
        assert len(before) == 1, before

        self._rebuilt(a_paid_invoice, tmp_path)

        assert _bank_transactions(a_paid_invoice) == before, \
            (before, _bank_transactions(a_paid_invoice))

    def test_and_the_invoice_still_reads_paid(self, a_paid_invoice,
                                               tmp_path):
        """The payment is back in the rebuilt invoice's lot, not merely
        left in the book: a settlement that stays loose leaves the invoice
        unpaid while the bank balance says the money arrived."""
        self._rebuilt(a_paid_invoice, tmp_path)

        text = _exported(a_paid_invoice, tmp_path, 'after.txt').read_text()
        block = text.split('invoice "INV-SPELL"')[1]
        assert 'payment: none' not in block, block
        assert 'due: 2026-03-31' in block, block
