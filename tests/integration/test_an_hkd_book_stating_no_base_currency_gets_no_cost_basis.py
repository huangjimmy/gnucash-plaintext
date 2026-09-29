"""What a book kept in Hong Kong dollars that states no base currency gets from cost bases: none.

A book is measured in the base currency its `company` block states, and one
stating none is measured in Canadian dollars, as every book was before Q-056.
This book is kept in Hong Kong dollars, states no base currency and states no
Canadian figure, so it opens no cost basis, and nothing that depends on one
applies to it:

* a spend that states no guid is not refused, because there is no cost basis to
  state;
* the shares carry no cost;
* the balance sheet leaves `realized_gains_fx` and `realized_gains_other` off
  rather than stating a gain it did not measure, and takes GnuCash's own
  revaluation for the unrealized figures;
* `--verify-integrity` finds the book consistent, drawn in its own currency.

Stating `base_currency: "HKD"` is what changes it: the costs are then recorded
in Hong Kong dollars, as
`tests/scenario/test_a_hong_kong_company_measures_its_usd_cny_and_eur_in_hkd.py`
states for a company that does.

`tests/fixtures/an_hkd_book_holding_us_dollars_and_shares.txt`.
"""

from click.testing import CliRunner

from cli.main import cli
from tests.conftest import _run
from tests.integration.text_report_pages import book_from, key_of

LEDGER = 'an_hkd_book_holding_us_dollars_and_shares.txt'


def test_the_book_imports_whole_and_keeps_no_cost_basis(tmp_path):
    book = tmp_path / 'book.gnucash'
    done = CliRunner().invoke(cli, ['import', '--new', str(book),
                                    f'tests/fixtures/{LEDGER}'])
    listing = CliRunner().invoke(cli, ['fx-balances', str(book)]).output

    assert 'Errors:       0' in done.output, done.output
    assert 'No foreign-currency cost bases found.' in listing, listing


def test_the_sheet_balances_and_states_no_realized_gain(tmp_path):
    drawn = _run(CliRunner(), 'balance-sheet', str(book_from(tmp_path, LEDGER)),
                 '--as-of', '2027-12-31', '--no-itemize')
    assert drawn.exit_code == 0, drawn.output

    assert key_of(drawn.output, 'total_assets') == '105790.00 HKD'
    assert key_of(drawn.output, 'total_liabilities_and_equity') == '105790.00 HKD'
    assert 'realized_gains_fx' not in drawn.output.replace('unrealized_gains_fx', ''), \
        drawn.output


def test_the_integrity_check_finds_it_consistent(tmp_path):
    checked = CliRunner().invoke(cli, ['--verify-integrity', str(book_from(tmp_path, LEDGER))])

    assert checked.exit_code == 0, checked.output
    assert '  as of 2027-06-30, in HKD' in checked.output.splitlines(), checked.output
    assert 'The book is consistent and balanced.' in checked.output, checked.output
