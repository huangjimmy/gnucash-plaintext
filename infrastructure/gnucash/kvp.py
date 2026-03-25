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
})

# Split metadata keys that have dedicated GnuCash setters.
KNOWN_SPLIT_METADATA_KEYS = frozenset({
    'share_price',
    'value',
    'action',
    'memo',
    'account.commodity.mnemonic',
    'account.commodity.namespace',
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

def set_custom_metadata(obj, metadata: dict) -> None:
    """
    Store custom metadata on a GnuCash Transaction or Split as a KVP slot.

    Serializes metadata as JSON in the 'plaintext_metadata' slot.
    Any existing custom metadata in that slot is replaced.

    Args:
        obj:      GnuCash Transaction or Split object (must be in BeginEdit
                  state if it is a Transaction)
        metadata: Dict of string key → string/int/float/bool values
    """
    if not metadata:
        return
    try:
        json_str = json.dumps(metadata, ensure_ascii=False, sort_keys=True)
        _set_string_slot(obj, PT_DATA_SLOT, json_str)
    except Exception as e:
        logging.error(f"Failed to store custom metadata: {e}")


def get_custom_metadata(obj) -> dict:
    """
    Read custom metadata from a GnuCash Transaction or Split KVP slot.

    Returns:
        Dict of custom key-value pairs, or {} if no custom metadata stored.
    """
    json_str = _get_string_slot(obj, PT_DATA_SLOT)
    if not json_str:
        return {}
    try:
        result = json.loads(json_str)
        if isinstance(result, dict):
            return result
        return {}
    except (json.JSONDecodeError, TypeError) as e:
        logging.warning(f"Failed to parse custom metadata JSON from KVP: {e}")
        return {}
