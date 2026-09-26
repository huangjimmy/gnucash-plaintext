"""A transaction has one exchange difference, however the file claims it.

There are two ways to say which split took the residual, and they produce the
same book: `$residual$` in place of an amount, which the import resolves and
records, or the figure written out with `took_the_residual: "true"` beside it.
Because they are equivalent, a file that writes one of each — or two of either
— claims the difference twice.

Counted twice it states as a gain money that was something else. These sales
pay a 5.00 bank charge out of what they fetched, so the entry carries two lines
a difference could land on — the charge and the exchange difference, both in
the profit and loss — and claiming both would put 105.00 into
`realized_gains_fx` where the sale made 100.00.

That shape is the point. Neither the arithmetic nor the account tells a bank
charge from an exchange difference, which is why the token and the key exist;
a claim on a bank or a receivable is not counted at all, so a file that
balances its residual onto the bank and states the gain beside it claims once,
not twice, and is accepted.

Two `$residual$` tokens were already refused, because two of them cannot be
resolved at all. These are the spellings that resolve perfectly well and are
simply not both true.
"""

import re
from pathlib import Path

from click.testing import CliRunner

from tests.conftest import _run
from tests.integration.text_report_pages import block_of

# What `realized_gains_fx` states for each of these sales: the 100.00 the sale
# made, and the one split it was booked to. Asserted whole rather than as a
# figure — a total on its own is the thing a reader cannot check, which is why
# the key carries its items at all.
THE_GAIN = '\n'.join((
    '\t\trealized_gains_fx: 100.00',
    '\t\tsplits:',
    '\t\t\tsplit:',
    '\t\t\t\tdate: 2026-06-01',
    '\t\t\t\taccount: "Income:FX Gain"',
    '\t\t\t\tamount: 100.00'))

BOUGHT = 'tests/fixtures/a_cad_book_that_bought_a_thousand_usd.txt'
TWO_MARKED = 'tests/fixtures/a_sale_marking_two_splits_as_the_residual.txt'
MARKED_BESIDE_TOKEN = ('tests/fixtures/'
                       'a_sale_marking_a_split_beside_its_residual_token.txt')
DECLARED = 'tests/fixtures/the_thousand_usd_sold_at_a_higher_rate.txt'
WRITTEN_OUT = 'tests/fixtures/the_thousand_usd_sold_with_the_gain_written_out.txt'
ONTO_THE_BANK = ('tests/fixtures/'
                 'a_sale_balancing_its_residual_onto_the_bank.txt')
LESS_A_CHARGE = 'tests/fixtures/the_thousand_usd_sold_less_a_bank_charge.txt'


def _import(tmp_path, sale):
    """The purchase, then `sale` on top of it, with the cost basis guid filled in."""
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    bought = _run(runner, 'import', '--new', str(book), BOUGHT)
    assert bought.exit_code == 0, bought.output

    listing = _run(runner, 'fx-balances', str(book))
    assert listing.exit_code == 0, listing.output
    found = re.search(r'\b([0-9a-f]{32})\b', listing.output)
    assert found, listing.output

    ledger = tmp_path / 'sale.txt'
    ledger.write_text(
        Path(sale).read_text(encoding='utf-8').replace('{usd_basis}', found.group(1)),
        encoding='utf-8')
    return _run(runner, 'import', str(book), str(ledger))


def test_two_stated_keys_are_refused(tmp_path):
    landed = _import(tmp_path, TWO_MARKED)

    assert landed.exit_code != 0, landed.output
    assert 'take the residual' in landed.output, landed.output


def test_a_stated_key_beside_the_token_is_refused(tmp_path):
    landed = _import(tmp_path, MARKED_BESIDE_TOKEN)

    assert landed.exit_code != 0, landed.output
    assert 'take the residual' in landed.output, landed.output


def test_the_refusal_lists_both_accounts(tmp_path):
    """A reader has to be told which two splits claim it, to drop one."""
    landed = _import(tmp_path, TWO_MARKED)

    assert 'Expenses:Bank Charges' in landed.output, landed.output
    assert 'Income:FX Gain' in landed.output, landed.output


def test_the_refusal_says_how_a_split_takes_it(tmp_path):
    landed = _import(tmp_path, TWO_MARKED)

    assert '$residual$' in landed.output, landed.output
    assert 'took_the_residual' in landed.output, landed.output


def test_the_token_on_its_own_is_accepted(tmp_path):
    """The rule refuses a second claim, not the ordinary one."""
    landed = _import(tmp_path, DECLARED)

    assert landed.exit_code == 0, landed.output


def test_a_key_stated_on_its_own_is_accepted(tmp_path):
    """The other of the two ways, equally ordinary."""
    landed = _import(tmp_path, WRITTEN_OUT)

    assert landed.exit_code == 0, landed.output


