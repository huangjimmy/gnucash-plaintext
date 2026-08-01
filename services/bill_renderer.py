#!/usr/bin/env python
"""
Service for rendering GnuCash vendor bills to HTML/PDF/plaintext.

Q-019: parallel to services/invoice_renderer.py. A bill is the inverse
of an invoice — money flows FROM us (Bill To) TO a vendor (Bill From),
so the two-sided rendering swaps the role of the company-info block
and the owner block compared to invoices.

Tax handling mirrors the invoice renderer: posted bills read tax from
the posting transaction's AP splits; unposted bills compute tax from
each entry's bill-side tax_table via compute_bill_entry_informational
and the rendered output carries a `draft-tax-notice` class so the
viewer knows the figures are provisional.
"""
import xml.etree.ElementTree as ET
from fractions import Fraction

import gnucash.gnucash_core_c as gc
from gnucash import Split

from infrastructure.gnucash.engine import (
    iterate_glist,
    load_gnc_engine,
    safe_ctypes_string,
)
from infrastructure.gnucash.kvp import get_custom_metadata
from infrastructure.gnucash.utils import exact_text, money_text, numeric_to_fraction
from services.invoice_renderer import (
    _ctypes_account_full_name,
    _fmt_money,
    _fmt_rate,
    _render_seller_header,
    _render_taxtable_block,
    build_company_xml,
)


def _read_bill_tax_label(lib, ptr):
    """Per-entry tax label for the rendered bill line. Uses Bill-side
    getters per CLAUDE.md ("Bill Entry API vs Invoice Entry API")."""
    taxable = bool(lib.gncEntryGetBillTaxable(ptr))
    if not taxable:
        return 'Exempt', 'exempt'

    tt_ptr = lib.gncEntryGetBillTaxTable(ptr)
    if not tt_ptr:
        return 'Taxable', 'single'

    tt_name = safe_ctypes_string(lib.gncTaxTableGetName, tt_ptr, default='Taxable')

    glist_ptr = lib.gncTaxTableGetEntries(tt_ptr)

    def process_tax_table_entry(_lib, tte_ptr):
        acct_ptr = _lib.gncTaxTableEntryGetAccount(tte_ptr)
        amt_c = _lib.gncTaxTableEntryGetAmount(tte_ptr)
        rate = numeric_to_fraction(amt_c) if amt_c.denom else Fraction(0)
        name = safe_ctypes_string(_lib.xaccAccountGetName, acct_ptr, default='?')
        rate_str = f'{exact_text(rate)}%'
        return name if rate_str in name else f"{name} {rate_str}"

    rate_parts = iterate_glist(lib, glist_ptr, process_tax_table_entry)
    rate_parts.reverse()

    if not rate_parts:
        return tt_name, 'single'

    label = ' + '.join(rate_parts)
    ttype = 'combined' if len(rate_parts) > 1 else 'single'
    return label, ttype


def _bill_tax_table_entries(lib, tt_ptr):
    """Return [(account_full_name, rate_decimal)] for one tax-table
    pointer in declaration order. Same shape as the invoice helper;
    used by compute_bill_entry_informational."""

    def _one(_lib, tte_ptr):
        acct_ptr = _lib.gncTaxTableEntryGetAccount(tte_ptr)
        amt_c = _lib.gncTaxTableEntryGetAmount(tte_ptr)
        # Exact, for the reason the invoice side is: a rate that no float says
        # exactly carries its error straight into the tax dollars.
        rate_pct = numeric_to_fraction(amt_c) if amt_c.denom else Fraction(0)
        rate = rate_pct / 100
        acct_name = _ctypes_account_full_name(_lib, acct_ptr) if acct_ptr else '?'
        return (acct_name, rate)

    entries_ptr = lib.gncTaxTableGetEntries(tt_ptr)
    entries = iterate_glist(lib, entries_ptr, _one)
    entries.reverse()
    return entries


def compute_bill_entry_informational(lib, entry_ptr):
    """Bill-side analogue of compute_entry_informational. Returns
    (entry_amount, entry_tax, breakdown) where the per-entry net amount,
    tax dollars, and per-account breakdown are computed from the entry's
    bill-side tax_table and tax_included flag."""
    qty_c = lib.gncEntryGetQuantity(entry_ptr)
    pri_c = lib.gncEntryGetBillPrice(entry_ptr)
    qty = numeric_to_fraction(qty_c) if qty_c.denom else Fraction(0)
    price = numeric_to_fraction(pri_c) if pri_c.denom else Fraction(0)
    gross_or_net = qty * price

    taxable = bool(lib.gncEntryGetBillTaxable(entry_ptr))
    tax_included = bool(lib.gncEntryGetBillTaxIncluded(entry_ptr))
    tt_ptr = lib.gncEntryGetBillTaxTable(entry_ptr) if taxable else None

    if not taxable or not tt_ptr:
        return (gross_or_net, Fraction(0), [])

    tt_entries = _bill_tax_table_entries(lib, tt_ptr)
    total_rate = sum((rate for _, rate in tt_entries), Fraction(0))
    net = gross_or_net / (1 + total_rate) if tax_included else gross_or_net
    breakdown = [(acct, rate, net * rate) for acct, rate in tt_entries]
    entry_tax = sum((amount for _, _, amount in breakdown), Fraction(0))
    return (net, entry_tax, breakdown)


