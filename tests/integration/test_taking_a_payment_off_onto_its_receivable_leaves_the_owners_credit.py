"""A payment taken off an invoice onto the receivable it sits on is the customer's credit.

`unapply-payment` and `unlink` take a settlement off its invoice and move the
split to the account `--to` states. Where that is the receivable the split is
already on, nothing moves it anywhere: the payment is no longer this invoice's
and is still the customer's money. It was left on the receivable in no lot,
owned by nobody. `find-prepayments` did not list it, and `find-orphan-payments`
either did not either or called it an unposted invoice's orphan at the bank's
whole figure. Measured on 5.10, for a credit the invoice had spent and for a
bank payment alike.

So it is put in a lot of the customer's, as GnuCash keeps a payment that pays
no invoice. On a foreign invoice the credit is currency the book holds and
owes back, so it is a cost basis again, as an overpayment's credit is: a spent
credit gets back the balance spending it took, and a bank payment is opened at
the cost the invoice carries. With INV-USD-AUTO owing again, the book holds
what it held before the credit was spent: 300.00 USD across three cost bases.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner

from cli.main import cli
from tests.integration.test_find_orphan_payments import ACCOUNTS as TAB_ACCOUNTS
from tests.integration.test_find_orphan_payments import _fixture

ACCOUNTS = 'tests/fixtures/payment_roundtrip_accounts.txt'
OVERPAID = 'tests/fixtures/q015_oh_inv_export_emits.txt'
SPENDING = 'tests/fixtures/an_invoice_spending_an_overpayments_credit.txt'
OVERPAID_USD = 'tests/fixtures/fx_invoice_usd_overpaid_into_usd_bank.txt'
SPENDING_USD = 'tests/fixtures/fx_invoice_auto_applying_the_whole_credit.txt'
RATES = 'tests/fixtures/fx_rates_usd_dated.yaml'
AR = 'Assets:Accounts Receivable'
AR_USD = 'Assets:Accounts Receivable USD'


def _run(*args):
    return CliRunner().invoke(cli, [str(arg) for arg in args])


def _imported(*args):
    result = _run('import', *args)
    assert result.exit_code == 0, result.output
    return result


def _the_credit(book, account):
    """The transaction and split of the credit on `account`: in a lot no invoice owns."""
    from gnucash import gnucash_core_c as gc

    from infrastructure.gnucash.utils import get_account_full_name, qof_instance
    from repositories.gnucash_repository import GnuCashRepository
    from services.foreign_currency import iter_splits

    repo = GnuCashRepository(str(book))
    repo.open()
    try:
        for split in iter_splits(repo.book):
            lot = split.GetLot()
            if (get_account_full_name(split.GetAccount()) == account and lot is not None
                    and not gc.gncInvoiceGetInvoiceFromLot(qof_instance(lot))):
                return split.GetParent().GetGUID().to_string(), split.GetGUID().to_string()
    finally:
        repo.close()
    raise AssertionError(f'no credit on {account}')


def _cad_spent_credit(tmp_path):
    book = tmp_path / 'book.gnucash'
    _imported('--new', book, ACCOUNTS)
    _imported(book, OVERPAID, '--include-business-objects')
    txn, split = _the_credit(book, AR)
    spending = tmp_path / 'spending.txt'
    spending.write_text(Path(SPENDING).read_text()
                        .replace('TXN_GUID', txn).replace('SPLIT_GUID', split))
    _imported(book, spending, '--include-business-objects')
    return book, 'INV-B', ['--txn', txn, '--to', AR], []


def _cad_bank_payment(tmp_path):
    book = tmp_path / 'book.gnucash'
    source = tmp_path / 'in.txt'
    source.write_text(TAB_ACCOUNTS + '\n' + _fixture('q014_invoice_posted_paid'))
    _imported('--new', book, source, '--include-business-objects')
    return book, 'INV-001', ['--to', AR], []


def _usd_spent_credit(tmp_path):
    book = tmp_path / 'book.gnucash'
    _imported('--new', book, OVERPAID_USD, '--include-business-objects', '--fx-rates', RATES)
    _imported(book, SPENDING_USD, '--include-business-objects', '--fx-rates', RATES)
    return book, 'INV-USD-AUTO', ['--to', AR_USD, '--fx-rates', RATES], ['--fx-rates', RATES]


def _usd_bank_payment(tmp_path):
    book = tmp_path / 'book.gnucash'
    _imported('--new', book, OVERPAID_USD, '--include-business-objects', '--fx-rates', RATES)
    return book, 'INV-USD-OVER', ['--to', AR_USD, '--fx-rates', RATES], ['--fx-rates', RATES]


CASES = [
    pytest.param(_cad_spent_credit, 'unapply-payment',
                 ['customer C001 (Acme)  CAD 50.00'], None, id='cad-spent-credit'),
    pytest.param(_cad_spent_credit, 'unlink',
                 ['customer C001 (Acme)  CAD 50.00'], None, id='cad-spent-credit-unlink'),
    pytest.param(_cad_bank_payment, 'unapply-payment',
                 ['customer C001 (Acme)  CAD 100.00'], None, id='cad-bank-payment'),
    pytest.param(_usd_spent_credit, 'unapply-payment',
                 ['Total credit available: USD 100.00 for customer C-US'],
                 'Total USD cost basis balance: 300.00 USD', id='usd-spent-credit'),
    pytest.param(_usd_bank_payment, 'unapply-payment',
                 ['Total credit available: USD 200.00 for customer C-US'],
                 'Total USD cost basis balance: 300.00 USD', id='usd-bank-payment'),
]


def _the_book_holds(book, credits, bases):
    listed = _run('find-prepayments', book)
    assert listed.exit_code == 0, listed.output
    for credit in credits:
        assert credit in listed.output, listed.output
    orphans = _run('find-orphan-payments', book)
    assert 'No orphan bank-side payment transactions found.' in orphans.output, orphans.output
    if bases:
        balances = _run('fx-balances', book)
        assert bases in balances.output, balances.output
        assert 'none recorded' not in balances.output, balances.output


@pytest.mark.parametrize('build, command, credits, bases', CASES)
def test_it_is_the_customers_credit(tmp_path, build, command, credits, bases):
    book, record, arguments, _rates = build(tmp_path)

    taken = _run(command, book, record, *arguments)

    assert taken.exit_code == 0, taken.output
    _the_book_holds(book, credits, bases)


@pytest.mark.parametrize('build, command, credits, bases', CASES)
def test_a_book_built_from_its_export_holds_the_same(tmp_path, build, command, credits,
                                                     bases):
    book, record, arguments, rates = build(tmp_path)
    assert _run(command, book, record, *arguments).exit_code == 0
    out = tmp_path / 'out.txt'
    assert _run('export', book, out, '--include-business-objects').exit_code == 0

    again = _imported(book, out, '--include-business-objects', *rates)
    fresh = tmp_path / 'fresh.gnucash'
    _imported('--new', fresh, out, '--include-business-objects', *rates)

    assert f'invoice "{record}": unchanged' in again.output, again.output
    _the_book_holds(fresh, credits, bases)
