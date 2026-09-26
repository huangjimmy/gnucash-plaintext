"""What an edit moving a deposit's other side to income records, when the fee's split on the same day has `$pending$`.

A user's application imports a 10.00 USD deposit and, on the same day, the
transaction that has its 1.00 USD fee, whose Wise USD split has
`cost_basis_split_guid: $pending$`. It then answers the deposit with "this
was income" by an edit moving the deposit's other side from Due from
director to Income:Sales. `fx-balances` then read the deposit as bringing in
9.00 USD, not 10.00.

Three cases, the deposit's US dollar split and its cost basis printed before
and after the edit:

- the fee's transaction on the same day, with `$pending$` on its Wise USD
  split, as reported;
- the fee's transaction on the same day, its Wise USD split drawing on the
  deposit's cost basis by guid;
- the fee's transaction on the day after the deposit, with `$pending$` on its
  Wise USD split.

And the order GnuCash keeps the two in, which is what decided it (Q-053):
the order as imported, with the moments entered a second and half a second
apart, with `num`; two transactions created in one session with their moments
set before the commit, read after a save and a reload; how two `num` texts are
ordered; what the book's export writes and whether it rebuilds the book; and
an edit restating the deposit's figure.

Run: ./scripts/test.sh latest tests/research/what_an_edit_to_a_deposit_beside_a_pending_fee_records_probe.py -s
"""

import re
from pathlib import Path

from click.testing import CliRunner

from tests.conftest import _run

FIXTURES = 'tests/fixtures/'
BASE = FIXTURES + 'a_usd_invoice_and_bill_for_statement_lines_on_a_holding_account.txt'
RATES = FIXTURES + 'usd_at_the_rates_the_statement_lines_records_were_posted_at.yaml'
LEDGER = FIXTURES + 'a_usd_deposit_and_its_fee_pending_its_cost_basis_the_same_day.txt'
HEAD = '2026-08-13 * "Received money from a customer"'


def _block(text, head):
    return re.search(rf'{re.escape(head)}\n(?:\t[^\n]*\n)*', text).group(0)


def _exported(book, tmp_path):
    ledger = tmp_path / 'exported.txt'
    _run(CliRunner(), 'export', str(book), str(ledger))
    return ledger.read_text()


def _row(book):
    listed = _run(CliRunner(), 'fx-balances', str(book)).output
    return [line for line in listed.splitlines()
            if 'Assets:Wise USD' in line or 'pending' in line]


def _wise_in_gnucash_s_order(book):
    """Each Wise USD split in the order GnuCash keeps the account in, with its running balance."""
    from infrastructure.gnucash.utils import get_account_full_name
    from repositories.gnucash_repository import GnuCashRepository, SessionMode
    from services.foreign_currency import iter_splits
    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        account = next(split.GetAccount() for split in iter_splits(repo.book)
                       if get_account_full_name(split.GetAccount()) == 'Assets:Wise USD')
        return [f'{split.GetParent().GetDate().date()} num {split.GetParent().GetNum()!r} entered '
                f'{split.GetParent().GetDateEntered()} {split.GetParent().GetDescription()!r} '
                f'amount {split.GetAmount()} running balance {split.GetBalance()}'
                for split in account.GetSplitList()]
    finally:
        repo.close()


def _the_deposit_as_the_edit_reads_it(book):
    """The figures the edit path reads for the deposit: the day's balance, the balance it is read against, and what its split holds."""
    from datetime import datetime, timedelta

    from infrastructure.gnucash.kvp import get_custom_metadata
    from repositories.gnucash_repository import GnuCashRepository, SessionMode
    from services.foreign_currency import (
        _stored_brought_in,
        iter_splits,
        split_guid,
        what_the_account_held_before,
    )
    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        split = next(each for each in iter_splits(repo.book)
                     if split_guid(each) == '0e530000000000000000000000000d22')
        deposit = split.GetParent()
        account = split.GetAccount()
        when = deposit.GetDate().date()
        day_after = datetime.combine(when + timedelta(days=1), datetime.min.time())
        return [f"Wise USD at the end of {when}: {account.GetBalanceAsOfDate(day_after)}",
                "the balance the deposit is read against (GnuCash's running balance "
                f'before it): {what_the_account_held_before([split])}',
                f'the deposit split: amount {split.GetAmount()}, recorded as bringing in '
                f'{_stored_brought_in(split)} (None: all of it), KVP {get_custom_metadata(split)}']
    finally:
        repo.close()


