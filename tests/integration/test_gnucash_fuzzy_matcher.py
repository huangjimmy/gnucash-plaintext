"""Integration tests for GnuCashFuzzyMatcher against a real GnuCash book.

These tests run in Docker with real GnuCash Python bindings.
No mocking of GnuCash types — per project testing philosophy.
"""
import os
import tempfile
from datetime import date
from decimal import Decimal

import pytest

from infrastructure.pdf.standard_tx import Split, StandardTransaction
from repositories.gnucash_repository import GnuCashRepository, SessionMode
from services.gnucash_fuzzy_matcher import GnuCashFuzzyMatcher, MatchStatus

# ---------------------------------------------------------------------------
# Fixture: temp GnuCash book with HKD accounts and known transactions
# ---------------------------------------------------------------------------

@pytest.fixture
def hkd_book():
    """Temp GnuCash book with BOC HKD accounts for fuzzy matcher tests."""
    import gnucash
    from gnucash import Account, GncNumeric, Session, Transaction
    from gnucash import Split as GncSplit

    fd, path = tempfile.mkstemp(suffix=".gnucash")
    os.close(fd)
    os.unlink(path)

    try:
        from gnucash import SessionOpenMode
        session = Session(f"xml://{path}", SessionOpenMode.SESSION_NEW_STORE)
    except ImportError:
        session = Session(f"xml://{path}", is_new=True)

    book = session.book
    root = book.get_root_account()
    table = book.get_table()
    hkd = table.lookup("CURRENCY", "HKD")

    def acct(name, type_, parent):
        a = Account(book)
        a.SetName(name)
        a.SetType(type_)
        a.SetCommodity(hkd)
        parent.append_child(a)
        return a

    # Account hierarchy
    assets = acct("Assets", gnucash.ACCT_TYPE_ASSET, root)
    bank = acct("BOC HKD Saving", gnucash.ACCT_TYPE_BANK, assets)
    expenses = acct("Expenses", gnucash.ACCT_TYPE_EXPENSE, root)
    dining = acct("Dining", gnucash.ACCT_TYPE_EXPENSE, expenses)
    acct("Groceries", gnucash.ACCT_TYPE_EXPENSE, expenses)
    liabilities = acct("Liabilities", gnucash.ACCT_TYPE_LIABILITY, root)
    boci = acct("BOCI-0012", gnucash.ACCT_TYPE_CREDIT, liabilities)

    def add_tx(d: date, splits: list[tuple[Account, int, int]]) -> Transaction:
        tx = Transaction(book)
        tx.BeginEdit()
        tx.SetCurrency(hkd)
        tx.SetDatePostedSecs(
            int(gnucash.GncDateTime(
                gnucash.GncDate(d.year, d.month, d.day)
            ).GetTime64())
            if hasattr(gnucash, "GncDateTime")
            else int(d.strftime("%s"))
        )
        for acct_obj, num, denom in splits:
            sp = GncSplit(book)
            sp.SetParent(tx)
            sp.SetAccount(acct_obj)
            sp.SetValue(GncNumeric(num, denom))
            sp.SetAmount(GncNumeric(num, denom))
        tx.CommitEdit()
        return tx

    # Transaction 1: salary deposit 2026-03-29 (different date/amount — won't interfere)
    add_tx(date(2026, 3, 29), [(bank, 1811000, 100), (dining, -1811000, 100)])

    # Transaction 2: credit card charge 2026-04-15 boci → dining (user-categorized)
    # This is the realistic PARTIAL_MATCH scenario: user manually chose Dining
    add_tx(date(2026, 4, 15), [(boci, 24710, 100), (dining, -24710, 100)])

    session.save()
    session.end()

    yield path, {
        "bank": "Assets:BOC HKD Saving",
        "dining": "Expenses:Dining",
        "groceries": "Expenses:Groceries",
        "boci": "Liabilities:BOCI-0012",
    }

    if os.path.exists(path):
        os.unlink(path)
    lock = path + ".LCK"
    if os.path.exists(lock):
        os.unlink(lock)


