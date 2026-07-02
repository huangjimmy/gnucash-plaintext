"""A single bank tx paying multiple invoices/bills must export each record's
`payment: amount:` as that record's own allocation (its AR/AP split in its own
lot), NOT the whole bank-tx total.

Re-import attaches each portion by `txn_split_guid:` (by GUID), so a wrong
`amount:` round-trips invisibly — the structural roundtrip test can't see it.
These tests assert the exported amount text directly.
"""

import re
from fractions import Fraction
from pathlib import Path

import pytest
from click.testing import CliRunner

from cli.main import cli

ACCOUNTS = 'tests/fixtures/payment_roundtrip_accounts.txt'


def _new_book(runner, tmp_path):
    gf = tmp_path / 'book.gnucash'
    r = runner.invoke(cli, ['import', '--new', str(gf), ACCOUNTS])
    assert r.exit_code == 0, r.output
    return gf


def _splits(gf, account):
    from repositories.gnucash_repository import GnuCashRepository
    repo = GnuCashRepository(str(gf))
    repo.open()
    try:
        def find(a, n):
            if a.get_full_name() == n:
                return a
            for c in a.get_children():
                g = find(c, n)
                if g:
                    return g
            return None
        ac = find(repo.book.get_root_account(), account)
        return [(s.GetGUID().to_string(),
                 s.GetParent().GetGUID().to_string(),
                 Fraction(s.GetAmount().num(), s.GetAmount().denom()))
                for s in ac.GetSplitList()]
    finally:
        repo.close()


def _import_text(runner, gf, text, name, tmp_path):
    p = tmp_path / name
    p.write_text(text)
    r = runner.invoke(cli, ['import', str(gf), str(p), '--include-business-objects'])
    assert r.exit_code == 0, r.output


def _export(runner, gf, tmp_path):
    out = tmp_path / 'exp.txt'
    r = runner.invoke(cli, ['export', str(gf), str(out), '--include-business-objects'])
    assert r.exit_code == 0, r.output
    return out.read_text()


def _payment_amounts(text):
    """Map invoice/bill id -> its first payment block's `amount:` value."""
    out = {}
    cur = None
    in_payment = False
    for line in text.splitlines():
        st = line.strip()
        m = re.match(r'(?:invoice|bill) "([^"]+)"', st)
        if m:
            cur = m.group(1)
            in_payment = False
            continue
        if cur and st == 'payment:':
            in_payment = True
            continue
        if cur and in_payment and st.startswith('amount:'):
            out[cur] = st.split('amount:', 1)[1].strip()
            in_payment = False
    return out


def _build_multi_invoice(runner, tmp_path):
    gf = _new_book(runner, tmp_path)
    _import_text(runner, gf, Path('tests/fixtures/q016_multi_invoice_bank.txt').read_text(),
                 'bank.txt', tmp_path)
    ar = _splits(gf, 'Assets.Accounts Receivable')
    bank_guid = next(t for _s, t, a in _splits(gf, 'Assets.Bank') if a == 400)
    sg = {a: s for s, _t, a in ar}
    inv = Path('tests/fixtures/q016_multi_invoice_invoices.txt').read_text().format(
        bank_txn_guid=bank_guid, split_guid_a=sg[-100], split_guid_b=sg[-120],
        split_guid_c=sg[-180])
    _import_text(runner, gf, inv, 'inv.txt', tmp_path)
    return gf


def _build_multi_bill(runner, tmp_path):
    gf = _new_book(runner, tmp_path)
    _import_text(runner, gf, Path('tests/fixtures/q016_multi_bill_bank.txt').read_text(),
                 'bank.txt', tmp_path)
    ap = _splits(gf, 'Liabilities.Accounts Payable')
    bank_guid = next(t for _s, t, a in _splits(gf, 'Assets.Bank') if a == -360)
    sg = {a: s for s, _t, a in ap}
    bills = Path('tests/fixtures/q016_multi_bill_bills.txt').read_text().format(
        bank_txn_guid=bank_guid, split_guid_a=sg[90], split_guid_b=sg[110],
        split_guid_c=sg[160])
    _import_text(runner, gf, bills, 'bills.txt', tmp_path)
    return gf


def test_multi_invoice_export_amount_is_per_invoice_allocation(tmp_path):
    runner = CliRunner()
    gf = _build_multi_invoice(runner, tmp_path)
    amts = _payment_amounts(_export(runner, gf, tmp_path))
    assert amts.get('INV-Q16-A-100') == '100.00', amts
    assert amts.get('INV-Q16-B-120') == '120.00', amts
    assert amts.get('INV-Q16-C-180') == '180.00', amts


def test_multi_bill_export_amount_is_per_bill_allocation(tmp_path):
    runner = CliRunner()
    gf = _build_multi_bill(runner, tmp_path)
    amts = _payment_amounts(_export(runner, gf, tmp_path))
    assert amts.get('BILL-Q16-A-90') == '90.00', amts
    assert amts.get('BILL-Q16-B-110') == '110.00', amts
    assert amts.get('BILL-Q16-C-160') == '160.00', amts