def _case(tmp_path, name, ledger_text):
    where = tmp_path / name
    where.mkdir()
    book = where / 'book.gnucash'
    _run(CliRunner(), 'import', '--new', str(book), BASE, '--include-business-objects',
         '--fx-rates', RATES)
    ledger = where / 'ledger.txt'
    ledger.write_text(ledger_text)
    done = _run(CliRunner(), 'import', str(book), str(ledger), '--fx-rates', RATES)
    print(f'\n=== {name}: import exit {done.exit_code}')
    deposit = _block(_exported(book, where), HEAD)
    print('--- the deposit before the edit\n' + deposit.rstrip())
    print('--- fx-balances before\n' + '\n'.join(_row(book)))
    print("--- Wise USD in GnuCash's order before\n" + '\n'.join(_wise_in_gnucash_s_order(book)))
    print('--- what the edit reads, before it\n' + '\n'.join(_the_deposit_as_the_edit_reads_it(book)))
    edit = where / 'edit.txt'
    edit.write_text(deposit.replace('\tAssets:Due from director -13.00 CAD\n',
                                    '\tIncome:Sales -13.00 CAD\n'))
    edited = _run(CliRunner(), 'import', str(book), str(edit), '--strategy', 'update',
                  '--fx-rates', RATES)
    print(f'--- the edit: exit {edited.exit_code}')
    print('--- the deposit after the edit\n' + _block(_exported(book, where), HEAD).rstrip())
    print('--- fx-balances after\n' + '\n'.join(_row(book)))
    print('--- the deposit split after\n' + _the_deposit_as_the_edit_reads_it(book)[2])


def test_what_order_gnucash_keeps_when_the_entry_times_differ(tmp_path):
    """The deposit stamped one second before the fee, as the file orders them, and the fee half a second after that."""
    from datetime import datetime, timedelta

    from repositories.gnucash_repository import GnuCashRepository, SessionMode
    from services.foreign_currency import iter_splits
    book = tmp_path / 'book.gnucash'
    _run(CliRunner(), 'import', '--new', str(book), BASE, '--include-business-objects',
         '--fx-rates', RATES)
    _run(CliRunner(), 'import', str(book), LEDGER, '--fx-rates', RATES)
    print("\n--- GnuCash's order as imported\n" + '\n'.join(_wise_in_gnucash_s_order(book)))
    # In the last case the deposit's transaction, entered first, has num 2 and
    # the fee's has num 1.
    for label, fee_after, nums in (
            ('one second', timedelta(seconds=1), ('', '')),
            ('half a second', timedelta(milliseconds=500), ('', '')),
            ('one second, the deposit num 2 and the fee num 1', timedelta(seconds=1), ('2', '1'))):
        repo = GnuCashRepository(str(book))
        repo.open(mode=SessionMode.NORMAL)
        try:
            by_description = {split.GetParent().GetDescription(): split.GetParent()
                              for split in iter_splits(repo.book)}
            at = datetime(2026, 9, 1, 12, 0, 0)
            for description, when, num in (('Received money from a customer', at, nums[0]),
                                           ('Charges for the deposit', at + fee_after, nums[1])):
                transaction = by_description[description]
                transaction.BeginEdit()
                transaction.SetDateEnteredSecs(when)
                transaction.SetNum(num)
                transaction.CommitEdit()
                print(f'set {when}, reads back {transaction.GetDateEntered()!r}')
            repo.save()
        finally:
            repo.close()
        print(f"--- GnuCash's order with the fee entered {label} after the deposit\n"
              + '\n'.join(_wise_in_gnucash_s_order(book)))


def test_what_order_two_transactions_created_in_one_session_keep(tmp_path):
    """As the import creates them: each opened, its moment entered set, committed; then saved, reloaded, read.

    The fee's transaction is created first and entered at the later second.
    If the deposit then reads back first, GnuCash ordered the two by the
    moment entered, not by the order they were created in.
    """
    from datetime import datetime, timedelta

    from gnucash import GncNumeric, Split, Transaction

    from infrastructure.gnucash.utils import get_account_full_name
    from repositories.gnucash_repository import GnuCashRepository, SessionMode
    book = tmp_path / 'book.gnucash'
    _run(CliRunner(), 'import', '--new', str(book), BASE, '--include-business-objects',
         '--fx-rates', RATES)
    at = datetime(2026, 9, 1, 12, 0, 0)
    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.NORMAL)
    try:
        accounts = {}

        def walk(account):
            accounts[get_account_full_name(account)] = account
            for child in account.get_children():
                walk(child)
        walk(repo.book.get_root_account())
        usd = accounts['Assets:Wise USD'].GetCommodity()
        for description, usd_amount, cad_amount, when in (
                ('Charges for the deposit', -100, 140, at + timedelta(seconds=1)),
                ('Received money from a customer', 1000, -1300, at)):
            transaction = Transaction(repo.book)
            transaction.BeginEdit()
            transaction.SetCurrency(usd)
            transaction.SetDescription(description)
            for name, amount, value in (('Assets:Wise USD', usd_amount, usd_amount),
                                        ('Assets:Due from director', cad_amount, -usd_amount)):
                split = Split(repo.book)
                split.SetParent(transaction)
                split.SetAccount(accounts[name])
                split.SetAmount(GncNumeric(amount, 100))
                split.SetValue(GncNumeric(value, 100))
            transaction.SetDateEnteredSecs(when)
            transaction.SetDatePostedSecsNormalized(datetime(2026, 8, 13))
            transaction.CommitEdit()
            print(f'\n{description}: set {when}, reads back after its commit '
                  f'{transaction.GetDateEntered()!r}')
        repo.save()
    finally:
        repo.close()
    print("--- GnuCash's order after a save and a reload\n"
          + '\n'.join(_wise_in_gnucash_s_order(book)))


