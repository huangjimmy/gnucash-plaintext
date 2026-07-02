"""
Q-013: `delete-invoices` / `delete-bills` CLI commands.

Mirrors the structure of test_unpost_invoice_bill.py (Q-010). The
commands hard-delete unposted invoices/bills via `Invoice.Destroy()`
and refuse posted records. The two-step path to delete a posted
record is `unpost-invoices <id>` followed by `delete-invoices <id>`
— never an auto-unpost-then-delete inside one command (see Q-013
issue doc for the reasoning).

Test coverage:

  - delete an unposted invoice → exit 0, record gone on reload
  - delete an unposted bill   → exit 0, record gone on reload
  - delete a posted invoice   → exit 1, FAILED_POSTED message, record still there
  - delete a posted bill      → exit 1, FAILED_POSTED message, record still there
  - delete a missing id       → exit 1, NOT_FOUND
  - --by-guid happy path
  - --by-guid bad guid format
  - batch: some succeed, some fail → exit 1; successes still persist on disk
  - multi-entry invoice can be deleted without segfault (entry-cleanup
    check — see CLAUDE.md hard-won finding #8; Q-013 destroys the
    parent so the dangling-pointer hazard shouldn't apply, but the
    test exists to catch the regression if it does)
"""

import os

import pytest
from click.testing import CliRunner

from cli.main import cli


def _fixture(name: str) -> str:
    path = os.path.join(os.path.dirname(__file__), '..', 'fixtures',
                        f'{name}.txt')
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


def _setup_book_with(runner, tmp_path, fixture_text):
    gnc = tmp_path / "book.gnucash"
    fix = _write(tmp_path / "in.txt", ACCOUNTS + "\n" + fixture_text)
    r = _import_new(runner, gnc, fix)
    assert r.exit_code == 0, r.output
    # GnuCash backup filenames use a per-second timestamp. Without a
    # pause, the next save in the same test would collide with the
    # import's backup timestamp and fail with ERR_FILEIO_BACKUP_ERROR.
    # The CLI's save handler swallows that specific error (so the
    # surrounding command still exits 0), which silently drops the
    # save — leaving the in-memory delete invisible on reload. Same
    # workaround the Q-010 unpost test uses.
    return gnc


def _record_ids_after_reload(gnc, search_for, owner_type_int):
    """Return the list of ids for invoices (owner_type=2) or bills
    (owner_type=4) in the saved .gnucash file. Used to assert that a
    deletion truly survived save+reload, not just an in-memory mutation."""
    from gnucash import Query, Session
    from gnucash.gnucash_business import Invoice
    ses = Session(f"xml://{gnc}")
    try:
        book = ses.book
        q = Query()
        q.search_for(search_for)
        q.set_book(book)
        ids = []
        for r in q.run():
            inv = Invoice(instance=r)
            if inv.GetOwnerType() == owner_type_int:
                ids.append(inv.GetID())
        q.destroy()
        return sorted(ids)
    finally:
        ses.end()


def _invoice_ids(gnc):
    return _record_ids_after_reload(gnc, 'gncInvoice', owner_type_int=2)


def _bill_ids(gnc):
    return _record_ids_after_reload(gnc, 'gncInvoice', owner_type_int=4)


def _taxtable_names(gnc):
    """Return the names of all tax tables in `gnc`.

    Tax tables aren't reachable via QofQuery (CLAUDE.md finding #3),
    so we call the same `_iter_taxtables` / `_taxtable_name_str`
    helpers the importer uses."""
    from gnucash import Session

    from services.gnucash_importer import _iter_taxtables, _taxtable_name_str
    ses = Session(f"xml://{gnc}")
    try:
        book = ses.book
        return sorted(_taxtable_name_str(p) for p in _iter_taxtables(book))
    finally:
        ses.end()


