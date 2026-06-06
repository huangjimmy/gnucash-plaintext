#!/usr/bin/env python
"""
Use case for exporting GnuCash business objects to plaintext format.

All tax-table and invoice-entry reading uses ctypes directly because the
GnuCash Python SWIG bindings have const-type mismatches for these calls
(confirmed on GnuCash 4.4 – 5.10 across Debian 11/12/13, Ubuntu 20/22).
See infrastructure/gnucash/engine.py for the platform notes.
"""

from fractions import Fraction

import gnucash.gnucash_business as gb
import gnucash.gnucash_core_c as gc
from gnucash import Book, Query, Split

from infrastructure.gnucash.engine import iterate_glist, load_gnc_engine, safe_ctypes_string
from infrastructure.gnucash.kvp import get_custom_metadata
from infrastructure.gnucash.utils import (
    format_amount_for_commodity,
    get_account_full_name,
)


def _fmt_rate(rate: float) -> str:
    """Format a tax rate: always show at least one decimal (e.g. 5.0%, 9.975%)."""
    s = f'{rate:g}'
    if '.' not in s:
        s += '.0'
    return s + '%'


def _fmt_quantity(val: float) -> str:
    """Format quantity/price: strip trailing zeros and unnecessary decimal point."""
    return f'{val:g}'


