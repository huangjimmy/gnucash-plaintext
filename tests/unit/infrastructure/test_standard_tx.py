from datetime import date
from decimal import Decimal

import pytest

from infrastructure.pdf.provider import StatementProvider
from infrastructure.pdf.standard_tx import Split, StandardTransaction


class TestSplit:
    def test_constructed_with_decimal(self):
        s = Split(account="Assets:Bank", amount=Decimal("100.00"))
        assert isinstance(s.amount, Decimal)
        assert s.amount == Decimal("100.00")

    def test_float_raises_type_error(self):
        with pytest.raises(TypeError, match="must be Decimal"):
            Split(account="Assets:Bank", amount=100.0)


class TestStandardTransaction:
    def _make(self, **kwargs):
        defaults = {
            "post_date": date(2026, 4, 15),
            "description": "Test",
            "currency": "HKD",
            "splits": [
                Split("Assets:Bank", Decimal("100.00")),
                Split("Income:Salary", Decimal("-100.00")),
            ],
        }
        defaults.update(kwargs)
        return StandardTransaction(**defaults)

    def test_defaults(self):
        tx = self._make()
        assert tx.guid is None
        assert tx.source_pdfs == []

    def test_source_pdfs_not_shared(self):
        tx1 = self._make()
        tx2 = self._make()
        tx1.source_pdfs.append("a.pdf")
        assert tx2.source_pdfs == []

    def test_single_split_raises(self):
        with pytest.raises(ValueError, match="at least 2 splits"):
            self._make(splits=[Split("Assets:Bank", Decimal("100.00"))])

    def test_three_splits(self):
        tx = self._make(splits=[
            Split("Assets:Bank", Decimal("300.00")),
            Split("Expenses:Dining", Decimal("-200.00")),
            Split("Expenses:Groceries", Decimal("-100.00")),
        ])
        assert len(tx.splits) == 3

    def test_cjk_description(self):
        tx = self._make(description="自動轉賬")
        assert tx.description == "自動轉賬"
        assert repr(tx)


class TestStatementProvider:
    def test_concrete_class_satisfies_protocol(self):
        class MockProvider:
            autopay_source = {"HKD": "Assets:Bank"}

            def can_handle(self, filename: str) -> bool:
                return filename.startswith("mock-")

            def parse(self, path: str) -> list[StandardTransaction]:
                return []

        assert isinstance(MockProvider(), StatementProvider)

    def test_missing_method_fails_protocol(self):
        class IncompleteProvider:
            autopay_source = {}

        assert not isinstance(IncompleteProvider(), StatementProvider)

    def test_missing_autopay_source_documents_runtime_gap(self):
        # autopay_source is a Protocol data attribute. On Python 3.11+,
        # isinstance() may or may not check its presence depending on the
        # minor version. Protocol compliance for data attributes is enforced
        # by static type checking (mypy), not solely by isinstance().
        # This test documents the actual runtime behaviour on the current
        # Python version rather than asserting a specific outcome.
        class ProviderWithoutAutopaySource:
            def can_handle(self, filename: str) -> bool:
                return False

            def parse(self, path: str) -> list[StandardTransaction]:
                return []

        result = isinstance(ProviderWithoutAutopaySource(), StatementProvider)
        # On Python 3.11.14 this is False (attribute checked); on older minor
        # versions it may be True (only methods checked). Either way, callers
        # must not rely solely on isinstance() — use mypy for data attribute
        # compliance. This assertion records the current runtime behaviour.
        assert result is False  # update if Python version changes behaviour
