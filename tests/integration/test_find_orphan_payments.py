"""
Q-014: integration tests for `find-orphan-payments`.

The command walks a book looking for payment-class bank transactions
whose AR/AP-side split's lot is no longer attached to any invoice/bill —
i.e. orphans left behind by a prior unpost. This is the after-the-fact
recovery path (the live unpost flow already warns via the
`unpost-invoices` / `unpost-bills` output).
"""

import os

import pytest
from click.testing import CliRunner

from cli.main import cli


def _fixture(name: str) -> str:
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


def _import_new(runner, gnc, fixture_path):
    return runner.invoke(cli, ["import", "--new", str(gnc), fixture_path,
                               "--include-business-objects"])


def _import(runner, gnc, fixture_path):
    return runner.invoke(cli, ["import", str(gnc), fixture_path,
                               "--include-business-objects"])


def _setup_book(runner, tmp_path, fixture_text):
    gnc = tmp_path / "book.gnucash"
    fix = _write(tmp_path / "in.txt", ACCOUNTS + "\n" + fixture_text)
    r = _import_new(runner, gnc, fix)
    assert r.exit_code == 0, r.output
    return gnc


def _make_orphan_invoice(runner, tmp_path, fixture_name, record_id, cmd):
    """Import a paid invoice/bill fixture, then unpost it via the CLI
    so the bank-side payment tx becomes orphaned. Returns the .gnucash path."""
    gnc = _setup_book(runner, tmp_path, _fixture(fixture_name))
    r = runner.invoke(cli, [cmd, str(gnc), record_id])
    assert r.exit_code == 0, r.output
    return gnc


