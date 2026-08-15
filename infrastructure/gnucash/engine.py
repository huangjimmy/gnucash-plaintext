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
import logging
from functools import lru_cache

ENGINE_LIB_PATHS = [
    '/usr/lib/x86_64-linux-gnu/gnucash/libgnc-engine.so',            # Debian 11/12/13, Ubuntu 22/24
    '/usr/lib/x86_64-linux-gnu/gnucash/gnucash/libgncmod-engine.so', # Ubuntu 20 (GnuCash 3.8)
    '/usr/lib64/gnucash/libgnc-engine.so',                           # Fedora 41+
    '/usr/lib64/libgnc-engine.so',                                   # openSUSE Tumbleweed
    '/usr/lib/libgnc-engine.so',                                     # Arch Linux
]


class GncNumericC(ctypes.Structure):
    """Mirrors the C GncNumeric struct: {int64 num, int64 denom}."""
    _fields_ = [('num', ctypes.c_int64), ('denom', ctypes.c_int64)]


class GList(ctypes.Structure):
    """GLib GList structure for safe traversal of lists returned by GnuCash C functions.

    GList layout: [data, next, prev] pointers.
    GnuCash often returns GList* from functions like gncTaxTableGetTables().
    """
    _fields_ = [
        ('data', ctypes.c_void_p),
        ('next', ctypes.c_void_p),
        ('prev', ctypes.c_void_p)
    ]

    @classmethod
    def from_address(cls, address):
        """Safe cast from integer address to GList* pointer."""
        return ctypes.cast(address, ctypes.POINTER(cls)).contents


def iterate_glist(lib, glist_ptr, process_func):
    """Safely iterate through GList returned by GnuCash C functions.

    Args:
        lib: ctypes.CDLL loaded with load_gnc_engine()
        glist_ptr: Integer pointer to GList (from ctypes function)
        process_func: Function that processes each element (lib, data_ptr) -> result

    Returns:
        List of results from process_func

    Note:
        GnuCash prepends to lists, so results are in reverse insertion order.
        Reverse the output if you need chronological/insertion order.
    """
    results = []
    while glist_ptr:
        try:
            glist = GList.from_address(glist_ptr)
        except Exception as e:
            logging.warning(f"Failed to read GList node at {glist_ptr:#x}: {e}")
            break  # Cannot know where the next node is; stop safely
        glist_ptr = glist.next  # Advance before processing so a bad element doesn't stall iteration
        if glist.data:
            try:
                results.append(process_func(lib, glist.data))
            except Exception as e:
                logging.warning(f"Failed to process GList element at {glist.data:#x}: {e}")
    return results


def safe_ctypes_string(func, ptr, default=""):
    """Call ctypes string-returning function with null check and UTF-8 decoding.

    Args:
        func: ctypes function that returns c_char_p
        ptr: Pointer argument to pass to func
        default: Default value if function returns None or empty

    Returns:
        Decoded UTF-8 string or default
    """
    result = func(ptr)
    return result.decode('utf-8') if result else default


