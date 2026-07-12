"""Probe: observed vendor-bill payment behaviour (overpayment + partial).

Grounds the docs in tests/../docs for AP-side bill payments. Imports real
bills through the production CLI, posts + pays them, then prints the REAL
posting-transaction splits, the REAL AP lot balances/signs and split
lists, and the REAL exported plaintext block (via the production
exporter). Nothing here is hand-computed — the docs copy these numbers.

Run in Docker (not collected by pytest — no `test_` prefix):

    docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp/home \
        -v "$PWD:/workspace" -w /workspace gnucash-dev:latest bash -c \
        'python3 -m pip install -e . weasyprint --break-system-packages \
         --user -q; python3 tests/research/bill_payment_reconciliation_probe.py'
"""
import tempfile
from pathlib import Path

from click.testing import CliRunner

from cli.main import cli
from infrastructure.gnucash.utils import wrap_invoice_or_bill

ACCOUNTS = 'tests/fixtures/payment_roundtrip_accounts.txt'

VENDOR = '''
vendor "V001"
\tname: "Supplier Co."
\tcurrency: CAD
'''

# A) Overpayment: $100 bill paid $150 in one payment.
BILL_OVERPAY = VENDOR + '''
bill "BILL-OVERPAY-100"
\tvendor_id: "V001"
\tcurrency: CAD
\tdate_opened: 2026-01-01
\tentry:
\t\tdate: 2026-01-01
\t\tdescription: "Materials"
\t\taccount: "Expenses:Supplies"
\t\tquantity: 1
\t\tprice: 100
\t\ttaxable: false
\t\ttax_included: false
\tposted:
\t\tdate: 2026-01-01
\t\tdue: 2026-01-31
\t\tap_account: "Liabilities:Accounts Payable"
\t\tmemo: "Bill BILL-OVERPAY-100"
\t\taccumulate: true
\tpayment:
\t\tdate: 2026-01-10
\t\tamount: 150
\t\tbank_account: "Assets:Bank"
\t\tmemo: "Paid 150 on a 100 bill (overpaid 50)"
\t\tprepayment: 50
'''

# B) Partial payments: $100 bill, two instalments ($40 + $35), $25 open.
BILL_PARTIAL = VENDOR + '''
bill "BILL-PARTIAL-100"
\tvendor_id: "V001"
\tcurrency: CAD
\tdate_opened: 2026-02-01
\tentry:
\t\tdate: 2026-02-01
\t\tdescription: "Materials"
\t\taccount: "Expenses:Supplies"
\t\tquantity: 1
\t\tprice: 100
\t\ttaxable: false
\t\ttax_included: false
\tposted:
\t\tdate: 2026-02-01
\t\tdue: 2026-03-03
\t\tap_account: "Liabilities:Accounts Payable"
\t\tmemo: "Bill BILL-PARTIAL-100"
\t\taccumulate: true
\tpayment:
\t\tdate: 2026-02-10
\t\tamount: 40
\t\tbank_account: "Assets:Bank"
\t\tmemo: "First instalment"
\tpayment:
\t\tdate: 2026-02-20
\t\tamount: 35
\t\tbank_account: "Assets:Bank"
\t\tmemo: "Second instalment"
'''


