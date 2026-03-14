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

from infrastructure.gnucash.utils import find_account, string_to_gnc_numeric
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
    def create_transaction(directive: PlaintextDirective, book: Book):
        """
        Create transaction from directive.

        Args:
            directive: PlaintextDirective of type TRANSACTION
            book: GnuCash book
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
            split_account_currency = split_account.GetCommodity()

            if split_account is None:
                raise Exception(f'Account {split_account_str} not found '
                              f'when trying to create transaction split {directive.line}')

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

        transaction.CommitEdit()
        logging.debug(f"Created transaction on {date_str}")
        return True

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

        account = find_account(book.get_root_account(), first_entry_directive.metadata['account'])
        rate_str = first_entry_directive.metadata['rate']
        rate = float(rate_str.replace("%", ""))
        first_entry = create_tax_table_entry(book, account, rate)

        taxtable = TaxTable(book, directive.props['name'], first_entry)

        for entry_directive in directive.children[1:]:
            if entry_directive.type == DirectiveType.TAXTABLE_ENTRY:
                account = find_account(book.get_root_account(), entry_directive.metadata['account'])
                rate_str = entry_directive.metadata['rate']
                rate = float(rate_str.replace("%", ""))
                entry = create_tax_table_entry(book, account, rate)
                taxtable.AddEntry(entry)

        logging.debug(f"Created taxtable {directive.props['name']}")

    @staticmethod
    def import_invoice(directive: PlaintextDirective, book: Book):
        if directive.type != DirectiveType.INVOICE:
            raise ValueError(f"Expected INVOICE but got {directive.type}")

        invoice = Invoice(book, directive.props['id'], book.get_table().lookup("CURRENCY", directive.metadata['currency']), book.CustomerLookupByID(directive.metadata['customer_id']))
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
                entry.SetInvAccount(find_account(book.get_root_account(), entry_directive.metadata['account']))
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
                ar_account = find_account(book.get_root_account(), entry_directive.metadata['ar_account'])
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
                bank_account = find_account(book.get_root_account(), entry_directive.metadata['bank_account'])
                pay_date = datetime.strptime(entry_directive.metadata['date'], "%Y-%m-%d")
                amount = string_to_gnc_numeric_quantity(entry_directive.metadata['amount'])
                memo = entry_directive.metadata['memo']
                num = entry_directive.metadata.get('num', None)
                new_txn = Transaction(instance=gc.xaccMallocTransaction(book.instance))
                invoice.ApplyPayment(new_txn, bank_account, amount, GncNumeric(1, 1), pay_date, memo, num)

        invoice.CommitEdit()
        logging.debug(f"Created invoice {directive.props['id']}")

    @staticmethod
    def import_bill(directive: PlaintextDirective, book: Book):
        if directive.type != DirectiveType.BILL:
            raise ValueError(f"Expected BILL but got {directive.type}")

        # Bills are Invoice objects whose owner is a Vendor (no separate Bill class)
        bill = Invoice(book, directive.props['id'], book.get_table().lookup("CURRENCY", directive.metadata['currency']), book.VendorLookupByID(directive.metadata['vendor_id']))
        bill.BeginEdit()
        bill.SetDateOpened(datetime.strptime(directive.metadata['date_opened'], "%Y-%m-%d"))

        for entry_directive in directive.children:
            if entry_directive.type == DirectiveType.BILL_ENTRY:
                entry = Entry(book)
                entry.BeginEdit()
                entry.SetDate(datetime.strptime(entry_directive.metadata['date'], "%Y-%m-%d"))
                entry.SetDescription(entry_directive.metadata['description'])
                entry.SetInvAccount(find_account(book.get_root_account(), entry_directive.metadata['account']))
                entry.SetQuantity(string_to_gnc_numeric_quantity(entry_directive.metadata['quantity']))
                entry.SetInvPrice(string_to_gnc_numeric_quantity(entry_directive.metadata['price']))
                entry.SetInvTaxable(entry_directive.metadata['taxable'] == 'true')
                if 'tax_table' in entry_directive.metadata:
                    tt_ptr = gc.gncTaxTableLookupByName(book.instance, entry_directive.metadata['tax_table'])
                    if tt_ptr:
                        entry.SetInvTaxTable(TaxTable(instance=tt_ptr))
                bill.AddEntry(entry)
                entry.CommitEdit()
            elif entry_directive.type == DirectiveType.POSTED:
                ap_account = find_account(book.get_root_account(), entry_directive.metadata['ap_account'])
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
                bank_account = find_account(book.get_root_account(), entry_directive.metadata['bank_account'])
                pay_date = datetime.strptime(entry_directive.metadata['date'], "%Y-%m-%d")
                amount = string_to_gnc_numeric_quantity(entry_directive.metadata['amount'])
                memo = entry_directive.metadata['memo']
                num = entry_directive.metadata.get('num', None)
                new_txn = Transaction(instance=gc.xaccMallocTransaction(book.instance))
                bill.ApplyPayment(new_txn, bank_account, amount, GncNumeric(1, 1), pay_date, memo, num)

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
