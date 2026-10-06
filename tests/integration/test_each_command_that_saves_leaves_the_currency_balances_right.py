"""The commands that change a book keeping a balance in each selected currency, beyond `import` (Q-057).

Each derives every balance again before it saves. The book is ACMU's of
`tests/scenario/test_acmu_migrates_from_cost_bases_after_five_years.py`,
after its migration: Chase Chequing holds 4,898.34 USD storing 6,254.11 CAD,
Wise EUR 800.00 EUR storing 1,048.80 CAD, RBC Chequing 3,944.80 CAD, and the
receivable INV-ABC-4's 1,000.00 USD storing 1,350.40 CAD. On 2024-12-31, at
1.4389 CAD/USD and 1.4928 CAD/EUR, its sheet in CAD states 13,626.16 CAD of
assets.
"""

import re
from pathlib import Path

from click.testing import CliRunner

from tests.conftest import _run

FIXTURES = Path('tests/fixtures')
MIGRATED = (
    'acmu_1_opens_with_1000_usd_that_cost_1298_80_cad_on_2020_01_01',
    'acmu_2_invoices_abc_1000_usd_at_1_2732_cad_per_usd_and_abc_europe_1000_eur_at_1_5608_cad_per_eur_'
    'and_is_paid_in_full',
    'acmu_3_sells_1000_eur_that_cost_1560_80_cad_for_1223_34_usd_worth_1472_90_cad_on_2021_06_01',
    'acmu_4_bank_of_canada_rates_from_2021_06_30_to_2024_12_31',
    'acmu_4_trades_from_2021_07_to_2024_12_with_cost_bases',
    'acmu_5_selects_cad_usd_cny_hkd_eur_and_gbp',
)


def _acmu(tmp_path):
    book = tmp_path / 'book.gnucash'
    for number, step in enumerate(MIGRATED):
        args = ['import', str(book), str(FIXTURES / f'{step}.txt'), '--include-business-objects']
        if number == 0:
            args.insert(1, '--new')
        done = _run(CliRunner(), *args)
        assert done.exit_code == 0 and 'Errors:       0' in done.output, done.output
    return book


def _balances(book):
    listing = _run(CliRunner(), 'fx-balances', str(book))
    assert listing.exit_code == 0, listing.output
    return dict(line.split(': ', 1) for line in listing.output.splitlines()[1:])


def _sheet(book):
    """The balance sheet in CAD on 2024-12-31, by key."""
    page = _run(CliRunner(), 'balance-sheet', str(book), '--as-of', '2024-12-31', '--currency', 'CAD')
    assert page.exit_code == 0, page.output
    return dict(re.findall(r'^\t([a-z_]+): (-?[\d.]+) CAD', page.output, re.M))


def _is_consistent_and_balanced(book):
    whole = _run(CliRunner(), '--verify-integrity', str(book))
    assert whole.exit_code == 0 and 'The book is consistent and balanced.' in whole.output, whole.output


def test_unposting_the_unpaid_invoice_takes_its_1000_usd_off_the_receivable(tmp_path):
    """`unpost-invoices INV-ABC-4`: the receivable holds nothing, and the sales are 1,350.40 CAD less.

    The sheet then states 12,187.26 CAD of assets: 4,898.34 USD worth
    7,048.22 CAD, 800.00 EUR worth 1,194.24 CAD, and 3,944.80 CAD. Retained
    earnings are 9,948.91 CAD, and 939.55 CAD is unrealized.
    """
    book = _acmu(tmp_path)
    done = _run(CliRunner(), 'unpost-invoices', str(book), 'INV-ABC-4')
    assert done.exit_code == 0 and 'unposted' in done.output, done.output
    balances = _balances(book)
    assert 'Assets:Accounts Receivable USD' not in balances
    assert balances['Assets:Chase Chequing'].startswith('4898.34 USD, 6254.11 CAD, ')
    assert balances['Income:Sales'].startswith('-11014.40 CAD, -8504.29 USD, ')
    sheet = _sheet(book)
    assert (sheet['total_assets'], sheet['total_liabilities_and_equity'], sheet['retained_earnings'],
            sheet['total_unrealized_gains']) == ('12187.26', '12187.26', '9948.91', '939.55')
    _is_consistent_and_balanced(book)


