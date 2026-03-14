import os
import re

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

    # Test the print-invoice command
    result = runner.invoke(cli, ["print-invoice", str(gnucash_file), "--invoice-id", "INV-2026-001", "-o", str(pdf_file)])
    assert result.exit_code == 0, f"print-invoice failed:\n{result.output}"
    assert os.path.exists(pdf_file)
