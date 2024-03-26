import logging

from gnucash import Account, Transaction, Session, Query
from gnucash import QOF_COMPARE_GTE, QOF_COMPARE_LTE
from gnucash.gnucash_core import QueryDatePredicate, QOF_QUERY_AND, GUID, GUIDString
from gnucash.gnucash_core_c import QOF_DATE_MATCH_DAY
from typing import Optional
from datetime import datetime, timedelta
import sys
from utils import find_account, get_transaction_sig
from editor.utils import create_commodity, create_account, create_transaction
from parser.plaintext_parser import PlaintextLedger, DirectiveType


class GnuCashEditor:

    def __init__(self, gnucash_xml_file):
        self.gnucash_xml_file = gnucash_xml_file
        self.session: Optional[Session] = None
        self.readonly = True
        self.create_new = False

    def start_session(self, readonly=True, create_new=False):
        self.readonly = readonly
        self.create_new = create_new
        if create_new and readonly:
            raise Exception("readonly and create_new cannot be True at the same time")

        if sys.version_info >= (3, 8):
            from gnucash import SessionOpenMode
            mode = SessionOpenMode.SESSION_NORMAL_OPEN
            if readonly:
                mode = SessionOpenMode.SESSION_READ_ONLY
            elif create_new:
                mode = SessionOpenMode.SESSION_NEW_STORE

            session = Session(f'xml://{self.gnucash_xml_file}', mode)
        else:
            ignore_lock = readonly
            is_new = not readonly and create_new
            session = Session(f'xml://{self.gnucash_xml_file}', is_new=is_new, ignore_lock=ignore_lock)
        self.session = session

    def end_session(self):
        if self.session is not None:
            if not self.readonly:
                self.session.save()
            self.session.end()
            self.session = None

    def get_account_by_guid(self, guid: str) -> Optional[Account]:
        if self.session is None:
            raise Exception("No available GnuCash session, did you call start_session?")
        book = self.session.get_book()
        account_guid = GUID()
        GUIDString(guid, account_guid)
        account = account_guid.AccountLookup(book)
        return account

    def find_account_by_fullname(self, account_name: str) -> Optional[Account]:
        if self.session is None:
            raise Exception("No available GnuCash session, did you call start_session?")
        book = self.session.get_book()
        root_account = book.get_root_account()
        return find_account(root_account, account_name)

    def get_transaction_by_guid(self, guid: str) -> Transaction:
        if self.session is None:
            raise Exception("No available GnuCash session, did you call start_session?")
        book = self.session.get_book()
        transaction_guid = GUID()
        GUIDString(guid, transaction_guid)
        transaction = transaction_guid.TransLookup(book)
        return transaction

    def find_transactions_by_sig(self, date_str: str, splits_sig: [str]) -> [Transaction]:
        """
        Find transactions that match signatures.
        A signature of a transaction is a tuple (date_str, [split_account1, ..., split_accountN])
        :param date_str: %Y-%m-%d format date string, e.g., 2020-02-02
        :param splits_sig: a list of account names, e.g., ['Assets:Cash in Wallet:CAD', 'Assets:Cash in Wallet:JPY']
        :return:
        """
        if self.session is None:
            raise Exception("No available GnuCash session, did you call start_session?")

        book = self.session.get_book()

        sig_to_find = (date_str, splits_sig)
        date = datetime.strptime(date_str, "%Y-%m-%d")
        one_day = timedelta(days=1)
        yesterday = date - one_day
        tomorrow = date + one_day

        query = Query()

        query.search_for('Trans')
        date_pred_gte = QueryDatePredicate(QOF_COMPARE_GTE, QOF_DATE_MATCH_DAY, yesterday)
        date_pred_lte = QueryDatePredicate(QOF_COMPARE_LTE, QOF_DATE_MATCH_DAY, tomorrow)
        query.add_term(['date-posted'], date_pred_gte, QOF_QUERY_AND)
        query.add_term(['date-posted'], date_pred_lte, QOF_QUERY_AND)
        query.set_book(book)
        transactions = []

        for _transaction in query.run():
            transaction = Transaction(instance=_transaction)
            tx_sig = get_transaction_sig(transaction)
            tx_date = transaction.GetDate().strftime("%Y-%m-%d")
            if tx_sig == sig_to_find and date_str == tx_date:
                transactions.append(transaction)

        return transactions

    def find_transctions_by_ledger(self, transaction_ledger: PlaintextLedger):
        date_str = transaction_ledger.props['date']
        split_accounts = [child.props['account'] for child in transaction_ledger.children]
        tx_sig = (date_str, split_accounts)

        transactions = self.find_transactions_by_sig(date_str, tx_sig)
        return transactions

    def create_new_transaction(self, transaction_ledger: PlaintextLedger, dryrun=False):
        if self.session is None:
            raise Exception('No available GnuCash session, did you call start_session?')
        if self.readonly:
            raise Exception('Cannot create new transactions in readonly mode')
        if transaction_ledger.type != DirectiveType.TRANSACTION:
            raise Exception(f'Expect ledger.type to be {DirectiveType.TRANSACTION} but get {transaction_ledger.type}')

        if 'guid' in transaction_ledger.metadata:
            guid = transaction_ledger.metadata['guid']
            existing_tx = self.get_transaction_by_guid(guid)
            if existing_tx is not None:
                logging.info(f'create_new_transaction: transaction {guid} already exists, '
                             f'will not create a duplicate transaction')
                return

        book = self.session.get_book()

        date_str = transaction_ledger.props['date']
        split_accounts = [child.props['account'] for child in transaction_ledger.children]

        existing_txs = self.find_transactions_by_sig(date_str, split_accounts)

        if len(existing_txs) > 0:
            logging.info(f'create_new_transaction: find matching transactions '
                         f'on {date_str} with splits {split_accounts}')
            for tx in existing_txs:
                pass
            return

        logging.info(f'create_new_transaction: will create a new transaction '
                     f'on {date_str} with splits {split_accounts}')
        if not dryrun:
            create_transaction(transaction_ledger, book)
        logging.info(f'create_new_transaction: created a new transaction '
                     f'on {date_str} with splits {split_accounts}')

    def create_new_account(self, account_ledger: PlaintextLedger, dryrun=False):
        if self.session is None:
            raise Exception('No available GnuCash session, did you call start_session?')
        if self.readonly:
            raise Exception('Cannot create new account in readonly mode')
        if account_ledger.type != DirectiveType.TRANSACTION:
            raise Exception(f'Expect ledger.type to be {DirectiveType.OPEN_ACCOUNT} but get {account_ledger.type}')

        account_full_nanme = account_ledger.props['account']
        account = self.find_account_by_fullname(account_full_nanme)
        if account is not None:
            logging.info(f'create_new_account: {account_full_nanme} already exists')
            return

        book = self.session.get_book()
        logging.info(f'create_new_account: {account_full_nanme} not found, will create {account_full_nanme}.')
        if not dryrun:
            create_account(account_ledger, book)
        logging.info(f'create_new_account: created {account_full_nanme}.')

    def create_new_commodity(self, commodity_ledger: PlaintextLedger, dryrun=False):
        if self.session is None:
            raise Exception("No available GnuCash session, did you call start_session?")
        if self.readonly:
            raise Exception("Cannot create new commodity in readonly mode")
        if commodity_ledger.type != DirectiveType.CREATE_COMMODITY:
            raise Exception(f'Expect ledger.type to be {DirectiveType.CREATE_COMMODITY} but get {commodity_ledger.type}')

        book = self.session.get_book()

        namespace = commodity_ledger.metadata['namespace']
        mnemonic = commodity_ledger.metadata['namespace']
        logging.info(f'create_new_commodity: try to create commodity {namespace}.{mnemonic} if not exists')
        if not dryrun:
            create_commodity(commodity_ledger, book)
        logging.info(f'create_new_commodity: commodity {namespace}.{mnemonic} now created if not exists')