def bill_to_xml(bill, book, company_info=None):
    """Render a vendor bill as XML for bill.xslt.

    The output XML shape mirrors invoice_to_xml so the same XSLT
    machinery (label-colspan template, per-entry rows, tax-line rows,
    payment-history block) can be reused. The semantic role swap
    ("Bill From" = vendor, "Bill To" = us) happens in bill.xslt's
    address section, not here — the XML uses neutral element names
    (`<vendor>`, `<company>`) so both renderers stay consistent.
    """
    lib = load_gnc_engine()

    bill_id = bill.GetID()
    posting_txn = bill.GetPostedTxn()
    is_draft = posting_txn is None
    is_paid = False if is_draft else gc.gncInvoiceIsPaid(bill.instance)

    bill_kvp = get_custom_metadata(bill) or {}
    cash_basis_marker = (
        str(bill_kvp.get('cash_basis', '')).strip().lower() == 'true'
    )
    currency = bill.GetCurrency().get_mnemonic()
    date_opened = bill.GetDateOpened().strftime("%Y-%m-%d")
    date_due = bill.GetDateDue()
    date_due_s = date_due.strftime("%Y-%m-%d") if date_due else ''
    if not date_due_s and is_draft and bill_kvp.get('due_date'):
        date_due_s = str(bill_kvp['due_date']).strip()
    notes = bill.GetNotes() or ''
    billing_id = bill.GetBillingID() or ''

    vendor = None
    try:
        owner = bill.GetOwner()
        vendor = owner.GetVendor()
    except Exception:
        pass
    if vendor is None:
        raise ValueError("Could not determine vendor for bill")

    addr = vendor.GetAddr()
    vend_name = vendor.GetName()
    addr1, addr2 = addr.GetAddr1(), addr.GetAddr2()
    addr3, addr4 = addr.GetAddr3(), addr.GetAddr4()
    email = addr.GetEmail()

    if is_draft and not cash_basis_marker:
        status = 'draft'
    elif is_paid:
        status = 'paid'
    else:
        status = 'unpaid'
    root = ET.Element('bill', status=status, currency=currency)
    ET.SubElement(root, 'id').text = bill_id
    ET.SubElement(root, 'date').text = date_opened
    ET.SubElement(root, 'due-date').text = date_due_s
    ET.SubElement(root, 'billing-id').text = billing_id
    ET.SubElement(root, 'notes').text = notes

    v_el = ET.SubElement(root, 'vendor')
    ET.SubElement(v_el, 'name').text = vend_name
    ET.SubElement(v_el, 'addr1').text = addr1 or ''
    ET.SubElement(v_el, 'addr2').text = addr2 or ''
    ET.SubElement(v_el, 'addr3').text = addr3 or ''
    ET.SubElement(v_el, 'addr4').text = addr4 or ''
    ET.SubElement(v_el, 'email').text = email or ''

    build_company_xml(root, company_info)

    entries_el = ET.SubElement(root, 'entries')
    # Every figure stays exact until it is written, at the bill currency's own
    # smallest unit.
    unit = bill.GetCurrency().get_fraction()
    entries_subtotal = Fraction(0)
    tax_account_totals = {}
    for raw_entry in bill.GetEntries():
        ptr = int(raw_entry.instance)
        desc = safe_ctypes_string(lib.gncEntryGetDescription, ptr)
        # Bills don't have an `action` field (see _format_bill_entry).
        qty_c = lib.gncEntryGetQuantity(ptr)
        price_c = lib.gncEntryGetBillPrice(ptr)
        qty = numeric_to_fraction(qty_c) if qty_c.denom else Fraction(0)
        price = numeric_to_fraction(price_c) if price_c.denom else Fraction(0)
        net_amount, _entry_tax, breakdown = compute_bill_entry_informational(
            lib, ptr,
        )
        entries_subtotal += net_amount
        for bd_acct_name, _bd_rate, bd_amount in breakdown:
            tax_account_totals[bd_acct_name] = (
                tax_account_totals.get(bd_acct_name, Fraction(0)) + bd_amount
            )

        tax_label, tax_type = _read_bill_tax_label(lib, ptr)

        e_el = ET.SubElement(entries_el, 'entry')
        ET.SubElement(e_el, 'description').text = desc
        ET.SubElement(e_el, 'action').text = ''
        ET.SubElement(e_el, 'quantity').text = exact_text(qty)
        ET.SubElement(e_el, 'unit-price').text = money_text(price, unit)
        ET.SubElement(e_el, 'amount').text = money_text(net_amount, unit)
        ET.SubElement(e_el, 'tax-label', type=tax_type).text = tax_label

    tax_lines_el = ET.SubElement(root, 'tax-lines')
    payments_el = ET.SubElement(root, 'payments')

    if is_draft:
        for acct_name, dollars in tax_account_totals.items():
            tl = ET.SubElement(tax_lines_el, 'tax-line')
            ET.SubElement(tl, 'name').text = acct_name.rsplit(':', 1)[-1]
            ET.SubElement(tl, 'amount').text = money_text(dollars, unit)
        grand_total = entries_subtotal + sum(
            tax_account_totals.values(), Fraction(0))
        ET.SubElement(root, 'subtotal').text = money_text(entries_subtotal, unit)
        ET.SubElement(root, 'total').text = money_text(grand_total, unit)
        ET.SubElement(root, 'draft-tax-notice')
        return ET.ElementTree(root)

    # Posted: derive tax lines + subtotal from the posting transaction's
    # splits. Skip the AP-posting split (matches the bill's PostedAcc);
    # EXPENSE splits make up the subtotal; everything else is a tax
    # accrual (LIABILITY for accrued payable tax, ASSET for a
    # recoverable input-tax-credit account, etc.).
    posted_ap_acct = bill.GetPostedAcc()
    subtotal_total = Fraction(0)
    tax_total = Fraction(0)
    for i in range(posting_txn.CountSplits()):
        s = posting_txn.GetSplit(i)
        acct = s.GetAccount()
        atype = gc.xaccAccountGetType(acct.instance)
        amt = abs(numeric_to_fraction(s.GetAmount()))
        if (posted_ap_acct is not None
                and acct.instance == posted_ap_acct.instance):
            continue
        if atype == gc.ACCT_TYPE_EXPENSE:
            subtotal_total += amt
        else:
            tax_total += amt
            tl = ET.SubElement(tax_lines_el, 'tax-line')
            ET.SubElement(tl, 'name').text = acct.GetName()
            ET.SubElement(tl, 'amount').text = money_text(amt, unit)

    grand_total = subtotal_total + tax_total
    ET.SubElement(root, 'subtotal').text = money_text(subtotal_total, unit)
    ET.SubElement(root, 'total').text = money_text(grand_total, unit)

    lot = bill.GetPostedLot()
    for raw_split in lot.get_split_list():
        s = Split(instance=raw_split)
        txn = s.GetParent()
        if txn is None:
            continue
        if gc.gncInvoiceGetInvoiceFromTxn(txn.instance) is not None:
            continue
        pay_date = txn.GetDate().strftime("%Y-%m-%d")
        pay_memo = txn.GetDescription() or ''
        pay_num = txn.GetNum() or ''
        pay_amt = abs(numeric_to_fraction(s.GetAmount()))
        p_el = ET.SubElement(payments_el, 'payment')
        ET.SubElement(p_el, 'date').text = pay_date
        ET.SubElement(p_el, 'memo').text = pay_memo
        ET.SubElement(p_el, 'num').text = pay_num
        ET.SubElement(p_el, 'amount').text = money_text(pay_amt, unit)

    remaining = abs(numeric_to_fraction(lot.get_balance()))
    ET.SubElement(root, 'amount-remaining').text = money_text(remaining, unit)

    return ET.ElementTree(root)


