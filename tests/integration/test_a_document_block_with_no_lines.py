"""A document block with no lines does not empty the document.

An invoice or bill is rebuilt from its block — the file is the source of truth
for the lines, which is what lets a person correct one by editing it. The
model is fine; what was missing is any way to tell "the writer restated one
line" from "the writer's file stops here".

So a block truncated after the three fields read unconditionally —
`customer_id:`, `currency:`, `date_opened:` — unposted the invoice, which
destroys the posting transaction and orphans its payments, and left the
document with no lines at all. A file cut short by a failed write does that,
and so does a copy-paste that stopped early.

Tax tables have refused this all along ("must have at least one entry"). A
document does now too, when the book has lines to lose: creating an empty
document is still allowed, since there is nothing there to destroy.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner
from gnucash import Query
from gnucash import gnucash_business as gb

from cli.main import cli
from repositories.gnucash_repository import GnuCashRepository, SessionMode

FIXTURES = Path('tests/fixtures')
WHOLE = str(FIXTURES / 'an_invoice_with_one_line.txt')
CUT = str(FIXTURES / 'an_invoice_block_cut_short.txt')


def _invoice(book):
    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        query = Query()
        query.search_for('gncInvoice')
        query.set_book(repo.book)
        for raw in query.run():
            invoice = gb.Invoice(instance=raw)
            if invoice.GetID() != 'INV-CUT':
                continue
            found = {
                'lines': len(list(invoice.GetEntries())),
                'posted': invoice.GetPostedTxn() is not None,
            }
            query.destroy()
            return found
        query.destroy()
        raise AssertionError('no INV-CUT')
    finally:
        repo.close()


@pytest.fixture
def book(tmp_path):
    path = tmp_path / 'book.gnucash'
    result = CliRunner().invoke(cli, [
        'import', '--new', str(path), WHOLE, '--include-business-objects'])
    assert result.exit_code == 0, result.output
    assert _invoice(path) == {'lines': 1, 'posted': True}, _invoice(path)
    return path


class TestATruncatedBlock:
    def _cut(self, book):
        return CliRunner().invoke(cli, [
            'import', str(book), CUT, '--include-business-objects'])

    def test_it_is_refused(self, book):
        result = self._cut(book)

        assert result.exit_code != 0, result.output
        assert 'INV-CUT' in result.output, result.output

    def test_the_lines_are_still_there(self, book):
        self._cut(book)

        assert _invoice(book)['lines'] == 1, _invoice(book)

    def test_the_invoice_is_still_posted(self, book):
        """Unposting destroys the posting and orphans what paid it."""
        self._cut(book)

        assert _invoice(book)['posted'] is True, _invoice(book)
