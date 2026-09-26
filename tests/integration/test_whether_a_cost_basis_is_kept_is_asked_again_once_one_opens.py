"""Whether the book keeps a cost basis is remembered through an import, and forgotten when one opens.

A spend that states no guid is refused only where the book keeps a cost basis
it could have drawn on, and answering that walks the accounts holding the
currency. It is asked of every such spend, so the answer is kept for the rest
of the import rather than walked for again each time — a book kept wholly in a
currency it holds no cost basis for otherwise pays for every payment with a
walk of every earlier one.

What a kept answer must not do is outlive what it answered.
`tests/fixtures/a_spend_before_and_after_a_cost_basis_opens_in_one_file.txt`
spends dollars no cost basis stands for, then buys dollars that open one, then
spends again stating no guid: the first spend is imported, the second refused.
"""

from click.testing import CliRunner

from cli.main import cli

LEDGER = 'tests/fixtures/a_spend_before_and_after_a_cost_basis_opens_in_one_file.txt'


def test_the_spend_before_is_imported_and_the_spend_after_is_refused(tmp_path):
    done = CliRunner().invoke(
        cli, ['import', '--new', str(tmp_path / 'book.gnucash'), LEDGER])

    assert 'Errors:       1' in done.output, done.output
    assert ('error: Sell 10.00 USD after a cost basis opened: this transaction is a '
            'sale of 10.00 USD the book held for 14.00 CAD: Assets:USD Bank, a Bank '
            'account in USD, is credited 10.00 USD; Assets:CAD Bank, a Bank account in '
            'CAD, is debited 14.00 CAD.') in done.output, done.output
    assert 'Sell 10.00 USD before any cost basis is kept:' not in done.output, done.output
    assert 'Sell 5.00 USD, still before any cost basis is kept:' not in done.output, \
        done.output
