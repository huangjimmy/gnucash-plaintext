from __future__ import annotations

import re
from utils import (beancount_compatible_account_name, beancount_compatible_commodity_symbol, decode_value_from_string)
import sys
if sys.version_info >= (3, 8):
    from typing import Tuple, Optional, Iterable, Dict, TypedDict, NotRequired
else:
    from typing_extensions import Tuple, Optional, Iterable, Dict, TypedDict, NotRequired

from enum import Enum


class DirectiveType(Enum):
    ROOT = 0
    OPEN_ACCOUNT = 1
    CREATE_COMMODITY = 2
    TRANSACTION = 3
    SPLIT = 4
    METADATA_KEY_VALUE = 5


CommodityMetadata = TypedDict('CommodityMetadata', {
    '__typename': str,
    'mnemonic': str,
    'fullname': str,
    'namespace': str,
    'fraction': int,
})


AccountMetadata = TypedDict('AccountMetadata', {
    'guid': NotRequired[str],
    'type': str,
    '__typename': NotRequired[str],
    'placeholder': NotRequired[str],
    'code': NotRequired[str],
    'description': NotRequired[str],
    'color': NotRequired[str],
    'notes': NotRequired[str],
    'tax_related': NotRequired[str],
    'commodity.namespace': str,
    'commodity.mnemonic': str
})


TransactionMetaData = TypedDict('TransactionMetaData', {
    'guid': NotRequired[str],
    '__typename': NotRequired[str],
    'currency.namespace': NotRequired[str],
    'currency.mnemonic': str,
    'doc_link': NotRequired[str],
    'notes': NotRequired[str],
})


SplitMetadata = TypedDict('SplitMetadata', {
    'guid': NotRequired[str],
    '__typename': NotRequired[str],
    'account.commodity.namespace': NotRequired[str],
    'account.commodity.mnemonic': NotRequired[str],
    'share_price': NotRequired[str],
    'value': NotRequired[str],
    'action': NotRequired[str],
    'memo': NotRequired[str],

})


class PlaintextLedger:
    def __init__(self, directive_type: DirectiveType, level: int, line: str, parent: 'PlaintextLedger' = None):
        self.type = directive_type
        self.children: [PlaintextLedger] = []
        self.props = {}
        self.metadata: CommodityMetadata | AccountMetadata | TransactionMetaData | SplitMetadata = {}
        self.level = level
        self.parent = parent
        self.line = line

    def beancount_compatible_commodity_symbol(self) -> Optional[str]:
        if self.type == DirectiveType.CREATE_COMMODITY:
            namespace = self.metadata['namespace']
            mnemonic = self.metadata['mnemonic']
            if namespace == 'CURRENCY':
                return beancount_compatible_commodity_symbol(mnemonic)
            else:
                return beancount_compatible_commodity_symbol(f'{namespace}.{mnemonic}')
        return None

    def beancount_compatible_account_name(self) -> Optional[str]:
        """
        returns a beancount compatible account name if this ledger directive is DirectiveType.OPEN_ACCOUNT

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
        :return:
        """
        if self.type == DirectiveType.OPEN_ACCOUNT:
            account_name = self.props['account']
            account_type = self.metadata['type']
            return beancount_compatible_account_name(account_name, account_type)
        return None

    def __str__(self):
        return (f'PlaintextObject(type={self.type}, level={self.level}, line={self.line}, props={self.props}, '
                f'metadata={self.metadata}, children_count={len(self.children)})')


class PlaintextIndentation:
    def __init__(self, indent_char: str, indent_count: int):
        self.indent_char = indent_char
        self.indent_count = indent_count


