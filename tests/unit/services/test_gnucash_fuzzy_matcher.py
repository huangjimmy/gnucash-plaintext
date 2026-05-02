"""Unit tests for GnuCashFuzzyMatcher pure-logic functions.

Tests cover amount normalization and tie-breaking using only StandardTransaction
and _IndexEntry (Python-native) — no GnuCash C-extension, no Docker.

MatchStatus classification tests (NEW/LIKELY_DUP/PARTIAL_MATCH) and merged_tx
content tests are in tests/integration/test_gnucash_fuzzy_matcher.py.
"""
from datetime import date
from decimal import Decimal

from infrastructure.pdf.standard_tx import Split, StandardTransaction
from services.gnucash_fuzzy_matcher import _IndexEntry, _pick_best


def _entry(
    d: date,
    accounts: list[str],
    amount: str = "247.10",
) -> _IndexEntry:
    return _IndexEntry(
        post_date=d,
        amount=Decimal(amount),
        account_names=frozenset(accounts),
        asset_liability_accounts=frozenset(a for a in accounts if "Assets" in a or "Liabilities" in a),
        guid="abc123",
        description="test",
        splits=[(accounts[0], Decimal(amount)), (accounts[1], Decimal(f"-{amount}"))],
    )


def _candidate(
    d: date = date(2026, 4, 15),
    acct1: str = "Assets:Bank",
    acct2: str = "Expenses:Dining",
) -> StandardTransaction:
    return StandardTransaction(
        post_date=d,
        description="AUTOPAY",
        currency="HKD",
        splits=[
            Split(acct1, Decimal("247.10")),
            Split(acct2, Decimal("-247.10")),
        ],
    )


class TestAmountNormalization:
    def test_two_split_sum(self):
        tx = _candidate()
        total = sum(s.amount for s in tx.splits if s.amount > 0)
        assert total == Decimal("247.10")

    def test_three_split_sum(self):
        tx = StandardTransaction(
            post_date=date(2026, 4, 15),
            description="Split",
            currency="HKD",
            splits=[
                Split("Assets:Bank", Decimal("300.00")),
                Split("Expenses:A", Decimal("-200.00")),
                Split("Expenses:B", Decimal("-100.00")),
            ],
        )
        total = sum(s.amount for s in tx.splits if s.amount > 0)
        assert total == Decimal("300.00")

    def test_symmetry_with_index_side(self):
        entry = _entry(date(2026, 4, 15), ["Assets:Bank", "Expenses:Dining"])
        candidate_sum = sum(s.amount for s in _candidate().splits if s.amount > 0)
        assert entry.amount == candidate_sum


class TestTieBreaking:
    def test_exact_date_beats_near_date(self):
        tx = _candidate(d=date(2026, 4, 15))
        near = _entry(date(2026, 4, 14), ["Assets:Bank", "Expenses:A"])
        exact = _entry(date(2026, 4, 15), ["Assets:Bank", "Expenses:A"])
        best = _pick_best([near, exact], tx, date(2026, 4, 15))
        assert best is exact

    def test_most_matching_accounts_wins(self):
        tx = _candidate(acct1="Assets:Bank", acct2="Expenses:Dining")
        fewer = _entry(date(2026, 4, 14), ["Assets:Other", "Expenses:X"])
        more = _entry(date(2026, 4, 14), ["Assets:Bank", "Expenses:X"])
        best = _pick_best([fewer, more], tx, date(2026, 4, 15))
        assert best is more

    def test_earliest_date_tiebreak(self):
        tx = _candidate(d=date(2026, 4, 15))
        later = _entry(date(2026, 4, 16), ["Assets:Bank", "Expenses:A"])
        earlier = _entry(date(2026, 4, 14), ["Assets:Bank", "Expenses:A"])
        best = _pick_best([later, earlier], tx, date(2026, 4, 15))
        assert best is earlier
