from datetime import date
from decimal import Decimal

import pytest

from infrastructure.pdf.standard_tx import Split, StandardTransaction


def test_split_decimal_enforcement_in_docker():
    # Runs in the Docker Python environment to confirm the installed package
    # preserves __post_init__ enforcement (catches packaging or import errors).
    with pytest.raises(TypeError, match="must be Decimal"):
        Split(account="Assets:Bank", amount=1.5)


def test_cjk_no_encoding_error():
    tx = StandardTransaction(
        post_date=date(2026, 4, 15),
        description="自動轉賬",
        currency="HKD",
        splits=[
            Split("Assets:Bank", Decimal("100.00")),
            Split("Expenses:Misc", Decimal("-100.00")),
        ],
    )
    assert tx.description == "自動轉賬"
    assert "自動轉賬" in repr(tx)
