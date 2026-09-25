"""Under `--atomic` a disposal restated or re-pointed is read as a new transaction would be.

`--atomic` defers `_require_no_cost_basis_edit` for a transaction whose cost
basis another transaction draws on, because repairing one runs through states
that refusal stops in either order. A disposal nothing draws on is not that
case: its edit is read as a new transaction would be (Q-051), which gives
back what it drew and draws again, meeting every check a new disposal meets.

That is what answers the fault this file was written for. Before an edit
drew anything, the 10.00 USD fee below restated as 400.00 USD, valued at
560.00 CAD, exited 0 under `--strategy update --atomic` and left a 400.00 USD
disposal against a cost basis still offering 90.00, with `--verify-costs`
calling the book sound. Read as new, the 400.00 out of an account holding
100.00 draws the 100.00 the purchase brought in and owes the other 300.00, and
the book says so.
"""

import re

from click.testing import CliRunner

from tests.conftest import _run
from tests.integration.test_a_repriced_basis_is_caught_under_its_sales import (
    RATES,
    _a_basis_with_a_fee_drawn_on_it,
)

ANOTHER_PURCHASE = 'tests/fixtures/fx_buy_60_usd_at_the_same_rate.txt'
A_EUR_PURCHASE = 'tests/fixtures/fx_buy_60_eur_at_the_same_rate.txt'


def _the_fee_block(text):
    return re.search(r'2026-02-10 \* "A 10 USD fee"[^\n]*\n(?:\t[^\n]*\n)*',
                     text).group(0)


def _exported(runner, book, path):
    assert _run(runner, 'export', str(book), str(path)).exit_code == 0
    return path.read_text()


def _the_balance_on(text, line):
    """The `cost_basis_balance:` the export writes under the split line given."""
    return re.search(rf'{re.escape(line)}\n(?:\t\t[^\n]*\n)*?\t\tcost_basis_balance: "([^"]*)"',
                     text).group(1)


def _the_fee_restated_as_400(runner, book, tmp_path):
    """The 10.00 USD fee written as 400.00 USD, at the rate its cost basis cost.

    560.00 CAD for 400.00 USD is 1.40, which is what the cost basis cost.
    """
    block = (_the_fee_block(_exported(runner, book, tmp_path / 'before.txt'))
             .replace('-10.00 USD', '-400.00 USD')
             .replace('value: "-14.00"', 'value: "-560.00"')
             .replace('14.00 CAD', '560.00 CAD')
             .replace('value: "14.00"', 'value: "560.00"'))
    assert '-400.00 USD' in block and 'value: "-560.00"' in block, block
    restated = tmp_path / 'restated.txt'
    restated.write_text(block)
    return restated


def _the_fee_pointed_at_the_other_purchase(runner, book, tmp_path):
    """The same fee, unchanged in every figure, drawing on the 60.00 USD cost basis."""
    text = _exported(runner, book, tmp_path / 'before.txt')
    other = re.search(r'Assets:Bank:USD 60\.00 USD\n\t+guid: "([0-9a-f]{32})"',
                      text).group(1)
    block = re.sub(r'cost_basis_split_guid: "[0-9a-f]{32}"',
                   f'cost_basis_split_guid: "{other}"', _the_fee_block(text))
    repointed = tmp_path / 'repointed.txt'
    repointed.write_text(block)
    return repointed, other


def test_restating_what_it_takes_draws_what_it_now_takes(tmp_path):
    """400.00 USD out of an account holding 100.00: all of it held, and 300.00 owed."""
    runner = CliRunner()
    book = _a_basis_with_a_fee_drawn_on_it(runner, tmp_path)
    restated = _the_fee_restated_as_400(runner, book, tmp_path)

    result = _run(runner, 'import', str(book), str(restated), '--atomic',
                  '--strategy', 'update', '--fx-rates', RATES)
    assert result.exit_code == 0, result.output + str(result.exception)

    text = _exported(runner, book, tmp_path / 'after.txt')
    assert '-400.00 USD' in _the_fee_block(text), text
    assert _the_balance_on(text, 'Assets:Bank:USD 100.00 USD') == '0.00', text
    assert _the_balance_on(text, 'Assets:Bank:USD -400.00 USD') == '300.00', text
    verified = _run(runner, 'fx-balances', str(book), '--verify-costs')
    assert verified.exit_code == 0, verified.output


