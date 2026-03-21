"""
Use case for computing account balances as of a given date.

Output format (balance directive):

    YYYY-MM-DD balance
        Account:Path  Amount Currency

No account_prefix:
    All accounts in the book (parent + leaf), each with its recursive cumulative
    balance.  Mixed-currency subtrees fall back to GnuCash pricedb for conversion;
    MissingFxRateError is raised when no rate source is available.

With account_prefix (no --with-children):
    Only the matched account with its recursive cumulative balance.

With account_prefix + include_children=True (--with-children):
    The matched account and all sub-accounts, each with their recursive balance.

FX rate lookup order: explicit yaml -> GnuCash pricedb -> MissingFxRateError.
With --fx-rates: pricedb is updated for changed rates before balances are computed.
"""

from dataclasses import dataclass, field
from datetime import date
from fractions import Fraction
from typing import List, Optional

from repositories.gnucash_repository import GnuCashRepository
from services.fx_rates import FxRates, MissingFxRateError


@dataclass
class AccountBalance:
    """A single account balance entry."""
    account_path: str
    amount: Fraction
    currency: str
    # Set when FX conversion was applied on a non-CAD leaf account
    original_amount: Optional[Fraction] = None
    original_currency: Optional[str] = None
    share_price: Optional[Fraction] = None  # rate: 1 original_currency = share_price CAD


@dataclass
class AccountBalanceResult:
    """Result of the account-balance use case."""
    as_of: date
    balances: List[AccountBalance] = field(default_factory=list)
    # Sum of the top-level shown account(s) in CAD when fx_rates provided.
    # No prefix: sum of all root-level accounts. With prefix: balance of matched account.
    consolidated_cad: Optional[Fraction] = None


# ---------------------------------------------------------------------------
# Account tree helpers
# ---------------------------------------------------------------------------

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


def _collect_accounts(account, result: list) -> None:
    """Append account and all descendants to result (DFS, parent before children)."""
    result.append(account)
    for child in account.get_children_sorted():
        _collect_accounts(child, result)


def _find_account(root, path: str):
    """Find account by exact path from root. Returns None if not found."""
    for child in root.get_children_sorted():
        child_path = _get_account_path(child)
        if child_path == path:
            return child
        if path.startswith(child_path + ":"):
            found = _find_account(child, path)
            if found is not None:
                return found
    return None


def _get_accounts_to_display(root, prefix: Optional[str], include_children: bool) -> list:
    """
    Return ordered list of accounts to display.

    No prefix:
        All accounts in the book (DFS, parent before children).
        include_children is ignored.

    With prefix + include_children=False (default):
        Only the matched account.

    With prefix + include_children=True (--with-children):
        The matched account and all descendants.
    """
    if prefix is None:
        result = []
        for child in root.get_children_sorted():
            _collect_accounts(child, result)
        return result

    target = _find_account(root, prefix)
    if target is None:
        return []

    if include_children:
        result = []
        _collect_accounts(target, result)
        return result
    else:
        return [target]


def _get_all_currencies(account) -> set:
    """Return the set of all commodity mnemonics in this account's subtree."""
    currencies = {account.GetCommodity().get_mnemonic()}
    for child in account.get_children_sorted():
        currencies |= _get_all_currencies(child)
    return currencies


def _get_direct_balance(account, as_of: date) -> Fraction:
    """Sum splits directly in this account (not children) up to and including as_of."""
    balance = Fraction(0)
    for split in account.GetSplitList():
        tx = split.GetParent()
        tx_date_raw = tx.GetDate()
        tx_date_obj = date(tx_date_raw.year, tx_date_raw.month, tx_date_raw.day)
        if tx_date_obj <= as_of:
            value = split.GetValue()
            balance += Fraction(value.num(), value.denom())
    return balance


def _get_recursive_balance_cad(account, as_of: date, get_rate) -> Fraction:
    """
    Recursively sum all balances in the account's subtree, converting each to CAD.

    get_rate(currency: str) -> Fraction raises MissingFxRateError if unavailable.
    """
    currency = account.GetCommodity().get_mnemonic()
    total = _get_direct_balance(account, as_of) * get_rate(currency)
    for child in account.get_children_sorted():
        total += _get_recursive_balance_cad(child, as_of, get_rate)
    return total


def _get_recursive_balance_native(account, as_of: date) -> Fraction:
    """
    Recursively sum all balances in the account's subtree without currency conversion.

    Only correct when the entire subtree uses the same currency.
    """
    total = _get_direct_balance(account, as_of)
    for child in account.get_children_sorted():
        total += _get_recursive_balance_native(child, as_of)
    return total


# ---------------------------------------------------------------------------
# Use case
# ---------------------------------------------------------------------------

