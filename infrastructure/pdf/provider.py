from __future__ import annotations

from typing import Protocol, runtime_checkable

from infrastructure.pdf.standard_tx import StandardTransaction


@runtime_checkable
class StatementProvider(Protocol):
    """Protocol for bank/credit-card PDF statement parsers.

    autopay_source maps currency code to the GnuCash account path that funds
    autopay for this card, e.g. {"HKD": "Assets:...:BOC HKD Saving"}.
    Used by StatementReconciler to resolve Reconcile:Autopay placeholders.
    """

    autopay_source: dict[str, str]  # currency_code → funding_account_path

    def can_handle(self, filename: str) -> bool: ...
    def parse(self, path: str) -> list[StandardTransaction]: ...
