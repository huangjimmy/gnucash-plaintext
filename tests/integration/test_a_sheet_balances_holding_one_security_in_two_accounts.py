"""A balance sheet balances when one security sits in two accounts.

GnuCash converts a commodity's whole holding once: two accounts holding one
unit each of something worth 10.005 CAD come to 20.01 in `total_assets`. The
gain this page states for them is added up account by account, each rounded to
money on its own, which comes to 10.01 twice — 20.02.

A cent then separates the two sides of a sheet that must balance, and the book
that shows it holds no foreign currency and opens no cost basis at all: a share
is counted in units and priced rather than converted, so it keeps GnuCash's own
revaluation whatever this change does. Two brokerage accounts holding one stock
is an ordinary thing for a company to have.

Adding the revaluation up per account is deliberate — it is what lets the
working beneath a key add up to the key — so what this asserts is the invariant
that has to survive that choice, rather than any particular figure.
"""

from fractions import Fraction

from click.testing import CliRunner

from tests.conftest import _run
from tests.integration.text_report_pages import block_of, block_total_of, key_of

TWO_BROKERS = 'tests/fixtures/a_cad_book_holding_one_security_in_two_accounts.txt'
AS_OF = '2026-12-31'


def _page(tmp_path):
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    made = _run(runner, 'import', '--new', str(book), TWO_BROKERS)
    assert made.exit_code == 0, made.output

    drawn = _run(runner, 'balance-sheet', str(book), '--as-of', AS_OF)
    assert drawn.exit_code == 0, drawn.output
    return drawn.output


def test_the_gain_is_what_gnucash_makes_of_the_holding(tmp_path):
    """One commodity, one conversion — not one conversion per account.

    `gnucash_balancing_amount` is GnuCash's own figure for the same book, so
    where every gain on the page is GnuCash's revaluation the two agree. This
    asserts that they do, rather than either figure on its own: it holds
    whatever the price and the rounding come to, and it is the check that
    catches the itemized block stating a figure of its own invention under
    GnuCash's name.
    """
    page = _page(tmp_path)

    assert block_total_of(page, 'unrealized_gains_other') == block_total_of(
        page, 'gnucash_balancing_amount'), page


def test_the_sheet_balances(tmp_path):
    """Whichever way the holdings are added up, the two sides must agree."""
    page = _page(tmp_path)

    assert key_of(page, 'total_assets') == key_of(
        page, 'total_liabilities_and_equity'), page


def test_the_gain_is_stated_of_the_commodity_and_the_accounts_are_listed_under_it(tmp_path):
    """One `security:` for the holding, because that is what the figure is of.

    GnuCash revalues a holding, not an account: it takes the whole quantity
    through the price once. A figure worked out per account stated a slice
    nobody computed, rounded on its own — two such came to 0.00 apiece where
    GnuCash made the pair 0.01.

    So the two accounts appear beneath the one security, as the balances the
    quantity was added up from, and the gain is stated once against the whole
    2.0000 XYZ rather than once per account.
    """
    page = _page(tmp_path)
    block = block_of(page, 'unrealized_gains_other')
    lines = block.splitlines()

    assert [line for line in lines if line.strip() == 'security:'] == [
        '\t\t\tsecurity:'], block
    assert '\t\t\t\tcommodity.mnemonic: "XYZ"' in lines, block
    assert '\t\t\t\tquantity: 2.0000' in lines, block
    assert len([line for line in lines if line.strip() == 'account:']) == 2, block
    assert block_total_of(page, 'unrealized_gains_other') == Fraction(1, 100)


def test_gnucashs_own_amount_lists_every_commodity_its_figure_is_summed_from(tmp_path):
    """Both commodities, because GnuCash's own figure is built from both.

    GnuCash merges the account balances, keyed by each account's own
    commodity, and subtracts the splits' values, keyed by the transaction's
    currency. This book has one of each: the shares are held in XYZ and no
    split is valued in it, while every split's value is in Canadian dollars.

    A block that grouped only by the currency splits are valued in listed the
    CAD term alone and stated −20.00 under a key whose own figure is 0.01.
    What is asserted here is that both terms are on the page and that they
    come to the figure, never either term on its own.
    """
    page = _page(tmp_path)
    lines = block_of(page, 'gnucash_balancing_amount').splitlines()

    assert '\t\t\t\tcommodity.mnemonic: "CAD"' in lines, lines
    assert '\t\t\t\tcommodity.mnemonic: "XYZ"' in lines, lines

    converted = [Fraction(line.split(': ')[1].split(' #')[0])
                 for line in lines if 'balance_sheet_value: ' in line]
    assert len(converted) == 2, lines
    assert sum(converted) == block_total_of(page, 'gnucash_balancing_amount'), lines
