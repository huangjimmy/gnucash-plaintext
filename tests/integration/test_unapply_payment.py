"""`unapply-payment` peels a payment off a still-posted invoice/bill.

The payment's AR/AP split is detached from the record's lot (so the invoice
returns to Outstanding, or partial if other payments remain) and re-homed to
`--to <account>`; the document stays posted and the bank tx is never deleted.
`--to` is required and accepts any account type.
"""

from fractions import Fraction
from pathlib import Path

from click.testing import CliRunner

from cli.main import cli

ACCOUNTS = 'tests/fixtures/payment_roundtrip_accounts.txt'

INV_ONE_PAYMENT = """\
customer "C1"
\tname: "Cust One"
\tcurrency: CAD

invoice "INV-1"
\tcustomer_id: "C1"
\tcurrency: CAD
\tdate_opened: 2026-01-01
\tentry:
\t\tdate: 2026-01-01
\t\tdescription: "Svc"
\t\taccount: "Income:Sales"
\t\tquantity: 1
\t\tprice: 100
\t\ttaxable: false
\t\ttax_included: false
\tposted:
\t\tdate: 2026-01-01
\t\tdue: 2026-01-31
\t\tar_account: "Assets:Accounts Receivable"
\t\tmemo: "INV-1"
\t\taccumulate: true
\tpayment:
\t\tdate: 2026-01-15
\t\tamount: 40
\t\tbank_account: "Assets:Bank"
\t\tmemo: "partial 40"
"""

INV_TWO_PAYMENTS = INV_ONE_PAYMENT.replace('"INV-1"', '"INV-2"').replace(
    'memo: "INV-1"', 'memo: "INV-2"') + """\
\tpayment:
\t\tdate: 2026-01-20
\t\tamount: 30
\t\tbank_account: "Assets:Bank"
\t\tmemo: "partial 30"
"""


def _runner():
    return CliRunner()


def _new_book(runner, tmp_path):
    gf = tmp_path / 'book.gnucash'
    r = runner.invoke(cli, ['import', '--new', str(gf), ACCOUNTS])
    assert r.exit_code == 0, r.output
    return gf


def _import(runner, gf, text, name, tmp_path):
    p = tmp_path / name
    p.write_text(text)
    r = runner.invoke(cli, ['import', str(gf), str(p),
                            '--include-business-objects'])
    assert r.exit_code == 0, r.output
    return r


def _bal(gf, name):
    from repositories.gnucash_repository import GnuCashRepository
    repo = GnuCashRepository(str(gf))
    repo.open()
    try:
        out = {}

        def walk(a):
            out[a.get_full_name()] = round(a.GetBalance().to_double(), 2)
            for c in a.get_children():
                walk(c)
        walk(repo.book.get_root_account())
        return out.get(name, 0.0)
    finally:
        repo.close()


def _bank_tx_count(gf, bank='Assets.Bank'):
    from repositories.gnucash_repository import GnuCashRepository
    repo = GnuCashRepository(str(gf))
    repo.open()
    try:
        def find(a, name):
            if a.get_full_name() == name:
                return a
            for c in a.get_children():
                g = find(c, name)
                if g:
                    return g
            return None
        b = find(repo.book.get_root_account(), bank)
        return len({s.GetParent().GetGUID().to_string() for s in b.GetSplitList()})
    finally:
        repo.close()


def test_unapply_single_payment_reopens_invoice_and_rehomes(tmp_path):
    runner = _runner()
    gf = _new_book(runner, tmp_path)
    _import(runner, gf, INV_ONE_PAYMENT, 'inv.txt', tmp_path)

    # before: AR = 100 (posting) - 40 (payment) = 60 outstanding
    assert _bal(gf, 'Assets.Accounts Receivable') == 60.0

    r = runner.invoke(cli, ['unapply-payment', str(gf), 'INV-1',
                            '--to', 'Liabilities'])
    assert r.exit_code == 0, r.output
    assert 'unapplied 1 payment' in r.output, r.output

    # AR back to full outstanding; the $40 re-homed to Liabilities; bank intact.
    assert _bal(gf, 'Assets.Accounts Receivable') == 100.0
    assert abs(_bal(gf, 'Liabilities')) == 40.0
    assert _bal(gf, 'Assets.Bank') == 40.0
    assert _bank_tx_count(gf) == 1, 'bank tx must not be deleted'


