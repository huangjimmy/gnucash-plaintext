"""Does the book record how a payment came to be — linked, or applied?

`unlink` undoes an invoice's payment by unlinking the transaction that paid it.
`unapply-payment` peels off a payment `gncOwnerApplyPaymentSecs` created. They
run the same code, and the question is whether anything in the book tells the
two apart, so `unlink` can refuse the one it does not mean.

`xaccTransGetTxnType` is the candidate: the engine stamps 'P' on a payment it
creates and 'I' on a posting. A transaction the bank feed wrote and a person
later linked was never through that path, so it looked as though it would read
as no type at all.

**Measured on GnuCash 5.10, and it does not tell them apart:**

| the transaction | `xaccTransGetTxnType` |
|---|---|
| the bank's own entry, before anything links it | `'\\x00'` — no type |
| the same entry, after a `payment:` block links it | `'P'` |
| a payment `ApplyPayment` created from a `payment:` block | `'P'` |

Linking *makes* the entry a payment in the book's own terms, and from then on
it is recorded exactly as one the engine created. So `unlink` cannot refuse a
payment it did not link, and `unapply-payment` cannot refuse one it did: the
two commands are one operation, and which name fits is the reader's to know.
This is CLAUDE.md finding 10 in another place — the book holds the state, not
the history that reached it.

Run:
    ./scripts/test.sh latest tests/research/what_tells_a_linked_payment_from_an_applied_one_probe.py
"""

import ctypes
from pathlib import Path

from click.testing import CliRunner
from gnucash import Query, Transaction

from cli.main import cli
from infrastructure.gnucash.engine import load_gnc_engine
from infrastructure.gnucash.utils import get_account_full_name
from repositories.gnucash_repository import GnuCashRepository, SessionMode

FIXTURES = Path('tests/fixtures')


def _txn_types(path):
    """Every transaction in the book: description, txn type, and the accounts
    its splits are on."""
    lib = load_gnc_engine()
    lib.xaccTransGetTxnType.restype = ctypes.c_char
    lib.xaccTransGetTxnType.argtypes = [ctypes.c_void_p]
    repo = GnuCashRepository(str(path))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        query = Query()
        query.search_for('Trans')
        query.set_book(repo.book)
        rows = []
        for raw in query.run():
            transaction = Transaction(instance=raw)
            raw_type = lib.xaccTransGetTxnType(int(transaction.instance))
            rows.append({
                'description': transaction.GetDescription(),
                'txn_type': raw_type.decode('ascii', 'replace') if raw_type else '',
                'accounts': sorted(get_account_full_name(s.GetAccount())
                                   for s in transaction.GetSplitList()),
            })
        query.destroy()
        return rows
    finally:
        repo.close()


def test_what_a_linked_payment_reads_as(tmp_path, capsys):
    """The Q-039 book: a USD invoice settled by a split of a CAD entry."""
    path = tmp_path / 'linked.gnucash'
    runner = CliRunner()
    assert runner.invoke(cli, [
        'import', '--new', str(path), str(FIXTURES / 'fx_usd_invoice_cad_income.txt'),
        '--include-business-objects',
        '--fx-rates', str(FIXTURES / 'fx_rates_usd_dated.yaml')]).exit_code == 0
    assert runner.invoke(cli, [
        'import', str(path),
        str(FIXTURES / 'money_parked_in_usd_that_reached_a_cad_bank.txt')]).exit_code == 0

    with capsys.disabled():
        print('\n--- the bank entry before anything links it ---')
        for row in _txn_types(path):
            print(f"  {row['txn_type']!r}  {row['description']!r}  {row['accounts']}")

    assert runner.invoke(cli, [
        'import', str(path),
        str(FIXTURES / 'a_payment_giving_the_usd_split_behind_a_cad_bank.txt'),
        '--include-business-objects',
        '--fx-rates', str(FIXTURES / 'fx_rates_usd_dated.yaml')]).exit_code == 0

    with capsys.disabled():
        print('\n--- linked (payment: with txn_guid:) ---')
        for row in _txn_types(path):
            print(f"  {row['txn_type']!r}  {row['description']!r}  {row['accounts']}")


def test_what_an_applied_payment_reads_as(tmp_path, capsys):
    """The ordinary book: payments the engine created from `payment:` blocks."""
    path = tmp_path / 'applied.gnucash'
    assert CliRunner().invoke(cli, [
        'import', '--new', str(path),
        str(FIXTURES / 'invoices_in_each_state_to_unapply.txt'),
        '--include-business-objects']).exit_code == 0

    with capsys.disabled():
        print('\n--- applied (payment: creating a transaction) ---')
        for row in _txn_types(path):
            print(f"  {row['txn_type']!r}  {row['description']!r}  {row['accounts']}")
