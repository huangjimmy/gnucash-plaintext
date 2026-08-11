"""Reading an unchanged converting-payment ledger twice changes nothing.

Re-importing a file the book was built from is how every correction in this
format is made, so a ledger that imports once and is refused the second time is
a ledger that can never be edited. The comparison that decides whether a
document already matches its file is what stands between the two: judged
different, the document is rebuilt, and rebuilding a settled one has to unpost
it.

A converting payment is the shape most likely to be misjudged, because the
block states two figures — `amount:` in the document's currency and
`settled_amount:` (or `share_price:`) in the bank's — and comparing the wrong
one against the wrong split makes every such document differ from the file that
wrote it.

The third-currency fixtures are all of that shape, and each was imported once
with `--new`. This reads them twice.
"""

import pytest
from click.testing import CliRunner

from cli.main import cli

BOTH = 'tests/fixtures/fx_rates_usd_and_hkd.yaml'
RATES = 'tests/fixtures/fx_rates_usd_dated.yaml'

LEDGERS = [
    ('a USD invoice settled into an HKD bank',
     'tests/fixtures/fx_usd_invoice_settled_into_an_hkd_bank.txt', BOTH),
    ('a USD bill settled from an HKD bank',
     'tests/fixtures/fx_usd_bill_settled_from_an_hkd_bank.txt', BOTH),
    ('a USD invoice paid from a CAD bank',
     'tests/fixtures/fx_invoice_usd_overpaid_into_cad_bank.txt', RATES),
]


def _transaction_count(book):
    from gnucash import Query

    from repositories.gnucash_repository import GnuCashRepository, SessionMode

    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        query = Query()
        query.search_for('Trans')
        query.set_book(repo.book)
        count = len(list(query.run()))
        query.destroy()
        return count
    finally:
        repo.close()


@pytest.mark.parametrize('name,ledger,rates', LEDGERS,
                         ids=[entry[0] for entry in LEDGERS])
class TestReadingItTwice:
    def _twice(self, tmp_path, ledger, rates):
        runner = CliRunner()
        book = tmp_path / 'book.gnucash'
        first = runner.invoke(cli, [
            'import', '--new', str(book), ledger,
            '--include-business-objects', '--fx-rates', rates])
        assert first.exit_code == 0, first.output
        before = _transaction_count(book)
        second = runner.invoke(cli, [
            'import', str(book), ledger,
            '--include-business-objects', '--fx-rates', rates])
        return book, before, second

    def test_the_second_run_is_not_refused(self, name, ledger, rates, tmp_path):
        _book, _before, second = self._twice(tmp_path, ledger, rates)

        assert second.exit_code == 0, f'{name}: {second.output}'
        assert 'cannot be unposted' not in second.output, second.output

    def test_it_moves_no_money(self, name, ledger, rates, tmp_path):
        """Unchanged in, unchanged out — no second settlement, no rebuild."""
        book, before, _second = self._twice(tmp_path, ledger, rates)

        assert _transaction_count(book) == before, name

    def test_the_book_still_says_the_same_thing(self, name, ledger, rates,
                                                tmp_path):
        book, _before, _second = self._twice(tmp_path, ledger, rates)

        listed = CliRunner().invoke(cli, ['fx-balances', str(book),
                                          '--verify-costs'])
        assert listed.exit_code == 0, f'{name}: {listed.output}'
