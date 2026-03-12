"""
GnuCash utility functions

These utilities work with GnuCash Python binding objects (Account, Transaction, etc.)
Extracted from legacy utils.py and placed in new architecture.
"""

import copy
from decimal import Decimal
from fractions import Fraction
from typing import List, Optional, Union

from gnucash import Account, GncCommodity, GncNumeric


def get_account_full_name(account: Account) -> str:
    """
    Get full hierarchical name of account (e.g., "Assets:Bank:Checking").

    Args:
        account: GnuCash Account object

    Returns:
        Full account name with hierarchy separated by colons
    """
    parent = account.get_parent()
    name = account.GetName()

    if parent is not None and (not parent.is_root()):
        name = ":".join([get_account_full_name(parent), name])
    return name


def get_parent_accounts_and_self(account: Account) -> List[Account]:
    """
    Get list of all parent accounts plus the account itself.

    Args:
        account: GnuCash Account object

    Returns:
        List of accounts from root to this account (inclusive)
    """
    accounts = [account]
    parent = account.get_parent()
    while parent is not None and not parent.is_root():
        accounts.insert(0, parent)
        parent = parent.get_parent()

    return accounts


def get_all_sub_accounts(account: Account, names=None):
    """
    Iterate over all sub accounts of a given account.

    Args:
        account: GnuCash Account object
        names: Internal parameter for recursion

    Yields:
        Tuple of (child_account, full_name)
    """
    if names is None:
        names = []

    for child in account.get_children_sorted():
        child_names = names.copy()
        child_names.append(child.GetName())
        yield child, '::'.join(child_names)
        yield from get_all_sub_accounts(child, child_names)


def find_account(account: Account, name: str) -> Optional[Account]:
    """
    Find account by full path (e.g., 'Assets:Bank:Checking').

    Args:
        account: Root account to start search from
        name: Account path separated by colons

    Returns:
        Account object if found, None otherwise
    """
    if name == "" or name == "Root Account":
        return account

    names = name.split(":")

    def find_child(account: Account, name: str) -> Optional[Account]:
        for child in account.get_children_sorted():
            child_name = child.GetName()
            if child_name == name:
                return child
        return None

    acc = account
    for n in names:
        acc = find_child(acc, n)
        if acc is None:
            break

    return acc


def get_commodity_ticker(commodity: GncCommodity) -> str:
    """
    Get commodity ticker in format 'NAMESPACE.MNEMONIC' or just 'MNEMONIC' for currencies.

    Args:
        commodity: GnuCash Commodity object

    Returns:
        Ticker string (e.g., 'CAD', 'NASDAQ.AAPL')
    """
    mnemonic = commodity.get_mnemonic()
    namespace = commodity.get_namespace()
    if namespace == 'CURRENCY':
        return mnemonic
    return f'{namespace}.{mnemonic}'


def to_string_in_fraction_format(number: GncNumeric) -> str:
    """
    Convert a GncNumeric to a string in num/denom format.

    Args:
        number: GnuCash numeric value

    Returns:
        String representation (e.g., '100', '50/3', '1')
    """
    number = copy.copy(number)
    numerator = number.num()
    denominator = number.denom()

    if numerator == denominator:
        return '1'
    if denominator == 1 or numerator == 0:
        return f'{numerator}'
    return f'{numerator}/{denominator}'


def string_to_gnc_numeric(s: str, currency: GncCommodity) -> GncNumeric:
    """
    Convert string to GncNumeric using currency fraction.

    Args:
        s: String representation of number (e.g., '123.45', '50/3')
        currency: Currency commodity for fraction info

    Returns:
        GncNumeric object
    """
    if '/' in s:
        amount = GncNumeric(s)
    else:
        amount_numerator = int(Decimal(s.replace(',', '.')) * currency.get_fraction())
        amount_denominator = currency.get_fraction()
        amount = GncNumeric(amount_numerator, amount_denominator)
    return amount


