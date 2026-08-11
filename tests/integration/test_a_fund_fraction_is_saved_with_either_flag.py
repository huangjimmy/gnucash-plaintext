"""One file, one answer — a fund's restated fraction is saved either way.

A security's fraction is written into the GnuCash file, so restating one is a
change the book has to be saved for. Unlike an ISO currency's, which GnuCash
looks up by code and never writes, so restating that changes the session and
nothing else.

`--include-business-objects` used to run its own pass over commodities and
accounts before the transaction pass, so with the flag that pass made the
change and the transaction pass then found the fractions equal and reported
nothing. Counting the two kinds of update as one, the run printed `1 updated`
and then `Nothing to import`, saved nothing, and the fraction reverted on the
next read. Without the flag the same file saved.

That the flag decided whether a change survives is the shape this whole change
set exists to remove: a book should not depend on which flags were typed. The
second pass is gone — the file is read once and each declaration carried out
once — and this holds it either way, which is what it was written to say.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner

from cli.main import cli

BASE = str(Path('tests/fixtures/qqd_declared_as_a_fund.txt'))
RESTATED = str(Path('tests/fixtures/a_fund_restated_at_another_fraction.txt'))


def _fund_fraction(book):
    """What the book holds FUNDX's fraction as, read back from disk."""
    from repositories.gnucash_repository import GnuCashRepository, SessionMode
    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        commodity = repo.book.get_table().lookup('FUND', 'FUNDX')
        return commodity.get_fraction() if commodity is not None else None
    finally:
        repo.close()


@pytest.fixture
def book(tmp_path):
    """A book holding FUNDX at 100."""
    path = tmp_path / 'book.gnucash'
    ledger = tmp_path / 'base.txt'
    ledger.write_text(
        '2026-01-01 commodity FUNDX\n'
        '\tmnemonic: "FUNDX"\n'
        '\tfullname: "Example Fund"\n'
        '\tnamespace: "FUND"\n'
        '\tfraction: 100\n')
    result = CliRunner().invoke(cli, ['import', '--new', str(path), str(ledger)])
    assert result.exit_code == 0, result.output
    assert _fund_fraction(path) == 100
    return path


class TestWithoutTheFlag:
    def test_the_fraction_is_saved(self, book):
        result = CliRunner().invoke(cli, ['import', str(book), RESTATED])

        assert result.exit_code == 0, result.output
        assert _fund_fraction(book) == 1000, result.output


class TestWithBusinessObjects:
    def test_the_fraction_is_saved_too(self, book):
        """The pre-pass makes the change, so the pre-pass has to say it is one."""
        result = CliRunner().invoke(cli, [
            'import', str(book), RESTATED, '--include-business-objects'])

        assert result.exit_code == 0, result.output
        assert _fund_fraction(book) == 1000, result.output

    def test_it_does_not_report_a_change_it_then_discards(self, book):
        """Reporting `1 updated` beside `Nothing to import` is the shape of
        the defect: the run said it did something and saved nothing."""
        result = CliRunner().invoke(cli, [
            'import', str(book), RESTATED, '--include-business-objects'])

        if '1 updated' in result.output:
            assert 'Nothing to import' not in result.output, result.output
