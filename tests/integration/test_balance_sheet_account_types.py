"""Q-032 (reopened): the balance sheet recognises every GnuCash asset and liability account type.

A user reported a balance sheet that disagreed with the figures `account-balance`
printed before the books were closed, and showed NOT BALANCED: Bank, Cash, Credit
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

from datetime import date
from fractions import Fraction
from pathlib import Path

from click.testing import CliRunner

from cli.main import cli
from repositories.gnucash_repository import GnuCashRepository
from tests.integration.text_report_pages import amount_of as _amount
from tests.integration.text_report_pages import block_of as _block_of
from tests.integration.text_report_pages import block_total_of as _block_total_of
from tests.integration.text_report_pages import key_of as _key
from tests.integration.text_report_pages import shares_as_a_block_writes, under
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


def _accounts_under(page, section):
    """The names of the accounts written beneath `section`.

    Every account line carries its whole path, so the section an account is in
    is the first part of its own path rather than a heading above it. The name
    is the last part, which is what a reader of the sheet looks for.
    """
    prefix = section + ':'
    return {line.strip().rsplit(' ', 2)[0].split(':')[-1]
            for line in page.splitlines()
            if line.startswith('\t') and not line.startswith('\t\t')
            and line.strip().startswith(prefix)}


def test_balance_sheet_figures_match_account_balance_and_the_sheet_balances(tmp_path):
    """The account types once left out: Bank (asset) and Credit Card (liability)."""
    runner = CliRunner()
    gf = _import(runner, tmp_path, 'balance_sheet_book.txt')
    as_of = date(2026, 12, 31)

    page = _balance_sheet(runner, gf, '2026-12-31')

    assert _amount(page, 'Assets:Bank') == '1500.00 CAD'
    assert _amount(page, 'Liabilities:CreditCard') == '500.00 CAD'
    # account-balance prints a liability with its credit-negative sign; the sheet
    # shows it positive.
    assert _account_balance(gf, 'Assets:Bank', as_of) == Fraction(1500)
    assert _account_balance(gf, 'Liabilities:CreditCard', as_of) == Fraction(-500)
    assert _key(page, 'total_assets') == '1500.00 CAD'
    assert _key(page, 'total_liabilities') == '500.00 CAD'
    # No equity account holds anything, so none is written; the year's profit
    # is not closed into one either, which is what `retained_earnings` states.
    assert 'Equity' not in page, page
    assert _key(page, 'retained_earnings') == '1000.00 CAD'
    assert _key(page, 'total_liabilities_and_equity') == '1500.00 CAD'


def test_retained_earnings_hold_each_closed_years_profit(tmp_path):
    runner = CliRunner()
    gf = _import(runner, tmp_path, 'balance_sheet_book.txt')

    _close(runner, gf, '2025-12-31')
    # Year 1: income 1,000.00, expenses 400.00.
    assert _amount(_balance_sheet(runner, gf, '2025-12-31'),
                   'Equity:Retained Earnings:CAD') == '600.00 CAD'

    _close(runner, gf, '2026-12-31')
    page = _balance_sheet(runner, gf, '2026-12-31')

    # Year 2 adds income 500.00 less expenses 100.00, and nothing is left
    # unclosed — so there are no retained earnings for the block to state.
    assert _amount(page, 'Equity:Retained Earnings:CAD') == '1000.00 CAD'
    assert 'retained_earnings' not in page, page
    assert _key(page, 'total_equity') == '1000.00 CAD'
    assert _key(page, 'total_liabilities_and_equity') == '1500.00 CAD'


def test_every_importable_account_type_is_in_its_section(tmp_path):
    runner = CliRunner()
    gf = _import(runner, tmp_path, 'all_account_types_book.txt')

    page = _balance_sheet(runner, gf, '2024-12-31')

    # Asset family: bare Asset, Bank, Cash, A/Receivable, Stock and Mutual Fund.
    assert {'OtherAsset', 'Bank', 'Cash', 'Receivable', 'ACME', 'VGRO'} <= _accounts_under(
        page, 'Assets')
    # Liability family: bare Liability, Credit Card, A/Payable.
    assert {'Loan', 'CreditCard', 'Payable'} <= _accounts_under(page, 'Liabilities')
    assert 'Opening' in _accounts_under(page, 'Equity')
    assert _key(page, 'total_assets') == '11800.00 CAD'
    assert _key(page, 'total_liabilities_and_equity') == '11800.00 CAD'


def test_a_usd_bank_account_shows_beside_its_value_and_a_rates_file_prices_it(tmp_path):
    """The user's original book: Bank accounts in CAD and USD, once left out."""
    runner = CliRunner()
    gf = _import(runner, tmp_path, 'balance_sheet_bug_repro.txt')
    as_of = date(2024, 12, 31)

    page = _balance_sheet(runner, gf, '2024-12-31')
    assert _amount(page, 'Assets:Bank:Checking') == '5850.00 CAD'
    # The book holds no USD price, so GnuCash's report values the USD at
    # nothing — and states no price at all, rather than a zero one.
    assert _amount(page, 'Assets:Bank:USD') == '400.00 USD'
    assert under(page, 'Assets:Bank:USD') == {
        'account.commodity.mnemonic': 'USD',
        'value': '0.00'}

    priced = _balance_sheet(runner, gf, '2024-12-31',
                            '--fx-rates', str(FIXTURES / 'usd_cad_rates.yaml'))
    assert under(priced, 'Assets:Bank:USD') == {
        'account.commodity.mnemonic': 'USD',
        'share_price': '1.35',
        'value': '540.00'}
    assert _key(priced, 'total_assets') == '6390.00 CAD'
    assert _key(priced, 'total_liabilities_and_equity') == '6390.00 CAD'

    assert _account_balance(gf, 'Assets:Bank:Checking', as_of) == Fraction(5850)
    assert _account_balance(gf, 'Assets:Bank:USD', as_of) == Fraction(400)


