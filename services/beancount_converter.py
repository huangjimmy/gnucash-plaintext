"""
Beancount format converter service.

Converts GnuCash data to beancount-compatible format following the beancount
specification for account names, commodity symbols, and metadata keys.
"""

import string
from typing import Optional


class BeancountConverter:
    """
    Convert GnuCash data to beancount-compatible format.

    This service ensures that GnuCash account names, commodity symbols, and
    metadata keys are formatted according to beancount requirements.
    """

    # Valid top-level account names in beancount
    TOP_LEVEL_ACCOUNTS = ['Assets', 'Liabilities', 'Equity', 'Income', 'Expenses']

    @staticmethod
    def convert_account_name(account_name: str, account_type: str) -> str:
        """
        Convert GnuCash account name to beancount-compatible format.

        Rules:
        1. Ensure top-level account is one of: Assets, Liabilities, Equity, Income, Expenses
        2. Replace special characters (/, \\, -, spaces, tabs) with dashes
        3. Capitalize each component
        4. Remove or escape characters invalid in beancount

        Examples:
            "Expenses-CAN" → "Expenses:Expenses-CAN"
            "식료품 장보기" → "Expenses:식료품-장보기"
            "Cash in Wallet" → "Assets:Cash-in-Wallet"

        Args:
            account_name: GnuCash account name (may include hierarchy with :)
            account_type: GnuCash account type (e.g., "Cash", "Credit Card", "Expense")

        Returns:
            Beancount-compatible account name
        """
        top_level_accounts = BeancountConverter.TOP_LEVEL_ACCOUNTS

        # Check if account already has valid top-level prefix
        need_append_top_level_prefix = not any(account_name.startswith(f'{prefix}:') or account_name == prefix
            for prefix in top_level_accounts)

        def determine_prefix():
            """Determine correct top-level prefix based on account type"""
            # Note: Legacy code checks account_name == 'A/Payable' (not account_type)
            # This is a quirk but we match it for parity
            if account_type == 'Credit Card' or account_name == 'A/Payable':
                return 'Liabilities'
            if account_type in ['Stock', 'Cash', 'Mutual Fund', 'Bank', 'A/Receivable']:
                return 'Assets'
            # Check if account_type starts with one of the top-level names
            for a in top_level_accounts:
                if a.startswith(account_type):
                    return a
            return None

        # Replace special characters with dashes
        # Keep colons for hierarchy, replace everything else
        custom_punctuation = ''.join(c for c in string.punctuation if c != ':')
        translation_table = str.maketrans(dict.fromkeys(custom_punctuation + ' ', '-'))
        account_name = account_name.translate(translation_table)

        # Add top-level prefix if needed
        if need_append_top_level_prefix:
            prefix = determine_prefix()
            # Legacy code adds prefix even if None (becomes "None:...")
            # This is a quirk but we match it for parity
            account_name = f'{prefix}:{account_name}'

        # Capitalize each component (words separated by :)
        # Keep already capitalized words as-is
        components = []
        for word in account_name.split(':'):
            if word and not word[0].isupper():
                components.append(word.capitalize())
            else:
                components.append(word)

        return ':'.join(components)

    @staticmethod
    def convert_commodity_symbol(symbol: str) -> str:
        """
        Convert GnuCash commodity symbol to beancount-compatible format.

        Rules:
        1. Convert to uppercase
        2. Replace spaces with underscores
        3. Remove special characters except: . - _
        4. Keep alphanumeric characters

        Examples:
            "template.template" → "TEMPLATE.TEMPLATE"
            "template.reward-points" → "TEMPLATE.REWARD-POINTS"
            "PC-Points" → "PC-POINTS"
            "Membership Rewards.Point" → "MEMBERSHIP_REWARDS.POINT"

        Args:
            symbol: GnuCash commodity symbol

        Returns:
            Beancount-compatible commodity symbol
        """
        if symbol is None:
            return symbol

        # Replace spaces with underscores first
        symbol = symbol.replace(' ', '_')

        # Characters to keep (in addition to alphanumeric)
        exclude_chars = ".-_"

        # Remove all punctuation except the excluded ones
        custom_punctuation = ''.join(c for c in string.punctuation if c not in exclude_chars)
        compatible_symbol = symbol.upper().translate(str.maketrans("", "", custom_punctuation))

        return compatible_symbol

    @staticmethod
    def convert_metadata_key(key: str) -> Optional[str]:
        """
        Convert GnuCash metadata key to beancount-compatible format.

        Rules:
        1. Replace dots with dashes
        2. Prefix keys starting with underscore with 'gnucash'

        Examples:
            "commodity.mnemonic" → "commodity-mnemonic"
            "_private_key" → "gnucash_private_key"

        Args:
            key: Metadata key string

        Returns:
            Beancount-compatible metadata key
        """
        if key is None:
            return key

        # Replace dots with dashes
        key = key.replace('.', '-')

        # Prefix underscore-prefixed keys with 'gnucash'
        if key.startswith('_'):
            key = f'gnucash{key}'

        return key
