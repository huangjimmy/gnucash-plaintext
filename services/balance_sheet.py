"""Balance sheet service (F-002).

Assets / Liabilities / Equity as of a date, with a computed **Current Year
Earnings** line so the sheet balances whether or not the books are closed.

Why it balances either way: every split nets to zero, so across all accounts
  Assets + Liabilities + Equity + Income + Expense = 0   (GnuCash sign convention)
hence
  Assets = (−Liabilities) + (−Equity) + (−(Income + Expense)).
Presenting Liabilities and Equity as positive and adding the net income line
(−(Income + Expense)) makes Assets = Liabilities + Equity + Current Year
Earnings — an identity. Closing entries just move that net income out of the
earnings line and into Equity (Retained Earnings); the total is unchanged. So
the balance sheet uses raw balances (closing entries included) and always
balances.
"""
from dataclasses import dataclass, field
from datetime import date
from fractions import Fraction
from typing import Dict, List, Optional

from gnucash import Account
from gnucash.gnucash_core_c import (
    ACCT_TYPE_ASSET,
    ACCT_TYPE_EQUITY,
    ACCT_TYPE_EXPENSE,
    ACCT_TYPE_INCOME,
    ACCT_TYPE_LIABILITY,
)

from services.fx_rates import FxRates

CURRENT_EARNINGS_LABEL = "Current Year Earnings"


@dataclass
class BSLine:
    path: str
    name: str
    depth: int                        # nesting depth (0 = direct child of root)
    currency: str
    balance: Fraction                 # presented (positive-normal) amount
    cad_balance: Optional[Fraction]


@dataclass
class BSSection:
    title: str
    lines: List[BSLine] = field(default_factory=list)
    currency_totals: Dict[str, Fraction] = field(default_factory=dict)
    cad_total: Optional[Fraction] = None


@dataclass
class BalanceSheetResult:
    as_of_date: date
    assets: BSSection
    liabilities: BSSection
    equity: BSSection                 # includes the synthetic Current Year Earnings line
    fx_rates_provided: bool
    balances: bool                    # Assets == Liabilities + Equity (in CAD when FX given)


class BalanceSheet:
    def balance_as_of(self, account: Account, as_of_date: date) -> Fraction:
        """Cumulative balance of `account` from inception through `as_of_date`
        (inclusive). Includes closing entries — see the module docstring."""
        total = Fraction(0)
        for split in account.GetSplitList():
            tx = split.GetParent()
            d = tx.GetDate()
            if date(d.year, d.month, d.day) <= as_of_date:
                value = split.GetValue()
                total += Fraction(value.num(), value.denom())
        return total

    def _full_path(self, account: Account) -> str:
        parts, node = [], account
        while node is not None and node.get_parent() is not None:
            parts.append(node.GetName())
            node = node.get_parent()
        return ':'.join(reversed(parts))

    def compute(self, root: Account, as_of_date: date,
                fx_rates: Optional[FxRates] = None) -> BalanceSheetResult:
        assets = BSSection("ASSETS")
        liabilities = BSSection("LIABILITIES")
        equity = BSSection("EQUITY")
        earnings_by_ccy: Dict[str, Fraction] = {}

        for account in root.get_descendants():
            atype = account.GetType()
            commodity = account.GetCommodity()
            if commodity is None:
                continue
            ccy = commodity.get_mnemonic()
            raw = self.balance_as_of(account, as_of_date)

            if atype in (ACCT_TYPE_INCOME, ACCT_TYPE_EXPENSE):
                # Fold into Current Year Earnings: net income = -(income + expense).
                earnings_by_ccy[ccy] = earnings_by_ccy.get(ccy, Fraction(0)) - raw
                continue

            if atype == ACCT_TYPE_ASSET:
                section, presented = assets, raw            # asset: debit-normal
            elif atype == ACCT_TYPE_LIABILITY:
                section, presented = liabilities, -raw      # liability: credit-normal
            elif atype == ACCT_TYPE_EQUITY:
                section, presented = equity, -raw           # equity: credit-normal
            else:
                continue

            if presented == Fraction(0):
                continue
            cad = fx_rates.to_cad(presented, ccy) if fx_rates is not None else None
            path = self._full_path(account)
            depth = len(path.split(':')) - 1
            section.lines.append(BSLine(path, account.GetName(), depth, ccy, presented, cad))
            section.currency_totals[ccy] = section.currency_totals.get(ccy, Fraction(0)) + presented

        # Current Year Earnings → an equity line per currency.
        for ccy, amount in earnings_by_ccy.items():
            if amount == Fraction(0):
                continue
            cad = fx_rates.to_cad(amount, ccy) if fx_rates is not None else None
            equity.lines.append(BSLine(CURRENT_EARNINGS_LABEL, CURRENT_EARNINGS_LABEL,
                                       0, ccy, amount, cad))
            equity.currency_totals[ccy] = equity.currency_totals.get(ccy, Fraction(0)) + amount

        balances = self._finalise(assets, liabilities, equity, fx_rates)
        return BalanceSheetResult(
            as_of_date=as_of_date, assets=assets, liabilities=liabilities,
            equity=equity, fx_rates_provided=fx_rates is not None, balances=balances)

    def _finalise(self, assets, liabilities, equity, fx_rates) -> bool:
        if fx_rates is None:
            # Single-currency books: balance per currency exactly.
            ccys = set(assets.currency_totals) | set(liabilities.currency_totals) | set(equity.currency_totals)
            ok = True
            for c in ccys:
                a = assets.currency_totals.get(c, Fraction(0))
                le = liabilities.currency_totals.get(c, Fraction(0)) + equity.currency_totals.get(c, Fraction(0))
                ok = ok and (a == le)
            return ok
        for sec in (assets, liabilities, equity):
            sec.cad_total = sum((fx_rates.to_cad(v, c) for c, v in sec.currency_totals.items()),
                                Fraction(0))
        return assets.cad_total == (liabilities.cad_total + equity.cad_total)
