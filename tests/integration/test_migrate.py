"""Q-031: `migrate` applies versioned migrations in a single save, tracks applied
history in the book + a cheap sidecar, is atomic, and treats applied migrations
as immutable.

A migration file is an ordered list of operation lines — each line is a CLI
invocation minus the book (the book is `migrate`'s target), parsed by Click.
"""

import time
from pathlib import Path

from click.testing import CliRunner

from cli.main import cli

BOOK = str(Path('tests/fixtures/rename_account_book.txt'))


def _new_book(runner, tmp_path):
    gf = tmp_path / 'book.gnucash'
    assert runner.invoke(cli, ['import', '--new', str(gf), BOOK]).exit_code == 0
    time.sleep(1)
    return gf


def _colon_name(acc):
    parts, node = [], acc
    while node is not None and node.get_parent() is not None:
        parts.append(node.GetName())
        node = node.get_parent()
    return ':'.join(reversed(parts))


def _accounts(gf):
    from repositories.gnucash_repository import GnuCashRepository
    repo = GnuCashRepository(str(gf))
    repo.open()
    try:
        return {_colon_name(a): a.GetGUID().to_string()
                for a in repo.book.get_root_account().get_descendants()}
    finally:
        repo.close()


def _migrations(tmp_path, files):
    d = tmp_path / 'migrations'
    d.mkdir(exist_ok=True)
    for name, content in files.items():
        (d / name).write_text(content)
    return d


def test_applies_a_batch_of_renames_in_one_run(tmp_path):
    runner = CliRunner()
    gf = _new_book(runner, tmp_path)
    a = _accounts(gf)
    chk, groc = a['Assets:Bank:Checking'], a['Expenses:Groceries']
    d = _migrations(tmp_path, {
        '0001_restructure.txt':
            f'# rename two accounts and stamp a version in one save\n'
            f'rename-account --guid {chk} --to "Assets:Bank:Chequing"\n'
            f'rename-account --guid {groc} --to "Food"\n'
            f'set-book-key --key schema_version --value 1\n',
    })
    r = runner.invoke(cli, ['migrate', str(gf), str(d)])
    assert r.exit_code == 0, r.output
    assert '1 save' in r.output
    time.sleep(1)

    after = _accounts(gf)
    assert 'Assets:Bank:Chequing' in after and 'Expenses:Food' in after
    assert 'Assets:Bank:Checking' not in after and 'Expenses:Groceries' not in after
    assert after['Assets:Bank:Chequing'] == chk      # same accounts, renamed
    assert after['Expenses:Food'] == groc


def test_rerun_is_a_noop_without_opening_the_book(tmp_path):
    runner = CliRunner()
    gf = _new_book(runner, tmp_path)
    chk = _accounts(gf)['Assets:Bank:Checking']
    d = _migrations(tmp_path, {'0001.txt': f'rename-account --guid {chk} --to "Chequing"\n'})
    assert runner.invoke(cli, ['migrate', str(gf), str(d)]).exit_code == 0

    r = runner.invoke(cli, ['migrate', str(gf), str(d)])
    assert r.exit_code == 0, r.output
    assert 'book not opened' in r.output           # fast path via the sidecar
    assert (Path(str(gf) + '.migrate-state.json')).exists()


def test_atomic_abort_leaves_the_book_unchanged(tmp_path):
    runner = CliRunner()
    gf = _new_book(runner, tmp_path)
    before = _accounts(gf)
    chk = before['Assets:Bank:Checking']
    d = _migrations(tmp_path, {
        '0001.txt':
            f'rename-account --guid {chk} --to "Chequing"\n'
            f'rename-account --guid 00000000000000000000000000000000 --to "Nope"\n',
    })
    r = runner.invoke(cli, ['migrate', str(gf), str(d)])
    assert r.exit_code != 0
    # The failing operation's OWN detailed message is surfaced, with context.
    assert 'no account in this book has guid' in r.output
    assert "migration '0001' failed at operation" in r.output
    assert 'No changes were saved' in r.output
    assert 'discarded' in r.output            # the earlier op ran in memory, then was discarded
    # The earlier good rename in the same migration must NOT have persisted.
    assert _accounts(gf) == before
    # Nothing recorded → still fully pending.
    s = runner.invoke(cli, ['migrate', str(gf), str(d), '--status'])
    assert '1 pending' in s.output and '0 applied' in s.output


