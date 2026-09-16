"""A payment an unpost left behind, exported without its customer, is still listed.

`export` without `--include-business-objects` writes the transactions alone,
and an orphaned payment keeps `txn_type: P` and `owner: customer:C001` so a
book read from the file can still say it is one and whose. Read into a fresh
book, C001 is not there: the owner line gives an ID the book has no customer
for. Dropped for that, the payment was listed by no command, at exit 0, in the
book whose whole purpose was to carry it.

So it is listed under the ID the file gives.
"""

from click.testing import CliRunner

from cli.main import cli
from tests.integration.test_find_orphan_payments import _make_orphan_invoice


def test_it_is_listed_under_the_id_its_owner_line_gives(tmp_path):
    runner = CliRunner()
    book = _make_orphan_invoice(runner, tmp_path, 'q014_invoice_posted_paid',
                                'INV-001', 'unpost-invoices')
    plain = tmp_path / 'transactions.txt'
    exported = runner.invoke(cli, ['export', str(book), str(plain)])
    assert exported.exit_code == 0, exported.output
    assert '\towner: customer:C001' in plain.read_text(), plain.read_text()
    fresh = tmp_path / 'fresh.gnucash'
    made = runner.invoke(cli, ['import', '--new', str(fresh), str(plain)])
    assert made.exit_code == 0, made.output

    listed = runner.invoke(cli, ['find-orphan-payments', str(fresh)])

    assert listed.exit_code == 0, listed.output
    assert 'Found 1 orphan bank-side payment transaction' in listed.output, listed.output
    assert 'C001' in listed.output, listed.output
