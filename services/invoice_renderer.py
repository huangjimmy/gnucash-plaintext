#!/usr/bin/env python
"""
Service for rendering GnuCash invoices to PDF.
"""
import xml.etree.ElementTree as ET

import gnucash.gnucash_core_c as gc
from gnucash import Split

from infrastructure.gnucash.engine import iterate_glist, load_gnc_engine, safe_ctypes_string
from infrastructure.gnucash.kvp import get_custom_metadata


def read_book_company_info(file_path):
    import gzip as _gz
    import xml.etree.ElementTree

    slot_key = '{http://www.gnucash.org/XML/slot}key'
    slot_val = '{http://www.gnucash.org/XML/slot}value'
    book_slots = '{http://www.gnucash.org/XML/book}slots'
    gnc_book = '{http://www.gnucash.org/XML/gnc}book'

    _not_gzip = getattr(_gz, 'BadGzipFile', OSError)
    try:
        with _gz.open(file_path, 'rb') as f:
            xml_root = xml.etree.ElementTree.parse(f).getroot()
    except (_not_gzip, EOFError):
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
        'contact': _str_val(biz_el, 'Company Contact Person'),
        'id': _str_val(biz_el, 'Company ID'),
        # Q-028: GnuCash has no GST/PST field — these are custom Business slots
        # this tool adds. `pst` may carry several numbers separated by ';'.
        'gst': _str_val(biz_el, 'Company GST Number'),
        'pst': _str_val(biz_el, 'Company PST Number'),
        'phone': _str_val(biz_el, 'Company Phone Number'),
        'fax': _str_val(biz_el, 'Company Fax Number'),
        'email': _str_val(biz_el, 'Company Email Address'),
        'url': _str_val(biz_el, 'Company Website URL'),
    }
    addr_raw = _str_val(biz_el, 'Company Address')
    addr_lines = addr_raw.split('\n') if addr_raw else []
    for i, k in enumerate(['addr1', 'addr2', 'addr3', 'addr4']):
        result[k] = addr_lines[i].strip() if i < len(addr_lines) else ''

    return result


def split_pst_numbers(value) -> list:
    """Q-028: split a `pst` company value into individual registration
    numbers. A filer may hold more than one provincial PST/QST number, so
    several are stored in the single `Company PST Number` slot separated by
    ';' and rendered as separate rows. `gst` is always a single value."""
    if not value:
        return []
    return [p.strip() for p in str(value).split(';') if p.strip()]


def build_company_xml(root, company_info):
    """Build the `<company>` seller block shared by invoice and bill XML.

    Emits GnuCash's native Business fields plus the custom GST/PST
    registration numbers (Q-028). GST is one `<gst>`; PST is one `<pst>`
    element per number so the stylesheet can render multiple provincial
    registrations as separate rows."""
    co = company_info or {}
    co_el = ET.SubElement(root, 'company')
    ET.SubElement(co_el, 'name').text = co.get('name', '')
    ET.SubElement(co_el, 'contact').text = co.get('contact', '')
    ET.SubElement(co_el, 'id').text = co.get('id', '')
    ET.SubElement(co_el, 'gst').text = co.get('gst', '')
    for pst in split_pst_numbers(co.get('pst', '')):
        ET.SubElement(co_el, 'pst').text = pst
    ET.SubElement(co_el, 'addr1').text = co.get('addr1', '')
    ET.SubElement(co_el, 'addr2').text = co.get('addr2', '')
    ET.SubElement(co_el, 'addr3').text = co.get('addr3', '')
    ET.SubElement(co_el, 'addr4').text = co.get('addr4', '')
    ET.SubElement(co_el, 'phone').text = co.get('phone', '')
    ET.SubElement(co_el, 'fax').text = co.get('fax', '')
    ET.SubElement(co_el, 'email').text = co.get('email', '')
    ET.SubElement(co_el, 'url').text = co.get('url', '')
    return co_el


