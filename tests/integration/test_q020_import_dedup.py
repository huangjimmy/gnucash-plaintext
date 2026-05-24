"""
Q-020 regression: `gnucash-plaintext import` must respect the full duplicate
signature `(date, accounts, doc_link, tx_num, owner)` — not just
`(date, accounts)`.

The buggy inline scan in `import_from_file` collapsed same-day same-account
transactions that genuinely differed on `doc_link` or `tx_num` (or both).
This drives the CLI end-to-end so the wiring
`cli/import_cmd.py → use_case.import_from_file → matcher` is exercised.
"""

import time
from pathlib import Path

from click.testing import CliRunner

from cli.import_cmd import import_transactions

FIXTURES = Path(__file__).parent.parent / 'fixtures'


def _import(runner, gnucash_file, fixture_name):
    # GnuCash backup filenames include a wall-clock timestamp with one-second
    # resolution; consecutive saves within the same second collide with
    # ERR_FILEIO_BACKUP_ERROR. Sleep before each invocation to keep tests
    # deterministic across distros.
    time.sleep(1)
    return runner.invoke(import_transactions, [gnucash_file, str(FIXTURES / fixture_name)])


class TestImportDedupSignature:

    def test_doc_link_and_tx_num_each_distinguish_transactions(self, temp_gnucash_file):
        """
        Sequence of imports against a single GnuCash file:

        1. Import trip1 (CHK-001, doc_link=trip1.txt) → 1 imported.
        2. Re-import trip1 → 0 imported, 1 skipped (genuine duplicate).
        3. Import trip2 (CHK-001, doc_link=trip2.txt — different doc_link)
           → 1 imported (the bug would have dropped this).
        4. Import trip3 (CHK-002, doc_link=trip1.txt — different tx_num)
           → 1 imported (the bug would have dropped this).
        """
        runner = CliRunner()

        result = _import(runner, temp_gnucash_file, 'q020_trip1.txt')
        assert result.exit_code == 0, result.output
        assert 'Transactions: 1' in result.output, result.output

        result = _import(runner, temp_gnucash_file, 'q020_trip1.txt')
        assert result.exit_code == 0, result.output
        assert 'Transactions: 0' in result.output, result.output
        assert 'Skipped:      1' in result.output, result.output

        result = _import(runner, temp_gnucash_file, 'q020_trip2_different_doclink.txt')
        assert result.exit_code == 0, result.output
        assert 'Transactions: 1' in result.output, (
            f"trip2 differs only by doc_link and was incorrectly skipped:\n{result.output}"
        )

        result = _import(runner, temp_gnucash_file, 'q020_trip3_different_num.txt')
        assert result.exit_code == 0, result.output
        assert 'Transactions: 1' in result.output, (
            f"trip3 differs only by tx_num and was incorrectly skipped:\n{result.output}"
        )
