"""A deposit linked to the invoice it collected, its fee a transaction of its own, in one `--atomic` file (Q-053).

The bank writes the deposit and its fee as two transactions stated in US
dollars, the fee drawing on the deposit's cost basis. An application links
the deposit to the invoice with the invoice's `payment:` block, giving the
deposit's transaction and the bank account. Once the deposit pays the
invoice, its dollars are the invoice's collected dollars, and the fee has to
draw on the invoice's cost basis: the file gives that, restating the fee.
"""

import re
from pathlib import Path

from click.testing import CliRunner

from infrastructure.gnucash.kvp import get_custom_metadata, set_custom_metadata
from repositories.gnucash_repository import GnuCashRepository, SessionMode
from services.foreign_currency import iter_splits, split_guid
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


def test_three_sales_of_the_deposit_giving_no_cost_basis_are_refused_as_sales(tmp_path):
    """US dollars out of Wise USD, Canadian dollars onto Assets:Due from director: each is a sale, and the refusal says so."""
    book = tmp_path / 'book.gnucash'
    made = _run(CliRunner(), 'import', '--new', str(book), BASE,
                '--include-business-objects', '--fx-rates', RATES)
    assert made.exit_code == 0, made.output
    on_disk = book.read_bytes()

    done = _run(CliRunner(), 'import', str(book),
                FIXTURES + 'a_usd_deposit_and_three_sales_of_it_giving_no_cost_basis.txt',
                '--fx-rates', RATES, '--atomic')

    assert done.exit_code != 0, done.output
    assert book.read_bytes() == on_disk
    for sold, received in (('0.72', '1.00'), ('2710.68', '3758.36'), ('8.60', '11.92')):
        assert (f'this transaction is a sale of {sold} USD the book held for {received} '
                f'CAD: Assets:Wise USD, a Bank account in USD, is credited {sold} USD; '
                f'Assets:Due from director, an Asset account in CAD, is debited {received} '
                'CAD. A sale requires a consumption of one or more cost bases, but no '
                'split says which.') in done.output, done.output
    assert 'cost_basis_split_guid: $transactions_to_import[0].splits[0].guid$' in done.output


def test_three_sales_of_the_deposit_each_giving_its_cost_basis_are_imported(tmp_path):
    """Sales stated in US dollars at the day's rate, each giving the deposit's cost basis, are imported.

    Each Canadian dollar figure is what the dollars fetched that day, not what
    they cost, and a transaction stated in US dollars has no split that can
    record the difference in Canadian ones. A check refusing every such sale
    whose figure was not the cost refused this file, the one the application
    sends.
    """
    book = tmp_path / 'book.gnucash'
    made = _run(CliRunner(), 'import', '--new', str(book), BASE,
                '--include-business-objects', '--fx-rates', RATES)
    assert made.exit_code == 0, made.output

    done = _run(CliRunner(), 'import', str(book),
                FIXTURES + 'a_usd_deposit_and_three_sales_of_it_each_giving_its_cost_basis.txt',
                '--fx-rates', RATES, '--atomic')

    assert done.exit_code == 0 and 'Errors:       0' in done.output, done.output
    assert 'Transactions: 4' in done.output, done.output
    checked = _run(CliRunner(), 'fx-balances', str(book), '--verify-costs')
    assert checked.exit_code == 0 and 'warning' not in checked.output, checked.output
    assert re.search(r'Assets:Wise USD\s+0\.00 USD', checked.output), checked.output
    whole = _run(CliRunner(), '--verify-integrity', str(book))
    assert whole.exit_code == 0, whole.output


def test_a_refund_giving_no_cost_basis_is_refused_as_a_refund(tmp_path):
    """50.00 USD out of Wise to the customer, Income:Sales debited: a refund, not an expense."""
    book = _book(tmp_path)
    ledger = tmp_path / 'refund.txt'
    ledger.write_text('2026-08-20 * "Refund to the customer"\n'
                      '\tcurrency.mnemonic: "CAD"\n'
                      '\tAssets:Wise USD -50.00 USD\n'
                      '\t\taccount.commodity.mnemonic: "USD"\n'
                      '\t\tvalue: "-69.69"\n'
                      '\tIncome:Sales 69.69 CAD\n')

    done = _run(CliRunner(), 'import', str(book), str(ledger), '--fx-rates', RATES, '--atomic')

    assert ('this transaction is a refund of 50.00 USD the book held: Assets:Wise USD, a '
            'Bank account in USD, is credited 50.00 USD; Income:Sales, an Income account in '
            'CAD, is debited 69.69 CAD. A refund requires a consumption of one or more cost '
            'bases, but no split says which.') in done.output, done.output


