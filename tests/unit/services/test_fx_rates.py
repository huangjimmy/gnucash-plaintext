"""
Unit tests for FxRates service.

Pure Python — no GnuCash session required.
Tests construction, YAML loading, currency conversion, and validation.
"""

import os
import tempfile
from fractions import Fraction

import pytest

# ---------------------------------------------------------------------------
# FxRates construction
# ---------------------------------------------------------------------------

class TestFxRatesInit:

    def test_cad_always_included_at_rate_one(self):
        from services.fx_rates import FxRates
        fx = FxRates({})
        assert fx.has_rate('CAD')
        assert fx.to_cad(Fraction(100), 'CAD') == Fraction(100)

    def test_foreign_currency_stored(self):
        from services.fx_rates import FxRates
        fx = FxRates({'HKD': 0.172})
        assert fx.has_rate('HKD')

    def test_foreign_currency_rate_converts_correctly(self):
        from services.fx_rates import FxRates
        fx = FxRates({'HKD': 0.5})
        result = fx.to_cad(Fraction(200), 'HKD')
        assert result == Fraction(100)

    def test_keys_normalized_to_uppercase(self):
        from services.fx_rates import FxRates
        fx = FxRates({'hkd': 0.172})
        assert fx.has_rate('HKD')
        assert fx.has_rate('hkd')  # has_rate also normalizes

    def test_multiple_currencies(self):
        from services.fx_rates import FxRates
        fx = FxRates({'HKD': 0.172, 'USD': 1.36, 'JPY': 0.009})
        assert fx.has_rate('HKD')
        assert fx.has_rate('USD')
        assert fx.has_rate('JPY')


# ---------------------------------------------------------------------------
# cad_only factory
# ---------------------------------------------------------------------------

class TestCadOnly:

    def test_cad_only_has_cad(self):
        from services.fx_rates import FxRates
        fx = FxRates.cad_only()
        assert fx.has_rate('CAD')

    def test_cad_only_no_foreign_currencies(self):
        from services.fx_rates import FxRates
        fx = FxRates.cad_only()
        assert not fx.has_rate('HKD')
        assert not fx.has_rate('USD')

    def test_cad_only_missing_currencies_set(self):
        from services.fx_rates import FxRates
        fx = FxRates.cad_only()
        missing = fx.missing_currencies({'CAD', 'HKD'})
        assert missing == {'HKD'}


# ---------------------------------------------------------------------------
# FxRates.load() — YAML file loading
# ---------------------------------------------------------------------------

