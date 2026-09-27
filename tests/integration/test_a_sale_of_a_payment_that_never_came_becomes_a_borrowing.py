"""A sale of dollars from a payment that never came becomes a borrowing.

A user holding no US dollars records a customer's payment of 100.00 USD into
Assets:Wise USD ahead of time, at 1.37, which opens an asset cost basis of
100.00. They sell 40.00 of those dollars for 56.00 CAD, stating that cost
basis. The payment then turns out not to be coming.

gnucash-plaintext offers no operation for this. The user does it with the
ones there are:

1. `delete-transactions` the payment. That destroys its cost basis, so the
   sale that drew on it is made `$pending$`, and the command says so.
2. Import the sale again, edited in place, with `cost_basis_split_guid: $None$`,
   which removes the key as `$None$` removes any custom key in the format; a
   line left out would say nothing about it. The edit is read as a new transaction is:
   the sale takes Wise from 0 to −40.00, which disposes of nothing the book
   held and makes what it owes grow, so it opens a liability cost basis of
   40.00 USD, at the 1.40 the sale records.

The test is the user: it states each step, and gnucash-plaintext chooses no
cost basis for it.
"""

import re

from click.testing import CliRunner

from tests.conftest import _run

BOOK = ('2026-07-01 commodity CAD\n'
        '\tmnemonic: "CAD"\n'
        '\tfullname: "Canadian Dollar"\n'
        '\tnamespace: "CURRENCY"\n'
        '\tfraction: 100\n'
        '2026-07-01 commodity USD\n'
        '\tmnemonic: "USD"\n'
        '\tfullname: "US Dollar"\n'
        '\tnamespace: "CURRENCY"\n'
        '\tfraction: 100\n'
        '2026-07-01 open Assets\n'
        '\ttype: "Asset"\n'
        '\tplaceholder: #True\n'
        '\tcommodity.namespace: "CURRENCY"\n'
        '\tcommodity.mnemonic: "CAD"\n'
        '2026-07-01 open Assets:Chequing\n'
        '\ttype: "Bank"\n'
        '\tcommodity.namespace: "CURRENCY"\n'
        '\tcommodity.mnemonic: "CAD"\n'
        '2026-07-01 open Assets:Wise USD\n'
        '\ttype: "Bank"\n'
        '\tcommodity.namespace: "CURRENCY"\n'
        '\tcommodity.mnemonic: "USD"\n'
        '2026-07-01 open Income\n'
        '\ttype: "Income"\n'
        '\tplaceholder: #True\n'
        '\tcommodity.namespace: "CURRENCY"\n'
        '\tcommodity.mnemonic: "CAD"\n'
        '2026-07-01 open Income:Sales\n'
        '\ttype: "Income"\n'
        '\tcommodity.namespace: "CURRENCY"\n'
        '\tcommodity.mnemonic: "CAD"\n')

PAYMENT_TXN = '0a550000000000000000000000000001'
ARRIVAL = '0a550000000000000000000000000002'
SALE_TXN = '0a550000000000000000000000000003'
SALE = '0a550000000000000000000000000004'

PAYMENT = ('2026-08-13 * "Customer payment recorded ahead"\n'
           f'\tguid: "{PAYMENT_TXN}"\n'
           '\tcurrency.mnemonic: "USD"\n'
           '\tAssets:Wise USD 100.00 USD\n'
           f'\t\tguid: "{ARRIVAL}"\n'
           '\tIncome:Sales -137.00 CAD\n'
           '\t\taccount.commodity.mnemonic: "CAD"\n'
           '\t\tvalue: "-100.00"\n')


def _sale(pick_line):
    return ('2026-08-20 * "Sell 40.00 USD"\n'
            f'\tguid: "{SALE_TXN}"\n'
            '\tcurrency.mnemonic: "USD"\n'
            '\tAssets:Wise USD -40.00 USD\n'
            f'\t\tguid: "{SALE}"\n'
            + pick_line
            + '\tAssets:Chequing 56.00 CAD\n'
            '\t\taccount.commodity.mnemonic: "CAD"\n'
            '\t\tvalue: "40.00"\n')


def _ledger(tmp_path, name, text):
    path = tmp_path / f'{name}.txt'
    path.write_text(text)
    return str(path)


def _imported(book, ledger, *options):
    done = _run(CliRunner(), 'import', *options, str(book), ledger)
    assert done.exit_code == 0 and 'Errors:       0' in done.output, done.output
    return done


def _costs(book):
    costs = _run(CliRunner(), 'fx-balances', str(book), '--verify-costs')
    assert costs.exit_code == 0 and 'warning' not in costs.output, costs.output
    return costs.output


def _the_sale_on_the_payment(tmp_path):
    book = tmp_path / 'book.gnucash'
    _imported(book, _ledger(tmp_path, 'book', BOOK + PAYMENT), '--new')
    _imported(book, _ledger(tmp_path, 'sale', _sale(
        f'\t\tcost_basis_split_guid: "{ARRIVAL}"\n')))
    return book


def test_deleting_the_payment_makes_the_sale_pending(tmp_path):
    book = _the_sale_on_the_payment(tmp_path)

    done = _run(CliRunner(), 'delete-transactions', str(book), '--by-guid', PAYMENT_TXN)

    assert done.exit_code == 0, done.output
    assert "2026-08-20 'Sell 40.00 USD' (40.00 USD)" in done.output, done.output
    # The book keeps no US dollar cost basis now, so the pending sale draws on
    # nothing, and `--verify-costs` reports it until the user edits it.
    checked = _run(CliRunner(), 'fx-balances', str(book), '--verify-costs')
    assert checked.exit_code == 1, checked.output
    assert 'Sell 40.00 USD' in checked.output, checked.output
    assert ARRIVAL not in checked.output, checked.output


def test_the_sale_imported_again_without_its_pick_opens_a_liability_cost_basis(tmp_path):
    book = _the_sale_on_the_payment(tmp_path)
    _run(CliRunner(), 'delete-transactions', str(book), '--by-guid', PAYMENT_TXN)

    # `key: ""` clears a key, as everywhere in the format; a line left out says
    # nothing about it, and would leave the sale pending.
    _imported(book, _ledger(tmp_path, 'restated', _sale('\t\tcost_basis_split_guid: $None$\n')),
              '--strategy', 'update')

    listed = _costs(book)
    assert 'pending their cost basis' not in listed, listed
    assert re.search(rf'{SALE}\s+Assets:Wise USD\s+1\.4 CAD/USD\s+40\.00 USD\s+'
                     r'40\.00 USD\s+liability', listed), listed
    assert re.search(r'Assets:Wise USD\s+-40\.00 USD', listed), listed
    integrity = _run(CliRunner(), '--verify-integrity', str(book))
    assert integrity.exit_code == 0, integrity.output
