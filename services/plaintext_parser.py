"""
Plaintext parser for GnuCash format.

Parses the full GnuCash plaintext format including:
- Commodity declarations (commodity CAD)
- Account declarations (open Assets:Bank:Checking)
- Transactions with full metadata (guid, notes, doc_link, etc.)
- Split metadata (share_price, value, action, memo)

This is a complete reimplementation for the new architecture that includes
all features from the legacy parser.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Iterable, List, Optional, Tuple

from infrastructure.gnucash.utils import decode_value_from_string


@dataclass
class CustomerDirective:
    id: str
    name: str
    currency: str
    addr1: Optional[str] = None
    addr2: Optional[str] = None
    addr3: Optional[str] = None
    addr4: Optional[str] = None
    email: Optional[str] = None


@dataclass
class VendorDirective:
    id: str
    name: str
    currency: str


@dataclass
class TaxTableEntry:
    account: str
    rate: str
    type: str


@dataclass
class TaxTableDirective:
    name: str
    entries: List[TaxTableEntry] = field(default_factory=list)


@dataclass
class InvoiceEntry:
    date: str
    description: str
    action: str
    account: str
    quantity: str
    price: str
    taxable: bool
    tax_included: bool
    tax_table: Optional[str] = None


@dataclass
class PostedDirective:
    date: str
    due: str
    account: str
    memo: str
    accumulate: bool


@dataclass
class PaymentDirective:
    date: str
    amount: str
    bank_account: str
    memo: str
    num: Optional[str] = None


@dataclass
class InvoiceDirective:
    id: str
    customer_id: str
    currency: str
    date_opened: str
    billing_id: Optional[str] = None
    notes: Optional[str] = None
    entries: List[InvoiceEntry] = field(default_factory=list)
    posted: Optional[PostedDirective] = None
    payments: List[PaymentDirective] = field(default_factory=list)


@dataclass
class BillEntry:
    date: str
    description: str
    account: str
    quantity: str
    price: str
    taxable: bool
    tax_table: Optional[str] = None


@dataclass
class BillDirective:
    id: str
    vendor_id: str
    currency: str
    date_opened: str
    entries: List[BillEntry] = field(default_factory=list)
    posted: Optional[PostedDirective] = None
    payments: List[PaymentDirective] = field(default_factory=list)


class DirectiveType(Enum):
    """Types of directives in plaintext format"""
    ROOT = 0
    OPEN_ACCOUNT = 1
    CREATE_COMMODITY = 2
    TRANSACTION = 3
    SPLIT = 4
    METADATA_KEY_VALUE = 5
    CUSTOMER = 6
    VENDOR = 7
    TAXTABLE = 8
    INVOICE = 9
    BILL = 10
    TAXTABLE_ENTRY = 11
    INVOICE_ENTRY = 12
    BILL_ENTRY = 13
    POSTED = 14
    PAYMENT = 15



class PlaintextDirective:
    """Represents a single directive (commodity, account, transaction, split)"""

    def __init__(self, directive_type: DirectiveType, level: int, line: str, parent: PlaintextDirective = None):
        self.type = directive_type
        self.children: List[PlaintextDirective] = []
        self.props: Dict[str, str] = {}
        self.metadata: Dict[str, any] = {}
        self.level = level
        self.parent = parent
        self.line = line

    def __str__(self):
        return (f'PlaintextDirective(type={self.type}, level={self.level}, '
                f'props={self.props}, metadata={self.metadata}, children={len(self.children)})')


class PlaintextIndentation:
    """Tracks indentation style (tabs or spaces and count)"""

    def __init__(self, indent_char: str, indent_count: int):
        self.indent_char = indent_char
        self.indent_count = indent_count


class PlaintextParser:
    """
    Parser for GnuCash plaintext format.

    Parses files into a tree structure with:
    - Root directive containing all top-level directives
    - Commodities, accounts, and transactions as children
    - Splits as children of transactions
    - Metadata attached to each directive
    """

    def __init__(self):
        self.root_directive: Optional[PlaintextDirective] = None
        self.current_directive: Optional[PlaintextDirective] = None
        self.indent: Optional[PlaintextIndentation] = None
        self.accounts: Dict[str, PlaintextDirective] = {}
        self.commodities: Dict[str, PlaintextDirective] = {}
        self.errors: List[str] = []

    def parse_file(self, plaintext_file_path: str):
        """Parse plaintext file"""
        def lines_of_file():
            with open(plaintext_file_path) as file:
                yield from file

        self.parse_iterable(lines_of_file())

    def parse_string(self, plaintext_content: str):
        """Parse plaintext string"""
        def plaintext_lines():
            start = 0
            while start < len(plaintext_content):
                end = plaintext_content.find('\n', start)
                if end == -1:
                    yield plaintext_content[start:]
                    break
                yield plaintext_content[start:end]
                start = end + 1

        return self.parse_iterable(plaintext_lines())

    def verify_line_indentation(self, leading_spaces: str) -> Tuple[bool, int, Optional[str]]:
        """
        Verify line indentation is consistent.

        Returns:
            Tuple of (is_valid, directive_level, error_msg)
        """
        tabs_count = leading_spaces.count('\t')
        spaces_count = leading_spaces.count(' ')

        if tabs_count > 0 and spaces_count > 0:
            return False, -1, 'Mixed tabs and spaces'

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
                    return False, -1, 'Expected spaces but found tabs'
                elif (tabs_count % self.indent.indent_count) != 0:
                    return False, -1, (f'Found {tabs_count} tabs but expected multiple of {self.indent.indent_count}')
                else:
                    return True, tabs_count // self.indent.indent_count + 1, None
            else:
                if self.indent.indent_char != ' ':
                    return False, -1, 'Expected tabs but found spaces'
                elif (spaces_count % self.indent.indent_count) != 0:
                    return False, -1, (f'Found {spaces_count} spaces but expected multiple of {self.indent.indent_count}')
                else:
                    return True, spaces_count // self.indent.indent_count + 1, None

    def parse_iterable(self, plaintext_lines: Iterable[str]):
        """Parse lines into directive tree"""
        self.root_directive = PlaintextDirective(DirectiveType.ROOT, 0, "", None)
        self.current_directive = self.root_directive

        for line_number, line in enumerate(plaintext_lines):
            if line.strip() == "":
                continue

            leading_spaces = re.match(r'^[\t\s]*', line).group(0)
            (is_indent_valid, line_level, indent_error_msg) = self.verify_line_indentation(leading_spaces)

            if not is_indent_valid:
                self.errors.append(f'Invalid indentation in line {line_number}: {indent_error_msg}')
                break

            parent_directive = self.find_parent_directive(line_level, self.current_directive)
            if parent_directive is None:
                self.errors.append(f'Error processing line {line_number}: cannot find parent directive')
                break

            # Try to parse line as different directive types
            (account_date, directive, account_name) = parse_open_account(line)
            (commodity_date, directive, commodity_symbol) = parse_commodity_directive(line)
            (tx_date, tx_num, tx_desc) = parse_transaction_head(line)
            (split_account_name, split_amount, split_symbol) = parse_split(line)
            (key, value) = parse_metadata(line)
            customer_id = parse_customer(line.strip())
            taxtable_name = parse_taxtable(line.strip())
            invoice_id = parse_invoice(line.strip())
            vendor_id = parse_vendor(line.strip())
            bill_id = parse_bill(line.strip())
            block_type = parse_block(line.strip())

            if account_date is not None:
                obj = PlaintextDirective(DirectiveType.OPEN_ACCOUNT, line_level, line, parent_directive)
                obj.props['account'] = account_name
                obj.props['date'] = account_date
                parent_directive.children.append(obj)
                self.accounts[account_name] = obj
                self.current_directive = obj
            elif commodity_date is not None:
                obj = PlaintextDirective(DirectiveType.CREATE_COMMODITY, line_level, line, parent_directive)
                obj.props['symbol'] = commodity_symbol
                obj.props['date'] = commodity_date
                parent_directive.children.append(obj)
                self.commodities[commodity_symbol] = obj
                self.current_directive = obj
            elif tx_date is not None:
                obj = PlaintextDirective(DirectiveType.TRANSACTION, line_level, line, parent_directive)
                obj.props['tx_num'] = tx_num
                obj.props['tx_desc'] = tx_desc
                obj.props['date'] = tx_date
                parent_directive.children.append(obj)
                self.current_directive = obj
            elif split_account_name is not None:
                obj = PlaintextDirective(DirectiveType.SPLIT, line_level, line, parent_directive)
                obj.props['amount'] = split_amount
                obj.props['symbol'] = split_symbol
                obj.props['account'] = split_account_name
                parent_directive.children.append(obj)
                self.current_directive = obj
            elif customer_id is not None:
                obj = PlaintextDirective(DirectiveType.CUSTOMER, line_level, line, parent_directive)
                obj.props['id'] = customer_id
                parent_directive.children.append(obj)
                self.current_directive = obj
            elif taxtable_name is not None:
                obj = PlaintextDirective(DirectiveType.TAXTABLE, line_level, line, parent_directive)
                obj.props['name'] = taxtable_name
                parent_directive.children.append(obj)
                self.current_directive = obj
            elif invoice_id is not None:
                obj = PlaintextDirective(DirectiveType.INVOICE, line_level, line, parent_directive)
                obj.props['id'] = invoice_id
                parent_directive.children.append(obj)
                self.current_directive = obj
            elif vendor_id is not None:
                obj = PlaintextDirective(DirectiveType.VENDOR, line_level, line, parent_directive)
                obj.props['id'] = vendor_id
                parent_directive.children.append(obj)
                self.current_directive = obj
            elif bill_id is not None:
                obj = PlaintextDirective(DirectiveType.BILL, line_level, line, parent_directive)
                obj.props['id'] = bill_id
                parent_directive.children.append(obj)
                self.current_directive = obj
            elif block_type is not None:
                if block_type == "entry":
                    if parent_directive.type == DirectiveType.TAXTABLE:
                        obj = PlaintextDirective(DirectiveType.TAXTABLE_ENTRY, line_level, line, parent_directive)
                    elif parent_directive.type == DirectiveType.INVOICE:
                        obj = PlaintextDirective(DirectiveType.INVOICE_ENTRY, line_level, line, parent_directive)
                    else:
                        obj = PlaintextDirective(DirectiveType.BILL_ENTRY, line_level, line, parent_directive)
                elif block_type == "posted":
                    obj = PlaintextDirective(DirectiveType.POSTED, line_level, line, parent_directive)
                else:
                    obj = PlaintextDirective(DirectiveType.PAYMENT, line_level, line, parent_directive)
                parent_directive.children.append(obj)
                self.current_directive = obj
            elif key is not None:
                parent_directive.metadata[key] = value
                if key == 'namespace' and parent_directive.type == DirectiveType.CREATE_COMMODITY:
                    namespace = value
                    symbol = parent_directive.props['symbol']
                    self.commodities[f'{namespace}.{symbol}'] = parent_directive

    def find_parent_directive(self, line_level: int, ctx_obj):
        """Find parent directive for given level"""
        if ctx_obj is None:
            return None
        if ctx_obj.level == line_level - 1:
            return ctx_obj
        return self.find_parent_directive(line_level, ctx_obj.parent)


# Regex patterns for parsing different line types
transaction_pattern1 = r'^(\d{4}-\d{2}-\d{2})\s+\*\s*$'
transaction_pattern2 = r'^(\d{4}-\d{2}-\d{2})\s+\*\s+("(?:\\.|[^"])*?"|\{.*?\})(?:\s("(?:\\.|[^"])*?"|\{.*?\}))?\s*$'
split_pattern = r'^\s*([^"]*?)\s+([+|-]*\d+(?:\.\d+)?)\s+([^ ]+)\s*$'
split_pattern2 = r'^\s*([^"]*?)\s+([+|-]*\d+(?:\.\d+)?)\s+("[^"]+")\s*$'
metadata_pattern = r'^\s*([a-z_][a-zA-Z0-9_\-.]*)\s*:\s*(.*?)\s*$'
commodity_pattern = r'^\s*(\d{4}-\d{2}-\d{2})\s+(commodity)\s+([^"\']*)\s*$'
open_account_pattern = r'^\s*(\d{4}-\d{2}-\d{2})\s+(open)\s+([^"]*)\s*([^"\']*)\s*$'
open_account_pattern2 = r'^\s*(\d{4}-\d{2}-\d{2})\s+(open)\s+("(?:\\.|[^"])*?"|\{.*?\})\s*([^"\']*)\s*$'
customer_pattern = r'^customer\s+"(.*?)"\s*$'
taxtable_pattern = r'^taxtable\s+"(.*?)"\s*$'
invoice_pattern = r'^invoice\s+"(.*?)"\s*$'
vendor_pattern = r'^vendor\s+"(.*?)"\s*$'
bill_pattern = r'^bill\s+"(.*?)"\s*$'
block_pattern = r'^\s*(entry|posted|payment):\s*$'


def parse_customer(line: str) -> Optional[str]:
    match = re.match(customer_pattern, line)
    if match:
        return match.group(1)
    return None


def parse_taxtable(line: str) -> Optional[str]:
    match = re.match(taxtable_pattern, line)
    if match:
        return match.group(1)
    return None


def parse_invoice(line: str) -> Optional[str]:
    match = re.match(invoice_pattern, line)
    if match:
        return match.group(1)
    return None


def parse_vendor(line: str) -> Optional[str]:
    match = re.match(vendor_pattern, line)
    if match:
        return match.group(1)
    return None


def parse_bill(line: str) -> Optional[str]:
    match = re.match(bill_pattern, line)
    if match:
        return match.group(1)
    return None


def parse_block(line: str) -> Optional[str]:
    match = re.match(block_pattern, line)
    if match:
        return match.group(1)
    return None





def parse_split(split_line: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Parse split line.

    Returns:
        Tuple of (account_name, amount, symbol)
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
    Parse transaction header line.

    Returns:
        Tuple of (date, num, description)
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


def parse_metadata(line: str) -> Tuple[Optional[str], Optional[any]]:
    """
    Parse metadata line.

    Returns:
        Tuple of (key, value)
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
    Parse open account directive.

    Returns:
        Tuple of (date, directive="open", account_name)
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
    Parse commodity directive.

    Returns:
        Tuple of (date, directive="commodity", symbol)
    """
    match = re.match(commodity_pattern, line)
    if match:
        date = match.group(1)
        directive = match.group(2)
        commodity = match.group(3)
        return date.strip(), directive.strip(), commodity.strip()
    else:
        return None, None, None
