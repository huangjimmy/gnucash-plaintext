from parser.plaintext_parser import (parse_split, parse_transaction_head, parse_metadata,
                              parse_open_account, parse_commodity_directive,
                              PlaintextLedgerParser, DirectiveType)
import unittest
import os

script_dir = os.path.dirname(os.path.abspath(__file__))


class TestPlaintextParser(unittest.TestCase):
    def test_parse_split(self):
        test_case = 'Assets:Membership Rewards:イオン会員 50000 "Membership Rewards.イオン"'
        (account_name, amount, symbol) = parse_split(test_case)
        self.assertEqual('Assets:Membership Rewards:イオン会員', account_name)
        self.assertEqual('50000', amount)
        self.assertEqual( 'Membership Rewards.イオン', symbol)

        test_case = 'Expenses-CAN:Tax CAN:EI Test Account 加拿大  94.80 CAD-加拿大元'
        (account_name, amount, symbol) = parse_split(test_case)
        self.assertEqual('Expenses-CAN:Tax CAN:EI Test Account 加拿大', account_name)
        self.assertEqual('94.80', amount)
        self.assertEqual( 'CAD-加拿大元', symbol)

        test_case = 'Expenses-CAN:Tax CAN:EI Test Account 加拿大  94.80 '
        (account_name, amount, symbol) = parse_split(test_case)
        self.assertTrue(account_name is None)
        self.assertTrue(amount is None)
        self.assertTrue(symbol is None)

        test_case = 'Assets:Current Assets:Cash in Wallet:PC Points 570 PC-Points'
        (account_name, amount, symbol) = parse_split(test_case)
        self.assertEqual('Assets:Current Assets:Cash in Wallet:PC Points', account_name)
        self.assertEqual('570', amount)
        self.assertEqual('PC-Points', symbol)

        test_case = 'Assets:Current Assets:Cash in Lottery:Lucky 649 Lottery 65000 CAD'
        (account_name, amount, symbol) = parse_split(test_case)
        self.assertEqual('Assets:Current Assets:Cash in Lottery:Lucky 649 Lottery', account_name)
        self.assertEqual('65000', amount)
        self.assertEqual('CAD', symbol)

        test_case = 'Expenses-CAN:Sales Tax:GST 0.89 CAD '
        (account_name, amount, symbol) = parse_split(test_case)
        self.assertEqual('Expenses-CAN:Sales Tax:GST', account_name)
        self.assertEqual('0.89', amount)
        self.assertEqual('CAD', symbol)

        test_case = 'notes: "This is a note"'
        (account_name, amount, symbol) = parse_split(test_case)
        self.assertTrue(account_name is None)
        self.assertTrue(amount is None)
        self.assertTrue(symbol is None)

        test_case = '2024-03-14 * "This is Num" "This is description"'
        (account_name, amount, symbol) = parse_split(test_case)
        self.assertTrue(account_name is None)
        self.assertTrue(amount is None)
        self.assertTrue(symbol is None)

        test_case = 'Income:Gifts Received:Grandpa]\'s Bro -100.00 CNY '
        (account_name, amount, symbol) = parse_split(test_case)
        self.assertEqual('Income:Gifts Received:Grandpa]\'s Bro', account_name)
        self.assertEqual('-100.00', amount)
        self.assertEqual('CNY', symbol)

    def test_parse_transaction_head(self):
        test_case = '2024-03-14 * "This is Num" "This is description"'
        (date, num, desc) = parse_transaction_head(test_case)
        self.assertEqual('2024-03-14', date)
        self.assertEqual('This is Num', num)
        self.assertEqual('This is description', desc)

        test_case = '2024-03-14 *  "This is description"'
        (date, num, desc) = parse_transaction_head(test_case)
        self.assertEqual('2024-03-14', date)
        self.assertIsNone(num)
        self.assertEqual('This is description', desc)

        test_case = '2024-03-14 *   '
        (date, num, desc) = parse_transaction_head(test_case)
        self.assertEqual('2024-03-14', date)
        self.assertIsNone(num)
        self.assertIsNone(desc)

        test_case = 'notes: "This is a note"'
        (date, num, desc) = parse_transaction_head(test_case)
        self.assertIsNone(date)
        self.assertIsNone(num)
        self.assertIsNone(desc)

        test_case = '2024-03-13 * "1 Lawson Convinience Store" "RO-SONN JPN 麻婆豆腐 497円 焼き鳥 599円 牛乳 230円 ケーキ 192円 袋 3円"'
        (date, num, desc) = parse_transaction_head(test_case)
        self.assertEqual('2024-03-13', date)
        self.assertEqual('1 Lawson Convinience Store', num)
        self.assertEqual('RO-SONN JPN 麻婆豆腐 497円 焼き鳥 599円 牛乳 230円 ケーキ 192円 袋 3円', desc)

    def test_parse_metadata(self):
        test_case = 'notes: "This is a note"  '
        (key, value) = parse_metadata(test_case)
        self.assertEqual('notes', key)
        self.assertEqual('This is a note', value)

        test_case = 'fraction: 100'
        (key, value) = parse_metadata(test_case)
        self.assertEqual('fraction', key)
        self.assertEqual(100, value)

        test_case = 'value: "500"'
        (key, value) = parse_metadata(test_case)
        self.assertEqual('value', key)
        self.assertEqual("500", value)

        test_case = 'value: "12345.67890"'
        (key, value) = parse_metadata(test_case)
        self.assertEqual('value', key)
        self.assertEqual("12345.67890", value)

        test_case = 'commodity_namespace: "CURRENCY"'
        (key, value) = parse_metadata(test_case)
        self.assertEqual('commodity_namespace', key)
        self.assertEqual('CURRENCY', value)

        test_case = 'commodity_namespace "CURRENCY"'
        (key, value) = parse_metadata(test_case)
        self.assertIsNone(key)
        self.assertIsNone(value)

        test_case = 'commodity.namespace: "CURRENCY"'
        (key, value) = parse_metadata(test_case)
        self.assertEqual('commodity.namespace', key)
        self.assertEqual('CURRENCY', value)

        test_case = 'memo:"I bought some groceries during my \\"Japan Trip\\""'
        (key, value) = parse_metadata(test_case)
        self.assertEqual('memo', key)
        self.assertEqual('I bought some groceries during my "Japan Trip"', value)

    def test_parse_open_account(self):
        test_case = '2022-12-30 open Assets:Current Assets:BofA'
        (date, directive, account_name) = parse_open_account(test_case)
        self.assertEqual('2022-12-30', date)
        self.assertEqual('open', directive)
        self.assertEqual('Assets:Current Assets:BofA', account_name)

        test_case = '2021-12-30 open'
        (date, directive, account_name) = parse_open_account(test_case)
        self.assertIsNone(date)
        self.assertIsNone(directive)
        self.assertIsNone(account_name)

        test_case = '2015-02-16 open Income:Gifts Received:Grandpa\'s Bro '
        (date, directive, account_name) = parse_open_account(test_case)
        self.assertEqual('2015-02-16', date)
        self.assertEqual('open', directive)
        self.assertEqual('Income:Gifts Received:Grandpa\'s Bro', account_name)

        test_case = '2015-02-16 open "Income:Gifts Received:Grandpa\'s Bro" '
        (date, directive, account_name) = parse_open_account(test_case)
        self.assertEqual('2015-02-16', date)
        self.assertEqual('open', directive)
        self.assertEqual('Income:Gifts Received:Grandpa\'s Bro', account_name)

    def test_parse_commodity_directive(self):
        test_case = '2021-12-30 commodity USD'
        (date, directive, commodity) = parse_commodity_directive(test_case)
        self.assertTrue(date == '2021-12-30')
        self.assertTrue(directive == 'commodity')
        self.assertTrue(commodity == 'USD')

        test_case = '2021-12-30 commodity'
        (date, directive, commodity) = parse_commodity_directive(test_case)
        self.assertIsNone(date)
        self.assertIsNone(directive)
        self.assertIsNone(commodity)

    def test_parse_indent(self):
        leading_spaces = ' '
        parser = PlaintextLedgerParser()
        self.assertIsNone(parser.indent)
        (valid, level, error_msg) = parser.verify_line_indentation(leading_spaces)
        self.assertIsNotNone(parser.indent)
        self.assertTrue(valid)
        self.assertEqual(2, level)
        self.assertIsNone(error_msg)

    def test_beancount_compatible_account_name(self):
        file_path = os.path.join(script_dir, 'test_beancount_compatible_account_name.book')
        parser = PlaintextLedgerParser()
        parser.parse_file(file_path)
        self.assertEqual(8, len(parser.root_directive.children))
        [expenses_can, expenses_can_groceries,
         assets, current_assets, cash_in_wallets,
         cash_in_wallets_cad, cash_in_wallets_usd, buy_napa] = parser.root_directive.children
        self.assertEqual('Expenses:Expenses-CAN', expenses_can.beancount_compatible_account_name())
        self.assertEqual('Expenses:Expenses-CAN:식료품-장보기', expenses_can_groceries.beancount_compatible_account_name())
        self.assertEqual('Assets', assets.beancount_compatible_account_name())
        self.assertEqual('Assets:Current-Assets', current_assets.beancount_compatible_account_name())
        self.assertEqual('Assets:Current-Assets:Cash-in-Wallet', cash_in_wallets.beancount_compatible_account_name())
        self.assertEqual('Assets:Current-Assets:Cash-in-Wallet:CAD', cash_in_wallets_cad.beancount_compatible_account_name())
        self.assertEqual('Assets:Current-Assets:Cash-in-Wallet:Usd-wallet', cash_in_wallets_usd.beancount_compatible_account_name())

    def test_beancount_compatible_commodity_symbol(self):
        file_path = os.path.join(script_dir, 'test_beancount_compatible_commodity_symbol.book')
        parser = PlaintextLedgerParser()
        parser.parse_file(file_path)
        self.assertEqual(2, len(parser.root_directive.children))
        [commodity1, commodity2] = parser.root_directive.children
        self.assertEqual('TEMPLATE.TEMPLATE', commodity1.beancount_compatible_commodity_symbol())
        self.assertEqual('TEMPLATE.REWARD-POINTS', commodity2.beancount_compatible_commodity_symbol())

    def test_parse_file(self):
        file_path = os.path.join(script_dir, "test_book.txt")
        parser = PlaintextLedgerParser()
        parser.parse_file(file_path)
        root_directive = parser.root_directive
        self.assertIsNotNone(root_directive)
        self.assertEqual({}, root_directive.metadata)
        self.assertEqual({}, root_directive.props)
        self.assertEqual(2, len(root_directive.children))

    def test_parse_file2(self):
        file_path = os.path.join(script_dir, "test_book2.txt")
        parser = PlaintextLedgerParser()
        parser.parse_file(file_path)
        root_directive = parser.root_directive
        self.assertIsNotNone(root_directive)
        self.assertEqual({}, root_directive.metadata)
        self.assertEqual({}, root_directive.props)
        self.assertEqual('CAD', root_directive.children[0].props['symbol'])
        self.assertEqual('経費 日本:食料品 しょくりょうひん', root_directive.children[23].props['account'])
        self.assertEqual('경비 한국:식료품', root_directive.children[25].props['account'])
        self.assertEqual('経費 日本:食料品 しょくりょうひん', root_directive.children[42].children[0].props['account'])
        self.assertEqual('Membership Rewards.イオン', root_directive.children[27].props['symbol'])
        self.assertEqual('Membership Rewards', root_directive.children[27].metadata['namespace'])
        self.assertEqual('イオン', root_directive.children[27].metadata['mnemonic'])
        self.assertEqual('イオン会員', root_directive.children[27].metadata['fullname'])
        self.assertEqual(2, len(root_directive.children[45].children))
        for child in root_directive.children:
            if child.type == DirectiveType.TRANSACTION:
                self.assertGreaterEqual(len(child.children), 2)
            elif child.type == DirectiveType.CREATE_COMMODITY:
                self.assertIsNotNone(child.metadata['fraction'])
        self.assertEqual(3, len(root_directive.children[34].children))
        self.assertEqual(46, len(root_directive.children))
        pass
