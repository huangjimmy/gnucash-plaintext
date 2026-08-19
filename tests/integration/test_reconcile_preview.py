"""Integration tests for ReconcilePreviewWriter + ReconcilePreviewReader pipeline."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from infrastructure.pdf.standard_tx import Split, StandardTransaction
from services.reconcile_preview_reader import AUTOPAY_ACCOUNT, ReconcilePreviewReader
from services.reconcile_preview_writer import ReconcilePreviewWriter
from services.statement_reconciler import StatementReconciler


def _bank(amount: str, pdf: str = "bochk.pdf") -> StandardTransaction:
    return StandardTransaction(
        post_date=date(2026, 4, 15),
        description="BOC CREDIT CARD",
        currency="HKD",
        splits=[
            Split("Assets:BOC HKD Saving", Decimal(f"-{amount}")),
            Split(AUTOPAY_ACCOUNT, Decimal(amount)),
        ],
        source_pdfs=[pdf],
    )


def _card(amount: str, pdf: str = "boci.pdf") -> StandardTransaction:
    return StandardTransaction(
        post_date=date(2026, 4, 15),
        description="AUTOPAY INGROUP",
        currency="HKD",
        splits=[
            Split("Liabilities:BOCI-0012", Decimal(amount)),
            Split(AUTOPAY_ACCOUNT, Decimal(f"-{amount}")),
        ],
        source_pdfs=[pdf],
    )


def _normal(desc: str) -> StandardTransaction:
    return StandardTransaction(
        post_date=date(2026, 4, 15),
        description=desc,
        currency="HKD",
        splits=[
            Split("Assets:BOC HKD Saving", Decimal("18110.00")),
            Split("Income:Salary:HKD", Decimal("-18110.00")),
        ],
        source_pdfs=["bochk.pdf"],
    )


def test_full_pipeline_no_transactions_dropped(tmp_path):
    """Reconciler → writer → reader: total in == total out, none dropped."""
    txs = [
        _bank("247.10"), _card("247.10"),  # pair → resolved
        _bank("999.00"),                   # no card → unresolved
        _normal("Salary"), _normal("Rent"),
    ]
    reconciler = StatementReconciler()
    resolved, unresolved, normal = reconciler.reconcile(txs)

    path = str(tmp_path / "_reconcile.txt")
    ReconcilePreviewWriter().write(path, resolved, unresolved, normal)
    importable, unresolved_out = ReconcilePreviewReader().read(path)

    total_in = len(resolved) + len(unresolved) + len(normal)
    total_out = len(importable) + len(unresolved_out)
    assert total_out == total_in, f"Dropped {total_in - total_out} transaction(s)"


def test_cjk_utf8_on_disk(tmp_path):
    """CJK characters survive write → disk → read without encoding error."""
    tx = StandardTransaction(
        post_date=date(2026, 4, 15),
        description="自動轉賬 / BOC CREDIT CARD (INT",
        currency="HKD",
        splits=[
            Split("Assets:BOC HKD Saving", Decimal("-247.10")),
            Split("Liabilities:BOCI-0012", Decimal("247.10")),
        ],
        source_pdfs=["bochk.pdf"],
    )
    path = str(tmp_path / "_reconcile.txt")
    ReconcilePreviewWriter().write(path, [tx], [], [])

    # Verify bytes on disk are valid UTF-8
    raw = Path(path).read_bytes()
    text = raw.decode("utf-8")
    assert "自動轉賬" in text

    importable, _ = ReconcilePreviewReader().read(path)
    assert importable[0].description == "自動轉賬 / BOC CREDIT CARD (INT"


@pytest.mark.parametrize("description", [
    r"AUTOPAY C:\name",
    r'AUTOPAY "INGROUP"',
    "AUTOPAY\nsecond line",
    "AUTOPAY\rsecond line",
    r'both: "C:\name"',
])
def test_a_description_comes_back_as_it_went_out(tmp_path, description):
    """The writer escapes four characters and the reader undoes four.

    They are one pair — nothing else reads this file — so a description
    holding a backslash or a newline is the writer's whole job: escaped and
    then unescaped by a rule that does not match, `C:\\name` comes back a
    character too many, and the transaction the reconciler hands on is not
    the one the statement carried.
    """
    tx = StandardTransaction(
        post_date=date(2026, 4, 15),
        description=description,
        currency="HKD",
        splits=[
            Split("Assets:BOC HKD Saving", Decimal("-247.10")),
            Split("Liabilities:BOCI-0012", Decimal("247.10")),
        ],
        source_pdfs=["bochk.pdf"],
    )
    path = str(tmp_path / "_reconcile.txt")
    ReconcilePreviewWriter().write(path, [tx], [], [])

    # One line for the block it heads, whatever the description holds: the
    # reader takes a key per line, so a raw newline would end it mid-word.
    written = Path(path).read_text(encoding="utf-8")
    assert len([ln for ln in written.splitlines()
                if ln.startswith("2026-")]) == 1, written

    importable, _ = ReconcilePreviewReader().read(path)
    assert len(importable) == 1, written
    assert importable[0].description == description
