#!/usr/bin/env python
"""
Use case for exporting GnuCash business objects to plaintext format.

All tax-table and invoice-entry reading uses ctypes directly because the
GnuCash Python SWIG bindings have const-type mismatches for these calls
(confirmed on GnuCash 4.4 – 5.10 across Debian 11/12/13, Ubuntu 20/22).
See infrastructure/gnucash/engine.py for the platform notes.
"""

import json
from fractions import Fraction

import gnucash.gnucash_business as gb
from gnucash import Book, Query

from infrastructure.gnucash.engine import iterate_glist, load_gnc_engine, safe_ctypes_string
from infrastructure.gnucash.kvp import (
    COMPANY_CUSTOM_SECTION,
    COMPANY_CUSTOM_SLOT,
    KNOWN_BILL_METADATA_KEYS,
    KNOWN_CUSTOMER_METADATA_KEYS,
    KNOWN_INVOICE_METADATA_KEYS,
    KNOWN_VENDOR_METADATA_KEYS,
    get_book_string_option,
    get_custom_metadata,
)
from infrastructure.gnucash.utils import (
    encode_value_as_string,
    exact_text,
    get_account_full_name,
    numeric_to_fraction,
    wrap_invoice_or_bill,
)
from services.gnucash_importer import COMPANY_FIELD_TO_SLOT
from services.invoice_renderer import credit_note_lines
from services.payment_links import kind_of, the_payment_account_on
from services.plaintext_addresses import (
    address_key,
    address_line_index,
    address_lines_beyond,
    is_address_key,
)
from services.plaintext_blocks import (
    bill_entry_flags,
    entry_discount,
    entry_notes,
    owner_block_lines,
    payment_amount_text,
    payment_memo_of,
    payment_residue,
    payment_residue_text,
    record_text_lines,
    settlements_by_transaction,
    split_was_applied_from_credit,
)
from use_cases.export_transactions import (
    UnwritableFigureError,
)


def _fmt_rate(rate: Fraction) -> str:
    """Format a tax rate: always show at least one decimal (e.g. 5.0%, 9.975%).

    Exact — the rate is written as the figure GnuCash stores, not as the
    shortest float that prints close to it.
    """
    s = exact_text(rate)
    if '.' not in s:
        s += '.0'
    return s + '%'


def _fmt_quantity(val: Fraction) -> str:
    """Format quantity/price: strip trailing zeros and unnecessary decimal point."""
    return exact_text(val)


def _payment_amount_text(split, where='', also_settling=()) -> str:
    """A payment's amount, at the unit its own account is kept to.

    An amount is held to its account's smallest unit, not its currency's: a
    receivable kept to a tenth of a cent holds 50.005, and `commodity_scu:`
    round-trips that. Written at the currency's two places, a block states a
    figure the split does not hold — and the importer compares the two
    exactly, so the book could not read back its own export.

    The same function the printed block uses. Two implementations of it
    disagreed: this one refused a figure the currency cannot hold while the
    renderers rounded it, so one book answered two ways depending on which
    command was asked.
    """
    return payment_amount_text(split, where, also_settling)


def _split_was_applied_from_credit(split) -> bool:
    """Q-015: True iff this split settled its invoice or bill out of the owner's
    credit rather than being paid to it.

    The split says so itself, because the import that applied the credit
    wrote it there. Nothing else in the book can answer it: once applied, a
    consumed credit's split sits in the record's lot exactly as a bank
    payment's split does, GnuCash keeps no record of the lot it came from,
    and on the day a deposit is taken and an invoice posted against it even
    the dates are the same.

    Two things were tried before this and both misread ordinary books. Asking
    the *transaction* whether it still touches a leftover credit lot gives one
    answer for every invoice and bill that transaction settles — so the invoice
    a bank transfer paid claimed a credit had paid it — and says no for a credit
    consumed to the last cent, which leaves no residual behind. Asking whether
    the transaction predates the posting is right for every case
    but the same-day one, where a genuine payment cannot be told from an
    application by any figure in the book.

    Lives in `services.plaintext_blocks` now, with the block writers whose
    choice it is: the renderers need the same answer, and asked only here they
    printed a credit-settled invoice as paid from the bank the credit had
    arrived through.
    """
    return split_was_applied_from_credit(split)


