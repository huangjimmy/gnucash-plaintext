"""
KVP slot utilities for storing custom metadata on GnuCash objects.

Custom metadata is stored as a JSON string in a single 'plaintext_metadata'
slot to avoid KvpFrame key-enumeration complexity across GnuCash versions.

## Cross-version compatibility

There is one path, on every supported version: ctypes
`qof_instance_set_kvp` / `qof_instance_get_kvp` with a GLib GValue (from
libgobject-2.0). Those functions live in libgncmod-engine.so, not
libgnc-engine.so.

This module used to describe two — a SWIG path for "GnuCash 4.x+" using
`KvpFrame.set_slot_path` / `get_slot_path` with `KvpValue`, and the ctypes
one above as a fallback for GnuCash 3.8 on Ubuntu 20.04. Neither half of that
was true. Measured on GnuCash 5.10, 5.15 and 3.8: `from gnucash import
KvpValue` raises ImportError, and `Transaction` carries no `GetSlots`
attribute at all. So the "4.x+ path" could only ever raise, and the branch
labelled as one distribution's fallback was doing the work everywhere.

The slot name is flat — 'plaintext_metadata', no slashes — to avoid the
difference between flat-key and nested-path semantics.
"""
import contextlib
import ctypes
import json
import logging
from functools import lru_cache
from typing import Optional

PT_DATA_SLOT = 'plaintext_metadata'

# Q-029: book option slot that stores the `company` directive's custom
# (non-Business) keys as one JSON blob — `fiscal_year_end`, `province`, etc.
# A private section so it never collides with GnuCash's own Business options;
# one fixed slot so export reads it back by path without KVP key-enumeration.
COMPANY_CUSTOM_SECTION = 'Plaintext'
COMPANY_CUSTOM_SLOT = 'Custom Metadata'

# Q-031: book option slot holding the applied-migrations history (a JSON list of
# {id, applied_at, checksum}) — the in-book source of truth for `migrate`, the
# "schema_migrations table" equivalent that travels with the .gnucash file.
MIGRATIONS_SECTION = 'Plaintext'
MIGRATIONS_SLOT = 'Migrations'

# Transaction metadata keys that have dedicated GnuCash setters.
# Any key NOT in this set is treated as custom metadata → KVP slot.
KNOWN_TX_METADATA_KEYS = frozenset({
    'guid',
    'currency.namespace',
    'currency.mnemonic',
    'doc_link',
    'notes',
    # Q-032: the book-closing flag (xaccTransGetIsClosingTxn). Emitted as
    # `closing: #True` only on closing transactions and re-applied on import via
    # xaccTransSetIsClosingTxn, so a plaintext roundtrip doesn't un-close the
    # books (which would re-break the income statement). Handled by the importer
    # directly, not as a custom KVP slot.
    'closing',
    # NOTE: `txn_type` and `owner` are deliberately NOT in this set even
    # though the exporter emits them on payment-class transactions, so both
    # are preserved as plain KVP slots — `find-orphan-payments` reads either
    # the C field (in-book) or the KVP (after a plaintext roundtrip).
    #
    # `xaccTransSetTxnType` writes the `trans-txn-type` slot on every version,
    # and what changed is the reader: on 3.8 and 4.4 `xaccTransGetTxnType`
    # reads that slot, so a stated type takes; from 4.13 it derives the type
    # from the transaction's splits and lots instead and never consults the
    # slot at all (`Transaction.h`: "It does not query the transaction kvp
    # slots" — the setter's own doc calls the slot a backward-compatibility
    # measure "for previous GnuCash versions whose xaccTransGetTxnType reads
    # from the kvp slots"). The importer calls the setter everywhere — it is
    # what makes the type take on the older engines — while the KVP is what
    # carries `txn_type` across a roundtrip everywhere, which is why the
    # exporter falls back to this slot when the C field reads unset. Measured
    # with an export → import → export of a plain transaction stating
    # `txn_type: P`, which survives on 3.8 and 4.4 through the reader and on
    # 4.13/5.10 through this slot. (`gncOwnerCopyOnTxn` remains unused from
    # Python; the owner survives as the KVP alone.)
})

