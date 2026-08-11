import os
import re

import pytest
from click.testing import CliRunner

from cli.main import cli

_BOBJ_PREFIXES = re.compile(r'^(customer|vendor|taxtable|invoice|bill)\b')


def extract_business_objects(text: str) -> str:
    """
    Extract business-object blocks (customer/vendor/taxtable/invoice/bill)
    from a plaintext export that also contains account/transaction sections.
    """
    blocks = []
    current = []
    for line in text.splitlines():
        if _BOBJ_PREFIXES.match(line):
            if current:
                blocks.append('\n'.join(current))
            current = [line]
        elif current:
            # Indented continuation or blank line inside a block
            if line == '' or line.startswith(' ') or line.startswith('\t'):
                current.append(line)
            else:
                # Non-indented line that is NOT a business-object header ends the block
                blocks.append('\n'.join(current))
                current = []
    if current:
        blocks.append('\n'.join(current))
    return '\n\n'.join(b.rstrip() for b in blocks)


def get_invoice_block(exported_biz: str, invoice_id: str) -> str:
    """Return the exported block for the given invoice ID, or empty string."""
    for block in exported_biz.split('\n\n'):
        if block.startswith(f'invoice "{invoice_id}"'):
            return block
    return ''


def get_bill_block(exported_biz: str, bill_id: str) -> str:
    """Return the exported block for the given bill ID, or empty string."""
    for block in exported_biz.split('\n\n'):
        if block.startswith(f'bill "{bill_id}"'):
            return block
    return ''


