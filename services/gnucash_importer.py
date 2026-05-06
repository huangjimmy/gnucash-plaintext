"""
Service for importing plaintext directives to GnuCash.

Converts PlaintextDirective objects from the parser into GnuCash objects
(commodities, accounts, transactions) with all metadata preserved.
"""

import ctypes
import logging
from datetime import datetime
from typing import List

import gnucash.gnucash_core_c as gc
from gnucash import Account, Book, GncCommodity, GncNumeric, Split, Transaction
from gnucash.gnucash_business import Customer, Entry, Invoice, TaxTable, TaxTableEntry, Vendor
from gnucash.gnucash_core_c import (
    ACCT_TYPE_ASSET,
    ACCT_TYPE_BANK,
    ACCT_TYPE_CASH,
    ACCT_TYPE_CREDIT,
    ACCT_TYPE_EQUITY,
    ACCT_TYPE_EXPENSE,
    ACCT_TYPE_INCOME,
    ACCT_TYPE_LIABILITY,
    ACCT_TYPE_MUTUAL,
    ACCT_TYPE_PAYABLE,
    ACCT_TYPE_RECEIVABLE,
    ACCT_TYPE_STOCK,
    gncTaxTableEntrySetAccount,
)

from infrastructure.gnucash.kvp import (
    KNOWN_ACCOUNT_METADATA_KEYS,
    KNOWN_BILL_METADATA_KEYS,
    KNOWN_CUSTOMER_METADATA_KEYS,
    KNOWN_INVOICE_METADATA_KEYS,
    KNOWN_SPLIT_METADATA_KEYS,
    KNOWN_TX_METADATA_KEYS,
    KNOWN_VENDOR_METADATA_KEYS,
    get_custom_metadata,
    set_custom_metadata,
)
from infrastructure.gnucash.utils import find_account, get_account_full_name, string_to_gnc_numeric
from services.plaintext_parser import DirectiveType, PlaintextDirective


def string_to_gnc_numeric_quantity(s):
    from decimal import Decimal

    from gnucash import GncNumeric
    s = str(s)
    if '/' in s:
        return GncNumeric(s)
    else:
        # Assuming a precision of 1,000,000 for quantities and prices
        num = int(Decimal(s) * 1000000)
        den = 1000000
        return GncNumeric(num, den)


_FALSY_STRINGS = {'false', '0', 'no'}


def _find_transaction_by_guid(book, guid: str):
    """Return the Transaction matching guid, or None."""
    from gnucash import Query, Transaction
    q = Query()
    q.search_for('Trans')
    q.set_book(book)
    txns = list(q.run())
    q.destroy()
    for r in txns:
        tx = Transaction(instance=r)
        if tx.GetGUID().to_string() == guid:
            return tx
    return None


def _retarget_counter_split_to_lot(lib, existing_tx, bank_acct_name: str,
                                   ar_ap_account, lot) -> bool:
    """
    Modify existing_tx in-place: find the split whose account is NOT the
    bank account (the "counter-split"), retarget it to ar_ap_account, and
    link it to the invoice/bill lot.

    This closes the lot without calling ApplyPayment(), preserving all
    original transaction metadata (notes, description, split memos, KVP).

    xaccSplitSetAccount has a SWIG const-type mismatch — ctypes is required.
    See docs/DEBUGGING_GNUCASH_BINDINGS.md.
    """
    from infrastructure.gnucash.engine import safe_ctypes_string
    lib.xaccSplitGetAccount.argtypes = [ctypes.c_void_p]
    lib.xaccSplitGetAccount.restype  = ctypes.c_void_p
    lib.xaccSplitSetAccount.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    lib.xaccSplitSetAccount.restype  = None
    lib.gnc_account_get_parent.argtypes = [ctypes.c_void_p]
    lib.gnc_account_get_parent.restype  = ctypes.c_void_p

    def _acct_name(acct_ptr):
        parts = []
        ptr = acct_ptr
        while ptr:
            name = safe_ctypes_string(lib.xaccAccountGetName, ptr)
            if name:
                parts.append(name)
            parent = lib.gnc_account_get_parent(ptr)
            if not parent:
                break
            if not lib.gnc_account_get_parent(parent):
                break
            ptr = parent
        parts.reverse()
        return ':'.join(parts)

    import gnucash.gnucash_core_c as _gc
    existing_tx.BeginEdit()
    for raw_sp in existing_tx.GetSplitList():
        sp_ptr = int(raw_sp.instance)
        acct_ptr = lib.xaccSplitGetAccount(sp_ptr)
        if not acct_ptr:
            continue
        if _acct_name(acct_ptr) != bank_acct_name:
            # This is the counter-split — retarget to AR/AP and close the lot
            lib.xaccSplitSetAccount(sp_ptr, int(ar_ap_account.instance))
            _gc.xaccSplitSetLot(raw_sp.instance, lot.instance)
            existing_tx.CommitEdit()
            return True
    existing_tx.CommitEdit()
    return False


