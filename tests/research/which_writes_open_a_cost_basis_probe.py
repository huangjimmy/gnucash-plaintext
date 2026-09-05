"""Probe: which writes leave a purchase without a cost basis balance.

A transaction that brings foreign currency in against the book's own is a
purchase or a borrowing, and the split that received the currency is a cost
basis holding all of it. `record_cost_bases` says so, and the create path
calls it.

This asks the same question of every other way a transaction reaches that
shape, because the answer should not depend on which command wrote it:

1. created by an import — the path that calls it;
2. edited into that shape by `import --strategy update`, a split given an
   account kept in another currency;
3. restated into that shape by `unapply-payment`, which takes the payment off
   a wrongly linked deposit.

And for each, what a fresh book built from that book's own ledger says about
the same transaction.

    ./scripts/test.sh latest tests/research/which_writes_open_a_cost_basis_probe.py
"""

import re
from pathlib import Path

from click.testing import CliRunner

from cli.main import cli
from tests.conftest import _run

RATES = 'tests/fixtures/fx_rates_usd_two_invoice_dates.yaml'
DEPOSIT_SPLIT = '00e958a8d56547d484d7629000292dc3'
BANK_USD = ('Assets:Current assets:Cash and deposits:Deposits in Canadian '
            'banks and institutions – Foreign currency:Foreign Payments '
            'Provider Chequing 000000000000001')
DUE_FROM = 'Assets:Current assets:Due from director'

A_CAD_ENTRY = '''\
2026-01-01 commodity CAD
\tmnemonic: "CAD"
\tfullname: "Canadian Dollar"
\tnamespace: "CURRENCY"
\tfraction: 100
2026-01-01 commodity USD
\tmnemonic: "USD"
\tfullname: "US Dollar"
\tnamespace: "CURRENCY"
\tfraction: 100
2026-01-01 open Assets
\ttype: Asset
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Assets:Bank
\ttype: Bank
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Assets:Bank:USD
\ttype: Bank
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "USD"
2026-01-01 open Assets:Suspense
\ttype: Asset
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"

2026-02-01 * "Money out"
\tguid: "aa11bb22cc33dd44ee55ff6600112233"
\tcurrency.mnemonic: "CAD"
\tAssets:Suspense 140.00 CAD
\t\tguid: "11112222333344445555666677778888"
\tAssets:Bank -140.00 CAD
\t\tguid: "99998888777766665555444433332222"
'''

# The same transaction, with the suspense split given the USD bank account:
# 100.00 USD in, 140.00 CAD out. A purchase of USD, written as an edit.
GIVEN_A_USD_ACCOUNT = '''\
2026-02-01 * "Money out"
\tguid: "aa11bb22cc33dd44ee55ff6600112233"
\tcurrency.mnemonic: "CAD"
\tAssets:Bank:USD 100.00 USD
\t\tguid: "11112222333344445555666677778888"
\t\taccount.commodity.mnemonic: "USD"
\t\tshare_price: "1.40"
\t\tvalue: "140.00"
\tAssets:Bank -140.00 CAD
\t\tguid: "99998888777766665555444433332222"
'''


def _balances(runner, book):
    return _run(runner, 'fx-balances', str(book)).output


def _line_for(runner, book, guid):
    return next((one for one in _balances(runner, book).splitlines()
                 if guid in one), None)


def _rebuilt(runner, book, tmp_path, name):
    """The same book, exported and imported into a fresh one."""
    out = tmp_path / f'{name}.txt'
    assert _run(runner, 'export', str(book), str(out),
                '--include-business-objects').exit_code == 0
    fresh = tmp_path / f'{name}.gnucash'
    result = _run(runner, 'import', '--new', str(fresh), str(out),
                  '--include-business-objects', '--fx-rates', RATES)
    return fresh, result, out


