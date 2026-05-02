from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal


@dataclass
class Split:
    account: str
    amount: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.amount, Decimal):
            raise TypeError(f"Split.amount must be Decimal, got {type(self.amount).__name__}")


@dataclass
class StandardTransaction:
    post_date: date
    description: str
    currency: str
    splits: list[Split]
    source_pdfs: list[str] = field(default_factory=list)
    guid: str | None = None

    def __post_init__(self) -> None:
        if len(self.splits) < 2:
            raise ValueError("StandardTransaction requires at least 2 splits")
        # Balance (splits summing to zero) is intentionally NOT enforced here.
        # Transactions containing Reconcile:Autopay placeholders are deliberately
        # unbalanced — they become balanced only after StatementReconciler merges
        # the two sides of an autopay pair.
