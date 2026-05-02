from datetime import date
from decimal import Decimal

import pytest

from infrastructure.pdf.standard_tx import Split, StandardTransaction
from services.statement_reconciler import AUTOPAY_ACCOUNT, StatementReconciler


def bank_tx(
    amount: str = "247.10",
    date_: date = date(2026, 4, 15),
    currency: str = "HKD",
    pdf: str = "bochk.pdf",
) -> StandardTransaction:
    return StandardTransaction(
        post_date=date_,
        description="BOC CREDIT CARD",
        currency=currency,
        splits=[
            Split("Assets:BOC HKD Saving", Decimal(f"-{amount}")),
            Split(AUTOPAY_ACCOUNT, Decimal(amount)),
        ],
        source_pdfs=[pdf],
    )


def card_tx(
    amount: str = "247.10",
    date_: date = date(2026, 4, 15),
    currency: str = "HKD",
    pdf: str = "boci.pdf",
    card_account: str = "Liabilities:BOCI-0012",
) -> StandardTransaction:
    return StandardTransaction(
        post_date=date_,
        description="AUTOPAY INGROUP",
        currency=currency,
        splits=[
            Split(card_account, Decimal(amount)),
            Split(AUTOPAY_ACCOUNT, Decimal(f"-{amount}")),
        ],
        source_pdfs=[pdf],
    )


def normal_tx(desc: str = "Salary") -> StandardTransaction:
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


class TestStatementReconciler:
    def setup_method(self):
        self.r = StatementReconciler()

    def test_clean_match(self):
        resolved, unresolved, normal = self.r.reconcile([bank_tx(), card_tx()])
        assert len(resolved) == 1
        assert len(unresolved) == 0

    def test_merged_no_autopay_account(self):
        resolved, _, _ = self.r.reconcile([bank_tx(), card_tx()])
        for split in resolved[0].splits:
            assert split.account != AUTOPAY_ACCOUNT

    def test_merged_card_description_wins(self):
        resolved, _, _ = self.r.reconcile([bank_tx(), card_tx()])
        assert resolved[0].description == "AUTOPAY INGROUP"

    def test_merged_card_date_wins(self):
        resolved, _, _ = self.r.reconcile([
            bank_tx(date_=date(2026, 4, 14)),
            card_tx(date_=date(2026, 4, 15)),
        ])
        assert resolved[0].post_date == date(2026, 4, 15)

    def test_merged_source_pdfs_card_first(self):
        resolved, _, _ = self.r.reconcile([bank_tx(), card_tx()])
        assert resolved[0].source_pdfs == ["boci.pdf", "bochk.pdf"]

    def test_date_plus_one_matches(self):
        resolved, unresolved, _ = self.r.reconcile([
            bank_tx(date_=date(2026, 4, 14)),
            card_tx(date_=date(2026, 4, 15)),
        ])
        assert len(resolved) == 1
        assert len(unresolved) == 0

    def test_date_minus_one_matches(self):
        resolved, unresolved, _ = self.r.reconcile([
            bank_tx(date_=date(2026, 4, 15)),
            card_tx(date_=date(2026, 4, 14)),
        ])
        assert len(resolved) == 1
        assert len(unresolved) == 0

    def test_date_plus_two_no_match(self):
        _, unresolved, _ = self.r.reconcile([
            bank_tx(date_=date(2026, 4, 13)),
            card_tx(date_=date(2026, 4, 15)),
        ])
        assert len(unresolved) == 2

    def test_partial_run_bank_only(self):
        _, unresolved, _ = self.r.reconcile([bank_tx()])
        assert len(unresolved) == 1

    def test_partial_run_card_only(self):
        _, unresolved, _ = self.r.reconcile([card_tx()])
        assert len(unresolved) == 1

    def test_same_side_collision_both_unresolved(self):
        _, unresolved, _ = self.r.reconcile([
            bank_tx(amount="247.10"),
            bank_tx(amount="247.10"),
            card_tx(amount="247.10"),
        ])
        assert len(unresolved) == 3

    def test_cross_side_collision_all_unresolved(self):
        _, unresolved, _ = self.r.reconcile([
            bank_tx(amount="247.10"),
            card_tx(amount="247.10", pdf="boci-0012.pdf"),
            card_tx(amount="247.10", pdf="aeon.pdf"),
        ])
        assert len(unresolved) == 3

    def test_currency_mismatch_no_match(self):
        _, unresolved, _ = self.r.reconcile([
            bank_tx(currency="HKD"),
            card_tx(currency="CNY"),
        ])
        assert len(unresolved) == 2

    def test_normal_passthrough(self):
        tx = normal_tx()
        _, _, normal = self.r.reconcile([tx])
        assert normal == [tx]

    def test_mixed_batch(self):
        txs = [
            normal_tx("Salary"),
            normal_tx("Rent"),
            bank_tx(amount="247.10"),
            card_tx(amount="247.10"),
            bank_tx(amount="999.99"),  # unresolved — no matching card
        ]
        resolved, unresolved, normal = self.r.reconcile(txs)
        assert len(resolved) == 1
        assert len(unresolved) == 1
        assert len(normal) == 2

    def test_cny_match(self):
        resolved, unresolved, _ = self.r.reconcile([
            bank_tx(amount="312.99", currency="CNY"),
            card_tx(amount="312.99", currency="CNY"),
        ])
        assert len(resolved) == 1
        assert resolved[0].currency == "CNY"
        assert len(unresolved) == 0
