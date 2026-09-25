"""An update that adds or restates what prices a cost basis is read as the transaction would be read if it were new.

Where a transaction is stated in a foreign currency, the cost of what it
brought in comes from its CAD splits: their amounts added up, divided by what
those amounts are worth added up. So a CAD split the file *adds* moves the
cost, exactly as changing one would, and so does restating the currency the
transaction is stated in.

`_require_no_cost_basis_edit` compares what a cost basis rests on before and
after, and reads the accounts to compare from the transaction the book holds
and from the block, so an added split is compared too. Where anything a cost
basis rests on moves, the edit is read as a new transaction would be (Q-051):
the cost basis is priced at what the new version's figures give, where no
other transaction draws on it, and a new version that does not balance, or
whose figures cannot be read, is refused as a new import of it would be.
Where another transaction draws on the cost basis, the edit is refused, as
`test_a_repriced_basis_is_caught_under_its_sales.py` holds.
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


def test_adding_a_cad_split_re_prices_a_cost_basis_nothing_else_draws_on(tmp_path):
    """Every existing split is left alone; two new CAD splits are added.

    They balance each other, so the transaction is still sound, and neither
    gives a `cost_basis_split_guid:`. What they change is the cost: 190.00 CAD
    over 140.00 USD is 19/14, against the 25/18 the book held. No other
    transaction draws on the cost basis, so the new figures are its figures.
    """
    runner = CliRunner()
    book, text = _book_and_export(runner, tmp_path)

    edited = tmp_path / 'edited.txt'
    edited.write_text(
        _accounts_for(text)
        + _the_transaction(text)
        + _without_comments(Path(ADDED_CAD_SPLITS).read_text()))

    result = _run(runner, 'import', str(book), str(edited),
                  '--strategy', 'update')
    assert result.exit_code == 0, result.output + str(result.exception)
    assert _cost_of_the_basis(runner, book) == '19/14'
    verified = _run(runner, 'fx-balances', str(book), '--verify-costs')
    assert verified.exit_code == 0, verified.output


def test_restating_the_transactions_own_currency_re_prices_it(tmp_path):
    """The currency a transaction is stated in prices the cost basis as much as any
    figure does, and every figure can be left where it is.

    `cost_of` reads a CAD-stated transaction as value over amount and a
    foreign-stated one through its CAD splits, so moving `currency.mnemonic:`
    from USD to CAD re-prices this cost basis from 25/18 to 1 — 100.00 over
    100.00 — with all four splits byte-identical. Read as the transaction would
    be read if it were new, that is the price the file states.
    """
    runner = CliRunner()
    book, text = _book_and_export(runner, tmp_path)

    edited = tmp_path / 'edited.txt'
    restated = _the_transaction(text).replace('currency.mnemonic: "USD"',
                                              'currency.mnemonic: "CAD"')
    assert 'currency.mnemonic: "CAD"' in restated, restated
    edited.write_text(restated)

    result = _run(runner, 'import', str(book), str(edited),
                  '--strategy', 'update')
    assert result.exit_code == 0, result.output + str(result.exception)
    assert _cost_of_the_basis(runner, book) == '1'


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
    ('0.9', 'the new version of this transaction does not balance: its values '
            'come to 1.00 USD'),
    ('abc', "the share_price on split 'Expenses:Bank Fees' must be a number, got 'abc'"),
], ids=['another-price', 'not-a-number'])
def test_a_price_stated_without_a_value_is_weighed_on_its_own(tmp_path, price, refusal):
    """The fee split with its `value:` taken off and a `share_price:` of its own.

    With one amount and the price, the price is what values the split: 10.00
    at 0.9 is 9.00 where the book holds 8.00, and nothing else in the block
    moves, so the new version's values come to 1.00 USD. GnuCash would put
    that on an Imbalance account, and a new version that does not balance is
    refused. `abc` cannot be read at all, and is refused as a figure that is
    not a number.
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
     "$residual$ on 'Expenses:Bank Fees' is a CAD account but the transaction is in USD"),
    ([('\t\tvalue: "8.00"\n', '\t\tvalue: "eight"\n')],
     "the value on split 'Expenses:Bank Fees' must be a number, got 'eight'"),
    ([('\tExpenses:Bank Fees 10.00 CAD\n', '\tExpenses:Bank Fees 12.00 CAD\n'),
      ('\t\tvalue: "8.00"\n', '')],
     'the new version of this transaction does not balance: its values come to 1.60 USD'),
    ([('\tExpenses:Bank Fees 10.00 CAD\n', '\tExpenses:Bank Fees --10.00 CAD\n')],
     "the amount on split 'Expenses:Bank Fees' must be a number, got '--10.00'"),
    ([('\tExpenses:Bank Fees 10.00 CAD\n', '\tExpenses:Bank Fees 1O.00 CAD\n')],
     'could not be read'),
], ids=['a-residual-amount', 'a-value-that-is-not-a-number', 'a-new-amount-with-no-value',
        'an-amount-with-two-signs', 'an-amount-that-is-not-a-number'])
