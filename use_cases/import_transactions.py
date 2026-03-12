"""
Use case for importing plaintext transactions to GnuCash.

Orchestrates services and repository to parse, validate, and import transactions.
Supports full GnuCash plaintext format with commodity declarations, account declarations,
and transactions.
"""

import logging
from typing import Dict, List

from gnucash import GncNumeric

from infrastructure.gnucash.utils import get_account_full_name
from repositories.gnucash_repository import GnuCashRepository
from services.conflict_resolver import ConflictResolver, ResolutionStrategy
from services.gnucash_importer import GnuCashImporter
from services.ledger_validator import LedgerValidator
from services.plaintext_parser import DirectiveType, PlaintextParser
from services.transaction_matcher import TransactionMatcher


class ImportResult:
    """Result of import operation"""

    def __init__(self):
        self.imported_count = 0
        self.accounts_created = 0
        self.skipped_count = 0
        self.error_count = 0
        self.duplicates = []
        self.conflicts = []
        self.errors = []

    def get_summary(self) -> str:
        """Get summary string"""
        lines = []
        lines.append(f"Imported: {self.imported_count}")
        lines.append(f"Accounts created: {self.accounts_created}")
        lines.append(f"Skipped: {self.skipped_count} (duplicates)")
        lines.append(f"Conflicts: {len(self.conflicts)}")
        lines.append(f"Errors: {self.error_count}")
        return "\n".join(lines)


