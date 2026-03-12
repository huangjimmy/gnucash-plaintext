"""
Use case for exporting GnuCash transactions to plaintext format.

Exports complete GnuCash data including commodities, accounts, and transactions
with all metadata required for round-trip import.
"""

import datetime
import os
from typing import Optional

from gnucash.gnucash_core_c import xaccAccountGetTypeStr

from infrastructure.gnucash.utils import (
    encode_value_as_string,
    get_account_full_name,
    get_commodity_ticker,
    get_parent_accounts_and_self,
    number_in_string_format_is_1,
    to_string_with_decimal_point_placed,
)
from repositories.gnucash_repository import GnuCashRepository


class ExportResult:
    """Container for export data"""
    def __init__(self):
        self.commodities = []  # List of (commodity, first_transaction)
        self.accounts = []     # List of (account, first_transaction)
        self.transactions = [] # List of transactions
        self.commodity_seen = set()
        self.account_seen = set()


class ExportTransactionsUseCase:
    """Use case for exporting transactions to plaintext with full metadata"""

    def __init__(self, repository: GnuCashRepository):
        """
        Initialize use case.

        Args:
            repository: GnuCash repository instance
        """
        self.repository = repository

    def execute(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        account_filter: Optional[str] = None,
        all_accounts: bool = False
    ) -> ExportResult:
        """
        Export transactions with ALL commodities and accounts.

        IMPORTANT: When filtering transactions, we still export ALL commodities
        and ALL accounts. This is required for successful import - commodities
        and accounts are declarations that must exist before transactions can
        reference them.

        Args:
            start_date: Optional start date for filtering TRANSACTIONS only
            end_date: Optional end date for filtering TRANSACTIONS only
            account_filter: Optional account path for filtering TRANSACTIONS only
            all_accounts: If True, export ALL accounts regardless of transactions

        Returns:
            ExportResult with:
            - ALL commodities (not filtered, or all from accounts if all_accounts=True)
            - ALL accounts (not filtered, or all from repository if all_accounts=True)
            - Filtered transactions (by date/account if specified)
        """
        # Get ALL transactions first (we'll filter them later)
        all_transactions = self.repository.get_all_transactions()

        # Sort by date
        all_transactions.sort(key=lambda tx: tx.GetDate())

        # Filter transactions by date range if specified
        if start_date and end_date:
            filtered_transactions = []
            for tx in all_transactions:
                tx_date = tx.GetDate().strftime("%Y-%m-%d")
                if start_date <= tx_date <= end_date:
                    filtered_transactions.append(tx)
            transactions = filtered_transactions
        else:
            transactions = all_transactions

        # Filter transactions by account if specified
        if account_filter:
            filtered = []
            for tx in transactions:
                for split in tx.GetSplitList():
                    account = split.GetAccount()
                    account_name = get_account_full_name(account)
                    if account_name.startswith(account_filter):
                        filtered.append(tx)
                        break
            transactions = filtered

        result = ExportResult()

        if all_accounts:
            # Collect ALL accounts and their commodities directly from repository
            for account in self.repository.get_all_accounts():
                commodity = account.GetCommodity()
                if commodity is None:
                    continue
                ticker = get_commodity_ticker(commodity)
                if ticker not in result.commodity_seen:
                    result.commodity_seen.add(ticker)
                    result.commodities.append((commodity, None))
                account_guid = account.GetGUID().to_string()
                if account_guid not in result.account_seen:
                    result.account_seen.add(account_guid)
                    result.accounts.append((account, None))
        else:
            # Collect ALL commodities and ALL accounts (not just from filtered transactions)
            # This is critical - without all declarations, import will fail
            for transaction in all_transactions:
                self._collect_transaction_data(transaction, result)

        # Only include the filtered transactions in the result
        result.transactions = transactions

        return result

    def _collect_transaction_data(self, transaction, result: ExportResult):
        """
        Collect commodity, account, and transaction data.

        Args:
            transaction: GnuCash Transaction object
            result: ExportResult to populate
        """
        splits = transaction.GetSplitList()

        # Collect commodities and accounts from splits
        for split in splits:
            split_account = split.GetAccount()
            commodity = split_account.GetCommodity()
            ticker = get_commodity_ticker(commodity)

            # Collect commodity if not seen
            if ticker not in result.commodity_seen:
                result.commodity_seen.add(ticker)
                result.commodities.append((commodity, transaction))

            # Collect account hierarchy if not seen
            accounts = get_parent_accounts_and_self(split_account)
            for account in accounts:
                account_guid = account.GetGUID().to_string()
                if account_guid not in result.account_seen:
                    result.account_seen.add(account_guid)
                    result.accounts.append((account, transaction))

        # Add transaction
        result.transactions.append(transaction)

    def format_as_plaintext(self, result: ExportResult) -> str:
        """
        Format export result as plaintext string with full legacy format.

        Args:
            result: ExportResult with commodities, accounts, and transactions

        Returns:
            Formatted plaintext string with all metadata
        """
        lines = []

        # Output commodities
        for commodity, transaction in result.commodities:
            self._format_commodity(commodity, transaction, lines)

        # Output accounts
        for account, transaction in result.accounts:
            self._format_account(account, transaction, lines)

        # Output transactions
        for transaction in result.transactions:
            self._format_transaction(transaction, lines)

        # Join lines and add trailing newline to match legacy format
        return '\n'.join(lines) + '\n' if lines else ''

    def _file_date_str(self) -> str:
        """Return GnuCash file modification date as YYYY-MM-DD string."""
        mtime = os.path.getmtime(self.repository.file_path)
        return datetime.date.fromtimestamp(mtime).strftime("%Y-%m-%d")

    def _format_commodity(self, commodity, transaction, lines: list):
        """Format commodity declaration"""
        mnemonic = commodity.get_mnemonic()
        namespace = commodity.get_namespace()
        fraction = commodity.get_fraction()
        fullname = commodity.get_fullname()

        if transaction is not None:
            date_str = transaction.GetDate().strftime("%Y-%m-%d")
        else:
            date_str = self._file_date_str()
        ticker = get_commodity_ticker(commodity)

        lines.append(f'{date_str} commodity {ticker}')
        lines.append(f'\tmnemonic: {encode_value_as_string(mnemonic)}')
        lines.append(f'\tfullname: {encode_value_as_string(fullname)}')
        lines.append(f'\tnamespace: {encode_value_as_string(namespace)}')
        lines.append(f'\tfraction: {fraction}')

    def _format_account(self, account, transaction, lines: list):
        """Format account declaration"""
        commodity = account.GetCommodity()
        if commodity is None:
            return

        mnemonic = commodity.get_mnemonic()
        namespace = commodity.get_namespace()
        fraction = commodity.get_fraction()
        commodity_scu = account.GetCommoditySCU()

        if transaction is not None:
            date_str = transaction.GetDate().strftime("%Y-%m-%d")
        else:
            date_str = self._file_date_str()
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

        lines.append(f'{date_str} open {account_full_name}')
        lines.append(f'\tguid: "{account_guid.to_string()}"')
        lines.append(f'\ttype: "{account_type_str}"')

        for (key, value) in [
            ('placeholder', is_placeholder),
            ('code', code),
            ('description', description),
            ('color', color),
            ('notes', notes),
            ('tax_related', tax_related),
        ]:
            if value is not None:
                lines.append(f'\t{key}: {encode_value_as_string(value)}')

        lines.append(f'\tcommodity.namespace: {encode_value_as_string(namespace)}')
        lines.append(f'\tcommodity.mnemonic: {encode_value_as_string(mnemonic)}')
        if commodity_scu != fraction:
            lines.append(f'\tcommodity_scu: {encode_value_as_string(commodity_scu)}')

    def _format_transaction(self, transaction, lines: list):
        """Format transaction with all metadata"""
        tx_guid = transaction.GetGUID()
        tx_splits = transaction.GetSplitList()
        date_str = transaction.GetDate().strftime("%Y-%m-%d")
        tx_num = transaction.GetNum()
        tx_desc = transaction.GetDescription()
        tx_notes = transaction.GetNotes()
        tx_currency = transaction.GetCurrency()
        tx_currency_namespace = tx_currency.get_namespace()
        tx_currency_symbol = tx_currency.get_mnemonic()

        # GetAssociation was renamed to GetDocLink in GnuCash 4.x
        try:
            tx_doc_link = transaction.GetDocLink()
        except AttributeError:
            # Fall back to older GnuCash API (< 4.0)
            tx_doc_link = transaction.GetAssociation()

        # Transaction header
        line = f'{date_str} *'
        if tx_num and tx_num.strip() != "":
            line += f' {encode_value_as_string(tx_num)}'
        if tx_desc and tx_desc.strip() != "":
            line += f' {encode_value_as_string(tx_desc)}'
        lines.append(line)

        # Transaction metadata
        lines.append(f'\tguid: {encode_value_as_string(tx_guid.to_string())}')
        if tx_currency_namespace != 'CURRENCY':
            lines.append(f'\tcurrency.namespace: {encode_value_as_string(tx_currency_namespace)}')

        # Check if multi-currency transaction
        split_currencies = [
            (split.GetAccount().GetCommodity().get_namespace(),
             split.GetAccount().GetCommodity().get_mnemonic())
            for split in tx_splits
        ]
        split_currencies = list(set(split_currencies))
        if len(split_currencies) > 1:
            lines.append(f'\tcurrency.mnemonic: {encode_value_as_string(tx_currency_symbol)}')

        if tx_doc_link is not None:
            lines.append(f'\tdoc_link: {encode_value_as_string(tx_doc_link)}')
        if tx_notes and tx_notes.strip() != "":
            lines.append(f'\tnotes: {encode_value_as_string(tx_notes)}')

        # Splits
        for split in tx_splits:
            self._format_split(split, tx_currency_namespace, tx_currency_symbol, lines)

    def _format_split(self, split, tx_currency_namespace, tx_currency_symbol, lines: list):
        """Format split with all metadata"""
        split_account = split.GetAccount()
        split_currency = split_account.GetCommodity()
        split_currency_namespace = split_currency.get_namespace()
        split_currency_symbol = split_currency.get_mnemonic()

        split_account_full_name = get_account_full_name(split_account)
        action = split.GetAction()
        memo = split.GetMemo()

        formatted_amount = to_string_with_decimal_point_placed(split.GetAmount())
        share_price = to_string_with_decimal_point_placed(split.GetSharePrice())
        split_value = to_string_with_decimal_point_placed(split.GetValue())

        # Split line
        currency_ticker = get_commodity_ticker(split_currency)
        if ' ' in currency_ticker or '\t' in currency_ticker:
            currency_ticker = encode_value_as_string(currency_ticker)
        lines.append(f'\t{split_account_full_name} {formatted_amount} {currency_ticker}')

        # Split metadata
        split_currency_not_match_tx = (
            split_currency_symbol != tx_currency_symbol or
            split_currency_namespace != tx_currency_namespace
        )

        if split_currency_not_match_tx:
            lines.append(f'\t\taccount.commodity.mnemonic: {encode_value_as_string(split_currency_symbol)}')
            if split_currency_namespace != 'CURRENCY':
                lines.append(f'\t\taccount.commodity.namespace: {encode_value_as_string(split_currency_namespace)}')

        if not number_in_string_format_is_1(share_price) or split_currency_not_match_tx:
            lines.append(f'\t\tshare_price: {encode_value_as_string(share_price)}')

        if split_value != formatted_amount:
            lines.append(f'\t\tvalue: {encode_value_as_string(split_value)}')

        if action is not None and action != "":
            lines.append(f'\t\taction: {encode_value_as_string(action)}')

        if memo and memo != "":
            lines.append(f'\t\tmemo:{encode_value_as_string(memo)}')

    def export_to_file(
        self,
        output_path: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        account_filter: Optional[str] = None,
        all_accounts: bool = False
    ) -> int:
        """
        Export transactions to file.

        Args:
            output_path: Path for output file
            start_date: Optional start date
            end_date: Optional end date
            account_filter: Optional account filter
            all_accounts: If True, export all accounts even without transactions

        Returns:
            Number of transactions exported
        """
        result = self.execute(start_date, end_date, account_filter, all_accounts)
        plaintext = self.format_as_plaintext(result)

        with open(output_path, 'w') as f:
            f.write(plaintext)

        return len(result.transactions)
