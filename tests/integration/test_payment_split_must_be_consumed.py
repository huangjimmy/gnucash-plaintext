"""A split written in a payment block reaches the book, or the file is refused.

The splits a `payment:` block carries are consumed by the cross-currency
settlement — that is the path with a realized difference for them to take. Any
other payment reaches its `return` without ever reading them, so a fee written
on an ordinary same-currency payment parses, is dropped, and the import reports
success: the exact failure Q-035 exists to end, where the book quietly holds
less than the file said.

An amount the currency cannot state is the same problem one level down. 2.005
CAD is half a cent; booking it costs the entry its balance, because the split
is written as whole cents while the residual is computed against what the file
stated.
"""

import re
from pathlib import Path

from click.testing import CliRunner

from cli.main import cli
from infrastructure.gnucash.utils import find_account
from repositories.gnucash_repository import GnuCashRepository, SessionMode


def _import(tmp_path, fixture, *extra):
    gnucash_file = tmp_path / 'book.gnucash'
    result = CliRunner().invoke(cli, [
        'import', '--new', str(gnucash_file), fixture,
        '--include-business-objects', *extra])
    return gnucash_file, result


def test_a_fee_split_on_a_same_currency_payment_is_not_dropped(tmp_path):
    """The fee is either booked or refused — never silently discarded."""
    gnucash_file, result = _import(
        tmp_path, 'tests/fixtures/payment_split_on_same_currency_payment.txt')

    if result.exit_code == 0:
        # If the import is accepted, the fee the file stated must be in the book.
        repo = GnuCashRepository(str(gnucash_file))
        repo.open(mode=SessionMode.READ_ONLY)
        try:
            fees = find_account(repo.book.get_root_account(), 'Expenses:Bank Fees')
            balance = fees.GetBalance().num() if fees is not None else 0
        finally:
            repo.close()
        assert balance != 0, (
            'the payment block stated a 2.00 CAD bank fee, the import reported '
            'success, and the book holds nothing on Expenses:Bank Fees')
    else:
        # Refused: the message must name the split it could not place, so the
        # writer knows which line to move rather than that "something" failed.
        assert 'Bank Fees' in result.output, result.output
        assert 'split line' in result.output, result.output


def test_a_fee_on_a_converting_payment_is_refused_whatever_it_states(tmp_path):
    """The amount is not the question here — the line is.

    This fee states half a cent, which no CAD split can hold, and the payment
    block refuses it before reading that: a payment carries the difference the
    settlement realized and nothing else, because everything else in it moved
    money and arrives as its own transaction. The amount rule still applies
    where such a line does belong, which is a transaction (below).
    """
    _, result = _import(
        tmp_path, 'tests/fixtures/fx_payment_split_sub_cent.txt',
        '--fx-rates', 'tests/fixtures/fx_rates_usd_dated.yaml')

    assert result.exit_code != 0, result.output
    assert 'Bank Fees' in result.output, result.output
    assert 'its own transaction' in result.output, result.output


def test_a_sub_cent_amount_on_an_ordinary_transaction_is_refused(tmp_path):
    """A figure CAD cannot hold is refused where such a figure belongs.

    Booked instead, it lands as 2.00 and `$residual$` quietly absorbs the
    missing half cent — two figures in the book that the file never stated.
    """
    gnucash_file, result = _import(
        tmp_path, 'tests/fixtures/transaction_split_sub_cent.txt')

    assert result.exit_code != 0 or 'Errors:       0' not in result.output, (
        'a half-cent CAD amount was accepted; the book now holds figures the '
        f'file never stated:\n{result.output}')
    assert '2.005' in result.output, result.output


def test_a_txn_guid_payment_carrying_a_split_is_refused(tmp_path):
    """The retarget path has its own early return, so it needs its own test.

    A payment attached with `txn_guid:` names a transaction that already exists
    and already carries whatever splits it was written with; a split line in
    the block would be placed nowhere at all. Reaching that path takes the full
    setup: the invoice, then the settlement transaction it claims.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    result = runner.invoke(cli, [
        'import', '--new', str(book),
        'tests/fixtures/fx_usd_invoice_cad_income.txt',
        '--include-business-objects',
        '--fx-rates', 'tests/fixtures/fx_rates_usd_dated.yaml'])
    assert result.exit_code == 0, result.output

    listing = runner.invoke(cli, ['fx-balances', str(book)]).output
    basis = re.search(r'\b([0-9a-f]{32})\b', listing).group(1)

    settlement = tmp_path / 'settlement.txt'
    settlement.write_text(
        Path('tests/fixtures/fx_settlement_txn_for_invoice.txt').read_text()
        .replace('{basis_guid}', basis))
    result = runner.invoke(cli, ['import', str(book), str(settlement)])
    assert result.exit_code == 0, result.output

    result = runner.invoke(cli, [
        'import', str(book),
        'tests/fixtures/fx_txn_guid_payment_with_split.txt',
        '--include-business-objects'])

    assert result.exit_code != 0, result.output
    assert 'txn_guid' in result.output, result.output
    assert 'Bank Fees' in result.output, result.output
