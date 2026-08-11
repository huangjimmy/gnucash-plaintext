"""A line naming a tax table the book does not hold is refused.

Swallowed, such a name left the entry with no table at all — and the
comparison that decides whether a document is already up to date reads the
name the *file* states against the table the *entry* carries. Those could then
never agree, so every re-import of an unchanged ledger found the document out
of date: a posted invoice was unposted, its posting transaction destroyed, its
payments orphaned and marked, the whole thing rebuilt and re-paid, and the run
reported `updated` with no error. On every import, forever.

The line is asking for a table. The book either has it or the file is wrong,
and saying so once costs a message; not saying it costs the posting
transaction every time the ledger is read.

Both sides are refused the same way — an invoice entry and a bill entry — and
`taxable: false` is refused too: the name is what the comparison reads, so an
untaxed line naming a missing table loops exactly like a taxed one.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner

from cli.main import cli

ACCOUNTS = """\
2026-01-01 commodity CAD
\tmnemonic: "CAD"
\tfullname: "Canadian Dollar"
\tnamespace: "CURRENCY"
\tfraction: 100
2026-01-01 open Assets
\ttype: Asset
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Assets:Accounts Receivable
\ttype: Accounts Receivable
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Income
\ttype: Income
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Income:Sales
\ttype: Income
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"

customer "C-TT"
\tname: "Tax Table Customer"
\tcurrency: CAD
"""

INVOICE = """
invoice "INV-TT"
\tcustomer_id: "C-TT"
\tcurrency: CAD
\tdate_opened: 2026-01-01
\tentry:
\t\tdate: 2026-01-01
\t\tdescription: "A line"
\t\taccount: "Income:Sales"
\t\tquantity: 1
\t\tprice: 100
\t\ttaxable: {taxable}
\t\ttax_included: false
\t\ttax_table: "GST"
"""


def _import(tmp_path, taxable: str):
    book = tmp_path / 'book.gnucash'
    ledger = tmp_path / 'ledger.txt'
    ledger.write_text(ACCOUNTS + INVOICE.format(taxable=taxable))
    return CliRunner().invoke(cli, [
        'import', '--new', str(book), str(ledger), '--include-business-objects'])


class TestATaxedLine:
    def test_it_is_refused(self, tmp_path):
        result = _import(tmp_path, 'true')

        assert result.exit_code != 0, result.output

    def test_the_table_it_named_is_quoted(self, tmp_path):
        result = _import(tmp_path, 'true')

        assert 'GST' in result.output, result.output


class TestAnUntaxedLine:
    """The name is what the comparison reads, so `taxable: false` loops too."""

    def test_it_is_refused_as_well(self, tmp_path):
        result = _import(tmp_path, 'false')

        assert result.exit_code != 0, result.output

    def test_it_says_the_book_does_not_have_the_table(self, tmp_path):
        result = _import(tmp_path, 'false')

        assert 'not in this book' in result.output, result.output