def _read_tax_label(lib, ptr):
    taxable = bool(lib.gncEntryGetInvTaxable(ptr))
    if not taxable:
        return 'Exempt', 'exempt'

    tt_ptr = lib.gncEntryGetInvTaxTable(ptr)
    if not tt_ptr:
        return 'Taxable', 'single'

    tt_name = safe_ctypes_string(lib.gncTaxTableGetName, tt_ptr, default='Taxable')

    # Process tax table entries using iterate_glist
    glist_ptr = lib.gncTaxTableGetEntries(tt_ptr)

    def process_tax_table_entry(lib, tte_ptr):
        """Process single tax table entry pointer."""
        acct_ptr = lib.gncTaxTableEntryGetAccount(tte_ptr)
        amt_c = lib.gncTaxTableEntryGetAmount(tte_ptr)
        rate = amt_c.num / amt_c.denom if amt_c.denom else 0.0
        name = safe_ctypes_string(lib.xaccAccountGetName, acct_ptr, default='?')
        rate_str = f"{rate:g}%"
        # If rate already appears in account name (e.g., "GST 5%"), use just the name
        return name if rate_str in name else f"{name} {rate_str}"

    rate_parts = iterate_glist(lib, glist_ptr, process_tax_table_entry)
    rate_parts.reverse()  # GnuCash prepends entries

    if not rate_parts:
        return tt_name, 'single'

    label = ' + '.join(rate_parts)
    ttype = 'combined' if len(rate_parts) > 1 else 'single'
    return label, ttype


def invoice_to_xml(inv, book, company_info=None):
    lib = load_gnc_engine()

    inv_id = inv.GetID()
    # Q-012: detect unposted state up front. The renderer's tax/payment
    # blocks below all assume a posted invoice (posting_txn + posted_lot
    # both non-None); for unposted we render a "draft" preview instead.
    posting_txn = inv.GetPostedTxn()
    is_draft = posting_txn is None
    is_paid = False if is_draft else gc.gncInvoiceIsPaid(inv.instance)

    # Q-018: a `cash_basis: true` KVP on an UNPOSTED invoice means
    # "this is a real bill awaiting cash, not a work-in-progress draft."
    # In a cash-basis workflow, the invoice posts only when cash arrives;
    # before that, the customer still needs a payable document. Render
    # as UNPAID (not DRAFT) for the badge, but keep the same draft-only
    # layout (no tax breakdown / no payment history — those don't exist
    # until posting). Also accept an optional KVP `due_date` slot
    # (string YYYY-MM-DD) for the due date — the GnuCash `posted:`
    # block is absent so there's no posted.due to pull from.
    inv_kvp = get_custom_metadata(inv) or {}
    cash_basis_marker = str(inv_kvp.get('cash_basis', '')).strip().lower() == 'true'
    currency = inv.GetCurrency().get_mnemonic()
    date_opened = inv.GetDateOpened().strftime("%Y-%m-%d")
    date_due = inv.GetDateDue()
    date_due_s = date_due.strftime("%Y-%m-%d") if date_due else ''
    # Q-018: when posted.due is absent (unposted cash-basis invoice),
    # fall back to the `due_date` KVP slot if the user provided one.
    if not date_due_s and is_draft and inv_kvp.get('due_date'):
        date_due_s = str(inv_kvp['due_date']).strip()
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

    if is_draft and not cash_basis_marker:
        status = 'draft'
    elif is_paid:
        status = 'paid'
    else:
        # Posted-but-unpaid (accrual), or unposted+cash_basis (Q-018):
        # both render with the same UNPAID badge.
        status = 'unpaid'
    root = ET.Element('invoice', status=status, currency=currency)
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

    build_company_xml(root, company_info)

    entries_el = ET.SubElement(root, 'entries')
    # Q-019: drafts (cash-basis or accrual) now compute tax from each
    # entry's tax_table via compute_entry_informational. The net amount
    # (qty × price adjusted for tax_included) is the per-entry subtotal,
    # and per-tax-account dollars are aggregated into tax_account_totals
    # for the <tax-lines> block below.
    entries_subtotal = 0.0
    tax_account_totals = {}
    for raw_entry in inv.GetEntries():
        ptr = int(raw_entry.instance)
        desc = safe_ctypes_string(lib.gncEntryGetDescription, ptr)
        action = safe_ctypes_string(lib.gncEntryGetAction, ptr)
        qty_c = lib.gncEntryGetQuantity(ptr)
        price_c = lib.gncEntryGetInvPrice(ptr)
        qty = qty_c.num / qty_c.denom if qty_c.denom else 0.0
        price = price_c.num / price_c.denom if price_c.denom else 0.0
        net_amount, _entry_tax, breakdown = compute_entry_informational(
            lib, ptr,
        )
        entries_subtotal += net_amount
        for bd_acct_name, _bd_rate, bd_amount in breakdown:
            tax_account_totals[bd_acct_name] = (
                tax_account_totals.get(bd_acct_name, 0.0) + bd_amount
            )

        tax_label, tax_type = _read_tax_label(lib, ptr)

        e_el = ET.SubElement(entries_el, 'entry')
        ET.SubElement(e_el, 'description').text = desc
        ET.SubElement(e_el, 'action').text = action
        ET.SubElement(e_el, 'quantity').text = f"{qty:.4f}".rstrip('0').rstrip('.')
        ET.SubElement(e_el, 'unit-price').text = f"{price:.2f}"
        ET.SubElement(e_el, 'amount').text = f"{net_amount:.2f}"
        ET.SubElement(e_el, 'tax-label', type=tax_type).text = tax_label

    tax_lines_el = ET.SubElement(root, 'tax-lines')
    payments_el = ET.SubElement(root, 'payments')

    if is_draft:
        # Q-019: render full tax breakdown for unposted invoices (cash-basis
        # or plain draft). GnuCash only materialises tax splits on the
        # posting transaction; before that, recompute the same numbers
        # from each entry's tax_table. The <draft-tax-notice/> element
        # tells the XSLT to mark these figures as provisional. Payment
        # history and amount-remaining still require a posted AR lot, so
        # they stay omitted on the draft path.
        for acct_name, dollars in tax_account_totals.items():
            tl = ET.SubElement(tax_lines_el, 'tax-line')
            # The posted path uses acct.GetName() (leaf only);
            # compute_entry_informational produces colon-joined fullnames
            # ("Liabilities:Tax:GST"). Take the leaf so a draft tax-line
            # row reads identically to the same row on a posted invoice.
            ET.SubElement(tl, 'name').text = acct_name.rsplit(':', 1)[-1]
            ET.SubElement(tl, 'amount').text = f"{dollars:.2f}"
        grand_total = entries_subtotal + sum(tax_account_totals.values())
        ET.SubElement(root, 'subtotal').text = f"{entries_subtotal:.2f}"
        ET.SubElement(root, 'total').text = f"{grand_total:.2f}"
        ET.SubElement(root, 'draft-tax-notice')
        return ET.ElementTree(root)

    # Posted: derive tax lines + subtotal from the posting transaction's splits.
    subtotal_total = 0.0
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


