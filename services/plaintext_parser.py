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
    # Q-017: per-entry tax breakdown — repeated child block under
    # INVOICE_ENTRY / BILL_ENTRY when rendered by `print-invoice
    # --format plaintext`. Informational only; the importer recomputes
    # from the tax_table + entry fields and errors on mismatch.
    TAX_BREAKDOWN = 16

    # Per-account open-credit summary — repeated child block under
    # OPEN_ACCOUNT on AR/AP accounts that hold an open prepayment lot.
    # Informational: the exporter recomputes and emits it from the live
    # lots; the importer does not act on it (the authoritative data is the
    # per-split lot_owner KVPs, which rebuild the lots).
    OPEN_PREPAYMENT = 17

    # Q-028: book-level seller/company identity (Company Name, Company ID,
    # GST/PST registration numbers, address, contact). A singleton header
    # block `company` whose indented `key: value` children populate the
    # book's Business → Company options. Round-trips the company info that
    # `print-invoice` / `print-bill` render in the seller block.
    COMPANY = 18

    # Q-039: which splits of one transaction settle this invoice or bill.
    #
    # `txn_guid:` + `txn_split_guid:` name one settling split, which is nearly
    # every settlement. A hand-written transaction may clear one receivable
    # with several splits, and that is still **one** payment — money arrived
    # once — so it is one `payment:` block naming all of them, not several
    # blocks. Written as directives rather than as a repeated key because a
    # split belongs to a transaction, and because the parse loop appends a
    # child per directive line while a repeated key would need `metadata` to
    # start collecting, which would make `memo:` collectable too.
    #
    #     payment:
    #         Transaction "c9f27c2b…"
    #             PaymentSplit "614b338d…"
    #             PaymentSplit "8d1c0a44…"
    #
    # Capitalised, which tells them from the lower-case keys of the block they
    # sit in and from an account path opening a split line.
    PAYMENT_TRANSACTION = 19
    PAYMENT_SPLIT = 20

    # Q-041: one entry of the book's price database — what one unit of a
    # commodity was worth in a currency at a moment. A header block like
    # `company`, with no date on its line: its `time:` is a moment, and a date
    # in front of it would say less than the block does.
    PRICE = 21



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
        # A transaction's block as the file writes it, its head and every line
        # under it but comments, so an update can tell a block the book's own
        # export would write from one that changes something.
        self.text: List[str] = [line.rstrip()] if directive_type == DirectiveType.TRANSACTION else []


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
        """Parse plaintext file.

        Read as UTF-8, which is what this format is written in — the exporter
        writes it and every fixture is in it. Left to the locale, a ledger
        naming a customer `Éditions Cliché` is unreadable on a machine whose
        `LANG` is not a UTF-8 one, and the error names a byte offset rather
        than the line it is on.
        """
        def lines_of_file():
            with open(plaintext_file_path, encoding='utf-8') as file:
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

        # `start=1`, because the numbers below go into messages a reader takes
        # to their editor, and every editor counts from one. Left at the
        # default they named the line above the mistake.
        for line_number, line in enumerate(plaintext_lines, start=1):
            if line.strip() == "":
                continue
            # A line written for a reader rather than for the book, opened by
            # `#`, `;` or `;;`.
            #
            # `#` is Q-019: the print-invoice / print-bill plaintext renderer
            # prepends caveats ("tax figures are provisional", "Issued by: …")
            # on `#` lines, and a rendered invoice has to re-import cleanly
            # without those reaching the recipient's book.
            #
            # `;` and `;;` are what a ledger keeps notes with, and this tool
            # already reads both elsewhere: a beancount file's comments are `;`
            # (`services/beancount_parser.py`), and the reconcile preview this
            # tool writes opens its sections with `;;`, which
            # `services/reconcile_preview_reader.py` skips. A person who edits
            # a preview and imports it, or who writes notes the way every other
            # plaintext ledger does, was told the line is "not a line this
            # format reads" — refused for being a comment, in a file this tool
            # had written the comments into.
            #
            # Only at the beginning of a line, as `#` is. The format has no
            # trailing comments, so a `;` after a value is part of that value
            # and a description reading "paid; see note" means what it says.
            if line.lstrip()[:1] in ('#', ';'):
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
            company_head = parse_company_head(line.strip())
            price_head = parse_price_head(line.strip())
            payment_txn_guid = parse_payment_transaction(line.strip())
            payment_split_guid = parse_payment_split(line.strip())
            customer_id = parse_customer(line.strip())
            taxtable_name = parse_taxtable(line.strip())
            invoice_id = parse_invoice(line.strip())
            vendor_id = parse_vendor(line.strip())
            bill_id = parse_bill(line.strip())
            block_type = parse_block(line.strip())
            # A line under a transaction is part of that transaction's block.
            block = parent_directive
            while block.parent is not None and block.parent.parent is not None:
                block = block.parent
            if block.type == DirectiveType.TRANSACTION:
                block.text.append(line.rstrip())

            # How many directives the parent held before this line, so one the
            # line adds can be checked against where it was written.
            children_before = len(parent_directive.children)

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
                # An account, then the amount. A line with the account left
                # out still matches the split pattern, with an empty account,
                # and an empty account name finds the book's root account:
                # the split was booked there with `Errors: 0`, and the book
                # could not be exported afterwards (measured on 5.10).
                if not split_account_name:
                    self.errors.append(
                        f'Error processing line {line_number}: a split line gives '
                        f'its account, then its amount and commodity, and this '
                        f'one has no account: {line.strip()!r}.')
                    break
                obj = PlaintextDirective(DirectiveType.SPLIT, line_level, line, parent_directive)
                obj.props['amount'] = split_amount
                obj.props['symbol'] = split_symbol
                obj.props['account'] = split_account_name
                parent_directive.children.append(obj)
                self.current_directive = obj
            elif payment_txn_guid is not None:
                # Under a `payment:` block, and nowhere else. Both of these
                # match on `line.strip()`, so without the check a
                # `Transaction "…"` under `posted:`, under an `entry:`, or at
                # top level parsed into a directive nothing ever reads — a
                # line the file states and the run ignores, which is what
                # every other unread line here is refused for.
                # `the_settlement_a_block_gives` refuses an astray
                # `PaymentSplit` one level in on exactly this reasoning; these
                # are the same mistake one level out.
                if parent_directive.type != DirectiveType.PAYMENT:
                    self.errors.append(
                        f'Error processing line {line_number}: a '
                        f'`Transaction "..."` line names the bank transaction '
                        f'a payment refers to, so it belongs under a '
                        f'`payment:` block. This one is under '
                        f'{parent_directive.type.name.lower()}, where nothing '
                        f'would read it.')
                    break
                obj = PlaintextDirective(DirectiveType.PAYMENT_TRANSACTION,
                                         line_level, line, parent_directive)
                obj.props['guid'] = payment_txn_guid
                parent_directive.children.append(obj)
                self.current_directive = obj
            elif payment_split_guid is not None:
                # Under the `Transaction` block whose split it gives. A split
                # is a child of its transaction everywhere else in this
                # format, and one written anywhere else gives a split of
                # nothing.
                if parent_directive.type != DirectiveType.PAYMENT_TRANSACTION:
                    self.errors.append(
                        f'Error processing line {line_number}: '
                        f'`PaymentSplit "{payment_split_guid}"` is not under a '
                        f'`Transaction` block, so it gives a split of nothing '
                        f'— it is under {parent_directive.type.name.lower()}, '
                        f'where nothing would read it. A payment gives its '
                        f'settling splits inside the transaction they belong '
                        f'to:\n'
                        f'\t\tTransaction "<the transaction>"\n'
                        f'\t\t\tPaymentSplit "<a split of it>"\n'
                        f'Indent it under one, or give a single split with '
                        f'`txn_split_guid:` instead.')
                    break
                obj = PlaintextDirective(DirectiveType.PAYMENT_SPLIT,
                                         line_level, line, parent_directive)
                obj.props['guid'] = payment_split_guid
                parent_directive.children.append(obj)
                self.current_directive = obj
            elif company_head:
                obj = PlaintextDirective(DirectiveType.COMPANY, line_level, line, parent_directive)
                parent_directive.children.append(obj)
                self.current_directive = obj
            elif price_head:
                # A price stands on its own. Written inside another block it
                # would be a child nothing reads, which is what every other
                # unread line here is refused for.
                if parent_directive.type != DirectiveType.ROOT:
                    self.errors.append(
                        f'Error processing line {line_number}: a `price` block '
                        f'stands on its own, not inside '
                        f'{parent_directive.type.name.lower()}.')
                    break
                obj = PlaintextDirective(DirectiveType.PRICE, line_level, line, parent_directive)
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
                elif block_type == "breakdown":
                    # Q-017: tax-breakdown sub-block, repeats under an
                    # invoice/bill entry. Each block carries account,
                    # rate, amount keys (informational).
                    obj = PlaintextDirective(DirectiveType.TAX_BREAKDOWN, line_level, line, parent_directive)
                elif block_type == "open_prepayment":
                    # Per-account open-credit summary under OPEN_ACCOUNT.
                    # Informational; the importer ignores it (the exporter
                    # recomputes it from the live lots on every export).
                    obj = PlaintextDirective(DirectiveType.OPEN_PREPAYMENT, line_level, line, parent_directive)
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
            else:
                # Read by nothing. Passed over, the line went missing from the
                # book with nothing said — a note typed where a key belongs,
                # or a split whose amount is written in a way no pattern here
                # reads — so it is refused like every other unread line.
                self.errors.append(
                    f'Error processing line {line_number}: {line.strip()!r} is not '
                    f'a line this format reads: not a block, not a split, and not '
                    f'a `key: value`.')
                break

            # Under an `open` line the import reads the account's keys and its
            # `open_prepayment:` blocks, and nothing else. A `payment:` block
            # or a transaction written there imported as nothing and reported
            # no error, so it is refused for the reason a `price` block inside
            # another block is.
            if (parent_directive.type == DirectiveType.OPEN_ACCOUNT
                    and len(parent_directive.children) > children_before
                    and parent_directive.children[-1].type != DirectiveType.OPEN_PREPAYMENT):
                self.errors.append(
                    f'Error processing line {line_number}: under an `open` line '
                    f'only its keys and `open_prepayment:` blocks are read. This '
                    f'{parent_directive.children[-1].type.name.lower()} is under '
                    f"the open of {parent_directive.props['account']}, where "
                    f'nothing would read it.')
                break
            # And under a transaction its keys and its splits. Every line there
            # was taken for a split, so a `posted:` block failed the import
            # with `'account'` — the key it lacked — and no line number.
            if (parent_directive.type == DirectiveType.TRANSACTION
                    and len(parent_directive.children) > children_before
                    and parent_directive.children[-1].type != DirectiveType.SPLIT):
                self.errors.append(
                    f'Error processing line {line_number}: under a transaction '
                    f'only its keys and its splits are read. This '
                    f'{parent_directive.children[-1].type.name.lower()} is under '
                    f"the transaction on {parent_directive.props['date']}, where "
                    f'nothing would read it.')
                break
            # And under a payment's `Transaction "..."` line, its `PaymentSplit`
            # lines. A split line written there parsed with no error and the
            # payment applied only the `PaymentSplit` beside it (measured on
            # 5.10), the line read by nobody.
            if (parent_directive.type == DirectiveType.PAYMENT_TRANSACTION
                    and len(parent_directive.children) > children_before
                    and parent_directive.children[-1].type != DirectiveType.PAYMENT_SPLIT):
                self.errors.append(
                    f'Error processing line {line_number}: under a `Transaction "..."` '
                    f'line only its `PaymentSplit` lines are read. This '
                    f'{parent_directive.children[-1].type.name.lower()} is under '
                    f"the transaction {parent_directive.props['guid']}, where "
                    f'nothing would read it.')
                break

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
# A split's amount is a number, or the literal `$residual$` — a request for
# whatever the other splits of the transaction leave over (Q-035). It is a
# token rather than an omitted amount so that a truncated line can never
# silently become a residual split, and sigil-delimited so `residual` stays
# usable as an account name or a commodity.
RESIDUAL_AMOUNT = '$residual$'
_amount_re = r'(?:[+|-]*\d+(?:\.\d+)?|\$residual\$)'
split_pattern = r'^\s*([^"]*?)\s+(' + _amount_re + r')\s+([^ ]+)\s*$'
split_pattern2 = r'^\s*([^"]*?)\s+(' + _amount_re + r')\s+("[^"]+")\s*$'
# A key, optionally indexed: `addr[0]`. The index is how the format writes a
# value that is a list of lines rather than one line — an address is the only
# one today — and it is part of the key rather than a new kind of line so that
# every reader that already splits on the colon keeps working.
#
# Bracketed rather than numbered (`addr1`, `addr2`) so that the list stays
# distinguishable from an ordinary key that happens to end in a digit. A book's
# custom keys are the book owner's to name, and `abc1`/`abc2` are two unrelated
# keys; without the brackets, taking `addr` + any number for the address would
# have reserved a whole namespace of names nobody had agreed to give up, and
# made `addr7` mean something different depending on which block it was in.
#
# Only a trailing index parses, and only digits inside it, so a stray bracket
# is still a line the reader has to fix rather than a key that quietly appears.
metadata_pattern = r'^\s*([a-z_][a-zA-Z0-9_\-.]*(?:\[\d+\])?)\s*:\s*(.*?)\s*$'
commodity_pattern = r'^\s*(\d{4}-\d{2}-\d{2})\s+(commodity)\s+([^"\']*)\s*$'
open_account_pattern = r'^\s*(\d{4}-\d{2}-\d{2})\s+(open)\s+([^"]*)\s*([^"\']*)\s*$'
open_account_pattern2 = r'^\s*(\d{4}-\d{2}-\d{2})\s+(open)\s+("(?:\\.|[^"])*?"|\{.*?\})\s*([^"\']*)\s*$'
payment_transaction_pattern = r'^Transaction\s+"(.*?)"\s*$'
payment_split_pattern = r'^PaymentSplit\s+"(.*?)"\s*$'
customer_pattern = r'^customer\s+"(.*?)"\s*$'
taxtable_pattern = r'^taxtable\s+"(.*?)"\s*$'
invoice_pattern = r'^invoice\s+"(.*?)"\s*$'
vendor_pattern = r'^vendor\s+"(.*?)"\s*$'
bill_pattern = r'^bill\s+"(.*?)"\s*$'
company_pattern = r'^company\s*$'
price_pattern = r'^price\s*$'
block_pattern = r'^\s*(entry|posted|payment|breakdown|open_prepayment):\s*$'


