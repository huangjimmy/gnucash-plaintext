"""What a book keeping a balance in each selected currency does beyond the author's scenario (Q-057).

The book is U's, of `tests/integration/test_u_keeps_a_balance_in_cad_usd_hkd_and_cny_on_every_account.py`:
USD_A holds 100.00 USD and stores 130.00 CAD, 780.00 HKD and 600.00 CNY.
"""

import re
from fractions import Fraction
from pathlib import Path

import pytest
from click.testing import CliRunner

from tests.conftest import _run

FIXTURES = Path('tests/fixtures')
HOLDS_100_USD = 'u_1_holds_100_usd_that_is_130_cad_780_hkd_and_600_cny'
TO_USD_A1 = 'u_2_transfers_10_usd_from_usd_a_to_usd_a1'


def _book(tmp_path, *steps):
    book = tmp_path / 'book.gnucash'
    for number, step in enumerate(steps):
        args = ['import', str(book), str(FIXTURES / f'{step}.txt')]
        if number == 0:
            args.insert(1, '--new')
        done = _run(CliRunner(), *args)
        assert done.exit_code == 0 and 'Errors:       0' in done.output, done.output
    return book


def _balances(book, *more):
    listing = _run(CliRunner(), 'fx-balances', str(book), *more)
    assert listing.exit_code == 0, listing.output
    return dict(line.split(': ', 1) for line in listing.output.splitlines()[1:])


def _company(tmp_path, line):
    stated = tmp_path / 'company.txt'
    stated.write_text(f'company\n\t{line}\n')
    return str(stated)


def test_150_usd_moved_out_of_an_account_holding_100_usd(tmp_path):
    """The 100.00 USD the account held move as they were stored, and the 50.00 USD past zero at the price of the day.

    USD_A gives up its 130.00 CAD, 780.00 HKD and 600.00 CNY with the 100.00
    USD. The other 50.00 USD it now owes are 65.00 CAD, 390.00 HKD and 300.00
    CNY at the book's prices of 1.30 CAD/USD, 7.80 HKD/USD and 6.00 CNY/USD.
    """
    book = _book(tmp_path, HOLDS_100_USD,
                 'u_2_transfers_150_usd_from_usd_a_holding_100_usd_to_usd_a1')
    balances = _balances(book)
    assert balances['Assets:USD_A'] == '-50.00 USD, -65.00 CAD, -390.00 HKD, -300.00 CNY'
    assert balances['Assets:USD_A1'] == '150.00 USD, 195.00 CAD, 1170.00 HKD, 900.00 CNY'


def test_4_usd_moved_to_another_usd_account_and_6_usd_exchanged_for_8_40_cad(tmp_path):
    """USD_A1 takes four tenths of what USD_A gave up, and CAD_B takes the 6.00 USD at the prices of the day.

    USD_A gives up 10.00 USD, 13.00 CAD, 78.00 HKD and 60.00 CNY. USD_A1's
    4.00 USD take 5.20 CAD, 31.20 HKD and 24.00 CNY. CAD_B's 8.40 CAD are
    6.00 USD, and 47.10 HKD and 39.00 CNY at 7.85 HKD/USD and 6.50 CNY/USD.
    The gain is 0.60 CAD, 0.30 HKD and 3.00 CNY.
    """
    book = _book(tmp_path, HOLDS_100_USD,
                 'u_2_moves_4_usd_to_usd_a1_and_exchanges_6_usd_for_8_40_cad')
    balances = _balances(book)
    assert balances['Assets:USD_A'] == '90.00 USD, 117.00 CAD, 702.00 HKD, 540.00 CNY'
    assert balances['Assets:USD_A1'] == '4.00 USD, 5.20 CAD, 31.20 HKD, 24.00 CNY'
    assert balances['Assets:CAD_B'] == '8.40 CAD, 6.00 USD, 47.10 HKD, 39.00 CNY'
    assert balances['Income:FX Gain'] == '-0.60 CAD, 0.00 USD, -0.30 HKD, -3.00 CNY'


