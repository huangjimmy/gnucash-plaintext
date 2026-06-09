"""
KVP slot utilities for storing custom metadata on GnuCash objects.

Custom metadata is stored as a JSON string in a single 'plaintext_metadata'
slot to avoid KvpFrame key-enumeration complexity across GnuCash versions.

## Cross-version compatibility

GnuCash 4.x+  (Debian 11/12/13, Ubuntu 22/24):
    Uses SWIG KvpFrame.set_slot_path / get_slot_path with KvpValue.
    Transaction and Split objects expose .GetSlots() → KvpFrame.

GnuCash 3.8   (Ubuntu 20.04):
    Transaction and Split do NOT expose .GetSlots(). The KVP API changed
    between 3.x and 4.x. Falls back to ctypes qof_instance_set_kvp /
    qof_instance_get_kvp with a GLib GValue (from libgobject-2.0).
    These functions are in libgncmod-engine.so (not libgnc-engine.so).

Both paths use the flat slot name 'plaintext_metadata' (no slashes) to
avoid the difference between flat-key and nested-path semantics.
"""
import contextlib
import ctypes
import json
import logging
from typing import Optional

PT_DATA_SLOT = 'plaintext_metadata'

# Transaction metadata keys that have dedicated GnuCash setters.
# Any key NOT in this set is treated as custom metadata → KVP slot.
KNOWN_TX_METADATA_KEYS = frozenset({
    'guid',
    'currency.namespace',
    'currency.mnemonic',
    'doc_link',
    'notes',
    # NOTE: `txn_type` and `owner` are deliberately NOT in this set even
    # though the exporter emits them on payment-class transactions. The
    # in-memory mutators (`xaccTransSetTxnType`, `gncOwnerCopyOnTxn`) are
    # no-ops from Python in GnuCash 5.x (both ctypes and SWIG paths
    # silently fail to mutate). Letting them fall into the custom-KVP
    # path makes the values round-trip-preserved as plain KVP slots —
    # `find-orphan-payments` reads either the C field (in-book) or the
    # KVP (after a plaintext roundtrip).
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

# Customer metadata keys that have dedicated GnuCash setters.
KNOWN_CUSTOMER_METADATA_KEYS = frozenset({
    'guid', 'name', 'currency', 'addr1', 'addr2', 'addr3', 'addr4', 'email', 'active',
})

# Vendor metadata keys that have dedicated GnuCash setters.
KNOWN_VENDOR_METADATA_KEYS = frozenset({
    'guid', 'name', 'currency', 'active',
})

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


# ---------------------------------------------------------------------------
# GLib GValue helper (used for GnuCash 3.8 ctypes path)
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

_gobj: Optional[ctypes.CDLL] = None


def _load_gobject() -> Optional[ctypes.CDLL]:
    """Load libgobject-2.0 (needed for GValue init/set/get on GnuCash 3.8)."""
    global _gobj
    if _gobj is not None:
        return _gobj
    with contextlib.suppress(OSError):
        _gobj = ctypes.CDLL('libgobject-2.0.so.0')
        return _gobj
    return None


def _load_gnc_engine() -> ctypes.CDLL:
    """
    Load libgncmod-engine with RTLD_GLOBAL promotion.

    On Ubuntu (RTLD_LOCAL extension loading), the library must be promoted
    to RTLD_GLOBAL before CDLL(None) so ctypes and the Python bindings share
    the same in-memory instance.

    GnuCash 3.8: qof_instance_set_kvp / qof_instance_get_kvp live in
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
# GnuCash 3.8 ctypes path: qof_instance_set/get_kvp + GValue
# ---------------------------------------------------------------------------

def _set_via_qof_instance(obj_ptr: int, slot_name: str, value: str) -> bool:
    """
    GnuCash 3.8: qof_instance_set_kvp(QofInstance*, GValue*, unsigned, ...).

    Sets a single string KVP slot on a QofInstance (Transaction or Split).
    Available in libgncmod-engine.so from GnuCash 3.8 / Ubuntu 20.
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
    GnuCash 3.8: qof_instance_get_kvp(QofInstance*, GValue*, unsigned, ...).
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
# Unified set / get (tries SWIG first, falls back to ctypes for 3.8)
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
    """Set a string KVP slot on a GnuCash object. Returns True on success."""
    # --- SWIG path (GnuCash 4.x+: Transaction/Split have .GetSlots()) ---
    try:
        from gnucash import KvpValue
        frame = obj.GetSlots()
        frame.set_slot_path([slot_name], KvpValue(value))
        # Verify round-trip (catches silent 3.8 failures if GetSlots existed)
        kv = frame.get_slot_path([slot_name])
        if kv is not None:
            # Mark dirty so the XML backend re-serialises this object on save.
            _mark_instance_dirty(int(obj.instance))
            return True
        logging.debug(
            f"SWIG set_slot_path for {slot_name!r} appeared to succeed but "
            f"get_slot_path returned None; trying ctypes fallback."
        )
    except AttributeError:
        # GetSlots() missing → GnuCash 3.8; fall through to ctypes below
        pass
    except Exception as e:
        logging.debug(f"SWIG KvpFrame set failed for {slot_name!r}: {e}")

    # --- ctypes path (GnuCash 3.8 / Ubuntu 20) ---
    try:
        obj_ptr = int(obj.instance)
        if _set_via_qof_instance(obj_ptr, slot_name, value):
            _mark_instance_dirty(obj_ptr)
            return True
    except Exception as e:
        logging.error(f"Failed to set KVP slot {slot_name!r}: {e}")
    return False


def _get_string_slot(obj, slot_name: str) -> Optional[str]:
    """Get a string KVP slot from a GnuCash object. Returns None if not found."""
    # --- SWIG path (GnuCash 4.x+) ---
    try:
        frame = obj.GetSlots()
        if frame is not None:
            try:
                kv = frame.get_slot_path([slot_name])
                if kv is not None:
                    for method in ('get', 'to_string'):
                        with contextlib.suppress(Exception):
                            result = getattr(kv, method)()
                            if isinstance(result, str):
                                return result
                    result = str(kv)
                    if result and result != 'None':
                        return result
            except Exception as e:
                logging.debug(f"SWIG get_slot_path failed for {slot_name!r}: {e}")
            return None
    except AttributeError:
        # GetSlots() missing → GnuCash 3.8; fall through to ctypes below
        pass
    except Exception as e:
        logging.debug(f"Failed to get KVP slot {slot_name!r}: {e}")

    # --- ctypes path (GnuCash 3.8 / Ubuntu 20) ---
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
    Any existing custom metadata in that slot is replaced.

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
    if not metadata:
        return
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
    """
    try:
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
        return True
    except Exception as e:
        logging.error(
            f"Failed to set book option options/{section}/{name}: {e}"
        )
        return False


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
