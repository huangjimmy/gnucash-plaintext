"""The book's own migration history is the truth; the sidecar is a cache.

`<book>.migrate-state.json` exists so a no-op `migrate` need not open the
GnuCash file. Everything about it is therefore recoverable: it can be deleted,
truncated by a save that ran out of disk, or left behind next to a book that
has since been migrated by somebody else's checkout. In each case the answer is
the same — ignore it and open the book, which is where the list actually lives.

The list in the book is read back the same way, and it too may be something
this tool did not write: a slot holding an older shape, or holding text that is
not JSON at all. A migration history that cannot be read is an empty one — the
migrations are then pending, and re-applying them is what their `id` and
checksum exist to make safe — rather than a traceback out of a command whose
job is to repair books.

`test_migrate.py` holds the ordinary path; this is what happens when the two
layers disagree.
"""

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from cli.main import cli
from tests.integration.test_migrate import _accounts, _migrations, _new_book


@pytest.fixture
def applied(tmp_path):
    """A book with `0001_chequing` applied, and a fresh sidecar beside it."""
    runner = CliRunner()
    gf = _new_book(runner, tmp_path)
    chk = _accounts(gf)['Assets:Bank:Checking']
    d = _migrations(tmp_path, {
        '0001_chequing.txt': f'rename-account --guid {chk} --to "Chequing"\n'})
    result = runner.invoke(cli, ['migrate', str(gf), str(d)])
    assert result.exit_code == 0, result.output
    return gf, d


def _sidecar(gf):
    return Path(str(gf) + '.migrate-state.json')


def _run(gf, d, *args):
    return CliRunner().invoke(cli, ['migrate', str(gf), str(d), *args])


def _write_migrations_slot(gf, text):
    """Put `text` in the book's migrations slot, whatever it says.

    Written through the same setter `migrate` itself uses, because how such a
    book is *read* is what is under test — and no command of this tool will
    write a slot that does not parse, which is exactly why the reader has to
    cope with one.
    """
    from infrastructure.gnucash.kvp import (
        MIGRATIONS_SECTION,
        MIGRATIONS_SLOT,
        set_book_string_option,
    )
    from repositories.gnucash_repository import GnuCashRepository, SessionMode

    repo = GnuCashRepository(str(gf))
    repo.open(mode=SessionMode.NORMAL)
    try:
        set_book_string_option(repo.book, MIGRATIONS_SECTION, MIGRATIONS_SLOT, text)
        repo.save()
    finally:
        repo.close()


class TestASidecarThatWillNotParse:
    """Truncated, half-written, or edited by hand."""

    def test_the_book_is_opened_instead(self, applied):
        gf, d = applied
        _sidecar(gf).write_text('{"applied": [')

        result = _run(gf, d, '--status')

        assert result.exit_code == 0, result.output
        assert '[from book]' in result.output, result.output

    def test_and_the_history_it_reports_is_the_real_one(self, applied):
        """Not the empty history an unreadable cache might be mistaken for."""
        gf, d = applied
        _sidecar(gf).write_text('not json at all')

        result = _run(gf, d, '--status')

        assert '(1 applied, 0 pending)' in result.output, result.output
        assert '0001_chequing' in result.output, result.output

    def test_it_is_rewritten_rather_than_left_broken(self, applied):
        """The next run gets its fast path back."""
        gf, d = applied
        _sidecar(gf).write_text('not json at all')
        _run(gf, d)

        assert json.loads(_sidecar(gf).read_text())['head'] == '0001_chequing'


class TestASlotTheToolDidNotWrite:
    def test_text_that_is_not_json_reads_as_no_history(self, applied):
        gf, d = applied
        _write_migrations_slot(gf, 'schema_version=3')

        result = _run(gf, d, '--status', '--verify')

        assert result.exit_code == 0, result.output
        assert '(0 applied, 1 pending)' in result.output, result.output

    def test_json_of_the_wrong_shape_reads_as_no_history(self, applied):
        """A mapping, say — valid JSON, and not the list this expects."""
        gf, d = applied
        _write_migrations_slot(gf, '{"0001_chequing": "2026-01-01"}')

        result = _run(gf, d, '--status', '--verify')

        assert result.exit_code == 0, result.output
        assert '(0 applied, 1 pending)' in result.output, result.output

    def test_the_migration_can_then_be_applied_again(self, applied):
        """Which is safe: it is the same file, and it lands on a book that has
        already had it, so the rename finds its account by guid either way."""
        gf, d = applied
        _write_migrations_slot(gf, 'schema_version=3')

        result = _run(gf, d, '--verify')

        assert result.exit_code == 0, result.output
        assert 'Assets:Bank:Chequing' in _accounts(gf), _accounts(gf)


class TestAnAppliedFileEditedSince:
    def test_the_book_catches_it_even_when_the_cache_is_gone(self, applied):
        """The checksum lives in both layers, so removing the cache does not
        get an edited migration past the immutability rule."""
        gf, d = applied
        _sidecar(gf).unlink()
        (d / '0001_chequing.txt').write_text('# edited after it was applied\n')

        result = _run(gf, d)

        assert result.exit_code != 0, result.output
        assert 'already applied have been edited' in result.output, result.output
        assert '0001_chequing' in result.output, result.output


class TestWhatIsNotAMigration:
    def test_notes_kept_beside_the_migrations_are_not_run(self, applied):
        """People keep a README next to them; it is not an operation list."""
        gf, d = applied
        (d / 'README.md').write_text('rename-account --guid nope --to "Boom"\n')
        (d / 'archive').mkdir()

        result = _run(gf, d, '--status', '--verify')

        assert result.exit_code == 0, result.output
        assert '(1 applied, 0 pending)' in result.output, result.output
        assert 'README' not in result.output, result.output

    def test_a_directory_named_like_a_migration_is_not_one(self, applied):
        """`.txt` is not enough — it has to be a file."""
        gf, d = applied
        (d / '0002_later.txt').mkdir()

        result = _run(gf, d, '--status', '--verify')

        assert result.exit_code == 0, result.output
        assert '(1 applied, 0 pending)' in result.output, result.output


class TestAFreshCacheWithNewWorkBesideIt:
    def test_it_falls_through_and_opens_the_book(self, applied):
        """The cache is fresh and right, and still not the whole answer: a
        migration added since is pending, and pending work needs the book."""
        gf, d = applied
        chq = _accounts(gf)['Assets:Bank:Chequing']
        (d / '0002_savings.txt').write_text(
            f'rename-account --guid {chq} --to "Savings"\n')

        result = _run(gf, d)

        assert result.exit_code == 0, result.output
        assert 'book not opened' not in result.output, result.output
        assert 'Assets:Bank:Savings' in _accounts(gf), _accounts(gf)
