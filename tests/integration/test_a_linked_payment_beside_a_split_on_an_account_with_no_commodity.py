"""A linked payment beside a split on an account with no commodity is refused, and says its figure.

The book of `test_linking_a_split_not_on_the_receivable.py`: the posted USD
invoice, then 100.00 USD received beside a 21.00 CAD fee, with the settlement
parked on `Assets:Due From Director`. The fee split is then put on `Holding`,
an asset account with no commodity, which GnuCash keeps through a save and a
reload. INV-USD-001's block gives the parked split.

With a third split in the transaction, the bank's 100.00 no longer says how much
settles the invoice, so the link is refused, listing that split with its
figure. The account has no commodity and so no smallest unit of its own, and
the figure is written to the hundredth. Measured on 5.10: `Holding 21.00`.
"""

from pathlib import Path

import gnucash
from click.testing import CliRunner
from gnucash import Account

from cli.main import cli
from infrastructure.gnucash.utils import find_account
from repositories.gnucash_repository import GnuCashRepository, SessionMode
from services.foreign_currency import iter_splits

FIXTURES = Path('tests/fixtures')
BOOK = FIXTURES / 'fx_usd_invoice_cad_income.txt'
RATES = FIXTURES / 'fx_rates_usd_dated.yaml'
MONEY_IN = FIXTURES / 'money_booked_to_a_cad_account.txt'
WITH_A_FEE = FIXTURES / 'money_parked_beside_a_cad_fee.txt'
LINKED_WITH_A_FEE = FIXTURES / 'a_payment_giving_the_split_parked_beside_a_fee.txt'
FEE_SPLIT = '3c4d5e6f708192a3b4c5d6e7f8091223'


def _run(*args):
    return CliRunner().invoke(cli, [str(arg) for arg in args])


def _done(*args):
    result = _run(*args)
    assert result.exit_code == 0, result.output


def test_it_is_refused_listing_that_split_to_the_hundredth(tmp_path):
    book = tmp_path / 'book.gnucash'
    _done('import', '--new', book, BOOK, '--include-business-objects', '--fx-rates', RATES)
    _done('import', book, MONEY_IN)
    _done('import', book, WITH_A_FEE)
    repo = GnuCashRepository(str(book))
    repo.open(SessionMode.NORMAL)
    try:
        root = repo.book.get_root_account()
        holding = Account(repo.book)
        holding.BeginEdit()
        holding.SetName('Holding')
        holding.SetType(gnucash.ACCT_TYPE_ASSET)
        root.append_child(holding)
        holding.CommitEdit()
        fee = next(split for split in iter_splits(repo.book)
                   if split.GetGUID().to_string() == FEE_SPLIT)
        transaction = fee.GetParent()
        transaction.BeginEdit()
        fee.SetAccount(find_account(root, 'Holding'))
        transaction.CommitEdit()
        repo.save()
    finally:
        repo.close()

    result = _run('import', book, LINKED_WITH_A_FEE, '--include-business-objects')

    assert result.exit_code != 0, result.output
    assert 'the transaction carries Holding 21.00 besides' in result.output, result.output
