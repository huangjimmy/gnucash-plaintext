"""
Service for importing plaintext directives to GnuCash.

Converts PlaintextDirective objects from the parser into GnuCash objects
(commodities, accounts, transactions) with all metadata preserved.
"""

import logging
from datetime import datetime

from gnucash import Account, Book, GncCommodity, Split, Transaction
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
)

from infrastructure.gnucash.utils import find_account, string_to_gnc_numeric
from services.plaintext_parser import DirectiveType, PlaintextDirective

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
        fraction = directive.metadata['fraction']

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
