"""CLI command: set a custom book-level key.

`set-book-key <book> --key <name> --value <value>`

Stores an arbitrary key (e.g. your own `schema_version`) in the book's custom
metadata — the same store the `company` directive round-trips (Q-029). Runs
standalone or, under `migrate`, against the shared batch session (one save).
"""

import sys

import click

from cli._batch import current_batch
from repositories.gnucash_repository import GnuCashRepository, SessionMode
from use_cases.set_book_key import execute_set_book_key


@click.command('set-book-key')
@click.argument('gnucash_file', required=False, type=click.Path(exists=True))
@click.option('--key', required=True, help='Book key to set (e.g. schema_version).')
@click.option('--value', required=True, help='Value to store.')
@click.pass_context
def set_book_key(ctx, gnucash_file, key, value):
    """Set a custom book-level key (book metadata, round-trips via `company`)."""
    batch = current_batch(ctx)

    try:
        if batch is not None:
            status = execute_set_book_key(batch.book, key, value)
            if status != 'unchanged':
                batch.mark_dirty()
            emit = batch.note
        else:
            if not gnucash_file:
                raise click.UsageError(
                    "missing book: set-book-key <book> --key … --value …")
            repo = GnuCashRepository(gnucash_file)
            repo.open(mode=SessionMode.NORMAL)
            try:
                status = execute_set_book_key(repo.book, key, value)
                if status != 'unchanged':
                    repo.save()
            finally:
                repo.close()
            emit = click.echo
    except ValueError as e:
        raise click.ClickException(str(e)) from e

    if status == 'unchanged':
        emit(f'book key {key!r} already = {value!r} — nothing to change')
    else:
        emit(f'{status} book key {key!r} = {value!r}')


if __name__ == '__main__':
    sys.exit(set_book_key())