# C) One vendor, three bills in different payment states — to exercise
#    detection across a whole vendor (paid / partial / overpaid).
BILLS_MIXED = VENDOR + '''
bill "BILL-PAID-100"
\tvendor_id: "V001"
\tcurrency: CAD
\tdate_opened: 2026-03-01
\tentry:
\t\tdate: 2026-03-01
\t\tdescription: "Fully paid"
\t\taccount: "Expenses:Supplies"
\t\tquantity: 1
\t\tprice: 100
\t\ttaxable: false
\t\ttax_included: false
\tposted:
\t\tdate: 2026-03-01
\t\tdue: 2026-03-31
\t\tap_account: "Liabilities:Accounts Payable"
\t\tmemo: "Bill BILL-PAID-100"
\t\taccumulate: true
\tpayment:
\t\tdate: 2026-03-05
\t\tamount: 100
\t\tbank_account: "Assets:Bank"
\t\tmemo: "Paid in full"

bill "BILL-PART-100"
\tvendor_id: "V001"
\tcurrency: CAD
\tdate_opened: 2026-03-02
\tentry:
\t\tdate: 2026-03-02
\t\tdescription: "Partly paid"
\t\taccount: "Expenses:Supplies"
\t\tquantity: 1
\t\tprice: 100
\t\ttaxable: false
\t\ttax_included: false
\tposted:
\t\tdate: 2026-03-02
\t\tdue: 2026-04-01
\t\tap_account: "Liabilities:Accounts Payable"
\t\tmemo: "Bill BILL-PART-100"
\t\taccumulate: true
\tpayment:
\t\tdate: 2026-03-06
\t\tamount: 60
\t\tbank_account: "Assets:Bank"
\t\tmemo: "Part payment (40 outstanding)"

bill "BILL-OVER-100"
\tvendor_id: "V001"
\tcurrency: CAD
\tdate_opened: 2026-03-03
\tentry:
\t\tdate: 2026-03-03
\t\tdescription: "Overpaid"
\t\taccount: "Expenses:Supplies"
\t\tquantity: 1
\t\tprice: 100
\t\ttaxable: false
\t\ttax_included: false
\tposted:
\t\tdate: 2026-03-03
\t\tdue: 2026-04-02
\t\tap_account: "Liabilities:Accounts Payable"
\t\tmemo: "Bill BILL-OVER-100"
\t\taccumulate: true
\tpayment:
\t\tdate: 2026-03-07
\t\tamount: 150
\t\tbank_account: "Assets:Bank"
\t\tmemo: "Overpaid by 50"
\t\tprepayment: 50
'''


# D) Taxed bills (GST 5% + PST 7% on net 100 → total 112) overpaid and
#    partially paid — to show payment works against the TAX-INCLUSIVE total.
TAXTABLE = '''
taxtable "GST+PST"
\tentry:
\t\taccount: "Liabilities:Tax:GST"
\t\trate: 5.0%
\t\ttype: PERCENT
\tentry:
\t\taccount: "Liabilities:Tax:PST"
\t\trate: 7.0%
\t\ttype: PERCENT
'''

TAXED_BILLS = TAXTABLE + VENDOR + '''
bill "BILL-TAX-OVER-112"
\tvendor_id: "V001"
\tcurrency: CAD
\tdate_opened: 2026-04-01
\tentry:
\t\tdate: 2026-04-01
\t\tdescription: "Materials (net 100 + 12% tax = 112)"
\t\taccount: "Expenses:Office Supplies"
\t\tquantity: 1
\t\tprice: 100
\t\ttaxable: true
\t\ttax_included: false
\t\ttax_table: "GST+PST"
\tposted:
\t\tdate: 2026-04-01
\t\tdue: 2026-05-01
\t\tap_account: "Liabilities:Accounts Payable"
\t\tmemo: "Bill BILL-TAX-OVER-112"
\t\taccumulate: true
\tpayment:
\t\tdate: 2026-04-10
\t\tamount: 150
\t\tbank_account: "Assets:Bank"
\t\tmemo: "Paid 150 on a 112 bill (overpaid 38)"

bill "BILL-TAX-PART-112"
\tvendor_id: "V001"
\tcurrency: CAD
\tdate_opened: 2026-04-02
\tentry:
\t\tdate: 2026-04-02
\t\tdescription: "Materials (net 100 + 12% tax = 112)"
\t\taccount: "Expenses:Office Supplies"
\t\tquantity: 1
\t\tprice: 100
\t\ttaxable: true
\t\ttax_included: false
\t\ttax_table: "GST+PST"
\tposted:
\t\tdate: 2026-04-02
\t\tdue: 2026-05-02
\t\tap_account: "Liabilities:Accounts Payable"
\t\tmemo: "Bill BILL-TAX-PART-112"
\t\taccumulate: true
\tpayment:
\t\tdate: 2026-04-11
\t\tamount: 60
\t\tbank_account: "Assets:Bank"
\t\tmemo: "Part payment (52 outstanding on a 112 bill)"
'''


