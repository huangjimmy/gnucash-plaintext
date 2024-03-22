import io
import unittest
from gnucash import Session, GnuCashBackendException
from gnucash_to_plaintext import GnuCashToPlainText


class GnuCashToPlaintextTest(unittest.TestCase):

    def test_(self):
        file = './gnucash_to_plaintext.test.input.gnucash'
        try:
            with Session(file) as session:
                book = session.get_book()
                output = io.StringIO()
                to_plaintext = GnuCashToPlainText(book, output)
                to_plaintext.gnucash_to_plaintext()
                plaintext = output.getvalue()
                with open('./gnucash_to_plaintext.test.expected.output.txt', 'r') as f:
                    file_cotent = f.read()
                    self.assertEqual(file_cotent, plaintext)
                pass
            self.assertTrue('\\\\' not in plaintext)
        except GnuCashBackendException as backend_exception:
            print(backend_exception)
            self.assertTrue(False)