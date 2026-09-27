"""gnucash-plaintext keeps the order of the transactions in the plaintext file, and GnuCash keeps them in that order (Q-053).

GnuCash orders the transactions of one day by `num`, then the moment each was
entered, then the description, and an account's running balance follows that
order. The import entered every transaction at `datetime.now()`, so a run's
transactions shared a second and were ordered by description: a 10.00 USD
deposit and the transaction that has its 1.00 USD fee, imported in that
order, read as the fee first, Wise USD at -1.00 and then 9.00. An edit then
read the deposit as bringing in 9.00, the book's own export did not rebuild
it, and an edit restating the deposit as 11.00 read it as bringing in 10.00.

To keep the file's order, the import now enters the first transaction it
creates at the moment the import started, and each after it one second
later. What an account held before a transaction is read in GnuCash's order.
"""

import re
from datetime import timedelta
from pathlib import Path

from click.testing import CliRunner

from infrastructure.gnucash.utils import get_account_full_name
from repositories.gnucash_repository import GnuCashRepository, SessionMode
from tests.conftest import _run

FIXTURES = 'tests/fixtures/'
BASE = FIXTURES + 'a_usd_invoice_and_bill_for_statement_lines_on_a_holding_account.txt'
RATES = FIXTURES + 'usd_at_the_rates_the_statement_lines_records_were_posted_at.yaml'
LEDGER = FIXTURES + 'a_usd_deposit_and_its_fee_pending_its_cost_basis_the_same_day.txt'
SUPPLIES = FIXTURES + 'supplies_bought_with_usd_the_day_of_the_deposit_pending_its_cost_basis.txt'
SECOND_DEPOSIT = FIXTURES + 'a_second_usd_deposit_the_day_of_the_first_booked_as_income.txt'
DEPOSIT = '2026-08-13 * "Received money from a customer"'
FEE = '2026-08-13 * "Charges for the deposit"'


def _block(text, head):
    return re.search(rf'{re.escape(head)}\n(?:\t[^\n]*\n)*', text).group(0)


def _written(tmp_path, name, text):
    ledger = tmp_path / name
    ledger.write_text(text)
    return str(ledger)


def _book(tmp_path):
    book = tmp_path / 'book.gnucash'
    made = _run(CliRunner(), 'import', '--new', str(book), BASE,
                '--include-business-objects', '--fx-rates', RATES)
    assert made.exit_code == 0, made.output
    return book


def _imported(book, ledger, *more):
    done = _run(CliRunner(), 'import', str(book), ledger, '--fx-rates', RATES, *more)
    assert done.exit_code == 0 and 'Errors:       0' in done.output, done.output
    return done


def _exported(book, tmp_path):
    ledger = tmp_path / 'exported.txt'
    done = _run(CliRunner(), 'export', str(book), str(ledger), '--include-business-objects')
    assert done.exit_code == 0, done.output
    return ledger.read_text()


def _wise(book):
    """Each Wise USD split in GnuCash's order: its description, the moment it was entered, its running balance."""
    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        root = repo.book.get_root_account()
        wise = next(account for account in root.get_descendants()
                    if get_account_full_name(account) == 'Assets:Wise USD')
        return [(split.GetParent().GetDescription(), split.GetParent().GetDateEntered(),
                 str(split.GetBalance())) for split in wise.GetSplitList()]
    finally:
        repo.close()


def _fx_balances(book):
    listed = _run(CliRunner(), 'fx-balances', str(book), '--verify-costs')
    assert listed.exit_code == 0, listed.output
    return listed.output


def _the_deposit_row(output, usd):
    """The deposit's cost basis row: it brought in `usd`, and its balance is `usd`."""
    return re.search(rf'0e530000000000000000000000000d22\s+Assets:Wise USD\s+\S+ CAD/USD'
                     rf'\s+{re.escape(usd)} USD\s+{re.escape(usd)} USD', output)


def test_one_import_enters_its_transactions_a_second_apart_in_the_order_it_creates_them(tmp_path):
    book = _book(tmp_path)

    _imported(book, LEDGER)

    wise = _wise(book)
    assert [(description, balance) for description, _entered, balance in wise] == [
        ('Received money from a customer', '1000/100'), ('Charges for the deposit', '900/100')]
    assert wise[1][1] - wise[0][1] == timedelta(seconds=1)


def test_three_imports_of_one_day_keep_the_order_they_were_imported_in(tmp_path, import_clock):
    """The order of one day's transactions is kept across imports: the deposit and its fee, then supplies, then a second deposit, each file imported by a run of its own, stay in that order however the book is read after.

    Each run starts a second or more after the one before, as imports are
    run in use. Runs within the same second are ordered by `num`, in the test
    after this one.
    """
    book = _book(tmp_path)

    _imported(book, LEDGER)
    import_clock.tick()
    _imported(book, SUPPLIES)
    import_clock.tick()
    _imported(book, SECOND_DEPOSIT)

    expected = [('Received money from a customer', '1000/100'),
                ('Charges for the deposit', '900/100'),
                ('Supplies bought', '700/100'),
                ('Received money from another customer', '1200/100')]
    wise = _wise(book)
    assert [(description, balance) for description, _entered, balance in wise] == expected
    assert wise[0][1] < wise[1][1] < wise[2][1] < wise[3][1]
    # Read again, from the book as saved, it is the same order at the same moments.
    assert _wise(book) == wise
    exported = _exported(book, tmp_path)
    assert (exported.index(DEPOSIT) < exported.index(FEE)
            < exported.index('2026-08-13 * "Supplies bought"')
            < exported.index('2026-08-13 * "Received money from another customer"'))
    # An edit keeps each transaction's moment, so the order stays.
    deposit = _block(exported, DEPOSIT)
    _imported(book, _written(tmp_path, 'edit.txt', deposit.replace(
        '\tAssets:Due from director -13.00 CAD\n', '\tIncome:Sales -13.00 CAD\n')),
        '--strategy', 'update')
    assert _wise(book) == wise
    assert _the_deposit_row(_fx_balances(book), '10.00')


