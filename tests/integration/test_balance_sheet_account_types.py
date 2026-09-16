"""Q-032 (reopened): the balance sheet recognises every GnuCash asset and liability account type.

A user reported a balance sheet that disagreed with the figures `account-balance`
gave before the books were closed, and showed NOT BALANCED: Bank, Cash, Credit
Card, A/Receivable and A/Payable balances had been left out. The balance sheet is
GnuCash's own report now (Q-042), and these check it through the real import,
balance-sheet and account-balance paths:

- the Asset and Liability figures equal the `account-balance` figures, and the
  sheet balances;
- across two closed years, Equity:Retained Earnings:CAD holds each year's profit;
- every importable account type lands in its section;
- a USD account shows its balance beside its value, and a rates file prices it;
- a foreign security is valued from a prices file and a rates file together.

The figures are GnuCash's, from the plain text report, measured on GnuCash 5.10.
"""

import re
from datetime import date
from fractions import Fraction
from pathlib import Path

from click.testing import CliRunner

from cli.main import cli
from repositories.gnucash_repository import GnuCashRepository
from tests.integration.text_report_pages import figures, shares_as_gnucash_writes
from use_cases.account_balance import AccountBalanceUseCase

FIXTURES = Path('tests/fixtures')


def _import(runner, tmp_path, fixture, name='book.gnucash'):
    gf = tmp_path / name
    r = runner.invoke(cli, ['import', '--new', str(gf), str(FIXTURES / fixture)])
    assert r.exit_code == 0, r.output
    return gf


def _close(runner, gf, closing_date):
    r = runner.invoke(cli, ['close-books', str(gf), '--closing-date', closing_date])
    assert r.exit_code == 0, r.output


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


def _balance_sheet(runner, gf, as_of, *flags):
    r = runner.invoke(cli, ['balance-sheet', str(gf), '--as-of', as_of, *flags])
    assert r.exit_code == 0, r.output
    return r.output


def _labels_between(page, heading, total):
    """The labels of the page's lines after the section heading `heading` and before `total`."""
    labels = [re.split(r' {2,}', line.strip())[0] for line in page.splitlines()]
    start = labels.index(heading)
    return labels[start + 1:labels.index(total, start)]


def test_balance_sheet_figures_match_account_balance_and_the_sheet_balances(tmp_path):
    """The account types once left out: Bank (asset) and Credit Card (liability)."""
    runner = CliRunner()
    gf = _import(runner, tmp_path, 'balance_sheet_book.txt')
    as_of = date(2026, 12, 31)

    page = _balance_sheet(runner, gf, '2026-12-31')

    assert figures(page, 'Bank') == ['C$1,500.00']
    assert figures(page, 'CreditCard') == ['C$500.00']
    # account-balance gives a liability its credit-negative sign; the sheet
    # shows it positive.
    assert _account_balance(gf, 'Assets:Bank', as_of) == Fraction(1500)
    assert _account_balance(gf, 'Liabilities:CreditCard', as_of) == Fraction(-500)
    assert figures(page, 'Total Assets') == ['C$1,500.00']
    assert figures(page, 'Total Liabilities') == ['C$500.00']
    assert figures(page, 'Total Equity') == ['C$1,000.00']
    assert figures(page, 'Total Liabilities & Equity') == ['C$1,500.00']


def test_retained_earnings_hold_each_closed_years_profit(tmp_path):
    runner = CliRunner()
    gf = _import(runner, tmp_path, 'balance_sheet_book.txt')

    _close(runner, gf, '2025-12-31')
    # Year 1: income 1,000.00, expenses 400.00.
    assert figures(_balance_sheet(runner, gf, '2025-12-31'), 'CAD') == ['C$600.00']

    _close(runner, gf, '2026-12-31')
    page = _balance_sheet(runner, gf, '2026-12-31')

    # Year 2 adds income 500.00 less expenses 100.00, and nothing is left unclosed.
    assert figures(page, 'CAD') == ['C$1,000.00']
    assert figures(page, 'Retained Earnings') == ['C$0.00']
    assert figures(page, 'Total Equity') == ['C$1,000.00']
    assert figures(page, 'Total Liabilities & Equity') == ['C$1,500.00']