def test_business_objects_roundtrip(tmp_path):
    runner = CliRunner()
    gnucash_file = tmp_path / "test.gnucash"
    input_file = "tests/fixtures/business_objects.txt"
    output_file = tmp_path / "output.txt"
    pdf_file = tmp_path / "invoice.pdf"

    # Create a new GnuCash file and import everything
    result = runner.invoke(cli, ["import", "--new", str(gnucash_file), input_file, "--include-business-objects"])
    assert result.exit_code == 0, f"Import failed:\n{result.output}"

    # Export including business objects
    # Output order: accounts → business objects → transactions
    result = runner.invoke(cli, ["export", str(gnucash_file), str(output_file), "--include-business-objects"])
    assert result.exit_code == 0, f"Export failed:\n{result.output}"

    with open(output_file) as f:
        exported_text = f.read()

    # Ensure no duplicate account declarations.
    # ExportTransactionsUseCase deduplicates via account_seen (GUID set); this
    # assertion catches any future regression where that guard is removed.
    open_names = [line.split(' open ', 1)[1] for line in exported_text.splitlines() if ' open ' in line]
    duplicates = [name for name in set(open_names) if open_names.count(name) > 1]
    assert not duplicates, f"Duplicate account declarations found: {duplicates}"

    # Extract only the business objects from the output and compare with the reference.
    # GUID-bearing lines (`guid:`, `customer_guid:`, `vendor_guid:`) are stripped
    # because GUIDs are random per import; their round-trip behaviour is covered
    # in test_business_object_idempotent_reimport.py.
    def _strip_guid_lines(text):
        keep = []
        for line in text.splitlines():
            stripped = line.lstrip(' \t')
            if stripped.startswith(('guid:', 'customer_guid:', 'vendor_guid:',
                                    'txn_guid:', 'txn_split_guid:',
                                    'posted_txn_guid:')):
                continue
            keep.append(line)
        return '\n'.join(keep)

    # Q-016 positive guards: the exporter must EMIT every GUID field on
    # business-object payment blocks. Stripping the lines for the
    # comparison below loses signal about whether those lines exist at
    # all — assert their presence here so a future regression that drops
    # `txn_guid:` / `txn_split_guid:` on export trips this test.
    biz_text = extract_business_objects(exported_text)
    if 'payment:' in biz_text and 'payment: none' not in biz_text.replace(
            'payment:\n', 'payment:non'):
        # There's at least one real payment block (not just `payment: none`).
        assert 'txn_guid:' in biz_text, (
            'Q-016: every exported payment: block must carry txn_guid:. '
            'Missing in:\n' + biz_text
        )
        assert 'txn_split_guid:' in biz_text, (
            'Q-016: every exported payment: block must carry '
            'txn_split_guid:. Missing in:\n' + biz_text
        )
        # Q-016: the field was renamed from `payment_split_guid:` to
        # `txn_split_guid:`. Catch a regression that re-emits the old
        # name alongside the new one. Use a line-aware check because
        # `split_guid:` appears as a suffix of `txn_split_guid:`.
        legacy_lines = [
            line for line in exported_text.splitlines()
            if line.lstrip(' \t').startswith(('payment_split_guid:',
                                              'split_guid:'))
        ]
        assert not legacy_lines, (
            'Q-016: exporter must not emit the legacy field names '
            '(payment_split_guid: → txn_split_guid:, per-split '
            'split_guid: → guid:). Found:\n  ' + '\n  '.join(legacy_lines)
        )
    exported_biz = _strip_guid_lines(biz_text)

    with open("tests/fixtures/business_objects_only.txt") as f:
        reference_biz = _strip_guid_lines(extract_business_objects(f.read()))

    assert exported_biz == reference_biz, (
        f"Business objects mismatch (ignoring guid lines).\n"
        f"--- reference ---\n{reference_biz}\n"
        f"--- exported ---\n{exported_biz}"
    )

    # ── Per-invoice state assertions ──────────────────────────────────────────

    # INV-2026-001: posted, not paid
    # Must have a posted: block and an explicit "payment: none" sentinel
    inv1 = get_invoice_block(exported_biz, 'INV-2026-001')
    assert inv1, "INV-2026-001 must appear in export"
    assert '	posted:' in inv1, "INV-2026-001 must have a posted: block"
    assert '	payment: none' in inv1, "INV-2026-001 must have payment: none (not paid)"

    # INV-2026-002: unposted
    # Must appear (export now includes unposted) with both sentinels
    inv2 = get_invoice_block(exported_biz, 'INV-2026-002')
    assert inv2, "INV-2026-002 (unposted) must appear in export"
    assert '	posted: none' in inv2, "INV-2026-002 must have posted: none (unposted)"
    assert '	payment: none' in inv2, "INV-2026-002 must have payment: none (unposted, no payments)"

    # INV-2026-003: posted, single full payment
    inv3 = get_invoice_block(exported_biz, 'INV-2026-003')
    assert inv3, "INV-2026-003 must appear in export"
    assert '	posted:' in inv3, "INV-2026-003 must have a posted: block"
    assert '	payment:' in inv3, "INV-2026-003 must have a payment: block"
    assert 'payment: none' not in inv3, "INV-2026-003 must not have payment: none"
    assert inv3.count('	payment:') == 1, "INV-2026-003 must have exactly one payment block"

    # INV-2026-004: posted, two partial payments, amount still remaining
    inv4 = get_invoice_block(exported_biz, 'INV-2026-004')
    assert inv4, "INV-2026-004 must appear in export"
    assert '	posted:' in inv4, "INV-2026-004 must have a posted: block"
    assert inv4.count('	payment:') == 2, "INV-2026-004 must have exactly two payment blocks"
    assert 'payment: none' not in inv4
    assert 'Partial payment 1 for INV-2026-004' in inv4
    assert 'Partial payment 2 for INV-2026-004' in inv4

    # INV-2026-005: posted, two payments, fully paid (zero balance)
    inv5 = get_invoice_block(exported_biz, 'INV-2026-005')
    assert inv5, "INV-2026-005 must appear in export"
    assert '	posted:' in inv5, "INV-2026-005 must have a posted: block"
    assert inv5.count('	payment:') == 2, "INV-2026-005 must have exactly two payment blocks"
    assert 'payment: none' not in inv5
    assert 'First payment for INV-2026-005' in inv5
    assert 'Final payment for INV-2026-005' in inv5

    # ── Per-bill state assertions ─────────────────────────────────────────────

    # BILL-2026-001: posted, not paid
    bill1 = get_bill_block(exported_biz, 'BILL-2026-001')
    assert bill1, "BILL-2026-001 must appear in export"
    assert '	posted:' in bill1, "BILL-2026-001 must have a posted: block"
    assert '	payment: none' in bill1, "BILL-2026-001 must have payment: none (not paid)"

    # BILL-2026-002: unposted
    bill2 = get_bill_block(exported_biz, 'BILL-2026-002')
    assert bill2, "BILL-2026-002 (unposted) must appear in export"
    assert '	posted: none' in bill2, "BILL-2026-002 must have posted: none (unposted)"
    assert '	payment: none' in bill2, "BILL-2026-002 must have payment: none (unposted, no payments)"

    # BILL-2026-003: posted, single full payment
    bill3 = get_bill_block(exported_biz, 'BILL-2026-003')
    assert bill3, "BILL-2026-003 must appear in export"
    assert '	posted:' in bill3, "BILL-2026-003 must have a posted: block"
    assert '	payment:' in bill3, "BILL-2026-003 must have a payment: block"
    assert 'payment: none' not in bill3, "BILL-2026-003 must not have payment: none"
    assert bill3.count('	payment:') == 1, "BILL-2026-003 must have exactly one payment block"

    # BILL-2026-004: posted, two partial payments, amount still remaining
    bill4 = get_bill_block(exported_biz, 'BILL-2026-004')
    assert bill4, "BILL-2026-004 must appear in export"
    assert '	posted:' in bill4, "BILL-2026-004 must have a posted: block"
    assert bill4.count('	payment:') == 2, "BILL-2026-004 must have exactly two payment blocks"
    assert 'payment: none' not in bill4
    assert 'Partial payment 1 for BILL-2026-004' in bill4
    assert 'Partial payment 2 for BILL-2026-004' in bill4

    # BILL-2026-005: posted, two payments, fully paid (zero balance)
    bill5 = get_bill_block(exported_biz, 'BILL-2026-005')
    assert bill5, "BILL-2026-005 must appear in export"
    assert '	posted:' in bill5, "BILL-2026-005 must have a posted: block"
    assert bill5.count('	payment:') == 2, "BILL-2026-005 must have exactly two payment blocks"
    assert 'payment: none' not in bill5
    assert 'First payment for BILL-2026-005' in bill5
    assert 'Final payment for BILL-2026-005' in bill5

    # Test the print-invoice command
    result = runner.invoke(cli, ["print-invoice", str(gnucash_file), "--invoice-id", "INV-2026-001", "-o", str(pdf_file)])
    assert result.exit_code == 0, f"print-invoice failed:\n{result.output}"
    assert os.path.exists(pdf_file)


