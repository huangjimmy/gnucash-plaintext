"""A currency fraction the file cannot keep is not a reason to save.

GnuCash writes an ISO currency without a fraction, looking it up by code when
it reads the book back. So a `fraction:` stated on a CURRENCY commodity is a
session value: it governs the rounding of that run and is gone from the file
afterwards.

Counted as a change, that made the difference permanent in the worst way — the
run saved because the fraction "changed", the save could not keep it, and the
next run found the same mismatch and saved again. An unchanged ledger rewrote
the book every time it was imported, leaving another timestamped backup each
time.

Nobody has to type an odd fraction to meet it. GnuCash disagrees with itself
about KRW — 1/100 before 5.15, 1 after — so a book carried between two
supported distributions hits this on every import.

A security's fraction *is* written into the file, so a fund or a stock still
counts as changed: `test_account_scu.py` and the commodity round-trip tests
cover that side.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner

from cli.main import cli

LEDGER = str(Path('tests/fixtures/a_currency_fraction_gnucash_will_not_keep.txt'))


@pytest.fixture
def book(tmp_path):
    path = tmp_path / 'book.gnucash'
    result = CliRunner().invoke(cli, ['import', '--new', str(path), LEDGER])
    assert result.exit_code == 0, result.output
    return path


class TestTheSecondImport:
    def test_it_succeeds(self, book):
        result = CliRunner().invoke(cli, ['import', str(book), LEDGER])

        assert result.exit_code == 0, result.output

    def test_the_restatement_is_still_reported(self, book):
        """A reader moving a file between GnuCash versions needs to see it —
        it is what the run did to the session."""
        result = CliRunner().invoke(cli, ['import', str(book), LEDGER])

        assert 'Commodities:  0 created, 1 updated' in result.output, result.output

    def test_it_does_not_save_the_book(self, book):
        """The whole point: an unchanged ledger leaves the file alone."""
        result = CliRunner().invoke(cli, ['import', str(book), LEDGER])

        assert '✓ Changes saved' not in result.output, result.output


class TestItKeepsHappening:
    def test_a_third_import_is_still_quiet(self, book):
        """A loop shows up on the run after the one that was supposed to fix
        it, so two more runs is the shape that catches it."""
        runner = CliRunner()
        runner.invoke(cli, ['import', str(book), LEDGER])

        result = runner.invoke(cli, ['import', str(book), LEDGER])

        assert '✓ Changes saved' not in result.output, result.output
