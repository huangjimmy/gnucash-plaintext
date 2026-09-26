"""A company address keeps the index of each line, and an empty line writes nothing.

The book keeps a company's address as one string of lines, so a line a block
left out is an empty line in the middle of it. The export writes each line that
holds something under the index it has, and none for the empty one, so the
ledger states the address the block stated.
"""

from click.testing import CliRunner

from tests.conftest import _run

FIXTURE = 'tests/fixtures/a_company_whose_address_skips_a_line.txt'


def test_the_lines_keep_their_indexes(tmp_path):
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    made = _run(runner, 'import', '--new', str(book), FIXTURE, '--include-business-objects')
    assert made.exit_code == 0, made.output

    out = tmp_path / 'out.txt'
    exported = _run(runner, 'export', str(book), str(out), '--include-business-objects')

    assert exported.exit_code == 0, exported.output
    text = out.read_text()
    assert 'addr[0]: "42 Example Street"' in text, text
    assert 'addr[2]: "Springfield ON"' in text, text
    assert 'addr[1]' not in text, text
