"""
Tests for payment transaction round-trip correctness (Q-003, Q-004).

BUG A — Account type round-trip:
  Exporter writes GnuCash internal type names (A/Receivable, A/Payable).
  Importer must accept both canonical and internal forms.

BUG B — Bank-first duplicate:
  When a bank feed transaction already exists and an invoice with a
  payment: block is imported, ApplyPayment() must NOT create a second
  bank entry.  The correct fix uses txn_guid to retarget the pre-existing
  transaction's counter-split in-place.

BUG C — Same-day same-amount idempotency:
  Re-importing the same invoice file must not duplicate payment transactions.

Fixture files used:
  tests/fixtures/payment_roundtrip_accounts.txt      — account hierarchy
  tests/fixtures/payment_roundtrip_bank_invoice.txt  — bank tx (invoice side)
  tests/fixtures/payment_roundtrip_bank_bill.txt     — bank tx (bill side)
  tests/fixtures/payment_roundtrip_invoice_txn_guid.txt — invoice template
  tests/fixtures/payment_roundtrip_bill_txn_guid.txt    — bill template
"""

import os
import tempfile
import time

from click.testing import CliRunner

from cli.main import cli

FIXTURES = "tests/fixtures"
ACCOUNTS      = f"{FIXTURES}/payment_roundtrip_accounts.txt"
BANK_INVOICE  = f"{FIXTURES}/payment_roundtrip_bank_invoice.txt"
BANK_BILL     = f"{FIXTURES}/payment_roundtrip_bank_bill.txt"
INV_TEMPLATE  = f"{FIXTURES}/payment_roundtrip_invoice_txn_guid.txt"
BILL_TEMPLATE = f"{FIXTURES}/payment_roundtrip_bill_txn_guid.txt"

# Business objects with payments (no txn_guid) — for round-trip and same-day tests
SINGLE_PAID_INVOICE = """\
customer "C1"
  name: "Acme"
  currency: CAD

invoice "INV-001"
  customer_id: "C1"
  currency: CAD
  date_opened: 2026-01-01
  entry:
    date: 2026-01-01
    description: "Service"
    action: "Hours"
    account: "Income:Sales"
    quantity: 1
    price: 100
    taxable: false
    tax_included: false
  posted:
    date: 2026-01-01
    due: 2026-01-31
    ar_account: "Assets:Accounts Receivable"
    memo: "Invoice INV-001"
    accumulate: true
  payment:
    date: 2026-01-15
    amount: 100
    bank_account: "Assets:Bank"
    memo: "Payment INV-001"
"""

TWO_SAME_DAY_INVOICES = """\
customer "C1"
  name: "Acme"
  currency: CAD

invoice "INV-A"
  customer_id: "C1"
  currency: CAD
  date_opened: 2026-01-01
  entry:
    date: 2026-01-01
    description: "Service A"
    action: "Hours"
    account: "Income:Sales"
    quantity: 1
    price: 100
    taxable: false
    tax_included: false
  posted:
    date: 2026-01-01
    due: 2026-01-31
    ar_account: "Assets:Accounts Receivable"
    memo: "Invoice INV-A"
    accumulate: true
  payment:
    date: 2026-01-15
    amount: 100
    bank_account: "Assets:Bank"
    memo: "Payment INV-A"

invoice "INV-B"
  customer_id: "C1"
  currency: CAD
  date_opened: 2026-01-02
  entry:
    date: 2026-01-02
    description: "Service B"
    action: "Hours"
    account: "Income:Sales"
    quantity: 1
    price: 100
    taxable: false
    tax_included: false
  posted:
    date: 2026-01-02
    due: 2026-01-31
    ar_account: "Assets:Accounts Receivable"
    memo: "Invoice INV-B"
    accumulate: true
  payment:
    date: 2026-01-15
    amount: 100
    bank_account: "Assets:Bank"
    memo: "Payment INV-B"
"""


# ── helpers ──────────────────────────────────────────────────────────────────

def accounts_plus(extra_fixture_path):
    """Concatenate the base accounts file with another fixture file."""
    with open(ACCOUNTS) as a, open(extra_fixture_path) as b:
        return a.read() + "\n" + b.read()


def accounts_plus_text(text):
    """Concatenate the base accounts file with inline text."""
    with open(ACCOUNTS) as a:
        return a.read() + "\n" + text


def invoice_fixture(txn_guid):
    """Return invoice fixture content with txn_guid substituted."""
    with open(INV_TEMPLATE) as f:
        return f.read().format(txn_guid=txn_guid)


