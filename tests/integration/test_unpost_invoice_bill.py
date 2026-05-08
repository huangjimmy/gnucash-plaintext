"""
Q-010: dedicated `unpost-invoices` / `unpost-bills` CLI commands.

Two paths can unpost a posted invoice/bill, and the tests below verify
that BOTH paths exist AND that they have observably different internal
behaviour:

  Path A — re-import with `posted: none`
    Triggered by editing the .txt: `posted: { ... }` → `posted: none`
    and re-importing. The importer detects "only the posted block
    changed" and short-circuits to a minimal `Unpost(False)` (no
    destroy-and-rebuild). Entry GUIDs preserved.

  Path B — `gnucash-plaintext unpost-invoices <book> <ID>`
    Standalone CLI command that doesn't read any plaintext file.
    Calls `Unpost(False)` directly. Entry GUIDs preserved.

Both end up with the same posted-state (invoice unposted, posting tx
destroyed, payment txns orphaned in bank). The differences:

  - Path A still rebuilds entries when the directive's entries differ
    from the existing record's. Path B never touches entries.
  - Path A requires a current .txt file. Path B doesn't.
  - Path A emits the per-directive status line via the import summary
    machinery. Path B prints `<id> (<guid>): unposted` per record.
"""

import os
import time

import pytest
from click.testing import CliRunner

from cli.main import cli


def _fixture(name: str) -> str:
    """Load a `tests/fixtures/<name>.txt` file as a string."""
    path = os.path.join(os.path.dirname(__file__), '..', 'fixtures', f'{name}.txt')
    with open(path) as f:
        return f.read()


ACCOUNTS = """
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
2026-01-01 open Liabilities
\ttype: Liability
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Liabilities:Accounts Payable
\ttype: Accounts Payable
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
2026-01-01 open Expenses
\ttype: Expense
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Expenses:Supplies
\ttype: Expense
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
"""


def _write(path, text):
    path.write_text(text)
    return str(path)


def _import_new(runner, gnc, fixture):
    return runner.invoke(cli, ["import", "--new", str(gnc), fixture,
                               "--include-business-objects"])


def _import(runner, gnc, fixture):
    return runner.invoke(cli, ["import", str(gnc), fixture,
                               "--include-business-objects"])


def _export_text(runner, gnc, tmp_path):
    out = tmp_path / "exported.txt"
    r = runner.invoke(cli, ["export", str(gnc), str(out),
                            "--include-business-objects"])
    assert r.exit_code == 0, r.output
    return out.read_text()


def _setup_book_with(runner, tmp_path, fixture_text):
    gnc = tmp_path / "book.gnucash"
    fix = _write(tmp_path / "in.txt", ACCOUNTS + "\n" + fixture_text)
    r = _import_new(runner, gnc, fix)
    assert r.exit_code == 0, r.output
    time.sleep(1)
    return gnc


def _entry_guids_for_invoice(runner, gnc, inv_id):
    """Reach into the book and read entry GUIDs for the named invoice.

    Used to assert the non-destructive-vs-rebuild distinction between
    the unpost CLI path and the re-import path.
    """
    from gnucash import Query, Session
    from gnucash.gnucash_business import Invoice
    ses = Session(f"xml://{gnc}")
    try:
        book = ses.book
        q = Query()
        q.search_for('gncInvoice')
        q.set_book(book)
        guids = []
        for r in q.run():
            inv = Invoice(instance=r)
            if inv.GetID() == inv_id:
                # Each entry's GUID via ctypes (SWIG GetGUID is unreliable
                # for Entry on some platforms).
                import ctypes
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


# ── Path A: re-import with `posted: none` ─────────────────────────────────────


