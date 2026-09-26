"""A book whose disposals carry no mark states no gain, and can be told of one.

The `took_the_residual` key is written at import, and only where the file wrote
`$residual$`. A book imported before the key existed therefore carries none on
any of its disposals, so `realized_gains_fx` reads 0.00 with a working of
`nothing` — on a book that plainly realized something.

Re-exporting does not mend it: the export writes the figure the residual
resolved to rather than the token, and a figure says nothing about which split
it is. What mends it is stating the key by hand and importing that back with
`--strategy update` — the second of the two ways to write a disposal.

A book of that shape is made here the only way a test can make one: by taking
the mark off a book that has it. `took_the_residual: ""` **removes** the key
rather than emptying it, which is what a key named empty means in this format —
so the export of a cleared book carries no such line at all, and putting the
mark back means adding a line rather than changing one. That is exactly what a
reader does to their own book, and it is why the two helpers below differ.
"""

import re
from pathlib import Path

from click.testing import CliRunner

from tests.conftest import _run
from tests.integration.text_report_pages import block_of, block_total_of

BOUGHT = 'tests/fixtures/a_cad_book_that_bought_a_thousand_usd.txt'
DECLARED = 'tests/fixtures/the_thousand_usd_sold_at_a_higher_rate.txt'
AS_OF = '2026-12-31'
MARK = re.compile(r'took_the_residual: "[^"]*"')
GAIN_SPLIT = 'Income:FX Gain '

# The two shapes `realized_gains_fx` takes on this book: the sale's 100.00 with
# the split it was booked to, and — once the mark is cleared — a zero that says
# it found no split rather than measuring nothing.
THE_GAIN = '\n'.join((
    '\t\trealized_gains_fx: 100.00',
    '\t\tsplits:',
    '\t\t\tsplit:',
    '\t\t\t\tdate: 2026-06-01',
    '\t\t\t\taccount: "Income:FX Gain"',
    '\t\t\t\tamount: 100.00'))
NO_GAIN = '\n'.join((
    '\t\trealized_gains_fx: 0.00',
    '\t\tsplits: # there is no split'))


def _sold(runner, tmp_path):
    """The purchase, then the sale that declares its gain with `$residual$`."""
    book = tmp_path / 'book.gnucash'
    bought = _run(runner, 'import', '--new', str(book), BOUGHT)
    assert bought.exit_code == 0, bought.output

    listing = _run(runner, 'fx-balances', str(book))
    assert listing.exit_code == 0, listing.output
    found = re.search(r'\b([0-9a-f]{32})\b', listing.output)
    assert found, listing.output

    ledger = tmp_path / 'sale.txt'
    ledger.write_text(
        Path(DECLARED).read_text(encoding='utf-8').replace('{usd_basis}',
                                                           found.group(1)),
        encoding='utf-8')
    landed = _run(runner, 'import', str(book), str(ledger))
    assert landed.exit_code == 0, landed.output
    return book


def _exported(runner, book, tmp_path, name):
    out = tmp_path / f'{name}.txt'
    wrote = _run(runner, 'export', str(book), str(out))
    assert wrote.exit_code == 0, wrote.output
    return out


def _re_imported(runner, book, ledger):
    again = _run(runner, 'import', str(book), str(ledger), '--strategy', 'update')
    assert again.exit_code == 0, again.output
    return book


def _with_the_mark_cleared(runner, book, tmp_path, name='cleared'):
    """A book that looks as one imported before the key existed looks."""
    ledger = _exported(runner, book, tmp_path, name)
    text = ledger.read_text(encoding='utf-8')
    assert MARK.search(text), text
    ledger.write_text(MARK.sub('took_the_residual: ""', text), encoding='utf-8')
    return _re_imported(runner, book, ledger)


def _with_the_mark_stated(runner, book, tmp_path, name='restated'):
    """The remedy: add the line the cleared book no longer has."""
    ledger = _exported(runner, book, tmp_path, name)
    text = ledger.read_text(encoding='utf-8')
    assert not MARK.search(text), 'the book already carries a mark'

    lines = []
    for line in text.splitlines():
        lines.append(line)
        if line.strip().startswith(GAIN_SPLIT):
            lines.append('\t\ttook_the_residual: "true"')
    assert any('took_the_residual' in line for line in lines), text
    ledger.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return _re_imported(runner, book, ledger)


def _page(runner, book):
    drawn = _run(runner, 'balance-sheet', str(book), '--as-of', AS_OF)
    assert drawn.exit_code == 0, drawn.output
    return drawn.output


def test_a_book_that_carries_the_mark_states_its_gain(tmp_path):
    """The starting point: this sale made 100.00 and the page says so."""
    runner = CliRunner()

    assert block_total_of(_page(runner, _sold(runner, tmp_path)),
                     'realized_gains_fx') == 100


def test_without_the_mark_it_states_nothing(tmp_path):
    """What a book imported before the key existed states."""
    runner = CliRunner()
    book = _with_the_mark_cleared(runner, _sold(runner, tmp_path), tmp_path)

    assert block_of(_page(runner, book), 'realized_gains_fx') == NO_GAIN


def test_and_says_nothing_rather_than_listing_a_gain(tmp_path):
    """The working is what shows that zero is not a measurement.

    The key states `there is no split` beside its zero, so a reader can see the
    figure was reached by finding nothing rather than by measuring nothing.
    """
    runner = CliRunner()
    book = _with_the_mark_cleared(runner, _sold(runner, tmp_path), tmp_path)

    block = block_of(_page(runner, book), 'realized_gains_fx')
    assert '\t\tsplits: # there is no split' in block.splitlines(), block
    assert GAIN_SPLIT not in block, block


def test_the_export_of_such_a_book_carries_no_mark_to_restore(tmp_path):
    """Why re-importing its own ledger does not mend it."""
    runner = CliRunner()
    book = _with_the_mark_cleared(runner, _sold(runner, tmp_path), tmp_path)

    text = _exported(runner, book, tmp_path, 'again').read_text(encoding='utf-8')
    assert not MARK.search(text), text


def test_stating_the_key_by_hand_restores_the_gain(tmp_path):
    """The remedy the format documents, on the book it is written for."""
    runner = CliRunner()
    book = _with_the_mark_cleared(runner, _sold(runner, tmp_path), tmp_path)
    assert block_of(_page(runner, book), 'realized_gains_fx') == NO_GAIN

    book = _with_the_mark_stated(runner, book, tmp_path)

    assert block_of(_page(runner, book), 'realized_gains_fx') == THE_GAIN
