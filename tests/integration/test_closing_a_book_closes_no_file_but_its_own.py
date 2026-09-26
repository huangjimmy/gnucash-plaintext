"""Closing a book, or refusing to open one, closes no file of the process but the book's own.

A book opened for writing holds `<book>.LCK` open on a descriptor. On GnuCash
3.4, 3.8 and 4.4 a session whose backend never took that lock — a book opened
read-only, a missing book, a locked book — still closes a lock descriptor when
it ends, holding whatever number the previous backend at that address used. By
then the number is free, and a file opened since has it: that file is closed.

Measured on all eleven builds
(`whether_closing_a_read_only_book_closes_a_file_it_never_opened_probe.py`,
`whether_a_book_that_fails_to_open_closes_a_file_it_never_opened_probe.py`):
closing a read-only book took the file 5 of 5 times on 3.4, 3.8 and 4.4 and
never on 4.8 or later; refusing a missing book took it on 3.4 and 3.8, and a
locked book on 3.8.

It is what `tests/conftest.py` absorbs in pytest's own paths, and what failed
`test_a_printed_page_keeps_its_characters.py` when it reached a test's file.

Each test opens a book for writing and closes it, so its lock number is free,
then opens a file on that number, then does the thing under test.
"""

import os

import gnucash
import pytest

from repositories.gnucash_repository import BookUnavailableError, GnuCashRepository, SessionMode


def _book(path):
    repo = GnuCashRepository(str(path))
    repo.open(SessionMode.NEW)
    account = gnucash.Account(repo.book)
    account.BeginEdit()
    account.SetName('Bank')
    account.SetType(2)
    account.SetCommodity(repo.book.get_table().lookup('CURRENCY', 'CAD'))
    repo.book.get_root_account().append_child(account)
    account.CommitEdit()
    repo.save()
    repo.close()
    return path


def _a_file_on_the_lock_number_a_book_just_freed(book, tmp_path):
    writer = GnuCashRepository(str(book))
    writer.open(SessionMode.NORMAL)
    writer.close()
    return os.open(str(tmp_path / 'a-file-of-the-process.txt'), os.O_CREAT | os.O_RDWR)


def _still_open(fd):
    try:
        os.fstat(fd)
    except OSError:
        return False
    os.close(fd)
    return True


def test_closing_a_book_opened_read_only(tmp_path):
    book = _book(tmp_path / 'book.gnucash')
    mine = _a_file_on_the_lock_number_a_book_just_freed(book, tmp_path)

    reader = GnuCashRepository(str(book))
    reader.open(SessionMode.READ_ONLY)
    reader.close()

    assert _still_open(mine)


def test_the_book_read_only_is_the_book(tmp_path):
    """Whatever the read-only open does, the accounts read are the book's own."""
    book = _book(tmp_path / 'book.gnucash')

    reader = GnuCashRepository(str(book))
    reader.open(SessionMode.READ_ONLY)
    try:
        names = [child.GetName() for child in reader.book.get_root_account().get_children()]
    finally:
        reader.close()

    assert names == ['Bank']


def test_a_read_only_open_leaves_no_lock_beside_the_book(tmp_path):
    book = _book(tmp_path / 'book.gnucash')

    reader = GnuCashRepository(str(book))
    reader.open(SessionMode.READ_ONLY)
    try:
        beside = sorted(p.name for p in tmp_path.iterdir())
    finally:
        reader.close()

    assert not [name for name in beside if name.endswith(('.LCK', '.LNK'))], beside


@pytest.mark.parametrize('mode', [SessionMode.READ_ONLY, SessionMode.NORMAL])
def test_refusing_a_missing_book(tmp_path, mode):
    book = _book(tmp_path / 'book.gnucash')
    mine = _a_file_on_the_lock_number_a_book_just_freed(book, tmp_path)

    with pytest.raises(BookUnavailableError):
        GnuCashRepository(str(tmp_path / 'no-such-book.gnucash')).open(mode)

    assert _still_open(mine)