def test_10_usd_sent_and_9_usd_received_keep_the_amounts_the_transaction_states(tmp_path):
    """The US dollars are GnuCash's, as stated, and the other currencies add up to zero across the two accounts.

    USD_A gives up 78.00 HKD and 60.00 CNY. USD_A1's 9.00 USD take nine
    tenths, 70.20 HKD and 54.00 CNY. The transaction has no `$residual$`
    split, so nothing is realized: the 7.80 HKD and 6.00 CNY between them are
    shared by the two splits, 3.90 HKD and 3.00 CNY each.
    """
    book = _book(tmp_path, HOLDS_100_USD, 'u_2_sends_10_usd_from_usd_a_and_usd_a1_receives_9_usd')
    balances = _balances(book)
    assert balances['Assets:USD_A'] == '90.00 USD, 117.00 CAD, 705.90 HKD, 543.00 CNY'
    assert balances['Assets:USD_A1'] == '9.00 USD, 13.00 CAD, 74.10 HKD, 57.00 CNY'


def test_two_transactions_of_one_day_are_read_in_the_order_gnucash_keeps_them(tmp_path):
    """Number 9 before number 10, as GnuCash's register shows them, whichever the file states first.

    Number 9 moves all 100.00 USD from USD_A to USD_A1, with the 130.00 CAD,
    780.00 HKD and 600.00 CNY they store. Number 10 moves 40.00 USD back,
    four tenths of each. Read the other way round, number 10 would take
    40.00 USD out of an empty account at the prices of the day, 1.40 CAD/USD.
    """
    book = _book(tmp_path, HOLDS_100_USD,
                 'u_2_moves_100_usd_to_usd_a1_as_number_9_and_40_usd_back_as_number_10_on_one_day')
    balances = _balances(book)
    assert balances['Assets:USD_A'] == '40.00 USD, 52.00 CAD, 312.00 HKD, 240.00 CNY'
    assert balances['Assets:USD_A1'] == '60.00 USD, 78.00 CAD, 468.00 HKD, 360.00 CNY'


TO_AN_ACCOUNT_CALLED_COST_BASIS = ('u_2_moves_10_usd_to_an_account_called_usd_kept_at_cost_basis_'
                                   'beside_a_split_of_0_00_usd')


def test_an_account_s_name_is_printed_as_the_book_has_it(tmp_path):
    """The balance sheet's working is reworded, and an account called `USD kept at cost basis` is not."""
    book = _book(tmp_path, HOLDS_100_USD, TO_AN_ACCOUNT_CALLED_COST_BASIS)
    page = _run(CliRunner(), 'balance-sheet', str(book), '--as-of', '2030-02-01',
                '--currency', 'CAD').output
    assert '\tAssets:USD kept at cost basis 10.00 USD\n' in page, page
    assert '\t\t\t\t\t\taccount: "Assets:USD kept at cost basis"\n' in page, page
    assert 'stored balance"' not in page and 'kept at stored balance' not in page, page
    assert '\t\t\t\tstored_balances:\n' in page, page


def test_a_split_of_0_00_usd_stores_0_00_in_each_currency(tmp_path):
    book = _book(tmp_path, HOLDS_100_USD, TO_AN_ACCOUNT_CALLED_COST_BASIS)
    out = tmp_path / 'exported.txt'
    assert _run(CliRunner(), 'export', str(book), str(out)).exit_code == 0
    split = re.search(r'^\tAssets:USD_A1 0\.00 USD\n((?:\t\t.*\n)*)', out.read_text(), re.M).group(1)
    assert '\t\tcurrency_amount.CAD: "0.00"\n' in split, split
    assert '\t\tcurrency_amount.CNY: "0.00"\n' in split, split
    assert '\t\tcurrency_amount.HKD: "0.00"\n' in split, split


