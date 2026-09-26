"""`--verify-costs` says why a split holding a balance is no cost basis.

A `cost_basis_balance` on a split that is no cost basis is read by nothing, and
the report prints the reason the split is not one, as the thing to go and look
at. Each case here is a split a book can be left holding a balance on, by a hand
edit or by an older tool, and each has a reason of its own: a sale, a line of
nothing, a refund of an owner's credit, and a settlement.

A share is not among them. It was, while a security was counted and priced
rather than converted and so had no cost basis at all; Q-046 records one for it in
the book's own currency, and a balance on a share purchase is now read like any
other.
"""

import re
from fractions import Fraction
from pathlib import Path

import pytest
from click.testing import CliRunner

from infrastructure.gnucash.kvp import get_custom_metadata, set_custom_metadata
from infrastructure.gnucash.utils import find_account
from repositories.gnucash_repository import GnuCashRepository, SessionMode
from services.foreign_currency import COST_BASIS_BALANCE_KEY, split_guid
from tests.conftest import _run

RATES = 'tests/fixtures/fx_rates_usd_dated.yaml'
RECEIVABLE = 'Assets:Accounts Receivable USD'


def _amount(split):
    amount = split.GetAmount()
    return Fraction(amount.num(), amount.denom())


def _import(runner, book, *args):
    result = _run(runner, 'import', *args)
    assert result.exit_code == 0, result.output
    assert 'Errors:       0' in result.output, result.output


def _a_sale(runner, tmp_path):
    book = tmp_path / 'book.gnucash'
    _import(runner, book, '--new', str(book), 'tests/fixtures/fx_buy_and_borrow_usd.txt')
    out = tmp_path / 'out.txt'
    assert _run(runner, 'export', str(book), str(out)).exit_code == 0
    bought = re.findall(r'Assets:Bank:USD 100\.00 USD\n\t+guid: "([0-9a-f]{32})"',
                        out.read_text())[0]
    sale = tmp_path / 'sale.txt'
    sale.write_text(Path('tests/fixtures/fx_sell_usd_partial.txt').read_text()
                    .replace('{basis_a}', bought))
    _import(runner, book, str(book), str(sale))
    return book, 'Assets:Bank:USD', lambda split: _amount(split) < 0


def _a_line_of_nothing(runner, tmp_path):
    book = tmp_path / 'book.gnucash'
    _import(runner, book, '--new', str(book), 'tests/fixtures/fx_buy_and_borrow_usd.txt')
    _import(runner, book, str(book), 'tests/fixtures/fx_a_usd_line_that_moves_nothing.txt')
    return book, 'Assets:Bank:USD', lambda split: _amount(split) == 0


def _a_refund(runner, tmp_path):
    book = tmp_path / 'book.gnucash'
    _import(runner, book, '--new', str(book), 'tests/fixtures/fx_refund_usd_prepayment.txt',
            '--include-business-objects')
    return book, RECEIVABLE, lambda split: _amount(split) > 0


def _a_settlement(runner, tmp_path):
    book = tmp_path / 'book.gnucash'
    _import(runner, book, '--new', str(book),
            'tests/fixtures/fx_invoice_usd_overpaid_into_usd_bank.txt',
            '--include-business-objects', '--fx-rates', RATES)
    # The settling split, not the overpaid credit beside it, which carries the
    # cost the invoice was booked at.
    return book, RECEIVABLE, lambda split: (
        _amount(split) < 0 and 'cost_basis_cost' not in get_custom_metadata(split))


def _a_balance_left_on(book, account_name, which):
    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.NORMAL)
    try:
        account = find_account(repo.book.get_root_account(), account_name)
        chosen = [split for split in account.GetSplitList() if which(split)]
        assert len(chosen) == 1, [split_guid(split) for split in chosen]
        split = chosen[0]
        transaction = split.GetParent()
        transaction.BeginEdit()
        metadata = dict(get_custom_metadata(split))
        metadata[COST_BASIS_BALANCE_KEY] = '1.00'
        set_custom_metadata(split, metadata)
        transaction.CommitEdit()
        guid = split_guid(split)
        repo.save()
    finally:
        repo.close()
    return guid


@pytest.mark.parametrize('book_with, reason', [
    (_a_sale, "it picks another split's cost basis, so it is a disposal rather "
              "than a source"),
    (_a_line_of_nothing, 'it moves nothing, so it brought no currency in'),
    (_a_refund, "it settles an owner's credit rather than posting a record, so "
                "it sends USD back rather than bringing any in"),
    (_a_settlement, "it lowers this account's USD rather than raising it"),
], ids=['sale', 'nothing', 'refund', 'settlement'])
def test_the_reason_is_the_one_that_split_has(tmp_path, book_with, reason):
    runner = CliRunner()
    book, account_name, which = book_with(runner, tmp_path)
    guid = _a_balance_left_on(book, account_name, which)

    verified = _run(runner, 'fx-balances', str(book), '--verify-costs')
    message = verified.output
    assert verified.exit_code == 1, message
    assert f'{guid}' in message, message
    assert f'but it is no cost basis: {reason}' in message, message