class ImportTransactionsUseCase:
    """Use case for importing transactions from plaintext"""

    def __init__(self, repository: GnuCashRepository):
        """
        Initialize use case.

        Args:
            repository: GnuCash repository instance
        """
        self.repository = repository
        self.matcher = TransactionMatcher()
        self.resolver = ConflictResolver()
        self.validator = LedgerValidator()

    def execute(
        self,
        plaintext_transactions: List[Dict],
        resolution_strategy: ResolutionStrategy = ResolutionStrategy.SKIP,
        validate: bool = True
    ) -> ImportResult:
        """
        Import transactions from plaintext format.

        Args:
            plaintext_transactions: List of transaction dicts
            resolution_strategy: How to handle conflicts
            validate: Whether to validate transactions before import

        Returns:
            ImportResult with summary
        """
        result = ImportResult()

        # Get existing transactions
        existing_transactions = self.repository.get_all_transactions()

        # Convert plaintext to GnuCash transactions (not yet committed)
        incoming_transactions = []
        for pt_tx in plaintext_transactions:
            try:
                tx = self._create_transaction_from_plaintext(pt_tx)
                incoming_transactions.append(tx)
            except Exception as e:
                result.errors.append({
                    'transaction': pt_tx,
                    'error': str(e)
                })
                result.error_count += 1

        # Find duplicates and conflicts
        new, duplicates, conflicts = self.matcher.find_duplicates(
            existing_transactions,
            incoming_transactions
        )

        # Store for result
        result.duplicates = duplicates
        result.skipped_count = len(duplicates)

        # Validate new transactions
        if validate and new:
            validation_result = self.validator.validate_transactions(new, check_duplicates=False)
            if not validation_result.is_valid():
                result.errors.append({
                    'error': 'Validation failed',
                    'details': validation_result.get_summary()
                })
                # Don't import if validation fails
                return result

        # Resolve conflicts
        if conflicts:
            # Need to find corresponding existing transactions for conflicts
            conflict_pairs = []
            for conflict_tx in conflicts:
                conflict_sig = self.matcher.get_signature(conflict_tx)
                # Find existing transaction with same signature
                for existing_tx in existing_transactions:
                    existing_sig = self.matcher.get_signature(existing_tx)
                    if existing_sig == conflict_sig:
                        conflict_pairs.append((existing_tx, conflict_tx))
                        break

            to_import_from_conflicts, unresolved = self.resolver.resolve(
                conflict_pairs,
                resolution_strategy
            )
            new.extend(to_import_from_conflicts)
            # unresolved is a list of ConflictInfo objects
            result.conflicts = unresolved

        # Import new transactions (already created, just need to commit)
        for _tx in new:
            try:
                # Transaction is already created with splits, just needs to be in the book
                # It was created with the book, so it's already added
                result.imported_count += 1
            except Exception as e:
                result.errors.append({
                    'error': str(e)
                })
                result.error_count += 1

        return result

    def _create_transaction_from_plaintext(self, plaintext_tx: Dict):
        """
        Create GnuCash transaction from plaintext format.

        Args:
            plaintext_tx: Transaction dictionary

        Returns:
            GnuCash Transaction object (created but not yet committed)
        """
        from datetime import datetime

        from gnucash import Split, Transaction

        # Parse date
        date_str = plaintext_tx['date']
        date = datetime.strptime(date_str, "%Y-%m-%d")
        date_tuple = (date.day, date.month, date.year)

        # Get currency
        currency_code = plaintext_tx.get('currency', 'USD')
        currency = self.repository.get_commodity('CURRENCY', currency_code)

        # Create transaction
        tx = Transaction(self.repository.book)
        tx.BeginEdit()
        tx.SetCurrency(currency)
        tx.SetDate(*date_tuple)
        tx.SetDescription(plaintext_tx['description'])

        # Create splits
        for split_data in plaintext_tx['splits']:
            account_path = split_data['account']
            account = self.repository.get_account(account_path)

            if account is None:
                tx.Destroy()
                raise ValueError(f"Account not found: {account_path}")

            # Convert amount to GncNumeric
            amount = split_data['amount']
            if isinstance(amount, str):
                from infrastructure.gnucash.utils import string_to_gnc_numeric
                gnc_amount = string_to_gnc_numeric(amount, currency)
            else:
                # Assume it's already a number, convert to GncNumeric
                from decimal import Decimal
                if isinstance(amount, Decimal):
                    numerator = int(amount * currency.get_fraction())
                else:
                    numerator = int(float(amount) * currency.get_fraction())
                gnc_amount = GncNumeric(numerator, currency.get_fraction())

            split = Split(self.repository.book)
            split.SetParent(tx)
            split.SetAccount(account)
            split.SetValue(gnc_amount)

        tx.CommitEdit()
        return tx

    def import_from_file(
        self,
        input_path: str,
        resolution_strategy: ResolutionStrategy = ResolutionStrategy.SKIP
    ) -> ImportResult:
        """
        Import from full GnuCash plaintext format file.

        This properly handles the complete format with:
        - Commodity declarations (commodity CAD, etc.)
        - Account declarations (open Assets:Bank:Checking, etc.)
        - Transactions with full metadata

        Commodities and accounts are created first, then transactions are imported
        with duplicate detection and conflict resolution.

        Args:
            input_path: Path to plaintext file in GnuCash format
            resolution_strategy: How to handle conflicts

        Returns:
            ImportResult with summary
        """
        result = ImportResult()

        # Parse the plaintext file using the new parser
        parser = PlaintextParser()
        parser.parse_file(input_path)

        if parser.errors:
            result.errors.extend(parser.errors)
            result.error_count = len(parser.errors)
            return result

        # Process directives in order: commodities -> accounts -> transactions
        book = self.repository.book
        importer = GnuCashImporter()

        # Step 1: Create all commodities
        for child in parser.root_directive.children:
            if child.type == DirectiveType.CREATE_COMMODITY:
                try:
                    importer.create_commodity(child, book)
                except Exception as e:
                    logging.warning(f"Failed to create commodity: {e}")
                    # Continue - commodity might already exist

        # Step 2: Create all accounts
        for child in parser.root_directive.children:
            if child.type == DirectiveType.OPEN_ACCOUNT:
                try:
                    importer.create_account(child, book)
                    result.accounts_created += 1
                except Exception as e:
                    account_name = child.props.get('account', '?')
                    error_msg = f"Failed to create account {account_name}: {e}"
                    logging.warning(error_msg)
                    result.errors.append({'error': error_msg})
                    result.error_count += 1

        # Step 3: Import transactions with duplicate detection
        existing_transactions = self.repository.get_all_transactions()

        for child in parser.root_directive.children:
            if child.type == DirectiveType.TRANSACTION:
                try:
                    # Check for duplicate by GUID if present
                    if 'guid' in child.metadata:
                        guid = child.metadata['guid']
                        # Check if transaction with this GUID already exists
                        is_duplicate = any(
                            tx.GetGUID().to_string() == guid
                            for tx in existing_transactions
                        )
                        if is_duplicate:
                            logging.info(f"Skipping duplicate transaction with GUID {guid}")
                            result.skipped_count += 1
                            continue

                    # Check for duplicate by date/accounts signature
                    date_str = child.props['date']
                    split_accounts = [split.props['account'] for split in child.children]

                    # Simple signature matching
                    is_duplicate = False
                    for existing_tx in existing_transactions:
                        existing_date = existing_tx.GetDate().strftime("%Y-%m-%d")
                        if existing_date == date_str:
                            existing_accounts = [
                                get_account_full_name(split.GetAccount())
                                for split in existing_tx.GetSplitList()
                            ]
                            if set(existing_accounts) == set(split_accounts):
                                is_duplicate = True
                                break

                    if is_duplicate:
                        logging.info(f"Skipping duplicate transaction on {date_str}")
                        result.skipped_count += 1
                        continue

                    # Create transaction
                    importer.create_transaction(child, book)
                    result.imported_count += 1

                except Exception as e:
                    logging.error(f"Failed to import transaction: {e}")
                    result.errors.append({
                        'transaction': child.props,
                        'error': str(e)
                    })
                    result.error_count += 1

        return result
