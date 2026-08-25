"""Q-035: a receivable that has not been collected holds no currency to sell.

An invoice's A/R split states what a customer owes, not what the book has.
Measuring a sale against it before the invoice is paid is selling money that has
not arrived, so it is refused by default — this tool keeps books, it does not
support trading a position it does not hold. `cost_basis_force: true` overrides
it for the case where the money is in hand and the record simply has not been
marked paid.

A payable is not restricted: its lot is open precisely until the bill is paid,
and settling it with foreign cash is the ordinary way that happens (covered in
test_residual_split.py and test_unpost_foreign_currency.py).
"""

import re
import time
from pathlib import Path

from click.testing import CliRunner

from cli.main import cli

RATES = 'tests/fixtures/fx_rates_usd_dated.yaml'


def _run(runner, *args):
    time.sleep(1.1)
    return runner.invoke(cli, list(args))


def _balances(runner, book):
    result = runner.invoke(cli, ['fx-balances', str(book)])
    assert result.exit_code == 0, result.output
    return result.output


def _sale_against(tmp_path, basis, forced=False, name='sale.txt'):
    text = (Path('tests/fixtures/fx_sell_usd_partial.txt').read_text()
            .replace('{basis_a}', basis)
            .replace('share_price: "1.35"', 'share_price: "1.40"')
            .replace('value: "-54.00"', 'value: "-56.00"'))
    if forced:
        text = text.replace(f'cost_basis_split_guid: "{basis}"',
                            f'cost_basis_split_guid: "{basis}"\n'
                            f'\t\tcost_basis_force: true')
    path = tmp_path / name
    path.write_text(text)
    return str(path)


def _unpaid_invoice_book(runner, tmp_path):
    book = tmp_path / 'book.gnucash'
    assert _run(runner, 'import', '--new', str(book),
                'tests/fixtures/fx_usd_invoice_cad_income.txt',
                '--include-business-objects', '--fx-rates', RATES).exit_code == 0
    basis = re.search(r'\b([0-9a-f]{32})\b', _balances(runner, book)).group(1)
    return book, basis


def test_selling_against_an_uncollected_receivable_is_refused(tmp_path):
    runner = CliRunner()
    book, basis = _unpaid_invoice_book(runner, tmp_path)

    result = _run(runner, 'import', str(book), _sale_against(tmp_path, basis))
    message = result.output + str(result.exception)
    assert 'has not been collected' in message, message
    # What is uncollected is the invoice, not the basis. A cost basis is what
    # something was acquired for; whether it has been collected is a fact
    # about the receivable the split sits on, and calling the basis itself
    # "an unpaid receivable" states neither.
    assert 'unpaid receivable' not in message, message
    assert 'owed, not held' in message, message

    # Nothing was recorded against it.
    assert 'Total USD basis balance: 100.00 USD' in _balances(runner, book)


def test_the_refusal_can_be_forced(tmp_path):
    runner = CliRunner()
    book, basis = _unpaid_invoice_book(runner, tmp_path)

    result = _run(runner, 'import', str(book),
                  _sale_against(tmp_path, basis, forced=True, name='forced.txt'))
    assert result.exit_code == 0, result.output
    assert 'error:' not in result.output, result.output
    assert 'Total USD basis balance: 60.00 USD' in _balances(runner, book)


def test_a_mistyped_override_is_refused_by_name(tmp_path):
    """As every other flag in a ledger is. Compared against a list of the
    truthy spellings, `cost_basis_force: treu` was silently *not* forced —
    and the sale then failed with the uncollected-invoice message, which
    tells its author to add the key they had just added."""
    runner = CliRunner()
    book, basis = _unpaid_invoice_book(runner, tmp_path)
    sale = Path(_sale_against(tmp_path, basis, forced=True,
                              name='mistyped.txt'))
    sale.write_text(sale.read_text().replace('cost_basis_force: true',
                                             'cost_basis_force: treu'))

    result = _run(runner, 'import', str(book), str(sale))

    message = result.output + str(result.exception)
    assert 'cost_basis_force' in message, message
    assert 'neither true nor false' in message, message
    assert 'has not been collected' not in message, message