def _setup(runner, tmp):
    gf = tmp / 'book.gnucash'
    r = runner.invoke(cli, ['import', '--new', str(gf), ACCOUNTS])
    assert r.exit_code == 0, r.output
    return gf


def _balances(gf, names):
    from repositories.gnucash_repository import GnuCashRepository
    repo = GnuCashRepository(str(gf))
    repo.open()
    try:
        out = {}

        def walk(a):
            from infrastructure.gnucash.utils import get_account_full_name
            out[get_account_full_name(a)] = round(a.GetBalance().to_double(), 2)
            for c in a.get_children():
                walk(c)
        walk(repo.book.get_root_account())
        return {n: out.get(n, 0.0) for n in names}
    finally:
        repo.close()


def _dc(gf):
    """Delete stale GnuCash backup/log files so two saves in the same wall
    second don't collide on the backup filename (ERR_FILEIO_BACKUP_ERROR)."""
    for stale in gf.parent.glob(gf.name + '.*'):
        stale.unlink()


def _import(runner, gf, text, name, tmp):
    p = tmp / name
    p.write_text(text)
    _dc(gf)
    r = runner.invoke(cli, ['import', str(gf), str(p),
                            '--include-business-objects'])
    assert r.exit_code == 0, r.output


def _dump_posting_and_lots(gf, bill_id):
    import gnucash.gnucash_business as gb
    import gnucash.gnucash_core_c as gc
    from gnucash import GncLot, Query, Split

    from infrastructure.gnucash.utils import get_account_full_name
    from repositories.gnucash_repository import GnuCashRepository

    repo = GnuCashRepository(str(gf))
    repo.open()
    try:
        q = Query()
        q.search_for('gncInvoice')
        q.set_book(repo.book)
        bill = next((wrap_invoice_or_bill(r) for r in q.run()
                     if wrap_invoice_or_bill(r).GetID() == bill_id), None)
        q.destroy()
        assert bill is not None

        tx = bill.GetPostedTxn()
        print(f'  posting transaction splits ({bill_id}):')
        for i in range(tx.CountSplits()):
            sp = tx.GetSplit(i)
            print(f'    {get_account_full_name(sp.GetAccount()):32s} '
                  f'{sp.GetAmount().to_double():+.2f}')

        # AP lots for this bill's vendor.
        def find(acct, name):
            if get_account_full_name(acct) == name:
                return acct
            for c in acct.get_children():
                r = find(c, name)
                if r:
                    return r
            return None
        ap = find(repo.book.get_root_account(),
                  'Liabilities:Accounts Payable')
        seen = set()
        lots = []
        for s in ap.GetSplitList():
            raw = s.GetLot()
            if raw is None or int(raw) in seen:
                continue
            seen.add(int(raw))
            lots.append(GncLot(instance=raw))
        print(f'  AP account "{get_account_full_name(ap)}" lots:')
        for lot in lots:
            members = list(lot.get_split_list())
            print(f'    lot closed={lot.is_closed()} '
                  f'balance={lot.get_balance().to_double():+.2f} '
                  f'({len(members)} splits):')
            for raw_sp in members:
                sp = Split(instance=raw_sp)
                ptx = sp.GetParent()
                is_posting = gc.gncInvoiceGetInvoiceFromTxn(
                    ptx.instance) is not None
                print(f'        {sp.GetAmount().to_double():+.2f}  '
                      f'{"posting" if is_posting else "payment"}  '
                      f'{ptx.GetDate().strftime("%Y-%m-%d")}  '
                      f'"{sp.GetMemo()}"')
    finally:
        repo.close()


