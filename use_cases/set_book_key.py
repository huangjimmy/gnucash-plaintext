"""Q-031: set a custom book-level key (e.g. a user's own `schema_version`).

Writes into the same book custom-metadata store the `company` directive uses for
arbitrary keys (Q-029), through the shared merge helper, so the value round-trips
and a write upserts one key without disturbing the others. This is how a
migration stamps the user's *own* semantic version into the book — separate from
`migrate`'s automatic applied-migrations history.
"""
import re

from infrastructure.gnucash.kvp import (
    get_book_custom_metadata,
    merge_book_custom_metadata,
)

# Same key grammar as plaintext metadata keys, so the value round-trips through
# the `company` directive (`key: value`) — lowercase-ish identifier, no colon.
_KEY_RE = re.compile(r'^[a-z_][a-zA-Z0-9_\-.]*$')


def execute_set_book_key(book, key, value):
    """Upsert `key` = `value` in the book's custom metadata (preserving the other
    keys). Returns 'created' / 'updated' / 'unchanged', or raises ValueError for a
    bad key."""
    if not _KEY_RE.match(key or ''):
        raise ValueError(
            f'invalid book key {key!r}: use a lowercase identifier with no ":" '
            f'(letters, digits, "_", "-", "."), e.g. "schema_version"')

    old = get_book_custom_metadata(book).get(key)
    if old == value:
        return 'unchanged'
    merge_book_custom_metadata(book, {key: value})
    return 'updated' if old is not None else 'created'
