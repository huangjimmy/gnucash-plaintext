"""Unposting an invoice is refused where GnuCash would delete a journal entry with it.

C001's credit is made by a journal entry whose splits are all on the
receivable, and INV-001 spends it. GnuCash's `gncInvoiceUnpost` deletes every
transaction in the invoice's lot that it reads as a link between two records,
and from GnuCash 4.13 it reads any transaction with no split off the
receivables and payables as one. So on those builds, unposting INV-001 deleted
the journal entry, which the book's owner entered, and C001's credit went with
it; `unpost-invoices` said only `unposted`. On 3.4, 3.8, 4.4 and 4.8 the
same unpost kept the entry.

A link GnuCash makes has every split in a posted record's lot. This entry has
a split in none, so it is not one, and the unpost is refused on every build
until the settlement is taken off the invoice.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner

from cli.main import cli

ACCOUNTS = 'tests/fixtures/payment_roundtrip_accounts.txt'
CREDIT = 'tests/fixtures/a_customers_credit_made_by_a_journal_entry.txt'
INVOICE = 'tests/fixtures/an_invoice_spending_the_journal_entrys_credit.txt'
ENTRY = 'a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1'


@pytest.fixture
def book(tmp_path):
    book = tmp_path / 'book.gnucash'
    for args in (['import', '--new', str(book), ACCOUNTS],
                 ['import', str(book), CREDIT, '--include-business-objects'],
                 ['import', str(book), INVOICE, '--include-business-objects']):
        made = CliRunner().invoke(cli, args)
        assert made.exit_code == 0, made.output
    return book


def _exported(book, tmp_path):
    out = tmp_path / 'out.txt'
    result = CliRunner().invoke(cli, ['export', str(book), str(out),
                                      '--include-business-objects'])
    assert result.exit_code == 0, result.output
    return out.read_text()


def _refused_and_left_whole(result, book, tmp_path):
    assert result.exit_code != 0, result.output
    assert f'would delete transaction {ENTRY}' in result.output, result.output
    assert f'unlink <book> INV-001 --txn {ENTRY} --to' in result.output, result.output
    exported = _exported(book, tmp_path)
    assert f'guid: "{ENTRY}"' in exported, exported
    invoice = exported[exported.index('invoice "INV-001"'):]
    assert '\tposted:\n' in invoice, invoice


def test_unpost_invoices_is_refused(book, tmp_path):
    result = CliRunner().invoke(cli, ['unpost-invoices', str(book), 'INV-001'])

    _refused_and_left_whole(result, book, tmp_path)


def test_an_import_reading_it_as_unposted_is_refused(book, tmp_path):
    text = Path(INVOICE).read_text()
    unposted = tmp_path / 'unposted.txt'
    unposted.write_text(text[:text.index('\tposted:\n')] + '\tposted: none\n')

    result = CliRunner().invoke(cli, ['import', str(book), str(unposted),
                                      '--include-business-objects'])

    _refused_and_left_whole(result, book, tmp_path)