def _bill_states(gf, bill_ids):
    """For each bill id print IsPaid and the posted lot's balance (the
    still-outstanding AP amount; 0 = settled, negative = still owed,
    positive = overpaid credit)."""
    import gnucash.gnucash_business as gb
    import gnucash.gnucash_core_c as gc
    from gnucash import Query

    from repositories.gnucash_repository import GnuCashRepository
    repo = GnuCashRepository(str(gf))
    repo.open()
    try:
        q = Query()
        q.search_for('gncInvoice')
        q.set_book(repo.book)
        by_id = {wrap_invoice_or_bill(r).GetID(): wrap_invoice_or_bill(r)
                 for r in q.run()}
        q.destroy()
        for bid in bill_ids:
            bill = by_id.get(bid)
            paid = bool(gc.gncInvoiceIsPaid(bill.instance))
            lot = bill.GetPostedLot()
            bal = lot.get_balance().to_double() if lot is not None else None
            print(f'    {bid:18s} is_paid={paid!s:5s} '
                  f'posted-lot balance={bal:+.2f}')
    finally:
        repo.close()


def _export_block(runner, gf, bill_id, tmp):
    out = tmp / 'export.txt'
    r = runner.invoke(cli, ['export', str(gf), str(out),
                            '--include-business-objects'])
    assert r.exit_code == 0, r.output
    text = out.read_text()
    block = []
    grab = False
    for line in text.splitlines():
        if line.startswith(f'bill "{bill_id}"'):
            grab = True
        elif grab and line and not (line.startswith(' ')
                                    or line.startswith('\t')):
            break
        if grab:
            block.append(line)
    print(f'  exported plaintext block ({bill_id}):')
    for line in block:
        print('    ' + line)


