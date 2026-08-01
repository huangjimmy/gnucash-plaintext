"""
Income statement service.

Computes income and expense account balances within a date range,
with optional FX conversion to CAD for CRA T2 filing.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from fractions import Fraction
from typing import Dict, List, Optional

from gnucash import Account
from gnucash.gnucash_core_c import ACCT_TYPE_EXPENSE, ACCT_TYPE_INCOME

from infrastructure.gnucash.utils import numeric_to_fraction
from services.fx_rates import FxRates


@dataclass
class AccountLine:
    """One line in the income statement — a single account."""
    path: str           # Full account path, e.g. "Income:Salary:Base"
    name: str           # Account name only, e.g. "Base"
    depth: int          # Nesting depth (0 = top-level like "Income")
    currency: str       # Native currency code, e.g. "CAD"
    balance: Fraction   # Balance in native currency (positive = amount earned/spent)
    cad_balance: Optional[Fraction]  # Converted to CAD (None if no FX rates supplied)


@dataclass
class AccountSubtotal:
    """Subtotal for an account group (accounts sharing a common parent path)."""
    path: str               # Parent path, e.g. "Income:Salary"
    name: str               # Parent name, e.g. "Salary"
    depth: int              # Nesting depth of this subtotal
    # Per-currency totals: {currency: native_total}
    currency_totals: Dict[str, Fraction] = field(default_factory=dict)
    # CAD total (None if no FX rates)
    cad_total: Optional[Fraction] = None


@dataclass
class IncomeStatementSection:
    """Either the Income or Expenses section of the report."""
    title: str                          # "INCOME" or "EXPENSES"
    lines: List[AccountLine] = field(default_factory=list)
    # Top-level currency totals: {currency: total}
    currency_totals: Dict[str, Fraction] = field(default_factory=dict)
    cad_total: Optional[Fraction] = None  # None if no FX rates


@dataclass
class IncomeStatementResult:
    """Full income statement result."""
    start_date: date
    end_date: date
    income: IncomeStatementSection
    expenses: IncomeStatementSection
    # Net income per currency (income - expenses, positive = profit)
    net_currency_totals: Dict[str, Fraction] = field(default_factory=dict)
    net_cad_total: Optional[Fraction] = None  # None if no FX rates
    fx_rates_provided: bool = False
    # How finely each currency on the statement divides, as GnuCash records it
    # on the commodity: {"CAD": 100, "JPY": 1}. Amounts are written at their
    # own currency's decimals rather than at an assumed two.
    currency_units: Dict[str, int] = field(default_factory=dict)


class IncomeStatementService:
    """
    Computes income and expense account balances within a date range.

    Date range is INCLUSIVE on both ends: start_date <= tx_date <= end_date.
    This is different from BookCloser.get_balance_as_of_date which is cumulative
    (from the beginning of time up to a date).
    """

    def get_balance_in_range(
        self,
        account: Account,
        start_date: date,
        end_date: date,
    ) -> Fraction:
        """
        Get account balance for transactions within [start_date, end_date].

        Returns balance as a Python Fraction.
        For Income accounts: negative means credit (revenue) in GnuCash convention.
        We negate Income balances before displaying so they appear as positive revenue.
        """
        # GnuCash computes this itself, in the account's own currency and with
        # closing entries left out — which is exactly what the statement wants,
        # since a closing entry is an equity transfer rather than activity in
        # the period. Asking the engine also avoids adding split *values*,
        # which are stated in each transaction's currency: a CAD income account
        # credited by a USD invoice holds a split whose amount is the CAD
        # revenue and whose value is the USD invoice total.
        # The engine's period runs from the start of `start_date` to the start
        # of the end argument, so a transaction dated `end_date` falls outside
        # it. This report's range includes both ends, hence the day added.
        return numeric_to_fraction(
            account.GetNoclosingBalanceChangeForPeriod(
                start_date, end_date + timedelta(days=1), False))

    def _account_full_path(self, account: Account) -> str:
        """Build full colon-separated path for an account, excluding root."""
        parts = []
        acc = account
        while acc is not None and not acc.is_root():
            parts.append(acc.GetName())
            acc = acc.get_parent()
        parts.reverse()
        return ":".join(parts)

    def _account_depth(self, account: Account) -> int:
        """Return nesting depth (0 = direct child of root)."""
        depth = 0
        acc = account.get_parent()
        while acc is not None and not acc.is_root():
            depth += 1
            acc = acc.get_parent()
        return depth

    def compute(
        self,
        root: Account,
        start_date: date,
        end_date: date,
        fx_rates: Optional[FxRates] = None,
    ) -> IncomeStatementResult:
        """
        Compute the income statement for the given date range.

        Args:
            root: Root account from GnuCash book
            start_date: First day of the period (inclusive)
            end_date: Last day of the period (inclusive)
            fx_rates: Optional FX rates for CAD conversion. If None, no CAD
                      totals are computed and fx_rates_provided=False.

        Returns:
            IncomeStatementResult with all lines and totals
        """
        income_lines: List[AccountLine] = []
        expense_lines: List[AccountLine] = []
        currency_units: Dict[str, int] = {}

        for account in root.get_descendants():
            acct_type = account.GetType()
            if acct_type not in (ACCT_TYPE_INCOME, ACCT_TYPE_EXPENSE):
                continue

            commodity = account.GetCommodity()
            if commodity is None:
                continue

            currency = commodity.get_mnemonic()
            currency_units[currency] = commodity.get_fraction()
            raw_balance = self.get_balance_in_range(account, start_date, end_date)

            if raw_balance == Fraction(0):
                continue

            # Income accounts: GnuCash stores revenue as negative (credit).
            # Negate so Income lines show positive = revenue earned.
            display_balance = -raw_balance if acct_type == ACCT_TYPE_INCOME else raw_balance

            cad_balance: Optional[Fraction] = None
            if fx_rates is not None:
                cad_balance = fx_rates.to_cad(display_balance, currency)

            line = AccountLine(
                path=self._account_full_path(account),
                name=account.GetName(),
                depth=self._account_depth(account),
                currency=currency,
                balance=display_balance,
                cad_balance=cad_balance,
            )

            if acct_type == ACCT_TYPE_INCOME:
                income_lines.append(line)
            else:
                expense_lines.append(line)

        # Sort each section by account path for consistent ordering
        income_lines.sort(key=lambda line: line.path)
        expense_lines.sort(key=lambda line: line.path)

        income_section = self._build_section("INCOME", income_lines, fx_rates)
        expense_section = self._build_section("EXPENSES", expense_lines, fx_rates)

        # Net income per currency
        all_currencies = set(income_section.currency_totals) | set(expense_section.currency_totals)
        net_currency_totals: Dict[str, Fraction] = {}
        for currency in all_currencies:
            inc = income_section.currency_totals.get(currency, Fraction(0))
            exp = expense_section.currency_totals.get(currency, Fraction(0))
            net_currency_totals[currency] = inc - exp

        net_cad_total: Optional[Fraction] = None
        if fx_rates is not None:
            inc_cad = income_section.cad_total or Fraction(0)
            exp_cad = expense_section.cad_total or Fraction(0)
            net_cad_total = inc_cad - exp_cad

        return IncomeStatementResult(
            start_date=start_date,
            end_date=end_date,
            income=income_section,
            expenses=expense_section,
            net_currency_totals=net_currency_totals,
            net_cad_total=net_cad_total,
            fx_rates_provided=fx_rates is not None,
            currency_units=currency_units,
        )

    def _build_section(
        self,
        title: str,
        lines: List[AccountLine],
        fx_rates: Optional[FxRates],
    ) -> IncomeStatementSection:
        """Build a section (Income or Expenses) with per-currency totals."""
        currency_totals: Dict[str, Fraction] = {}
        cad_total = Fraction(0) if fx_rates is not None else None

        for line in lines:
            currency_totals[line.currency] = (
                currency_totals.get(line.currency, Fraction(0)) + line.balance
            )
            if cad_total is not None and line.cad_balance is not None:
                cad_total += line.cad_balance

        return IncomeStatementSection(
            title=title,
            lines=lines,
            currency_totals=currency_totals,
            cad_total=cad_total,
        )

    def get_all_currencies(self, root: Account, start_date: date, end_date: date) -> set:
        """
        Return set of all currency codes used by Income/Expense accounts
        with non-zero balances in the date range.

        Useful for pre-validating that FX rates file covers all currencies.
        """
        currencies = set()
        for account in root.get_descendants():
            acct_type = account.GetType()
            if acct_type not in (ACCT_TYPE_INCOME, ACCT_TYPE_EXPENSE):
                continue
            commodity = account.GetCommodity()
            if commodity is None:
                continue
            balance = self.get_balance_in_range(account, start_date, end_date)
            if balance != Fraction(0):
                currencies.add(commodity.get_mnemonic())
        return currencies
