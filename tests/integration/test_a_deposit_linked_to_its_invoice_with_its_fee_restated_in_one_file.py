"""A deposit linked to the invoice it collected, its fee a transaction of its own, in one `--atomic` file (Q-053).

The bank writes the deposit and its fee as two transactions stated in US
dollars, the fee drawing on the deposit's cost basis. An application links
the deposit to the invoice with the invoice's `payment:` block, giving the
deposit's transaction and the bank account. Once the deposit pays the
invoice, its dollars are the invoice's collected dollars, and the fee has to
draw on the invoice's cost basis: the file gives that, restating the fee.
"""

import re

from click.testing import CliRunner

from tests.conftest import _run

FIXTURES = 'tests/fixtures/'
BASE = FIXTURES + 'a_usd_invoice_and_bill_for_statement_lines_on_a_holding_account.txt'
RATES = FIXTURES + 'usd_at_the_rates_the_statement_lines_records_were_posted_at.yaml'
STATEMENT = FIXTURES + 'a_usd_deposit_and_its_fee_stated_in_usd_as_two_transactions.txt'
LINK = FIXTURES + 'inv_usd_1_paid_by_linking_the_deposit.txt'
FEE_HEAD = '2026-08-13 * "Charges for the deposit"'


def _book(tmp_path):
    book = tmp_path / 'book.gnucash'
    made = _run(CliRunner(), 'import', '--new', str(book), BASE,
                '--include-business-objects', '--fx-rates', RATES)
    assert made.exit_code == 0, made.output
    done = _run(CliRunner(), 'import', str(book), STATEMENT, '--fx-rates', RATES)
    assert done.exit_code == 0 and 'Errors:       0' in done.output, done.output
    return book


def _exported(book, tmp_path):
    ledger = tmp_path / 'exported.txt'
    done = _run(CliRunner(), 'export', str(book), str(ledger), '--include-business-objects')
    assert done.exit_code == 0, done.output
    return ledger.read_text()


def _block(text, head):
    return re.search(rf'{re.escape(head)}\n(?:\t[^\n]*\n)*', text).group(0)


def _without_comments(path):
    return ''.join(line for line in open(path).read().splitlines(keepends=True)
                   if not line.startswith('#'))


def _the_invoice_s_posting_split(text):
    return re.search(r'Accounts Receivable USD 2720\.00 USD\n'
                     r'\t+guid: "([0-9a-f]{32})"', text).group(1)


def _import(book, tmp_path, text):
    ledger = tmp_path / 'link.txt'
    ledger.write_text(text)
    return _run(CliRunner(), 'import', str(book), str(ledger), '--strategy', 'update',
                '--include-business-objects', '--fx-rates', RATES, '--atomic')


def test_the_link_alone_is_refused_saying_to_restate_the_fee_in_the_same_file(tmp_path):
    book = _book(tmp_path)
    on_disk = book.read_bytes()

    done = _import(book, tmp_path, _without_comments(LINK))

    assert done.exit_code != 0, done.output
    assert "restate them in this file, drawing on the record's cost basis" in done.output
    assert book.read_bytes() == on_disk


def test_the_link_and_the_fee_restated_giving_no_cost_basis_are_refused(tmp_path):
    """The fee keeps its US dollar split and gives no cost basis: it is a spend refused for that, and the whole file with it."""
    book = _book(tmp_path)
    fee = _block(_exported(book, tmp_path), FEE_HEAD)
    giving_none = ''.join(line + '\n' for line in fee.splitlines()
                          if 'cost_basis_split_guid' not in line)
    on_disk = book.read_bytes()

    done = _import(book, tmp_path, _without_comments(LINK) + '\n' + giving_none)

    assert done.exit_code != 0, done.output
    assert '✗ Rolled back' in done.output
    assert book.read_bytes() == on_disk


def test_the_link_and_the_fee_restated_in_one_file_are_accepted(tmp_path):
    book = _book(tmp_path)
    before = _exported(book, tmp_path)
    posting = _the_invoice_s_posting_split(before)
    fee = _block(before, FEE_HEAD).replace(
        'cost_basis_split_guid: "0e530000000000000000000000000b22"',
        f'cost_basis_split_guid: "{posting}"')

    done = _import(book, tmp_path, _without_comments(LINK) + '\n' + fee)

    assert done.exit_code == 0 and 'Errors:       0' in done.output, done.output
    after = _exported(book, tmp_path)
    assert 'txn_guid: "0e530000000000000000000000000b21"' in _block(after, 'invoice "INV-USD-1"')
    assert f'cost_basis_split_guid: "{posting}"' in _block(after, FEE_HEAD)
    checked = _run(CliRunner(), 'fx-balances', str(book), '--verify-costs')
    assert checked.exit_code == 0 and 'warning' not in checked.output, checked.output


# The reported file with one thing in it wrong. Each is refused whole, and the
# book file is left as it was.

def _posting_of(text, line):
    """The guid of the posting split the export writes as `line`."""
    return re.search(rf'{re.escape(line)}\n\t+guid: "([0-9a-f]{{32}})"', text).group(1)


def _the_fee_drawing_on(before, basis):
    """The fee's block as the book holds it, drawing on `basis`, its `share_price:` left out."""
    fee = _block(before, FEE_HEAD).replace(
        'cost_basis_split_guid: "0e530000000000000000000000000b22"',
        f'cost_basis_split_guid: "{basis}"')
    return ''.join(line + '\n' for line in fee.splitlines() if 'share_price' not in line)