def verify_ctypes_functions(lib, required_functions=None):
    """Verify critical ctypes functions exist before use.

    Args:
        lib: ctypes.CDLL loaded with load_gnc_engine()
        required_functions: List of function names to check (defaults to common ones)

    Raises:
        RuntimeError if any required functions are missing
    """
    if required_functions is None:
        required_functions = [
            'gncTaxTableGetTables',
            'gncTaxTableGetName',
            'gncTaxTableGetEntries',
            'gncTaxTableEntryGetAccount',
            'gncTaxTableEntryGetAmount',
            'xaccAccountGetName',
            'xaccAccountGetCommodity',
            'xaccAccountGetCommoditySCU',
            'xaccSplitGetAccount',
            'xaccAccountGetType',
            'gnc_account_get_parent',
            'gncEntryGetDescription',
            'gncEntryGetAction',
            'gncEntryGetQuantity',
            'gncEntryGetInvPrice',
            'gncEntryGetBillPrice',
            'gncEntryGetBillTaxable',
            'gncEntryGetBillTaxIncluded',
            'gncEntryGetBillTaxTable',
            # Whose money a payment split is. A payment block reaches a split
            # by guid, and without these there is no way to tell one owner's
            # money from another's — so a book would import with the check
            # that stops a customer's credit settling somebody else's invoice
            # quietly doing nothing. Failing here, before a book is opened,
            # is the whole point: the alternative is a file that imports
            # clean and reads as though it had been checked.
            'gncOwnerGetOwnerFromLot',
            'gncOwnerGetOwnerFromTxn',
            'gncOwnerGetID',
            'gncOwnerGetType',
            'gncOwnerGetGUID',
            'guid_to_string_buff',
            # Dividing a payment bigger than the document it settles. Absent,
            # an overpayment would take the document's own lot past zero and
            # leave the owner's money where nothing can spend it.
            'xaccSplitSetAccount',
            'gnc_lot_new',
            'xaccAccountInsertLot',
            'gnc_lot_add_split',
            'gncOwnerInitCustomer',
            'gncOwnerInitVendor',
            'gncOwnerAttachToLot',
            # Which book everything else is about. Rendering a document asks
            # GnuCash's own report to draw it, and the report resolves the
            # document from a guid against the *current* book — the Python
            # bindings open a session without making it current, so this says
            # so. Declared here like every other pointer-taking call: passed
            # as a Python int with no argtypes, the session pointer would be
            # truncated to 32 bits.
            'gnc_set_current_session',
        ]

    missing = [f for f in required_functions if not hasattr(lib, f)]
    if missing:
        raise RuntimeError(
            f"GnuCash C library missing required functions: {missing}\n"
            f"This usually means libgnc-engine.so couldn't be loaded properly.\n"
            f"Check that GnuCash is installed and library paths are correct."
        )


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
    # ── Owner ────────────────────────────────────────────────────────────────
    # Whose money a lot or a payment transaction holds. Set here with every
    # other signature rather than at each call: an argtypes line that lives
    # beside its caller is one a second caller does without, and a pointer
    # passed without argtypes is truncated to 32 bits on x86_64.
    lib.gncOwnerGetOwnerFromLot.restype        = ctypes.c_int
    lib.gncOwnerGetOwnerFromLot.argtypes       = [ctypes.c_void_p, ctypes.c_void_p]
    lib.gncOwnerGetOwnerFromTxn.restype        = ctypes.c_int
    lib.gncOwnerGetOwnerFromTxn.argtypes       = [ctypes.c_void_p, ctypes.c_void_p]
    lib.gncOwnerGetID.restype                  = ctypes.c_char_p
    lib.gncOwnerGetID.argtypes                 = [ctypes.c_void_p]
    lib.gncOwnerGetType.restype                = ctypes.c_int
    lib.gncOwnerGetType.argtypes               = [ctypes.c_void_p]
    lib.gncOwnerGetGUID.restype                = ctypes.c_void_p
    lib.gncOwnerGetGUID.argtypes               = [ctypes.c_void_p]
    lib.guid_to_string_buff.restype            = ctypes.c_char_p
    lib.guid_to_string_buff.argtypes           = [ctypes.c_void_p, ctypes.c_char_p]
    # Putting an owner on a lot: a credit's lot is where the book records whose
    # money it is, and a lot without one is money nothing can apply or refund.
    # A GncOwner has to be built from the Customer/Vendor first — handing the
    # raw pointer to gncOwnerAttachToLot is a silent no-op.
    lib.gncOwnerInitCustomer.restype           = None
    lib.gncOwnerInitCustomer.argtypes          = [ctypes.c_void_p, ctypes.c_void_p]
    lib.gncOwnerInitVendor.restype             = None
    lib.gncOwnerInitVendor.argtypes            = [ctypes.c_void_p, ctypes.c_void_p]
    lib.gncOwnerAttachToLot.restype            = None
    lib.gncOwnerAttachToLot.argtypes           = [ctypes.c_void_p, ctypes.c_void_p]
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
    # ── Bill entry ───────────────────────────────────────────────────────────
    lib.gncEntryGetBillPrice.restype           = GncNumericC
    lib.gncEntryGetBillPrice.argtypes          = [ctypes.c_void_p]
    lib.gncEntryGetBillTaxable.restype         = ctypes.c_int
    lib.gncEntryGetBillTaxable.argtypes        = [ctypes.c_void_p]
    lib.gncEntryGetBillTaxIncluded.restype     = ctypes.c_int
    lib.gncEntryGetBillTaxIncluded.argtypes    = [ctypes.c_void_p]
    lib.gncEntryGetBillTaxTable.restype        = ctypes.c_void_p
    lib.gncEntryGetBillTaxTable.argtypes       = [ctypes.c_void_p]
    # ── Split, transaction and lot ───────────────────────────────────────────
    # Lots are how this project reads and writes ownership of money: a credit
    # sits in a lot of the owner's, a settlement in one the document owns, and
    # dividing a payment that covers more than its document owes moves one into
    # the other. Declared here for the reason the owner lookups above are — a
    # signature that lives beside its caller is one the next caller does
    # without, and a pointer passed with no argtypes is truncated to 32 bits on
    # x86_64, which segfaults rather than failing.
    #
    # Declared once, so two callers cannot disagree about the same symbol: the
    # handle is cached process-wide, so a second, different declaration is not
    # a local choice — it rewrites what every earlier caller is holding.
    lib.xaccSplitSetAccount.restype            = None
    lib.xaccSplitSetAccount.argtypes           = [ctypes.c_void_p, ctypes.c_void_p]
    lib.xaccSplitGetParent.restype             = ctypes.c_void_p
    lib.xaccSplitGetParent.argtypes            = [ctypes.c_void_p]
    lib.xaccSplitGetAmount.restype             = GncNumericC
    lib.xaccSplitGetAmount.argtypes            = [ctypes.c_void_p]
    lib.xaccTransGetDate.restype               = ctypes.c_int64
    lib.xaccTransGetDate.argtypes              = [ctypes.c_void_p]
    lib.gnc_lot_new.restype                    = ctypes.c_void_p
    lib.gnc_lot_new.argtypes                   = [ctypes.c_void_p]
    # Read by nobody, so `None` is right whether the C function returns void or
    # a gboolean — where declaring an int for a void function reads whatever
    # the return register happened to hold.
    lib.gnc_set_current_session.restype        = None
    lib.gnc_set_current_session.argtypes       = [ctypes.c_void_p]
    lib.gnc_lot_add_split.restype              = None
    lib.gnc_lot_add_split.argtypes             = [ctypes.c_void_p, ctypes.c_void_p]
    lib.gnc_lot_get_balance.restype            = GncNumericC
    lib.gnc_lot_get_balance.argtypes           = [ctypes.c_void_p]
    lib.gnc_lot_is_closed.restype              = ctypes.c_int
    lib.gnc_lot_is_closed.argtypes             = [ctypes.c_void_p]
    lib.gnc_lot_get_earliest_split.restype     = ctypes.c_void_p
    lib.gnc_lot_get_earliest_split.argtypes    = [ctypes.c_void_p]
    lib.xaccAccountInsertLot.restype           = None
    lib.xaccAccountInsertLot.argtypes          = [ctypes.c_void_p, ctypes.c_void_p]
    lib.xaccAccountGetLotList.restype          = ctypes.c_void_p
    lib.xaccAccountGetLotList.argtypes         = [ctypes.c_void_p]
    # A split's amount is in its *account's* commodity, which is not the
    # transaction's on a foreign document settled from a base-currency bank.
    lib.xaccAccountGetCommodity.restype        = ctypes.c_void_p
    lib.xaccAccountGetCommodity.argtypes       = [ctypes.c_void_p]
    # And the unit that account is kept to, which is not the commodity's
    # fraction wherever `commodity_scu:` says otherwise.
    lib.xaccAccountGetCommoditySCU.restype     = ctypes.c_int
    lib.xaccAccountGetCommoditySCU.argtypes    = [ctypes.c_void_p]
    # Which account a split is on, and what kind it is — asked of every split
    # of every transaction on the way out, to find the few on a receivable or
    # payable before anything more expensive is read off them.
    lib.xaccSplitGetAccount.restype            = ctypes.c_void_p
    lib.xaccSplitGetAccount.argtypes           = [ctypes.c_void_p]
    lib.xaccAccountGetType.restype             = ctypes.c_int
    lib.xaccAccountGetType.argtypes            = [ctypes.c_void_p]
    lib.gncInvoiceGetInvoiceFromLot.restype    = ctypes.c_void_p
    lib.gncInvoiceGetInvoiceFromLot.argtypes   = [ctypes.c_void_p]
    # The date format every date on a printed page that is *not* the
    # document's own is written in. A process-wide setting: GnuCash's GUI
    # writes it at startup from its own preference, and nothing does in a
    # process that only loaded the library, so it sits at its compiled
    # default of `QOF_DATE_FORMAT_LOCALE` and the printing machine's locale
    # decides. See `services/gnucash_report.py`, which sets it from the book.
    lib.qof_date_format_set.restype            = None
    lib.qof_date_format_set.argtypes           = [ctypes.c_int]
    lib.qof_date_format_get.restype            = ctypes.c_int
    lib.qof_date_format_get.argtypes           = []


@lru_cache(maxsize=1)
def load_gnc_engine() -> ctypes.CDLL:
    """Load libgnc-engine and return a correctly configured ctypes handle.

    Always promotes the library to RTLD_GLOBAL via its known on-disk path
    before calling CDLL(None), ensuring we use the same library instance as
    the GnuCash Python extension (critical on Ubuntu where RTLD_LOCAL is
    the default).
    """
    for path in ENGINE_LIB_PATHS:
        try:
            ctypes.CDLL(path, mode=ctypes.RTLD_GLOBAL)
            lib = ctypes.CDLL(None)
            _setup_lib_restypes(lib)
            verify_ctypes_functions(lib)
            return lib
        except (OSError, AttributeError, RuntimeError):
            pass

    # Final fallback: symbols already globally visible (e.g. RTLD_GLOBAL load
    # by another part of the process, or LD_PRELOAD).
    try:
        lib = ctypes.CDLL(None)
        _setup_lib_restypes(lib)
        verify_ctypes_functions(lib)
        return lib
    except (OSError, AttributeError, RuntimeError):
        pass

    raise RuntimeError(
        "Could not load libgnc-engine.so — tried: " + str(ENGINE_LIB_PATHS)
    )
