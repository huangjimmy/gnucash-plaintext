import os.path
from typing import Optional, Dict
import datetime
import os
import sys
from gnucash import Account, Book, Transaction, Split, Session, GnuCashBackendException, GncCommodity
from editor.utils import create_account, create_transaction, create_commodity
from parser.plaintext_parser import PlaintextLedger, PlaintextLedgerParser, DirectiveType


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
