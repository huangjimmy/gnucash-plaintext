#!/usr/bin/env python
"""
Service for rendering GnuCash invoices to PDF.
"""
import ctypes
import xml.etree.ElementTree as ET

import gnucash.gnucash_core_c as gc
from gnucash import Split

from infrastructure.gnucash.engine import load_gnc_engine


def read_book_company_info(file_path):
    import gzip as _gz
    import xml.etree.ElementTree

    slot_key = '{http://www.gnucash.org/XML/slot}key'
    slot_val = '{http://www.gnucash.org/XML/slot}value'
    book_slots = '{http://www.gnucash.org/XML/book}slots'
    gnc_book = '{http://www.gnucash.org/XML/gnc}book'

    try:
        with _gz.open(file_path, 'rb') as f:
            xml_root = xml.etree.ElementTree.parse(f).getroot()
    except Exception:
        xml_root = xml.etree.ElementTree.parse(file_path).getroot()

    def _frame_val(parent, key):
        if parent is None:
            return None
        candidates = parent.findall('slot')
        if not candidates:
            candidates = [c for c in parent if c.tag.endswith('}slot') or c.tag == 'slot']
        for slot in candidates:
            k = slot.find(slot_key)
            if k is not None and k.text == key:
                return slot.find(slot_val)
        return None

    def _str_val(parent, key):
        v = _frame_val(parent, key)
        return (v.text or '').strip() if v is not None else ''

    book_el = xml_root.find('.//' + gnc_book)
    book_slots = book_el.find(book_slots) if book_el is not None else None
    options_el = _frame_val(book_slots, 'options')
    biz_el = _frame_val(options_el, 'Business')

    result = {
        'name': _str_val(biz_el, 'Company Name'),
        'id': _str_val(biz_el, 'Company ID'),
        'phone': _str_val(biz_el, 'Company Phone Number'),
        'email': _str_val(biz_el, 'Company Email Address'),
        'url': _str_val(biz_el, 'Company Website URL'),
    }
    addr_raw = _str_val(biz_el, 'Company Address')
    addr_lines = addr_raw.split('\n') if addr_raw else []
    for i, k in enumerate(['addr1', 'addr2', 'addr3', 'addr4']):
        result[k] = addr_lines[i].strip() if i < len(addr_lines) else ''

    return result


def _read_tax_label(lib, ptr):
    taxable = bool(lib.gncEntryGetInvTaxable(ptr))
    if not taxable:
        return 'Exempt', 'exempt'

    tt_ptr = lib.gncEntryGetInvTaxTable(ptr)
    if not tt_ptr:
        return 'Taxable', 'single'

    tt_name_b = lib.gncTaxTableGetName(tt_ptr)
    tt_name = tt_name_b.decode('utf-8') if tt_name_b else 'Taxable'

    glist_ptr = lib.gncTaxTableGetEntries(tt_ptr)
    rate_parts = []
    while glist_ptr:
        buf = (ctypes.c_void_p * 3).from_address(glist_ptr)
        tte_ptr = buf[0]
        glist_ptr = buf[1]
        if not tte_ptr:
            continue
        acct_ptr = lib.gncTaxTableEntryGetAccount(tte_ptr)
        amt_c = lib.gncTaxTableEntryGetAmount(tte_ptr)
        rate = amt_c.num / amt_c.denom if amt_c.denom else 0.0
        name_b = lib.xaccAccountGetName(acct_ptr) if acct_ptr else None
        name = name_b.decode('utf-8') if name_b else '?'
        rate_str = f"{rate:g}%"
        label = name if rate_str in name else f"{name} {rate_str}"
        rate_parts.append(label)

    rate_parts.reverse()
    if not rate_parts:
        return tt_name, 'single'

    label = ' + '.join(rate_parts)
    ttype = 'combined' if len(rate_parts) > 1 else 'single'
    return label, ttype


