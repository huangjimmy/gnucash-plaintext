#!/usr/bin/env python
"""
Service for rendering GnuCash invoices to PDF.
"""
from fractions import Fraction

import gnucash.gnucash_core_c as gc
from gnucash import Split

from infrastructure.gnucash.engine import iterate_glist, load_gnc_engine, safe_ctypes_string
from infrastructure.gnucash.kvp import KNOWN_CUSTOMER_METADATA_KEYS
from infrastructure.gnucash.utils import exact_text, money_text, numeric_to_fraction
from services.plaintext_blocks import (
    document_text_lines,
    owner_block_lines,
    payment_block_lines,
    posted_block_lines,
)


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


def render_to_html(invoice, session, report=None, report_file=None,
                   warn=None) -> str:
    """The document as HTML, drawn by GnuCash.

    The page is a GnuCash report, through `services/gnucash_report` — by
    default the Printable Invoice its own File → Print Invoice draws. So what
    this prints is what GnuCash prints, and there is no second layout here to
    keep in step with it: the one this project used to carry had its own
    columns, its own tax rows and its own totals, and its totals were wrong
    for a document in a currency the book is not kept in.

    `report` picks a different one — by the name GnuCash's GUI lists it under,
    or by template guid — and `report_file` loads a `.scm` first, so a report
    written by the reader is registered by the time it is named. Customising
    the page is writing a GnuCash report, which is what GnuCash's own pages
    are.

    `session` is the open session holding the document: GnuCash's report
    resolves the document from its guid against the *current* book and reads
    the book's own options for the company block, so neither a book handle nor
    a company block read out of the file has anything left to say here.

    HTML and not a PDF, so a caller — and a test — can read what the page says
    without going through weasyprint. `cli/invoice_print_cmd.py` lays the PDF
    out from this, after every document in the run has been rendered.
    """
    from services.gnucash_importer import _swig_invoice_guid_str
    from services.gnucash_report import (
        _extra_text,
        carry_slot_values_onto_the_fields,
        render_document_html,
    )

    carry_slot_values_onto_the_fields(invoice)
    company_extra, owner_extra = _extra_text(invoice)
    return render_document_html(
        session, _swig_invoice_guid_str(invoice),
        company_extra=company_extra, owner_extra=owner_extra,
        report=report, report_file=report_file, warn=warn)


# ── Q-017: plaintext render ────────────────────────────────────────────────
#
# Same canonical format as `export --include-business-objects`, with
# **informational** fields added (entry_amount, entry_tax,
# entry_tax_breakdown, invoice_subtotal, invoice_tax_total, invoice_total).
# The importer recomputes the informational fields from the source-of-truth
# fields (quantity, price, tax_table, tax_included) on re-import and errors
# loudly on mismatch — see the format-spec section in
# docs/issues/Q-017-print-invoice-plaintext-format-and-multi-invoice.md.


def _fmt_money(value: Fraction, unit: int) -> str:
    """An amount at its own currency's decimals, exactly as the engine rounds
    it — the same figure the importer recomputes and checks against."""
    return money_text(value, unit)


def _fmt_rate(rate_decimal: Fraction) -> str:
    """Format a tax rate as it appears in the plaintext: percentage with the
    smallest representation (e.g. `5.0`, `9.975`)."""
    s = exact_text(Fraction(rate_decimal) * 100)
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


def _close(a, b, tol=Fraction(1, 100)) -> bool:
    """Whether two figures agree to within `tol` — compared as the exact
    rationals they are, so "a cent apart" means a cent, not a cent plus
    whatever the nearest double happened to be."""
    return abs(Fraction(a) - Fraction(b)) <= tol


def _declared_number(raw, label: str, field: str) -> Fraction:
    """A number the user wrote, read exactly. `0.07` is 7/100, not the double
    nearest to it, so comparing it against a recomputed figure is a comparison
    of the two figures rather than of two approximations."""
    try:
        return Fraction(str(raw).strip())
    except (ValueError, ZeroDivisionError) as exc:
        raise ValueError(
            f'{label}: {field} must be a number, got {raw!r}') from exc