def test_how_gnucash_orders_two_texts_in_num(tmp_path):
    """The deposit entered first; each pair of `num` texts, and which of the two GnuCash puts first."""
    from datetime import datetime, timedelta

    from repositories.gnucash_repository import GnuCashRepository, SessionMode
    from services.foreign_currency import iter_splits
    book = tmp_path / 'book.gnucash'
    _run(CliRunner(), 'import', '--new', str(book), BASE, '--include-business-objects',
         '--fx-rates', RATES)
    _run(CliRunner(), 'import', str(book), LEDGER, '--fx-rates', RATES)
    print()
    for deposit_num, fee_num in (('9', '10'), ('B', 'A'), ('b', 'A'), ('10', 'A'), ('2a', '10'),
                                 ('A10', 'A9'), ('', '1'), ('1', '')):
        repo = GnuCashRepository(str(book))
        repo.open(mode=SessionMode.NORMAL)
        try:
            by_description = {split.GetParent().GetDescription(): split.GetParent()
                              for split in iter_splits(repo.book)}
            at = datetime(2026, 9, 1, 12, 0, 0)
            for description, when, num in (
                    ('Received money from a customer', at, deposit_num),
                    ('Charges for the deposit', at + timedelta(seconds=1), fee_num)):
                transaction = by_description[description]
                transaction.BeginEdit()
                transaction.SetDateEnteredSecs(when)
                transaction.SetNum(num)
                transaction.CommitEdit()
            repo.save()
        finally:
            repo.close()
        first = _wise_in_gnucash_s_order(book)[0]
        print(f'deposit {deposit_num!r}, fee {fee_num!r}: first is '
              f"{'the deposit' if 'Received' in first else 'the fee'}")


def test_what_the_export_of_the_imported_book_writes_and_rebuilds(tmp_path):
    """The two blocks in the order the export writes them, and whether that file rebuilds the book."""
    book = tmp_path / 'book.gnucash'
    _run(CliRunner(), 'import', '--new', str(book), BASE, '--include-business-objects',
         '--fx-rates', RATES)
    _run(CliRunner(), 'import', str(book), LEDGER, '--fx-rates', RATES)
    exported = _exported(book, tmp_path)
    order = [line for line in exported.splitlines() if line.startswith('2026-08-13')]
    print('\n--- the export writes, in this order\n' + '\n'.join(order))
    ledger = tmp_path / 'whole.txt'
    ledger.write_text(exported)
    rebuilt = CliRunner().invoke(__import__('cli.main').main.cli, [
        'import', '--new', str(tmp_path / 'rebuilt.gnucash'), str(ledger),
        '--include-business-objects'])
    print(f'--- rebuilt from it: exit {rebuilt.exit_code}\n{rebuilt.output[-1500:]}')


def test_what_an_edit_to_the_deposit_s_figure_records(tmp_path):
    """The deposit restated as 11.00 USD, 14.30 CAD: a figure of the US dollar split changes, so it is read again."""
    book = tmp_path / 'book.gnucash'
    _run(CliRunner(), 'import', '--new', str(book), BASE, '--include-business-objects',
         '--fx-rates', RATES)
    _run(CliRunner(), 'import', str(book), LEDGER, '--fx-rates', RATES)
    deposit = _block(_exported(book, tmp_path), HEAD)
    edit = tmp_path / 'edit.txt'
    edit.write_text(deposit.replace('\tAssets:Wise USD 10.00 USD\n', '\tAssets:Wise USD 11.00 USD\n')
                    .replace('-13.00 CAD', '-14.30 CAD').replace('"1000/1300"', '"1100/1430"')
                    .replace('value: "-10.00"', 'value: "-11.00"'))
    print('\n--- the edit\n' + edit.read_text())
    edited = _run(CliRunner(), 'import', str(book), str(edit), '--strategy', 'update',
                  '--fx-rates', RATES)
    print(f'--- the edit: exit {edited.exit_code}\n{edited.output[-800:]}')
    print('--- fx-balances after\n' + '\n'.join(_row(book)))
    print('--- the deposit split after\n' + _the_deposit_as_the_edit_reads_it(book)[2])


def test_probe(tmp_path):
    reported = Path(LEDGER).read_text()
    _case(tmp_path, 'pending-same-day', reported)
    _case(tmp_path, 'guid-same-day', reported.replace(
        'cost_basis_split_guid: $pending$',
        'cost_basis_split_guid: "0e530000000000000000000000000d22"'))
    _case(tmp_path, 'pending-day-after', reported.replace(
        '2026-08-13 * "Charges for the deposit"', '2026-08-14 * "Charges for the deposit"'))
