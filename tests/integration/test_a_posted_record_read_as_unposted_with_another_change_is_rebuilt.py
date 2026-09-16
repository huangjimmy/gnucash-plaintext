"""A posted invoice or bill read as `posted: none` with another field changed is rebuilt.

`posted: none` with nothing else changed takes the short path: the record is
unposted and its lines keep their guids. With the date opened, the notes or a
custom key changed as well, it is more than an unpost, so the record is
unposted and rebuilt from the file, and the book then holds what the file says.
"""

import pytest
from click.testing import CliRunner

from tests.integration.test_unpost_invoice_bill import (
    ACCOUNTS,
    _export_text,
    _fixture,
    _import,
    _setup_book_with,
    _write,
)

CHANGES = [
    ('\tdate_opened: 2026-01-01\n', '\tdate_opened: 2026-01-02\n',
     'date_opened: 2026-01-02'),
    ('\tdate_opened: 2026-01-01\n', '\tdate_opened: 2026-01-01\n\tnotes: "Call first"\n',
     'notes: "Call first"'),
    ('\tdate_opened: 2026-01-01\n', '\tdate_opened: 2026-01-01\n\tproject: "Apollo"\n',
     'project: "Apollo"'),
]
RECORDS = [
    ('q010_invoice_posted', 'q010_invoice_unposted', 'invoice "INV-001"'),
    ('q010_bill_posted', 'q010_bill_unposted', 'bill "BILL-001"'),
]


@pytest.mark.parametrize('posted, unposted, record', RECORDS, ids=['invoice', 'bill'])
@pytest.mark.parametrize('old, new, written', CHANGES,
                         ids=['date-opened', 'notes', 'custom-key'])
def test_it_is_unposted_and_takes_the_change(tmp_path, posted, unposted, record,
                                             old, new, written):
    runner = CliRunner()
    book = _setup_book_with(runner, tmp_path, _fixture(posted))
    text = _fixture(unposted)
    assert old in text, text

    result = _import(runner, book, _write(tmp_path / 'unposted.txt',
                                          ACCOUNTS + '\n' + text.replace(old, new)))

    assert result.exit_code == 0, result.output
    assert f'{record}: updated' in result.output, result.output
    exported = _export_text(runner, book, tmp_path)
    block = exported[exported.index(record):]
    block = block[:block.index('\n\n')] if '\n\n' in block else block
    assert '\tposted: none' in block, block
    assert written in block, block
