import sys
from gnucash import Account, Book, Transaction, Query, GncCommodity
from gnucash.gnucash_core_c import xaccAccountGetTypeStr, gncEntryGetGUID
from utils import (get_account_full_name, to_string_with_decimal_point_placed,
                   get_parent_accounts_and_self, encode_value_as_string, number_in_string_format_is_1,
                   get_commodity_ticker)
import io
from typing import Dict


class GnuCashToPlainText:
    def __init__(self, book: Book, output: io.StringIO):
        self.book = book
        self.output = output

    def load_commodities(self) -> Dict[str, GncCommodity]:
        book = self.book
        commodity_dict: Dict[str, GncCommodity] = {}
        commodity_table = book.get_table()
        namespaces = commodity_table.get_namespaces_list()
        for namespace in namespaces:
            namespace_name = namespace.get_name()
            # Get a list of all commodities in namespace
            commodities = commodity_table.get_commodities(namespace_name)
            for i, commodity in enumerate(commodities):
                commodity_dict[get_commodity_ticker(commodity)] = commodity
        return commodity_dict

    def get_all_transactions(self) -> [Transaction]:

        book = self.book
        query = Query()
        query.search_for('Trans')
        query.set_book(book)
        transactions = []
        commodity_seen: Dict[str, bool] = {}
        account_seen: Dict[str, bool] = {}
        for transaction in query.run():
            transaction = Transaction(instance=transaction)
            transactions.append(transaction)
            splits = transaction.GetSplitList()
            for s in splits:
                split_account = s.GetAccount()
                commodity = split_account.GetCommodity()
                ticker = get_commodity_ticker(commodity)
                if ticker not in commodity_seen:
                    commodity_seen[ticker] = True
                    self.print_gnucash_commodity(commodity, transaction)

                accounts = get_parent_accounts_and_self(split_account)
                for account in accounts:
                    account_guid = account.GetGUID().to_string()
                    if account_guid not in account_seen:
                        account_seen[account_guid] = True
                        self.print_gnucash_account(account, transaction)

        for transaction in transactions:
            self.print_gnucash_transaction(transaction)
        return transactions

    def print_gnucash_commodity(self, commodity: GncCommodity, transaction: Transaction):
        output: io.StringIO = self.output
        mnemonic = commodity.get_mnemonic()
        namespace = commodity.get_namespace()
        fraction = commodity.get_fraction()
        fullname = commodity.get_fullname()

        date_str = transaction.GetDate().strftime("%Y-%m-%d")
        ticker = get_commodity_ticker(commodity)
        print(f'{date_str} commodity {ticker}', file=output, end='')
        print(f'\n\tmnemonic: {encode_value_as_string(mnemonic)}'
              f'\n\tfullname: {encode_value_as_string(fullname)}'
              f'\n\tnamespace: {encode_value_as_string(namespace)}'
              f'\n\tfraction: {fraction}', file=output)
        pass

    def print_gnucash_account(self, account: Account, transaction: Transaction):
        output: io.StringIO = self.output
        commodity = account.GetCommodity()
        if commodity is None:
            return
        mnemonic = commodity.get_mnemonic()
        namespace = commodity.get_namespace()
        fraction = commodity.get_fraction()
        commodity_scu = account.GetCommoditySCU()

        date_str = transaction.GetDate().strftime("%Y-%m-%d")
        account_full_name = get_account_full_name(account)
        account_guid = account.GetGUID()
        account_type = account.GetType()
        account_type_str = xaccAccountGetTypeStr(account_type)
        is_placeholder = account.GetPlaceholder()
        code = account.GetCode()
        description = account.GetDescription()
        color = account.GetColor()
        notes = account.GetNotes()
        tax_related = account.GetTaxRelated()

        print(f'{date_str} open {account_full_name}', file=output)
        print(f'\tguid: "{account_guid.to_string()}"', file=output)
        print(f'\ttype: "{account_type_str}"', file=output)
        for (key, value) in [('placeholder', is_placeholder),
                             ('code', code),
                             ('description', description),
                             ('color', color),
                             ('notes', notes),
                             ('tax_related', tax_related),
                             ]:
            if value is not None:
                print(f'\t{key}: {encode_value_as_string(value)}', file=output)

        print(f'\tcommodity.namespace: {encode_value_as_string(namespace)}', file=output)
        print(f'\tcommodity.mnemonic: {encode_value_as_string(mnemonic)}', file=output)
        if commodity_scu != fraction:
            print(f'\tcommodity_scu: {encode_value_as_string(commodity_scu)}', file=output)
        pass

    def print_gnucash_transaction(self, transaction: Transaction):
        output: io.StringIO = self.output
        tx_guid = transaction.GetGUID()
        tx_splits = transaction.GetSplitList()
        date_str = transaction.GetDate().strftime("%Y-%m-%d")
        tx_num = transaction.GetNum()
        tx_desc = transaction.GetDescription()
        tx_notes = transaction.GetNotes()
        tx_currency = transaction.GetCurrency()
        tx_currency_namespace = tx_currency.get_namespace()
        tx_currency_symbol = tx_currency.get_mnemonic()
        if sys.version_info >= (3, 8):
            tx_doc_link = transaction.GetDocLink()
        else:
            # GetAssociation was renamed to GetDocLink in Sep 2020
            tx_doc_link = transaction.GetAssociation()

        print(f'{date_str} *', end='', file=output)
        if tx_num and tx_num.strip() != "":
            print(f' {encode_value_as_string(tx_num)}', end='', file=output)
        if tx_desc and tx_desc.strip() != "":
            print(f' {encode_value_as_string(tx_desc)}', end='', file=output)
        print("\n", end='', file=output)
        print(f'\tguid: {encode_value_as_string(tx_guid.to_string())}', file=output)
        if tx_currency_namespace != 'CURRENCY':
            print(f'\tcurrency.namespace: {encode_value_as_string(tx_currency_namespace)}', file=output)

        split_currencies = [(c.get_namespace(), c.get_mnemonic()) for c in
                            [tx.GetAccount().GetCommodity() for tx in tx_splits]]
        split_currencies = list(set(split_currencies))
        if len(split_currencies) > 1:
            print(f'\tcurrency.mnemonic: {encode_value_as_string(tx_currency_symbol)}', file=output)
        if tx_doc_link is not None:
            print(f'\tdoc_link: {encode_value_as_string(tx_doc_link)}', file=output)
        if tx_notes and tx_notes.strip() != "":
            print(f'\tnotes: {encode_value_as_string(tx_notes)}', file=output)
        for s in tx_splits:
            split_account = s.GetAccount()
            split_currency = split_account.GetCommodity()
            split_currency_namespace = split_currency.get_namespace()
            split_currency_symbol = split_currency.get_mnemonic()

            split_account_full_name = get_account_full_name(split_account)
            guid = s.GetGUID()
            action = s.GetAction()
            memo = s.GetMemo()
            formatted_amount = to_string_with_decimal_point_placed(s.GetAmount())
            share_price = to_string_with_decimal_point_placed(s.GetSharePrice())
            split_value = to_string_with_decimal_point_placed(s.GetValue())

            print(f'\t{split_account_full_name}', end='', file=output)
            currency_ticker = get_commodity_ticker(split_currency)
            if ' ' in currency_ticker or '\t' in currency_ticker:
                currency_ticker = encode_value_as_string(currency_ticker)
            print(f' {formatted_amount} {currency_ticker}', file=output)

            # print(f'\t\tguid: {encode_value_as_string(guid)}')
            split_currency_not_match_tx = (split_currency_symbol != tx_currency_symbol
                                           or split_currency_namespace != tx_currency_namespace)
            if split_currency_not_match_tx:
                print(f'\t\taccount.commodity.mnemonic: {encode_value_as_string(split_currency_symbol)}', file=output)
                if split_currency_namespace != 'CURRENCY':
                    print(f'\t\taccount.commodity.namespace: {encode_value_as_string(split_currency_namespace)}', file=output)

            if not number_in_string_format_is_1(share_price) or split_currency_not_match_tx:
                print(f'\t\tshare_price: {encode_value_as_string(share_price)}', file=output)

            if split_value != formatted_amount:
                print(f'\t\tvalue: {encode_value_as_string(split_value)}', file=output)

            if action is not None and action != "":
                print(f'\t\taction: {encode_value_as_string(action)}', file=output)

            if memo and memo != "":
                print(f'\t\tmemo:{encode_value_as_string(memo)}', file=output)
        pass

    def gnucash_to_plaintext(self):
        self.get_all_transactions()
