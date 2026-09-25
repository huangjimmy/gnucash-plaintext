"""A book can keep no cost bases (Q-049).

Cost bases are gnucash-plaintext's, not GnuCash's: GnuCash asks no one which
lot a dollar came out of. A book whose `company` block says
`cost_bases: "off"` keeps its foreign currency as GnuCash does. The import
neither checks cost bases nor records them, a file stating a cost basis key is
refused, the realized gains are what the transactions record, and the balance
sheet measures unrealized gains from GnuCash's own revaluation.
"""

import re

from click.testing import CliRunner

from cli.main import cli
from tests.conftest import _run

FIXTURES = 'tests/fixtures/'
BASE = FIXTURES + 'a_usd_invoice_and_bill_for_statement_lines_on_a_holding_account.txt'
RATES = FIXTURES + 'usd_at_the_rates_the_statement_lines_records_were_posted_at.yaml'
OFF = FIXTURES + 'a_company_that_keeps_no_cost_bases.txt'
DOLLARS = FIXTURES + 'usd_bought_into_wise_before_the_statement.txt'
SPENT = FIXTURES + 'usd_spent_on_a_fee_and_sold_giving_no_cost_basis.txt'
DEPOSIT = FIXTURES + 'a_usd_deposit_and_its_fee_on_a_holding_account.txt'


def _imported(book, ledger, *flags):
    return _run(CliRunner(), 'import', str(book), ledger, '--fx-rates', RATES, *flags)


def _accepted(done):
    assert done.exit_code == 0 and 'Errors:       0' in done.output, done.output


def _book(tmp_path, *ledgers, off=True):
    """A book kept with no cost bases from the start where `off`, then the base ledger, then each ledger.

    Off from the start, so the invoices and bills are posted into a book that
    keeps none.
    """
    book = tmp_path / 'book.gnucash'
    made = _run(CliRunner(), 'import', '--new', str(book), OFF if off else BASE,
                '--include-business-objects', '--fx-rates', RATES)
    assert made.exit_code == 0, made.output
    if off:
        _accepted(_imported(book, BASE, '--include-business-objects'))
    for ledger in ledgers:
        _accepted(_imported(book, ledger))
    return book


def _without_comments(path):
    return ''.join(line for line in open(path).read().splitlines(keepends=True)
                   if not line.startswith('#'))


def _exported(book, tmp_path):
    ledger = tmp_path / 'exported.txt'
    done = _run(CliRunner(), 'export', str(book), str(ledger), '--include-business-objects')
    assert done.exit_code == 0, done.output
    return ledger.read_text()


def test_a_spend_that_gives_no_cost_basis_is_accepted(tmp_path):
    book = _book(tmp_path, DOLLARS)

    _accepted(_imported(book, SPENT))


def test_a_book_keeping_cost_bases_refuses_the_same_spend(tmp_path):
    book = _book(tmp_path, DOLLARS, off=False)

    done = _imported(book, SPENT)

    assert done.exit_code != 0, done.output


def test_nothing_is_recorded(tmp_path):
    book = _book(tmp_path, DOLLARS, SPENT)

    assert 'cost_basis_' not in _exported(book, tmp_path)


def test_dollars_paid_in_dollars_record_no_cost(tmp_path):
    """A USD advance into a USD account: a book keeping cost bases records its cost on the split."""
    book = _book(tmp_path, FIXTURES + 'a_usd_advance_parked_as_the_customers_credit.txt')

    assert 'cost_basis_' not in _exported(book, tmp_path)


def test_a_disposal_restated_in_place_is_edited(tmp_path):
    book = _book(tmp_path, DOLLARS, SPENT)
    exported = _exported(book, tmp_path)
    fee = exported[exported.index('2026-08-20 * "Transfer fee"'):]
    guids = re.findall(r'guid: "([0-9a-f]{32})"', fee)[:3]
    edit = tmp_path / 'edit.txt'
    edit.write_text(_without_comments(
        FIXTURES + 'usd_spent_on_a_fee_restated_at_another_value.txt').format(
        fee=guids[0], charge=guids[1], spent=guids[2]))

    done = _imported(book, str(edit), '--strategy', 'update')

    _accepted(done)
    assert 'Updated:      1' in done.output
    edited = _exported(book, tmp_path)
    assert 'Assets:Wise USD -0.80 USD' in edited and 'value: "-1.12"' in edited
    assert 'cost_basis_' not in edited