def test_a_loss_a_sale_stated_in_usd_records_on_a_split_of_no_value_is_not_stated_again(tmp_path):
    """The 8.60 USD fee cost 11.99 CAD and fetched 11.92; booked with its 0.07 loss on Income:FX gain, only the transfer's 19.79 is stated as not recorded."""
    book = tmp_path / 'book.gnucash'
    made = _run(CliRunner(), 'import', '--new', str(book), BASE,
                '--include-business-objects', '--fx-rates', RATES)
    assert made.exit_code == 0, made.output
    ledger = tmp_path / 'sales.txt'
    ledger.write_text(Path(FIXTURES + 'a_usd_deposit_and_three_sales_of_it_each_giving_its_cost_basis.txt')
                      .read_text().replace(
                          '\t\tshare_price: "215/298"\n\t\tvalue: "8.60"\n',
                          '\t\tshare_price: "215/298"\n\t\tvalue: "8.60"\n'
                          '\tIncome:FX gain 0.07 CAD\n'
                          '\t\taccount.commodity.mnemonic: "CAD"\n'
                          '\t\tvalue: "0"\n'))

    done = _run(CliRunner(), 'import', str(book), str(ledger), '--fx-rates', RATES, '--atomic')

    assert done.exit_code == 0 and 'Errors:       0' in done.output, done.output
    page = _run(CliRunner(), 'balance-sheet', str(book), '--as-of', '2026-08-17',
                '--output-format', 'text', '--itemize')
    assert ('\t\trealized_gains_not_recorded: -19.79 # sum of each cost_basis\'s '
            'realized_gains_not_recorded') in page.output, page.output
    whole = _run(CliRunner(), '--verify-integrity', str(book))
    assert whole.exit_code == 0, whole.output


PENDING = FIXTURES + 'a_usd_deposit_and_three_sales_of_it_pending_their_cost_basis.txt'


def _pending_book(tmp_path):
    book = tmp_path / 'book.gnucash'
    made = _run(CliRunner(), 'import', '--new', str(book), BASE,
                '--include-business-objects', '--fx-rates', RATES)
    assert made.exit_code == 0, made.output
    done = _run(CliRunner(), 'import', str(book), PENDING, '--fx-rates', RATES, '--atomic')
    assert done.exit_code == 0 and 'Errors:       0' in done.output, done.output
    return book


def test_sales_pending_their_cost_basis_are_imported_drawing_on_nothing(tmp_path):
    """`cost_basis_split_guid: $pending$` imports a sale whose cost basis is not decided yet, and it is listed as pending."""
    book = _pending_book(tmp_path)

    listed = _run(CliRunner(), 'fx-balances', str(book))
    assert listed.exit_code == 0, listed.output
    assert re.search(r'0e530000000000000000000000000c22\s+Assets:Wise USD\s+\S+ CAD/USD'
                     r'\s+2,720\.00 USD\s+2,720\.00 USD', listed.output), listed.output
    assert ('3 disposal(s) pending their cost basis, drawing on none until an edit '
            'gives it: 2,720.00 USD') in listed.output, listed.output
    assert '2026-08-13   Assets:Wise USD   0.72 USD   Charges for the deposit' in listed.output
    exported = _exported(book, tmp_path)
    assert exported.count('\t\tcost_basis_split_guid: $pending$\n') == 3, exported


def test_verifying_the_costs_counts_the_pending_sales_and_finds_nothing_wrong(tmp_path):
    book = _pending_book(tmp_path)

    checked = _run(CliRunner(), 'fx-balances', str(book), '--verify-costs')

    assert checked.exit_code == 0 and 'warning' not in checked.output, checked.output
    assert ('Checked 5 cost basis(es): every cost agrees with the figures it is derived '
            'from. 3 disposal(s) are pending their cost basis.') in checked.output, \
        checked.output
    in_hkd = _run(CliRunner(), 'fx-balances', str(book), '--currency', 'HKD', '--verify-costs')
    assert in_hkd.exit_code == 0 and 'pending' not in in_hkd.output, in_hkd.output


