"""Editing a sale and re-importing it does not escape the cost-basis rules.

`--strategy update` is the path the tool itself recommends: `import` tells the
user to re-run with it whenever a GUID-matched transaction's content differs
("looks like an edit"). That is the export → edit → re-import loop, so every
rule that governs a sale on the way in has to govern it on the way back too.

Otherwise the guarantee is only skin deep: a sale of 40.00 USD against a
100.00 USD cost basis can be edited to 400.00 USD and re-imported cleanly, leaving
the cost basis claiming a balance that the book's own transactions contradict.
"""

import re
from fractions import Fraction
from pathlib import Path

import pytest
from click.testing import CliRunner

from cli.main import cli
from infrastructure.gnucash.utils import find_account
from repositories.gnucash_repository import GnuCashRepository, SessionMode
from services.foreign_currency import cost_basis_balance_of


def _book_with_a_partial_sale(tmp_path):
    """100 USD bought at 1.35, then 40 of it sold — 60.00 of balance left."""
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    result = runner.invoke(cli, [
        'import', '--new', str(book),
        'tests/fixtures/fx_buy_and_borrow_usd.txt'])
    assert result.exit_code == 0, result.output

    exported = _exported(runner, book, tmp_path / 'bases.txt')
    basis = re.findall(
        r'Assets:Bank:USD 100\.00 USD\n\t+guid: "([0-9a-f]{32})"', exported)[0]

    sale = tmp_path / 'sale.txt'
    sale.write_text(Path('tests/fixtures/fx_sell_usd_partial.txt')
                    .read_text().replace('{basis_a}', basis))
    result = runner.invoke(cli, ['import', str(book), str(sale)])
    assert result.exit_code == 0, result.output
    return runner, book


def _exported(runner, book, path):
    result = runner.invoke(cli, ['export', str(book), str(path)])
    assert result.exit_code == 0, result.output
    return path.read_text()


def _balance_on_the_basis(book):
    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        account = find_account(repo.book.get_root_account(), 'Assets:Bank:USD')
        for split in account.GetSplitList():
            balance = cost_basis_balance_of(split)
            if balance is not None:
                return balance
    finally:
        repo.close()
    return None


def test_editing_a_sale_beyond_its_basis_is_refused_on_reimport(tmp_path):
    """The same refusal a fresh import gives, on the edit path.

    Selling more of a cost basis than its balance is refused when the sale is
    written; re-importing an edited copy of that sale must be refused for the
    same reason, or the check is one an editor walks straight past.
    """
    runner, book = _book_with_a_partial_sale(tmp_path)
    before = _balance_on_the_basis(book)
    assert before is not None, 'the fixture should leave a cost basis with a balance'

    edited = tmp_path / 'edited.txt'
    text = _exported(runner, book, tmp_path / 'out.txt')
    assert '-40.00 USD' in text, text
    edited.write_text(text.replace('-40.00 USD', '-400.00 USD'))

    result = runner.invoke(cli, ['import', str(book), str(edited),
                                 '--strategy', 'update'])

    after = _balance_on_the_basis(book)
    # Refused for the right reason — the cost basis — and pointed at the route
    # that does work: delete the transaction (which gives the cost basis back what
    # it took) and import the new version, where every check runs again.
    assert 'cost basis' in result.output, (
        f'a sale of 400.00 USD against a cost basis holding {before} USD was not '
        f'refused:\n{result.output}')
    assert 'delete-transactions' in result.output, result.output
    assert after == before, (
        f'the cost basis moved from {before} to {after} on a refused edit')


def test_editing_only_a_description_on_such_a_transaction_is_accepted(tmp_path):
    """What a cost basis rests on is the figures, not the prose.

    A memo or description cannot change what a cost basis holds or what it cost, so
    editing one on a sale is ordinary bookkeeping and goes through — refusing
    it would make every cost-basis transaction unamendable for a typo.
    """
    runner, book = _book_with_a_partial_sale(tmp_path)
    before = _balance_on_the_basis(book)

    edited = tmp_path / 'edited.txt'
    text = _exported(runner, book, tmp_path / 'out.txt')
    assert 'Sell 40 USD' in text, text
    edited.write_text(text.replace('Sell 40 USD', 'Sell 40 USD (Q1 wire)'))

    result = runner.invoke(cli, ['import', str(book), str(edited),
                                 '--strategy', 'update'])
    assert result.exit_code == 0, result.output
    assert 'cost basis' not in result.output, result.output

    after_text = _exported(runner, book, tmp_path / 'after.txt')
    assert 'Sell 40 USD (Q1 wire)' in after_text, after_text
    assert _balance_on_the_basis(book) == before


