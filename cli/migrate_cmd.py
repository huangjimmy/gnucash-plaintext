"""CLI command: apply versioned migrations to a book in a single save.

`migrate <book> <migrations-dir> [--dry-run] [--status] [--verify]`

Each migration file (`migrations/0002_rename_chequing.txt`) is an ordered list
of operation lines — every line is a CLI invocation minus the book (the book is
this command's target), parsed by Click itself. All pending migrations apply to
one open book and are persisted with ONE save, so 200 renames cost ~1 save, not
200 (each save writes a second-stamped backup, forcing ≥1s between saves).

History lives in two layers: the in-book `options/Plaintext/Migrations` slot is
the source of truth (travels with the file); a cheap `<book>.migrate-state.json`
sidecar, stamped with the book's size+mtime, lets a no-op run conclude there is
nothing to do WITHOUT opening the (expensive) GnuCash file.
"""

import shlex
import sys
from datetime import datetime, timezone

import click

from cli._batch import BatchSession
from cli.rename_account_cmd import rename_account
from cli.set_book_key_cmd import set_book_key
from repositories.gnucash_repository import GnuCashRepository, SessionMode
from use_cases.migrate import (
    compute_pending,
    discover_migrations,
    read_applied_from_book,
    read_sidecar,
    sidecar_is_fresh,
    write_applied_to_book,
    write_sidecar,
)

# The ALLOWLIST of operations a migration line may invoke: name → batch-aware
# Click command. A migration line uses CLI syntax, but it is NOT "any CLI
# command" — only these mutating operations are valid. Read/meta commands
# (export, import, print-invoice, and `migrate` itself) are intentionally absent,
# so a migration can only apply changes to the target book, and migrations cannot
# nest. Adding a batch-aware command here makes it a valid migration operation.
_OPERATIONS = {
    'rename-account': rename_account,
    'set-book-key': set_book_key,
}


def _now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _apply_op(batch, line):
    """Parse one migration line as a CLI invocation and run it against the shared
    batch session. Raises click.ClickException / UsageError on failure."""
    tokens = shlex.split(line)
    if not tokens:
        return
    name, rest = tokens[0], tokens[1:]
    if name == 'migrate':
        raise click.ClickException(
            "'migrate' cannot appear inside a migration — migrations do not nest. "
            "A migration file lists operations (e.g. rename-account), not migrate "
            "itself.")
    cmd = _OPERATIONS.get(name)
    if cmd is None:
        raise click.ClickException(
            f"{name!r} is not a migration operation. A migration file may use only "
            f"these operations: {', '.join(sorted(_OPERATIONS))}. Read/meta commands "
            f"(export, import, print-invoice, migrate, …) are not operations — a "
            f"migration only applies changes to the target book.")
    cmd.main(args=rest, obj=batch, standalone_mode=False)


def _immutability_error(errors):
    ids = ', '.join(eid for eid, _old, _new in errors)
    return click.ClickException(
        f'migration(s) already applied have been edited since: {ids}. Applied '
        f'migrations are immutable — revert the file(s), or write a new migration '
        f'for further changes.')


def _print_status(applied, pending, opened):
    head = applied[-1]['id'] if applied else '(none)'
    src = 'book' if opened else 'sidecar cache'
    click.echo(f'head: {head}  ({len(applied)} applied, {len(pending)} pending) '
               f'[from {src}]')
    for a in applied:
        click.echo(f'  applied  {a["id"]}  @ {a.get("applied_at", "?")}')
    for f in pending:
        click.echo(f'  pending  {f.id}  ({len(f.ops)} op(s))')


@click.command('migrate')
@click.argument('gnucash_file', type=click.Path(exists=True))
@click.argument('migrations_dir', type=click.Path(exists=True, file_okay=False))
@click.option('--dry-run', is_flag=True, help='Show what would apply; change nothing.')
@click.option('--status', 'show_status', is_flag=True,
              help='Report applied vs pending migrations (uses the sidecar when fresh).')
@click.option('--verify', is_flag=True,
              help='Ignore the sidecar cache and check the book directly.')
def migrate(gnucash_file, migrations_dir, dry_run, show_status, verify):
    """Apply pending migrations to the book in a single save."""
    files = discover_migrations(migrations_dir)

    # ── Fast path: trust the sidecar when it still matches the book on disk ──
    if not verify:
        sc = read_sidecar(gnucash_file)
        if sidecar_is_fresh(gnucash_file, sc):
            applied = sc.get('applied', [])
            pending, errors = compute_pending(files, applied)
            if show_status:
                _print_status(applied, pending, opened=False)
                return
            if errors:
                raise _immutability_error(errors)
            if not pending:
                head = sc.get('head')
                click.echo(f'up to date (head: {head}); book not opened')
                return
            # pending work exists → fall through and open the book

    # ── Authoritative path: open the book ──────────────────────────────────
    repo = GnuCashRepository(gnucash_file)
    repo.open(mode=SessionMode.NORMAL)
    saved = False
    try:
        applied = read_applied_from_book(repo.book)
        pending, errors = compute_pending(files, applied)
        if errors:
            raise _immutability_error(errors)

        if show_status:
            _print_status(applied, pending, opened=True)
            return
        if dry_run:
            if not pending:
                click.echo('up to date; nothing to apply')
            else:
                click.echo(f'would apply {len(pending)} migration(s):')
                for f in pending:
                    click.echo(f'  {f.id}')
                    for line in f.ops:
                        click.echo(f'      {line}')
            return

        if pending:
            batch = BatchSession(repo.book)
            for mf in pending:
                for line in mf.ops:
                    try:
                        _apply_op(batch, line)
                    except Exception as e:
                        # Surface the operation command's own message (Click
                        # errors via format_message, anything else via str), name
                        # the migration + line, and abort BEFORE saving — migrate
                        # is atomic, so a failure in the middle of the batch
                        # persists nothing and records nothing.
                        detail = (e.format_message()
                                  if isinstance(e, click.ClickException) else str(e))
                        done = len(batch.log)
                        raise click.ClickException(
                            f'migration {mf.id!r} failed at operation:\n'
                            f'    {line}\n'
                            f'  → {detail}\n'
                            f'  No changes were saved. migrate is atomic: the whole '
                            f'batch applies in one save or nothing does '
                            f'({done} operation(s) had run in memory and were '
                            f'discarded). Fix the migration and re-run.') from e
                applied.append({'id': mf.id, 'applied_at': _now(),
                                'checksum': mf.checksum})
            write_applied_to_book(repo.book, applied)
            repo.save()
            saved = True
            report = batch.log
        else:
            report = []
    finally:
        repo.close()

    # Refresh the sidecar from the now-authoritative applied list (also stamps a
    # fresh book size/mtime so the next run can fast-path).
    write_sidecar(gnucash_file, applied)

    if not pending:
        click.echo('up to date; nothing to apply')
        return
    for line in report:
        click.echo(f'  {line}')
    click.echo(f'applied {len(pending)} migration(s) in {"1 save" if saved else "0 saves"}; '
               f'head: {applied[-1]["id"]}')


if __name__ == '__main__':
    sys.exit(migrate())