def _create_duplicate_invoice(gnc, dup_id, customer_id, currency_code):
    """Create a second invoice in `gnc` whose id already exists.

    The importer enforces id uniqueness (Q-006 / Q-008), so the only
    way to produce the legacy-data scenario the AMBIGUOUS_ID path
    guards against is to bypass the importer and call the GnuCash
    SWIG constructor directly. After this returns there are two
    distinct gncInvoice records with the same id.
    """
    from gnucash import Session
    from gnucash.gnucash_business import Invoice
    ses = Session(f"xml://{gnc}")
    try:
        book = ses.book
        cust = book.CustomerLookupByID(customer_id)
        assert cust is not None, (
            f"Setup: customer {customer_id!r} must already exist in {gnc}")
        currency = book.get_table().lookup("CURRENCY", currency_code)
        # Invoice(book, id, currency, owner) creates a new gncInvoice
        # under `book` with the given id. No uniqueness check is done
        # at the C level — that's only enforced by our importer.
        Invoice(book, dup_id, currency, cust)
        ses.save()
    finally:
        ses.end()


def _invoice_guid(gnc, inv_id):
    """Look up the GUID of an invoice/bill by id (works for both — same
    underlying gncInvoice type, differentiated by owner type).

    Uses `_swig_invoice_guid_str` rather than SWIG `Invoice.GetGUID()`
    because the latter raises AttributeError on debian13 / ubuntu24
    (per CLAUDE.md hard-won finding)."""
    from gnucash import Query, Session
    from gnucash.gnucash_business import Invoice

    from services.gnucash_importer import _swig_invoice_guid_str
    ses = Session(f"xml://{gnc}")
    try:
        book = ses.book
        q = Query()
        q.search_for('gncInvoice')
        q.set_book(book)
        guid = None
        for r in q.run():
            inv = Invoice(instance=r)
            if inv.GetID() == inv_id:
                guid = _swig_invoice_guid_str(inv)
                break
        q.destroy()
        return guid
    finally:
        ses.end()


# ── delete-invoices happy path ────────────────────────────────────────────────


class TestDeleteUnpostedInvoice:
    def test_single_unposted_invoice_deleted_and_persists(self, tmp_path):
        runner = CliRunner()
        gnc = _setup_book_with(runner, tmp_path, _fixture('q010_invoice_unposted'))
        assert _invoice_ids(gnc) == ['INV-001'], (
            "Setup: expected one unposted invoice INV-001")

        r = runner.invoke(cli, ["delete-invoices", str(gnc), "INV-001"])
        assert r.exit_code == 0, r.output
        assert 'INV-001' in r.output and ': deleted' in r.output, r.output

        # Reload from disk to confirm save persisted the deletion.
        assert _invoice_ids(gnc) == [], (
            f"INV-001 should be gone after delete+reload. Still present: "
            f"{_invoice_ids(gnc)}")

    def test_multi_entry_invoice_deleted_without_segfault(self, tmp_path):
        """Q-013 regression guard: CLAUDE.md finding #8 documents a
        dangling-pointer hazard when destroying entries one-by-one
        while the parent invoice stays alive. We destroy the parent,
        so the hazard should not apply — but if any GnuCash version
        crashes here we want a directly-named test pointing at it."""
        runner = CliRunner()
        gnc = _setup_book_with(runner, tmp_path,
                               _fixture('q013_invoice_unposted_multi_entry'))
        assert _invoice_ids(gnc) == ['INV-001']

        r = runner.invoke(cli, ["delete-invoices", str(gnc), "INV-001"])
        assert r.exit_code == 0, r.output
        assert _invoice_ids(gnc) == []

    def test_by_guid_path(self, tmp_path):
        runner = CliRunner()
        gnc = _setup_book_with(runner, tmp_path, _fixture('q010_invoice_unposted'))
        guid = _invoice_guid(gnc, 'INV-001')
        assert guid, "Setup: failed to read GUID for INV-001"
        # Strip hyphens to test the normalisation path (matches Q-007 fix).
        guid_no_hyphens = guid.replace('-', '')

        r = runner.invoke(cli, ["delete-invoices", str(gnc),
                                "--by-guid", guid_no_hyphens])
        assert r.exit_code == 0, r.output
        assert ': deleted' in r.output, r.output
        assert _invoice_ids(gnc) == []

    def test_by_guid_format_error(self, tmp_path):
        runner = CliRunner()
        gnc = _setup_book_with(runner, tmp_path, _fixture('q010_invoice_unposted'))

        r = runner.invoke(cli, ["delete-invoices", str(gnc),
                                "--by-guid", "not-a-guid"])
        assert r.exit_code != 0
        assert _invoice_ids(gnc) == ['INV-001'], (
            "Malformed guid must not touch the book")

    def test_deletion_does_not_destroy_referenced_tax_table(self, tmp_path):
        """Correctness guard: tax tables are book-level shared objects
        that may be referenced by many invoices. Destroying an invoice
        with a `tax_table: "GST"` entry must NOT cascade into deleting
        the GST tax table itself — that would silently break every
        other invoice still using it.

        The Q-013 use case only destroys entries (which clears each
        entry's tax_table back-pointer) and the parent invoice. Tax
        tables stay put. This test asserts that invariant explicitly."""
        runner = CliRunner()
        gnc = _setup_book_with(runner, tmp_path,
                               _fixture('q013_invoice_unposted_with_tax'))
        assert _invoice_ids(gnc) == ['INV-001']
        assert _taxtable_names(gnc) == ['GST'], (
            "Setup: GST tax table should exist after import")

        r = runner.invoke(cli, ["delete-invoices", str(gnc), "INV-001"])
        assert r.exit_code == 0, r.output
        assert _invoice_ids(gnc) == [], "Invoice should be gone"
        assert _taxtable_names(gnc) == ['GST'], (
            "GST tax table must survive invoice deletion — tax tables "
            "are book-level shared objects, not invoice-owned. "
            f"Found tax tables after delete: {_taxtable_names(gnc)}")