def render_to_html(invoice, book, xslt_path, company_info=None) -> str:
    """Apply the XSLT to the invoice's XML and return the resulting HTML.

    Q-011: split out from render_to_pdf so callers (and tests) can
    inspect the XSLT output directly without going through weasyprint.
    Useful for verifying that a custom `--template <path>` was actually
    threaded through to the transform.
    """
    from lxml import etree as lxml_etree

    xml_tree = invoice_to_xml(invoice, book, company_info=company_info)
    xml_str = ET.tostring(xml_tree.getroot(), encoding='unicode')
    xml_doc = lxml_etree.fromstring(xml_str)
    xslt_doc = lxml_etree.parse(xslt_path)
    transform = lxml_etree.XSLT(xslt_doc)
    return str(transform(xml_doc))


def render_to_pdf(invoice, book, xslt_path, pdf_path, company_info=None):
    import weasyprint

    html = render_to_html(invoice, book, xslt_path, company_info=company_info)
    weasyprint.HTML(string=html).write_pdf(pdf_path)


# ── Q-017: plaintext render ────────────────────────────────────────────────
#
# Same canonical format as `export --include-business-objects`, with
# **informational** fields added (entry_amount, entry_tax,
# entry_tax_breakdown, invoice_subtotal, invoice_tax_total, invoice_total).
# The importer recomputes the informational fields from the source-of-truth
# fields (quantity, price, tax_table, tax_included) on re-import and errors
# loudly on mismatch — see the format-spec section in
# docs/issues/Q-017-print-invoice-plaintext-format-and-multi-invoice.md.


def _fmt_money(value: float) -> str:
    """Format an amount with 2 decimals, matching the importer's tolerance."""
    return f'{value:.2f}'


