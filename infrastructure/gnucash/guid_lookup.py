"""
Shared helpers for resolving customers/vendors by GUID.

Used by both the importer (`services/gnucash_importer.py`) and the
delete/archive use cases (`use_cases/delete_business_objects.py`) — kept
here so neither has to depend on the other's internals.
"""

from typing import Optional

import gnucash.gnucash_business as gb
from gnucash import Book, Query
from gnucash.gnucash_core_c import GncGUID, string_to_guid


def normalise_guid(guid) -> str:
    """Validate and canonicalise a user-supplied GUID string.

    Accepts:
      - 32-char lowercase hex
      - UUID-with-hyphens (`xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`)
      - mixed-case hex (lowercased on the way out)

    Rejects any string that `string_to_guid` cannot parse.

    Everything that reaches here is a string, because every caller is a Click
    option: `--txn` on `unapply-payment`, `--by-guid` on
    `delete-transactions`, `--by-guid` on the `unpost-*` commands, and
    `--guid` on `rename-account` (reached directly and through `migrate`,
    which re-enters commands with text arguments).

    A guard against `int`/`float`/`bool` stood here for a plaintext hazard —
    an unquoted all-digit guid, which the parser converts to a number that has
    lost its leading zeros and its digit count — but no plaintext path calls
    this function, so the guard could not be reached to catch it. The importer
    keeps its own `_normalise_guid` with that check intact, which is where
    file-stated guids actually arrive. If this one is ever wired to a file,
    the check belongs with it, where a test can reach it.
    """
    if not string_to_guid(guid, GncGUID()):
        raise ValueError(f"Invalid GUID format: {guid!r}")
    return guid.replace('-', '').lower()


def find_customer_by_guid(book: Book, guid_norm: str) -> Optional[gb.Customer]:
    """Return the Customer whose GUID matches `guid_norm`, or None.

    `guid_norm` must already be normalised (32-char lowercase hex) — call
    `normalise_guid()` first if dealing with raw user input.
    """
    q = Query()
    q.search_for('gncCustomer')
    q.set_book(book)
    found = None
    for r in q.run():
        c = gb.Customer(instance=r)
        if c.GetGUID().to_string() == guid_norm:
            found = c
            break
    q.destroy()
    return found


def find_vendor_by_guid(book: Book, guid_norm: str) -> Optional[gb.Vendor]:
    """Return the Vendor whose GUID matches `guid_norm`, or None."""
    q = Query()
    q.search_for('gncVendor')
    q.set_book(book)
    found = None
    for r in q.run():
        v = gb.Vendor(instance=r)
        if v.GetGUID().to_string() == guid_norm:
            found = v
            break
    q.destroy()
    return found
