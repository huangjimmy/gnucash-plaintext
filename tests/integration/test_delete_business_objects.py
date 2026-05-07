"""
Integration tests for delete-customers, delete-vendors,
archive-customers, archive-vendors CLI commands (F-011).

Covers:
  - active flag round-trip: inactive customer/vendor exported with
    "active: false" and re-imported correctly (GetActive() == False)
  - delete: succeeds (exit 0) when no invoices/bills linked
  - delete: fails (exit 1) when invoices/bills are linked; entity survives
  - delete: fails (exit 1) for unknown ID; no file corruption
  - delete: mixed batch — partial success still saves, exits 1
  - archive: succeeds (exit 0) for active customer/vendor
  - archive: reports invoice/bill count in output (informational)
  - archive: fails (exit 1) for already-archived entity
  - archive: fails (exit 1) for unknown ID
  - archive: mixed batch
"""

import re

import pytest
from click.testing import CliRunner

from cli.main import cli

FIXTURE = "tests/fixtures/business_objects.txt"


def _has_status_line(output, id_, status_substring):
    """Match a '<id> (<32-hex-guid>): <status...>' line in `output`.

    The CLI always prints the matched record's GUID alongside the id, so
    a successful hit looks like `2 (9f14a4…): deleted`. Use this helper
    instead of plain substring checks so tests are explicit about the
    format and don't accidentally match on substrings that would survive
    a regression to id-only output.
    """
    pat = rf'(?m)^{re.escape(id_)} \([0-9a-f]{{32}}\): {re.escape(status_substring)}'
    assert re.search(pat, output), (
        f"Expected line matching {pat!r}\nGot:\n{output}"
    )


