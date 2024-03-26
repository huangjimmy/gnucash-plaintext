import io

from editor.gnucash_editor import GnuCashEditor
from editor.gnucash_to_plaintext import GnuCashToPlainText
from parser.plaintext_parser import PlaintextLedger, DirectiveType, PlaintextLedgerParser
import unittest
from unittest.mock import patch, MagicMock
import os
import shutil
import glob
import time

script_dir = os.path.dirname(os.path.abspath(__file__))
xml_file_path = os.path.join(script_dir, 'gnucash_editor.test.input.gnucash')
text_file_path = os.path.join(script_dir, 'gnucash_editor.test.input.txt')


class GnuCashEditorTest(unittest.TestCase):
    def test_open_gnucash_file_readonly(self):
        editor = GnuCashEditor(xml_file_path)
        editor.start_session()
        editor.end_session()
        self.assertTrue(True)

    def test_open_gnucash_file_normal(self):
        editor = GnuCashEditor(xml_file_path)
        editor.start_session(readonly=False, create_new=False)
        editor.end_session()
        self.assertTrue(True)

    def test_add_transaction_to_gnucash_readonly(self):
        editor = GnuCashEditor(xml_file_path)
        editor.start_session(readonly=False, create_new=False)
        with self.assertRaises(Exception):
            editor.create_new_transaction(PlaintextLedger(DirectiveType.TRANSACTION, 1, ""))
        editor.end_session()
        self.assertTrue(True)

    def test_find_transaction_by_sig(self):
        date_str = '2024-03-13'
        account1 = '経費 日本:食料品 しょくりょうひん'
        account2 = 'Assets:Cash In Wallets:JPY'

        editor = GnuCashEditor(xml_file_path)
        editor.start_session(readonly=True, create_new=False)
        transaction = editor.find_transactions_by_sig(date_str, [account1, account2])
        editor.end_session()

        self.assertEqual(1, len(transaction))

    @patch('logging.info')
    def test_add_transactions_to_gnucash(self, mock_logging_info: MagicMock):
        xml_tmp_path = os.path.join(script_dir, 'gnucash_editor.test.to_edit.gnucash')
        shutil.copy2(xml_file_path, xml_tmp_path)
        editor = GnuCashEditor(xml_tmp_path)
        editor.start_session(readonly=False, create_new=False)

        output = io.StringIO()
        to_plaintext = GnuCashToPlainText(editor.session.get_book(), output)
        to_plaintext.gnucash_to_plaintext()
        plaintext = output.getvalue()

        self.assertFalse('2024-03-14 * "1 Lawson Convinience Store" "牛乳 230円 袋 3円"' in plaintext)
        self.assertFalse('2024-03-15 * "1 Lawson Convinience Store" "麻婆豆腐 497円 袋 3円"' in plaintext)

        parser = PlaintextLedgerParser()
        parser.parse_file(text_file_path)
        for child in parser.root_directive.children:
            ledger: PlaintextLedger = child
            if ledger.type == DirectiveType.TRANSACTION:
                editor.create_new_transaction(ledger, dryrun=False)

        editor.end_session()

        time.sleep(2)
        editor = GnuCashEditor(xml_tmp_path)
        editor.start_session(readonly=False, create_new=False)

        for child in parser.root_directive.children:
            ledger: PlaintextLedger = child
            if ledger.type == DirectiveType.TRANSACTION:
                editor.create_new_transaction(ledger, dryrun=False)

        editor.end_session()

        time.sleep(2)
        editor = GnuCashEditor(xml_tmp_path)
        editor.start_session(readonly=True, create_new=False)
        output = io.StringIO()
        to_plaintext = GnuCashToPlainText(editor.session.get_book(), output)
        to_plaintext.gnucash_to_plaintext()
        plaintext = output.getvalue()
        editor.end_session()

        actual_output = os.path.join(script_dir, 'gnucash_editor.test.output.txt')
        with open(actual_output, 'w') as f:
            f.write(plaintext)
        # there are 15 transactions in plaintext, 13 exist in gnucash, 2 new
        # so logging.info should be called 13*1+2*2 = 17 calls and then 15 calls
        self.assertEqual(17+15, mock_logging_info.call_count)
        self.assertTrue('will not create a duplicate transaction' in mock_logging_info.call_args_list[0][0][0])
        self.assertTrue('will not create a duplicate transaction' in mock_logging_info.call_args_list[1][0][0])
        self.assertTrue('will not create a duplicate transaction' in mock_logging_info.call_args_list[12][0][0])
        self.assertTrue('create_new_transaction: will create a new transaction'
                        in mock_logging_info.call_args_list[13][0][0])
        self.assertTrue('create_new_transaction: created a new transaction'
                        in mock_logging_info.call_args_list[14][0][0])
        self.assertTrue('create_new_transaction: will create a new transaction'
                        in mock_logging_info.call_args_list[15][0][0])
        self.assertTrue('create_new_transaction: created a new transaction'
                        in mock_logging_info.call_args_list[16][0][0])

        self.assertTrue('will not create a duplicate transaction' in mock_logging_info.call_args_list[29][0][0])
        self.assertTrue('create_new_transaction: find matching transactions'
                        in mock_logging_info.call_args_list[30][0][0])
        self.assertTrue('create_new_transaction: find matching transactions'
                        in mock_logging_info.call_args_list[31][0][0])

        self.assertTrue('2024-03-14 * "1 Lawson Convinience Store" "牛乳 230円 袋 3円"' in plaintext)
        self.assertTrue('2024-03-15 * "1 Lawson Convinience Store" "麻婆豆腐 497円 袋 3円"' in plaintext)

        for pattern in ['gnucash_editor.test.to_edit.*',
                        'gnucash_editor.test.input.gnucash.*.log',
                        'gnucash_to_plaintext.test.input.gnucash.*.log']:
            for file_path in glob.glob(os.path.join(script_dir, pattern)):
                try:
                    os.remove(file_path)
                except OSError:
                    pass
            pass
        pass


