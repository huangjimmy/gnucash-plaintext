"""An `invoice` or `bill` block is read whole, or refused.

Under an invoice or a bill, the import reads `entry:`, `posted:` and
`payment:` blocks, and a line's own blocks under its `entry:`. A block written
anywhere else under the record, such as a line's `breakdown:` under the
invoice itself, was read by nothing: the import answered `created`, and the
block went missing with nothing said.
"""

import pytest
from click.testing import CliRunner

from cli.main import cli

ACCOUNTS = 'tests/fixtures/payment_roundtrip_accounts.txt'


@pytest.mark.parametrize('fixture, record, kind', [
    ('an_invoice_with_a_breakdown_block_outside_its_lines.txt', 'invoice "INV-001"',
     'an invoice'),
    ('a_bill_with_a_breakdown_block_outside_its_lines.txt', 'bill "BILL-001"',
     'a bill'),
], ids=['invoice', 'bill'])
def test_it_is_refused_and_nothing_is_written(tmp_path, fixture, record, kind):
    book = tmp_path / 'book.gnucash'
    made = CliRunner().invoke(cli, ['import', '--new', str(book), ACCOUNTS])
    assert made.exit_code == 0, made.output

    result = CliRunner().invoke(cli, ['import', str(book), f'tests/fixtures/{fixture}',
                                      '--include-business-objects'])

    assert result.exit_code != 0, result.output
    assert (f'{record}: a `breakdown:` block is not read under {kind}, only '
            f'`entry:`, `posted:` and `payment:` blocks are') in result.output, \
        result.output
    out = tmp_path / 'out.txt'
    exported = CliRunner().invoke(cli, ['export', str(book), str(out),
                                        '--include-business-objects'])
    assert exported.exit_code == 0, exported.output
    assert record not in out.read_text(), out.read_text()
