"""Unposting an invoice GnuCash linked to a credit note goes through, and GnuCash removes its link.

INV-CN-001 and the credit note CN-001 are posted for the same customer, and
neither is paid. Applying the owner's credit to INV-CN-001, as GnuCash's
Process Payment does, offsets the two with a link: a transaction with one
split in each record's lot and no split off the receivable. Measured on 5.10
and 3.4, GnuCash deletes that link when INV-CN-001 is unposted, and CN-001 is
left posted and open.

`unpost-invoices` refuses where GnuCash would delete a transaction with a
split in no record's lot (`test_an_unpost_leaves_a_journal_entry_whole.py`).
A link GnuCash made has none, so it is GnuCash's to remove and the unpost is
not refused.
"""

from click.testing import CliRunner

from cli.main import cli
from repositories.gnucash_repository import GnuCashRepository
from services.gnucash_importer import _find_invoices_by_id

LEDGER = 'tests/fixtures/a_credit_note_and_the_invoice_it_reverses.txt'


def _linked(tmp_path):
    book = tmp_path / 'book.gnucash'
    made = CliRunner().invoke(cli, ['import', '--new', str(book), LEDGER,
                                    '--include-business-objects'])
    assert made.exit_code == 0, made.output
    repo = GnuCashRepository(str(book))
    repo.open()
    try:
        _find_invoices_by_id(repo.book, 'INV-CN-001')[0].AutoApplyPayments()
        repo.save()
    finally:
        repo.close()
    return book


def _exported(book, tmp_path):
    out = tmp_path / 'out.txt'
    result = CliRunner().invoke(cli, ['export', str(book), str(out),
                                      '--include-business-objects'])
    assert result.exit_code == 0, result.output
    return out.read_text()


def _record(exported, header):
    block = exported[exported.index(header):]
    return block[:block.index('\n\n')] if '\n\n' in block else block


def test_the_unpost_goes_through_and_the_link_is_gone(tmp_path):
    book = _linked(tmp_path)
    before = _exported(book, tmp_path)
    assert '* "Reversal Ltd"' in before, before

    result = CliRunner().invoke(cli, ['unpost-invoices', str(book), 'INV-CN-001'])

    assert result.exit_code == 0, result.output
    assert 'INV-CN-001' in result.output and 'unposted' in result.output, result.output
    after = _exported(book, tmp_path)
    assert '* "Reversal Ltd"' not in after, after
    assert '\tposted: none' in _record(after, 'invoice "INV-CN-001"'), after
    assert '\tposted:\n' in _record(after, 'invoice "CN-001"'), after
