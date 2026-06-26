"""CLI command: rename an account, identified by its GUID.

`rename-account <book> --guid <account-guid> --to "<new name>"`

Renames an account in place. `--to` is the account's new full name; one rename
can change the leaf, the parent, or both at once:
  - bare leaf ("Chequing")           → new leaf, same parent
  - full path ("Assets:Chequing")    → new parent, same leaf
  - full path ("Assets:Cash:Petty")  → new parent and new leaf together

The account is found by GUID, never by its old name (that is what changes).
Because GnuCash keeps splits attached to accounts by reference, every
transaction that touched the account follows it automatically — nothing in the
ledger text needs editing. On the next export the account's new path is printed
wherever it appears.
"""

import sys

import click

from repositories.gnucash_repository import GnuCashRepository, SessionMode
from use_cases.rename_account import execute_rename


@click.command('rename-account')
@click.argument('gnucash_file', type=click.Path(exists=True))
@click.option('--guid', 'account_guid', required=True,
              help='GUID of the account to rename (stable identity, not the old name).')
@click.option('--to', 'new_name', required=True,
              help='New full name. Bare leaf ("Chequing") keeps the parent; full '
                   'path ("Assets:Cash:Petty") sets a new parent and/or leaf.')
def rename_account(gnucash_file, account_guid, new_name):
    """Rename an account by GUID, keeping all its splits."""
    repo = GnuCashRepository(gnucash_file)
    repo.open(mode=SessionMode.NORMAL)
    try:
        result = execute_rename(repo.book, account_guid, new_name)
        if result.status == 'renamed':
            repo.save()
    finally:
        repo.close()

    if result.status == 'renamed':
        click.echo(f'renamed account {result.old_name!r} → {result.new_name!r} '
                   f'(guid {result.guid})')
        return
    if result.status == 'unchanged':
        click.echo(f'account {result.old_name!r} (guid {result.guid}) is already '
                   f'named {new_name!r} — nothing to change')
        return

    # Failure: every message names the account, what was attempted, why it was
    # refused, and how to fix it — and the book is left untouched.
    msgs = {
        'bad_guid':
            f'--guid {account_guid!r} is not a valid account GUID: {result.detail}. '
            f'Pass the 32-character hex GUID; run `export-accounts` to list each '
            f"account's `guid:`.",
        'not_found':
            f'no account in this book has guid {account_guid!r}. Identify the '
            f'account by GUID, not its name — run `export-accounts` to list each '
            f"account with its `guid:`.",
        'bad_name':
            f'invalid --to value {new_name!r} for account {result.old_name!r}: an '
            f'account name cannot be empty or start/end with ":". Use a bare leaf '
            f'("Chequing") or a full path ("Assets:Chequing").',
        'parent_not_found':
            f'cannot rename account {result.old_name!r} to {new_name!r}: the parent '
            f'{result.detail!r} does not exist in this book. Create the parent '
            f'account first, or check the path (parents are colon-separated).',
        'cycle':
            f'cannot rename account {result.old_name!r} to {new_name!r}: the new '
            f'parent {result.detail!r} is {result.old_name!r} itself or one of its '
            f'descendants, which would make the account its own ancestor. Choose a '
            f'parent outside the {result.old_name!r} subtree.',
        'name_taken':
            f'cannot rename account {result.old_name!r} to {new_name!r}: an account '
            f'named {result.detail!r} already exists under that parent. Pick a '
            f'different leaf name, or rename/remove the existing account first.',
    }
    raise click.ClickException(
        msgs.get(result.status, f'rename failed ({result.status})'))


if __name__ == '__main__':
    sys.exit(rename_account())
