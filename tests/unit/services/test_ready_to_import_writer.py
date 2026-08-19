from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from infrastructure.pdf.standard_tx import Split, StandardTransaction
from services.gnucash_fuzzy_matcher import MatchResult, MatchStatus, _IndexEntry
from services.ready_to_import_writer import AUTOPAY_ACCOUNT, ReadyToImportWriter

WRITER = ReadyToImportWriter()


def _new_tx(desc: str = "AUTOPAY INGROUP", pdf: str = "boci.pdf") -> StandardTransaction:
    return StandardTransaction(
        post_date=date(2026, 4, 15),
        description=desc,
        currency="HKD",
        splits=[
            Split("Liabilities:BOCI-0012", Decimal("247.10")),
            Split("Assets:BOC HKD Saving", Decimal("-247.10")),
        ],
        source_pdfs=[pdf],
    )


def _unresolved_tx() -> StandardTransaction:
    return StandardTransaction(
        post_date=date(2026, 4, 2),
        description="BOC CREDIT CARD",
        currency="HKD",
        splits=[
            Split("Assets:BOC HKD Saving", Decimal("-125.00")),
            Split(AUTOPAY_ACCOUNT, Decimal("125.00")),
        ],
        source_pdfs=["bochk.pdf"],
    )


def _make_entry(desc: str = "AUTOPAY INGROUP", guid: str = "abc1" * 8) -> _IndexEntry:
    return _IndexEntry(
        post_date=date(2026, 4, 15),
        amount=Decimal("247.10"),
        account_names=frozenset(["Liabilities:BOCI-0012", "Expenses:Dining"]),
        asset_liability_accounts=frozenset(["Liabilities:BOCI-0012"]),
        guid=guid,
        description=desc,
        splits=[
            ("Liabilities:BOCI-0012", Decimal("247.10")),
            ("Expenses:Dining", Decimal("-247.10")),
        ],
    )


def _partial_result(candidate_pdf: str = "boci.pdf") -> MatchResult:
    existing = _make_entry()
    merged = StandardTransaction(
        post_date=date(2026, 4, 15),
        description="AUTOPAY INGROUP",
        currency="HKD",
        splits=[
            Split("Liabilities:BOCI-0012", Decimal("247.10")),
            Split("Expenses:Dining", Decimal("-247.10")),
        ],
        source_pdfs=[candidate_pdf],
        guid=existing.guid,
    )
    return MatchResult(status=MatchStatus.PARTIAL_MATCH, existing=existing, merged_tx=merged)


def _dup_result() -> MatchResult:
    return MatchResult(
        status=MatchStatus.LIKELY_DUP,
        existing=_make_entry(),
        merged_tx=None,
    )