def _fmt_rate(rate_decimal: float) -> str:
    """Format a tax rate as it appears in the plaintext: percentage with the
    smallest representation (e.g. `5.0`, `9.975`)."""
    s = f'{rate_decimal * 100:g}'
    if '.' not in s:
        s += '.0'
    return s


def _ctypes_account_full_name(lib, acct_ptr) -> str:
    """Walk the parent chain via ctypes to produce 'Liabilities:Tax:GST'.
    Same approach as `_export_tax_tables` in use_cases/export_business_objects
    — required because acct_ptr comes from `gncTaxTableEntryGetAccount`,
    a ctypes function, and SWIG's `Account(instance=ptr)` doesn't accept
    raw pointers safely (Ubuntu const-type bug — see CLAUDE.md)."""
    parts = []
    ptr = acct_ptr
    while ptr:
        name = safe_ctypes_string(lib.xaccAccountGetName, ptr)
        if name:
            parts.append(name)
        parent = lib.gnc_account_get_parent(ptr)
        if not parent:
            break
        grandparent = lib.gnc_account_get_parent(parent)
        if not grandparent:
            break  # parent is the root; stop before climbing into it
        ptr = parent
    parts.reverse()
    return ':'.join(parts)


def _tax_table_entries(lib, tt_ptr):
    """Return [(account_name, rate_as_decimal)] for one tax-table pointer,
    in declaration order (GST before PST, etc.)."""

    def _one(_lib, tte_ptr):
        acct_ptr = _lib.gncTaxTableEntryGetAccount(tte_ptr)
        amt_c = _lib.gncTaxTableEntryGetAmount(tte_ptr)
        rate_pct = amt_c.num / amt_c.denom if amt_c.denom else 0.0
        # GnuCash stores tax-table amounts as percentages (e.g. 13.0
        # for HST). Internally we want the decimal fraction (0.13) so
        # `entry_amount × rate` gives the tax dollars directly.
        rate = rate_pct / 100.0
        acct_name = _ctypes_account_full_name(_lib, acct_ptr) if acct_ptr else '?'
        return (acct_name, rate)

    entries_ptr = lib.gncTaxTableGetEntries(tt_ptr)
    entries = iterate_glist(lib, entries_ptr, _one)
    entries.reverse()  # GnuCash prepends; we want declaration order.
    return entries


def compute_entry_informational(lib, entry_ptr):
    """For one invoice entry, return (entry_amount, entry_tax,
    breakdown) where:
      * entry_amount = qty × price, adjusted for tax_included (the net
        amount; informational invoice_subtotal sums these).
      * entry_tax    = total tax dollars contributed by this entry.
      * breakdown    = [(account_name, rate_decimal, amount), ...] —
        one tuple per tax-table entry, or [] when the entry isn't
        taxable (or has no tax_table).

    `tax_included` semantics: when true, the displayed price already
    includes tax; the net amount is `gross / (1 + total_rate)` and the
    tax dollars are `gross − net`. When false, the price is the net
    amount and tax is added on top.
    """
    qty_c = lib.gncEntryGetQuantity(entry_ptr)
    pri_c = lib.gncEntryGetInvPrice(entry_ptr)
    qty = qty_c.num / qty_c.denom if qty_c.denom else 0.0
    price = pri_c.num / pri_c.denom if pri_c.denom else 0.0
    gross_or_net = qty * price

    taxable = bool(lib.gncEntryGetInvTaxable(entry_ptr))
    tax_included = bool(lib.gncEntryGetInvTaxIncluded(entry_ptr))
    tt_ptr = lib.gncEntryGetInvTaxTable(entry_ptr) if taxable else None

    if not taxable or not tt_ptr:
        return (gross_or_net, 0.0, [])

    tt_entries = _tax_table_entries(lib, tt_ptr)
    total_rate = sum(rate for _, rate in tt_entries)

    net = gross_or_net / (1.0 + total_rate) if tax_included else gross_or_net

    breakdown = [(acct_name, rate, net * rate) for acct_name, rate in tt_entries]
    entry_tax = sum(amount for _, _, amount in breakdown)
    return (net, entry_tax, breakdown)


