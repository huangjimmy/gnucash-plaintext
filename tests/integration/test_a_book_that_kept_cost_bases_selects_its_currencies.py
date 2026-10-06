"""A book with a history, which kept cost bases, turns `currency_balances:` on (Q-057).

The book is the Hong Kong company's of Q-056, after its six steps: two USD
invoices collected in USD, 8,000.00 USD sold, 50,000.00 CNY bought, a EUR
bill paid with EUR bought for it, and its year-end prices. It kept cost
bases, and its base currency is HKD.

`a_hong_kong_company_7_selects_hkd_usd_cny_and_eur.txt` holds a `company`
block stating `currency_balances: "HKD USD CNY EUR"`, and a price of 8.50
HKD/EUR. Importing it derives every split's amounts and every account's
balances from the book's first transaction.
"""

from fractions import Fraction
from pathlib import Path

from click.testing import CliRunner

from tests.conftest import _run

FIXTURES = Path('tests/fixtures')

STEPS = [
    'a_hong_kong_company_1_invoices_10000_usd_at_7_80_hkd_per_usd_and_collects_it_in_usd',
    'a_hong_kong_company_2_invoices_5000_usd_at_7_75_hkd_per_usd_and_collects_it_in_usd',
    'a_hong_kong_company_3_sells_8000_usd_at_7_85_hkd_per_usd',
    'a_hong_kong_company_4_buys_50000_cny_at_1_08_hkd_per_cny',
    'a_hong_kong_company_5_pays_a_2000_eur_bill_with_eur_bought_at_8_45_hkd_per_eur',
    'a_hong_kong_company_6_adds_prices_of_7_83_hkd_per_usd_and_1_09_hkd_per_cny_on_2026_12_31',
]
SELECTS = 'a_hong_kong_company_7_selects_hkd_usd_cny_and_eur'


def _turned_on(tmp_path):
    """The book after its six steps and the import that turns the setting on, and that import's output."""
    book = tmp_path / 'book.gnucash'
    for number, step in enumerate(STEPS):
        args = ['import', str(book), str(FIXTURES / f'{step}.txt'), '--include-business-objects']
        if number == 0:
            args.insert(1, '--new')
        assert _run(CliRunner(), *args).exit_code == 0
    done = _run(CliRunner(), 'import', str(book), str(FIXTURES / f'{SELECTS}.txt'))
    assert done.exit_code == 0, done.output
    return book, done.output


def _balances(book):
    listing = _run(CliRunner(), 'fx-balances', str(book))
    assert listing.exit_code == 0, listing.output
    return dict(line.split(': ', 1) for line in listing.output.splitlines()[1:])


def test_the_import_warns_that_the_book_cannot_be_migrated_back(tmp_path):
    _, output = _turned_on(tmp_path)
    assert ('this book kept cost bases, and from now on it keeps a balance in each of '
            'HKD USD CNY EUR on every account instead. The cost bases it recorded stay '
            'in it. A book migrated away from cost bases cannot be migrated back to '
            'them.') in output


def test_each_account_holds_what_its_history_comes_to(tmp_path):
    """The USD and the CNY the company still holds store what they cost in HKD.

    7,000.00 USD cost 54,350.00 HKD and 50,000.00 CNY cost 54,000.00 HKD, as
    the book's cost bases recorded (Q-056), and the 500.00 HKD it realized is
    in `Income:FX Gain`.
    """
    book, _ = _turned_on(tmp_path)
    balances = _balances(book)
    assert balances['Assets:Bank USD'].startswith('7000.00 USD, 54350.00 HKD, ')
    assert balances['Assets:Bank CNY'].startswith('50000.00 CNY, 54000.00 HKD, ')
    assert balances['Assets:Bank HKD'].startswith('991900.00 HKD, ')
    assert balances['Income:FX Gain'].startswith('-500.00 HKD, ')


def test_every_currency_adds_up_to_zero_across_the_accounts(tmp_path):
    book, _ = _turned_on(tmp_path)
    totals = {}
    for held in _balances(book).values():
        for each in held.split(', '):
            amount, code = each.split(' ')
            totals[code] = totals.get(code, Fraction(0)) + Fraction(amount)
    assert totals == {'HKD': 0, 'USD': 0, 'CNY': 0, 'EUR': 0}


def test_the_cost_bases_the_book_recorded_stay_in_it(tmp_path):
    book, _ = _turned_on(tmp_path)
    out = tmp_path / 'exported.txt'
    assert _run(CliRunner(), 'export', str(book), str(out)).exit_code == 0
    exported = out.read_text()
    assert 'cost_basis_balance: "2000.00"' in exported
    assert 'cost_basis_split_guid: "0d560000000000000000000000000111"' in exported


def test_the_setting_cannot_be_removed(tmp_path):
    book, _ = _turned_on(tmp_path)
    removal = tmp_path / 'removal.txt'
    removal.write_text('company\n\tcurrency_balances: $None$\n')
    done = _run(CliRunner(), 'import', str(book), str(removal))
    assert ('`currency_balances:` cannot be removed: a book migrated away from cost '
            'bases cannot be migrated back to them') in done.output, done.output
    assert _balances(book)['Assets:Bank USD'].startswith('7000.00 USD, 54350.00 HKD, ')