def _matcher(path: str) -> GnuCashFuzzyMatcher:
    repo = GnuCashRepository(path)
    return GnuCashFuzzyMatcher(repo)


def _tx(
    d: date,
    acct1: str,
    acct2: str,
    amount: str = "247.10",
    desc: str = "AUTOPAY",
) -> StandardTransaction:
    return StandardTransaction(
        post_date=d,
        description=desc,
        currency="HKD",
        splits=[
            Split(acct1, Decimal(amount)),
            Split(acct2, Decimal(f"-{amount}")),
        ],
        source_pdfs=["boci.pdf"],
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestGnuCashFuzzyMatcher:
    def test_new_no_match(self, hkd_book):
        path, accts = hkd_book
        m = _matcher(path)
        tx = _tx(date(2026, 4, 20), accts["bank"], accts["dining"], amount="999.99")
        assert m.match(tx).status == MatchStatus.NEW

    def test_likely_dup_exact_date(self, hkd_book):
        path, accts = hkd_book
        m = _matcher(path)
        # Exact match: same accounts (boci→dining) as in GnuCash
        tx = _tx(date(2026, 4, 15), accts["boci"], accts["dining"], amount="247.10")
        result = m.match(tx)
        assert result.status == MatchStatus.LIKELY_DUP
        assert result.merged_tx is None

    def test_likely_dup_plus_one_day(self, hkd_book):
        path, accts = hkd_book
        m = _matcher(path)
        tx = _tx(date(2026, 4, 16), accts["boci"], accts["dining"], amount="247.10")
        result = m.match(tx)
        assert result.status == MatchStatus.LIKELY_DUP

    def test_likely_dup_minus_one_day(self, hkd_book):
        path, accts = hkd_book
        m = _matcher(path)
        tx = _tx(date(2026, 4, 14), accts["boci"], accts["dining"], amount="247.10")
        result = m.match(tx)
        assert result.status == MatchStatus.LIKELY_DUP

    def test_two_days_away_is_new(self, hkd_book):
        path, accts = hkd_book
        m = _matcher(path)
        tx = _tx(date(2026, 4, 13), accts["boci"], accts["dining"], amount="247.10")
        assert m.match(tx).status == MatchStatus.NEW

    def test_partial_match_expense_differs(self, hkd_book):
        path, accts = hkd_book
        m = _matcher(path)
        # GnuCash has boci→bank; we generate boci→groceries (same bank, diff expense)
        tx = _tx(date(2026, 4, 15), accts["boci"], accts["groceries"], amount="247.10")
        result = m.match(tx)
        assert result.status == MatchStatus.PARTIAL_MATCH
        assert result.existing is not None

    def test_partial_match_merged_guid(self, hkd_book):
        path, accts = hkd_book
        m = _matcher(path)
        tx = _tx(date(2026, 4, 15), accts["boci"], accts["groceries"], amount="247.10")
        result = m.match(tx)
        assert result.merged_tx is not None
        assert result.merged_tx.guid is not None
        assert len(result.merged_tx.guid) == 32  # GnuCash GUID is 32 hex chars

    def test_partial_match_gnucash_category(self, hkd_book):
        path, accts = hkd_book
        m = _matcher(path)
        tx = _tx(date(2026, 4, 15), accts["boci"], accts["groceries"], amount="247.10")
        result = m.match(tx)
        merged_accounts = {s.account for s in result.merged_tx.splits}
        # GnuCash has Dining; our candidate had Groceries — Dining should win
        assert any("Dining" in a for a in merged_accounts)
        assert not any("Groceries" in a for a in merged_accounts)

    def test_partial_match_generated_doc_link(self, hkd_book):
        path, accts = hkd_book
        m = _matcher(path)
        tx = _tx(date(2026, 4, 15), accts["boci"], accts["groceries"], amount="247.10")
        tx.source_pdfs = ["boci-0012-2026-04.pdf"]
        result = m.match(tx)
        assert result.merged_tx.source_pdfs[0] == "boci-0012-2026-04.pdf"