class AccountBalanceUseCase:
    """
    Compute account balances as of a given date.

    No account_prefix:
        Shows all accounts in the book with recursive cumulative balances.
        Raises MissingFxRateError when mixed-currency subtrees have no rate source.

    With account_prefix (include_children=False, default):
        Shows only the matched account with its recursive cumulative balance.

    With account_prefix + include_children=True (--with-children):
        Shows the matched account and all sub-accounts, each with recursive balance.

    With fx_rates:
        All balances consolidated to CAD. Call update_pricedb() before execute()
        to write any changed rates to the GnuCash pricedb.
    """

    def __init__(self, repository: GnuCashRepository):
        self.repository = repository

    def _build_pricedb_rate_fn(self):
        """
        Build a rate function that reads FX rates from the GnuCash pricedb.

        Raises MissingFxRateError when no pricedb entry exists for a currency.
        """
        import ctypes

        from gnucash.gnucash_core_c import gnc_pricedb_get_db, gnc_pricedb_lookup_latest

        from infrastructure.gnucash.engine import GncNumericC, load_gnc_engine

        book = self.repository.book
        commod_table = book.get_table()
        cad_commodity = commod_table.lookup("CURRENCY", "CAD")
        pricedb = gnc_pricedb_get_db(book.instance)

        lib = load_gnc_engine()
        lib.gnc_price_get_value.restype = GncNumericC
        lib.gnc_price_get_value.argtypes = [ctypes.c_void_p]

        def get_rate(currency: str) -> Fraction:
            if currency == "CAD":
                return Fraction(1)
            commodity = commod_table.lookup("CURRENCY", currency)
            if commodity is None:
                raise MissingFxRateError(
                    f"Currency {currency} not found in GnuCash commodity table"
                )
            existing = gnc_pricedb_lookup_latest(
                pricedb, commodity.instance, cad_commodity.instance
            )
            if existing is None:
                raise MissingFxRateError(
                    f"No FX rate for {currency} -> CAD in GnuCash pricedb. "
                    f"Provide rates via --fx-rates."
                )
            val = lib.gnc_price_get_value(int(existing))
            if val.denom == 0:
                raise MissingFxRateError(f"Invalid pricedb entry for {currency} -> CAD")
            return Fraction(val.num, val.denom).limit_denominator(1_000_000)

        return get_rate

    def execute(
        self,
        as_of: date,
        account_prefix: Optional[str] = None,
        fx_rates: Optional[FxRates] = None,
        include_children: bool = False,
    ) -> AccountBalanceResult:
        """
        Compute balances as of the given date.

        Args:
            as_of:           Balance date (inclusive).
            account_prefix:  Exact account path to query (e.g. "Assets:Bank").
                             None = all accounts in the book.
            fx_rates:        When provided, convert all amounts to CAD.
            include_children: Only relevant when account_prefix is given.
                             False (default) = show only the matched account.
                             True (--with-children) = show matched account + all sub-accounts.

        Returns:
            AccountBalanceResult with ordered list of AccountBalance entries.
        """
        root = self.repository.get_root_account()
        result = AccountBalanceResult(as_of=as_of)

        accounts = _get_accounts_to_display(root, account_prefix, include_children)

        # Raise early when the prefix names an account that doesn't exist
        if account_prefix is not None and not accounts:
            raise ValueError(f"Account not found: {account_prefix!r}")

        # Rate function from explicit yaml fx_rates
        explicit_rate_fn = None
        if fx_rates is not None:
            def explicit_rate_fn(currency: str) -> Fraction:
                return Fraction(fx_rates.get_rate(currency)).limit_denominator(1_000_000)

        # Pricedb rate function, built lazily on first multi-currency account encountered
        pricedb_rate_fn = None

        # Accumulators for consolidated_cad (avoids recomputing after the loop)
        first_account_cad: Optional[Fraction] = None   # with prefix: matched account balance
        top_level_cad = Fraction(0)                     # no prefix: sum of root children

        for account in accounts:
            currency = account.GetCommodity().get_mnemonic()
            all_currencies = _get_all_currencies(account)
            needs_fx = len(all_currencies) > 1

            if fx_rates is not None:
                # Explicit FX: always output in CAD
                cad_balance = _get_recursive_balance_cad(account, as_of, explicit_rate_fn)

                # Track for consolidated_cad without a second traversal
                if account_prefix is not None and first_account_cad is None:
                    first_account_cad = cad_balance
                if account_prefix is None and account.get_parent().is_root():
                    top_level_cad += cad_balance

                if _is_leaf(account) and currency != "CAD":
                    # Non-CAD leaf: include original amount and exchange rate metadata
                    direct = _get_direct_balance(account, as_of)
                    rate = explicit_rate_fn(currency)
                    result.balances.append(AccountBalance(
                        account_path=_get_account_path(account),
                        amount=cad_balance,
                        currency="CAD",
                        original_amount=direct,
                        original_currency=currency,
                        share_price=rate,
                    ))
                else:
                    result.balances.append(AccountBalance(
                        account_path=_get_account_path(account),
                        amount=cad_balance,
                        currency="CAD",
                    ))

            elif needs_fx:
                # Multi-currency subtree without explicit fx_rates: try pricedb
                if pricedb_rate_fn is None:
                    pricedb_rate_fn = self._build_pricedb_rate_fn()
                cad_balance = _get_recursive_balance_cad(account, as_of, pricedb_rate_fn)
                result.balances.append(AccountBalance(
                    account_path=_get_account_path(account),
                    amount=cad_balance,
                    currency="CAD",
                ))

            else:
                # Single currency, no FX needed
                balance = _get_recursive_balance_native(account, as_of)
                result.balances.append(AccountBalance(
                    account_path=_get_account_path(account),
                    amount=balance,
                    currency=currency,
                ))

        # consolidated_cad: balance of the top-level shown account(s) in CAD.
        # With prefix: balance of the matched account.
        # No prefix: sum of all root-level account balances.
        if fx_rates is not None:
            if account_prefix is not None:
                result.consolidated_cad = first_account_cad or Fraction(0)
            else:
                result.consolidated_cad = top_level_cad

        return result

    def update_pricedb(self, fx_rates: FxRates, price_date: date) -> None:
        """
        Sync fx_rates into GnuCash pricedb.

        For each currency in fx_rates (other than CAD), compare against the
        pricedb latest rate. If different or missing, write a new price entry
        dated price_date.

        Args:
            fx_rates:   FxRates instance with currency->CAD rates
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
            existing = gnc_pricedb_lookup_latest(
                pricedb, commodity.instance, cad_commodity.instance
            )
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