BUYS_2_AMZN = 'u_2_buys_2_amzn_for_10_usd_at_1_40_cad_per_usd'


def _realized(book, as_of, currency='CAD'):
    """The balance sheet's realized gain on currency and its realized gain on shares."""
    page = _run(CliRunner(), 'balance-sheet', str(book), '--as-of', as_of, '--currency', currency)
    assert page.exit_code == 0, page.output
    fx = re.search(rf'^\trealized_gains_fx:(?: (-?[\d.]+) {currency}|\n\t\trealized_gains_fx: (-?[\d.]+))',
                   page.output, re.M)
    other = re.search(
        rf'^\trealized_gains_other:(?: (-?[\d.]+) {currency}|\n\t\trealized_gains_other: (-?[\d.]+))',
        page.output, re.M)
    return (fx.group(1) or fx.group(2)), (other.group(1) or other.group(2))


def test_10_usd_paying_for_2_shares_realizes_1_cad_on_the_us_dollars(tmp_path):
    """The US dollars are disposed of, in a book whose base currency is CAD, and the shares are not.

    USD_A gives up 10.00 USD, 13.00 CAD, 78.00 HKD and 60.00 CNY. The 2
    shares cost 14.00 CAD, and 10.00 USD, 78.50 HKD and 65.00 CNY at 7.85
    HKD/USD and 6.50 CNY/USD, with no price of the shares read. The file's
    `$residual$` split takes 1.00 CAD, 0.50 HKD and 5.00 CNY, a gain on
    currency.
    """
    book = _book(tmp_path, HOLDS_100_USD, BUYS_2_AMZN)
    balances = _balances(book)
    assert balances['Assets:USD_A'] == '90.00 USD, 117.00 CAD, 702.00 HKD, 540.00 CNY'
    assert balances['Assets:AMZN'] == '2.0000 AMZN, 14.00 CAD, 10.00 USD, 78.50 HKD, 65.00 CNY'
    assert balances['Income:FX Gain'] == '-1.00 CAD, 0.00 USD, -0.50 HKD, -5.00 CNY'
    assert _realized(book, '2030-02-01') == ('1.00', '0.00')


def test_1_share_that_cost_7_cad_sold_for_9_cad_realizes_2_cad_on_the_shares(tmp_path):
    """The share gives up half of what the AMZN account stores, and the gain is a gain on shares."""
    book = _book(tmp_path, HOLDS_100_USD, BUYS_2_AMZN, 'u_3_sells_1_amzn_that_cost_7_cad_for_9_cad')
    balances = _balances(book)
    assert balances['Assets:AMZN'] == '1.0000 AMZN, 7.00 CAD, 5.00 USD, 39.25 HKD, 32.50 CNY'
    assert balances['Assets:CAD_B'] == '9.00 CAD, 6.43 USD, 50.46 HKD, 41.79 CNY'
    assert balances['Income:FX Gain'] == '-3.00 CAD, -1.43 USD, -11.71 HKD, -14.29 CNY'
    assert _realized(book, '2030-03-01') == ('1.00', '2.00')


def test_1_share_and_10_usd_sold_in_one_transaction_state_each_its_own_gain(tmp_path):
    """One `$residual$` split of 4.00 CAD is 1.50 CAD on the US dollars and 2.50 CAD on the share.

    The share cost 7.00 CAD and the 10.00 USD store 13.00 CAD, and together
    they sell for 24.00 CAD. The 10.00 USD at the day's 1.45 CAD/USD are
    14.50 CAD, 1.50 CAD more than they store, which is what selling them
    alone would state. The other 2.50 CAD is the share's. With the 1.00 CAD
    the purchase of the shares realized on its US dollars, the sheet states
    2.50 CAD on currency and 2.50 CAD on shares.

    In USD the 10.00 USD are their own currency and gain nothing. The 24.00
    CAD are 16.55 USD at 1.45 CAD/USD, against the 10.00 USD and the 5.00 USD
    the share stores, so the split takes 1.55 USD and all of it is the
    share's.
    """
    book = _book(tmp_path, HOLDS_100_USD, BUYS_2_AMZN,
                 'u_3_sells_1_amzn_and_10_usd_together_for_24_cad_at_1_45_cad_per_usd')
    balances = _balances(book)
    assert balances['Income:FX Gain'].startswith('-5.00 CAD, -1.55 USD, ')
    assert balances['Assets:CAD_B'].startswith('24.00 CAD, 16.55 USD, ')
    assert _realized(book, '2030-03-01') == ('2.50', '2.50')
    assert _realized(book, '2030-03-01', 'USD') == ('0.00', '1.55')


