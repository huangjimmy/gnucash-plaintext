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
import gnucash.gnucash_core_c as gc
from gnucash import Book, Query, Split

from infrastructure.gnucash.engine import iterate_glist, load_gnc_engine, safe_ctypes_string
from infrastructure.gnucash.kvp import (
    COMPANY_CUSTOM_SECTION,
    COMPANY_CUSTOM_SLOT,
    get_book_string_option,
    get_custom_metadata,
)
from infrastructure.gnucash.utils import (
    encode_value_as_string,
    exact_text,
    format_amount_for_commodity,
    get_account_full_name,
    money_text,
    numeric_to_fraction,
    wrap_invoice_or_bill,
)
from services.gnucash_importer import is_a_bank_paid_orphan


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


def _payment_amount_text(split) -> str:
    """A payment's amount, at the unit its own account is kept to.

    An amount is held to its account's smallest unit, not its currency's: a
    receivable kept to a tenth of a cent holds 50.005, and `commodity_scu:`
    round-trips that. Written at the currency's two places, a block states a
    figure the split does not hold — and the importer compares the two
    exactly, so the book could not read back its own export.
    """
    account = split.GetAccount()
    scu = account.GetCommoditySCU() if account is not None else None
    if not scu:
        return format_amount_for_commodity(
            split.GetAmount().abs(),
            account.GetCommodity() if account is not None else None)
    return money_text(abs(numeric_to_fraction(split.GetAmount())), scu)


def _split_was_applied_from_credit(split) -> bool:
    """Q-015: True iff this split settled its document out of the owner's
    credit rather than being paid to it.

    The split says so itself, because the import that applied the credit
    wrote it there. Nothing else in the book can answer it: once applied, a
    consumed credit's split sits in the document's lot exactly as a bank
    payment's split does, GnuCash keeps no record of the lot it came from,
    and on the day a deposit is taken and an invoice raised against it even
    the dates are the same.

    Two things were tried before this and both misread ordinary books. Asking
    the *transaction* whether it still touches a leftover credit lot gives one
    answer for every document that transaction settles — so the invoice a bank
    transfer paid claimed a credit had paid it — and says no for a credit
    consumed to the last cent, which leaves no residual behind. Asking whether
    the transaction predates the document's posting is right for every case
    but the same-day one, where a genuine payment cannot be told from an
    application by any figure in the book.

    A split with nothing written on it — a book from the GnuCash GUI, or one
    written before this — reads as a payment, which is what it was before this
    tool had anything to say about it.
    """
    return str(get_custom_metadata(split).get('applied_from_credit', '')
               ).strip().lower() == 'true'