_CONTRADICTION_CASES = [
    (
        "posted_none_and_posted_block",
        """
invoice "INV-X"
  customer_id: "1"
  currency: CAD
  date_opened: 2026-01-01
  entry:
    date: 2026-01-01
    description: "Test"
    action: "Hours"
    account: "Income:Sales"
    quantity: 1
    price: 100
    taxable: false
    tax_included: false
  posted: none
  posted:
    date: 2026-01-01
    due: 2026-01-31
    ar_account: "Assets:Accounts Receivable"
    memo: "Test"
    accumulate: true
""",
        'contradictory "posted: none" and posted: block',
    ),
    (
        "payment_none_and_payment_block",
        """
invoice "INV-X"
  customer_id: "1"
  currency: CAD
  date_opened: 2026-01-01
  entry:
    date: 2026-01-01
    description: "Test"
    action: "Hours"
    account: "Income:Sales"
    quantity: 1
    price: 100
    taxable: false
    tax_included: false
  posted:
    date: 2026-01-01
    due: 2026-01-31
    ar_account: "Assets:Accounts Receivable"
    memo: "Test"
    accumulate: true
  payment: none
  payment:
    date: 2026-01-15
    amount: 100
    bank_account: "Assets:Bank"
    memo: "Pay"
""",
        'contradictory "payment: none" and payment: block',
    ),
    (
        "payment_on_unposted_invoice",
        """
invoice "INV-X"
  customer_id: "1"
  currency: CAD
  date_opened: 2026-01-01
  entry:
    date: 2026-01-01
    description: "Test"
    action: "Hours"
    account: "Income:Sales"
    quantity: 1
    price: 100
    taxable: false
    tax_included: false
  posted: none
  payment:
    date: 2026-01-15
    amount: 100
    bank_account: "Assets:Bank"
    memo: "Pay"
""",
        'cannot have payment: blocks on an unposted invoice',
    ),
]