def test_unapply_one_of_two_payments_leaves_partial(tmp_path):
    runner = _runner()
    gf = _new_book(runner, tmp_path)
    _import(runner, gf, INV_TWO_PAYMENTS, 'inv.txt', tmp_path)
    # AR = 100 - 40 - 30 = 30 outstanding
    assert _bal(gf, 'Assets.Accounts Receivable') == 30.0

    # find the $30 payment tx guid
    from repositories.gnucash_repository import GnuCashRepository
    repo = GnuCashRepository(str(gf))
    repo.open()
    try:
        def find(a, name):
            if a.get_full_name() == name:
                return a
            for c in a.get_children():
                g = find(c, name)
                if g:
                    return g
            return None
        bank = find(repo.book.get_root_account(), 'Assets.Bank')
        guid30 = next(s.GetParent().GetGUID().to_string()
                      for s in bank.GetSplitList()
                      if Fraction(s.GetAmount().num(), s.GetAmount().denom()) == 30)
    finally:
        repo.close()

    r = runner.invoke(cli, ['unapply-payment', str(gf), 'INV-2',
                            '--txn', guid30, '--to', 'Liabilities'])
    assert r.exit_code == 0, r.output
    # the $40 stays applied → outstanding 60 (partial); the $30 re-homed
    assert _bal(gf, 'Assets.Accounts Receivable') == 60.0
    assert abs(_bal(gf, 'Liabilities')) == 30.0


def test_unapply_all_returns_fully_outstanding(tmp_path):
    runner = _runner()
    gf = _new_book(runner, tmp_path)
    _import(runner, gf, INV_TWO_PAYMENTS, 'inv.txt', tmp_path)

    r = runner.invoke(cli, ['unapply-payment', str(gf), 'INV-2',
                            '--all', '--to', 'Liabilities'])
    assert r.exit_code == 0, r.output
    assert _bal(gf, 'Assets.Accounts Receivable') == 100.0   # fully outstanding
    assert abs(_bal(gf, 'Liabilities')) == 70.0              # 40 + 30 re-homed


def test_multi_payment_without_selector_errors(tmp_path):
    runner = _runner()
    gf = _new_book(runner, tmp_path)
    _import(runner, gf, INV_TWO_PAYMENTS, 'inv.txt', tmp_path)
    r = runner.invoke(cli, ['unapply-payment', str(gf), 'INV-2',
                            '--to', 'Liabilities'])
    assert r.exit_code != 0
    assert '2 payments' in r.output and ('--txn' in r.output or '--all' in r.output), r.output
    # book untouched
    assert _bal(gf, 'Assets.Accounts Receivable') == 30.0


def test_to_is_required(tmp_path):
    runner = _runner()
    gf = _new_book(runner, tmp_path)
    _import(runner, gf, INV_ONE_PAYMENT, 'inv.txt', tmp_path)
    r = runner.invoke(cli, ['unapply-payment', str(gf), 'INV-1'])
    assert r.exit_code != 0
    assert '--to' in r.output, r.output


def test_unapply_unknown_invoice_errors(tmp_path):
    runner = _runner()
    gf = _new_book(runner, tmp_path)
    _import(runner, gf, INV_ONE_PAYMENT, 'inv.txt', tmp_path)
    r = runner.invoke(cli, ['unapply-payment', str(gf), 'NOPE',
                            '--to', 'Liabilities'])
    assert r.exit_code != 0
    assert 'not found' in r.output.lower(), r.output


def test_unapply_to_unknown_account_errors(tmp_path):
    runner = _runner()
    gf = _new_book(runner, tmp_path)
    _import(runner, gf, INV_ONE_PAYMENT, 'inv.txt', tmp_path)
    r = runner.invoke(cli, ['unapply-payment', str(gf), 'INV-1',
                            '--to', 'Nonexistent:Account'])
    assert r.exit_code != 0
    assert 'not found' in r.output.lower(), r.output


