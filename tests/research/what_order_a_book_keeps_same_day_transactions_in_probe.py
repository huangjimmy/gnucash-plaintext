"""Probe: what order a book hands its same-day transactions over in.

Three questions, in the order the export has to answer them:

1. what the bindings give for a transaction's entered timestamp, and at what
   resolution — the deposit of the Q-040 fee book was created by one import
   and the fee by the next;
2. what order `get_all_transactions` returns, which is `qof_query_run`, and
   whether it is already `xaccTransOrder`;
3. what the export writes for a book whose fee draws on a deposit of the same
   day, and whether that file rebuilds the book.

    ./scripts/test.sh latest tests/research/what_order_a_book_keeps_same_day_transactions_in_probe.py
"""

import re
from pathlib import Path

from click.testing import CliRunner
from gnucash.gnucash_core_c import xaccTransOrder

from cli.main import cli
from repositories.gnucash_repository import GnuCashRepository, SessionMode
from tests.conftest import _run

RATES = 'tests/fixtures/fx_rates_usd_two_invoice_dates.yaml'


def test_what_the_bindings_give(tmp_path, capsys):
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    assert runner.invoke(cli, [
        'import', '--new', str(book),
        'tests/fixtures/fx_buy_100_usd_into_a_usd_bank.txt',
        '--fx-rates', RATES]).exit_code == 0

    out = tmp_path / 'out.txt'
    assert runner.invoke(cli, ['export', str(book), str(out)]).exit_code == 0
    basis = re.search(r'Assets:Bank:USD 100\.00 USD\n\t+guid: "([0-9a-f]{32})"',
                      out.read_text()).group(1)
    fee = tmp_path / 'fee.txt'
    fee.write_text(
        Path('tests/fixtures/fx_fee_drawn_from_the_purchase.txt').read_text()
        .replace('{basis}', basis))
    assert runner.invoke(cli, ['import', str(book), str(fee),
                               '--fx-rates', RATES]).exit_code == 0

    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        rows = []
        for transaction in repo.get_all_transactions():
            entered = getattr(transaction, 'GetDateEntered', None)
            rows.append((transaction.GetDescription(),
                         str(transaction.GetDate()),
                         repr(entered()) if entered else 'no GetDateEntered',
                         transaction.GetGUID().to_string()[:8]))
    finally:
        repo.close()

    with capsys.disabled():
        print()
        for row in rows:
            print(' | '.join(row))


def _a_deposit_and_a_fee_of_the_same_day(runner, tmp_path):
    """The Q-040 book, sound: 2720.00 USD in, and a 0.72 USD fee drawn on it.

    Two imports, so the two transactions are entered a moment apart — which
    used to be a second apart, because every command in the suite slept.
    """
    book = tmp_path / 'book.gnucash'
    assert runner.invoke(cli, [
        'import', '--new', str(book),
        'tests/fixtures/fx_two_usd_invoices_posted.txt',
        '--include-business-objects', '--fx-rates', RATES]).exit_code == 0
    assert _run(runner, 'import', str(book),
                'tests/fixtures/fx_usd_deposit_against_due_from_director.txt'
                ).exit_code == 0
    assert _run(runner, 'import', str(book),
                'tests/fixtures/fx_fee_drawn_from_the_deposits_basis.txt'
                ).exit_code == 0
    return book


def test_what_the_query_returns_and_what_the_export_writes(tmp_path, capsys):
    runner = CliRunner()
    book = _a_deposit_and_a_fee_of_the_same_day(runner, tmp_path)

    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        given = repo.get_all_transactions()
        rows = [(t.GetDescription()[:34], str(t.GetDate())[:10],
                 repr(t.GetDateEntered())) for t in given]
        pairs = []
        for one in given:
            for other in given:
                if one.GetDate() == other.GetDate() and one is not other:
                    pairs.append((one.GetDescription()[:34],
                                  other.GetDescription()[:34],
                                  xaccTransOrder(one.instance,
                                                 other.instance)))
    finally:
        repo.close()

    out = tmp_path / 'out.txt'
    assert _run(runner, 'export', str(book), str(out)).exit_code == 0
    written = re.findall(r'^\d{4}-\d\d-\d\d \* "([^"]*)"', out.read_text(),
                         re.M)

    fresh = tmp_path / 'fresh.gnucash'
    rebuilt = _run(runner, 'import', '--new', str(fresh), str(out))

    with capsys.disabled():
        print()
        print('what get_all_transactions returns, in that order:')
        for row in rows:
            print('   ', ' | '.join(row))
        print('xaccTransOrder, of the pairs sharing a date '
              '(negative = the first comes first):')
        for one, other, verdict in pairs:
            print(f'    {one} vs {other}: {verdict}')
        print('what the export writes, in that order:')
        for description in written:
            print('   ', description)
        print(f'the export re-imported into a fresh book: '
              f'exit {rebuilt.exit_code}')
        for line in rebuilt.output.splitlines():
            if 'rror' in line or 'cost basis' in line:
                print('   ', line)
