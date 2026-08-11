"""A book this tool cannot open has to be said, not raised.

Two ways it happens, and both are ordinary: the book is open in GnuCash — the
lock is what that means — or it sits somewhere the command cannot write, which
a read-only mount or a copy owned by someone else both produce. GnuCash
answers either with `GnuCashBackendException: call to begin resulted in the
following errors, ERR_BACKEND_LOCKED`, and nothing caught it, so every command
in this tool met the commonest situation there is with a traceback and an empty
message.

The lock is not a fault to fix but a state to report, and what the reader needs
is the sentence that says which state.
"""

import os

import pytest
from click.testing import CliRunner

from cli.main import cli

LEDGER = 'tests/fixtures/business_objects.txt'


@pytest.fixture
def book(tmp_path):
    path = tmp_path / 'book.gnucash'
    result = CliRunner().invoke(cli, [
        'import', '--new', str(path), LEDGER, '--include-business-objects'])
    assert result.exit_code == 0, result.output
    return path


class TestABookOpenInGnuCash:
    """What GnuCash leaves beside a book it has open."""

    def _lock(self, book):
        (book.parent / f'{book.name}.LCK').write_text('')
        (book.parent / f'{book.name}.somehost.1234.LNK').write_text('')

    def test_it_is_reported_rather_than_raised(self, book):
        self._lock(book)

        result = CliRunner().invoke(
            cli, ['unpost-invoices', str(book), 'INV-2026-001'])

        assert result.exit_code != 0, result.output
        assert result.exception is None or isinstance(
            result.exception, SystemExit), repr(result.exception)
        assert 'locked' in result.output.lower(), result.output

    def test_it_says_what_to_do_about_it(self, book):
        self._lock(book)

        result = CliRunner().invoke(
            cli, ['unpost-invoices', str(book), 'INV-2026-001'])

        assert 'GnuCash' in result.output, result.output
        assert '.LCK' in result.output, result.output

    def test_every_writing_command_answers_the_same_way(self, book):
        """It is caught once, above all of them, not per command."""
        self._lock(book)

        for command in (['delete-invoices', str(book), 'INV-2026-001'],
                        ['delete-transactions', str(book), '--by-guid',
                         'a' * 32],
                        ['import', str(book), LEDGER]):
            result = CliRunner().invoke(cli, command)
            assert 'locked' in result.output.lower(), (command, result.output)

    def test_reading_one_is_still_allowed(self, book):
        """A lock stops writers, and reading a book GnuCash has open is fine."""
        self._lock(book)

        out = book.parent / 'out.txt'
        exported = CliRunner().invoke(cli, ['export', str(book), str(out)])
        validated = CliRunner().invoke(cli, ['validate', str(book)])

        assert exported.exit_code == 0, exported.output
        assert out.read_text(), 'nothing was exported'
        assert validated.exit_code == 0, validated.output


class TestAPathThatIsNotABook:
    """Every command takes a path, and a person can type the wrong one.

    `Error: call to begin resulted in the following errors,
    ERR_BACKEND_NO_HANDLER` is what GnuCash says about it, and it says nothing
    a reader can act on.
    """

    def test_a_plaintext_ledger_is_not_a_book(self, tmp_path):
        """The two files this tool works with, mixed up — the likeliest slip."""
        result = CliRunner().invoke(cli, [
            'export', LEDGER, str(tmp_path / 'out.txt')])

        assert result.exit_code != 0, result.output
        assert 'not a GnuCash book' in result.output, result.output
        assert 'ERR_BACKEND' not in result.output, result.output

    def test_a_directory_is_not_one_either(self, tmp_path):
        result = CliRunner().invoke(cli, [
            'export', str(tmp_path), str(tmp_path / 'out.txt')])

        assert result.exit_code != 0, result.output
        assert 'not a GnuCash book' in result.output, result.output


class TestABookItCannotWrite:
    """A book somewhere the command cannot write.

    Made by taking write permission off the directory the book sits in, which
    is what a read-only mount or a copy owned by somebody else amounts to:
    GnuCash locks a book by creating files beside it, so the directory decides
    whether a command that only reads may run at all.

    A process running as root is not subject to that. The mode is 0o555 and it
    writes anyway, so the state under test does not exist and the run opens the
    book perfectly well — which is what the assertions would then be reading.

    So the condition is checked rather than assumed, and it is the condition
    and not the venue: any run of this suite that can write regardless of the
    mode, which in practice means a container given no `--user`.

    Which of the two answers it gets is decided by whether the runner says it
    passed one. `scripts/test.sh` sets `GNC_UNPRIVILEGED_RUN`, so a run that
    claims to be unprivileged and turns out not to be is a **failure** —
    dropping `--user` is what happened, CI ran as root on every version, and it
    was found as a CI failure rather than as anything the suite said. Skipping
    on the process's own judgement alone would turn that same regression into a
    green suite with this behaviour quietly untested and its lines quietly out
    of the union `scripts/coverage.sh` gates.

    Where nothing claims otherwise, root is taken at face value and the test
    skips: `scripts/shell.sh` runs the container without `--user` deliberately,
    and `pytest tests/` in there is a documented way to work.
    """

    def test_it_is_reported_rather_than_raised(self, book):
        os.chmod(book.parent, 0o555)
        try:
            if os.access(book.parent, os.W_OK):
                if os.environ.get('GNC_UNPRIVILEGED_RUN'):
                    pytest.fail(
                        'the runner says this container was given --user, and '
                        'the process writes whatever the mode says anyway — so '
                        'it is root, and every test needing a directory it '
                        'cannot write to is silently skipping')
                pytest.skip('this process writes whatever the mode says, so '
                            'the book is not unwritable and there is nothing '
                            'here to report')
            result = CliRunner().invoke(
                cli, ['unpost-invoices', str(book), 'INV-2026-001'])
        finally:
            os.chmod(book.parent, 0o755)

        assert result.exit_code != 0, result.output
        assert result.exception is None or isinstance(
            result.exception, SystemExit), repr(result.exception)
        assert 'write' in result.output.lower(), result.output
