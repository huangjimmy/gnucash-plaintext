import io
import unittest
from gnucash import Session, GnuCashBackendException
from gnucash_to_plaintext import GnuCashToPlainText


class GnuCashToPlaintextTest(unittest.TestCase):

    def test_(self):
        file = './gnucash_to_plaintext.test.input.gnucash'
        try:
            session = Session(file)
            book = session.get_book()
            output = io.StringIO()
            to_plaintext = GnuCashToPlainText(book, output)
            to_plaintext.gnucash_to_plaintext()
            plaintext = output.getvalue()
            with open('./gnucash_to_plaintext.test.actual.output.txt', 'w') as f:
                f.write(plaintext)

            with open('./gnucash_to_plaintext.test.expected.output.txt', 'r') as f:
                file_cotent = f.read()
                actual_lines = plaintext.split('\n')
                expected_lines = file_cotent.split('\n')
                self.assertEqual(len(actual_lines), len(expected_lines))
                self.assertTrue(all(line in actual_lines for line in expected_lines))
            pass
            session.save()
            session.end()
            self.assertTrue('\\\\' not in plaintext)
        except GnuCashBackendException as backend_exception:
            print(backend_exception)
            self.assertTrue(False)