# Split metadata keys that have dedicated GnuCash setters.
KNOWN_SPLIT_METADATA_KEYS = frozenset({
    'share_price',
    'value',
    'action',
    'memo',
    'account.commodity.mnemonic',
    'account.commodity.namespace',
    # Q-014: emitted on the AR/AP-side split of an orphan payment tx so
    # the importer can re-create the orphan lot at re-import time. The
    # value is "customer:<id>" or "vendor:<id>". Without this round-trip,
    # the GnuCash 5.x txn-type heuristic on the restored book returns
    # NONE (it needs the AR/AP-side split's lot to have either an
    # invoice attached OR an owner) and `find-orphan-payments` would
    # only fire via the custom-KVP fallback (also emitted on the txn
    # itself as `owner:` / `txn_type:`).
    'lot_owner',
    # Q-016: every split serialises its own GUID as `guid:` (matching
    # the convention used at the transaction/customer/invoice level —
    # self-identification, not a foreign reference). An invoice/bill
    # payment block then refers to it via `txn_split_guid:` (the typed-
    # reference form). Handled by the importer's `_set_object_guid`
    # path, not as a KVP slot.
    'guid',
})

# The four lines of a `GncAddress`, in both spellings: `addr[0]`..`addr[3]`,
# which is what the writers emit, and `addr1`..`addr4`, which is what ledgers
# and older books still hold. Both belong in a known-key set — a set naming one
# of them emits the other twice, once as the address and once as a leftover
# custom key, and the stale copy comes second, which is the one a re-import
# keeps.
#
# Spelled out here rather than built from `services/plaintext_addresses`, which
# is where the syntax is defined and where every other reader of it asks: this
# is infrastructure, and importing a service into it points the layering the
# wrong way. Four fields is a fact about `GncAddress` and does not move.
_ADDRESS_KEYS = frozenset(
    {f'addr[{i}]' for i in range(4)} | {f'addr{i + 1}' for i in range(4)})

# Customer metadata keys that have dedicated GnuCash setters.
KNOWN_CUSTOMER_METADATA_KEYS = frozenset({
    'guid', 'name', 'currency', 'email', 'active',
}) | _ADDRESS_KEYS

# Vendor metadata keys that have dedicated GnuCash setters. The address keys
# belong here for the same reason they do above: a vendor has an address, the
# bill renderer prints it, and without a setter behind them these keys were
# filed as custom metadata — a slot named `addr1` rather than the address.
KNOWN_VENDOR_METADATA_KEYS = frozenset({
    'guid', 'name', 'currency', 'email', 'active',
}) | _ADDRESS_KEYS

# Invoice metadata keys that have dedicated GnuCash setters.
KNOWN_INVOICE_METADATA_KEYS = frozenset({
    'guid', 'customer_id', 'customer_guid', 'currency', 'date_opened',
    'billing_id', 'notes', 'posted', 'payment',
    'auto_apply_credit',  # Q-015: triggers gncInvoiceAutoApplyPayments after posting
    # Q-017: informational totals emitted by `print-invoice --format
    # plaintext`. Recomputed from entries on import; mismatch is an
    # error. Listed here so they don't fall into the custom-KVP path.
    'invoice_subtotal', 'invoice_tax_total', 'invoice_total',
})

# Bill metadata keys that have dedicated GnuCash setters.
KNOWN_BILL_METADATA_KEYS = frozenset({
    'guid', 'vendor_id', 'vendor_guid', 'currency', 'date_opened',
    # `notes` and `billing_id` as the invoice set has them: the bill
    # comparison reads `GetNotes()`, so leaving them out of this set sent
    # `notes:` to the slot, left `GetNotes()` empty, and made the comparison
    # unanswerable — every re-import of an unchanged ledger unposted the bill
    # and built it again.
    'billing_id', 'notes',
    'posted', 'payment',
    'auto_apply_credit',  # Q-015: triggers gncInvoiceAutoApplyPayments after posting
    # Q-017: bill analogues of the invoice informational totals.
    'bill_subtotal', 'bill_tax_total', 'bill_total',
})

# Account metadata keys that have dedicated GnuCash setters.
KNOWN_ACCOUNT_METADATA_KEYS = frozenset({
    'guid', 'type', 'placeholder', 'code', 'description', 'color',
    'notes', 'tax_related', 'commodity.namespace', 'commodity.mnemonic',
    'commodity_scu',
})


