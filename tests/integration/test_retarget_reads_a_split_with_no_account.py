"""A split in a committed transaction always has an account.

Both paths that retarget a payment find "the side that is not the bank" by
naming each split's account and comparing it, inside an open edit on the
transaction. If a split could have no account, naming it would raise and leave
the transaction in that edit — so those loops would need a guard, and a guard
on a state that cannot arise is dead code in the middle of the money path.

Asked of the engine rather than reasoned about, because this is the sort of
thing the bindings answer differently from what the headers suggest.
"""

from click.testing import CliRunner

from cli.main import cli

ACCOUNTS = 'tests/fixtures/payment_roundtrip_accounts.txt'


def _find(account, name):
    if account.get_full_name() == name:
        return account
    for child in account.get_children():
        hit = _find(child, name)
        if hit is not None:
            return hit
    return None


def test_a_split_committed_without_an_account_is_given_one(tmp_path):
    """Built the only way one can be, and the engine will not keep it that way.

    A `Split` is given a parent and never an account, and the transaction is
    committed. GnuCash scrubs it on the way through, so by the time any reader
    can reach the split it has an account — the imbalance account, since the
    split holds nothing and the transaction has to balance.

    That is what lets the retarget loops name a split's account without asking
    whether it has one: a transaction they can reach has been committed, and a
    committed transaction has no accountless splits to offer.
    """
    from gnucash import Query, Split, Transaction

    from repositories.gnucash_repository import GnuCashRepository, SessionMode

    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    assert runner.invoke(cli, ['import', '--new', str(book), ACCOUNTS]).exit_code == 0

    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.NORMAL)
    try:
        bank = _find(repo.book.get_root_account(), 'Assets.Bank')
        transaction = Transaction(repo.book)
        transaction.BeginEdit()
        transaction.SetCurrency(bank.GetCommodity())
        transaction.SetDescription('A split with nowhere to be')
        placed = Split(repo.book)
        placed.SetParent(transaction)
        placed.SetAccount(bank)
        loose = Split(repo.book)
        loose.SetParent(transaction)
        transaction.CommitEdit()

        assert loose.GetAccount() is not None, (
            'the engine kept a split with no account, so every reader that '
            'names a split\'s account needs a guard against it')
        repo.save()
    finally:
        repo.close()

    # And the same holds for a book read back off disk, which is the only kind
    # the retarget paths are ever handed.
    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        query = Query()
        query.search_for('Trans')
        query.set_book(repo.book)
        accountless = 0
        for raw in query.run():
            for split in Transaction(instance=raw).GetSplitList():
                if split.GetAccount() is None:
                    accountless += 1
        query.destroy()
    finally:
        repo.close()

    assert accountless == 0, (
        f'a saved and reopened book holds {accountless} split(s) with no '
        f'account, so every reader that names a split\'s account needs a '
        f'guard against it')