def _tax_table_entries(lib, tt_ptr):
    """Return [(account_name, rate_as_decimal)] for one tax-table pointer,
    in declaration order (GST before PST, etc.)."""

    def _one(_lib, tte_ptr):
        acct_ptr = _lib.gncTaxTableEntryGetAccount(tte_ptr)
        amt_c = _lib.gncTaxTableEntryGetAmount(tte_ptr)
        rate_pct = numeric_to_fraction(amt_c) if amt_c.denom else Fraction(0)
        # GnuCash stores tax-table amounts as percentages (e.g. 13.0
        # for HST). Internally we want the decimal fraction (0.13) so
        # `entry_amount × rate` gives the tax dollars directly. Kept as an
        # exact fraction: a rate like 1/3 % has no float that says it, and
        # the error rides straight into the tax dollars.
        rate = rate_pct / 100
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
    qty = numeric_to_fraction(qty_c) if qty_c.denom else Fraction(0)
    price = numeric_to_fraction(pri_c) if pri_c.denom else Fraction(0)
    gross_or_net = qty * price

    taxable = bool(lib.gncEntryGetInvTaxable(entry_ptr))
    tax_included = bool(lib.gncEntryGetInvTaxIncluded(entry_ptr))
    tt_ptr = lib.gncEntryGetInvTaxTable(entry_ptr) if taxable else None

    if not taxable or not tt_ptr:
        return (gross_or_net, Fraction(0), [])

    tt_entries = _tax_table_entries(lib, tt_ptr)
    total_rate = sum((rate for _, rate in tt_entries), Fraction(0))

    # Backing tax out of a tax-included price is a division, which is where a
    # float stops being able to say the answer: 113.00 / 1.13 is 100 exactly
    # as a fraction and 99.99999999999999 as a double.
    net = gross_or_net / (1 + total_rate) if tax_included else gross_or_net

    breakdown = [(acct_name, rate, net * rate) for acct_name, rate in tt_entries]
    entry_tax = sum((amount for _, _, amount in breakdown), Fraction(0))
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

    if 'entry_amount' in declared:
        declared_amount = _declared_number(
            declared['entry_amount'], entry_label, 'entry_amount')
        if not _close(declared_amount, computed_amount):
            raise ValueError(
                f'{entry_label}: declared entry_amount {exact_text(declared_amount)} '
                f'does not match recomputed {exact_text(computed_amount)} '
                f'(from quantity × price, adjusted for tax_included)'
            )

    if 'entry_tax' in declared:
        declared_tax = _declared_number(
            declared['entry_tax'], entry_label, 'entry_tax')
        if not _close(declared_tax, computed_tax):
            raise ValueError(
                f'{entry_label}: declared entry_tax {exact_text(declared_tax)} does '
                f'not match recomputed {exact_text(computed_tax)} (from tax_table '
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
                decl_rate = Fraction(str(decl['rate']))
                decl_amount = Fraction(str(decl['amount']))
            except (KeyError, ValueError, ZeroDivisionError) as exc:
                raise ValueError(
                    f'{entry_label}: breakdown for {acct!r} must declare '
                    f'numeric rate and amount; got {decl!r}'
                ) from exc
            # `rate` is stored as decimal fraction internally (0.13) but
            # serialised as percent (13.0); accept either form.
            if not (_close(decl_rate, comp_rate * 100, tol=Fraction(1, 1000))
                    or _close(decl_rate, comp_rate, tol=Fraction(1, 100000))):
                raise ValueError(
                    f'{entry_label}: breakdown for {acct!r} declares '
                    f'rate {exact_text(decl_rate)} but tax_table stores '
                    f'{exact_text(comp_rate * 100)}%'
                )
            if not _close(decl_amount, comp_amount):
                raise ValueError(
                    f'{entry_label}: breakdown for {acct!r} declares '
                    f'amount {exact_text(decl_amount)} but recomputed value is '
                    f'{exact_text(comp_amount)} (entry_amount × rate)'
                )


def validate_invoice_informational(declared, computed_subtotal,
                                   computed_tax, invoice_label):
    """Q-017: invoice-level totals. `declared` is a dict with optional
    keys invoice_subtotal/invoice_tax_total/invoice_total (or the bill_*
    analogues — caller passes whichever set). Raises ValueError on any
    mismatch."""
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
            decl = _declared_number(declared[field], invoice_label, field)
            if not _close(decl, computed):
                raise ValueError(
                    f'{invoice_label}: declared {field} {exact_text(decl)} does '
                    f'not match recomputed {exact_text(computed)} (sum of entries)'
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
    """The customer block, written by `services/plaintext_blocks`."""
    return '\n'.join(owner_block_lines(
        'customer', cust, KNOWN_CUSTOMER_METADATA_KEYS))


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
    unit = invoice.GetCurrency().get_fraction()
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
    inv_lines += document_text_lines(invoice)

    # Per-entry blocks with informational fields
    from infrastructure.gnucash.utils import (
        get_account_full_name,
    )

    for raw_entry, entry_amount, entry_tax, breakdown in entries_data:
        ent_ptr = int(raw_entry.instance)
        desc = safe_ctypes_string(lib.gncEntryGetDescription, ent_ptr)
        action = safe_ctypes_string(lib.gncEntryGetAction, ent_ptr)
        qty_c = lib.gncEntryGetQuantity(ent_ptr)
        pri_c = lib.gncEntryGetInvPrice(ent_ptr)
        qty = numeric_to_fraction(qty_c) if qty_c.denom else Fraction(0)
        price = numeric_to_fraction(pri_c) if pri_c.denom else Fraction(0)
        taxable = bool(lib.gncEntryGetInvTaxable(ent_ptr))
        tax_included = bool(lib.gncEntryGetInvTaxIncluded(ent_ptr))
        acct_name = get_account_full_name(raw_entry.GetInvAccount())
        date_str = raw_entry.GetDate().strftime('%Y-%m-%d')

        inv_lines.append('\tentry:')
        inv_lines.append(f'\t\tdate: {date_str}')
        inv_lines.append(f'\t\tdescription: "{desc}"')
        inv_lines.append(f'\t\taction: "{action}"')
        inv_lines.append(f'\t\taccount: "{acct_name}"')
        inv_lines.append(f'\t\tquantity: {exact_text(qty)}')
        inv_lines.append(f'\t\tprice: {exact_text(price)}')
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
        inv_lines.append(f'\t\tentry_amount: {_fmt_money(entry_amount, unit)}')
        inv_lines.append(f'\t\tentry_tax: {_fmt_money(entry_tax, unit)}')
        for bd_acct_name, bd_rate, bd_amount in breakdown:
            inv_lines.append('\t\tbreakdown:')
            inv_lines.append(f'\t\t\taccount: "{bd_acct_name}"')
            inv_lines.append(f'\t\t\trate: {_fmt_rate(bd_rate)}')
            inv_lines.append(f'\t\t\tamount: {_fmt_money(bd_amount, unit)}')

    # Posted / payment blocks (mirror canonical export sentinel form)
    if is_draft:
        inv_lines.append('\tposted: none')
        inv_lines.append('\tpayment: none')
    else:
        ar_name = get_account_full_name(invoice.GetPostedAcc())
        inv_lines += posted_block_lines(invoice, 'ar_account', ar_name)

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
                # The amount is the block writer's to work out — from `s`, the
                # AR split in this invoice's own lot, not the bank-side total,
                # which would over-report when one bank tx pays several
                # invoices. Computed here instead, it was rounded to the
                # currency's places while the export refused the same figure.
                inv_lines += payment_block_lines(
                    txn, s, bank_name, pay_memo,
                    f'invoice "{invoice.GetID()}"', txn.GetNum() or '')
                had_payment = True
        if not had_payment:
            inv_lines.append('\tpayment: none')

    # Invoice-level informational totals
    subtotal = sum((e[1] for e in entries_data), Fraction(0))
    tax_total = sum((e[2] for e in entries_data), Fraction(0))
    inv_lines.append(f'\tinvoice_subtotal: {_fmt_money(subtotal, unit)}')
    # Q-019: tax_total and grand total are now emitted for drafts too,
    # computed from each entry's tax_table.
    inv_lines.append(f'\tinvoice_tax_total: {_fmt_money(tax_total, unit)}')
    inv_lines.append(f'\tinvoice_total: {_fmt_money(subtotal + tax_total, unit)}')

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
