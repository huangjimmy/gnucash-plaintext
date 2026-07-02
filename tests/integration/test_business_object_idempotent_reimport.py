"""
Q-006: Business-object IDs must be unique on re-import; GUIDs must round-trip.

Tests in this file describe the desired behaviour of the importer/exporter
once Q-006 is fixed. They are written first so we can confirm the gap before
changing any implementation:

  1. Re-import of a customer/vendor with the same id must NOT create a
     duplicate record. Existing record fields update in place.
  2. Each business-object block (customer, vendor, taxtable, invoice, bill)
     exports its own GUID under a universal `guid:` field.
  3. Invoice → customer and bill → vendor cross-references export both id
     and guid (`customer_id:` + `customer_guid:`, `vendor_id:` + `vendor_guid:`).
     If both are present on import, they must resolve to the same record;
     mismatches are errors.
  4. Re-import resolution honours `id` ⇔ `guid` agreement: any contradiction
     between the directive and the existing book record is an error.

These tests intentionally avoid depending on internal helpers; they drive
everything through the CLI to mirror the user-level scenario reported by
the external tester.
"""

import os
import re

import pytest
from click.testing import CliRunner

from cli.main import cli

# ── helpers ──────────────────────────────────────────────────────────────────


_GUID_RE = re.compile(r'^[0-9a-f]{32}$')


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


def _export(runner, gnc, out):
    return runner.invoke(cli, ["export", str(gnc), str(out),
                               "--include-business-objects"])


def _count_blocks(text, header_prefix):
    """Count business-object blocks whose header line starts with header_prefix.
    e.g. _count_blocks(text, 'customer "C001"') counts customer blocks for C001."""
    return sum(1 for line in text.splitlines() if line.startswith(header_prefix))


def _all_blocks_for(text, header):
    """Return a list of blocks (each a list of lines) whose header equals `header`."""
    blocks = []
    current = None
    for line in text.splitlines():
        if line == header:
            if current is not None:
                blocks.append(current)
            current = [line]
            continue
        if current is not None:
            if line == '' or line.startswith(' ') or line.startswith('\t'):
                current.append(line)
            else:
                blocks.append(current)
                current = None
    if current is not None:
        blocks.append(current)
    return blocks


def _block_for(text, header):
    """Return the unique block whose header equals `header`.

    Asserts that exactly one block exists. Returns 0 or >1 → AssertionError so
    a duplicate (the very bug Q-006 is about) cannot silently pass a test that
    only inspects fields.
    """
    blocks = _all_blocks_for(text, header)
    assert len(blocks) == 1, (
        f"Expected exactly 1 block matching {header!r}, got {len(blocks)}.\n"
        f"This usually means the importer created duplicates."
    )
    return blocks[0]


def _field_in_block(block_lines, key, *, strip_quotes=False):
    """Return the value of a `\\tkey: value` field, or None.

    If `strip_quotes` is True, surrounding double quotes are stripped from
    the value. Use this when reading e.g. guid: "abcd…" → "abcd…".
    """
    for line in block_lines:
        m = re.match(rf'^\t{re.escape(key)}:\s*(.*)$', line)
        if m:
            v = m.group(1).strip()
            if strip_quotes and len(v) >= 2 and v[0] == '"' and v[-1] == '"':
                v = v[1:-1]
            return v
    return None


def _setup_book_with(runner, tmp_path, fixture_text):
    """Create a fresh GnuCash file and import the given fixture text. Returns its path."""
    gnc = tmp_path / "book.gnucash"
    fix = _write(tmp_path / "in.txt", ACCOUNTS + "\n" + fixture_text)
    r = _import_new(runner, gnc, fix)
    assert r.exit_code == 0, f"Setup import failed:\n{r.output}"
    return gnc


def _exported_biz_text(runner, tmp_path, gnc):
    out = tmp_path / "exported.txt"
    r = _export(runner, gnc, out)
    assert r.exit_code == 0, f"Export failed:\n{r.output}"
    return out.read_text()


def _fixture(name: str) -> str:
    """Read a `tests/fixtures/<name>.txt` fixture as a single string.

    Big plaintext fixtures live in their own files rather than as inline
    Python strings: easier to read, easier to diff, easier to reuse across
    tests, and the indentation is preserved verbatim.
    """
    import os
    path = os.path.join(os.path.dirname(__file__), '..', 'fixtures', f'{name}.txt')
    with open(path) as f:
        return f.read()


# ── 1. Re-import idempotency ─────────────────────────────────────────────────


class TestReimportDoesNotDuplicate:
    def test_customer_same_id_does_not_duplicate(self, tmp_path):
        runner = CliRunner()
        gnc = _setup_book_with(runner, tmp_path,
                               'customer "C001"\n\tname: "Acme"\n\tcurrency: CAD\n')
        # Re-import the same fixture with no changes.
        again = _write(tmp_path / "again.txt",
                       'customer "C001"\n\tname: "Acme"\n\tcurrency: CAD\n')
        r = _import(runner, gnc, again)
        assert r.exit_code == 0, f"Re-import must succeed:\n{r.output}"
        text = _exported_biz_text(runner, tmp_path, gnc)
        assert _count_blocks(text, 'customer "C001"') == 1, (
            f"Expected exactly one customer 'C001' after re-import; got\n{text}"
        )

    def test_vendor_same_id_does_not_duplicate(self, tmp_path):
        runner = CliRunner()
        gnc = _setup_book_with(runner, tmp_path,
                               'vendor "V001"\n\tname: "Supplier"\n\tcurrency: CAD\n')
        again = _write(tmp_path / "again.txt",
                       'vendor "V001"\n\tname: "Supplier"\n\tcurrency: CAD\n')
        r = _import(runner, gnc, again)
        assert r.exit_code == 0, f"Re-import must succeed:\n{r.output}"
        text = _exported_biz_text(runner, tmp_path, gnc)
        assert _count_blocks(text, 'vendor "V001"') == 1, (
            f"Expected exactly one vendor 'V001' after re-import; got\n{text}"
        )

    def test_customer_three_imports_one_record(self, tmp_path):
        """Regression for the bug: N imports must NOT produce N records."""
        runner = CliRunner()
        gnc = _setup_book_with(runner, tmp_path,
                               'customer "C001"\n\tname: "Acme"\n\tcurrency: CAD\n')
        for _ in range(2):
            again = _write(tmp_path / "again.txt",
                           'customer "C001"\n\tname: "Acme"\n\tcurrency: CAD\n')
            r = _import(runner, gnc, again)
            assert r.exit_code == 0, f"Re-import must succeed:\n{r.output}"
        text = _exported_biz_text(runner, tmp_path, gnc)
        assert _count_blocks(text, 'customer "C001"') == 1


# ── 2. Re-import updates fields rather than skipping ─────────────────────────


class TestReimportUpdatesFields:
    def test_customer_name_updates(self, tmp_path):
        runner = CliRunner()
        gnc = _setup_book_with(runner, tmp_path,
                               'customer "C001"\n\tname: "Acme Original"\n\tcurrency: CAD\n')
        renamed = _write(tmp_path / "renamed.txt",
                         'customer "C001"\n\tname: "Acme Renamed"\n\tcurrency: CAD\n')
        r = _import(runner, gnc, renamed)
        assert r.exit_code == 0, f"Re-import must succeed:\n{r.output}"

        text = _exported_biz_text(runner, tmp_path, gnc)
        assert _count_blocks(text, 'customer "C001"') == 1
        block = _block_for(text, 'customer "C001"')
        assert _field_in_block(block, 'name') == '"Acme Renamed"', (
            "Expected updated name in re-imported customer; got block:\n" + "\n".join(block)
        )

    def test_customer_active_flag_updates_to_false(self, tmp_path):
        runner = CliRunner()
        gnc = _setup_book_with(runner, tmp_path,
                               'customer "C001"\n\tname: "Acme"\n\tcurrency: CAD\n')
        deact = _write(tmp_path / "deact.txt",
                       'customer "C001"\n\tname: "Acme"\n\tcurrency: CAD\n\tactive: false\n')
        r = _import(runner, gnc, deact)
        assert r.exit_code == 0, f"Re-import must succeed:\n{r.output}"
        text = _exported_biz_text(runner, tmp_path, gnc)
        assert _count_blocks(text, 'customer "C001"') == 1, (
            f"Re-import with active: false must update the existing record, not "
            f"create a duplicate. Got:\n{text}"
        )
        block = _block_for(text, 'customer "C001"')
        assert _field_in_block(block, 'active') == 'false', (
            "Expected active: false after re-import; got block:\n" + "\n".join(block)
        )