def validate_entry_informational(lib, entry_ptr, declared, breakdown_declared,
                                 entry_label):
    """Q-017: recompute entry_amount/entry_tax/breakdown from the entry's
    source-of-truth fields (qty/price/tax_table/tax_included) and verify
    each declared informational field matches.

    Arguments:
        lib                  — engine library (load_gnc_engine())
        entry_ptr            — int pointer to the gnc Entry (post-commit)
        declared             — dict with optional keys 'entry_amount' and
                               'entry_tax' (string values from plaintext);
                               either or both may be absent.
        breakdown_declared   — list of dicts [{account, rate, amount}]; may
                               be empty if no `breakdown:` blocks were
                               present on this entry.
        entry_label          — human-readable identifier for error messages
                               (e.g. "invoice INV-Q17 entry #1").

    Raises ValueError with a clear message naming the field and the two
    numbers when any declared informational value disagrees with the
    recomputed value by more than 0.01.
    """
    computed_amount, computed_tax, computed_breakdown = (
        compute_entry_informational(lib, entry_ptr)
    )

    def _close(a, b, tol=0.01):
        return abs(float(a) - float(b)) <= tol

    if 'entry_amount' in declared:
        declared_amount = float(declared['entry_amount'])
        if not _close(declared_amount, computed_amount):
            raise ValueError(
                f'{entry_label}: declared entry_amount {declared_amount:.2f} '
                f'does not match recomputed {computed_amount:.2f} '
                f'(from quantity × price, adjusted for tax_included)'
            )

    if 'entry_tax' in declared:
        declared_tax = float(declared['entry_tax'])
        if not _close(declared_tax, computed_tax):
            raise ValueError(
                f'{entry_label}: declared entry_tax {declared_tax:.2f} does '
                f'not match recomputed {computed_tax:.2f} (from tax_table '
                f'entries × entry_amount)'
            )

    # Breakdown validation: each declared breakdown block must match one
    # of the computed breakdown rows by account name (the canonical key),
    # and the declared rate + amount must match within tolerance. Counts
    # must agree too (no missing or extra blocks).
    if breakdown_declared:
        if len(breakdown_declared) != len(computed_breakdown):
            raise ValueError(
                f'{entry_label}: declared breakdown has '
                f'{len(breakdown_declared)} block(s) but the tax_table '
                f'has {len(computed_breakdown)} entry/entries'
            )
        computed_by_acct = {acct: (rate, amt)
                            for acct, rate, amt in computed_breakdown}
        for decl in breakdown_declared:
            acct = decl.get('account', '').strip().strip('"')
            if acct not in computed_by_acct:
                raise ValueError(
                    f'{entry_label}: breakdown account {acct!r} is not on '
                    f'the entry\'s tax_table (table has '
                    f'{sorted(computed_by_acct)})'
                )
            comp_rate, comp_amount = computed_by_acct[acct]
            try:
                decl_rate = float(decl['rate'])
                decl_amount = float(decl['amount'])
            except (KeyError, ValueError) as exc:
                raise ValueError(
                    f'{entry_label}: breakdown for {acct!r} must declare '
                    f'numeric rate and amount; got {decl!r}'
                ) from exc
            # `rate` is stored as decimal fraction internally (0.13) but
            # serialised as percent (13.0); accept either form.
            if not (_close(decl_rate, comp_rate * 100, tol=0.001)
                    or _close(decl_rate, comp_rate, tol=0.00001)):
                raise ValueError(
                    f'{entry_label}: breakdown for {acct!r} declares '
                    f'rate {decl_rate} but tax_table stores '
                    f'{comp_rate * 100:.4f}%'
                )
            if not _close(decl_amount, comp_amount):
                raise ValueError(
                    f'{entry_label}: breakdown for {acct!r} declares '
                    f'amount {decl_amount:.2f} but recomputed value is '
                    f'{comp_amount:.2f} (entry_amount × rate)'
                )