def test_verifying_the_book_counts_the_pending_sales_and_finds_nothing_wrong(tmp_path):
    """The cost bases offer 2,720.00 USD more than the accounts hold, which is what the pending sales took."""
    book = _pending_book(tmp_path)

    checked = _run(CliRunner(), '--verify-integrity', str(book))

    assert checked.exit_code == 0, checked.output
    assert ('checked: no cost basis holds more of a currency than the accounts do, '
            'beside 3 disposal(s) pending their cost basis: 2,720.00 USD, which drew '
            'on none') in checked.output, checked.output
    assert 'checked: the balance sheet as of 2026-08-17 balances' in checked.output


def test_the_balance_sheet_lists_the_pending_sales_at_what_they_were_recorded_at(tmp_path):
    """Taken off the cost bases at the 3,771.28 CAD their transactions recorded, so no gain is stated for them."""
    book = _pending_book(tmp_path)

    page = _run(CliRunner(), 'balance-sheet', str(book), '--as-of', '2026-08-17',
                '--output-format', 'text', '--itemize')

    assert page.exit_code == 0, page.output
    assert ('\t\t\t\t\t\tsplit_guid: $pending$\n'
            '\t\t\t\t\t\taccount: "pending their cost basis"\n'
            '\t\t\t\t\t\tcost_basis_balance: -2720.00\n'
            '\t\t\t\t\t\tcost_share_price: 1\n'
            '\t\t\t\t\t\tcost_rate: 1.3865 # CAD per USD, what the pending '
            'disposals\' transactions recorded\n') in page.output, page.output
    assert '\t\t\t\t\t\tcost_value: -3771.28 # cost_basis_balance' in page.output


def test_a_balance_sheet_drawn_before_a_pending_sale_leaves_it_out(tmp_path):
    """Drawn at 13 August, the sheet counts the fee pending that day and not the two sales of the 17th."""
    book = _pending_book(tmp_path)

    page = _run(CliRunner(), 'balance-sheet', str(book), '--as-of', '2026-08-13',
                '--output-format', 'text', '--itemize')

    assert page.exit_code == 0, page.output
    assert ('\t\t\t\t\t\tsplit_guid: $pending$\n'
            '\t\t\t\t\t\taccount: "pending their cost basis"\n'
            '\t\t\t\t\t\tcost_basis_balance: -0.72\n') in page.output, page.output


def test_a_pending_sale_given_its_cost_basis_by_an_edit_draws_it_down(tmp_path):
    book = _pending_book(tmp_path)
    fee = _block(_exported(book, tmp_path), FEE_HEAD).replace(
        'cost_basis_split_guid: $pending$',
        'cost_basis_split_guid: "0e530000000000000000000000000c22"')

    done = _import(book, tmp_path, fee)

    assert done.exit_code == 0 and 'Errors:       0' in done.output, done.output
    listed = _run(CliRunner(), 'fx-balances', str(book))
    assert re.search(r'Assets:Wise USD\s+\S+ CAD/USD\s+2,720\.00 USD\s+2,719\.28 USD',
                     listed.output), listed.output
    assert ('2 disposal(s) pending their cost basis, drawing on none until an edit '
            'gives it: 2,719.28 USD') in listed.output, listed.output


SALE_HEADS = (FEE_HEAD, '2026-08-17 * "Sent money"', '2026-08-17 * "Charges for the transfer"')
DEPOSIT_S_COST_BASIS = 'cost_basis_split_guid: "0e530000000000000000000000000c22"'