A_GAIN_AS_AN_ORDINARY_SPLIT = ('u_2_exchanges_10_usd_for_14_cad_with_its_1_cad_gain_stated_as_an_'
                               'ordinary_split')


def test_a_gain_stated_as_an_ordinary_split_is_counted_once_its_account_is_passed(tmp_path):
    """A book written before `took_the_residual`: 10.00 USD storing 13.00 CAD exchanged for 14.00 CAD.

    The 1.00 CAD gain is an ordinary split with no mark. CAD_B's 14.00 CAD
    take what the US dollars stored, 78.00 HKD and 60.00 CNY, and the gain
    account stores nothing in them. The balance sheet states no realized gain
    until `--fx-gain-account` says where the gain is booked, and then 1.00 CAD.
    """
    book = _book(tmp_path, HOLDS_100_USD, A_GAIN_AS_AN_ORDINARY_SPLIT)
    balances = _balances(book)
    assert balances['Assets:CAD_B'] == '14.00 CAD, 10.00 USD, 78.00 HKD, 60.00 CNY'
    assert balances['Income:FX Gain'] == '-1.00 CAD, 0.00 USD, 0.00 HKD, 0.00 CNY'

    def realized(*more):
        page = _run(CliRunner(), 'balance-sheet', str(book), '--as-of', '2030-02-01',
                    '--currency', 'CAD', '--no-itemize', *more)
        assert page.exit_code == 0, page.output
        return re.search(r'^\trealized_gains_fx: (-?[\d.]+) CAD', page.output, re.M).group(1), page

    assert realized()[0] == '0.00'
    assert realized('--fx-gain-account', 'Income:FX Gain')[0] == '1.00'
    stated, page = realized('--fx-gain-account', 'Assets:CAD_B')
    assert stated == '0.00'
    assert ('--fx-gain-account "Assets:CAD_B" is not an income or expense account'
            in page.output), page.output


def test_fx_balances_as_of_a_date_lists_what_each_account_held_that_day(tmp_path):
    """The day before the transfer to USD_A1, USD_A holds all 100.00 USD and what they store."""
    book = _book(tmp_path, HOLDS_100_USD, TO_USD_A1)
    listing = _run(CliRunner(), 'fx-balances', str(book), '--as-of', '2030-01-31')
    assert listing.exit_code == 0, listing.output
    assert listing.output.splitlines()[1:] == [
        'As of 2030-01-31:',
        'Assets:USD_A: 100.00 USD, 130.00 CAD, 780.00 HKD, 600.00 CNY',
        'Equity:Opening Balances: -130.00 CAD, -100.00 USD, -780.00 HKD, -600.00 CNY',
    ]


def test_fx_balances_as_of_a_date_is_refused_for_a_book_selecting_no_currency(tmp_path):
    """A cost basis balance has no day to be read at, so `--as-of` is for a book that selected its currencies."""
    book = tmp_path / 'book.gnucash'
    first = FIXTURES / 'a_hong_kong_company_1_invoices_10000_usd_at_7_80_hkd_per_usd_and_collects_it_in_usd.txt'
    assert _run(CliRunner(), 'import', '--new', str(book), str(first),
                '--include-business-objects').exit_code == 0
    listing = _run(CliRunner(), 'fx-balances', str(book), '--as-of', '2026-03-31')
    assert listing.exit_code != 0
    assert ('--as-of lists what each account held on a day in every selected currency, and '
            'this book selects none') in listing.output, listing.output


