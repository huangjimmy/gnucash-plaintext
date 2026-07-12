"""A customer credit consumed across TWO invoices — the AR mirror of
test_credit_consumption_across_bills.py.

Customer C-MB holds a $150 pre-payment credit (from an earlier
overpayment). Two follow-on invoices each carry `auto_apply_credit: true`,
so the credit is drawn down across both in posting order:

  * credit spans two invoices, the second goes partial when it runs out:
    invoice 1 ($100) settles fully from the credit, invoice 2 ($100) takes
    the remaining $50 and stays $50 outstanding (AR lot +50 — still owed to
    us, the sign-inverse of the bill case); the credit hits $0.
  * credit + one cash payment settle two invoices: the credit fully pays
    invoice 1 and half of invoice 2, and a $50 cash payment on invoice 2
    covers the rest — both settled, credit $0.
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
    """Fresh book → accounts → primer that leaves C-MB a $150 customer credit."""
    gf = tmp_path / 'book.gnucash'
    r = runner.invoke(cli, ['import', '--new', str(gf), ACCOUNTS])
    assert r.exit_code == 0, r.output
    r = _import(runner, gf, _fx('credit_primer_invoice_150.txt'),
                'primer.txt', tmp_path)
    assert r.exit_code == 0, r.output
    return gf


def _lot(gf, invoice_id):
    """The invoice's posted AR-lot balance (0 settled, positive still owed)."""
    import gnucash.gnucash_business as gb
    from gnucash import Query

    from repositories.gnucash_repository import GnuCashRepository
    repo = GnuCashRepository(str(gf))
    repo.open()
    try:
        q = Query()
        q.search_for('gncInvoice')
        q.set_book(repo.book)
        inv = next((wrap_invoice_or_bill(r) for r in q.run()
                    if wrap_invoice_or_bill(r).GetID() == invoice_id), None)
        q.destroy()
        assert inv is not None, f'{invoice_id!r} not found'
        lot = inv.GetPostedLot()
        assert lot is not None, f'{invoice_id!r} not posted'
        return round(lot.get_balance().to_double(), 2)
    finally:
        repo.close()


def _credit(gf, customer_id):
    from repositories.gnucash_repository import GnuCashRepository
    from use_cases.unpost_business_objects import find_prepayments_in_book
    repo = GnuCashRepository(str(gf))
    repo.open()
    try:
        return round(sum(float(c.amount) for c in find_prepayments_in_book(
            repo.book, customer_id=customer_id)), 2)
    finally:
        repo.close()


def test_credit_spans_two_invoices_second_goes_partial(tmp_path):
    """$150 credit, two $100 invoices both `auto_apply_credit`: invoice 1
    settles from the credit; invoice 2 takes the remaining $50 and stays
    $50 outstanding (AR lot +50); the credit is exhausted."""
    runner = CliRunner()
    gf = _book_with_credit(runner, tmp_path)
    assert _credit(gf, 'C-MB') == 150.00

    r = _import(runner, gf, _fx('credit_two_invoices_both_flagged.txt'),
                'two.txt', tmp_path)
    assert r.exit_code == 0, r.output

    assert _lot(gf, 'INV-MB-1') == 0.00, 'first invoice fully paid from credit'
    assert _lot(gf, 'INV-MB-2') == 50.00, 'second invoice partial — credit ran out'
    assert _credit(gf, 'C-MB') == 0.00, 'credit fully consumed'


def test_credit_full_first_invoice_credit_plus_cash_settle_second(tmp_path):
    """$150 credit + a $50 cash payment settle two $100 invoices: the credit
    fully pays invoice 1 and half of invoice 2, the $50 cash covers invoice
    2's rest. Both settle, credit exhausted."""
    runner = CliRunner()
    gf = _book_with_credit(runner, tmp_path)
    assert _credit(gf, 'C-MB') == 150.00

    r = _import(runner, gf, _fx('credit_two_invoices_second_has_cash.txt'),
                'two.txt', tmp_path)
    assert r.exit_code == 0, r.output

    assert _lot(gf, 'INV-MBC-1') == 0.00, 'first invoice fully paid from credit'
    assert _lot(gf, 'INV-MBC-2') == 0.00, 'second invoice: 50 credit + 50 cash'
    assert _credit(gf, 'C-MB') == 0.00, 'credit fully consumed'
