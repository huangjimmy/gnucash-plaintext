from fractions import Fraction
from gnucash import Account, GncNumeric, GncCommodity
import copy
import re
import string
from typing import Optional
from decimal import Decimal


def get_account_full_name(account: Account):
    parent = account.get_parent()
    name = account.GetName()

    if parent != None and (not parent.is_root()):
        name = ":".join([get_account_full_name(parent), name])
    return name


def get_parent_accounts_and_self(account: Account):
    accounts = [account]
    parent = account.get_parent()
    while parent != None and not parent.is_root():
        accounts.insert(0, parent)
        parent = parent.get_parent()

    return accounts


def get_all_sub_accounts(account: Account, names=[]):
    "Iterate over all sub accounts of a given account."

    for child in account.get_children_sorted():
        child_names = names.copy()
        child_names.append(child.GetName())
        yield child, '::'.join(child_names)
        yield from get_all_sub_accounts(child, child_names)


def find_account(account: Account, name):
    if name == "" or name == "Root Account":
        return account

    names = name.split(":")

    def find_child(account: Account, name):
        for child in account.get_children_sorted():
            child_name = child.GetName()
            if child_name == name:
                return child
        return None

    acc = account
    for n in names:
        acc = find_child(acc, n)
        if acc == None:
            break

    return acc


def get_commodity_ticker(commodity: GncCommodity) -> str:
    mnemonic = commodity.get_mnemonic()
    namespace = commodity.get_namespace()
    if namespace == 'CURRENCY':
        return mnemonic
    return f'{namespace}.{mnemonic}'