def _is_falsy(val: str) -> bool:
    """Return True if val is a recognised falsy string (case-insensitive)."""
    return val.strip().lower() in _FALSY_STRINGS


ACCT_TYPE_MAP = {
    "Asset": ACCT_TYPE_ASSET,
    "Bank": ACCT_TYPE_BANK,
    "Expense": ACCT_TYPE_EXPENSE,
    "Income": ACCT_TYPE_INCOME,
    "Equity": ACCT_TYPE_EQUITY,
    "Credit Card": ACCT_TYPE_CREDIT,
    "Liability": ACCT_TYPE_LIABILITY,
    "Mutual Fund": ACCT_TYPE_MUTUAL,
    "Accounts Payable": ACCT_TYPE_PAYABLE,
    "A/Payable": ACCT_TYPE_PAYABLE,          # GnuCash internal short form
    "Accounts Receivable": ACCT_TYPE_RECEIVABLE,
    "A/Receivable": ACCT_TYPE_RECEIVABLE,    # GnuCash internal short form
    "Stock": ACCT_TYPE_STOCK,
    "Cash": ACCT_TYPE_CASH,
}


def create_tax_table_entry(book, account, amount_percent):
    from gnucash.gnucash_core_c import (
        GNC_AMT_TYPE_PERCENT,
        gncTaxTableEntryCreate,
        gncTaxTableEntrySetAmount,
        gncTaxTableEntrySetType,
    )
    raw = gncTaxTableEntryCreate()
    gncTaxTableEntrySetType(raw, GNC_AMT_TYPE_PERCENT)
    amount = GncNumeric(round(amount_percent * 100000), 100000)
    gncTaxTableEntrySetAmount(raw, amount.instance)
    gncTaxTableEntrySetAccount(raw, account.instance)
    return TaxTableEntry(instance=raw)


