"""Q-032 (reopened): every GnuCash *posting* account type must be classified by
the balance sheet into exactly one section. The original bug was a type silently
falling through (matched neither ASSET nor LIABILITY) and being dropped, so the
sheet didn't balance.

This test enumerates every ACCT_TYPE_* constant the running gnucash binding
exposes — including the commodity types (Stock, Mutual Fund), the business types
(A/Receivable, A/Payable), Trading, and the deprecated codes still found in
long-lived books (Checking, Savings, MoneyMrkt, CreditLine, legacy Currency) —
and asserts each lands in exactly one bucket. If a future GnuCash adds a new
posting type, this fails loudly instead of silently dropping balances.
"""

import gnucash.gnucash_core_c as gc
from gnucash.gnucash_core_c import (
    ACCT_TYPE_BANK,
    ACCT_TYPE_CASH,
    ACCT_TYPE_CREDIT,
    ACCT_TYPE_EQUITY,
    ACCT_TYPE_EXPENSE,
    ACCT_TYPE_INCOME,
    ACCT_TYPE_MUTUAL,
    ACCT_TYPE_PAYABLE,
    ACCT_TYPE_RECEIVABLE,
    ACCT_TYPE_STOCK,
)

from services.balance_sheet import _ASSET_TYPES, _LIABILITY_TYPES

# Structural / non-posting markers — accounts never carry these in a real book.
_NON_POSTING_NAMES = {
    'ACCT_TYPE_INVALID', 'ACCT_TYPE_NONE', 'ACCT_TYPE_ROOT', 'ACCT_TYPE_LAST',
}

_EQUITY_TYPES = frozenset({ACCT_TYPE_EQUITY})
_EARNINGS_TYPES = frozenset({ACCT_TYPE_INCOME, ACCT_TYPE_EXPENSE})


def _all_posting_types():
    """Every ACCT_TYPE_* posting constant exposed by this gnucash build, as a
    {name: value} map (structural markers excluded)."""
    out = {}
    for name in dir(gc):
        if not name.startswith('ACCT_TYPE_') or name in _NON_POSTING_NAMES:
            continue
        value = getattr(gc, name)
        if isinstance(value, int):
            out[name] = value
    return out


def test_every_posting_type_is_classified_exactly_once():
    buckets = (_ASSET_TYPES, _LIABILITY_TYPES, _EQUITY_TYPES, _EARNINGS_TYPES)
    for name, value in _all_posting_types().items():
        hits = [value in bucket for bucket in buckets]
        assert sum(hits) == 1, (
            f"{name} ({value}) must be classified into exactly one balance-sheet "
            f"bucket, was in {sum(hits)} — a balance sheet would drop or "
            f"double-count it."
        )


def test_asset_family_types_are_assets():
    # The "more asset-like types" beyond bare ASSET that the dropped-type bug hit.
    for atype in (ACCT_TYPE_BANK, ACCT_TYPE_CASH, ACCT_TYPE_STOCK,
                  ACCT_TYPE_MUTUAL, ACCT_TYPE_RECEIVABLE):
        assert atype in _ASSET_TYPES


def test_liability_family_types_are_liabilities():
    # Credit Card and A/Payable are liabilities, not "other" / dropped.
    for ltype in (ACCT_TYPE_CREDIT, ACCT_TYPE_PAYABLE):
        assert ltype in _LIABILITY_TYPES


def test_receivable_and_payable_do_not_collide():
    # A/Receivable is an asset and A/Payable is a liability — never swapped.
    assert ACCT_TYPE_RECEIVABLE in _ASSET_TYPES
    assert ACCT_TYPE_RECEIVABLE not in _LIABILITY_TYPES
    assert ACCT_TYPE_PAYABLE in _LIABILITY_TYPES
    assert ACCT_TYPE_PAYABLE not in _ASSET_TYPES


def test_legacy_types_are_covered_when_present():
    # Deprecated codes from old books, looked up defensively. Whichever this
    # binding exposes must still be classified (asset-side or liability-side).
    legacy_assets = ('ACCT_TYPE_CHECKING', 'ACCT_TYPE_SAVINGS',
                     'ACCT_TYPE_MONEYMRKT', 'ACCT_TYPE_CURRENCY')
    for name in legacy_assets:
        if hasattr(gc, name):
            assert getattr(gc, name) in _ASSET_TYPES, name
    if hasattr(gc, 'ACCT_TYPE_CREDITLINE'):
        assert gc.ACCT_TYPE_CREDITLINE in _LIABILITY_TYPES