def test_an_update_that_brings_in_currency_opens_its_basis(tmp_path):
    """Currency arriving through an edit opens a cost basis like any other.

    `create_transaction` opens a cost basis for what a transaction brings in;
    `update_transaction` did not, so correcting a placeholder into a USD
    holding left it listed as `none recorded` — over a message saying this tool
    had never written that split, which it had just written — and the currency
    could not be sold until the user hand-wrote a balance for it.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    result = runner.invoke(cli, [
        'import', '--new', str(book),
        'tests/fixtures/cad_transaction_before_becoming_usd.txt'])
    assert result.exit_code == 0, result.output
    assert 'No foreign-currency cost bases found' in runner.invoke(
        cli, ['fx-balances', str(book)]).output

    # The transaction had no foreign currency in it; the edit gives it some.
    text = _exported(runner, book, tmp_path / 'out.txt')
    guid = re.search(r'To be corrected into a USD purchase"\n\tguid: "([0-9a-f]{32})"',
                     text).group(1)
    edited = tmp_path / 'edited.txt'
    edited.write_text(
        '2026-01-10 * "Corrected into a USD purchase"\n'
        f'\tguid: "{guid}"\n'
        '\tcurrency.mnemonic: "CAD"\n'
        '\tAssets:Bank:USD 100.00 USD\n'
        '\t\taccount.commodity.mnemonic: "USD"\n'
        '\t\tshare_price: "1.35"\n'
        '\t\tvalue: "135.00"\n'
        '\tAssets:Bank -135.00 CAD\n'
        '\t\taccount.commodity.mnemonic: "CAD"\n')

    result = runner.invoke(cli, ['import', str(book), str(edited),
                                 '--strategy', 'update'])
    assert result.exit_code == 0, result.output

    listing = runner.invoke(cli, ['fx-balances', str(book)]).output
    assert 'none recorded' not in listing, listing
    assert 'Total USD cost basis balance: 100.00' in listing, listing


@pytest.mark.parametrize('stated', [
    '1.35',                 # no direction at all
    '1.35 USD/CAD',         # stated the wrong way round
    'abc CAD/USD',          # not a number
    '-1.35 CAD/USD',        # not positive
])
def test_a_refused_update_leaves_the_transaction_alone(tmp_path, stated):
    """A refusal must not land half the edit.

    The cost-basis work an update triggers happens after `CommitEdit`, and a
    rollback cannot undo a committed edit — so a failure there reported an
    error while the rewritten transaction stayed on disk: new splits, a
    poisoned KVP, and no cost basis balance, which is exactly the unrecorded
    state the work exists to prevent. A stated cost is checked before anything
    is written, so the refusal leaves the book as it was.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    result = runner.invoke(cli, [
        'import', '--new', str(book),
        'tests/fixtures/cad_transaction_before_becoming_usd.txt'])
    assert result.exit_code == 0, result.output

    text = _exported(runner, book, tmp_path / 'out.txt')
    guid = re.search(r'To be corrected into a USD purchase"\n\tguid: "([0-9a-f]{32})"',
                     text).group(1)
    edited = tmp_path / 'edited.txt'
    edited.write_text(
        '2026-01-10 * "Corrected into a USD purchase"\n'
        f'\tguid: "{guid}"\n'
        '\tcurrency.mnemonic: "CAD"\n'
        '\tAssets:Bank:USD 100.00 USD\n'
        '\t\taccount.commodity.mnemonic: "USD"\n'
        '\t\tshare_price: "1.35"\n'
        '\t\tvalue: "135.00"\n'
        f'\t\tcost_basis_cost: "{stated}"\n'     # refused, every way it can be
        '\tAssets:Bank -135.00 CAD\n'
        '\t\taccount.commodity.mnemonic: "CAD"\n')

    result = runner.invoke(cli, ['import', str(book), str(edited),
                                 '--strategy', 'update'])
    assert 'cost_basis_cost' in result.output, result.output

    # The book still holds what it held: the edit did not land.
    after = _exported(runner, book, tmp_path / 'after.txt')
    assert 'To be corrected into a USD purchase' in after, after
    assert 'Assets:Bank:USD' not in after.split('2026-01-10 *')[1], after


