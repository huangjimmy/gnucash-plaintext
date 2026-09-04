"""The retarget block README shows is a block this tool accepts.

Refusing a `payment:` that spends a foreign account's cost basis balance, the run
names the way out: *"Write the settlement as an ordinary transaction with
`cost_basis_split_guid:` on the bank line and attach it with `txn_guid:` /
`txn_split_guid:`"* — and `docs/multi-currency.md` adds "README's
foreign-currency section shows the shape".

So that snippet is not an illustration; it is the remedy a hard refusal sends
the reader to. It has to import.

Read out of README.md rather than copied here, because a copy is what lets the
two drift: the point is that the *documented* block works, not that some block
resembling it does.
"""

import re
from pathlib import Path

import pytest
from click.testing import CliRunner

from cli.main import cli

README = Path('README.md')
FIXTURES = Path('tests/fixtures')


def _the_retarget_snippets():
    """The two fenced blocks under the remedy paragraph, in order.

    Anchored on the sentence the refusal paraphrases, so moving the section
    does not silently start testing some other block.
    """
    text = README.read_text()
    anchor = text.index('The way to spend a cost basis balance is the way every '
                        'other foreign disposal is written')
    after = text[anchor:]
    blocks = re.findall(r'```\n(.*?)```', after, re.DOTALL)
    assert len(blocks) >= 2, blocks
    return blocks[0], blocks[1]


@pytest.fixture
def book_and_basis(tmp_path):
    """A book holding USD bought at 1.35, and the guid of its cost basis."""
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    result = runner.invoke(cli, [
        'import', '--new', str(book),
        str(FIXTURES / 'usd_bought_at_the_readmes_rate.txt')])
    assert result.exit_code == 0, result.output

    listed = runner.invoke(cli, ['fx-balances', str(book)])
    assert listed.exit_code == 0, listed.output
    basis = next(line.split()[1] for line in listed.output.splitlines()
                 if 'Assets:Bank:USD' in line)
    return book, basis


def _split_accounts(book):
    """Every account a split in the book sits on."""
    from gnucash import Query, Transaction

    from repositories.gnucash_repository import GnuCashRepository, SessionMode

    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        query = Query()
        query.search_for('Trans')
        query.set_book(repo.book)
        names = sorted({
            split.GetAccount().get_full_name()
            for raw in query.run()
            for split in Transaction(instance=raw).GetSplitList()
            if split.GetAccount() is not None})
        query.destroy()
        return names
    finally:
        repo.close()


class TestTheDocumentedRemedy:
    def _import_the_transaction(self, book, basis, tmp_path):
        transaction, _payment = _the_retarget_snippets()
        ledger = tmp_path / 'spend.txt'
        # Only the cost basis guid, which no printed example can know in advance.
        # Every figure — the rate, the value, the accounts — is read from
        # README as written, against a book built to match it.
        ledger.write_text(
            transaction.replace('c4ccb16d7be34e15a112d903319c5267', basis))
        return CliRunner().invoke(cli, ['import', str(book), str(ledger)])

    def test_the_transaction_block_imports(self, book_and_basis, tmp_path):
        book, basis = book_and_basis

        result = self._import_the_transaction(book, basis, tmp_path)

        assert result.exit_code == 0, result.output

    def test_the_transaction_balances(self, book_and_basis, tmp_path):
        """Exit 0 is not enough: an entry whose values do not sum to zero is
        imported, and GnuCash scrubs in an `Imbalance` split at commit.

        The bank line states what its 100.00 USD is worth in the book's
        currency and the payable line has to as well, or it is valued at
        100.00 CAD — a rate of 1 against the 1.40 beside it — and the 40.00
        difference lands in `Imbalance-CAD`. A remedy block that does that is
        worse than no block: the run says nothing and the ledger is wrong.
        """
        book, basis = book_and_basis
        self._import_the_transaction(book, basis, tmp_path)

        assert not [name for name in _split_accounts(book)
                    if 'Imbalance' in name], _split_accounts(book)

    def test_the_payment_block_names_an_account(self, book_and_basis):
        """A `payment:` with neither `account:` nor `bank_account:` is refused
        outright — by name, before anything else about it is read."""
        _book, _basis = book_and_basis
        _transaction, payment = _the_retarget_snippets()

        assert 'account:' in payment, payment

    def test_the_three_guids_are_three_different_guids(self):
        """The cost basis, the transaction, and the transaction's payable split.

        The prose says so — "`txn_guid:` is the transaction above,
        `txn_split_guid:` its A/P split" — and the same literal stood for the
        basis split and the transaction, so a reader following it names a
        split where a transaction goes. It resolves to nothing, the block
        describes itself, and the duplicate guard then finds the transaction
        they have just written: the documented remedy for one hard refusal
        ends in another.
        """
        transaction, payment = _the_retarget_snippets()

        basis = re.search(r'cost_basis_split_guid: "([0-9a-f]+)"',
                          transaction).group(1)
        named = re.search(r'txn_guid: "([0-9a-f]+)"', payment).group(1)
        split = re.search(r'txn_split_guid: "([0-9a-f]+)"', payment).group(1)

        assert len({basis, named, split}) == 3, (basis, named, split)
