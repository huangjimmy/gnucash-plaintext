"""A job's invoice is not settled by another customer's payment.

INV-JOB is for job J-1 of customer C-JOB, paid and unposted. C-OTHER's
INV-OTHER is paid 100.00 and unposted as well, which leaves its payment loose
for an invoice of C-OTHER's to take. A hand-written INV-JOB block, which keeps
the invoice on the job, posts it and gives that payment's transaction with
`txn_guid:`.

One customer's payment cannot settle another customer's invoice, and a job is
for a customer, so INV-JOB is C-JOB's. The owner checks read INV-JOB's owner as
the job, which is neither a customer nor a vendor, and answered nothing.
Measured on 5.10: INV-JOB was posted and settled out of C-OTHER's payment at
exit 0, and a block of INV-JOB's recording a payment of its own was refused as
a mistyped guid for C-OTHER's.
"""

from pathlib import Path

from click.testing import CliRunner

from cli.main import cli
from tests.integration.test_a_jobs_orphaned_payment_keeps_its_customer import (
    _a_jobs_invoice_paid_and_unposted,
)
from tests.integration.test_a_jobs_orphaned_payment_settles_only_its_customers_invoice import (
    _bank_transactions,
)

FIXTURES = Path('tests/fixtures')
OTHER = FIXTURES / 'another_customers_invoice_giving_a_jobs_orphaned_payment.txt'
JOB = FIXTURES / 'a_jobs_invoice_giving_another_customers_orphaned_payment.txt'


def _run(*args):
    return CliRunner().invoke(cli, [str(arg) for arg in args])


def _done(*args):
    result = _run(*args)
    assert result.exit_code == 0, result.output


def test_it_is_refused(tmp_path):
    book = _a_jobs_invoice_paid_and_unposted(tmp_path)
    jobs = set(_bank_transactions(book))
    other = tmp_path / 'other.txt'
    other.write_text(OTHER.read_text().replace('\t\ttxn_guid: "TXN_GUID"\n', ''))
    _done('import', book, other, '--include-business-objects')
    _done('unpost-invoices', book, 'INV-OTHER')
    (theirs,) = set(_bank_transactions(book)) - jobs
    source = tmp_path / 'job.txt'
    source.write_text(JOB.read_text().replace('TXN_GUID', theirs))

    result = _run('import', book, source, '--include-business-objects')

    assert result.exit_code != 0, result.output
    assert "is customer C-OTHER's money" in result.output, result.output
    assert "this invoice is customer C-JOB's" in result.output, result.output


def test_its_block_like_another_customers_payment_records_its_own(tmp_path):
    """INV-OTHER is paid 100.00 on 2026-01-11 and stays posted. INV-JOB's block
    gives a guid the book lacks, with that payment's date, figure, account and
    memo. Money settling another customer's invoice is not the movement the
    block describes, so the payment is recorded from the block."""
    book = _a_jobs_invoice_paid_and_unposted(tmp_path)

    def dated_apart(text):
        return (text.replace('\t\tdate: 2026-01-10', '\t\tdate: 2026-01-11')
                .replace('memo: "Paid"', 'memo: "Other"'))

    other = tmp_path / 'other.txt'
    other.write_text(dated_apart(OTHER.read_text()).replace('\t\ttxn_guid: "TXN_GUID"\n', ''))
    _done('import', book, other, '--include-business-objects')
    source = tmp_path / 'job.txt'
    source.write_text(dated_apart(JOB.read_text())
                      .replace('TXN_GUID', 'feedfacefeedfacefeedfacefeedface'))

    result = _run('import', book, source, '--include-business-objects')

    assert result.exit_code == 0, result.output
    assert 'invoice "INV-JOB": updated' in result.output, result.output
    assert len(_bank_transactions(book)) == 3
