"""A line left out of an unposted invoice or bill's block is removed from it.

The block is the record's whole list of lines: a line it gives no block for
is gone from the record. The record here is unposted, so nothing is booked
against the line, and the import edits the one line it keeps and removes the
other.
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

SECOND_LINE = {
    'q010_invoice_unposted': (
        '\tentry:\n\t\tdate: 2026-01-01\n\t\tdescription: "Travel"\n'
        '\t\taction: "Hours"\n\t\taccount: "Income:Sales"\n\t\tquantity: 1\n'
        '\t\tprice: 20\n\t\ttaxable: false\n\t\ttax_included: false\n'),
    'q010_bill_unposted': (
        '\tentry:\n\t\tdate: 2026-01-01\n\t\tdescription: "Travel"\n'
        '\t\taccount: "Expenses:Supplies"\n\t\tquantity: 1\n'
        '\t\tprice: 20\n\t\ttaxable: true\n\t\ttax_included: false\n'),
}


@pytest.mark.parametrize('fixture, record', [
    ('q010_invoice_unposted', 'invoice "INV-001"'),
    ('q010_bill_unposted', 'bill "BILL-001"'),
], ids=['invoice', 'bill'])
def test_the_line_is_removed(tmp_path, fixture, record):
    runner = CliRunner()
    one_line = _fixture(fixture)
    two_lines = one_line.replace('\tposted: none\n',
                                 SECOND_LINE[fixture] + '\tposted: none\n')
    assert two_lines != one_line
    book = _setup_book_with(runner, tmp_path, two_lines)
    before = _export_text(runner, book, tmp_path)
    assert 'description: "Travel"' in before, before

    result = _import(runner, book, _write(tmp_path / 'one_line.txt',
                                          ACCOUNTS + '\n' + one_line))

    assert result.exit_code == 0, result.output
    assert f'{record}: updated' in result.output, result.output
    after = _export_text(runner, book, tmp_path)
    block = after[after.index(record):]
    block = block[:block.index('\n\n')] if '\n\n' in block else block
    assert block.count('\tentry:\n') == 1, block
    assert 'description: "Travel"' not in block, block