def test_every_pending_sale_given_its_cost_basis_leaves_the_book_consistent(tmp_path):
    """Each sale given the deposit's cost basis by an edit: nothing pending, the cost basis spent to what Wise holds, and every check passes."""
    book = _pending_book(tmp_path)
    before = _exported(book, tmp_path)
    decided = '\n'.join(_block(before, head).replace('cost_basis_split_guid: $pending$',
                                                     DEPOSIT_S_COST_BASIS)
                        for head in SALE_HEADS)

    done = _import(book, tmp_path, decided)

    assert done.exit_code == 0 and 'Errors:       0' in done.output, done.output
    assert '$pending$' not in _exported(book, tmp_path)
    costs = _run(CliRunner(), 'fx-balances', str(book), '--verify-costs')
    assert costs.exit_code == 0 and 'warning' not in costs.output, costs.output
    assert 'pending' not in costs.output, costs.output
    assert re.search(r'0e530000000000000000000000000c22\s+Assets:Wise USD\s+\S+ CAD/USD'
                     r'\s+2,720\.00 USD\s+0\.00 USD', costs.output), costs.output
    assert re.search(r'Assets:Wise USD\s+0\.00 USD\n', costs.output), costs.output
    whole = _run(CliRunner(), '--verify-integrity', str(book))
    assert whole.exit_code == 0, whole.output
    assert ('checked: no cost basis holds more of a currency than the accounts do\n'
            in whole.output), whole.output
    assert 'checked: the balance sheet as of 2026-08-17 balances' in whole.output
    page = _run(CliRunner(), 'balance-sheet', str(book), '--as-of', '2026-08-17',
                '--output-format', 'text', '--itemize')
    assert page.exit_code == 0 and '$pending$' not in page.output, page.output
    # The sales fetched 3,771.28 CAD for dollars that cost 3,791.14, and a
    # transaction stated in US dollars has no split to record that in.
    assert ('\t\trealized_gains_not_recorded: -19.86 # sum of each cost_basis\'s '
            'realized_gains_not_recorded') in page.output, page.output


def test_a_pending_sale_given_a_bill_s_cost_basis_is_refused_and_stays_pending(tmp_path):
    book = _pending_book(tmp_path)
    before = _exported(book, tmp_path)
    bill = _posting_of(before, 'Liabilities:Accounts Payable USD -1000.00 USD')
    fee = _block(before, FEE_HEAD).replace('cost_basis_split_guid: $pending$',
                                           f'cost_basis_split_guid: "{bill}"')

    refused = _refused(book, tmp_path, fee)

    assert (f"cost_basis_split_guid '{bill}' is a cost basis of USD the book owed, "
            'but this split spends USD the book held') in refused, refused
    assert ('3 disposal(s) pending their cost basis'
            in _run(CliRunner(), 'fx-balances', str(book)).output)


def test_a_pending_sale_given_a_cost_basis_holding_less_is_refused_and_stays_pending(tmp_path):
    """INV-USD-1 has not been collected in this book, so its cost basis holds nothing to sell."""
    book = _pending_book(tmp_path)
    before = _exported(book, tmp_path)
    sale = _block(before, '2026-08-17 * "Sent money"').replace(
        'cost_basis_split_guid: $pending$',
        f'cost_basis_split_guid: "{_the_invoice_s_posting_split(before)}"')

    refused = _refused(book, tmp_path, sale)

    assert 'has not been collected' in refused, refused
    assert ('3 disposal(s) pending their cost basis'
            in _run(CliRunner(), 'fx-balances', str(book)).output)


def test_pending_given_on_a_split_bringing_dollars_in_is_refused(tmp_path):
    """`$pending$` stands for a disposal's cost basis; on the deposit's own arrival it would be a disposal that took nothing."""
    book = tmp_path / 'book.gnucash'
    made = _run(CliRunner(), 'import', '--new', str(book), BASE,
                '--include-business-objects', '--fx-rates', RATES)
    assert made.exit_code == 0, made.output
    ledger = tmp_path / 'file.txt'
    ledger.write_text(Path(PENDING).read_text().replace(
        '\t\tguid: "0e530000000000000000000000000c22"\n',
        '\t\tguid: "0e530000000000000000000000000c22"\n'
        '\t\tcost_basis_split_guid: $pending$\n'))
    on_disk = book.read_bytes()

    done = _run(CliRunner(), 'import', str(book), str(ledger), '--fx-rates', RATES, '--atomic')

    assert done.exit_code != 0 and book.read_bytes() == on_disk, done.output
    refused = done.output
    assert ('the split on Assets:Wise USD gives `cost_basis_split_guid: $pending$`, and '
            'it is no disposition: it disposes of nothing the book holds or owes') \
        in refused, refused


