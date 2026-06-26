"""Q-031: set a custom book-level key (e.g. a user's own `schema_version`).

Writes into the same book custom-metadata store the `company` directive uses for
arbitrary keys (Q-029), so the value round-trips through export/import. This is
how a migration stamps the user's *own* semantic version into the book —
separate from `migrate`'s automatic applied-migrations history.
"""
import json
import re

from infrastructure.gnucash.kvp import (
    COMPANY_CUSTOM_SECTION,
    COMPANY_CUSTOM_SLOT,
    get_book_string_option,
    set_book_string_option,
)

# Same key grammar as plaintext metadata keys, so the value round-trips through
# the `company` directive (`key: value`) — lowercase-ish identifier, no colon.
_KEY_RE = re.compile(r'^[a-z_][a-zA-Z0-9_\-.]*$')


def execute_set_book_key(book, key, value):
    """Set `key` to `value` in the book's custom metadata. Returns
    'created' / 'updated' / 'unchanged', or raises ValueError for a bad key."""
    if not _KEY_RE.match(key or ''):
        raise ValueError(
            f'invalid book key {key!r}: use a lowercase identifier with no ":" '
            f'(letters, digits, "_", "-", "."), e.g. "schema_version"')

    blob = get_book_string_option(book, COMPANY_CUSTOM_SECTION, COMPANY_CUSTOM_SLOT) or ''
    try:
        data = json.loads(blob) if blob else {}
        if not isinstance(data, dict):
            data = {}
    except (ValueError, TypeError):
        data = {}

    old = data.get(key)
    if old == value:
        return 'unchanged'
    data[key] = value
    set_book_string_option(book, COMPANY_CUSTOM_SECTION, COMPANY_CUSTOM_SLOT,
                           json.dumps(data, ensure_ascii=False, sort_keys=True))
    return 'updated' if old is not None else 'created'