def test_a_fee_split_whose_figures_cannot_be_weighed_is_refused(tmp_path, edits, refusal):
    """The fee split edited so what the cost basis would rest on cannot be read.

    A value that is not a number and an amount with two signs are figures the
    edit cannot apply, and each is refused for itself, the split and the field
    given. `$residual$` on a Canadian dollar split of a transaction stated in
    US dollars is refused as the create path refuses it: the residual is a US
    dollar figure. A new amount with no value to go with it is valued at the
    amount, 12.00 where the book holds 8.00, so the new version's values come
    to 1.60 USD and it does not balance. An amount that is not a number is a
    line the parser cannot read, and the file is refused before anything is
    compared.
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


def test_adding_a_foreign_split_to_a_cad_stated_transaction_opens_its_cost_basis(tmp_path):
    """The mirror of the case above, on a transaction stated in CAD.

    60.00 EUR appended to a purchase holding a USD cost basis, bought for 84.00
    CAD. Read as a new transaction would be, the euros open a cost basis of
    their own, 60.00 EUR at 1.40, as an import of that purchase would open
    one. Accepted without being read so, they had none: the listing showed
    them `none recorded`, currency the book holds that nothing can sell.
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
    assert result.exit_code == 0, result.output + str(result.exception)
    listing = _run(runner, 'fx-balances', str(book)).output
    assert re.search(r'2026-02-01\s+\S+\s+Assets:Bank:EUR\s+1\.4 CAD/EUR\s+60\.00 EUR'
                     r'\s+60\.00 EUR', listing), listing
    verified = _run(runner, 'fx-balances', str(book), '--verify-costs')
    assert verified.exit_code == 0, verified.output


