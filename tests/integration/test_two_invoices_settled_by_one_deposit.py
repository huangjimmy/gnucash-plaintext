"""One invoice's unpost must not blind the duplicate guard to another's money.

A deposit can settle two invoices at once, a portion each. Rebuilding one of
them unposts it, and the unpost writes its mark on the split it loosened — in
that shared transaction.

The duplicate-payment guard skips a transaction its own rebuild orphaned,
because that money is the rebuild's to put back rather than money the book
independently had. Asked as "does this transaction carry a mark at all", the
first invoice's mark hides the whole deposit from the second's check — and the
second invoice, whose `txn_guid:` names nothing, is handed a fresh payment for
money that moved once.

The mark names the invoice it was settling (CLAUDE.md finding 10), for exactly
this: one transaction can carry orphans from two invoices, and which of them
was mine is answerable rather than guessed at.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner

from cli.main import cli

FIXTURES = Path('tests/fixtures')
ACCOUNTS = str(FIXTURES / 'payment_roundtrip_accounts.txt')
SETUP = str(FIXTURES / 'one_deposit_split_between_two_invoices.txt')

PAYMENT = (
    '\tpayment:\n'
    '\t\tdate: 2026-05-15\n'
    '\t\tamount: {amount}\n'
    '\t\tbank_account: "Assets:Bank"\n'
    '\t\ttxn_guid: "{txn}"\n'
    '\t\ttxn_split_guid: "{split}"\n'
    '\t\tmemo: "Portion for {who}"\n')


def _the_deposits_parts(book):
    """(transaction guid, {memo: receivable split guid}) for the deposit."""
    from gnucash import Query, Transaction

    from repositories.gnucash_repository import GnuCashRepository, SessionMode

    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        query = Query()
        query.search_for('Trans')
        query.set_book(repo.book)
        for raw in query.run():
            transaction = Transaction(instance=raw)
            if transaction.GetDescription() != 'Deposit covering Alpha and Beta':
                continue
            parts = {}
            for split in transaction.GetSplitList():
                name = split.GetAccount().get_full_name()
                if name != 'Assets.Accounts Receivable':
                    continue
                parts[(split.GetMemo() or '').strip()] = \
                    split.GetGUID().to_string()
            query.destroy()
            return transaction.GetGUID().to_string(), parts
        query.destroy()
    finally:
        repo.close()
    raise AssertionError('the deposit is not in the book')


def _transaction_count(book):
    from gnucash import Query

    from repositories.gnucash_repository import GnuCashRepository, SessionMode

    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        query = Query()
        query.search_for('Trans')
        query.set_book(repo.book)
        count = len(list(query.run()))
        query.destroy()
        return count
    finally:
        repo.close()


def _invoices(txn_a, split_a, txn_b, split_b) -> str:
    """Both invoices, each retargeting one portion of the deposit."""
    text = Path(SETUP).read_text()
    text = text.split('2026-05-15 * ')[0].rstrip() + '\n'
    blocks = []
    for name, amount, txn, split, who in (
            ('INV-SHARE-A', '100', txn_a, split_a, 'Alpha'),
            ('INV-SHARE-B', '120', txn_b, split_b, 'Beta')):
        head, _, tail = text.partition(f'invoice "{name}"')
        del head
        block = f'invoice "{name}"' + tail.split('\ninvoice "')[0].rstrip() + '\n'
        blocks.append(block + PAYMENT.format(
            amount=amount, txn=txn, split=split, who=who))
    return '\n'.join(blocks)


@pytest.fixture
def book_with_both_settled(tmp_path):
    """Both invoices settled out of the one deposit, each naming its portion."""
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    assert runner.invoke(cli, ['import', '--new', str(book),
                               ACCOUNTS]).exit_code == 0
    result = runner.invoke(cli, ['import', str(book), SETUP,
                                 '--include-business-objects'])
    assert result.exit_code == 0, result.output

    txn, parts = _the_deposits_parts(book)
    assert set(parts) == {'Portion for Alpha', 'Portion for Beta'}, parts

    settle = tmp_path / 'settle.txt'
    settle.write_text(_invoices(txn, parts['Portion for Alpha'],
                                 txn, parts['Portion for Beta']))
    result = runner.invoke(cli, ['import', str(book), str(settle),
                                 '--include-business-objects'])
    assert result.exit_code == 0, result.output
    return book


class TestBothGuidsMistyped:
    """Each block names nothing, and the book holds both movements already.

    Both invoices are rebuilt, so each has an orphan of its own in the shared
    deposit and each reattaches to it. Nothing is duplicated and nothing is
    refused — the guid was the only wrong thing in the file, and the mark says
    which portion belonged to which invoice without it.

    The refusal still belongs to a mistyped guid on an invoice that is
    otherwise unchanged: no rebuild, so no orphan, so nothing to reattach and
    the money in the book is somebody's already
    (`test_a_mistyped_txn_guid_does_not_pay_twice`).
    """

    WRONG_A = 'deadbeefdeadbeefdeadbeefdeadbeef'
    WRONG_B = 'feedfacefeedfacefeedfacefeedface'

    def _reimport(self, book, tmp_path):
        _txn, parts = _the_deposits_parts(book)
        ledger = tmp_path / 'mistyped.txt'
        ledger.write_text(_invoices(
            self.WRONG_A, parts['Portion for Alpha'],
            self.WRONG_B, parts['Portion for Beta']))
        return CliRunner().invoke(cli, [
            'import', str(book), str(ledger), '--include-business-objects'])

    def test_neither_portion_is_paid_a_second_time(self, book_with_both_settled,
                                                   tmp_path):
        """One deposit, two portions, and no new bank transaction for either.

        Asked as "does this transaction carry a mark at all", the first
        invoice's mark hid the whole deposit from the second invoice's
        check, and the second was handed a fresh payment for money that had
        moved once — measured, two extra bank transactions on a run that
        exited 0.
        """
        book = book_with_both_settled
        before = _transaction_count(book)

        result = self._reimport(book, tmp_path)

        assert result.exit_code == 0, result.output
        assert _transaction_count(book) == before

    def test_both_invoices_are_still_settled(self, book_with_both_settled,
                                              tmp_path):
        """Reattached, not merely left alone: each is paid out of its portion."""
        book = book_with_both_settled
        self._reimport(book, tmp_path)

        deposit, _parts = _the_deposits_parts(book)
        exported = tmp_path / 'out.txt'
        assert CliRunner().invoke(cli, [
            'export', str(book), str(exported),
            '--include-business-objects']).exit_code == 0
        text = exported.read_text()

        # Each invoice names that one deposit as what paid it.
        for name in ('INV-SHARE-A', 'INV-SHARE-B'):
            block = text.split(f'invoice "{name}"')[1].split('\ninvoice ')[0]
            assert f'txn_guid: "{deposit}"' in block, block
