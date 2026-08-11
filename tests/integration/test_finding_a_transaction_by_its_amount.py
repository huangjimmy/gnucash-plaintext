"""`find-transactions --amount` answers about the figure the reader typed.

The command exists to hand back a GUID to paste into a `txn_guid:` line, so
the one thing it must not do is hand back the wrong transaction's. It matched
within half a cent of the amount asked for, which is not a distinction any
book makes: a fund account kept to thousandths holds 12.345 and 12.346 as two
different quantities, and asking for one answered with both — and with
everything from 12.341 to 12.349 besides.

The figure it prints has to be the one the book holds, too. Printed to two
decimals whatever the commodity, 12.345 units came back as 12.35 and ¥2,000 as
2000.00 — a quantity the account cannot hold and a figure with no meaning in
yen, either of which a reader would then copy into a file.

The amount is read as an exact number and compared as one, which is what the
rest of this tool does with money.

Every question this command asks of a split is a question about the split's
account — which one is it, and to what unit is it kept — so a split with no
account is worth knowing about rather than guessing at. It is not asserted
here, because the answer is GnuCash's and it is not the same one on every
supported version: given a book edited to take a `<split:account>` away, 5.x
drops the whole transaction rather than hand over a split with a null account,
and 4.x and earlier segfault inside `qof_session_load` before this tool is
given control at all. Either way no such split reaches the loop below, which
is why the null check the ctypes version carried was removed rather than
rewritten. Recorded in CLAUDE.md; a test cannot hold it, since the half that
is demonstrable takes the interpreter down on the other four builds.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner

from cli.main import cli

LEDGER = str(Path('tests/fixtures/two_fund_lots_a_thousandth_apart.txt'))


@pytest.fixture
def book(tmp_path):
    path = tmp_path / 'book.gnucash'
    result = CliRunner().invoke(cli, ['import', '--new', str(path), LEDGER])
    assert result.exit_code == 0, result.output
    return path


def _lines(result):
    return [line for line in result.output.splitlines() if line.strip()]


class TestMatchingAnAmount:
    def test_it_answers_with_the_one_asked_for(self, book):
        result = CliRunner().invoke(
            cli, ['find-transactions', str(book), '--amount', '12.345'])

        assert result.exit_code == 0, result.output
        lines = _lines(result)
        assert len(lines) == 1, lines
        assert 'Buy 12.345 units' in lines[0], lines

    def test_the_neighbour_a_thousandth_away_is_not_it(self, book):
        result = CliRunner().invoke(
            cli, ['find-transactions', str(book), '--amount', '12.346'])

        lines = _lines(result)
        assert len(lines) == 1, lines
        assert 'Buy 12.346 units' in lines[0], lines

    def test_an_amount_the_book_does_not_hold_matches_nothing(self, book):
        """12.3455 is half a thousandth from both, and is neither."""
        result = CliRunner().invoke(
            cli, ['find-transactions', str(book), '--amount', '12.3455'])

        assert 'No matching transactions found' in result.output, result.output


class TestWhatItPrints:
    def test_a_fund_quantity_keeps_its_third_decimal(self, book):
        result = CliRunner().invoke(
            cli, ['find-transactions', str(book), '--amount', '12.345'])

        assert '12.345' in result.output, result.output
        assert '12.35' not in result.output, result.output

    def test_yen_are_printed_as_yen(self, book):
        result = CliRunner().invoke(
            cli, ['find-transactions', str(book), '--amount', '2000'])

        assert '2000' in result.output, result.output
        assert '2000.00' not in result.output, result.output


class TestWhatItAsksFor:
    def test_no_filter_at_all_is_refused(self, book):
        result = CliRunner().invoke(cli, ['find-transactions', str(book)])

        assert result.exit_code != 0, result.output
        assert '--account' in result.output, result.output

    def test_an_amount_that_is_not_a_number_is_refused(self, book):
        result = CliRunner().invoke(
            cli, ['find-transactions', str(book), '--amount', '1.2.3'])

        assert result.exit_code != 0, result.output
        assert '1.2.3' in result.output, result.output

    def test_an_account_and_a_date_narrow_it_together(self, book):
        result = CliRunner().invoke(cli, [
            'find-transactions', str(book), '--account', 'Assets:Fund',
            '--date', '2026-02-02'])

        lines = _lines(result)
        assert len(lines) == 1, lines
        assert 'Buy 12.346 units' in lines[0], lines

    def test_a_date_with_nothing_on_it_matches_nothing(self, book):
        result = CliRunner().invoke(
            cli, ['find-transactions', str(book), '--date', '2026-03-01'])

        assert 'No matching transactions found' in result.output, result.output

    def test_a_date_it_cannot_read_is_refused(self, book):
        """Not answered with "nothing found", which is a statement about the
        book made for a question the command did not understand."""
        result = CliRunner().invoke(
            cli, ['find-transactions', str(book), '--date', '03/02/2026'])

        assert result.exit_code != 0, result.output
        assert 'YYYY-MM-DD' in result.output, result.output
