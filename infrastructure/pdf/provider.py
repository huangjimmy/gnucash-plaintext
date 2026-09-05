from __future__ import annotations

try:                       # Python 3.8 and later carry both in the stdlib
    from typing import Protocol, runtime_checkable
except ImportError:        # Python 3.7 (Debian 10) has neither; both are
    # backported by `typing_extensions`, which pyproject already requires
    # below 3.11 for `NotRequired` and the `TypedDict` backport.
    from typing_extensions import Protocol, runtime_checkable

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