def _payment_is_credit_consumption(txn, this_lot_id: int) -> bool:
    """Q-015 / Q-016: True iff this payment tx was an
    `gncInvoiceAutoApplyPayments` credit consumption — distinct from a
    Q-016 multi-invoice shared bank tx.

    Credit consumption produces a tx with splits in:
      * THIS invoice's lot, AND
      * a PREPAY lot (open AR/AP lot with NO invoice attached — the
        residual that the auto-apply consumed against this invoice).

    A Q-016 multi-invoice shared tx produces splits in MULTIPLE invoice
    lots but NO prepay lot — every other AR/AP-side split is in a
    different invoice's lot, all closed via posting + payment portion.

    We differentiate by looking for the prepay-lot signature: an
    AR/AP-side split on this tx whose lot has no invoice attached.
    Without that signature, the tx is a Q-016 multi-invoice payment and
    the exporter should emit a regular `payment:` block with
    `txn_guid:` + `txn_split_guid:` for each invoice's slice.
    """
    has_other_invoice_lot = False
    has_prepay_lot = False
    for i in range(txn.CountSplits()):
        sp = txn.GetSplit(i)
        acct = sp.GetAccount()
        if acct is None:
            continue
        atype = gc.xaccAccountGetType(acct.instance)
        if atype not in (gc.ACCT_TYPE_RECEIVABLE, gc.ACCT_TYPE_PAYABLE):
            continue
        raw_lot = sp.GetLot()
        if raw_lot is None:
            continue
        if int(raw_lot) == this_lot_id:
            continue
        if gc.gncInvoiceGetInvoiceFromLot(raw_lot):
            has_other_invoice_lot = True
        else:
            has_prepay_lot = True
    # Auto-apply consumption signature: tx has splits in BOTH another
    # invoice lot (the original-closure lot) AND a prepay lot (the
    # residual). Q-015 overpayment has only the prepay lot (no other
    # invoice involved); Q-016 multi-invoice payments have only other
    # invoice lots (no prepay residual). Both must NOT trigger the
    # auto_apply_credit emission.
    return has_other_invoice_lot and has_prepay_lot


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
        customers = self._export_customers()
        vendors   = self._export_vendors()
        tables    = self._export_tax_tables()
        invoices  = self._export_invoices()
        bills     = self._export_bills()
        for section in (customers, vendors, tables, invoices, bills):
            if section:
                parts.append(section)
        return '\n\n'.join(parts)

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
                rate = amt_c.num / amt_c.denom if amt_c.denom else 0.0
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
        all_invoices = [gb.Invoice(instance=r) for r in q.run()]
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
            # Q-015: payment-txs that are also attached to a different invoice's
            # lot were applied via gncInvoiceAutoApplyPayments (credit consumption).
            # They are NOT this invoice's payment; instead we set the
            # `auto_apply_credit: true` flag on the invoice header.
            lot = inv.GetPostedLot()
            has_payments = False
            uses_auto_apply = False
            if lot:
                this_lot_id = int(lot.instance)
                for raw_split in lot.get_split_list():
                    s   = Split(instance=raw_split)
                    txn = s.GetParent()
                    if txn is None:
                        continue
                    # Skip the posting transaction itself
                    if gc.gncInvoiceGetInvoiceFromTxn(txn.instance) is not None:
                        continue
                    if _payment_is_credit_consumption(txn, this_lot_id):
                        uses_auto_apply = True
                        continue
                    lines += self._format_payment(txn, s)
                    has_payments = True
            if not has_payments:
                lines.append('	payment: none')
            if uses_auto_apply:
                # Insert the flag after date_opened (slot 5 in `lines`),
                # before any billing_id / notes / custom_meta / entries.
                lines.insert(6, '	auto_apply_credit: true')

            invoice_strings.append('\n'.join(lines))
        return '\n\n'.join(invoice_strings)

    def _format_inv_entry(self, lib, raw_entry) -> list:
        ptr = int(raw_entry.instance)

        desc   = safe_ctypes_string(lib.gncEntryGetDescription, ptr)
        action = safe_ctypes_string(lib.gncEntryGetAction, ptr)
        qty_c  = lib.gncEntryGetQuantity(ptr)
        pri_c  = lib.gncEntryGetInvPrice(ptr)
        qty    = qty_c.num / qty_c.denom if qty_c.denom else 0.0
        price  = pri_c.num / pri_c.denom if pri_c.denom else 0.0

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
        qty   = qty_c.num / qty_c.denom if qty_c.denom else 0.0
        price = pri_c.num / pri_c.denom if pri_c.denom else 0.0

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
        # Format at the AR/AP commodity's own decimal count, exactly (no float).
        ar_commodity = in_lot_ar_ap_split.GetAccount().GetCommodity()
        pay_amt_str = format_amount_for_commodity(
            in_lot_ar_ap_split.GetAmount().abs(), ar_commodity)

        # Q-015 / Q-016: prepayment residual — AR/AP splits on this tx
        # that are NOT in another invoice/bill's lot. In the Q-015
        # overpayment case the residual lives in a fresh prepay lot
        # (open lot, no invoice attached) or is loose (no lot). In the
        # Q-016 multi-invoice case, sibling AR splits ARE in another
        # invoice's lot — those must NOT count as prepayment residual,
        # they're portions for other invoices.
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
            if raw_lot is not None and gc.gncInvoiceGetInvoiceFromLot(raw_lot):
                # Belongs to another invoice/bill's lot — not residual.
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
            lines.append(
                f'		prepayment: {format_amount_for_commodity(prepay, ar_commodity)}')
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
        all_invoices = [gb.Invoice(instance=r) for r in q.run()]
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

            # payment blocks — same Q-015 auto-apply logic as the invoice side.
            lot = inv.GetPostedLot()
            has_payments = False
            uses_auto_apply = False
            if lot:
                this_lot_id = int(lot.instance)
                for raw_split in lot.get_split_list():
                    s   = Split(instance=raw_split)
                    txn = s.GetParent()
                    if txn is None:
                        continue
                    if gc.gncInvoiceGetInvoiceFromTxn(txn.instance) is not None:
                        continue
                    if _payment_is_credit_consumption(txn, this_lot_id):
                        uses_auto_apply = True
                        continue
                    lines += self._format_payment(txn, s)
                    has_payments = True
            if not has_payments:
                lines.append('	payment: none')
            if uses_auto_apply:
                # Insert after date_opened (slot 5 — bills have no billing_id).
                lines.insert(6, '	auto_apply_credit: true')

            bill_strings.append('\n'.join(lines))
        return '\n\n'.join(bill_strings)