def test_correcting_a_sign_error_opens_the_basis_it_creates(tmp_path):
    """A cost basis can arrive by correcting a split, not only by adding one.

    Splits are matched by account, so fixing reversed signs reuses the very
    same split — same guid — and it becomes a purchase where it was not one
    before. Skipping every split that existed before the edit left that
    currency `none recorded`, over a message saying this tool never wrote the
    split. What matters is whether it was a cost basis before, not whether it
    existed.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    result = runner.invoke(cli, [
        'import', '--new', str(book),
        'tests/fixtures/usd_purchase_with_sign_error.txt'])
    assert result.exit_code == 0, result.output
    assert 'No foreign-currency cost bases found' in runner.invoke(
        cli, ['fx-balances', str(book)]).output

    text = _exported(runner, book, tmp_path / 'out.txt')
    guid = re.search(r'Buy 100 USD at 1\.35"\n\tguid: "([0-9a-f]{32})"', text).group(1)
    edited = tmp_path / 'edited.txt'
    edited.write_text(
        '2026-01-10 * "Buy 100 USD at 1.35"\n'
        f'\tguid: "{guid}"\n'
        '\tcurrency.mnemonic: "CAD"\n'
        '\tAssets:Bank:USD 100.00 USD\n'
        '\t\taccount.commodity.mnemonic: "USD"\n'
        '\t\tshare_price: "1.35"\n'
        '\t\tvalue: "135.00"\n'
        '\tAssets:Bank -135.00 CAD\n'
        '\t\taccount.commodity.mnemonic: "CAD"\n')

    result = runner.invoke(cli, ['import', str(book), str(edited),
                                 '--strategy', 'update'])
    assert result.exit_code == 0, result.output

    listing = runner.invoke(cli, ['fx-balances', str(book)]).output
    assert 'none recorded' not in listing, listing
    assert 'Total USD cost basis balance: 100.00' in listing, listing


def test_the_same_export_gives_the_same_balance_either_way_in(tmp_path):
    """`--new` and `--strategy update` agree about the same file.

    Both paths note that a stated balance is already net of the file's own
    sales, so neither lowers it again. This covers the case where every
    transaction in the file still exists in the book; a cost basis whose sale has
    since been deleted and is then re-imported is covered by
    `test_deleting_a_sale_then_reimporting_under_update_is_refused`, and what
    a file can do with a stated balance whose transaction is lost by
    `test_a_balance_stated_on_a_lost_transaction_reaches_no_later_sale`.
    """
    runner, book = _book_with_a_partial_sale(tmp_path)
    text = _exported(runner, book, tmp_path / 'out.txt')
    assert 'cost_basis_balance: "60.00"' in text, text

    fresh = tmp_path / 'fresh.gnucash'
    result = runner.invoke(cli, ['import', '--new', str(fresh),
                                 str(tmp_path / 'out.txt')])
    assert result.exit_code == 0, result.output
    into_fresh = _balance_on_the_basis(fresh)

    result = runner.invoke(cli, ['import', str(book), str(tmp_path / 'out.txt'),
                                 '--strategy', 'update'])
    assert result.exit_code == 0, result.output
    over_itself = _balance_on_the_basis(book)

    assert over_itself == into_fresh, (
        f'the same file gives {into_fresh} USD into a fresh book and '
        f'{over_itself} USD re-imported over its own')


def test_an_update_that_writes_a_prepayment_puts_it_in_its_owner_s_lot(tmp_path):
    """`lot_owner:` has to mean the same thing on both ways in.

    A receivable credit is a prepayment — currency owed back, and a cost basis
    — when it sits in an owner lot no invoice owns, and `lot_owner:` is what
    puts it there. Only the create path acted on it, so an update that wrote
    such a split dropped the line silently: the split landed in no lot, read
    as a settlement, and the currency the same file gives a cost basis through
    `--new` got no balance with no error to say so.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    result = runner.invoke(cli, [
        'import', '--new', str(book),
        'tests/fixtures/cad_transaction_before_becoming_a_prepayment.txt',
        '--include-business-objects'])
    assert result.exit_code == 0, result.output

    text = _exported(runner, book, tmp_path / 'out.txt')
    guid = re.search(r'corrected into a customer prepayment"\n\tguid: "([0-9a-f]{32})"',
                     text).group(1)
    edited = tmp_path / 'edited.txt'
    edited.write_text(
        '2026-02-01 * "Customer prepaid 100 USD, arriving as CAD"\n'
        f'\tguid: "{guid}"\n'
        '\tcurrency.mnemonic: "CAD"\n'
        '\tAssets:Bank 137.00 CAD\n'
        '\t\taccount.commodity.mnemonic: "CAD"\n'
        '\tAssets:Accounts Receivable USD -100.00 USD\n'
        '\t\taccount.commodity.mnemonic: "USD"\n'
        '\t\tshare_price: "1.37"\n'
        '\t\tvalue: "-137.00"\n'
        '\t\tlot_owner: "customer:C-US"\n')

    result = runner.invoke(cli, ['import', str(book), str(edited),
                                 '--strategy', 'update'])
    assert result.exit_code == 0, result.output

    listing = runner.invoke(cli, ['fx-balances', str(book)]).output
    assert 'Total USD cost basis balance: 100.00' in listing, listing
    assert 'Accounts Receivable USD' in listing, listing

    # And the lot is really there, not merely inferred from the listing: the
    # export reads it back out, with the owner guid the lot now carries, and
    # the account reports an open credit against that customer.
    after = _exported(runner, book, tmp_path / 'after.txt')
    assert 'lot_owner: customer:C-US:' in after, after
    assert 'open_prepayment:' in after, after


