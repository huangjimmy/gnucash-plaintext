"""
Bill-side mirror of `test_post_pay_unpost_cycle.py`.

Same six-step lifecycle (create → post → pay → unpost → re-post → re-pay)
but for a vendor bill instead of a customer invoice. The point is to
check whether the orphan-bank-tx behaviour established for invoices is
symmetric on the AP side.

Run with:

    ./scripts/test.sh latest tests/research/test_post_pay_unpost_cycle_bill.py
"""

import os
import shutil
import time

from click.testing import CliRunner

from cli.main import cli

WORKTREE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
EXPORTS_DIR = os.path.join(WORKTREE, "exports", "bill")


ACCOUNTS = """\
2026-01-01 open Assets
\ttype: Asset
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Assets:Bank
\ttype: Bank
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Liabilities
\ttype: Liability
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Liabilities:Accounts Payable
\ttype: Accounts Payable
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Expenses
\ttype: Expense
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Expenses:Supplies
\ttype: Expense
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
"""


# Step A — bill exists but is not posted.
# Note: taxable=true everywhere because GnuCash never persists
# `taxable: false` on bills (CLAUDE.md finding #8). Keeping taxable=true with
# no tax-table reference means "taxable in principle but no actual tax".
BILL_UNPOSTED = """\
vendor "V001"
\tname: "Supplier"
\tcurrency: CAD

bill "BILL-001"
\tvendor_id: "V001"
\tcurrency: CAD
\tdate_opened: 2026-01-01
\tentry:
\t\tdate: 2026-01-01
\t\tdescription: "Supplies"
\t\taccount: "Expenses:Supplies"
\t\tquantity: 1
\t\tprice: 100
\t\ttaxable: true
\t\ttax_included: false
\tposted: none
\tpayment: none
"""


BILL_POSTED = """\
vendor "V001"
\tname: "Supplier"
\tcurrency: CAD

bill "BILL-001"
\tvendor_id: "V001"
\tcurrency: CAD
\tdate_opened: 2026-01-01
\tentry:
\t\tdate: 2026-01-01
\t\tdescription: "Supplies"
\t\taccount: "Expenses:Supplies"
\t\tquantity: 1
\t\tprice: 100
\t\ttaxable: true
\t\ttax_included: false
\tposted:
\t\tdate: 2026-01-01
\t\tdue: 2026-01-31
\t\tap_account: "Liabilities:Accounts Payable"
\t\tmemo: "Bill BILL-001"
\t\taccumulate: true
\tpayment: none
"""


BILL_POSTED_PAID = """\
vendor "V001"
\tname: "Supplier"
\tcurrency: CAD

bill "BILL-001"
\tvendor_id: "V001"
\tcurrency: CAD
\tdate_opened: 2026-01-01
\tentry:
\t\tdate: 2026-01-01
\t\tdescription: "Supplies"
\t\taccount: "Expenses:Supplies"
\t\tquantity: 1
\t\tprice: 100
\t\ttaxable: true
\t\ttax_included: false
\tposted:
\t\tdate: 2026-01-01
\t\tdue: 2026-01-31
\t\tap_account: "Liabilities:Accounts Payable"
\t\tmemo: "Bill BILL-001"
\t\taccumulate: true
\tpayment:
\t\tdate: 2026-01-15
\t\tamount: 100
\t\tbank_account: "Assets:Bank"
\t\tmemo: "Payment BILL-001 (first)"
"""


BILL_POSTED_REPAID = """\
vendor "V001"
\tname: "Supplier"
\tcurrency: CAD

bill "BILL-001"
\tvendor_id: "V001"
\tcurrency: CAD
\tdate_opened: 2026-01-01
\tentry:
\t\tdate: 2026-01-01
\t\tdescription: "Supplies"
\t\taccount: "Expenses:Supplies"
\t\tquantity: 1
\t\tprice: 100
\t\ttaxable: true
\t\ttax_included: false
\tposted:
\t\tdate: 2026-01-01
\t\tdue: 2026-01-31
\t\tap_account: "Liabilities:Accounts Payable"
\t\tmemo: "Bill BILL-001"
\t\taccumulate: true
\tpayment:
\t\tdate: 2026-02-15
\t\tamount: 100
\t\tbank_account: "Assets:Bank"
\t\tmemo: "Payment BILL-001 (second, after re-post)"
"""


def _write(path, text):
    path.write_text(text)
    return str(path)


def _read_entry_guids(gnc_path, bill_id):
    """Same trick as the invoice test — read the entry GUIDs directly from
    the book via ctypes. Bills and invoices share the gncInvoice type, so
    the query is identical."""
    import ctypes

    from gnucash import Query, Session
    from gnucash.gnucash_business import Invoice

    ses = Session(f"xml://{gnc_path}")
    try:
        book = ses.book
        q = Query()
        q.search_for('gncInvoice')
        q.set_book(book)
        guids = []
        for r in q.run():
            inv = Invoice(instance=r)
            if inv.GetID() == bill_id:
                lib = ctypes.CDLL(None)
                lib.qof_instance_get_guid.argtypes = [ctypes.c_void_p]
                lib.qof_instance_get_guid.restype = ctypes.c_void_p
                lib.guid_to_string_buff.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
                lib.guid_to_string_buff.restype = ctypes.c_char_p
                buf = ctypes.create_string_buffer(40)
                for entry in inv.GetEntries():
                    guid_ptr = lib.qof_instance_get_guid(int(entry.instance))
                    lib.guid_to_string_buff(guid_ptr, buf)
                    guids.append(buf.value.decode('ascii'))
                break
        q.destroy()
        return guids
    finally:
        ses.end()


