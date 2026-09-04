"""An update may not add a CAD split that re-prices a cost basis.

Where a transaction is stated in a foreign currency, the cost of what it
brought in comes from its CAD splits: their amounts added up, divided by what
those amounts are worth added up. So a CAD split the file *adds* moves the
cost, exactly as changing one would.

`_require_no_cost_basis_edit` compares what a cost basis rests on before and
after. It reads the accounts to compare from the transaction the book holds,
which is right for the splits already there and wrong for a new one: an added
split is on an account that transaction has never seen, so it was dropped from
the comparison, the two sides matched, and the edit went through. The basis
was then priced at a figure nobody stated.

Removal was always caught, because the removed split is on the booked side.
"""

import re
import time
from pathlib import Path

from click.testing import CliRunner

from cli.main import cli

ADDED_CAD_SPLITS = 'tests/fixtures/fx_two_cad_splits_added_to_a_transaction.txt'


def _without_comments(text: str) -> str:
    """The fixture's split lines alone.

    It is a fragment appended under a transaction the export wrote, so its
    header comment cannot travel with it — a `#` line between splits ends the
    transaction.
    """
    return ''.join(line for line in text.splitlines(keepends=True)
                   if not line.startswith('#'))

FIXTURE = 'tests/fixtures/fx_two_base_splits_at_different_rates.txt'


def _run(runner, *args):
    time.sleep(1.1)
    return runner.invoke(cli, list(args))


def _book_and_export(runner, tmp_path):
    book = tmp_path / 'book.gnucash'
    result = runner.invoke(cli, ['import', '--new', str(book), FIXTURE])
    assert result.exit_code == 0, result.output
    out = tmp_path / 'out.txt'
    result = _run(runner, 'export', str(book), str(out))
    assert result.exit_code == 0, result.output
    return book, out.read_text()


def _cost_of_the_basis(runner, book):
    result = _run(runner, 'fx-balances', str(book))
    assert result.exit_code == 0, result.output
    row = next(line for line in result.output.splitlines()
               if 'CAD/USD' in line)
    return re.search(r'(\S+) CAD/USD', row).group(1)


def _accounts_for(text):
    """The `open` blocks, so a new account can be declared alongside the edit."""
    return ('2026-01-01 open Expenses:Other\n'
            '\ttype: Expense\n'
            '\tcommodity.namespace: "CURRENCY"\n'
            '\tcommodity.mnemonic: "CAD"\n'
            '2026-01-01 open Income:Misc\n'
            '\ttype: Income\n'
            '\tcommodity.namespace: "CURRENCY"\n'
            '\tcommodity.mnemonic: "CAD"\n\n')


def _the_transaction(text):
    return re.search(r'2026-01-10 \* "100 USD in[^\n]*\n(?:\t[^\n]*\n)*',
                     text).group(0)


def test_the_basis_costs_what_the_fixture_says(tmp_path):
    """150.00 CAD over 108.00 USD, which is 25/18."""
    runner = CliRunner()
    book, _ = _book_and_export(runner, tmp_path)
    assert _cost_of_the_basis(runner, book) == '25/18'


def test_adding_a_cad_split_is_refused(tmp_path):
    """Every existing split is left alone; two new CAD splits are added.

    They balance each other, so the transaction is still sound, and neither
    gives a `cost_basis_split_guid:`. What they change is the cost: 190.00 CAD
    over 140.00 USD is 19/14, against the 25/18 the book holds.
    """
    runner = CliRunner()
    book, text = _book_and_export(runner, tmp_path)
    before = _cost_of_the_basis(runner, book)

    edited = tmp_path / 'edited.txt'
    edited.write_text(
        _accounts_for(text)
        + _the_transaction(text)
        + _without_comments(Path(ADDED_CAD_SPLITS).read_text()))

    result = _run(runner, 'import', str(book), str(edited),
                  '--strategy', 'update')
    message = result.output + str(result.exception)
    assert result.exit_code != 0, message
    assert 'cannot be edited in place' in message, message
    assert _cost_of_the_basis(runner, book) == before


def test_restating_the_transactions_own_currency_is_refused(tmp_path):
    """The currency a transaction is stated in prices the basis as much as any
    figure does, and every figure can be left where it is.

    `cost_of` reads a CAD-stated transaction as value over amount and a
    foreign-stated one through its CAD splits, so moving `currency.mnemonic:`
    from USD to CAD re-prices this basis from 25/18 to 1 — 100.00 over 100.00
    — with all four splits byte-identical. Compared on the splits alone the
    two sides matched and the edit went through.
    """
    runner = CliRunner()
    book, text = _book_and_export(runner, tmp_path)
    before = _cost_of_the_basis(runner, book)

    edited = tmp_path / 'edited.txt'
    restated = _the_transaction(text).replace('currency.mnemonic: "USD"',
                                              'currency.mnemonic: "CAD"')
    assert 'currency.mnemonic: "CAD"' in restated, restated
    edited.write_text(restated)

    result = _run(runner, 'import', str(book), str(edited),
                  '--strategy', 'update')
    message = result.output + str(result.exception)
    assert result.exit_code != 0, message
    assert 'cannot be edited in place' in message, message
    assert _cost_of_the_basis(runner, book) == before