def test_a_balance_stated_on_a_lost_transaction_reaches_no_later_sale(tmp_path):
    """Why noting a stated balance after the commit cannot be observed.

    "This cost basis's balance came from the file" is module state that no rollback
    undoes, so it is noted once the transaction commits rather than while its
    splits are written. Noted too early, a transaction that then failed would
    still have told the sales below it to leave that cost basis alone — and this is
    the test that no file can arrange it.

    Both routes are closed. On the create path the cost basis goes down with its
    transaction, guid and all, so the sale that names it is refused for a
    basis the book does not have. On the update path a file has to carry a
    `guid:` on every transaction, so it cannot hold both a failing edit and a
    fresh sale — the fresh sale has no guid to carry, and one taken from
    elsewhere names a transaction the book does not hold.

    The ordering therefore changes no outcome; it is kept because what makes
    it unobservable is those two refusals, not anything about the note itself.
    """
    runner = CliRunner()
    created = tmp_path / 'created'
    created.mkdir()
    book = created / 'book.gnucash'
    result = runner.invoke(
        cli, ['import', '--new', str(book),
              'tests/fixtures/fx_stated_balance_on_a_failing_transaction.txt'])

    assert 'txn_type' in result.output, result.output
    assert 'matches no split in the book' in result.output, result.output
    assert 'Errors:       2' in result.output, result.output

    listing = runner.invoke(cli, ['fx-balances', str(book)]).output
    assert 'No foreign-currency cost bases found' in listing, listing

    # The update route, on a book that does hold a cost basis: a file it would take
    # is one with a guid on every transaction, which a newly written sale has
    # nothing to put there.
    runner, book = _book_with_a_partial_sale(tmp_path)
    text = _exported(runner, book, tmp_path / 'out.txt')
    basis = re.findall(
        r'Assets:Bank:USD 100\.00 USD\n\t+guid: "([0-9a-f]{32})"', text)[0]
    before = _balance_on_the_basis(book)

    edited = tmp_path / 'edited.txt'
    edited.write_text(
        text.replace('2026-01-10 * "Buy 100 USD at 1.35"\n',
                     '2026-01-10 * "Buy 100 USD at 1.35"\n\ttxn_type: Z\n')
        + Path('tests/fixtures/fx_sell_usd_partial.txt').read_text()
        .replace('{basis_a}', basis))

    result = runner.invoke(cli, ['import', str(book), str(edited),
                                 '--strategy', 'update'])
    assert 'requires a guid' in result.output, result.output
    assert _balance_on_the_basis(book) == before, result.output


