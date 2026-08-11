"""A beancount export writes the figure the book holds, to its last digit.

GnuCash keeps a smallest unit per account as well as per commodity, and stores
each amount at the account's. A fund declaring `fraction: 100` — the number on
a prospectus — held in an account kept to thousandths therefore carries
quantities like 12.345 units, and both this tool's importers accept them: a
security is judged against its account's unit, never against a currency's cent.

Written at the *commodity's* fraction on the way out, that holding exported as
12.35. An export that rounds away units the book holds is the one thing an
export must not do, and nothing said so: the figure looked ordinary, and only
comparing it with the book showed the third decimal missing.

The plaintext exporter has always written at the account's unit, so this is
also what makes the two exports agree about the same split.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner

from cli.main import cli

FUND = str(Path('tests/fixtures/fund_units_at_the_accounts_unit.txt'))


@pytest.fixture
def book(tmp_path):
    """12.345 FUNDX on an account kept to thousandths."""
    path = tmp_path / 'fund.gnucash'
    result = CliRunner().invoke(cli, ['import', '--new', str(path), FUND])
    assert result.exit_code == 0, result.output
    return path


class TestTheExport:
    def test_it_writes_all_three_decimals(self, book, tmp_path):
        out = tmp_path / 'out.beancount'
        result = CliRunner().invoke(cli, ['export-beancount', str(book), str(out)])

        assert result.exit_code == 0, result.output
        text = out.read_text()
        assert '12.345 FUND.FUNDX' in text, text

    def test_it_does_not_round_to_the_commoditys_fraction(self, book, tmp_path):
        """FUNDX declares `fraction: 100`; the account is kept finer."""
        out = tmp_path / 'out.beancount'
        CliRunner().invoke(cli, ['export-beancount', str(book), str(out)])
        text = out.read_text()

        assert '12.345 FUND.FUNDX' in text, text
        assert '12.35 FUND.FUNDX' not in text, text

    def test_the_two_exports_agree_about_the_same_split(self, book, tmp_path):
        """Plaintext has always written at the account's unit."""
        plain = tmp_path / 'out.txt'
        assert CliRunner().invoke(
            cli, ['export', str(book), str(plain)]).exit_code == 0
        assert '12.345 FUND.FUNDX' in plain.read_text(), plain.read_text()

        beans = tmp_path / 'out.beancount'
        assert CliRunner().invoke(
            cli, ['export-beancount', str(book), str(beans)]).exit_code == 0
        assert '12.345 FUND.FUNDX' in beans.read_text(), beans.read_text()


class TestTheRoundTrip:
    """Writing the third decimal is half of it; reading it back is the rest.

    Two things had to be carried for the figure to survive. The account's own
    smallest unit — `gnucash-scu`, `commodity_scu:` in plaintext — because the
    account was otherwise rebuilt at the commodity's fraction and GnuCash
    rounded every amount to it on save. And the `@ <rate> <commodity>` tail,
    because a posting valued at its own amount put 12.345 CAD against 1,234.50
    of cash, and GnuCash balanced that by inventing an `Imbalance-FUNDX`
    account holding 1,222.15 units of the fund.
    """

    def _round_tripped(self, book, tmp_path):
        out = tmp_path / 'out.beancount'
        assert CliRunner().invoke(
            cli, ['export-beancount', str(book), str(out)]).exit_code == 0

        back = tmp_path / 'back.gnucash'
        result = CliRunner().invoke(
            cli, ['import-beancount', str(back), str(out)])
        assert result.exit_code == 0, result.output

        listing = tmp_path / 'back.txt'
        assert CliRunner().invoke(
            cli, ['export', str(back), str(listing)]).exit_code == 0
        return listing.read_text()

    def test_the_quantity_survives(self, book, tmp_path):
        text = self._round_tripped(book, tmp_path)

        assert '12.345 FUND.FUNDX' in text, text

    def test_the_accounts_own_unit_survives_with_it(self, book, tmp_path):
        """Which is what lets the quantity survive the save."""
        text = self._round_tripped(book, tmp_path)

        assert 'commodity_scu: 1000' in text, text

    def test_nothing_is_scrubbed_into_an_imbalance(self, book, tmp_path):
        text = self._round_tripped(book, tmp_path)

        assert 'Imbalance' not in text, text

    def test_the_cash_side_still_says_what_it_paid(self, book, tmp_path):
        """1,234.50 CAD for 12.345 units at 100 — the value the rate states."""
        text = self._round_tripped(book, tmp_path)

        assert 'Assets:Bank -1234.50 CAD' in text, text
        assert 'value: "1234.50"' in text, text

    def test_a_figure_too_big_for_a_rounded_rate_still_balances(self, tmp_path):
        """¥2,000,000 worth 18,200.01 CAD — an ordinary yen bank balance.

        The rate is 0.0091000050, which no fixed number of decimals states
        exactly. Written as an 8-place rate and multiplied back out, the
        value lands a cent either side of 18,200.01 depending on which way
        the eighth digit went; the CAD side carries no rate and comes back
        exact, so the entry no longer sums to zero and GnuCash parks the
        difference. Stating the total instead, nothing is reconstructed.
        """
        source = tmp_path / 'jpy.gnucash'
        assert CliRunner().invoke(cli, [
            'import', '--new', str(source),
            'tests/fixtures/jpy_bought_at_an_unroundable_rate.txt',
        ]).exit_code == 0

        beans = tmp_path / 'jpy.beancount'
        assert CliRunner().invoke(
            cli, ['export-beancount', str(source), str(beans)]).exit_code == 0

        back = tmp_path / 'back.gnucash'
        result = CliRunner().invoke(
            cli, ['import-beancount', str(back), str(beans)])
        assert result.exit_code == 0, result.output

        listing = tmp_path / 'back.txt'
        assert CliRunner().invoke(
            cli, ['export', str(back), str(listing)]).exit_code == 0
        text = listing.read_text()

        assert 'Imbalance' not in text, text
        assert 'Assets:Bank:JPY 2000000 JPY' in text, text
        assert 'value: "18200.01"' in text, text
        assert 'Assets:Bank -18200.01 CAD' in text, text

    def test_the_entry_is_denominated_in_a_currency(self, book, tmp_path):
        """Not in the fund, which is what the first posting happened to hold.

        Taken from the first posting whatever it was, a share purchase was
        denominated in the share: the cash side was then valued in units of
        the fund, and everything downstream followed it.
        """
        text = self._round_tripped(book, tmp_path)

        assert 'currency.mnemonic: "CAD"' in text, text
        assert 'currency.mnemonic: "FUNDX"' not in text, text
