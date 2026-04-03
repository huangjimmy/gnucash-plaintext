"""
Unit tests for BeancountConverter.

Pure Python — no GnuCash session required.
Tests all three conversion methods: convert_account_name,
convert_commodity_symbol, and convert_metadata_key.
"""

import pytest

# ---------------------------------------------------------------------------
# convert_account_name
# ---------------------------------------------------------------------------

class TestConvertAccountName:

    def test_already_has_assets_prefix(self):
        from services.beancount_converter import BeancountConverter
        result = BeancountConverter.convert_account_name('Assets:Bank:Checking', 'Bank')
        assert result == 'Assets:Bank:Checking'

    def test_already_has_expenses_prefix(self):
        from services.beancount_converter import BeancountConverter
        result = BeancountConverter.convert_account_name('Expenses:Groceries', 'Expense')
        assert result == 'Expenses:Groceries'

    def test_already_has_income_prefix(self):
        from services.beancount_converter import BeancountConverter
        result = BeancountConverter.convert_account_name('Income:Salary', 'Income')
        assert result == 'Income:Salary'

    def test_already_has_liabilities_prefix(self):
        from services.beancount_converter import BeancountConverter
        result = BeancountConverter.convert_account_name('Liabilities:CreditCard', 'Credit Card')
        assert result == 'Liabilities:CreditCard'

    def test_already_has_equity_prefix(self):
        from services.beancount_converter import BeancountConverter
        result = BeancountConverter.convert_account_name('Equity:OpeningBalance', 'Equity')
        assert result == 'Equity:OpeningBalance'

    def test_credit_card_type_gets_liabilities_prefix(self):
        from services.beancount_converter import BeancountConverter
        result = BeancountConverter.convert_account_name('Visa', 'Credit Card')
        assert result.startswith('Liabilities:')

    def test_bank_type_gets_assets_prefix(self):
        from services.beancount_converter import BeancountConverter
        result = BeancountConverter.convert_account_name('Checking', 'Bank')
        assert result.startswith('Assets:')

    def test_cash_type_gets_assets_prefix(self):
        from services.beancount_converter import BeancountConverter
        result = BeancountConverter.convert_account_name('Wallet', 'Cash')
        assert result.startswith('Assets:')

    def test_stock_type_gets_assets_prefix(self):
        from services.beancount_converter import BeancountConverter
        result = BeancountConverter.convert_account_name('MSFT', 'Stock')
        assert result.startswith('Assets:')

    def test_mutual_fund_type_gets_assets_prefix(self):
        from services.beancount_converter import BeancountConverter
        result = BeancountConverter.convert_account_name('BalancedFund', 'Mutual Fund')
        assert result.startswith('Assets:')

    def test_expense_type_gets_expenses_prefix(self):
        from services.beancount_converter import BeancountConverter
        result = BeancountConverter.convert_account_name('Dining', 'Expense')
        assert result.startswith('Expenses:')

    def test_income_type_gets_income_prefix(self):
        from services.beancount_converter import BeancountConverter
        result = BeancountConverter.convert_account_name('Salary', 'Income')
        assert result.startswith('Income:')

    def test_equity_type_gets_equity_prefix(self):
        from services.beancount_converter import BeancountConverter
        result = BeancountConverter.convert_account_name('OpeningBalance', 'Equity')
        assert result.startswith('Equity:')

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "Bug: 'Liability' type falls through determine_prefix() because "
            "'Liabilities'.startswith('Liability') is False — 'i' vs 'y' at char 8. "
            "Currently produces 'None:Loan'. Remove this marker when fixed."
        ),
    )
    def test_liability_type_gets_liabilities_prefix(self):
        from services.beancount_converter import BeancountConverter
        result = BeancountConverter.convert_account_name('Loan', 'Liability')
        assert result.startswith('Liabilities:')

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "Bug: determine_prefix() checks 'account_name == A/Payable' but the "
            "special-char translation runs first, replacing '/' with '-', so the "
            "check always sees 'A-Payable' and never matches. "
            "Currently produces 'Assets:A-Payable'. Remove this marker when fixed."
        ),
    )
    def test_a_payable_account_name_gets_liabilities_prefix(self):
        """'A/Payable' as the account name should trigger Liabilities regardless of type."""
        from services.beancount_converter import BeancountConverter
        result = BeancountConverter.convert_account_name('A/Payable', 'Asset')
        assert result.startswith('Liabilities:')

    def test_slash_replaced_with_dash(self):
        from services.beancount_converter import BeancountConverter
        result = BeancountConverter.convert_account_name('Expenses:Food/Drink', 'Expense')
        assert '/' not in result
        assert '-' in result

    def test_space_replaced_with_dash(self):
        from services.beancount_converter import BeancountConverter
        result = BeancountConverter.convert_account_name('Cash in Wallet', 'Cash')
        assert ' ' not in result

    def test_each_component_capitalized(self):
        from services.beancount_converter import BeancountConverter
        result = BeancountConverter.convert_account_name('expenses:dining:restaurants', 'Expense')
        parts = result.split(':')
        assert all(p[0].isupper() for p in parts if p)

    def test_unrecognized_type_produces_none_prefix(self):
        """Known quirk: unrecognized account_type produces literal 'None:...' prefix.

        This test documents the current (intentional-for-parity) behavior.
        If this bug is ever fixed, this test should be updated.
        """
        from services.beancount_converter import BeancountConverter
        result = BeancountConverter.convert_account_name('SomeName', 'UnknownType')
        # Current behavior: prefix = None → "None:SomeName"
        assert result.startswith('None:')

    def test_hierarchical_name_preserved(self):
        from services.beancount_converter import BeancountConverter
        result = BeancountConverter.convert_account_name('Expenses:Travel:Flight', 'Expense')
        assert result == 'Expenses:Travel:Flight'

    def test_single_component_no_colon(self):
        from services.beancount_converter import BeancountConverter
        result = BeancountConverter.convert_account_name('Salary', 'Income')
        assert ':' in result  # prefix is added