def render_to_html(bill, book, xslt_path, company_info=None) -> str:
    """Apply bill.xslt to the bill's XML and return the HTML string."""
    from lxml import etree as lxml_etree

    xml_tree = bill_to_xml(bill, book, company_info=company_info)
    xml_str = ET.tostring(xml_tree.getroot(), encoding='unicode')
    xml_doc = lxml_etree.fromstring(xml_str)
    xslt_doc = lxml_etree.parse(xslt_path)
    transform = lxml_etree.XSLT(xslt_doc)
    return str(transform(xml_doc))


def render_to_pdf(bill, book, xslt_path, pdf_path, company_info=None):
    import weasyprint

    html = render_to_html(bill, book, xslt_path, company_info=company_info)
    weasyprint.HTML(string=html).write_pdf(pdf_path)


def _render_vendor_block(vendor) -> str:
    """Minimal vendor block — id, name, currency. The bill plaintext
    re-importer looks up vendors by id, so the block is required for
    self-contained re-import; address/email aren't needed."""
    return (
        f'vendor "{vendor.GetID()}"\n'
        f'\tname: "{vendor.GetName()}"\n'
        f'\tcurrency: {vendor.GetCurrency().get_mnemonic()}'
    )


def render_to_plaintext(bill, book, company_info=None) -> str:
    """Render one vendor bill as canonical plaintext, populated with the
    Q-017 bill_* informational fields (entry_amount, entry_tax,
    breakdown, bill_subtotal, bill_tax_total, bill_total). The output is
    self-contained: taxtable definitions for every referenced table, the
    vendor header, then the bill block. A `# Bill received from: ...`
    seller comment (Q-019) tells the recipient who the vendor is."""
    lib = load_gnc_engine()

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
            lib, ent_ptr,
        )
        entries_data.append((raw_entry, entry_amount, entry_tax, breakdown))
        tt_ptr = lib.gncEntryGetBillTaxTable(ent_ptr)
        if tt_ptr and int(tt_ptr) not in seen_tt:
            seen_tt[int(tt_ptr)] = tt_ptr

    blocks = []
    for tt_ptr in seen_tt.values():
        blocks.append(_render_taxtable_block(lib, tt_ptr))

    blocks.append(_render_vendor_block(vendor))

    bill_lines = [
        f'bill "{bill_id}"',
        f'\tvendor_id: "{vendor.GetID()}"',
        f'\tcurrency: {currency}',
        f'\tdate_opened: {date_opened}',
    ]

    from infrastructure.gnucash.utils import (
        format_amount_for_commodity,
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
        bill_lines.append(f'\t\tdescription: "{desc}"')
        bill_lines.append(f'\t\taccount: "{acct_name}"')
        bill_lines.append(f'\t\tquantity: {exact_text(qty)}')
        bill_lines.append(f'\t\tprice: {exact_text(price)}')
        bill_lines.append(f'\t\ttaxable: {"true" if taxable else "false"}')
        bill_lines.append(
            f'\t\ttax_included: {"true" if tax_included else "false"}'
        )

        tt_ptr = lib.gncEntryGetBillTaxTable(ent_ptr)
        if tt_ptr:
            tt_name = safe_ctypes_string(lib.gncTaxTableGetName, tt_ptr)
            if tt_name:
                bill_lines.append(f'\t\ttax_table: "{tt_name}"')

        bill_lines.append(f'\t\tentry_amount: {_fmt_money(entry_amount, unit)}')
        bill_lines.append(f'\t\tentry_tax: {_fmt_money(entry_tax, unit)}')
        for bd_acct_name, bd_rate, bd_amount in breakdown:
            bill_lines.append('\t\tbreakdown:')
            bill_lines.append(f'\t\t\taccount: "{bd_acct_name}"')
            bill_lines.append(f'\t\t\trate: {_fmt_rate(bd_rate)}')
            bill_lines.append(f'\t\t\tamount: {_fmt_money(bd_amount, unit)}')

    if is_draft:
        bill_lines.append('\tposted: none')
        bill_lines.append('\tpayment: none')
    else:
        ap_name = get_account_full_name(bill.GetPostedAcc())
        bill_lines.append('\tposted:')
        bill_lines.append(
            f'\t\tdate: {bill.GetDatePosted().strftime("%Y-%m-%d")}'
        )
        bill_lines.append(
            f'\t\tdue: {bill.GetDateDue().strftime("%Y-%m-%d")}'
        )
        bill_lines.append(f'\t\tap_account: "{ap_name}"')
        bill_lines.append(f'\t\tmemo: "{posting_txn.GetDescription()}"')
        bill_lines.append('\t\taccumulate: true')

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
                pay_date = txn.GetDate().strftime('%Y-%m-%d')
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
                # This bill's payment amount is its own allocation — the AP
                # split in its lot (`s`) — not the bank-side total, which would
                # over-report when one bank tx pays several bills. Format exactly
                # at the AP commodity's decimal count (no to_double).
                pay_amt = format_amount_for_commodity(
                    s.GetAmount().abs(), s.GetAccount().GetCommodity())
                bill_lines.append('\tpayment:')
                bill_lines.append(f'\t\tdate: {pay_date}')
                bill_lines.append(f'\t\tamount: {pay_amt}')
                bill_lines.append(f'\t\tbank_account: "{bank_name}"')
                bill_lines.append(f'\t\tmemo: "{pay_memo}"')
                had_payment = True
        if not had_payment:
            bill_lines.append('\tpayment: none')

    subtotal = sum((e[1] for e in entries_data), Fraction(0))
    tax_total = sum((e[2] for e in entries_data), Fraction(0))
    bill_lines.append(f'\tbill_subtotal: {_fmt_money(subtotal, unit)}')
    bill_lines.append(f'\tbill_tax_total: {_fmt_money(tax_total, unit)}')
    bill_lines.append(f'\tbill_total: {_fmt_money(subtotal + tax_total, unit)}')

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
