"""Integration test: full pipeline end-to-end with real GnuCash book."""
from __future__ import annotations

import os
import tempfile
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from infrastructure.pdf.standard_tx import Split, StandardTransaction
from repositories.gnucash_repository import GnuCashRepository
from services.gnucash_fuzzy_matcher import GnuCashFuzzyMatcher, MatchStatus
from services.ready_to_import_writer import AUTOPAY_ACCOUNT, ReadyToImportWriter
from services.reconcile_preview_reader import ReconcilePreviewReader
from services.reconcile_preview_writer import ReconcilePreviewWriter
from services.statement_reconciler import StatementReconciler


@pytest.fixture
def simple_book():
    """Minimal GnuCash book: one manually-entered credit card charge."""
    import gnucash
    from gnucash import Account, GncNumeric, Session, Transaction
    from gnucash import Split as GncSplit

    fd, path = tempfile.mkstemp(suffix=".gnucash")
    os.close(fd)
    os.unlink(path)

    try:
        from gnucash import SessionOpenMode
        session = Session(f"xml://{path}", SessionOpenMode.SESSION_NEW_STORE)
    except ImportError:
        session = Session(f"xml://{path}", is_new=True)

    book = session.book
    root = book.get_root_account()
    table = book.get_table()
    hkd = table.lookup("CURRENCY", "HKD")

    def acct(name, type_, parent):
        a = Account(book)
        a.SetName(name)
        a.SetType(type_)
        a.SetCommodity(hkd)
        parent.append_child(a)
        return a

    assets = acct("Assets", gnucash.ACCT_TYPE_ASSET, root)
    acct("BOC HKD Saving", gnucash.ACCT_TYPE_BANK, assets)
    expenses = acct("Expenses", gnucash.ACCT_TYPE_EXPENSE, root)
    dining = acct("Dining", gnucash.ACCT_TYPE_EXPENSE, expenses)
    liabilities = acct("Liabilities", gnucash.ACCT_TYPE_LIABILITY, root)
    boci = acct("BOCI-0012", gnucash.ACCT_TYPE_CREDIT, liabilities)

    # Manually-entered charge: BOCI-0012 → Dining (user already categorized)
    tx = Transaction(book)
    tx.BeginEdit()
    tx.SetCurrency(hkd)
    # The setter the importer uses. `SetDatePostedSecs` with plain epoch
    # seconds reads back as 4753-05-01 on GnuCash 3.4 — see
    # `tests/research/what_a_posted_date_reads_back_as_probe.py`.
    tx.SetDatePostedSecsNormalized(date(2026, 4, 15))
    for acct_obj, num, denom in [(boci, 24710, 100), (dining, -24710, 100)]:
        sp = GncSplit(book)
        sp.SetParent(tx)
        sp.SetAccount(acct_obj)
        sp.SetValue(GncNumeric(num, denom))
        sp.SetAmount(GncNumeric(num, denom))
    tx.CommitEdit()

    session.save()
    session.end()

    yield path

    if os.path.exists(path):
        os.unlink(path)
    lock = path + ".LCK"
    if os.path.exists(lock):
        os.unlink(lock)


def _make_tx(acct1, acct2, amount, d=date(2026, 4, 15), pdf="boci.pdf"):
    return StandardTransaction(
        post_date=d, description="AUTOPAY INGROUP", currency="HKD",
        splits=[Split(acct1, Decimal(amount)), Split(acct2, Decimal(f"-{amount}"))],
        source_pdfs=[pdf],
    )


def test_end_to_end_pipeline(tmp_path, simple_book):
    """Full pipeline: StandardTransactions → reconciler → writer → reader →
    fuzzy matcher → ready-to-import writer → PlaintextParser-parseable output.
    """
    boci = "Liabilities:BOCI-0012"
    bank = "Assets:BOC HKD Saving"
    groceries = "Expenses:Groceries"

    # Three transactions coming from statement parsers:
    # 1. A salary (normal, NEW — not in GnuCash)
    salary = StandardTransaction(
        post_date=date(2026, 3, 29), description="Salary", currency="HKD",
        splits=[Split(bank, Decimal("18110.00")), Split("Income:Salary:HKD", Decimal("-18110.00"))],
        source_pdfs=["bochk.pdf"],
    )
    # 2. A credit card charge (PARTIAL_MATCH — GnuCash has boci→dining, we have boci→groceries)
    charge = _make_tx(boci, groceries, "247.10")
    # 3. An unresolved autopay (no matching card statement provided)
    unresolved_bank = StandardTransaction(
        post_date=date(2026, 4, 2), description="BOC CREDIT CARD", currency="HKD",
        splits=[Split(bank, Decimal("-125.00")), Split(AUTOPAY_ACCOUNT, Decimal("125.00"))],
        source_pdfs=["bochk.pdf"],
    )

    # Phase 1: reconcile (no autopay pairs to merge in this batch)
    resolved, unresolved, normal = StatementReconciler().reconcile(
        [salary, charge, unresolved_bank]
    )

    # Write preview
    preview = str(tmp_path / "_reconcile.txt")
    ReconcilePreviewWriter().write(preview, resolved, unresolved, normal)

    # Phase 2: read back and fuzzy match
    importable, unresolved_out = ReconcilePreviewReader().read(preview)

    matcher = GnuCashFuzzyMatcher(GnuCashRepository(simple_book))
    new_txs, likely_dup, partial_match = [], [], []
    for tx in importable:
        result = matcher.match(tx)
        if result.status == MatchStatus.NEW:
            new_txs.append(tx)
        elif result.status == MatchStatus.LIKELY_DUP:
            likely_dup.append(result)
        else:
            partial_match.append(result)

    # Write ready-to-import
    output = str(tmp_path / "ready.txt")
    ReadyToImportWriter().write(output, new_txs, likely_dup, partial_match, unresolved_out)

    content = Path(output).read_text(encoding="utf-8")

    # Salary should be NEW
    assert "Salary" in content
    assert "18110.00" in content

    # Charge should be PARTIAL_MATCH with GnuCash's Dining category in merged
    assert "SUGGESTED MERGE" in content
    assert "Expenses:Dining" in content
    assert "Expenses:Groceries" not in content.split("SUGGESTED MERGE")[1].split("===")[0]

    # Unresolved should be commented out with warning
    assert "[UNRESOLVED — DO NOT IMPORT]" in content

    # No live Reconcile:Autopay anywhere
    live_lines = [ln for ln in content.splitlines() if not ln.startswith(";;") and AUTOPAY_ACCOUNT in ln]
    assert live_lines == []


def test_idempotency(tmp_path, simple_book):
    """Running the full pipeline twice on the same inputs produces no duplicates."""
    boci = "Liabilities:BOCI-0012"
    dining = "Expenses:Dining"

    tx = _make_tx(boci, dining, "247.10")
    matcher = GnuCashFuzzyMatcher(GnuCashRepository(simple_book))

    result1 = matcher.match(tx)
    result2 = matcher.match(tx)

    # Both runs should see the same existing transaction
    assert result1.status == result2.status
    assert result1.existing.guid == result2.existing.guid
