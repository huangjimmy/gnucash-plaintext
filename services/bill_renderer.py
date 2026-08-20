#!/usr/bin/env python
"""
Service for rendering GnuCash vendor bills to HTML/PDF/plaintext.

Q-019: parallel to services/invoice_renderer.py. A bill is a vendor's
invoice — one `gncInvoice` type with a vendor owner — so the HTML page
is GnuCash's own Printable Invoice, drawn exactly as an invoice's is,
with the vendor as the document's owner. Nothing here decides which
party goes on which side of it.

The plaintext render is this project's, and computes what GnuCash
would: an unposted bill has no tax splits yet, so tax comes from each
entry's bill-side tax_table through compute_bill_entry_informational,
and the output says the figures are provisional — a plaintext document
is re-imported, and its numbers are checked against a recomputation.
"""
from fractions import Fraction

import gnucash.gnucash_core_c as gc
from gnucash import Split

from infrastructure.gnucash.engine import (
    load_gnc_engine,
    safe_ctypes_string,
)
from infrastructure.gnucash.kvp import (
    KNOWN_VENDOR_METADATA_KEYS,
)
from infrastructure.gnucash.utils import (
    encode_value_as_string,
    exact_text,
    numeric_to_fraction,
)
from services.invoice_renderer import (
    _fmt_money,
    _fmt_rate,
    _render_seller_header,
    _render_taxtable_block,
    credit_note_lines,
    document_totals,
    entries_fitted_to_the_document,
    tax_breakdown,
)
from services.plaintext_blocks import (
    bill_entry_flags,
    document_text_lines,
    entry_notes,
    owner_block_lines,
    payment_block_lines,
    posted_block_lines,
)


def compute_bill_entry_informational(lib, entry_ptr, is_credit_note=0):
    """Bill-side analogue of `compute_entry_informational`, and asked of the
    same engine functions with `is_cust_doc=0`.

    `is_credit_note` is the document's credit-note flag, and it does here what it does
    on the invoice side: a vendor credit note stores its lines negated, so
    the flag is what turns them back into the figures its own totals state.

    A bill line has no discount — GnuCash's bill window has no such column —
    so the figures are what quantity × price gave before, with one
    difference that matters: these are rounded to the currency's smallest
    unit per line, as the posting is. Summing exact fractions and rounding
    the total at print time can differ from the A/P split by a cent on a
    tax-included bill of several lines, which is the defect the invoice side
    was just taken off.
    """
    value = lib.gncEntryGetDocValue(entry_ptr, 1, 0, is_credit_note)
    # Unrounded, as the invoice side reads it: the document's tax is rounded
    # once, and the lines are fitted to it where the page is written.
    tax = lib.gncEntryGetDocTaxValue(entry_ptr, 0, 0, is_credit_note)
    net = numeric_to_fraction(value) if value.denom else Fraction(0)
    entry_tax = numeric_to_fraction(tax) if tax.denom else Fraction(0)

    taxable = bool(lib.gncEntryGetBillTaxable(entry_ptr))
    tt_ptr = lib.gncEntryGetBillTaxTable(entry_ptr) if taxable else None
    if not taxable or not tt_ptr:
        return (net, Fraction(0), [])

    return (net, entry_tax,
            tax_breakdown(lib, entry_ptr, tt_ptr, is_cust_doc=0, is_credit_note=is_credit_note))


def render_to_html(bill, session, report=None, report_file=None,
                   warn=None) -> str:
    """The bill as HTML — see `invoice_renderer.render_to_html`.

    One report serves both: a bill is a `gncInvoice` with a vendor owner, and
    GnuCash draws it from the same report — including a report of the reader's
    own, named through `report` after `report_file` has registered it.
    """
    from services.gnucash_importer import _swig_invoice_guid_str
    from services.gnucash_report import (
        _extra_text,
        carry_slot_values_onto_the_fields,
        render_document_html,
    )

    carry_slot_values_onto_the_fields(bill)
    company_extra, owner_extra = _extra_text(bill)
    return render_document_html(
        session, _swig_invoice_guid_str(bill),
        company_extra=company_extra, owner_extra=owner_extra,
        report=report, report_file=report_file, warn=warn)


