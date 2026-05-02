from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from infrastructure.pdf.standard_tx import Split, StandardTransaction

AUTOPAY_ACCOUNT = "Reconcile:Autopay"


def _autopay_amount(tx: StandardTransaction) -> Decimal | None:
    """Return the signed Reconcile:Autopay split amount, or None if not present."""
    for split in tx.splits:
        if split.account == AUTOPAY_ACCOUNT:
            return split.amount
    return None


def _other_account(tx: StandardTransaction) -> str:
    """Return the non-autopay account from a 2-split autopay transaction."""
    for split in tx.splits:
        if split.account != AUTOPAY_ACCOUNT:
            return split.account
    return ""


class StatementReconciler:
    """Merges Reconcile:Autopay placeholder pairs across statements.

    Inputs are a flat list of StandardTransaction from all providers.
    Outputs three buckets: resolved (autopay pairs merged), unresolved
    (Reconcile:Autopay still present), normal (no autopay involvement).
    """

    DATE_TOLERANCE = timedelta(days=1)

    def reconcile(
        self,
        transactions: list[StandardTransaction],
    ) -> tuple[
        list[StandardTransaction],  # resolved
        list[StandardTransaction],  # unresolved
        list[StandardTransaction],  # normal
    ]:
        bank_side: list[StandardTransaction] = []   # Reconcile:Autopay > 0
        card_side: list[StandardTransaction] = []   # Reconcile:Autopay < 0
        normal: list[StandardTransaction] = []

        for tx in transactions:
            amt = _autopay_amount(tx)
            if amt is None:
                normal.append(tx)
            elif amt > Decimal(0):
                bank_side.append(tx)
            else:
                card_side.append(tx)

        matched_bank: set[int] = set()
        matched_card: set[int] = set()
        resolved: list[StandardTransaction] = []

        for bi, bank in enumerate(bank_side):
            bank_amt = _autopay_amount(bank)
            card_matches = [
                ci for ci, card in enumerate(card_side)
                if ci not in matched_card
                and card.currency == bank.currency
                and abs(_autopay_amount(card)) == bank_amt  # type: ignore[arg-type]
                and abs((bank.post_date - card.post_date).days) <= 1
            ]

            # Also check for same-side collisions: other bank entries with same
            # amount/currency/date that haven't been matched yet
            bank_collisions = [
                bi2 for bi2, bank2 in enumerate(bank_side)
                if bi2 != bi
                and bi2 not in matched_bank
                and bank2.currency == bank.currency
                and _autopay_amount(bank2) == bank_amt
                and abs((bank.post_date - bank2.post_date).days) <= 1
            ]

            if len(card_matches) == 1 and len(bank_collisions) == 0:
                ci = card_matches[0]
                card = card_side[ci]
                matched_bank.add(bi)
                matched_card.add(ci)
                resolved.append(_merge(bank, card))
            # else: collision or no match — leave for unresolved

        unresolved = (
            [tx for i, tx in enumerate(bank_side) if i not in matched_bank]
            + [tx for i, tx in enumerate(card_side) if i not in matched_card]
        )

        return resolved, unresolved, normal


def _merge(bank: StandardTransaction, card: StandardTransaction) -> StandardTransaction:
    """Produce one merged transaction from a matched bank/card autopay pair.

    Card side is primary: provides date, description, source_pdfs[0].
    Bank side provides the savings account split.
    """
    bank_account = _other_account(bank)
    card_account = _other_account(card)
    bank_amt = _autopay_amount(bank)
    assert bank_amt is not None

    return StandardTransaction(
        post_date=card.post_date,
        description=card.description,
        currency=card.currency,
        splits=[
            Split(card_account, abs(bank_amt)),    # card liability: +X (reduce)
            Split(bank_account, -abs(bank_amt)),   # bank savings: -X (debit)
        ],
        source_pdfs=(card.source_pdfs or []) + (bank.source_pdfs or []),
        guid=None,
    )
