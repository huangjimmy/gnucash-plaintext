"""Whether a book can be destroyed after a split was put in a lot with `xaccSplitSetLot`.

`xaccSplitSetLot` sets the split's lot without adding the split to the lot's own
split list (CLAUDE.md finding 9); `gnc_lot_add_split` does both. The importer
attached payments with `xaccSplitSetLot`, and a `GnuCashRepository.close` that
destroyed its session then segfaulted inside `qof_book_destroy`, in
`gnc_lot_remove_split`, so no session was destroyed and every book stayed in
memory (Q-041).

Each case runs in a child process of its own, so a crash in one does not hide
what another does:

- `set-lot`: `xaccSplitSetLot`, then end and destroy the session;
- `add-split`: `gnc_lot_add_split`, then end and destroy the session;
- `set-lot-saved`: `xaccSplitSetLot`, save, then end and destroy;
- `add-split-other-account`: `gnc_lot_add_split` handed a split whose account
  is not the lot's.

Measured on GnuCash 5.10: both `set-lot` cases segfault (exit -11); `add-split`
is destroyed cleanly; `add-split-other-account` attaches nothing and says
nothing — the split is in no lot afterwards and the lot lists no split.

Run:

    docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp/home \
        -e PYTHONPATH=/workspace -v "$PWD:/workspace" -w /workspace \
        gnucash-dev:<tag> python3 tests/research/whether_a_split_put_in_a_lot_survives_destroying_the_book_probe.py
"""

import os
import subprocess
import sys
import tempfile

VARIANTS = ('set-lot', 'add-split', 'set-lot-saved', 'add-split-other-account')


def child(variant):
    from gnucash import Account, GncLot, GncNumeric, Split, Transaction
    from gnucash import gnucash_core_c as gc

    from infrastructure.gnucash.engine import load_gnc_engine
    from repositories.gnucash_repository import GnuCashRepository, SessionMode

    path = os.path.join(tempfile.mkdtemp(), 'book.gnucash')
    repo = GnuCashRepository(path)
    repo.open(SessionMode.NEW)
    book = repo.book
    cad = book.get_table().lookup('CURRENCY', 'CAD')
    root = book.get_root_account()

    accounts = []
    for label, kind in (('Receivable', 11), ('Bank', 2)):
        account = Account(book)
        account.BeginEdit()
        account.SetName(label)
        account.SetType(kind)
        account.SetCommodity(cad)
        root.append_child(account)
        account.CommitEdit()
        accounts.append(account)
    receivable, bank = accounts

    tx = Transaction(book)
    tx.BeginEdit()
    tx.SetCurrency(cad)
    tx.SetDate(5, 1, 2026)
    tx.SetDescription('payment')
    splits = []
    for account, cents in ((bank, 10000), (receivable, -10000)):
        split = Split(book)
        split.SetParent(tx)
        split.SetAccount(account)
        split.SetValue(GncNumeric(cents, 100))
        split.SetAmount(GncNumeric(cents, 100))
        splits.append(split)
    tx.CommitEdit()

    lot = GncLot(book)
    receivable.InsertLot(lot)
    if variant == 'add-split':
        load_gnc_engine().gnc_lot_add_split(int(lot.instance), int(splits[1].instance))
    elif variant == 'add-split-other-account':
        # The bank split, whose account is not the lot's.
        load_gnc_engine().gnc_lot_add_split(int(lot.instance), int(splits[0].instance))
        in_lot = splits[0].GetLot() is not None
        listed = len(lot.get_split_list())
        print(f'{variant}: split in a lot afterwards: {in_lot}; lot lists {listed} split(s)',
              flush=True)
    else:
        gc.xaccSplitSetLot(splits[1].instance, lot.instance)

    if variant == 'set-lot-saved':
        repo.save()
    session = repo.session
    session.end()
    print(f'{variant}: ended; destroying', flush=True)
    session.destroy()
    print(f'{variant}: destroyed', flush=True)


def main():
    if len(sys.argv) > 1:
        child(sys.argv[1])
        return
    for variant in VARIANTS:
        run = subprocess.run([sys.executable, __file__, variant],
                             capture_output=True, text=True)
        lines = [line for line in run.stdout.splitlines() if line.startswith(variant)]
        print(f'{variant:14s} exit {run.returncode:4d}  ' + ' | '.join(lines))


if __name__ == '__main__':
    main()
