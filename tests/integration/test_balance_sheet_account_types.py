"""Q-032 (reopened): the balance sheet must recognise *every* GnuCash asset and
liability account type, not just the bare ASSET / LIABILITY.

A user reported a balance sheet that disagreed with the numbers they had read
from `account-balance` before closing the books, and showed NOT BALANCED. The
cause: the sheet only matched ACCT_TYPE_ASSET / ACCT_TYPE_LIABILITY, so Bank,
Cash, Credit Card, A/Receivable and A/Payable balances were silently dropped —
the very account types a real book is full of.

These tests guard the fix by going through the real import + balance-sheet +
account-balance code paths:

  * the balance sheet's Asset / Liability totals equal the `account-balance`
    figures a user reads before closing, and the accounting equation
    Assets = Liabilities + Equity holds;
  * across two years, Retained Earnings grow by exactly each year's profit;
  * every importable GnuCash account type lands in the correct section and
    nothing with a non-zero balance is dropped — including Stock and Mutual
    Fund, reported at cost basis in the transaction currency;
  * supplying `--prices` marks securities to market (in the holding's own
    currency, converted to CAD via `--fx-rates` for foreign holdings) and adds an
    Unrealized Gains line that keeps the sheet balanced;
  * the original multi-currency repro now balances with Bank balances present.
"""

import time
from datetime import date
from fractions import Fraction
from pathlib import Path

from click.testing import CliRunner

from cli.main import cli
from repositories.gnucash_repository import GnuCashRepository
from services.balance_sheet import UNREALIZED_GAINS_LABEL, BalanceSheet
from services.fx_rates import FxRates
from use_cases.account_balance import AccountBalanceUseCase

FIXTURES = Path('tests/fixtures')


def _import(runner, tmp_path, fixture, name='book.gnucash'):
    gf = tmp_path / name
    r = runner.invoke(cli, ['import', '--new', str(gf), str(FIXTURES / fixture)])
    assert r.exit_code == 0, r.output
    time.sleep(1)
    return gf


def _close(runner, gf, closing_date):
    r = runner.invoke(cli, ['close-books', str(gf), '--closing-date', closing_date])
    assert r.exit_code == 0, r.output
    time.sleep(1)


def _account_balance(gf, prefix, as_of):
    """Recursive native balance of one account, via the real account-balance
    use case — the number a user reads before closing."""
    repo = GnuCashRepository(str(gf))
    repo.open()
    try:
        result = AccountBalanceUseCase(repo).execute(as_of, account_prefix=prefix)
        return result.balances[0].amount
    finally:
        repo.close()


def _balance_sheet(gf, as_of, fx=None, prices=None):
    repo = GnuCashRepository(str(gf))
    repo.open()
    try:
        return BalanceSheet().compute(repo.book.get_root_account(), as_of, fx, prices)
    finally:
        repo.close()


def test_balance_sheet_totals_match_account_balance_and_equation_holds(tmp_path):
    """The dropped-type regression: Bank (asset) and Credit Card (liability) must
    appear, their totals must equal what `account-balance` reports, and the sheet
    must balance."""
    runner = CliRunner()
    gf = _import(runner, tmp_path, 'balance_sheet_book.txt')
    as_of = date(2026, 12, 31)

    bs = _balance_sheet(gf, as_of)

    # The previously-dropped types are present and named.
    assert any(line.name == 'Bank' for line in bs.assets.lines)
    assert any(line.name == 'CreditCard' for line in bs.liabilities.lines)

    # Section totals equal the account-balance figures (account-balance reports
    # liabilities with their raw credit-negative sign; the sheet presents them
    # positive).
    bank = _account_balance(gf, 'Assets:Bank', as_of)
    credit_card = _account_balance(gf, 'Liabilities:CreditCard', as_of)
    assert bs.assets.currency_totals['CAD'] == bank == Fraction(1500)
    assert bs.liabilities.currency_totals['CAD'] == -credit_card == Fraction(500)

    # Accounting equation, exactly, per currency.
    assets = bs.assets.currency_totals.get('CAD', Fraction(0))
    liab_equity = (bs.liabilities.currency_totals.get('CAD', Fraction(0))
                   + bs.equity.currency_totals.get('CAD', Fraction(0)))
    assert assets == liab_equity
    assert bs.balances is True