class TestReadyToImportWriter:
    def _write(self, tmp_path: Path, new=None, likely_dup=None, partial=None, unresolved=None):
        p = str(tmp_path / "out.txt")
        WRITER.write(p, new or [], likely_dup or [], partial or [], unresolved or [])
        return Path(p).read_text(encoding="utf-8")

    def test_new_section_live_block(self, tmp_path):
        content = self._write(tmp_path, new=[_new_tx()])
        assert '2026-04-15 * "AUTOPAY INGROUP"' in content
        # The date line is a live (uncommented) transaction line
        live_date_lines = [ln for ln in content.splitlines() if ln.startswith("2026-")]
        assert len(live_date_lines) == 1

    def test_likely_dup_fully_commented(self, tmp_path):
        content = self._write(tmp_path, likely_dup=[_dup_result()])
        lines = [ln for ln in content.splitlines() if ln.strip() and "=====" not in ln]
        non_comment = [ln for ln in lines if not ln.startswith(";;")]
        assert non_comment == []

    def test_partial_match_structure(self, tmp_path):
        content = self._write(tmp_path, partial=[_partial_result()])
        assert ";; EXISTING (GnuCash):" in content
        assert ";; GENERATED (statement):" in content
        assert ";; SUGGESTED MERGE" in content
        # The MERGE block should be a live (uncommented) transaction
        assert '2026-04-15 * "AUTOPAY INGROUP"' in content

    def test_partial_match_guid_in_merge(self, tmp_path):
        content = self._write(tmp_path, partial=[_partial_result()])
        assert 'guid: "abc1abc1abc1abc1abc1abc1abc1abc1"' in content

    def test_partial_match_gnucash_category(self, tmp_path):
        content = self._write(tmp_path, partial=[_partial_result()])
        # SUGGESTED MERGE uses GnuCash's Dining, not Groceries
        assert "Expenses:Dining" in content

    def test_partial_match_generated_doc_link(self, tmp_path):
        content = self._write(tmp_path, partial=[_partial_result("boci-0012-2026-04.pdf")])
        assert 'doc_link: "bank_statements/boci-0012-2026-04.pdf"' in content

    def test_unresolved_do_not_import(self, tmp_path):
        content = self._write(tmp_path, unresolved=[_unresolved_tx()])
        assert "[UNRESOLVED — DO NOT IMPORT]" in content

    def test_unresolved_fully_commented(self, tmp_path):
        content = self._write(tmp_path, unresolved=[_unresolved_tx()])
        unresolved_lines = []
        in_section = False
        for line in content.splitlines():
            if "UNRESOLVED" in line and "=====" in line:
                in_section = True
            if in_section and line.strip():
                unresolved_lines.append(line)
        live_lines = [ln for ln in unresolved_lines if not ln.startswith(";;")]
        assert live_lines == []

    def test_no_live_reconcile_autopay(self, tmp_path):
        content = self._write(
            tmp_path,
            new=[_new_tx()],
            likely_dup=[_dup_result()],
            partial=[_partial_result()],
            unresolved=[_unresolved_tx()],
        )
        live_lines = [ln for ln in content.splitlines() if not ln.startswith(";;") and AUTOPAY_ACCOUNT in ln]
        assert live_lines == []

    def test_autopay_in_new_raises(self, tmp_path):
        with pytest.raises(ValueError, match="Reconcile:Autopay"):
            self._write(tmp_path, new=[_unresolved_tx()])

    def test_doc_link_prefix(self, tmp_path):
        content = self._write(tmp_path, new=[_new_tx(pdf="boci.pdf")])
        assert 'doc_link: "bank_statements/boci.pdf"' in content

    def test_cjk_in_output(self, tmp_path):
        content = self._write(tmp_path, new=[_new_tx(desc="自動轉賬")])
        assert "自動轉賬" in content

    def test_two_source_pdfs_uses_first(self, tmp_path):
        tx = _new_tx()
        tx.source_pdfs = ["boci.pdf", "bochk.pdf"]
        content = self._write(tmp_path, new=[tx])
        assert 'doc_link: "bank_statements/boci.pdf"' in content
        assert "bochk.pdf" not in content  # bank PDF not in doc_link

    def test_empty_all_buckets(self, tmp_path):
        content = self._write(tmp_path)
        assert "=====" in content  # section headers present
        assert content  # not empty


class TestWhatADescriptionMayHold:
    r"""This file is written to be imported, so `import` is what reads it.

    `parse_transaction_head` unescapes four characters, and a quote-only
    escape on the way out matched one of them: `C:\name` was written raw and
    came back as `C:` and a newline, and a description holding a real
    newline ended its own block, offering the rest of itself to the parser
    as a key of its own.
    """

    def _written(self, tmp_path: Path, description: str) -> str:
        path = str(tmp_path / "out.txt")
        WRITER.write(path, [_new_tx(desc=description)], [], [], [])
        return Path(path).read_text(encoding="utf-8")

    @pytest.mark.parametrize("description", [
        r"AUTOPAY C:\name",
        r'AUTOPAY "INGROUP"',
        "AUTOPAY\nsecond line",
        "AUTOPAY\rsecond line",
        r'both: "C:\name"',
    ])
    def test_the_importer_reads_back_what_was_written(
            self, tmp_path, description):
        from services.plaintext_parser import parse_transaction_head

        content = self._written(tmp_path, description)

        heads = [ln for ln in content.splitlines() if ln.startswith("2026-")]
        assert len(heads) == 1, content
        _, _, read_back = parse_transaction_head(heads[0])
        assert read_back == description

    def test_a_commented_block_stays_commented(self, tmp_path):
        """A commented section is commented per line, so a raw newline in a
        description left the rest of it uncommented — a stray line in a file
        whose whole point is that a duplicate is not imported."""
        dup = MatchResult(
            status=MatchStatus.LIKELY_DUP,
            existing=_make_entry(desc="AUTOPAY\nsecond line"),
            merged_tx=None,
        )
        path = str(tmp_path / "out.txt")
        WRITER.write(path, [], [dup], [], [])
        content = Path(path).read_text(encoding="utf-8")

        assert all(ln.startswith(";;") or not ln.strip()
                   for ln in content.splitlines()), content