def test_a_transaction_edited_into_a_purchase(tmp_path, capsys):
    runner = CliRunner()
    book = tmp_path / 'edited.gnucash'
    ledger = tmp_path / 'cad.txt'
    ledger.write_text(A_CAD_ENTRY)
    assert runner.invoke(cli, ['import', '--new', str(book), str(ledger)]
                         ).exit_code == 0

    edit = tmp_path / 'edit.txt'
    edit.write_text(GIVEN_A_USD_ACCOUNT)
    edited = _run(runner, 'import', str(book), str(edit),
                  '--strategy', 'update', '--fx-rates', RATES)

    line = _line_for(runner, book, '11112222333344445555666677778888')
    fresh, rebuilt, _ = _rebuilt(runner, book, tmp_path, 'edited-again')
    there = _line_for(runner, fresh, '11112222333344445555666677778888')

    with capsys.disabled():
        print()
        print(f'the edit: exit {edited.exit_code}')
        for one in edited.output.splitlines():
            if 'rror' in one or 'refus' in one or 'cannot' in one:
                print('   ', one.strip())
        print('in the edited book:      ', line)
        print(f'rebuilt from its ledger: exit {rebuilt.exit_code}')
        print('in the rebuilt book:     ', there)


def test_an_overpayment_unapplied_into_the_book_currency(tmp_path, capsys):
    """The shape where the transaction holds more than this record's money.

    A 100.00 USD invoice paid with 200.00 USD from a USD bank: the settlement
    is 100.00 and the other 100.00 is the customer's credit, which is a cost
    basis of its own. Every split is USD, so nothing in the transaction says
    what the USD cost and the bank split is no cost basis.

    Unapplying the payment into a CAD account gives the transaction a
    base-currency figure, and the bank split — all 200.00 of it, including the
    half that is still the customer's — can be priced from it.
    """
    runner = CliRunner()
    book = tmp_path / 'over.gnucash'
    assert runner.invoke(cli, [
        'import', '--new', str(book),
        'tests/fixtures/fx_invoice_usd_overpaid_into_usd_bank.txt',
        '--include-business-objects',
        '--fx-rates', 'tests/fixtures/fx_rates_usd_dated.yaml']).exit_code == 0

    before = _balances(runner, book)
    unapplied = _run(runner, 'unapply-payment', str(book), 'INV-USD-OVER',
                     '--to', 'Assets:Bank',
                     '--fx-rates', 'tests/fixtures/fx_rates_usd_dated.yaml')
    after = _balances(runner, book)

    with capsys.disabled():
        print()
        print('--- before the unapply ---')
        print(before)
        print(f'--- unapply: exit {unapplied.exit_code} ---')
        print('--- after ---')
        print(after)


def test_an_overpayment_whose_credit_another_invoice_has_spent(tmp_path,
                                                               capsys):
    """The same transaction, once the credit has settled a second invoice.

    The residue is no longer a cost basis — spending it takes the balance off
    and puts the split in the second invoice's lot — so nothing in the
    transaction is one. Whether the bank's 200.00 is opened then turns on
    whether that split still reads as somebody's money.
    """
    runner = CliRunner()
    book = tmp_path / 'spent.gnucash'
    rates = 'tests/fixtures/fx_rates_usd_dated.yaml'
    assert runner.invoke(cli, [
        'import', '--new', str(book),
        'tests/fixtures/fx_invoice_usd_overpaid_into_usd_bank.txt',
        '--include-business-objects', '--fx-rates', rates]).exit_code == 0
    spent = _run(runner, 'import', str(book),
                 'tests/fixtures/fx_invoice_auto_applying_the_whole_credit.txt',
                 '--include-business-objects', '--fx-rates', rates)
    assert spent.exit_code == 0, spent.output

    before = _balances(runner, book)
    unapplied = _run(runner, 'unapply-payment', str(book), 'INV-USD-OVER',
                     '--to', 'Assets:Bank', '--fx-rates', rates)
    after = _balances(runner, book)

    with capsys.disabled():
        print()
        print('--- the credit spent on a second invoice ---')
        print(before)
        print(f'--- unapply of the first: exit {unapplied.exit_code} ---')
        print(after)