def test_refusing_to_create_a_book_where_one_already_is(tmp_path):
    book = _book(tmp_path / 'book.gnucash')
    there = _book(tmp_path / 'there.gnucash')
    mine = _a_file_on_the_lock_number_a_book_just_freed(book, tmp_path)

    with pytest.raises(BookUnavailableError):
        GnuCashRepository(str(there)).open(SessionMode.NEW)

    assert _still_open(mine)


def test_refusing_to_create_a_book_in_a_directory_that_does_not_exist(tmp_path):
    book = _book(tmp_path / 'book.gnucash')
    mine = _a_file_on_the_lock_number_a_book_just_freed(book, tmp_path)

    with pytest.raises(BookUnavailableError):
        GnuCashRepository(str(tmp_path / 'no-such-directory' / 'book.gnucash')).open(SessionMode.NEW)

    assert _still_open(mine)


def test_refusing_to_create_a_book_in_a_directory_it_cannot_write(tmp_path):
    book = _book(tmp_path / 'book.gnucash')
    shut = tmp_path / 'shut'
    shut.mkdir()
    os.chmod(shut, 0o555)
    try:
        if os.access(shut, os.W_OK):
            if os.environ.get('GNC_UNPRIVILEGED_RUN'):
                pytest.fail('the runner says this container was started with --user, and the '
                            'process writes whatever the mode says anyway')
            pytest.skip('this process writes whatever the mode says, so the directory is not '
                        'unwritable')
        mine = _a_file_on_the_lock_number_a_book_just_freed(book, tmp_path)

        with pytest.raises(BookUnavailableError):
            GnuCashRepository(str(shut / 'new.gnucash')).open(SessionMode.NEW)

        assert _still_open(mine)
    finally:
        os.chmod(shut, 0o755)


@pytest.mark.parametrize('mode', [SessionMode.READ_ONLY, SessionMode.NORMAL])
def test_refusing_a_directory(tmp_path, mode):
    book = _book(tmp_path / 'book.gnucash')
    mine = _a_file_on_the_lock_number_a_book_just_freed(book, tmp_path)

    with pytest.raises(BookUnavailableError, match='not a GnuCash book'):
        GnuCashRepository(str(tmp_path)).open(mode)

    assert _still_open(mine)


def test_refusing_a_book_in_a_directory_it_cannot_write(tmp_path):
    """Made the way `test_a_book_that_will_not_open.py` makes it, and skipped or failed as it is there."""
    book = _book(tmp_path / 'book.gnucash')
    shut = tmp_path / 'shut'
    shut.mkdir()
    in_shut = _book(shut / 'book.gnucash')
    os.chmod(shut, 0o555)
    try:
        if os.access(shut, os.W_OK):
            if os.environ.get('GNC_UNPRIVILEGED_RUN'):
                pytest.fail('the runner says this container was started with --user, and the '
                            'process writes whatever the mode says anyway')
            pytest.skip('this process writes whatever the mode says, so the directory is not '
                        'unwritable')
        mine = _a_file_on_the_lock_number_a_book_just_freed(book, tmp_path)

        with pytest.raises(BookUnavailableError, match='write'):
            GnuCashRepository(str(in_shut)).open(SessionMode.NORMAL)

        assert _still_open(mine)
    finally:
        os.chmod(shut, 0o755)


def test_refusing_a_locked_book(tmp_path):
    book = _book(tmp_path / 'book.gnucash')
    held = _book(tmp_path / 'held.gnucash')
    holder = GnuCashRepository(str(held))
    holder.open(SessionMode.NORMAL)
    try:
        mine = _a_file_on_the_lock_number_a_book_just_freed(book, tmp_path)

        with pytest.raises(BookUnavailableError, match='locked'):
            GnuCashRepository(str(held)).open(SessionMode.NORMAL)

        assert _still_open(mine)
    finally:
        holder.close()