# ── 2b. No-change re-import is reported as 'unchanged' (Q-010) ──────────────
#
# An external reviewer flagged that 'updated' was liberal under Q-009: when
# the directive matches the existing record byte-for-byte, the importer
# was reporting 'updated' even though nothing actually changed. Q-010 adds
# a new status `unchanged` for this case, freeing `skipped` to mean only
# "the importer refused to apply the change because the record is immutable
# (e.g. posted invoice)". Four statuses total:
#
#   created   — fresh record
#   updated   — existing record had at least one mutable field changed
#   unchanged — existing record matches the directive; no work performed
#   skipped   — existing record is immutable for this directive
#
# Script writers can then assert on counts cleanly.
# ─────────────────────────────────────────────────────────────────────────────


class TestNoChangeReimportIsUnchanged:
    """Re-import where directive matches existing record must report 'unchanged'.

    'unchanged' (this class) is distinct from 'skipped' (the
    `TestImmutablePostedSkipReportsSkipped` class below):
      - 'unchanged': record is mutable, directive matches existing state,
        nothing to do.
      - 'skipped':   record is immutable for this directive (e.g. posted
        invoice/bill), so the importer refuses to apply any change.
    """

    def test_customer_no_change_is_unchanged(self, tmp_path):
        runner = CliRunner()
        gnc = _setup_book_with(runner, tmp_path,
                               'customer "C001"\n\tname: "Acme"\n\tcurrency: CAD\n')
        same = _write(tmp_path / "again.txt",
                      ACCOUNTS + "\n" +
                      'customer "C001"\n\tname: "Acme"\n\tcurrency: CAD\n')
        r = _import(runner, gnc, same)
        assert r.exit_code == 0, f"Re-import must succeed:\n{r.output}"
        assert 'customer "C001": unchanged' in r.output, (
            f"No-change re-import must report 'unchanged', not 'updated' or "
            f"'skipped'. Got:\n{r.output}"
        )

    def test_customer_name_change_is_updated(self, tmp_path):
        runner = CliRunner()
        gnc = _setup_book_with(runner, tmp_path,
                               'customer "C001"\n\tname: "Acme"\n\tcurrency: CAD\n')
        renamed = _write(tmp_path / "renamed.txt",
                         ACCOUNTS + "\n" +
                         'customer "C001"\n\tname: "Acme Renamed"\n\tcurrency: CAD\n')
        r = _import(runner, gnc, renamed)
        assert r.exit_code == 0
        assert 'customer "C001": updated' in r.output, (
            f"Real change must report 'updated'. Got:\n{r.output}"
        )

    def test_customer_kvp_added_is_updated(self, tmp_path):
        runner = CliRunner()
        gnc = _setup_book_with(runner, tmp_path,
                               'customer "C001"\n\tname: "Acme"\n\tcurrency: CAD\n')
        with_kvp = _write(tmp_path / "with_kvp.txt",
                          ACCOUNTS + "\n" +
                          'customer "C001"\n\tname: "Acme"\n\tcurrency: CAD\n'
                          '\tjw.country: "CA"\n')
        r = _import(runner, gnc, with_kvp)
        assert r.exit_code == 0
        assert 'customer "C001": updated' in r.output

    def test_customer_active_change_is_updated(self, tmp_path):
        runner = CliRunner()
        gnc = _setup_book_with(runner, tmp_path,
                               'customer "C001"\n\tname: "Acme"\n\tcurrency: CAD\n')
        archived = _write(tmp_path / "archived.txt",
                          ACCOUNTS + "\n" +
                          'customer "C001"\n\tname: "Acme"\n\tcurrency: CAD\n'
                          '\tactive: false\n')
        r = _import(runner, gnc, archived)
        assert r.exit_code == 0
        assert 'customer "C001": updated' in r.output

    def test_vendor_no_change_is_unchanged(self, tmp_path):
        runner = CliRunner()
        gnc = _setup_book_with(runner, tmp_path,
                               'vendor "V001"\n\tname: "Supplier"\n\tcurrency: CAD\n')
        same = _write(tmp_path / "again.txt",
                      ACCOUNTS + "\n" +
                      'vendor "V001"\n\tname: "Supplier"\n\tcurrency: CAD\n')
        r = _import(runner, gnc, same)
        assert r.exit_code == 0
        assert 'vendor "V001": unchanged' in r.output

    def test_vendor_name_change_is_updated(self, tmp_path):
        runner = CliRunner()
        gnc = _setup_book_with(runner, tmp_path,
                               'vendor "V001"\n\tname: "Supplier"\n\tcurrency: CAD\n')
        renamed = _write(tmp_path / "renamed.txt",
                         ACCOUNTS + "\n" +
                         'vendor "V001"\n\tname: "Renamed Supplier"\n\tcurrency: CAD\n')
        r = _import(runner, gnc, renamed)
        assert r.exit_code == 0
        assert 'vendor "V001": updated' in r.output

    def test_unposted_invoice_no_change_is_unchanged(self, tmp_path):
        """Re-importing an unposted invoice fixture with no edits must NOT
        do destroy+rebuild — the directive matches existing state, so
        the importer should short-circuit and report 'unchanged'."""
        runner = CliRunner()
        invoice_fixture = _fixture('q010_invoice_unposted')
        gnc = _setup_book_with(runner, tmp_path, invoice_fixture)
        r = _import(runner, gnc, _write(tmp_path / "again.txt",
                                        ACCOUNTS + "\n" + invoice_fixture))
        assert r.exit_code == 0, r.output
        assert 'invoice "INV-001": unchanged' in r.output, (
            f"No-change re-import of unposted invoice must report 'unchanged':\n"
            f"{r.output}"
        )

    def test_unposted_invoice_entry_change_is_updated(self, tmp_path):
        """Changing an entry on an unposted invoice via re-import must
        still go through the update path and report 'updated'."""
        runner = CliRunner()
        base = _fixture('q010_invoice_unposted')
        gnc = _setup_book_with(runner, tmp_path, base)
        edited = base.replace('\t\tquantity: 1\n', '\t\tquantity: 2\n')
        r = _import(runner, gnc, _write(tmp_path / "edited.txt",
                                        ACCOUNTS + "\n" + edited))
        assert r.exit_code == 0, r.output
        assert 'invoice "INV-001": updated' in r.output, (
            f"Entry change must report 'updated':\n{r.output}"
        )

    def test_unposted_bill_no_change_is_unchanged(self, tmp_path):
        runner = CliRunner()
        bill_fixture = _fixture('q010_bill_unposted')
        gnc = _setup_book_with(runner, tmp_path, bill_fixture)
        r = _import(runner, gnc, _write(tmp_path / "again.txt",
                                        ACCOUNTS + "\n" + bill_fixture))
        assert r.exit_code == 0, r.output
        assert 'bill "BILL-001": unchanged' in r.output


# ── 2c. Immutable records report 'skipped' (Q-010 status semantics) ─────────
#
# Distinct from 'unchanged' (mutable, no diff): 'skipped' means the importer
# *refused* to apply the directive because the record's state forbids
# mutation. Currently:
#
#   - Posted invoice / bill: AR/AP lots are wired into a real transaction;
#     entries, posted block, and metadata are all locked.
#   - Tax table on hit: tax tables are referenced by stored pointers from
#     posted invoices/bills; mutating their entries would change accounting
#     on past records.
#
# (`TestUnpostedToPostedTransition` further down also has assertions that
# overlap with this class — kept for backward compatibility with Q-007's
# original suite; the dedicated class here is the canonical test for the
# 'skipped' status semantics introduced by Q-010.)
# ─────────────────────────────────────────────────────────────────────────────