def test_a_residual_balanced_onto_the_bank_is_accepted(tmp_path):
    """The token on a bank is no claim, so this file claims once.

    Counted as a claim it was refused as two, and the gain could then be had
    no other way than by working the bank's figure out by hand.
    """
    landed = _import(tmp_path, ONTO_THE_BANK)

    assert landed.exit_code == 0, landed.output


def test_and_the_gain_it_states_is_counted(tmp_path):
    """Accepting the file is only half of it: the 100.00 has to reach the key."""
    runner = CliRunner()
    book = _sold(runner, tmp_path, ONTO_THE_BANK)

    drawn = _run(runner, 'balance-sheet', str(book), '--as-of', '2026-12-31')
    assert drawn.exit_code == 0, drawn.output
    assert block_of(drawn.output, 'realized_gains_fx') == THE_GAIN


def _sold(runner, tmp_path, sale=DECLARED):
    """The purchase and a sale on top of it, as a book to draw or export."""
    book = tmp_path / 'book.gnucash'
    bought = _run(runner, 'import', '--new', str(book), BOUGHT)
    assert bought.exit_code == 0, bought.output

    listing = _run(runner, 'fx-balances', str(book))
    assert listing.exit_code == 0, listing.output
    found = re.search(r'\b([0-9a-f]{32})\b', listing.output)
    assert found, listing.output

    ledger = tmp_path / 'sale.txt'
    ledger.write_text(
        Path(sale).read_text(encoding='utf-8').replace('{usd_basis}',
                                                       found.group(1)),
        encoding='utf-8')
    landed = _run(runner, 'import', str(book), str(ledger))
    assert landed.exit_code == 0, landed.output
    return book


def _exported(runner, book, tmp_path, marking=None):
    """The book's own ledger, with a second `took_the_residual` added to `marking`."""
    out = tmp_path / 'exported.txt'
    wrote = _run(runner, 'export', str(book), str(out))
    assert wrote.exit_code == 0, wrote.output
    if marking is not None:
        lines = []
        for line in out.read_text(encoding='utf-8').splitlines():
            lines.append(line)
            if line.strip() == marking:
                lines.append('\t\ttook_the_residual: "true"')
        assert '\t\ttook_the_residual: "true"' in lines, (marking, out.read_text())
        out.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return out


def test_the_export_re_imports_as_it_stands(tmp_path):
    """The control, and the one that matters most.

    An exported disposal already carries the key on its gain split, so a check
    that counted it wrongly would refuse every round trip of every book that
    has a real one.
    """
    runner = CliRunner()
    book = _sold(runner, tmp_path)
    again = _run(runner, 'import', str(book),
                 str(_exported(runner, book, tmp_path)), '--strategy', 'update')

    assert again.exit_code == 0, again.output


def test_a_second_mark_added_to_an_export_is_refused(tmp_path):
    """The route the create-path check cannot see.

    No file states two claims: the gain split's key came out of the book, and
    the block adding one to the bank charge beside it moves no figure at all,
    so the cost-basis refusal has nothing to catch.
    """
    runner = CliRunner()
    book = _sold(runner, tmp_path, LESS_A_CHARGE)
    ledger = _exported(runner, book, tmp_path,
                       marking='Expenses:Bank Charges 5.00 CAD')
    again = _run(runner, 'import', str(book), str(ledger), '--strategy', 'update')

    assert again.exit_code != 0, again.output
    assert 'would take the residual' in again.output, again.output


def test_the_refused_update_leaves_the_book_as_it_was(tmp_path):
    """Refused before the edit begins, so the gain is still the sale's own."""
    runner = CliRunner()
    book = _sold(runner, tmp_path, LESS_A_CHARGE)
    ledger = _exported(runner, book, tmp_path,
                       marking='Expenses:Bank Charges 5.00 CAD')
    _run(runner, 'import', str(book), str(ledger), '--strategy', 'update')

    drawn = _run(runner, 'balance-sheet', str(book), '--as-of', '2026-12-31')
    assert drawn.exit_code == 0, drawn.output
    assert block_of(drawn.output, 'realized_gains_fx') == THE_GAIN


def test_a_mark_added_to_a_bank_line_is_no_second_claim(tmp_path):
    """What the update path must not refuse, because the create path accepts it.

    A key on a bank line is passed over by the page and by the import alike, so
    it claims nothing. Counted here and nowhere else, a file the create path
    took was refused when it came back from its own export — and a format whose
    export cannot be re-imported is broken at the one journey it has to make.
    """
    runner = CliRunner()
    book = _sold(runner, tmp_path, LESS_A_CHARGE)
    ledger = _exported(runner, book, tmp_path,
                       marking='Assets:CAD Bank 1395.00 CAD')
    again = _run(runner, 'import', str(book), str(ledger), '--strategy', 'update')

    assert again.exit_code == 0, again.output

    drawn = _run(runner, 'balance-sheet', str(book), '--as-of', '2026-12-31')
    assert drawn.exit_code == 0, drawn.output
    assert block_of(drawn.output, 'realized_gains_fx') == THE_GAIN
