"""A closed book is freed, so a process that opens many books does not keep them all.

`GnuCashRepository.close` ended the session and never destroyed it, and an
ended session keeps its whole book in memory until the process exits. A command
opens one book, so no one running a command saw it. The test suite opens
12,056 in one process, and that process grew from about 90 MB to about 1.7 GB.

The session could not simply be destroyed as well. The importer put a split in
a lot with `xaccSplitSetLot`, which leaves the split off the lot's own split
list (CLAUDE.md finding 9), and a book holding such a split segfaults when it
is destroyed, inside `gnc_lot_remove_split`. A payment linked to an invoice is
such a split.

Measured by `tests/research/what_a_closed_book_keeps_in_memory_probe.py` and
`tests/research/whether_a_split_put_in_a_lot_survives_destroying_the_book_probe.py`;
the account of it is in
docs/issues/Q-041-a-price-cannot-be-recorded-for-a-past-date-or-kept-through-export-and-import.md.
"""

import gc
import subprocess
import sys
from pathlib import Path

from click.testing import CliRunner

from cli.main import cli
from repositories.gnucash_repository import GnuCashRepository, SessionMode

FIXTURES = Path('tests/fixtures')
OPENS = 100


def _resident_mib():
    with open('/proc/self/status') as status:
        for line in status:
            if line.startswith('VmRSS:'):
                return int(line.split()[1]) / 1024
    raise AssertionError('/proc/self/status has no VmRSS line')


def _a_book_of_300_transactions(path):
    from gnucash import Account, GncNumeric, Split, Transaction

    repo = GnuCashRepository(path)
    repo.open(SessionMode.NEW)
    book = repo.book
    cad = book.get_table().lookup('CURRENCY', 'CAD')
    accounts = []
    for label, kind in (('Bank', 2), ('Groceries', 9)):
        account = Account(book)
        account.BeginEdit()
        account.SetName(label)
        account.SetType(kind)
        account.SetCommodity(cad)
        book.get_root_account().append_child(account)
        account.CommitEdit()
        accounts.append(account)
    bank, groceries = accounts
    for i in range(300):
        tx = Transaction(book)
        tx.BeginEdit()
        tx.SetCurrency(cad)
        tx.SetDate(1 + i % 28, 1 + i % 12, 2025)
        tx.SetDescription(f'purchase {i}')
        for account, cents in ((bank, -(1000 + i)), (groceries, 1000 + i)):
            split = Split(book)
            split.SetParent(tx)
            split.SetAccount(account)
            split.SetValue(GncNumeric(cents, 100))
            split.SetAmount(GncNumeric(cents, 100))
        tx.CommitEdit()
    repo.save()
    repo.close()


def _the_deposit_guid(book):
    from gnucash import Query, Transaction

    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        query = Query()
        query.search_for('Trans')
        query.set_book(repo.book)
        guids = [Transaction(instance=raw).GetGUID().to_string() for raw in query.run()
                 if Transaction(instance=raw).GetDescription() == 'Part payment from Acme']
        query.destroy()
    finally:
        repo.close()
    assert len(guids) == 1, guids
    return guids[0]


class TestABookOpenedAndClosedAgainAndAgain:
    def test_the_process_keeps_nothing_of_it(self, tmp_path):
        path = str(tmp_path / 'book.gnucash')
        _a_book_of_300_transactions(path)
        # Opened once first, so what GnuCash loads once per process is not counted.
        repo = GnuCashRepository(path)
        repo.open(SessionMode.READ_ONLY)
        repo.close()
        gc.collect()
        before = _resident_mib()

        for _ in range(OPENS):
            repo = GnuCashRepository(path)
            repo.open(SessionMode.READ_ONLY)
            repo.close()
        gc.collect()

        kept = _resident_mib() - before
        assert kept < 10, (f'{OPENS} opens and closes of one book of 300 '
                           f'transactions kept {kept:.1f} MiB')


class TestABookAPaymentWasLinkedInto:
    """An import that links a deposit to an invoice puts a split in the invoice's lot."""

    def test_its_import_frees_the_book_and_exits_cleanly(self, tmp_path):
        runner = CliRunner()
        book = tmp_path / 'book.gnucash'
        assert runner.invoke(cli, ['import', '--new', str(book),
                                   str(FIXTURES / 'payment_roundtrip_accounts.txt')]).exit_code == 0
        assert runner.invoke(cli, ['import', str(book),
                                   str(FIXTURES / 'a_loose_deposit_to_retarget.txt')]).exit_code == 0
        ledger = tmp_path / 'ledger.txt'
        ledger.write_text((FIXTURES / 'an_invoice_with_a_bare_retarget_and_a_payment.txt')
                          .read_text().replace('TXN_GUID', _the_deposit_guid(book)))

        # In a child process: a segfault ends that process, and this one reports it.
        # The child is not run by pytest, so it imports the suite's conftest,
        # whose `_patch_session_save` deletes GnuCash's backup before each save.
        # After the command line, which loads the page engine before GnuCash
        # (CLAUDE.md finding 23).
        run = subprocess.run(
            [sys.executable, '-c',
             'from cli.main import cli; import tests.conftest; cli()',
             'import', str(book), str(ledger),
             '--include-business-objects'],
            capture_output=True, text=True)

        assert run.returncode == 0, (run.returncode, run.stdout, run.stderr)
