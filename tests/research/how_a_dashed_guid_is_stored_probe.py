"""Probe: what a file's dashed `cost_basis_split_guid:` becomes in the book.

A guid may be written either way in a file — every reader of that key takes
the dashes out — and this asks two things about the dashed spelling: what the
book stores, and whether GnuCash's own `string_to_guid` reads it.

Measured on GnuCash 5.10:

    imported                0                     (the sale lands)
    stored, as exported     cost_basis_split_guid: "7ef90eef-1da2-4c67-…"
    string_to_guid          True                  (dashes and all)

So the key is kept exactly as the file spelled it, and a lookup through
`string_to_guid` finds the split without normalising. The export normalises
anyway, because that answer belongs to GnuCash's parser rather than to this
tool, and the ten supported builds do not have to agree about it.

    ./scripts/test.sh latest tests/research/how_a_dashed_guid_is_stored_probe.py
"""

from pathlib import Path

from click.testing import CliRunner

from cli.main import cli
from tests.conftest import _run
from tests.integration.test_a_disposal_follows_a_divided_credits_basis import (
    RATES,
    _dashed,
)
from tests.integration.test_applied_credit_carries_its_basis import (
    _overpaid_book,
)


def test_what_a_dashed_guid_becomes(tmp_path, capsys):
    runner = CliRunner()
    book = _overpaid_book(runner, tmp_path)
    listing = runner.invoke(cli, ['fx-balances', str(book)]).output
    credit = next(line.split()[1] for line in listing.splitlines()
                  if 'Accounts Receivable USD' in line and '2026-02-25' in line)

    sale = tmp_path / 'sale.txt'
    sale.write_text(
        Path('tests/fixtures/fx_sell_part_of_a_credit.txt').read_text()
        .replace('{basis}', _dashed(credit)))
    imported = _run(runner, 'import', str(book), str(sale), '--fx-rates', RATES)

    out = tmp_path / 'out.txt'
    _run(runner, 'export', str(book), str(out))
    written = [line.strip() for line in out.read_text().splitlines()
               if 'cost_basis_split_guid' in line]

    from gnucash.gnucash_core_c import GncGUID, string_to_guid
    parsed = GncGUID()
    accepts_dashes = bool(string_to_guid(_dashed(credit), parsed))

    with capsys.disabled():
        print(f'\nimported             {imported.exit_code}')
        print(f'stored, as exported  {written}')
        print(f'string_to_guid       {accepts_dashes}')
