"""Integration test: realistic month simulation for StatementReconciler."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from infrastructure.pdf.standard_tx import Split, StandardTransaction
from services.statement_reconciler import AUTOPAY_ACCOUNT, StatementReconciler


def _bank(amount: str, day: int, pdf: str, savings: str = "Assets:BOC HKD Saving") -> StandardTransaction:
    return StandardTransaction(
        post_date=date(2026, 4, day),
        description="BOC CREDIT CARD",
        currency="HKD",
        splits=[
            Split(savings, Decimal(f"-{amount}")),
            Split(AUTOPAY_ACCOUNT, Decimal(amount)),
        ],
        source_pdfs=[pdf],
    )


def _card(amount: str, day: int, pdf: str, liability: str, currency: str = "HKD") -> StandardTransaction:
    return StandardTransaction(
        post_date=date(2026, 4, day),
        description="AUTOPAY INGROUP",
        currency=currency,
        splits=[
            Split(liability, Decimal(amount)),
            Split(AUTOPAY_ACCOUNT, Decimal(f"-{amount}")),
        ],
        source_pdfs=[pdf],
    )


def _normal(desc: str, amount: str) -> StandardTransaction:
    return StandardTransaction(
        post_date=date(2026, 4, 15),
        description=desc,
        currency="HKD",
        splits=[
            Split("Assets:BOC HKD Saving", Decimal(amount)),
            Split("Income:Salary:HKD", Decimal(f"-{amount}")),
        ],
        source_pdfs=["bochk.pdf"],
    )


def test_realistic_month():
    """3 autopay pairs + 5 normal transactions → 3 resolved, 0 unresolved, 5 normal."""
    txs = [
        # Normal transactions from BOCHK
        _normal("Salary", "18110.00"),
        _normal("Interest", "0.06"),
        _normal("Interest CNY", "1.90"),
        _normal("Rent", "7200.00"),
        _normal("ATM", "400.00"),
        # BOCHK autopay debits
        _bank("247.10", 15, "bochk-2026-04.pdf"),   # → BOCI-0012
        _bank("65.80",  10, "bochk-2026-04.pdf"),   # → BOCI-0113
        _bank("1091.84", 23, "bochk-2026-04.pdf"),  # → AEON
        # Credit card autopay credits
        _card("247.10", 15, "boci-0012-2026-04.pdf", "Liabilities:BOCI-0012"),
        _card("65.80",  10, "boci-0113-2026-04.pdf", "Liabilities:BOCI-0113"),
        _card("1091.84", 24, "aeon-hk-2026-04.pdf", "Liabilities:AEON-HK-9044"),
    ]

    resolved, unresolved, normal = StatementReconciler().reconcile(txs)

    assert len(resolved) == 3, f"Expected 3 resolved, got {len(resolved)}"
    assert len(unresolved) == 0, f"Expected 0 unresolved, got {len(unresolved)}"
    assert len(normal) == 5, f"Expected 5 normal, got {len(normal)}"

    for tx in resolved:
        for split in tx.splits:
            assert split.account != AUTOPAY_ACCOUNT, (
                f"Resolved tx still contains {AUTOPAY_ACCOUNT}"
            )
