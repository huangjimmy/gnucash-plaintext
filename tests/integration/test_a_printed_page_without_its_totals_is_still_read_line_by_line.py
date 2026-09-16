"""A printed page with its totals taken off is read on the figures it still states.

`print-invoice --format plaintext` writes each line's `entry_amount:` and
`entry_tax:` and the page's `invoice_subtotal:`, `invoice_tax_total:` and
`invoice_total:`. A page trimmed of the three totals still states its lines'
figures, so those are checked against the book, and the page has no totals for
the book to be compared against. Read back into the book it was printed from, it
is that invoice, `unchanged`.
"""

import re

from click.testing import CliRunner

from cli.main import cli
from tests.integration.test_find_orphan_payments import ACCOUNTS, _fixture

TOTALS = re.compile(r'\t*invoice_(subtotal|tax_total|total):')


def _run(*args):
    return CliRunner().invoke(cli, [str(arg) for arg in args])


def test_it_reads_back_unchanged(tmp_path):
    book = tmp_path / 'book.gnucash'
    source = tmp_path / 'in.txt'
    source.write_text(ACCOUNTS + '\n' + _fixture('q014_invoice_posted_paid'))
    made = _run('import', '--new', book, source, '--include-business-objects')
    assert made.exit_code == 0, made.output
    page = tmp_path / 'page.txt'
    printed = _run('print-invoice', book, 'INV-001', '--format', 'plaintext', '-o', page)
    assert printed.exit_code == 0, printed.output
    lines = page.read_text().splitlines()
    assert any(TOTALS.match(line) for line in lines), page.read_text()
    assert any('entry_amount:' in line for line in lines), page.read_text()
    trimmed = tmp_path / 'trimmed.txt'
    trimmed.write_text(''.join(line + '\n' for line in lines if not TOTALS.match(line)))

    result = _run('import', book, trimmed, '--include-business-objects')

    assert result.exit_code == 0, result.output
    assert 'invoice "INV-001": unchanged' in result.output, result.output