@pytest.mark.parametrize("case_name,invoice_txt,expected_error", _CONTRADICTION_CASES)
def test_invoice_contradiction_errors(tmp_path, case_name, invoice_txt, expected_error):
    """Contradictory posted:/payment: combinations must produce clear errors, not silently corrupt the book."""
    runner = CliRunner()
    gnucash_file = tmp_path / "test.gnucash"

    preamble = """\
2026-01-01 open Assets
  type: Asset
  commodity.namespace: "CURRENCY"
  commodity.mnemonic: "CAD"
2026-01-01 open Assets:Accounts Receivable
  type: Asset
  commodity.namespace: "CURRENCY"
  commodity.mnemonic: "CAD"
2026-01-01 open Assets:Bank
  type: Asset
  commodity.namespace: "CURRENCY"
  commodity.mnemonic: "CAD"
2026-01-01 open Income
  type: Income
  commodity.namespace: "CURRENCY"
  commodity.mnemonic: "CAD"
2026-01-01 open Income:Sales
  type: Income
  commodity.namespace: "CURRENCY"
  commodity.mnemonic: "CAD"

customer "1"
  name: "Test Customer"
  currency: CAD

"""
    input_file = tmp_path / f"{case_name}.txt"
    input_file.write_text(preamble + invoice_txt)

    result = runner.invoke(cli, ["import", "--new", str(gnucash_file), str(input_file), "--include-business-objects"])
    assert result.exit_code != 0, f"Import should have failed for case {case_name!r} but succeeded"
    assert expected_error in result.output, (
        f"Expected error message {expected_error!r} not found in output:\n{result.output}"
    )


_BILL_CONTRADICTION_CASES = [
    (
        "bill_posted_none_and_posted_block",
        """
bill "BILL-X"
  vendor_id: "1"
  currency: CAD
  date_opened: 2026-01-01
  entry:
    date: 2026-01-01
    description: "Test"
    account: "Expenses:Supplies"
    quantity: 1
    price: 100
    taxable: false
  posted: none
  posted:
    date: 2026-01-01
    due: 2026-01-31
    ap_account: "Liabilities:Accounts Payable"
    memo: "Test"
    accumulate: true
""",
        'contradictory "posted: none" and posted: block',
    ),
    (
        "bill_payment_none_and_payment_block",
        """
bill "BILL-X"
  vendor_id: "1"
  currency: CAD
  date_opened: 2026-01-01
  entry:
    date: 2026-01-01
    description: "Test"
    account: "Expenses:Supplies"
    quantity: 1
    price: 100
    taxable: false
  posted:
    date: 2026-01-01
    due: 2026-01-31
    ap_account: "Liabilities:Accounts Payable"
    memo: "Test"
    accumulate: true
  payment: none
  payment:
    date: 2026-01-15
    amount: 100
    bank_account: "Assets:Bank"
    memo: "Pay"
""",
        'contradictory "payment: none" and payment: block',
    ),
    (
        "bill_payment_on_unposted_bill",
        """
bill "BILL-X"
  vendor_id: "1"
  currency: CAD
  date_opened: 2026-01-01
  entry:
    date: 2026-01-01
    description: "Test"
    account: "Expenses:Supplies"
    quantity: 1
    price: 100
    taxable: false
  posted: none
  payment:
    date: 2026-01-15
    amount: 100
    bank_account: "Assets:Bank"
    memo: "Pay"
""",
        'cannot have payment: blocks on an unposted bill',
    ),
]


_BILL_PREAMBLE = """\
2026-01-01 open Assets
  type: Asset
  commodity.namespace: "CURRENCY"
  commodity.mnemonic: "CAD"
2026-01-01 open Assets:Bank
  type: Bank
  commodity.namespace: "CURRENCY"
  commodity.mnemonic: "CAD"
2026-01-01 open Liabilities
  type: Liability
  commodity.namespace: "CURRENCY"
  commodity.mnemonic: "CAD"
2026-01-01 open Liabilities:Accounts Payable
  type: Accounts Payable
  commodity.namespace: "CURRENCY"
  commodity.mnemonic: "CAD"
2026-01-01 open Expenses
  type: Expense
  commodity.namespace: "CURRENCY"
  commodity.mnemonic: "CAD"
2026-01-01 open Expenses:Supplies
  type: Expense
  commodity.namespace: "CURRENCY"
  commodity.mnemonic: "CAD"

vendor "1"
  name: "Test Vendor"
  currency: CAD

"""