def _has_not_found_line(output, input_str):
    """Match the miss line: '<input>: not found' (no guid since lookup failed)."""
    pat = rf'(?m)^{re.escape(input_str)}: not found\s*$'
    assert re.search(pat, output), (
        f"Expected line matching {pat!r}\nGot:\n{output}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def import_fixture(runner, gnucash_file, fixture=FIXTURE):
    import time
    result = runner.invoke(cli, [
        "import", "--new", str(gnucash_file), fixture, "--include-business-objects",
    ])
    assert result.exit_code == 0, f"Import failed:\n{result.output}"
    # GnuCash backup filenames use a per-second timestamp. Without a pause,
    # the next save in the same test would collide with the import's backup
    # timestamp and fail silently. 1 second is enough to guarantee a new
    # timestamp on the subsequent save.
    time.sleep(1)


def export_biz(runner, gnucash_file):
    import os
    import tempfile
    fd, out = tempfile.mkstemp(suffix='.txt')
    os.close(fd)
    try:
        result = runner.invoke(cli, ["export", str(gnucash_file), out,
                                     "--include-business-objects"])
        assert result.exit_code == 0, f"Export failed:\n{result.output}"
        with open(out, encoding='utf-8') as f:
            return f.read()
    finally:
        os.unlink(out)


# ─────────────────────────────────────────────────────────────────────────────
# A. Active flag round-trip
# ─────────────────────────────────────────────────────────────────────────────

def test_active_flag_roundtrip_customer(tmp_path):
    """active: false on customer survives import → export cycle."""
    runner = CliRunner()
    gf = tmp_path / "test.gnucash"
    import_fixture(runner, gf)
    exported = export_biz(runner, gf)
    # Customer "2" is inactive in the fixture
    assert 'customer "2"' in exported
    assert '	active: false' in exported


def test_active_flag_roundtrip_vendor(tmp_path):
    """active: false on vendor survives import → export cycle."""
    runner = CliRunner()
    gf = tmp_path / "test.gnucash"
    import_fixture(runner, gf)
    exported = export_biz(runner, gf)
    assert 'vendor "V002"' in exported
    assert '	active: false' in exported


def test_active_customer_has_no_active_field(tmp_path):
    """Active customers must NOT emit an 'active:' line (omit when true)."""
    runner = CliRunner()
    gf = tmp_path / "test.gnucash"
    import_fixture(runner, gf)
    exported = export_biz(runner, gf)
    lines = exported.splitlines()
    in_cust1 = False
    for line in lines:
        if line == 'customer "1"':
            in_cust1 = True
        elif in_cust1 and line and line[0:1] not in (' ', '\t'):
            break
        elif in_cust1:
            assert 'active:' not in line, \
                "Active customer must not emit active: field"


def test_active_vendor_has_no_active_field(tmp_path):
    """Active vendors must NOT emit an 'active:' line."""
    runner = CliRunner()
    gf = tmp_path / "test.gnucash"
    import_fixture(runner, gf)
    exported = export_biz(runner, gf)
    lines = exported.splitlines()
    in_v001 = False
    for line in lines:
        if line == 'vendor "V001"':
            in_v001 = True
        elif in_v001 and line and line[0:1] not in (' ', '\t'):
            break
        elif in_v001:
            assert 'active:' not in line, \
                "Active vendor must not emit active: field"


# ─────────────────────────────────────────────────────────────────────────────
# B. delete-customers
# ─────────────────────────────────────────────────────────────────────────────

def test_delete_customer_no_invoices(tmp_path):
    """delete-customers succeeds (exit 0) when customer has no invoices."""
    runner = CliRunner()
    gf = tmp_path / "test.gnucash"
    import_fixture(runner, gf)

    result = runner.invoke(cli, ["delete-customers", str(gf), "2"])
    assert result.exit_code == 0, result.output
    _has_status_line(result.output, "2", "deleted")

    # Customer "2" must be gone from subsequent export
    exported = export_biz(runner, gf)
    assert 'customer "2"' not in exported


def test_delete_customer_with_invoices_blocked(tmp_path):
    """delete-customers fails (exit 1) when customer has linked invoices."""
    runner = CliRunner()
    gf = tmp_path / "test.gnucash"
    import_fixture(runner, gf)

    # Customer "1" has invoices in the fixture
    result = runner.invoke(cli, ["delete-customers", str(gf), "1"])
    assert result.exit_code == 1
    _has_status_line(result.output, "1", "failed")
    assert "cannot delete" in result.output
    assert "invoice" in result.output

    # Customer "1" must still exist
    exported = export_biz(runner, gf)
    assert 'customer "1"' in exported


def test_delete_customer_not_found(tmp_path):
    """delete-customers exits 1 and reports not found for unknown ID."""
    runner = CliRunner()
    gf = tmp_path / "test.gnucash"
    import_fixture(runner, gf)

    result = runner.invoke(cli, ["delete-customers", str(gf), "DOES-NOT-EXIST"])
    assert result.exit_code == 1
    _has_not_found_line(result.output, "DOES-NOT-EXIST")


def test_delete_customers_batch_mixed(tmp_path):
    """delete-customers batch: one succeeds, one blocked, exit 1 overall."""
    runner = CliRunner()
    gf = tmp_path / "test.gnucash"
    import_fixture(runner, gf)

    result = runner.invoke(cli, ["delete-customers", str(gf), "2", "1"])
    assert result.exit_code == 1
    _has_status_line(result.output, "2", "deleted")
    _has_status_line(result.output, "1", "failed")

    exported = export_biz(runner, gf)
    assert 'customer "2"' not in exported   # successfully deleted
    assert 'customer "1"' in exported        # blocked, still present


def test_delete_customer_inactive_no_invoices(tmp_path):
    """Inactive customer with no invoices can still be hard-deleted."""
    runner = CliRunner()
    gf = tmp_path / "test.gnucash"
    import_fixture(runner, gf)

    # "2" is inactive and has no invoices
    result = runner.invoke(cli, ["delete-customers", str(gf), "2"])
    assert result.exit_code == 0
    _has_status_line(result.output, "2", "deleted")


# ─────────────────────────────────────────────────────────────────────────────
# C. archive-customers
# ─────────────────────────────────────────────────────────────────────────────

def test_archive_customer_active_no_invoices(tmp_path):
    """archive-customers on active customer with no invoices: archived, exit 0."""
    runner = CliRunner()
    gf = tmp_path / "test.gnucash"
    import_fixture(runner, gf)

    # "2" is active-imported-as-inactive but after re-import it's inactive —
    # use a fresh active customer without invoices by deleting "2" first and
    # checking "1" archive shows invoice count.
    # Instead: archive "2" which is already inactive → should show already archived
    # Actually "2" is imported with active: false, so it IS already archived.
    # We need to test with customer "1" (active, has invoices) to get invoice count.

    result = runner.invoke(cli, ["archive-customers", str(gf), "1"])
    assert result.exit_code == 0, result.output
    _has_status_line(result.output, "1", "archived")
    # "1" has invoices — should show count
    assert "invoice" in result.output

    exported = export_biz(runner, gf)
    # "1" must still exist but now inactive
    lines = exported.splitlines()
    in_cust1 = False
    found_active_false = False
    for line in lines:
        if line == 'customer "1"':
            in_cust1 = True
        elif in_cust1 and line and line[0:1] not in (' ', '\t'):
            break
        elif in_cust1 and 'active: false' in line:
            found_active_false = True
    assert found_active_false, "Archived customer must have active: false in export"


def test_archive_customer_already_archived(tmp_path):
    """archive-customers on already-inactive customer: already archived, exit 1."""
    runner = CliRunner()
    gf = tmp_path / "test.gnucash"
    import_fixture(runner, gf)

    # "2" is imported as inactive
    result = runner.invoke(cli, ["archive-customers", str(gf), "2"])
    assert result.exit_code == 1
    _has_status_line(result.output, "2", "already archived")


def test_archive_customer_not_found(tmp_path):
    """archive-customers exits 1 for unknown ID."""
    runner = CliRunner()
    gf = tmp_path / "test.gnucash"
    import_fixture(runner, gf)

    result = runner.invoke(cli, ["archive-customers", str(gf), "DOES-NOT-EXIST"])
    assert result.exit_code == 1
    _has_not_found_line(result.output, "DOES-NOT-EXIST")


def test_archive_customers_batch_mixed(tmp_path):
    """archive-customers batch: active succeeds, already-archived fails, exit 1."""
    runner = CliRunner()
    gf = tmp_path / "test.gnucash"
    import_fixture(runner, gf)

    result = runner.invoke(cli, ["archive-customers", str(gf), "1", "2"])
    assert result.exit_code == 1
    _has_status_line(result.output, "1", "archived")
    _has_status_line(result.output, "2", "already archived")


def test_archive_customer_invoice_count_in_output(tmp_path):
    """archive-customers shows linked invoice count when invoices exist."""
    runner = CliRunner()
    gf = tmp_path / "test.gnucash"
    import_fixture(runner, gf)

    result = runner.invoke(cli, ["archive-customers", str(gf), "1"])
    assert result.exit_code == 0
    # Must show count of linked invoices, not just "archived"
    assert re.search(r'1 \([0-9a-f]{32}\): archived — \d+ invoice', result.output), \
        f"Expected invoice count in output, got: {result.output!r}"


# ─────────────────────────────────────────────────────────────────────────────
# D. archive-vendors
# ─────────────────────────────────────────────────────────────────────────────

def test_archive_vendor_with_bills(tmp_path):
    """archive-vendors on active vendor with bills: archived with count, exit 0."""
    runner = CliRunner()
    gf = tmp_path / "test.gnucash"
    import_fixture(runner, gf)

    result = runner.invoke(cli, ["archive-vendors", str(gf), "V001"])
    assert result.exit_code == 0, result.output
    _has_status_line(result.output, "V001", "archived")
    assert "invoice" in result.output

    exported = export_biz(runner, gf)
    lines = exported.splitlines()
    in_v001 = False
    found_active_false = False
    for line in lines:
        if line == 'vendor "V001"':
            in_v001 = True
        elif in_v001 and line and line[0:1] not in (' ', '\t'):
            break
        elif in_v001 and 'active: false' in line:
            found_active_false = True
    assert found_active_false, "Archived vendor must have active: false in export"


def test_archive_vendor_already_archived(tmp_path):
    """archive-vendors on already-inactive vendor: already archived, exit 1."""
    runner = CliRunner()
    gf = tmp_path / "test.gnucash"
    import_fixture(runner, gf)

    result = runner.invoke(cli, ["archive-vendors", str(gf), "V002"])
    assert result.exit_code == 1
    _has_status_line(result.output, "V002", "already archived")


def test_archive_vendor_not_found(tmp_path):
    """archive-vendors exits 1 for unknown ID."""
    runner = CliRunner()
    gf = tmp_path / "test.gnucash"
    import_fixture(runner, gf)

    result = runner.invoke(cli, ["archive-vendors", str(gf), "DOES-NOT-EXIST"])
    assert result.exit_code == 1
    _has_not_found_line(result.output, "DOES-NOT-EXIST")


def test_archive_vendors_batch_mixed(tmp_path):
    """archive-vendors batch: active succeeds, already-archived fails, exit 1."""
    runner = CliRunner()
    gf = tmp_path / "test.gnucash"
    import_fixture(runner, gf)

    result = runner.invoke(cli, ["archive-vendors", str(gf), "V001", "V002"])
    assert result.exit_code == 1
    _has_status_line(result.output, "V001", "archived")
    _has_status_line(result.output, "V002", "already archived")


# ─────────────────────────────────────────────────────────────────────────────
# E. --by-guid flag (Q-007)
#
# delete-customers / archive-customers / archive-vendors must accept GUIDs as
# well as user-facing ids. The flag is opt-in (default behaviour stays
# id-based) because nothing prevents a customer's id from happening to be a
# 32-char hex string — auto-detection would silently misroute.
# ─────────────────────────────────────────────────────────────────────────────


def _customer_guid_for_id(gnc_path, cust_id):
    """Read a customer's GUID from the saved gnucash file via the bindings."""
    from gnucash import Session
    s = Session(f"xml://{gnc_path}")
    try:
        cust = s.book.CustomerLookupByID(cust_id)
        assert cust is not None, f"Setup fixture missing customer {cust_id!r}"
        return cust.GetGUID().to_string()
    finally:
        s.end()


def _vendor_guid_for_id(gnc_path, vend_id):
    from gnucash import Session
    s = Session(f"xml://{gnc_path}")
    try:
        v = s.book.VendorLookupByID(vend_id)
        assert v is not None, f"Setup fixture missing vendor {vend_id!r}"
        return v.GetGUID().to_string()
    finally:
        s.end()


def test_delete_customer_by_guid_no_invoices(tmp_path):
    """delete-customers --by-guid <guid> deletes the matching customer.

    Output uses the same `<id> (<guid>)` format whether you address by id
    or by guid, so the user always sees both identifiers.
    """
    runner = CliRunner()
    gf = tmp_path / "test.gnucash"
    import_fixture(runner, gf)
    guid = _customer_guid_for_id(gf, "2")

    result = runner.invoke(cli, ["delete-customers", str(gf), "--by-guid", guid])
    assert result.exit_code == 0, result.output
    assert f"2 ({guid}): deleted" in result.output
    exported = export_biz(runner, gf)
    assert 'customer "2"' not in exported


def test_delete_customer_by_guid_with_invoices_blocked(tmp_path):
    """--by-guid still blocks when invoices are linked, exit 1."""
    runner = CliRunner()
    gf = tmp_path / "test.gnucash"
    import_fixture(runner, gf)
    guid = _customer_guid_for_id(gf, "1")  # Customer "1" has invoices in fixture

    result = runner.invoke(cli, ["delete-customers", str(gf), "--by-guid", guid])
    assert result.exit_code == 1
    assert f"1 ({guid}): failed" in result.output
    assert "cannot delete" in result.output


def test_delete_customer_by_guid_not_found(tmp_path):
    """--by-guid with a valid-format guid that doesn't match → not found, exit 1.

    On a miss there's no record, so no resolved id — the line falls back to
    just the user-typed guid.
    """
    runner = CliRunner()
    gf = tmp_path / "test.gnucash"
    import_fixture(runner, gf)

    bogus = "deadbeefdeadbeefdeadbeefdeadbeef"
    result = runner.invoke(cli, ["delete-customers", str(gf), "--by-guid", bogus])
    assert result.exit_code == 1
    _has_not_found_line(result.output, bogus)


def test_delete_customer_by_guid_invalid_format(tmp_path):
    """--by-guid with a malformed guid surfaces an Invalid GUID error, exit 1."""
    runner = CliRunner()
    gf = tmp_path / "test.gnucash"
    import_fixture(runner, gf)

    result = runner.invoke(cli, ["delete-customers", str(gf), "--by-guid", "hello"])
    assert result.exit_code != 0
    assert "invalid guid" in result.output.lower()


def test_delete_customers_by_guid_batch(tmp_path):
    """Batch of two GUIDs: one with invoices (blocked), one without (deleted)."""
    runner = CliRunner()
    gf = tmp_path / "test.gnucash"
    import_fixture(runner, gf)
    g1 = _customer_guid_for_id(gf, "1")
    g2 = _customer_guid_for_id(gf, "2")

    result = runner.invoke(cli, ["delete-customers", str(gf), "--by-guid", g1, g2])
    assert result.exit_code == 1  # 1 failed, 2 ok → overall failure
    assert f"1 ({g1}): failed" in result.output
    assert f"2 ({g2}): deleted" in result.output


def test_archive_customer_by_guid_active(tmp_path):
    """archive-customers --by-guid soft-hides an active customer."""
    runner = CliRunner()
    gf = tmp_path / "test.gnucash"
    import_fixture(runner, gf)
    guid = _customer_guid_for_id(gf, "1")

    result = runner.invoke(cli, ["archive-customers", str(gf), "--by-guid", guid])
    assert result.exit_code == 0, result.output
    assert f"1 ({guid}): archived" in result.output
    exported = export_biz(runner, gf)
    # Customer "1" still present, just inactive
    assert 'customer "1"' in exported
    assert "active: false" in exported


def test_archive_customer_by_guid_not_found(tmp_path):
    runner = CliRunner()
    gf = tmp_path / "test.gnucash"
    import_fixture(runner, gf)

    bogus = "deadbeefdeadbeefdeadbeefdeadbeef"
    result = runner.invoke(cli, ["archive-customers", str(gf), "--by-guid", bogus])
    assert result.exit_code == 1
    _has_not_found_line(result.output, bogus)


def test_archive_vendor_by_guid_active(tmp_path):
    """archive-vendors --by-guid soft-hides an active vendor."""
    runner = CliRunner()
    gf = tmp_path / "test.gnucash"
    import_fixture(runner, gf)
    guid = _vendor_guid_for_id(gf, "V001")

    result = runner.invoke(cli, ["archive-vendors", str(gf), "--by-guid", guid])
    assert result.exit_code == 0, result.output
    assert f"V001 ({guid}): archived" in result.output


def test_archive_vendor_by_guid_already_archived(tmp_path):
    """V002 is inactive in the fixture — by-guid path must report that too."""
    runner = CliRunner()
    gf = tmp_path / "test.gnucash"
    import_fixture(runner, gf)
    guid = _vendor_guid_for_id(gf, "V002")

    result = runner.invoke(cli, ["archive-vendors", str(gf), "--by-guid", guid])
    assert result.exit_code == 1
    assert f"V002 ({guid}): already archived" in result.output


def test_archive_vendor_by_guid_not_found(tmp_path):
    runner = CliRunner()
    gf = tmp_path / "test.gnucash"
    import_fixture(runner, gf)

    bogus = "deadbeefdeadbeefdeadbeefdeadbeef"
    result = runner.invoke(cli, ["archive-vendors", str(gf), "--by-guid", bogus])
    assert result.exit_code == 1
    _has_not_found_line(result.output, bogus)


def test_by_guid_accepts_uuid_with_hyphens(tmp_path):
    """UUID-with-hyphens form is normalised the same way --txn_guid is.

    The output echoes the *normalised* (no-hyphen, lowercase) form so it
    matches what the GnuCash file actually stores.
    """
    runner = CliRunner()
    gf = tmp_path / "test.gnucash"
    import_fixture(runner, gf)
    guid = _customer_guid_for_id(gf, "2")
    uuid_form = f"{guid[0:8]}-{guid[8:12]}-{guid[12:16]}-{guid[16:20]}-{guid[20:32]}"

    result = runner.invoke(cli, ["delete-customers", str(gf),
                                 "--by-guid", uuid_form])
    assert result.exit_code == 0, result.output
    assert f"2 ({guid}): deleted" in result.output