class ExportBusinessObjectsUseCase:
    def __init__(self, book: Book):
        self.book = book
        self._lib = load_gnc_engine()
        # Whose figures are being written, for a refusal to name.
        # Without it the message had only the account, and a book with many
        # payments gave the reader nothing to find the offender by.
        self._being_written = ''
        # Every invoice and bill the format cannot write, not just the first. The
        # transaction export and the beancount export both gather them and
        # refuse once, on the reasoning that a book of thousands should not be
        # fixed one run at a time; this raised on the first, so a book with
        # several unwritable payment amounts took one run per payment — and
        # since the business objects are written before the transactions
        # section, its offenders were never reached at all.
        self._refusals: list = []

    def _guid_for_ptr_factory(self):
        """Return a function (qof_ptr -> 32-char hex guid) for use with ctypes pointers.

        Used for Invoices/Bills (SWIG `Invoice` does not expose GetGUID on
        all platforms) and tax tables (only available via ctypes).
        """
        import ctypes
        lib = self._lib
        lib.qof_instance_get_guid.argtypes = [ctypes.c_void_p]
        lib.qof_instance_get_guid.restype = ctypes.c_void_p
        lib.guid_to_string_buff.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        lib.guid_to_string_buff.restype = ctypes.c_char_p

        def guid_for_ptr(qof_ptr):
            buf = ctypes.create_string_buffer(40)
            guid_ptr = lib.qof_instance_get_guid(qof_ptr)
            if not guid_ptr:
                return ''
            lib.guid_to_string_buff(guid_ptr, buf)
            return buf.value.decode('ascii')

        return guid_for_ptr

    def _account_full_name(self, acct_ptr: int) -> str:
        """
        Build colon-separated account full name via ctypes (avoids SWIG const-type bug).
        Walks the parent chain until the root (parent with no parent).

        MUST use ctypes because:
        1. acct_ptr comes from gncTaxTableEntryGetAccount (ctypes function)
        2. SWIG Account() constructor doesn't accept raw pointers safely
        3. SWIG's account name getters have const-type bugs on Ubuntu
        """
        lib = self._lib
        parts = []
        ptr = acct_ptr
        while ptr:
            name = safe_ctypes_string(lib.xaccAccountGetName, ptr)
            if name:
                parts.append(name)
            parent = lib.gnc_account_get_parent(ptr)
            if not parent:
                break
            # Stop before root account (root's parent is None)
            grandparent = lib.gnc_account_get_parent(parent)
            if not grandparent:
                break
            ptr = parent
        parts.reverse()
        return ':'.join(parts)

    def execute(self) -> str:
        """Return the complete business-objects plaintext block.

        Refuses once, naming every invoice and bill the format cannot write, rather
        than on the first — the rule the transaction and beancount exports
        already keep, and for the reason they give: a book of thousands should
        not be fixed one run at a time. Invoices and bills are gathered
        together, so a book with an offender on each side reports both.
        """
        self._refusals = []
        parts = []
        company   = self._export_company()
        customers = self._export_customers()
        vendors   = self._export_vendors()
        tables    = self._export_tax_tables()
        invoices  = self._export_invoices()
        bills     = self._export_bills()
        if self._refusals:
            raise UnwritableFigureError(
                f'{len(self._refusals)} business object(s) hold figures this '
                f'format cannot write, and nothing was exported:\n  - '
                + '\n  - '.join(self._refusals))
        for section in (company, customers, vendors, tables, invoices, bills):
            if section:
                parts.append(section)
        return '\n\n'.join(parts)

    # ── Company ───────────────────────────────────────────────────────────────

    def _export_company(self) -> str:
        """Q-028: emit the book-level `company` directive from the Business
        options — GnuCash's own Company Name/Contact/Phone/Fax/Email/URL/ID
        plus the custom GST/PST registration numbers. Returns '' when the
        book has no company option set, so books without company info export
        unchanged. Address is split back from the single multi-line `Company
        Address` slot into one indexed key per line, the inverse of the
        importer's join."""
        ordered = [
            ('name',    'Company Name'),
            ('contact', 'Company Contact Person'),
            ('id',      'Company ID'),
            ('gst',     'Company GST Number'),
            ('pst',     'Company PST Number'),
        ]
        trailing = [
            ('phone', 'Company Phone Number'),
            ('fax',   'Company Fax Number'),
            ('email', 'Company Email Address'),
            ('url',   'Company Website URL'),
            # Nested under `Fancy Date Format` — see `COMPANY_FIELD_TO_SLOT`.
            # Emitted because it is the book's, and a book that says how its
            # dates are written must still say so after a round trip; left
            # out, an export and re-import handed the rebuilt book back to
            # whatever the printing machine's date preference happened to be.
            ('date_format', 'Fancy Date Format/custom'),
        ]

        # The slot is read first, because it is what an older book has. A key
        # that has since become a field of its own may be in either place: on
        # the option, where this version writes it, or in the custom blob,
        # where a book written before it was a field still keeps it. This is
        # the book-level `held_value` — field wins, slot is the fallback —
        # and without the fallback an export of such a book emitted no line
        # at all, having filtered the only copy the book had out of the
        # custom keys below.
        held = {}
        blob = get_book_string_option(self.book, COMPANY_CUSTOM_SECTION,
                                      COMPANY_CUSTOM_SLOT)
        if blob:
            try:
                held = json.loads(blob) or {}
            except (ValueError, TypeError):
                held = {}

        def opt(slot, key):
            value = (get_book_string_option(self.book, 'Business', slot)
                     or '').strip()
            if value:
                return value
            carried = held.get(key)
            return '' if carried is None else str(carried).strip()

        lines = ['company']
        has_value = False
        for key, slot in ordered:
            val = opt(slot, key)
            if val:
                lines.append(f'\t{key}: {encode_value_as_string(val)}')
                has_value = True

        # Every line the address has, not the first four of them. The option
        # is one free multi-line string and File → Properties → Business takes
        # as many lines as are typed into it, so reading four back was a
        # silent truncation — and the export is the whole ledger, so what it
        # leaves out is gone from any book rebuilt from it.
        addr_raw = get_book_string_option(self.book, 'Business',
                                          'Company Address') or ''
        addr_lines = [line.strip() for line in addr_raw.split('\n')] \
            if addr_raw else []

        # And the lines the blob holds past the end of it. A book written
        # before the company block had address lines keeps them there; a book
        # that then had an address typed into File → Properties → Business
        # holds *both*, and these keys are skipped in the custom dump below,
        # so whatever this does not read appears in no export and in no book
        # rebuilt from one.
        #
        # Past the end only, never inside. A line the option lacks within its
        # own length was cleared — by a block naming it empty or in GnuCash —
        # and putting one of those back from the blob is the export
        # contradicting the book it was taken from. Read as all-or-nothing
        # this was worse in the other direction: the blob was consulted only
        # for a book with no address at all, so a four-line blob behind a
        # two-line option lost lines three and four outright.
        carried = {address_line_index(k): str(v).strip()
                   for k, v in held.items()
                   if is_address_key(k) and v is not None and str(v).strip()}
        addr_lines = address_lines_beyond(addr_lines, carried)

        # However many lines that is. Nothing here caps it: GnuCash's own box
        # takes as many as are typed into it, and a book it holds happily is a
        # book this has to be able to state. Refusing an export over an
        # address length would leave such a book with no way out of GnuCash
        # and into this format at all — and unlike a sub-cent amount, which
        # genuinely cannot be written, an address of any length is only more
        # keys.

        for index, val in enumerate(addr_lines):
            if val:
                key = address_key(index)
                lines.append(f'\t{key}: {encode_value_as_string(val)}')
                has_value = True

        for key, slot in trailing:
            val = opt(slot, key)
            if val:
                lines.append(f'\t{key}: {encode_value_as_string(val)}')
                has_value = True

        # Q-029: custom (non-Business) keys stored as one JSON blob — emit each
        # back as its own `key: value` line (sorted for a stable round-trip).
        custom = held
        if custom:
            # A key that has since become a field of its own is skipped here,
            # because the loops above have already emitted it — from the
            # option where this version keeps it, or from this blob where an
            # older book still does. Written from both, the line appeared
            # twice and the stale copy came second, which is the one a
            # re-import keeps, so a book would have been dragged back to the
            # old value on every round trip. Skipping it here without the
            # fallback above is the other half of the same mistake: the line
            # then disappeared from a book whose only copy was here.
            # `date_format` is the case that exists — it was any old key
            # before it was a Business option. (CLAUDE.md finding 11.)
            for key in sorted(custom):
                if key in COMPANY_FIELD_TO_SLOT or is_address_key(key):
                    continue
                lines.append(f'\t{key}: {encode_value_as_string(custom[key])}')
                has_value = True

        return '\n'.join(lines) if has_value else ''

    # ── Customers ────────────────────────────────────────────────────────────

    def _export_customers(self) -> str:
        q = Query()
        q.search_for('gncCustomer')
        q.set_book(self.book)
        customers = sorted([gb.Customer(instance=r) for r in q.run()], key=lambda c: c.GetID())
        q.destroy()

        lines_list = []
        for cust in customers:
            lines_list.append('\n'.join(owner_block_lines(
                'customer', cust, KNOWN_CUSTOMER_METADATA_KEYS,
                with_guid=True, with_custom_keys=True)))
        return '\n\n'.join(lines_list)

    # ── Vendors ──────────────────────────────────────────────────────────────

    def _export_vendors(self) -> str:
        q = Query()
        q.search_for('gncVendor')
        q.set_book(self.book)
        vendors = sorted([gb.Vendor(instance=r) for r in q.run()], key=lambda v: v.GetID())
        q.destroy()

        lines_list = []
        for v in vendors:
            lines_list.append('\n'.join(owner_block_lines(
                'vendor', v, KNOWN_VENDOR_METADATA_KEYS,
                with_guid=True, with_custom_keys=True)))
        return '\n\n'.join(lines_list)

    # ── Tax tables ───────────────────────────────────────────────────────────

    def _export_tax_tables(self) -> str:
        """
        List all tax tables via ctypes gncTaxTableGetTables (GList* of GncTaxTable*).
        book.get_taxtables() does not exist in the Python bindings.
        """
        lib = self._lib

        # gncTaxTableGetTables returns a GList* of GncTaxTable* pointers
        glist_ptr = lib.gncTaxTableGetTables(int(self.book.instance))

        guid_for_ptr = self._guid_for_ptr_factory()

        def process_tax_table(lib, tt_ptr):
            """Process single tax table pointer to plaintext lines."""
            tt_name = safe_ctypes_string(lib.gncTaxTableGetName, tt_ptr)
            lines = [
                f'taxtable "{tt_name}"',
                f'\tguid: "{guid_for_ptr(tt_ptr)}"',
            ]

            # Process entries using iterate_glist
            entries_ptr = lib.gncTaxTableGetEntries(tt_ptr)

            def process_tax_table_entry(lib, tte_ptr):
                """Process single tax table entry pointer."""
                acct_ptr = lib.gncTaxTableEntryGetAccount(tte_ptr)
                amt_c = lib.gncTaxTableEntryGetAmount(tte_ptr)
                rate = numeric_to_fraction(amt_c) if amt_c.denom else Fraction(0)
                acct_name = self._account_full_name(acct_ptr) if acct_ptr else '?'
                return (acct_name, rate)

            entry_parts = iterate_glist(lib, entries_ptr, process_tax_table_entry)
            entry_parts.reverse()  # GnuCash prepends → put GST before PST/QST

            for acct_name, rate in entry_parts:
                lines.append('	entry:')
                lines.append(f'		account: {encode_value_as_string(acct_name)}')
                lines.append(f'		rate: {_fmt_rate(rate)}')
                lines.append('		type: PERCENT')

            return '\n'.join(lines)

        tables = iterate_glist(lib, glist_ptr, process_tax_table)
        return '\n\n'.join(tables)

    def _refusal_naming_its_source(self, exc) -> str:
        """The refusal, with the invoice or bill it came out of named once.

        An export writes a whole book, so a sentence about "this line" or
        "this amount" leaves a reader nothing to find. Some refusals are
        built with that name in them already — the payment ones take
        `_being_written` as an argument — so it is added only where
        it is missing, rather than naming the same one twice.
        """
        said = str(exc)
        if (self._being_written
                and self._being_written not in said):
            return f'{self._being_written}: {said}'
        return said

    # ── Invoices ─────────────────────────────────────────────────────────────

    def _export_invoices(self) -> str:
        lib = self._lib
        guid_for_ptr = self._guid_for_ptr_factory()

        q = Query()
        q.search_for('gncInvoice')
        q.set_book(self.book)
        all_invoices = [wrap_invoice_or_bill(r) for r in q.run()]
        q.destroy()

        # Export all customer invoices (owner is Customer, not Vendor), including unposted
        invoices = []
        for inv in all_invoices:
            # No `except` around it, like its bill-side twin: `GetCustomer()`
            # answers None for a vendor bill rather than raising, on all ten
            # supported builds — measured. The guard that used to be here held
            # the `append` inside the `try`, so had it ever fired it would
            # have dropped a customer invoice from the exported ledger without
            # a word, which is worse than the failure it was there for.
            cust = inv.GetOwner().GetCustomer()
            if cust is not None:
                invoices.append((inv, cust))

        invoice_strings = []
        for inv, cust in invoices:
            # Which invoice the figures below belong to, for the refusal to
            # name. The message otherwise had only the account, and a book
            # with many payments gave the reader nothing to find it by.
            self._being_written = f'invoice "{inv.GetID()}"'
            try:
                invoice_strings.append('\n'.join(
                    self._invoice_lines(inv, cust, guid_for_ptr, lib)))
            except UnwritableFigureError as exc:
                # Collected, and this invoice written nowhere: a partial
                # block would re-import as an edit that silently drops
                # whatever could not be written.
                self._refusals.append(self._refusal_naming_its_source(exc))
        return '\n\n'.join(invoice_strings)

    def _invoice_lines(self, inv, cust, guid_for_ptr, lib) -> list:
        """One invoice block, or `UnwritableFigureError` if the format cannot
        state one of its figures."""
        lines = [
            f'invoice "{inv.GetID()}"',
            f'\tguid: "{guid_for_ptr(int(inv.instance))}"',
            f'	customer_id: {encode_value_as_string(cust.GetID())}',
            f'\tcustomer_guid: "{cust.GetGUID().to_string()}"',
            f'	currency: {inv.GetCurrency().get_mnemonic()}',
            f'	date_opened: {inv.GetDateOpened().strftime("%Y-%m-%d")}',
        ]
        # Written before anything else about the invoice, because it is what
        # the rest of it means: the same quantities and the same accounts
        # post the other way round. Without it a credit note rebuilt in a
        # fresh book as an ordinary invoice, and the export is what a book is
        # reconstructed from.
        lines += credit_note_lines(inv)
        lines += record_text_lines(inv)

        custom_meta = {k: v for k, v
                       in (get_custom_metadata(inv) or {}).items()
                       if k not in KNOWN_INVOICE_METADATA_KEYS}
        for k, v in sorted(custom_meta.items()):
            lines.append(f'	{k}: {encode_value_as_string(v)}')

        for raw_entry in inv.GetEntries():
            lines += self._format_inv_entry(lib, raw_entry, guid_for_ptr)

        # posted block — always emitted; "none" sentinel when not posted
        posted_txn = inv.GetPostedTxn()
        if posted_txn:
            ar_name = get_account_full_name(inv.GetPostedAcc())
            lines.append('	posted:')
            lines.append(f'		date: {inv.GetDatePosted().strftime("%Y-%m-%d")}')
            lines.append(f'		due: {inv.GetDateDue().strftime("%Y-%m-%d")}')
            lines.append(f'		ar_account: {encode_value_as_string(ar_name)}')
            lines.append(
                f'		memo: {encode_value_as_string(posted_txn.GetDescription())}')
            # Always emit posted_txn_guid (symmetric with Q-016's
            # always-emit payment txn_guid). On re-import, the importer
            # links this existing tx instead of calling PostToAccount,
            # which would otherwise mint a duplicate alongside the
            # standalone-imported one and orphan the original.
            lines.append(f'		posted_txn_guid: "{posted_txn.GetGUID().to_string()}"')
            lines.append('		accumulate: #True')
        else:
            lines.append('	posted: none')

        # payment blocks — always emitted; "none" sentinel when no payments exist.
        # Q-015: a payment tx that also has a split in a prepay lot settled
        # this invoice out of the owner's credit. That is a payment like any
        # other and says so, with `from_credit: true` in place of the bank
        # account no money came from.
        lot = inv.GetPostedLot()
        has_payments = False
        if lot:
            for txn, sharing in settlements_by_transaction(lot):
                s = sharing[0]
                if _split_was_applied_from_credit(s):
                    lines += self._format_credit_payment(txn, s, sharing[1:])
                else:
                    lines += self._format_payment(
                        txn, s, kind_of(inv), sharing[1:])
                has_payments = True
        if not has_payments:
            lines.append('	payment: none')

        return lines

    def _format_inv_entry(self, lib, raw_entry, guid_for_ptr) -> list:
        ptr = int(raw_entry.instance)

        desc   = safe_ctypes_string(lib.gncEntryGetDescription, ptr)
        action = safe_ctypes_string(lib.gncEntryGetAction, ptr)
        qty_c  = lib.gncEntryGetQuantity(ptr)
        pri_c  = lib.gncEntryGetInvPrice(ptr)
        qty    = numeric_to_fraction(qty_c) if qty_c.denom else Fraction(0)
        price  = numeric_to_fraction(pri_c) if pri_c.denom else Fraction(0)

        taxable     = bool(lib.gncEntryGetInvTaxable(ptr))
        tax_incl    = bool(lib.gncEntryGetInvTaxIncluded(ptr))

        # Account full name via Python wrapper (works fine here)
        acct_name = get_account_full_name(raw_entry.GetInvAccount())

        date_str = raw_entry.GetDate().strftime("%Y-%m-%d")

        lines = [
            '	entry:',
            # Which line this is, so a re-import updates it rather than
            # destroying every line and building new ones.
            # Written first, as an invoice block writes its own guid.
            f'		guid: "{guid_for_ptr(ptr)}"',
            f'		date: {date_str}',
            f'		description: {encode_value_as_string(desc)}',
            f'		action: {encode_value_as_string(action)}',
            f'		account: {encode_value_as_string(acct_name)}',
            f'		quantity: {_fmt_quantity(qty)}',
            f'		price: {_fmt_quantity(price)}',
            f'		taxable: {encode_value_as_string(taxable)}',
            f'		tax_included: {encode_value_as_string(tax_incl)}',
        ]

        # Tax table — ctypes required (SWIG const-type bug)
        tt_ptr = lib.gncEntryGetInvTaxTable(ptr)
        if tt_ptr:
            tt_name = safe_ctypes_string(lib.gncTaxTableGetName, tt_ptr)
            if tt_name:
                lines.append(
                    f'		tax_table: {encode_value_as_string(tt_name)}')

        lines.extend(entry_notes(lib, ptr))
        lines.extend(entry_discount(lib, raw_entry, ptr))

        return lines

    def _format_bill_entry(self, lib, raw_entry, guid_for_ptr) -> list:
        """Format one bill (vendor invoice) entry as plaintext lines.

        `action:` is written here as it is for an invoice. A `GncEntry` has
        one action field, which GnuCash's bill window shows in its Action
        column like the invoice window does — measured on 5.10: an entry
        given `Material`, saved and reopened, reads back `Material`. This
        used to be left out on the belief that the field was invoice-side
        only, so a bill's Action was dropped by every export and lost on the
        re-import that followed.
        """
        ptr = int(raw_entry.instance)

        desc  = safe_ctypes_string(lib.gncEntryGetDescription, ptr)
        qty_c = lib.gncEntryGetQuantity(ptr)
        pri_c = lib.gncEntryGetBillPrice(ptr)
        qty   = numeric_to_fraction(qty_c) if qty_c.denom else Fraction(0)
        price = numeric_to_fraction(pri_c) if pri_c.denom else Fraction(0)

        taxable  = bool(lib.gncEntryGetBillTaxable(ptr))
        tax_incl = bool(lib.gncEntryGetBillTaxIncluded(ptr))

        acct_name = get_account_full_name(raw_entry.GetBillAccount())
        date_str  = raw_entry.GetDate().strftime("%Y-%m-%d")

        lines = [
            '	entry:',
            f'		guid: "{guid_for_ptr(ptr)}"',   # as an invoice line writes it
            f'		date: {date_str}',
            f'		description: {encode_value_as_string(desc)}',
        ]

        # Written whichever it is, as an invoice line writes it: one
        # `GncEntry` field, one export, and a reader should not have to know
        # that an absent line means an empty action.
        action = safe_ctypes_string(lib.gncEntryGetAction, ptr) or ''

        lines.extend([
            f'		action: {encode_value_as_string(action)}',
            f'		account: {encode_value_as_string(acct_name)}',
            f'		quantity: {_fmt_quantity(qty)}',
            f'		price: {_fmt_quantity(price)}',
            f'		taxable: {encode_value_as_string(taxable)}',
            f'		tax_included: {encode_value_as_string(tax_incl)}',
        ])

        tt_ptr = lib.gncEntryGetBillTaxTable(ptr)
        if tt_ptr:
            tt_name = safe_ctypes_string(lib.gncTaxTableGetName, tt_ptr)
            if tt_name:
                lines.append(
                    f'		tax_table: {encode_value_as_string(tt_name)}')

        lines.extend(entry_notes(lib, ptr))
        lines.extend(bill_entry_flags(lib, ptr))

        return lines

    def _format_credit_payment(self, txn, in_lot_ar_ap_split,
                               also_settling=()) -> list:
        """Format the slice of an owner's credit that settled this invoice or bill.

        A credit is applied by moving currency the book already has: GnuCash
        writes no transaction for it, reduces the split the credit sits on to
        the part being spent, and carves the rest into a new split of the same
        transaction. There is no bank account, because no bank moved anything,
        and no date for the application, because the book records none — what
        it holds is the transaction the credit arrived in, which is what
        `credit_dated:` names.

        The block records the outcome rather than the request. Re-importing it
        attaches this exact split to that record's lot, where re-running the
        `auto_apply_credit:` that produced it would apply whatever credit the
        book has at the time, which is not necessarily this one.

        **One split to a block**, so companions are refused rather than
        dropped. There is no grouped spelling of a credit block —
        `Transaction` / `PaymentSplit` is read by `_apply_payment_directive`
        and a `from_credit:` block goes elsewhere — and
        `settlements_by_transaction` keys each credit settlement by its own
        split so this cannot arise. Dropped in silence, as taking no such
        parameter amounted to, a second credit settlement on one transaction
        went missing from the ledger and the record read as changed by its own
        export.
        """
        if also_settling:
            raise ValueError(
                'a credit settlement is written one split to a block, so it '
                f'takes no companions; {len(also_settling)} were passed. '
                'Group credit splits by their own guid — see '
                'settlements_by_transaction.')
        amount = _payment_amount_text(in_lot_ar_ap_split,
                                      self._being_written)
        return [
            '	payment:',
            f'		amount: {amount}',
            '		from_credit: #True',
            f'		credit_dated: {txn.GetDate().strftime("%Y-%m-%d")}',
            f'		memo: '
            f'{encode_value_as_string(in_lot_ar_ap_split.GetMemo() or "")}',
            f'		txn_guid: "{txn.GetGUID().to_string()}"',
            f'		txn_split_guid: "{in_lot_ar_ap_split.GetGUID().to_string()}"',
        ]

    def _format_payment(self, txn, in_lot_ar_ap_split, kind,
                        also_settling=()) -> list:
        """Format one payment transaction as `payment:` lines.

        `in_lot_ar_ap_split` is the AR/AP-side split that lives in the
        invoice/bill's posted lot (the loop driving the export is already
        walking that lot's splits). Used to compute the `prepayment:`
        residual when GnuCash split the payment across multiple lots
        (overpayment).

        `kind` is `'invoice'` or `'bill'`, from the record's owner. Which
        accounts a payment may sit on differs between the two, and the block
        has to state one this book will take back.
        """
        pay_date = txn.GetDate().strftime("%Y-%m-%d")
        pay_num  = txn.GetNum() or ''

        # Where the money came from. `the_payment_account_on` holds the rule,
        # and the printed invoice and bill ask it too — all three wrote this
        # loop out and all three took the first split that was not on the
        # receivable, which is the money only while the transaction carries
        # nothing else. The memo is separate: `ApplyPayment` stores it on the
        # splits rather than on the transaction description, which it sets to
        # the owner's name.
        bank_name = the_payment_account_on(txn, kind, in_lot_ar_ap_split)
        # The memo off the split the import writes it to, which is not the
        # bank side where one payment settles several invoices: they share
        # that split and each block says what its own portion was for.
        pay_memo = payment_memo_of(txn, in_lot_ar_ap_split)

        # This record's payment amount is its OWN allocation — the AR/AP split
        # in this invoice/bill's lot (`in_lot_ar_ap_split`) — NOT the bank-side
        # total. They differ when one bank tx is split across several
        # invoices/bills: each lot holds its portion, the bank split holds the
        # sum. Emitting the bank total would over-report every record (a $400
        # wire across 3 invoices would otherwise export amount: 400 on each).
        # Format at the AR/AP account's own smallest unit, exactly (no float).
        in_lot_ar_ap_split.GetAccount().GetCommodity()
        pay_amt_str = _payment_amount_text(in_lot_ar_ap_split,
                                           self._being_written,
                                           also_settling)

        # Q-015 / Q-016: prepayment residual — what this payment left over
        # when it was made. Worked out by `payment_residue`, which the printed
        # block writer reads too: computed here alone, a printed overpayment
        # stated its own slice and nothing about the residue, so read into a
        # book that never held the deposit it entered a 100.00 bank movement
        # for money that moved 250.00.
        # Weighed against the splits this block does not name, so a payment
        # made of several does not count its own other halves as residue.
        prepay = payment_residue(txn, in_lot_ar_ap_split, also_settling)

        # Q-016: always emit `txn_guid:` so re-import resolves the payment
        # via the standalone-tx pass rather than via ApplyPayment (which
        # would create a duplicate bank transaction).
        txn_guid = txn.GetGUID().to_string()

        # Q-016: emit `txn_split_guid:` identifying the specific
        # AR/AP-side split that belongs to this invoice/bill on the
        # bank tx named by `txn_guid:` above. For a single-invoice
        # payment this is unambiguous; for a shared bank tx covering
        # multiple invoices, the importer needs this to know which
        # split to attach to this invoice's posted lot. The `txn_`
        # prefix mirrors `txn_guid:` — both point at the bank tx that
        # the payment block is linking to.
        txn_split_guid = in_lot_ar_ap_split.GetGUID().to_string()

        lines = [
            '	payment:',
            f'		date: {pay_date}',
            f'		amount: {pay_amt_str}',
            f'		bank_account: {encode_value_as_string(bank_name)}',
        ]
        if also_settling:
            # More than one split of this transaction settles this record, and
            # it is still one payment. `txn_split_guid:` names one split and
            # there is no second of it, so the settlement is written as the
            # transaction it is, with its splits as children — which is where
            # a split lives everywhere else in this format.
            lines.append(f'		Transaction "{txn_guid}"')
            for split in (in_lot_ar_ap_split, *also_settling):
                lines.append(
                    f'			PaymentSplit "{split.GetGUID().to_string()}"')
        else:
            lines += [
                f'		txn_guid: "{txn_guid}"',
                f'		txn_split_guid: "{txn_split_guid}"',
            ]
        lines.append(f'		memo: {encode_value_as_string(pay_memo)}')
        if pay_num:
            lines.append(f'		num: {encode_value_as_string(pay_num)}')
        if prepay > 0:
            lines.append(
                f'		prepayment: '
                f'{payment_residue_text(prepay, in_lot_ar_ap_split, self._being_written)}')
        return lines

    # ── Bills (vendor invoices) ───────────────────────────────────────────────

    def _export_bills(self) -> str:
        """
        Bills are gncInvoice objects whose owner is a Vendor.
        There is no separate 'gncBill' QOF type.
        """
        lib = self._lib

        q = Query()
        q.search_for('gncInvoice')
        q.set_book(self.book)
        all_invoices = [wrap_invoice_or_bill(r) for r in q.run()]
        q.destroy()

        # Export all vendor bills, including unposted. Asked of every one
        # in the book, customer invoices included: `GetVendor()` answers None
        # for one rather than raising, on all ten supported builds — measured,
        # and the same reason the two print commands carry no guard here.
        #
        # The `except Exception` that used to wrap this held the append inside
        # it, so had it ever fired it would have dropped a vendor bill from
        # the exported ledger without a word — a worse failure than the one it
        # was there for, on a path nothing could reach.
        bills = []
        for inv in all_invoices:
            vendor = inv.GetOwner().GetVendor()
            if vendor is not None:
                bills.append((inv, vendor))

        guid_for_ptr = self._guid_for_ptr_factory()
        bill_strings = []
        for inv, vendor in bills:
            self._being_written = f'bill "{inv.GetID()}"'
            try:
                bill_strings.append('\n'.join(
                    self._bill_lines(inv, vendor, guid_for_ptr, lib)))
            except UnwritableFigureError as exc:
                # As the invoice side collects them, and for the same reason.
                self._refusals.append(self._refusal_naming_its_source(exc))
        return '\n\n'.join(bill_strings)

    def _bill_lines(self, inv, vendor, guid_for_ptr, lib) -> list:
        """One bill block, or `UnwritableFigureError` if the format cannot
        state one of its figures."""
        lines = [
            f'bill "{inv.GetID()}"',
            f'\tguid: "{guid_for_ptr(int(inv.instance))}"',
            f'	vendor_id: {encode_value_as_string(vendor.GetID())}',
            f'\tvendor_guid: "{vendor.GetGUID().to_string()}"',
            f'	currency: {inv.GetCurrency().get_mnemonic()}',
            f'	date_opened: {inv.GetDateOpened().strftime("%Y-%m-%d")}',
            *credit_note_lines(inv),   # as the invoice side writes it
        ]
        # As the invoice block writes them: a bill has both, the bill
        # comparison reads `GetNotes()`, and an export that did not carry
        # them could not be read back into the same bill.
        lines += record_text_lines(inv)

        # Filtered, as the owner blocks are: a key that has since become a
        # field of its own is still in the slot of a book written before.
        custom_meta = {k: v for k, v
                       in (get_custom_metadata(inv) or {}).items()
                       if k not in KNOWN_BILL_METADATA_KEYS}
        for k, v in sorted(custom_meta.items()):
            lines.append(f'	{k}: {encode_value_as_string(v)}')

        for raw_entry in inv.GetEntries():
            lines += self._format_bill_entry(lib, raw_entry, guid_for_ptr)

        # posted block — always emitted; "none" sentinel when not posted
        posted_txn = inv.GetPostedTxn()
        if posted_txn:
            ap_name = get_account_full_name(inv.GetPostedAcc())
            lines.append('	posted:')
            lines.append(f'		date: {inv.GetDatePosted().strftime("%Y-%m-%d")}')
            lines.append(f'		due: {inv.GetDateDue().strftime("%Y-%m-%d")}')
            lines.append(f'		ap_account: {encode_value_as_string(ap_name)}')
            lines.append(
                f'		memo: {encode_value_as_string(posted_txn.GetDescription())}')
            lines.append(f'		posted_txn_guid: "{posted_txn.GetGUID().to_string()}"')
            lines.append('		accumulate: #True')
        else:
            lines.append('	posted: none')

        # payment blocks — same Q-015 credit logic as the invoice side,
        # where the credit is money the book sent this vendor.
        lot = inv.GetPostedLot()
        has_payments = False
        if lot:
            for txn, sharing in settlements_by_transaction(lot):
                s = sharing[0]
                if _split_was_applied_from_credit(s):
                    lines += self._format_credit_payment(txn, s, sharing[1:])
                else:
                    lines += self._format_payment(
                        txn, s, kind_of(inv), sharing[1:])
                has_payments = True
        if not has_payments:
            lines.append('	payment: none')

        return lines