def test_print_invoice_render_amount_is_per_invoice_allocation(tmp_path):
    runner = CliRunner()
    gf = _build_multi_invoice(runner, tmp_path)
    out = tmp_path / 'inv.txt'
    r = runner.invoke(cli, ['print-invoice', str(gf), 'INV-Q16-B-120',
                            '--format', 'plaintext', '--output', str(out)])
    assert r.exit_code == 0, r.output
    assert _payment_amounts(out.read_text()).get('INV-Q16-B-120') == '120.00', out.read_text()


# A zero-decimal currency (JPY: GnuCash SCU fraction = 1) must export whole
# amounts — `1000`, never `1000.00` — proving the amount is formatted to the
# commodity's own decimal count. (GnuCash's table records KRW with fraction 100
# / 2 decimals despite real-world KRW being 0-decimal; the exporter faithfully
# follows whatever fraction the book's commodity defines.)
def _jpy_accounts(mnem):
    return '\n'.join(
        f'2026-01-01 open {name}\n'
        f'\ttype: {atype}\n'
        f'\tcommodity.namespace: "CURRENCY"\n'
        f'\tcommodity.mnemonic: "{mnem}"'
        for name, atype in [
            ('Assets', 'Asset'),
            ('Assets:Accounts Receivable', 'Accounts Receivable'),
            ('Assets:Bank', 'Bank'),
            ('Income', 'Income'),
            ('Income:Sales', 'Income'),
        ]) + '\n'


def _zero_decimal_invoice(mnem):
    return (
        f'customer "C-{mnem}"\n\tname: "Co"\n\tcurrency: {mnem}\n\n'
        f'invoice "INV-{mnem}"\n\tcustomer_id: "C-{mnem}"\n\tcurrency: {mnem}\n'
        '\tdate_opened: 2026-01-01\n'
        '\tentry:\n\t\tdate: 2026-01-01\n\t\tdescription: "Svc"\n'
        '\t\taccount: "Income:Sales"\n\t\tquantity: 1\n\t\tprice: 1000\n'
        '\t\ttaxable: false\n\t\ttax_included: false\n'
        '\tposted:\n\t\tdate: 2026-01-01\n\t\tdue: 2026-01-31\n'
        '\t\tar_account: "Assets:Accounts Receivable"\n\t\tmemo: "INV"\n'
        '\t\taccumulate: true\n'
        '\tpayment:\n\t\tdate: 2026-01-15\n\t\tamount: 1000\n'
        '\t\tbank_account: "Assets:Bank"\n\t\tmemo: "paid"\n')


@pytest.mark.parametrize('mnem', ['JPY'])
def test_zero_decimal_currency_payment_amount_has_no_decimals(tmp_path, mnem):
    runner = CliRunner()
    gf = tmp_path / 'book.gnucash'
    acc = tmp_path / 'acc.txt'
    acc.write_text(_jpy_accounts(mnem))
    assert runner.invoke(cli, ['import', '--new', str(gf), str(acc)]).exit_code == 0
    _import_text(runner, gf, _zero_decimal_invoice(mnem), 'inv.txt', tmp_path)
    amts = _payment_amounts(_export(runner, gf, tmp_path))
    assert amts.get(f'INV-{mnem}') == '1000', amts   # 0-decimal: no ".00"


def test_double_roundtrip_preserves_every_guid(tmp_path):
    """export → import (fresh book) → export must preserve EVERY GUID — account,
    transaction, split, posting-tx, and customer/vendor/invoice/bill. Account
    GUIDs were silently re-minted on import, so they drifted each roundtrip;
    this pins that all guid-bearing lines are identical across the 2nd roundtrip.
    """
    import difflib
    runner = CliRunner()
    gf_a = _build_multi_invoice(runner, tmp_path)   # accounts + bank tx + 4 splits + 3 invoices

    e1 = tmp_path / 'e1.txt'
    assert runner.invoke(cli, ['export', str(gf_a), str(e1),
                               '--include-business-objects']).exit_code == 0
    gf_b = tmp_path / 'B.gnucash'
    assert runner.invoke(cli, ['import', '--new', str(gf_b), str(e1),
                               '--include-business-objects']).exit_code == 0
    e2 = tmp_path / 'e2.txt'
    assert runner.invoke(cli, ['export', str(gf_b), str(e2),
                               '--include-business-objects']).exit_code == 0

    def guid_lines(path):
        return sorted(line.strip() for line in path.read_text().splitlines()
                      if re.search(r'guid:', line))

    g1, g2 = guid_lines(e1), guid_lines(e2)
    assert g1 == g2, 'GUIDs drifted across the roundtrip:\n' + '\n'.join(
        difflib.unified_diff(g1, g2, 'export1', 'export2', lineterm=''))
