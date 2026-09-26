"""A record read again with one field changed is updated, not reported unchanged.

Reading a vendor or an invoice the book already holds, the import compares the
book's record with the file, field by field, and writes nothing where they
agree. Where one field differs the record is updated, and the book then holds
what the file says.
"""

from pathlib import Path

from click.testing import CliRunner

from cli.main import cli

ACCOUNTS = 'tests/fixtures/payment_roundtrip_accounts.txt'
VENDOR = 'tests/fixtures/vendor_v001_active.txt'
INVOICE = 'tests/fixtures/a_draft_invoice_with_one_line.txt'


def _book(tmp_path):
    book = tmp_path / 'book.gnucash'
    made = CliRunner().invoke(cli, ['import', '--new', str(book), ACCOUNTS])
    assert made.exit_code == 0, made.output
    return book


def _read_again_with(tmp_path, book, fixture, old, new):
    first = CliRunner().invoke(cli, ['import', str(book), fixture,
                                     '--include-business-objects'])
    assert first.exit_code == 0, first.output
    text = Path(fixture).read_text()
    assert old in text, text
    again = tmp_path / 'again.txt'
    again.write_text(text.replace(old, new))
    return CliRunner().invoke(cli, ['import', str(book), str(again),
                                    '--include-business-objects'])


def _exported(tmp_path, book):
    out = tmp_path / 'out.txt'
    assert CliRunner().invoke(cli, ['export', str(book), str(out),
                                    '--include-business-objects']).exit_code == 0
    return out.read_text()


def test_a_vendor_made_inactive_is_updated(tmp_path):
    book = _book(tmp_path)

    result = _read_again_with(tmp_path, book, VENDOR, '\tactive: true\n', '\tactive: false\n')

    assert result.exit_code == 0, result.output
    assert 'vendor "V001": updated' in result.output, result.output
    vendor = _exported(tmp_path, book).split('vendor "V001"')[1].split('\n\n')[0]
    assert 'active: #False' in vendor, vendor


def test_an_invoice_with_a_billing_id_added_is_updated(tmp_path):
    book = _book(tmp_path)

    result = _read_again_with(tmp_path, book, INVOICE, '\tcurrency: CAD\n\tdate_opened',
                              '\tcurrency: CAD\n\tbilling_id: "PO-2"\n\tdate_opened')

    assert result.exit_code == 0, result.output
    assert 'invoice "INV-LINE": updated' in result.output, result.output
    assert 'billing_id: "PO-2"' in _exported(tmp_path, book)
