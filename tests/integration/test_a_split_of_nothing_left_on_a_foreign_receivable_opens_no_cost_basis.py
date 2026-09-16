"""A 0.00 split left on a foreign record's own receivable is no cost basis.

`unapply-payment --to` the receivable the settlement is already on leaves that
settlement there, and it is the owner's money rather than the record's, so on a
foreign record it opens a cost basis at the cost the record carries
(`_keep_them_as_the_owners_credit`). A split of nothing holds no currency, so
there is nothing to open one for.

GnuCash's View → Lots puts a 0.00 split in a record's lot — "add split to lot"
calls `gnc_lot_add_split` with no scrub, which
`test_a_split_of_nothing_in_an_invoice_lot_is_exported_with_its_bank.py`
measures — and `unapply-payment --all` takes every split the lot holds, with no
figure deciding which. So the two meet.

Measured on 5.10 before this: `unapply-payment INV-USD --all --to` its own
receivable ended in `ZeroDivisionError: Fraction(0, 1)`, raised in
`write_cost_basis_cost` where it divides the base-currency value by the units
the split holds. The cost was being written because `cost_of` answers None for
a split with no amount to divide by, which is the one condition under which
`record_borrowed_basis` writes a cost of its own.
"""

import os
from pathlib import Path

import pytest
from click.testing import CliRunner

from cli.main import cli
from infrastructure.gnucash.engine import load_gnc_engine
from infrastructure.gnucash.utils import qof_pointer
from repositories.gnucash_repository import GnuCashRepository
from services.foreign_currency import cost_basis_balance_of, iter_splits, stated_cost_of
from services.gnucash_importer import _find_invoices_by_id

INVOICE = 'tests/fixtures/a_usd_invoice_paid_from_the_usd_bank.txt'
NOTHING = 'tests/fixtures/a_line_of_nothing_on_the_usd_receivable.txt'
RATES = 'tests/fixtures/fx_rates_usd_dated.yaml'
RECEIVABLE = 'Assets:Accounts Receivable USD'


def _run(*args):
    return CliRunner().invoke(cli, [str(arg) for arg in args])


def _the_split_of_nothing(book):
    return next(split for split in iter_splits(book)
                if split.GetParent().GetDescription() == 'A line of nothing'
                and split.GetAccount().GetName() == 'Accounts Receivable USD')


@pytest.fixture
def book(tmp_path):
    """INV-USD paid in full, with a 0.00 USD split added to its lot."""
    path = tmp_path / 'book.gnucash'
    source = tmp_path / 'in.txt'
    source.write_text(Path(INVOICE).read_text() + '\n'
                      + Path(NOTHING).read_text())
    made = _run('import', '--new', path, source,
                '--include-business-objects', '--fx-rates', RATES)
    assert made.exit_code == 0, made.output

    lib = load_gnc_engine()
    repo = GnuCashRepository(str(path))
    repo.open()
    try:
        lot = _find_invoices_by_id(repo.book, 'INV-USD')[0].GetPostedLot()
        nothing = _the_split_of_nothing(repo.book)
        account = nothing.GetAccount()
        account.BeginEdit()
        lib.gnc_lot_add_split(qof_pointer(lot), int(nothing.instance))
        account.CommitEdit()
        assert nothing.GetLot() is not None
        repo.save()
    finally:
        repo.close()
    return path


def test_taking_every_payment_off_onto_that_receivable_is_not_refused(book):
    result = _run('unapply-payment', book, 'INV-USD', '--all',
                  '--to', RECEIVABLE, '--fx-rates', RATES)

    assert result.exit_code == 0, result.output
    assert result.exception is None or isinstance(
        result.exception, SystemExit), repr(result.exception)


def test_the_split_of_nothing_is_left_holding_no_cost_basis(book):
    """No cost and no balance: a cost basis of 0.00 is currency that is not there."""
    assert _run('unapply-payment', book, 'INV-USD', '--all',
                '--to', RECEIVABLE, '--fx-rates', RATES).exit_code == 0

    repo = GnuCashRepository(str(book))
    repo.open()
    try:
        nothing = _the_split_of_nothing(repo.book)

        assert stated_cost_of(nothing) is None
        assert cost_basis_balance_of(nothing) is None
    finally:
        repo.close()


def test_the_settlement_beside_it_is_still_the_customers_credit(book):
    """The real 100.00 USD settlement keeps what this change does not touch."""
    assert _run('unapply-payment', book, 'INV-USD', '--all',
                '--to', RECEIVABLE, '--fx-rates', RATES).exit_code == 0

    listed = _run('find-prepayments', book)

    assert listed.exit_code == 0, listed.output
    assert 'C-USD' in listed.output, listed.output
