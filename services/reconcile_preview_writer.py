from __future__ import annotations

from decimal import Decimal

from infrastructure.gnucash.utils import escape_string
from infrastructure.pdf.standard_tx import StandardTransaction

AUTOPAY_ACCOUNT = "Reconcile:Autopay"
DOC_LINK_BASE = "bank_statements"


class ReconcilePreviewWriter:
    """Writes _reconcile.txt from the three StatementReconciler output buckets.

    Format:
      - Section headers are ;; comment lines (human-readable, not parsed by reader)
      - Transaction blocks: date line, tab-indented metadata and splits, blank line
      - doc_link uses source_pdfs[0] (card PDF for merged autopay, only PDF otherwise)
    """

    doc_link_base: str = DOC_LINK_BASE

    def write(
        self,
        path: str,
        resolved: list[StandardTransaction],
        unresolved: list[StandardTransaction],
        normal: list[StandardTransaction],
    ) -> None:
        with open(path, "w", encoding="utf-8") as f:
            f.write(";; ===== RESOLVED =====\n")
            f.write(";; Transactions where Reconcile:Autopay was matched across statements\n\n")
            for tx in resolved:
                _write_tx(f, tx, self.doc_link_base)

            f.write(";; ===== NORMAL =====\n")
            f.write(";; Regular transactions with no autopay involvement\n\n")
            for tx in normal:
                _write_tx(f, tx, self.doc_link_base)

            f.write(";; ===== UNRESOLVED =====\n")
            f.write(";; Transactions still containing Reconcile:Autopay — re-run with missing PDF\n\n")
            for tx in unresolved:
                _write_tx(f, tx, self.doc_link_base)


def _write_tx(f, tx: StandardTransaction, doc_link_base: str) -> None:
    # As `ready_to_import_writer` does it: the escapes the reader undoes.
    desc = escape_string(tx.description)
    f.write(f'{tx.post_date.strftime("%Y-%m-%d")} * "{desc}"\n')

    if tx.guid:
        f.write(f'\tguid: "{tx.guid}"\n')

    if tx.source_pdfs:
        f.write(f'\tdoc_link: "{doc_link_base}/{tx.source_pdfs[0]}"\n')

    f.write(f'\tcurrency.mnemonic: "{tx.currency}"\n')

    for split in tx.splits:
        amount_str = _format_amount(split.amount)
        f.write(f'\t{split.account} {amount_str} {tx.currency}\n')

    f.write("\n")


def _format_amount(amount: Decimal) -> str:
    """The amount exactly as the statement stated it.

    A statement line is already written in its own currency's decimals — two
    for a dollar, none for a yen — and the parsed Decimal carries that scale.
    Forcing two here would invent hundredths for currencies that have none and
    silently restate the figure; `f` prints the Decimal plainly, without
    exponent notation and without changing its scale.
    """
    return format(amount, 'f')
