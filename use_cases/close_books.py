"""
Use case for closing books at fiscal year end.

Orchestrates BookCloser service and GnuCashRepository to:
- Zero out all Income/Expense account balances as of the closing date
- Create one closing transaction per currency
- Auto-create Equity:Retained Earnings:{currency} accounts
- Support --force to re-close and --dry-run to preview
"""

from dataclasses import dataclass, field
from datetime import date
from typing import List, Set

from gnucash import Transaction

from repositories.gnucash_repository import GnuCashRepository
from services.book_closer import BookCloser


class AlreadyClosedError(Exception):
    """Raised when books are already closed and --force was not specified"""
    pass


class NothingToCloseError(Exception):
    """Raised when all Income/Expense accounts already have zero balance"""
    pass


@dataclass
class CloseBooksResult:
    """Result of a close books operation"""
    closing_date: date
    currencies_closed: List[str] = field(default_factory=list)
    transactions_created: List[Transaction] = field(default_factory=list)
    equity_accounts_created: List[str] = field(default_factory=list)
    dry_run: bool = False

    def get_summary(self) -> str:
        lines = []
        if self.dry_run:
            lines.append(f"DRY RUN - Books would be closed as of {self.closing_date}")
        else:
            lines.append(f"Books closed as of {self.closing_date}")

        if self.currencies_closed:
            lines.append(f"Currencies closed: {', '.join(sorted(self.currencies_closed))}")
            if not self.dry_run:
                lines.append(f"Closing transactions created: {len(self.transactions_created)}")
        else:
            lines.append("No Income/Expense balances found — nothing to close")

        if self.equity_accounts_created:
            lines.append(f"Equity accounts created: {', '.join(self.equity_accounts_created)}")

        return "\n".join(lines)


class CloseBooksUseCase:
    """Use case for closing books at fiscal year end"""

    def __init__(self, repository: GnuCashRepository):
        self.repository = repository
        self.book_closer = BookCloser()

    def check_status(self, closing_date: date) -> bool:
        """
        Check if books are closed as of closing_date without making changes.

        Returns:
            True if all Income/Expense accounts have zero balance as of closing_date
        """
        root = self.repository.get_root_account()
        return self.book_closer.is_closed(root, closing_date)

    def execute(
        self,
        closing_date: date,
        equity_template: str = "Equity:Retained Earnings",
        force: bool = False,
        dry_run: bool = False,
    ) -> CloseBooksResult:
        """
        Close books as of closing_date.

        Zeroes out ALL Income/Expense account balances cumulatively up to and
        including closing_date. Creates one closing transaction per currency.

        Args:
            closing_date: Date to close books (all history up to this date is closed)
            equity_template: Base path for retained earnings accounts
                             (e.g., "Equity:Retained Earnings" → creates
                              "Equity:Retained Earnings:CAD" per currency)
            force: If True, delete existing closing transactions and re-close
            dry_run: If True, preview what would be closed without making changes

        Returns:
            CloseBooksResult with details of what was (or would be) done

        Raises:
            AlreadyClosedError: Books already closed and force=False
        """
        root = self.repository.get_root_account()

        # Check if already closed
        already_closed = self.book_closer.is_closed(root, closing_date)

        if already_closed and not force:
            raise AlreadyClosedError(
                f"Books are already closed as of {closing_date}. "
                "Use --force to delete existing closing entries and re-close."
            )

        # For --force: identify existing closing transactions to exclude/delete
        exclude_guids: Set[str] = set()
        if already_closed and force:
            closing_txns = self.book_closer.find_closing_transactions(root, closing_date)
            exclude_guids = {tx.GetGUID().to_string() for tx in closing_txns}

            if not dry_run:
                # Delete existing closing transactions before re-closing
                for tx in closing_txns:
                    self.repository.delete_transaction(tx)
                exclude_guids = set()  # No need to exclude after deletion

        # Compute which accounts need closing (excluding prior closing transactions
        # when doing a force dry-run, so we see what would happen post-deletion)
        accounts_by_currency = self.book_closer.group_accounts_by_currency(
            root, closing_date, exclude_guids=exclude_guids if dry_run else None
        )

        result = CloseBooksResult(closing_date=closing_date, dry_run=dry_run)

        if not accounts_by_currency:
            return result

        book = self.repository.book

        for currency_code, account_balances in accounts_by_currency.items():
            result.currencies_closed.append(currency_code)

            if dry_run:
                continue

            # Get or create equity account for this currency
            equity_account, was_created = self.book_closer.get_or_create_equity_account(
                book, root, equity_template, currency_code
            )
            if was_created:
                result.equity_accounts_created.append(
                    f"{equity_template}:{currency_code}"
                )

            # Create the closing transaction
            tx = self.book_closer.create_closing_transaction(
                book, closing_date, currency_code, account_balances, equity_account
            )
            result.transactions_created.append(tx)

        return result