class TestReimportPathUnpostsAndPreservesEntryGuids:
    """When the only difference between existing and directive is
    `posted: { ... }` → `posted: none`, the importer takes the minimal
    unpost path: Unpost(False) without destroy-and-rebuild. Entry GUIDs
    survive."""

    def test_invoice_minimal_unpost_preserves_entry_guids(self, tmp_path):
        runner = CliRunner()
        gnc = _setup_book_with(runner, tmp_path, _fixture('q010_invoice_posted'))
        before = _entry_guids_for_invoice(runner, gnc, "INV-001")
        assert len(before) == 1, f"Setup expected 1 entry, got {before}"

        r = _import(runner, gnc, _write(tmp_path / "unpost.txt",
                                        ACCOUNTS + "\n" + _fixture('q010_invoice_unposted')))
        assert r.exit_code == 0, r.output
        assert 'invoice "INV-001": updated' in r.output, r.output

        after = _entry_guids_for_invoice(runner, gnc, "INV-001")
        assert after == before, (
            "Minimal-unpost re-import (only `posted` differs) must preserve "
            f"entry GUIDs; before={before}, after={after}"
        )

    def test_bill_minimal_unpost_preserves_entry_guids(self, tmp_path):
        runner = CliRunner()
        gnc = _setup_book_with(runner, tmp_path, _fixture('q010_bill_posted'))
        before = _entry_guids_for_invoice(runner, gnc, "BILL-001")
        assert len(before) == 1

        r = _import(runner, gnc, _write(tmp_path / "unpost.txt",
                                        ACCOUNTS + "\n" + _fixture('q010_bill_unposted')))
        assert r.exit_code == 0, r.output
        assert 'bill "BILL-001": updated' in r.output, r.output

        after = _entry_guids_for_invoice(runner, gnc, "BILL-001")
        assert after == before, (
            "Bill minimal-unpost must preserve entry GUIDs; "
            f"before={before}, after={after}"
        )


class TestReimportFullRebuildChurnsEntryGuids:
    """For comparison: when the directive ALSO modifies an entry (not
    just the posted block), the importer goes through the full
    destroy-and-rebuild path. Entry GUIDs change. This is the
    behavioural difference vs the minimal-unpost path."""

    def test_invoice_rebuild_with_entry_change_changes_entry_guids(self, tmp_path):
        runner = CliRunner()
        gnc = _setup_book_with(runner, tmp_path, _fixture('q010_invoice_posted'))
        before = _entry_guids_for_invoice(runner, gnc, "INV-001")
        assert len(before) == 1

        edited = _fixture('q010_invoice_posted').replace('\t\tquantity: 1\n', '\t\tquantity: 2\n')
        r = _import(runner, gnc, _write(tmp_path / "edited.txt",
                                        ACCOUNTS + "\n" + edited))
        assert r.exit_code == 0, r.output
        assert 'invoice "INV-001": updated' in r.output, r.output

        after = _entry_guids_for_invoice(runner, gnc, "INV-001")
        assert after != before, (
            "Full-rebuild path (entries changed) is expected to give the "
            f"entry a new GUID; before={before}, after={after}. If this "
            "assertion fires, the destroy-and-rebuild path may have been "
            "removed — re-check the import_invoice flow."
        )


# ── Path B: `unpost-invoices` / `unpost-bills` CLI commands ──────────────────