def test_retained_earnings_grow_by_each_years_profit(tmp_path):
    """Close two consecutive years; Retained Earnings must equal the cumulative
    profit and grow by exactly the second year's net income."""
    runner = CliRunner()
    gf = _import(runner, tmp_path, 'balance_sheet_book.txt')

    def retained_earnings(as_of):
        bs = _balance_sheet(gf, as_of)
        return sum((line.balance for line in bs.equity.lines
                    if 'Retained Earnings' in line.path), Fraction(0))

    _close(runner, gf, '2025-12-31')
    re_2025 = retained_earnings(date(2025, 12, 31))
    assert re_2025 == Fraction(600)          # year-1 profit: income 1000 - expenses 400

    _close(runner, gf, '2026-12-31')
    re_2026 = retained_earnings(date(2026, 12, 31))
    assert re_2026 == Fraction(1000)         # cumulative
    assert re_2026 - re_2025 == Fraction(400)  # year-2 profit: income 500 - expenses 100

    # Closing only moved net income from earnings into equity — still balances.
    assert _balance_sheet(gf, date(2026, 12, 31)).balances is True


def test_every_importable_account_type_is_classified(tmp_path):
    """A book that uses every importable GnuCash account type must balance and
    place each account in the right section — none dropped."""
    runner = CliRunner()
    gf = _import(runner, tmp_path, 'all_account_types_book.txt')
    as_of = date(2024, 12, 31)
    bs = _balance_sheet(gf, as_of)

    assert bs.balances is True

    asset_names = {line.name for line in bs.assets.lines}
    liability_names = {line.name for line in bs.liabilities.lines}
    equity_names = {line.name for line in bs.equity.lines}

    # Asset family: bare Asset, Bank, Cash, A/Receivable, plus the commodity
    # types Stock and Mutual Fund.
    assert {'OtherAsset', 'Bank', 'Cash', 'Receivable', 'ACME', 'VGRO'} <= asset_names
    # Liability family: bare Liability, Credit Card, A/Payable.
    assert {'Loan', 'CreditCard', 'Payable'} <= liability_names
    # Equity, plus Income/Expense folded into Current Year Earnings.
    assert 'Opening' in equity_names
    assert any('Current Year Earnings' in line.path for line in bs.equity.lines)

    # Securities are reported at cost basis in the transaction currency (CAD),
    # not under the security ticker — so they land in the CAD column and the
    # book balances. Each was bought for 500 CAD.
    for ticker in ('ACME', 'VGRO'):
        line = next(line for line in bs.assets.lines if line.name == ticker)
        assert line.currency == 'CAD'
        assert line.balance == Fraction(500)

    # No account with a non-zero balance is missing from the sheet. Build the set
    # of leaf accounts the book actually carries balances on, and confirm each is
    # represented (asset/liability/equity by path, income/expense folded).
    repo = GnuCashRepository(str(gf))
    repo.open()
    try:
        from gnucash.gnucash_core_c import ACCT_TYPE_EQUITY, ACCT_TYPE_EXPENSE, ACCT_TYPE_INCOME

        from services.balance_sheet import _ASSET_TYPES, _LIABILITY_TYPES
        shown_paths = {line.path for line in
                       bs.assets.lines + bs.liabilities.lines + bs.equity.lines}
        sheet = BalanceSheet()
        for account in repo.book.get_root_account().get_descendants():
            atype = account.GetType()
            if sum(sheet.value_by_currency(account, as_of).values(), Fraction(0)) == Fraction(0):
                continue
            if atype in (ACCT_TYPE_INCOME, ACCT_TYPE_EXPENSE):
                continue  # folded into Current Year Earnings, not a line
            if atype in _ASSET_TYPES or atype in _LIABILITY_TYPES or atype == ACCT_TYPE_EQUITY:
                assert sheet._full_path(account) in shown_paths
    finally:
        repo.close()


