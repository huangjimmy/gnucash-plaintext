"""`migrate --status` reports the history, and says where it read it.

The sidecar is a cache of the book's own migration history, kept so a no-op
`migrate` need not open the file. A cache that can be wrong is one a reader has
to be able to distrust, so every status line names its source — `[from sidecar
cache]` or `[from book]` — and `--verify` is how you ask for the second.

`--dry-run` is the other question that changes nothing: what *would* apply.
Asked when nothing would, it says so rather than printing an empty list.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner

from cli.main import cli
from tests.integration.test_migrate import _accounts, _migrations, _new_book


@pytest.fixture
def book_and_migrations(tmp_path):
    runner = CliRunner()
    gf = _new_book(runner, tmp_path)
    chk = _accounts(gf)['Assets:Bank:Checking']
    d = _migrations(tmp_path, {
        '0001_chequing.txt': f'rename-account --guid {chk} --to "Chequing"\n'})
    return gf, d


def _run(gf, d, *args):
    return CliRunner().invoke(cli, ['migrate', str(gf), str(d), *args])


def _apply(gf, d):
    result = _run(gf, d)
    assert result.exit_code == 0, result.output
    return result


class TestBeforeAnythingIsApplied:
    def test_it_reads_the_book_because_there_is_no_cache_yet(
            self, book_and_migrations):
        gf, d = book_and_migrations
        result = _run(gf, d, '--status')

        assert result.exit_code == 0, result.output
        assert '[from book]' in result.output, result.output

    def test_the_head_is_named_as_none_rather_than_left_blank(
            self, book_and_migrations):
        gf, d = book_and_migrations
        result = _run(gf, d, '--status')

        assert 'head: (none)' in result.output, result.output
        assert '(0 applied, 1 pending)' in result.output, result.output

    def test_the_pending_migration_is_listed_with_its_size(
            self, book_and_migrations):
        """The op count is how a reader tells a stub from a real batch."""
        gf, d = book_and_migrations
        result = _run(gf, d, '--status')

        assert 'pending  0001_chequing  (1 op(s))' in result.output, result.output

    def test_asking_for_the_status_applies_nothing(self, book_and_migrations):
        gf, d = book_and_migrations
        _run(gf, d, '--status')

        assert 'Assets:Bank:Checking' in _accounts(gf), _accounts(gf)


class TestOnceApplied:
    def test_the_cache_answers_and_says_so(self, book_and_migrations):
        gf, d = book_and_migrations
        _apply(gf, d)

        result = _run(gf, d, '--status')

        assert result.exit_code == 0, result.output
        assert '[from sidecar cache]' in result.output, result.output

    def test_verify_asks_the_book_instead(self, book_and_migrations):
        """Same answer, from the source of truth — that is what --verify buys."""
        gf, d = book_and_migrations
        _apply(gf, d)

        result = _run(gf, d, '--status', '--verify')

        assert result.exit_code == 0, result.output
        assert '[from book]' in result.output, result.output
        assert '(1 applied, 0 pending)' in result.output, result.output

    def test_the_applied_migration_is_listed_with_when(self, book_and_migrations):
        gf, d = book_and_migrations
        _apply(gf, d)

        result = _run(gf, d, '--status')

        assert 'applied  0001_chequing  @ 20' in result.output, result.output


class TestDryRun:
    def test_it_names_the_operations_it_would_run(self, book_and_migrations):
        gf, d = book_and_migrations
        result = _run(gf, d, '--dry-run')

        assert result.exit_code == 0, result.output
        assert 'would apply 1 migration(s)' in result.output, result.output
        assert 'rename-account' in result.output, result.output

    def test_with_nothing_pending_it_says_so(self, book_and_migrations):
        """Through --verify, because the cache answers first otherwise."""
        gf, d = book_and_migrations
        _apply(gf, d)

        result = _run(gf, d, '--dry-run', '--verify')

        assert result.exit_code == 0, result.output
        assert 'up to date; nothing to apply' in result.output, result.output
