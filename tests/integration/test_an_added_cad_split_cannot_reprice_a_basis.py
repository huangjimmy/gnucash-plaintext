"""An update may not add a CAD split that re-prices a cost basis.

Where a transaction is stated in a foreign currency, the cost of what it
brought in comes from its CAD splits: their amounts added up, divided by what
those amounts are worth added up. So a CAD split the file *adds* moves the
cost, exactly as changing one would.

`_require_no_cost_basis_edit` compares what a cost basis rests on before and
after. It reads the accounts to compare from the transaction the book holds,
which is right for the splits already there and wrong for a new one: an added
split is on an account that transaction has never seen, so it was dropped from
the comparison, the two sides matched, and the edit went through. The cost basis
was then priced at a figure nobody stated.

Removal was always caught, because the removed split is on the booked side.
"""

import re
from pathlib import Path

import pytest
from click.testing import CliRunner

from cli.main import cli
from tests.conftest import _run

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
    """The currency a transaction is stated in prices the cost basis as much as any
    figure does, and every figure can be left where it is.

    `cost_of` reads a CAD-stated transaction as value over amount and a
    foreign-stated one through its CAD splits, so moving `currency.mnemonic:`
    from USD to CAD re-prices this cost basis from 25/18 to 1 — 100.00 over 100.00
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


def test_under_atomic_a_re_price_the_file_states_in_full_is_allowed(tmp_path):
    """Where every figure can be read, the deferral does what it is for.

    `--atomic` defers the refusal to edit a transaction a cost basis rests on,
    because a repair passes through states it stops in either order. What it
    reads before granting that is the figures the file states. Each added
    split states both its amounts, so its price is the one they give, and the
    file says what the transaction is to become: the refusal is deferred to
    the finished book. A re-priced cost basis is caught there by the sales
    measured against it — this one has none, so nothing contradicts the
    figures the file asked for and they stand, at 190.00 CAD over 140.00 USD,
    19/14. That is the flag working as designed, and it is stated here rather
    than left between two files, since the rest of this one is about the same
    edit being refused.
    """
    runner = CliRunner()
    book, text = _book_and_export(runner, tmp_path)
    assert _cost_of_the_basis(runner, book) == '25/18'

    edited = tmp_path / 'edited.txt'
    edited.write_text(
        _accounts_for(text)
        + _the_transaction(text)
        + _without_comments(Path(ADDED_CAD_SPLITS).read_text()))

    result = _run(runner, 'import', str(book), str(edited), '--atomic',
                  '--strategy', 'update')
    assert result.exit_code == 0, result.output
    assert 'Changes saved' in result.output, result.output
    assert _cost_of_the_basis(runner, book) == '19/14'

    verified = _run(runner, 'fx-balances', str(book), '--verify-costs')
    assert verified.exit_code == 0, verified.output


@pytest.mark.parametrize('price, refusal', [
    ('0.9', "the file states 10.00 CAD on 'Expenses:Bank Fees' valued at 9.00"),
    ('abc', "the share_price on split 'Expenses:Bank Fees' must be a number, got 'abc'"),
], ids=['another-price', 'not-a-number'])
def test_a_price_stated_without_a_value_is_weighed_on_its_own(tmp_path, price, refusal):
    """The fee split with its `value:` taken off and a `share_price:` of its own.

    With one amount and the price, the price is what values the split, so it is
    the figure the cost basis would rest on: 0.9 is not the 4/5 the book holds,
    and re-prices the cost basis, which cannot be done in place. The refusal
    gives the split at the value the edit would write, 10.00 at 0.9. `abc` cannot be
    read at all, and is refused as a figure that is not a number.
    """
    runner = CliRunner()
    book, text = _book_and_export(runner, tmp_path)
    before = _cost_of_the_basis(runner, book)
    transaction = _the_transaction(text)
    fee = re.search(r'\tExpenses:Bank Fees 10\.00 CAD\n(?:\t\t[^\n]*\n)*', transaction).group(0)
    kept = ''.join(line + '\n' for line in fee.splitlines()
                   if not line.startswith(('\t\tvalue:', '\t\tshare_price:')))
    edited = tmp_path / 'edited.txt'
    edited.write_text(transaction.replace(fee, kept + f'\t\tshare_price: "{price}"\n'))

    result = _run(runner, 'import', str(book), str(edited), '--strategy', 'update')

    message = result.output + str(result.exception)
    assert result.exit_code != 0, message
    assert refusal in message, message
    assert _cost_of_the_basis(runner, book) == before


@pytest.mark.parametrize('edits, refusal', [
    ([('\tExpenses:Bank Fees 10.00 CAD\n', '\tExpenses:Bank Fees $residual$ CAD\n')],
     "the amount on split 'Expenses:Bank Fees' must be a number, got '$residual$'"),
    ([('\t\tvalue: "8.00"\n', '\t\tvalue: "eight"\n')],
     "the value on split 'Expenses:Bank Fees' must be a number, got 'eight'"),
    ([('\tExpenses:Bank Fees 10.00 CAD\n', '\tExpenses:Bank Fees 12.00 CAD\n'),
      ('\t\tvalue: "8.00"\n', '')], 'cannot be edited in place'),
    ([('\tExpenses:Bank Fees 10.00 CAD\n', '\tExpenses:Bank Fees --10.00 CAD\n')],
     "the amount on split 'Expenses:Bank Fees' must be a number, got '--10.00'"),
    ([('\tExpenses:Bank Fees 10.00 CAD\n', '\tExpenses:Bank Fees 1O.00 CAD\n')],
     'could not be read'),
], ids=['a-residual-amount', 'a-value-that-is-not-a-number', 'a-new-amount-with-no-value',
        'an-amount-with-two-signs', 'an-amount-that-is-not-a-number'])
def test_a_fee_split_whose_figures_cannot_be_weighed_is_refused(tmp_path, edits, refusal):
    """The fee split edited so what the cost basis would rest on cannot be read.

    A `$residual$` amount, a value that is not a number and an amount with two
    signs are figures the edit cannot apply, and each is refused for itself,
    the split and the field given. A new amount with no value to go with it is
    applied, re-prices the cost basis, and cannot be edited in place. An amount
    that is not a number is a line the parser cannot read, and the file is
    refused before anything is compared. Measured on 5.10 and 3.4.
    """
    runner = CliRunner()
    book, text = _book_and_export(runner, tmp_path)
    before = _cost_of_the_basis(runner, book)
    transaction = _the_transaction(text)
    edited_text = transaction
    for old, new in edits:
        assert old in edited_text, edited_text
        edited_text = edited_text.replace(old, new)
    edited = tmp_path / 'edited.txt'
    edited.write_text(edited_text)

    result = _run(runner, 'import', str(book), str(edited), '--strategy', 'update')

    message = result.output + str(result.exception)
    assert result.exit_code != 0, message
    assert refusal in message, message
    assert _cost_of_the_basis(runner, book) == before


def test_under_atomic_two_added_zero_amount_cad_splits_leave_the_cost_basis_as_it_was(tmp_path):
    """Two 0.00 CAD splits, each stating a value of 0.00 and no price.

    A split of no amount has no price its two amounts give, and GnuCash's own
    answer for one differs by version (0 on 5.10 and 1 on 3.4, for a value of
    0.00), so the figures the edit changes could not be weighed one by one, and
    the edit was refused. What decides it is the cost basis itself, read once
    the edit is applied: the CAD splits' amounts and values added up are what
    they were, so the cost basis costs what it cost and the edit goes through.
    """
    runner = CliRunner()
    book, text = _book_and_export(runner, tmp_path)
    before = _cost_of_the_basis(runner, book)
    added = _without_comments(Path(ADDED_CAD_SPLITS).read_text())
    for written in ('20.00 CAD', 'value: "16.00"', 'value: "-16.00"'):
        assert written in added, added
    nothing = (added.replace('20.00 CAD', '0.00 CAD')
               .replace('value: "16.00"', 'value: "0.00"')
               .replace('value: "-16.00"', 'value: "0.00"'))
    edited = tmp_path / 'edited.txt'
    edited.write_text(_accounts_for(text) + _the_transaction(text) + nothing)

    result = _run(runner, 'import', str(book), str(edited), '--atomic',
                  '--strategy', 'update')

    assert result.exit_code == 0, result.output
    assert 'Changes saved' in result.output, result.output
    assert _cost_of_the_basis(runner, book) == before


def test_under_atomic_a_price_beside_both_amounts_changes_nothing_they_give(tmp_path):
    """The same two splits with `share_price: "1"` beside their values.

    Each states both its amounts, 20.00 CAD valued 16.00, so the price is the
    one those two give. The stated 1 would value them at 20.00 and the cost
    basis at 190.00 over 148.00, 95/74. It is warned about and the two amounts
    decide, so the cost basis is 19/14, as without the line.
    """
    runner = CliRunner()
    book, text = _book_and_export(runner, tmp_path)

    added = _without_comments(Path(ADDED_CAD_SPLITS).read_text()).replace(
        '\t\tvalue:', '\t\tshare_price: "1"\n\t\tvalue:')
    edited = tmp_path / 'edited.txt'
    edited.write_text(_accounts_for(text) + _the_transaction(text) + added)

    result = _run(runner, 'import', str(book), str(edited), '--atomic',
                  '--strategy', 'update')
    assert result.exit_code == 0, result.output
    assert 'the price is the one the two amounts give' in result.output, result.output
    assert _cost_of_the_basis(runner, book) == '19/14'

    verified = _run(runner, 'fx-balances', str(book), '--verify-costs')
    assert verified.exit_code == 0, verified.output


def test_adding_a_foreign_split_to_a_cad_stated_transaction_is_refused(tmp_path):
    """The mirror of the case above, on a transaction stated in CAD.

    The accounts to compare are read from the transaction the book holds, so a
    split on an account it has never used falls outside them — and where the
    transaction is stated in CAD, the rule that catches an added CAD split
    does not apply either. Left out, an update could append 60.00 EUR to a
    purchase holding a USD cost basis and be accepted, and no cost basis would
    open for those euros. The listing would show them reading `none recorded`
    — currency the book holds that nothing can sell — and the per-currency
    totals leave such a cost basis out of both sides, so nothing would report it.
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