def test_fx_balances_says_no_cost_was_checked(tmp_path):
    book = _book(tmp_path, HOLDS_100_USD, TO_USD_A1)
    listing = _run(CliRunner(), 'fx-balances', str(book), '--verify-costs')
    assert listing.exit_code == 0, listing.output
    assert listing.output.splitlines()[-1] == 'No cost was checked: this book records no cost basis.'


def test_a_book_using_gnucash_s_trading_accounts_stores_and_states_the_same(tmp_path):
    """U's book with "Use Trading Accounts" on: the same balances, and the same balance sheet in CAD and in HKD.

    GnuCash adds its own trading splits to each transaction that crosses
    currencies. They are no money moved, and store 0.00 in each currency.
    The page measures the gains from what the accounts store, as it does
    without trading accounts: 1.00 CAD realized and 9.00 CAD unrealized, and
    in HKD 785.00 HKD of assets, 0.50 HKD realized and 4.50 HKD unrealized.
    """
    from tests.integration.text_report_pages import a_book_using_trading_accounts

    book = a_book_using_trading_accounts(tmp_path, f'{HOLDS_100_USD}.txt')
    done = _run(CliRunner(), 'import', str(book),
                str(FIXTURES / 'u_2_transfers_10_usd_from_usd_a_to_cad_b_at_1_40_cad_per_usd.txt'))
    assert done.exit_code == 0 and 'Errors:       0' in done.output, done.output
    balances = _balances(book)
    assert balances['Assets:USD_A'] == '90.00 USD, 117.00 CAD, 702.00 HKD, 540.00 CNY'
    assert balances['Assets:CAD_B'] == '14.00 CAD, 10.00 USD, 78.50 HKD, 65.00 CNY'
    assert balances['Income:FX Gain'] == '-1.00 CAD, 0.00 USD, -0.50 HKD, -5.00 CNY'
    assert balances['Trading:CURRENCY:USD'] == '-90.00 USD, 0.00 CAD, 0.00 HKD, 0.00 CNY'
    for currency, assets, realized, unrealized in (('CAD', '140.00', '1.00', '9.00'),
                                                   ('HKD', '785.00', '0.50', '4.50')):
        page = _run(CliRunner(), 'balance-sheet', str(book), '--as-of', '2030-02-01',
                    '--currency', currency)
        assert page.exit_code == 0, page.output
        keys = dict(re.findall(rf'^\t([a-z_]+): (-?[\d.]+) {currency}', page.output, re.M))
        assert (keys['total_assets'], keys['total_liabilities_and_equity'],
                keys['total_realized_gains'], keys['total_unrealized_gains']) == (
                    assets, assets, realized, unrealized), page.output
        assert 'trading_gains' not in page.output, page.output
    # The income statement states the gain as it does without trading
    # accounts, and no section for the trading accounts.
    for currency, gain in (('CAD', '1.00'), ('HKD', '0.50')):
        page = _run(CliRunner(), 'income-statement', str(book), '--currency', currency,
                    '--start', '2030-01-01', '--end', '2030-12-31')
        assert page.exit_code == 0, page.output
        assert f'\tIncome:FX Gain {gain} {currency}\n' in page.output, page.output
        assert f'\tnet_income: {gain} {currency}' in page.output, page.output
        assert 'rading' not in page.output, page.output
    whole = _run(CliRunner(), '--verify-integrity', str(book))
    assert whole.exit_code == 0 and 'The book is consistent and balanced.' in whole.output, whole.output


