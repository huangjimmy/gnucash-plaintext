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
from services.gnucash_importer import COMPANY_FIELD_TO_SLOT
from services.plaintext_addresses import (
    is_address_key,
    refuse_an_index_on_a_key_that_has_no_list,
)

# Same key grammar as plaintext metadata keys, so the value round-trips through
# the `company` directive (`key: value`) — lowercase-ish identifier, no colon,
# and the optional `[<digits>]` index a list key carries. The index parses here
# so that a bracketed key reaches the refusals below and is answered for what
# it is: left out, `addr[0]` was turned away as a *malformed* key, which tells
# the reader their spelling is wrong when it is the format's own.
_KEY_RE = re.compile(r'^[a-z_][a-zA-Z0-9_\-.]*(?:\[\d+\])?$')


def execute_set_book_key(book, key, value):
    """Upsert `key` = `value` in the book's custom metadata (preserving the other
    keys). Returns 'created' / 'updated' / 'unchanged', or raises ValueError for a
    bad key."""
    if not _KEY_RE.match(key or ''):
        raise ValueError(
            f'invalid book key {key!r}: use a lowercase identifier with no ":" '
            f'(letters, digits, "_", "-", "."), e.g. "schema_version"')

    # A name the `company` block owns is refused rather than written where
    # nothing reads it. These keys live in GnuCash's own Business options now,
    # and everything that reads one reads it there: the export prefers the
    # option, the printed page reads the option, and the migration that moves
    # an old blob copy onto the option only fires while the option is empty.
    # So a write here would report `created` and then be invisible in every
    # direction — until the next `company` block naming the key deleted it.
    #
    # A key that is stored where nothing reads it is worse than one that is
    # refused, because the file and the command both look like they worked.
    if key in COMPANY_FIELD_TO_SLOT or is_address_key(key):
        raise ValueError(
            f'{key!r} is a field of the `company` block, not a custom book '
            f'key: it is kept in GnuCash\'s own Business options, which is '
            f'where every reader looks for it. Written here it would be '
            f'stored where nothing reads it, and dropped by the next import '
            f'that carries a `company` block. State it in that block instead.')

    # And no bracketed key of the reader's own, for the reason the brackets
    # exist: they mark the format's own numbering, and a book minting
    # `note[0]` today takes the name the next list-valued key would need.
    refuse_an_index_on_a_key_that_has_no_list(key)

    old = get_book_custom_metadata(book).get(key)
    if old == value:
        return 'unchanged'
    merge_book_custom_metadata(book, {key: value})
    return 'updated' if old is not None else 'created'
