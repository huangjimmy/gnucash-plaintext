"""Declaring a finer `fraction:` for a currency does not make sub-cent money.

An amount is judged against its currency's smallest unit as well as its
account's, and the currency's comes from the commodity in the book. A file may
also *declare* a commodity — and for an ISO currency GnuCash keeps its own
fraction and never saves a changed one, so a declared `fraction: 1000` for CAD
lives for the length of the import and no longer.

Read from that session commodity, the rule is one a file can widen its way
past: `1.819 CAD` is accepted, the run reports `Errors: 0`, and the book is
saved. Opened again, CAD is a hundredth, the split is sub-cent, and `export`
refuses the whole book — with no `--skip-unwritable` and nothing to correct
from inside this tool. A clean import would have produced a book this tool
cannot get back out.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner

from cli.main import cli

LEDGER = str(Path('tests/fixtures/a_file_widening_the_base_currency.txt'))


@pytest.fixture(params=[[], ['--include-business-objects']],
                ids=['bare', 'with business objects'])
def result_and_book(request, tmp_path):
    """Both ways in, because the flag decides which passes run.

    The commodity is declared once in the pre-pass and again in the
    transaction pass, with the run-state reset between them — so a rule that
    remembers something from the first was reading nothing by the second, and
    the same file imported cleanly with the flag and was refused without it.
    """
    book = tmp_path / 'widened.gnucash'
    result = CliRunner().invoke(
        cli, ['import', '--new', str(book), LEDGER] + request.param)
    return result, book


class TestTheSameOnAStatedBalance:
    """The rule on `cost_basis_balance:` is the rule on `amount:`.

    Three copies of "what unit must this figure fit" live in this importer, and
    the comment on this one says why that matters: three copies that disagree
    is how the odd one out becomes the reachable one. The amount was fixed and
    this was not, so a file could still widen its way past it — with the amount
    itself written in whole cents so the guarded rule never fired.
    """

    STATED = str(Path(
        'tests/fixtures/a_stated_balance_behind_a_widened_currency.txt'))

    @pytest.fixture(params=[[], ['--include-business-objects']],
                    ids=['bare', 'with business objects'])
    def outcome(self, request, tmp_path):
        book = tmp_path / 'stated.gnucash'
        result = CliRunner().invoke(
            cli, ['import', '--new', str(book), self.STATED] + request.param)
        return result, book

    def test_the_balance_is_refused(self, outcome):
        result, _book = outcome

        assert result.exit_code != 0, result.output
        assert '60.001' in result.output, result.output

    def test_the_book_holds_no_balance_it_cannot_express(self, outcome):
        """And so the export of what did land reads back in."""
        _result, book = outcome

        listed = CliRunner().invoke(cli, ['fx-balances', str(book)])
        assert listed.exit_code == 0, listed.output
        assert '60.00' not in listed.output, listed.output


class TestTheDeclaredFractionDoesNotLoosenTheRule:
    def test_the_amount_is_still_refused(self, result_and_book):
        result, _book = result_and_book

        assert result.exit_code != 0, result.output
        assert '1.819' in result.output, result.output

    def test_what_was_written_can_still_be_exported(self, result_and_book,
                                                    tmp_path):
        """The whole point: what a run leaves has to come back out again.

        A bare import saves what did land and exits 1 for what did not, so a
        book is expected here — what must not be in it is the split the widened
        fraction would have let through. Measured before the refusal: the
        import exited 0 and the export of the book it wrote exited 1.
        """
        _result, book = result_and_book

        out = tmp_path / 'out.txt'
        exported = CliRunner().invoke(cli, ['export', str(book), str(out)])
        assert exported.exit_code == 0, exported.output
        assert '1.819' not in out.read_text(), out.read_text()
