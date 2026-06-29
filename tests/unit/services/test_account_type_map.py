"""Q-033: the importer must map the account-type strings users and the docs
actually write — including the natural ``Receivable`` / ``Payable`` forms — to
the right GnuCash account types. If it doesn't, the account imports with no
(INVALID) type and silently drops off the balance sheet.
"""
from gnucash.gnucash_core_c import (
    ACCT_TYPE_ASSET,
    ACCT_TYPE_EXPENSE,
    ACCT_TYPE_PAYABLE,
    ACCT_TYPE_RECEIVABLE,
)

from services.gnucash_importer import ACCT_TYPE_MAP


def test_natural_receivable_payable_forms_map_to_business_types():
    # The bare natural forms a user types (the reported bug).
    assert ACCT_TYPE_MAP["Receivable"] == ACCT_TYPE_RECEIVABLE
    assert ACCT_TYPE_MAP["Payable"] == ACCT_TYPE_PAYABLE
    # The longer GnuCash forms still work.
    assert ACCT_TYPE_MAP["Accounts Receivable"] == ACCT_TYPE_RECEIVABLE
    assert ACCT_TYPE_MAP["A/Receivable"] == ACCT_TYPE_RECEIVABLE
    assert ACCT_TYPE_MAP["Accounts Payable"] == ACCT_TYPE_PAYABLE
    assert ACCT_TYPE_MAP["A/Payable"] == ACCT_TYPE_PAYABLE


def test_readme_wording_aliases_map_correctly():
    # Spellings the README used; the importer must accept them too.
    assert ACCT_TYPE_MAP["Other Assets"] == ACCT_TYPE_ASSET
    assert ACCT_TYPE_MAP["Expenses"] == ACCT_TYPE_EXPENSE
