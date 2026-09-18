"""Does GnuCash's own report agree with `unrealized_gains_other` on shares held?

The securities half of the same question `what_gnucash_computes_as_a_securitys_realized_gain_probe.py`
asks about a disposal, on a book that disposes of nothing: a Canadian company
buys 12 NASDAQ:AMZN at 200.00 USD with the US dollar at 1.30 — 3,120.00 CAD —
and still holds every share at the year end, with the share at 280.00 USD and
the dollar at 1.42.

The book holds **no foreign currency at all**, which is what makes it worth
asking here. On a book holding currency and shares together the two figures
share a page and a reader cannot tell which computation produced which; here
`unrealized_gains_fx` is 0.00 and every penny of the gain is the shares'.

The two arithmetics share no code. The balance sheet takes each account's
converted balance less the sum of its splits' values; Advanced Portfolio takes
value less basis, through its own basis logic. Agreement is therefore a real
check rather than a restatement — which is the same reason the drift book's
1,363.20 is quoted twice over.

Run it: ./scripts/run.sh python3 tests/research/whether_gnucash_agrees_on_the_gain_on_shares_still_held_probe.py
"""

import sys
import tempfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from what_gnucash_computes_as_a_securitys_realized_gain_probe import (  # noqa: E402
    _render_advanced_portfolio,
    _report,
)

FIXTURE = 'tests/fixtures/a_cad_book_holding_us_listed_shares.txt'
AS_OF = date(2026, 12, 31)


def main():
    from click.testing import CliRunner

    from cli.main import cli
    from repositories.gnucash_repository import GnuCashRepository

    work = Path(tempfile.mkdtemp(prefix='shares-held-book-'))
    book_path = work / 'book.gnucash'
    made = CliRunner().invoke(cli, ['import', '--new', str(book_path), FIXTURE])
    if made.exit_code != 0:
        print(made.output)
        return 1
    # The backup a second save would collide with, the way conftest does it.
    for stale in work.glob('book.gnucash.2*'):
        stale.unlink()

    sheet = CliRunner().invoke(
        cli, ['balance-sheet', str(book_path), '--as-of', str(AS_OF)])
    if sheet.exit_code != 0:
        print(sheet.output)
        return 1

    print('=== what gnucash-plaintext states ===')
    for line in sheet.output.splitlines():
        if 'gains' in line or 'balancing' in line or 'total_assets' in line:
            print(f'  {line.strip()}')

    repo = GnuCashRepository(str(book_path))
    repo.open()
    try:
        html = _render_advanced_portfolio(repo.session, 'CAD', AS_OF)
    finally:
        repo.close()

    print()
    print("=== what GnuCash's Advanced Portfolio computes, its own defaults ===")
    return _report(html)


if __name__ == '__main__':
    sys.exit(main())