# ── delete-bills happy path ───────────────────────────────────────────────────


class TestDeleteUnpostedBill:
    def test_single_unposted_bill_deleted_and_persists(self, tmp_path):
        runner = CliRunner()
        gnc = _setup_book_with(runner, tmp_path, _fixture('q010_bill_unposted'))
        assert _bill_ids(gnc) == ['BILL-001']

        r = runner.invoke(cli, ["delete-bills", str(gnc), "BILL-001"])
        assert r.exit_code == 0, r.output
        assert 'BILL-001' in r.output and ': deleted' in r.output, r.output
        assert _bill_ids(gnc) == []


# ── refusal: posted records ───────────────────────────────────────────────────


class TestPostedRefused:
    def test_posted_invoice_not_deleted(self, tmp_path):
        """`delete-invoices` must refuse a posted invoice and leave the
        record in place. The error message must steer the user toward
        the explicit two-step path: unpost-invoices, then delete-invoices."""
        runner = CliRunner()
        gnc = _setup_book_with(runner, tmp_path, _fixture('q010_invoice_posted'))
        assert _invoice_ids(gnc) == ['INV-001']

        r = runner.invoke(cli, ["delete-invoices", str(gnc), "INV-001"])
        assert r.exit_code == 1, (
            f"Posted invoice deletion must fail with exit 1. Output:\n{r.output}")
        assert 'failed — posted' in r.output, r.output
        assert 'unpost-invoices' in r.output, (
            "Failure message must point at unpost-invoices as the next step. "
            f"Output:\n{r.output}")
        # Record still present on disk:
        assert _invoice_ids(gnc) == ['INV-001']

    def test_posted_bill_not_deleted(self, tmp_path):
        runner = CliRunner()
        gnc = _setup_book_with(runner, tmp_path, _fixture('q010_bill_posted'))
        assert _bill_ids(gnc) == ['BILL-001']

        r = runner.invoke(cli, ["delete-bills", str(gnc), "BILL-001"])
        assert r.exit_code == 1, r.output
        assert 'failed — posted' in r.output, r.output
        assert 'unpost-bills' in r.output, r.output
        assert _bill_ids(gnc) == ['BILL-001']


