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


class GncAccountValueC(ctypes.Structure):
    """Mirrors the C GncAccountValue: {Account *account, gnc_numeric value}.

    What `gncEntryGetDocTaxValues` hands back, one per account a line's tax
    reaches — the same figures its posting splits carry.
    """
    _fields_ = [('account', ctypes.c_void_p), ('value', GncNumericC)]


class GncGuidC(ctypes.Structure):
    """Mirrors the C GncGUID: sixteen raw bytes.

    What `qof_collection_lookup_entity` is asked for, and what
    `guid_from_hex` builds out of the 32 hex characters a file writes.
    """
    _fields_ = [('data', ctypes.c_uint8 * 16)]


def guid_from_hex(guid_norm: str) -> GncGuidC:
    """A `GncGuidC` from 32 lowercase hex characters."""
    guid = GncGuidC()
    for i in range(16):
        guid.data[i] = int(guid_norm[i * 2:i * 2 + 2], 16)
    return guid


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
            # The fields an entry carries beyond the eight this format used
            # to write, and what GnuCash makes a line and a whole page worth.
            'gncEntryGetNotes',
            'gncEntryGetInvDiscount',
            'gncEntryGetBillable',
            'gncEntryGetBillPayment',
            'gncEntryGetBillTo',
            'gncEntrySetBillTo',
            'gncOwnerNew',
            'gncOwnerFree',
            'gncEntryGetDocValue',
            'gncEntryGetDocTaxValue',
            'gncEntryGetDocTaxValues',
            'gncAccountValueDestroy',
            'gncInvoiceGetTotal',
            'gncInvoiceGetTotalSubtotal',
            'gncInvoiceGetTotalTax',
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
            'qof_instance_get_guid',
            # Dividing a payment bigger than the invoice it settles. Absent,
            # an overpayment would take that invoice's lot past zero and
            # leave the owner's money where nothing can spend it.
            'xaccSplitSetAccount',
            # Undoing a link: the split's value is what it takes on an
            # account kept in the transaction's currency.
            'xaccSplitGetValue',
            'xaccSplitSetAmount',
            'gnc_lot_new',
            'xaccAccountInsertLot',
            'gnc_lot_add_split',
            'gncOwnerInitCustomer',
            'gncOwnerInitVendor',
            'gncOwnerAttachToLot',
            # Which book everything else is about. Rendering a page asks
            # GnuCash's own report to draw it, and the report resolves the
            # invoice from a guid against the *current* book — the Python
            # bindings open a session without making it current, so this says
            # so. Declared here like every other pointer-taking call: passed
            # as a Python int with no argtypes, the session pointer would be
            # truncated to 32 bits.
            'gnc_set_current_session',
            # Whether a guid is free. A line, a split and an invoice are each
            # reached only through their collection, so without these a check
            # for "does this book already hold that guid" answers yes about
            # an account and no about the line the file is naming.
            'qof_book_get_collection',
            'qof_collection_lookup_entity',
            # And giving one to a lot the import creates, so a split can say
            # which of an owner's credits it settles.
            'qof_instance_set_guid',
            'gnc_lot_begin_edit',
            'gnc_lot_commit_edit',
            'qof_book_mark_session_dirty',
            'xaccAccountLookup',
            'gncEntryGetBill',
            'gncEntrySetBill',
            'gncEntrySetInvoice',
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
    # ── The book's own answer to "which report prints an invoice" ────────────
    # File → Properties → Business has it, and GnuCash reads it when its own
    # Print Invoice button draws a page. Asked here rather than assuming a
    # report, so a book that names one is printed the way its owner set it up
    # without anyone repeating it on the command line. `None` when nobody has
    # set one, which is a book GnuCash prints with its own built-in default.
    # Declared only where the build has it: the accessor arrived with GnuCash
    # 5 — measured absent from `libgnc-engine.so` and from `qofbook.h` on 4.4
    # and 4.13 as well as 3.8 — and naming a symbol a library does not export
    # raises `AttributeError` here, which took down `load_gnc_engine` itself,
    # so every command that touches the engine failed on those builds with
    # "Could not load libgnc-engine.so". Nothing else in this function is
    # optional, which is why it had no such guard before.
    #
    # `c_void_p` and not `c_char_p`, because the string is the **caller's**:
    # `qofbook.h` declares it `gchar *`, non-const, beside the `const char *`
    # of `qof_book_get_string_option`. Measured on 5.10: consecutive calls
    # return different pointers, and 500 000 of them grow maxrss by 23 MB. As
    # `c_char_p` ctypes copies it and the original is never freed, so the
    # reader is the one who has to — see `_the_report_this_book_prints_with`.
    # The name beside the guid is what the reader picked in that dialog, and
    # it is what a message about their choice has to say: a guid names the
    # report exactly and tells them nothing about which one it is.
    for optional in ('qof_book_get_default_invoice_report_guid',
                     'qof_book_get_default_invoice_report_name'):
        found = getattr(lib, optional, None)
        if found is not None:
            found.restype  = ctypes.c_void_p
            found.argtypes = [ctypes.c_void_p]
    # What frees it. GLib is loaded already — the engine is built on it — so
    # this resolves wherever the accessor above does.
    if getattr(lib, 'g_free', None) is not None:
        lib.g_free.restype  = None
        lib.g_free.argtypes = [ctypes.c_void_p]
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
    # And whose guid to write into that buffer. Read for a line, a lot and
    # an invoice, none of which the bindings give a `GetGUID` (CLAUDE.md
    # §13) — often enough per import that opening the library per call was
    # worth ending.
    lib.qof_instance_get_guid.restype          = ctypes.c_void_p
    lib.qof_instance_get_guid.argtypes         = [ctypes.c_void_p]
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
    # The note an entry carries of its own, beside the invoice's, and the
    # discount figure. Both are shown in GnuCash's invoice window and both
    # survive a save, so a ledger that omits them describes an invoice the
    # book does not hold. The two discount *choices* — what the figure means
    # and where it falls relative to tax — are read through SWIG, being plain
    # ints with no const-type trouble.
    lib.gncEntryGetNotes.restype               = ctypes.c_char_p
    lib.gncEntryGetNotes.argtypes              = [ctypes.c_void_p]
    lib.gncEntryGetInvDiscount.restype         = GncNumericC
    lib.gncEntryGetInvDiscount.argtypes        = [ctypes.c_void_p]
    # What the line is worth, asked of the engine that posts it. A discount
    # is applied by three different rules — measured on 5.10, 10 × 100 less
    # 10% against a 10% tax table posts 900 + 90 `pretax`, 900 + 100
    # `sametime` and 890 + 100 `posttax` — and only these functions know
    # which. Arithmetic of this project's own printed 1000 + 100 for all
    # three, so a page handed to a customer named a total the book
    # contradicted.
    #
    # `(entry, round, is_cust_doc, is_cn)` in GnuCash's own header, which
    # this project spells out: round to the currency's smallest unit as
    # posting does, `is_cust_doc` selects the invoice side or the bill side
    # of the entry, and the last is the credit-note flag — `is_credit_note`
    # everywhere above here, because `cn` is a word in nobody's vocabulary.
    lib.gncEntryGetDocValue.restype            = GncNumericC
    lib.gncEntryGetDocValue.argtypes           = [ctypes.c_void_p,
                                                  ctypes.c_int, ctypes.c_int,
                                                  ctypes.c_int]
    lib.gncEntryGetDocTaxValue.restype         = GncNumericC
    lib.gncEntryGetDocTaxValue.argtypes        = [ctypes.c_void_p,
                                                  ctypes.c_int, ctypes.c_int,
                                                  ctypes.c_int]
    # A GList of `GncAccountValue*` — the tax each account receives, the
    # figures the posting splits carry. `(entry, is_cust_doc, is_credit_note)`.
    lib.gncEntryGetDocTaxValues.restype        = ctypes.c_void_p
    lib.gncEntryGetDocTaxValues.argtypes       = [ctypes.c_void_p,
                                                  ctypes.c_int, ctypes.c_int]
    # That list belongs to whoever asked for it — it is built fresh, not the
    # entry's own — and this is what frees it.
    lib.gncAccountValueDestroy.restype         = None
    lib.gncAccountValueDestroy.argtypes        = [ctypes.c_void_p]
    # And what the whole is worth, which is not the sum of its lines.
    # GnuCash rounds the tax once rather than line by line —
    # measured on 5.10, a bill of three 100.00 lines at 15% tax-included
    # posts 260.88 + 39.13 = 300.01, where the rounded per-line tax adds to
    # 39.12. These three answer what its posting splits carry, for a draft as
    # well as a posted one, since they read the entries either way.
    lib.gncInvoiceGetTotal.restype             = GncNumericC
    lib.gncInvoiceGetTotal.argtypes            = [ctypes.c_void_p]
    lib.gncInvoiceGetTotalSubtotal.restype     = GncNumericC
    lib.gncInvoiceGetTotalSubtotal.argtypes    = [ctypes.c_void_p]
    lib.gncInvoiceGetTotalTax.restype          = GncNumericC
    lib.gncInvoiceGetTotalTax.argtypes         = [ctypes.c_void_p]
    # ── Bill entry ───────────────────────────────────────────────────────────
    # `Billable?` and `Payment` are the two columns a bill window has and an
    # invoice window does not: a line marked billable is re-billed to a
    # customer, and the payment decides whether that shows as cash or card.
    lib.gncEntryGetBillable.restype            = ctypes.c_int
    lib.gncEntryGetBillable.argtypes           = [ctypes.c_void_p]
    lib.gncEntryGetBillPayment.restype         = ctypes.c_int
    lib.gncEntryGetBillPayment.argtypes        = [ctypes.c_void_p]
    # The owner a billable line is re-billed to. `gncEntrySetBillTo` copies
    # what it is handed — measured on 3.8 and 5.10, the billto still reads
    # back after the owner passed to it is freed — so the one `gncOwnerNew`
    # allocates is freed rather than parked for the entry's lifetime.
    lib.gncEntryGetBillTo.restype              = ctypes.c_void_p
    lib.gncEntryGetBillTo.argtypes             = [ctypes.c_void_p]
    lib.gncEntrySetBillTo.restype              = None
    lib.gncEntrySetBillTo.argtypes             = [ctypes.c_void_p,
                                                  ctypes.c_void_p]
    lib.gncOwnerNew.restype                    = ctypes.c_void_p
    lib.gncOwnerNew.argtypes                   = []
    lib.gncOwnerFree.restype                   = None
    lib.gncOwnerFree.argtypes                  = [ctypes.c_void_p]
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
    # sits in a lot of the owner's, a settlement in one an invoice owns, and
    # dividing a payment that covers more than that invoice owes moves one into
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
    # A split's other figure, and the setter for the one that changes with the
    # account. Undoing a link gives a split an account in another currency,
    # and what it takes there is its value — read off the split, not converted.
    lib.xaccSplitGetValue.restype              = GncNumericC
    lib.xaccSplitGetValue.argtypes             = [ctypes.c_void_p]
    lib.xaccSplitSetAmount.restype             = None
    lib.xaccSplitSetAmount.argtypes            = [ctypes.c_void_p, GncNumericC]
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
    # transaction's on a foreign invoice settled from a base-currency bank.
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
    # The date format every date on a printed page that is *not* the posted
    # or due date is written in. A process-wide setting: GnuCash's GUI
    # writes it at startup from its own preference, and nothing does in a
    # process that only loaded the library, so it sits at its compiled
    # default of `QOF_DATE_FORMAT_LOCALE` and the printing machine's locale
    # decides. See `services/gnucash_report.py`, which sets it from the book.
    lib.qof_date_format_set.restype            = None
    lib.qof_date_format_set.argtypes           = [ctypes.c_int]
    lib.qof_date_format_get.restype            = ctypes.c_int
    lib.qof_date_format_get.argtypes           = []
    # ── Whether a guid is free ───────────────────────────────────────────────
    # `gncEntryLookup`, `xaccSplitLookup` and their siblings are macros in
    # GnuCash's headers, so no library exports one and ctypes cannot call
    # them. What each expands to is this pair, taking the QOF type as a
    # string — so one declaration answers for every collection. Forcing a
    # guid GnuCash already gave to another object is how a book gets two
    # objects with one guid, and a collection is a hash of them: the loser
    # is unreachable.
    lib.qof_book_get_collection.restype        = ctypes.c_void_p
    lib.qof_book_get_collection.argtypes       = [ctypes.c_void_p,
                                                  ctypes.c_char_p]
    lib.qof_collection_lookup_entity.restype   = ctypes.c_void_p
    lib.qof_collection_lookup_entity.argtypes  = [ctypes.c_void_p,
                                                  ctypes.POINTER(GncGuidC)]
    # An account by guid, asked of every guid a file forces on an object it
    # creates — which since a line carries one is once per line of every
    # invoice restored, so opening the library for it each time was worth ending.
    lib.xaccAccountLookup.restype              = ctypes.c_void_p
    lib.xaccAccountLookup.argtypes             = [ctypes.POINTER(GncGuidC),
                                                  ctypes.c_void_p]
    # A line's bill-side owner pointer, which decides whether GnuCash writes
    # its bill-side tax flags at all (CLAUDE.md §8). SWIG's `Entry` has no
    # `SetBill`, measured on 5.10.
    lib.gncEntryGetBill.restype                = ctypes.c_void_p
    lib.gncEntryGetBill.argtypes               = [ctypes.c_void_p]
    lib.gncEntrySetBill.restype                = None
    lib.gncEntrySetBill.argtypes               = [ctypes.c_void_p,
                                                  ctypes.c_void_p]
    # And the invoice pointer, cleared when a bill's line is repaired: the
    # writer emits a reference per pointer and the reader adds the entry
    # once per reference, so a line holding both is listed twice.
    lib.gncEntrySetInvoice.restype             = None
    lib.gncEntrySetInvoice.argtypes            = [ctypes.c_void_p,
                                                  ctypes.c_void_p]
    # ── Naming a lot ─────────────────────────────────────────────────────────
    # A credit lot takes the guid its file names, so a split can say which of
    # an owner's credits it belongs to and a restored book holds the same
    # lots it came from. Bracketed like every other write: a forced guid
    # marks nothing dirty, so a session whose only change is one saves
    # nothing (tests/research/a_lot_can_be_named_probe.py).
    lib.qof_instance_set_guid.restype          = None
    lib.qof_instance_set_guid.argtypes         = [ctypes.c_void_p,
                                                  ctypes.POINTER(GncGuidC)]
    lib.gnc_lot_begin_edit.restype             = None
    lib.gnc_lot_begin_edit.argtypes            = [ctypes.c_void_p]
    lib.gnc_lot_commit_edit.restype            = None
    lib.gnc_lot_commit_edit.argtypes           = [ctypes.c_void_p]
    # A book option is written straight into the book's slots on GnuCash 3.4,
    # whose `qof_book_set_string_option` cannot reach a nested path. Marking
    # the instance dirty is not enough to get that to disk — the session has
    # to be told too, or the save writes nothing and the value is gone on the
    # next open (CLAUDE.md finding 18, on a book rather than a lot).
    lib.qof_book_mark_session_dirty.restype    = None
    lib.qof_book_mark_session_dirty.argtypes   = [ctypes.c_void_p]


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