def test_pending_on_a_sale_of_more_than_the_account_holds_is_refused(tmp_path):
    """3,000.00 USD credited to Wise, which holds 2,710.68 once the day's other lines are in, is a disposition of 2,710.68 and a borrowing of the rest; a pending row cannot take off part of a split."""
    book = tmp_path / 'book.gnucash'
    made = _run(CliRunner(), 'import', '--new', str(book), BASE,
                '--include-business-objects', '--fx-rates', RATES)
    assert made.exit_code == 0, made.output
    ledger = tmp_path / 'file.txt'
    ledger.write_text(Path(PENDING).read_text()
                      .replace('Assets:Wise USD -2710.68 USD', 'Assets:Wise USD -3000.00 USD')
                      .replace('Assets:Due from director 3758.36 CAD',
                               'Assets:Due from director 4159.40 CAD')
                      .replace('value: "2710.68"', 'value: "3000.00"'))
    on_disk = book.read_bytes()

    done = _run(CliRunner(), 'import', str(book), str(ledger), '--fx-rates', RATES, '--atomic')

    assert done.exit_code != 0 and book.read_bytes() == on_disk, done.output
    assert ('error: Sent money: the split on Assets:Wise USD gives `cost_basis_split_guid: '
            '$pending$`, and it disposes of 2710.68 of the 3000.00 USD on it: the rest is '
            'a borrowing') in done.output, \
        done.output


BACKDATED_TRANSFER = ('2026-08-14 * "Moved to savings"\n'
                      '\tcurrency.mnemonic: "USD"\n'
                      '\tAssets:Wise USD -100.00 USD\n'
                      '\tAssets:USD Savings 100.00 USD\n')


def test_a_transfer_dated_before_the_pending_sales_leaves_them_as_they_were_imported(tmp_path):
    """What each pending split moves was recorded when it was imported, so 100.00 USD moved out of Wise on 14 August changes none of them."""
    book = _pending_book(tmp_path)
    ledger = tmp_path / 'transfer.txt'
    ledger.write_text(BACKDATED_TRANSFER)

    done = _run(CliRunner(), 'import', str(book), str(ledger), '--fx-rates', RATES, '--atomic')

    assert done.exit_code == 0 and 'Errors:       0' in done.output, done.output
    checked = _run(CliRunner(), 'fx-balances', str(book), '--verify-costs')
    assert checked.exit_code == 0, checked.output
    assert ('3 disposal(s) pending their cost basis, drawing on none until an edit '
            'gives it: 2,720.00 USD') in checked.output, checked.output


def test_pending_added_by_an_edit_to_a_sale_s_canadian_dollar_split_is_refused(tmp_path):
    """`$pending$` on the Due from director split of "Sent money", the only change the edit makes: refused, and the book file unchanged."""
    book = tmp_path / 'book.gnucash'
    made = _run(CliRunner(), 'import', '--new', str(book), BASE,
                '--include-business-objects', '--fx-rates', RATES)
    assert made.exit_code == 0, made.output
    sales = _run(CliRunner(), 'import', str(book),
                 FIXTURES + 'a_usd_deposit_and_three_sales_of_it_each_giving_its_cost_basis.txt',
                 '--fx-rates', RATES)
    assert sales.exit_code == 0, sales.output
    sale = _block(_exported(book, tmp_path), '2026-08-17 * "Sent money"')
    edited = sale.replace('\tAssets:Due from director 3758.36 CAD\n',
                          '\tAssets:Due from director 3758.36 CAD\n'
                          '\t\tcost_basis_split_guid: $pending$\n')
    assert edited != sale
    on_disk = book.read_bytes()

    done = _import(book, tmp_path, edited)

    assert done.exit_code != 0 and book.read_bytes() == on_disk, done.output
    assert ('the split on Assets:Due from director gives `cost_basis_split_guid: '
            '$pending$`, and it is no disposition') in done.output, done.output


def test_pending_added_by_an_edit_to_a_sale_dated_before_any_cost_basis_is_refused(tmp_path):
    """The fixture's first sale was imported before any US dollar cost basis opened; one opened later does not make `$pending$` on it decidable."""
    book = tmp_path / 'book.gnucash'
    made = _run(CliRunner(), 'import', '--new', str(book),
                FIXTURES + 'a_spend_before_and_after_a_cost_basis_opens_in_one_file.txt')
    sale = _block(_exported(book, tmp_path), '2036-01-10 * "Sell 10.00 USD before any cost basis is kept"')
    edited = sale.replace('\t\tvalue: "-14.00"\n',
                          '\t\tvalue: "-14.00"\n\t\tcost_basis_split_guid: $pending$\n', 1)
    assert edited != sale, made.output
    on_disk = book.read_bytes()

    done = _import(book, tmp_path, edited)

    assert done.exit_code != 0 and book.read_bytes() == on_disk, done.output
    assert ('the split on Assets:USD Bank gives `cost_basis_split_guid: $pending$`, and '
            'the book keeps no cost basis of the USD it holds opened by 2036-01-10') \
        in done.output, done.output