def test_multicurrency_repro_balances_with_bank_accounts_present(tmp_path):
    """The user's original repro: Bank accounts (CAD + USD) were dropped, leaving
    empty ASSETS and NOT BALANCED. They must now appear and balance per currency."""
    runner = CliRunner()
    gf = _import(runner, tmp_path, 'balance_sheet_bug_repro.txt')
    as_of = date(2024, 12, 31)
    bs = _balance_sheet(gf, as_of)

    assert bs.balances is True
    assert bs.assets.currency_totals.get('CAD') == Fraction(5850)
    assert bs.assets.currency_totals.get('USD') == Fraction(400)

    # Each Bank leaf matches its account-balance figure.
    assert _account_balance(gf, 'Assets:Bank:Checking', as_of) == Fraction(5850)
    assert _account_balance(gf, 'Assets:Bank:USD', as_of) == Fraction(400)


def test_prices_mark_securities_to_market_with_unrealized_gains(tmp_path):
    """`--prices` values Stock/Mutual Fund holdings at shares × price (CAD) and
    adds an Unrealized Gains equity line so the sheet still balances."""
    runner = CliRunner()
    gf = _import(runner, tmp_path, 'all_account_types_book.txt')
    as_of = date(2024, 12, 31)
    prices = FxRates.load(str(FIXTURES / 'security_prices.yaml'))

    bs = _balance_sheet(gf, as_of, prices=prices)

    assert bs.prices_provided is True
    assert bs.balances is True

    # ACME: 10 shares × 60 = 600 CAD (cost was 500). VGRO: 20 × 30 = 600 (cost 500).
    acme = next(line for line in bs.assets.lines if line.name == 'ACME')
    vgro = next(line for line in bs.assets.lines if line.name == 'VGRO')
    assert acme.currency == 'CAD' and acme.balance == Fraction(600)
    assert vgro.currency == 'CAD' and vgro.balance == Fraction(600)

    # Unrealized gains = (600 - 500) + (600 - 500) = 200, on the equity side.
    unrealized = next(line for line in bs.equity.lines
                      if line.name == UNREALIZED_GAINS_LABEL)
    assert unrealized.balance == Fraction(200)

    # Revaluation flows symmetrically into assets and equity (each +200 vs cost),
    # so the accounting equation still holds.
    assert bs.assets.currency_totals['CAD'] == Fraction(13000)
    le = (bs.liabilities.currency_totals.get('CAD', Fraction(0))
          + bs.equity.currency_totals.get('CAD', Fraction(0)))
    assert bs.assets.currency_totals['CAD'] == le


def test_balance_sheet_cli_accepts_prices(tmp_path):
    """End-to-end: `--prices` marks securities to market; the output carries the
    Unrealized Gains line, the market-valuation note, and still balances."""
    runner = CliRunner()
    gf = _import(runner, tmp_path, 'all_account_types_book.txt')
    r = runner.invoke(cli, ['balance-sheet', str(gf), '--as-of', '2024-12-31',
                            '--prices', str(FIXTURES / 'security_prices.yaml')])
    assert r.exit_code == 0, r.output
    assert UNREALIZED_GAINS_LABEL in r.output
    assert 'marked to market' in r.output
    assert 'NOT BALANCED' not in r.output
    assert '600.00' in r.output            # ACME at 10 × 60


def test_report_accepts_prices(tmp_path):
    """`report` threads `--prices` into its balance sheet too."""
    runner = CliRunner()
    gf = _import(runner, tmp_path, 'all_account_types_book.txt')
    r = runner.invoke(cli, ['report', str(gf), 'balance-sheet',
                            '--fiscal-year-end', '2024-12-31',
                            '--prices', str(FIXTURES / 'security_prices.yaml')])
    assert r.exit_code == 0, r.output
    assert UNREALIZED_GAINS_LABEL in r.output
    assert 'NOT BALANCED' not in r.output