def held_value(obj, current: str, key: str, held: dict = None) -> str:
    """What an object holds for a key, wherever the value is kept.

    `held` is the object's slot contents where the caller already has them.
    Every KVP read is a ctypes call and a JSON parse, and the export asks this
    five times per owner for the address keys alone — each one re-reading the
    same slot it had already read to build its own block.

    A key that has since become a field of its own still sits in the slot of
    every book written before it was one — a vendor's address, a bill's notes
    — because back then it had no setter and went where anything without one
    goes. Every reader has to know that, not just the one someone happened to
    fix: read from the field alone, an export carried no address at all, a
    rebuilt book lost the note, and a rendered bill printed the line blank.

    The field wins when it has anything, so a value the book or the file has
    actually stated is never overridden by a stale copy. The slot copy is
    dropped on the next import that states the key (see
    `_merge_custom_metadata`), so this is a migration rather than a permanent
    second home.
    """
    if current:
        return current
    if held is None:
        held = get_custom_metadata(obj) or {}
    return held.get(key, '')


# ---------------------------------------------------------------------------
# GLib GValue helper: every KVP read and write goes through one of these.
# ---------------------------------------------------------------------------

class _GValue(ctypes.Structure):
    """
    GLib GValue struct (64-bit layout):
        GType g_type  (8 bytes = c_ulong on LP64)
        union data[2] (2 × 8 bytes = two c_uint64)
    """
    _fields_ = [
        ('g_type', ctypes.c_ulong),
        ('data', ctypes.c_uint64 * 2),
    ]


_G_TYPE_STRING = 64  # G_TYPE_STRING on all platforms (GLib constant)


@lru_cache(maxsize=1)
def _load_gobject() -> Optional[ctypes.CDLL]:
    """Load libgobject-2.0, which builds the GValue every KVP call passes.

    Cached by `lru_cache` and by nothing else. A module-global holding the
    same handle sat under a `if _gobj is not None: return _gobj` guard that
    the cache above makes unreachable — the body runs once, and on that one
    run the global is still None.

    None where the library is absent, which is a broken install rather than a
    version difference: every supported build has it. Both callers report and
    carry on rather than raising, so an import meeting it does not abort
    part-way through a book.

    That None is the implicit one the suppressed `OSError` falls out to. An
    explicit `return None` under the `with` says the same thing in a line no
    supported build can execute.
    """
    with contextlib.suppress(OSError):
        return ctypes.CDLL('libgobject-2.0.so.0')


def _load_gnc_engine() -> ctypes.CDLL:
    """
    Load libgncmod-engine with RTLD_GLOBAL promotion.

    On Ubuntu (RTLD_LOCAL extension loading), the library must be promoted
    to RTLD_GLOBAL before CDLL(None) so ctypes and the Python bindings share
    the same in-memory instance.

    qof_instance_set_kvp / qof_instance_get_kvp live in
    libgncmod-engine.so (not libgnc-engine.so).  Promote both paths.
    """
    for path in (
        '/usr/lib/x86_64-linux-gnu/gnucash/gnucash/libgncmod-engine.so',
        '/usr/lib/x86_64-linux-gnu/gnucash/libgnc-engine.so',
    ):
        with contextlib.suppress(OSError):
            ctypes.CDLL(path, mode=ctypes.RTLD_GLOBAL)
    return ctypes.CDLL(None)


# ---------------------------------------------------------------------------
# The KVP path, on every supported version: qof_instance_set/get_kvp + GValue
# ---------------------------------------------------------------------------

def _set_via_qof_instance(obj_ptr: int, slot_name: str, value: str) -> bool:
    """
    qof_instance_set_kvp(QofInstance*, GValue*, unsigned, ...).

    Sets a single string KVP slot on a QofInstance (Transaction or Split).
    Lives in libgncmod-engine.so, not libgnc-engine.so.
    """
    try:
        gobj = _load_gobject()
        if gobj is None:
            logging.debug("libgobject not available; skipping qof_instance_set_kvp")
            return False
        lib = _load_gnc_engine()

        gobj.g_value_init.argtypes = [ctypes.POINTER(_GValue), ctypes.c_ulong]
        gobj.g_value_init.restype = ctypes.POINTER(_GValue)
        gobj.g_value_set_string.argtypes = [ctypes.POINTER(_GValue), ctypes.c_char_p]
        gobj.g_value_set_string.restype = None
        gobj.g_value_unset.argtypes = [ctypes.POINTER(_GValue)]
        gobj.g_value_unset.restype = None

        lib.qof_instance_set_kvp.restype = None
        # Note: no argtypes for variadic function — Python ctypes handles
        # variadic calls with explicit c_void_p / c_uint / c_char_p casts.

        gval = _GValue()
        gobj.g_value_init(ctypes.byref(gval), _G_TYPE_STRING)
        gobj.g_value_set_string(ctypes.byref(gval), value.encode('utf-8'))

        lib.qof_instance_set_kvp(
            ctypes.c_void_p(obj_ptr),
            ctypes.byref(gval),
            ctypes.c_uint(1),
            slot_name.encode('utf-8'),
        )

        gobj.g_value_unset(ctypes.byref(gval))
        return True
    except Exception as e:
        logging.debug(f"qof_instance_set_kvp failed for {slot_name!r}: {e}")
        return False


