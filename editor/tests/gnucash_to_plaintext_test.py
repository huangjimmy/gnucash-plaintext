import io
import sys
import unittest
from gnucash import Session, GnuCashBackendException
from editor.gnucash_to_plaintext import GnuCashToPlainText
import os

script_dir = os.path.dirname(os.path.abspath(__file__))


class GnuCashToPlaintextTest(unittest.TestCase):

    def test_gnucash_to_plaintext(self):
        file = os.path.join(script_dir, 'gnucash_to_plaintext.test.input.gnucash')
        try:
            # To support GnuCash 3.4, we need to use is_new=True here.
            if sys.version_info >= (3, 8):
                from gnucash import SessionOpenMode
                session = Session(f'xml://{file}', SessionOpenMode.SESSION_READ_ONLY)
            else:
                session = Session(f'xml://{file}', ignore_lock=True, is_new=False, force_new=False)

            book = session.get_book()
            output = io.StringIO()
            to_plaintext = GnuCashToPlainText(book, output)
            to_plaintext.gnucash_to_plaintext()
            plaintext = output.getvalue()
            actual_output = os.path.join(script_dir, 'gnucash_to_plaintext.test.actual.output.txt')
            with open(actual_output, 'w') as f:
                f.write(plaintext)

            expected_output = os.path.join(script_dir, 'gnucash_to_plaintext.test.expected.output.txt')
            with open(expected_output, 'r') as f:
                file_cotent = f.read()
                actual_lines = plaintext.split('\n')
                expected_lines = file_cotent.split('\n')
                self.assertEqual(len(actual_lines), len(expected_lines))
                self.assertTrue(all(line in actual_lines for line in expected_lines))
            pass
            session.end()
            self.assertTrue('\\\\' not in plaintext)
        except GnuCashBackendException as backend_exception:
            print(backend_exception)
            self.assertTrue(False)
