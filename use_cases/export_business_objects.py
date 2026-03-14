#!/usr/bin/env python
"""
Use case for exporting GnuCash business objects to plaintext format.

All tax-table and invoice-entry reading uses ctypes directly because the
GnuCash Python SWIG bindings have const-type mismatches for these calls
(confirmed on GnuCash 4.4 – 5.10 across Debian 11/12/13, Ubuntu 20/22).
See infrastructure/gnucash/engine.py for the platform notes.
"""
import ctypes

import gnucash.gnucash_business as gb
import gnucash.gnucash_core_c as gc
from gnucash import Book, Query, Split

from infrastructure.gnucash.engine import load_gnc_engine
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
        """
        lib = self._lib
        parts = []
        ptr = acct_ptr
        while ptr:
            name_b = lib.xaccAccountGetName(ptr)
            if name_b:
                parts.append(name_b.decode('utf-8'))
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
        customers = [gb.Customer(instance=r) for r in q.run()]
        q.destroy()

        lines_list = []
        for cust in customers:
            addr  = cust.GetAddr()
            lines = [
                f'customer "{cust.GetID()}"',
                f'  name: "{cust.GetName()}"',
                f'  currency: {cust.GetCurrency().get_mnemonic()}',
            ]
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
            lines_list.append('\n'.join(lines))
        return '\n\n'.join(lines_list)

    # ── Vendors ──────────────────────────────────────────────────────────────

    def _export_vendors(self) -> str:
        q = Query()
        q.search_for('gncVendor')
        q.set_book(self.book)
        vendors = [gb.Vendor(instance=r) for r in q.run()]
        q.destroy()

        lines_list = []
        for v in vendors:
            lines = [
                f'vendor "{v.GetID()}"',
                f'  name: "{v.GetName()}"',
                f'  currency: {v.GetCurrency().get_mnemonic()}',
            ]
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

        tables = []
        while glist_ptr:
            buf    = (ctypes.c_void_p * 3).from_address(glist_ptr)
            tt_ptr = buf[0]
            glist_ptr = buf[1]
            if not tt_ptr:
                continue

            name_b  = lib.gncTaxTableGetName(tt_ptr)
            tt_name = name_b.decode('utf-8') if name_b else ''

            lines = [f'taxtable "{tt_name}"']

            # Walk the entries GList (GnuCash prepends → reverse for canonical order)
            entries_ptr = lib.gncTaxTableGetEntries(tt_ptr)
            entry_parts = []
            while entries_ptr:
                ebuf        = (ctypes.c_void_p * 3).from_address(entries_ptr)
                tte_ptr     = ebuf[0]
                entries_ptr = ebuf[1]
                if not tte_ptr:
                    continue
                acct_ptr  = lib.gncTaxTableEntryGetAccount(tte_ptr)
                amt_c     = lib.gncTaxTableEntryGetAmount(tte_ptr)
                rate      = amt_c.num / amt_c.denom if amt_c.denom else 0.0
                acct_name = self._account_full_name(acct_ptr) if acct_ptr else '?'
                entry_parts.append((acct_name, rate))

            entry_parts.reverse()   # GnuCash prepends → put GST before PST/QST
            for acct_name, rate in entry_parts:
                lines.append('  entry:')
                lines.append(f'    account: "{acct_name}"')
                lines.append(f'    rate: {_fmt_rate(rate)}')
                lines.append('    type: PERCENT')

            tables.append('\n'.join(lines))
        return '\n\n'.join(tables)

    # ── Invoices ─────────────────────────────────────────────────────────────

    def _export_invoices(self) -> str:
        lib = self._lib

        q = Query()
        q.search_for('gncInvoice')
        q.set_book(self.book)
        all_invoices = [gb.Invoice(instance=r) for r in q.run()]
        q.destroy()

        # Only export customer invoices (owner is Customer, not Vendor)
        invoices = []
        for inv in all_invoices:
            if not inv.IsPosted():
                continue
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

            for raw_entry in inv.GetEntries():
                lines += self._format_inv_entry(lib, raw_entry)

            # posted block
            posted_txn = inv.GetPostedTxn()
            if posted_txn:
                ar_name = get_account_full_name(inv.GetPostedAcc())
                lines.append('  posted:')
                lines.append(f'    date: {inv.GetDatePosted().strftime("%Y-%m-%d")}')
                lines.append(f'    due: {inv.GetDateDue().strftime("%Y-%m-%d")}')
                lines.append(f'    ar_account: "{ar_name}"')
                lines.append(f'    memo: "{posted_txn.GetDescription()}"')
                lines.append('    accumulate: true')

            # payment blocks — from lot splits, excluding the posting transaction
            lot = inv.GetPostedLot()
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

            invoice_strings.append('\n'.join(lines))
        return '\n\n'.join(invoice_strings)

    def _format_inv_entry(self, lib, raw_entry) -> list:
        ptr = int(raw_entry.instance)

        desc   = (lib.gncEntryGetDescription(ptr) or b'').decode('utf-8')
        action = (lib.gncEntryGetAction(ptr)      or b'').decode('utf-8')
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
            name_b  = lib.gncTaxTableGetName(tt_ptr)
            tt_name = name_b.decode('utf-8') if name_b else ''
            if tt_name:
                lines.append(f'    tax_table: "{tt_name}"')

        return lines

    def _format_payment(self, txn) -> list:
        """Format one payment transaction as payment: lines."""
        pay_date = txn.GetDate().strftime("%Y-%m-%d")
        pay_memo = txn.GetDescription() or ''
        pay_num  = txn.GetNum() or ''

        # Find the bank/asset side (non-AR) split for amount + account
        bank_name = ''
        pay_amt   = 0.0
        for i in range(txn.CountSplits()):
            split = txn.GetSplit(i)
            acct  = split.GetAccount()
            atype = gc.xaccAccountGetType(acct.instance)
            if atype not in (gc.ACCT_TYPE_RECEIVABLE, gc.ACCT_TYPE_PAYABLE):
                bank_name = get_account_full_name(acct)
                pay_amt   = abs(split.GetAmount().to_double())
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

        bills = []
        for inv in all_invoices:
            if not inv.IsPosted():
                continue
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

            for raw_entry in inv.GetEntries():
                lines += self._format_inv_entry(lib, raw_entry)

            posted_txn = inv.GetPostedTxn()
            if posted_txn:
                ap_name = get_account_full_name(inv.GetPostedAcc())
                lines.append('  posted:')
                lines.append(f'    date: {inv.GetDatePosted().strftime("%Y-%m-%d")}')
                lines.append(f'    due: {inv.GetDateDue().strftime("%Y-%m-%d")}')
                lines.append(f'    ap_account: "{ap_name}"')
                lines.append(f'    memo: "{posted_txn.GetDescription()}"')
                lines.append('    accumulate: true')

            lot = inv.GetPostedLot()
            if lot:
                for raw_split in lot.get_split_list():
                    s   = Split(instance=raw_split)
                    txn = s.GetParent()
                    if txn is None:
                        continue
                    if gc.gncInvoiceGetInvoiceFromTxn(txn.instance) is not None:
                        continue
                    lines += self._format_payment(txn)

            bill_strings.append('\n'.join(lines))
        return '\n\n'.join(bill_strings)
