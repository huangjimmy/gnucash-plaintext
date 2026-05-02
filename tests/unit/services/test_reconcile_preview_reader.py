from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from infrastructure.pdf.standard_tx import Split, StandardTransaction
from services.reconcile_preview_reader import ReconcilePreviewReader
from services.reconcile_preview_writer import ReconcilePreviewWriter

AUTOPAY_ACCOUNT = "Reconcile:Autopay"


def _resolved_tx(desc: str = "AUTOPAY INGROUP", pdf: str = "boci.pdf") -> StandardTransaction:
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


def _normal_tx(desc: str = "Salary") -> StandardTransaction:
    return StandardTransaction(
        post_date=date(2026, 3, 29),
        description="Salary",
        currency="HKD",
        splits=[
            Split("Assets:BOC HKD Saving", Decimal("18110.00")),
            Split("Income:Salary:HKD", Decimal("-18110.00")),
        ],
        source_pdfs=["bochk.pdf"],
    )


class TestRoundTrip:
    def _rw(self, tmp_path: Path, resolved, unresolved, normal):
        p = str(tmp_path / "_reconcile.txt")
        ReconcilePreviewWriter().write(p, resolved, unresolved, normal)
        return ReconcilePreviewReader().read(p)

    def test_round_trip_resolved(self, tmp_path):
        tx = _resolved_tx()
        importable, unresolved = self._rw(tmp_path, [tx], [], [])
        assert len(importable) == 1
        assert importable[0].description == tx.description
        assert importable[0].post_date == tx.post_date

    def test_round_trip_unresolved(self, tmp_path):
        tx = _unresolved_tx()
        importable, unresolved = self._rw(tmp_path, [], [tx], [])
        assert len(unresolved) == 1
        assert any(s.account == AUTOPAY_ACCOUNT for s in unresolved[0].splits)

    def test_normal_tx_in_importable(self, tmp_path):
        tx = _normal_tx()
        importable, unresolved = self._rw(tmp_path, [], [], [tx])
        assert len(importable) == 1
        assert importable[0].description == "Salary"

    def test_total_count_preserved(self, tmp_path):
        resolved = [_resolved_tx()]
        unresolved = [_unresolved_tx()]
        normal = [_normal_tx(), _normal_tx("Rent")]
        importable_out, unresolved_out = self._rw(tmp_path, resolved, unresolved, normal)
        assert len(importable_out) + len(unresolved_out) == 4

    def test_section_position_irrelevant(self, tmp_path):
        # Write unresolved tx under RESOLVED header by constructing file manually
        p = str(tmp_path / "_reconcile.txt")
        with open(p, "w", encoding="utf-8") as f:
            f.write(";; ===== RESOLVED =====\n\n")
            f.write('2026-04-02 * "BOC CREDIT CARD"\n')
            f.write('\tdoc_link: "bank_statements/bochk.pdf"\n')
            f.write('\tcurrency.mnemonic: "HKD"\n')
            f.write('\tAssets:BOC HKD Saving -125.00 HKD\n')
            f.write(f'\t{AUTOPAY_ACCOUNT} 125.00 HKD\n\n')
        importable, unresolved = ReconcilePreviewReader().read(p)
        assert len(unresolved) == 1
        assert len(importable) == 0

    def test_comment_lines_skipped(self, tmp_path):
        p = str(tmp_path / "_reconcile.txt")
        with open(p, "w", encoding="utf-8") as f:
            f.write(";; This is a comment\n")
            f.write(";; ===== RESOLVED =====\n")
            f.write(";; another comment\n\n")
            f.write('2026-04-15 * "AUTOPAY INGROUP"\n')
            f.write('\tcurrency.mnemonic: "HKD"\n')
            f.write('\tLiabilities:BOCI-0012 247.10 HKD\n')
            f.write('\tAssets:BOC HKD Saving -247.10 HKD\n\n')
        importable, unresolved = ReconcilePreviewReader().read(p)
        assert len(importable) == 1
        for split in importable[0].splits:
            assert ";;" not in split.account

    def test_empty_file(self, tmp_path):
        p = str(tmp_path / "_reconcile.txt")
        Path(p).write_text("", encoding="utf-8")
        importable, unresolved = ReconcilePreviewReader().read(p)
        assert importable == []
        assert unresolved == []

    def test_importable_never_contains_autopay(self, tmp_path):
        txs = [_resolved_tx(), _normal_tx(), _unresolved_tx()]
        importable, _ = self._rw(tmp_path, [txs[0]], [txs[2]], [txs[1]])
        for tx in importable:
            for split in tx.splits:
                assert split.account != AUTOPAY_ACCOUNT

    def test_doc_link_prefix(self, tmp_path):
        p = str(tmp_path / "_reconcile.txt")
        ReconcilePreviewWriter().write(p, [_resolved_tx(pdf="boci.pdf")], [], [])
        content = Path(p).read_text(encoding="utf-8")
        assert 'doc_link: "bank_statements/boci.pdf"' in content

    def test_cjk_preserved(self, tmp_path):
        tx = _resolved_tx(desc="自動轉賬")
        importable, _ = self._rw(tmp_path, [tx], [], [])
        assert importable[0].description == "自動轉賬"

    def test_three_splits_round_trip(self, tmp_path):
        tx = StandardTransaction(
            post_date=date(2026, 4, 15),
            description="Split expense",
            currency="HKD",
            splits=[
                Split("Assets:Bank", Decimal("300.00")),
                Split("Expenses:Dining", Decimal("-200.00")),
                Split("Expenses:Groceries", Decimal("-100.00")),
            ],
            source_pdfs=["test.pdf"],
        )
        importable, _ = self._rw(tmp_path, [tx], [], [])
        assert len(importable[0].splits) == 3

    def test_guid_round_trip(self, tmp_path):
        tx = _resolved_tx()
        tx.guid = "abc123"
        importable, _ = self._rw(tmp_path, [tx], [], [])
        assert importable[0].guid == "abc123"

    def test_two_source_pdfs(self, tmp_path):
        tx = StandardTransaction(
            post_date=date(2026, 4, 15),
            description="AUTOPAY INGROUP",
            currency="HKD",
            splits=[
                Split("Liabilities:BOCI-0012", Decimal("247.10")),
                Split("Assets:BOC HKD Saving", Decimal("-247.10")),
            ],
            source_pdfs=["boci.pdf", "bochk.pdf"],
        )
        importable, _ = self._rw(tmp_path, [tx], [], [])
        assert importable[0].source_pdfs[0] == "boci.pdf"
        assert importable[0].source_pdfs[1] == "bochk.pdf"