def invoice_to_xml(inv, book, company_info=None):
    lib = load_gnc_engine()

    inv_id = inv.GetID()
    is_paid = gc.gncInvoiceIsPaid(inv.instance)
    currency = inv.GetCurrency().get_mnemonic()
    date_opened = inv.GetDateOpened().strftime("%Y-%m-%d")
    date_due = inv.GetDateDue()
    date_due_s = date_due.strftime("%Y-%m-%d") if date_due else ''
    notes = inv.GetNotes() or ''
    billing_id = inv.GetBillingID() or ''

    cust = None
    try:
        owner = inv.GetOwner()
        cust = owner.GetCustomer()
    except Exception:
        pass
    if cust is None:
        raise ValueError("Could not determine customer for invoice")

    addr = cust.GetAddr()
    cust_name = cust.GetName()
    addr1, addr2 = addr.GetAddr1(), addr.GetAddr2()
    addr3, addr4 = addr.GetAddr3(), addr.GetAddr4()
    email = addr.GetEmail()

    root = ET.Element('invoice',
                      status='paid' if is_paid else 'unpaid',
                      currency=currency)
    ET.SubElement(root, 'id').text = inv_id
    ET.SubElement(root, 'date').text = date_opened
    ET.SubElement(root, 'due-date').text = date_due_s
    ET.SubElement(root, 'billing-id').text = billing_id
    ET.SubElement(root, 'notes').text = notes

    c_el = ET.SubElement(root, 'customer')
    ET.SubElement(c_el, 'name').text = cust_name
    ET.SubElement(c_el, 'addr1').text = addr1 or ''
    ET.SubElement(c_el, 'addr2').text = addr2 or ''
    ET.SubElement(c_el, 'addr3').text = addr3 or ''
    ET.SubElement(c_el, 'addr4').text = addr4 or ''
    ET.SubElement(c_el, 'email').text = email or ''

    co = company_info or {}
    co_el = ET.SubElement(root, 'company')
    ET.SubElement(co_el, 'name').text = co.get('name', '')
    ET.SubElement(co_el, 'id').text = co.get('id', '')
    ET.SubElement(co_el, 'addr1').text = co.get('addr1', '')
    ET.SubElement(co_el, 'addr2').text = co.get('addr2', '')
    ET.SubElement(co_el, 'addr3').text = co.get('addr3', '')
    ET.SubElement(co_el, 'addr4').text = co.get('addr4', '')
    ET.SubElement(co_el, 'phone').text = co.get('phone', '')
    ET.SubElement(co_el, 'email').text = co.get('email', '')
    ET.SubElement(co_el, 'url').text = co.get('url', '')

    entries_el = ET.SubElement(root, 'entries')
    for raw_entry in inv.GetEntries():
        ptr = int(raw_entry.instance)
        desc = (lib.gncEntryGetDescription(ptr) or b'').decode('utf-8')
        action = (lib.gncEntryGetAction(ptr) or b'').decode('utf-8')
        qty_c = lib.gncEntryGetQuantity(ptr)
        price_c = lib.gncEntryGetInvPrice(ptr)
        qty = qty_c.num / qty_c.denom if qty_c.denom else 0.0
        price = price_c.num / price_c.denom if price_c.denom else 0.0

        tax_label, tax_type = _read_tax_label(lib, ptr)

        e_el = ET.SubElement(entries_el, 'entry')
        ET.SubElement(e_el, 'description').text = desc
        ET.SubElement(e_el, 'action').text = action
        ET.SubElement(e_el, 'quantity').text = f"{qty:.4f}".rstrip('0').rstrip('.')
        ET.SubElement(e_el, 'unit-price').text = f"{price:.2f}"
        ET.SubElement(e_el, 'amount').text = f"{qty * price:.2f}"
        ET.SubElement(e_el, 'tax-label', type=tax_type).text = tax_label

    posting_txn = inv.GetPostedTxn()
    subtotal_total = 0.0
    tax_lines_el = ET.SubElement(root, 'tax-lines')
    for i in range(posting_txn.CountSplits()):
        s = posting_txn.GetSplit(i)
        acct = s.GetAccount()
        atype = gc.xaccAccountGetType(acct.instance)
        amt = s.GetAmount().to_double()
        if atype == gc.ACCT_TYPE_INCOME:
            subtotal_total += abs(amt)
        elif atype in (gc.ACCT_TYPE_LIABILITY, gc.ACCT_TYPE_PAYABLE):
            tl = ET.SubElement(tax_lines_el, 'tax-line')
            ET.SubElement(tl, 'name').text = acct.GetName()
            ET.SubElement(tl, 'amount').text = f"{abs(amt):.2f}"

    grand_total = subtotal_total + sum(
        float(tl.find('amount').text) for tl in tax_lines_el
    )
    ET.SubElement(root, 'subtotal').text = f"{subtotal_total:.2f}"
    ET.SubElement(root, 'total').text = f"{grand_total:.2f}"

    lot = inv.GetPostedLot()
    payments_el = ET.SubElement(root, 'payments')
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
        pay_amt = abs(s.GetAmount().to_double())
        p_el = ET.SubElement(payments_el, 'payment')
        ET.SubElement(p_el, 'date').text = pay_date
        ET.SubElement(p_el, 'memo').text = pay_memo
        ET.SubElement(p_el, 'num').text = pay_num
        ET.SubElement(p_el, 'amount').text = f"{pay_amt:.2f}"

    remaining = lot.get_balance().to_double()
    ET.SubElement(root, 'amount-remaining').text = f"{abs(remaining):.2f}"

    return ET.ElementTree(root)


def render_to_pdf(invoice, book, xslt_path, pdf_path, company_info=None):
    import weasyprint
    from lxml import etree as lxml_etree

    xml_tree = invoice_to_xml(invoice, book, company_info=company_info)

    # In-memory transformation
    xml_str = ET.tostring(xml_tree.getroot(), encoding='unicode')
    xml_doc = lxml_etree.fromstring(xml_str)
    xslt_doc = lxml_etree.parse(xslt_path)
    transform = lxml_etree.XSLT(xslt_doc)
    html_doc = transform(xml_doc)

    weasyprint.HTML(string=str(html_doc)).write_pdf(pdf_path)
