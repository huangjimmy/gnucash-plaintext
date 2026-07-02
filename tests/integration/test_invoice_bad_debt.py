"""Bad debt on an invoice/bill — a `payment:` whose transfer account is an
expense writes the invoice off instead of receiving cash. The payment account
(`account:`, or the legacy `bank_account:` alias) is constrained by side: an
invoice payment may be an asset (cash) or an expense (write-off); a bill payment
must be an asset (an unpaid bill is debt forgiveness — a gain — out of scope).
"""

from pathlib import Path

from click.testing import CliRunner

from cli.main import cli

ACCOUNTS_PATH = 'tests/fixtures/payment_roundtrip_accounts.txt'
FIXTURES_DIR = Path('tests/fixtures')


def _new_book(runner, tmp_path):
    gf = tmp_path / 'book.gnucash'
    r = runner.invoke(cli, ['import', '--new', str(gf), ACCOUNTS_PATH])
    assert r.exit_code == 0, r.output
    return gf


def _import(runner, gf, fixture_name, tmp_path):
    p = tmp_path / fixture_name
    p.write_text((FIXTURES_DIR / fixture_name).read_text())
    return runner.invoke(cli, ['import', str(gf), str(p),
                               '--include-business-objects'])


def _balance(gf, name):
    from repositories.gnucash_repository import GnuCashRepository
    repo = GnuCashRepository(str(gf))
    repo.open()
    try:
        out = {}

        def walk(a):
            out[a.get_full_name()] = round(a.GetBalance().to_double(), 2)
            for c in a.get_children():
                walk(c)
        walk(repo.book.get_root_account())
        return out.get(name, 0.0)
    finally:
        repo.close()


def test_invoice_written_off_to_expense(tmp_path):
    runner = CliRunner()
    gf = _new_book(runner, tmp_path)
    r = _import(runner, gf, 'q_invoice_bad_debt.txt', tmp_path)
    assert r.exit_code == 0, r.output
    # AR cleared (invoice settled), the $100 booked to the bad-debt expense.
    assert _balance(gf, 'Assets.Accounts Receivable') == 0.0
    assert _balance(gf, 'Expenses.Supplies') == 100.0


def test_invoice_payment_to_income_is_rejected(tmp_path):
    runner = CliRunner()
    gf = _new_book(runner, tmp_path)
    r = _import(runner, gf, 'q_invoice_pay_to_income.txt', tmp_path)
    # Routing an invoice payment to income (a credit memo) is not allowed.
    assert 'asset' in r.output.lower() and 'expense' in r.output.lower(), r.output


def test_bill_payment_to_expense_is_rejected(tmp_path):
    runner = CliRunner()
    gf = _new_book(runner, tmp_path)
    r = _import(runner, gf, 'q_bill_pay_to_expense.txt', tmp_path)
    # A bill has no bad-debt write-off; paying it to an expense is rejected.
    assert 'bill payment must use an asset' in r.output.lower(), r.output