def test_a_book_holding_shares_and_owing_usd_adds_up_to_zero_in_each_currency(tmp_path):
    """A book with shares priced in its price database, a USD loan and HKD selects CAD, USD and HKD."""
    book = _book(tmp_path, 'a_cad_book_with_usd_hkd_and_shares_priced_in_its_price_database',
                 'u_3_selects_cad_usd_and_hkd')
    totals = {}
    for held in _balances(book).values():
        for each in held.split(', '):
            amount, code = each.split(' ')
            totals[code] = totals.get(code, Fraction(0)) + Fraction(amount)
    assert {code: totals[code] for code in ('CAD', 'USD', 'HKD')} == {'CAD': 0, 'USD': 0, 'HKD': 0}


def test_the_balance_sheet_as_gnucash_ships_it_is_printed_in_a_selected_currency(tmp_path):
    book = _book(tmp_path, HOLDS_100_USD, TO_USD_A1)
    out = tmp_path / 'sheet.html'
    page = _run(CliRunner(), 'balance-sheet', str(book), '--as-of', '2030-02-01',
                '--currency', 'HKD', '--output-format', 'html', '--output', str(out))
    assert page.exit_code == 0, page.output
    assert '<html' in out.read_text() and '780.00' in out.read_text()


def test_the_books_own_export_is_up_to_date_when_imported_back(tmp_path):
    """The export states each split's amounts and each account's balances, and the book already holds them."""
    book = _book(tmp_path, HOLDS_100_USD, TO_USD_A1)
    out = tmp_path / 'exported.txt'
    assert _run(CliRunner(), 'export', str(book), str(out)).exit_code == 0
    exported = out.read_text()
    assert '\tcurrency_balance.CAD: "117.00"\n' in exported
    assert '\t\tcurrency_amount.HKD: "-78.00"\n' in exported
    again = _run(CliRunner(), 'import', str(book), str(out), '--strategy', 'update')
    assert again.exit_code == 0, again.output
    assert 'Up to date:   2 (no new changes, not edited)' in again.output, again.output
    assert 'Nothing to import' in again.output, again.output


def test_fx_balances_lists_the_accounts_of_one_currency(tmp_path):
    book = _book(tmp_path, HOLDS_100_USD, TO_USD_A1)
    assert sorted(_balances(book, '--currency', 'USD')) == ['Assets:USD_A', 'Assets:USD_A1']


def test_a_deleted_transfer_gives_usd_a_its_balances_back(tmp_path):
    """`delete-transactions` derives the balances again before it saves."""
    book = _book(tmp_path, HOLDS_100_USD, TO_USD_A1)
    done = _run(CliRunner(), 'delete-transactions', str(book), '--by-guid',
                '0d570000000000000000000000000002')
    assert done.exit_code == 0, done.output
    balances = _balances(book)
    assert balances['Assets:USD_A'] == '100.00 USD, 130.00 CAD, 780.00 HKD, 600.00 CNY'
    assert 'Assets:USD_A1' not in balances


def test_a_currency_selected_later_is_worked_out_from_the_first_transaction(tmp_path):
    """EUR added to the selection: USD_A's 90.00 USD store 81.00 EUR at 0.90 EUR/USD."""
    book = _book(tmp_path, HOLDS_100_USD, TO_USD_A1, 'u_3_selects_eur_too_at_0_90_eur_per_usd')
    balances = _balances(book)
    assert balances['Assets:USD_A'] == '90.00 USD, 117.00 CAD, 702.00 HKD, 540.00 CNY, 81.00 EUR'
    assert balances['Assets:USD_A1'] == '10.00 USD, 13.00 CAD, 78.00 HKD, 60.00 CNY, 9.00 EUR'


def test_a_currency_left_out_of_the_selection_later_is_no_longer_kept(tmp_path):
    book = _book(tmp_path, HOLDS_100_USD, TO_USD_A1, 'u_3_selects_cad_usd_and_hkd')
    assert _balances(book)['Assets:USD_A'] == '90.00 USD, 117.00 CAD, 702.00 HKD'
    out = tmp_path / 'exported.txt'
    assert _run(CliRunner(), 'export', str(book), str(out)).exit_code == 0
    assert 'currency_amount.CNY' not in out.read_text()


