"""Writing the book back, and what to say when that fails.

Seven commands each carried their own copy of this, down to the wording, which
is how a shared answer to a shared question ends up being seven places to
change and seven places to cover.
"""

import click


def save_or_report(repo) -> None:
    """Save the book, or refuse with a message rather than a traceback.

    A backup GnuCash cannot make is a failed save like any other. GnuCash keeps
    a backup under the second the save happens in —
    `<book>.20240201120000.gnucash` — and when that name is already taken the
    save stops with `ERR_FILEIO_BACKUP_ERROR` and the book is not written:
    measured on 5.10, a book option set before such a save reads back unset
    afterwards. Reading it as a harmless collision reported every such command
    as done while nothing had been saved
    (`tests/integration/test_a_save_gnucash_refuses_is_reported_and_changes_nothing.py`).
    """
    try:
        repo.save()
    except Exception as e:
        raise click.ClickException(f'Failed to save: {e}') from e