A_CAD_PAID_CREDIT = '''\
2026-01-01 commodity CAD
\tmnemonic: "CAD"
\tfullname: "Canadian Dollar"
\tnamespace: "CURRENCY"
\tfraction: 100
2026-01-01 commodity USD
\tmnemonic: "USD"
\tfullname: "US Dollar"
\tnamespace: "CURRENCY"
\tfraction: 100
2026-01-01 open Assets
\ttype: Asset
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Assets:Bank
\ttype: Bank
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Assets:Bank:USD
\ttype: Bank
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "USD"
2026-01-01 open Assets:Accounts Receivable USD
\ttype: Accounts Receivable
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "USD"
2026-01-01 open Income
\ttype: Income
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Income:Sales
\ttype: Income
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Income:FX Gain
\ttype: Income
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"

customer "C-US"
\tname: "US Customer"
\tcurrency: USD

2026-02-01 * "Customer prepaid 100 USD, arriving as CAD"
\tcurrency.mnemonic: "CAD"
\tAssets:Bank 137.00 CAD
\t\taccount.commodity.mnemonic: "CAD"
\tAssets:Accounts Receivable USD -100.00 USD
\t\taccount.commodity.mnemonic: "USD"
\t\tshare_price: "1.37"
\t\tvalue: "-137.00"
\t\tlot_owner: "customer:C-US"
'''

A_SALE_OF_80 = '''\
2026-02-28 * "Sell 80 USD of the credit"
\tcurrency.mnemonic: "CAD"
\tAssets:Bank:USD -80.00 USD
\t\taccount.commodity.mnemonic: "USD"
\t\tshare_price: "1.37"
\t\tvalue: "-109.60"
\t\tcost_basis_split_guid: "{basis}"
\tAssets:Bank 110.40 CAD
\tIncome:FX Gain $residual$ CAD
'''

AN_INVOICE_SPENDING_IT = '''\
invoice "INV-SPENDS-IT"
\tcustomer_id: "C-US"
\tcurrency: USD
\tdate_opened: 2026-03-01
\tentry:
\t\tdate: 2026-03-01
\t\tdescription: "Consulting"
\t\taccount: "Income:Sales"
\t\tquantity: 1
\t\tprice: 100
\t\ttaxable: false
\t\ttax_included: false
\tposted:
\t\tdate: 2026-03-01
\t\tdue: 2026-04-01
\t\tar_account: "Assets:Accounts Receivable USD"
\t\tmemo: "INV-SPENDS-IT"
\t\taccumulate: true
\tpayment:
\t\tamount: 100.00
\t\tfrom_credit: true
\t\tcredit_dated: 2026-02-01
\t\ttxn_guid: "TXN_GUID"
\t\ttxn_split_guid: "SPLIT_GUID"
'''


def test_both_records_unapplied_off_a_part_sold_credit(tmp_path, capsys):
    """Both records taken off a part-sold credit, which does *not* reach it.

    100.00 USD invoice overpaid with 200.00, 80.00 of the credit sold, the
    credit then spent whole on a second invoice, and both records unapplied.
    By the second unapply the transaction is already priced by the first —
    so the bank split is already a cost basis, and an edit only opens what it
    *made* one. Measured: `none recorded`, with or without the spent-credit
    check.
    """
    runner = CliRunner()
    book = tmp_path / 'both.gnucash'
    rates = 'tests/fixtures/fx_rates_usd_dated.yaml'
    assert runner.invoke(cli, [
        'import', '--new', str(book),
        'tests/fixtures/fx_invoice_usd_overpaid_into_usd_bank.txt',
        '--include-business-objects', '--fx-rates', rates]).exit_code == 0

    credit = next(line.split()[1] for line in _balances(runner, book).splitlines()
                  if 'Accounts Receivable USD' in line and '2026-02-25' in line)
    sale = tmp_path / 'sale.txt'
    sale.write_text(Path('tests/fixtures/fx_sell_part_of_a_credit.txt')
                    .read_text().replace('{basis}', credit))
    sold = _run(runner, 'import', str(book), str(sale), '--fx-rates', rates)
    spent = _run(runner, 'import', str(book),
                 'tests/fixtures/fx_invoice_auto_applying_the_whole_credit.txt',
                 '--include-business-objects', '--fx-rates', rates)
    after_spend = _balances(runner, book)

    first = _run(runner, 'unapply-payment', str(book), 'INV-USD-OVER',
                 '--to', 'Assets:Bank', '--fx-rates', rates)
    second = _run(runner, 'unapply-payment', str(book), 'INV-USD-AUTO',
                  '--to', 'Assets:Bank', '--fx-rates', rates)

    with capsys.disabled():
        print()
        print(f'sold 80: exit {sold.exit_code}; spent whole: '
              f'exit {spent.exit_code}')
        print(after_spend)
        print(f'unapplied the first: exit {first.exit_code}; '
              f'the second: exit {second.exit_code}')
        print(_balances(runner, book))


