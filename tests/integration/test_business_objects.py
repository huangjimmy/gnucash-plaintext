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

    # Extract only the business objects from the output and compare with the reference
    exported_biz = extract_business_objects(exported_text)

    with open("tests/fixtures/business_objects_only.txt") as f:
        reference_biz = extract_business_objects(f.read())

    assert exported_biz == reference_biz, (
        f"Business objects mismatch.\n"
        f"--- reference ---\n{reference_biz}\n"
        f"--- exported ---\n{exported_biz}"
    )

    # ── Per-invoice state assertions ──────────────────────────────────────────

    # INV-2026-001: posted, not paid
    # Must have a posted: block and an explicit "payment: none" sentinel
    inv1 = get_invoice_block(exported_biz, 'INV-2026-001')
    assert inv1, "INV-2026-001 must appear in export"
    assert '  posted:' in inv1, "INV-2026-001 must have a posted: block"
    assert '  payment: none' in inv1, "INV-2026-001 must have payment: none (not paid)"

    # INV-2026-002: unposted
    # Must appear (export now includes unposted) with both sentinels
    inv2 = get_invoice_block(exported_biz, 'INV-2026-002')
    assert inv2, "INV-2026-002 (unposted) must appear in export"
    assert '  posted: none' in inv2, "INV-2026-002 must have posted: none (unposted)"
    assert '  payment: none' in inv2, "INV-2026-002 must have payment: none (unposted, no payments)"

    # INV-2026-003: posted, single full payment
    inv3 = get_invoice_block(exported_biz, 'INV-2026-003')
    assert inv3, "INV-2026-003 must appear in export"
    assert '  posted:' in inv3, "INV-2026-003 must have a posted: block"
    assert '  payment:' in inv3, "INV-2026-003 must have a payment: block"
    assert 'payment: none' not in inv3, "INV-2026-003 must not have payment: none"
    assert inv3.count('  payment:') == 1, "INV-2026-003 must have exactly one payment block"

    # INV-2026-004: posted, two partial payments, amount still remaining
    inv4 = get_invoice_block(exported_biz, 'INV-2026-004')
    assert inv4, "INV-2026-004 must appear in export"
    assert '  posted:' in inv4, "INV-2026-004 must have a posted: block"
    assert inv4.count('  payment:') == 2, "INV-2026-004 must have exactly two payment blocks"
    assert 'payment: none' not in inv4
    assert 'Partial payment 1 for INV-2026-004' in inv4
    assert 'Partial payment 2 for INV-2026-004' in inv4

    # INV-2026-005: posted, two payments, fully paid (zero balance)
    inv5 = get_invoice_block(exported_biz, 'INV-2026-005')
    assert inv5, "INV-2026-005 must appear in export"
    assert '  posted:' in inv5, "INV-2026-005 must have a posted: block"
    assert inv5.count('  payment:') == 2, "INV-2026-005 must have exactly two payment blocks"
    assert 'payment: none' not in inv5
    assert 'First payment for INV-2026-005' in inv5
    assert 'Final payment for INV-2026-005' in inv5

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