def validate_invoice_informational(declared, computed_subtotal,
                                   computed_tax, invoice_label):
    """Q-017: invoice-level totals. `declared` is a dict with optional
    keys invoice_subtotal/invoice_tax_total/invoice_total (or the bill_*
    analogues — caller passes whichever set). Raises ValueError on any
    mismatch."""
    def _close(a, b, tol=0.01):
        return abs(float(a) - float(b)) <= tol

    pairs = [
        ('invoice_subtotal', computed_subtotal),
        ('bill_subtotal',    computed_subtotal),
        ('invoice_tax_total', computed_tax),
        ('bill_tax_total',    computed_tax),
        ('invoice_total', computed_subtotal + computed_tax),
        ('bill_total',    computed_subtotal + computed_tax),
    ]
    for field, computed in pairs:
        if field in declared:
            try:
                decl = float(declared[field])
            except ValueError as exc:
                raise ValueError(
                    f'{invoice_label}: {field} must be a number, got '
                    f'{declared[field]!r}'
                ) from exc
            if not _close(decl, computed):
                raise ValueError(
                    f'{invoice_label}: declared {field} {decl:.2f} does '
                    f'not match recomputed {computed:.2f} (sum of entries)'
                )


def _render_taxtable_block(lib, tt_ptr) -> str:
    """Render one tax-table object as plaintext (same syntax `export`
    emits). Used to make the per-invoice plaintext self-contained for
    the recipient — they get the tax rates inline."""

    tt_name = safe_ctypes_string(lib.gncTaxTableGetName, tt_ptr)
    lines = [f'taxtable "{tt_name}"']
    for acct_name, rate in _tax_table_entries(lib, tt_ptr):
        lines.append('\tentry:')
        lines.append(f'\t\taccount: "{acct_name}"')
        lines.append(f'\t\trate: {_fmt_rate(rate)}%')
        lines.append('\t\ttype: PERCENT')
    return '\n'.join(lines)


def _render_customer_block(cust) -> str:
    """Minimal customer block — id, name, currency. The renderer doesn't
    emit address/email because the recipient already has those; the block
    exists to satisfy the importer's `customer_id:` lookup if someone
    re-imports the rendered file for validation."""
    return (
        f'customer "{cust.GetID()}"\n'
        f'\tname: "{cust.GetName()}"\n'
        f'\tcurrency: {cust.GetCurrency().get_mnemonic()}'
    )


def _render_seller_header(company_info) -> str:
    """Q-019: emit a `# Issued by: ...` comment header so the recipient
    of a rendered plaintext invoice / bill knows who issued it. Uses
    `#` comment syntax so the line is dropped on re-import (we don't
    want seller info to land as KVPs on the recipient's invoice).

    Returns an empty string when company_info is missing or has no
    company name — there's nothing useful to render in that case."""
    if not company_info:
        return ''
    name = (company_info.get('name') or '').strip()
    if not name:
        return ''
    parts = [f'Issued by: {name}']
    contact = (company_info.get('contact') or '').strip()
    if contact:
        parts.append(f'Attn: {contact}')
    company_id = (company_info.get('id') or '').strip()
    if company_id:
        # Label matches GnuCash's own slot name ("Company ID") rather
        # than any one jurisdiction's tax-registration scheme. Users
        # put a CRA business number, US EIN, UK VAT, HK BR, JP
        # corporate number, etc. here; the rendered output stays
        # neutral so the slot value reads correctly regardless.
        parts.append(f'Company ID: {company_id}')
    # Q-028: dedicated GST/PST registration numbers, labelled so the
    # recipient can tell them apart from the generic Company ID. GST is a
    # single value; PST may hold several (one rendered segment each).
    gst = (company_info.get('gst') or '').strip()
    if gst:
        parts.append(f'GST: {gst}')
    for pst in split_pst_numbers(company_info.get('pst')):
        parts.append(f'PST: {pst}')
    addr_lines = [
        (company_info.get(k) or '').strip()
        for k in ('addr1', 'addr2', 'addr3', 'addr4')
    ]
    addr_joined = ', '.join(line for line in addr_lines if line)
    if addr_joined:
        parts.append(addr_joined)
    for key in ('phone', 'fax', 'email', 'url'):
        val = (company_info.get(key) or '').strip()
        if val:
            label = {'fax': 'Fax: '}.get(key, '')
            parts.append(f'{label}{val}')
    return '# ' + ' | '.join(parts)


