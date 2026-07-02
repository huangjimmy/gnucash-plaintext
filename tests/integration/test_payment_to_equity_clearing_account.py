"""A payment's transfer account may be an owner's-equity deposit / clearing
account, not only a bank (or, for invoices, a bad-debt expense). A Canadian sole
proprietor has no separate business bank — the business tax return reports only
income and expense — so customer receipts and personally-paid vendor bills flow
through `Equity:Owner equity:Owner's equity`. Both invoice and bill payments
must accept it.
"""

from pathlib import Path

from click.testing import CliRunner

from cli.main import cli

ACCOUNTS_PATH = 'tests/fixtures/q022_clearing_accounts.txt'
FIXTURES_DIR = Path('tests/fixtures')
EQUITY = "Equity.Owner equity.Owner's equity"


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


def test_invoice_payment_to_owner_equity_closes_ar(tmp_path):
    runner = CliRunner()
    gf = _new_book(runner, tmp_path)
    r = _import(runner, gf, 'q022_invoice_paid_to_equity.txt', tmp_path)
    assert r.exit_code == 0, r.output
    # AR cleared (invoice settled); the $100 receipt landed in owner's equity.
    assert _balance(gf, 'Assets.Accounts Receivable') == 0.0
    assert abs(_balance(gf, EQUITY)) == 100.0


def test_bill_payment_to_owner_equity_closes_ap(tmp_path):
    runner = CliRunner()
    gf = _new_book(runner, tmp_path)
    r = _import(runner, gf, 'q022_bill_paid_to_equity.txt', tmp_path)
    assert r.exit_code == 0, r.output
    # AP cleared (bill settled); the $60 was paid from personal funds via equity.
    assert _balance(gf, 'Liabilities.Accounts Payable') == 0.0
    assert abs(_balance(gf, EQUITY)) == 60.0