def test_a_mistyped_override_is_named_even_where_it_would_change_nothing(
        tmp_path):
    """The flag is read before every reason this check has to return early —
    a settled lot, a payable, an overpayment — so a typo is named wherever a
    file states it. Read where it is used, the same typo was refused on a
    sale against an unpaid invoice and ignored on a sale against a paid one,
    which is the reader learning the rule from whichever sale they wrote
    first."""
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    assert _run(runner, 'import', '--new', str(book),
                'tests/fixtures/fx_invoice_usd_paid_from_usd_bank.txt',
                '--include-business-objects', '--fx-rates',
                RATES).exit_code == 0
    basis = re.search(r'\b([0-9a-f]{32})\b', _balances(runner, book)).group(1)
    sale = Path(_sale_against(tmp_path, basis, forced=True, name='paid.txt'))
    sale.write_text(sale.read_text().replace('cost_basis_force: true',
                                             'cost_basis_force: treu'))

    result = _run(runner, 'import', str(book), str(sale))

    message = result.output + str(result.exception)
    assert 'cost_basis_force' in message, message
    assert 'neither true nor false' in message, message


def test_the_override_takes_every_spelling_of_true(tmp_path):
    """The other half of making it strict: a key that stopped accepting what
    it always accepted would be worse than the typo it now catches."""
    for spelling in ('True', '1', 'yes'):
        runner = CliRunner()
        # A book of its own per spelling: `import --new` will not write over
        # one already there.
        where = tmp_path / spelling
        where.mkdir()
        book, basis = _unpaid_invoice_book(runner, where)
        sale = Path(_sale_against(where, basis, forced=True,
                                  name=f'{spelling}.txt'))
        sale.write_text(sale.read_text().replace(
            'cost_basis_force: true', f'cost_basis_force: {spelling}'))

        result = _run(runner, 'import', str(book), str(sale))

        assert result.exit_code == 0, f'{spelling}: {result.output}'
        assert 'error:' not in result.output, f'{spelling}: {result.output}'


def test_selling_is_allowed_once_the_invoice_is_paid(tmp_path):
    """Paid into a USD bank: the money is in hand, the lot is closed, and the
    basis is sellable with no override."""
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    assert _run(runner, 'import', '--new', str(book),
                'tests/fixtures/fx_invoice_usd_paid_from_usd_bank.txt',
                '--include-business-objects', '--fx-rates', RATES).exit_code == 0
    basis = re.search(r'\b([0-9a-f]{32})\b', _balances(runner, book)).group(1)

    result = _run(runner, 'import', str(book), _sale_against(tmp_path, basis))
    assert result.exit_code == 0, result.output
    assert 'error:' not in result.output, result.output
    assert 'Total USD basis balance: 60.00 USD' in _balances(runner, book)


def test_currency_bought_outright_needs_no_override(tmp_path):
    """A purchase is not a receivable — the money is already in the account."""
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    assert _run(runner, 'import', '--new', str(book),
                'tests/fixtures/fx_buy_and_borrow_usd.txt',
                '--include-business-objects').exit_code == 0
    basis = re.search(r'\b([0-9a-f]{32})\b', _balances(runner, book)).group(1)

    sale = tmp_path / 'buy_sale.txt'
    sale.write_text(Path('tests/fixtures/fx_sell_usd_partial.txt').read_text()
                    .replace('{basis_a}', basis))
    result = _run(runner, 'import', str(book), str(sale))
    assert result.exit_code == 0, result.output
    assert 'error:' not in result.output, result.output
    assert 'Total USD basis balance: 160.00 USD' in _balances(runner, book)