def parse_price_head(line: str) -> bool:
    """Match the header line of a `price` block (Q-041)."""
    return re.match(price_pattern, line) is not None


def parse_company_head(line: str) -> bool:
    """Match the book-level `company` header line (Q-028). The block's
    indented `key: value` children are accumulated as metadata by the
    generic metadata path, so this only has to recognise the header."""
    return re.match(company_pattern, line) is not None


def parse_payment_transaction(line: str) -> Optional[str]:
    """The guid on a `Transaction "…"` line under a `payment:` block."""
    match = re.match(payment_transaction_pattern, line)
    if match:
        return match.group(1)
    return None


def parse_payment_split(line: str) -> Optional[str]:
    """The guid on a `PaymentSplit "…"` line under a `Transaction` block."""
    match = re.match(payment_split_pattern, line)
    if match:
        return match.group(1)
    return None


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
        if account_name.strip().endswith(':'):
            # A `key: NUM SYMBOL` metadata line (e.g. `amount: 50.00 CAD`)
            # superficially matches the split shape. A real account path
            # never ends with a colon, so fall through to metadata parsing.
            return None, None, None
        return account_name.strip(), amount.strip(), symbol.strip()
    else:
        match = re.match(split_pattern2, split_line)
        if match:
            account_name = match.group(1)
            amount = match.group(2)
            symbol = decode_value_from_string(match.group(3))
            if account_name.strip().endswith(':'):
                return None, None, None
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
