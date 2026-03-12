"""
Use case for exporting GnuCash transactions to beancount format.

Exports GnuCash data to beancount-compatible format with proper account names,
commodity symbols, and metadata keys following beancount conventions.
"""

from typing import Optional

from gnucash.gnucash_core_c import xaccAccountGetTypeStr

from infrastructure.gnucash.utils import (
    get_account_full_name,
    get_commodity_ticker,
    get_parent_accounts_and_self,
    to_string_with_decimal_point_placed,
)
from repositories.gnucash_repository import GnuCashRepository
from services.beancount_converter import BeancountConverter


class ExportBeancountUseCase:
    """Use case for exporting transactions to beancount format"""

    def __init__(self, repository: GnuCashRepository):
        """
        Initialize use case.

        Args:
            repository: GnuCash repository instance
        """
        self.repository = repository
        self.converter = BeancountConverter()

    def execute(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        account_filter: Optional[str] = None
    ) -> str:
        """
        Export transactions to beancount format with ALL commodities and accounts.

        IMPORTANT: When filtering transactions, we still export ALL commodities
        and ALL accounts. This is required for beancount - commodities and accounts
        are declarations that must exist before transactions can reference them.

        Args:
            start_date: Optional start date for filtering TRANSACTIONS only
            end_date: Optional end date for filtering TRANSACTIONS only
            account_filter: Optional account path for filtering TRANSACTIONS only

        Returns:
            Beancount-formatted string with:
            - ALL commodity declarations (not filtered)
            - ALL account declarations (not filtered)
            - Filtered transactions (by date/account if specified)
        """
        # Get ALL transactions first
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

        # Collect ALL commodities and ALL accounts from ALL transactions
        # This is critical - beancount requires all declarations before use
        commodity_seen = set()
        account_seen = set()
        commodities = []
        accounts = []

        for transaction in all_transactions:
            splits = transaction.GetSplitList()
            for split in splits:
                split_account = split.GetAccount()
                commodity = split_account.GetCommodity()
                ticker = get_commodity_ticker(commodity)

                # Collect commodity if not seen
                if ticker not in commodity_seen:
                    commodity_seen.add(ticker)
                    commodities.append((commodity, transaction))

                # Collect account hierarchy if not seen
                account_list = get_parent_accounts_and_self(split_account)
                for account in account_list:
                    account_guid = account.GetGUID().to_string()
                    if account_guid not in account_seen:
                        account_seen.add(account_guid)
                        accounts.append((account, transaction))

        # Generate beancount output
        lines = []

        # Output commodities
        for commodity, transaction in commodities:
            self._format_commodity(commodity, transaction, lines)

        # Output accounts
        for account, transaction in accounts:
            self._format_account(account, transaction, lines)

        # Output transactions
        for transaction in transactions:
            self._format_transaction(transaction, lines)

        return '\n'.join(lines) + '\n' if lines else ''

    def _format_commodity(self, commodity, transaction, lines: list):
        """Format commodity declaration in beancount format with GnuCash metadata"""
        date_str = transaction.GetDate().strftime("%Y-%m-%d")

        # Get original GnuCash commodity info
        gnucash_mnemonic = commodity.get_mnemonic()
        gnucash_namespace = commodity.get_namespace()
        gnucash_fullname = commodity.get_fullname() or ""
        fraction = commodity.get_fraction()

        # Convert ticker (namespace.mnemonic) to beancount-compatible symbol
        # Use ticker so it matches what's used in account declarations
        commodity_ticker = get_commodity_ticker(commodity)
        beancount_symbol = self.converter.convert_commodity_symbol(commodity_ticker)

        lines.append(f'{date_str} commodity {beancount_symbol}')
        lines.append(f'    gnucash-mnemonic: "{gnucash_mnemonic}"')
        lines.append(f'    gnucash-namespace: "{gnucash_namespace}"')
        if gnucash_fullname:
            lines.append(f'    gnucash-fullname: "{gnucash_fullname}"')
        lines.append(f'    gnucash-fraction: "{fraction}"')

    def _format_account(self, account, transaction, lines: list):
        """Format account declaration in beancount format with GnuCash metadata"""
        commodity = account.GetCommodity()
        if commodity is None:
            return

        date_str = transaction.GetDate().strftime("%Y-%m-%d")
        gnucash_account_name = get_account_full_name(account)
        account_type = account.GetType()
        account_type_str = xaccAccountGetTypeStr(account_type)

        # Convert to beancount-compatible account name
        beancount_account = self.converter.convert_account_name(
            gnucash_account_name,
            account_type_str
        )

        # Get GnuCash metadata
        guid = account.GetGUID().to_string()
        placeholder = account.GetPlaceholder()
        code = account.GetCode() or ""
        description = account.GetDescription() or ""
        tax_related = account.GetTaxRelated()

        # Get commodity info
        commodity_ticker = get_commodity_ticker(commodity)
        beancount_commodity = self.converter.convert_commodity_symbol(commodity_ticker)

        lines.append(f'{date_str} open {beancount_account} {beancount_commodity}')
        lines.append(f'    gnucash-name: "{gnucash_account_name}"')
        lines.append(f'    gnucash-guid: "{guid}"')
        lines.append(f'    gnucash-type: "{account_type_str}"')
        lines.append(f'    gnucash-placeholder: "{placeholder}"')
        if code:
            lines.append(f'    gnucash-code: "{code}"')
        if description:
            lines.append(f'    gnucash-description: "{description}"')
        lines.append(f'    gnucash-tax-related: "{tax_related}"')

    def _format_transaction(self, transaction, lines: list):
        """Format transaction in beancount format with GnuCash metadata"""
        tx_splits = transaction.GetSplitList()
        date_str = transaction.GetDate().strftime("%Y-%m-%d")
        tx_num = transaction.GetNum()
        tx_desc = transaction.GetDescription()

        # Transaction header
        # Beancount format: YYYY-MM-DD * "Payee" "Narration"
        # GnuCash num field can be used as payee, description as narration
        if tx_num and tx_num.strip() != "":
            if tx_desc and tx_desc.strip() != "":
                lines.append(f'{date_str} * "{tx_num}" "{tx_desc}"')
            else:
                lines.append(f'{date_str} * "{tx_num}"')
        else:
            if tx_desc and tx_desc.strip() != "":
                lines.append(f'{date_str} * "{tx_desc}"')
            else:
                lines.append(f'{date_str} *')

        # Add transaction-level GnuCash metadata
        guid = transaction.GetGUID().to_string()
        lines.append(f'    gnucash-guid: "{guid}"')

        notes = transaction.GetNotes()
        if notes:
            # Escape quotes and handle multi-line notes
            escaped_notes = notes.replace('"', '\\"').replace('\n', '\\n')
            lines.append(f'    gnucash-notes: "{escaped_notes}"')

        # Try to get doclink (GnuCash 4.0+) or association (GnuCash 3.x)
        try:
            doclink = transaction.GetDocLink()
            if doclink:
                lines.append(f'    gnucash-doclink: "{doclink}"')
        except AttributeError:
            try:
                doclink = transaction.GetAssociation()
                if doclink:
                    lines.append(f'    gnucash-doclink: "{doclink}"')
            except AttributeError:
                pass

        # Splits (postings in beancount)
        for split in tx_splits:
            self._format_split(split, lines)

        # Add blank line after transaction
        lines.append("")

    def _format_split(self, split, lines: list):
        """Format split as beancount posting with GnuCash metadata"""
        split_account = split.GetAccount()
        split_currency = split_account.GetCommodity()

        split_account_full_name = get_account_full_name(split_account)
        account_type = split_account.GetType()
        account_type_str = xaccAccountGetTypeStr(account_type)

        # Convert to beancount format
        beancount_account = self.converter.convert_account_name(
            split_account_full_name,
            account_type_str
        )

        beancount_commodity = self.converter.convert_commodity_symbol(
            get_commodity_ticker(split_currency)
        )

        formatted_amount = to_string_with_decimal_point_placed(split.GetAmount())

        # Beancount posting format: <indent><account> <amount> <commodity>
        lines.append(f'  {beancount_account} {formatted_amount} {beancount_commodity}')

        # Add split-level GnuCash metadata (indented under the posting)
        memo = split.GetMemo()
        if memo:
            escaped_memo = memo.replace('"', '\\"').replace('\n', '\\n')
            lines.append(f'      gnucash-memo: "{escaped_memo}"')

        action = split.GetAction()
        if action:
            escaped_action = action.replace('"', '\\"').replace('\n', '\\n')
            lines.append(f'      gnucash-action: "{escaped_action}"')

    def export_to_file(
        self,
        output_path: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        account_filter: Optional[str] = None
    ) -> int:
        """
        Export transactions to beancount file.

        Args:
            output_path: Path for output file
            start_date: Optional start date
            end_date: Optional end date
            account_filter: Optional account filter

        Returns:
            Number of lines exported
        """
        beancount = self.execute(start_date, end_date, account_filter)

        with open(output_path, 'w') as f:
            f.write(beancount)

        return len(beancount.split('\n'))
