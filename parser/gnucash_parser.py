from gnucash import Book, Transaction, Query, Session, GnuCashBackendException
from gnucash.gnucash_core_c import xaccAccountGetTypeStr
from utils import (get_account_full_name, to_string_with_decimal_point_placed,
                   get_parent_accounts_and_self, escape_string)
import io


class GnuCashLedger:
    def __init__(self, file):
        self.file = file
    def load_accounts_and_commodities(self):
        try:
            with Session(self.file) as session:
                book = session.get_book()
                root = book.get_root_account()
                pass
        except GnuCashBackendException as backend_exception:
            print(backend_exception.errors)