def test_deleting_a_sale_then_reimporting_under_update_is_refused(tmp_path):
    """Deleting a sale and re-importing its file cannot double-count it.

    The worry was that the cost basis transaction would take the update path while
    the deleted sale was created afresh and lowered the stated balance a second
    time, leaving the cost basis 40.00 short. It cannot happen by this route:
    `--strategy update` refuses a transaction the book no longer holds instead
    of creating it, so the file is rejected and the cost basis keeps what the
    deletion gave back.
    """
    runner, book = _book_with_a_partial_sale(tmp_path)
    text = _exported(runner, book, tmp_path / 'out.txt')
    assert 'cost_basis_balance: "60.00"' in text, text

    sale_guid = re.search(r'Sell 40 USD"\n\tguid: "([0-9a-f]{32})"', text).group(1)
    result = runner.invoke(cli, ['delete-transactions', str(book),
                                 sale_guid, '--by-guid'])
    assert result.exit_code == 0, result.output
    assert _balance_on_the_basis(book) == Fraction(100), 'delete should restore it'

    result = runner.invoke(cli, ['import', str(book), str(tmp_path / 'out.txt'),
                                 '--strategy', 'update'])

    # The route is closed, and that is the finding: `--strategy update` refuses
    # a transaction whose guid the book no longer holds rather than creating
    # it, so the deleted sale cannot come back this way and cannot lower the
    # stated balance a second time. The cost basis keeps what deleting the sale gave
    # back to it.
    assert 'not found in book' in result.output, result.output
    assert _balance_on_the_basis(book) == Fraction(100), (
        f'the cost basis moved to {_balance_on_the_basis(book)} on an import that '
        f'refused the only transaction that could have moved it')


def test_a_cost_stated_on_a_base_currency_split_is_refused_both_ways_in(tmp_path):
    """The same file cannot mean one thing on create and another on update.

    `cost_basis_cost:` on a CAD split states what a unit of CAD cost in CAD.
    Nothing reads it — the split establishes no cost basis — so it is refused, and
    refused identically whichever way the file arrives. Checked only on the
    update path, the line was an error there and an inert KVP through `--new`.
    """
    runner = CliRunner()
    fixture = 'tests/fixtures/stated_cost_on_a_base_currency_split.txt'

    book = tmp_path / 'book.gnucash'
    fresh = runner.invoke(cli, ['import', '--new', str(book), fixture])
    assert 'cost_basis_cost' in fresh.output, fresh.output
    assert 'Assets:Bank' in fresh.output, fresh.output
    assert 'Errors:       1' in fresh.output, fresh.output

    # And on the update path, against a book that already holds the purchase.
    clean = tmp_path / 'clean.gnucash'
    result = runner.invoke(cli, ['import', '--new', str(clean),
                                 'tests/fixtures/fx_buy_and_borrow_usd.txt'])
    assert result.exit_code == 0, result.output
    text = _exported(runner, clean, tmp_path / 'out.txt')
    guid = re.search(r'Buy 100 USD at 1\.35"\n\tguid: "([0-9a-f]{32})"', text).group(1)

    edited = tmp_path / 'edited.txt'
    edited.write_text(
        Path(fixture).read_text()
        .replace('2026-01-10 * "Buy 100 USD at 1.35"\n',
                 f'2026-01-10 * "Buy 100 USD at 1.35"\n\tguid: "{guid}"\n'))
    updated = runner.invoke(cli, ['import', str(clean), str(edited),
                                  '--strategy', 'update'])
    assert 'cost_basis_cost' in updated.output, updated.output


