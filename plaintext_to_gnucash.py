import os.path
from typing import Optional, Dict
import datetime
import os
import sys
from gnucash import Account, Book, Transaction, Split, Session, GnuCashBackendException, GncCommodity
from utils import find_account, string_to_gnc_numeric
from parser.plaintext_parser import PlaintextLedger, PlaintextLedgerParser, DirectiveType

from gnucash.gnucash_core_c import  ACCT_TYPE_ASSET, ACCT_TYPE_BANK, ACCT_TYPE_CASH, \
    ACCT_TYPE_CREDIT, ACCT_TYPE_EQUITY, ACCT_TYPE_EXPENSE, ACCT_TYPE_INCOME, \
    ACCT_TYPE_LIABILITY, ACCT_TYPE_MUTUAL, ACCT_TYPE_PAYABLE, \
    ACCT_TYPE_RECEIVABLE, ACCT_TYPE_STOCK

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


def create_account(ledger: PlaintextLedger, book: Book) -> bool:
    root_account = book.get_root_account()
    account = Account(book)
    account_fullname = ledger.props['account']
    account_type_str = ledger.metadata['type']
    account_names = account_fullname.split(':')
    account_name = account_names[-1]
    parent_account_names = account_names[0:-1]

    commodity_table = book.get_table()

    placeholder = ledger.metadata['placeholder']
    code = ledger.metadata['code']
    description = ledger.metadata['description']
    tax_related = ledger.metadata['tax_related']
    namespace = ledger.metadata['commodity.namespace']
    mnemonic = ledger.metadata['commodity.mnemonic']
    commodity = commodity_table.lookup(namespace, mnemonic)
    if commodity is None:
        raise Exception(f'Cannot find commodity ({namespace, mnemonic}) when trying to create account {account_fullname}')
        pass
    else:
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
    pass


def create_commodity(ledger: PlaintextLedger, book: Book):
    mnemonic = ledger.metadata['mnemonic']
    fullname = ledger.metadata['fullname']
    namespace = ledger.metadata['namespace']
    fraction = ledger.metadata['fraction']

    commodity_table = book.get_table()
    commodity = commodity_table.lookup(namespace, mnemonic)
    if commodity is None:
        commodity = GncCommodity(book, fullname, namespace, mnemonic, f'{namespace}.{mnemonic}', fraction)
        commodity_table.insert(commodity)
    pass


def create_transaction(ledger: PlaintextLedger, book: Book):
    root_account = book.get_root_account()
    transaction = Transaction(book)
    transaction.BeginEdit()

    commodity_table = book.get_table()

    namespace = 'CURRENCY' if 'currency.namespace' not in ledger.metadata else ledger.metadata['currency.namespac']
    if 'currency.mnemonic' in ledger.metadata:
        mnemonic = ledger.metadata['currency.mnemonic']
        commodity = commodity_table.lookup(namespace, mnemonic)
    else:
        split_ledger: PlaintextLedger = ledger.children[0]
        split_account_name = split_ledger.props['account']
        split_account = find_account(root_account, split_account_name)
        commodity = split_account.GetCommodity()
        mnemonic = commodity.get_mnemonic()

    if commodity is None:
        raise Exception(f'cannot find commodity ({namespace}, {mnemonic}) when trying to create transaction {ledger.line}')
    transaction.SetCurrency(commodity)

    date_str = ledger.props['date']
    tx_num = ledger.props['tx_num']
    tx_desc = ledger.props['tx_desc']

    if tx_num is not None:
        transaction.SetNum(tx_num)
    if tx_desc is not None:
        transaction.SetDescription(tx_desc)

    if 'doc_link' in ledger.metadata:
        dock_link = ledger.metadata['doc_link']
        transaction.SetDocLink(dock_link)
    if 'notes' in ledger.metadata:
        notes = ledger.metadata['notes']
        transaction.SetNotes(notes)

    transaction.SetDateEnteredSecs(datetime.datetime.now())
    date = datetime.datetime.strptime(date_str, '%Y-%m-%d')
    transaction.SetDate(year=date.year, mon=date.month, day=date.day)

    for child in ledger.children:
        split_ledger: PlaintextLedger = child
        split_account_str = split_ledger.props['account']
        split_account = find_account(root_account, split_account_str)
        split_account_currency = split_account.GetCommodity()
        if split_account is None:
            raise Exception(f'Account {split_account_str} not found when trying to create transaction split {ledger.line}')

        split_amount_str = split_ledger.props['amount']
        amount = string_to_gnc_numeric(split_amount_str, split_account_currency)

        split = Split(book)
        split.SetParent(transaction)
        split.SetAccount(split_account)
        split.SetAmount(amount)

        if 'share_price' in split_ledger.metadata:
            share_price = string_to_gnc_numeric(split_ledger.metadata['share_price'], commodity)
            split.SetSharePrice(share_price)
            pass
        if 'value' in split_ledger.metadata:
            value_str = split_ledger.metadata['value']
            value = string_to_gnc_numeric(value_str, commodity)
            split.SetValue(value)
            pass
        else:
            split.SetValue(amount)
        if 'action' in split_ledger.metadata:
            action = split_ledger.metadata['action']
            if action is not None:
                split.SetAction(action)
            pass
        if 'memo' in split_ledger.metadata:
            memo = split_ledger.metadata['memo']
            if memo is not None:
                split.SetMemo(memo)
            pass

    transaction.CommitEdit()
    return True
    pass


class PlaintextToGnuCash:
    def __init__(self, plaintext_file: str):
        self.parser = PlaintextLedgerParser()
        self.parser.parse_file(plaintext_file)
        self.accounts: Dict[str, Account] = {}

        pass

    def export_to_gnucash(self, xml_file: str) -> (bool, Optional[GnuCashBackendException]):
        """
        export GnuCash plaintext to GnuCash format
        :param xml_file: the path of the GnuCash file to save
        :param overwrite: if GnuCash file exists, shall we overwrite that? Default is False
        :return: True if file created successfully, False otherwise
        """
        fullpath = os.path.abspath(xml_file)

        try:
            # To support GnuCash 3.4, we need to use is_new=True here.
            if sys.version_info >= (3, 8):
                from gnucash import SessionOpenMode
                session = Session(f'xml://{fullpath}', SessionOpenMode.SESSION_NEW_STORE)
            else:
                session = Session(f'xml://{fullpath}', is_new=True)
            book = session.get_book()
            root_account = book.get_root_account()
            root_account.SetDescription("Created by GnuCash plaintext")

            for child in self.parser.root_directive.children:
                ledger: PlaintextLedger = child
                operations = {
                    DirectiveType.CREATE_COMMODITY: create_commodity,
                    DirectiveType.OPEN_ACCOUNT: create_account,
                    DirectiveType.TRANSACTION: create_transaction
                }
                operations[ledger.type](ledger, book)
                pass

            session.save()
            session.end()
            return not book.session_not_saved(), None
        except GnuCashBackendException as backend_exception:
            raise backend_exception
        pass
