"""
Use case for validating GnuCash ledger.

Orchestrates validation services to check ledger integrity.
"""

from typing import Optional

from repositories.gnucash_repository import GnuCashRepository
from services.ledger_validator import LedgerValidator, ValidationResult
from services.transaction_matcher import TransactionMatcher


class ValidateLedgerUseCase:
    """Use case for comprehensive ledger validation"""

    def __init__(self, repository: GnuCashRepository):
        """
        Initialize use case.

        Args:
            repository: GnuCash repository instance
        """
        self.repository = repository
        self.validator = LedgerValidator()
        self.matcher = TransactionMatcher()

    def execute(
        self,
        check_duplicates: bool = True,
        check_date_order: bool = True,
        check_future_dates: bool = True
    ) -> ValidationResult:
        """
        Validate entire ledger.

        Args:
            check_duplicates: Whether to check for duplicate transactions
            check_date_order: Whether to check transaction date order
            check_future_dates: Whether to check for future dates

        Returns:
            ValidationResult with all issues found
        """
        root = self.repository.get_root_account()
        transactions = self.repository.get_all_transactions()

        # Full ledger validation
        result = self.validator.validate_ledger(root, transactions)

        # Additional checks
        if check_duplicates:
            dup_count = self.matcher.get_duplicate_count(transactions)
            if dup_count > 0:
                result.add_warning(
                    "DUPLICATES_DETECTED",
                    f"Found {dup_count} duplicate transaction(s)",
                    {'count': dup_count}
                )

        if check_date_order:
            order_result = self.validator.check_transaction_date_order(transactions)
            result.errors.extend(order_result.errors)
            result.warnings.extend(order_result.warnings)
            result.info.extend(order_result.info)

        if check_future_dates:
            future_result = self.validator.check_future_transactions(transactions)
            result.errors.extend(future_result.errors)
            result.warnings.extend(future_result.warnings)
            result.info.extend(future_result.info)

        return result

    def validate_and_report(
        self,
        output_path: Optional[str] = None
    ) -> ValidationResult:
        """
        Validate ledger and generate report.

        Args:
            output_path: Optional path to write report file

        Returns:
            ValidationResult
        """
        result = self.execute()
        report = self.validator.format_validation_report(result)

        if output_path:
            with open(output_path, 'w') as f:
                f.write(report)
        else:
            print(report)

        return result

    def quick_check(self) -> bool:
        """
        Quick validation check.

        Returns:
            True if ledger is valid (no errors)
        """
        result = self.execute(
            check_duplicates=True,
            check_date_order=False,
            check_future_dates=False
        )
        return result.is_valid()

    def get_statistics(self) -> dict:
        """
        Get ledger statistics with validation status.

        Returns:
            Dictionary with stats and validation info
        """
        stats = self.repository.get_statistics()
        result = self.execute()

        stats['validation'] = {
            'is_valid': result.is_valid(),
            'error_count': len(result.errors),
            'warning_count': len(result.warnings),
            'info_count': len(result.info)
        }

        return stats
