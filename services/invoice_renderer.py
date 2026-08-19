#!/usr/bin/env python
"""
Service for rendering GnuCash invoices to PDF.
"""
import ctypes
import math
from fractions import Fraction

import gnucash.gnucash_core_c as gc
from gnucash import Split

from infrastructure.gnucash.engine import (
    GncAccountValueC,
    iterate_glist,
    load_gnc_engine,
    safe_ctypes_string,
)
from infrastructure.gnucash.kvp import KNOWN_CUSTOMER_METADATA_KEYS
from infrastructure.gnucash.utils import (
    encode_value_as_string,
    exact_text,
    money_text,
    numeric_to_fraction,
    to_money,
)
from services.plaintext_blocks import (
    document_text_lines,
    entry_discount,
    entry_notes,
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
    # Every line the slot holds, under `address`, rather than four keys named
    # after the first four of them. The book's address is one free-text field
    # and takes as many lines as are typed into it, so reading four was the
    # same truncation the export had — and this is the copy a *printed*
    # document is drawn from, so a company with a country on line five posted
    # invoices without it.
    addr_raw = _str_val(biz_el, 'Company Address')
    result['address'] = [line.strip()
                         for line in (addr_raw.split('\n') if addr_raw else [])]

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
    default the Printable Invoice its own Print Invoice button draws. So what
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
    without laying it out. `cli/invoice_print_cmd.py` prints the PDF from
    this, through WebKit, after every document in the run has been rendered.
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


def _line_key(raw_entry):
    """What tells one line of a document from another, wherever it is read.

    Its description and its date — the fields `gncEntryCompare` itself sorts
    on, minus the date entered, which a rebuilt book stamps anew.
    """
    return (raw_entry.GetDescription() or '',
            raw_entry.GetDate().strftime('%Y-%m-%d'))


def entries_fitted_to_the_document(entries_data, document_tax, unit,
                                   document_subtotal=None):
    """`entries_data` with every tax figure rounded so the columns add up.

    Two levels, both of them a column a reader can add: each line's tax to
    the document's stated tax, and each line's `breakdown:` blocks to that
    line's own tax.

    The **net** column needs no fitting and gets none: a document's subtotal
    is the sum of its lines' rounded values — measured on 5.10, three lines
    of 86.96 against a stated 260.88 — so the lines already add to it. It is
    checked all the same when `document_subtotal` is given, because "needs no
    fitting" is a claim about GnuCash, and a page whose net column does not
    add to its own subtotal is exactly as wrong as one whose tax column does
    not. Both checks refuse rather than print, since the import recomputes
    the page the same way the writer wrote it and would agree with it.
    """
    # Fitted per *account* first, across every line, because that is how the
    # book holds it: each account's tax is rounded once over the whole
    # document and posted as one split. Fitting each line's tax first and
    # splitting it between accounts afterwards makes both columns add up on
    # the page and neither match the book — measured shape: two lines of 1.10
    # taxed 5% + 5%, where each line's 0.055 + 0.055 rounds to 0.06 + 0.05 on
    # every line, so the page shows one account 0.12 and the other 0.10 while
    # the book posts 0.11 each.
    #
    # Ties are broken on what a line *is* — its description and date — not on
    # where it sits: `gncEntryCompare` orders a document by date, then date
    # entered, then description, and a rebuilt book stamps its own date
    # entered, so a page keyed on position could disagree with its own
    # re-import by a unit.
    rows_by_account = {}
    for position, (_, _, _, breakdown) in enumerate(entries_data):
        for name, _rate, amount in breakdown:
            rows_by_account.setdefault(name, []).append((position, amount))

    share = {}
    for name, rows in rows_by_account.items():
        account_total = numeric_to_fraction(
            to_money(sum((amount for _, amount in rows), Fraction(0)), unit))
        for (position, _), fitted_amount in zip(rows, figures_that_add_up(
                [amount for _, amount in rows], account_total, unit,
                keys=[_line_key(entries_data[position][0])
                      for position, _ in rows])):
            share[(position, name)] = fitted_amount

    fitted = []
    for position, (raw_entry, amount, _, breakdown) in enumerate(entries_data):
        rows = [(name, rate, share[(position, name)])
                for name, rate, _ in breakdown]
        fitted.append((raw_entry, amount,
                       sum((row[2] for row in rows), Fraction(0)), rows))

    # What the lines now state, against what the document says it is worth.
    # They agree because a document's tax *is* the sum of its accounts' —
    # measured on 5.10 — and this fits to those same account totals. A
    # disagreement would mean that model is wrong on some version, and a page
    # whose column does not add to its own total is one to refuse.
    stated = sum((entry_tax for _, _, entry_tax, _ in fitted), Fraction(0))
    if stated != document_tax:
        from use_cases.export_transactions import UnwritableFigureError
        raise UnwritableFigureError(
            f'this document is worth {exact_text(document_tax)} in tax and '
            f'its lines account for {exact_text(stated)} — the two are '
            f'GnuCash\'s own figures and no page can state both')

    # And the net column, which is not fitted and so is only ever right
    # because GnuCash sums the rounded lines for its subtotal. Unchecked,
    # that was the one column of the two where a version rounding it some
    # other way would print a page that does not add up, have the import
    # recompute it identically, and re-import clean.
    if document_subtotal is not None:
        net = sum((amount for _, amount, _, _ in fitted), Fraction(0))
        if net != document_subtotal:
            from use_cases.export_transactions import UnwritableFigureError
            raise UnwritableFigureError(
                f'this document is worth {exact_text(document_subtotal)} '
                f'before tax and its lines account for {exact_text(net)} — '
                f'the two are GnuCash\'s own figures and no page can state '
                f'both')
    return fitted


def figures_that_add_up(parts, whole, unit, keys=None):
    """`parts` rounded to the currency's unit, summing to `whole` exactly.

    A printed document states a tax per line and a tax for the document, and
    the book holds only the second: GnuCash rounds a document's tax once, and
    an accumulated posting has no per-line tax split to compare a line
    against. Rounding each line on its own then leaves a column that does not
    add up — measured on 5.10, three 100.00 lines at 15 per cent tax-included
    print 13.04 apiece against a stated 39.13.

    GnuCash's own page sidesteps this by printing no per-line tax at all;
    this format states one, for a reader and for the re-import that checks
    it, so the parts are fitted to the whole instead. Each is rounded down
    and the units that leaves are handed out one apiece, largest remainder
    first.

    **`whole` is the parts' own sum, rounded to the unit** — that is what
    `entries_fitted_to_the_document` passes, per tax account, and it is what
    keeps this to a single pass. Rounding to nearest puts the whole within
    half a unit of the exact sum, and flooring a part loses less than a unit,
    so the shortfall is never negative and never exceeds the number of parts
    carrying a fraction. Every such line therefore takes at most one unit,
    has room for it — flooring left it under its own figure — and cannot
    reach zero from the other side on the way. A caller handing a `whole`
    from somewhere else would break all three at once.
    """
    if not parts:
        return []

    scaled = [part * unit for part in parts]
    # Floored, not truncated: `int()` rounds toward zero, so a negative part
    # would keep a remainder in (-1, 0], sort first as the largest, and take
    # the +1 that belongs to the line with the biggest fraction — a line
    # whose own tax is -0.001 printing 0.01. Only a document mixing signs
    # reaches it, a negative quantity beside a positive one.
    floors = [math.floor(value) for value in scaled]
    # Floored like the parts, for the same reason and not because it matters
    # here: a whole is a figure in the currency's own units, so it scales to
    # an integer. Truncating beside a floor is an asymmetry a later edit
    # would trip over.
    short = math.floor(whole * unit) - sum(floors)

    # Only among the lines that carry any of it. A line the page declares
    # `taxable: false` holds no tax and has no `breakdown:` block under it,
    # so a unit landing there states tax the line does not carry and that
    # nothing on the page adds up to. Every part zero is the untaxed
    # document, where the whole is zero too and nothing moves.
    carrying = [i for i in range(len(parts)) if scaled[i] != 0]

    # Largest fractional part first, and by what each part *is* after that —
    # `keys`, see `_line_key`, rather than where it happens to sit. Without
    # them the position stands in, which is only stable while the list is.
    # Either way the same document allocates the same way every time, which
    # is what lets the import recompute what the writer printed.
    tie = keys if keys is not None else list(range(len(parts)))
    remainders = sorted(carrying,
                        key=lambda i: (-(scaled[i] - floors[i]), tie[i]))
    for index in remainders[:short]:
        floors[index] += 1
    return [Fraction(units, unit) for units in floors]


def tax_breakdown(lib, entry_ptr, tt_ptr, is_cust_doc=1, is_credit_note=0):
    """`[(account, rate, amount)]` — one row per tax-table entry.

    The rate comes from the table and the amount from the engine, joined on
    the account each names, so a row states the money the posting split
    carries beside the rate that produced it. The rate is written as a
    percentage whatever the table entry's own type is — a table entry stating
    a flat amount rather than a rate is drawn as one here too, which is older
    than this and unchanged by it. A table naming one account
    twice is merged by the engine, so the rows are grouped the same way
    rather than each claiming the whole amount.
    """
    by_account = _doc_tax_by_account(lib, entry_ptr, is_cust_doc, is_credit_note)
    rows = []
    for acct_name, rate in _tax_table_entries(lib, tt_ptr):
        for row, (seen_name, seen_rate, _) in enumerate(rows):
            if seen_name == acct_name:
                rows[row] = (seen_name, seen_rate + rate,
                             by_account.get(acct_name, Fraction(0)))
                break
        else:
            rows.append((acct_name, rate,
                         by_account.get(acct_name, Fraction(0))))
    return rows


def credit_note_lines(document) -> list:
    """`credit_note: true` for one, and nothing for an ordinary document.

    GnuCash's Business → New Credit Note makes a `gncInvoice` with a flag
    and its lines stored negated: a credit note for 200.00 holds a quantity
    of −2 at 100.00, its `gncInvoiceGetTotal*` answer +200.00, and its
    posting splits are the mirror of an invoice's — Sales +200.00 and A/R
    −200.00. Measured on 5.10.

    So a ledger states one key and nothing else changes: the quantities are
    already what the book holds, and the figures agree with the totals once
    the flag is passed to `gncEntryGetDocValue`. Written only when it is set,
    because `credit_note: false` on every ordinary document is a line saying
    nothing about the overwhelming majority of them, and its absence is
    already what a fresh document holds.
    """
    return ['\tcredit_note: #True'] if document.GetIsCreditNote() else []


def document_totals(lib, document):
    """`(subtotal, tax, total)` for an invoice or a bill, as GnuCash has them.

    Not the sum of the per-line figures: GnuCash rounds a document's tax once
    rather than line by line, so a bill of three 100.00 lines at 15 per cent
    tax-included posts 260.88 + 39.13 = **300.01** while the rounded per-line
    tax adds to 39.12 — measured on 5.10, and the page said 300.00 against
    its own A/P split of 300.01.

    Read for a draft too. These compute from the entries, so an unposted
    document has totals before it has splits.
    """
    ptr = int(document.instance)

    def figure(value):
        # `denom` guarded as every other reading here is: a gnc_numeric error
        # value carries denominator 0, and dividing by it would surface as a
        # bare ZeroDivisionError rather than a figure of zero.
        return numeric_to_fraction(value) if value.denom else Fraction(0)

    return (figure(lib.gncInvoiceGetTotalSubtotal(ptr)),
            figure(lib.gncInvoiceGetTotalTax(ptr)),
            figure(lib.gncInvoiceGetTotal(ptr)))


def _doc_tax_by_account(lib, entry_ptr, is_cust_doc=1, is_credit_note=0):
    """`{account full name: tax}` for one entry, as the engine computes it.

    The figures its posting splits carry: measured on 5.10, a line taxed by
    a two-entry table (5% + 8%) and discounted 10 per cent posts 45.00 to
    GST and 72.00 to PST, and this returns exactly those.
    """
    def _one(_lib, data_ptr):
        pair = ctypes.cast(
            data_ptr, ctypes.POINTER(GncAccountValueC)).contents
        name = (_ctypes_account_full_name(_lib, pair.account)
                if pair.account else '?')
        amount = (numeric_to_fraction(pair.value)
                  if pair.value.denom else Fraction(0))
        return (name, amount)

    # The list is the caller's: `gncEntryGetDocTaxValues` builds a fresh
    # `AccountValueList` rather than handing back the entry's own, and
    # `gncAccountValueDestroy` is what the header says to free it with. Left
    # alone it leaks a node and a value per tax account per entry, on every
    # export, every printed document and every import that checks one.
    values = lib.gncEntryGetDocTaxValues(entry_ptr, is_cust_doc, is_credit_note)
    try:
        found = {}
        for name, amount in iterate_glist(lib, values, _one):
            found[name] = found.get(name, Fraction(0)) + amount
        return found
    finally:
        if values:
            lib.gncAccountValueDestroy(values)


def compute_entry_informational(lib, entry_ptr, is_credit_note=0):
    """For one invoice entry, return (entry_amount, entry_tax,
    breakdown) where:
      * entry_amount = what GnuCash posts to the income account for this
        line — quantity × price, less the discount, and net of tax where
        the price includes it.
      * entry_tax    = the tax GnuCash puts on this line.
      * breakdown    = [(account_name, rate_decimal, amount), ...] —
        one tuple per tax-table entry, or [] when the entry isn't
        taxable (or has no tax_table).

    The document's `invoice_subtotal:` and `invoice_tax_total:` are *not*
    these added up — see `document_totals`, which GnuCash rounds once.

    Every figure is GnuCash's own, read through `gncEntryGetDocValue`,
    `gncEntryGetDocTaxValue` and `gncEntryGetDocTaxValues` — the functions
    `gncInvoicePostToAccount` posts from. They answer what this project's
    own arithmetic could not: a discount lands by three different rules,
    and `tax_included` backs the tax out beneath them.

    Measured on 5.10, a line of 10 × 100 discounted 10 per cent against a
    10 per cent tax table:

        pretax     posts 900.00 + 90.00 tax   (discount, then tax)
        sametime   posts 900.00 + 100.00 tax  (both off the full amount)
        posttax    posts 890.00 + 100.00 tax  (tax, then discount on the sum)

    `qty × price` said 1000.00 + 100.00 for all three, so a printed document
    stated a total the book contradicted — and `--format pdf`, drawn by
    GnuCash's own report, disagreed with `--format plaintext` from the same
    command.

    `is_cust_doc=1`: these are the invoice-side fields. The bill side has
    `compute_bill_entry_informational`, and a bill has no discount.

    `is_credit_note` is the document's credit-note flag, and it belongs here for the
    same reason `is_cust_doc` does — it is what the engine posts from.
    GnuCash stores a credit note's lines negated, so a credit note for 200
    holds a quantity of −2 at 100 and `gncEntryGetDocValue(..., is_credit_note=1)`
    answers +200: the figure the document's own total states, and the figure
    a person typed into the window. Measured on 5.10, against a credit note
    built the way GnuCash's window builds one — flag set and quantity stored
    negative — where the posting splits are Sales +200 and A/R −200.
    """
    # The net rounded as the engine rounds it, because the document's own
    # subtotal is the sum of these — measured, three 86.96 lines and a stated
    # 260.88. The tax unrounded, because the document's tax is *not* the sum
    # of the rounded lines: GnuCash rounds it once, and the writer fits the
    # lines to it through `figures_that_add_up`.
    value = lib.gncEntryGetDocValue(entry_ptr, 1, 1, is_credit_note)
    tax = lib.gncEntryGetDocTaxValue(entry_ptr, 0, 1, is_credit_note)
    net = numeric_to_fraction(value) if value.denom else Fraction(0)
    entry_tax = numeric_to_fraction(tax) if tax.denom else Fraction(0)

    taxable = bool(lib.gncEntryGetInvTaxable(entry_ptr))
    tt_ptr = lib.gncEntryGetInvTaxTable(entry_ptr) if taxable else None
    if not taxable or not tt_ptr:
        return (net, Fraction(0), [])

    return (net, entry_tax,
            tax_breakdown(lib, entry_ptr, tt_ptr, is_credit_note=is_credit_note))


def validate_entry_informational(declared, breakdown_declared, computed,
                                 entry_label):
    """Q-017: what a page says a line is worth, against what it is worth.

    A comparison and nothing else. The figures come from the caller, which
    has the whole document and has fitted its lines the way the writer fits
    them — a line's tax is rounded to make the document's column add up, so
    what a line is worth on the page is not a property of the line alone.
    Working one line out here instead is what made a printed yen invoice
    disagree with itself: the line's own tax is 103.5 and the page states
    the 104 the book posts.

    Every comparison is exact. These are money, and money in this project is
    compared as the exact rational it is — a page that states a figure the
    book does not hold is a page to refuse, not to accept within a cent.

    Arguments:
        declared             — dict with optional keys 'entry_amount' and
                               'entry_tax' (string values from plaintext);
                               either or both may be absent.
        breakdown_declared   — list of dicts [{account, rate, amount}]; may
                               be empty if no `breakdown:` blocks were
                               present on this entry.
        computed             — `(amount, tax, breakdown)` for this line, as
                               the writer would print it.
        entry_label          — human-readable identifier for error messages
                               (e.g. "invoice INV-Q17 entry #1").

    Raises ValueError naming the field and both numbers.
    """
    computed_amount, computed_tax, computed_breakdown = computed

    if 'entry_amount' in declared:
        declared_amount = _declared_number(
            declared['entry_amount'], entry_label, 'entry_amount')
        if declared_amount != computed_amount:
            raise ValueError(
                f'{entry_label}: declared entry_amount '
                f'{exact_text(declared_amount)} does not match '
                f'{exact_text(computed_amount)}, which is what GnuCash posts '
                f'for this line — quantity × price, less any discount, net '
                f'of tax where the price includes it'
            )

    if 'entry_tax' in declared:
        declared_tax = _declared_number(
            declared['entry_tax'], entry_label, 'entry_tax')
        if declared_tax != computed_tax:
            raise ValueError(
                f'{entry_label}: declared entry_tax '
                f'{exact_text(declared_tax)} does not match '
                f'{exact_text(computed_tax)}, which is the tax GnuCash puts '
                f'on this line — where a discount falls relative to the tax '
                f'decides it'
            )

    # Breakdown validation: each declared breakdown block must match one
    # of the computed breakdown rows by account name (the canonical key),
    # and the declared rate + amount must match. Counts must agree too (no
    # missing or extra blocks).
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
            # serialised as percent (13.0); either form is read, and each
            # exactly — a rate is a number the file states, not an estimate.
            if decl_rate != comp_rate * 100 and decl_rate != comp_rate:
                raise ValueError(
                    f'{entry_label}: breakdown for {acct!r} declares '
                    f'rate {exact_text(decl_rate)} but tax_table stores '
                    f'{exact_text(comp_rate * 100)}%'
                )
            if decl_amount != comp_amount:
                raise ValueError(
                    f'{entry_label}: breakdown for {acct!r} declares '
                    f'amount {exact_text(decl_amount)} but the tax GnuCash '
                    f'sends that account is {exact_text(comp_amount)}'
                )


def validate_invoice_informational(declared, computed_subtotal,
                                   computed_tax, computed_total,
                                   invoice_label):
    """Q-017: invoice-level totals. `declared` is a dict with optional
    keys invoice_subtotal/invoice_tax_total/invoice_total (or the bill_*
    analogues — caller passes whichever set). Raises ValueError on any
    mismatch.

    The total is asked for rather than added up here. GnuCash rounds each of
    the three separately, so `subtotal + tax` can sit a cent off the total it
    reports — and the writer prints the total it reports, which would then be
    refused by this, the importer of the command that wrote it.

    Compared exactly, as every figure here is: a page states what a document
    is worth, and a figure the book does not hold is one to refuse. Held to a
    cent instead, the page this check exists to catch went through — a
    document printed by an earlier release states a total exactly one cent
    under what a tax-included book posts.
    """
    pairs = [
        ('invoice_subtotal', computed_subtotal),
        ('bill_subtotal',    computed_subtotal),
        ('invoice_tax_total', computed_tax),
        ('bill_tax_total',    computed_tax),
        ('invoice_total', computed_total),
        ('bill_total',    computed_total),
    ]
    for field, computed in pairs:
        if field in declared:
            decl = _declared_number(declared[field], invoice_label, field)
            if decl != computed:
                raise ValueError(
                    f'{invoice_label}: declared {field} {exact_text(decl)} '
                    f'does not match {exact_text(computed)}, which is what '
                    f'GnuCash makes this document worth'
                )


def _render_taxtable_block(lib, tt_ptr) -> str:
    """Render one tax-table object as plaintext (same syntax `export`
    emits). Used to make the per-invoice plaintext self-contained for
    the recipient — they get the tax rates inline."""

    tt_name = safe_ctypes_string(lib.gncTaxTableGetName, tt_ptr)
    lines = [f'taxtable "{tt_name}"']
    for acct_name, rate in _tax_table_entries(lib, tt_ptr):
        lines.append('\tentry:')
        lines.append(f'\t\taccount: {encode_value_as_string(acct_name)}')
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
    addr_joined = ', '.join(
        line for line in (company_info.get('address') or [])
        if (line or '').strip())
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

    # Every figure below is read with it, so the lines agree with the totals
    # a credit note states — see `compute_entry_informational`.
    is_credit_note = 1 if invoice.GetIsCreditNote() else 0

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
            lib, ent_ptr, is_credit_note
        )
        entries_data.append((raw_entry, entry_amount, entry_tax, breakdown))
        tt_ptr = lib.gncEntryGetInvTaxTable(ent_ptr)
        if tt_ptr and int(tt_ptr) not in seen_tt:
            seen_tt[int(tt_ptr)] = tt_ptr

    subtotal, tax_total, total = document_totals(lib, invoice)
    entries_data = entries_fitted_to_the_document(entries_data, tax_total,
                                                  unit, subtotal)

    blocks = []
    for tt_ptr in seen_tt.values():
        blocks.append(_render_taxtable_block(lib, tt_ptr))

    blocks.append(_render_customer_block(cust))

    # Invoice block
    inv_lines = [
        f'invoice "{inv_id}"',
        f'\tcustomer_id: {encode_value_as_string(cust.GetID())}',
        f'\tcurrency: {currency}',
        f'\tdate_opened: {date_opened}',
    ]
    inv_lines += credit_note_lines(invoice)
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
        inv_lines.append(f'\t\tdescription: {encode_value_as_string(desc)}')
        inv_lines.append(f'\t\taction: {encode_value_as_string(action)}')
        inv_lines.append(f'\t\taccount: {encode_value_as_string(acct_name)}')
        inv_lines.append(f'\t\tquantity: {exact_text(qty)}')
        inv_lines.append(f'\t\tprice: {exact_text(price)}')
        inv_lines.append(f'\t\ttaxable: {encode_value_as_string(taxable)}')
        inv_lines.append(
            f'\t\ttax_included: {encode_value_as_string(tax_included)}')

        tt_ptr = lib.gncEntryGetInvTaxTable(ent_ptr)
        if tt_ptr:
            tt_name = safe_ctypes_string(lib.gncTaxTableGetName, tt_ptr)
            if tt_name:
                inv_lines.append(f'\t\ttax_table: {encode_value_as_string(tt_name)}')

        # The note and the discount, written exactly as `export` writes them:
        # a printed plaintext document carries the guids that make it
        # re-importable, so a field this drops is a field the re-import
        # removes from the book.
        inv_lines.extend(entry_notes(lib, ent_ptr))
        inv_lines.extend(entry_discount(lib, raw_entry, ent_ptr))

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
            inv_lines.append(f'\t\t\taccount: {encode_value_as_string(bd_acct_name)}')
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

    # Invoice-level informational totals, asked of the document rather than
    # added up from its lines: GnuCash rounds a document's tax once, so the
    # two differ by a cent on a tax-included document of several lines and
    # the posting split follows GnuCash. The lines above were fitted to these.
    inv_lines.append(f'\tinvoice_subtotal: {_fmt_money(subtotal, unit)}')
    # Q-019: tax_total and grand total are emitted for drafts too — these
    # read the entries, so an unposted document has them before it has splits.
    inv_lines.append(f'\tinvoice_tax_total: {_fmt_money(tax_total, unit)}')
    inv_lines.append(f'\tinvoice_total: {_fmt_money(total, unit)}')

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