A_VENDOR_CLAIM_PAID_IN_CAD = '''\
2026-01-01 commodity CAD
\tmnemonic: "CAD"
\tfullname: "Canadian Dollar"
\tnamespace: "CURRENCY"
\tfraction: 100
2026-01-01 commodity USD
\tmnemonic: "USD"
\tfullname: "US Dollar"
\tnamespace: "CURRENCY"
\tfraction: 100
2026-01-01 open Assets
\ttype: Asset
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Assets:Bank
\ttype: Bank
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Assets:Bank:USD
\ttype: Bank
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "USD"
2026-01-01 open Liabilities
\ttype: Liability
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Liabilities:Accounts Payable USD
\ttype: Accounts Payable
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "USD"
2026-01-01 open Expenses
\ttype: Expense
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Expenses:Supplies
\ttype: Expense
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Income
\ttype: Income
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Income:FX Gain
\ttype: Income
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"

vendor "V-US"
\tname: "US Supplier"
\tcurrency: USD

2026-02-01 * "Prepaid the supplier 100 USD, paid in CAD"
\tcurrency.mnemonic: "CAD"
\tLiabilities:Accounts Payable USD 100.00 USD
\t\taccount.commodity.mnemonic: "USD"
\t\tshare_price: "1.37"
\t\tvalue: "137.00"
\t\tlot_owner: "vendor:V-US"
\tAssets:Bank -137.00 CAD
\t\taccount.commodity.mnemonic: "CAD"
'''

A_BILL_SPENDING_THE_CLAIM = '''\
bill "BILL-SPENDS-IT"
\tvendor_id: "V-US"
\tcurrency: USD
\tdate_opened: 2026-03-01
\tentry:
\t\tdate: 2026-03-01
\t\tdescription: "Supplies"
\t\taccount: "Expenses:Supplies"
\t\tquantity: 1
\t\tprice: 100
\t\ttaxable: false
\t\ttax_included: false
\tposted:
\t\tdate: 2026-03-01
\t\tdue: 2026-04-01
\t\tap_account: "Liabilities:Accounts Payable USD"
\t\tmemo: "BILL-SPENDS-IT"
\t\taccumulate: true
\tpayment:
\t\tamount: 100.00
\t\tfrom_credit: true
\t\tcredit_dated: 2026-02-01
\t\ttxn_guid: "TXN_GUID"
\t\ttxn_split_guid: "SPLIT_GUID"
'''


def test_a_vendor_claim_part_sold_then_spent_by_a_bill(tmp_path, capsys):
    """The payable side, where the claim on the vendor is a positive split.

    100.00 USD prepaid to a supplier out of a CAD bank, 80.00 of it sold, and
    a bill then spends the claim whole. Unapplying that bill puts the claim
    split on a USD bank, priced by the CAD split beside it — a purchase of
    100.00 USD, of which only 20.00 was left.
    """
    runner = CliRunner()
    book = tmp_path / 'vendor.gnucash'
    rates = 'tests/fixtures/fx_rates_usd_dated.yaml'

    def write(name, text):
        path = tmp_path / name
        path.write_text(text, encoding='utf-8')
        return str(path)

    opened = runner.invoke(cli, [
        'import', '--new', str(book),
        write('open.txt', A_VENDOR_CLAIM_PAID_IN_CAD),
        '--include-business-objects', '--fx-rates', rates])
    listing = _balances(runner, book)
    claim = next((line.split()[1] for line in listing.splitlines()
                  if 'Accounts Payable USD' in line), None)
    sold = spent = unapplied = None
    if claim:
        sold = _run(runner, 'import', str(book),
                    write('sale.txt', A_SALE_OF_80.replace('{basis}', claim)),
                    '--fx-rates', rates)
        out = tmp_path / 'tx.txt'
        _run(runner, 'export', str(book), str(out))
        tx = re.search(r'2026-02-01 \* "Prepaid[^\n]*\n\t+guid: '
                       r'"([0-9a-f]{32})"', out.read_text()).group(1)
        spent = _run(runner, 'import', str(book),
                     write('bill.txt', A_BILL_SPENDING_THE_CLAIM
                           .replace('TXN_GUID', tx)
                           .replace('SPLIT_GUID', claim)),
                     '--include-business-objects', '--fx-rates', rates)
        unapplied = _run(runner, 'unapply-payment', str(book),
                         'BILL-SPENDS-IT', '--bill',
                         '--to', 'Assets:Bank:USD', '--fx-rates', rates)

    with capsys.disabled():
        print()
        print(f'opened: exit {opened.exit_code}')
        print(listing)
        for label, result in (('sold 80', sold), ('a bill spent it', spent),
                              ('unapplied the bill', unapplied)):
            if result is None:
                continue
            print(f'{label}: exit {result.exit_code}')
            for line in (result.output + str(result.exception)).splitlines():
                if 'rror' in line or 'refus' in line:
                    print('   ', line.strip()[:150])
        print(_balances(runner, book))