def _snapshot(runner, gnc, tmp_path, label):
    out = tmp_path / f"{label}.txt"
    r = runner.invoke(cli, ["export", str(gnc), str(out),
                            "--include-business-objects"])
    assert r.exit_code == 0, f"export failed at {label}:\n{r.output}"
    dest = os.path.join(EXPORTS_DIR, f"{label}.txt")
    os.makedirs(EXPORTS_DIR, exist_ok=True)
    shutil.copy(str(out), dest)
    return out.read_text()


def test_bill_post_pay_unpost_cycle(tmp_path):
    runner = CliRunner()
    gnc = tmp_path / "book.gnucash"
    entry_guid_trace = {}

    # ── A: create unposted bill ──────────────────────────────────────────────
    fix_a = _write(tmp_path / "a.txt", ACCOUNTS + "\n" + BILL_UNPOSTED)
    r = runner.invoke(cli, ["import", "--new", str(gnc), fix_a,
                            "--include-business-objects"])
    assert r.exit_code == 0, r.output
    time.sleep(1)
    entry_guid_trace["A"] = _read_entry_guids(str(gnc), "BILL-001")
    text_a = _snapshot(runner, gnc, tmp_path, "step_A_created")
    assert 'bill "BILL-001"' in text_a
    assert "posted: none" in text_a

    # ── B: post the bill ─────────────────────────────────────────────────────
    fix_b = _write(tmp_path / "b.txt", ACCOUNTS + "\n" + BILL_POSTED)
    r = runner.invoke(cli, ["import", str(gnc), fix_b,
                            "--include-business-objects"])
    assert r.exit_code == 0, r.output
    time.sleep(1)
    entry_guid_trace["B"] = _read_entry_guids(str(gnc), "BILL-001")
    text_b = _snapshot(runner, gnc, tmp_path, "step_B_posted")
    assert "posted:" in text_b and "posted: none" not in text_b
    assert "Liabilities:Accounts Payable" in text_b
    assert "Expenses:Supplies" in text_b
    # Bill posting: DR Expense / CR AP.
    assert "Bill BILL-001" in text_b

    # ── C: pay the bill ──────────────────────────────────────────────────────
    fix_c = _write(tmp_path / "c.txt", ACCOUNTS + "\n" + BILL_POSTED_PAID)
    r = runner.invoke(cli, ["import", str(gnc), fix_c,
                            "--include-business-objects"])
    assert r.exit_code == 0, r.output
    time.sleep(1)
    entry_guid_trace["C"] = _read_entry_guids(str(gnc), "BILL-001")
    text_c = _snapshot(runner, gnc, tmp_path, "step_C_paid")
    assert "Assets:Bank" in text_c
    # Should have both posting (touching AP) and payment (touching Bank+AP).
    assert text_c.count("Liabilities:Accounts Payable") >= 2

    # ── D: unpost via the dedicated CLI ──────────────────────────────────────
    r = runner.invoke(cli, ["unpost-bills", str(gnc), "BILL-001"])
    assert r.exit_code == 0, r.output
    assert ": unposted" in r.output
    # Q-014: same warning path as for invoices, but with AP/sent wording
    # (mirroring the invoice side's AR/received).
    assert "1 bank-side payment transaction is now orphaned" in r.output, (
        "Q-014: unpost-bills on a paid bill must surface the orphan "
        f"bank-side payment transaction. Got:\n{r.output}")
    assert "AP posting transaction" in r.output
    assert "sent from" in r.output
    assert "CAD 100.00" in r.output
    time.sleep(1)
    entry_guid_trace["D"] = _read_entry_guids(str(gnc), "BILL-001")
    text_d = _snapshot(runner, gnc, tmp_path, "step_D_unposted")
    assert "posted: none" in text_d
    # The bank-side orphan should still be there; we'll assert on it below.
    assert "Assets:Bank" in text_d

    # ── E: re-post the unposted bill ─────────────────────────────────────────
    fix_e = _write(tmp_path / "e.txt", ACCOUNTS + "\n" + BILL_POSTED)
    r = runner.invoke(cli, ["import", str(gnc), fix_e,
                            "--include-business-objects"])
    assert r.exit_code == 0, r.output
    time.sleep(1)
    entry_guid_trace["E"] = _read_entry_guids(str(gnc), "BILL-001")
    text_e = _snapshot(runner, gnc, tmp_path, "step_E_reposted")
    assert "posted:" in text_e and "posted: none" not in text_e

    # ── F: re-pay with a second payment, different date ──────────────────────
    fix_f = _write(tmp_path / "f.txt", ACCOUNTS + "\n" + BILL_POSTED_REPAID)
    r = runner.invoke(cli, ["import", str(gnc), fix_f,
                            "--include-business-objects"])
    assert r.exit_code == 0, r.output
    time.sleep(1)
    entry_guid_trace["F"] = _read_entry_guids(str(gnc), "BILL-001")
    text_f = _snapshot(runner, gnc, tmp_path, "step_F_repaid")
    # Either the orphaned Jan 15 payment or the new Feb 15 one must show up.
    assert "2026-01-15" in text_f or "2026-02-15" in text_f

    import json
    with open(os.path.join(EXPORTS_DIR, "entry_guid_trace.json"), "w") as f:
        json.dump(entry_guid_trace, f, indent=2)