def main():
    runner = CliRunner()
    tmp = Path(tempfile.mkdtemp())

    print('=' * 70)
    print('A) VENDOR-BILL OVERPAYMENT — $100 bill paid $150')
    print('=' * 70)
    gf = _setup(runner, tmp)
    _import(runner, gf, BILL_OVERPAY, 'overpay.txt', tmp)
    _dump_posting_and_lots(gf, 'BILL-OVERPAY-100')
    _export_block(runner, gf, 'BILL-OVERPAY-100', tmp)

    print()
    print('=' * 70)
    print('B) VENDOR-BILL PARTIAL PAYMENTS — $100 bill, $40 + $35, $25 open')
    print('=' * 70)
    gf2 = tmp / 'book2.gnucash'
    r = runner.invoke(cli, ['import', '--new', str(gf2), ACCOUNTS])
    assert r.exit_code == 0, r.output
    _import(runner, gf2, BILL_PARTIAL, 'partial.txt', tmp)
    _dump_posting_and_lots(gf2, 'BILL-PARTIAL-100')
    _export_block(runner, gf2, 'BILL-PARTIAL-100', tmp)

    print()
    print('=' * 70)
    print('C) DETECTION ACROSS ONE VENDOR — paid + partial + overpaid bills')
    print('=' * 70)
    gf3 = tmp / 'book3.gnucash'
    r = runner.invoke(cli, ['import', '--new', str(gf3), ACCOUNTS])
    assert r.exit_code == 0, r.output
    _import(runner, gf3, BILLS_MIXED, 'mixed.txt', tmp)

    ids = ['BILL-PAID-100', 'BILL-PART-100', 'BILL-OVER-100']
    print('  per-bill posted-lot state (0=settled, -=still owed, +=overpaid):')
    _bill_states(gf3, ids)

    print()
    print('  $ find-prepayments book.gnucash --vendor V001')
    r = runner.invoke(cli, ['find-prepayments', str(gf3), '--vendor', 'V001'])
    for line in r.output.splitlines():
        print('    ' + line)

    print()
    print('  $ print-bill book.gnucash --vendor V001 --format plaintext -o -')
    r = runner.invoke(cli, ['print-bill', str(gf3), '--vendor', 'V001',
                            '--format', 'plaintext', '-o', '-'])
    # Only show the bill headers + bill_total + payment amounts (compact).
    for line in r.output.splitlines():
        s = line.strip()
        if (s.startswith('bill "') or s.startswith('bill_total:')
                or s.startswith('amount:') or s.startswith('prepayment:')):
            print('    ' + line)

    print()
    print('  AP account open_prepayment: block from `export`:')
    out = tmp / 'mixed_export.txt'
    r = runner.invoke(cli, ['export', str(gf3), str(out),
                            '--include-business-objects'])
    assert r.exit_code == 0, r.output
    grab = 0
    for line in out.read_text().splitlines():
        if 'Accounts Payable' in line and line.startswith(('2', '1')):
            grab = 1
        elif grab and line and not (line.startswith(' ') or line.startswith('\t')):
            grab = 0
        if grab and ('Accounts Payable' in line or 'open_prepayment'
                     in line or line.strip().startswith(('owner:', 'amount:',
                                                         'owner_guid:'))):
            print('    ' + line)

    print()
    print('=' * 70)
    print('D) TAXED BILLS (net 100 + GST5+PST7 = 112) — overpaid + partial')
    print('=' * 70)
    gf4 = tmp / 'book4.gnucash'
    r = runner.invoke(cli, ['import', '--new', str(gf4),
                            'tests/fixtures/q019_accounts.txt'])
    assert r.exit_code == 0, r.output
    _import(runner, gf4, TAXED_BILLS, 'taxed.txt', tmp)
    print('  --- overpaid taxed bill ($112 total, paid $150) ---')
    _dump_posting_and_lots(gf4, 'BILL-TAX-OVER-112')
    _export_block(runner, gf4, 'BILL-TAX-OVER-112', tmp)
    print('  --- partially paid taxed bill ($112 total, paid $60) ---')
    _dump_posting_and_lots(gf4, 'BILL-TAX-PART-112')
    print('  per-bill posted-lot state:')
    _bill_states(gf4, ['BILL-TAX-OVER-112', 'BILL-TAX-PART-112'])
    print('  $ find-prepayments --vendor V001')
    r = runner.invoke(cli, ['find-prepayments', str(gf4), '--vendor', 'V001'])
    for line in r.output.splitlines():
        if 'CAD' in line or 'Total credit' in line or 'Found' in line:
            print('    ' + line)

    print()
    print('=' * 70)
    print('E) REFUND ACCOUNTING — which accounts move? (is it an expense?)')
    print('=' * 70)
    names = ['Assets:Bank', 'Assets:Accounts Receivable',
             'Liabilities:Accounts Payable', 'Income', 'Expenses:Supplies']

    print('  --- CUSTOMER overpaid us by $50 (invoice 100 paid 150); we refund ---')
    gfe = tmp / 'book_cust.gnucash'
    r = runner.invoke(cli, ['import', '--new', str(gfe), ACCOUNTS])
    assert r.exit_code == 0, r.output
    _import(runner, gfe, Path('tests/fixtures/q015_aac_primer_invoice.txt').read_text(),
            'cprimer.txt', tmp)
    print('    before refund:', _balances(gfe, names))
    _import(runner, gfe, Path('tests/fixtures/q_refund_prepayment.txt').read_text(),
            'crefund.txt', tmp)
    print('    after  refund:', _balances(gfe, names))

    print('  --- WE overpaid a vendor by $50 (bill 100 paid 150); vendor refunds us ---')
    gfv = tmp / 'book_vend.gnucash'
    r = runner.invoke(cli, ['import', '--new', str(gfv), ACCOUNTS])
    assert r.exit_code == 0, r.output
    _import(runner, gfv, Path('tests/fixtures/q015_aac_primer_bill.txt').read_text(),
            'vprimer.txt', tmp)
    print('    before refund:', _balances(gfv, names))
    _import(runner, gfv, Path('tests/fixtures/q_vendor_refund.txt').read_text(),
            'vrefund.txt', tmp)
    print('    after  refund:', _balances(gfv, names))


if __name__ == '__main__':
    main()