class PlaintextLedgerParser:

    def __init__(self):
        self.root_directive: Optional[PlaintextLedger] = None
        self.current_directive: Optional[PlaintextLedger] = None
        self.indent: Optional[PlaintextIndentation] = None
        self.accounts: Dict[str, PlaintextLedger] = {}
        self.commodities: Dict[str, PlaintextLedger] = {}
        self.errors = []

    def parse_file(self, plaintext_file_path: str):
        def lines_of_file():
            with open(plaintext_file_path, "r") as file:
                for line in file:
                    yield line
            pass
        self.parse_iterable(lines_of_file())

    def parse_string(self, plaintext_content: str):
        def plaintext_lines():
            start = 0
            while start < len(plaintext_content):
                end = plaintext_content.find('\n', start)
                if end == -1:
                    yield plaintext_content[start:]
                    break
                yield plaintext_content[start:end]
                start = end + 1
            pass
        return self.parse_iterable(plaintext_lines())

    def verify_line_indentation(self, leading_spaces: str) -> Tuple[bool, int, Optional[str]]:
        """
        AA ; level = 1
        \tBB ; level = 2
        \t\tCC ; level = 3
        :param leading_spaces:
        :return: A tuple of (is_indent_valid: bool, directive_level: int, error_msg: Optional[str])
        """
        tabs_count = leading_spaces.count('\t')
        spaces_count = leading_spaces.count(' ')
        if tabs_count > 0 and spaces_count > 0:
            return False, -1, ''
        if tabs_count == 0 and spaces_count == 0:
            return True, 1, None
        if self.indent is None:
            if tabs_count > 0:
                self.indent = PlaintextIndentation('\t', tabs_count)
            else:
                self.indent = PlaintextIndentation(' ', spaces_count)
            return True, 2, None
        else:
            if tabs_count > 0:
                if self.indent.indent_char != '\t':
                    return False, -1, 'expecting tabs but found spaces'
                elif (tabs_count % self.indent.indent_count) != 0:
                    return False, -1, (f'there are {tabs_count} tabs '
                                       f'but {tabs_count} is not a multiple of {self.indent.indent_count}')
                else:
                    return True, tabs_count // self.indent.indent_count + 1, None
            else:
                if self.indent.indent_char != ' ':
                    return False, -1, 'expecting spaces but found tabs'
                elif (spaces_count % self.indent.indent_count) != 0:
                    return False, -1, (f'there are {spaces_count} spaces '
                                       f'but {spaces_count} is not a multiple of {self.indent.indent_count}')
                else:
                    return True, spaces_count // self.indent.indent_count + 1, None

    def parse_iterable(self, plaintext_lines: Iterable[str]):
        self.root_directive = PlaintextLedger(directive_type=DirectiveType.ROOT, level=0, line="", parent=None)
        self.current_directive = self.root_directive

        for line_number, line in enumerate(plaintext_lines):
            if line.strip() == "":
                continue
            leading_spaces = re.match(r'^[\t\s]*', line).group(0)
            (is_ident_valid, line_level, indent_error_msg) = self.verify_line_indentation(leading_spaces)
            if not is_ident_valid:
                self.errors.append(f'invalid indentation in line {line_number}, {indent_error_msg}')
                print(f'invalid indentation in line {line_number}, {indent_error_msg}')
                break
            parent_directive = self.find_parent_directive(line_level, self.current_directive)
            if parent_directive is None:
                self.errors.append(f'error processing line {line_number}, cannot find parent directive')
                print(f'error processing line {line_number}, cannot find parent directive')
                break

            (account_open_date, directive, account_name) = parse_open_account(line)
            (commodity_open_date, directive, commodity_symbol) = parse_commodity_directive(line)
            (tx_date, tx_num, tx_desc) = parse_transaction_head(line)
            (split_account_name, split_amount, split_symbol) = parse_split(line)
            (key, value) = parse_metadata(line)
            if account_open_date is not None:
                obj = PlaintextLedger(DirectiveType.OPEN_ACCOUNT, line_level, line, parent_directive)
                obj.props['account'] = account_name
                obj.props['date'] = account_open_date
                parent_directive.children.append(obj)
                self.accounts[account_name] = obj
                self.current_directive = obj
                pass
            elif commodity_open_date is not None:
                obj = PlaintextLedger(DirectiveType.CREATE_COMMODITY, line_level, line, parent_directive)
                obj.props['symbol'] = commodity_symbol
                obj.props['date'] = commodity_open_date
                parent_directive.children.append(obj)
                self.commodities[commodity_symbol] = obj
                self.current_directive = obj
                pass
            elif tx_date is not None:
                obj = PlaintextLedger(DirectiveType.TRANSACTION, line_level, line, parent_directive)
                obj.props['tx_num'] = tx_num
                obj.props['tx_desc'] = tx_desc
                obj.props['date'] = tx_date
                parent_directive.children.append(obj)
                self.current_directive = obj
                pass
            elif split_account_name is not None:
                obj = PlaintextLedger(DirectiveType.SPLIT, line_level, line, parent_directive)
                obj.props['amount'] = split_amount
                obj.props['symbol'] = split_symbol
                obj.props['account'] = split_account_name
                parent_directive.children.append(obj)
                self.current_directive = obj
                pass
            elif key is not None:
                parent_directive.metadata[key] = value
                if key == 'namespace' and parent_directive.type == DirectiveType.CREATE_COMMODITY:
                    namespace = value
                    symbol = parent_directive.props['symbol']
                    self.commodities[f'{namespace}.{symbol}'] = parent_directive
                pass
            else:
                pass
        pass

    def find_parent_directive(self, line_level: int, ctx_obj):
        if ctx_obj is None:
            return None
        if ctx_obj.level == line_level - 1:
            return ctx_obj
        return self.find_parent_directive(line_level, ctx_obj.parent)