class TestUnpostInvoiceCommand:
    def test_unposts_a_posted_invoice(self, tmp_path):
        runner = CliRunner()
        gnc = _setup_book_with(runner, tmp_path, _fixture('q010_invoice_posted'))

        r = runner.invoke(cli, ["unpost-invoices", str(gnc), "INV-001"])
        assert r.exit_code == 0, r.output
        assert ': unposted' in r.output, r.output

        text = _export_text(runner, gnc, tmp_path)
        assert 'posted: none' in text, (
            f"Invoice must be unposted after `unpost-invoices`:\n{text}"
        )

    def test_preserves_entry_guids(self, tmp_path):
        """The CLI unpost is non-destructive on entries — same end state
        as the minimal-unpost re-import path."""
        runner = CliRunner()
        gnc = _setup_book_with(runner, tmp_path, _fixture('q010_invoice_posted'))
        before = _entry_guids_for_invoice(runner, gnc, "INV-001")
        assert len(before) == 1

        r = runner.invoke(cli, ["unpost-invoices", str(gnc), "INV-001"])
        assert r.exit_code == 0, r.output

        after = _entry_guids_for_invoice(runner, gnc, "INV-001")
        assert after == before, (
            f"unpost-invoices CLI must preserve entry GUIDs; "
            f"before={before}, after={after}"
        )

    def test_already_unposted_reports_failed_with_detail_and_exits_1(self, tmp_path):
        """Same exit-1 pattern as archive-customers' 'already archived' —
        running unpost against a never-posted (or previously-unposted)
        record is a non-no-op failure. The message must explain *both*
        possible reasons so the user can tell whether they're hitting an
        idempotency replay or genuinely targeted the wrong record."""
        runner = CliRunner()
        gnc = _setup_book_with(runner, tmp_path, _fixture('q010_invoice_unposted'))

        r = runner.invoke(cli, ["unpost-invoices", str(gnc), "INV-001"])
        assert r.exit_code == 1, r.output
        assert 'no posting transaction' in r.output, r.output
        assert 'never posted' in r.output, r.output
        assert 'already unposted' in r.output, r.output

    def test_not_found_reports_and_exits_1(self, tmp_path):
        runner = CliRunner()
        gnc = _setup_book_with(runner, tmp_path, _fixture('q010_invoice_posted'))

        r = runner.invoke(cli, ["unpost-invoices", str(gnc), "DOES-NOT-EXIST"])
        assert r.exit_code == 1
        assert 'not found' in r.output

    def test_by_guid_unposts(self, tmp_path):
        runner = CliRunner()
        gnc = _setup_book_with(runner, tmp_path, _fixture('q010_invoice_posted'))
        # Read the guid from the exported text
        text = _export_text(runner, gnc, tmp_path)
        import re
        m = re.search(r'invoice "INV-001"\n(?:\t.*\n)*\tguid: "([0-9a-f]{32})"',
                      text)
        assert m is not None, f"Couldn't find guid in export:\n{text}"
        guid = m.group(1)

        r = runner.invoke(cli, ["unpost-invoices", str(gnc), "--by-guid", guid])
        assert r.exit_code == 0, r.output
        assert ': unposted' in r.output

    def test_multiple_ids_partial_failure_exits_1(self, tmp_path):
        """One success + one not-found: save the success but exit 1."""
        runner = CliRunner()
        gnc = _setup_book_with(runner, tmp_path, _fixture('q010_invoice_posted'))

        r = runner.invoke(cli, ["unpost-invoices", str(gnc),
                                "INV-001", "DOES-NOT-EXIST"])
        assert r.exit_code == 1, r.output
        assert ': unposted' in r.output
        assert 'not found' in r.output

        # The successful unpost was saved.
        text = _export_text(runner, gnc, tmp_path)
        assert 'posted: none' in text


class TestUnpostBillCommand:
    def test_unposts_a_posted_bill(self, tmp_path):
        runner = CliRunner()
        gnc = _setup_book_with(runner, tmp_path, _fixture('q010_bill_posted'))

        r = runner.invoke(cli, ["unpost-bills", str(gnc), "BILL-001"])
        assert r.exit_code == 0, r.output
        assert ': unposted' in r.output

        text = _export_text(runner, gnc, tmp_path)
        assert 'posted: none' in text, (
            f"Bill must be unposted after `unpost-bills`:\n{text}"
        )

    def test_preserves_entry_guids(self, tmp_path):
        runner = CliRunner()
        gnc = _setup_book_with(runner, tmp_path, _fixture('q010_bill_posted'))
        before = _entry_guids_for_invoice(runner, gnc, "BILL-001")
        assert len(before) == 1

        r = runner.invoke(cli, ["unpost-bills", str(gnc), "BILL-001"])
        assert r.exit_code == 0, r.output

        after = _entry_guids_for_invoice(runner, gnc, "BILL-001")
        assert after == before, (
            f"unpost-bills CLI must preserve entry GUIDs; "
            f"before={before}, after={after}"
        )