def test_pending_added_by_an_edit_to_the_deposit_s_arrival_is_refused(tmp_path):
    book = _pending_book(tmp_path)
    deposit = _block(_exported(book, tmp_path), '2026-08-13 * "Balance-leaving deposit"')
    edited = deposit.replace('\t\tguid: "0e530000000000000000000000000c22"\n',
                             '\t\tguid: "0e530000000000000000000000000c22"\n'
                             '\t\tcost_basis_split_guid: $pending$\n')
    assert edited != deposit
    on_disk = book.read_bytes()

    done = _import(book, tmp_path, edited)

    assert done.exit_code != 0 and book.read_bytes() == on_disk, done.output
    assert ('the split on Assets:Wise USD gives `cost_basis_split_guid: $pending$`, and it '
            'is no disposition') in done.output, done.output


def test_pending_written_into_the_book_elsewhere_where_it_cannot_stand_is_reported(tmp_path):
    """`$pending$` put on the deposit's own arrival outside this tool, which the import refuses: the checks report it with the reason."""
    book = _pending_book(tmp_path)
    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.NORMAL)
    try:
        arrival = next(split for split in iter_splits(repo.book)
                       if split_guid(split) == '0e530000000000000000000000000c22')
        deposit = arrival.GetParent()
        deposit.BeginEdit()
        set_custom_metadata(arrival, {**get_custom_metadata(arrival),
                                      'cost_basis_split_guid': '$pending$'})
        deposit.CommitEdit()
        repo.save()
    finally:
        repo.close()

    costs = _run(CliRunner(), 'fx-balances', str(book), '--verify-costs')
    whole = _run(CliRunner(), '--verify-integrity', str(book))

    reason = ('the split on Assets:Wise USD gives `cost_basis_split_guid: $pending$`, and it '
              'is no disposition: it disposes of nothing the book holds or owes')
    assert costs.exit_code == 1 and reason in costs.output, costs.output
    assert '3 disposal(s) pending their cost basis' in costs.output, costs.output
    assert whole.exit_code == 1 and reason in whole.output, whole.output


def test_pending_on_a_split_beside_a_transfer_is_refused(tmp_path):
    """100.00 USD credited to Wise on 14 August, 60.00 of it debited to USD Savings: a transfer of 60.00 and a disposition of 40.00 in one split."""
    book = _pending_book(tmp_path)
    ledger = tmp_path / 'transfer.txt'
    ledger.write_text('2026-08-14 * "Moved to savings, and a charge"\n'
                      '\tcurrency.mnemonic: "USD"\n'
                      '\tAssets:Wise USD -100.00 USD\n'
                      '\t\tcost_basis_split_guid: $pending$\n'
                      '\tAssets:USD Savings 60.00 USD\n'
                      '\tAssets:Due from director 55.75 CAD\n'
                      '\t\taccount.commodity.mnemonic: "CAD"\n'
                      '\t\tvalue: "40.00"\n')
    on_disk = book.read_bytes()

    done = _run(CliRunner(), 'import', str(book), str(ledger), '--fx-rates', RATES, '--atomic')

    assert done.exit_code != 0 and book.read_bytes() == on_disk, done.output
    assert ('the split on Assets:Wise USD gives `cost_basis_split_guid: $pending$`, and it '
            'disposes of 40.00 of the 100.00 USD on it') in done.output, done.output