class TestTaxTableImmutableReportsSkipped:
    """Tax tables are the only business-object kind that remains truly
    immutable on hit: mutating their entries would silently change
    accounting on past posted invoices that reference them. Status on
    re-import: 'skipped', not 'unchanged'.

    Posted invoices and bills are NOT in this category any more — Q-010
    extended the importer to support unpost-edit-repost just like the
    GnuCash UI does. See `TestPostedToPostedReimport` below.
    """

    def test_taxtable_reimport_is_skipped(self, tmp_path):
        runner = CliRunner()
        fixture = _fixture('q010_taxtable')
        gnc = _setup_book_with(runner, tmp_path, fixture)
        r = _import(runner, gnc, _write(tmp_path / "again.txt",
                                        ACCOUNTS + "\n" + fixture))
        assert r.exit_code == 0
        assert 'taxtable "GST": skipped' in r.output


class TestPostedToPostedReimport:
    """Q-010 expanded scope: GnuCash itself supports unpost → edit → repost.
    Pre-Q-010 our importer treated every posted invoice/bill as a permanent
    dead-end for re-imports. This class covers the four scenarios that
    Q-010 must handle when the existing record is posted:

      1. directive matches existing      → 'unchanged' (no-op)
      2. directive entry differs         → unpost, rebuild, repost → 'updated'
      3. directive posted block differs  → unpost, rebuild, repost → 'updated'
      4. directive sets posted: none     → unpost, leave unposted   → 'updated'
    """

    def test_posted_invoice_no_change_is_unchanged(self, tmp_path):
        runner = CliRunner()
        fixture = _fixture('q010_invoice_posted')
        gnc = _setup_book_with(runner, tmp_path, fixture)
        r = _import(runner, gnc, _write(tmp_path / "again.txt",
                                        ACCOUNTS + "\n" + fixture))
        assert r.exit_code == 0, r.output
        assert 'invoice "INV-001": unchanged' in r.output, (
            f"Identical re-import of posted invoice must report 'unchanged' "
            f"(no diff applied). Got:\n{r.output}"
        )
        # Sanity: the invoice is still posted with the same single entry.
        text = _exported_biz_text(runner, tmp_path, gnc)
        assert _count_blocks(text, 'invoice "INV-001"') == 1

    def test_posted_invoice_entry_change_unposts_and_reposts(self, tmp_path):
        """Editing an entry on a posted invoice must trigger Unpost → rebuild
        → PostToAccount, and report 'updated'. The new posted state must
        match the directive (quantity 2, not 1)."""
        runner = CliRunner()
        fixture = _fixture('q010_invoice_posted')
        gnc = _setup_book_with(runner, tmp_path, fixture)
        edited = fixture.replace('\t\tquantity: 1\n', '\t\tquantity: 2\n')
        r = _import(runner, gnc, _write(tmp_path / "edited.txt",
                                        ACCOUNTS + "\n" + edited))
        assert r.exit_code == 0, r.output
        assert 'invoice "INV-001": updated' in r.output, (
            f"Posted-invoice entry edit must report 'updated' (unpost-repost "
            f"cycle). Got:\n{r.output}"
        )
        text = _exported_biz_text(runner, tmp_path, gnc)
        block = _block_for(text, 'invoice "INV-001"')
        # Verify the rebuilt entry has quantity 2 (not 1) and is still posted.
        assert any('quantity: 2' in line for line in block), (
            "Rebuilt entry must show quantity: 2:\n" + "\n".join(block)
        )
        assert any('posted:' in line and 'none' not in line for line in block), (
            "Invoice must remain posted after edit:\n" + "\n".join(block)
        )

    def test_posted_invoice_memo_change_reposts(self, tmp_path):
        """Editing the posted-block memo must trigger Unpost → repost with
        the new memo. The posting transaction's description (set from
        memo) is the externally-observable signal."""
        runner = CliRunner()
        fixture = _fixture('q010_invoice_posted')
        gnc = _setup_book_with(runner, tmp_path, fixture)
        edited = fixture.replace(
            'memo: "Invoice INV-001"',
            'memo: "Invoice INV-001 (corrected)"',
        )
        r = _import(runner, gnc, _write(tmp_path / "memo_edit.txt",
                                        ACCOUNTS + "\n" + edited))
        assert r.exit_code == 0, r.output
        assert 'invoice "INV-001": updated' in r.output, r.output
        text = _exported_biz_text(runner, tmp_path, gnc)
        block = _block_for(text, 'invoice "INV-001"')
        assert any('Invoice INV-001 (corrected)' in line for line in block), (
            "Posted memo must be rewritten on re-import:\n" + "\n".join(block)
        )

    def test_posted_invoice_to_posted_none_unposts(self, tmp_path):
        """Going from posted → posted: none on re-import is a real change:
        Unpost the invoice (drop the AR posting transaction) and leave
        the invoice unposted. Status: 'updated'."""
        runner = CliRunner()
        fixture = _fixture('q010_invoice_posted')
        gnc = _setup_book_with(runner, tmp_path, fixture)
        edited = _fixture('q010_invoice_unposted')
        r = _import(runner, gnc, _write(tmp_path / "to_unposted.txt",
                                        ACCOUNTS + "\n" + edited))
        assert r.exit_code == 0, r.output
        assert 'invoice "INV-001": updated' in r.output, (
            f"posted → posted:none must report 'updated' (unpost happened):\n"
            f"{r.output}"
        )
        text = _exported_biz_text(runner, tmp_path, gnc)
        block = _block_for(text, 'invoice "INV-001"')
        assert any('posted: none' in line for line in block), (
            "Invoice must be unposted after re-import:\n" + "\n".join(block)
        )

    def test_posted_bill_no_change_is_unchanged(self, tmp_path):
        runner = CliRunner()
        fixture = _fixture('q010_bill_posted')
        gnc = _setup_book_with(runner, tmp_path, fixture)
        r = _import(runner, gnc, _write(tmp_path / "again.txt",
                                        ACCOUNTS + "\n" + fixture))
        assert r.exit_code == 0, r.output
        assert 'bill "BILL-001": unchanged' in r.output, (
            f"Identical re-import of posted bill must report 'unchanged':\n"
            f"{r.output}"
        )

    def test_posted_bill_entry_change_unposts_and_reposts(self, tmp_path):
        runner = CliRunner()
        fixture = _fixture('q010_bill_posted')
        gnc = _setup_book_with(runner, tmp_path, fixture)
        edited = fixture.replace('\t\tquantity: 1\n', '\t\tquantity: 3\n')
        r = _import(runner, gnc, _write(tmp_path / "edited.txt",
                                        ACCOUNTS + "\n" + edited))
        assert r.exit_code == 0, r.output
        assert 'bill "BILL-001": updated' in r.output, r.output
        text = _exported_biz_text(runner, tmp_path, gnc)
        block = _block_for(text, 'bill "BILL-001"')
        assert any('quantity: 3' in line for line in block), (
            "Rebuilt bill entry must show quantity: 3:\n" + "\n".join(block)
        )

    def test_posted_bill_to_posted_none_unposts(self, tmp_path):
        runner = CliRunner()
        fixture = _fixture('q010_bill_posted')
        gnc = _setup_book_with(runner, tmp_path, fixture)
        edited = _fixture('q010_bill_unposted')
        r = _import(runner, gnc, _write(tmp_path / "to_unposted.txt",
                                        ACCOUNTS + "\n" + edited))
        assert r.exit_code == 0, r.output
        assert 'bill "BILL-001": updated' in r.output, r.output
        text = _exported_biz_text(runner, tmp_path, gnc)
        block = _block_for(text, 'bill "BILL-001"')
        assert any('posted: none' in line for line in block), (
            "Bill must be unposted after re-import:\n" + "\n".join(block)
        )


# ── 3. Universal `guid:` field on each object's own block ────────────────────