def _get_via_qof_instance(obj_ptr: int, slot_name: str) -> Optional[str]:
    """
    qof_instance_get_kvp(QofInstance*, GValue*, unsigned, ...).
    """
    try:
        gobj = _load_gobject()
        if gobj is None:
            return None
        lib = _load_gnc_engine()

        gobj.g_value_init.argtypes = [ctypes.POINTER(_GValue), ctypes.c_ulong]
        gobj.g_value_init.restype = ctypes.POINTER(_GValue)
        gobj.g_value_get_string.argtypes = [ctypes.POINTER(_GValue)]
        gobj.g_value_get_string.restype = ctypes.c_char_p
        gobj.g_value_unset.argtypes = [ctypes.POINTER(_GValue)]
        gobj.g_value_unset.restype = None

        lib.qof_instance_get_kvp.restype = None

        gval = _GValue()
        gobj.g_value_init(ctypes.byref(gval), _G_TYPE_STRING)

        lib.qof_instance_get_kvp(
            ctypes.c_void_p(obj_ptr),
            ctypes.byref(gval),
            ctypes.c_uint(1),
            slot_name.encode('utf-8'),
        )

        raw = gobj.g_value_get_string(ctypes.byref(gval))
        gobj.g_value_unset(ctypes.byref(gval))

        if raw is None:
            return None
        return raw.decode('utf-8')
    except Exception as e:
        logging.debug(f"qof_instance_get_kvp failed for {slot_name!r}: {e}")
        return None


# ---------------------------------------------------------------------------
# Set / get a string slot — one route, through the qof_instance calls above
# ---------------------------------------------------------------------------

def _mark_instance_dirty(obj_ptr: int) -> None:
    """
    Call qof_instance_set_dirty so the XML backend re-serializes this object.

    Required after any ctypes-based KVP write (including the SWIG path on
    4.x when modifying an *existing* object loaded from disk).  Without this,
    the GnuCash dirty-tracking system doesn't know the object has changed and
    CommitEdit / session.save() may skip re-writing it.
    """
    with contextlib.suppress(Exception):
        lib = _load_gnc_engine()
        lib.qof_instance_set_dirty.restype = None
        lib.qof_instance_set_dirty.argtypes = [ctypes.c_void_p]
        lib.qof_instance_set_dirty(ctypes.c_void_p(obj_ptr))


def _set_string_slot(obj, slot_name: str, value: str) -> bool:
    """Set a string KVP slot on a GnuCash object. Returns True on success.

    Through `qof_instance` in ctypes, on every supported version — not as a
    fallback for one of them. The SWIG spelling this tried first, `from
    gnucash import KvpValue` plus `obj.GetSlots()`, exists on none of the ten:
    measured on GnuCash 5.10, 5.15 and 3.8, the import raises `ImportError`
    and `Transaction` carries no `GetSlots` attribute at all. So the branch
    labelled "GnuCash 4.x+" could only ever raise, and the one labelled
    "GnuCash 3.8 / Ubuntu 20" was doing the work everywhere, under a comment
    saying it was for one distribution.

    Marking the instance dirty is what makes the XML backend re-serialise the
    object on save; a slot written without it is lost on the way to disk.
    """
    try:
        obj_ptr = int(obj.instance)
        if _set_via_qof_instance(obj_ptr, slot_name, value):
            _mark_instance_dirty(obj_ptr)
            return True
    except Exception as e:
        logging.error(f"Failed to set KVP slot {slot_name!r}: {e}")
    return False


