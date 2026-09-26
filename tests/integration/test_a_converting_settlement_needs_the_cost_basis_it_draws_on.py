"""A converting settlement needs the cost basis it draws on, and says so where there is too little or none.

INV-USD-001 is 100.00 USD booked at 1.40, and a payment of 100.00 USD from the
CAD bank converts all of it, so it draws 100.00 USD out of the invoice's
posting split, the cost basis that prices the receivable. Measured on 5.10:

- **with 40.00 USD already sold against it**, by a sale forced past the rule
  that an uncollected receivable holds no currency, 60.00 is left, and the
  payment is refused, and the refusal states both figures;
- **with no balance recorded**, as on an invoice GnuCash posted itself, the
  payment is refused, and stating `cost_basis_balance:` on the posting split
  with `--strategy update`, as the refusal says to, lets the same payment
  through.
"""

import re
from pathlib import Path

from click.testing import CliRunner

from cli.main import cli
from infrastructure.gnucash.kvp import get_custom_metadata, set_custom_metadata
from repositories.gnucash_repository import GnuCashRepository, SessionMode
from services.foreign_currency import COST_BASIS_BALANCE_KEY, find_split_by_guid

FIXTURES = Path('tests/fixtures')
BOOK = FIXTURES / 'fx_usd_invoice_cad_income.txt'
RATES = FIXTURES / 'fx_rates_usd_dated.yaml'
PAID = FIXTURES / 'inv_usd_001_paid_100_usd_from_the_cad_bank_at_1_37.txt'
SOLD = FIXTURES / 'forty_usd_sold_against_an_uncollected_invoice_by_force.txt'


def _run(*args):
    return CliRunner().invoke(cli, [str(arg) for arg in args])


def _done(*args):
    result = _run(*args)
    assert result.exit_code == 0, result.output
    return result


def _a_book(tmp_path):
    book = tmp_path / 'book.gnucash'
    _done('import', '--new', book, BOOK, '--include-business-objects', '--fx-rates', RATES)
    return book


def _the_posting_block(book, tmp_path):
    """INV-USD-001's posting transaction as the export writes it, and the guid of its receivable split."""
    out = tmp_path / 'out.txt'
    _done('export', book, out, '--include-business-objects')
    block = next(part for part in out.read_text().split('\n\n') if 'txn_type: I' in part)
    guid = re.search(r'Assets:Accounts Receivable USD 100\.00 USD\n\t+guid: "([0-9a-f]+)"',
                     block).group(1)
    return block, guid


def _pay(book):
    return _run('import', book, PAID, '--include-business-objects', '--fx-rates', RATES)


def test_too_little_left_is_refused_stating_both_figures(tmp_path):
    book = _a_book(tmp_path)
    _, basis = _the_posting_block(book, tmp_path)
    sold = tmp_path / 'sold.txt'
    sold.write_text(SOLD.read_text().replace('BASIS', basis))
    _done('import', book, sold)

    result = _pay(book)

    assert result.exit_code != 0, result.output
    assert (f'converts 100.00 USD but cost basis {basis} has only 60.00 left'
            in result.output), result.output


def test_no_balance_is_refused_and_a_stated_one_lets_it_through(tmp_path):
    book = _a_book(tmp_path)
    _, basis = _the_posting_block(book, tmp_path)
    repo = GnuCashRepository(str(book))
    repo.open(SessionMode.NORMAL)
    try:
        split = find_split_by_guid(repo.book, basis)
        metadata = dict(get_custom_metadata(split))
        del metadata[COST_BASIS_BALANCE_KEY]
        transaction = split.GetParent()
        transaction.BeginEdit()
        set_custom_metadata(split, metadata)
        transaction.CommitEdit()
        repo.save()
    finally:
        repo.close()

    refused = _pay(book)

    assert refused.exit_code != 0, refused.output
    assert f'cost basis {basis} has no balance recorded' in refused.output, refused.output
    block, _ = _the_posting_block(book, tmp_path)
    assert COST_BASIS_BALANCE_KEY not in block, block
    guid_line = f'\t\tguid: "{basis}"\n'
    stated = tmp_path / 'stated.txt'
    stated.write_text(block.replace(guid_line, guid_line + '\t\tcost_basis_balance: "100.00"\n')
                      + '\n')
    _done('import', book, stated, '--strategy', 'update')
    paid = _pay(book)
    assert paid.exit_code == 0, paid.output
    assert 'invoice "INV-USD-001": updated' in paid.output, paid.output
