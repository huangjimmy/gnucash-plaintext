"""
Use case for importing GnuCash-compatible beancount files to GnuCash.

Reconstructs GnuCash files from beancount files that were exported with
all gnucash-* metadata. Validates that all required metadata is present.
"""

import contextlib

from repositories.gnucash_repository import GnuCashRepository
from services.beancount_parser import BeancountParser, BeancountValidationError
from services.gnucash_importer import GnuCashImporter
from services.plaintext_parser import DirectiveType, PlaintextDirective


class ImportBeancountResult:
    """Result of importing beancount file"""

    def __init__(self):
        self.commodities_created = 0
        self.accounts_created = 0
        self.transactions_created = 0
        self.errors = []

    def add_error(self, error: str):
        """Add an error message"""
        self.errors.append(error)

    def has_errors(self) -> bool:
        """Check if import had errors"""
        return len(self.errors) > 0


class ImportBeancountUseCase:
    """Use case for importing beancount files to GnuCash"""

    def __init__(self, repository: GnuCashRepository):
        """
        Initialize use case.

        Args:
            repository: GnuCash repository instance
        """
        self.repository = repository
        self.parser = BeancountParser()

    def import_from_file(self, beancount_file: str) -> ImportBeancountResult:
        """
        Import GnuCash-compatible beancount file.

        Args:
            beancount_file: Path to beancount file

        Returns:
            ImportBeancountResult with status

        Raises:
            BeancountValidationError: If file fails validation
        """
        result = ImportBeancountResult()

        # Parse and validate beancount file
        try:
            self.parser.parse_file(beancount_file)
        except BeancountValidationError as e:
            result.add_error(str(e))
            return result

        # Create commodities
        for commodity_data in self.parser.commodities:
            try:
                self._create_commodity(commodity_data)
                result.commodities_created += 1
            except Exception as e:
                result.add_error(f"Failed to create commodity {commodity_data.symbol}: {e}")

        # Create accounts (with original GnuCash names)
        for account_data in self.parser.accounts:
            try:
                self._create_account(account_data)
                result.accounts_created += 1
            except Exception as e:
                result.add_error(
                    f"Failed to create account {account_data.gnucash_name}: {e}"
                )

        # Create transactions
        account_mapping = self.parser.get_account_mapping()
        for tx_data in self.parser.transactions:
            try:
                self._create_transaction(tx_data, account_mapping)
                result.transactions_created += 1
            except Exception as e:
                result.add_error(f"Failed to create transaction: {e}")

        return result

    def _create_commodity(self, commodity_data):
        """Create or update commodity from beancount data"""
        # Check if commodity already exists
        commodity = self.repository.get_commodity(
            commodity_data.gnucash_namespace,
            commodity_data.gnucash_mnemonic
        )

        if commodity is None:
            # Convert to PlaintextDirective format to reuse GnuCashImporter
            directive = PlaintextDirective(
                directive_type=DirectiveType.CREATE_COMMODITY,
                level=0,
                line=f"commodity {commodity_data.symbol}"
            )
            directive.metadata = {
                'mnemonic': commodity_data.gnucash_mnemonic,
                'fullname': commodity_data.gnucash_fullname or "",
                'namespace': commodity_data.gnucash_namespace,
                'fraction': commodity_data.gnucash_fraction
            }

            # Use existing GnuCashImporter
            GnuCashImporter.create_commodity(directive, self.repository.book)

    def _create_account(self, account_data):
        """Create account from beancount data using original GnuCash name"""
        # Use the original GnuCash name, not the beancount name
        gnucash_name = account_data.gnucash_name

        # Check if account already exists
        existing = self.repository.get_account(gnucash_name)
        if existing:
            return existing

        # Find the commodity info for this account
        commodity_namespace = 'CURRENCY'
        commodity_mnemonic = account_data.commodity
        for commodity in self.parser.commodities:
            if commodity.symbol == account_data.commodity:
                commodity_namespace = commodity.gnucash_namespace
                commodity_mnemonic = commodity.gnucash_mnemonic
                break

        # Convert beancount account data to PlaintextDirective format
        # so we can use the existing GnuCashImporter
        directive = PlaintextDirective(
            directive_type=DirectiveType.OPEN_ACCOUNT,
            level=0,
            line=f"open {gnucash_name}"
        )
        directive.props = {'account': gnucash_name}
        directive.metadata = {
            'type': account_data.gnucash_type,
            'placeholder': account_data.gnucash_placeholder == "True",
            'code': account_data.gnucash_code or "",
            'description': account_data.gnucash_description or "",
            'tax_related': account_data.gnucash_tax_related == "True",
            'commodity.namespace': commodity_namespace,
            'commodity.mnemonic': commodity_mnemonic,
            'guid': account_data.gnucash_guid
        }

        # Use GnuCashImporter to create the account
        # This handles type mapping and all GnuCash internals
        GnuCashImporter.create_account(directive, self.repository.book)

        # Get the created account
        # Note: GUIDs are auto-generated by GnuCash, we don't set them manually
        account = self.repository.get_account(gnucash_name)
        return account

    def _create_transaction(self, tx_data, account_mapping: dict):
        """Create transaction from beancount data"""
        from gnucash import Split, Transaction

        from infrastructure.gnucash.utils import string_to_gnc_numeric

        book = self.repository.book
        commodity_table = book.get_table()

        # Create transaction
        transaction = Transaction(book)
        transaction.BeginEdit()

        # Get transaction currency from first posting
        first_posting = tx_data.postings[0]
        currency = commodity_table.lookup('CURRENCY', first_posting.commodity)
        if currency is None:
            # Try looking up as non-currency commodity
            for commodity_data in self.parser.commodities:
                if commodity_data.symbol == first_posting.commodity:
                    currency = commodity_table.lookup(
                        commodity_data.gnucash_namespace,
                        commodity_data.gnucash_mnemonic
                    )
                    break
        if currency is None:
            raise ValueError(f"Currency {first_posting.commodity} not found")

        transaction.SetCurrency(currency)

        # Set transaction properties
        description = tx_data.narration or ""
        num = tx_data.payee or ""

        if num:
            transaction.SetNum(num)
        if description:
            transaction.SetDescription(description)

        # Set date
        transaction.SetDatePostedSecsNormalized(tx_data.date)

        # Set notes if present
        if tx_data.gnucash_notes:
            transaction.SetNotes(tx_data.gnucash_notes)

        # Set doclink/association if present
        if tx_data.gnucash_doclink:
            try:
                transaction.SetDocLink(tx_data.gnucash_doclink)
            except AttributeError:
                with contextlib.suppress(AttributeError):
                    transaction.SetAssociation(tx_data.gnucash_doclink)

        # Create splits
        for posting in tx_data.postings:
            # Get original GnuCash account name from mapping
            gnucash_account_name = account_mapping.get(posting.account)
            if not gnucash_account_name:
                raise ValueError(
                    f"Account {posting.account} not found in account mapping"
                )

            account = self.repository.get_account(gnucash_account_name)
            if not account:
                raise ValueError(f"Account {gnucash_account_name} not found in GnuCash")

            # Get account commodity
            account_commodity = account.GetCommodity()

            # Create split
            split = Split(book)
            split.SetParent(transaction)
            split.SetAccount(account)

            # Set amount
            amount = string_to_gnc_numeric(posting.amount, account_commodity)
            split.SetAmount(amount)
            split.SetValue(amount)

            # Set memo and action if present
            if posting.gnucash_memo:
                split.SetMemo(posting.gnucash_memo)
            if posting.gnucash_action:
                split.SetAction(posting.gnucash_action)

        transaction.CommitEdit()
        return transaction