def test_a_stated_cost_cannot_contradict_the_transaction_that_carries_one(tmp_path):
    """Two answers to one question, and the file's would win.

    `cost_of` reads a stated cost before deriving one, so `cost_basis_cost:
    "9.99 CAD/USD"` on a split the transaction prices at 1.35 is what
    `fx-balances` reports and what every later sale is checked against. The
    tool never writes such a line — a cost is stored only where the
    transaction cannot state one — and a file that writes it is refused for
    the same reason, rather than quietly overriding the book's own figures.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    result = runner.invoke(
        cli, ['import', '--new', str(book),
              'tests/fixtures/stated_cost_contradicting_the_transaction.txt'])

    assert 'cost_basis_cost' in result.output, result.output
    assert '9.99' in result.output, result.output
    assert 'Errors:       1' in result.output, result.output

    listing = runner.invoke(cli, ['fx-balances', str(book)]).output
    assert '9.99' not in listing, listing
    assert 'No foreign-currency cost bases found' in listing, listing


def test_a_stated_cost_is_refused_by_what_the_transaction_prices_not_by_keys(tmp_path):
    """The guard reads the transaction, not which lines the file typed.

    A split in a base-currency transaction is valued whether or not the file
    says so — with no `value:` it is valued at its own amount — so the
    transaction prices it and a stated cost is a second answer. Testing for a
    `value:` or `share_price:` line instead let exactly that through: the KVP
    was written, `cost_of` then ignored it because the derived cost wins, and
    the book was left stating one cost and using another, which is the drift
    this refusal exists to make impossible.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    result = runner.invoke(
        cli, ['import', '--new', str(book),
              'tests/fixtures/stated_cost_without_a_value_line.txt'])

    assert 'cost_basis_cost' in result.output, result.output
    assert 'Errors:       1' in result.output, result.output

    listing = runner.invoke(cli, ['fx-balances', str(book)]).output
    assert 'No foreign-currency cost bases found' in listing, listing


def test_an_update_reads_the_transactions_currency_when_the_file_omits_it(tmp_path):
    """`currency.mnemonic:` is stated to *change* a currency, not to repeat it.

    A file that leaves it out keeps whatever the transaction already has, so
    reading the file alone to decide whether the transaction can price a split
    answers for a transaction that does not exist. On a CAD-denominated
    purchase edited without that line, it answered "no base-currency side" and
    let a stated cost through — written, then ignored by `cost_of`, which is
    the drift the check exists to prevent.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    result = runner.invoke(cli, [
        'import', '--new', str(book),
        'tests/fixtures/fx_buy_and_borrow_usd.txt'])
    assert result.exit_code == 0, result.output

    text = _exported(runner, book, tmp_path / 'out.txt')
    guid = re.search(r'Buy 100 USD at 1\.35"\n\tguid: "([0-9a-f]{32})"', text).group(1)

    # The same transaction, its currency unstated, with a cost on the USD
    # split. The CAD split is still there and still prices it.
    edited = tmp_path / 'edited.txt'
    edited.write_text(
        '2026-01-10 * "Buy 100 USD at 1.35"\n'
        f'\tguid: "{guid}"\n'
        '\tAssets:Bank:USD 100.00 USD\n'
        '\t\taccount.commodity.mnemonic: "USD"\n'
        '\t\tshare_price: "1.35"\n'
        '\t\tvalue: "135.00"\n'
        '\t\tcost_basis_cost: "9.99 CAD/USD"\n'
        '\tAssets:Bank -135.00 CAD\n'
        '\t\taccount.commodity.mnemonic: "CAD"\n')

    result = runner.invoke(cli, ['import', str(book), str(edited),
                                 '--strategy', 'update'])
    assert 'cost_basis_cost' in result.output, result.output
    assert 'already prices' in result.output, result.output

    # And the book is as it was: no copy written, the transaction's own figure
    # still the cost.
    listing = runner.invoke(cli, ['fx-balances', str(book)]).output
    assert '1.35 CAD/USD' in listing, listing
    assert '9.99' not in listing, listing
