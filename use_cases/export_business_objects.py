#!/usr/bin/env python
"""
Use case for exporting GnuCash business objects to plaintext format.

All tax-table and invoice-entry reading uses ctypes directly because the
GnuCash Python SWIG bindings have const-type mismatches for these calls
(confirmed on GnuCash 4.4 – 5.10 across Debian 11/12/13, Ubuntu 20/22).
See infrastructure/gnucash/engine.py for the platform notes.
"""

import gnucash.gnucash_business as gb
import gnucash.gnucash_core_c as gc
from gnucash import Book, Query, Split

from infrastructure.gnucash.engine import iterate_glist, load_gnc_engine, safe_ctypes_string
from infrastructure.gnucash.kvp import get_custom_metadata
from infrastructure.gnucash.utils import get_account_full_name


def _fmt_rate(rate: float) -> str:
    """Format a tax rate: always show at least one decimal (e.g. 5.0%, 9.975%)."""
    s = f'{rate:g}'
    if '.' not in s:
        s += '.0'
    return s + '%'


def _fmt_quantity(val: float) -> str:
    """Format quantity/price: strip trailing zeros and unnecessary decimal point."""
    return f'{val:g}'


class ExportBusinessObjectsUseCase:
    def __init__(self, book: Book):
        self.book = book
        self._lib = load_gnc_engine()

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
                f'  name: "{cust.GetName()}"',
                f'  currency: {cust.GetCurrency().get_mnemonic()}',
            ]
            if not cust.GetActive():
                lines.append('  active: false')
            # Only emit optional address/contact fields when non-empty
            for field, val in [
                ('addr1', addr.GetAddr1()),
                ('addr2', addr.GetAddr2()),
                ('addr3', addr.GetAddr3()),
                ('addr4', addr.GetAddr4()),
                ('email', addr.GetEmail()),
            ]:
                if val:
                    lines.append(f'  {field}: "{val}"')
            custom_meta = get_custom_metadata(cust)
            for k, v in sorted(custom_meta.items()):
                lines.append(f'  {k}: "{v}"')
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
                f'  name: "{v.GetName()}"',
                f'  currency: {v.GetCurrency().get_mnemonic()}',
            ]
            if not v.GetActive():
                lines.append('  active: false')
            custom_meta = get_custom_metadata(v)
            for k, v_val in sorted(custom_meta.items()):
                lines.append(f'  {k}: "{v_val}"')
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

        def process_tax_table(lib, tt_ptr):
            """Process single tax table pointer to plaintext lines."""
            tt_name = safe_ctypes_string(lib.gncTaxTableGetName, tt_ptr)
            lines = [f'taxtable "{tt_name}"']

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
                lines.append('  entry:')
                lines.append(f'    account: "{acct_name}"')
                lines.append(f'    rate: {_fmt_rate(rate)}')
                lines.append('    type: PERCENT')

            return '\n'.join(lines)

        tables = iterate_glist(lib, glist_ptr, process_tax_table)
        return '\n\n'.join(tables)

    # ── Invoices ─────────────────────────────────────────────────────────────

    def _export_invoices(self) -> str:
        lib = self._lib

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
                f'  customer_id: "{cust.GetID()}"',
                f'  currency: {inv.GetCurrency().get_mnemonic()}',
                f'  date_opened: {inv.GetDateOpened().strftime("%Y-%m-%d")}',
            ]
            if inv.GetBillingID():
                lines.append(f'  billing_id: "{inv.GetBillingID()}"')
            if inv.GetNotes():
                lines.append(f'  notes: "{inv.GetNotes()}"')

            custom_meta = get_custom_metadata(inv)
            for k, v in sorted(custom_meta.items()):
                lines.append(f'  {k}: "{v}"')

            for raw_entry in inv.GetEntries():
                lines += self._format_inv_entry(lib, raw_entry)

            # posted block — always emitted; "none" sentinel when not posted
            posted_txn = inv.GetPostedTxn()
            if posted_txn:
                ar_name = get_account_full_name(inv.GetPostedAcc())
                lines.append('  posted:')
                lines.append(f'    date: {inv.GetDatePosted().strftime("%Y-%m-%d")}')
                lines.append(f'    due: {inv.GetDateDue().strftime("%Y-%m-%d")}')
                lines.append(f'    ar_account: "{ar_name}"')
                lines.append(f'    memo: "{posted_txn.GetDescription()}"')
                lines.append('    accumulate: true')
            else:
                lines.append('  posted: none')

            # payment blocks — always emitted; "none" sentinel when no payments exist
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
                    lines += self._format_payment(txn)
                    has_payments = True
            if not has_payments:
                lines.append('  payment: none')

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
            '  entry:',
            f'    date: {date_str}',
            f'    description: "{desc}"',
            f'    action: "{action}"',
            f'    account: "{acct_name}"',
            f'    quantity: {_fmt_quantity(qty)}',
            f'    price: {_fmt_quantity(price)}',
            f'    taxable: {"true" if taxable else "false"}',
            f'    tax_included: {"true" if tax_incl else "false"}',
        ]

        # Tax table — ctypes required (SWIG const-type bug)
        tt_ptr = lib.gncEntryGetInvTaxTable(ptr)
        if tt_ptr:
            tt_name = safe_ctypes_string(lib.gncTaxTableGetName, tt_ptr)
            if tt_name:
                lines.append(f'    tax_table: "{tt_name}"')

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
            '  entry:',
            f'    date: {date_str}',
            f'    description: "{desc}"',
            f'    account: "{acct_name}"',
            f'    quantity: {_fmt_quantity(qty)}',
            f'    price: {_fmt_quantity(price)}',
            f'    taxable: {"true" if taxable else "false"}',
            f'    tax_included: {"true" if tax_incl else "false"}',
        ]

        tt_ptr = lib.gncEntryGetBillTaxTable(ptr)
        if tt_ptr:
            tt_name = safe_ctypes_string(lib.gncTaxTableGetName, tt_ptr)
            if tt_name:
                lines.append(f'    tax_table: "{tt_name}"')

        return lines

    def _format_payment(self, txn) -> list:
        """Format one payment transaction as payment: lines."""
        pay_date = txn.GetDate().strftime("%Y-%m-%d")
        pay_num  = txn.GetNum() or ''

        # Find the bank/asset side (non-AR) split for amount, account, and memo.
        # GnuCash's ApplyPayment stores the memo on the splits (not on the
        # transaction description, which is set to the owner/customer name).
        # Reading split.GetMemo() is consistent across all GnuCash versions.
        bank_name = ''
        pay_amt   = 0.0
        pay_memo  = ''
        for i in range(txn.CountSplits()):
            split = txn.GetSplit(i)
            acct  = split.GetAccount()
            atype = gc.xaccAccountGetType(acct.instance)
            if atype not in (gc.ACCT_TYPE_RECEIVABLE, gc.ACCT_TYPE_PAYABLE):
                bank_name = get_account_full_name(acct)
                pay_amt   = abs(split.GetAmount().to_double())
                pay_memo  = split.GetMemo() or ''
                break

        lines = [
            '  payment:',
            f'    date: {pay_date}',
            f'    amount: {_fmt_quantity(pay_amt)}',
            f'    bank_account: "{bank_name}"',
            f'    memo: "{pay_memo}"',
        ]
        if pay_num:
            lines.append(f'    num: "{pay_num}"')
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

        bill_strings = []
        for inv, vendor in bills:
            lines = [
                f'bill "{inv.GetID()}"',
                f'  vendor_id: "{vendor.GetID()}"',
                f'  currency: {inv.GetCurrency().get_mnemonic()}',
                f'  date_opened: {inv.GetDateOpened().strftime("%Y-%m-%d")}',
            ]

            custom_meta = get_custom_metadata(inv)
            for k, v in sorted(custom_meta.items()):
                lines.append(f'  {k}: "{v}"')

            for raw_entry in inv.GetEntries():
                lines += self._format_bill_entry(lib, raw_entry)

            # posted block — always emitted; "none" sentinel when not posted
            posted_txn = inv.GetPostedTxn()
            if posted_txn:
                ap_name = get_account_full_name(inv.GetPostedAcc())
                lines.append('  posted:')
                lines.append(f'    date: {inv.GetDatePosted().strftime("%Y-%m-%d")}')
                lines.append(f'    due: {inv.GetDateDue().strftime("%Y-%m-%d")}')
                lines.append(f'    ap_account: "{ap_name}"')
                lines.append(f'    memo: "{posted_txn.GetDescription()}"')
                lines.append('    accumulate: true')
            else:
                lines.append('  posted: none')

            # payment blocks — always emitted; "none" sentinel when no payments exist
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
                    lines += self._format_payment(txn)
                    has_payments = True
            if not has_payments:
                lines.append('  payment: none')

            bill_strings.append('\n'.join(lines))
        return '\n\n'.join(bill_strings)