class TestExportEmitsObjectGuid:
    @pytest.mark.parametrize("kind,header,fixture_text", [
        ("customer", 'customer "C001"',
         'customer "C001"\n\tname: "Acme"\n\tcurrency: CAD\n'),
        ("vendor", 'vendor "V001"',
         'vendor "V001"\n\tname: "Supplier"\n\tcurrency: CAD\n'),
        ("taxtable", 'taxtable "GST"',
         'taxtable "GST"\n\tentry:\n\t\taccount: "Liabilities:Accounts Payable"\n\t\trate: 5.0%\n\t\ttype: PERCENT\n'),
    ])
    def test_object_block_has_guid_field(self, tmp_path, kind, header, fixture_text):
        runner = CliRunner()
        gnc = _setup_book_with(runner, tmp_path, fixture_text)
        text = _exported_biz_text(runner, tmp_path, gnc)
        block = _block_for(text, header)
        guid = _field_in_block(block, 'guid', strip_quotes=True)
        assert guid is not None, f"{kind} block must export guid:\n" + "\n".join(block)
        assert _GUID_RE.match(guid), f"{kind} guid must be 32-char hex; got {guid!r}"


# ── 4. Cross-reference guid pairs ────────────────────────────────────────────


_INVOICE = """
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
"""


_BILL = """
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
\t\tprice: 50
\t\ttaxable: false
"""


class TestCrossReferenceGuid:
    def test_invoice_exports_customer_guid_matching_customer_block_guid(self, tmp_path):
        runner = CliRunner()
        gnc = _setup_book_with(runner, tmp_path, _INVOICE)
        text = _exported_biz_text(runner, tmp_path, gnc)

        cust_block = _block_for(text, 'customer "C001"')
        cust_guid = _field_in_block(cust_block, 'guid', strip_quotes=True)
        assert cust_guid is not None and _GUID_RE.match(cust_guid)

        inv_block = _block_for(text, 'invoice "INV-001"')
        ref_guid = _field_in_block(inv_block, 'customer_guid', strip_quotes=True)
        assert ref_guid == cust_guid, (
            f"Invoice's customer_guid must equal the customer's guid.\n"
            f"customer guid: {cust_guid}\ninvoice ref:  {ref_guid}\n"
            f"invoice block:\n" + "\n".join(inv_block)
        )

    def test_bill_exports_vendor_guid_matching_vendor_block_guid(self, tmp_path):
        runner = CliRunner()
        gnc = _setup_book_with(runner, tmp_path, _BILL)
        text = _exported_biz_text(runner, tmp_path, gnc)

        vend_block = _block_for(text, 'vendor "V001"')
        vend_guid = _field_in_block(vend_block, 'guid', strip_quotes=True)
        assert vend_guid is not None and _GUID_RE.match(vend_guid)

        bill_block = _block_for(text, 'bill "BILL-001"')
        ref_guid = _field_in_block(bill_block, 'vendor_guid', strip_quotes=True)
        assert ref_guid == vend_guid, (
            f"Bill's vendor_guid must equal the vendor's guid.\n"
            f"vendor guid: {vend_guid}\nbill ref:    {ref_guid}\n"
            f"bill block:\n" + "\n".join(bill_block)
        )


# ── 5. Conflict detection on the cross-reference ─────────────────────────────


class TestCrossReferenceMismatchErrors:
    def test_invoice_with_mismatched_customer_id_and_guid_errors(self, tmp_path):
        """Invoice that names customer_id="C001" + customer_guid pointing at C002 → error."""
        runner = CliRunner()
        # Create a book with TWO customers so we have two valid GUIDs.
        gnc = _setup_book_with(runner, tmp_path,
            'customer "C001"\n\tname: "Acme"\n\tcurrency: CAD\n'
            '\ncustomer "C002"\n\tname: "Other"\n\tcurrency: CAD\n')
        text = _exported_biz_text(runner, tmp_path, gnc)
        c1_block = _block_for(text, 'customer "C001"')
        c2_block = _block_for(text, 'customer "C002"')
        c1_guid = _field_in_block(c1_block, 'guid', strip_quotes=True)
        c2_guid = _field_in_block(c2_block, 'guid', strip_quotes=True)
        assert c1_guid and c2_guid

        # New invoice file with customer_id=C001 but customer_guid=C002's guid → contradiction
        bad = (
            f'invoice "INV-001"\n'
            f'\tcustomer_id: "C001"\n'
            f'\tcustomer_guid: "{c2_guid}"\n'
            f'\tcurrency: CAD\n'
            f'\tdate_opened: 2026-01-01\n'
            f'\tentry:\n'
            f'\t\tdate: 2026-01-01\n'
            f'\t\tdescription: "Service"\n'
            f'\t\taction: "Hours"\n'
            f'\t\taccount: "Income:Sales"\n'
            f'\t\tquantity: 1\n'
            f'\t\tprice: 100\n'
            f'\t\ttaxable: false\n'
            f'\t\ttax_included: false\n'
        )
        r = _import(runner, gnc, _write(tmp_path / "bad.txt", bad))
        assert r.exit_code != 0, "Mismatched customer_id/customer_guid must error"
        out = r.output.lower()
        assert "customer_id" in out or "customer_guid" in out or "mismatch" in out, (
            f"Error must explain the conflict; got:\n{r.output}"
        )


# ── 6. Conflict detection on the object block itself ─────────────────────────


class TestObjectBlockGuidIdConflictErrors:
    def test_reimport_with_guid_match_but_id_mismatch_errors(self, tmp_path):
        """guid: <X> already exists with id="C001"; directive says id="C999" → error.

        We refuse to silently rename a customer because the old id may be
        referenced by invoices, and renaming would break those references.
        """
        runner = CliRunner()
        gnc = _setup_book_with(runner, tmp_path,
                               'customer "C001"\n\tname: "Acme"\n\tcurrency: CAD\n')
        text = _exported_biz_text(runner, tmp_path, gnc)
        guid = _field_in_block(_block_for(text, 'customer "C001"'), 'guid', strip_quotes=True)
        assert guid

        bad = (
            f'customer "C999"\n'
            f'\tguid: "{guid}"\n'
            f'\tname: "Renamed"\n'
            f'\tcurrency: CAD\n'
        )
        r = _import(runner, gnc, _write(tmp_path / "bad.txt", bad))
        assert r.exit_code != 0, (
            f"GUID-already-exists with mismatched id must error; got success:\n{r.output}"
        )


# ── 7. Pre-existing duplicates surface at next import ────────────────────────