def test_unapplying_a_payment_leaves_an_invoice_held_beside_a_credit_owed(tmp_path):
    """`unapply-payment INV-ABC-3`: 1,500.00 USD are owing again, and the 1,500.00 USD paid are the customer's credit.

    No money moved, so every account stores what it stored and the sheet
    states the same 13,626.16 CAD of assets and 1,028.05 CAD unrealized. The
    receivable is on both sides: 2,500.00 USD held, the two unpaid invoices,
    and 1,500.00 USD owed back. The credit stores the 2,037.00 CAD it was
    paid at and is worth 2,158.35 CAD at 1.4389 CAD/USD, so the owed side
    states a loss of 121.35 CAD.
    """
    book = _acmu(tmp_path)
    before = _balances(book)
    done = _run(CliRunner(), 'unapply-payment', str(book), 'INV-ABC-3',
                '--to', 'Assets:Accounts Receivable USD')
    assert done.exit_code == 0 and 'unapplied 1 payment' in done.output, done.output
    assert _balances(book) == before
    sheet = _sheet(book)
    assert (sheet['total_assets'], sheet['total_liabilities_and_equity'], sheet['retained_earnings'],
            sheet['total_realized_gains'], sheet['total_unrealized_gains']) == (
                '13626.16', '13626.16', '11299.31', '37.69', '1028.05')
    assert sheet['unrealized_gains_liabilities_fx'] == '-121.35'
    _is_consistent_and_balanced(book)


def test_fx_balances_verify_costs_on_the_migrated_book_says_no_cost_was_checked(tmp_path):
    """The book holds the eight cost bases it recorded before, and checks none of them now."""
    listing = _run(CliRunner(), 'fx-balances', str(_acmu(tmp_path)), '--verify-costs')
    assert listing.exit_code == 0, listing.output
    assert listing.output.splitlines()[-1] == 'No cost was checked: this book records no cost basis.'


def test_a_deletion_that_leaves_a_transaction_with_no_price_is_refused_and_saves_nothing(tmp_path):
    """50.00 of 100.00 USD bought 45.00 EUR, in a book with no price of the euro; the 100.00 USD are then deleted.

    With the US dollars in the account, the euros arrive at the day's
    amounts of the dollars that paid for them, and no price of the euro is
    read. With their arrival deleted, the account held no dollars to pay
    with, and the euros can only be given the day's amounts of their own
    currency, which the book has no price of. `delete-transactions` refuses,
    and the book is as it was.
    """
    book = tmp_path / 'book.gnucash'
    done = _run(CliRunner(), 'import', '--new', str(book), str(
        FIXTURES / 'a_cad_book_selecting_cad_usd_and_hkd_buys_45_eur_with_50_of_the_100_usd_it_received.txt'))
    assert done.exit_code == 0 and 'Errors:       0' in done.output, done.output
    before = _balances(book)
    assert before['Assets:EUR Bank'] == '45.00 EUR, 63.00 CAD, 50.00 USD, 390.00 HKD'

    deleted = _run(CliRunner(), 'delete-transactions', str(book), '--by-guid',
                   '0d570000000000000000000000000150')
    assert deleted.exit_code == 1, deleted.output
    assert ('Error: Failed to save: Nothing was saved: this book keeps a balance in each selected '
            'currency, and 1 transaction(s) cannot be given theirs: 2030-02-01 "Buy 45.00 EUR with '
            '50.00 USD": the book has no price of EUR in USD') in deleted.output, deleted.output
    assert _balances(book) == before
