"""
Use case for deleting a single transaction by its GnuCash GUID.

Before deleting, the transaction is exported to plaintext so the caller can
present a copy to the user for safe-keeping (undo by re-importing).

Fails immediately with ValueError if the GUID is not found in the book.
Only transactions can be deleted — not accounts or commodities.
"""

from dataclasses import dataclass
from typing import Optional

from repositories.gnucash_repository import GnuCashRepository
from services.foreign_currency import (
    amounts_by_cost_basis,
    give_back_to_cost_bases,
    require_no_cost_basis_dependents,
)
from use_cases.export_transactions import (
    ExportTransactionsUseCase,
    UnwritableFigureError,
)


@dataclass
class DeleteTransactionResult:
    """Result of the delete-transactions use case (single tx)."""
    guid: str
    description: str
    date: str
    plaintext: str  # Plaintext export of the deleted transaction (for undo)
    # Why no re-importable copy could be made, when that is the case. The
    # transaction is deleted either way; `plaintext` then holds a commented
    # note instead of a transaction block, and the caller says so.
    undo_copy_error: Optional[str] = None


class DeleteTransactionUseCase:
    """Delete a single transaction identified by its GnuCash GUID."""

    def __init__(self, repository: GnuCashRepository):
        self.repository = repository

    def execute(self, guid: str) -> DeleteTransactionResult:
        """
        Export then delete the transaction with the given GUID.

        The plaintext export is produced before deletion so the caller can
        write it to stdout or a file, giving the user a copy they can
        re-import to undo the deletion.

        Args:
            guid: GnuCash transaction GUID (32 hex characters).

        Returns:
            DeleteTransactionResult including the pre-deletion plaintext export.

        Raises:
            ValueError: If no transaction with the given GUID exists in the book.
        """
        transactions = self.repository.get_all_transactions()
        target = next(
            (tx for tx in transactions if tx.GetGUID().to_string() == guid),
            None,
        )
        if target is None:
            raise ValueError(f"Transaction GUID {guid!r} not found in book")

        description = target.GetDescription()
        date = target.GetDate().strftime("%Y-%m-%d")

        # Export before deletion so the caller has an undo copy.
        #
        # A transaction plaintext cannot state does not get to be undeletable.
        # A book holding a figure finer than its currency is exactly the book
        # someone reaches for `delete-transactions` to fix, and refusing here
        # left them no remedy inside the tool at all: `export` refuses it,
        # and the deletion refused it for the same reason, one step removed.
        # So the copy is what is lost, not the command — and loudly, in the
        # place the copy would have been and again on the result, because a
        # deletion with no way back is the caller's decision to have made.
        exporter = ExportTransactionsUseCase(self.repository)
        export_result = exporter.execute_by_guid(guid)
        undo_copy_error = None
        try:
            plaintext = exporter.format_as_plaintext(export_result)
        except UnwritableFigureError as exc:
            undo_copy_error = str(exc)
            # Every line commented, the refusal's own included: it names one
            # split per line, and a bare continuation line in a backup file
            # is a parse error waiting for whoever re-imports the rest.
            reason = '\n'.join(f'#   {line}'
                               for line in undo_copy_error.splitlines())
            plaintext = (
                f'# No undo copy could be written for {date} '
                f'{description!r} ({guid}).\n'
                f'{reason}\n'
                f'# The transaction was deleted anyway. Re-creating it means '
                f'entering it in GnuCash.\n')

        # Q-035: a transaction that establishes a cost basis cannot go while
        # anything still measures against it — that split *is* the basis.
        require_no_cost_basis_dependents(
            self.repository.book, target, f'{date} {description!r}')

        # And read what this transaction takes from each cost basis before it
        # goes, so those amounts can be given back — deleting a sale returns
        # its currency to the basis it was measured against.
        taken = amounts_by_cost_basis(target)

        self.repository.delete_transaction(target)

        give_back_to_cost_bases(self.repository.book, taken)

        return DeleteTransactionResult(
            guid=guid,
            description=description,
            date=date,
            plaintext=plaintext,
            undo_copy_error=undo_copy_error,
        )
