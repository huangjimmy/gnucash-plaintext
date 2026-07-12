"""A vendor credit consumed across TWO bills — including running out.

The vendor V-MB holds a $150 pre-payment credit (from an earlier
overpayment). Two follow-on bills each carry `auto_apply_credit: true`, so
GnuCash's `gncInvoiceAutoApplyPayments` draws the credit down across both:

  * credit spans two bills, the second goes partial when it runs out:
    bill 1 ($100) settles fully from the credit, bill 2 ($100) takes the
    remaining $50 and stays $50 outstanding; the credit hits $0.
  * credit + one cash payment settle two bills: the credit fully pays
    bill 1 and half of bill 2, and a $50 cash payment on bill 2 covers the
    rest — both bills settled, credit $0.

Posting order is the fixture order (bill 1 before bill 2), so the first
bill is the one paid in full and the second is the one the credit runs
out on.
"""
from pathlib import Path

from click.testing import CliRunner

from cli.main import cli
from infrastructure.gnucash.utils import wrap_invoice_or_bill

FIXTURES = Path('tests/fixtures')
ACCOUNTS = str(FIXTURES / 'q019_accounts.txt')


def _fx(name):
    return (FIXTURES / name).read_text()


def _import(runner, gf, text, name, tmp_path):
    p = tmp_path / name
    p.write_text(text)
    return runner.invoke(cli, ['import', str(gf), str(p),
                               '--include-business-objects'])


def _book_with_credit(runner, tmp_path):
    """Fresh book → accounts → primer that leaves V-MB a $150 vendor credit."""
    gf = tmp_path / 'book.gnucash'
    r = runner.invoke(cli, ['import', '--new', str(gf), ACCOUNTS])
    assert r.exit_code == 0, r.output
    r = _import(runner, gf, _fx('credit_primer_150.txt'), 'primer.txt', tmp_path)
    assert r.exit_code == 0, r.output
    return gf


def _lot(gf, bill_id):
    """The bill's posted AP-lot balance (0 settled, negative still owed)."""
    import gnucash.gnucash_business as gb
    from gnucash import Query

    from repositories.gnucash_repository import GnuCashRepository
    repo = GnuCashRepository(str(gf))
    repo.open()
    try:
        q = Query()
        q.search_for('gncInvoice')
        q.set_book(repo.book)
        bill = next((wrap_invoice_or_bill(r) for r in q.run()
                     if wrap_invoice_or_bill(r).GetID() == bill_id), None)
        q.destroy()
        assert bill is not None, f'{bill_id!r} not found'
        lot = bill.GetPostedLot()
        assert lot is not None, f'{bill_id!r} not posted'
        return round(lot.get_balance().to_double(), 2)
    finally:
        repo.close()


def _credit(gf, vendor_id):
    from repositories.gnucash_repository import GnuCashRepository
    from use_cases.unpost_business_objects import find_prepayments_in_book
    repo = GnuCashRepository(str(gf))
    repo.open()
    try:
        return round(sum(float(c.amount) for c in find_prepayments_in_book(
            repo.book, vendor_id=vendor_id)), 2)
    finally:
        repo.close()


def test_credit_spans_two_bills_second_goes_partial(tmp_path):
    """$150 credit, two $100 bills both `auto_apply_credit`: bill 1 settles
    from the credit; bill 2 takes the remaining $50 and stays $50
    outstanding; the credit is exhausted."""
    runner = CliRunner()
    gf = _book_with_credit(runner, tmp_path)
    assert _credit(gf, 'V-MB') == 150.00

    r = _import(runner, gf, _fx('credit_two_bills_both_flagged.txt'),
                'two.txt', tmp_path)
    assert r.exit_code == 0, r.output

    assert _lot(gf, 'BILL-MB-1') == 0.00, 'first bill fully paid from credit'
    assert _lot(gf, 'BILL-MB-2') == -50.00, 'second bill partial — credit ran out'
    assert _credit(gf, 'V-MB') == 0.00, 'credit fully consumed'


def test_credit_full_first_bill_credit_plus_cash_settle_second(tmp_path):
    """$150 credit + a $50 cash payment settle two $100 bills: the credit
    fully pays bill 1 and half of bill 2, the $50 cash covers bill 2's
    rest. Both bills settle, credit exhausted."""
    runner = CliRunner()
    gf = _book_with_credit(runner, tmp_path)
    assert _credit(gf, 'V-MB') == 150.00

    r = _import(runner, gf, _fx('credit_two_bills_second_has_cash.txt'),
                'two.txt', tmp_path)
    assert r.exit_code == 0, r.output

    assert _lot(gf, 'BILL-MBC-1') == 0.00, 'first bill fully paid from credit'
    assert _lot(gf, 'BILL-MBC-2') == 0.00, 'second bill: 50 credit + 50 cash'
    assert _credit(gf, 'V-MB') == 0.00, 'credit fully consumed'
