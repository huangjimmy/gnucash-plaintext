"""What the fuzzy matcher does when a candidate is not good enough.

The matcher exists to keep a statement import from entering money the book
already holds. Both of its mistakes are expensive and only one is visible: a
missed duplicate shows up as a doubled balance somebody eventually notices,
while a false duplicate silently drops a real transaction on the floor. So the
bar for `LIKELY_DUP` is every account matching, the bar for `PARTIAL_MATCH` is
every asset/liability account matching — the side the money actually moved
through — and anything short of that is `NEW`.

`test_gnucash_fuzzy_matcher.py` holds the matches; this is the other side, plus
the two shapes that have no amount to match on at all.
"""

from __future__ import annotations

import os
import tempfile
from datetime import date
from decimal import Decimal

import pytest

from infrastructure.pdf.standard_tx import Split, StandardTransaction
from repositories.gnucash_repository import GnuCashRepository
from services.gnucash_fuzzy_matcher import GnuCashFuzzyMatcher, MatchStatus


@pytest.fixture
def book():
    """An HKD book holding one ordinary charge, one zero-amount transaction,
    and one charge carrying a `doc_link` from a previous import."""
    import gnucash
    from gnucash import Account, GncNumeric, Session, Transaction
    from gnucash import Split as GncSplit

    from infrastructure.gnucash.kvp import set_custom_metadata

    fd, path = tempfile.mkstemp(suffix='.gnucash')
    os.close(fd)
    os.unlink(path)
    try:
        from gnucash import SessionOpenMode
        session = Session(f'xml://{path}', SessionOpenMode.SESSION_NEW_STORE)
    except ImportError:
        session = Session(f'xml://{path}', is_new=True)

    gbook = session.book
    root = gbook.get_root_account()
    hkd = gbook.get_table().lookup('CURRENCY', 'HKD')

    def acct(name, kind, parent):
        a = Account(gbook)
        a.SetName(name)
        a.SetType(kind)
        a.SetCommodity(hkd)
        parent.append_child(a)
        return a

    assets = acct('Assets', gnucash.ACCT_TYPE_ASSET, root)
    bank = acct('BOC HKD Saving', gnucash.ACCT_TYPE_BANK, assets)
    expenses = acct('Expenses', gnucash.ACCT_TYPE_EXPENSE, root)
    dining = acct('Dining', gnucash.ACCT_TYPE_EXPENSE, expenses)
    acct('Groceries', gnucash.ACCT_TYPE_EXPENSE, expenses)
    liabilities = acct('Liabilities', gnucash.ACCT_TYPE_LIABILITY, root)
    boci = acct('BOCI-0012', gnucash.ACCT_TYPE_CREDIT, liabilities)

    def add_tx(d, splits, description=''):
        tx = Transaction(gbook)
        tx.BeginEdit()
        tx.SetCurrency(hkd)
        # day, month, year — the accessor every supported binding has.
        # `GncDateTime` is absent on GnuCash 5.10 among others.
        tx.SetDate(d.day, d.month, d.year)
        if description:
            tx.SetDescription(description)
        for account, num, denom in splits:
            sp = GncSplit(gbook)
            sp.SetParent(tx)
            sp.SetAccount(account)
            sp.SetValue(GncNumeric(num, denom))
            sp.SetAmount(GncNumeric(num, denom))
        tx.CommitEdit()
        return tx

    add_tx(date(2026, 4, 15), [(boci, 24710, 100), (dining, -24710, 100)])
    # Nothing moved. A fee waived, or a correction that cancelled itself — the
    # book keeps them, and they have no amount for the index to key on.
    add_tx(date(2026, 4, 16), [(bank, 0, 100), (dining, 0, 100)], 'Fee waived')
    linked = add_tx(date(2026, 4, 17), [(boci, 5000, 100), (dining, -5000, 100)])
    linked.BeginEdit()
    set_custom_metadata(linked, {'doc_link': 'file:///statements/boci-2026-04.pdf'})
    linked.CommitEdit()

    session.save()
    session.end()

    yield path, {
        'bank': 'Assets:BOC HKD Saving',
        'dining': 'Expenses:Dining',
        'groceries': 'Expenses:Groceries',
        'boci': 'Liabilities:BOCI-0012',
    }

    for leftover in (path, path + '.LCK'):
        if os.path.exists(leftover):
            os.unlink(leftover)


def _matcher(path):
    return GnuCashFuzzyMatcher(GnuCashRepository(path))


def _tx(d, acct1, acct2, amount='247.10', desc='AUTOPAY', pdfs=('boci.pdf',)):
    return StandardTransaction(
        post_date=d, description=desc, currency='HKD',
        splits=[Split(acct1, Decimal(amount)), Split(acct2, Decimal(f'-{amount}'))],
        source_pdfs=list(pdfs))


class TestTheMoneyCameThroughADifferentAccount:
    """Same day, same amount, and not the same transaction."""

    def test_it_is_new_rather_than_a_duplicate(self, book):
        """A 247.10 on the bank on the day of a 247.10 on the credit card is
        two payments, not one seen twice — and calling it a duplicate would
        drop it."""
        path, accts = book

        result = _matcher(path).match(
            _tx(date(2026, 4, 15), accts['bank'], accts['groceries']))

        assert result.status == MatchStatus.NEW, result.status

    def test_it_offers_nothing_to_merge(self, book):
        """NEW means there is nothing to merge into, and saying otherwise
        would hand a caller a transaction to write over."""
        path, accts = book

        result = _matcher(path).match(
            _tx(date(2026, 4, 15), accts['bank'], accts['groceries']))

        assert result.existing is None, result.existing
        assert result.merged_tx is None, result.merged_tx


class TestATransactionWithNoAmount:
    def test_one_arriving_is_new(self, book):
        """Nothing to key on, so nothing can be claimed about it."""
        path, accts = book

        result = _matcher(path).match(
            _tx(date(2026, 4, 16), accts['bank'], accts['dining'], amount='0.00'))

        assert result.status == MatchStatus.NEW, result.status

    def test_one_already_in_the_book_matches_nothing(self, book):
        """The zero-amount transaction the book holds is not indexed, so it
        cannot be handed back as the match for anything."""
        path, accts = book

        result = _matcher(path).match(
            _tx(date(2026, 4, 16), accts['bank'], accts['dining'], amount='0.00'))

        assert result.existing is None, result.existing


class TestTheDocumentLinkOnAMerge:
    def test_the_books_own_link_is_kept_when_the_import_has_none(self, book):
        """A statement re-read without its PDF to hand must not blank the link
        an earlier import recorded — that link is how the entry is traced back
        to the document it came from."""
        path, accts = book

        result = _matcher(path).match(_tx(
            date(2026, 4, 17), accts['boci'], accts['groceries'],
            amount='50.00', pdfs=()))

        assert result.status == MatchStatus.PARTIAL_MATCH, result.status
        assert result.merged_tx.source_pdfs == ['boci-2026-04.pdf'], \
            result.merged_tx.source_pdfs

    def test_a_second_document_is_carried_across_too(self, book):
        """An entry can be evidenced by two — a statement and a receipt — and
        keeping only the first loses the one a reader went looking for."""
        path, accts = book

        result = _matcher(path).match(_tx(
            date(2026, 4, 17), accts['boci'], accts['groceries'],
            amount='50.00', pdfs=('statement.pdf', 'receipt.pdf')))

        assert result.merged_tx.source_pdfs == ['statement.pdf', 'receipt.pdf'], \
            result.merged_tx.source_pdfs
