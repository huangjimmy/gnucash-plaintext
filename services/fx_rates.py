"""
FX rates service for currency conversion to CAD.

Loads annual average exchange rates from a YAML file and converts amounts.
CRA accepts Bank of Canada annual average rates for foreign currency conversion.
"""

from fractions import Fraction
from pathlib import Path
from typing import Dict, Set

import yaml


class MissingFxRateError(Exception):
    """Raised when a required currency has no FX rate."""
    pass


class FxRates:
    """
    Holds exchange rates for converting foreign currencies to CAD.

    All rates are expressed as: 1 unit of foreign currency = N CAD.
    CAD is always 1.0.
    """

    def __init__(self, rates: Dict[str, float]):
        """
        Initialize with a dict of currency → CAD rate.

        Args:
            rates: e.g. {"HKD": 0.172, "CNY": 0.185, "JPY": 0.009}
                   CAD need not be included (always 1.0).
        """
        self._rates: Dict[str, Fraction] = {"CAD": Fraction(1)}
        for currency, rate in rates.items():
            self._rates[currency.upper()] = Fraction(rate).limit_denominator(1_000_000)

    @classmethod
    def load(cls, path: str) -> "FxRates":
        """
        Load FX rates from a YAML file.

        Expected format:
            HKD: 0.172
            CNY: 0.185
            JPY: 0.009
            USD: 1.36
            CAD: 1.0   # optional

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

        with open(p) as f:
            data = yaml.safe_load(f)

        if not isinstance(data, dict):
            raise ValueError(f"FX rates file must be a YAML mapping, got: {type(data)}")

        for key, value in data.items():
            if not isinstance(key, str):
                raise ValueError(f"Currency code must be a string, got: {key!r}")
            if not isinstance(value, (int, float)):
                raise ValueError(f"Rate for {key!r} must be a number, got: {value!r}")
            if value <= 0:
                raise ValueError(f"Rate for {key!r} must be positive, got: {value}")

        return cls(data)

    @classmethod
    def cad_only(cls) -> "FxRates":
        """Create an FxRates instance with only CAD (no conversion needed)."""
        return cls({})

    def to_cad(self, amount: Fraction, currency: str) -> Fraction:
        """
        Convert an amount in the given currency to CAD.

        Args:
            amount: Amount in foreign currency
            currency: ISO currency code (e.g., "HKD")

        Returns:
            Amount in CAD

        Raises:
            MissingFxRateError: If no rate is available for the currency
        """
        code = currency.upper()
        if code not in self._rates:
            raise MissingFxRateError(
                f"No FX rate for {code}. "
                f"Add '{code}: <rate>' to your --fx-rates file."
            )
        return amount * self._rates[code]

    def get_rate(self, currency: str) -> float:
        """
        Return the CAD rate for a currency as a float.

        Raises:
            MissingFxRateError: If no rate is available for the currency
        """
        code = currency.upper()
        if code not in self._rates:
            raise MissingFxRateError(f"No FX rate for {code}.")
        return float(self._rates[code])

    def has_rate(self, currency: str) -> bool:
        """Check if a rate exists for the given currency."""
        return currency.upper() in self._rates

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