def _render_vendor_block(vendor) -> str:
    """The vendor block, written by `services/plaintext_blocks`."""
    return '\n'.join(owner_block_lines(
        'vendor', vendor, KNOWN_VENDOR_METADATA_KEYS))


def render_to_plaintext(bill, book, company_info=None) -> str:
    """Render one vendor bill as canonical plaintext, populated with the
    Q-017 bill_* informational fields (entry_amount, entry_tax,
    breakdown, bill_subtotal, bill_tax_total, bill_total). The output is
    self-contained: taxtable definitions for every referenced table, the
    vendor header, then the bill block. A `# Bill received from: ...`
    seller comment (Q-019) tells the recipient who the vendor is."""
    lib = load_gnc_engine()

    # As the invoice side reads it, and for the same reason.
    is_credit_note = 1 if bill.GetIsCreditNote() else 0

    bill_id = bill.GetID()
    vendor = bill.GetOwner().GetVendor()
    if vendor is None:
        raise ValueError(f'bill {bill_id!r} has no vendor owner')

    posting_txn = bill.GetPostedTxn()
    is_draft = posting_txn is None
    currency = bill.GetCurrency().get_mnemonic()
    unit = bill.GetCurrency().get_fraction()
    date_opened = bill.GetDateOpened().strftime('%Y-%m-%d')

    seen_tt = {}
    entries_data = []
    for raw_entry in bill.GetEntries():
        ent_ptr = int(raw_entry.instance)
        entry_amount, entry_tax, breakdown = compute_bill_entry_informational(
            lib, ent_ptr, is_credit_note,
        )
        entries_data.append((raw_entry, entry_amount, entry_tax, breakdown))
        tt_ptr = lib.gncEntryGetBillTaxTable(ent_ptr)
        if tt_ptr and int(tt_ptr) not in seen_tt:
            seen_tt[int(tt_ptr)] = tt_ptr

    subtotal, tax_total, total = document_totals(lib, bill)
    entries_data = entries_fitted_to_the_document(entries_data, tax_total,
                                                  unit, subtotal)

    blocks = []
    for tt_ptr in seen_tt.values():
        blocks.append(_render_taxtable_block(lib, tt_ptr))

    blocks.append(_render_vendor_block(vendor))

    bill_lines = [
        f'bill "{bill_id}"',
        f'\tvendor_id: {encode_value_as_string(vendor.GetID())}',
        f'\tcurrency: {currency}',
        f'\tdate_opened: {date_opened}',
    ]
    bill_lines += credit_note_lines(bill)
    bill_lines += document_text_lines(bill)

    from infrastructure.gnucash.utils import (
        get_account_full_name,
    )

    for raw_entry, entry_amount, entry_tax, breakdown in entries_data:
        ent_ptr = int(raw_entry.instance)
        desc = safe_ctypes_string(lib.gncEntryGetDescription, ent_ptr)
        qty_c = lib.gncEntryGetQuantity(ent_ptr)
        pri_c = lib.gncEntryGetBillPrice(ent_ptr)
        qty = numeric_to_fraction(qty_c) if qty_c.denom else Fraction(0)
        price = numeric_to_fraction(pri_c) if pri_c.denom else Fraction(0)
        taxable = bool(lib.gncEntryGetBillTaxable(ent_ptr))
        tax_included = bool(lib.gncEntryGetBillTaxIncluded(ent_ptr))
        acct_name = get_account_full_name(raw_entry.GetBillAccount())
        date_str = raw_entry.GetDate().strftime('%Y-%m-%d')

        bill_lines.append('\tentry:')
        bill_lines.append(f'\t\tdate: {date_str}')
        bill_lines.append(f'\t\tdescription: {encode_value_as_string(desc)}')
        # One `GncEntry` action field, shown in the bill window's Action
        # column too, written as `export` writes it and re-imported from here.
        action = safe_ctypes_string(lib.gncEntryGetAction, ent_ptr) or ''
        bill_lines.append(f'\t\taction: {encode_value_as_string(action)}')
        bill_lines.append(f'\t\taccount: {encode_value_as_string(acct_name)}')
        bill_lines.append(f'\t\tquantity: {exact_text(qty)}')
        bill_lines.append(f'\t\tprice: {exact_text(price)}')
        bill_lines.append(f'\t\ttaxable: {encode_value_as_string(taxable)}')
        bill_lines.append(
            f'\t\ttax_included: {encode_value_as_string(tax_included)}'
        )

        tt_ptr = lib.gncEntryGetBillTaxTable(ent_ptr)
        if tt_ptr:
            tt_name = safe_ctypes_string(lib.gncTaxTableGetName, tt_ptr)
            if tt_name:
                bill_lines.append(
                    f'\t\ttax_table: {encode_value_as_string(tt_name)}')

        # Written from the same place `export` writes them, this document
        # being re-importable: a field dropped here is a field the re-import
        # takes out of the book.
        bill_lines.extend(entry_notes(lib, ent_ptr))
        bill_lines.extend(bill_entry_flags(lib, ent_ptr))

        bill_lines.append(f'\t\tentry_amount: {_fmt_money(entry_amount, unit)}')
        bill_lines.append(f'\t\tentry_tax: {_fmt_money(entry_tax, unit)}')
        for bd_acct_name, bd_rate, bd_amount in breakdown:
            bill_lines.append('\t\tbreakdown:')
            bill_lines.append(
                f'\t\t\taccount: {encode_value_as_string(bd_acct_name)}')
            bill_lines.append(f'\t\t\trate: {_fmt_rate(bd_rate)}')
            bill_lines.append(f'\t\t\tamount: {_fmt_money(bd_amount, unit)}')

    if is_draft:
        bill_lines.append('\tposted: none')
        bill_lines.append('\tpayment: none')
    else:
        ap_name = get_account_full_name(bill.GetPostedAcc())
        bill_lines += posted_block_lines(bill, 'ap_account', ap_name)

        lot = bill.GetPostedLot()
        had_payment = False
        if lot is not None:
            for raw_split in lot.get_split_list():
                s = Split(instance=raw_split)
                txn = s.GetParent()
                if txn is None:
                    continue
                if gc.gncInvoiceGetInvoiceFromTxn(txn.instance) is not None:
                    continue
                bank_name = ''
                pay_memo = ''
                for i in range(txn.CountSplits()):
                    sp = txn.GetSplit(i)
                    atype = gc.xaccAccountGetType(sp.GetAccount().instance)
                    if atype not in (
                        gc.ACCT_TYPE_RECEIVABLE, gc.ACCT_TYPE_PAYABLE,
                    ):
                        bank_name = get_account_full_name(sp.GetAccount())
                        pay_memo = sp.GetMemo() or ''
                        break
                # As the invoice renderer does: the amount is the block
                # writer's to work out, from `s` — this bill's own allocation,
                # not the bank-side total.
                bill_lines += payment_block_lines(
                    txn, s, bank_name, pay_memo,
                    f'bill "{bill.GetID()}"', txn.GetNum() or '')

                had_payment = True
        if not had_payment:
            bill_lines.append('\tpayment: none')

    # The document's own totals, as the invoice side takes them: GnuCash
    # rounds a document's tax once, and three 100.00 lines at 15 per cent
    # tax-included post 300.01 where the rounded per-line tax adds to 300.00.
    # The lines above were fitted to these, so both columns add up.
    bill_lines.append(f'\tbill_subtotal: {_fmt_money(subtotal, unit)}')
    bill_lines.append(f'\tbill_tax_total: {_fmt_money(tax_total, unit)}')
    bill_lines.append(f'\tbill_total: {_fmt_money(total, unit)}')

    # Q-019: bill-scoped caveats — vendor name line and (drafts only)
    # provisional-tax notice. Both prepend to the bill block; the
    # seller `# Bill received by:` header (file-scoped) is added below.
    bill_scoped = [f'# Bill from vendor: {vendor.GetName()}']
    if is_draft:
        bill_scoped.append(
            '# Tax figures are provisional — bill not yet posted; '
            'recomputed at post time.'
        )
    bill_lines = bill_scoped + bill_lines

    blocks.append('\n'.join(bill_lines))

    co_header = _render_seller_header(company_info)
    if co_header:
        # File-scoped — "this whole rendered document was sent to us".
        # Reuse the invoice header but swap the "Issued by" prefix for
        # bill-side phrasing.
        blocks.insert(
            0,
            co_header.replace('# Issued by:', '# Bill received by:', 1),
        )

    return '\n\n'.join(blocks) + '\n'