def bill_fixture(txn_guid):
    """Return bill fixture content with txn_guid substituted."""
    with open(BILL_TEMPLATE) as f:
        return f.read().format(txn_guid=txn_guid)


def write_fixture(tmp_path, name, content):
    p = tmp_path / name
    p.write_text(content)
    return str(p)


def import_new(runner, gf, fixture_path, biz=False):
    args = ["import", "--new", str(gf), fixture_path]
    if biz:
        args.append("--include-business-objects")
    r = runner.invoke(cli, args)
    assert r.exit_code == 0, f"import --new failed:\n{r.output}"
    time.sleep(1)  # avoid GnuCash backup timestamp collision on subsequent save
    return r


def import_into(runner, gf, fixture_path, biz=True):
    args = ["import", str(gf), fixture_path]
    if biz:
        args.append("--include-business-objects")
    return runner.invoke(cli, args)


def get_guid(runner, gf, account, date="2026-01-15"):
    r = runner.invoke(cli, ["find-transactions", str(gf),
                            "--account", account, "--date", date])
    assert r.exit_code == 0, f"find-transactions failed:\n{r.output}"
    lines = [line for line in r.output.strip().splitlines() if line]
    assert lines, f"No transactions found for {account} on {date}"
    return lines[0].split()[0]


def bank_tx_count(runner, gf, tmp_path):
    """Count unique transactions touching Assets:Bank via export."""
    fd, out = tempfile.mkstemp(suffix=".txt")
    os.close(fd)
    try:
        r = runner.invoke(cli, ["export", str(gf), out])
        assert r.exit_code == 0, f"export failed:\n{r.output}"
        with open(out) as f:
            content = f.read()
    finally:
        os.unlink(out)

    count = 0
    in_tx = has_bank = False
    for line in content.splitlines():
        if line and line[0:1] not in (' ', '\t'):
            if in_tx and has_bank:
                count += 1
            in_tx = line[0].isdigit()
            has_bank = False
        elif in_tx and 'Assets:Bank' in line:
            has_bank = True
    if in_tx and has_bank:
        count += 1
    return count


def export_text(runner, gf):
    fd, out = tempfile.mkstemp(suffix=".txt")
    os.close(fd)
    try:
        runner.invoke(cli, ["export", str(gf), out])
        return open(out).read()
    finally:
        os.unlink(out)


# ─────────────────────────────────────────────────────────────────────────────
# BUG A: account type round-trip
# ─────────────────────────────────────────────────────────────────────────────