def _the_prepayment_tx(runner, book):
    """The guid of the transaction the prepayment arrived on."""
    out = book.parent / 'txids.txt'
    assert _run(runner, 'export', str(book), str(out)).exit_code == 0
    return re.search(r'2026-02-01 \* "Customer prepaid[^\n]*\n\t+guid: '
                     r'"([0-9a-f]{32})"', out.read_text()).group(1)


def test_a_credit_part_sold_then_spent_whole(tmp_path, capsys):
    """The customer side of the vendor case below, which does *not* reach it.

    A credit of 100.00 USD with 80.00 sold, spent whole on an invoice, and
    that invoice unapplied. The transaction holds nothing else — no second
    settlement, no other credit, no orphan — so every question the guard asks
    answers no, and still nothing is opened.

    A customer's credit is money owed back and sits **negative** on the
    receivable, so moving it to a bank account takes currency out rather than
    bringing it in and it establishes no cost basis. A claim on a vendor is a
    debit, and does — which is why the shape that reaches this is the payable
    one.
    """
    runner = CliRunner()
    book = tmp_path / 'credit.gnucash'
    rates = 'tests/fixtures/fx_rates_usd_dated.yaml'

    def write(name, text):
        path = tmp_path / name
        path.write_text(text, encoding='utf-8')
        return str(path)

    assert runner.invoke(cli, [
        'import', '--new', str(book), write('open.txt', A_CAD_PAID_CREDIT),
        '--include-business-objects', '--fx-rates', rates]).exit_code == 0

    listing = _balances(runner, book)
    credit = next(line.split()[1] for line in listing.splitlines()
                  if 'Accounts Receivable USD' in line)
    sold = _run(runner, 'import', str(book),
                write('sale.txt', A_SALE_OF_80.replace('{basis}', credit)),
                '--fx-rates', rates)
    after_sale = _balances(runner, book)

    prepaid = next(line for line in _balances(runner, book).splitlines()
                   if 'Accounts Receivable USD' in line)
    spent = _run(runner, 'import', str(book),
                 write('spend.txt', AN_INVOICE_SPENDING_IT
                       .replace('TXN_GUID', _the_prepayment_tx(runner, book))
                       .replace('SPLIT_GUID', prepaid.split()[1])),
                 '--include-business-objects', '--fx-rates', rates)
    unapplied = _run(runner, 'unapply-payment', str(book), 'INV-SPENDS-IT',
                     '--to', 'Assets:Bank:USD', '--fx-rates', rates)

    with capsys.disabled():
        print()
        print(f'sold 80 of it: exit {sold.exit_code}')
        print(after_sale)
        print(f'an invoice spent it whole: exit {spent.exit_code}')
        for line in spent.output.splitlines():
            if 'rror' in line or 'refus' in line or 'cost basis' in line:
                print('   ', line.strip()[:160])
        print(f'unapplied that invoice: exit {unapplied.exit_code}')
        for line in (unapplied.output + str(unapplied.exception)).splitlines():
            if line.strip():
                print('   ', line.strip()[:160])
        print(_balances(runner, book))


def _with_payment(text, header, payment_lines):
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(header))
    end = start + 1
    while end < len(lines) and (lines[end].startswith('\t')
                                or not lines[end].strip()):
        end += 1
    block = [line for line in lines[start:end]
             if line.strip() != 'payment: none']
    return '\n'.join(lines[:start] + block + payment_lines + lines[end:]) + '\n'


