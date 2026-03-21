"""
Use case for computing account balances as of a given date.

Outputs balances in a `balance` directive format:

    YYYY-MM-DD balance
        Account:Path  Amount Currency

Without --fx-rates: each leaf account is output in its own commodity currency.
With --fx-rates: consolidates all leaf accounts to CAD using the provided rates,
writing new price entries to the pricedb when rates differ from the current latest.
"""

from dataclasses import dataclass, field
from datetime import date
from fractions import Fraction
from typing import List, Optional

from repositories.gnucash_repository import GnuCashRepository
from services.fx_rates import FxRates


@dataclass
class AccountBalance:
    """A single account balance entry."""
    account_path: str
    amount: Fraction
    currency: str
    # Set when FX conversion was applied (currency != original_currency)
    original_amount: Optional[Fraction] = None
    original_currency: Optional[str] = None
    share_price: Optional[Fraction] = None  # rate: 1 original_currency = share_price CAD


@dataclass
class AccountBalanceResult:
    """Result of the account-balance use case."""
    as_of: date
    balances: List[AccountBalance] = field(default_factory=list)
    consolidated_cad: Optional[Fraction] = None  # set when fx_rates provided


def _get_account_path(account) -> str:
    """Build full colon-separated path for an account."""
    parts = []
    acc = account
    while acc is not None and not acc.is_root():
        parts.append(acc.GetName())
        acc = acc.get_parent()
    parts.reverse()
    return ":".join(parts)


def _is_leaf(account) -> bool:
    """Return True if account has no children."""
    return len(account.get_children_sorted()) == 0


def _walk_leaves(account, prefix: Optional[str] = None):
    """Yield all leaf accounts under account, optionally filtered by prefix."""
    if _is_leaf(account):
        path = _get_account_path(account)
        if prefix is None or path == prefix or path.startswith(prefix + ":"):
            yield account
    else:
        for child in account.get_children_sorted():
            yield from _walk_leaves(child, prefix)


