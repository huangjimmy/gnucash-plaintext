"""Every split that spends foreign currency the book keeps a cost basis for draws on one of its own side.

`tests/fixtures/us_dollars_spent_from_two_banks_one_giving_no_cost_basis.txt`
spends 100.00 USD out of one bank giving that bank's cost basis, and 50.00 USD
out of a second bank giving none.

`tests/fixtures/us_dollars_spent_from_the_bank_giving_a_loans_cost_basis.txt`
spends 100.00 USD out of the bank giving the cost basis of a loan, which stands
for dollars owed, not dollars held.

Either way the book would be left with cost bases that no longer match what its
accounts hold and owe, so the sale is refused, and `--verify-integrity` finds
the book consistent afterwards.
"""

from click.testing import CliRunner

from cli.main import cli

TWO_BANKS = 'tests/fixtures/us_dollars_spent_from_two_banks_one_giving_no_cost_basis.txt'
A_LOANS_COST_BASIS = 'tests/fixtures/us_dollars_spent_from_the_bank_giving_a_loans_cost_basis.txt'


def _imported(tmp_path, ledger):
    book = tmp_path / 'book.gnucash'
    done = CliRunner().invoke(cli, ['import', '--new', str(book), ledger])
    return book, done


class TestASplitGivingNoCostBasisBesideOneThatGivesOne:
    def test_the_sale_is_refused(self, tmp_path):
        _, done = _imported(tmp_path, TWO_BANKS)

        assert 'Errors:       1' in done.output, done.output
        assert ('this transaction spends 50.00 USD the book held, which draws '
                'down a cost basis, but no split says which one') in done.output, done.output

    def test_the_cost_bases_still_match_the_accounts(self, tmp_path):
        book, _ = _imported(tmp_path, TWO_BANKS)
        checked = CliRunner().invoke(cli, ['--verify-integrity', str(book)])

        assert checked.exit_code == 0, checked.output


class TestAHeldSplitGivingTheCostBasisOfADebt:
    def test_the_sale_is_refused(self, tmp_path):
        _, done = _imported(tmp_path, A_LOANS_COST_BASIS)

        assert 'Errors:       1' in done.output, done.output
        assert ("cost_basis_split_guid '0f0f0000000000000000000000000013' is a "
                'cost basis of USD the book owed, but this split spends USD the '
                'book held') in done.output, done.output

    def test_the_cost_bases_still_match_the_accounts(self, tmp_path):
        book, _ = _imported(tmp_path, A_LOANS_COST_BASIS)
        checked = CliRunner().invoke(cli, ['--verify-integrity', str(book)])

        assert checked.exit_code == 0, checked.output
