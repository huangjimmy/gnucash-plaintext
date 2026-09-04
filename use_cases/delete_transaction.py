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
class APreparedDelete:
    """One transaction read and written out, and not yet deleted.

    `plaintext` is the undo copy, and what it states about a cost basis is
    true of the book as it stands. Deleting a sale gives its currency back to
    the basis it drew on, so a transaction written out after a sibling's
    deletion states a balance the book no longer had when the command began —
    and the undo copy, re-imported, then leaves the book offering currency its
    bank does not hold. So every transaction a run deletes is written out
    before any of them goes.

    The transaction itself is not held here, only its guid, and `carry_out`
    looks it up again. A guid named twice in one run is prepared twice, and a
    kept wrapper would be a pointer to a transaction the first deletion had
    already freed — read, written and destroyed a second time.
    """
    guid: str
    description: str
    date: str
    plaintext: str
    undo_copy_error: Optional[str]


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
        return self.carry_out(self.prepare(guid))

    def prepare(self, guid: str) -> APreparedDelete:
        """Read the transaction and write the undo copy. Nothing is deleted.

        A caller deleting several transactions prepares all of them first, so
        that no undo copy states a cost basis balance a sibling's deletion has
        already changed.

        Raises:
            ValueError: If no transaction with the given GUID exists in the book.
        """
        target = self._the_one_the_book_holds(guid)
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

        return APreparedDelete(
            guid=guid,
            description=description,
            date=date,
            plaintext=plaintext,
            undo_copy_error=undo_copy_error,
        )

    def _the_one_the_book_holds(self, guid: str):
        transactions = self.repository.get_all_transactions()
        target = next(
            (tx for tx in transactions if tx.GetGUID().to_string() == guid),
            None,
        )
        if target is None:
            raise ValueError(f"Transaction GUID {guid!r} not found in book")
        return target

    def carry_out(self, prepared: APreparedDelete) -> DeleteTransactionResult:
        """Delete a transaction already written out by `prepare`.

        Looked up again rather than kept from `prepare`, so that a guid named
        twice in one run is refused the second time by the book rather than
        destroyed twice.

        Raises:
            ValueError: If the book no longer holds it, or if a cost basis in
                it is still measured against.
        """
        target = self._the_one_the_book_holds(prepared.guid)

        # Q-035: a transaction that establishes a cost basis cannot go while
        # anything still measures against it — that split *is* the basis.
        require_no_cost_basis_dependents(
            self.repository.book, target,
            f'{prepared.date} {prepared.description!r}')

        # And read what this transaction takes from each cost basis before it
        # goes, so those amounts can be given back — deleting a sale returns
        # its currency to the basis it was measured against.
        taken = amounts_by_cost_basis(target)

        self.repository.delete_transaction(target)

        give_back_to_cost_bases(self.repository.book, taken)

        return DeleteTransactionResult(
            guid=prepared.guid,
            description=prepared.description,
            date=prepared.date,
            plaintext=prepared.plaintext,
            undo_copy_error=prepared.undo_copy_error,
        )