# ---------------------------------------------------------------------------
# convert_commodity_symbol
# ---------------------------------------------------------------------------

class TestConvertCommoditySymbol:

    def test_none_returns_none(self):
        from services.beancount_converter import BeancountConverter
        assert BeancountConverter.convert_commodity_symbol(None) is None

    def test_lowercase_converted_to_uppercase(self):
        from services.beancount_converter import BeancountConverter
        assert BeancountConverter.convert_commodity_symbol('cad') == 'CAD'

    def test_mixed_case_converted_to_uppercase(self):
        from services.beancount_converter import BeancountConverter
        assert BeancountConverter.convert_commodity_symbol('Usd') == 'USD'

    def test_already_uppercase_unchanged(self):
        from services.beancount_converter import BeancountConverter
        assert BeancountConverter.convert_commodity_symbol('HKD') == 'HKD'

    def test_space_converted_to_underscore(self):
        from services.beancount_converter import BeancountConverter
        result = BeancountConverter.convert_commodity_symbol('Membership Rewards')
        assert ' ' not in result
        assert '_' in result

    def test_dot_preserved(self):
        from services.beancount_converter import BeancountConverter
        result = BeancountConverter.convert_commodity_symbol('template.template')
        assert '.' in result
        assert result == 'TEMPLATE.TEMPLATE'

    def test_dash_preserved(self):
        from services.beancount_converter import BeancountConverter
        result = BeancountConverter.convert_commodity_symbol('PC-Points')
        assert '-' in result
        assert result == 'PC-POINTS'

    def test_underscore_preserved(self):
        from services.beancount_converter import BeancountConverter
        result = BeancountConverter.convert_commodity_symbol('my_fund')
        assert '_' in result

    def test_other_punctuation_removed(self):
        from services.beancount_converter import BeancountConverter
        result = BeancountConverter.convert_commodity_symbol('A$B')
        assert '$' not in result

    def test_example_from_docstring_reward_points(self):
        from services.beancount_converter import BeancountConverter
        assert BeancountConverter.convert_commodity_symbol('template.reward-points') == 'TEMPLATE.REWARD-POINTS'

    def test_example_from_docstring_membership(self):
        from services.beancount_converter import BeancountConverter
        assert BeancountConverter.convert_commodity_symbol('Membership Rewards.Point') == 'MEMBERSHIP_REWARDS.POINT'


# ---------------------------------------------------------------------------
# convert_metadata_key
# ---------------------------------------------------------------------------

class TestConvertMetadataKey:

    def test_none_returns_none(self):
        from services.beancount_converter import BeancountConverter
        assert BeancountConverter.convert_metadata_key(None) is None

    def test_dot_replaced_with_dash(self):
        from services.beancount_converter import BeancountConverter
        result = BeancountConverter.convert_metadata_key('commodity.mnemonic')
        assert result == 'commodity-mnemonic'

    def test_multiple_dots_all_replaced(self):
        from services.beancount_converter import BeancountConverter
        result = BeancountConverter.convert_metadata_key('a.b.c')
        assert result == 'a-b-c'

    def test_underscore_prefix_gets_gnucash_prepended(self):
        from services.beancount_converter import BeancountConverter
        result = BeancountConverter.convert_metadata_key('_private_key')
        assert result == 'gnucash_private_key'

    def test_no_underscore_prefix_unchanged(self):
        from services.beancount_converter import BeancountConverter
        result = BeancountConverter.convert_metadata_key('notes')
        assert result == 'notes'

    def test_normal_key_no_dots_no_underscore_unchanged(self):
        from services.beancount_converter import BeancountConverter
        result = BeancountConverter.convert_metadata_key('guid')
        assert result == 'guid'

    def test_dot_and_underscore_prefix_combined(self):
        # Intentional order: dots replaced first, then underscore-prefix check.
        # '_some.key' → '_some-key' (dot→dash) → 'gnucash_some-key' (prefix added).
        from services.beancount_converter import BeancountConverter
        result = BeancountConverter.convert_metadata_key('_some.key')
        assert result == 'gnucash_some-key'