class TestFindOrphanPayments:

    def test_clean_book_reports_no_orphans(self, tmp_path):
        """A freshly-imported posted+paid invoice has its payment attached
        to the invoice's lot — not orphaned. find-orphan-payments reports
        nothing and exits 0."""
        runner = CliRunner()
        gnc = _setup_book(runner, tmp_path, _fixture('q014_invoice_posted_paid'))

        r = runner.invoke(cli, ["find-orphan-payments", str(gnc)])
        assert r.exit_code == 0, r.output
        assert 'No orphan bank-side payment transactions found' in r.output, r.output

    def test_finds_one_invoice_orphan_after_unpost(self, tmp_path):
        """After `unpost-invoices INV-001`, the bank tx becomes orphaned.
        find-orphan-payments lists it with customer + GUID."""
        runner = CliRunner()
        gnc = _make_orphan_invoice(runner, tmp_path,
                                   'q014_invoice_posted_paid', 'INV-001',
                                   'unpost-invoices')

        r = runner.invoke(cli, ["find-orphan-payments", str(gnc)])
        assert r.exit_code == 0, r.output
        assert 'Found 1 orphan bank-side payment transaction' in r.output, r.output

        # Tx fields:
        assert '2026-01-15' in r.output
        assert 'Assets:Bank' in r.output
        assert 'CAD 100.00' in r.output
        assert '"Acme"' in r.output
        assert 'Payment INV-001' in r.output

        # Per-orphan "why classified as orphan" block must quote the
        # actual classifier evidence for THIS transaction (not a generic
        # paragraph) — the user should be able to audit the decision.
        assert 'why classified as orphan' in r.output, r.output
        # Criterion 1: txn-type is 'P'.
        assert "xaccTransGetTxnType(tx) == 'P'" in r.output, r.output
        # Criterion 2: KVP owner backref names this specific customer.
        assert 'gncOwnerGetOwnerFromTxn(tx) returned customer C001 (Acme)' in r.output, r.output
        # Criterion 3 + 4: AR-side on the AR account, lot detached.
        assert 'AR-side split is on Assets:Accounts Receivable' in r.output, r.output
        assert 'gncInvoiceGetInvoiceFromLot' in r.output, r.output
        assert 'invoice was unposted' in r.output, r.output

        # Total + cleanup-options summary:
        assert 'Total: CAD 100.00 in Assets:Bank' in r.output, r.output
        assert 'Cleanup options' in r.output
        assert 'delete-transactions --by-guid' in r.output
        assert 'txn_guid' in r.output

    def test_finds_bill_orphan_with_vendor_backref(self, tmp_path):
        """Mirror for the bill side — vendor backref instead of customer."""
        runner = CliRunner()
        gnc = _make_orphan_invoice(runner, tmp_path,
                                   'q014_bill_posted_paid', 'BILL-001',
                                   'unpost-bills')

        r = runner.invoke(cli, ["find-orphan-payments", str(gnc)])
        assert r.exit_code == 0, r.output
        assert 'Found 1 orphan bank-side payment transaction' in r.output, r.output
        assert 'CAD 50.00' in r.output
        # Bill side: vendor backref + AP-side wording.
        assert 'gncOwnerGetOwnerFromTxn(tx) returned vendor V001 (Supplier)' in r.output, r.output
        assert 'AP-side split is on Liabilities:Accounts Payable' in r.output, r.output
        assert 'bill was unposted' in r.output, r.output

    def test_customer_filter_narrows_results(self, tmp_path):
        """--customer scopes to that customer's orphans only."""
        runner = CliRunner()
        gnc = _make_orphan_invoice(runner, tmp_path,
                                   'q014_invoice_posted_paid', 'INV-001',
                                   'unpost-invoices')

        # Hit: actual customer.
        r = runner.invoke(cli, ["find-orphan-payments", str(gnc),
                                "--customer", "C001"])
        assert r.exit_code == 0, r.output
        assert 'Found 1 orphan bank-side payment transaction' in r.output

        # Miss: customer with no orphans.
        r = runner.invoke(cli, ["find-orphan-payments", str(gnc),
                                "--customer", "C999"])
        assert r.exit_code == 0, r.output
        assert 'No orphan bank-side payment transactions found' in r.output
        assert 'for customer C999' in r.output

    def test_normal_bank_tx_is_not_classified_as_orphan(self, tmp_path):
        """Manual bank txs (deposits, transfers — not created via
        `gncOwnerApplyPayment`) have `xaccTransGetTxnType == 'N'`, which
        fails criterion 1 of the orphan classifier. A book consisting of
        only such transactions should report zero orphans.

        Boundary test: confirms that the classifier doesn't false-positive
        on the most common type of non-payment transaction (the kind a
        bank-statement importer or hand entry creates)."""
        runner = CliRunner()
        gnc = tmp_path / "book.gnucash"
        # No invoice or bill — just an accounts file plus one manual bank
        # tx between Bank and Income.
        manual_tx = """
2026-02-01 * "Interest received"
\tAssets:Bank 25.00 CAD
\tIncome -25.00 CAD
"""
        fix = _write(tmp_path / "in.txt", ACCOUNTS + manual_tx)
        r = _import_new(runner, gnc, fix)
        assert r.exit_code == 0, r.output

        r = runner.invoke(cli, ["find-orphan-payments", str(gnc)])
        assert r.exit_code == 0, r.output
        assert 'No orphan bank-side payment transactions found' in r.output, r.output

    def test_mix_of_orphan_attached_payment_and_manual_tx(self, tmp_path):
        """The classifier must report ONLY the orphan in a book that also
        contains (a) a still-attached payment and (b) a manual bank tx.
        This exercises all three classification outcomes in one book:
          - orphan payment (txn_type=P, lot detached) → reported
          - still-attached payment (txn_type=P, lot has invoice) → NOT reported
          - manual deposit (txn_type=N) → NOT reported"""
        runner = CliRunner()

        # Step 1: book starts with INV-PAID (will stay paid + attached) plus
        # INV-ORPHAN (will be paid then unposted).
        paid_fixture = _fixture('q014_invoice_posted_paid').replace(
            'INV-001', 'INV-PAID')
        gnc = _setup_book(runner, tmp_path, paid_fixture)

        # Add a second invoice, also paid (will become the orphan).
        orphan_fixture = _fixture('q014_invoice_posted_paid').replace(
            'INV-001', 'INV-ORPHAN')
        r = _import(runner, gnc, _write(tmp_path / "orphan.txt",
                                        ACCOUNTS + "\n" + orphan_fixture))
        assert r.exit_code == 0, r.output

        # Add a manual bank tx (txn_type='N').
        manual_tx = """
2026-02-01 * "Manual deposit"
\tAssets:Bank 999.00 CAD
\tIncome -999.00 CAD
"""
        r = _import(runner, gnc, _write(tmp_path / "manual.txt", manual_tx))
        assert r.exit_code == 0, r.output

        # Unpost INV-ORPHAN (but NOT INV-PAID).
        r = runner.invoke(cli, ["unpost-invoices", str(gnc), "INV-ORPHAN"])
        assert r.exit_code == 0, r.output

        # The classifier must find exactly the one orphan, not 2 or 3.
        r = runner.invoke(cli, ["find-orphan-payments", str(gnc)])
        assert r.exit_code == 0, r.output
        assert 'Found 1 orphan bank-side payment transaction' in r.output, (
            f"Expected exactly 1 orphan (INV-ORPHAN's payment). The manual tx "
            f"and the still-attached INV-PAID payment must NOT be classified "
            f"as orphans. Got:\n{r.output}")
        # No accidental sweep of the manual tx:
        assert '999.00' not in r.output, (
            f"Manual bank tx (CAD 999.00) must not appear in the orphan list. "
            f"Got:\n{r.output}")

    def test_orphan_classification_survives_plaintext_roundtrip(self, tmp_path):
        """Detection must work after export → re-import into a fresh book.

        Without the plaintext format carrying `txn_type:`, the orphan bank
        tx loses its `'P'` classification on the way through the .txt file
        (the importer's default is `'N'`). Criterion 1 of the classifier
        then fails on the restored book and the orphan is invisible.

        With `txn_type:` round-tripping, the orphan is detectable in both
        the original and the restored book."""
        runner = CliRunner()

        # 1. Original book: posted → paid → unposted invoice (orphan exists).
        gnc = _make_orphan_invoice(runner, tmp_path,
                                   'q014_invoice_posted_paid', 'INV-001',
                                   'unpost-invoices')
        r = runner.invoke(cli, ["find-orphan-payments", str(gnc)])
        assert r.exit_code == 0, r.output
        assert 'Found 1 orphan bank-side payment transaction' in r.output, (
            f"Setup: orphan must be detectable in the original book. "
            f"Got:\n{r.output}")

        # 2. Export the full book to plaintext (transactions + business
        #    objects). The orphan bank tx lives in the `transactions:`
        #    section since it's no longer attached to any invoice.
        #
        # `--all-accounts` is required here because the post-unpost book
        # has no transactions touching Income:Sales — the AR posting tx
        # was destroyed, the payment tx touches only Bank+AR. The
        # exporter's default policy emits only accounts referenced by
        # transactions in the result set, so without --all-accounts the
        # invoice entry's `account: "Income:Sales"` would dangle on
        # re-import. (This is the pre-existing exporter gap flagged in
        # docs/research/2026-05-14-...md's "Implications for the
        # codebase" section.)
        exported = tmp_path / "exported.txt"
        r = runner.invoke(cli, ["export", str(gnc), str(exported),
                                "--include-business-objects",
                                "--all-accounts"])
        assert r.exit_code == 0, r.output
        text = exported.read_text()
        # The export must carry the orphan's txn_type so the importer can
        # restore the 'P' classification.
        assert 'txn_type: P' in text, (
            f"Export must emit `txn_type: P` for the orphan payment tx. "
            f"Without it the roundtrip silently demotes the tx to 'N' and "
            f"find-orphan-payments goes blind. Export:\n{text}")
        assert 'owner: customer:C001' in text, (
            f"Export must emit `owner: customer:C001` so the importer can "
            f"restore the gncOwner KVP on the tx (criterion 2 of the "
            f"classifier). Export:\n{text}")

        # 3. Re-import the plaintext into a fresh book.
        fresh = tmp_path / "fresh.gnucash"
        r = runner.invoke(cli, ["import", "--new", str(fresh), str(exported),
                                "--include-business-objects"])
        assert r.exit_code == 0, r.output

        # 4. The classifier must still find the orphan on the restored
        # book. Detection now reads `txn_type: P` and `owner: customer:C001`
        # from the custom-KVP slots the importer preserved (since
        # `xaccTransSetTxnType` and `gncOwnerCopyOnTxn` are no-ops from
        # Python on GnuCash 4.9+/5.x — the type is a heuristic derived
        # from splits + lots, neither of which round-trip).
        r = runner.invoke(cli, ["find-orphan-payments", str(fresh)])
        assert r.exit_code == 0, r.output
        assert 'Found 1 orphan bank-side payment transaction' in r.output, (
            f"Q-014 roundtrip regression: orphan must remain classifiable "
            f"after export+re-import. find-orphan-payments output:\n{r.output}")

    def test_lists_multiple_orphans_with_per_account_total(self, tmp_path):
        """Two paid invoices, both unposted → two orphan bank txs, total
        rolled up by account."""
        runner = CliRunner()
        # First invoice (INV-001), paid in full ($100).
        gnc = _setup_book(runner, tmp_path, _fixture('q014_invoice_posted_paid'))

        # Second invoice (INV-002) posted+paid, then unpost both.
        fixture_002 = _fixture('q014_invoice_posted_paid').replace(
            'INV-001', 'INV-002')
        r = _import(runner, gnc, _write(tmp_path / "inv2.txt",
                                        ACCOUNTS + "\n" + fixture_002))
        assert r.exit_code == 0, r.output

        for inv_id in ('INV-001', 'INV-002'):
            r = runner.invoke(cli, ["unpost-invoices", str(gnc), inv_id])
            assert r.exit_code == 0, r.output

        r = runner.invoke(cli, ["find-orphan-payments", str(gnc)])
        assert r.exit_code == 0, r.output
        assert 'Found 2 orphan bank-side payment transactions' in r.output, r.output
        assert 'Total: CAD 200.00 in Assets:Bank' in r.output, r.output