class TestCrossReferenceFailureModes:
    """Negative cases for invoice→customer / bill→vendor cross-references.

    Each row of the §4 resolution table that should error gets a test."""

    def test_invoice_with_unknown_customer_id_only_errors(self, tmp_path):
        runner = CliRunner()
        gnc = _setup_book_with(runner, tmp_path,
            'customer "C001"\n\tname: "Acme"\n\tcurrency: CAD\n')
        bad = (
            'invoice "INV-001"\n'
            '\tcustomer_id: "GHOST"\n'
            '\tcurrency: CAD\n'
            '\tdate_opened: 2026-01-01\n'
            '\tentry:\n'
            '\t\tdate: 2026-01-01\n'
            '\t\tdescription: "Service"\n'
            '\t\taction: "Hours"\n'
            '\t\taccount: "Income:Sales"\n'
            '\t\tquantity: 1\n'
            '\t\tprice: 100\n'
            '\t\ttaxable: false\n'
            '\t\ttax_included: false\n'
        )
        r = _import(runner, gnc, _write(tmp_path / "bad.txt", bad))
        assert r.exit_code != 0, "Unknown customer_id must error"
        assert "ghost" in r.output.lower() or "not found" in r.output.lower()

    def test_invoice_with_unknown_customer_guid_only_errors(self, tmp_path):
        runner = CliRunner()
        gnc = _setup_book_with(runner, tmp_path,
            'customer "C001"\n\tname: "Acme"\n\tcurrency: CAD\n')
        bad = (
            'invoice "INV-001"\n'
            '\tcustomer_guid: "deadbeefdeadbeefdeadbeefdeadbeef"\n'
            '\tcurrency: CAD\n'
            '\tdate_opened: 2026-01-01\n'
            '\tentry:\n'
            '\t\tdate: 2026-01-01\n'
            '\t\tdescription: "Service"\n'
            '\t\taction: "Hours"\n'
            '\t\taccount: "Income:Sales"\n'
            '\t\tquantity: 1\n'
            '\t\tprice: 100\n'
            '\t\ttaxable: false\n'
            '\t\ttax_included: false\n'
        )
        r = _import(runner, gnc, _write(tmp_path / "bad.txt", bad))
        assert r.exit_code != 0, "Unknown customer_guid must error"

    def test_invoice_with_no_customer_reference_errors(self, tmp_path):
        runner = CliRunner()
        gnc = _setup_book_with(runner, tmp_path, "")
        bad = (
            'invoice "INV-001"\n'
            '\tcurrency: CAD\n'
            '\tdate_opened: 2026-01-01\n'
            '\tentry:\n'
            '\t\tdate: 2026-01-01\n'
            '\t\tdescription: "Service"\n'
            '\t\taction: "Hours"\n'
            '\t\taccount: "Income:Sales"\n'
            '\t\tquantity: 1\n'
            '\t\tprice: 100\n'
            '\t\ttaxable: false\n'
            '\t\ttax_included: false\n'
        )
        r = _import(runner, gnc, _write(tmp_path / "bad.txt", bad))
        assert r.exit_code != 0, (
            f"Invoice missing both customer_id and customer_guid must error.\n"
            f"Got:\n{r.output}"
        )

    def test_invoice_with_only_customer_guid_imports_ok(self, tmp_path):
        """Hand-written invoice using customer_guid (no customer_id) is allowed.

        Note: this only applies to the invoice→customer cross-reference field.
        A `customer "..."` block itself always carries the customer number in
        its directive header — there is no such thing as a guid-only customer
        record.
        """
        runner = CliRunner()
        gnc = _setup_book_with(runner, tmp_path,
            'customer "C001"\n\tname: "Acme"\n\tcurrency: CAD\n')
        text = _exported_biz_text(runner, tmp_path, gnc)
        c_guid = _field_in_block(_block_for(text, 'customer "C001"'), 'guid', strip_quotes=True)
        assert c_guid

        guid_only = (
            f'invoice "INV-001"\n'
            f'\tcustomer_guid: "{c_guid}"\n'
            f'\tcurrency: CAD\n'
            f'\tdate_opened: 2026-01-01\n'
            f'\tentry:\n'
            f'\t\tdate: 2026-01-01\n'
            f'\t\tdescription: "Service"\n'
            f'\t\taction: "Hours"\n'
            f'\t\taccount: "Income:Sales"\n'
            f'\t\tquantity: 1\n'
            f'\t\tprice: 100\n'
            f'\t\ttaxable: false\n'
            f'\t\ttax_included: false\n'
        )
        r = _import(runner, gnc, _write(tmp_path / "ok.txt", guid_only))
        assert r.exit_code == 0, f"customer_guid-only must succeed:\n{r.output}"


class TestObjectBlockGuidValidation:
    """Negative cases for the object's own `guid:` field."""

    def test_unknown_guid_with_existing_id_errors(self, tmp_path):
        """Directive guid is unknown; id is taken → refuse to rebuild."""
        runner = CliRunner()
        gnc = _setup_book_with(runner, tmp_path,
            'customer "C001"\n\tname: "Acme"\n\tcurrency: CAD\n')
        bad = (
            'customer "C001"\n'
            '\tguid: "deadbeefdeadbeefdeadbeefdeadbeef"\n'
            '\tname: "Other"\n'
            '\tcurrency: CAD\n'
        )
        r = _import(runner, gnc, _write(tmp_path / "bad.txt", bad))
        assert r.exit_code != 0, (
            f"Unknown guid + existing id must error.\nGot:\n{r.output}"
        )

    def test_unquoted_mixed_hex_guid_works(self, tmp_path):
        """Unquoted mixed-hex guids (e.g. b2b3...b4) must still parse as strings.

        This is the friction-free hand-written form — users shouldn't be
        forced to add quotes when the value is unambiguously hex.
        """
        runner = CliRunner()
        gnc = _setup_book_with(runner, tmp_path, "")
        ok = (
            'customer "C001"\n'
            '\tguid: b2b3b2b3b2b3b2b3b2b3b2b3b2b3b2b4\n'
            '\tname: "Acme"\n'
            '\tcurrency: CAD\n'
        )
        r = _import(runner, gnc, _write(tmp_path / "ok.txt", ok))
        assert r.exit_code == 0, (
            f"Unquoted mixed-hex guid must be accepted:\n{r.output}"
        )
        text = _exported_biz_text(runner, tmp_path, gnc)
        guid = _field_in_block(_block_for(text, 'customer "C001"'), 'guid', strip_quotes=True)
        assert guid == "b2b3b2b3b2b3b2b3b2b3b2b3b2b3b2b4"

    def test_unquoted_all_digit_guid_errors_with_clear_message(self, tmp_path):
        """Unquoted all-digit guids are lossy (parser converts to int) — must
        be rejected with a message asking the user to quote."""
        runner = CliRunner()
        gnc = _setup_book_with(runner, tmp_path, "")
        bad = (
            'customer "C001"\n'
            '\tguid: 22222222222222222222222222222222\n'
            '\tname: "Acme"\n'
            '\tcurrency: CAD\n'
        )
        r = _import(runner, gnc, _write(tmp_path / "bad.txt", bad))
        assert r.exit_code != 0, "Unquoted all-digit guid must error"
        out = r.output.lower()
        assert "quote" in out or "string" in out, (
            f"Error must hint at quoting; got:\n{r.output}"
        )

    def test_malformed_guid_errors(self, tmp_path):
        """guid: 'hello' must surface as an invalid-format error."""
        runner = CliRunner()
        gnc = _setup_book_with(runner, tmp_path, "")
        bad = (
            'customer "C001"\n'
            '\tguid: "hello"\n'
            '\tname: "Acme"\n'
            '\tcurrency: CAD\n'
        )
        r = _import(runner, gnc, _write(tmp_path / "bad.txt", bad))
        assert r.exit_code != 0, "Malformed guid must error"
        assert "invalid" in r.output.lower() or "guid" in r.output.lower()


class TestRoundtripPreservesGuid:
    """Round-trip: customer with explicit guid → import → export → same guid."""

    def test_customer_guid_preserved_through_fresh_book(self, tmp_path):
        runner = CliRunner()
        original_guid = "abc123def456abc123def456abc12345"
        fix = (
            f'customer "C001"\n'
            f'\tguid: "{original_guid}"\n'
            f'\tname: "Acme"\n'
            f'\tcurrency: CAD\n'
        )
        gnc = _setup_book_with(runner, tmp_path, fix)
        text = _exported_biz_text(runner, tmp_path, gnc)
        guid = _field_in_block(_block_for(text, 'customer "C001"'), 'guid', strip_quotes=True)
        assert guid == original_guid, (
            f"Customer's explicit guid must round-trip; got {guid!r}, "
            f"expected {original_guid!r}"
        )

    def test_full_fixture_with_guids_roundtrips_exactly(self, tmp_path):
        """Fixture pre-populated with guids → import → export → identical biz blocks.

        Complement to test_business_objects_roundtrip in test_business_objects.py:
        that test imports a guid-less fixture and ignores guid lines on compare;
        this one imports a fixture WITH explicit guids and demands exact match
        (because the guids are deterministic on the input side, they should be
        deterministic on the output side too).
        """
        from tests.integration.test_business_objects import extract_business_objects

        runner = CliRunner()
        gnc = tmp_path / "book.gnucash"
        r = _import_new(runner, gnc, "tests/fixtures/business_objects_with_guids.txt")
        assert r.exit_code == 0, f"Import failed:\n{r.output}"

        text = _exported_biz_text(runner, tmp_path, gnc)
        exported_biz = extract_business_objects(text)

        with open("tests/fixtures/business_objects_with_guids.txt") as f:
            reference_biz = extract_business_objects(f.read())

        assert exported_biz == reference_biz, (
            f"Business objects with explicit guids must round-trip exactly.\n"
            f"--- reference ---\n{reference_biz}\n"
            f"--- exported ---\n{exported_biz}"
        )


