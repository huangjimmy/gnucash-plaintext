"""A new book whose name the file system cannot hold is refused, and nothing is written.

A file name of 300 characters is longer than a name may be. GnuCash cannot
create the book or the lock beside it, and says so in words that differ by
version: `ERR_FILEIO_FILE_LOCKERR` on 5.10 and `ERR_BACKEND_LOCKED` on 3.4
(`tests/research/what_gnucash_says_to_a_path_it_cannot_follow_probe.py`). What
holds on every build is what this asserts: the command is refused without a
traceback, and the directory is left as it was.
"""

from click.testing import CliRunner

from cli.main import cli


def test_nothing_is_written(tmp_path):
    book = tmp_path / ('a' * 300 + '.gnucash')

    result = CliRunner().invoke(cli, [
        'import', '--new', str(book), 'tests/fixtures/q019_accounts.txt'])

    assert result.exit_code != 0, result.output
    assert result.exception is None or isinstance(result.exception, SystemExit), (
        result.exception)
    assert list(tmp_path.iterdir()) == []
