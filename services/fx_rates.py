"""
FX rates service for currency conversion to CAD.

Loads exchange rates from a YAML file and converts amounts. Rates come in two
forms in the same file, so one file serves every command:

    USD: 1.36                 # flat — one rate, no date
    HKD: 0.172

    USD/CAD:                  # dated — a rate per day
      2026-01-05: 1.35
      2026-02-20: 1.37

Both mean "1 unit of the foreign currency = N CAD". A dated lookup takes the
most recent quote on or before the date asked for; a date earlier than every
quote is an error rather than an extrapolation. Rates are held as exact
fractions, never rounded to a float.

CRA accepts Bank of Canada rates for foreign currency conversion — annual
average (the flat form) or the daily rate on the transaction date (the dated
form).
"""

from datetime import date as _date
from datetime import datetime
from fractions import Fraction
from pathlib import Path
from typing import Dict, Optional, Set, Union

import yaml


class MissingFxRateError(Exception):
    """Raised when a required currency has no FX rate."""
    pass


def _to_fraction(value) -> Fraction:
    """An exact Fraction from a YAML scalar. Goes through str() so 1.35 is
    27/20 — the number the user wrote — and not the binary-float neighbour
    that `Fraction(1.35)` would produce."""
    return Fraction(str(value))


def _to_date(value) -> _date:
    """A date from a YAML key, which PyYAML gives as a date for `2026-01-05`
    and as a string when quoted."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, _date):
        return value
    return datetime.strptime(str(value), '%Y-%m-%d').date()


def _normalise_currency(key: str) -> str:
    """`USD` and `USD/CAD` both name the USD → CAD rate. The pair spelling is
    accepted because a dated block reads better with both sides named; only
    conversion to the book's own currency is supported, so the second half must
    be CAD."""
    code = str(key).upper().strip()
    if '/' not in code:
        return code
    left, right = code.split('/', 1)
    if right != 'CAD':
        raise ValueError(
            f"FX rate key {key!r} converts to {right}; only rates to CAD are "
            f"supported (write it as '{left}: <rate>' or '{left}/CAD:')")
    return left


class FxRates:
    """
    Holds exchange rates for converting foreign currencies to CAD.

    All rates are expressed as: 1 unit of foreign currency = N CAD.
    CAD is always 1.0.
    """

    def __init__(self, rates: Dict[str, Union[float, Dict]]):
        """
        Initialize with a dict of currency → rate, or currency → {date: rate}.

        Args:
            rates: e.g. {"HKD": 0.172, "USD": {"2026-01-05": 1.35}}
                   CAD need not be included (always 1.0).
        """
        self._rates: Dict[str, Fraction] = {"CAD": Fraction(1)}
        self._dated: Dict[str, Dict[_date, Fraction]] = {}
        for currency, rate in rates.items():
            code = _normalise_currency(currency)
            if isinstance(rate, dict):
                quotes = {_to_date(d): _to_fraction(r) for d, r in rate.items()}
                if not quotes:
                    raise ValueError(f"Dated rates for {code!r} are empty")
                self._dated[code] = quotes
                # The latest quote also answers an undated lookup, so a dated
                # file still works with a command that asks for no date.
                self._rates[code] = quotes[max(quotes)]
            else:
                self._rates[code] = _to_fraction(rate)

    @classmethod
    def load(cls, path: str) -> "FxRates":
        """
        Load FX rates from a YAML file.

        Expected format (the two forms may be mixed in one file):
            HKD: 0.172
            USD: 1.36
            CAD: 1.0   # optional

            USD/CAD:
              2026-01-05: 1.35
              2026-02-20: 1.37

        Args:
            path: Path to YAML file

        Returns:
            FxRates instance

        Raises:
            FileNotFoundError: If file does not exist
            ValueError: If file format is invalid
        """
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"FX rates file not found: {path}")

        # UTF-8 and not the locale's: YAML is a UTF-8 format by its own spec.
        with open(p, encoding='utf-8') as f:
            try:
                data = yaml.safe_load(f)
            except yaml.YAMLError as e:
                # As a ValueError, which is what this method documents itself
                # as raising for a file it cannot read, and what every caller
                # already handles. A `YAMLError` escaping instead reached the
                # CLI's `except (FileNotFoundError, ValueError)` unhandled, so
                # a rates file with a typo in it came back as a traceback with
                # no message — on `report` and on `import --fx-rates` alike.
                raise ValueError(
                    f"FX rates file {path} is not valid YAML: {e}") from e

        if not isinstance(data, dict):
            raise ValueError(f"FX rates file must be a YAML mapping, got: {type(data)}")

        for key, value in data.items():
            if not isinstance(key, str):
                raise ValueError(f"Currency code must be a string, got: {key!r}")
            if isinstance(value, dict):
                if not value:
                    raise ValueError(f"Dated rates for {key!r} are empty")
                for quote_date, quote in value.items():
                    if not isinstance(quote, (int, float)):
                        raise ValueError(
                            f"Rate for {key!r} on {quote_date} must be a number, "
                            f"got: {quote!r}")
                    if quote <= 0:
                        raise ValueError(
                            f"Rate for {key!r} on {quote_date} must be positive, "
                            f"got: {quote}")
                    _to_date(quote_date)      # raises on an unparseable date
                continue
            if not isinstance(value, (int, float)):
                raise ValueError(f"Rate for {key!r} must be a number, got: {value!r}")
            if value <= 0:
                raise ValueError(f"Rate for {key!r} must be positive, got: {value}")

        return cls(data)

    @classmethod
    def cad_only(cls) -> "FxRates":
        """Create an FxRates instance with only CAD (no conversion needed)."""
        return cls({})

    def to_cad(self, amount: Fraction, currency: str,
               as_of: Optional[_date] = None) -> Fraction:
        """
        Convert an amount in the given currency to CAD.

        Args:
            amount: Amount in foreign currency
            currency: ISO currency code (e.g., "HKD")
            as_of: Date to price the conversion at. Only meaningful for a
                currency quoted with dated rates; omitted means "the latest
                rate in the file".

        Returns:
            Amount in CAD

        Raises:
            MissingFxRateError: If no rate is available for the currency
        """
        return amount * self.rate_fraction(currency, as_of)

    def rate_fraction(self, currency: str,
                      as_of: Optional[_date] = None) -> Fraction:
        """The exact CAD-per-unit rate for a currency, as a Fraction.

        Raises:
            MissingFxRateError: If no rate covers the currency and date.
        """
        code = currency.upper()
        if code == 'CAD':
            return Fraction(1)
        quotes = self._dated.get(code)
        if quotes is not None and as_of is not None:
            usable = [d for d in quotes if d <= as_of]
            if not usable:
                earliest = min(quotes)
                raise MissingFxRateError(
                    f"No {code} rate on or before {as_of.isoformat()}; the "
                    f"earliest quote in the rates file is "
                    f"{earliest.isoformat()}. Add a {code} rate covering "
                    f"{as_of.isoformat()} — rates are not extrapolated "
                    f"backwards.")
            return quotes[max(usable)]
        if code not in self._rates:
            raise MissingFxRateError(
                f"No FX rate for {code}. "
                f"Add '{code}: <rate>' to your --fx-rates file."
            )
        return self._rates[code]

    def has_rate(self, currency: str) -> bool:
        """Check if a rate exists for the given currency."""
        return currency.upper() in self._rates

    def is_dated(self, currency: str) -> bool:
        """True if this currency is quoted with dated rates."""
        return currency.upper() in self._dated

    def missing_currencies(self, currencies: Set[str]) -> Set[str]:
        """
        Return currencies from the given set that have no rate.

        Args:
            currencies: Set of currency codes to check

        Returns:
            Set of currencies with missing rates (empty if all covered)
        """
        return {c for c in currencies if not self.has_rate(c)}

    @property
    def available_currencies(self) -> Set[str]:
        """Return set of currencies with known rates."""
        return set(self._rates.keys())