def test_a_shared_deposit_whose_other_share_is_still_loose(tmp_path, capsys):
    """3,740.00 USD settling two invoices, with only the first one linked.

    The second invoice's 1,020.00 share is on the receivable and in no lot at
    all — nobody's lot owns it, no unpost orphaned it, and it is no cost basis
    — so every question the guard asks about it answers no.
    """
    runner = CliRunner()
    book = tmp_path / 'loose.gnucash'
    assert runner.invoke(cli, [
        'import', '--new', str(book),
        'tests/fixtures/fx_two_usd_invoices_posted.txt',
        '--include-business-objects', '--fx-rates', RATES]).exit_code == 0
    assert _run(runner, 'import', str(book),
                'tests/fixtures/fx_one_usd_deposit_settling_two_invoices.txt'
                ).exit_code == 0

    out = tmp_path / 'out.txt'
    assert _run(runner, 'export', str(book), str(out),
                '--include-business-objects').exit_code == 0
    linked = tmp_path / 'one.txt'
    linked.write_text(_with_payment(out.read_text(), 'invoice "INV-USD-001"', [
        '\tpayment:',
        '\t\tdate: 2026-08-13',
        '\t\tamount: 2720',
        f'\t\taccount: "{BANK_USD}"',
        '\t\ttxn_guid: "5a1e77cc11d34cf0b2b0c0d5aa9e3311"',
        '\t\ttxn_split_guid: "5a1e77cc11d34cf0b2b0c0d5aa9e3313"',
    ]))
    applied = _run(runner, 'import', str(book), str(linked),
                   '--include-business-objects', '--fx-rates', RATES,
                   '--strategy', 'update')

    unapplied = _run(runner, 'unapply-payment', str(book), 'INV-USD-001',
                     '--to', DUE_FROM, '--fx-rates', RATES)
    after = _balances(runner, book)

    with capsys.disabled():
        print()
        print(f'--- linked the first only: exit {applied.exit_code} ---')
        print(f'--- unapplied it: exit {unapplied.exit_code} ---')
        print(after)


def test_a_transaction_restated_into_a_purchase_by_an_unapply(tmp_path,
                                                              capsys):
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    assert runner.invoke(cli, [
        'import', '--new', str(book),
        'tests/fixtures/fx_two_usd_invoices_posted.txt',
        '--include-business-objects', '--fx-rates', RATES]).exit_code == 0
    assert _run(runner, 'import', str(book),
                'tests/fixtures/fx_usd_deposit_against_due_from_director.txt'
                ).exit_code == 0
    as_imported = _line_for(runner, book, DEPOSIT_SPLIT)

    out = tmp_path / 'out.txt'
    assert _run(runner, 'export', str(book), str(out),
                '--include-business-objects').exit_code == 0
    text = out.read_text()
    deposit_tx = re.search(
        r'2026-08-13 \* "Received[^\n]*\n\t+guid: "([0-9a-f]{32})"',
        text).group(1)
    linked = tmp_path / 'linked.txt'
    linked.write_text(_with_payment(text, 'invoice "INV-USD-001"', [
        '\tpayment:',
        '\t\tdate: 2026-08-13',
        '\t\tamount: 2720',
        f'\t\taccount: "{BANK_USD}"',
        f'\t\ttxn_guid: "{deposit_tx}"',
    ]))
    assert _run(runner, 'import', str(book), str(linked),
                '--include-business-objects', '--fx-rates', RATES,
                '--strategy', 'update').exit_code == 0
    while_linked = _line_for(runner, book, DEPOSIT_SPLIT)

    assert _run(runner, 'unapply-payment', str(book), 'INV-USD-001',
                '--to', DUE_FROM, '--fx-rates', RATES).exit_code == 0
    unlinked = _line_for(runner, book, DEPOSIT_SPLIT)

    fresh, rebuilt, ledger = _rebuilt(runner, book, tmp_path, 'unlinked-again')
    there = _line_for(runner, fresh, DEPOSIT_SPLIT)

    with capsys.disabled():
        print()
        print('as imported:             ', as_imported)
        print('while linked:            ', while_linked)
        print('after the unapply:       ', unlinked)
        print(f'rebuilt from its ledger: exit {rebuilt.exit_code}')
        print('in the rebuilt book:     ', there)
        print('what the ledger states for it:')
        block = re.search(r'2026-08-13 \* "Received[^\n]*\n(?:\t[^\n]*\n)*',
                          ledger.read_text()).group(0)
        for one in block.splitlines():
            print('   ', one)
