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

Commodity (Stock / Mutual Fund) accounts default to **cost basis** in the
transaction currency — the value GnuCash already stores on each split. Pass a
`prices` table (mnemonic → price, same shape as the FX rates) to instead value a
holding at **market**: shares held × your supplied price. The price is read in
the currency the holding was bought in (its transaction currency); for a
foreign-currency holding, `fx_rates` then converts the market value to CAD.
Market value isn't booked anywhere, so the revaluation (market − cost) is
collected into a single **Unrealized Gains** equity line, exactly as GnuCash's
own market-value balance sheet does, keeping Assets = Liabilities + Equity.
Securities without a supplied price stay at cost.
"""
from dataclasses import dataclass, field
from datetime import date
from fractions import Fraction
from typing import Dict, List, Optional

import gnucash.gnucash_core_c as _gc
from gnucash import Account
from gnucash.gnucash_core_c import (
    ACCT_TYPE_EQUITY,
    ACCT_TYPE_EXPENSE,
    ACCT_TYPE_INCOME,
)

from services.fx_rates import FxRates


def _type_set(*names: str) -> frozenset:
    """Resolve GnuCash ACCT_TYPE_* constants by name, skipping any the running
    binding doesn't define. The legacy CHECKING/SAVINGS/MONEYMRKT/CREDITLINE/
    CURRENCY codes exist in older books but not every gnucash build exports the
    symbol, so look them up defensively rather than importing them."""
    return frozenset(getattr(_gc, n) for n in names if hasattr(_gc, n))


# A balance sheet groups every account by its broad category. GnuCash has many
# concrete asset/liability types (Bank, Cash, Credit Card, A/Receivable, …), not
# just the bare ASSET/LIABILITY — missing any of them silently drops real
# balances and the sheet won't balance. Includes the deprecated codes still
# found in long-lived books.
_ASSET_TYPES = _type_set(
    'ACCT_TYPE_ASSET', 'ACCT_TYPE_BANK', 'ACCT_TYPE_CASH', 'ACCT_TYPE_STOCK',
    'ACCT_TYPE_MUTUAL', 'ACCT_TYPE_RECEIVABLE', 'ACCT_TYPE_TRADING',
    'ACCT_TYPE_CHECKING', 'ACCT_TYPE_SAVINGS', 'ACCT_TYPE_MONEYMRKT',
    'ACCT_TYPE_CURRENCY',
)
_LIABILITY_TYPES = _type_set(
    'ACCT_TYPE_LIABILITY', 'ACCT_TYPE_CREDIT', 'ACCT_TYPE_PAYABLE',
    'ACCT_TYPE_CREDITLINE',
)
# Trading accounts net to zero by their own currency-trading mechanics; they are
# never marked to market (that would double-count).
_TRADING_TYPES = _type_set('ACCT_TYPE_TRADING')

CURRENT_EARNINGS_LABEL = "Current Year Earnings"
UNREALIZED_GAINS_LABEL = "Unrealized Gains"


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
    prices_provided: bool = False     # securities marked to market from a supplied price table


class BalanceSheet:
    def value_by_currency(self, account: Account,
                          as_of_date: date) -> Dict[str, Fraction]:
        """Cost-basis value of `account` from inception through `as_of_date`
        (inclusive), bucketed by the currency each split's value is denominated
        in — i.e. the split's *transaction* currency, which is what
        `xaccSplitGetValue` returns.

        For an ordinary currency account every split is already in that account's
        own currency, so this collapses to a single entry. For a commodity /
        security account (Stock, Mutual Fund) the value is the **cost** paid in
        the transaction currency (e.g. CAD), not the share count — so the holding
        lands under the report currency and the sheet balances. Market value
        (shares × supplied price) is layered on top in `compute` when a `prices`
        table is given.

        Includes closing entries — see the module docstring."""
        totals: Dict[str, Fraction] = {}
        for split in account.GetSplitList():
            tx = split.GetParent()
            d = tx.GetDate()
            if date(d.year, d.month, d.day) <= as_of_date:
                ccy = tx.GetCurrency().get_mnemonic()
                value = split.GetValue()
                totals[ccy] = totals.get(ccy, Fraction(0)) + Fraction(value.num(), value.denom())
        return totals

    def quantity_as_of(self, account: Account, as_of_date: date) -> Fraction:
        """Units held (share count) of `account` through `as_of_date`
        (inclusive) — `xaccSplitGetAmount`, the commodity-denominated amount, as
        opposed to the transaction-currency value summed by `value_by_currency`.
        Used to mark a security to market: shares × price."""
        total = Fraction(0)
        for split in account.GetSplitList():
            tx = split.GetParent()
            d = tx.GetDate()
            if date(d.year, d.month, d.day) <= as_of_date:
                amount = split.GetAmount()
                total += Fraction(amount.num(), amount.denom())
        return total

    def _cost_in_cad(self, cost_by_ccy: Dict[str, Fraction],
                     fx_rates: Optional[FxRates]) -> Optional[Fraction]:
        """Cost basis converted to CAD, or None when a non-CAD cost can't be
        converted — no FX table, or one that lacks the holding's currency. The
        caller turns None into an actionable error."""
        total = Fraction(0)
        for ccy, amount in cost_by_ccy.items():
            if ccy == 'CAD':
                total += amount
            elif fx_rates is not None and fx_rates.has_rate(ccy):
                total += fx_rates.to_cad(amount, ccy)
            else:
                return None
        return total

    def _full_path(self, account: Account) -> str:
        parts, node = [], account
        while node is not None and node.get_parent() is not None:
            parts.append(node.GetName())
            node = node.get_parent()
        return ':'.join(reversed(parts))

    def compute(self, root: Account, as_of_date: date,
                fx_rates: Optional[FxRates] = None,
                prices: Optional[FxRates] = None) -> BalanceSheetResult:
        assets = BSSection("ASSETS")
        liabilities = BSSection("LIABILITIES")
        equity = BSSection("EQUITY")
        earnings_by_ccy: Dict[str, Fraction] = {}
        unrealized_cad = Fraction(0)    # market − cost of revalued securities

        for account in root.get_descendants():
            atype = account.GetType()
            commodity = account.GetCommodity()
            if commodity is None:
                continue
            value_by_ccy = self.value_by_currency(account, as_of_date)

            if atype in (ACCT_TYPE_INCOME, ACCT_TYPE_EXPENSE):
                # Fold into Current Year Earnings: net income = -(income + expense).
                for ccy, raw in value_by_ccy.items():
                    earnings_by_ccy[ccy] = earnings_by_ccy.get(ccy, Fraction(0)) - raw
                continue

            if atype in _ASSET_TYPES:
                section, sign = assets, 1                   # asset: debit-normal
            elif atype in _LIABILITY_TYPES:
                section, sign = liabilities, -1             # liability: credit-normal
            elif atype == ACCT_TYPE_EQUITY:
                section, sign = equity, -1                  # equity: credit-normal
            else:
                continue

            path = self._full_path(account)
            depth = len(path.split(':')) - 1

            # Mark a security to market when its price is supplied. The price is
            # quoted in the currency the holding was transacted in (its cost
            # currency); shares × price gives the market value there, which FX
            # then converts to CAD. Present that instead of cost and accrue
            # (market − cost) into the Unrealized Gains line so the sheet still
            # balances. Currency accounts and unpriced securities fall through to
            # cost basis.
            mnemonic = commodity.get_mnemonic()
            if (prices is not None and commodity.get_namespace() != 'CURRENCY'
                    and atype not in _TRADING_TYPES and prices.has_rate(mnemonic)):
                cost_cad = self._cost_in_cad(value_by_ccy, fx_rates)
                if cost_cad is None:
                    foreign = ', '.join(sorted(c for c in value_by_ccy if c != 'CAD'))
                    raise ValueError(
                        f"{mnemonic} is held in {foreign}, so its price is in "
                        f"{foreign} too — pass --fx-rates with a rate for {foreign} "
                        f"to express its market value in CAD.")
                price_ccy = next(iter(value_by_ccy)) if len(value_by_ccy) == 1 else 'CAD'
                # prices.to_cad is just quantity × price here; the product is in
                # price_ccy, which FX converts to CAD (identity when CAD).
                market_native = prices.to_cad(self.quantity_as_of(account, as_of_date),
                                              mnemonic)
                market_cad = (market_native if price_ccy == 'CAD'
                              else fx_rates.to_cad(market_native, price_ccy))
                # Securities are asset-normal (sign == 1); present market value in
                # the asset section and accrue the gain/loss vs cost.
                unrealized_cad += market_cad - cost_cad
                if market_cad != Fraction(0):
                    cad = market_cad if fx_rates is not None else None
                    section.lines.append(BSLine(path, account.GetName(), depth,
                                                'CAD', market_cad, cad))
                    section.currency_totals['CAD'] = (
                        section.currency_totals.get('CAD', Fraction(0)) + market_cad)
                continue

            for ccy, raw in value_by_ccy.items():
                presented = sign * raw                      # credit-normal sections flip sign
                if presented == Fraction(0):
                    continue
                cad = fx_rates.to_cad(presented, ccy) if fx_rates is not None else None
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

        # Unrealized gains reconcile market value back to the booked cost so the
        # accounting identity still holds.
        if unrealized_cad != Fraction(0):
            cad = unrealized_cad if fx_rates is not None else None
            equity.lines.append(BSLine(UNREALIZED_GAINS_LABEL, UNREALIZED_GAINS_LABEL,
                                       0, 'CAD', unrealized_cad, cad))
            equity.currency_totals['CAD'] = (
                equity.currency_totals.get('CAD', Fraction(0)) + unrealized_cad)

        balances = self._finalise(assets, liabilities, equity, fx_rates)
        return BalanceSheetResult(
            as_of_date=as_of_date, assets=assets, liabilities=liabilities,
            equity=equity, fx_rates_provided=fx_rates is not None, balances=balances,
            prices_provided=prices is not None)

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
