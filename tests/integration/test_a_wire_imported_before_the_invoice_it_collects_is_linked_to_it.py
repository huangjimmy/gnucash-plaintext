"""A wire imported before the invoice it collects, linked to it by the invoice's payment block (Q-054).

INV-USD-WIRE bills C-US 100.00 USD, posted on 2026-01-05 at 1.40 CAD/USD. On
2026-02-25 C-US wires 200.00 USD into Assets:Bank:USD, entered in Canadian
dollars: 278.00 CAD, the 100.00 USD settling the invoice at 140.00 CAD and the
other 100.00 USD, C-US's credit, at 138.00 CAD. The invoice's payment block
states the settling split with `txn_split_guid:` and the rest with
`prepayment: 100`.

Once linked, the book holds the invoice's 100.00 USD cost basis, standing for
the dollars the wire collected; the bank's own 100.00 USD, what it brought in
past the invoice, at the 138.00 CAD it cost; and C-US's credit of 100.00 USD
owed at 1.38. The cost bases then hold the 200.00 USD the bank holds, however
the wire and the invoice reached the book.
"""

import re
from pathlib import Path

from click.testing import CliRunner

from tests.conftest import _run

FIXTURES = Path('tests/fixtures')
RATES = FIXTURES / 'fx_rates_usd_dated.yaml'
ACCOUNTS = FIXTURES / 'usd_invoicing_accounts_with_a_cad_bank_and_a_usd_bank.txt'
WIRE_AND_INVOICE = (
    FIXTURES / 'inv_usd_wire_overpaid_into_the_usd_bank_entered_in_cad_imported_before_the_invoice.txt')


def _import(book, ledger, *more):
    done = _run(CliRunner(), 'import', *more, str(book), str(ledger),
                '--include-business-objects', '--fx-rates', str(RATES))
    assert done.exit_code == 0 and 'Errors:       0' in done.output, done.output


def _the_wire_and_the_invoice():
    """The file's wire, and its invoice block, apart."""
    wire, invoice = WIRE_AND_INVOICE.read_text().split('invoice "INV-USD-WIRE"', 1)
    return wire, 'invoice "INV-USD-WIRE"' + invoice


def _linked(book):
    listing = _run(CliRunner(), 'fx-balances', str(book), '--verify-costs')
    assert listing.exit_code == 0, listing.output
    assert re.search(r'Assets:Bank:USD\s+1\.38 CAD/USD\s+100\.00 USD\s+100\.00 USD\s+asset',
                     listing.output), listing.output
    assert re.search(r'Assets:Accounts Receivable USD\s+1\.4 CAD/USD\s+100\.00 USD\s+'
                     r'100\.00 USD\s+asset', listing.output), listing.output
    assert re.search(r'f3f3f3f3f3f3f3f3f3f3f3f3f3f3f3f3\s+Assets:Accounts Receivable USD\s+'
                     r'1\.38 CAD/USD\s+100\.00 USD\s+100\.00 USD\s+liability',
                     listing.output), listing.output
    assert 'Total USD cost basis balance: 200.00 USD held, 100.00 USD owed' in listing.output
    checked = _run(CliRunner(), '--verify-integrity', str(book))
    assert checked.exit_code == 0, checked.output


def _book(tmp_path):
    book = tmp_path / 'book.gnucash'
    made = _run(CliRunner(), 'import', '--new', str(book), str(ACCOUNTS),
                '--include-business-objects', '--fx-rates', str(RATES))
    assert made.exit_code == 0, made.output
    return book


def test_the_wire_and_the_invoice_in_one_file(tmp_path):
    book = _book(tmp_path)

    _import(book, WIRE_AND_INVOICE)

    _linked(book)


def test_the_wire_imported_after_the_invoice_was_posted(tmp_path):
    book = _book(tmp_path)
    wire, invoice = _the_wire_and_the_invoice()
    posted = tmp_path / 'posted.txt'
    posted.write_text(invoice.split('\tpayment:')[0])
    _import(book, posted)
    linking = tmp_path / 'linking.txt'
    linking.write_text(wire + invoice)

    _import(book, linking)

    _linked(book)


def test_a_sale_drawing_on_more_than_the_link_leaves_the_bank_is_refused(tmp_path):
    """150.00 USD sold against the wire before it was linked, where the link leaves the bank 100.00.

    Read loose, the bank's split brought in all 200.00 USD, and the sale drew
    150.00 of them at the wire's 1.39 CAD/USD. Linked, 100.00 of the wire is the
    invoice's, and the bank's split brings in only the other 100.00. The sale
    was measured against a cost basis the link takes it past, so the link is
    refused and the book file is left as it was.
    """
    book = _book(tmp_path)
    wire, invoice = _the_wire_and_the_invoice()
    first = tmp_path / 'wire.txt'
    first.write_text(wire)
    _import(book, first)
    sale = tmp_path / 'sale.txt'
    sale.write_text('2026-03-10 * "Sell 150.00 USD"\n'
                    '\tcurrency.mnemonic: "CAD"\n'
                    '\tAssets:Bank:USD -150.00 USD\n'
                    '\t\taccount.commodity.mnemonic: "USD"\n'
                    '\t\tshare_price: "139/100"\n'
                    '\t\tvalue: "-208.50"\n'
                    '\t\tcost_basis_split_guid: "b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1"\n'
                    '\tAssets:Bank 208.50 CAD\n')
    _import(book, sale)
    on_disk = book.read_bytes()
    linking = tmp_path / 'invoice.txt'
    linking.write_text(invoice)

    done = _run(CliRunner(), 'import', '--atomic', str(book), str(linking),
                '--include-business-objects', '--fx-rates', str(RATES))

    assert done.exit_code != 0, done.output
    assert ('linking this payment makes part of what split '
            "b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1 brought in the invoice's, whose own cost "
            "basis stands for it, so the split's cost basis covers the 100.00 USD it "
            'brought in past the invoice, and the disposals drawing on it consume '
            '150.00 USD; 1 disposal(s) are measured against that cost basis') \
        in done.output, done.output
    assert book.read_bytes() == on_disk


def test_the_wire_imported_by_an_earlier_run(tmp_path):
    book = _book(tmp_path)
    wire, invoice = _the_wire_and_the_invoice()
    first = tmp_path / 'wire.txt'
    first.write_text(wire)
    _import(book, first)
    linking = tmp_path / 'invoice.txt'
    linking.write_text(invoice)

    _import(book, linking)

    _linked(book)
