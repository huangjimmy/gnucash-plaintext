"""Q-035: `--fx-rates` takes dated rates, and keeps taking flat ones.

One file serves every command: the flat `USD: 1.36` the reporting commands have
always accepted still means CAD per unit, and a dated block gives a rate per
day. Lookups take the most recent quote on or before the date asked for; a date
earlier than every quote is an error rather than an extrapolation.
"""

from datetime import date
from fractions import Fraction

import pytest

from services.fx_rates import FxRates, MissingFxRateError


def _write(tmp_path, text):
    path = tmp_path / 'rates.yaml'
    path.write_text(text)
    return str(path)


def test_flat_rates_still_load_and_convert(tmp_path):
    rates = FxRates.load(_write(tmp_path, 'USD: 1.36\nHKD: 0.172\n'))
    assert rates.rate_fraction('USD') == Fraction('1.36')
    assert rates.to_cad(Fraction(100), 'USD') == Fraction(136)
    assert rates.to_cad(Fraction(100), 'CAD') == Fraction(100)


def test_rates_are_exact_fractions_not_floats(tmp_path):
    """1.35 is 27/20 — the number the user wrote — so 100 USD is exactly
    135 CAD and not 134.99999999999999."""
    rates = FxRates.load(_write(tmp_path, 'USD: 1.35\n'))
    assert rates.rate_fraction('USD') == Fraction(27, 20)
    assert rates.to_cad(Fraction(100), 'USD') == Fraction(135)


def test_dated_rates_take_the_most_recent_quote_on_or_before(tmp_path):
    rates = FxRates.load(_write(
        tmp_path, 'USD/CAD:\n  2026-01-05: 1.35\n  2026-02-20: 1.37\n'))
    assert rates.rate_fraction('USD', date(2026, 1, 5)) == Fraction(27, 20)
    assert rates.rate_fraction('USD', date(2026, 2, 19)) == Fraction(27, 20)
    assert rates.rate_fraction('USD', date(2026, 2, 20)) == Fraction(137, 100)
    assert rates.rate_fraction('USD', date(2026, 12, 31)) == Fraction(137, 100)


def test_a_date_before_every_quote_is_an_error(tmp_path):
    rates = FxRates.load(_write(
        tmp_path, 'USD/CAD:\n  2026-01-05: 1.35\n  2026-02-20: 1.37\n'))
    with pytest.raises(MissingFxRateError) as excinfo:
        rates.rate_fraction('USD', date(2025, 12, 31))
    message = str(excinfo.value)
    assert '2026-01-05' in message, message
    assert '2025-12-31' in message, message


def test_undated_lookup_on_dated_rates_uses_the_latest_quote(tmp_path):
    rates = FxRates.load(_write(
        tmp_path, 'USD/CAD:\n  2026-01-05: 1.35\n  2026-02-20: 1.37\n'))
    assert rates.rate_fraction('USD') == Fraction(137, 100)


def test_both_forms_may_share_one_file(tmp_path):
    rates = FxRates.load(_write(
        tmp_path, 'HKD: 0.172\nUSD/CAD:\n  2026-01-05: 1.35\n'))
    assert rates.rate_fraction('HKD') == Fraction(43, 250)
    assert rates.rate_fraction('USD', date(2026, 6, 1)) == Fraction(27, 20)
    assert rates.has_rate('HKD') and rates.has_rate('USD')


def test_the_pair_spelling_names_the_same_currency(tmp_path):
    """`USD` and `USD/CAD` are one rate; a pair to anything but CAD is not a
    conversion this tool performs."""
    rates = FxRates.load(_write(tmp_path, 'USD/CAD: 1.36\n'))
    assert rates.rate_fraction('USD') == Fraction(34, 25)

    with pytest.raises(ValueError):
        FxRates({'USD/EUR': 1.1})


def test_missing_currency_names_the_flag(tmp_path):
    rates = FxRates.load(_write(tmp_path, 'USD: 1.36\n'))
    with pytest.raises(MissingFxRateError) as excinfo:
        rates.rate_fraction('JPY')
    assert '--fx-rates' in str(excinfo.value)


def test_a_non_numeric_or_negative_rate_is_rejected(tmp_path):
    with pytest.raises(ValueError):
        FxRates.load(_write(tmp_path, 'USD: not-a-number\n'))
    with pytest.raises(ValueError):
        FxRates.load(_write(tmp_path, 'USD: -1.3\n'))
    with pytest.raises(ValueError):
        FxRates.load(_write(tmp_path, 'USD/CAD:\n  2026-01-05: -1.35\n'))
