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

    Rejects:
      - int/float/bool — these come from unquoted all-digit guid values in
        plaintext where the parser auto-converts to int and silently loses
        the digit count. Force the caller to quote.
      - any string that `string_to_guid` cannot parse.
    """
    if isinstance(guid, (int, float, bool)):
        raise ValueError(
            f"guid must be a quoted string (got {type(guid).__name__} {guid!r}); "
            f"unquoted all-digit values are auto-converted to a number and "
            f"lose their digit count. Quote the guid: e.g. \"{guid:032x}\""
            if isinstance(guid, int) and 0 <= guid < 2**128
            else f"guid must be a quoted string (got {type(guid).__name__} {guid!r})"
        )
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