def render_to_plaintext(invoice, book, company_info=None) -> str:
    """Render one invoice as canonical plaintext, populated with the
    Q-017 informational fields (per-entry amount + tax breakdown, plus
    invoice subtotal/tax_total/total). Output is self-contained for the
    invoice itself: taxtable definitions for every referenced table, the
    customer header, and the invoice block. Accounts must already exist
    on the importing side."""
    lib = load_gnc_engine()

    inv_id = invoice.GetID()
    cust = invoice.GetOwner().GetCustomer()
    if cust is None:
        raise ValueError(f'invoice {inv_id!r} has no customer owner')

    posting_txn = invoice.GetPostedTxn()
    is_draft = posting_txn is None
    currency = invoice.GetCurrency().get_mnemonic()
    date_opened = invoice.GetDateOpened().strftime('%Y-%m-%d')

    # Collect referenced tax tables (de-dup by pointer).
    seen_tt = {}
    entries_data = []  # [(raw_entry, entry_amount, entry_tax, breakdown)]
    for raw_entry in invoice.GetEntries():
        ent_ptr = int(raw_entry.instance)
        entry_amount, entry_tax, breakdown = compute_entry_informational(
            lib, ent_ptr
        )
        entries_data.append((raw_entry, entry_amount, entry_tax, breakdown))
        tt_ptr = lib.gncEntryGetInvTaxTable(ent_ptr)
        if tt_ptr and int(tt_ptr) not in seen_tt:
            seen_tt[int(tt_ptr)] = tt_ptr

    blocks = []
    for tt_ptr in seen_tt.values():
        blocks.append(_render_taxtable_block(lib, tt_ptr))

    blocks.append(_render_customer_block(cust))

    # Invoice block
    inv_lines = [
        f'invoice "{inv_id}"',
        f'\tcustomer_id: "{cust.GetID()}"',
        f'\tcurrency: {currency}',
        f'\tdate_opened: {date_opened}',
    ]
    if invoice.GetBillingID():
        inv_lines.append(f'\tbilling_id: "{invoice.GetBillingID()}"')
    if invoice.GetNotes():
        inv_lines.append(f'\tnotes: "{invoice.GetNotes()}"')

    # Per-entry blocks with informational fields
    from infrastructure.gnucash.utils import (
        format_amount_for_commodity,
        get_account_full_name,
    )

    for raw_entry, entry_amount, entry_tax, breakdown in entries_data:
        ent_ptr = int(raw_entry.instance)
        desc = safe_ctypes_string(lib.gncEntryGetDescription, ent_ptr)
        action = safe_ctypes_string(lib.gncEntryGetAction, ent_ptr)
        qty_c = lib.gncEntryGetQuantity(ent_ptr)
        pri_c = lib.gncEntryGetInvPrice(ent_ptr)
        qty = qty_c.num / qty_c.denom if qty_c.denom else 0.0
        price = pri_c.num / pri_c.denom if pri_c.denom else 0.0
        taxable = bool(lib.gncEntryGetInvTaxable(ent_ptr))
        tax_included = bool(lib.gncEntryGetInvTaxIncluded(ent_ptr))
        acct_name = get_account_full_name(raw_entry.GetInvAccount())
        date_str = raw_entry.GetDate().strftime('%Y-%m-%d')

        inv_lines.append('\tentry:')
        inv_lines.append(f'\t\tdate: {date_str}')
        inv_lines.append(f'\t\tdescription: "{desc}"')
        inv_lines.append(f'\t\taction: "{action}"')
        inv_lines.append(f'\t\taccount: "{acct_name}"')
        inv_lines.append(f'\t\tquantity: {qty:g}')
        inv_lines.append(f'\t\tprice: {price:g}')
        inv_lines.append(f'\t\ttaxable: {"true" if taxable else "false"}')
        inv_lines.append(f'\t\ttax_included: {"true" if tax_included else "false"}')

        tt_ptr = lib.gncEntryGetInvTaxTable(ent_ptr)
        if tt_ptr:
            tt_name = safe_ctypes_string(lib.gncTaxTableGetName, tt_ptr)
            if tt_name:
                inv_lines.append(f'\t\ttax_table: "{tt_name}"')

        # Q-017 informational fields. `breakdown:` is a nested block (one
        # per tax-table entry); matches the existing taxtable entry-block
        # convention so the parser can use the same indented-children path.
        # Q-019: emitted for drafts too — compute_entry_informational works
        # off the entry's tax_table, which exists pre-posting. The leading
        # `# Tax figures are provisional` comment on the invoice block
        # (added below) tells the recipient these numbers will be
        # recomputed at post time.
        inv_lines.append(f'\t\tentry_amount: {_fmt_money(entry_amount)}')
        inv_lines.append(f'\t\tentry_tax: {_fmt_money(entry_tax)}')
        for bd_acct_name, bd_rate, bd_amount in breakdown:
            inv_lines.append('\t\tbreakdown:')
            inv_lines.append(f'\t\t\taccount: "{bd_acct_name}"')
            inv_lines.append(f'\t\t\trate: {_fmt_rate(bd_rate)}')
            inv_lines.append(f'\t\t\tamount: {_fmt_money(bd_amount)}')

    # Posted / payment blocks (mirror canonical export sentinel form)
    if is_draft:
        inv_lines.append('\tposted: none')
        inv_lines.append('\tpayment: none')
    else:
        ar_name = get_account_full_name(invoice.GetPostedAcc())
        inv_lines.append('\tposted:')
        inv_lines.append(f'\t\tdate: {invoice.GetDatePosted().strftime("%Y-%m-%d")}')
        inv_lines.append(f'\t\tdue: {invoice.GetDateDue().strftime("%Y-%m-%d")}')
        inv_lines.append(f'\t\tar_account: "{ar_name}"')
        inv_lines.append(f'\t\tmemo: "{posting_txn.GetDescription()}"')
        inv_lines.append('\t\taccumulate: true')

        # Payment blocks reuse the export logic — but the render path
        # cares about audit info, not round-trip, so we emit a minimal
        # form (date / amount / bank_account / memo). No txn_guid here:
        # the rendered file is for human consumption, not re-importing
        # full lot structure.
        lot = invoice.GetPostedLot()
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
                # bank-side split = the non-AR side; find any (for the account
                # name + memo only)
                bank_name = ''
                pay_memo = ''
                for i in range(txn.CountSplits()):
                    sp = txn.GetSplit(i)
                    atype = gc.xaccAccountGetType(sp.GetAccount().instance)
                    if atype not in (gc.ACCT_TYPE_RECEIVABLE, gc.ACCT_TYPE_PAYABLE):
                        bank_name = get_account_full_name(sp.GetAccount())
                        pay_memo = sp.GetMemo() or ''
                        break
                # This invoice's payment amount is its own allocation — the AR
                # split in its lot (`s`) — not the bank-side total, which would
                # over-report when one bank tx pays several invoices. Format
                # exactly at the AR commodity's decimal count (no to_double).
                pay_amt = format_amount_for_commodity(
                    s.GetAmount().abs(), s.GetAccount().GetCommodity())
                inv_lines.append('\tpayment:')
                inv_lines.append(f'\t\tdate: {pay_date}')
                inv_lines.append(f'\t\tamount: {pay_amt}')
                inv_lines.append(f'\t\tbank_account: "{bank_name}"')
                inv_lines.append(f'\t\tmemo: "{pay_memo}"')
                had_payment = True
        if not had_payment:
            inv_lines.append('\tpayment: none')

    # Invoice-level informational totals
    subtotal = sum(e[1] for e in entries_data)
    tax_total = sum(e[2] for e in entries_data)
    inv_lines.append(f'\tinvoice_subtotal: {_fmt_money(subtotal)}')
    # Q-019: tax_total and grand total are now emitted for drafts too,
    # computed from each entry's tax_table.
    inv_lines.append(f'\tinvoice_tax_total: {_fmt_money(tax_total)}')
    inv_lines.append(f'\tinvoice_total: {_fmt_money(subtotal + tax_total)}')

    # Q-019: provisional-tax caveat — invoice-scoped (drafts only),
    # prepended inside the invoice block. The seller `# Issued by:`
    # header (also Q-019) is file-scoped and emitted ahead of every
    # block below.
    if is_draft:
        inv_lines.insert(
            0,
            '# Tax figures are provisional — invoice not yet posted; '
            'recomputed at post time.',
        )

    blocks.append('\n'.join(inv_lines))

    seller_header = _render_seller_header(company_info)
    if seller_header:
        # File-scoped — "this whole rendered document is from Acme".
        blocks.insert(0, seller_header)

    return '\n\n'.join(blocks) + '\n'
