"""A payment an unpost left behind on a job's invoice keeps the customer the job is for.

GnuCash's Business menu makes jobs, and an invoice can be for one. It reports
its customer's owner type, so `unpost-invoices` finds and unposts it, and the
payment it leaves is in a lot whose owner is the job. Measured on 5.10 and 3.4
(tests/research/what_an_unpost_leaves_on_a_jobs_invoice_probe.py).

The format has no job, and the export writes a payment's `owner:` so that a
book rebuilt from it can still say whose the payment is. Written from the job,
there was nothing to write, and the rebuilt book's payment belonged to nobody.
A job is for a customer, so that customer is the owner written.
"""

from datetime import datetime

import gnucash
from click.testing import CliRunner
from gnucash import Account, GncNumeric

from cli.main import cli
from repositories.gnucash_repository import GnuCashRepository, SessionMode


def _a_jobs_invoice_paid_and_unposted(tmp_path, paid_cents=10000, unpost=True):
    """INV-JOB, 100.00 CAD for job J-1 of customer C-JOB, paid `paid_cents`
    and, where asked, unposted with `unpost-invoices`."""
    from gnucash.gnucash_business import Customer, Entry, Invoice, Job

    path = tmp_path / 'job.gnucash'
    repo = GnuCashRepository(str(path))
    repo.open(SessionMode.NEW)
    try:
        book = repo.book
        cad = book.get_table().lookup('CURRENCY', 'CAD')
        root = book.get_root_account()

        def account(name, kind):
            made = Account(book)
            made.BeginEdit()
            made.SetName(name)
            made.SetType(kind)
            made.SetCommodity(cad)
            root.append_child(made)
            made.CommitEdit()
            return made

        receivable = account('Receivable', gnucash.ACCT_TYPE_RECEIVABLE)
        bank = account('Bank', gnucash.ACCT_TYPE_BANK)
        income = account('Income', gnucash.ACCT_TYPE_INCOME)
        customer = Customer(book, 'C-JOB', cad, 'Customer With A Job')
        job = Job(book, 'J-1', customer, 'A job')
        invoice = Invoice(book, 'INV-JOB', cad, job)
        invoice.SetDateOpened(datetime(2026, 1, 5))
        line = Entry(book, invoice)
        line.SetDate(datetime(2026, 1, 5))
        line.SetDescription('Work')
        line.SetQuantity(GncNumeric(1, 1))
        line.SetInvAccount(income)
        line.SetInvPrice(GncNumeric(10000, 100))
        invoice.PostToAccount(receivable, datetime(2026, 1, 5), datetime(2026, 1, 5),
                              '', True, False)
        invoice.ApplyPayment(None, bank, GncNumeric(paid_cents, 100), GncNumeric(1, 1),
                             datetime(2026, 1, 10), 'Paid', '')
        repo.save()
    finally:
        repo.close()

    if unpost:
        unposted = CliRunner().invoke(cli, ['unpost-invoices', str(path), 'INV-JOB'])
        assert unposted.exit_code == 0, unposted.output
    return path


def test_a_jobs_credit_is_listed_under_the_customer_the_job_is_for(tmp_path):
    """Paid 150.00 against 100.00, the invoice leaves 50.00 of credit.
    `find-prepayments` gives it as the customer's, as `export` and
    `find-orphan-payments` give the job's payment."""
    book = _a_jobs_invoice_paid_and_unposted(tmp_path, paid_cents=15000, unpost=False)

    listed = CliRunner().invoke(cli, ['find-prepayments', str(book)])

    assert listed.exit_code == 0, listed.output
    assert 'Found 1 open pre-payment credit.' in listed.output, listed.output
    assert 'C-JOB' in listed.output, listed.output
    assert 'J-1' not in listed.output, listed.output


def _the_payment_block(text):
    return next(block for block in text.split('\n\n') if 'txn_type: P' in block)


def test_the_export_writes_the_jobs_customer_as_the_owner(tmp_path):
    book = _a_jobs_invoice_paid_and_unposted(tmp_path)
    out = tmp_path / 'out.txt'

    exported = CliRunner().invoke(cli, ['export', str(book), str(out),
                                        '--include-business-objects'])

    assert exported.exit_code == 0, exported.output
    assert 'owner: customer:C-JOB' in _the_payment_block(out.read_text()), out.read_text()


def test_the_listing_gives_the_jobs_customer_as_the_owner_too(tmp_path):
    """The same answer the export writes, in the book the unpost left. Given
    as the job, the listing and the export disagreed about whose it is, and a
    listing narrowed to C-JOB passed the payment over."""
    book = _a_jobs_invoice_paid_and_unposted(tmp_path)

    listed = CliRunner().invoke(cli, ['find-orphan-payments', str(book)])

    assert listed.exit_code == 0, listed.output
    assert 'Found 1 orphan bank-side payment transaction' in listed.output, listed.output
    assert 'C-JOB' in listed.output, listed.output
    assert 'J-1' not in listed.output, listed.output


def test_a_book_rebuilt_from_that_export_still_lists_it_under_the_customer(tmp_path):
    book = _a_jobs_invoice_paid_and_unposted(tmp_path)
    out = tmp_path / 'out.txt'
    assert CliRunner().invoke(cli, ['export', str(book), str(out),
                                    '--include-business-objects']).exit_code == 0
    rebuilt = tmp_path / 'rebuilt.gnucash'
    made = CliRunner().invoke(cli, ['import', '--new', str(rebuilt), str(out),
                                    '--include-business-objects'])
    assert made.exit_code == 0, made.output

    listed = CliRunner().invoke(cli, ['find-orphan-payments', str(rebuilt)])

    assert listed.exit_code == 0, listed.output
    assert 'Found 1 orphan bank-side payment transaction' in listed.output, listed.output
    assert 'C-JOB' in listed.output, listed.output
