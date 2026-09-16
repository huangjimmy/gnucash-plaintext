"""A `taxtable` block is read whole, or refused.

A tax table is its entries. One with no `entry:` block has nothing to charge,
and GnuCash's own dialog will not save it; it used to be answered `skipped`,
which the README keeps for a tax table the book already holds. A block nothing
reads under a tax table, such as a line's `breakdown:`, went missing with
nothing said, like any other unread line would have.
"""

import pytest
from click.testing import CliRunner

from cli.main import cli


@pytest.mark.parametrize('fixture, refusal', [
    ('a_tax_table_with_no_entry.txt',
     'taxtable "GST": a tax table needs at least one `entry:` block'),
    ('a_tax_table_with_a_breakdown_block_before_its_entry.txt',
     'taxtable "GST": a `breakdown:` block is not read under a tax table, '
     'only `entry:` blocks are'),
], ids=['no-entry', 'a-breakdown-block'])
def test_it_is_refused_and_no_book_is_left(tmp_path, fixture, refusal):
    book = tmp_path / 'book.gnucash'

    result = CliRunner().invoke(cli, [
        'import', '--new', str(book), f'tests/fixtures/{fixture}',
        '--include-business-objects'])

    assert result.exit_code != 0, result.output
    assert refusal in result.output, result.output
    assert not book.exists()
