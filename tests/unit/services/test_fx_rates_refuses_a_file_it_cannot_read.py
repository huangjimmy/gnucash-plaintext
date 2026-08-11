"""A rates file is checked before any figure is taken from it.

Every currency conversion this tool does is priced from this file, and a rate
read wrong is not visible afterwards: the report balances, the totals add up,
and the number is simply the wrong one. So the file is validated as a whole
when it loads — a key that is not a currency, a block with no quotes in it, a
rate that is not a number — rather than failing at whichever transaction
happened to need the bad entry first.

Dates are the other half. A YAML date key comes back as three different Python
types depending on how it was written, and all three name the same day: bare
`2026-01-05` is a `date`, one with a time on it is a `datetime`, and a quoted
one is a `str`. A file that a person hand-edited, or that a spreadsheet
exported, is as likely to hold any of them.

`test_fx_rates_dated.py` holds the lookups; this is what happens before there
is anything to look up.
"""

from datetime import date
from fractions import Fraction

import pytest

from services.fx_rates import FxRates


def _write(tmp_path, text):
    path = tmp_path / 'rates.yaml'
    path.write_text(text)
    return str(path)


class TestHowTheDayIsWritten:
    """Three spellings, one day — a quote must not be lost to its notation."""

    def test_a_bare_date_is_a_day(self, tmp_path):
        rates = FxRates.load(_write(tmp_path, 'USD/CAD:\n  2026-01-05: 1.35\n'))

        assert rates.rate_fraction('USD', date(2026, 1, 5)) == Fraction('1.35')

    def test_a_date_carrying_a_time_is_the_same_day(self, tmp_path):
        """A spreadsheet export writes midnight onto every date it has."""
        rates = FxRates.load(
            _write(tmp_path, 'USD/CAD:\n  2026-01-05 00:00:00: 1.35\n'))

        assert rates.rate_fraction('USD', date(2026, 1, 5)) == Fraction('1.35')

    def test_a_quoted_date_is_the_same_day(self, tmp_path):
        """Quoting it keeps YAML from parsing it, and it is still a date."""
        rates = FxRates.load(
            _write(tmp_path, "USD/CAD:\n  '2026-01-05': 1.35\n"))

        assert rates.rate_fraction('USD', date(2026, 1, 5)) == Fraction('1.35')

    def test_the_three_spellings_agree(self, tmp_path):
        """Because they are the same fact written three ways."""
        bare = FxRates.load(_write(tmp_path, 'USD/CAD:\n  2026-01-05: 1.35\n'))
        timed = FxRates.load(
            _write(tmp_path, 'USD/CAD:\n  2026-01-05 00:00:00: 1.35\n'))
        quoted = FxRates.load(_write(tmp_path, "USD/CAD:\n  '2026-01-05': 1.35\n"))

        asked = date(2026, 1, 5)
        assert (bare.rate_fraction('USD', asked)
                == timed.rate_fraction('USD', asked)
                == quoted.rate_fraction('USD', asked))


class TestAKeyThatIsNotACurrency:
    def test_a_number_is_refused(self, tmp_path):
        """`2026: 1.35` — a year where a currency code goes."""
        with pytest.raises(ValueError, match='must be a string'):
            FxRates.load(_write(tmp_path, '2026: 1.35\n'))

    def test_the_key_it_could_not_read_is_shown(self, tmp_path):
        with pytest.raises(ValueError, match='2026'):
            FxRates.load(_write(tmp_path, '2026: 1.35\n'))


class TestADatedBlockWithNoQuotesInIt:
    def test_it_is_refused_rather_than_read_as_no_rate(self, tmp_path):
        """Otherwise the currency is silently absent and every amount in it
        fails later, one transaction at a time, saying the file has no rate for
        a currency the file plainly names."""
        with pytest.raises(ValueError, match='are empty'):
            FxRates.load(_write(tmp_path, 'USD: {}\n'))

    def test_the_currency_is_named(self, tmp_path):
        with pytest.raises(ValueError, match='USD'):
            FxRates.load(_write(tmp_path, 'USD: {}\n'))

    def test_the_constructor_refuses_it_too(self):
        """`load` is not the only door: `FxRates({...})` is called directly by
        callers that build rates in memory, and an empty block means the same
        nothing there."""
        with pytest.raises(ValueError, match='are empty'):
            FxRates({'USD': {}})


class TestAQuoteThatIsNotANumber:
    def test_it_is_refused(self, tmp_path):
        with pytest.raises(ValueError, match='must be a number'):
            FxRates.load(_write(tmp_path, 'USD/CAD:\n  2026-01-05: about 1.35\n'))

    def test_the_day_and_the_value_are_both_named(self, tmp_path):
        """The file may hold hundreds of days; one of them is wrong."""
        with pytest.raises(ValueError, match='2026-01-05'):
            FxRates.load(_write(tmp_path, 'USD/CAD:\n  2026-01-05: about 1.35\n'))


class TestWhichCurrenciesAreDated:
    def test_a_dated_currency_says_so(self, tmp_path):
        rates = FxRates.load(
            _write(tmp_path, 'USD/CAD:\n  2026-01-05: 1.35\nHKD: 0.172\n'))

        assert rates.is_dated('USD') is True

    def test_a_flat_one_does_not(self, tmp_path):
        rates = FxRates.load(
            _write(tmp_path, 'USD/CAD:\n  2026-01-05: 1.35\nHKD: 0.172\n'))

        assert rates.is_dated('HKD') is False

    def test_a_currency_the_file_never_mentions_does_not(self, tmp_path):
        rates = FxRates.load(_write(tmp_path, 'HKD: 0.172\n'))

        assert rates.is_dated('JPY') is False

    def test_the_code_is_read_however_it_is_cased(self, tmp_path):
        """As every other lookup on this class reads it."""
        rates = FxRates.load(_write(tmp_path, 'USD/CAD:\n  2026-01-05: 1.35\n'))

        assert rates.is_dated('usd') is True
