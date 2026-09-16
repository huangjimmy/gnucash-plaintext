"""A payment an unpost left on a job's invoice settles only an invoice of the customer the job is for.

INV-JOB is for job J-1 of customer C-JOB, paid 100.00 and unposted with
`unpost-invoices`, which leaves the payment in a lot whose owner is the job
(tests/research/what_an_unpost_leaves_on_a_jobs_invoice_probe.py). A file then
gives that payment's transaction with `txn_guid:` on another invoice's block.

One customer's payment cannot settle another customer's invoice, and a job is
for a customer, so the payment is C-JOB's money. The owner check read the lot's
owner as the job, which is neither a customer nor a vendor, answered nothing,
and nothing is refused on silence. Measured on 5.10: C-OTHER's invoice was
created and settled out of that payment, and the import saved at exit 0.
"""

from click.testing import CliRunner

from cli.main import cli
from repositories.gnucash_repository import GnuCashRepository, SessionMode
from tests.integration.test_a_jobs_orphaned_payment_keeps_its_customer import (
    _a_jobs_invoice_paid_and_unposted,
)

FIXTURE = 'tests/fixtures/another_customers_invoice_giving_a_jobs_orphaned_payment.txt'


def _bank_transactions(book):
    """The guids of the transactions on `Bank`."""
    repo = GnuCashRepository(str(book))
    repo.open(SessionMode.READ_ONLY)
    try:
        bank = repo.book.get_root_account().lookup_by_name('Bank')
        return [split.GetParent().GetGUID().to_string() for split in bank.GetSplitList()]
    finally:
        repo.close()


def _the_jobs_payment(book):
    """The guid of the one transaction on `Bank`."""
    (only,) = _bank_transactions(book)
    return only


def _run(*args):
    return CliRunner().invoke(cli, [str(arg) for arg in args])


def test_another_customers_invoice_giving_it_is_refused(tmp_path):
    book = _a_jobs_invoice_paid_and_unposted(tmp_path)
    source = tmp_path / 'other.txt'
    with open(FIXTURE) as fixture:
        source.write_text(fixture.read().replace('TXN_GUID', _the_jobs_payment(book)))

    result = _run('import', book, source, '--include-business-objects')

    assert result.exit_code != 0, result.output
    assert "is customer C-JOB's money" in result.output, result.output
    assert "this invoice is customer C-OTHER's" in result.output, result.output
    orphans = _run('find-orphan-payments', book)
    assert 'Found 1 orphan bank-side payment transaction' in orphans.output, orphans.output


def test_an_invoice_of_the_jobs_customer_giving_it_is_settled(tmp_path):
    book = _a_jobs_invoice_paid_and_unposted(tmp_path)
    source = tmp_path / 'same.txt'
    with open(FIXTURE) as fixture:
        source.write_text(fixture.read()
                          .replace('TXN_GUID', _the_jobs_payment(book))
                          .replace('Another Customer', 'Customer With A Job')
                          .replace('C-OTHER', 'C-JOB'))

    result = _run('import', book, source, '--include-business-objects')

    assert result.exit_code == 0, result.output
    orphans = _run('find-orphan-payments', book)
    assert 'No orphan bank-side payment transactions found.' in orphans.output, orphans.output


def test_another_customers_block_like_the_jobs_payment_records_its_own(tmp_path):
    """INV-JOB is posted and still paid. C-OTHER's block gives a guid the book
    lacks, with the date, figure, account and memo of the job's payment. Two
    customers each paying 100.00 into one account on one day is ordinary, and
    money settling another customer's invoice is not the movement the block
    describes, so the payment is recorded from the block."""
    book = _a_jobs_invoice_paid_and_unposted(tmp_path, unpost=False)
    source = tmp_path / 'other.txt'
    with open(FIXTURE) as fixture:
        source.write_text(fixture.read().replace('TXN_GUID', 'feedfacefeedfacefeedfacefeedface'))

    result = _run('import', book, source, '--include-business-objects')

    assert result.exit_code == 0, result.output
    assert 'invoice "INV-OTHER": created' in result.output, result.output
    assert len(_bank_transactions(book)) == 2
