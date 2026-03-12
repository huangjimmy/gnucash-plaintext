"""
Ledger validation service for GnuCash data.

Validates transactions, accounts, and overall ledger integrity.
Detects common errors and inconsistencies in GnuCash data.
"""

from datetime import datetime
from typing import Dict, List, Optional

from gnucash import Account, Split, Transaction


class ValidationError:
    """Represents a validation error"""

    def __init__(
        self,
        severity: str,
        code: str,
        message: str,
        context: Optional[Dict] = None
    ):
        """
        Initialize validation error.

        Args:
            severity: Error severity (ERROR, WARNING, INFO)
            code: Error code for programmatic handling
            message: Human-readable error message
            context: Additional context (transaction ID, account name, etc.)
        """
        self.severity = severity
        self.code = code
        self.message = message
        self.context = context or {}

    def __repr__(self):
        return f"ValidationError({self.severity}, {self.code}, {self.message})"

    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return {
            'severity': self.severity,
            'code': self.code,
            'message': self.message,
            'context': self.context
        }


class ValidationResult:
    """Results from validation"""

    def __init__(self):
        """Initialize validation result"""
        self.errors = []
        self.warnings = []
        self.info = []

    def add_error(self, code: str, message: str, context: Optional[Dict] = None):
        """Add an error"""
        self.errors.append(ValidationError("ERROR", code, message, context))

    def add_warning(self, code: str, message: str, context: Optional[Dict] = None):
        """Add a warning"""
        self.warnings.append(ValidationError("WARNING", code, message, context))

    def add_info(self, code: str, message: str, context: Optional[Dict] = None):
        """Add an info message"""
        self.info.append(ValidationError("INFO", code, message, context))

    def has_errors(self) -> bool:
        """Check if there are any errors"""
        return len(self.errors) > 0

    def has_warnings(self) -> bool:
        """Check if there are any warnings"""
        return len(self.warnings) > 0

    def is_valid(self) -> bool:
        """Check if validation passed (no errors)"""
        return not self.has_errors()

    def get_all_issues(self) -> List[ValidationError]:
        """Get all issues (errors, warnings, info)"""
        return self.errors + self.warnings + self.info

    def get_summary(self) -> str:
        """Get summary string"""
        if self.is_valid() and not self.has_warnings():
            return "Validation passed with no issues."

        lines = []
        if self.errors:
            lines.append(f"{len(self.errors)} error(s)")
        if self.warnings:
            lines.append(f"{len(self.warnings)} warning(s)")
        if self.info:
            lines.append(f"{len(self.info)} info message(s)")

        return f"Validation completed: {', '.join(lines)}"


