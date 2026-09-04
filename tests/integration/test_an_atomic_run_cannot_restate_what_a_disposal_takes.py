"""Under `--atomic` a disposal may be re-pointed, and not restated.

`--atomic` defers `_require_no_cost_basis_edit`, because repairing a cost
basis runs through states that refusal stops in either order. What it may not
defer is a block that restates *what a disposal takes*, and the reason is
where the drawdown lives: `apply_cost_basis_picks` is called from the create
path alone, so an edited transaction never draws a basis down and never meets
the over-sell refusal either. Nothing at commit time can stand in for that —
a basis's balance is not lowered by an edit, so the finished book cannot tell
a 400.00 USD sale against a basis holding 90.00 from a 10.00 one.

Measured before this was refused: the 10.00 USD fee below, restated as 400.00
USD valued at 560.00 CAD — 1.40 × 400, so the sale is valued at exactly what
its basis cost — imported with `--strategy update --atomic`, exited 0, saved
the book, and left a 400.00 USD disposal against a basis still offering 90.00.
`--verify-costs` then called that book sound.

Re-pointing the same fee at another basis is what a repair does and is still
allowed: the figures do not move, so nothing is drawn down that was not drawn
down before.
"""

import re
from pathlib import Path

from click.testing import CliRunner

from cli.main import cli
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


def _the_fee_restated_as_400(runner, book, tmp_path):
    """The 10.00 USD fee written as 400.00 USD, at the rate its basis cost.

    Every other check is satisfied. 560.00 CAD for 400.00 USD is 1.40, which
    is what the basis cost, so the sale is valued at the basis it picks; the
    basis is real, is collected, and its balance of 90.00 is inside the 100.00
    it brought in.
    """
    out = tmp_path / 'before.txt'
    assert _run(runner, 'export', str(book), str(out)).exit_code == 0
    block = (_the_fee_block(out.read_text())
             .replace('-10.00 USD', '-400.00 USD')
             .replace('value: "-14.00"', 'value: "-560.00"')
             .replace('14.00 CAD', '560.00 CAD')
             .replace('value: "14.00"', 'value: "560.00"'))
    assert '-400.00 USD' in block and 'value: "-560.00"' in block, block
    restated = tmp_path / 'restated.txt'
    restated.write_text(block)
    return restated


def _the_fee_pointed_at_the_other_purchase(runner, book, tmp_path):
    """The same fee, unchanged in every figure, drawing on the 60.00 USD basis."""
    out = tmp_path / 'before.txt'
    assert _run(runner, 'export', str(book), str(out)).exit_code == 0
    text = out.read_text()
    other = re.search(r'Assets:Bank:USD 60\.00 USD\n\t+guid: "([0-9a-f]{32})"',
                      text).group(1)
    block = re.sub(r'cost_basis_split_guid: "[0-9a-f]{32}"',
                   f'cost_basis_split_guid: "{other}"', _the_fee_block(text))
    repointed = tmp_path / 'repointed.txt'
    repointed.write_text(block)
    return repointed, other


def test_restating_what_it_takes_is_refused(tmp_path):
    """The block is refused as it is applied, `--atomic` or not."""
    runner = CliRunner()
    book = _a_basis_with_a_fee_drawn_on_it(runner, tmp_path)
    restated = _the_fee_restated_as_400(runner, book, tmp_path)

    result = _run(runner, 'import', str(book), str(restated), '--atomic',
                  '--strategy', 'update', '--fx-rates', RATES)
    message = result.output + str(result.exception)
    assert result.exit_code != 0, message
    assert 'Changes saved' not in result.output, result.output
    assert 'delete-transactions --by-guid' in message, message


def test_the_fee_is_still_the_fee_the_book_held(tmp_path):
    """Ten dollars taken from a basis offering ninety, as it was before.

    The balance is not what says so — nothing lowers a basis on the update
    path, so it reads 90.00 whether the restatement landed or not, which is
    the whole reason the finished book cannot answer this. The fee itself is
    what says so.
    """
    runner = CliRunner()
    book = _a_basis_with_a_fee_drawn_on_it(runner, tmp_path)
    restated = _the_fee_restated_as_400(runner, book, tmp_path)

    _run(runner, 'import', str(book), str(restated), '--atomic',
         '--strategy', 'update', '--fx-rates', RATES)

    after = tmp_path / 'after.txt'
    assert _run(runner, 'export', str(book), str(after)).exit_code == 0
    fee = _the_fee_block(after.read_text())
    assert '-10.00 USD' in fee, fee
    assert '-400.00 USD' not in fee, fee

    listing = _run(runner, 'fx-balances', str(book)).output
    basis = [line for line in listing.splitlines()
             if 'Assets:Bank:USD' in line and '100.00 USD' in line]
    assert basis, listing
    assert '90.00 USD' in basis[0], basis[0]