class ExportBusinessObjectsUseCase:
    def __init__(self, book: Book):
        self.book = book
        self._lib = load_gnc_engine()

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
        """Return the complete business-objects plaintext block."""
        parts = []
        company   = self._export_company()
        customers = self._export_customers()
        vendors   = self._export_vendors()
        tables    = self._export_tax_tables()
        invoices  = self._export_invoices()
        bills     = self._export_bills()
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
        Address` slot into addr1..4, the inverse of the importer's join."""
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
        ]

        def opt(slot):
            return (get_book_string_option(self.book, 'Business', slot) or '').strip()

        lines = ['company']
        has_value = False
        for key, slot in ordered:
            val = opt(slot)
            if val:
                lines.append(f'\t{key}: {encode_value_as_string(val)}')
                has_value = True

        addr_raw = get_book_string_option(self.book, 'Business', 'Company Address') or ''
        addr_lines = addr_raw.split('\n') if addr_raw else []
        for i, key in enumerate(('addr1', 'addr2', 'addr3', 'addr4')):
            val = addr_lines[i].strip() if i < len(addr_lines) else ''
            if val:
                lines.append(f'\t{key}: {encode_value_as_string(val)}')
                has_value = True

        for key, slot in trailing:
            val = opt(slot)
            if val:
                lines.append(f'\t{key}: {encode_value_as_string(val)}')
                has_value = True

        # Q-029: custom (non-Business) keys stored as one JSON blob — emit each
        # back as its own `key: value` line (sorted for a stable round-trip).
        blob = get_book_string_option(self.book, COMPANY_CUSTOM_SECTION, COMPANY_CUSTOM_SLOT)
        if blob:
            try:
                custom = json.loads(blob)
            except (ValueError, TypeError):
                custom = {}
            for key in sorted(custom):
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
            addr  = cust.GetAddr()
            lines = [
                f'customer "{cust.GetID()}"',
                f'\tguid: "{cust.GetGUID().to_string()}"',
                f'\tname: "{cust.GetName()}"',
                f'\tcurrency: {cust.GetCurrency().get_mnemonic()}',
            ]
            if not cust.GetActive():
                lines.append('	active: false')
            # Only emit optional address/contact fields when non-empty
            for field, val in [
                ('addr1', addr.GetAddr1()),
                ('addr2', addr.GetAddr2()),
                ('addr3', addr.GetAddr3()),
                ('addr4', addr.GetAddr4()),
                ('email', addr.GetEmail()),
            ]:
                if val:
                    lines.append(f'	{field}: "{val}"')
            custom_meta = get_custom_metadata(cust)
            for k, v in sorted(custom_meta.items()):
                lines.append(f'	{k}: "{v}"')
            lines_list.append('\n'.join(lines))
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
            lines = [
                f'vendor "{v.GetID()}"',
                f'\tguid: "{v.GetGUID().to_string()}"',
                f'	name: "{v.GetName()}"',
                f'	currency: {v.GetCurrency().get_mnemonic()}',
            ]
            if not v.GetActive():
                lines.append('	active: false')
            custom_meta = get_custom_metadata(v)
            for k, v_val in sorted(custom_meta.items()):
                lines.append(f'	{k}: "{v_val}"')
            lines_list.append('\n'.join(lines))
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
                lines.append(f'		account: "{acct_name}"')
                lines.append(f'		rate: {_fmt_rate(rate)}')
                lines.append('		type: PERCENT')

            return '\n'.join(lines)

        tables = iterate_glist(lib, glist_ptr, process_tax_table)
        return '\n\n'.join(tables)

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
            try:
                cust = inv.GetOwner().GetCustomer()
                if cust is not None:
                    invoices.append((inv, cust))
            except Exception:
                pass

        invoice_strings = []
        for inv, cust in invoices:
            lines = [
                f'invoice "{inv.GetID()}"',
                f'\tguid: "{guid_for_ptr(int(inv.instance))}"',
                f'	customer_id: "{cust.GetID()}"',
                f'\tcustomer_guid: "{cust.GetGUID().to_string()}"',
                f'	currency: {inv.GetCurrency().get_mnemonic()}',
                f'	date_opened: {inv.GetDateOpened().strftime("%Y-%m-%d")}',
            ]
            if inv.GetBillingID():
                lines.append(f'	billing_id: "{inv.GetBillingID()}"')
            if inv.GetNotes():
                lines.append(f'	notes: "{inv.GetNotes()}"')

            custom_meta = get_custom_metadata(inv)
            for k, v in sorted(custom_meta.items()):
                lines.append(f'	{k}: "{v}"')

            for raw_entry in inv.GetEntries():
                lines += self._format_inv_entry(lib, raw_entry)

            # posted block — always emitted; "none" sentinel when not posted
            posted_txn = inv.GetPostedTxn()
            if posted_txn:
                ar_name = get_account_full_name(inv.GetPostedAcc())
                lines.append('	posted:')
                lines.append(f'		date: {inv.GetDatePosted().strftime("%Y-%m-%d")}')
                lines.append(f'		due: {inv.GetDateDue().strftime("%Y-%m-%d")}')
                lines.append(f'		ar_account: "{ar_name}"')
                lines.append(f'		memo: "{posted_txn.GetDescription()}"')
                # Always emit posted_txn_guid (symmetric with Q-016's
                # always-emit payment txn_guid). On re-import, the importer
                # links this existing tx instead of calling PostToAccount,
                # which would otherwise mint a duplicate alongside the
                # standalone-imported one and orphan the original.
                lines.append(f'		posted_txn_guid: "{posted_txn.GetGUID().to_string()}"')
                lines.append('		accumulate: true')
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
                for raw_split in lot.get_split_list():
                    s   = Split(instance=raw_split)
                    txn = s.GetParent()
                    if txn is None:
                        continue
                    # Skip the posting transaction itself
                    if gc.gncInvoiceGetInvoiceFromTxn(txn.instance) is not None:
                        continue
                    if _split_was_applied_from_credit(s):
                        lines += self._format_credit_payment(txn, s)
                    else:
                        lines += self._format_payment(txn, s)
                    has_payments = True
            if not has_payments:
                lines.append('	payment: none')

            invoice_strings.append('\n'.join(lines))
        return '\n\n'.join(invoice_strings)

    def _format_inv_entry(self, lib, raw_entry) -> list:
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
            f'		date: {date_str}',
            f'		description: "{desc}"',
            f'		action: "{action}"',
            f'		account: "{acct_name}"',
            f'		quantity: {_fmt_quantity(qty)}',
            f'		price: {_fmt_quantity(price)}',
            f'		taxable: {"true" if taxable else "false"}',
            f'		tax_included: {"true" if tax_incl else "false"}',
        ]

        # Tax table — ctypes required (SWIG const-type bug)
        tt_ptr = lib.gncEntryGetInvTaxTable(ptr)
        if tt_ptr:
            tt_name = safe_ctypes_string(lib.gncTaxTableGetName, tt_ptr)
            if tt_name:
                lines.append(f'		tax_table: "{tt_name}"')

        return lines

    def _format_bill_entry(self, lib, raw_entry) -> list:
        """Format one bill (vendor invoice) entry as plaintext lines.

        Note: the `action:` field is intentionally absent. GnuCash's Entry
        object stores action on the invoice side only (gncEntryGetAction is
        for customer invoices, not vendor bills). Bills do not expose or
        persist an action field through the GnuCash API.
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
            f'		date: {date_str}',
            f'		description: "{desc}"',
            f'		account: "{acct_name}"',
            f'		quantity: {_fmt_quantity(qty)}',
            f'		price: {_fmt_quantity(price)}',
            f'		taxable: {"true" if taxable else "false"}',
            f'		tax_included: {"true" if tax_incl else "false"}',
        ]

        tt_ptr = lib.gncEntryGetBillTaxTable(ptr)
        if tt_ptr:
            tt_name = safe_ctypes_string(lib.gncTaxTableGetName, tt_ptr)
            if tt_name:
                lines.append(f'		tax_table: "{tt_name}"')

        return lines

    def _format_credit_payment(self, txn, in_lot_ar_ap_split) -> list:
        """Format the slice of an owner's credit that settled this document.

        A credit is applied by moving currency the book already has: GnuCash
        writes no transaction for it, reduces the split the credit sits on to
        the part being spent, and carves the rest into a new split of the same
        transaction. There is no bank account, because no bank moved anything,
        and no date for the application, because the book records none — what
        it holds is the transaction the credit arrived in, which is what
        `credit_dated:` names.

        The block records the outcome rather than the request. Re-importing it
        attaches this exact split to this document's lot, where re-running the
        `auto_apply_credit:` that produced it would apply whatever credit the
        book has at the time, which is not necessarily this one.
        """
        amount = _payment_amount_text(in_lot_ar_ap_split)
        return [
            '	payment:',
            f'		amount: {amount}',
            '		from_credit: true',
            f'		credit_dated: {txn.GetDate().strftime("%Y-%m-%d")}',
            f'		memo: "{in_lot_ar_ap_split.GetMemo() or ""}"',
            f'		txn_guid: "{txn.GetGUID().to_string()}"',
            f'		txn_split_guid: "{in_lot_ar_ap_split.GetGUID().to_string()}"',
        ]

    def _format_payment(self, txn, in_lot_ar_ap_split) -> list:
        """Format one payment transaction as `payment:` lines.

        `in_lot_ar_ap_split` is the AR/AP-side split that lives in the
        invoice/bill's posted lot (the loop driving the export is already
        walking that lot's splits). Used to compute the `prepayment:`
        residual when GnuCash split the payment across multiple lots
        (overpayment).
        """
        pay_date = txn.GetDate().strftime("%Y-%m-%d")
        pay_num  = txn.GetNum() or ''

        # Find the bank/asset side (non-AR/AP) split for amount, account,
        # and memo. ApplyPayment stores the memo on the splits (not on
        # the transaction description, which is set to the owner name).
        bank_name = ''
        pay_memo  = ''
        for i in range(txn.CountSplits()):
            split = txn.GetSplit(i)
            acct  = split.GetAccount()
            atype = gc.xaccAccountGetType(acct.instance)
            if atype not in (gc.ACCT_TYPE_RECEIVABLE, gc.ACCT_TYPE_PAYABLE):
                bank_name = get_account_full_name(acct)
                pay_memo  = split.GetMemo() or ''
                break

        # This record's payment amount is its OWN allocation — the AR/AP split
        # in this invoice/bill's lot (`in_lot_ar_ap_split`) — NOT the bank-side
        # total. They differ when one bank tx is split across several
        # invoices/bills: each lot holds its portion, the bank split holds the
        # sum. Emitting the bank total would over-report every record (a $400
        # wire across 3 invoices would otherwise export amount: 400 on each).
        # Format at the AR/AP account's own smallest unit, exactly (no float).
        ar_commodity = in_lot_ar_ap_split.GetAccount().GetCommodity()
        pay_amt_str = _payment_amount_text(in_lot_ar_ap_split)

        # Q-015 / Q-016: prepayment residual — what this payment left over
        # when it was made. In the Q-015 overpayment case that residual lives
        # in a fresh prepay lot (open lot, no invoice attached) or is loose
        # (no lot). In the Q-016 multi-invoice case, sibling AR splits are in
        # other invoices' lots — those are portions for those invoices and
        # were never residual.
        #
        # A document *posted after this payment* is the third case, and it
        # counts: its slice was the customer's credit on the day the money
        # arrived, and only later did it settle anything. Reading the book as
        # it stands today would say a 150.00 payment against a 100.00 invoice
        # left 20.00, because a later invoice has since taken 30.00 of it —
        # while a rebuild reaches this payment before that invoice exists and
        # finds 50.00 sitting loose, which is what the payment really left.
        in_lot_guid = in_lot_ar_ap_split.GetGUID().to_string()
        prepay = Fraction(0)
        for i in range(txn.CountSplits()):
            s = txn.GetSplit(i)
            if s.GetGUID().to_string() == in_lot_guid:
                continue
            acct = s.GetAccount()
            if acct is None:
                continue
            atype = gc.xaccAccountGetType(acct.instance)
            if atype not in (gc.ACCT_TYPE_RECEIVABLE, gc.ACCT_TYPE_PAYABLE):
                continue
            raw_lot = s.GetLot()
            if (raw_lot is not None
                    and gc.gncInvoiceGetInvoiceFromLot(raw_lot)
                    and not _split_was_applied_from_credit(s)):
                # A portion for a document this payment was made against —
                # never residual. A sibling that settled a document out of
                # credit *is* residual: it was the owner's money on the day
                # this payment landed, and a rebuild reaches this block
                # before anything has taken it.
                continue
            if is_a_bank_paid_orphan(s):
                # Q-035: nor is what an unpost left loose. `prepayment:` says
                # "park this much as the owner's credit", and restoring a file
                # that says it does exactly that — so a divided orphan's
                # residue came back an ordinary spendable credit, which is the
                # harm omitting `lot_owner:` on the same split is for. The
                # money is a settlement waiting to be put back, and a file
                # that does not claim otherwise leaves it loose.
                continue
            a = s.GetAmount()
            prepay += abs(Fraction(a.num(), a.denom()))

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
            f'		bank_account: "{bank_name}"',
            f'		txn_guid: "{txn_guid}"',
            f'		txn_split_guid: "{txn_split_guid}"',
            f'		memo: "{pay_memo}"',
        ]
        if pay_num:
            lines.append(f'		num: "{pay_num}"')
        if prepay > 0:
            # At the account's unit, like the `amount:` seven lines above it:
            # both are compared exactly on the way back in, and a residual of
            # 20.005 written as 20.00 makes a file its own book cannot read —
            # failing on the rebuild, after the document has been unposted.
            ar_account = in_lot_ar_ap_split.GetAccount()
            prepay_unit = ((ar_account.GetCommoditySCU() if ar_account else None)
                           or ar_commodity.get_fraction())
            lines.append(f'		prepayment: {money_text(prepay, prepay_unit)}')
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

        # Export all vendor bills, including unposted
        bills = []
        for inv in all_invoices:
            try:
                vendor = inv.GetOwner().GetVendor()
                if vendor is not None:
                    bills.append((inv, vendor))
            except Exception:
                pass

        guid_for_ptr = self._guid_for_ptr_factory()
        bill_strings = []
        for inv, vendor in bills:
            lines = [
                f'bill "{inv.GetID()}"',
                f'\tguid: "{guid_for_ptr(int(inv.instance))}"',
                f'	vendor_id: "{vendor.GetID()}"',
                f'\tvendor_guid: "{vendor.GetGUID().to_string()}"',
                f'	currency: {inv.GetCurrency().get_mnemonic()}',
                f'	date_opened: {inv.GetDateOpened().strftime("%Y-%m-%d")}',
            ]

            custom_meta = get_custom_metadata(inv)
            for k, v in sorted(custom_meta.items()):
                lines.append(f'	{k}: "{v}"')

            for raw_entry in inv.GetEntries():
                lines += self._format_bill_entry(lib, raw_entry)

            # posted block — always emitted; "none" sentinel when not posted
            posted_txn = inv.GetPostedTxn()
            if posted_txn:
                ap_name = get_account_full_name(inv.GetPostedAcc())
                lines.append('	posted:')
                lines.append(f'		date: {inv.GetDatePosted().strftime("%Y-%m-%d")}')
                lines.append(f'		due: {inv.GetDateDue().strftime("%Y-%m-%d")}')
                lines.append(f'		ap_account: "{ap_name}"')
                lines.append(f'		memo: "{posted_txn.GetDescription()}"')
                lines.append(f'		posted_txn_guid: "{posted_txn.GetGUID().to_string()}"')
                lines.append('		accumulate: true')
            else:
                lines.append('	posted: none')

            # payment blocks — same Q-015 credit logic as the invoice side,
            # where the credit is money the book sent this vendor.
            lot = inv.GetPostedLot()
            has_payments = False
            if lot:
                for raw_split in lot.get_split_list():
                    s   = Split(instance=raw_split)
                    txn = s.GetParent()
                    if txn is None:
                        continue
                    if gc.gncInvoiceGetInvoiceFromTxn(txn.instance) is not None:
                        continue
                    if _split_was_applied_from_credit(s):
                        lines += self._format_credit_payment(txn, s)
                    else:
                        lines += self._format_payment(txn, s)
                    has_payments = True
            if not has_payments:
                lines.append('	payment: none')

            bill_strings.append('\n'.join(lines))
        return '\n\n'.join(bill_strings)