class TestGuidCollisionAcrossObjectTypes:
    """GnuCash keeps GUIDs unique book-wide. A customer cannot share its GUID
    with an account, transaction, vendor, or any other entity. Re-using a GUID
    that already belongs to a different entity type must error."""

    def _read_first_guid(self, gnc_path, qof_type: str) -> str:
        """Open the gnucash file with bindings and return the GUID of the
        first entity of the given QOF type ('Trans' or 'Account').

        Note: Account(instance=raw_ptr) wrapping is unsafe per CLAUDE.md
        ("SWIG may not wrap raw pointers safely"), so for accounts we walk
        the parent→children tree via the proper SWIG API instead of using
        the QofQuery results directly.
        """
        from gnucash import Query, Session, Transaction
        s = Session(f"xml://{gnc_path}")
        try:
            book = s.book
            if qof_type == 'Account':
                root = book.get_root_account()

                def first_descendant(acct):
                    for child in acct.get_children():
                        return child
                    return None

                first = first_descendant(root)
                assert first is not None, (
                    f"No accounts found in {gnc_path} — setup didn't populate."
                )
                return first.GetGUID().to_string()

            q = Query()
            q.search_for(qof_type)
            q.set_book(book)
            results = list(q.run())
            q.destroy()
            assert results, (
                f"No {qof_type} found in {gnc_path} — setup import was silent "
                f"about a malformed fixture. Check the fixture text."
            )
            return Transaction(instance=results[0]).GetGUID().to_string()
        finally:
            s.end()

    def test_customer_guid_collides_with_existing_transaction_errors(self, tmp_path):
        """Existing transaction has guid X; importing customer with guid: X must error."""
        runner = CliRunner()
        gnc = _setup_book_with(runner, tmp_path, "")
        # Setup: import a real transaction so the book has a transaction with a guid.
        tx_fix = (
            '2026-01-15 * "Test transaction"\n'
            '\tAssets:Bank          100.00 CAD\n'
            '\tIncome:Sales        -100.00 CAD\n'
        )
        r = _import(runner, gnc, _write(tmp_path / "tx.txt", tx_fix))
        assert r.exit_code == 0, f"Setup tx import failed:\n{r.output}"

        # Read the transaction's actual guid via gnucash bindings.
        tx_guid = self._read_first_guid(gnc, 'Trans')

        bad = (
            f'customer "C001"\n'
            f'\tguid: "{tx_guid}"\n'
            f'\tname: "Acme"\n'
            f'\tcurrency: CAD\n'
        )
        r = _import(runner, gnc, _write(tmp_path / "bad.txt", bad))
        assert r.exit_code != 0, (
            f"Customer with guid already used by a transaction must error.\n"
            f"Got success:\n{r.output}"
        )

    def test_customer_guid_collides_with_existing_account_errors(self, tmp_path):
        """The Assets account has a guid; reusing it for a customer must error."""
        runner = CliRunner()
        gnc = _setup_book_with(runner, tmp_path, "")
        # Read an existing account's guid via gnucash bindings (the plaintext
        # exporter doesn't emit account guids, so we go to the source).
        acct_guid = self._read_first_guid(gnc, 'Account')

        bad = (
            f'customer "C001"\n'
            f'\tguid: "{acct_guid}"\n'
            f'\tname: "Acme"\n'
            f'\tcurrency: CAD\n'
        )
        r = _import(runner, gnc, _write(tmp_path / "bad.txt", bad))
        assert r.exit_code != 0, (
            f"Customer with guid already used by an account must error.\n"
            f"Got success:\n{r.output}"
        )

    def test_vendor_guid_collides_with_existing_customer_errors(self, tmp_path):
        """Vendor and customer cannot share a GUID even though they're different types."""
        runner = CliRunner()
        gnc = _setup_book_with(runner, tmp_path,
            'customer "C001"\n\tguid: "22222222222222222222222222222222"\n\tname: "Acme"\n\tcurrency: CAD\n')

        bad = (
            'vendor "V001"\n'
            '\tguid: "22222222222222222222222222222222"\n'
            '\tname: "Supplier"\n'
            '\tcurrency: CAD\n'
        )
        r = _import(runner, gnc, _write(tmp_path / "bad.txt", bad))
        assert r.exit_code != 0, (
            f"Vendor with guid already used by a customer must error.\n"
            f"Got success:\n{r.output}"
        )


class TestPreexistingDuplicates:
    def test_reimport_into_book_with_duplicate_customers_errors(self, tmp_path):
        """If the book already has two customers sharing id, next re-import errors.

        We can't easily *create* such a state with the post-fix importer, so
        we exercise this path by constructing a book the legacy way (two
        sequential `customer "C001"` directives in a single file) and rely on
        the fact that the importer must either:
        - Error during the bad import itself (multiple-match on the second), or
        - Error on a subsequent re-import when the now-duplicated state is hit
        """
        runner = CliRunner()
        # Two customer "C001" blocks in one fixture — under the post-fix
        # importer this should already error or update; either way the book
        # should not end up with two C001 records.
        fixture = (
            'customer "C001"\n\tname: "First"\n\tcurrency: CAD\n'
            '\ncustomer "C001"\n\tname: "Second"\n\tcurrency: CAD\n'
        )
        gnc = tmp_path / "book.gnucash"
        fix = _write(tmp_path / "dup.txt", ACCOUNTS + "\n" + fixture)
        r = _import_new(runner, gnc, fix)
        # Either the import errors (preferred), or the export shows exactly 1.
        if r.exit_code == 0:
            text = _exported_biz_text(runner, tmp_path, gnc)
            assert _count_blocks(text, 'customer "C001"') == 1, (
                f"Two same-id directives in one file must not produce two records.\n"
                f"Export:\n{text}"
            )


# ─────────────────────────────────────────────────────────────────────────────
# Invoice / bill identity enforcement (Q-007 follow-up)
#
# Q-006 added id ⇔ guid conflict detection for customers and vendors.
# Invoices and bills had a weaker idempotency model (skip on id match, no
# guid check). These tests describe the desired behaviour after extending
# the conflict detection to invoices/bills:
#
#   - skip-on-existing stays the same (invoices have AR/AP lots, can't
#     update mutable fields safely mid-flight)
#   - but BEFORE skipping, verify identity is consistent: directive's
#     `guid:` must match the existing invoice's GUID, else error
#   - if directive's guid resolves to a DIFFERENT invoice's id, error
#   - same rules apply to bills
# ─────────────────────────────────────────────────────────────────────────────