def test_foreign_security_market_value_uses_price_currency_and_fx(tmp_path):
    """A US-listed holding is priced in its own currency (USD); `--fx-rates`
    converts the market value to CAD. Cost is converted the same way, so the
    unrealized gain and the whole sheet are consistent in CAD."""
    runner = CliRunner()
    gf = _import(runner, tmp_path, 'foreign_security_book.txt')
    as_of = date(2024, 12, 31)
    fx = FxRates.load(str(FIXTURES / 'usd_cad_rates.yaml'))
    prices = FxRates.load(str(FIXTURES / 'foreign_security_prices.yaml'))

    bs = _balance_sheet(gf, as_of, fx=fx, prices=prices)

    assert bs.balances is True
    ustech = next(line for line in bs.assets.lines if line.name == 'USTECH')
    # 10 shares × 60 USD × 1.35 = 810 CAD.
    assert ustech.currency == 'CAD' and ustech.balance == Fraction(810)
    # Unrealized = (60 − 50) × 10 = 100 USD × 1.35 = 135 CAD.
    unrealized = next(line for line in bs.equity.lines
                      if line.name == UNREALIZED_GAINS_LABEL)
    assert unrealized.balance == Fraction(135)


def test_foreign_security_priced_without_fx_is_a_clear_error(tmp_path):
    """Pricing a USD-held security with no USD→CAD rate can't yield a CAD market
    value — fail with an actionable message instead of silently mis-valuing it."""
    runner = CliRunner()
    gf = _import(runner, tmp_path, 'foreign_security_book.txt')
    r = runner.invoke(cli, ['balance-sheet', str(gf), '--as-of', '2024-12-31',
                            '--prices', str(FIXTURES / 'foreign_security_prices.yaml')])
    assert r.exit_code != 0
    assert 'USTECH' in r.output and 'fx-rates' in r.output and 'USD' in r.output


def test_foreign_security_priced_with_incomplete_fx_is_a_clear_error(tmp_path):
    """`--fx-rates` supplied but missing the holding's currency must still fail
    with a clean, actionable message — the message reaching the output proves it
    was a handled ClickException, not an unhandled MissingFxRateError traceback."""
    runner = CliRunner()
    gf = _import(runner, tmp_path, 'foreign_security_book.txt')
    r = runner.invoke(cli, ['balance-sheet', str(gf), '--as-of', '2024-12-31',
                            '--prices', str(FIXTURES / 'foreign_security_prices.yaml'),
                            '--fx-rates', str(FIXTURES / 'non_usd_rates.yaml')])
    assert r.exit_code != 0
    assert 'Error:' in r.output
    assert 'USD' in r.output and 'fx-rates' in r.output


def test_natural_form_receivable_payable_land_on_balance_sheet(tmp_path):
    """Q-033: the natural `type: "Receivable"` / `type: "Payable"` spellings must
    import as the RECEIVABLE / PAYABLE account *types* (matched by type, not name)
    and appear on the balance sheet, balanced — not be silently dropped because
    the importer only knew the longer 'Accounts Receivable' form.
    """
    from gnucash.gnucash_core_c import ACCT_TYPE_PAYABLE, ACCT_TYPE_RECEIVABLE
    runner = CliRunner()
    gf = _import(runner, tmp_path, 'receivable_payable_natural_form_book.txt')
    as_of = date(2024, 12, 31)
    bs = _balance_sheet(gf, as_of)

    asset_paths = {line.path for line in bs.assets.lines}
    liability_paths = {line.path for line in bs.liabilities.lines}

    # Match by ACCOUNT TYPE: the receivable account really is RECEIVABLE-typed and
    # the payable account PAYABLE-typed, and each lands in the right section.
    repo = GnuCashRepository(str(gf))
    repo.open()
    try:
        sheet = BalanceSheet()
        receivable = payable = 0
        for a in repo.book.get_root_account().get_descendants():
            t = a.GetType()
            if t == ACCT_TYPE_RECEIVABLE:
                receivable += 1
                assert sheet._full_path(a) in asset_paths
            elif t == ACCT_TYPE_PAYABLE:
                payable += 1
                assert sheet._full_path(a) in liability_paths
        assert receivable == 1 and payable == 1   # the natural forms really mapped
    finally:
        repo.close()

    # Cash 600 + Receivable 400 = 1000 assets; Payable 250; Equity 750 → balances.
    assert bs.assets.currency_totals.get('CAD') == Fraction(1000)
    assert bs.liabilities.currency_totals.get('CAD') == Fraction(250)
    assert bs.balances is True
    assert _account_balance(gf, 'Assets:Trade receivable', as_of) == Fraction(400)
    assert _account_balance(gf, 'Liabilities:Trade payable', as_of) == Fraction(-250)