def test_operation_with_bad_arguments_aborts_with_its_message(tmp_path):
    runner = CliRunner()
    gf = _new_book(runner, tmp_path)
    chk = _accounts(gf)['Assets:Bank:Checking']
    # rename-account line missing the required --to → Click MissingParameter.
    d = _migrations(tmp_path, {'0001.txt': f'rename-account --guid {chk}\n'})
    r = runner.invoke(cli, ['migrate', str(gf), str(d)])
    assert r.exit_code != 0
    assert "'--to'" in r.output                # Click's own parameter error
    assert 'failed at operation' in r.output and 'No changes were saved' in r.output


def test_applied_migration_is_immutable(tmp_path):
    runner = CliRunner()
    gf = _new_book(runner, tmp_path)
    chk = _accounts(gf)['Assets:Bank:Checking']
    d = _migrations(tmp_path, {'0001.txt': f'rename-account --guid {chk} --to "Chequing"\n'})
    assert runner.invoke(cli, ['migrate', str(gf), str(d)]).exit_code == 0

    # Edit a migration that was already applied → checksum no longer matches.
    (d / '0001.txt').write_text(f'rename-account --guid {chk} --to "Savings"\n')
    r = runner.invoke(cli, ['migrate', str(gf), str(d)])
    assert r.exit_code != 0
    assert 'immutable' in r.output and '0001' in r.output


def test_dry_run_changes_nothing(tmp_path):
    runner = CliRunner()
    gf = _new_book(runner, tmp_path)
    before = _accounts(gf)
    chk = before['Assets:Bank:Checking']
    d = _migrations(tmp_path, {'0001.txt': f'rename-account --guid {chk} --to "Chequing"\n'})
    r = runner.invoke(cli, ['migrate', str(gf), str(d), '--dry-run'])
    assert r.exit_code == 0, r.output
    assert '0001' in r.output and 'rename-account' in r.output
    assert _accounts(gf) == before                 # untouched


def test_unknown_operation_is_rejected(tmp_path):
    runner = CliRunner()
    gf = _new_book(runner, tmp_path)
    d = _migrations(tmp_path, {'0001.txt': 'frobnicate --foo bar\n'})
    r = runner.invoke(cli, ['migrate', str(gf), str(d)])
    assert r.exit_code != 0
    assert 'not a migration operation' in r.output


def test_migrate_cannot_be_nested(tmp_path):
    """A migration file may not contain `migrate` — migrations don't nest."""
    runner = CliRunner()
    gf = _new_book(runner, tmp_path)
    d = _migrations(tmp_path, {'0001.txt': 'migrate other.gnucash more-migrations/\n'})
    r = runner.invoke(cli, ['migrate', str(gf), str(d)])
    assert r.exit_code != 0
    assert 'do not nest' in r.output
    assert 'No changes were saved' in r.output


def test_read_meta_command_is_not_an_operation(tmp_path):
    """A real CLI command that isn't a mutating operation (export) is refused —
    migration lines are operations, not arbitrary CLI commands."""
    runner = CliRunner()
    gf = _new_book(runner, tmp_path)
    d = _migrations(tmp_path, {'0001.txt': 'export book.gnucash out.txt\n'})
    r = runner.invoke(cli, ['migrate', str(gf), str(d)])
    assert r.exit_code != 0
    assert 'not a migration operation' in r.output


def test_version_marker_is_set_and_round_trips(tmp_path):
    runner = CliRunner()
    gf = _new_book(runner, tmp_path)
    d = _migrations(tmp_path, {'0001.txt': 'set-book-key --key schema_version --value 3\n'})
    assert runner.invoke(cli, ['migrate', str(gf), str(d)]).exit_code == 0
    time.sleep(1)
    out = tmp_path / 'exp.txt'
    assert runner.invoke(cli, ['export', str(gf), str(out),
                               '--include-business-objects']).exit_code == 0
    text = out.read_text()
    assert 'schema_version' in text and '"3"' in text
