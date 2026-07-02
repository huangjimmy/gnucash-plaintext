"""
Research harness for the invoice post → pay → unpost → re-post → re-pay cycle.

Walks one invoice through six lifecycle states (A–F) and snapshots the full
plaintext export after each, dropping the snapshots into the worktree's
`exports/` directory for direct human inspection.

The test is *not* a behavioural specification — it intentionally exercises a
scenario (re-pay after unpost) whose current behaviour may be surprising or
buggy. Assertions here lock in the observed end-state of each step so that
future changes to the importer or exporter produce a visible diff against
this run.

Run with:

    ./scripts/test.sh latest tests/research/test_post_pay_unpost_cycle.py
"""

import os
import shutil

from click.testing import CliRunner

from cli.main import cli

# Resolve the repo root from this test file's location so the path is correct
# both inside Docker (/workspace/tests/research/...) and on the host.
WORKTREE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
EXPORTS_DIR = os.path.join(WORKTREE, "exports")


ACCOUNTS = """\
2026-01-01 open Assets
\ttype: Asset
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Assets:Bank
\ttype: Bank
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Assets:Accounts Receivable
\ttype: Accounts Receivable
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Income
\ttype: Income
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Income:Sales
\ttype: Income
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
"""


# Step A: invoice exists but is not posted.
INV_UNPOSTED = """\
customer "C001"
\tname: "Acme"
\tcurrency: CAD

invoice "INV-001"
\tcustomer_id: "C001"
\tcurrency: CAD
\tdate_opened: 2026-01-01
\tentry:
\t\tdate: 2026-01-01
\t\tdescription: "Service"
\t\taction: "Hours"
\t\taccount: "Income:Sales"
\t\tquantity: 1
\t\tprice: 100
\t\ttaxable: false
\t\ttax_included: false
\tposted: none
\tpayment: none
"""


# Step B: same invoice, now with a posted block (no payment).
INV_POSTED = """\
customer "C001"
\tname: "Acme"
\tcurrency: CAD

invoice "INV-001"
\tcustomer_id: "C001"
\tcurrency: CAD
\tdate_opened: 2026-01-01
\tentry:
\t\tdate: 2026-01-01
\t\tdescription: "Service"
\t\taction: "Hours"
\t\taccount: "Income:Sales"
\t\tquantity: 1
\t\tprice: 100
\t\ttaxable: false
\t\ttax_included: false
\tposted:
\t\tdate: 2026-01-01
\t\tdue: 2026-01-31
\t\tar_account: "Assets:Accounts Receivable"
\t\tmemo: "Invoice INV-001"
\t\taccumulate: true
\tpayment: none
"""


# Step C: posted invoice plus first payment on 2026-01-15 from Bank.
INV_POSTED_PAID = """\
customer "C001"
\tname: "Acme"
\tcurrency: CAD

invoice "INV-001"
\tcustomer_id: "C001"
\tcurrency: CAD
\tdate_opened: 2026-01-01
\tentry:
\t\tdate: 2026-01-01
\t\tdescription: "Service"
\t\taction: "Hours"
\t\taccount: "Income:Sales"
\t\tquantity: 1
\t\tprice: 100
\t\ttaxable: false
\t\ttax_included: false
\tposted:
\t\tdate: 2026-01-01
\t\tdue: 2026-01-31
\t\tar_account: "Assets:Accounts Receivable"
\t\tmemo: "Invoice INV-001"
\t\taccumulate: true
\tpayment:
\t\tdate: 2026-01-15
\t\tamount: 100
\t\tbank_account: "Assets:Bank"
\t\tmemo: "Payment INV-001 (first)"
"""


# Step F: posted invoice plus a SECOND payment on a different date.
# We deliberately drop the 2026-01-15 payment block from the .txt to model
# "the user lost track of the old payment after unpost and is re-paying" —
# this is the worst-case for surfacing duplicates on the bank side.
INV_POSTED_REPAID = """\
customer "C001"
\tname: "Acme"
\tcurrency: CAD

invoice "INV-001"
\tcustomer_id: "C001"
\tcurrency: CAD
\tdate_opened: 2026-01-01
\tentry:
\t\tdate: 2026-01-01
\t\tdescription: "Service"
\t\taction: "Hours"
\t\taccount: "Income:Sales"
\t\tquantity: 1
\t\tprice: 100
\t\ttaxable: false
\t\ttax_included: false
\tposted:
\t\tdate: 2026-01-01
\t\tdue: 2026-01-31
\t\tar_account: "Assets:Accounts Receivable"
\t\tmemo: "Invoice INV-001"
\t\taccumulate: true
\tpayment:
\t\tdate: 2026-02-15
\t\tamount: 100
\t\tbank_account: "Assets:Bank"
\t\tmemo: "Payment INV-001 (second, after re-post)"
"""


def _write(path, text):
    path.write_text(text)
    return str(path)


def _read_entry_guids(gnc_path, inv_id):
    """Read the GUIDs of all entries on the named invoice.

    Used to answer the "do entry GUIDs survive the full cycle?" research
    question — the plaintext export doesn't emit entry GUIDs, so we crack
    the book open with ctypes and read them directly. Same approach as
    tests/integration/test_unpost_invoice_bill.py::_entry_guids_for_invoice.
    """
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
            if inv.GetID() == inv_id:
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
    """Export the full book (accounts + business objects + transactions)
    and copy the resulting file into the worktree's exports/ directory.

    Returns the snapshot text so the caller can assert on it.
    """
    out = tmp_path / f"{label}.txt"
    r = runner.invoke(cli, ["export", str(gnc), str(out),
                            "--include-business-objects"])
    assert r.exit_code == 0, f"export failed at {label}:\n{r.output}"
    dest = os.path.join(EXPORTS_DIR, f"{label}.txt")
    os.makedirs(EXPORTS_DIR, exist_ok=True)
    shutil.copy(str(out), dest)
    return out.read_text()