def test_three_imports_within_the_same_second_are_ordered_by_num(tmp_path):
    """Imports run one after another within the same second enter their transactions at the same second, so a `num` on each sets their order."""
    book = _book(tmp_path)
    numbered = (Path(LEDGER).read_text()
                .replace(DEPOSIT, '2026-08-13 * "1" "Received money from a customer"')
                .replace(FEE, '2026-08-13 * "2" "Charges for the deposit"'))
    supplies = Path(SUPPLIES).read_text().replace(
        '2026-08-13 * "Supplies bought"', '2026-08-13 * "3" "Supplies bought"')
    second = Path(SECOND_DEPOSIT).read_text().replace(
        '2026-08-13 * "Received money from another customer"',
        '2026-08-13 * "4" "Received money from another customer"')

    _imported(book, _written(tmp_path, 'numbered.txt', numbered))
    _imported(book, _written(tmp_path, 'supplies.txt', supplies))
    _imported(book, _written(tmp_path, 'second.txt', second))

    assert [(description, balance) for description, _entered, balance in _wise(book)] == [
        ('Received money from a customer', '1000/100'),
        ('Charges for the deposit', '900/100'),
        ('Supplies bought', '700/100'),
        ('Received money from another customer', '1200/100')]


def test_the_deposit_edited_to_income_still_brings_in_what_it_did_beside_a_pending_fee(tmp_path):
    """An edit that changes no figure of the deposit's US dollar split does not change what the deposit brought in: with its other side moved from Due from director to Income:Sales, it still brought in 10.00 USD at the same cost basis, and the fee is still pending."""
    book = _book(tmp_path)
    _imported(book, LEDGER)
    deposit = _block(_exported(book, tmp_path), DEPOSIT)
    edited = deposit.replace('\tAssets:Due from director -13.00 CAD\n', '\tIncome:Sales -13.00 CAD\n')
    assert edited != deposit

    _imported(book, _written(tmp_path, 'edit.txt', edited), '--strategy', 'update')

    listed = _fx_balances(book)
    assert _the_deposit_row(listed, '10.00'), listed
    assert '1 disposal(s) pending their cost basis: 1.00 USD.' in listed, listed


def test_the_deposit_restated_as_11_usd_brings_in_11(tmp_path):
    """An edit that changes the deposit's figure is read in GnuCash's order, where the deposit comes before the fee: restated as 11.00 USD for 14.30 CAD, it brings in 11.00."""
    book = _book(tmp_path)
    _imported(book, LEDGER)
    deposit = _block(_exported(book, tmp_path), DEPOSIT)
    edited = (deposit.replace('\tAssets:Wise USD 10.00 USD\n', '\tAssets:Wise USD 11.00 USD\n')
              .replace('-13.00 CAD', '-14.30 CAD').replace('"1000/1300"', '"1100/1430"')
              .replace('value: "-10.00"', 'value: "-11.00"'))

    _imported(book, _written(tmp_path, 'edit.txt', edited), '--strategy', 'update')

    listed = _fx_balances(book)
    assert _the_deposit_row(listed, '11.00'), listed


def test_the_book_is_rebuilt_from_its_own_export(tmp_path):
    """A book is rebuilt from its own export: the export writes the deposit above the fee's transaction, in GnuCash's order, so the fee disposes of dollars Wise holds."""
    book = _book(tmp_path)
    _imported(book, LEDGER)
    exported = _exported(book, tmp_path)
    assert exported.index(DEPOSIT) < exported.index(FEE)

    rebuilt = tmp_path / 'rebuilt.gnucash'
    done = _run(CliRunner(), 'import', '--new', str(rebuilt),
                _written(tmp_path, 'whole.txt', exported), '--include-business-objects')

    assert done.exit_code == 0 and 'Errors:       0' in done.output, done.output
    # The same rows and totals; the rebuilt book lists its cost bases in the
    # order it created them, which is the export's.
    assert sorted(_fx_balances(rebuilt).splitlines()) == sorted(_fx_balances(book).splitlines())


def test_the_fee_s_transaction_numbered_before_the_deposit_s_comes_first(tmp_path):
    """A `num` in the file decides the order before the moment entered does: with `num` 1 on the fee's transaction and `num` 2 on the deposit's, the fee comes first, and disposes of dollars Wise does not hold yet."""
    book = _book(tmp_path)
    numbered = (Path(LEDGER).read_text()
                .replace(DEPOSIT, '2026-08-13 * "2" "Received money from a customer"')
                .replace(FEE, '2026-08-13 * "1" "Charges for the deposit"'))

    done = _run(CliRunner(), 'import', str(book), _written(tmp_path, 'numbered.txt', numbered),
                '--fx-rates', RATES)

    assert ('Charges for the deposit: the split on Assets:Wise USD has '
            '`cost_basis_split_guid: $pending$`, but it disposes of nothing the book holds '
            'or owes.') in done.output, done.output