def _get_string_slot(obj, slot_name: str) -> Optional[str]:
    """Get a string KVP slot from a GnuCash object. Returns None if not found.

    Through `qof_instance` in ctypes, for the reason its writing counterpart
    gives: `obj.GetSlots()` raises `AttributeError` on every supported build,
    so the SWIG reader that stood above this could never return a value.
    """
    try:
        obj_ptr = int(obj.instance)
        return _get_via_qof_instance(obj_ptr, slot_name)
    except Exception as e:
        logging.debug(f"qof_instance ctypes get failed for {slot_name!r}: {e}")
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _validate_custom_keys(metadata: dict) -> None:
    """
    Reject custom metadata keys that contain a colon.

    Colons are the key/value delimiter in the plaintext format (`key: value`).
    Allowing colons inside a key name would create parsing ambiguity —
    the parser cannot tell where the key ends and the value begins.
    Use dots for hierarchical keys instead (e.g. `tax.category`).

    Raises:
        ValueError: If any key contains a colon.
    """
    bad = [k for k in metadata if ':' in k]
    if bad:
        raise ValueError(
            f"Custom metadata keys must not contain ':' (parsing ambiguity). "
            f"Use dots for hierarchy instead (e.g. 'tax.category'). "
            f"Invalid keys: {bad}"
        )


def set_custom_metadata(obj, metadata: dict) -> None:
    """
    Store custom metadata on a GnuCash Transaction or Split as a KVP slot.

    Serializes metadata as JSON in the 'plaintext_metadata' slot.
    Any existing custom metadata in that slot is replaced — including by
    nothing: an empty dict empties the slot, so a caller that reads the
    metadata, drops the last key and writes the rest back leaves the object
    carrying none, rather than carrying what it had before the read.

    Note on merge workflows: callers that read existing metadata with
    `get_custom_metadata`, update it, and then call this function must only
    pass the *merged* dict (not the raw stored one) — `get_custom_metadata`
    already strips any pre-existing colon keys, so the merged dict will be
    clean.

    Args:
        obj:      GnuCash Transaction or Split object (must be in BeginEdit
                  state if it is a Transaction)
        metadata: Dict of string key → string/int/float/bool values.
                  Keys must not contain ':' (parsing ambiguity); use dots
                  for hierarchy (e.g. 'tax.category').

    Raises:
        ValueError: If any key in *metadata* contains a colon.
    """
    _validate_custom_keys(metadata)
    try:
        json_str = json.dumps(metadata, ensure_ascii=False, sort_keys=True)
        _set_string_slot(obj, PT_DATA_SLOT, json_str)
    except Exception as e:
        logging.error(f"Failed to store custom metadata: {e}")


def set_book_string_option(book, section: str, name: str, value: str) -> bool:
    """Set a string-valued book option at the canonical nested slot path
    `options → <section> → <name>`. This is the same KVP layout the
    GnuCash File→Properties dialog writes to, and the same one
    `read_book_company_info` reads from. Used to populate book-level
    options like Business→Company Name without going through the
    GnuCash GUI.

    Calls `qof_book_set_string_option(book, opt_name, opt_val)` via
    ctypes: opt_name is slash-separated (e.g. `options/Business/Company
    Name`) and the C side does the GSList path construction +
    `g_strdup`-ing internally — no lifetime / variadic-ABI hazards to
    manage in Python. Marks the book instance dirty so the next
    session save serialises the new slots to XML.

    There is no SWIG fallback: GnuCash's Python bindings don't expose
    `KvpValue` at the top level on any platform we ship (verified on
    Debian 11/12/13, Ubuntu 20/22/24/26), and the `KvpFrame.set_slot_path`
    method on `book.GetSlots()` requires a `KvpValue` to wrap the string.
    All paths funnel through ctypes.

    Why this exists separately from `set_custom_metadata`: that helper
    targets per-business-object KVPs (transactions, invoices) at a
    single flat slot key (`plaintext_metadata`). Book options live at a
    nested 3-deep path in a different namespace, so they need their
    own API.
    A caller that has to *report* a failure — a command whose whole job is
    the one write — calls `write_book_string_option` instead, which lets the
    reason out rather than leaving it in the log.
    """
    try:
        write_book_string_option(book, section, name, value)
        return True
    except Exception as e:
        logging.error(
            f"Failed to set book option options/{section}/{name}: {e}"
        )
        return False


def write_book_string_option(book, section: str, name: str, value: str) -> None:
    """`set_book_string_option`, with the failure raised rather than logged.

    The bool form is what a bulk write wants: importing a ledger sets many
    options, and one refused slot is reported beside everything else the run
    reported rather than ending it. A command setting a single option wants
    the opposite — the reason the write failed is the only thing to say, and
    a bool has already thrown it away by the time the caller sees `False`.

    One body, two contracts, so the ctypes call and the dirty-marking below
    exist once.
    """
    obj_ptr = int(book.instance)
    lib = _load_gnc_engine()
    lib.qof_book_set_string_option.argtypes = [
        ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p,
    ]
    lib.qof_book_set_string_option.restype = None

    opt_path = f'options/{section}/{name}'.encode()
    lib.qof_book_set_string_option(
        ctypes.c_void_p(obj_ptr),
        opt_path,
        value.encode('utf-8'),
    )
    # qof_book_set_string_option marks the book dirty internally,
    # but call our helper too so the session save reliably re-emits
    # the slots (matches the pattern of every other write here).
    _mark_instance_dirty(obj_ptr)