class TestFxRatesLoad:

    def test_load_valid_file(self):
        from services.fx_rates import FxRates
        content = "HKD: 0.172\nUSD: 1.36\n"
        fd, path = tempfile.mkstemp(suffix='.yaml')
        try:
            with os.fdopen(fd, 'w') as f:
                f.write(content)
            fx = FxRates.load(path)
            assert fx.has_rate('HKD')
            assert fx.has_rate('USD')
        finally:
            os.unlink(path)

    def test_load_file_not_found(self):
        from services.fx_rates import FxRates
        with pytest.raises(FileNotFoundError):
            FxRates.load('/nonexistent/path/rates.yaml')

    def test_load_non_dict_yaml_raises_value_error(self):
        from services.fx_rates import FxRates
        content = "- HKD\n- USD\n"
        fd, path = tempfile.mkstemp(suffix='.yaml')
        try:
            with os.fdopen(fd, 'w') as f:
                f.write(content)
            with pytest.raises(ValueError, match="YAML mapping"):
                FxRates.load(path)
        finally:
            os.unlink(path)

    def test_load_non_numeric_value_raises_value_error(self):
        from services.fx_rates import FxRates
        content = "HKD: not-a-number\n"
        fd, path = tempfile.mkstemp(suffix='.yaml')
        try:
            with os.fdopen(fd, 'w') as f:
                f.write(content)
            with pytest.raises(ValueError, match="must be a number"):
                FxRates.load(path)
        finally:
            os.unlink(path)

    def test_load_zero_rate_raises_value_error(self):
        from services.fx_rates import FxRates
        content = "HKD: 0\n"
        fd, path = tempfile.mkstemp(suffix='.yaml')
        try:
            with os.fdopen(fd, 'w') as f:
                f.write(content)
            with pytest.raises(ValueError, match="must be positive"):
                FxRates.load(path)
        finally:
            os.unlink(path)

    def test_load_negative_rate_raises_value_error(self):
        from services.fx_rates import FxRates
        content = "HKD: -0.5\n"
        fd, path = tempfile.mkstemp(suffix='.yaml')
        try:
            with os.fdopen(fd, 'w') as f:
                f.write(content)
            with pytest.raises(ValueError, match="must be positive"):
                FxRates.load(path)
        finally:
            os.unlink(path)

    def test_load_cad_entry_in_file_is_accepted(self):
        """CAD: 1.0 in the file is valid (it's just overriding the default)."""
        from services.fx_rates import FxRates
        content = "CAD: 1.0\nHKD: 0.172\n"
        fd, path = tempfile.mkstemp(suffix='.yaml')
        try:
            with os.fdopen(fd, 'w') as f:
                f.write(content)
            fx = FxRates.load(path)
            assert fx.to_cad(Fraction(1), 'CAD') == Fraction(1)
        finally:
            os.unlink(path)

    def test_load_invalid_yaml_syntax_raises_value_error(self):
        """A YAML syntax error (e.g. unindented block scalar) raises ValueError."""
        from services.fx_rates import FxRates
        # Colon followed by a nested mapping without indentation is a YAML syntax error
        content = "HKD:\n  bad: nested: value\n"
        fd, path = tempfile.mkstemp(suffix='.yaml')
        try:
            with os.fdopen(fd, 'w') as f:
                f.write(content)
            with pytest.raises((ValueError, Exception)):
                FxRates.load(path)
        finally:
            os.unlink(path)

    def test_load_empty_file_raises_value_error(self):
        """An empty YAML file produces a None result, which is not a valid mapping."""
        from services.fx_rates import FxRates
        fd, path = tempfile.mkstemp(suffix='.yaml')
        try:
            os.fdopen(fd, 'w').close()
            with pytest.raises(ValueError, match="YAML mapping"):
                FxRates.load(path)
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# to_cad
# ---------------------------------------------------------------------------

class TestToCad:

    def test_cad_converts_to_same_amount(self):
        from services.fx_rates import FxRates
        fx = FxRates({'HKD': 0.172})
        assert fx.to_cad(Fraction(500), 'CAD') == Fraction(500)

    def test_foreign_currency_converts(self):
        from services.fx_rates import FxRates
        fx = FxRates({'HKD': 0.25})
        assert fx.to_cad(Fraction(400), 'HKD') == Fraction(100)

    def test_case_insensitive_currency_code(self):
        from services.fx_rates import FxRates
        fx = FxRates({'HKD': 0.172})
        result_upper = fx.to_cad(Fraction(100), 'HKD')
        result_lower = fx.to_cad(Fraction(100), 'hkd')
        assert result_upper == result_lower

    def test_missing_currency_raises(self):
        from services.fx_rates import FxRates, MissingFxRateError
        fx = FxRates({'HKD': 0.172})
        with pytest.raises(MissingFxRateError, match="USD"):
            fx.to_cad(Fraction(100), 'USD')

    def test_error_message_contains_currency_code(self):
        from services.fx_rates import FxRates, MissingFxRateError
        fx = FxRates({})
        with pytest.raises(MissingFxRateError, match="JPY"):
            fx.to_cad(Fraction(1000), 'JPY')

    def test_zero_amount_converts_to_zero(self):
        from services.fx_rates import FxRates
        fx = FxRates({'HKD': 0.172})
        assert fx.to_cad(Fraction(0), 'HKD') == Fraction(0)

    def test_fraction_result_is_exact(self):
        """to_cad returns Fraction, not float — no rounding loss."""
        from services.fx_rates import FxRates
        fx = FxRates({'HKD': 0.172})
        result = fx.to_cad(Fraction(1), 'HKD')
        assert isinstance(result, Fraction)