BILL_ONE_PAYMENT = """\
vendor "V1"
\tname: "Vend One"
\tcurrency: CAD

bill "BILL-1"
\tvendor_id: "V1"
\tcurrency: CAD
\tdate_opened: 2026-01-01
\tentry:
\t\tdate: 2026-01-01
\t\tdescription: "Supplies"
\t\taccount: "Expenses:Supplies"
\t\tquantity: 1
\t\tprice: 100
\t\ttaxable: false
\tposted:
\t\tdate: 2026-01-01
\t\tdue: 2026-01-31
\t\tap_account: "Liabilities:Accounts Payable"
\t\tmemo: "BILL-1"
\t\taccumulate: true
\tpayment:
\t\tdate: 2026-01-15
\t\tamount: 40
\t\tbank_account: "Assets:Bank"
\t\tmemo: "partial 40"
"""


def _all_splits(gf, account):
    from repositories.gnucash_repository import GnuCashRepository
    repo = GnuCashRepository(str(gf))
    repo.open()
    try:
        def find(a, name):
            if a.get_full_name() == name:
                return a
            for c in a.get_children():
                g = find(c, name)
                if g:
                    return g
            return None
        acct = find(repo.book.get_root_account(), account)
        # Exact amount via num()/denom() as a Fraction — never to_double()
        # (float can't represent decimals exactly) and never to_decimal()
        # (its signature varies across GnuCash versions). The caller keys on
        # the split GUID; the amount is only an exact coarse filter.
        def _exact(s):
            a = s.GetAmount()
            return Fraction(a.num(), a.denom())
        return [(s.GetGUID().to_string(),                 # split's own guid
                 s.GetParent().GetGUID().to_string(),     # parent tx guid
                 _exact(s)) for s in acct.GetSplitList()]
    finally:
        repo.close()


def test_unapply_one_of_several_invoices_on_one_bank_tx(tmp_path):
    """One $400 bank tx pays INV A/B/C ($100/$120/$180). Unapply B only:
    B reopens to Outstanding $120; A and C stay paid; the bank tx survives."""
    runner = _runner()
    gf = _new_book(runner, tmp_path)

    # pre-existing $400 bank tx with 3 AR splits
    p = tmp_path / 'bank.txt'
    p.write_text(Path('tests/fixtures/q016_multi_invoice_bank.txt').read_text())
    r = runner.invoke(cli, ['import', str(gf), str(p)])
    assert r.exit_code == 0, r.output

    splits = _all_splits(gf, 'Assets.Accounts Receivable')
    bank_guid = next(txg for _spg, txg, a in _all_splits(gf, 'Assets.Bank')
                     if a == 400)
    sg = {a: spg for spg, _txg, a in splits}   # keys are exact Decimals
    inv_text = Path('tests/fixtures/q016_multi_invoice_invoices.txt').read_text().format(
        bank_txn_guid=bank_guid,
        split_guid_a=sg[-100], split_guid_b=sg[-120], split_guid_c=sg[-180])
    p2 = tmp_path / 'invs.txt'
    p2.write_text(inv_text)
    r = runner.invoke(cli, ['import', str(gf), str(p2), '--include-business-objects'])
    assert r.exit_code == 0, r.output

    # all 3 paid → AR net 0
    assert _bal(gf, 'Assets.Accounts Receivable') == 0.0

    r = runner.invoke(cli, ['unapply-payment', str(gf), 'INV-Q16-B-120',
                            '--to', 'Liabilities'])
    assert r.exit_code == 0, r.output

    # only B reopened: AR = +400 posting − 100(A) − 180(C) = +120 (B outstanding)
    assert _bal(gf, 'Assets.Accounts Receivable') == 120.0
    assert abs(_bal(gf, 'Liabilities')) == 120.0   # B's -120 re-homed
    assert _bank_tx_count(gf) == 1, 'the shared bank tx must survive'


def test_unapply_bill_payment(tmp_path):
    runner = _runner()
    gf = _new_book(runner, tmp_path)
    _import(runner, gf, BILL_ONE_PAYMENT, 'bill.txt', tmp_path)
    # AP = -100 posting + 40 payment = -60 (owe 60)
    assert _bal(gf, 'Liabilities.Accounts Payable') == -60.0

    r = runner.invoke(cli, ['unapply-payment', str(gf), 'BILL-1', '--bill',
                            '--to', 'Liabilities'])
    assert r.exit_code == 0, r.output
    # AP back to fully owed; the +40 re-homed
    assert _bal(gf, 'Liabilities.Accounts Payable') == -100.0
    assert abs(_bal(gf, 'Liabilities')) == 40.0


