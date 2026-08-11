"""Writing the book back, and what to say when that fails.

Seven commands each carried their own copy of this, down to the wording, which
is how a shared answer to a shared question ends up being seven places to
change and seven places to cover.
"""

import click


def save_or_report(repo) -> None:
    """Save the book, or refuse with a message rather than a traceback.

    A backup collision is not a failure to report. GnuCash names its backup
    after the current second — `<book>.20240201120000.gnucash` — so two saves
    inside one second collide on that filename while the book itself is
    written. What the caller wanted has happened, and saying otherwise sends
    the reader looking for damage that is not there.
    """
    try:
        repo.save()
    except Exception as e:
        if 'ERR_FILEIO_BACKUP_ERROR' not in str(e):
            raise click.ClickException(f'Failed to save: {e}') from e