_INVOICE_BASE = """
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


_BILL_BASE = """
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
\t\tprice: 50
\t\ttaxable: true
\t\ttax_included: false
\tposted: none
\tpayment: none
"""


class TestInvoiceBillIdentityEnforcement:
    """Invoice/bill identity must be consistent on re-import."""

    def test_reimport_same_invoice_is_idempotent(self, tmp_path):
        """Existing baseline: re-importing identical invoice file is a no-op."""
        runner = CliRunner()
        gnc = _setup_book_with(runner, tmp_path, _INVOICE_BASE)
        r = _import(runner, gnc, _write(tmp_path / "again.txt",
                                        ACCOUNTS + "\n" + _INVOICE_BASE))
        assert r.exit_code == 0, f"Re-import should be idempotent:\n{r.output}"
        text = _exported_biz_text(runner, tmp_path, gnc)
        assert _count_blocks(text, 'invoice "INV-001"') == 1

    def test_reimport_invoice_with_matching_guid_is_idempotent(self, tmp_path):
        """Directive carries `guid:` matching the existing invoice → skip cleanly."""
        runner = CliRunner()
        gnc = _setup_book_with(runner, tmp_path, _INVOICE_BASE)
        text = _exported_biz_text(runner, tmp_path, gnc)
        guid = _field_in_block(_block_for(text, 'invoice "INV-001"'),
                               'guid', strip_quotes=True)
        assert guid

        with_guid = _INVOICE_BASE.replace(
            'invoice "INV-001"\n',
            f'invoice "INV-001"\n\tguid: "{guid}"\n',
        )
        r = _import(runner, gnc, _write(tmp_path / "again.txt",
                                        ACCOUNTS + "\n" + with_guid))
        assert r.exit_code == 0, f"Re-import with matching guid must succeed:\n{r.output}"
        text2 = _exported_biz_text(runner, tmp_path, gnc)
        assert _count_blocks(text2, 'invoice "INV-001"') == 1

    def test_reimport_invoice_with_mismatched_guid_errors(self, tmp_path):
        """Directive's `guid:` doesn't match the existing INV-001's guid → error.

        Refuses to silently skip when the directive is claiming a different
        identity for an existing id.
        """
        runner = CliRunner()
        gnc = _setup_book_with(runner, tmp_path, _INVOICE_BASE)

        bad = _INVOICE_BASE.replace(
            'invoice "INV-001"\n',
            'invoice "INV-001"\n\tguid: "deadbeefdeadbeefdeadbeefdeadbeef"\n',
        )
        r = _import(runner, gnc, _write(tmp_path / "bad.txt",
                                        ACCOUNTS + "\n" + bad))
        assert r.exit_code != 0, (
            f"Mismatched guid on existing invoice id must error:\n{r.output}"
        )

    def test_reimport_invoice_guid_resolves_to_different_id_errors(self, tmp_path):
        """Directive says `INV-002` + guid of INV-001 → error.

        We must not let the user file a new invoice claiming an existing
        invoice's GUID.
        """
        runner = CliRunner()
        gnc = _setup_book_with(runner, tmp_path, _INVOICE_BASE)
        text = _exported_biz_text(runner, tmp_path, gnc)
        inv1_guid = _field_in_block(_block_for(text, 'invoice "INV-001"'),
                                    'guid', strip_quotes=True)
        assert inv1_guid

        # Replace only the header line (first occurrence) and add a guid line.
        bad = _INVOICE_BASE.replace(
            'invoice "INV-001"',
            f'invoice "INV-002"\n\tguid: "{inv1_guid}"',
            1,
        )
        r = _import(runner, gnc, _write(tmp_path / "bad.txt",
                                        ACCOUNTS + "\n" + bad))
        assert r.exit_code != 0, (
            f"Reusing INV-001's guid for new INV-002 must error:\n{r.output}"
        )

    # ─── Same suite for bills ───────────────────────────────────────────────

    def test_reimport_same_bill_is_idempotent(self, tmp_path):
        runner = CliRunner()
        gnc = _setup_book_with(runner, tmp_path, _BILL_BASE)
        r = _import(runner, gnc, _write(tmp_path / "again.txt",
                                        ACCOUNTS + "\n" + _BILL_BASE))
        assert r.exit_code == 0, f"Re-import should be idempotent:\n{r.output}"
        text = _exported_biz_text(runner, tmp_path, gnc)
        assert _count_blocks(text, 'bill "BILL-001"') == 1

    def test_reimport_bill_with_matching_guid_is_idempotent(self, tmp_path):
        runner = CliRunner()
        gnc = _setup_book_with(runner, tmp_path, _BILL_BASE)
        text = _exported_biz_text(runner, tmp_path, gnc)
        guid = _field_in_block(_block_for(text, 'bill "BILL-001"'),
                               'guid', strip_quotes=True)
        assert guid

        with_guid = _BILL_BASE.replace(
            'bill "BILL-001"\n',
            f'bill "BILL-001"\n\tguid: "{guid}"\n',
        )
        r = _import(runner, gnc, _write(tmp_path / "again.txt",
                                        ACCOUNTS + "\n" + with_guid))
        assert r.exit_code == 0, f"Re-import with matching guid must succeed:\n{r.output}"

    def test_reimport_bill_with_mismatched_guid_errors(self, tmp_path):
        runner = CliRunner()
        gnc = _setup_book_with(runner, tmp_path, _BILL_BASE)

        bad = _BILL_BASE.replace(
            'bill "BILL-001"\n',
            'bill "BILL-001"\n\tguid: "deadbeefdeadbeefdeadbeefdeadbeef"\n',
        )
        r = _import(runner, gnc, _write(tmp_path / "bad.txt",
                                        ACCOUNTS + "\n" + bad))
        assert r.exit_code != 0, (
            f"Mismatched guid on existing bill id must error:\n{r.output}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Tax-table identity enforcement (Q-008)
#
# Tax tables previously had no idempotency or guid honour at all in the
# importer: each re-import created a fresh duplicate, and invoice/bill
# entries that reference `tax_table: "GST"` would non-deterministically
# pick whichever match `gncTaxTableLookupByName` returned first. That
# silently misroutes tax onto the wrong rate. These tests describe the
# desired behaviour after extending Q-006 §2 resolution to tax tables:
#
#   - skip-on-existing (referenced by posted invoices, can't safely mutate)
#   - directive's `guid:` must match the existing tax table's guid, else
#     error
#   - directive's `guid:` resolving to a different name → error
#   - book has multiple tax tables with the same name → error
# ─────────────────────────────────────────────────────────────────────────────


_TAXTABLE_BASE = """
taxtable "GST"
\tentry:
\t\taccount: "Liabilities:Accounts Payable"
\t\trate: 5.0%
\t\ttype: PERCENT
"""


_TAXTABLE_PST = """
taxtable "PST"
\tentry:
\t\taccount: "Liabilities:Accounts Payable"
\t\trate: 7.0%
\t\ttype: PERCENT
"""


class TestTaxTableIdentityEnforcement:
    """Tax-table identity must be consistent on re-import."""

    def test_reimport_same_taxtable_is_idempotent(self, tmp_path):
        """Re-importing a file with the same `taxtable "GST"` block must
        not create a duplicate."""
        runner = CliRunner()
        gnc = _setup_book_with(runner, tmp_path, _TAXTABLE_BASE)
        r = _import(runner, gnc, _write(tmp_path / "again.txt",
                                        ACCOUNTS + "\n" + _TAXTABLE_BASE))
        assert r.exit_code == 0, f"Re-import should be idempotent:\n{r.output}"
        text = _exported_biz_text(runner, tmp_path, gnc)
        assert _count_blocks(text, 'taxtable "GST"') == 1, (
            f"Expected exactly one taxtable 'GST' after re-import; got\n{text}"
        )

    def test_reimport_taxtable_with_matching_guid_is_idempotent(self, tmp_path):
        """Directive carries `guid:` matching the existing tax table → skip."""
        runner = CliRunner()
        gnc = _setup_book_with(runner, tmp_path, _TAXTABLE_BASE)
        text = _exported_biz_text(runner, tmp_path, gnc)
        guid = _field_in_block(_block_for(text, 'taxtable "GST"'),
                               'guid', strip_quotes=True)
        assert guid

        with_guid = _TAXTABLE_BASE.replace(
            'taxtable "GST"\n',
            f'taxtable "GST"\n\tguid: "{guid}"\n',
        )
        r = _import(runner, gnc, _write(tmp_path / "again.txt",
                                        ACCOUNTS + "\n" + with_guid))
        assert r.exit_code == 0, f"Re-import with matching guid must succeed:\n{r.output}"
        text2 = _exported_biz_text(runner, tmp_path, gnc)
        assert _count_blocks(text2, 'taxtable "GST"') == 1

    def test_reimport_taxtable_with_mismatched_guid_errors(self, tmp_path):
        """Directive's `guid:` doesn't match the existing GST's guid → error."""
        runner = CliRunner()
        gnc = _setup_book_with(runner, tmp_path, _TAXTABLE_BASE)

        bad = _TAXTABLE_BASE.replace(
            'taxtable "GST"\n',
            'taxtable "GST"\n\tguid: "deadbeefdeadbeefdeadbeefdeadbeef"\n',
        )
        r = _import(runner, gnc, _write(tmp_path / "bad.txt",
                                        ACCOUNTS + "\n" + bad))
        assert r.exit_code != 0, (
            f"Mismatched guid on existing taxtable name must error:\n{r.output}"
        )

    def test_reimport_taxtable_guid_resolves_to_different_name_errors(self, tmp_path):
        """Directive says `taxtable "PST"` + guid of existing GST → error."""
        runner = CliRunner()
        gnc = _setup_book_with(runner, tmp_path, _TAXTABLE_BASE)
        text = _exported_biz_text(runner, tmp_path, gnc)
        gst_guid = _field_in_block(_block_for(text, 'taxtable "GST"'),
                                   'guid', strip_quotes=True)
        assert gst_guid

        bad = _TAXTABLE_PST.replace(
            'taxtable "PST"\n',
            f'taxtable "PST"\n\tguid: "{gst_guid}"\n',
        )
        r = _import(runner, gnc, _write(tmp_path / "bad.txt",
                                        ACCOUNTS + "\n" + bad))
        assert r.exit_code != 0, (
            f"Reusing GST's guid for new PST must error:\n{r.output}"
        )

    def test_same_file_two_taxtables_with_same_name(self, tmp_path):
        """Two `taxtable "GST"` blocks in one file must NOT produce two
        records. Either the importer errors or the second is skipped
        (because the first already created the table). Both are acceptable;
        what we forbid is silent duplication."""
        runner = CliRunner()
        fixture = _TAXTABLE_BASE + _TAXTABLE_BASE  # duplicate!
        gnc = tmp_path / "book.gnucash"
        fix = _write(tmp_path / "dup.txt", ACCOUNTS + "\n" + fixture)
        r = _import_new(runner, gnc, fix)
        if r.exit_code == 0:
            text = _exported_biz_text(runner, tmp_path, gnc)
            assert _count_blocks(text, 'taxtable "GST"') == 1