def test_every_importable_account_type_is_in_its_section(tmp_path):
    runner = CliRunner()
    gf = _import(runner, tmp_path, 'all_account_types_book.txt')

    page = _balance_sheet(runner, gf, '2024-12-31')

    # Asset family: bare Asset, Bank, Cash, A/Receivable, Stock and Mutual Fund.
    assert {'OtherAsset', 'Bank', 'Cash', 'Receivable', 'ACME', 'VGRO'} <= set(
        _labels_between(page, 'Assets', 'Total Assets'))
    # Liability family: bare Liability, Credit Card, A/Payable.
    assert {'Loan', 'CreditCard', 'Payable'} <= set(
        _labels_between(page, 'Liabilities', 'Total Liabilities'))
    assert 'Opening' in _labels_between(page, 'Equity', 'Total Equity')
    assert figures(page, 'Total Assets') == ['C$11,800.00']
    assert figures(page, 'Total Liabilities & Equity') == ['C$11,800.00']


def test_a_usd_bank_account_shows_beside_its_value_and_a_rates_file_prices_it(tmp_path):
    """The user's original book: Bank accounts in CAD and USD, once left out."""
    runner = CliRunner()
    gf = _import(runner, tmp_path, 'balance_sheet_bug_repro.txt')
    as_of = date(2024, 12, 31)

    page = _balance_sheet(runner, gf, '2024-12-31')
    assert figures(page, 'Checking') == ['C$5,850.00']
    # The book holds no USD price, so GnuCash's report values the USD at nothing.
    assert figures(page, 'USD') == ['$400.00', 'C$0.00']

    priced = _balance_sheet(runner, gf, '2024-12-31',
                            '--fx-rates', str(FIXTURES / 'usd_cad_rates.yaml'))
    assert figures(priced, 'USD') == ['$400.00', 'C$540.00']
    assert figures(priced, 'Total Assets') == ['C$6,390.00']
    assert figures(priced, 'Total Liabilities & Equity') == ['C$6,390.00']

    assert _account_balance(gf, 'Assets:Bank:Checking', as_of) == Fraction(5850)
    assert _account_balance(gf, 'Assets:Bank:USD', as_of) == Fraction(400)


def test_a_foreign_security_is_valued_from_a_prices_file_and_a_rates_file(tmp_path):
    """USTECH: 60 is in USD, the currency it was bought in, and USD: 1.35 prices the USD in CAD.

    The book's top-level accounts are in CAD and USD, so the command gives the
    currency.
    """
    runner = CliRunner()
    gf = _import(runner, tmp_path, 'foreign_security_book.txt')

    page = _balance_sheet(runner, gf, '2024-12-31', '--currency', 'CAD',
                          '--prices', str(FIXTURES / 'foreign_security_prices.yaml'),
                          '--fx-rates', str(FIXTURES / 'usd_cad_rates.yaml'))

    held, value = figures(page, 'USTECH')
    assert held in shares_as_gnucash_writes('10', 'USTECH'), page
    assert value == 'C$810.00'
    assert figures(page, 'Unrealized Gains') == ['C$135.00']


def test_natural_form_receivable_payable_land_on_balance_sheet(tmp_path):
    """Q-033: `type: "Receivable"` and `type: "Payable"` import as those account types.

    Matched by account type, not by name, and each lands in its section of the
    sheet rather than being left out because the importer knew only the longer
    'Accounts Receivable' form.
    """
    from gnucash.gnucash_core_c import ACCT_TYPE_PAYABLE, ACCT_TYPE_RECEIVABLE
    runner = CliRunner()
    gf = _import(runner, tmp_path, 'receivable_payable_natural_form_book.txt')
    as_of = date(2024, 12, 31)

    repo = GnuCashRepository(str(gf))
    repo.open()
    try:
        types = {a.GetName(): a.GetType() for a in repo.book.get_root_account().get_descendants()}
    finally:
        repo.close()
    assert types['Trade receivable'] == ACCT_TYPE_RECEIVABLE
    assert types['Trade payable'] == ACCT_TYPE_PAYABLE

    page = _balance_sheet(runner, gf, '2024-12-31')

    assert 'Trade receivable' in _labels_between(page, 'Assets', 'Total Assets')
    assert 'Trade payable' in _labels_between(page, 'Liabilities', 'Total Liabilities')
    # Cash 600 + Receivable 400 = 1,000 of assets; Payable 250; Equity 750.
    assert figures(page, 'Trade receivable') == ['C$400.00']
    assert figures(page, 'Cash') == ['C$600.00']
    assert figures(page, 'Trade payable') == ['C$250.00']
    assert figures(page, 'Total Assets') == ['C$1,000.00']
    assert figures(page, 'Total Liabilities & Equity') == ['C$1,000.00']
    assert _account_balance(gf, 'Assets:Trade receivable', as_of) == Fraction(400)
    assert _account_balance(gf, 'Liabilities:Trade payable', as_of) == Fraction(-250)