def test_re_pointing_it_at_another_basis_moves_what_it_drew(tmp_path):
    """The 10.00 USD goes back to the first purchase and comes off the second.

    Deferred, a re-pointed disposal left the cost basis it came from 10.00
    short and the one it joined undrawn, for the file to state by hand.
    """
    runner = CliRunner()
    book = _a_basis_with_a_fee_drawn_on_it(runner, tmp_path)
    assert _run(runner, 'import', str(book), ANOTHER_PURCHASE,
                '--fx-rates', RATES).exit_code == 0
    repointed, other = _the_fee_pointed_at_the_other_purchase(
        runner, book, tmp_path)

    result = _run(runner, 'import', str(book), str(repointed), '--atomic',
                  '--strategy', 'update', '--fx-rates', RATES)
    assert result.exit_code == 0, result.output
    assert 'Changes saved' in result.output, result.output
    assert 'points a disposal at another cost basis' not in result.output, result.output

    text = _exported(runner, book, tmp_path / 'after.txt')
    assert f'cost_basis_split_guid: "{other}"' in _the_fee_block(text), text
    assert _the_balance_on(text, 'Assets:Bank:USD 100.00 USD') == '100.00', text
    assert _the_balance_on(text, 'Assets:Bank:USD 60.00 USD') == '50.00', text


def test_leaving_the_pick_out_leaves_it_where_it_is(tmp_path):
    """A block without its `cost_basis_split_guid:` line keeps the pick the book holds.

    An absent key is not an instruction (CLAUDE.md finding 11): the fee still
    draws on its cost basis, every cost basis is what it was, and the edit
    goes through.
    """
    runner = CliRunner()
    book = _a_basis_with_a_fee_drawn_on_it(runner, tmp_path)

    dropped = tmp_path / 'dropped.txt'
    dropped.write_text(re.sub(r'\t\tcost_basis_split_guid: "[0-9a-f]{32}"\n', '',
                              _the_fee_block(_exported(runner, book, tmp_path / 'before.txt'))))

    result = _run(runner, 'import', str(book), str(dropped), '--atomic',
                  '--strategy', 'update', '--fx-rates', RATES)
    assert result.exit_code == 0, result.output

    after = _exported(runner, book, tmp_path / 'after.txt')
    assert 'cost_basis_split_guid' in _the_fee_block(after), after


def test_dropping_the_pick_is_refused(tmp_path):
    """Cleared, the fee spends dollars the book holds giving no cost basis, as a new spend may not."""
    runner = CliRunner()
    book = _a_basis_with_a_fee_drawn_on_it(runner, tmp_path)

    dropped = tmp_path / 'dropped.txt'
    dropped.write_text(re.sub(r'\t\tcost_basis_split_guid: "[0-9a-f]{32}"\n',
                              '\t\tcost_basis_split_guid: ""\n',
                              _the_fee_block(_exported(runner, book, tmp_path / 'before.txt'))))

    result = _run(runner, 'import', str(book), str(dropped), '--atomic',
                  '--strategy', 'update', '--fx-rates', RATES)
    message = result.output + str(result.exception)
    assert result.exit_code != 0, message
    assert 'Changes saved' not in result.output, result.output
    assert 'no split says which one' in message, message

    after = _exported(runner, book, tmp_path / 'after.txt')
    assert 'cost_basis_split_guid' in _the_fee_block(after), after


def test_re_pointing_it_at_another_currencys_basis_is_refused(tmp_path):
    """A pool of euros has no US dollars in it to take.

    Read as a new transaction would be, the fee giving a cost basis of euros
    for the US dollars it spends is refused as a new import of it is, and the
    run is rolled back.
    """
    runner = CliRunner()
    book = _a_basis_with_a_fee_drawn_on_it(runner, tmp_path)
    assert _run(runner, 'import', str(book), A_EUR_PURCHASE,
                '--fx-rates', RATES).exit_code == 0

    text = _exported(runner, book, tmp_path / 'before.txt')
    euros = re.search(r'Assets:Bank:EUR 60\.00 EUR\n\t+guid: "([0-9a-f]{32})"',
                      text).group(1)
    repointed = tmp_path / 'repointed.txt'
    repointed.write_text(re.sub(r'cost_basis_split_guid: "[0-9a-f]{32}"',
                                f'cost_basis_split_guid: "{euros}"',
                                _the_fee_block(text)))

    result = _run(runner, 'import', str(book), str(repointed), '--atomic',
                  '--strategy', 'update', '--fx-rates', RATES)
    assert result.exit_code != 0, result.output
    assert 'Rolled back' in result.output, result.output
    assert 'Changes saved' not in result.output, result.output
    assert f"cost_basis_split_guid '{euros}' is a EUR split but this split sells USD" \
        in result.output, result.output

    after = _exported(runner, book, tmp_path / 'after.txt')
    assert f'cost_basis_split_guid: "{euros}"' not in after, after