def test_invoice_stays_posted_after_unapply_and_roundtrips(tmp_path):
    runner = _runner()
    gf = _new_book(runner, tmp_path)
    _import(runner, gf, INV_ONE_PAYMENT, 'inv.txt', tmp_path)
    r = runner.invoke(cli, ['unapply-payment', str(gf), 'INV-1', '--to', 'Liabilities'])
    assert r.exit_code == 0, r.output
    out = tmp_path / 'exp.txt'
    r = runner.invoke(cli, ['export', str(gf), str(out), '--include-business-objects'])
    assert r.exit_code == 0, r.output
    text = out.read_text()
    # still a posted invoice (not draft / not none), now with no payment
    assert 'invoice "INV-1"' in text
    assert 'posted:' in text and 'posted: none' not in text, text


# Two payments of the SAME amount — the case that breaks any amount-based
# matching (a float key collides, and even exact amounts can't disambiguate
# two identical payments). Selection must be by transaction GUID.
INV_TWO_SAME = INV_ONE_PAYMENT.replace('"INV-1"', '"INV-SAME"').replace(
    'memo: "INV-1"', 'memo: "INV-SAME"').replace('memo: "partial 40"', 'memo: "first 40"') + """\
\tpayment:
\t\tdate: 2026-01-20
\t\tamount: 40
\t\tbank_account: "Assets:Bank"
\t\tmemo: "second 40"
"""


def test_unapply_one_of_two_same_amount_payments_by_guid(tmp_path):
    runner = _runner()
    gf = _new_book(runner, tmp_path)
    _import(runner, gf, INV_TWO_SAME, 'inv.txt', tmp_path)
    # AR = 100 - 40 - 40 = 20 outstanding
    assert _bal(gf, 'Assets.Accounts Receivable') == 20.0

    # two $40 bank txs — distinguishable only by GUID, not amount
    forties = sorted({txg for _spg, txg, a in _all_splits(gf, 'Assets.Bank')
                      if a == 40})
    assert len(forties) == 2, forties

    # peel exactly one of them, named by its GUID
    r = runner.invoke(cli, ['unapply-payment', str(gf), 'INV-SAME',
                            '--txn', forties[0], '--to', 'Liabilities'])
    assert r.exit_code == 0, r.output

    # one $40 remains applied → outstanding 60; exactly one $40 re-homed; both
    # bank txs still present (nothing deleted)
    assert _bal(gf, 'Assets.Accounts Receivable') == 60.0
    assert abs(_bal(gf, 'Liabilities')) == 40.0
    assert _bank_tx_count(gf) == 2


# Three payments, two wrong — repeatable --txn peels exactly the named subset.
INV_THREE = INV_ONE_PAYMENT.replace('"INV-1"', '"INV-3P"').replace(
    'memo: "INV-1"', 'memo: "INV-3P"').replace('memo: "partial 40"', 'memo: "p40"') + """\
\tpayment:
\t\tdate: 2026-01-18
\t\tamount: 30
\t\tbank_account: "Assets:Bank"
\t\tmemo: "p30"
\tpayment:
\t\tdate: 2026-01-20
\t\tamount: 20
\t\tbank_account: "Assets:Bank"
\t\tmemo: "p20"
"""


def test_unapply_two_of_three_payments_via_repeated_txn(tmp_path):
    runner = _runner()
    gf = _new_book(runner, tmp_path)
    _import(runner, gf, INV_THREE, 'inv.txt', tmp_path)
    # AR = 100 - 40 - 30 - 20 = 10 outstanding
    assert _bal(gf, 'Assets.Accounts Receivable') == 10.0

    bank = {a: txg for _spg, txg, a in _all_splits(gf, 'Assets.Bank')}
    g40, g20 = bank[40], bank[20]

    # peel the $40 and $20, leaving the $30 applied
    r = runner.invoke(cli, ['unapply-payment', str(gf), 'INV-3P',
                            '--txn', g40, '--txn', g20, '--to', 'Liabilities'])
    assert r.exit_code == 0, r.output
    assert 'unapplied 2 payments' in r.output, r.output

    # the $30 stays applied → outstanding 70; the $40+$20 = $60 re-homed
    assert _bal(gf, 'Assets.Accounts Receivable') == 70.0
    assert abs(_bal(gf, 'Liabilities')) == 60.0
    assert _bank_tx_count(gf) == 3, 'all three bank txs survive'