def _refused(book, tmp_path, text):
    on_disk = book.read_bytes()
    done = _import(book, tmp_path, text)
    assert done.exit_code != 0, done.output
    assert book.read_bytes() == on_disk
    return done.output


def test_the_fee_restated_onto_the_invoice_at_another_cad_figure_is_refused(tmp_path):
    """0.72 USD of the invoice's dollars cost 1.00 CAD; the fee restated at 1.01 is not valued at that."""
    book = _book(tmp_path)
    before = _exported(book, tmp_path)
    posting = _the_invoice_s_posting_split(before)
    fee = _the_fee_drawing_on(before, posting).replace(
        'Assets:Due from director 1.00 CAD', 'Assets:Due from director 1.01 CAD')

    refused = _refused(book, tmp_path, _without_comments(LINK) + '\n' + fee)

    assert (f'this split sells 0.72 USD valued at 1.01 CAD, but cost basis {posting} '
            'cost 189557/136000 CAD per USD, i.e. 1.00 CAD') in refused, refused
    assert ('It is stated in USD: write it in CAD, this split with share_price: '
            '"189557/136000" and no value:, and give the difference to a `$residual$` '
            'split') in refused, refused


def test_the_fee_restated_onto_the_invoice_drawing_another_amount_at_its_cost_is_accepted(tmp_path):
    """The fee corrected to 0.73 USD, valued at the invoice's cost, 1.02 CAD: a correct transaction, and the book agrees with itself after it."""
    book = _book(tmp_path)
    before = _exported(book, tmp_path)
    fee = (_the_fee_drawing_on(before, _the_invoice_s_posting_split(before))
           .replace('Assets:Due from director 1.00 CAD', 'Assets:Due from director 1.02 CAD')
           .replace('value: "0.72"', 'value: "0.73"')
           .replace('Assets:Wise USD -0.72 USD', 'Assets:Wise USD -0.73 USD'))

    done = _import(book, tmp_path, _without_comments(LINK) + '\n' + fee)

    assert done.exit_code == 0 and 'Errors:       0' in done.output, done.output
    assert 'Assets:Wise USD -0.73 USD' in _block(_exported(book, tmp_path), FEE_HEAD)
    checked = _run(CliRunner(), 'fx-balances', str(book), '--verify-costs')
    assert checked.exit_code == 0 and 'warning' not in checked.output, checked.output
    assert re.search(r'Assets:Accounts Receivable USD\s+189557/136000 CAD/USD\s+2,720\.00 USD'
                     r'\s+2,719\.27 USD\n\s+Invoice INV-USD-1\n', checked.output), checked.output
    assert re.search(r'Assets:Wise USD\s+2,719\.27 USD', checked.output), checked.output


def test_the_fee_restated_onto_an_invoice_not_collected_is_refused(tmp_path):
    """INV-USD-2 is unpaid, so its cost basis holds no dollars the fee could spend."""
    book = _book(tmp_path)
    before = _exported(book, tmp_path)
    fee = _the_fee_drawing_on(
        before, _posting_of(before, 'Assets:Accounts Receivable USD 4000.00 USD'))

    _refused(book, tmp_path, _without_comments(LINK) + '\n' + fee)


def test_the_fee_restated_onto_a_bill_is_refused(tmp_path):
    """BILL-USD-1's cost basis is dollars the book owes, and the fee spends dollars it holds."""
    book = _book(tmp_path)
    before = _exported(book, tmp_path)
    bill = _posting_of(before, 'Liabilities:Accounts Payable USD -1000.00 USD')
    fee = _the_fee_drawing_on(before, bill)

    refused = _refused(book, tmp_path, _without_comments(LINK) + '\n' + fee)

    assert (f"cost_basis_split_guid '{bill}' is a cost basis of USD the book owed, "
            'but this split spends USD the book held') in refused, refused


def _the_fee_onto_the_invoice(before):
    return _the_fee_drawing_on(before, _the_invoice_s_posting_split(before))


def test_the_link_giving_the_fee_s_transaction_is_refused(tmp_path):
    book = _book(tmp_path)
    before = _exported(book, tmp_path)
    link = _without_comments(LINK).replace(
        'txn_guid: "0e530000000000000000000000000b21"',
        'txn_guid: "0e530000000000000000000000000b31"')

    _refused(book, tmp_path, link + '\n' + _the_fee_onto_the_invoice(before))


def test_the_link_giving_another_bank_account_is_refused(tmp_path):
    book = _book(tmp_path)
    before = _exported(book, tmp_path)
    link = _without_comments(LINK).replace(
        'bank_account: "Assets:Wise USD"', 'bank_account: "Assets:USD Savings"')

    _refused(book, tmp_path, link + '\n' + _the_fee_onto_the_invoice(before))


def test_the_link_giving_the_deposit_s_bank_split_is_refused(tmp_path):
    """`txn_split_guid:` gives the split that settles the invoice; the bank split is what the payment brings in."""
    book = _book(tmp_path)
    before = _exported(book, tmp_path)
    link = _without_comments(LINK).replace(
        '\t\ttxn_guid: "0e530000000000000000000000000b21"\n',
        '\t\ttxn_guid: "0e530000000000000000000000000b21"\n'
        '\t\ttxn_split_guid: "0e530000000000000000000000000b22"\n')

    _refused(book, tmp_path, link + '\n' + _the_fee_onto_the_invoice(before))
