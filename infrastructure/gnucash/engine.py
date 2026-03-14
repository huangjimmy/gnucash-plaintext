"""
Shared ctypes loader for GnuCash's libgnc-engine.

Why ctypes instead of the SWIG bindings
----------------------------------------
Several GnuCash C functions (tax-table access, invoice-entry fields) have
const-type mismatches in the SWIG Python bindings that make them unusable
from Python directly (confirmed on GnuCash 4.4–5.10, all supported distros).

Why RTLD_GLOBAL + CDLL(None) instead of CDLL(path)
----------------------------------------------------
On Debian the GnuCash Python extension loads libgnc-engine with RTLD_GLOBAL,
so CDLL(None) naturally finds the correct already-loaded instance.
On Ubuntu the extension uses RTLD_LOCAL (Python's default for .so modules),
so CDLL(None) may resolve symbols from a *different* globally-visible copy,
causing a library-instance mismatch and segfault inside gncTaxTableGetTables.

Fix: always call dlopen on the known .so path with RTLD_GLOBAL *first*.
If the library is already mapped (same inode), dlopen reuses the existing
mapping and merely promotes its symbols to the global table — no second copy
is created.  The subsequent CDLL(None) then resolves every symbol from the
*same* instance that the GnuCash Python extension is using.

Why argtypes must be set for every pointer argument
----------------------------------------------------
Without argtypes, Python ctypes converts integer arguments to C int (32-bit).
On x86_64 a 64-bit pointer like 0x7f1234567890 is silently truncated to
0x34567890 — a garbage address — and the C function segfaults.
Setting argtypes = [ctypes.c_void_p] tells ctypes to pass the full 64-bit
value.  This is mandatory; omitting it will crash on Ubuntu (and silently
give wrong results on any 64-bit platform if the pointer happens to be >4 GB).
"""
import ctypes

_ENGINE_LIB_PATHS = [
    '/usr/lib/x86_64-linux-gnu/gnucash/libgnc-engine.so',            # Debian 11/12/13, Ubuntu 22/24
    '/usr/lib/x86_64-linux-gnu/gnucash/gnucash/libgncmod-engine.so', # Ubuntu 20 (GnuCash 3.8)
]


class GncNumericC(ctypes.Structure):
    """Mirrors the C GncNumeric struct: {int64 num, int64 denom}."""
    _fields_ = [('num', ctypes.c_int64), ('denom', ctypes.c_int64)]


def _setup_lib_restypes(lib: ctypes.CDLL) -> None:
    """Set restype AND argtypes for every ctypes function we call.

    argtypes must be set for every function that takes a pointer argument.
    Without it ctypes uses C int (32-bit) for Python integers, truncating
    64-bit pointers on x86_64 and causing segfaults.
    """
    # ── Tax table ────────────────────────────────────────────────────────────
    lib.gncTaxTableGetTables.restype           = ctypes.c_void_p
    lib.gncTaxTableGetTables.argtypes          = [ctypes.c_void_p]
    lib.gncTaxTableGetName.restype             = ctypes.c_char_p
    lib.gncTaxTableGetName.argtypes            = [ctypes.c_void_p]
    lib.gncTaxTableGetEntries.restype          = ctypes.c_void_p
    lib.gncTaxTableGetEntries.argtypes         = [ctypes.c_void_p]
    lib.gncTaxTableEntryGetAccount.restype     = ctypes.c_void_p
    lib.gncTaxTableEntryGetAccount.argtypes    = [ctypes.c_void_p]
    lib.gncTaxTableEntryGetType.restype        = ctypes.c_int
    lib.gncTaxTableEntryGetType.argtypes       = [ctypes.c_void_p]
    lib.gncTaxTableEntryGetAmount.restype      = GncNumericC
    lib.gncTaxTableEntryGetAmount.argtypes     = [ctypes.c_void_p]
    # ── Account ──────────────────────────────────────────────────────────────
    lib.xaccAccountGetName.restype             = ctypes.c_char_p
    lib.xaccAccountGetName.argtypes            = [ctypes.c_void_p]
    lib.gnc_account_get_parent.restype         = ctypes.c_void_p
    lib.gnc_account_get_parent.argtypes        = [ctypes.c_void_p]
    lib.gnc_account_get_full_name.restype      = ctypes.c_char_p
    lib.gnc_account_get_full_name.argtypes     = [ctypes.c_void_p]
    # ── Invoice entry ────────────────────────────────────────────────────────
    lib.gncEntryGetDescription.restype         = ctypes.c_char_p
    lib.gncEntryGetDescription.argtypes        = [ctypes.c_void_p]
    lib.gncEntryGetAction.restype              = ctypes.c_char_p
    lib.gncEntryGetAction.argtypes             = [ctypes.c_void_p]
    lib.gncEntryGetQuantity.restype            = GncNumericC
    lib.gncEntryGetQuantity.argtypes           = [ctypes.c_void_p]
    lib.gncEntryGetInvPrice.restype            = GncNumericC
    lib.gncEntryGetInvPrice.argtypes           = [ctypes.c_void_p]
    lib.gncEntryGetInvTaxable.restype          = ctypes.c_int
    lib.gncEntryGetInvTaxable.argtypes         = [ctypes.c_void_p]
    lib.gncEntryGetInvTaxIncluded.restype      = ctypes.c_int
    lib.gncEntryGetInvTaxIncluded.argtypes     = [ctypes.c_void_p]
    lib.gncEntryGetInvTaxTable.restype         = ctypes.c_void_p
    lib.gncEntryGetInvTaxTable.argtypes        = [ctypes.c_void_p]


def load_gnc_engine() -> ctypes.CDLL:
    """Load libgnc-engine and return a correctly configured ctypes handle.

    Always promotes the library to RTLD_GLOBAL via its known on-disk path
    before calling CDLL(None), ensuring we use the same library instance as
    the GnuCash Python extension (critical on Ubuntu where RTLD_LOCAL is
    the default).
    """
    for path in _ENGINE_LIB_PATHS:
        try:
            ctypes.CDLL(path, mode=ctypes.RTLD_GLOBAL)
            lib = ctypes.CDLL(None)
            _setup_lib_restypes(lib)
            return lib
        except (OSError, AttributeError):
            pass

    # Final fallback: symbols already globally visible (e.g. RTLD_GLOBAL load
    # by another part of the process, or LD_PRELOAD).
    try:
        lib = ctypes.CDLL(None)
        _setup_lib_restypes(lib)
        return lib
    except AttributeError:
        pass

    raise RuntimeError(
        "Could not load libgnc-engine.so — tried: " + str(_ENGINE_LIB_PATHS)
    )