class GnuCashImporter:
    """Service for importing plaintext directives to GnuCash"""



    @staticmethod
    def create_commodity(directive: PlaintextDirective, book: Book):
        """
        Create commodity from directive.

        Args:
            directive: PlaintextDirective of type CREATE_COMMODITY
            book: GnuCash book
        """
        if directive.type != DirectiveType.CREATE_COMMODITY:
            raise ValueError(f"Expected CREATE_COMMODITY but got {directive.type}")

        mnemonic = directive.metadata['mnemonic']
        fullname = directive.metadata['fullname']
        namespace = directive.metadata['namespace']
        fraction = int(directive.metadata['fraction'])

        commodity_table = book.get_table()
        commodity = commodity_table.lookup(namespace, mnemonic)
        if commodity is None:
            commodity = GncCommodity(book, fullname, namespace, mnemonic, f'{namespace}.{mnemonic}', fraction)
            commodity_table.insert(commodity)
            logging.debug(f"Created commodity {namespace}.{mnemonic}")
        else:
            logging.debug(f"Commodity {namespace}.{mnemonic} already exists")

    @staticmethod
    def create_account(directive: PlaintextDirective, book: Book):
        """
        Create account from directive.

        Args:
            directive: PlaintextDirective of type OPEN_ACCOUNT
            book: GnuCash book
        """
        if directive.type != DirectiveType.OPEN_ACCOUNT:
            raise ValueError(f"Expected OPEN_ACCOUNT but got {directive.type}")

        root_account = book.get_root_account()
        account = Account(book)
        account_fullname = directive.props['account']
        account_type_str = directive.metadata['type']
        account_names = account_fullname.split(':')
        account_name = account_names[-1]
        parent_account_names = account_names[0:-1]

        commodity_table = book.get_table()

        placeholder = directive.metadata.get('placeholder', False)
        code = directive.metadata.get('code', "")
        description = directive.metadata.get('description', "")
        tax_related = directive.metadata.get('tax_related', False)
        namespace = directive.metadata['commodity.namespace']
        mnemonic = directive.metadata['commodity.mnemonic']

        commodity = commodity_table.lookup(namespace, mnemonic)
        if commodity is None:
            raise Exception(f'Cannot find commodity ({namespace}, {mnemonic}) '
                          f'when trying to create account {account_fullname}')
        account.SetCommodity(commodity)

        parent = root_account
        for name in parent_account_names:
            parent = parent.lookup_by_name(name)
            if parent is None:
                raise Exception(f'Cannot find parent account {name} of {account_fullname}')

        # Idempotency check: skip if an account with this name already exists
        # under the same parent.  create_account may be called twice for the
        # same file (once from import_cmd pre-pass, once from ImportTransactionsUseCase).
        if parent.lookup_by_name(account_name) is not None:
            logging.debug(f"Account {account_fullname} already exists, skipping")
            return

        parent.append_child(account)
        account.SetName(account_name)
        account.SetType(ACCT_TYPE_MAP[account_type_str])
        account.SetPlaceholder(placeholder)
        account.SetCode(code)
        account.SetDescription(description)
        account.SetTaxRelated(tax_related)

        custom_meta = {k: v for k, v in directive.metadata.items()
                       if k not in KNOWN_ACCOUNT_METADATA_KEYS and v is not None}
        if custom_meta:
            set_custom_metadata(account, custom_meta)

        if 'commodity_scu' in directive.metadata:
            commodity_scu = directive.metadata['commodity_scu']
            account.SetCommoditySCU(commodity_scu)

        logging.debug(f"Created account {account_fullname}")

    @staticmethod
    def create_transaction(directive: PlaintextDirective, book: Book) -> 'Transaction':
        """
        Create transaction from directive.

        Args:
            directive: PlaintextDirective of type TRANSACTION
            book: GnuCash book

        Returns:
            The newly created GnuCash Transaction object (after CommitEdit).
            Raises on any error (e.g. missing account) — never returns None.
        """
        if directive.type != DirectiveType.TRANSACTION:
            raise ValueError(f"Expected TRANSACTION but got {directive.type}")

        root_account = book.get_root_account()
        transaction = Transaction(book)
        transaction.BeginEdit()

        commodity_table = book.get_table()

        # Get transaction currency
        namespace = directive.metadata.get('currency.namespace', 'CURRENCY')
        if 'currency.mnemonic' in directive.metadata:
            mnemonic = directive.metadata['currency.mnemonic']
            commodity = commodity_table.lookup(namespace, mnemonic)
        else:
            # Get currency from first split account
            split_directive: PlaintextDirective = directive.children[0]
            split_account_name = split_directive.props['account']
            split_account = find_account(root_account, split_account_name)
            if split_account is None:
                raise Exception(f'Account {split_account_name!r} not found '
                              f'when trying to determine currency for transaction {directive.line}')
            commodity = split_account.GetCommodity()
            mnemonic = commodity.get_mnemonic()

        if commodity is None:
            raise Exception(f'Cannot find commodity ({namespace}, {mnemonic}) '
                          f'when trying to create transaction {directive.line}')
        transaction.SetCurrency(commodity)

        date_str = directive.props['date']
        tx_num = directive.props['tx_num']
        tx_desc = directive.props['tx_desc']

        if tx_num is not None:
            transaction.SetNum(tx_num)
        if tx_desc is not None:
            transaction.SetDescription(tx_desc)

        if 'doc_link' in directive.metadata:
            doc_link = directive.metadata['doc_link']
            # SetAssociation was renamed to SetDocLink in GnuCash 4.x
            try:
                transaction.SetDocLink(doc_link)
            except AttributeError:
                # Fall back to older GnuCash API (< 4.0)
                transaction.SetAssociation(doc_link)

        if 'notes' in directive.metadata:
            notes = directive.metadata['notes']
            transaction.SetNotes(notes)

        transaction.SetDateEnteredSecs(datetime.now())
        date = datetime.strptime(date_str, '%Y-%m-%d')
        transaction.SetDatePostedSecsNormalized(date)

        # Create splits
        for child in directive.children:
            split_directive: PlaintextDirective = child
            split_account_str = split_directive.props['account']
            split_account = find_account(root_account, split_account_str)

            if split_account is None:
                raise Exception(f'Account {split_account_str!r} not found '
                              f'when trying to create transaction split {directive.line}')

            split_account_currency = split_account.GetCommodity()

            split_amount_str = split_directive.props['amount']
            amount = string_to_gnc_numeric(split_amount_str, split_account_currency)

            split = Split(book)
            split.SetParent(transaction)
            split.SetAccount(split_account)
            split.SetAmount(amount)

            if 'share_price' in split_directive.metadata:
                share_price = string_to_gnc_numeric(split_directive.metadata['share_price'], commodity)
                split.SetSharePrice(share_price)

            if 'value' in split_directive.metadata:
                value_str = split_directive.metadata['value']
                value = string_to_gnc_numeric(value_str, commodity)
                split.SetValue(value)
            else:
                split.SetValue(amount)

            if 'action' in split_directive.metadata:
                action = split_directive.metadata['action']
                if action is not None:
                    split.SetAction(action)

            if 'memo' in split_directive.metadata:
                memo = split_directive.metadata['memo']
                if memo is not None:
                    split.SetMemo(memo)

            # Store any non-standard split metadata as KVP slots
            custom_split_meta = {
                k: v for k, v in split_directive.metadata.items()
                if k not in KNOWN_SPLIT_METADATA_KEYS and v is not None
            }
            if custom_split_meta:
                set_custom_metadata(split, custom_split_meta)

        # Store any non-standard metadata as KVP slots
        custom_tx_meta = {
            k: v for k, v in directive.metadata.items()
            if k not in KNOWN_TX_METADATA_KEYS and v is not None
        }
        if custom_tx_meta:
            set_custom_metadata(transaction, custom_tx_meta)

        transaction.CommitEdit()
        logging.debug(f"Created transaction on {date_str}")
        return transaction

    @staticmethod
    def update_transaction(existing_tx, directive: PlaintextDirective, book: Book) -> None:
        """
        Update an existing GnuCash transaction in-place from a plaintext directive.

        The transaction's GUID is preserved — the transaction object is modified,
        not replaced. This makes the export→edit-plaintext→re-import cycle stable
        across multiple runs: the same GUID is always present, so subsequent imports
        with UPDATE strategy will keep updating the same transaction instead of
        creating duplicates.

        All scalar fields (description, date, num, doc_link, notes, currency) and
        splits are updated to match the directive. Split matching is by account
        full-name. Splits for accounts absent from the directive are removed; splits
        for new accounts are created.

        Note: When two splits in the directive share the same account (e.g. meal + tip
        both on Expenses:Dining), all of them are applied positionally — each directive
        entry is matched to the corresponding existing split at the same index for that
        account. Extra existing splits are removed; extra desired splits are created.

        Args:
            existing_tx: GnuCash Transaction object to update
            directive:   PlaintextDirective of type TRANSACTION containing new values
            book:        GnuCash Book (required to create new Split objects)

        Raises:
            ValueError: If a split account named in the directive cannot be found
        """
        if directive.type != DirectiveType.TRANSACTION:
            raise ValueError(f"Expected TRANSACTION but got {directive.type}")

        root_account = book.get_root_account()
        commodity_table = book.get_table()

        existing_tx.BeginEdit()
        try:
            # Update transaction-level scalar fields
            date_str = directive.props['date']
            date = datetime.strptime(date_str, '%Y-%m-%d')
            existing_tx.SetDatePostedSecsNormalized(date)

            tx_num = directive.props.get('tx_num')
            tx_desc = directive.props.get('tx_desc')
            if tx_num is not None:
                existing_tx.SetNum(tx_num)
            if tx_desc is not None:
                existing_tx.SetDescription(tx_desc)

            if 'doc_link' in directive.metadata:
                try:
                    existing_tx.SetDocLink(directive.metadata['doc_link'])
                except AttributeError:
                    existing_tx.SetAssociation(directive.metadata['doc_link'])

            if 'notes' in directive.metadata:
                existing_tx.SetNotes(directive.metadata['notes'])

            # Update currency if specified
            namespace = directive.metadata.get('currency.namespace', 'CURRENCY')
            if 'currency.mnemonic' in directive.metadata:
                mnemonic = directive.metadata['currency.mnemonic']
                commodity = commodity_table.lookup(namespace, mnemonic)
                if commodity is not None:
                    existing_tx.SetCurrency(commodity)

            # Update transaction-level custom metadata (merge: new values win)
            custom_tx_meta = {
                k: v for k, v in directive.metadata.items()
                if k not in KNOWN_TX_METADATA_KEYS and v is not None
            }
            if custom_tx_meta:
                existing_custom = get_custom_metadata(existing_tx)
                existing_custom.update(custom_tx_meta)
                set_custom_metadata(existing_tx, existing_custom)

            tx_currency = existing_tx.GetCurrency()

            # Build account-name → [splits] map for existing splits.
            # Using lists preserves multiple splits that share the same account
            # (e.g. meal + tip both posted to Expenses:Dining).
            existing_splits_by_account: dict[str, list] = {}
            for split in existing_tx.GetSplitList():
                acct_name = get_account_full_name(split.GetAccount())
                existing_splits_by_account.setdefault(acct_name, []).append(split)

            # Build account-name → [directives] map for desired splits.
            desired_by_account: dict[str, list] = {}
            for child in directive.children:
                desired_by_account.setdefault(child.props['account'], []).append(child)

            # Validate all desired accounts exist before making any changes
            for acct_name in desired_by_account:
                if find_account(root_account, acct_name) is None:
                    raise ValueError(f"Account not found: {acct_name}")

            # Remove splits for accounts no longer in the directive
            for acct_name, splits in list(existing_splits_by_account.items()):
                if acct_name not in desired_by_account:
                    for split in splits:
                        split.Destroy()

            # Update existing splits or create new ones, matched positionally
            # within each account group.
            for acct_name, split_directives in desired_by_account.items():
                split_account = find_account(root_account, acct_name)
                split_account_currency = split_account.GetCommodity()
                existing_splits = existing_splits_by_account.get(acct_name, [])

                # Destroy excess existing splits when directive has fewer
                for surplus in existing_splits[len(split_directives):]:
                    surplus.Destroy()

                for i, split_directive in enumerate(split_directives):
                    amount = string_to_gnc_numeric(split_directive.props['amount'], split_account_currency)

                    if 'value' in split_directive.metadata:
                        value = string_to_gnc_numeric(split_directive.metadata['value'], tx_currency)
                    else:
                        value = amount

                    if i < len(existing_splits):
                        split = existing_splits[i]
                    else:
                        split = Split(book)
                        split.SetParent(existing_tx)
                        split.SetAccount(split_account)

                    split.SetAmount(amount)
                    split.SetValue(value)

                    if 'share_price' in split_directive.metadata:
                        share_price = string_to_gnc_numeric(split_directive.metadata['share_price'], tx_currency)
                        split.SetSharePrice(share_price)

                    if 'action' in split_directive.metadata:
                        action = split_directive.metadata['action']
                        if action is not None:
                            split.SetAction(action)

                    if 'memo' in split_directive.metadata:
                        memo = split_directive.metadata['memo']
                        if memo is not None:
                            split.SetMemo(memo)

                    # Update split-level custom metadata (merge: new values win)
                    custom_split_meta = {
                        k: v for k, v in split_directive.metadata.items()
                        if k not in KNOWN_SPLIT_METADATA_KEYS and v is not None
                    }
                    if custom_split_meta:
                        existing_split_custom = get_custom_metadata(split)
                        existing_split_custom.update(custom_split_meta)
                        set_custom_metadata(split, existing_split_custom)

            existing_tx.CommitEdit()
            logging.debug(f"Updated transaction on {date_str}")

        except Exception:
            existing_tx.RollbackEdit()
            raise

    @staticmethod
    def import_customer(directive: PlaintextDirective, book: Book):
        if directive.type != DirectiveType.CUSTOMER:
            raise ValueError(f"Expected CUSTOMER but got {directive.type}")

        customer = Customer(book, directive.props['id'], book.get_table().lookup("CURRENCY", directive.metadata['currency']))
        customer.BeginEdit()
        customer.SetName(directive.metadata['name'])

        addr = customer.GetAddr()
        addr.SetAddr1(directive.metadata.get('addr1', ''))
        addr.SetAddr2(directive.metadata.get('addr2', ''))
        addr.SetAddr3(directive.metadata.get('addr3', ''))
        addr.SetAddr4(directive.metadata.get('addr4', ''))
        addr.SetEmail(directive.metadata.get('email', ''))

        customer.CommitEdit()
        if _is_falsy(directive.metadata.get('active', 'true')):
            customer.SetActive(False)
        custom_meta = {k: v for k, v in directive.metadata.items()
                       if k not in KNOWN_CUSTOMER_METADATA_KEYS and v is not None}
        if custom_meta:
            set_custom_metadata(customer, custom_meta)
        logging.debug(f"Created customer {directive.props['id']}")

    @staticmethod
    def import_vendor(directive: PlaintextDirective, book: Book):
        if directive.type != DirectiveType.VENDOR:
            raise ValueError(f"Expected VENDOR but got {directive.type}")

        vendor = Vendor(book, directive.props['id'], book.get_table().lookup("CURRENCY", directive.metadata['currency']))
        vendor.BeginEdit()
        vendor.SetName(directive.metadata['name'])
        vendor.CommitEdit()
        if _is_falsy(directive.metadata.get('active', 'true')):
            vendor.SetActive(False)
        custom_meta = {k: v for k, v in directive.metadata.items()
                       if k not in KNOWN_VENDOR_METADATA_KEYS and v is not None}
        if custom_meta:
            set_custom_metadata(vendor, custom_meta)
        logging.debug(f"Created vendor {directive.props['id']}")

    @staticmethod
    def import_taxtable(directive: PlaintextDirective, book: Book):
        if directive.type != DirectiveType.TAXTABLE:
            raise ValueError(f"Expected TAXTABLE but got {directive.type}")

        first_entry_directive = None
        for d in directive.children:
            if d.type == DirectiveType.TAXTABLE_ENTRY:
                first_entry_directive = d
                break

        if not first_entry_directive:
            # A taxtable must have at least one entry
            return

        acct_name = first_entry_directive.metadata['account']
        account = find_account(book.get_root_account(), acct_name)
        if account is None:
            raise Exception(f'Account {acct_name!r} not found when creating tax table {directive.props["name"]}')
        rate_str = first_entry_directive.metadata['rate']
        rate = float(rate_str.replace("%", ""))
        first_entry = create_tax_table_entry(book, account, rate)

        taxtable = TaxTable(book, directive.props['name'], first_entry)

        for entry_directive in directive.children[1:]:
            if entry_directive.type == DirectiveType.TAXTABLE_ENTRY:
                acct_name = entry_directive.metadata['account']
                account = find_account(book.get_root_account(), acct_name)
                if account is None:
                    raise Exception(f'Account {acct_name!r} not found when creating tax table {directive.props["name"]}')
                rate_str = entry_directive.metadata['rate']
                rate = float(rate_str.replace("%", ""))
                entry = create_tax_table_entry(book, account, rate)
                taxtable.AddEntry(entry)

        logging.debug(f"Created taxtable {directive.props['name']}")

    @staticmethod
    def import_invoice(directive: PlaintextDirective, book: Book):
        if directive.type != DirectiveType.INVOICE:
            raise ValueError(f"Expected INVOICE but got {directive.type}")

        inv_id = directive.props['id']

        # Idempotency: skip if this invoice already exists in the book.
        # Re-importing the same file would otherwise create a duplicate invoice
        # and a duplicate payment transaction for each payment: block.
        if book.InvoiceLookupByID(inv_id) is not None:
            logging.debug(f"Invoice {inv_id} already exists, skipping")
            return

        # Validate: posted: none and a real posted: block are contradictory
        has_posted_none = directive.metadata.get('posted') == 'none'
        posted_children = [c for c in directive.children if c.type == DirectiveType.POSTED]
        if has_posted_none and posted_children:
            raise ValueError(f'Invoice {inv_id}: contradictory "posted: none" and posted: block')
        if len(posted_children) > 1:
            raise ValueError(f'Invoice {inv_id}: multiple posted: blocks are not allowed')

        # Validate: payment: none and a real payment: block are contradictory;
        # also, an unposted invoice cannot have payments
        has_payment_none = directive.metadata.get('payment') == 'none'
        payment_children = [c for c in directive.children if c.type == DirectiveType.PAYMENT]
        if has_payment_none and payment_children:
            raise ValueError(f'Invoice {inv_id}: contradictory "payment: none" and payment: block')
        if has_posted_none and payment_children:
            raise ValueError(f'Invoice {inv_id}: cannot have payment: blocks on an unposted invoice (posted: none)')

        invoice = Invoice(book, inv_id, book.get_table().lookup("CURRENCY", directive.metadata['currency']), book.CustomerLookupByID(directive.metadata['customer_id']))
        invoice.BeginEdit()
        invoice.SetDateOpened(datetime.strptime(directive.metadata['date_opened'], "%Y-%m-%d"))

        if 'billing_id' in directive.metadata:
            invoice.SetBillingID(directive.metadata['billing_id'])
        if 'notes' in directive.metadata:
            invoice.SetNotes(directive.metadata['notes'])

        for entry_directive in directive.children:
            if entry_directive.type == DirectiveType.INVOICE_ENTRY:
                entry = Entry(book)
                entry.BeginEdit()
                entry.SetDate(datetime.strptime(entry_directive.metadata['date'], "%Y-%m-%d"))
                entry.SetDescription(entry_directive.metadata['description'])
                entry.SetAction(entry_directive.metadata['action'])
                inv_acct_name = entry_directive.metadata['account']
                inv_acct = find_account(book.get_root_account(), inv_acct_name)
                if inv_acct is None:
                    raise Exception(f'Account {inv_acct_name!r} not found when creating invoice entry')
                entry.SetInvAccount(inv_acct)
                entry.SetQuantity(string_to_gnc_numeric_quantity(entry_directive.metadata['quantity']))
                entry.SetInvPrice(string_to_gnc_numeric_quantity(entry_directive.metadata['price']))
                entry.SetInvTaxable(entry_directive.metadata['taxable'] == 'true')
                entry.SetInvTaxIncluded(entry_directive.metadata['tax_included'] == 'true')
                if 'tax_table' in entry_directive.metadata:
                    tt_ptr = gc.gncTaxTableLookupByName(book.instance, entry_directive.metadata['tax_table'])
                    if tt_ptr:
                        entry.SetInvTaxTable(TaxTable(instance=tt_ptr))
                invoice.AddEntry(entry)
                entry.CommitEdit()
            elif entry_directive.type == DirectiveType.POSTED:
                ar_acct_name = entry_directive.metadata['ar_account']
                ar_account = find_account(book.get_root_account(), ar_acct_name)
                if ar_account is None:
                    raise Exception(f'AR account {ar_acct_name!r} not found when posting invoice {directive.props["id"]}')
                post_date = datetime.strptime(entry_directive.metadata['date'], "%Y-%m-%d")
                due_date = datetime.strptime(entry_directive.metadata['due'], "%Y-%m-%d")
                memo = entry_directive.metadata['memo']
                accumulate = entry_directive.metadata['accumulate'] == 'true'
                invoice.PostToAccount(ar_account, post_date, due_date, memo, accumulate, False)
                # Override the transaction description GnuCash set automatically,
                # so the roundtrip preserves the memo field exactly.
                posting_txn = invoice.GetPostedTxn()
                if posting_txn:
                    posting_txn.BeginEdit()
                    posting_txn.SetDescription(memo)
                    posting_txn.SetNotes("business_generated: true")
                    posting_txn.CommitEdit()
            elif entry_directive.type == DirectiveType.PAYMENT:
                bank_acct_name = entry_directive.metadata['bank_account']
                bank_account = find_account(book.get_root_account(), bank_acct_name)
                if bank_account is None:
                    raise Exception(f'Bank account {bank_acct_name!r} not found when applying invoice payment')

                txn_guid = entry_directive.metadata.get('txn_guid', '').strip()
                if txn_guid:
                    # Retarget approach: the bank transaction already exists.
                    # Find the counter-split (non-bank side), retarget it to AR,
                    # and link it to the invoice lot. No new transaction is created,
                    # all original bank metadata (notes, memos, KVP) is preserved.
                    # ApplyPayment() is NOT called — the lot closes automatically
                    # when the AR split sum reaches zero.
                    existing_tx = _find_transaction_by_guid(book, txn_guid)
                    if existing_tx is None:
                        raise Exception(f'txn_guid {txn_guid!r} not found in book')
                    ar_account = invoice.GetPostedAcc()
                    lot = invoice.GetPostedLot()
                    if lot is None:
                        raise Exception(f'Invoice {inv_id} has no posted lot — must be posted before payment')
                    from infrastructure.gnucash.engine import load_gnc_engine
                    if not _retarget_counter_split_to_lot(
                            load_gnc_engine(), existing_tx, bank_acct_name, ar_account, lot):
                        raise Exception(
                            f'Could not find counter-split in tx {txn_guid!r} — '
                            f'expected a non-{bank_acct_name!r} split'
                        )
                else:
                    # Normal path: no pre-existing bank tx — ApplyPayment creates one.
                    pay_date = datetime.strptime(entry_directive.metadata['date'], "%Y-%m-%d")
                    amount = string_to_gnc_numeric_quantity(entry_directive.metadata['amount'])
                    memo = entry_directive.metadata['memo']
                    num = entry_directive.metadata.get('num', '')
                    # Pass None for txn: GnuCash creates the payment transaction
                    # internally. Passing a manually-allocated Transaction causes
                    # a segfault on GnuCash 3.8 (ubuntu20) because the transaction
                    # is not properly initialised before ApplyPayment uses it.
                    invoice.ApplyPayment(None, bank_account, amount, GncNumeric(1, 1), pay_date, memo, num)

        invoice.CommitEdit()
        custom_meta = {k: v for k, v in directive.metadata.items()
                       if k not in KNOWN_INVOICE_METADATA_KEYS and v is not None}
        if custom_meta:
            set_custom_metadata(invoice, custom_meta)
        logging.debug(f"Created invoice {directive.props['id']}")

    @staticmethod
    def import_bill(directive: PlaintextDirective, book: Book):
        if directive.type != DirectiveType.BILL:
            raise ValueError(f"Expected BILL but got {directive.type}")

        bill_id = directive.props['id']

        # Idempotency: skip if this bill already exists in the book.
        if book.InvoiceLookupByID(bill_id) is not None:
            logging.debug(f"Bill {bill_id} already exists, skipping")
            return

        # Validate: posted: none and a real posted: block are contradictory
        has_posted_none = directive.metadata.get('posted') == 'none'
        posted_children = [c for c in directive.children if c.type == DirectiveType.POSTED]
        if has_posted_none and posted_children:
            raise ValueError(f'Bill {bill_id}: contradictory "posted: none" and posted: block')
        if len(posted_children) > 1:
            raise ValueError(f'Bill {bill_id}: multiple posted: blocks are not allowed')

        # Validate: payment: none and a real payment: block are contradictory;
        # also, an unposted bill cannot have payments
        has_payment_none = directive.metadata.get('payment') == 'none'
        payment_children = [c for c in directive.children if c.type == DirectiveType.PAYMENT]
        if has_payment_none and payment_children:
            raise ValueError(f'Bill {bill_id}: contradictory "payment: none" and payment: block')
        if has_posted_none and payment_children:
            raise ValueError(f'Bill {bill_id}: cannot have payment: blocks on an unposted bill (posted: none)')

        # Bills are Invoice objects whose owner is a Vendor (no separate Bill class)
        bill = Invoice(book, bill_id, book.get_table().lookup("CURRENCY", directive.metadata['currency']), book.VendorLookupByID(directive.metadata['vendor_id']))
        bill.BeginEdit()
        bill.SetDateOpened(datetime.strptime(directive.metadata['date_opened'], "%Y-%m-%d"))

        for entry_directive in directive.children:
            if entry_directive.type == DirectiveType.BILL_ENTRY:
                entry = Entry(book)
                entry.BeginEdit()
                entry.SetDate(datetime.strptime(entry_directive.metadata['date'], "%Y-%m-%d"))
                entry.SetDescription(entry_directive.metadata['description'])
                bill_acct_name = entry_directive.metadata['account']
                bill_acct = find_account(book.get_root_account(), bill_acct_name)
                if bill_acct is None:
                    raise Exception(f'Account {bill_acct_name!r} not found when creating bill entry')
                entry.SetBillAccount(bill_acct)
                entry.SetQuantity(string_to_gnc_numeric_quantity(entry_directive.metadata['quantity']))
                entry.SetBillPrice(string_to_gnc_numeric_quantity(entry_directive.metadata['price']))
                entry.SetBillTaxable(entry_directive.metadata['taxable'] == 'true')
                if 'tax_table' in entry_directive.metadata:
                    tt_ptr = gc.gncTaxTableLookupByName(book.instance, entry_directive.metadata['tax_table'])
                    if tt_ptr:
                        entry.SetBillTaxTable(TaxTable(instance=tt_ptr))
                bill.AddEntry(entry)
                entry.CommitEdit()
            elif entry_directive.type == DirectiveType.POSTED:
                ap_acct_name = entry_directive.metadata['ap_account']
                ap_account = find_account(book.get_root_account(), ap_acct_name)
                if ap_account is None:
                    raise Exception(f'AP account {ap_acct_name!r} not found when posting bill {directive.props["id"]}')
                post_date = datetime.strptime(entry_directive.metadata['date'], "%Y-%m-%d")
                due_date = datetime.strptime(entry_directive.metadata['due'], "%Y-%m-%d")
                memo = entry_directive.metadata['memo']
                accumulate = entry_directive.metadata['accumulate'] == 'true'
                bill.PostToAccount(ap_account, post_date, due_date, memo, accumulate, False)
                # Override the transaction description GnuCash set automatically,
                # so the roundtrip preserves the memo field exactly.
                posting_txn = bill.GetPostedTxn()
                if posting_txn:
                    posting_txn.BeginEdit()
                    posting_txn.SetDescription(memo)
                    posting_txn.SetNotes("business_generated: true")
                    posting_txn.CommitEdit()
            elif entry_directive.type == DirectiveType.PAYMENT:
                bank_acct_name = entry_directive.metadata['bank_account']
                bank_account = find_account(book.get_root_account(), bank_acct_name)
                if bank_account is None:
                    raise Exception(f'Bank account {bank_acct_name!r} not found when applying bill payment')

                txn_guid = entry_directive.metadata.get('txn_guid', '').strip()
                if txn_guid:
                    # Retarget approach — same as invoice, but targeting AP.
                    existing_tx = _find_transaction_by_guid(book, txn_guid)
                    if existing_tx is None:
                        raise Exception(f'txn_guid {txn_guid!r} not found in book')
                    ap_account = bill.GetPostedAcc()
                    lot = bill.GetPostedLot()
                    if lot is None:
                        raise Exception(f'Bill {bill_id} has no posted lot — must be posted before payment')
                    from infrastructure.gnucash.engine import load_gnc_engine
                    if not _retarget_counter_split_to_lot(
                            load_gnc_engine(), existing_tx, bank_acct_name, ap_account, lot):
                        raise Exception(
                            f'Could not find counter-split in tx {txn_guid!r} — '
                            f'expected a non-{bank_acct_name!r} split'
                        )
                else:
                    # Normal path: ApplyPayment creates the bank+AP transaction.
                    # AP and AR have opposite sign conventions, so bill payments
                    # require a negated amount:
                    #
                    #   Bill posting:    CR AP −N  →  lot starts at −N
                    #   Bill payment:    DR AP +N  →  ApplyPayment(+N) creates AP = −N ✗
                    #                                 (same sign as posting → new lot)
                    #                   ApplyPayment(−N) creates AP = +N ✓
                    #                                 (opposite sign → closes existing lot)
                    #
                    # Passing a positive amount puts the payment split in a brand-new
                    # lot instead of the bill's posted lot.
                    pay_date = datetime.strptime(entry_directive.metadata['date'], "%Y-%m-%d")
                    amount_str = entry_directive.metadata['amount']
                    memo = entry_directive.metadata['memo']
                    num = entry_directive.metadata.get('num', '')
                    neg_amount = string_to_gnc_numeric_quantity(f'-{amount_str}')
                    bill.ApplyPayment(None, bank_account, neg_amount, GncNumeric(1, 1), pay_date, memo, num)

        bill.CommitEdit()
        custom_meta = {k: v for k, v in directive.metadata.items()
                       if k not in KNOWN_BILL_METADATA_KEYS and v is not None}
        if custom_meta:
            set_custom_metadata(bill, custom_meta)
        logging.debug(f"Created bill {directive.props['id']}")

    def import_business_objects(self, directives: List[PlaintextDirective], book: Book):
        # Import customers and vendors first
        for directive in directives:
            if directive.type == DirectiveType.CUSTOMER:
                cid = directive.props.get('id', '?')
                try:
                    self.import_customer(directive, book)
                except Exception as e:
                    raise ValueError(f'customer "{cid}": {e}') from e
            elif directive.type == DirectiveType.VENDOR:
                vid = directive.props.get('id', '?')
                try:
                    self.import_vendor(directive, book)
                except Exception as e:
                    raise ValueError(f'vendor "{vid}": {e}') from e

        # Then tax tables
        for directive in directives:
            if directive.type == DirectiveType.TAXTABLE:
                tname = directive.props.get('name', '?')
                try:
                    self.import_taxtable(directive, book)
                except Exception as e:
                    raise ValueError(f'taxtable "{tname}": {e}') from e

        # Finally, invoices and bills
        for directive in directives:
            if directive.type == DirectiveType.INVOICE:
                iid = directive.props.get('id', '?')
                try:
                    self.import_invoice(directive, book)
                except Exception as e:
                    raise ValueError(f'invoice "{iid}": {e}') from e
            elif directive.type == DirectiveType.BILL:
                bid = directive.props.get('id', '?')
                try:
                    self.import_bill(directive, book)
                except Exception as e:
                    raise ValueError(f'bill "{bid}": {e}') from e
