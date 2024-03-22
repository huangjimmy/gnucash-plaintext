import os.path
import unittest
import io
from gnucash import GnuCashBackendException, Session
from plaintext_to_gnucash import PlaintextToGnuCash
from gnucash_to_plaintext import GnuCashToPlainText


class PlaintextToGnuCashTest(unittest.TestCase):

    def test_plaintext_to_gnucash(self):
        text_input_file = './plaintext_to_gnucash.test.input.txt'
        text_output_file = './plaintext_to_gnucash.test.output.txt'
        xml_output_file = './plaintext_to_gnucash.test.output.gnucash'
        lck_file = f'{xml_output_file}.LCK'

        if not os.path.exists(lck_file):
            if os.path.exists(xml_output_file):
                os.remove(xml_output_file)
                self.assertFalse(os.path.exists(xml_output_file))
        else:
            raise Exception(f'Found gnucash lock file {lck_file}. GnuCash is single-user app and an existing LCK '
                            f'file usually indicates other program is accessing ${xml_output_file}')

        try:
            plaintext_to_gnucash = PlaintextToGnuCash(text_input_file)
            plaintext_to_gnucash.export_to_gnucash(xml_output_file)
            self.assertTrue(os.path.exists(xml_output_file))
        except GnuCashBackendException as backend_exception:
            print(backend_exception)
            self.assertTrue(False)
            pass

        # now try to convert GnuCash file back to plaintext and verify input text file and output text are consistent
        # all those lines starting with 'guid' shall not equal and the rest lines shall equal
        try:
            with Session(xml_output_file) as session:
                book = session.get_book()
                output = io.StringIO()
                gnucash = GnuCashToPlainText(book, output)
                gnucash.gnucash_to_plaintext()
                plaintext = output.getvalue()
                with open(text_input_file, 'r') as f:
                    file_cotent = f.read()
                    self.assertNotEqual(file_cotent, plaintext)
                pass
            self.assertTrue('\\\\' not in plaintext)

            with open(text_output_file, 'w') as f:
                f.write(plaintext)

            with open(text_input_file, 'r') as f:
                input_content = f.read()
                input_content_lines = input_content.split('\n')
                plaintext_lines = plaintext.split('\n')
                self.assertEqual(len(input_content_lines), len(plaintext_lines))
                for (line1, line2) in zip(input_content_lines, plaintext_lines):
                    str1 = line1.strip()
                    str2 = line2.strip()

                    if str1.startswith('guid:'):
                        self.assertTrue(str2.startswith('guid:'))
                        self.assertNotEqual(str1, str2)
                    else:
                        self.assertEqual(str1, str2)

        except GnuCashBackendException as backend_exception:
            print(backend_exception)
            self.assertTrue(False)
