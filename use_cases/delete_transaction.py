"""
Use case for deleting a single transaction by its GnuCash GUID.

Before deleting, the transaction is exported to plaintext so the caller can
present a copy to the user for safe-keeping (undo by re-importing).

Fails immediately with ValueError if the GUID is not found in the book.
Only transactions can be deleted — not accounts or commodities.
"""

from dataclasses import dataclass

from repositories.gnucash_repository import GnuCashRepository
from use_cases.export_transactions import ExportTransactionsUseCase


@dataclass
class DeleteTransactionResult:
    """Result of the delete-transactions use case (single tx)."""
    guid: str
    description: str
    date: str
    plaintext: str  # Plaintext export of the deleted transaction (for undo)


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

        # Export before deletion so the caller has an undo copy
        exporter = ExportTransactionsUseCase(self.repository)
        export_result = exporter.execute_by_guid(guid)
        plaintext = exporter.format_as_plaintext(export_result)

        self.repository.delete_transaction(target)

        return DeleteTransactionResult(
            guid=guid,
            description=description,
            date=date,
            plaintext=plaintext,
        )