@pytest.mark.parametrize('line, said', [
    ('currency_balances: "CAD USD XYZ"',
     'currency_balances: "CAD USD XYZ" lists XYZ, and a book selects from '
     'USD, CAD, HKD, CNY, EUR, JPY, GBP, KRW'),
    ('currency_balances: "CAD USD USD"',
     'currency_balances: "CAD USD USD" lists a currency twice'),
    ('currency_balances: "USD HKD"',
     'currency_balances: "USD HKD" leaves out CAD, the book\'s base currency, '
     'which a realized gain is posted in'),
], ids=['a-currency-it-may-not-select', 'a-currency-twice', 'without-its-base-currency'])
def test_a_selection_the_book_cannot_be_kept_by_is_refused(tmp_path, line, said):
    book = _book(tmp_path, HOLDS_100_USD)
    done = _run(CliRunner(), 'import', str(book), _company(tmp_path, line))
    assert said in done.output, done.output
    assert _balances(book)['Assets:USD_A'] == '100.00 USD, 130.00 CAD, 780.00 HKD, 600.00 CNY'


def test_a_book_that_never_selected_any_may_state_none(tmp_path):
    """`currency_balances: $None$` on a book that keeps cost bases changes nothing."""
    book = tmp_path / 'book.gnucash'
    first = FIXTURES / 'a_hong_kong_company_1_invoices_10000_usd_at_7_80_hkd_per_usd_and_collects_it_in_usd.txt'
    assert _run(CliRunner(), 'import', '--new', str(book), str(first),
                '--include-business-objects').exit_code == 0
    done = _run(CliRunner(), 'import', str(book),
                _company(tmp_path, 'currency_balances: $None$'))
    assert done.exit_code == 0, done.output
    assert 'Assets:Accounts Receivable USD' in _run(CliRunner(), 'fx-balances', str(book)).output


def test_a_transaction_the_book_has_no_price_for_is_not_saved(tmp_path):
    """100.00 USD arrive in a book selecting HKD that has no price of USD in HKD."""
    book = _book(tmp_path, 'a_cad_book_selecting_cad_usd_and_hkd_that_holds_no_price')
    done = _run(CliRunner(), 'import', str(book),
                str(FIXTURES / 'a_cad_book_receives_100_usd_for_130_cad.txt'))
    assert done.exit_code == 1, done.output
    assert ('Nothing was saved: this book keeps a balance in each selected currency, '
            'and 1 transaction(s) cannot be given theirs: 2030-01-02 "The USD bank holds '
            '100.00 USD": the book has no price of USD in HKD, so what its splits move in '
            'each selected currency cannot be worked out. Add a price for that pair'
            ) in done.output, done.output
    assert _balances(book) == {}


def test_set_book_key_leaves_the_selection_to_the_company_block(tmp_path):
    book = _book(tmp_path, HOLDS_100_USD)
    done = _run(CliRunner(), 'set-book-key', str(book), '--key', 'currency_balances',
                '--value', 'CAD USD')
    assert done.exit_code != 0
    assert ("'currency_balances' is set in the `company` block, and the import that "
            "reads it derives every balance from the book's first transaction"
            ) in done.output, done.output


def test_verify_integrity_says_why_no_cost_basis_is_checked(tmp_path):
    book = _book(tmp_path, HOLDS_100_USD, TO_USD_A1)
    whole = _run(CliRunner(), '--verify-integrity', str(book))
    assert whole.exit_code == 0, whole.output
    assert ('this book keeps a balance in each of CAD, USD, HKD, CNY on every account, '
            'and records no cost basis (`currency_balances:` in its company block)'
            ) in whole.output, whole.output