def test_under_atomic_this_file_is_refused_for_the_figures_it_leaves_unread(tmp_path):
    """The deferral is granted on figures that can be read, and these cannot.

    `--atomic` defers the refusal to edit a transaction a cost basis rests on,
    because a repair passes through states it stops in either order. What it
    reads before granting that is the figures the file states, and a split the
    file *adds* states no `share_price:` — there is no booked one to fall back
    on either, the split being new — so what the basis would rest on
    afterwards cannot be worked out here at all. An unreadable directive is
    refused rather than deferred.
    """
    runner = CliRunner()
    book, text = _book_and_export(runner, tmp_path)
    before = _cost_of_the_basis(runner, book)

    edited = tmp_path / 'edited.txt'
    edited.write_text(
        _accounts_for(text)
        + _the_transaction(text)
        + _without_comments(Path(ADDED_CAD_SPLITS).read_text()))

    result = _run(runner, 'import', str(book), str(edited), '--atomic',
                  '--strategy', 'update')
    message = result.output + str(result.exception)
    assert result.exit_code != 0, message
    assert 'cannot be edited in place' in message, message
    assert 'Rolled back' in result.output, result.output
    assert _cost_of_the_basis(runner, book) == before


def test_under_atomic_a_re_price_the_file_states_in_full_is_allowed(tmp_path):
    """And where every figure is stated, the deferral does what it is for.

    The same two splits with a rate on each: the file says what the
    transaction is to become, the guard can read it, and the refusal is
    deferred to the finished book. A re-priced basis is caught there by the
    sales measured against it — this one has none, so nothing contradicts the
    figures the file asked for and they stand. That is the flag working as
    designed, and it is stated here rather than left between two files, since
    the rest of this one is about the same edit being refused.

    `share_price: "1"` is what those splits are then worth: 20.00 CAD each,
    rather than the 16.00 the fixture values them at, so the cost comes out at
    190.00 over 148.00 — 95/74 — and not the 19/14 the fixture's own figures
    would give. The rate is stated because a split the file adds has no booked
    one to fall back on, which is the refusal above.
    """
    runner = CliRunner()
    book, text = _book_and_export(runner, tmp_path)
    assert _cost_of_the_basis(runner, book) == '25/18'

    added = _without_comments(Path(ADDED_CAD_SPLITS).read_text()).replace(
        '\t\tvalue:', '\t\tshare_price: "1"\n\t\tvalue:')
    edited = tmp_path / 'edited.txt'
    edited.write_text(_accounts_for(text) + _the_transaction(text) + added)

    result = _run(runner, 'import', str(book), str(edited), '--atomic',
                  '--strategy', 'update')
    assert result.exit_code == 0, result.output
    assert 'Changes saved' in result.output, result.output
    assert _cost_of_the_basis(runner, book) == '95/74'

    verified = _run(runner, 'fx-balances', str(book), '--verify-costs')
    assert verified.exit_code == 0, verified.output


def test_adding_a_foreign_split_to_a_cad_stated_transaction_is_refused(tmp_path):
    """The mirror of the case above, on a transaction stated in CAD.

    The accounts to compare are read from the transaction the book holds, so a
    split on an account it has never used falls outside them — and where the
    transaction is stated in CAD, the rule that catches an added CAD split
    does not apply either. Left out, an update could append 60.00 EUR to a
    purchase holding a USD basis and be accepted, and no basis would open for
    those euros: `record_cost_bases` runs where a transaction is created, not
    where one is edited. The listing would show them reading `none recorded`
    — currency the book holds that nothing can sell — and the per-currency
    totals leave such a basis out of both sides, so nothing would report it.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    result = runner.invoke(cli, [
        'import', '--new', str(book),
        'tests/fixtures/fx_buy_100_usd_into_a_usd_bank.txt'])
    assert result.exit_code == 0, result.output
    assert _run(runner, 'import', str(book),
                'tests/fixtures/fx_buy_60_eur_at_the_same_rate.txt'
                ).exit_code == 0

    out = tmp_path / 'out.txt'
    assert _run(runner, 'export', str(book), str(out)).exit_code == 0
    purchase = re.search(r'2026-02-01 \* "Buy 100 USD"[^\n]*\n(?:\t[^\n]*\n)*',
                         out.read_text()).group(0)
    edited = tmp_path / 'edited.txt'
    edited.write_text(purchase
                      + '\tAssets:Bank:EUR 60.00 EUR\n'
                        '\t\taccount.commodity.mnemonic: "EUR"\n'
                        '\t\tshare_price: "1.40"\n'
                        '\t\tvalue: "84.00"\n'
                        '\tAssets:Bank -84.00 CAD\n'
                        '\t\taccount.commodity.mnemonic: "CAD"\n'
                        '\t\tshare_price: "1"\n'
                        '\t\tvalue: "-84.00"\n')

    result = _run(runner, 'import', str(book), str(edited),
                  '--strategy', 'update')
    message = result.output + str(result.exception)
    assert result.exit_code != 0, message
    assert 'cannot be edited in place' in message, message


def test_an_edit_that_adds_no_cad_split_is_still_allowed(tmp_path):
    """The narrowing this protects must survive: a description still edits."""
    runner = CliRunner()
    book, text = _book_and_export(runner, tmp_path)
    before = _cost_of_the_basis(runner, book)

    edited = tmp_path / 'edited.txt'
    edited.write_text(_the_transaction(text).replace(
        '100 USD in, with a CAD fee converted at another rate',
        '100 USD in, with a CAD fee (wire)'))

    result = _run(runner, 'import', str(book), str(edited),
                  '--strategy', 'update')
    assert result.exit_code == 0, result.output
    assert _cost_of_the_basis(runner, book) == before