def get_book_string_option(book, section: str, name: str) -> Optional[str]:
    """Read a string-valued book option from the nested slot path
    `options → <section> → <name>` — the inverse of
    `set_book_string_option`, and the same layout `read_book_company_info`
    walks in the saved XML. Reads straight from the live in-memory book
    via `qof_book_get_string_option(book, opt_name)` (ctypes), so it sees
    unsaved writes and needs no file path.

    Returns the option value, or None when the slot is absent. Verified
    on GnuCash 3.8 (Ubuntu 20) through 5.x (Debian 13): the C getter
    resolves the slash-separated path internally, including custom slots
    such as `Company GST Number` that GnuCash itself never writes.
    """
    try:
        obj_ptr = int(book.instance)
        lib = _load_gnc_engine()
        lib.qof_book_get_string_option.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        lib.qof_book_get_string_option.restype = ctypes.c_char_p

        opt_path = f'options/{section}/{name}'.encode()
        raw = lib.qof_book_get_string_option(ctypes.c_void_p(obj_ptr), opt_path)
        if raw is None:
            return None
        return raw.decode('utf-8')
    except Exception as e:
        logging.debug(
            f"Failed to read book option options/{section}/{name}: {e}"
        )
        return None


def get_book_custom_metadata(book) -> dict:
    """Read the book's custom-metadata JSON blob (the keys the `company`
    directive's non-Business tier and `set-book-key` share) as a dict."""
    current = get_book_string_option(book, COMPANY_CUSTOM_SECTION, COMPANY_CUSTOM_SLOT)
    if not current:
        return {}
    try:
        data = json.loads(current)
        return data if isinstance(data, dict) else {}
    except (ValueError, TypeError):
        return {}


def merge_book_custom_metadata(book, updates: dict) -> bool:
    """Upsert keys into the book's custom-metadata blob with **JSON Merge Patch**
    semantics (RFC 7386): a key with a non-None value is set; a key whose value
    is None is *removed*; keys not named in `updates` are left untouched. This is
    the single, shared writer for the `company` directive's custom keys and
    `set-book-key`, so both behave identically — a partial update never silently
    drops keys it didn't mention. Returns True if the stored blob changed."""
    current = get_book_string_option(book, COMPANY_CUSTOM_SECTION, COMPANY_CUSTOM_SLOT) or ''
    try:
        data = json.loads(current) if current else {}
        if not isinstance(data, dict):
            data = {}
    except (ValueError, TypeError):
        data = {}

    for key, value in updates.items():
        if value is None:
            data.pop(key, None)
        else:
            data[key] = value

    blob = json.dumps(data, ensure_ascii=False, sort_keys=True)
    if blob != current:
        set_book_string_option(book, COMPANY_CUSTOM_SECTION, COMPANY_CUSTOM_SLOT, blob)
        return True
    return False


def get_custom_metadata(obj) -> dict:
    """
    Read custom metadata from a GnuCash Transaction or Split KVP slot.

    Any stored keys that contain ':' (written by external tools or by an
    earlier version of this code before the colon restriction was added) are
    silently dropped with a warning.  This prevents merge operations from
    failing with a confusing error when the invalid key came from stored data
    rather than from the current directive.

    Returns:
        Dict of custom key-value pairs, or {} if no custom metadata stored.
        Keys containing ':' are excluded from the returned dict.
    """
    json_str = _get_string_slot(obj, PT_DATA_SLOT)
    if not json_str:
        return {}
    try:
        result = json.loads(json_str)
        if not isinstance(result, dict):
            return {}
        # Sanitize: drop keys that would now be rejected by _validate_custom_keys.
        sanitized = {}
        for k, v in result.items():
            if ':' in k:
                logging.warning(
                    f"Custom metadata key {k!r} contains ':' (written by an "
                    f"external tool or older version); dropping it on read."
                )
            else:
                sanitized[k] = v
        return sanitized
    except (json.JSONDecodeError, TypeError) as e:
        logging.warning(f"Failed to parse custom metadata JSON from KVP: {e}")
        return {}
