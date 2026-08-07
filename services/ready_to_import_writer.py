from __future__ import annotations

from decimal import Decimal

from infrastructure.pdf.standard_tx import Split, StandardTransaction
from services.gnucash_fuzzy_matcher import MatchResult, MatchStatus
from services.reconcile_preview_writer import DOC_LINK_BASE

AUTOPAY_ACCOUNT = "Reconcile:Autopay"


class ReadyToImportWriter:
    """Writes ready-to-import.txt from the four output buckets.

    Sections:
    - NEW: live importable blocks
    - PARTIAL_MATCH: EXISTING + GENERATED commented; SUGGESTED MERGE live with guid
    - LIKELY_DUP: fully commented (already in GnuCash, no action needed)
    - UNRESOLVED: [DO NOT IMPORT] header, fully commented
    """

    doc_link_base: str = DOC_LINK_BASE

    def write(
        self,
        path: str,
        new: list[StandardTransaction],
        likely_dup: list[MatchResult],
        partial_match: list[MatchResult],
        unresolved: list[StandardTransaction],
    ) -> None:
        with open(path, "w", encoding="utf-8") as f:
            f.write(";; ===== NEW — ready to import =====\n\n")
            for tx in new:
                _assert_no_autopay(tx)
                _write_live(f, tx, self.doc_link_base)

            f.write(";; ===== PARTIAL MATCH — review merged suggestion =====\n\n")
            for result in partial_match:
                if result.status != MatchStatus.PARTIAL_MATCH:
                    raise ValueError(f"Expected PARTIAL_MATCH, got {result.status}")
                if result.existing is None or result.merged_tx is None:
                    raise ValueError("PARTIAL_MATCH result must have existing and merged_tx")
                _assert_no_autopay(result.merged_tx)
                _write_partial_match(f, result, self.doc_link_base)

            f.write(";; ===== LIKELY DUPLICATE — already in GnuCash =====\n\n")
            for result in likely_dup:
                f.write(f";; LIKELY DUPLICATE — already in GnuCash (guid: {result.existing.guid})\n")
                display_tx = StandardTransaction(
                    post_date=result.existing.post_date,
                    description=result.existing.description,
                    currency="HKD",
                    splits=[Split(a, amt) for a, amt in result.existing.splits],
                    guid=result.existing.guid,
                )
                _write_commented_tx(f, display_tx, result.existing.doc_link or "", self.doc_link_base)
                f.write("\n")

            f.write(";; ===== UNRESOLVED — DO NOT IMPORT =====\n\n")
            for tx in unresolved:
                f.write(";; [UNRESOLVED — DO NOT IMPORT]\n")
                f.write(";; Missing statement: the other side of this autopay was not provided.\n")
                f.write(";; Re-run with the missing PDF to resolve.\n")
                _write_commented_tx(f, tx, "", self.doc_link_base)
                f.write("\n")


def _assert_no_autopay(tx: StandardTransaction) -> None:
    for split in tx.splits:
        if split.account == AUTOPAY_ACCOUNT:
            raise ValueError(
                f"Transaction '{tx.description}' contains {AUTOPAY_ACCOUNT} "
                f"— must not be written as a live importable block"
            )


def _write_live(f, tx: StandardTransaction, doc_link_base: str) -> None:
    desc = tx.description.replace('"', '\\"')
    f.write(f'{tx.post_date.strftime("%Y-%m-%d")} * "{desc}"\n')
    if tx.guid:
        f.write(f'\tguid: "{tx.guid}"\n')
    if tx.source_pdfs:
        f.write(f'\tdoc_link: "{doc_link_base}/{tx.source_pdfs[0]}"\n')
    f.write(f'\tcurrency.mnemonic: "{tx.currency}"\n')
    for split in tx.splits:
        f.write(f'\t{split.account} {_fmt(split.amount)} {tx.currency}\n')
    f.write("\n")


def _write_commented_tx(
    f, tx: StandardTransaction, explicit_doc_link: str, doc_link_base: str
) -> None:
    desc = tx.description.replace('"', '\\"')
    f.write(f';; {tx.post_date.strftime("%Y-%m-%d")} * "{desc}"\n')
    if tx.guid:
        f.write(f';;     guid: "{tx.guid}"\n')
    if explicit_doc_link:
        f.write(f';;     doc_link: "{explicit_doc_link}"\n')
    elif tx.source_pdfs:
        f.write(f';;     doc_link: "{doc_link_base}/{tx.source_pdfs[0]}"\n')
    f.write(f';;     currency.mnemonic: "{tx.currency}"\n')
    for split in tx.splits:
        f.write(f';;     {split.account} {_fmt(split.amount)} {tx.currency}\n')


def _write_partial_match(f, result: MatchResult, doc_link_base: str) -> None:
    existing = result.existing
    merged = result.merged_tx
    candidate_doc = (
        f"{doc_link_base}/{merged.source_pdfs[0]}" if merged.source_pdfs else ""
    )

    existing_display = StandardTransaction(
        post_date=existing.post_date,
        description=existing.description,
        currency=merged.currency,
        splits=[Split(a, amt) for a, amt in existing.splits],
        guid=existing.guid,
    )
    candidate_display = StandardTransaction(
        post_date=merged.post_date,
        description=merged.description,
        currency=merged.currency,
        splits=merged.splits,
        source_pdfs=merged.source_pdfs,
    )

    f.write(";; EXISTING (GnuCash):\n")
    _write_commented_tx(f, existing_display, existing.doc_link, doc_link_base)

    f.write(";; GENERATED (statement):\n")
    _write_commented_tx(f, candidate_display, candidate_doc, doc_link_base)

    f.write(";; SUGGESTED MERGE (edit if needed, then import):\n")
    _write_live(f, merged, doc_link_base)


def _fmt(amount: Decimal) -> str:
    """The amount exactly as the statement stated it — see
    `reconcile_preview_writer._format_amount`: the parsed Decimal already
    carries its currency's scale, and forcing two decimals would invent
    hundredths for a currency that has none."""
    return format(amount, 'f')
