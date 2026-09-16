"""A paid invoice's own block, read back with a guid this book does not hold.

INV-001 is imported paid and exported, and its block is read back into the
same book with one guid changed to one the book does not hold. Measured on
5.10.

- **`txn_split_guid:`.** A page printed from another book gives that book's
  split, so a split guid the transaction has not got is read as the split
  settling this invoice, as if the block gave none. The payment the block
  describes is the one the invoice has, so the invoice is unchanged.
- **The line's `guid:`.** A block giving a line guid the invoice has not got
  describes a line the invoice does not hold. That changes a posted invoice,
  and it is refused.
"""

from click.testing import CliRunner

from cli.main import cli
from tests.integration.test_find_orphan_payments import ACCOUNTS, _fixture

UNKNOWN = 'feedfacefeedfacefeedfacefeedface'


def _run(*args):
    return CliRunner().invoke(cli, [str(arg) for arg in args])


def _paid_and_exported(tmp_path):
    """The book, and INV-001's block as the export writes it."""
    book = tmp_path / 'book.gnucash'
    source = tmp_path / 'in.txt'
    source.write_text(ACCOUNTS + '\n' + _fixture('q014_invoice_posted_paid'))
    made = _run('import', '--new', book, source, '--include-business-objects')
    assert made.exit_code == 0, made.output
    out = tmp_path / 'out.txt'
    assert _run('export', book, out, '--include-business-objects').exit_code == 0
    block = next(part for part in out.read_text().split('\n\n')
                 if part.startswith('invoice "INV-001"'))
    return book, block


def _the_value(text, key):
    return next(line.split(':', 1)[1].strip().strip('"') for line in text.splitlines()
                if line.strip().startswith(f'{key}:'))


def _read_back(tmp_path, book, text):
    edited = tmp_path / 'edited.txt'
    edited.write_text(text + '\n')
    return _run('import', book, edited, '--include-business-objects')


def test_a_split_guid_it_lacks_reads_as_the_split_settling_the_invoice(tmp_path):
    book, block = _paid_and_exported(tmp_path)

    result = _read_back(tmp_path, book,
                        block.replace(_the_value(block, 'txn_split_guid'), UNKNOWN))

    assert result.exit_code == 0, result.output
    assert 'invoice "INV-001": unchanged' in result.output, result.output


def test_a_line_guid_it_lacks_is_a_change_to_a_posted_invoice(tmp_path):
    book, block = _paid_and_exported(tmp_path)
    line_guid = _the_value(block.split('entry:')[1], 'guid')

    result = _read_back(tmp_path, book, block.replace(line_guid, UNKNOWN))

    assert result.exit_code != 0, result.output
    assert 'this invoice is posted, and this file changes it' in result.output, result.output