class LedgerValidator:
    """Service for validating GnuCash ledger data"""

    def __init__(self):
        """Initialize ledger validator"""
        pass

    def validate_transaction(self, transaction: Transaction) -> ValidationResult:
        """
        Validate a single transaction.

        Args:
            transaction: Transaction to validate

        Returns:
            ValidationResult with any issues found
        """
        result = ValidationResult()

        # Check description
        desc = transaction.GetDescription()
        if not desc or desc.strip() == "":
            result.add_warning(
                "EMPTY_DESCRIPTION",
                "Transaction has empty description",
                {'guid': transaction.GetGUID().to_string()}
            )

        # Check date
        date = transaction.GetDate()
        if date is None:
            result.add_error(
                "MISSING_DATE",
                "Transaction has no date",
                {'guid': transaction.GetGUID().to_string()}
            )

        # Check splits
        splits = transaction.GetSplitList()
        if len(splits) == 0:
            result.add_error(
                "NO_SPLITS",
                "Transaction has no splits",
                {
                    'guid': transaction.GetGUID().to_string(),
                    'description': desc
                }
            )
        elif len(splits) == 1:
            result.add_warning(
                "SINGLE_SPLIT",
                "Transaction has only one split",
                {
                    'guid': transaction.GetGUID().to_string(),
                    'description': desc
                }
            )

        # Check if transaction is balanced
        if len(splits) > 0 and not self._is_transaction_balanced(splits):
            result.add_error(
                "UNBALANCED",
                "Transaction is not balanced",
                {
                    'guid': transaction.GetGUID().to_string(),
                    'description': desc
                }
            )

        # Check for splits without accounts
        for split in splits:
            account = split.GetAccount()
            if account is None:
                result.add_error(
                    "SPLIT_NO_ACCOUNT",
                    "Split has no account",
                    {
                        'transaction_guid': transaction.GetGUID().to_string(),
                        'description': desc
                    }
                )

        # Check currency
        currency = transaction.GetCurrency()
        if currency is None:
            result.add_error(
                "NO_CURRENCY",
                "Transaction has no currency",
                {
                    'guid': transaction.GetGUID().to_string(),
                    'description': desc
                }
            )

        return result

    def _is_transaction_balanced(self, splits: List[Split]) -> bool:
        """
        Check if splits balance to zero.

        Args:
            splits: List of splits to check

        Returns:
            True if balanced
        """
        if not splits:
            return True

        total_num = 0
        for split in splits:
            value = split.GetValue()
            total_num += value.num()

        return total_num == 0

    def validate_account(self, account: Account) -> ValidationResult:
        """
        Validate a single account.

        Args:
            account: Account to validate

        Returns:
            ValidationResult with any issues found
        """
        result = ValidationResult()

        # Check name
        name = account.GetName()
        if not name or name.strip() == "":
            result.add_error(
                "EMPTY_ACCOUNT_NAME",
                "Account has empty name",
                {'guid': account.GetGUID().to_string()}
            )

        # Check for placeholder with transactions
        if account.GetPlaceholder():
            # Placeholder accounts shouldn't have transactions
            # Note: We can't easily check this without iterating splits
            result.add_info(
                "PLACEHOLDER_ACCOUNT",
                f"Account '{name}' is a placeholder",
                {'name': name}
            )

        # Check commodity
        commodity = account.GetCommodity()
        if commodity is None:
            result.add_warning(
                "NO_COMMODITY",
                f"Account '{name}' has no commodity",
                {'name': name}
            )

        return result

    def validate_account_hierarchy(
        self,
        root_account: Account
    ) -> ValidationResult:
        """
        Validate account hierarchy consistency.

        Args:
            root_account: Root account to validate from

        Returns:
            ValidationResult with any issues found
        """
        result = ValidationResult()

        def visit(account: Account, path: List[str]):
            if not account.is_root():
                name = account.GetName()
                current_path = path + [name]

                # Check parent-child category consistency
                parent = account.get_parent()
                if parent and not parent.is_root():
                    from services.account_categorizer import AccountCategorizer
                    categorizer = AccountCategorizer()

                    parent_category = categorizer.get_category(parent)
                    account_category = categorizer.get_category(account)

                    if parent_category != account_category:
                        result.add_warning(
                            "CATEGORY_MISMATCH",
                            "Category mismatch in hierarchy",
                            {
                                'account': ':'.join(current_path),
                                'account_category': account_category,
                                'parent_category': parent_category
                            }
                        )

            # Visit children
            for child in account.get_children_sorted():
                visit(child, path + [account.GetName()] if not account.is_root() else path)

        visit(root_account, [])
        return result

    def validate_transactions(
        self,
        transactions: List[Transaction],
        check_duplicates: bool = True
    ) -> ValidationResult:
        """
        Validate a list of transactions.

        Args:
            transactions: List of transactions to validate
            check_duplicates: Whether to check for duplicates

        Returns:
            ValidationResult with any issues found
        """
        result = ValidationResult()

        for tx in transactions:
            tx_result = self.validate_transaction(tx)

            # Merge results
            result.errors.extend(tx_result.errors)
            result.warnings.extend(tx_result.warnings)
            result.info.extend(tx_result.info)

        if check_duplicates:
            # Check for duplicate transactions
            from services.transaction_matcher import TransactionMatcher
            matcher = TransactionMatcher()
            dup_count = matcher.get_duplicate_count(transactions)

            if dup_count > 0:
                result.add_warning(
                    "DUPLICATES_FOUND",
                    f"Found {dup_count} duplicate transaction(s)",
                    {'count': dup_count}
                )

        return result

    def validate_ledger(
        self,
        root_account: Account,
        transactions: List[Transaction]
    ) -> ValidationResult:
        """
        Validate entire ledger (accounts + transactions).

        Args:
            root_account: Root account
            transactions: List of all transactions

        Returns:
            ValidationResult with all issues found
        """
        result = ValidationResult()

        # Validate account hierarchy
        hierarchy_result = self.validate_account_hierarchy(root_account)
        result.errors.extend(hierarchy_result.errors)
        result.warnings.extend(hierarchy_result.warnings)
        result.info.extend(hierarchy_result.info)

        # Validate all accounts
        def visit_accounts(account: Account):
            if not account.is_root():
                account_result = self.validate_account(account)
                result.errors.extend(account_result.errors)
                result.warnings.extend(account_result.warnings)
                result.info.extend(account_result.info)

            for child in account.get_children_sorted():
                visit_accounts(child)

        visit_accounts(root_account)

        # Validate transactions
        tx_result = self.validate_transactions(transactions)
        result.errors.extend(tx_result.errors)
        result.warnings.extend(tx_result.warnings)
        result.info.extend(tx_result.info)

        return result

    def check_transaction_date_order(
        self,
        transactions: List[Transaction]
    ) -> ValidationResult:
        """
        Check if transactions are in date order.

        Args:
            transactions: List of transactions to check

        Returns:
            ValidationResult with any issues
        """
        result = ValidationResult()

        if len(transactions) <= 1:
            return result

        prev_date = None
        for tx in transactions:
            current_date = tx.GetDate()

            if prev_date and current_date < prev_date:
                result.add_info(
                    "OUT_OF_ORDER",
                    "Transactions are not in chronological order",
                    {
                        'description': tx.GetDescription(),
                        'date': current_date.strftime("%Y-%m-%d")
                    }
                )

            prev_date = current_date

        return result

    def check_future_transactions(
        self,
        transactions: List[Transaction],
        reference_date: Optional[datetime] = None
    ) -> ValidationResult:
        """
        Check for transactions with future dates.

        Args:
            transactions: List of transactions to check
            reference_date: Reference date (defaults to today)

        Returns:
            ValidationResult with any issues
        """
        result = ValidationResult()

        if reference_date is None:
            reference_date = datetime.now()

        for tx in transactions:
            tx_date = tx.GetDate()
            tx_datetime = datetime(tx_date.year, tx_date.month, tx_date.day)

            if tx_datetime > reference_date:
                result.add_info(
                    "FUTURE_DATE",
                    "Transaction has future date",
                    {
                        'description': tx.GetDescription(),
                        'date': tx_date.strftime("%Y-%m-%d")
                    }
                )

        return result

    def format_validation_report(self, result: ValidationResult) -> str:
        """
        Format validation result as human-readable report.

        Args:
            result: ValidationResult to format

        Returns:
            Formatted report string
        """
        lines = []
        lines.append("=" * 60)
        lines.append("VALIDATION REPORT")
        lines.append("=" * 60)
        lines.append("")
        lines.append(result.get_summary())
        lines.append("")

        if result.errors:
            lines.append("ERRORS:")
            lines.append("-" * 60)
            for error in result.errors:
                lines.append(f"  [{error.code}] {error.message}")
                if error.context:
                    for key, value in error.context.items():
                        lines.append(f"    {key}: {value}")
            lines.append("")

        if result.warnings:
            lines.append("WARNINGS:")
            lines.append("-" * 60)
            for warning in result.warnings:
                lines.append(f"  [{warning.code}] {warning.message}")
                if warning.context:
                    for key, value in warning.context.items():
                        lines.append(f"    {key}: {value}")
            lines.append("")

        if result.info:
            lines.append("INFO:")
            lines.append("-" * 60)
            for info in result.info:
                lines.append(f"  [{info.code}] {info.message}")
                if info.context:
                    for key, value in info.context.items():
                        lines.append(f"    {key}: {value}")
            lines.append("")

        lines.append("=" * 60)
        return "\n".join(lines)