class AccountBalanceUseCase:
    """
    Compute account balances as of a given date.

    Opens the GnuCash file, iterates leaf accounts (optionally filtered by
    account_prefix), and returns their balances.

    Without fx_rates: read-only, each account in its own currency.
    With fx_rates: opens in NORMAL mode, writes new pricedb entries for any
    currency whose rate differs from the current pricedb latest, then returns
    balances in CAD.
    """

    def __init__(self, repository: GnuCashRepository):
        self.repository = repository

    def execute(
        self,
        as_of: date,
        account_prefix: Optional[str] = None,
        fx_rates: Optional[FxRates] = None,
    ) -> AccountBalanceResult:
        """
        Compute balances as of the given date.

        Args:
            as_of: Balance date (balances include transactions on this date)
            account_prefix: Colon-separated account prefix to filter (e.g. "Assets:Bank")
                            None means all accounts
            fx_rates: If provided, consolidate to CAD and update pricedb as needed

        Returns:
            AccountBalanceResult with list of AccountBalance entries
        """
        root = self.repository.get_root_account()
        result = AccountBalanceResult(as_of=as_of)

        total_cad = Fraction(0)

        for account in _walk_leaves(root, account_prefix):
            commodity = account.GetCommodity()
            currency = commodity.get_mnemonic()

            # Sum all splits whose transaction date is <= as_of.
            # Uses split.GetValue() (proven to work in income_statement service).
            balance = Fraction(0)
            for split in account.GetSplitList():
                tx = split.GetParent()
                tx_date_raw = tx.GetDate()
                tx_date = date(tx_date_raw.year, tx_date_raw.month, tx_date_raw.day)
                if tx_date <= as_of:
                    value = split.GetValue()
                    balance += Fraction(value.num(), value.denom())

            if fx_rates is not None:
                # Consolidate to CAD; record original amount and rate for display
                rate_frac = Fraction(fx_rates.get_rate(currency)).limit_denominator(1_000_000)
                cad_amount = balance * rate_frac
                total_cad += cad_amount
                path = _get_account_path(account)
                if currency == "CAD":
                    result.balances.append(AccountBalance(
                        account_path=path,
                        amount=cad_amount,
                        currency="CAD",
                    ))
                else:
                    result.balances.append(AccountBalance(
                        account_path=path,
                        amount=cad_amount,
                        currency="CAD",
                        original_amount=balance,
                        original_currency=currency,
                        share_price=rate_frac,
                    ))
            else:
                result.balances.append(AccountBalance(
                    account_path=_get_account_path(account),
                    amount=balance,
                    currency=currency,
                ))

        if fx_rates is not None:
            result.consolidated_cad = total_cad

        return result

    def update_pricedb(self, fx_rates: FxRates, price_date: date) -> None:
        """
        Sync fx_rates into GnuCash pricedb.

        For each currency in fx_rates (other than CAD), compare against the
        pricedb latest rate. If different or missing, write a new price entry
        dated price_date.

        Args:
            fx_rates: FxRates instance with currency→CAD rates
            price_date: Date to use for new price entries (always today)
        """
        import calendar
        import ctypes
        import time

        from gnucash import GncNumeric
        from gnucash.gnucash_core_c import (
            PRICE_SOURCE_USER_PRICE,
            gnc_price_create,
            gnc_price_set_commodity,
            gnc_price_set_currency,
            gnc_price_set_source,
            gnc_price_set_time64,
            gnc_price_set_typestr,
            gnc_price_set_value,
            gnc_pricedb_add_price,
            gnc_pricedb_get_db,
            gnc_pricedb_lookup_latest,
        )

        from infrastructure.gnucash.engine import GncNumericC, load_gnc_engine

        book = self.repository.book
        book_instance = book.instance
        commod_table = book.get_table()
        cad_commodity = commod_table.lookup("CURRENCY", "CAD")
        pricedb = gnc_pricedb_get_db(book_instance)

        # gnc_price_get_value returns gnc_numeric by value; SWIG wraps it as an
        # opaque int on some platforms. Use ctypes with GncNumericC to read it.
        lib = load_gnc_engine()
        lib.gnc_price_get_value.restype = GncNumericC
        lib.gnc_price_get_value.argtypes = [ctypes.c_void_p]

        # time64 for price_date (noon UTC)
        price_struct = time.struct_time((
            price_date.year, price_date.month, price_date.day,
            12, 0, 0, 0, 0, 0,
        ))
        price_time64 = calendar.timegm(price_struct)

        for currency_code in sorted(fx_rates.available_currencies):
            if currency_code == "CAD":
                continue

            commodity = commod_table.lookup("CURRENCY", currency_code)
            if commodity is None:
                continue

            new_rate = fx_rates.get_rate(currency_code)

            # Compare against existing latest price to avoid duplicate entries
            existing = gnc_pricedb_lookup_latest(pricedb, commodity.instance, cad_commodity.instance)
            needs_update = True
            if existing is not None:
                existing_val = lib.gnc_price_get_value(int(existing))
                if existing_val.denom != 0:
                    existing_rate = existing_val.num / existing_val.denom
                    if abs(existing_rate - new_rate) < 1e-9:
                        needs_update = False

            if needs_update:
                frac = Fraction(new_rate).limit_denominator(1_000_000)
                gnc_val = GncNumeric(frac.numerator, frac.denominator)

                price = gnc_price_create(book_instance)
                # commodity/currency/value require raw SwigPyObject (.instance)
                gnc_price_set_commodity(price, commodity.instance)
                gnc_price_set_currency(price, cad_commodity.instance)
                gnc_price_set_time64(price, price_time64)
                gnc_price_set_source(price, PRICE_SOURCE_USER_PRICE)
                gnc_price_set_typestr(price, "last")
                gnc_price_set_value(price, gnc_val.instance)
                gnc_pricedb_add_price(pricedb, price)