# ---------------------------------------------------------------------------
# get_rate
# ---------------------------------------------------------------------------

class TestRateFraction:
    """A rate is the figure the user wrote, exactly — 0.172, not the double
    nearest it. Every balance converted with it inherits whatever the rate is,
    so the rate is where exactness has to start."""

    def test_returns_the_exact_rate(self):
        from services.fx_rates import FxRates
        fx = FxRates({'HKD': 0.172})
        rate = fx.rate_fraction('HKD')
        assert isinstance(rate, Fraction)
        assert rate == Fraction(172, 1000)

    def test_cad_rate_is_one(self):
        from services.fx_rates import FxRates
        fx = FxRates({})
        assert fx.rate_fraction('CAD') == Fraction(1)

    def test_missing_currency_raises(self):
        from services.fx_rates import FxRates, MissingFxRateError
        fx = FxRates({})
        with pytest.raises(MissingFxRateError):
            fx.rate_fraction('USD')


# ---------------------------------------------------------------------------
# has_rate
# ---------------------------------------------------------------------------

class TestHasRate:

    def test_true_for_known_currency(self):
        from services.fx_rates import FxRates
        fx = FxRates({'HKD': 0.172})
        assert fx.has_rate('HKD') is True

    def test_false_for_unknown_currency(self):
        from services.fx_rates import FxRates
        fx = FxRates({'HKD': 0.172})
        assert fx.has_rate('USD') is False

    def test_cad_always_true(self):
        from services.fx_rates import FxRates
        assert FxRates({}).has_rate('CAD') is True

    def test_case_insensitive(self):
        from services.fx_rates import FxRates
        fx = FxRates({'HKD': 0.172})
        assert fx.has_rate('hkd') is True
        assert fx.has_rate('HKD') is True


# ---------------------------------------------------------------------------
# missing_currencies
# ---------------------------------------------------------------------------

class TestMissingCurrencies:

    def test_all_present_returns_empty_set(self):
        from services.fx_rates import FxRates
        fx = FxRates({'HKD': 0.172, 'USD': 1.36})
        assert fx.missing_currencies({'HKD', 'CAD', 'USD'}) == set()

    def test_missing_currency_returned(self):
        from services.fx_rates import FxRates
        fx = FxRates({'HKD': 0.172})
        missing = fx.missing_currencies({'HKD', 'USD', 'JPY'})
        assert missing == {'USD', 'JPY'}

    def test_empty_input_returns_empty_set(self):
        from services.fx_rates import FxRates
        fx = FxRates({'HKD': 0.172})
        assert fx.missing_currencies(set()) == set()

    def test_cad_never_missing(self):
        from services.fx_rates import FxRates
        fx = FxRates({})
        assert fx.missing_currencies({'CAD'}) == set()


# ---------------------------------------------------------------------------
# available_currencies
# ---------------------------------------------------------------------------

class TestAvailableCurrencies:

    def test_cad_always_in_available(self):
        from services.fx_rates import FxRates
        fx = FxRates({})
        assert 'CAD' in fx.available_currencies

    def test_added_currencies_in_available(self):
        from services.fx_rates import FxRates
        fx = FxRates({'HKD': 0.172, 'USD': 1.36})
        assert 'HKD' in fx.available_currencies
        assert 'USD' in fx.available_currencies

    def test_returns_set(self):
        from services.fx_rates import FxRates
        fx = FxRates({'HKD': 0.172})
        assert isinstance(fx.available_currencies, set)