def test_pending_where_no_cost_basis_is_kept_is_refused(tmp_path):
    """The fixture's first sale comes before any US dollar cost basis opens: there is none for `$pending$` to leave undecided."""
    ledger = tmp_path / 'spend.txt'
    ledger.write_text(Path(FIXTURES + 'a_spend_before_and_after_a_cost_basis_opens_in_one_file.txt')
                      .read_text().replace(
                          '\tAssets:USD Bank -10.00 USD\n'
                          '\t\taccount.commodity.mnemonic: "USD"\n'
                          '\t\tshare_price: "7/5"\n'
                          '\t\tvalue: "-14.00"\n'
                          '\tAssets:CAD Bank 14.00 CAD\n\n'
                          '2036-01-12',
                          '\tAssets:USD Bank -10.00 USD\n'
                          '\t\taccount.commodity.mnemonic: "USD"\n'
                          '\t\tshare_price: "7/5"\n'
                          '\t\tvalue: "-14.00"\n'
                          '\t\tcost_basis_split_guid: $pending$\n'
                          '\tAssets:CAD Bank 14.00 CAD\n\n'
                          '2036-01-12'))

    done = _run(CliRunner(), 'import', '--new', str(tmp_path / 'book.gnucash'), str(ledger))

    assert ('error: Sell 10.00 USD before any cost basis is kept: the split on '
            'Assets:USD Bank gives `cost_basis_split_guid: $pending$`, and the book keeps '
            'no cost basis of the USD it holds') in done.output, done.output


def test_pending_in_a_book_keeping_no_cost_bases_is_refused(tmp_path):
    book = tmp_path / 'book.gnucash'
    made = _run(CliRunner(), 'import', '--new', str(book), BASE,
                '--include-business-objects', '--fx-rates', RATES)
    assert made.exit_code == 0, made.output
    off = _run(CliRunner(), 'import', str(book), FIXTURES + 'a_company_that_keeps_no_cost_bases.txt',
               '--include-business-objects')
    assert off.exit_code == 0, off.output
    on_disk = book.read_bytes()

    done = _run(CliRunner(), 'import', str(book), PENDING, '--fx-rates', RATES, '--atomic')

    assert done.exit_code != 0 and book.read_bytes() == on_disk, done.output
    assert ('states cost_basis_split_guid:, and this book keeps no cost bases'
            in done.output), done.output


def test_a_fee_restated_onto_the_invoice_at_another_cad_figure_states_what_it_realized(tmp_path):
    """0.72 of the invoice's dollars cost 1.00 CAD; stated in US dollars at 1.01, the 0.01 it realized is stated as not recorded."""
    book = _book(tmp_path)
    before = _exported(book, tmp_path)
    fee = _the_fee_drawing_on(before, _the_invoice_s_posting_split(before)).replace(
        'Assets:Due from director 1.00 CAD', 'Assets:Due from director 1.01 CAD')

    done = _import(book, tmp_path, _without_comments(LINK) + '\n' + fee)

    assert done.exit_code == 0 and 'Errors:       0' in done.output, done.output
    page = _run(CliRunner(), 'balance-sheet', str(book), '--as-of', '2026-08-17',
                '--output-format', 'text', '--itemize')
    assert ('\t\trealized_gains_not_recorded: 0.01 # sum of each cost_basis\'s '
            'realized_gains_not_recorded') in page.output, page.output
    assert _run(CliRunner(), '--verify-integrity', str(book)).exit_code == 0


def test_pending_in_a_transaction_stating_no_canadian_figure_is_refused(tmp_path):
    """The second loan repaid wholly in US dollars, the bank's pick made `$pending$`: nothing says what it left the book at."""
    ledger = tmp_path / 'loan.txt'
    ledger.write_text(Path(FIXTURES + 'a_us_loan_repaid_in_a_transaction_stating_no_canadian_figure.txt')
                      .read_text().replace(
                          '\tAssets:USD Bank -500.00 USD\n'
                          '\t\tcost_basis_split_guid: "d4d4d4d4d4d4d4d4d4d4d4d4d4d40001"',
                          '\tAssets:USD Bank -500.00 USD\n'
                          '\t\tcost_basis_split_guid: $pending$'))

    done = _run(CliRunner(), 'import', '--new', str(tmp_path / 'book.gnucash'), str(ledger))

    assert ('error: Repay the second loan, written wholly in US dollars: the split on '
            'Assets:USD Bank gives `cost_basis_split_guid: $pending$`, and its '
            'transaction states no CAD figure for all it disposes of') in done.output, \
        done.output


