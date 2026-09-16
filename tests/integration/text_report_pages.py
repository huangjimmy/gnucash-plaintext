"""A book made from a fixture, and the figures on a line of a text report page.

The text page of `balance-sheet`, `income-statement` and `report` is written by
the customized GnuCash reports in
`infrastructure/gnucash/reports/balance-sheet-and-income-statement-as-text.scm`:
a label, then its figures, each column at least two spaces from the next.
"""

import re
from pathlib import Path

from click.testing import CliRunner

from tests.conftest import _run

FIXTURES = Path('tests/fixtures')


def book_from(tmp_path, fixture, *flags):
    """A new book imported from `tests/fixtures/<fixture>`."""
    book = tmp_path / 'book.gnucash'
    result = _run(CliRunner(), 'import', '--new', str(book), str(FIXTURES / fixture), *flags)
    assert result.exit_code == 0, result.output
    return book


def shares_as_gnucash_writes(quantity, mnemonic):
    """The ways GnuCash writes a whole number of shares on a report.

    `10 AMZN` on GnuCash 3.4, 3.8, 4.4, 4.8, 4.13, 5.5 and 5.10, and `10. AMZN`
    on 5.13, 5.14, 5.15 and 5.16 — GnuCash's own shipped Balance Sheet report writes
    it with the point there too, so it is GnuCash's formatting, not the text
    report's.
    """
    return (f'{quantity} {mnemonic}', f'{quantity}. {mnemonic}')


def figures(output, label):
    """The figures on the one line of the page whose label is `label`.

    A label has no two spaces in a row, so splitting at two spaces or more
    separates the label from each figure.
    """
    rows = [re.split(r' {2,}', line.strip()) for line in output.splitlines()]
    found = [row[1:] for row in rows if row[0] == label]
    assert len(found) == 1, output
    return found[0]