def test_invoice_post_pay_unpost_cycle(tmp_path):
    runner = CliRunner()
    gnc = tmp_path / "book.gnucash"
    entry_guid_trace = {}

    # ── Step A: create the unposted invoice ──────────────────────────────────
    fix_a = _write(tmp_path / "a.txt", ACCOUNTS + "\n" + INV_UNPOSTED)
    r = runner.invoke(cli, ["import", "--new", str(gnc), fix_a,
                            "--include-business-objects"])
    assert r.exit_code == 0, r.output

    entry_guid_trace["A"] = _read_entry_guids(str(gnc), "INV-001")
    text_a = _snapshot(runner, gnc, tmp_path, "step_A_created")
    assert 'invoice "INV-001"' in text_a
    assert "posted: none" in text_a
    assert "payment: none" in text_a

    # ── Step B: post the invoice ─────────────────────────────────────────────
    fix_b = _write(tmp_path / "b.txt", ACCOUNTS + "\n" + INV_POSTED)
    r = runner.invoke(cli, ["import", str(gnc), fix_b,
                            "--include-business-objects"])
    assert r.exit_code == 0, r.output

    entry_guid_trace["B"] = _read_entry_guids(str(gnc), "INV-001")
    text_b = _snapshot(runner, gnc, tmp_path, "step_B_posted")
    assert "posted:" in text_b and "posted: none" not in text_b
    # Posting creates the AR/Income transaction.
    assert "Assets:Accounts Receivable" in text_b
    assert "Income:Sales" in text_b
    assert "Invoice INV-001" in text_b  # memo line on the posted tx

    # ── Step C: apply the first payment ──────────────────────────────────────
    fix_c = _write(tmp_path / "c.txt", ACCOUNTS + "\n" + INV_POSTED_PAID)
    r = runner.invoke(cli, ["import", str(gnc), fix_c,
                            "--include-business-objects"])
    assert r.exit_code == 0, r.output

    entry_guid_trace["C"] = _read_entry_guids(str(gnc), "INV-001")
    text_c = _snapshot(runner, gnc, tmp_path, "step_C_paid")
    # The payment tx hits Bank with -100 and AR with +100 (or symmetric).
    assert "Assets:Bank" in text_c
    # Both the posting and payment transactions live in the book; quick sanity:
    assert text_c.count("Assets:Accounts Receivable") >= 2

    # ── Step D: unpost via the dedicated CLI command (Q-010) ─────────────────
    r = runner.invoke(cli, ["unpost-invoices", str(gnc), "INV-001"])
    assert r.exit_code == 0, r.output
    assert ": unposted" in r.output
    # Q-014: the paid invoice's payment tx is about to be orphaned, so the
    # CLI now warns the user with the orphan's date, bank account, amount,
    # and GUID. The warning is what tells the user that re-pay-after-unpost
    # would silently duplicate the bank deposit unless they delete the
    # orphan or use `txn_guid:` retarget.
    assert "1 bank-side payment transaction is now orphaned" in r.output, (
        "Q-014: unpost-invoices on a paid invoice must surface the orphan "
        f"bank-side payment transaction. Got:\n{r.output}")
    assert "Assets:Bank" in r.output
    assert "CAD 100.00" in r.output

    entry_guid_trace["D"] = _read_entry_guids(str(gnc), "INV-001")
    text_d = _snapshot(runner, gnc, tmp_path, "step_D_unposted")
    assert "posted: none" in text_d, (
        "Invoice must be in `posted: none` state after unpost-invoices.\n"
        f"Got:\n{text_d}"
    )
    # The bank-side split is documented as orphaned — bank must still appear.
    assert "Assets:Bank" in text_d

    # ── Step E: re-post the unposted invoice ─────────────────────────────────
    fix_e = _write(tmp_path / "e.txt", ACCOUNTS + "\n" + INV_POSTED)
    r = runner.invoke(cli, ["import", str(gnc), fix_e,
                            "--include-business-objects"])
    assert r.exit_code == 0, r.output

    entry_guid_trace["E"] = _read_entry_guids(str(gnc), "INV-001")
    text_e = _snapshot(runner, gnc, tmp_path, "step_E_reposted")
    assert "posted:" in text_e and "posted: none" not in text_e
    # The re-posted invoice should once again have an AR posting transaction.
    assert "Invoice INV-001" in text_e

    # ── Step F: re-pay (second payment, different date) ──────────────────────
    fix_f = _write(tmp_path / "f.txt", ACCOUNTS + "\n" + INV_POSTED_REPAID)
    r = runner.invoke(cli, ["import", str(gnc), fix_f,
                            "--include-business-objects"])
    assert r.exit_code == 0, r.output

    entry_guid_trace["F"] = _read_entry_guids(str(gnc), "INV-001")
    text_f = _snapshot(runner, gnc, tmp_path, "step_F_repaid")
    # The crucial question: does the orphan bank split from step C survive,
    # giving two bank-side -100 entries (Jan 15 and Feb 15)?
    assert "2026-01-15" in text_f or "2026-02-15" in text_f

    # Drop the entry-GUID trace into exports/ so the research doc can quote it.
    import json
    with open(os.path.join(EXPORTS_DIR, "entry_guid_trace.json"), "w") as f:
        json.dump(entry_guid_trace, f, indent=2)