def test_pending_written_in_quotes_is_pending_too(tmp_path):
    """No split's guid is `$pending$`, so a file quoting it means the same, and the export writes it unquoted."""
    book = tmp_path / 'book.gnucash'
    made = _run(CliRunner(), 'import', '--new', str(book), BASE,
                '--include-business-objects', '--fx-rates', RATES)
    assert made.exit_code == 0, made.output
    ledger = tmp_path / 'file.txt'
    ledger.write_text(Path(PENDING).read_text().replace(
        'cost_basis_split_guid: $pending$', 'cost_basis_split_guid: "$pending$"'))

    done = _run(CliRunner(), 'import', str(book), str(ledger), '--fx-rates', RATES, '--atomic')

    assert done.exit_code == 0 and 'Errors:       0' in done.output, done.output
    assert '3 disposal(s) pending their cost basis' in _run(
        CliRunner(), 'fx-balances', str(book)).output
    assert _exported(book, tmp_path).count('\t\tcost_basis_split_guid: $pending$\n') == 3


def test_a_sale_given_its_cost_basis_and_made_pending_again_gives_it_back(tmp_path):
    book = _pending_book(tmp_path)
    fee = _block(_exported(book, tmp_path), FEE_HEAD)
    decided = fee.replace('cost_basis_split_guid: $pending$', DEPOSIT_S_COST_BASIS)
    done = _import(book, tmp_path, decided)
    assert done.exit_code == 0 and 'Errors:       0' in done.output, done.output

    again = _import(book, tmp_path, fee)

    assert again.exit_code == 0 and 'Errors:       0' in again.output, again.output
    listed = _run(CliRunner(), 'fx-balances', str(book))
    assert re.search(r'Assets:Wise USD\s+\S+ CAD/USD\s+2,720\.00 USD\s+2,720\.00 USD',
                     listed.output), listed.output
    assert '3 disposal(s) pending their cost basis' in listed.output, listed.output


LAST_SALE_STATED_IN_CAD = (
    FIXTURES + 'a_usd_deposit_sold_in_usd_then_its_last_dollars_sold_in_cad_at_their_cost.txt')


def test_the_last_sale_stated_in_cad_after_one_stated_in_usd_is_valued_at_its_own_cost(tmp_path):
    """The USD-stated sale's loss is its own, stated as not recorded, and not put on the last sale."""
    book = tmp_path / 'book.gnucash'
    made = _run(CliRunner(), 'import', '--new', str(book), BASE,
                '--include-business-objects', '--fx-rates', RATES)
    assert made.exit_code == 0, made.output

    done = _run(CliRunner(), 'import', str(book), LAST_SALE_STATED_IN_CAD,
                '--fx-rates', RATES, '--atomic')

    assert done.exit_code == 0 and 'Errors:       0' in done.output, done.output
    whole = _run(CliRunner(), '--verify-integrity', str(book))
    assert whole.exit_code == 0, whole.output
    page = _run(CliRunner(), 'balance-sheet', str(book), '--as-of', '2026-08-17',
                '--output-format', 'text', '--itemize')
    assert ('\t\trealized_gains_not_recorded: -19.79 # sum of each cost_basis\'s '
            'realized_gains_not_recorded') in page.output, page.output


def test_a_book_holding_pending_sales_imported_again_from_its_export_is_left_alone(tmp_path):
    """The file states each pending split as the book holds it, so nothing is edited and nothing saved."""
    book = _pending_book(tmp_path)
    ledger = tmp_path / 'whole.txt'
    ledger.write_text(_exported(book, tmp_path))
    on_disk = book.read_bytes()

    done = _run(CliRunner(), 'import', str(book), str(ledger), '--strategy', 'update',
                '--include-business-objects', '--atomic')

    assert done.exit_code == 0 and 'Errors:       0' in done.output, done.output
    assert 'Updated:      0' in done.output, done.output
    assert book.read_bytes() == on_disk


def test_a_book_holding_pending_sales_is_rebuilt_from_its_export(tmp_path):
    book = _pending_book(tmp_path)
    ledger = tmp_path / 'whole.txt'
    ledger.write_text(_exported(book, tmp_path))

    rebuilt = _run(CliRunner(), 'import', '--new', str(tmp_path / 'again.gnucash'),
                   str(ledger), '--include-business-objects', '--atomic')

    assert rebuilt.exit_code == 0 and 'Errors:       0' in rebuilt.output, rebuilt.output
    assert _exported(tmp_path / 'again.gnucash', tmp_path).count('$pending$') == 3


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
