"""
Q-009: business-object import gives clear feedback on every directive.
Q-010: extends the status set with 'unchanged' (no-diff re-import) and
makes posted invoices/bills mutable via unpost-edit-repost. Tax tables
remain the only kind that's immutable on hit.

Tests describe the desired CLI output. On import, the user should see
two complementary signals:

1. **Per-directive line, inline as the import runs:**

       customer "C001": created
       customer "C002": unchanged
       taxtable "GST": skipped       ← immutable, refused
       invoice "INV-001": unchanged  ← exact byte-for-byte match
       bill "BILL-001": updated      ← entry edited, unposted+reposted

2. **Aggregate counts in the import summary at the end:**

       Business Objects:
         Customers:  1 created, 1 updated, 0 unchanged, 0 skipped
         Vendors:    0 created, 1 updated, 0 unchanged, 0 skipped
         Tax tables: 0 created, 0 updated, 0 unchanged, 1 skipped
         Invoices:   1 created, 0 updated, 1 unchanged, 0 skipped
         Bills:      0 created, 0 updated, 1 unchanged, 0 skipped

These tests don't introspect the gnucash file at all — they're
purely about CLI surface output. The other identity tests in
test_business_object_idempotent_reimport.py already cover the
underlying behaviour.
"""

import re

import pytest
from click.testing import CliRunner

from cli.main import cli

FIXTURE = "tests/fixtures/business_objects.txt"


def _import_new(runner, gnc):
    return runner.invoke(cli, ["import", "--new", str(gnc), FIXTURE,
                               "--include-business-objects"])


def _reimport(runner, gnc):
    return runner.invoke(cli, ["import", str(gnc), FIXTURE,
                               "--include-business-objects"])


# ── Per-directive output ────────────────────────────────────────────────────


class TestPerDirectiveOutput:
    """Each business-object directive emits a status line as it imports."""

    def test_fresh_import_shows_created_for_each_directive(self, tmp_path):
        runner = CliRunner()
        gnc = tmp_path / "test.gnucash"
        r = _import_new(runner, gnc)
        assert r.exit_code == 0, r.output
        # Fixture has customers "1" and "2", vendor V001 and V002,
        # taxtable GST, invoices INV-2026-001..005, bills BILL-2026-001..005
        for line_substr in [
            'customer "1": created',
            'customer "2": created',
            'vendor "V001": created',
            'vendor "V002": created',
            'taxtable "GST": created',
            'invoice "INV-2026-001": created',
            'bill "BILL-2026-001": created',
        ]:
            assert line_substr in r.output, (
                f"Expected {line_substr!r} in import output:\n{r.output}"
            )

    def test_reimport_shows_unchanged_for_customers_vendors(self, tmp_path):
        """Q-010: a no-diff re-import of customers/vendors reports 'unchanged',
        not 'updated'. ('updated' is reserved for re-imports that actually
        mutate something.)"""
        runner = CliRunner()
        gnc = tmp_path / "test.gnucash"
        r1 = _import_new(runner, gnc)
        assert r1.exit_code == 0

        r2 = _reimport(runner, gnc)
        assert r2.exit_code == 0, r2.output
        assert 'customer "1": unchanged' in r2.output, r2.output
        assert 'vendor "V001": unchanged' in r2.output, r2.output

    def test_reimport_shows_unchanged_for_invoice_bill_and_skipped_for_taxtable(self, tmp_path):
        """Q-010: invoices and bills are no longer permanently skipped on
        re-import; an identical re-import is 'unchanged'. Tax tables are
        the only kind that remains 'skipped' on hit (they're truly
        immutable because past posted invoices reference them by pointer)."""
        runner = CliRunner()
        gnc = tmp_path / "test.gnucash"
        r1 = _import_new(runner, gnc)
        assert r1.exit_code == 0

        r2 = _reimport(runner, gnc)
        assert r2.exit_code == 0, r2.output
        assert 'taxtable "GST": skipped' in r2.output, r2.output
        assert 'invoice "INV-2026-001": unchanged' in r2.output, r2.output
        assert 'bill "BILL-2026-001": unchanged' in r2.output, r2.output


# ── Aggregate summary ───────────────────────────────────────────────────────


class TestAggregateSummary:
    """Import summary includes a Business Objects section with counts."""

    def test_fresh_import_summary_counts(self, tmp_path):
        """Fresh import → all counts on the 'created' line, none on 'updated'
        or 'skipped'."""
        runner = CliRunner()
        gnc = tmp_path / "test.gnucash"
        r = _import_new(runner, gnc)
        assert r.exit_code == 0
        # Summary mentions a Business Objects section
        assert 'Business Objects' in r.output, r.output
        # Customers: 2 created in the fixture
        assert re.search(r'Customers:\s+2 created', r.output), (
            f"Expected 'Customers: 2 created' line; got:\n{r.output}"
        )
        # Vendors: 2 created
        assert re.search(r'Vendors:\s+2 created', r.output)
        # Tax tables: 1 created
        assert re.search(r'Tax tables:\s+1 created', r.output)
        # Invoices: 5 created
        assert re.search(r'Invoices:\s+5 created', r.output)
        # Bills: 5 created
        assert re.search(r'Bills:\s+5 created', r.output)

    def test_reimport_summary_counts(self, tmp_path):
        """Q-010: an identical re-import is 'unchanged' across the board for
        customers/vendors/invoices/bills (no field differs). Tax tables
        still report 'skipped' — they're immutable on hit so an identical
        re-import is the only safe outcome."""
        runner = CliRunner()
        gnc = tmp_path / "test.gnucash"
        r1 = _import_new(runner, gnc)
        assert r1.exit_code == 0

        r2 = _reimport(runner, gnc)
        assert r2.exit_code == 0, r2.output
        # Customers: 0 created, 0 updated, 2 unchanged, 0 skipped
        assert re.search(r'Customers:\s+0 created,\s*0 updated,\s*2 unchanged',
                         r2.output), r2.output
        # Vendors: 0 created, 0 updated, 2 unchanged, 0 skipped
        assert re.search(r'Vendors:\s+0 created,\s*0 updated,\s*2 unchanged',
                         r2.output), r2.output
        # Tax tables: 0 created, 0 updated, 0 unchanged, 1 skipped
        assert re.search(r'Tax tables:\s+0 created,.*1 skipped', r2.output)
        # Invoices: 0 created, 0 updated, 5 unchanged, 0 skipped (all 5 match)
        assert re.search(r'Invoices:\s+0 created,\s*0 updated,\s*5 unchanged',
                         r2.output), r2.output
        # Bills: 0 created, 0 updated, 5 unchanged, 0 skipped
        assert re.search(r'Bills:\s+0 created,\s*0 updated,\s*5 unchanged',
                         r2.output), r2.output

    def test_summary_appears_after_per_directive_lines(self, tmp_path):
        """Per-directive output comes first; aggregate summary at the end.

        Order matters for terminal UX — users see the activity stream as
        the import runs, and the summary is the final word."""
        runner = CliRunner()
        gnc = tmp_path / "test.gnucash"
        r = _import_new(runner, gnc)
        assert r.exit_code == 0

        idx_per_dir = r.output.find('customer "1": created')
        idx_summary = r.output.find('Business Objects')
        assert idx_per_dir != -1 and idx_summary != -1
        assert idx_per_dir < idx_summary, (
            f"Per-directive lines must come before the aggregate summary. "
            f"Got per-directive at {idx_per_dir}, summary at {idx_summary}."
        )
