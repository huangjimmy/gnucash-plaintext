"""Whether a book opened and closed stays in memory: a session only ended, against `GnuCashRepository.close`.

This builds one book of 300 transactions, then opens it and closes it 100
times each way, printing the process's resident memory every 20 rounds:

- `session.end()` alone, which is all `GnuCashRepository.close` once did;
- `GnuCashRepository.close`, which destroys the session: `destroy()` ends it
  and frees the book.

Measured on GnuCash 5.10: `end()` alone kept about 0.5 MiB per open (35 MiB to
84 MiB over 100 opens); ended and destroyed, memory stayed flat.

Measured on GnuCash 3.8 once `close` called `destroy()` alone: `end()` alone
went from 59.9 MiB to 110.8 MiB over 100 opens; `close` from 111.4 MiB to
111.7 MiB.

Run:

    docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp/home \
        -e PYTHONPATH=/workspace -v "$PWD:/workspace" -w /workspace \
        gnucash-dev:<tag> python3 tests/research/what_a_closed_book_keeps_in_memory_probe.py
"""

import gc
import os
import tempfile

from gnucash import Account, GncNumeric, Split, Transaction

from repositories.gnucash_repository import GnuCashRepository, SessionMode

ROUNDS = 100
EVERY = 20


def resident_mib():
    with open('/proc/self/status') as status:
        for line in status:
            if line.startswith('VmRSS:'):
                return int(line.split()[1]) / 1024
    return 0.0


def build_book(path, transactions=300):
    repo = GnuCashRepository(path)
    repo.open(SessionMode.NEW)
    book = repo.book
    cad = book.get_table().lookup('CURRENCY', 'CAD')
    root = book.get_root_account()
    accounts = []
    for label in ('Bank', 'Groceries'):
        account = Account(book)
        account.BeginEdit()
        account.SetName(label)
        account.SetType(2 if label == 'Bank' else 9)
        account.SetCommodity(cad)
        root.append_child(account)
        account.CommitEdit()
        accounts.append(account)
    bank, groceries = accounts
    for i in range(transactions):
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


def rounds(path, end_only):
    for i in range(1, ROUNDS + 1):
        repo = GnuCashRepository(path)
        repo.open(SessionMode.READ_ONLY)
        if end_only:
            session = repo.session
            repo.session = None
            repo._book = None
            session.end()
            del session
        else:
            repo.close()
        del repo
        if i % EVERY == 0:
            gc.collect()
            print(f'  after {i:3d} opens: {resident_mib():7.1f} MiB', flush=True)


def main():
    directory = tempfile.mkdtemp()
    path = os.path.join(directory, 'book.gnucash')
    build_book(path)
    print(f'book of 300 transactions: {os.path.getsize(path)} bytes on disk')
    gc.collect()
    print(f'before any open: {resident_mib():7.1f} MiB')
    print('session.end() alone:')
    rounds(path, end_only=True)
    print('GnuCashRepository.close(), which destroys the session:')
    rounds(path, end_only=False)


if __name__ == '__main__':
    main()
