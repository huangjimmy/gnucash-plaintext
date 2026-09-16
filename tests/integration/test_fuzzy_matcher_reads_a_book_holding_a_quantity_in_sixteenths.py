"""The fuzzy matcher reads a book holding a quantity that has no decimal form at its unit.

Before matching anything it indexes every split in the book by amount. A split
of 3/16 of a share of a security traded in sixteenths came back from GnuCash as
the fraction it is, and the index handed that fraction to `Decimal`, which does
not take one — so a statement could not be matched against such a book at all.
"""

from datetime import date
from decimal import Decimal

from click.testing import CliRunner

from cli.main import cli
from infrastructure.pdf.standard_tx import Split, StandardTransaction
from repositories.gnucash_repository import GnuCashRepository
from services.gnucash_fuzzy_matcher import GnuCashFuzzyMatcher, MatchStatus


def test_a_statement_line_is_matched_against_it(tmp_path):
    book = tmp_path / 'book.gnucash'
    made = CliRunner().invoke(cli, [
        'import', '--new', str(book), 'tests/fixtures/a_security_traded_in_sixteenths.txt'])
    assert made.exit_code == 0, made.output

    line = StandardTransaction(
        post_date=date(2026, 3, 1), description='Deposit', currency='CAD',
        splits=[Split('Assets:Broker Cash', Decimal('20.00')),
                Split('Assets:OLDCO', Decimal('-20.00'))],
        source_pdfs=['broker.pdf'])

    result = GnuCashFuzzyMatcher(GnuCashRepository(str(book))).match(line)

    assert result.status == MatchStatus.NEW, result.status
