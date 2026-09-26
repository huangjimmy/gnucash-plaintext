"""A transaction in the file with a guid not in the book is a new transaction, however like a transaction in the book it is (Q-053).

The book holds a 10.00 USD deposit on 2026-08-13, between Wise USD and Due
from director. The transaction that has its 1.00 USD fee is on the same date
and the same two accounts. The duplicate check compares only those, so the
fee's transaction was skipped as a copy of the deposit, with `Errors: 0`,
even when its guid was one no transaction in the book has. A guid says which
transaction a block is. The duplicate check is for a block without one.
"""

import re
from pathlib import Path

from click.testing import CliRunner

from tests.conftest import _run

FIXTURES = 'tests/fixtures/'
BASE = FIXTURES + 'a_usd_invoice_and_bill_for_statement_lines_on_a_holding_account.txt'
RATES = FIXTURES + 'usd_at_the_rates_the_statement_lines_records_were_posted_at.yaml'
LEDGER = FIXTURES + 'a_usd_deposit_and_its_fee_pending_its_cost_basis_the_same_day.txt'
DEPOSIT = '2026-08-13 * "Received money from a customer"'
FEE = '2026-08-13 * "Charges for the deposit"'
NEW_GUID = '0e530000000000000000000000000fee'


def _block(text, head):
    return re.search(rf'{re.escape(head)}\n(?:\t[^\n]*\n)*', text).group(0)


def _with_a_guid(block, head, guid):
    return block.replace(head + '\n', f'{head}\n\tguid: "{guid}"\n')


def _exported(book, tmp_path):
    ledger = tmp_path / 'exported.txt'
    done = _run(CliRunner(), 'export', str(book), str(ledger))
    assert done.exit_code == 0, done.output
    return ledger.read_text()


def _the_book_with_the_deposit(tmp_path, import_clock):
    book = tmp_path / 'book.gnucash'
    made = _run(CliRunner(), 'import', '--new', str(book), BASE,
                '--include-business-objects', '--fx-rates', RATES)
    assert made.exit_code == 0, made.output
    deposit = tmp_path / 'deposit.txt'
    deposit.write_text(_block(Path(LEDGER).read_text(), DEPOSIT))
    done = _run(CliRunner(), 'import', str(book), str(deposit), '--fx-rates', RATES)
    assert done.exit_code == 0 and 'Transactions: 1' in done.output, done.output
    # The next import starts a second or more later, as imports are run in
    # use, so its transactions are entered after the deposit and come after
    # it on the same day.
    import_clock.tick()
    return book


def _imported(book, tmp_path, text):
    ledger = tmp_path / 'ledger.txt'
    ledger.write_text(text)
    done = _run(CliRunner(), 'import', str(book), str(ledger), '--fx-rates', RATES)
    assert done.exit_code == 0 and 'Errors:       0' in done.output, done.output
    return done


def _the_fee():
    return _block(Path(LEDGER).read_text(), FEE)


def test_the_fee_s_transaction_with_a_guid_not_in_the_book_is_created(tmp_path, import_clock):
    book = _the_book_with_the_deposit(tmp_path, import_clock)

    done = _imported(book, tmp_path, _with_a_guid(_the_fee(), FEE, NEW_GUID))

    assert 'Transactions: 1' in done.output and 'Skipped:      0' in done.output, done.output
    assert f'{FEE}\n\tguid: "{NEW_GUID}"\n' in _exported(book, tmp_path)


def test_a_copy_of_the_deposit_with_a_guid_not_in_the_book_is_created(tmp_path, import_clock):
    """The copy has the deposit's date, accounts, amounts and description. Its splits have no guid, because a split guid belongs to one split."""
    book = _the_book_with_the_deposit(tmp_path, import_clock)
    deposit = _block(_exported(book, tmp_path), DEPOSIT)
    copy = re.sub(r'\n\t+guid: "[0-9a-f]{32}"', '', deposit)
    assert 'guid:' not in copy

    done = _imported(book, tmp_path, _with_a_guid(copy, DEPOSIT, NEW_GUID))

    assert 'Transactions: 1' in done.output and 'Skipped:      0' in done.output, done.output
    exported = _exported(book, tmp_path)
    assert exported.count(DEPOSIT) == 2
    assert f'{DEPOSIT}\n\tguid: "{NEW_GUID}"\n' in exported


def test_the_fee_s_transaction_without_a_guid_whose_splits_have_guids_not_in_the_book_is_skipped(
        tmp_path, import_clock):
    """Only the transaction's own guid decides that it is new. Without one, the duplicate check matches it to the deposit, as Q-050 E19 relies on, though no split in the book has its splits' guids."""
    book = _the_book_with_the_deposit(tmp_path, import_clock)
    fee = (_the_fee()
           .replace('\tAssets:Wise USD -1.00 USD\n',
                    '\tAssets:Wise USD -1.00 USD\n\t\tguid: "0e530000000000000000000000000f01"\n')
           .replace('\tAssets:Due from director 1.40 CAD\n',
                    '\tAssets:Due from director 1.40 CAD\n\t\tguid: "0e530000000000000000000000000f02"\n'))

    done = _imported(book, tmp_path, fee)

    assert 'Transactions: 0' in done.output and 'Skipped:      1' in done.output, done.output
    assert FEE not in _exported(book, tmp_path)


def test_the_fee_s_transaction_with_the_deposit_s_guid_is_skipped(tmp_path, import_clock):
    """With the deposit's guid the block is the deposit, and the default strategy leaves the deposit as the book holds it."""
    book = _the_book_with_the_deposit(tmp_path, import_clock)
    held = re.search(rf'{re.escape(DEPOSIT)}\n\tguid: "([0-9a-f]{{32}})"',
                     _exported(book, tmp_path)).group(1)

    done = _imported(book, tmp_path, _with_a_guid(_the_fee(), FEE, held))

    assert 'Transactions: 0' in done.output and 'Skipped:      1' in done.output, done.output
    assert FEE not in _exported(book, tmp_path)


def test_the_fee_s_transaction_without_a_guid_is_skipped_as_a_copy_of_the_deposit(
        tmp_path, import_clock):
    """The duplicate check compares the date and the accounts and not the amounts, as README states."""
    book = _the_book_with_the_deposit(tmp_path, import_clock)

    done = _imported(book, tmp_path, _the_fee())

    assert 'Transactions: 0' in done.output and 'Skipped:      1' in done.output, done.output
    assert FEE not in _exported(book, tmp_path)


def test_the_fee_s_transaction_with_an_empty_guid_is_skipped_as_a_copy_of_the_deposit(
        tmp_path, import_clock):
    """`guid: ""` states no guid, so the block is matched by signature as one without a `guid:` line is."""
    book = _the_book_with_the_deposit(tmp_path, import_clock)

    done = _imported(book, tmp_path, _with_a_guid(_the_fee(), FEE, ''))

    assert 'Transactions: 0' in done.output and 'Skipped:      1' in done.output, done.output
    assert FEE not in _exported(book, tmp_path)