# ── miss path ─────────────────────────────────────────────────────────────────


class TestNotFound:
    def test_unknown_invoice_id(self, tmp_path):
        runner = CliRunner()
        gnc = _setup_book_with(runner, tmp_path, _fixture('q010_invoice_unposted'))

        r = runner.invoke(cli, ["delete-invoices", str(gnc), "INV-DOES-NOT-EXIST"])
        assert r.exit_code == 1, r.output
        assert 'not found' in r.output, r.output
        # Real invoice untouched
        assert _invoice_ids(gnc) == ['INV-001']

    def test_unknown_bill_id(self, tmp_path):
        runner = CliRunner()
        gnc = _setup_book_with(runner, tmp_path, _fixture('q010_bill_unposted'))

        r = runner.invoke(cli, ["delete-bills", str(gnc), "BILL-MISSING"])
        assert r.exit_code == 1, r.output
        assert 'not found' in r.output, r.output
        assert _bill_ids(gnc) == ['BILL-001']


# ── batch behaviour ───────────────────────────────────────────────────────────


class TestAmbiguousId:
    """Legacy data may contain multiple invoices/bills sharing the
    same user-facing id (the importer enforces uniqueness from
    Q-008 onwards, but pre-Q-008 books or hand-edited XML can have
    them). The use case must refuse to pick one — it returns
    AMBIGUOUS_ID with a message steering the user toward --by-guid,
    and touches neither record.

    Mirrors the AMBIGUOUS_ID path in unpost-business-objects."""

    def test_duplicate_id_refused_and_no_record_deleted(self, tmp_path):
        runner = CliRunner()
        gnc = _setup_book_with(runner, tmp_path, _fixture('q010_invoice_unposted'))
        # Bypass the importer to create a second invoice with the
        # same id — the only way to reproduce legacy duplicates.
        _create_duplicate_invoice(gnc, dup_id="INV-001",
                                  customer_id="C001",
                                  currency_code="CAD")
        ids_before = _invoice_ids(gnc)
        assert ids_before == ['INV-001', 'INV-001'], (
            f"Setup: should have two invoices both named INV-001; got {ids_before}")

        r = runner.invoke(cli, ["delete-invoices", str(gnc), "INV-001"])
        assert r.exit_code == 1, (
            f"Ambiguous id must exit 1, not silently pick one. Output:\n{r.output}")
        assert 'multiple records share this id' in r.output, r.output
        assert '--by-guid' in r.output, (
            "Failure message must point at --by-guid as the disambiguator. "
            f"Output:\n{r.output}")
        # Neither record was deleted:
        assert _invoice_ids(gnc) == ['INV-001', 'INV-001'], (
            f"Ambiguous case must not delete either record. After: "
            f"{_invoice_ids(gnc)}")


class TestBatchPartialSuccess:
    """Per the established `_run_delete` / `_run_unpost` pattern: when
    a batch contains a mix of successes and failures, the successful
    deletes must still be saved to disk and the overall exit code must
    be 1. Lifting the saved-deletions would force users to debug-and-
    rerun the whole batch."""

    def test_one_success_one_failure_persists_success_and_exits_1(self, tmp_path):
        runner = CliRunner()
        gnc = _setup_book_with(runner, tmp_path,
                               _fixture('q013_two_unposted_invoices'))
        assert _invoice_ids(gnc) == ['INV-001', 'INV-002']

        # INV-001 exists (unposted) → should delete.
        # INV-NOPE doesn't exist → should fail.
        r = runner.invoke(cli, ["delete-invoices", str(gnc),
                                "INV-001", "INV-NOPE"])
        assert r.exit_code == 1, r.output
        assert 'INV-001' in r.output and ': deleted' in r.output, r.output
        assert 'INV-NOPE' in r.output and 'not found' in r.output, r.output

        # The successful deletion must have persisted:
        assert _invoice_ids(gnc) == ['INV-002'], (
            f"INV-001 should be deleted, INV-002 should remain. "
            f"Got: {_invoice_ids(gnc)}")