def test_a_deposit_and_its_fee_are_edited_as_they_were_created(tmp_path):
    """An arrival and a spend giving no cost basis in one transaction: created, and then edited, with nothing asked about cost bases either time."""
    book = _book(tmp_path, FIXTURES + 'a_usd_deposit_and_its_fee_giving_no_cost_basis.txt')
    exported = _exported(book, tmp_path)
    edit = tmp_path / 'edit.txt'
    edit.write_text(exported.replace('"Received money from Example Customer Inc"',
                                     '"Received from Example Customer Inc, less the fee"'))

    done = _imported(book, str(edit), '--strategy', 'update')

    _accepted(done)
    assert 'Received from Example Customer Inc, less the fee' in _exported(book, tmp_path)


def test_an_overpaid_invoice_leaves_a_credit_with_no_cost(tmp_path):
    book = _book(tmp_path)

    done = _imported(book, FIXTURES + 'inv_usd_1_overpaid_in_us_dollars.txt',
                     '--include-business-objects')

    _accepted(done)
    assert 'cost_basis_' not in _exported(book, tmp_path)


def test_the_company_block_imported_again_changes_nothing(tmp_path):
    book = _book(tmp_path)

    done = _imported(book, OFF, '--include-business-objects')

    _accepted(done)
    assert 'company "Example Books Inc": unchanged' in done.output


def test_on_keeps_them(tmp_path):
    book = _book(tmp_path, DEPOSIT, off=False)

    done = _imported(book, FIXTURES + 'a_company_that_keeps_cost_bases.txt',
                     '--include-business-objects')

    _accepted(done)
    assert 'cost_basis_balance' in _exported(book, tmp_path)


def test_a_book_that_keeps_none_is_not_turned_on_in_place(tmp_path):
    book = _book(tmp_path)
    on_disk = book.read_bytes()

    done = _imported(book, FIXTURES + 'a_company_that_keeps_cost_bases.txt',
                     '--include-business-objects')

    assert done.exit_code != 0, done.output
    assert 'turning them on in place' in done.output
    assert book.read_bytes() == on_disk


def test_a_residual_beside_a_purchase_is_the_realized_difference_the_file_states(tmp_path):
    """A realized gain is recorded, not worked out: the file states it, whichever way the USD split moves."""
    book = _book(tmp_path, FIXTURES + 'usd_bought_with_a_fee_taken_as_the_residual.txt')

    assert 'realized_gains_fx: -3.00' in _sheet(book)


def test_a_dry_run_turning_them_off_leaves_the_book_keeping_them(tmp_path):
    """Nothing about a book outlives the run that did not save it, in one process."""
    book = _book(tmp_path, DOLLARS, off=False)
    _accepted(_imported(book, OFF, '--include-business-objects', '--dry-run'))

    done = _imported(book, SPENT)

    assert done.exit_code != 0, done.output


def test_a_share_sale_s_realized_gain_is_what_the_transaction_records(tmp_path):
    book = _book(tmp_path, FIXTURES + 'shares_bought_and_sold_giving_no_cost_basis.txt')

    assert 'realized_gains_other: 200.00 CAD' in _sheet(book)


LINKED = FIXTURES + 'a_usd_deposit_on_the_receivable_and_inv_usd_1_paid_by_it.txt'


def test_unlink_writes_no_cost_basis_key(tmp_path):
    book = _book(tmp_path)
    _accepted(_imported(book, LINKED, '--include-business-objects'))

    done = _run(CliRunner(), 'unlink', str(book), 'INV-USD-1', '--to', 'Assets:Due from director')

    assert done.exit_code == 0, done.output
    assert 'cost_basis_' not in _exported(book, tmp_path)


def test_unapply_payment_writes_no_cost_basis_key(tmp_path):
    book = _book(tmp_path)
    _accepted(_imported(book, LINKED, '--include-business-objects'))

    done = _run(CliRunner(), 'unapply-payment', str(book), 'INV-USD-1',
                '--to', 'Assets:Accounts Receivable USD')

    assert done.exit_code == 0, done.output
    assert 'cost_basis_' not in _exported(book, tmp_path)