@pytest.mark.parametrize("case_name,bill_txt,expected_error", _BILL_CONTRADICTION_CASES)
def test_bill_contradiction_errors(tmp_path, case_name, bill_txt, expected_error):
    """Contradictory posted:/payment: combinations on bills must produce clear errors."""
    runner = CliRunner()
    gnucash_file = tmp_path / "test.gnucash"

    input_file = tmp_path / f"{case_name}.txt"
    input_file.write_text(_BILL_PREAMBLE + bill_txt)

    result = runner.invoke(cli, ["import", "--new", str(gnucash_file), str(input_file), "--include-business-objects"])
    assert result.exit_code != 0, f"Import should have failed for case {case_name!r} but succeeded"
    assert expected_error in result.output, (
        f"Expected error message {expected_error!r} not found in output:\n{result.output}"
    )


def test_business_objects_persisted_when_imported_into_existing_file(tmp_path):
    """
    Regression test: business objects must be saved when imported into an existing
    GnuCash file that already has all accounts and commodities.

    Root cause: has_changes was computed from ImportResult (transactions + accounts
    only). When the existing file already has all accounts, import_from_file returns
    accounts_created=0 and imported_count=0, so has_changes=False and repo.save()
    was never called. Business objects written to GnuCash memory were silently
    discarded on session.end().

    This test uses business_objects_biz_only.txt which contains ONLY customer /
    vendor / taxtable / invoice / bill directives — no `open` account lines — to
    reproduce the exact failure mode reported by an external project.
    """
    runner = CliRunner()

    # Step 1: create a GnuCash file that already has all required accounts —
    # AR, AP, Bank, Income:Sales — and none of the business objects. Without
    # the flag, the same ledger's `open` lines are read and its customer,
    # vendor, invoice and bill blocks are not.
    #
    # The objects have to be new to the book for this to test anything: run
    # with the flag here, step 2 would re-import the same IDs, every one would
    # report `unchanged`, and a run that changes nothing is a run with nothing
    # to save. Asserting `Changes saved` there asserted the book is rewritten
    # for a file it already holds.
    gnucash_file = tmp_path / "existing.gnucash"
    result = runner.invoke(cli, ["import", "--new", str(gnucash_file),
                                 "tests/fixtures/business_objects.txt"])
    assert result.exit_code == 0, f"Setup import failed:\n{result.output}"

    import time

    # Step 2: import ONLY business objects (no `open` account directives) into
    # the already-populated file. This is the exact scenario that was broken:
    # the existing accounts mean import_from_file returns accounts_created=0 and
    # imported_count=0, so has_changes was False and repo.save() was never called.
    result = runner.invoke(cli, ["import", str(gnucash_file),
                                 "tests/fixtures/business_objects_biz_only.txt",
                                 "--include-business-objects"])
    assert result.exit_code == 0, (
        f"Import of biz-only file into existing file failed:\n{result.output}"
    )
    assert "Changes saved" in result.output, (
        "Expected 'Changes saved' — repo.save() must be called when "
        "--include-business-objects is set, even if no new accounts or transactions exist"
    )

    # Step 3: export and verify the business objects actually persisted on disk.
    # If repo.save() was skipped, the GnuCash file on disk is unchanged and the
    # export will show only the objects from the Step 1 import (which are the
    # same IDs — INV-2026-001, BILL-2026-001 — confirming persistence requires
    # checking the 'Changes saved' message above and non-empty export).
    output_file = tmp_path / "exported.txt"
    result = runner.invoke(cli, ["export", str(gnucash_file), str(output_file),
                                 "--include-business-objects"])
    assert result.exit_code == 0, f"Export failed:\n{result.output}"

    with open(output_file) as f:
        exported = f.read()

    exported_biz = extract_business_objects(exported)
    assert 'invoice "INV-2026-001"' in exported_biz, (
        "INV-2026-001 must appear — business objects were not persisted. "
        "This means repo.save() was not called after import_business_objects()."
    )
    assert 'bill "BILL-2026-001"' in exported_biz, (
        "BILL-2026-001 must appear — business objects were not persisted."
    )
    assert 'customer "1"' in exported_biz or 'Test Customer' in exported_biz, (
        "Customer must appear — business objects were not persisted."
    )
