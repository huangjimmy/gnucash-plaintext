"""
Service for importing plaintext directives to GnuCash.

Converts PlaintextDirective objects from the parser into GnuCash objects
(commodities, accounts, transactions) with all metadata preserved.
"""

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
    KNOWN_SPLIT_METADATA_KEYS,
    KNOWN_TX_METADATA_KEYS,
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
    "Accounts Receivable": ACCT_TYPE_RECEIVABLE,
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

        Note: When two splits in the directive share the same account (rare but valid),
        the last directive entry for that account wins — consistent with create_transaction.

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

            # Build account-name → split maps for existing and desired splits
            existing_splits_by_account = {}
            for split in existing_tx.GetSplitList():
                acct_name = get_account_full_name(split.GetAccount())
                existing_splits_by_account[acct_name] = split

            desired_by_account = {}
            for child in directive.children:
                desired_by_account[child.props['account']] = child

            # Validate all desired accounts exist before making any changes
            for acct_name in desired_by_account:
                if find_account(root_account, acct_name) is None:
                    raise ValueError(f"Account not found: {acct_name}")

            # Remove splits for accounts no longer in the directive
            for acct_name, split in list(existing_splits_by_account.items()):
                if acct_name not in desired_by_account:
                    split.Destroy()

            # Update existing splits or create new ones
            for acct_name, split_directive in desired_by_account.items():
                split_account = find_account(root_account, acct_name)
                split_account_currency = split_account.GetCommodity()
                amount = string_to_gnc_numeric(split_directive.props['amount'], split_account_currency)

                if 'value' in split_directive.metadata:
                    value = string_to_gnc_numeric(split_directive.metadata['value'], tx_currency)
                else:
                    value = amount

                if acct_name in existing_splits_by_account:
                    split = existing_splits_by_account[acct_name]
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
        logging.debug(f"Created customer {directive.props['id']}")

    @staticmethod
    def import_vendor(directive: PlaintextDirective, book: Book):
        if directive.type != DirectiveType.VENDOR:
            raise ValueError(f"Expected VENDOR but got {directive.type}")

        vendor = Vendor(book, directive.props['id'], book.get_table().lookup("CURRENCY", directive.metadata['currency']))
        vendor.BeginEdit()
        vendor.SetName(directive.metadata['name'])
        vendor.CommitEdit()
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
        logging.debug(f"Created invoice {directive.props['id']}")

    @staticmethod
    def import_bill(directive: PlaintextDirective, book: Book):
        if directive.type != DirectiveType.BILL:
            raise ValueError(f"Expected BILL but got {directive.type}")

        bill_id = directive.props['id']

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
                pay_date = datetime.strptime(entry_directive.metadata['date'], "%Y-%m-%d")
                amount_str = entry_directive.metadata['amount']
                memo = entry_directive.metadata['memo']
                num = entry_directive.metadata.get('num', '')
                # AP and AR have opposite sign conventions, so bill payments
                # require a negated amount:
                #
                #   Invoice posting: DR AR +N  →  lot starts at +N
                #   Invoice payment: CR AR −N  →  ApplyPayment(+N) creates AR = −N ✓
                #
                #   Bill posting:    CR AP −N  →  lot starts at −N
                #   Bill payment:    DR AP +N  →  ApplyPayment(+N) creates AP = −N ✗
                #                                 (same sign as posting → new lot)
                #                   ApplyPayment(−N) creates AP = +N ✓
                #                                 (opposite sign → closes existing lot)
                #
                # Passing a positive amount for a bill puts the payment split in a
                # brand-new lot instead of the bill's posted lot, making the exporter
                # unable to find the payment via GetPostedLot().get_split_list().
                neg_amount = string_to_gnc_numeric_quantity(f'-{amount_str}')
                bill.ApplyPayment(None, bank_account, neg_amount, GncNumeric(1, 1), pay_date, memo, num)

        bill.CommitEdit()
        logging.debug(f"Created bill {directive.props['id']}")

    def import_business_objects(self, directives: List[PlaintextDirective], book: Book):
        # Import customers and vendors first
        for directive in directives:
            if directive.type == DirectiveType.CUSTOMER:
                self.import_customer(directive, book)
            elif directive.type == DirectiveType.VENDOR:
                self.import_vendor(directive, book)

        # Then tax tables
        for directive in directives:
            if directive.type == DirectiveType.TAXTABLE:
                self.import_taxtable(directive, book)

        # Finally, invoices and bills
        for directive in directives:
            if directive.type == DirectiveType.INVOICE:
                self.import_invoice(directive, book)
            elif directive.type == DirectiveType.BILL:
                self.import_bill(directive, book)