def test_delete_transactions_deletes_what_spends_dollars_giving_no_cost_basis(tmp_path):
    """The dollars the fee and the sale spent are deleted, where a book keeping cost bases refuses while a disposal draws on them; the book holds nothing to give back."""
    book = _book(tmp_path, DOLLARS, SPENT)

    done = _run(CliRunner(), 'delete-transactions', str(book), '--by-guid',
                '0e510000000000000000000000000d01')

    assert done.exit_code == 0, done.output
    assert 'cost_basis_' not in _exported(book, tmp_path)


def test_a_file_stating_a_cost_basis_key_is_refused(tmp_path):
    book = _book(tmp_path)

    done = _imported(book, DEPOSIT)

    assert done.exit_code != 0, done.output
    assert 'states cost_basis_split_guid:, and this book keeps no cost bases' in done.output


def test_turning_them_off_clears_the_ones_the_book_held(tmp_path):
    book = _book(tmp_path, DEPOSIT, off=False)
    assert 'cost_basis_balance' in _exported(book, tmp_path)

    done = _imported(book, OFF, '--include-business-objects')

    _accepted(done)
    assert 'this book keeps no cost bases now' in done.output
    assert 'cost_basis_' not in _exported(book, tmp_path)


def test_a_setting_that_is_neither_on_nor_off_is_refused(tmp_path):
    book = _book(tmp_path)

    done = _imported(book, FIXTURES + 'a_company_whose_cost_bases_setting_is_neither_on_nor_off.txt',
                     '--include-business-objects')

    assert done.exit_code != 0, done.output
    assert 'cost_bases: "sometimes" is neither "on" nor "off"' in done.output


def test_set_book_key_leaves_it_to_the_company_block(tmp_path):
    book = _book(tmp_path, off=False)

    done = _run(CliRunner(), 'set-book-key', str(book), '--key', 'cost_bases', '--value', 'off')

    assert done.exit_code != 0, done.output
    assert 'is set in the `company` block' in done.output


def _sheet(book):
    drawn = _run(CliRunner(), 'balance-sheet', str(book), '--as-of', '2026-12-31',
                 '--fx-rates', RATES)
    assert drawn.exit_code == 0, drawn.output
    return drawn.output


def test_the_export_rebuilds_the_book_in_a_new_one(tmp_path):
    """With `--include-business-objects`, which imports the `company` block turning cost bases off before the spends that give none."""
    book = _book(tmp_path, DOLLARS, SPENT)
    exported = tmp_path / 'whole.txt'
    written = _run(CliRunner(), 'export', str(book), str(exported), '--include-business-objects')
    assert written.exit_code == 0, written.output
    rebuilt = tmp_path / 'rebuilt.gnucash'

    done = _run(CliRunner(), 'import', '--new', str(rebuilt), str(exported),
                '--include-business-objects')

    _accepted(done)
    assert 'realized_gains_fx: 50.00' in _sheet(rebuilt)
    assert 'cost_basis_' not in _exported(rebuilt, tmp_path)


def test_the_realized_gain_is_what_the_transactions_record(tmp_path):
    book = _book(tmp_path, DOLLARS, SPENT)

    assert 'realized_gains_fx: 50.00' in _sheet(book)


def test_the_unrealized_gain_is_measured_from_gnucash_s_revaluation(tmp_path):
    book = _book(tmp_path, DOLLARS, SPENT)

    assert ('measured_from: gnucash_revaluation # this book keeps no cost bases'
            in _sheet(book))


def test_fx_balances_says_so_and_lists_what_the_accounts_hold(tmp_path):
    book = _book(tmp_path, DOLLARS, SPENT)

    listed = _run(CliRunner(), 'fx-balances', str(book), '--verify-costs')

    assert listed.exit_code == 0, listed.output
    assert 'This book keeps no cost bases' in listed.output
    assert 'Assets:Wise USD' in listed.output and '999.28 USD' in listed.output


def test_verify_integrity_lists_the_cost_basis_checks_as_not_checked(tmp_path):
    book = _book(tmp_path, DOLLARS, SPENT)

    checked = CliRunner().invoke(cli, ['--verify-integrity', str(book)])

    assert ('not checked: every cost basis agrees with the ledger it comes from: '
            'this book keeps no cost bases') in checked.output