# '2020-04-17 *'
transaction_pattern1 = r'^(\d{4}-\d{2}-\d{2})\s+\*\s*$'
# '2020-04-17 * "PAYROLL Amazon Canada F PAY EF0160010706702401379765 ZEFT04107"'
# '2020-04-17 * "{Tx\\\" Num}" "PAYROLL Amazon Canada F PAY EF0160010706702401379765 ZEFT04107"'
transaction_pattern2 = r'^(\d{4}-\d{2}-\d{2})\s+\*\s+("(?:\\.|[^"])*?"|\{.*?\})(?:\s("(?:\\.|[^"])*?"|\{.*?\}))?\s*$'

# 'Expenses-CAN:Tax CAN:EI Test Account 加拿大  94.80 CAD人民币'
# Expenses-CAN:Tax CAN:EI Test Account 加拿大
# 94.80
# CAD人民币
split_pattern = r'^\s*([^"]*?)\s+([+|-]*\d+(?:\.\d+)?)\s+([^ ]+)\s*$'
split_pattern2 = r'^\s*([^"]*?)\s+([+|-]*\d+(?:\.\d+)?)\s+("[^"]+")\s*$'

# notes: "This is a note"
# fraction: 100
metadata_pattern = r'^\s*([a-z_][a-zA-Z0-9_\-.]*)\s*:\s*(.*?)\s*$'

# 2021-12-30 commodity AMZN
commodity_pattern = r'^\s*(\d{4}-\d{2}-\d{2})\s+(commodity)\s+([^"\']*)\s*$'
# 2013-03-17 open Expenses:Auto:Gas
open_account_pattern = r'^\s*(\d{4}-\d{2}-\d{2})\s+(open)\s+([^"]*)\s*([^"\']*)\s*$'
open_account_pattern2 = r'^\s*(\d{4}-\d{2}-\d{2})\s+(open)\s+("(?:\\.|[^"])*?"|\{.*?\})\s*([^"\']*)\s*$'


def parse_split(split_line: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    :param split_line: a line that is expected to be a split of a gnucash transaction
    :return: tuple(account_name: str, amount: str, symbol: str)
    """
    match = re.match(split_pattern, split_line)
    if match:
        account_name = match.group(1)
        amount = match.group(2)
        symbol = match.group(3)
        return account_name.strip(), amount.strip(), symbol.strip()
    else:
        match = re.match(split_pattern2, split_line)
        if match:
            account_name = match.group(1)
            amount = match.group(2)
            symbol = decode_value_from_string(match.group(3))
            return account_name.strip(), amount.strip(), symbol.strip()
    return None, None, None


def parse_transaction_head(tx_line: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    :param tx_line: the first line of a gnucash transaction in plaintext format
    :return: (date: str, num: str, description: str)
    """
    match = re.match(transaction_pattern2, tx_line)
    if match:
        date = match.group(1)
        first_str = match.group(2)
        second_str = match.group(3)
        if second_str is None:
            return date, None, decode_value_from_string(first_str)
        else:
            return date, decode_value_from_string(first_str), decode_value_from_string(second_str)
    else:
        match = re.match(transaction_pattern1, tx_line)
        if match:
            return match.group(1), None, None
        else:
            return None, None, None


def parse_metadata(line: str) -> Tuple[Optional[str], Optional[None | int | float | bool | str]]:
    """

    :param line:
    :return: (key, value)
    """
    match = re.match(metadata_pattern, line)
    if match:
        key = match.group(1)
        value = match.group(2)
        return key.strip(), decode_value_from_string(value.strip())
    else:
        return None, None


def parse_open_account(line: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """

    :param line:
    :return: (date, directive = "open", account_name)
    """
    match = re.match(open_account_pattern, line)
    if match:
        date = match.group(1)
        directive = match.group(2)
        account_name = match.group(3)
        return date.strip(), directive.strip(), account_name.strip()
    else:
        match = re.match(open_account_pattern2, line)
        if match:
            date = match.group(1)
            directive = match.group(2)
            account_name = match.group(3)
            return date.strip(), directive.strip(), decode_value_from_string(account_name)
        return None, None, None


def parse_commodity_directive(line: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """

    :param line:
    :return: (date, directive = "commodity", symbol)
    """
    match = re.match(commodity_pattern, line)
    if match:
        date = match.group(1)
        directive = match.group(2)
        commodity = match.group(3)
        return date.strip(), directive.strip(), commodity.strip()
    else:
        return None, None, None