def gnc_numeric_to_fraction_or_decimal(number: GncNumeric) -> Union[Fraction, Decimal]:
    """
    Convert GncNumeric to Python Fraction or Decimal.

    Args:
        number: GnuCash numeric value

    Returns:
        Fraction if denominator is not power of 10, otherwise Decimal
    """
    number = copy.copy(number)
    numerator = int(number.num())
    denominator = int(number.denom())
    denom_str = str(denominator)

    # Check if denominator is power of 10 (1, 10, 100, 1000, etc.)
    if denom_str[0] == '1' and all(c == '0' for c in denom_str[1:]):
        num_decimal = Decimal(numerator)
        denom_decimal = Decimal(denominator)
        return num_decimal / denom_decimal
    else:
        return Fraction(numerator, denominator)


def to_string_with_decimal_point_placed(number: GncNumeric) -> str:
    """
    Convert a GncNumeric to a string with decimal point placed if permissible.
    Otherwise returns its fractional representation.

    Args:
        number: GnuCash numeric value

    Returns:
        String representation with decimal point (e.g., '123.45') or fraction (e.g., '50/3')
    """
    number = copy.copy(number)
    if not number.to_decimal(None):
        return str(number)

    numerator = str(number.num())
    point_place = str(number.denom()).count('0')  # How many zeros in the denominator?

    if point_place == 0:
        return numerator
    elif len(numerator) > point_place:
        return numerator[:-point_place] + '.' + numerator[-point_place:]
    else:
        return '0.' + '0' * (point_place - len(numerator)) + numerator


def escape_string(s: str) -> str:
    """
    Escape special characters in string for plaintext format.

    Args:
        s: String to escape

    Returns:
        Escaped string
    """
    if s is None:
        return s

    translation_table = str.maketrans({
        '"': '\\"',
        '\\': '\\\\'
    })
    return s.translate(translation_table)


def encode_value_as_string(value) -> str:
    """
    Encode value as string for plaintext format with proper quoting.

    Args:
        value: Value to encode (None, bool, int, float, Fraction, or str)

    Returns:
        Encoded string representation
    """
    if value is None:
        return '#None'
    if isinstance(value, bool):
        return f'#{value}'
    if isinstance(value, (int, float)):
        return f'{value}'
    if isinstance(value, Fraction):
        return f'#{value.numerator}/{value.denominator}'
    if isinstance(value, str):
        return f'"{escape_string(value)}"'
    # Fallback for other types
    return f'"{escape_string(str(value))}"'


def unescape_string(s: str) -> str:
    """
    Unescape special characters in string.

    Args:
        s: Escaped string

    Returns:
        Unescaped string
    """
    if s is None:
        return s
    return s.replace('\\"', '"').replace('\\\\', '\\')


def decode_value_from_string(s: str):
    """
    Decode value from plaintext string representation.

    Handles:
    - None values (#None)
    - Integers (123)
    - Floats (123.45)
    - Booleans (True, False, #True, #False)
    - Quoted strings ("...")
    - Numbers with # prefix (#100)

    Args:
        s: String representation

    Returns:
        Decoded value (int, float, bool, str, or None)
    """
    import re

    if s is None or s == '#None':
        return None
    if s.isnumeric():
        return int(s)
    try:
        return float(s)
    except ValueError:
        pass
    if s == 'True':
        return True
    if s == 'False':
        return False
    if s == 'true':
        return True
    if s == 'false':
        return False
    if s.startswith('#'):
        if s == '#True':
            return True
        if s == '#False':
            return False
        fraction_pattern = r'#(\d+)\s*$'
        match = re.search(fraction_pattern, s)
        if match:
            return int(s[1:].strip())
        else:
            # if it is a float, just return the string itself
            return s
    elif s.startswith('"'):
        content = s[1:-1]
        return unescape_string(content)
    return s


def number_in_string_format_is_1(s: str) -> bool:
    """
    Check if a number string represents 1 (handles decimals like '1.0', '1.00').

    Args:
        s: String representation of number

    Returns:
        True if number represents 1
    """
    if '.' in s:
        return s.rstrip('0').rstrip('.') == '1'
    else:
        return s == '1'
