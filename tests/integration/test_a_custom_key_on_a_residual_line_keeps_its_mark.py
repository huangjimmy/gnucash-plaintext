"""A custom key on a `$residual$` line does not cost the split its mark.

Which split took the residual is recorded in a `took_the_residual` KVP, and a
KVP lives in the split's `plaintext_metadata` slot. So does every custom key a
file writes under a split line, and `set_custom_metadata` replaces that slot
whole rather than merging into it.

Marked before those custom keys were stored, the mark was overwritten by them.
Nothing reported it: the transaction imported at exit 0, the sale's gain simply
never reached `realized_gains_fx`, and because the export writes the figure the
residual resolved to rather than the token, the ledger that book writes could
not put the mark back either.

Every residual line in the rest of the suite carries reserved keys only —
`share_price:`, `value:`, `cost_basis_split_guid:` — which are stored as fields
rather than in that slot, so nothing else here reaches the case.
"""

import re
from pathlib import Path

from click.testing import CliRunner

from tests.conftest import _run
from tests.integration.text_report_pages import key_of

BOUGHT = 'tests/fixtures/a_cad_book_that_bought_a_thousand_usd.txt'
PLAIN = 'tests/fixtures/the_thousand_usd_sold_at_a_higher_rate.txt'
WITH_A_CUSTOM_KEY = ('tests/fixtures/'
                     'the_thousand_usd_sold_with_a_custom_key_on_the_residual.txt')
AS_OF = '2026-12-31'


def _sold(runner, tmp_path, sale, name):
    """The purchase, then `sale` on top of it, in a book of its own."""
    book = tmp_path / f'{name}.gnucash'
    bought = _run(runner, 'import', '--new', str(book), BOUGHT)
    assert bought.exit_code == 0, bought.output

    listing = _run(runner, 'fx-balances', str(book))
    assert listing.exit_code == 0, listing.output
    found = re.search(r'\b([0-9a-f]{32})\b', listing.output)
    assert found, listing.output

    ledger = tmp_path / f'{name}.txt'
    ledger.write_text(
        Path(sale).read_text(encoding='utf-8').replace('{usd_basis}', found.group(1)),
        encoding='utf-8')
    landed = _run(runner, 'import', str(book), str(ledger))
    assert landed.exit_code == 0, landed.output
    return book


def _page(runner, book):
    drawn = _run(runner, 'balance-sheet', str(book), '--as-of', AS_OF)
    assert drawn.exit_code == 0, drawn.output
    return drawn.output


def test_the_gain_is_still_counted(tmp_path):
    """1,000.00 USD costing 1,300.00 CAD fetched 1,400.00."""
    runner = CliRunner()
    page = _page(runner, _sold(runner, tmp_path, WITH_A_CUSTOM_KEY, 'keyed'))

    assert key_of(page, 'realized_gains_fx') == '100.00 CAD'
    assert key_of(page, 'total_realized_gains') == '100.00 CAD'


def test_the_custom_key_is_no_difference_to_the_page(tmp_path):
    """The key is the reader's own note; the statement must not turn on it."""
    runner = CliRunner()
    keyed = _page(runner, _sold(runner, tmp_path, WITH_A_CUSTOM_KEY, 'keyed'))
    plain = _page(runner, _sold(runner, tmp_path, PLAIN, 'plain'))

    assert keyed == plain


def test_the_working_still_states_the_gain(tmp_path):
    runner = CliRunner()
    page = _page(runner, _sold(runner, tmp_path, WITH_A_CUSTOM_KEY, 'keyed'))

    listed = [line.strip() for line in page.splitlines()
              if line.lstrip().startswith('#   ') and 'Income:FX Gain' in line]
    assert listed == ['#   2026-06-01 Income:FX Gain 100.00 CAD'], page


def test_the_custom_key_survives_the_round_trip(tmp_path):
    """Both keys share one slot, so keeping the mark must not cost the key."""
    runner = CliRunner()
    book = _sold(runner, tmp_path, WITH_A_CUSTOM_KEY, 'keyed')
    out = tmp_path / 'exported.txt'
    wrote = _run(runner, 'export', str(book), str(out))
    assert wrote.exit_code == 0, wrote.output

    text = out.read_text(encoding='utf-8')
    assert 'department: "ops"' in text, text
    assert 'took_the_residual: "true"' in text, text