def test_re_pointing_it_at_another_basis_still_commits(tmp_path):
    """What a repair does, and what the deferral is for.

    Nothing about what the fee takes moves — the same 10.00 USD at the same
    14.00 CAD — so the file states a disposal the book already holds, against
    a basis that cost what this one values it at.
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
    # And it says what it did not do. A basis balance is lowered where a
    # disposal is created and raised where one is deleted; an edit does
    # neither, so the basis this fee leaves stays 10.00 short and the basis it
    # joins is not drawn down for it. The finished book cannot tell — one
    # reads 90.00 with nothing drawing on it and the other 60.00 with a fee
    # drawing on it, and the two cancel in the only book-wide question asked.
    assert 'points a disposal at another cost basis' in result.output, \
        result.output

    after = tmp_path / 'after.txt'
    assert _run(runner, 'export', str(book), str(after)).exit_code == 0
    assert f'cost_basis_split_guid: "{other}"' in _the_fee_block(
        after.read_text()), after.read_text()


def test_dropping_the_pick_is_refused_too(tmp_path):
    """Taking the line off does not give the basis back what the fee took.

    A sale that draws on nothing takes nothing, which is true of the state the
    file asks for and says nothing about the state it is leaving: the 10.00
    USD came out of the basis when the fee was imported, and only deleting the
    transaction gives it back — `give_back_to_cost_bases` runs on that path
    and on no other. Allowed, the pool would be 10.00 USD short with nothing
    in the book recording where it went, and every question the finished book
    is asked would pass: the balance is inside its bounds, no figure is stored
    where nothing reads it, and there is no disposal left to ask about.
    """
    runner = CliRunner()
    book = _a_basis_with_a_fee_drawn_on_it(runner, tmp_path)

    out = tmp_path / 'before.txt'
    assert _run(runner, 'export', str(book), str(out)).exit_code == 0
    dropped = tmp_path / 'dropped.txt'
    dropped.write_text(re.sub(r'\t\tcost_basis_split_guid: "[0-9a-f]{32}"\n',
                              '', _the_fee_block(out.read_text())))

    result = _run(runner, 'import', str(book), str(dropped), '--atomic',
                  '--strategy', 'update', '--fx-rates', RATES)
    message = result.output + str(result.exception)
    assert result.exit_code != 0, message
    assert 'Changes saved' not in result.output, result.output
    assert 'delete-transactions --by-guid' in message, message

    after = tmp_path / 'after.txt'
    assert _run(runner, 'export', str(book), str(after)).exit_code == 0
    assert 'cost_basis_split_guid' in _the_fee_block(after.read_text()), \
        after.read_text()


def test_re_pointing_it_at_another_currencys_basis_is_rolled_back(tmp_path):
    """A pool of euros has no US dollars in it to take.

    The figures do not move, so the deferred guard lets the block through, and
    the update path draws no basis down, so nothing looks at the pick as it
    lands. The finished book is where it is caught — and the EUR purchase here
    cost 1.40 CAD, exactly what the USD one cost, so the sale is valued at what
    its new basis cost and the valuation question has nothing to say. Only
    asking what the basis holds catches this.
    """
    runner = CliRunner()
    book = _a_basis_with_a_fee_drawn_on_it(runner, tmp_path)
    assert _run(runner, 'import', str(book), A_EUR_PURCHASE,
                '--fx-rates', RATES).exit_code == 0

    out = tmp_path / 'before.txt'
    assert _run(runner, 'export', str(book), str(out)).exit_code == 0
    text = out.read_text()
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
    assert 'which holds EUR' in result.output, result.output

    after = tmp_path / 'after.txt'
    assert _run(runner, 'export', str(book), str(after)).exit_code == 0
    assert f'cost_basis_split_guid: "{euros}"' not in after.read_text(), \
        after.read_text()
