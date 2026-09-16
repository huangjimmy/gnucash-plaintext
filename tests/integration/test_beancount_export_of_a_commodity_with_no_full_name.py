"""A commodity with no full name is exported with no `gnucash-fullname` line.

An empty full name is left out rather than written as `""`, as the export does
for an account's empty code and description, and every other commodity keeps
its line.
"""

import re

from click.testing import CliRunner

from cli.main import cli

LEDGER = 'tests/fixtures/fund_units_of_a_commodity_with_no_full_name.txt'


def test_only_that_commodity_goes_without_the_line(tmp_path):
    gnc = tmp_path / 'book.gnucash'
    created = CliRunner().invoke(cli, ['import', '--new', str(gnc), LEDGER])
    assert created.exit_code == 0, created.output
    out = tmp_path / 'ledger.beancount'

    exported = CliRunner().invoke(cli, ['export-beancount', str(gnc), str(out)])

    assert exported.exit_code == 0, exported.output
    # One directive to a block: each starts on a line of its own with a date.
    blocks = re.split(r'\n(?=\d{4}-\d{2}-\d{2} )', out.read_text())
    noname = [block for block in blocks if 'gnucash-mnemonic: "NONAME"' in block]
    cad = [block for block in blocks if 'gnucash-mnemonic: "CAD"' in block]
    assert len(noname) == 1 and 'gnucash-fullname' not in noname[0], blocks
    assert len(cad) == 1 and 'gnucash-fullname: "Canadian Dollar"' in cad[0], blocks