class TestWhereASaleDrawsOnTheCostBasis:
    """20.00 USD of the cost basis sold at 25/18: an edit moving the cost basis would leave the sale at another cost."""

    SALE = 'tests/fixtures/fx_usd_sold_out_of_the_purchase_at_two_rates.txt'

    def _book(self, runner, tmp_path):
        book, text = _book_and_export(runner, tmp_path)
        basis = re.search(r'Assets:Bank:USD 100\.00 USD\n\t+guid: "([0-9a-f]{32})"',
                          text).group(1)
        sale = tmp_path / 'sale.txt'
        sale.write_text(Path(self.SALE).read_text().replace('{basis}', basis))
        sold = _run(runner, 'import', str(book), str(sale))
        assert sold.exit_code == 0, sold.output
        out = tmp_path / 'with-the-sale.txt'
        assert _run(runner, 'export', str(book), str(out)).exit_code == 0
        return book, _the_transaction(out.read_text())

    def _refused(self, runner, book, tmp_path, edited_text, *flags):
        edited = tmp_path / 'edited.txt'
        edited.write_text(edited_text)
        result = _run(runner, 'import', str(book), str(edited), '--strategy', 'update', *flags)
        message = result.output + str(result.exception)
        assert result.exit_code != 0, message
        assert _cost_of_the_basis(runner, book) == '25/18'
        return message

    def test_adding_a_cad_split_is_refused(self, tmp_path):
        """Nothing the book holds is changed, only added: the refusal gives what the file states."""
        runner = CliRunner()
        book, transaction = self._book(runner, tmp_path)

        message = self._refused(runner, book, tmp_path, _accounts_for(transaction) + transaction
                                + _without_comments(Path(ADDED_CAD_SPLITS).read_text()))

        assert 'cannot be edited in place' in message, message
        assert 'costs 25/18 CAD/USD and would cost 19/14' in message, message
        assert 'the file states' in message and 'the book holds' not in message, message
        assert "'Sell 20 USD'" in message, message

    def test_removing_the_fee_that_prices_it_is_refused(self, tmp_path):
        """The fee's two splits taken off: 140.00 CAD over 100.00 USD re-prices the cost basis to 1.4.

        Read before the commit, while GnuCash still listed the fee's splits in
        the transaction, the cost came out as it was and the edit went through,
        re-pricing the cost basis under the sale.

        Nothing is added, only taken off, so the refusal gives what the book
        holds and nothing the file states.
        """
        runner = CliRunner()
        book, transaction = self._book(runner, tmp_path)
        cad_fee = re.search(r'\tExpenses:Bank Fees 10\.00 CAD\n(?:\t\t[^\n]*\n)*',
                            transaction).group(0)
        usd_fee = re.search(r'\tAssets:Bank:USD -8\.00 USD\n(?:\t\t[^\n]*\n)*',
                            transaction).group(0)

        message = self._refused(runner, book, tmp_path,
                                transaction.replace(cad_fee, '').replace(usd_fee, ''))

        assert 'costs 25/18 CAD/USD and would cost 1.4' in message, message
        assert "the book holds -8.00 USD on 'Assets:Bank:USD' valued at -8.00" in message, message
        assert "10.00 CAD on 'Expenses:Bank Fees' valued at 8.00" in message, message
        assert 'the file states' not in message, message

    def test_restating_what_it_brought_in_is_refused(self, tmp_path):
        """90.00 USD for 126.00 CAD: what the cost basis brought in moves, and its cost with it."""
        runner = CliRunner()
        book, transaction = self._book(runner, tmp_path)
        restated = (transaction
                    .replace('Assets:Bank:USD 100.00 USD', 'Assets:Bank:USD 90.00 USD')
                    .replace('value: "100.00"', 'value: "90.00"')
                    .replace('Income:Sales -140.00 CAD', 'Income:Sales -126.00 CAD')
                    .replace('value: "-100.00"', 'value: "-90.00"'))
        assert 'Assets:Bank:USD 90.00 USD' in restated, restated

        message = self._refused(runner, book, tmp_path, restated)

        assert 'brought in 100 USD held and would bring in 90 held' in message, message
        assert 'costs 25/18 CAD/USD and would cost 68/49' in message, message

    def test_under_atomic_a_re_price_is_left_to_the_finished_book(self, tmp_path):
        """Deferred, and the finished book refuses it: the sale is valued at the old cost.

        The purchase's own 8.00 USD fee is stated in US dollars and draws on
        the cost basis too, but its value is read through the same Canadian
        dollar splits that price it, so it does not stand in the deferral's way.
        """
        runner = CliRunner()
        book, transaction = self._book(runner, tmp_path)

        message = self._refused(runner, book, tmp_path, _accounts_for(transaction) + transaction
                                + _without_comments(Path(ADDED_CAD_SPLITS).read_text()),
                                '--atomic')

        assert 'Rolled back' in message, message
        assert 'value what is sold at the cost basis it picks' in message, message


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