def test_account_type_roundtrip(tmp_path):
    """Export writes A/Receivable; re-import must not crash on that type."""
    runner = CliRunner()
    gf1 = tmp_path / "first.gnucash"
    fixture = write_fixture(tmp_path, "full.txt",
                            accounts_plus_text(SINGLE_PAID_INVOICE))
    import_new(runner, gf1, fixture, biz=True)

    exported = tmp_path / "exported.txt"
    r = runner.invoke(cli, ["export", str(gf1), str(exported),
                            "--include-business-objects"])
    assert r.exit_code == 0, f"Export failed:\n{r.output}"

    gf2 = tmp_path / "second.gnucash"
    r = runner.invoke(cli, ["import", "--new", str(gf2), str(exported),
                            "--include-business-objects"])
    assert r.exit_code == 0, (
        f"BUG A: re-import of exported file failed — "
        f"account types not round-tripping:\n{r.output}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# BUG B: txn_guid — retarget existing bank transaction to invoice lot
# ─────────────────────────────────────────────────────────────────────────────

def test_bank_first_then_invoice_with_txn_guid(tmp_path):
    """
    Happy path: bank tx imported first, invoice imported with txn_guid.
    The counter-split is retargeted to AR and linked to the lot in-place.
    Original bank metadata (notes, description, split memo) must survive.
    """
    runner = CliRunner()
    gf = tmp_path / "book.gnucash"
    import_new(runner, gf, write_fixture(tmp_path, "bank.txt",
                                         accounts_plus(BANK_INVOICE)))

    assert bank_tx_count(runner, gf, tmp_path) == 1

    guid = get_guid(runner, gf, "Assets:Bank")
    invoice_file = write_fixture(tmp_path, "invoice.txt", invoice_fixture(guid))

    r = import_into(runner, gf, invoice_file)
    assert r.exit_code == 0, f"Invoice import failed:\n{r.output}"
    assert bank_tx_count(runner, gf, tmp_path) == 1, \
        "txn_guid retarget must not create a second bank transaction"

    exported = export_text(runner, gf)
    assert "E-transfer from Acme" in exported, \
        "Original bank tx description must be preserved"
    assert "fitid:20260115001" in exported, \
        "Original bank tx notes (fitid) must be preserved"
    assert "QFX split memo to preserve" in exported, \
        "Original bank split memo must be preserved"


def test_bank_first_then_invoice_no_duplicate(tmp_path):
    """Without txn_guid, ApplyPayment() creates a duplicate (known behaviour)."""
    runner = CliRunner()
    gf = tmp_path / "book.gnucash"
    import_new(runner, gf, write_fixture(tmp_path, "bank.txt",
                                         accounts_plus(BANK_INVOICE)))
    invoice_file = write_fixture(tmp_path, "invoice.txt",
                                 accounts_plus_text(SINGLE_PAID_INVOICE))
    import_into(runner, gf, invoice_file)
    assert bank_tx_count(runner, gf, tmp_path) == 2, \
        "Without txn_guid, expected 2 bank transactions (known duplicate)"


# ── error branches ────────────────────────────────────────────────────────────

def test_txn_guid_on_unposted_invoice_fails(tmp_path):
    """payment: block with txn_guid on posted: none invoice must fail clearly."""
    runner = CliRunner()
    gf = tmp_path / "book.gnucash"
    import_new(runner, gf, write_fixture(tmp_path, "bank.txt",
                                         accounts_plus(BANK_INVOICE)))
    guid = get_guid(runner, gf, "Assets:Bank")

    unposted = write_fixture(tmp_path, "inv.txt",
        accounts_plus_text(
            'customer "C1"\n  name: "Acme"\n  currency: CAD\n\n'
            'invoice "INV-UNPOSTED"\n'
            '  customer_id: "C1"\n  currency: CAD\n  date_opened: 2026-01-01\n'
            '  entry:\n    date: 2026-01-01\n    description: "Service"\n'
            '    action: "Hours"\n    account: "Income:Sales"\n'
            '    quantity: 1\n    price: 100\n    taxable: false\n    tax_included: false\n'
            '  posted: none\n'
            '  payment:\n'
            '    bank_account: "Assets:Bank"\n'
            f'    txn_guid: {guid}\n'
        )
    )
    r = import_into(runner, gf, unposted)
    assert r.exit_code != 0
    assert "posted" in r.output.lower() or "lot" in r.output.lower(), \
        f"Error must mention posting/lot. Got:\n{r.output}"


def test_txn_guid_not_found_fails(tmp_path):
    """txn_guid referencing a non-existent GUID must fail clearly."""
    runner = CliRunner()
    gf = tmp_path / "book.gnucash"
    import_new(runner, gf, write_fixture(tmp_path, "bank.txt",
                                         accounts_plus(BANK_INVOICE)))

    bad_guid_file = write_fixture(tmp_path, "inv.txt",
                                  invoice_fixture("deadbeefdeadbeefdeadbeefdeadbeef"))
    r = import_into(runner, gf, bad_guid_file)
    assert r.exit_code != 0
    assert "not found" in r.output.lower(), \
        f"Error must mention 'not found'. Got:\n{r.output}"


def test_txn_guid_invalid_format_fails(tmp_path):
    """txn_guid that is not a valid GUID/UUID string must fail with a format error."""
    runner = CliRunner()
    gf = tmp_path / "book.gnucash"
    import_new(runner, gf, write_fixture(tmp_path, "bank.txt",
                                         accounts_plus(BANK_INVOICE)))

    bad_fmt_file = write_fixture(tmp_path, "inv.txt", invoice_fixture("hello"))
    r = import_into(runner, gf, bad_fmt_file)
    assert r.exit_code != 0
    assert "invalid guid" in r.output.lower(), \
        f"Error must mention 'invalid guid'. Got:\n{r.output}"


def test_txn_guid_uuid_with_hyphens(tmp_path):
    """txn_guid in UUID-with-hyphens form must resolve to the same transaction."""
    runner = CliRunner()
    gf = tmp_path / "book.gnucash"
    import_new(runner, gf, write_fixture(tmp_path, "bank.txt",
                                         accounts_plus(BANK_INVOICE)))
    guid = get_guid(runner, gf, "Assets:Bank")
    # Insert hyphens into the 32-char hex GUID: 8-4-4-4-12
    uuid_form = f"{guid[0:8]}-{guid[8:12]}-{guid[12:16]}-{guid[16:20]}-{guid[20:32]}"
    r = import_into(runner, gf, write_fixture(tmp_path, "inv.txt",
                                              invoice_fixture(uuid_form)))
    assert r.exit_code == 0, f"UUID-with-hyphens txn_guid must be accepted:\n{r.output}"
    assert bank_tx_count(runner, gf, tmp_path) == 1, \
        "UUID-with-hyphens must not create a duplicate bank transaction"


def test_txn_guid_wrong_bank_account_fails(tmp_path):
    """bank_account that matches no split — counter-split search fails."""
    runner = CliRunner()
    gf = tmp_path / "book.gnucash"
    import_new(runner, gf, write_fixture(tmp_path, "bank.txt",
                                         accounts_plus(BANK_INVOICE)))
    guid = get_guid(runner, gf, "Assets:Bank")

    with open(INV_TEMPLATE) as f:
        wrong_bank = f.read().format(txn_guid=guid).replace(
            'bank_account: "Assets:Bank"',
            'bank_account: "Assets:Does:Not:Exist"'
        )
    wrong_file = write_fixture(tmp_path, "inv.txt", wrong_bank)
    r = import_into(runner, gf, wrong_file)
    assert r.exit_code != 0
    assert any(w in r.output.lower() for w in ("counter-split", "not found", "bank")), \
        f"Error must identify the problem. Got:\n{r.output}"


# ── idempotency ───────────────────────────────────────────────────────────────

def test_txn_guid_idempotent_reimport(tmp_path):
    """Re-importing the same invoice file after retarget must be a no-op."""
    runner = CliRunner()
    gf = tmp_path / "book.gnucash"
    import_new(runner, gf, write_fixture(tmp_path, "bank.txt",
                                         accounts_plus(BANK_INVOICE)))
    guid = get_guid(runner, gf, "Assets:Bank")
    invoice_file = write_fixture(tmp_path, "invoice.txt", invoice_fixture(guid))

    r = import_into(runner, gf, invoice_file)
    assert r.exit_code == 0, f"First import failed:\n{r.output}"
    assert bank_tx_count(runner, gf, tmp_path) == 1

    time.sleep(1)

    r = import_into(runner, gf, invoice_file)
    assert r.exit_code == 0, f"Re-import failed:\n{r.output}"
    assert bank_tx_count(runner, gf, tmp_path) == 1, \
        "Re-import must not create additional bank transactions"


# ── bill (vendor) equivalent ──────────────────────────────────────────────────

def test_txn_guid_bill_retarget(tmp_path):
    """txn_guid works for vendor bills — counter-split retargeted to AP."""
    runner = CliRunner()
    gf = tmp_path / "book.gnucash"
    import_new(runner, gf, write_fixture(tmp_path, "bank.txt",
                                         accounts_plus(BANK_BILL)))

    guid = get_guid(runner, gf, "Assets:Bank")
    bill_file = write_fixture(tmp_path, "bill.txt", bill_fixture(guid))

    r = import_into(runner, gf, bill_file)
    assert r.exit_code == 0, f"Bill import failed:\n{r.output}"
    assert bank_tx_count(runner, gf, tmp_path) == 1, \
        "Bill txn_guid must not create a duplicate bank transaction"

    exported = export_text(runner, gf)
    assert "fitid:20260115002" in exported, \
        "Original bill payment tx notes must be preserved"
    assert "Bill payment memo to preserve" in exported, \
        "Original bill payment split memo must be preserved"


# ─────────────────────────────────────────────────────────────────────────────
# BUG C: same-day same-amount — signature collapse on invoice-first re-import
# ─────────────────────────────────────────────────────────────────────────────

def test_same_day_same_amount_idempotent(tmp_path):
    """
    Two invoices both paid $100 on 2026-01-15 from Assets:Bank.
    Re-importing into the SAME existing file (not --new) must not add
    duplicate bank transactions.  GUID-based dedup should handle this.
    """
    runner = CliRunner()
    fixture = write_fixture(tmp_path, "two_invoices.txt",
                            accounts_plus_text(TWO_SAME_DAY_INVOICES))

    gf = tmp_path / "book.gnucash"
    import_new(runner, gf, fixture, biz=True)

    assert bank_tx_count(runner, gf, tmp_path) == 2

    r = import_into(runner, gf, fixture)
    assert r.exit_code == 0, f"Re-import failed:\n{r.output}"
    assert bank_tx_count(runner, gf, tmp_path) == 2, \
        "Re-import must not duplicate bank transactions"