def test_a_foreign_security_is_valued_from_a_prices_file_and_a_rates_file(tmp_path):
    """USTECH: 60 is in USD, the currency it was bought in, and USD: 1.35 prices the USD in CAD.

    The book's top-level accounts are in CAD and USD, so the command states the
    currency.
    """
    runner = CliRunner()
    gf = _import(runner, tmp_path, 'foreign_security_book.txt')

    page = _balance_sheet(runner, gf, '2024-12-31', '--currency', 'CAD',
                          '--prices', str(FIXTURES / 'foreign_security_prices.yaml'),
                          '--fx-rates', str(FIXTURES / 'usd_cad_rates.yaml'))

    assert _amount(page, 'Assets:Brokerage:USTECH') == shares_as_a_block_writes('10', 'USTECH'), page
    assert under(page, 'Assets:Brokerage:USTECH')['value'] == '810.00'
    # USTECH is priced in US dollars, but a security opens no cost basis, so
    # its whole gain — the share price and the US dollar moving together —
    # keeps GnuCash's own revaluation, and none of it is stated as an
    # exchange movement.
    assert _block_total_of(page, 'unrealized_gains_assets_fx') == 0
    # Nothing owed in a foreign currency, so the owed side comes to nothing —
    # and says so as a figure, because the book holds no such liability rather
    # than the side going unmeasured.
    assert _key(page, 'unrealized_gains_liabilities_fx') == '0.00 CAD'
    assert _key(page, 'unrealized_gains_fx') == '0.00 CAD'
    # Stated in full: the shares, what the book paid for them converted, what
    # they are worth at the file's prices, and the difference. 10 USTECH bought
    # for 500.00 USD cost 675.00 CAD at 1.35 and are worth 810.00 at 81.00 CAD
    # each — so every figure a reader would check is on the page.
    assert _block_of(page, 'unrealized_gains_other') == '\n'.join((
        '\t\tsecurities: # security, fund, etc',
        '\t\t\tsecurity:',
        '\t\t\t\tcommodity.namespace: "NASDAQ"',
        '\t\t\t\tcommodity.mnemonic: "USTECH"',
        '\t\t\t\tquantity: 10.0000',
        '\t\t\t\tshare_price: 81 # what price-fn returns for this commodity',
        '\t\t\t\tmeasured_from: gnucash_revaluation # its cost bases do not'
        ' account for what the accounts hold',
        '\t\t\t\taccounts:',
        '\t\t\t\t\taccount:',
        '\t\t\t\t\t\tguid: <guid>',
        '\t\t\t\t\t\tname: "Assets:Brokerage:USTECH"',
        '\t\t\t\t\t\tbalance: 10.0000',
        '\t\t\t\t\t\tsplits:',
        '\t\t\t\t\t\t\tsplit_amount 10.0000 | value 500.00 USD',
        "\t\t\t\tvalue: 810.00 # the holding converted at the sheet's price",
        "\t\t\t\tcost_value: 675.00 # its splits' values, converted",
        '\t\t\t\tunrealized_gains_other: 135.00 # value - cost_value',
        "\t\tvalue: 810.00 # sum of each security's value",
        "\t\tcost_value: 675.00 # sum of each security's cost_value",
        '\t\tunrealized_gains_other: 135.00 # value - cost_value')), page
    assert _key(page, 'total_unrealized_gains') == '135.00 CAD'


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

    assert 'Trade receivable' in _accounts_under(page, 'Assets')
    assert 'Trade payable' in _accounts_under(page, 'Liabilities')
    # Cash 600 + Receivable 400 = 1,000 of assets; Payable 250; Equity 750.
    assert _amount(page, 'Assets:Trade receivable') == '400.00 CAD'
    assert _amount(page, 'Assets:Cash') == '600.00 CAD'
    assert _amount(page, 'Liabilities:Trade payable') == '250.00 CAD'
    assert _key(page, 'total_assets') == '1000.00 CAD'
    assert _key(page, 'total_liabilities_and_equity') == '1000.00 CAD'
    assert _account_balance(gf, 'Assets:Trade receivable', as_of) == Fraction(400)
    assert _account_balance(gf, 'Liabilities:Trade payable', as_of) == Fraction(-250)
