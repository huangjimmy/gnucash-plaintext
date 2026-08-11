"""Writing a basis's balance takes the pre-rename key off it.

`cost_basis_available` became `cost_basis_balance`, and every *read* accepts
either name so a book written by the shipped release keeps its balances. That
leaves one hazard: a split carrying both, where the two disagree and which one
answers depends on which code path asked.

The importer reads the metadata directly in a dozen places — carrying a basis
across an applied credit, dividing one, stripping a settlement's — and each is
a chance for the pair to be read the wrong way round. A split that never holds
both cannot be read two ways, so the write is where it is resolved: the moment
a balance is written under the current name, the old one goes.

That also migrates a book by using it. Any basis this tool touches comes out
carrying one key, and the ones it has not touched still read correctly.
"""

from fractions import Fraction

import pytest


def _split_with(metadata):
    """A stand-in split carrying `metadata`, backed by a real GnuCash book."""
    import os
    import tempfile

    import gnucash
    from gnucash import Account, GncNumeric, Session, Split, Transaction
    fd, path = tempfile.mkstemp(suffix='.gnucash')
    os.close(fd)
    os.unlink(path)
    try:
        from gnucash import SessionOpenMode
        session = Session(f'xml://{path}', SessionOpenMode.SESSION_NEW_STORE)
    except ImportError:
        session = Session(f'xml://{path}', is_new=True)

    book = session.book
    root = book.get_root_account()
    usd = book.get_table().lookup('CURRENCY', 'USD')

    account = Account(book)
    account.SetName('Bank')
    account.SetType(gnucash.ACCT_TYPE_BANK)
    account.SetCommodity(usd)
    root.append_child(account)

    transaction = Transaction(book)
    transaction.BeginEdit()
    transaction.SetCurrency(usd)
    transaction.SetDate(1, 1, 2026)
    split = Split(book)
    split.SetParent(transaction)
    split.SetAccount(account)
    split.SetValue(GncNumeric(10000, 100))
    split.SetAmount(GncNumeric(10000, 100))
    transaction.CommitEdit()

    from infrastructure.gnucash.kvp import set_custom_metadata
    transaction.BeginEdit()
    set_custom_metadata(split, metadata)
    transaction.CommitEdit()
    return split, session, path


class TestWritingABalance:
    def test_it_removes_the_pre_rename_key(self):
        from infrastructure.gnucash.kvp import get_custom_metadata
        from services.foreign_currency import write_cost_basis_balance

        split, session, path = _split_with({'cost_basis_available': '20.00'})
        try:
            write_cost_basis_balance(split, Fraction(15))

            held = get_custom_metadata(split)
            assert 'cost_basis_available' not in held, held
            assert held.get('cost_basis_balance'), held
        finally:
            session.end()
            import os
            if os.path.exists(path):
                os.unlink(path)

    def test_the_figure_written_is_the_one_asked_for(self):
        from services.foreign_currency import (
            cost_basis_balance_of,
            write_cost_basis_balance,
        )

        split, session, path = _split_with({'cost_basis_available': '20.00'})
        try:
            write_cost_basis_balance(split, Fraction(15))

            assert cost_basis_balance_of(split) == Fraction(15)
        finally:
            session.end()
            import os
            if os.path.exists(path):
                os.unlink(path)