# ─────────────────────────────────────────────────────────────────────────────
# Q-007 follow-up: unposted → posted transition must be allowed
#
# Q-007 introduced "skip on existing invoice/bill" so that posted records
# (whose AR/AP lots are wired into a real transaction) can't be silently
# mutated. That was right for the posted case but wrong for the unposted
# case — a user's natural workflow is:
#
#   1. import invoice with `posted: none`
#   2. edit the file: replace `posted: none` with a real `posted:` block
#   3. re-import
#
# Reported by an external user. After Q-007 step 3 silently skipped,
# leaving the invoice unposted forever. These tests describe the desired
# behaviour: the importer should *allow* the unposted → posted transition
# (no AR/AP lot exists yet to corrupt) but keep skipping when the existing
# record is already posted.
# ─────────────────────────────────────────────────────────────────────────────


_INVOICE_UNPOSTED = """
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


_INVOICE_POSTED = """
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


_BILL_UNPOSTED = """
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
\t\tprice: 50
\t\ttaxable: true
\t\ttax_included: false
\tposted: none
\tpayment: none
"""


_BILL_POSTED = """
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
\t\tprice: 50
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


class TestUnpostedToPostedTransition:
    """Re-import must allow the unposted→posted transition (Q-007 fix)."""

    def test_invoice_unposted_can_be_posted_via_reimport(self, tmp_path):
        """Step 1: import invoice with `posted: none`. Step 2: re-import same
        invoice but with a real `posted:` block. Expected: the existing
        invoice is now posted, not silently skipped."""
        runner = CliRunner()
        gnc = _setup_book_with(runner, tmp_path, _INVOICE_UNPOSTED)
        # Confirm baseline: invoice exists and is unposted
        text = _exported_biz_text(runner, tmp_path, gnc)
        block = _block_for(text, 'invoice "INV-001"')
        assert any('posted: none' in line for line in block), (
            "Setup expected unposted invoice; got:\n" + "\n".join(block)
        )

        # Re-import with a real posted block
        r = _import(runner, gnc, _write(tmp_path / "post.txt",
                                        ACCOUNTS + "\n" + _INVOICE_POSTED))
        assert r.exit_code == 0, f"Posting via re-import must succeed:\n{r.output}"

        # The existing invoice should now have a posted: block (not 'posted: none')
        text2 = _exported_biz_text(runner, tmp_path, gnc)
        block2 = _block_for(text2, 'invoice "INV-001"')
        assert _count_blocks(text2, 'invoice "INV-001"') == 1, (
            "Posting must not duplicate the invoice"
        )
        assert any('posted:' in line and 'posted: none' not in line
                   for line in block2), (
            "Invoice must be posted after re-import; block:\n"
            + "\n".join(block2)
        )

    def test_bill_unposted_can_be_posted_via_reimport(self, tmp_path):
        runner = CliRunner()
        gnc = _setup_book_with(runner, tmp_path, _BILL_UNPOSTED)

        r = _import(runner, gnc, _write(tmp_path / "post.txt",
                                        ACCOUNTS + "\n" + _BILL_POSTED))
        assert r.exit_code == 0, f"Posting via re-import must succeed:\n{r.output}"

        text = _exported_biz_text(runner, tmp_path, gnc)
        block = _block_for(text, 'bill "BILL-001"')
        assert _count_blocks(text, 'bill "BILL-001"') == 1
        assert any('posted:' in line and 'posted: none' not in line
                   for line in block), (
            "Bill must be posted after re-import; block:\n" + "\n".join(block)
        )

    def test_already_posted_invoice_unchanged_on_identical_reimport(self, tmp_path):
        """Q-010: an identical re-import of a posted invoice is 'unchanged'
        (not 'skipped'). The previous Q-007 'always skip posted' rule was
        too coarse and contradicted GnuCash's own UI."""
        runner = CliRunner()
        gnc = _setup_book_with(runner, tmp_path, _INVOICE_POSTED)

        r = _import(runner, gnc, _write(tmp_path / "again.txt",
                                        ACCOUNTS + "\n" + _INVOICE_POSTED))
        assert r.exit_code == 0
        assert 'invoice "INV-001": unchanged' in r.output, (
            f"Identical re-import of posted invoice should be 'unchanged':\n{r.output}"
        )

    def test_already_posted_bill_unchanged_on_identical_reimport(self, tmp_path):
        runner = CliRunner()
        gnc = _setup_book_with(runner, tmp_path, _BILL_POSTED)

        r = _import(runner, gnc, _write(tmp_path / "again.txt",
                                        ACCOUNTS + "\n" + _BILL_POSTED))
        assert r.exit_code == 0
        assert 'bill "BILL-001": unchanged' in r.output

    def test_unposted_to_posted_status_line_says_updated(self, tmp_path):
        """When re-import successfully posts an unposted invoice, the
        per-directive status line should say 'updated' (not 'skipped' and
        not 'created' — the record already existed and was modified)."""
        runner = CliRunner()
        gnc = _setup_book_with(runner, tmp_path, _INVOICE_UNPOSTED)

        r = _import(runner, gnc, _write(tmp_path / "post.txt",
                                        ACCOUNTS + "\n" + _INVOICE_POSTED))
        assert r.exit_code == 0
        assert 'invoice "INV-001": updated' in r.output, (
            f"Posting an unposted invoice should report 'updated':\n{r.output}"
        )

    def test_posted_invoice_notes_change_unposts_and_reposts(self, tmp_path):
        """Q-010: posted invoices ARE editable via re-import (unpost → edit
        → repost), matching what GnuCash's UI itself supports. Adding a
        notes field to a posted invoice triggers the unpost-repost cycle
        and the new notes appear in the exported invoice."""
        runner = CliRunner()
        gnc = _setup_book_with(runner, tmp_path, _INVOICE_POSTED)
        with_notes = _INVOICE_POSTED.replace(
            'invoice "INV-001"\n',
            'invoice "INV-001"\n\tnotes: "Updated after the fact"\n',
        )
        r = _import(runner, gnc, _write(tmp_path / "with_notes.txt",
                                        ACCOUNTS + "\n" + with_notes))
        assert r.exit_code == 0, r.output
        assert 'invoice "INV-001": updated' in r.output, r.output
        text = _exported_biz_text(runner, tmp_path, gnc)
        block = _block_for(text, 'invoice "INV-001"')
        assert any('Updated after the fact' in line for line in block), (
            "New notes must appear after re-import; got:\n" + "\n".join(block)
        )