def to_string_in_fraction_format(number: GncNumeric):
    """Convert a GncNumeric to a string in num/denom format
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
    if '/' in s:
        amount = GncNumeric(s)
    else:
        amount_numerator = int(Decimal(s.replace(',', '.')) * currency.get_fraction())
        amount_denominator = currency.get_fraction()
        amount = GncNumeric(amount_numerator, amount_denominator)
    return amount


def to_string_with_decimal_point_placed(number: GncNumeric):
    """Convert a GncNumeric to a string with decimal point placed if permissible.
    Otherwise returns its fractional representation.
    """

    number = copy.copy(number)
    if not number.to_decimal(None):
        return str(number)

    nominator = str(number.num())
    point_place = str(number.denom()).count('0')  # How many zeros in the denominator?
    if point_place == 0:
        return nominator

    if len(nominator) <= point_place:  # prepending zeros if the nominator is too short
        nominator = '0' * (point_place - len(nominator)) + nominator

    number_str = '.'.join([nominator[:-point_place], nominator[-point_place:]])
    if number_str.startswith('.-'):
        number_str = number_str.replace('.-', '-0.0')
    elif number_str[0] == '.':
        number_str = f'0{number_str}'
    if number_str.startswith('-.'):
        number_str = f'-0.{number_str[2:]}'
    return number_str


def escape_string(s: str) -> str:
    if s is None:
        return s

    chars_to_replace = "%\"\\\r\n"
    translation_table = str.maketrans(
        # {char: f"%{ord(char):02x}" for char in chars_to_replace}
        {
            '"': '\\"',
            '\\': '\\\\'
        }
    )
    return s.translate(translation_table)


def unescape_string(s: str) -> str:
    if s is None:
        return s

    return s.replace('\\"', '"').replace('\\\\', '\\')

    # def repl(match):
    #     hex_str = match.group(1)
    #     return chr(int(hex_str, 16))
    #
    # return re.sub(r'%([0-9a-fA-F]{2})', repl, s)


def encode_value_as_string(value):
    if value is None:
        return '#None'
    if isinstance(value, bool):
        return f'#{value}'
    if isinstance(value, (int, float, )):
        return '{value}'
    if isinstance(value, Fraction):
        return f'#{value.numerator}/{value.denominator}'
    if isinstance(value, str):
        return f'"{escape_string(value)}"'
    return encode_value_as_string(f'{value}')


def decode_value_from_string(s: str):
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
            return int(s)
        else:
            # if it is a float, just return the string itself
            return s
    elif s.startswith('"'):
        content = s[1:-1]
        return unescape_string(content)


def number_in_string_format_is_1(s):
    if '.' in s:
        return s.rstrip('0').rstrip('.') == '1'
    else:
        return s == '1'


def beancount_compatible_account_name(account_name: str, account_type: str) -> str:
    """
    returns a beancount compatible account name

    1 ensure top leve account name is one of Assets Liabilities Equity Income Expenses
        1.1 If a top level account name is not one of above, will append a one of above prefix to account name
            the prefix will be determined by top leve account type in gnucash
    2 Ensure each account name component starts with uppercase letter and follows by letters, numbers or dash.
        2.1 '\', '/','-', spaces and tabs are replaced with '-'
        2.2 CJK chars will be converted to its UTF-8 bytes hex string representation prefixed with 'H'
        text = "信用卡"
        utf8_bytes = text.encode('utf-8')
        hex_representation = utf8_bytes.hex()
        UTF-8 Bytes: b'\xe4\xbf\xa1\xe7\x94\xa8\xe5\x8d\xa1'
        Hex Representation: e4bfa1e794a8e58da1

    Account Liabilities:信用卡:BofA Rewards will become Liabilities:He4bfa1e794a8e58da1:BofA-Rewards
    Account Expenses-대한민국:식료품 장보기 물품 will become
        Expenses:Expenses-Heb8c80ed959cebafbceab5ad:Hec8b9deba38ced9288-Hec9ea5ebb3b4eab8b0

    6 asset accounts (Cash, Bank, Stock, Mutual Fund, Accounts Receivable, and Other Assets),
    3 liability accounts (Credit Card, Accounts Payable, and Liability), 1 equity account (Equity), 1 income account (Income), and 1 expense account (Expenses).

    GnuCash definitions

    static char const *
        account_type_name[NUM_ACCOUNT_TYPES] =
        {
            N_("Bank"),
            N_("Cash"),
            N_("Asset"),
            N_("Credit Card"),
            N_("Liability"),
            N_("Stock"),
            N_("Mutual Fund"),
            N_("Currency"),
            N_("Income"),
            N_("Expense"),
            N_("Equity"),
            N_("A/Receivable"),
            N_("A/Payable"),
            N_("Root"),
            N_("Trading")
            /*
              N_("Checking"),
              N_("Savings"),
              N_("Money Market"),
              N_("Credit Line")
            */
        };

    :return:
    """
    top_level_accounts = ['Assets', 'Liabilities', 'Equity', 'Income', 'Expenses']
    need_append_top_level_prefix = not any([account_name.startswith(f'{prefix}:') or account_name == prefix
                                            for prefix in top_level_accounts])

    def determine_prefix():
        if account_type == 'Credit Card' or account_name == 'A/Payable':
            return 'Liabilities'
        if (account_type == 'Stock' or account_type == 'Cash'
                or account_type == 'Mutual Fund' or account_type == 'Bank' or account_type == 'A/Receivable'):
            return 'Assets'
        for a in top_level_accounts:
            if a.startswith(account_type):
                return a
        return None

    # def find_cjk_indices(text):
    #     cjk_pattern = re.compile(r'[\u4e00-\u9fff\u3400-\u4dbf\u3040-\u309f\u30a0-\u30ff\uac00-\ud7af]+')
    #     matches = cjk_pattern.finditer(text)
    #     indices = [(match.start(), match.end()) for match in matches]
    #     return indices
    #
    # cjk_indicies = find_cjk_indices(account_name)
    # account_name_str = str(account_name)
    # for ind in cjk_indicies:
    #     (start, end) = ind
    #     cjk_substring = account_name_str[start:end]
    #     account_name = account_name.replace(cjk_substring, f'H{cjk_substring.encode("utf-8").hex()}')

    custom_punctuation = ''.join(c for c in string.punctuation if c != ':')
    translation_table = str.maketrans({char: '-' for char in custom_punctuation + ' '})
    account_name = account_name.translate(translation_table)
    if need_append_top_level_prefix:
        prefix = determine_prefix()
        account_name = f'{prefix}:{account_name}'
    return ':'.join(word.capitalize() if not word[0].isupper() else word for word in account_name.split(':'))


def beancount_compatible_commodity_symbol(symbol: str) -> str:
    if symbol is None:
        return symbol
    exclude_chars = ".-_"
    custom_punctuation = ''.join(c for c in string.punctuation if c not in exclude_chars)
    compatible_symbol = symbol.upper().translate(str.maketrans("", "", custom_punctuation))
    return compatible_symbol


def beancount_compatible_metadata_key(key: str) -> Optional[str]:
    if key is None:
        return key

    key = key.replace('.', '-')
    if key.startswith('_'):
        key = f'gnucash{key}'
    return key