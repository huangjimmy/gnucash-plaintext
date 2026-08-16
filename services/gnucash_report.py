#!/usr/bin/env python
"""Render a document by asking GnuCash to render it.

The page is GnuCash's own — by default the **Printable Invoice** report, which
is what File → Print Invoice draws: `Invoice #<id>` at the top left, the
customer on one side and your company on the other, then Date / Description /
Action / Quantity / Unit Price / Discount / Taxable / Total, and Net Price,
Tax, Total Price and Amount Due beneath. Nothing here reimplements a layout, a
column rule or a total; this module hands GnuCash a guid and asks it to draw.

Which report draws it is the caller's to choose — one of the five GnuCash
ships, or one the reader wrote — and that is the whole of this project's
customisation story, because a report is what a page here is. See
`render_document_html`.

**Guile runs inside this process.** `scm_init_guile()` on the already-loaded
libguile puts a Scheme interpreter in the same process that has the book open,
and because the Python bindings and Guile's are the same C library sharing the
same globals, `gnc-get-current-session` answers with the session Python
opened. Nothing is shelled out to and no book is opened twice.

That is what makes every supported build work, GnuCash 3.8 included. Driving
`gnucash-cli` would have left 3.8 out — it has none — and driving a standalone
Guile would have left every build out, because `qof-session-begin` is exposed
to Guile on no version. Both were tried; sharing the process is what works.

The two eras differ only in names, and the setup strings below hold them:
* 4.x/5.x load modules with `use-modules`; 3.8 needs `gnc:module-load` first;
* the report module is `(gnucash reports standard invoice)` on 4.x/5.x and
  `(gnucash report invoice)` on 3.8;
* the option API is `gnc-set-option` on 4.x/5.x, `gnc:option-set-value` on 3.8.

A stylesheet module is loaded on both, because a report is drawn through one
and a build with none registered fails inside `symbol->string` on a #f name —
which reads like a bug in the caller and is not.
"""
import contextlib
import html as html_escaping
import os
import re
import tempfile
from pathlib import Path

from infrastructure.guile import load_guile

# GnuCash's "Printable Invoice", the report its own Print Invoice uses.
PRINTABLE_INVOICE_GUID = '5123a759ceb9483abf2182d01c140e8d'

# Printable, Easy and Fancy Invoice are three `gnc:define-report` calls in one
# `invoice.scm`, differing only in their option defaults and sharing one
# `'renderer reg-renderer` — read out of the shipped file on 5.10 and 3.8,
# where the three guids are also identical.
#
# So they are one page as far as anything here needs to know, and both of the
# checks below belong to all three rather than to whichever one this tool
# picks by default:
#
#   * `reg-renderer` draws `gnc:html-make-generic-warning` — "No valid invoice
#     selected." — for a guid the book does not hold, with no `invoice-title`
#     div, which is what that check exists to catch;
#   * all three build their company and client blocks from the same
#     `make-company-table` / `make-client-table`, so a block missing from one
#     is a GnuCash this tool does not know rather than that report's design.
INVOICE_FAMILY_GUIDS = frozenset({
    PRINTABLE_INVOICE_GUID,
    '67112f318bef4fc496bdc27d106bbda4',   # Easy Invoice
    '3ce293441e894423a2425d7a22dd1ac6',   # Fancy Invoice
})

TAX_INVOICE_GUID = '0769e242be474010b4acf264a5512e6e'

# Loading Tax Invoice's module registers a second report beside it, measured
# on 5.10 and 3.8. It is reachable by name the moment the module is loaded, so
# it is checked and its options are set like the rest rather than being a
# report this tool made reachable and then left unguarded.
AUSTRALIAN_TAX_INVOICE_GUID = '3dbbc2584da64e7a8674355bc3fbfe3d'

# What each report this tool *advertises* writes for a real document and not
# for its "no invoice selected" page, so a page drawn for a guid the open book
# does not hold can be told apart from a document. Every one of these is a
# structure rather than a sentence, because the sentences are translated.
#
# Asked of the report that drew, so naming one changes nothing about whether
# it is checked. A report of the reader's own is deliberately absent: this
# project has no claim on someone else's markup, and what is asked of those is
# that something was drawn at all.
#
# Measured, per report, on GnuCash 5.10 and 3.8:
#
#   the invoice family  `reg-renderer` draws `gnc:html-make-generic-warning`
#                       with no heading div;
#   Tax Invoice         builds its page from an eguile template and writes
#                       neither that div nor that warning. Its empty page is a
#                       232-byte fragment — a DOCTYPE, an `<h2>`, one `<p>`,
#                       and closing tags for elements it never opened — where
#                       a real one is ~4kB opening `<html dir='auto'>` with a
#                       `<title>`. So `<title` is the thing it writes for a
#                       document and not otherwise.
_DREW_A_DOCUMENT = {
    **dict.fromkeys(INVOICE_FAMILY_GUIDS, 'class="invoice-title"'),
    TAX_INVOICE_GUID: '<title',
    AUSTRALIAN_TAX_INVOICE_GUID: '<title',   # same eguile machinery
}


# The era's names, worked out once per process — see `_dialect`.
_dialect_cache = None

# `.scm` files already loaded into this interpreter, mapped to the template
# guids each one registered, so a run printing a whole book loads each file
# once rather than once per document and still knows whose reports those are
# on every document after the first.
_loaded_report_files = {}


class DocumentNotRenderedError(RuntimeError):
    """GnuCash did not draw the document, and why.

    Its own class rather than a bare `RuntimeError` so the commands can turn
    it into the sentence it is written as. A refusal a reader cannot read
    tells them nothing about what to do next, which is why `print-invoice`
    already translates `UnwritableFigureError` the same way.
    """

# Loading the modern names first: a 4.x/5.x build has none of the 3.8 ones, and
# a 3.8 build has none of the modern ones, so whichever loads is this build's.
_MODERN_SETUP = '''
(use-modules (gnucash engine) (gnucash app-utils) (gnucash report))
(use-modules (gnucash reports standard invoice))
(use-modules (gnucash report stylesheets plain))
'''

_LEGACY_SETUP = '''
(use-modules (gnucash gnc-module))
(gnc:module-system-init)
(gnc:module-load "gnucash/engine" 0)
(gnc:module-load "gnucash/app-utils" 0)
(gnc:module-load "gnucash/report/report-system" 0)
(use-modules (gnucash report report-system))
(use-modules (gnucash report invoice))
(use-modules (gnucash report stylesheet-plain))
;; The report registry — `gnc-report-add`, which `gnc:make-report` calls, and
;; `gnc-report-find`. On 3.8 they are not in the report-system module but in
;; its SWIG module, so without this `gnc:make-report` looks broken when it is
;; only missing an import.
(use-modules (sw_report_system))
(use-modules (srfi srfi-1))
'''


# The book's `date_format` written the way QOF's own setting spells it.
#
# `date_format` reaches the document's posted and due dates only; every other
# date on the page — each entry's, each payment's, "printed on" — is written
# by `qof-print-date`, which reads this process-wide setting. GnuCash's GUI
# writes it at startup from its preference; a process that only loaded the
# library leaves it at `QOF_DATE_FORMAT_LOCALE`, so those dates followed the
# locale of whoever ran the command while the document's followed the book.
#
# Setting it from the book is what makes one page read one way. QOF takes a
# style and not a format string — `qof_date_format_set` "checks to make sure
# it's a legal value" and `QOF_DATE_FORMAT_CUSTOM` is the check printer's —
# so only these four can be matched. Values from `QofDateFormat` in
# `gnc-date.h`; the strings are what each style prints.
_QOF_DATE_STYLES = {
    '%Y-%m-%d': 3,      # QOF_DATE_FORMAT_ISO
    '%m/%d/%Y': 0,      # QOF_DATE_FORMAT_US
    '%d/%m/%Y': 1,      # QOF_DATE_FORMAT_UK
    '%d.%m.%Y': 2,      # QOF_DATE_FORMAT_CE
}


def _say_nothing(*_args, **_kwargs) -> None:
    """The `warn` a library caller who passed none gets."""


def _write_every_date_the_books_way(book, warn):
    """Point QOF at the book's `date_format`, and say so when it cannot be.

    Returns what QOF held before, for the caller to put back: it is a global
    of the whole process, and a command that printed one document should not
    leave every later one — or the next test in the file — reading its book's
    format.
    """
    from infrastructure.gnucash.engine import load_gnc_engine
    from infrastructure.gnucash.kvp import get_book_string_option

    wanted = (get_book_string_option(book, 'Business',
                                     'Fancy Date Format/custom') or '').strip()
    if not wanted:
        return None

    lib = load_gnc_engine()
    style = _QOF_DATE_STYLES.get(wanted)
    if style is None:
        # Settable, and said out loud. A format QOF has no style for is a
        # perfectly good thing to want on the document's own dates — it is
        # the reason `date_format` takes a format string at all — but the
        # rest of the page cannot be made to match it, and a reader who is
        # not told will see two formats on one document and think this
        # broken.
        warn(f'the book\'s date_format is {wanted!r}, which GnuCash has '
             f'no date style for — the document\'s date and due date '
             f'will read that way and every other date on the page will '
             f'follow this machine\'s locale. For one format throughout, '
             f'use one of: '
             + ', '.join(sorted(_QOF_DATE_STYLES)),
             key=('date_format', wanted))
        return None

    before = lib.qof_date_format_get()
    lib.qof_date_format_set(style)
    return before


def _restore_the_date_style(before) -> None:
    """Put QOF back where it was, for the reason `_make_current(None)` exists."""
    if before is None:
        return
    from infrastructure.gnucash.engine import load_gnc_engine

    load_gnc_engine().qof_date_format_set(before)


def _make_current(session) -> None:
    """Tell GnuCash which book everything else is about.

    Declared in `infrastructure/gnucash/engine.py` with every other C call, so
    one place decides the signatures — the ratchet test enforces it.
    """
    from infrastructure.gnucash.engine import load_gnc_engine

    load_gnc_engine().gnc_set_current_session(
        int(session.instance) if session is not None else None)


def _party(doc):
    """The customer or the vendor — whoever this document's owner is."""
    from gnucash.gnucash_business import GNC_OWNER_VENDOR

    owner = doc.GetOwner()
    return (owner.GetVendor() if owner.GetType() == GNC_OWNER_VENDOR
            else owner.GetCustomer())


def _extra_text(doc) -> tuple:
    """The two free-text blocks: the seller's, and this owner's.

    The seller's block states first what this format keeps and GnuCash's page
    has no row for — the GST and each PST registration number, which GnuCash
    has no field for at all and this tool writes into book options of its own.
    A Canadian invoice is required to state the GST/HST number, so leaving it
    to whatever the seller typed as free text would print an invoice that is
    not one. Then the free text itself.

    The owner's is a custom key on the customer or vendor, which the plaintext
    format already round-trips. Both print as they stand — no rule is inferred
    from them, which is what makes "a different website for this customer" a
    thing you write on the customer rather than a template you maintain.

    Only the `extra_text` keys are read out of either slot. The rest of what is
    in there is the book owner's own — a fiscal year end, a credit rating — and
    the document goes to the other party.
    """
    from infrastructure.gnucash.kvp import (
        get_book_custom_metadata,
        get_book_string_option,
        get_custom_metadata,
    )
    from services.invoice_renderer import split_pst_numbers

    book = doc.GetBook()
    lines = []
    gst = (get_book_string_option(book, 'Business',
                                  'Company GST Number') or '').strip()
    if gst:
        lines.append(f'GST: {gst}')
    for pst in split_pst_numbers(
            get_book_string_option(book, 'Business', 'Company PST Number')):
        lines.append(f'PST: {pst}')
    free = _free_text(get_book_custom_metadata(book))
    if free:
        lines.append(free)
    company = '\n'.join(lines)

    return company, _free_text(get_custom_metadata(_party(doc)) or {})


def _free_text(held: dict) -> str:
    """The `extra_text1:`, `extra_text2:` … lines a slot holds, in order.

    One key per line, for the reason an address is written that way: a value
    here is one line, there is no escape for a newline, and a quoted value
    does not span lines. So more lines is more keys.

    Numbered from one without brackets, unlike an address. These are ordinary
    custom keys — a name the book owner chose — and the brackets on an address
    mark a key the format itself owns.

    Ordered by the number and not by the key as text, which would put
    `extra_text10` between `extra_text1` and `extra_text2`.
    """
    numbered = []
    for key, value in held.items():
        found = re.fullmatch(r'extra_text(\d+)', str(key))
        if found and str(value):
            numbered.append((int(found.group(1)), str(value)))
    return '\n'.join(value for _, value in sorted(numbered))


def carry_slot_values_onto_the_fields(doc) -> None:
    """Put what the book holds where GnuCash's report reads it.

    A key that has since become a field of its own still sits in the slot of
    every book written before it was one — a bill's notes, a vendor's address.
    Every reader in this tool knows that and asks `held_value`; GnuCash's
    report does not and cannot, because it reads its own engine's fields. So a
    bill whose ledger states notes printed the line blank, and one whose
    vendor has an address printed none.

    Written onto the in-memory objects rather than into the file: printing
    opens the book read-only and never saves, so this is the same migration
    `held_value` performs for every other reader, done where the report can
    see it. A field that already says something is left alone — the field wins,
    as it does everywhere else.
    """
    from infrastructure.gnucash.kvp import get_custom_metadata, held_value

    held = get_custom_metadata(doc) or {}
    for key, current, setter in (('notes', doc.GetNotes(), doc.SetNotes),
                                 ('billing_id', doc.GetBillingID(),
                                  doc.SetBillingID)):
        value = held_value(doc, current, key, held)
        if value and value != current:
            doc.BeginEdit()
            setter(value)
            doc.CommitEdit()

    party = _party(doc)
    if party is None:
        return
    address = party.GetAddr()
    held = get_custom_metadata(party) or {}
    # Keyed `addr1`..`addr4` because that is what is *in* such a slot: this
    # reads the books written before these keys had setters, and those are the
    # names they used. Nothing writes an indexed key into a slot — a known key
    # goes to the field, and `set-book-key` refuses the name — so there is no
    # second spelling to look for here.
    for key, current, setter in (
            ('addr1', address.GetAddr1(), address.SetAddr1),
            ('addr2', address.GetAddr2(), address.SetAddr2),
            ('addr3', address.GetAddr3(), address.SetAddr3),
            ('addr4', address.GetAddr4(), address.SetAddr4),
            ('email', address.GetEmail(), address.SetEmail)):
        value = held_value(party, current, key, held)
        if value and value != current:
            party.BeginEdit()
            setter(value)
            party.CommitEdit()


def render_document_html(session, guid: str, company_extra='',
                         owner_extra='', report=None, report_file=None,
                         warn=None) -> str:
    """The open book's document `guid`, as HTML, rendered by GnuCash.

    `session` is the open GnuCash session — this book, in this process. It is
    registered as GnuCash's *current* session before rendering, because the
    report resolves the document from a guid string against the current book:
    without it the option silently stays unset and GnuCash draws its "no
    invoice selected" page. The Python bindings open a session but do not make
    it current, so we do.

    `report` names which of GnuCash's reports draws the page — by name, as the
    GUI lists it, or by its template guid. Five of GnuCash's own are
    registered and draw on every supported build: Printable Invoice, Fancy
    Invoice, Easy Invoice, Tax Invoice and Australian Tax Invoice — the last
    arriving with Tax Invoice's module rather than being asked for. The
    default is the Printable Invoice its own File → Print Invoice uses.

    `report_file` is a Scheme file loaded before the report is looked up, so a
    report of your own — `gnc:define-report` in a `.scm` of your writing — is
    registered by the time it is asked for and can then be named in `report`.
    That is GnuCash's own extension point, and it is the answer to "I want a
    different page": one written in the language the other reports are written
    in, drawn by the same machinery, rather than a second renderer living
    here.

    Every file this needs lives in one directory that is removed on the way
    out. Scheme is handed paths and not descriptors, so each of these would
    otherwise be a `mkstemp` whose fd nothing closes — five per document on
    4.x/5.x — and printing a whole book in one run is a documented flow
    (`print-invoice book '*' -o out/`), which would exhaust the descriptor
    limit partway through and fail as something unrelated.
    """
    if session is None:
        raise DocumentNotRenderedError(
            'no open session was given, so GnuCash cannot be told which book '
            'the document is in')
    # An empty string is nothing named, not a report called "". `--report
    # "$REPORT"` with the variable unset is how a shell script arrives here,
    # and the two readings disagreed: the lookup took the name branch and
    # matched nothing, while the refusal it produced filled the blank in with
    # the default's name — telling the reader that `Printable Invoice`, which
    # they had not typed and which is registered, is not registered. Settled
    # here, once, so everything downstream sees one answer.
    report = report or None
    report_file = report_file or None
    # Loading a report is not choosing one, so a file with nothing to name it
    # would be registered and then unused while GnuCash drew its stock page.
    # Refused here as well as at the two commands, because everything below
    # asks `report is None` to mean "this is the page this tool chose" — and
    # with this pair allowed it would have meant that while drawing the
    # Printable Invoice with both of its guards switched off.
    if report_file and not report:
        raise DocumentNotRenderedError(
            'a report file was given with no report named, so nothing would '
            'have drawn the page but GnuCash\'s default — name the report the '
            'file defines')
    lib = load_guile()
    # After `load_guile`, so a machine without an interpreter raises before the
    # global is set rather than leaving it naming a session the caller is about
    # to end — the state the `finally` below exists to avoid.
    _make_current(session)

    was = None
    try:
        # Inside the `try`, for the reason the comment above `_make_current`
        # gives: anything that raises between setting the current session and
        # entering this block leaves the global naming a session the caller is
        # about to end, and skips the restore below. Every date on the page is
        # written the book's way where GnuCash has a style for it, and a
        # sentence goes to stderr where it has not — see
        # `_write_every_date_the_books_way`.
        # Normalised once here rather than checked at each place that reports
        # something: a caller inside this repo always has a way to reach the
        # reader, and the default exists for a library caller who has not.
        was = _write_every_date_the_books_way(session.book,
                                              warn or _say_nothing)
        with tempfile.TemporaryDirectory(prefix='gnucash-render-') as work:
            return _render(lib, Path(work), guid, company_extra, owner_extra,
                           report=report, report_file=report_file, warn=warn)
    finally:
        # Both of these put a process-wide global back, and the date style is
        # the one that must not be skipped: a session pointer left set is read
        # by the next thing that asks for a *session*, while a date format
        # left set silently changes how every later document in the process is
        # dated — including the next test in the same pytest run. So the
        # restore is nested rather than sequenced, and survives a throw from
        # the unset above.
        try:
            # Unset on the way out: the caller is about to end this session,
            # and a global still naming it is a pointer to a book that no
            # longer exists for whatever runs next in this process. NULL is
            # the state before the first render — `gnc_get_current_session`
            # makes an empty one of its own if something asks — where
            # `gnc_clear_current_session` would end and destroy the session
            # the repository is itself about to end.
            _make_current(None)
        finally:
            _restore_the_date_style(was)


def _dialect(run, work: Path) -> tuple:
    """`(setter, find_report)` — the two names that differ between eras.

    Loading the report modules and asking the build which names it has is done
    once per process and remembered. Nothing about the answer depends on the
    document, and `print-invoice book '*' -o out/` — a documented way to print
    a whole book — renders every document in one run, so per-document that is
    a module load and four probes each, for an answer that cannot have
    changed.

    Which call sets an option is asked of the build, not inferred from which
    modules loaded: GnuCash 4.13 loads the modern module names and still wants
    the *old* option API, so a single "era" flag gets it wrong on exactly that
    build.
    """
    global _dialect_cache
    if _dialect_cache is not None:
        return _dialect_cache

    # Nothing is `define`d at top level: every eval is a self-contained
    # expression, because a `define` inside the catch wrapper's lambda binds
    # locally and is gone by the next eval.
    with contextlib.suppress(DocumentNotRenderedError):
        run(_MODERN_SETUP)
    # Whether the report is registered is the real test, not whether the eval
    # raised: a missing module leaves the report unregistered rather than
    # failing loudly.
    if not _registered(run, work):
        # Suppressed for the same reason the modern arm is. On a 4.x/5.x build
        # whose report modules are absent — a split package, a partial install
        # — `(use-modules (gnucash gnc-module))` is itself unbound, and letting
        # that out reports a missing `gnc:module-system-init`: a GnuCash 3.8
        # module name, on a build that never had one, in place of the sentence
        # below that says what is actually wrong.
        with contextlib.suppress(DocumentNotRenderedError):
            run(_LEGACY_SETUP)
        if not _registered(run, work):
            raise DocumentNotRenderedError(  # pragma: no cover - see below
                'GnuCash\'s Printable Invoice report is not registered on '
                'this build, so there is no report to render the document '
                'with')

    # Tax Invoice, which `--report` offers by name. Its siblings — Fancy and
    # Easy — live in the invoice module already loaded above and come with it;
    # this one is a module of its own and does not, so on 4.x and 5.x the name
    # named a report that was not in the registry. Measured: registered by the
    # stock setup on 3.8 alone, and absent on 5.10 and 4.13 until its module
    # is loaded.
    #
    # Both spellings tried, tolerantly and once per process. The era that owns
    # neither name is a build where Tax Invoice is refused, which is what it
    # already was — so a build without the report loses nothing, and no other
    # report's registration depends on this succeeding.
    for module in ('(gnucash reports standard taxinvoice)',
                   '(gnucash report taxinvoice)'):
        with contextlib.suppress(DocumentNotRenderedError):
            run(f'(use-modules {module})')

    setter = ('(lambda (o p n v) (gnc-set-option (gnc:optiondb o) p n v))'
              if _defined(run, work, 'gnc-set-option')
              else '(lambda (o p n v) (gnc:option-set-value '
                   '(gnc:lookup-option o p n) v))')
    # `gnc:make-report` answers with an id and the renderer wants the report
    # itself, so the id is looked up — by whichever name this build has.
    find_report = ('gnc-report-find'
                   if _defined(run, work, 'gnc-report-find')
                   else 'gnc:find-report')
    _dialect_cache = (setter, find_report)
    return _dialect_cache


def _render(lib, work: Path, guid: str, company_extra, owner_extra,
            report=None, report_file=None, warn=None) -> str:
    """The render itself, with `work` a directory to write through.

    **The page crosses from Scheme to Python as UTF-8, said on both sides.**
    Guile picks a port's encoding from the locale and replaces anything the
    locale cannot hold with `?` — silently, with no error and a zero exit:
    measured in the C locale, `(display "a…¥b" port)` writes `a?????b`. That a
    document survives today is incidental, because CPython's PEP 538 coercion
    turns the container's `C` into `C.UTF-8` before Guile is initialised; with
    `PYTHONCOERCECLOCALE=0`, or any non-UTF-8 `LANG`, a customer's name or a
    line description would arrive as question marks on the printed document.
    So the port is told, and the read is told.
    """
    out = work / 'document.html'
    errors = work / 'errors.txt'
    # Which template actually drew, written by the Scheme that resolved it.
    # Asked of the render rather than inferred from the flags: `--report` may
    # name any of the three reports that share one renderer, and "did the
    # caller type a name" is not the same question as "which page is this".
    drew = work / 'template.id'

    def run(scheme):
        """Evaluate, catching Scheme errors rather than letting them out.

        An uncaught Guile exception aborts the process it is embedded in —
        measured: a wrong argument inside the render took the whole `pytest`
        down with `guile: uncaught exception`. Caught here, a failure becomes
        a message this function can raise as a Python error.
        """
        # `#t` after the body because a lambda may not end on a definition,
        # and several of these evals define rather than compute.
        wrapped = (f'(catch #t (lambda () {scheme} #t)'
                   f' (lambda (key . args)'
                   f'   (call-with-output-file {_scheme_string(errors)}'
                   f'     (lambda (port)'
                   f'       (set-port-encoding! port "UTF-8")'
                   f'       (display (list key args) port)))))')
        # Said to be UTF-8 rather than left to the locale to guess — see
        # `infrastructure/guile.py`, where a report name came back with two
        # characters where one had been sent.
        lib.scm_eval_string(lib.scm_from_utf8_string(wrapped.encode('utf-8')))
        if errors.exists() and errors.read_text(encoding='utf-8').strip():
            message = errors.read_text(encoding='utf-8').strip()
            errors.unlink()
            raise DocumentNotRenderedError(
                # Room for the message to finish. Several of these are
                # sentences this module wrote, and the ambiguity one ends in
                # the list of guids it tells the reader to choose between —
                # cut at 300 that list was what went missing.
                f'GnuCash could not render the document: {message[:900]}')

    setter, find_report = _dialect(run, work)

    # A report of the caller's own, registered before it is looked for. This is
    # GnuCash's extension point rather than one invented here: a `.scm` calling
    # `gnc:define-report` is what every report GnuCash ships is, and one loaded
    # now is indistinguishable from them by the time `report` is resolved.
    #
    # Once per file per process, not once per document: `print-invoice book '*'`
    # renders every document in one run, and re-`load`ing the same file would
    # re-register the same report guid for each of them.
    # What *this call's* file registered, not every `.scm` the process has
    # loaded. The two are the same through either command — one `--report-file`
    # per invocation, one invocation per process — and differ only for a
    # library caller that loads file A, then names A's report while passing
    # file B: A's report then reads as GnuCash's and is given its treatment.
    # Keyed per call rather than accumulated because the question each guard
    # asks is "did the file this run was given register this?", and a union
    # over the process would answer a different one as the session went on.
    # `from_this_file` answers "did the file this run was given register
    # anything?", which is what the refusal below leans on. `readers_own`
    # answers "is this page one a reader wrote?", which is a wider question —
    # see the union below.
    from_this_file = set()
    if report_file:
        resolved = Path(report_file).resolve()
        if resolved not in _loaded_report_files:
            # What the registry held before and after, so the guids this file
            # registered are known rather than guessed — a page of the
            # reader's keeps its own options and is never refused for lacking
            # a `div` nobody asked its author for, whatever guid it chose.
            #
            # A set difference is the whole of it because **GnuCash refuses a
            # duplicate guid**: `gnc:define-report` checks the registry and
            # logs "One of your reports has a report-guid that is a duplicate"
            # rather than replacing what is there. Measured on 5.10 and 3.8 by
            # re-registering `5123a759…` — the template came back byte for
            # byte the one `invoice.scm` had registered, the registry the same
            # size, and the reader's report simply absent. So re-using a
            # shipped guid does not silently take that report over, and a page
            # drawn under one is GnuCash's own, which is what the difference
            # says. (README says to start from `invoice.scm`, so this is a
            # copy-paste away and worth knowing rather than assuming.)
            before = _registered_ids(run, work)
            try:
                run(f'(load {_scheme_string(resolved)})')
            except DocumentNotRenderedError as exc:
                # Named, and named as a *load* failure. Every other first-run
                # mistake here earns a sentence, and this is the likeliest of
                # them — a `.scm` that does not parse otherwise reported
                # "GnuCash could not render the document", pointing the reader
                # at their document instead of at their file.
                raise DocumentNotRenderedError(
                    f'the report file {resolved} could not be loaded, so no '
                    f'report of yours was registered: {exc}') from exc
            _loaded_report_files[resolved] = _registered_ids(run, work) - before
        from_this_file = _loaded_report_files[resolved]

    # Every guid any file has registered into this interpreter, not only this
    # path's. The same report reached by a second path — a copy, a symlink, a
    # relative spelling — registers nothing the second time, because GnuCash
    # refuses the duplicate guid; the difference across *that* load is empty,
    # and the reader's own page would then read as GnuCash's and be given its
    # treatment, warned about by name for lacking a block nobody asked its
    # author for. One `--report-file` per process makes that unreachable from
    # either command, and a library caller or a test can do it in one line.
    #
    # Safe to union because these guids only ever arrive from a file the
    # caller named: nothing GnuCash registers itself is in here.
    readers_own = set()
    for registered in _loaded_report_files.values():
        readers_own = readers_own | registered

    wanted = _report_id_expression(report, from_this_file)
    # The reports whose display options this tool sets — the same five it
    # advertises and checks, as they register themselves, sorted so the Scheme
    # it builds is the same string on every run.
    #
    # Nothing is subtracted for the reader's own reports because nothing can
    # collide: a `.scm` registering
    # one of these guids exactly is refused by GnuCash as a duplicate
    # (measured), and one registering a different case of it is a different
    # entry that is not in this list. Either way a page of theirs draws under
    # a guid that is not here, and none of these switches is set on it.
    advertised = ' '.join(_scheme_string(g) for g in sorted(_DREW_A_DOCUMENT))
    # Four of the report's own switches, and nothing else — written as six
    # `try-set` lines because the last of them has three spellings across the
    # reports and the eras. Two carry fields this format has and GnuCash ships
    # hidden; two take out defaults of the report's that are wrong for a
    # document this tool prints:
    #
    #   Display/Invoice Notes            the document's `notes:`
    #   Display/Company contact          the book's `contact:`, printed by
    #                                    GnuCash as "Please direct all
    #                                    enquiries to <name>"
    #   Display/Use Detailed Tax Summary one row per tax account — `GST` and
    #                                    `PST` by name and by amount, rather
    #                                    than one combined `Tax` figure. A
    #                                    Canadian invoice has to state the
    #                                    GST/HST *amount*, and GST + PST added
    #                                    together does not state it. This
    #                                    format has always carried the
    #                                    breakdown per tax account, and the
    #                                    plaintext render still writes it.
    #   Notes/Extra Notes                the same row under the page and name
    #   Notes/Extra notes                Tax Invoice gives it. That report is
    #                                    a module of its own and spells its
    #                                    options its own way, so the `Display`
    #                                    line below is a no-op there and the
    #                                    patronage sentence was printing on
    #                                    every Tax Invoice page.
    #
    #                                    Two spellings because GnuCash changed
    #                                    the capital: `Extra notes` on 3.8,
    #                                    `Extra Notes` on 4.13 and 5.10. Each
    #                                    build takes the one it has and
    #                                    ignores the other, which is what
    #                                    `try-set` is for — and the difference
    #                                    was found by the test failing on 3.8
    #                                    alone after the 5.10 spelling fixed
    #                                    it there.
    #   Display/Extra Notes              emptied. Its default is the literal
    #                                    "Thank you for your patronage!",
    #                                    which the report appends to every
    #                                    page — uninvited on an invoice of
    #                                    yours, and untrue on a bill, where it
    #                                    thanks the supplier for their
    #                                    patronage of you. It is a text option
    #                                    and not a hidden row, which is how it
    #                                    escaped the audit of what gets set.
    #
    # `try-set` and not `set-opt` for every one, and it asks before it writes.
    #
    # A row missing on an older GnuCash, or on a report that spells it
    # differently, must not cost that build its document — and the two eras
    # fail differently, so catching is not enough on its own. On 3.8 the
    # legacy setter takes `#f` from the lookup and raises, which a `catch`
    # does hold. On 4.13 and 5.10 nothing raises: GnuCash writes "Attempt to
    # write non-existent option <section>/<name>" to fd 2 and carries on, so
    # the `catch` catches nothing and the line stands.
    #
    # Measured on 5.10 before this `if`: the *default* page logged two of them
    # per document — the two `Notes/` spellings, which no invoice-family
    # report has — so `print-invoice book '*'` over fifty invoices wrote a
    # hundred lines of GnuCash internals to the stream the dropped-block
    # warning is written to. That warning exists so a missing GST number does
    # not leave silently, and this buried it.
    #
    # `gnc:lookup-option` answers on all three eras, which the required write
    # above already depends on.
    drawing = f'''
(let* ((set-opt {setter})
       (try-set (lambda (o p n v)
                  (if (gnc:lookup-option o p n)
                      (catch #t (lambda () (set-opt o p n v))
                        (lambda ignored #f)))))
       (template-id {wanted}))
  (if (not template-id)
      (error (string-append
               "no report of that name is registered on this build: "
               {_scheme_string(report if report else 'Printable Invoice')}
               " — reports register their English names, so a localized "
               "GnuCash lists a translated one that is not this; naming the "
               "report by its guid works in every language")))
  (call-with-output-file {_scheme_string(drew)}
    (lambda (port)
      ;; Said, like every other port here: this is read back as UTF-8, and a
      ;; port left on the locale writes whatever the locale can hold.
      (set-port-encoding! port "UTF-8")
      (display template-id port)))
  (let ((options (gnc:make-report-options template-id)))
    ;; The document. Every report that prints one takes it here, so this is
    ;; the one write that is not optional — and a report without the option is
    ;; a report that cannot be told which document to draw, which is said as a
    ;; sentence.
    ;;
    ;; Asked before writing rather than caught after, because the two eras
    ;; fail differently and neither answer is one to hand a reader: on 3.8 the
    ;; legacy setter takes `#f` from the lookup and dies in `vector-ref`,
    ;; while 4.13 and 5.10 print "Attempt to write non-existent option" to
    ;; stderr and carry on — so the page drew, exit 0, `✓ Wrote 1 invoice(s)`,
    ;; and the document the reader named never reached the report at all.
    ;; `gnc:lookup-option` answers on all three, measured.
    (if (not (gnc:lookup-option options "General" "Invoice Number"))
        (error (string-append
                 "that report does not print a document: "
                 {_scheme_string(report if report else 'Printable Invoice')}
                 " — it has no General / Invoice Number option, so there is "
                 "no way to tell it which invoice or bill to draw")))
    (set-opt options "General" "Invoice Number" {_scheme_string(guid)})
    ;; The four display switches, and only for the reports this tool
    ;; advertises. A report of the reader's own decides its own page: one
    ;; declaring an `Extra Notes` of its own had it silently blanked, which is
    ;; the same overreach as demanding a `div` of it.
    (if (member template-id (list {advertised}))
        (begin
          (try-set options "Display" "Invoice Notes" #t)
          (try-set options "Display" "Company contact" #t)
          (try-set options "Display" "Use Detailed Tax Summary" #t)
          (try-set options "Display" "Extra Notes" "")
          (try-set options "Notes" "Extra Notes" "")
          (try-set options "Notes" "Extra notes" "")))
    (let* ((report (gnc:make-report template-id options))
           (html (gnc:report-render-html ({find_report} report) #t)))
      (call-with-output-file {_scheme_string(out)}
        (lambda (port)
          ;; Not the locale's: see this function's docstring.
          (set-port-encoding! port "UTF-8")
          (display html port)))
      ;; The registry `gnc:make-report` added it to holds it for the life of
      ;; the process, and printing a whole book is one process making one
      ;; report per document. Removed where the build has a way to; `catch`
      ;; because the name differs and 3.8 has none, and a report left behind
      ;; costs memory rather than correctness.
      (catch #t (lambda () (gnc-report-remove-by-id report)) (lambda i #f)))))
'''
    try:
        run(drawing)
    except DocumentNotRenderedError as exc:
        # A file that registered nothing is the likely reason a name was not
        # found, and Python is holding the evidence that Scheme is not.
        # README says to start from GnuCash's `invoice.scm`, which carries the
        # Printable Invoice's guid, and GnuCash declines a definition that
        # duplicates one already registered — so the reader's report is absent
        # and the name they gave it matches nothing. Left to the Scheme's own
        # sentence they were told their English name might be a translation,
        # which sends them to look at their locale for a problem that is in
        # their `.scm`.
        # Onto the refusal it explains and no other. A `.scm` of shared
        # helpers that defines no report is a legitimate thing to load beside
        # `--report "Fancy Invoice"`, and `report_file and not readers_own` is
        # true of it — so attached to any failure this blamed a guid for a
        # render that went wrong somewhere else entirely.
        #
        # Both causes named, because from here they are the same fact. A file
        # that defines no report and a file whose report GnuCash declined look
        # identical: an empty difference. Asserting the second told the writer
        # of the first to go and change a guid they do not have.
        if (report_file and not from_this_file
                and 'no report of that name' in str(exc)):
            raise DocumentNotRenderedError(
                f'{exc} — and {Path(report_file).name} registered no report '
                f'at all, so nothing in it can be named: either it defines '
                f'none, or its report-guid duplicates one GnuCash has '
                f'already registered, which GnuCash refuses. A file copied '
                f'from one of GnuCash\'s own reports needs a guid of its '
                f'own.') from exc
        raise

    text = out.read_text(encoding='utf-8') if out.exists() else ''
    if not text.strip():
        raise DocumentNotRenderedError(
            f'GnuCash drew nothing at all for guid {guid}')

    # Asked for a document the current book does not hold, the Printable
    # Invoice draws a page all the same: "No valid invoice selected. Click on
    # the Options button and select the invoice to use." Told apart by the
    # heading div, which that report writes for a real document on every
    # version and in every language, where the sentence is neither.
    #
    # Only for that report. A report of the reader's own writes whatever its
    # author decided, and this project has no business requiring a particular
    # `div` of it — a page it drew is the page they asked for. What is checked
    # for those is that something was drawn, above.
    # Which report drew, not whether one was named. `--report "Printable
    # Invoice"` is the same page as naming nothing, and Easy and Fancy are
    # that page's siblings from the same file and the same renderer — so all
    # three owe both of the checks below, and keying them on "did the caller
    # type a name" let `--report "Printable Invoice"` write GnuCash's "No
    # valid invoice selected" warning to a PDF and report success.
    #
    # The file exists by the time this runs: the Scheme writes it immediately
    # after resolving the template and before drawing anything, and a failure
    # anywhere in that expression raises out of `run` rather than arriving
    # here. Read without a fallback for that reason — a missing file would be
    # a state this function cannot reach, and inventing an answer for it would
    # only decide which guards a machine in that state silently loses.
    # Both spellings kept: the registry distinguishes case and the sets of
    # guids this module carries are written in lower case, so whose report it
    # is is asked of the id as registered, and which report it is of the id
    # folded.
    registered_as = drew.read_text(encoding='utf-8').strip()
    drawn_by = registered_as.lower()
    # A guid the reader's own `.scm` registered is theirs, whichever guid it
    # is — and that is a real question rather than a formality, because a
    # `.scm` can register a guid this module names. Not by taking one exactly:
    # GnuCash refuses that as a duplicate, measured, which is why
    # `a_report_reusing_a_shipped_guid.scm` draws GnuCash's page and not its
    # own. By taking one in a different case: the registry compares with
    # `equal?`, so `5123A759…` is a second entry beside the Printable Invoice
    # — `a_report_reusing_a_shipped_guid_in_caps.scm` — and the id written out
    # above is that spelling, matching nothing in the lowercase sets below.
    #
    # So this decides whose page it is, and everything after it follows: their
    # page keeps its own options, is not refused for lacking a `div` its
    # author never wrote, and is never told the book does not hold a document
    # the book does hold.
    ours = registered_as not in readers_own
    of_the_invoice_family = ours and drawn_by in INVOICE_FAMILY_GUIDS

    # The boundary here is "a report this tool knows", not "a report of
    # GnuCash's": a shipped report absent from `_DREW_A_DOCUMENT` gets no
    # check either, because there is nothing measured to check it against.
    # Nothing reaches that today — the five are every report a stock run has
    # registered — but `AUSTRALIAN_TAX_INVOICE_GUID` is here because loading
    # one module registered a report nobody asked for, so a GnuCash that adds
    # a sixth would land in this branch rather than being refused. What that
    # costs is this check, not the page: it draws, and its blocks are still
    # left alone as any unknown report's are.
    drew_a_document = _DREW_A_DOCUMENT.get(drawn_by) if ours else None
    if drew_a_document and drew_a_document not in text:
        raise DocumentNotRenderedError(
            f'GnuCash rendered no document for guid {guid} — the open book '
            f'does not hold a document with that guid')
    # Required of the family, which all build these two blocks from the same
    # `make-company-table` / `make-client-table`: a block missing from one of
    # them is a GnuCash this tool does not know, not that report's design, and
    # a Canadian invoice printed without its registration numbers is not an
    # invoice whichever of the three drew it.
    #
    # Any other report writes whatever its author decided, and this project
    # has no business refusing it for not having a `div` nobody asked its
    # author for. `company_extra` is non-empty for any book carrying a GST or
    # PST number, so that refusal would have met the reader most likely to
    # want a page of their own on their first run. Where the blocks are there
    # the numbers still go in; see `_with_extra_row`.
    #
    # A report of GnuCash's that has nowhere to put them says so out loud.
    # Tax Invoice is the case: this tool names it in `--report`, loads its
    # module on purpose and documents it, and it has neither block — so a book
    # carrying a GST number prints a document stating none, exit 0, with only
    # README to have warned. That is the outcome `_with_extra_row`'s docstring
    # calls unacceptable, and refusing is not the answer either, since the
    # report is doing what it was written to do. Nothing is said for a report
    # of the reader's own: the numbers are on the book, and their page is
    # theirs to lay out.
    def dropped(block, missing, block_was_there):
        # A page with no such block at all is a page laid out some other way,
        # and for a report of the reader's own that is their business — the
        # numbers are on the book and their report can read them. A page that
        # *has* the block and cannot hold the row is a different thing: they
        # kept `class="company-table"`, which is the very signal README uses
        # to say the registration numbers come with you, and then restructured
        # what is inside it. Silence there drops a GST number from a reader
        # who has every reason to believe it is on the page.
        if warn is None:
            return
        if not ours and not block_was_there:
            return
        lines = missing.splitlines()
        # Keyed on the report and the block, not on the sentence. The sentence
        # names what was dropped, and for the client block that is *this
        # owner's* text — so keying on it would say the same thing once per
        # customer, which is the flood the sink exists to stop.
        # "no document in this run", not "the printed document". It is said
        # once for the whole run, and the seller's block is the same on every
        # document — but the owner's is that owner's, so the line quoted is
        # the first one dropped and the others are not named. A sentence about
        # one document would have read as though only that one lost anything.
        # `report` is a name here, never None: with no `--report` the page is
        # the Printable Invoice, which is of the family, which makes the block
        # required — so that path refuses above rather than arriving here.
        warn(f'{report} has '
             + (f'a {block.split("-")[0]} block with no table in it to put '
                f'this on' if block_was_there
                else f'no {block.split("-")[0]} block to put this on')
             + f', so no document printed in this run states it. '
             f'First dropped: {lines[0][:80]}'
             + (f' (and {len(lines) - 1} more on that document)'
                if len(lines) > 1 else ''),
             key=(report, block))

    text = _with_extra_row(text, 'company-table', company_extra,
                           required=of_the_invoice_family, on_drop=dropped)
    return _with_extra_row(text, 'client-table', owner_extra,
                           required=of_the_invoice_family, on_drop=dropped)


def _scheme_string(text) -> str:
    """A Python string as a Scheme literal, quotes and backslashes escaped.

    Everything interpolated into an eval goes through this. A report name or a
    path comes from the command line, and one carrying a `"` would otherwise
    end the literal and leave the rest of it being read as code.

    A backslash costs more than a wrong answer. `--report 'back\\slash'`
    interpolated raw makes `"back\\slash"`, whose `\\s` is not an escape Guile
    knows, and that is a *reader* error rather than an evaluation one — so the
    `catch` in `_render`, which wraps the expression being read, never runs.
    Measured: the uncaught exception took the whole `pytest` process down
    mid-file, which is the same abort the module docstring describes and the
    reason nothing here lets a Guile error out.

    So both characters are escaped, and neither is exotic: `\\` is a directory
    separator on the platform this may yet run on, and a report named
    `Acme "Ltd" Invoice` is a name somebody types.
    """
    escaped = _as_text(text).replace('\\', '\\\\').replace('"', '\\"')
    return f'"{escaped}"'


def _as_text(value) -> str:
    """A string from the command line as text, whatever the locale made of it.

    Python decodes `sys.argv` with the filesystem encoding and the
    `surrogateescape` handler, so under a non-UTF-8 locale a byte it cannot
    decode becomes a lone surrogate rather than a character. `--report
    "Facture améliorée"` under `LC_ALL=C` is then a string that cannot be
    encoded at all: measured, `UnicodeEncodeError: surrogates not allowed`,
    as a traceback, from a reader typing the name their own GnuCash showed
    them.

    The bytes are still there — that is what `surrogateescape` is for — so
    they are taken back out and read as UTF-8, which is what a terminal sends
    whatever `LC_ALL` claims. `errors='replace'` for bytes that are not UTF-8
    either: a name that arrives as `?` is refused by a sentence naming what
    arrived, where raising here is a traceback for a name nobody can fix.
    """
    text = str(value)
    if any('\udc80' <= character <= '\udcff' for character in text):
        return os.fsencode(text).decode('utf-8', 'replace')
    return text


def _report_id_expression(report, from_this_file) -> str:
    """Scheme evaluating to the template id to draw, or `#f` if there is none.

    `from_this_file` is the guids the caller's `--report-file` registered, and
    is used only to say what to do about a guid two entries answer to — see
    `_guid_collision_remedy`. Empty is an ordinary value for it, being what a
    run with no `--report-file` passes; it is required rather than defaulted
    because the one caller always knows it, and a default would be a second
    way to say the same thing that no run takes.

    A guid is used as it stands. A name is looked up in the registry, so
    `--report "Fancy Invoice"` means what it reads as — and so does the name
    of a report the caller registered from a `.scm` of their own a moment
    earlier.

    **The name is the one the report registers itself under, which is
    English.** `gnc:define-report` stores `'name (N_ "Printable Invoice")`,
    and `N_` only marks the string for extraction — GnuCash applies `G_` when
    it draws its menus, so a localized GnuCash lists `Facture améliorée`
    while the registry still says `Fancy Invoice`. Whoever types what their
    GUI showed them gets the refusal below, so it says as much and points at
    the guid, which is the same on every build and in every language.

    Matched on the whole name and not a prefix: `Invoice` is a prefix of
    several of the reports GnuCash ships, and drawing the wrong one of those
    is a different document with nothing saying so.

    **A name two reports answer to is refused**, naming both ids, for the
    same reason. `gnc:report-templates-for-each` walks a hash, so keeping the
    first match hands the reader whichever the hash happened to yield — and
    the way to end up here is to write a `.scm` that calls its own report
    `Fancy Invoice`, which is a natural thing to do when the intent is to
    replace that page and leaves the two indistinguishable on the command
    line. A guid says which, and the refusal says so.
    """
    if report is None:
        return _scheme_string(PRINTABLE_INVOICE_GUID)
    # Dashes taken out before asking whether this is a guid, because that is
    # the shape `uuidgen` prints — `b0dcb0dc-b0dc-b0dc-b0dc-b0dcb0dcb0dc`,
    # 36 characters. Matched at 32 only, a reader who pasted what they
    # generated fell to the *name* branch and was told no report of that name
    # is registered and that a localized GnuCash lists translated names: an
    # answer about translation for something plainly a guid.
    #
    # What this can take for a guid is anything whose non-dash characters are
    # 32 hex digits, wherever the dashes fall — so a report *named*
    # `Deadbeef-Deadbeef-Deadbeef-Deadbeef` would be read as one and refused
    # for not being registered under that guid. Nothing shorter is safe
    # without deciding that only `uuidgen`'s exact 8-4-4-4-12 counts, and a
    # name of 32 hex letters is a stranger thing to have written than a guid
    # spaced some other way is to have pasted.
    typed = str(report)
    undashed = typed.replace('-', '')
    if re.fullmatch(r'[0-9a-fA-F]{32}', undashed):
        report = undashed
        # Matched without regard to case, and answering with the spelling the
        # report registered under — which is what everything downstream needs.
        #
        # `gnc:find-report-template` is a `hash-ref` compared with `equal?`,
        # so it takes only an exact match, and neither case is the safe guess:
        # GnuCash's own reports register lowercase guids, while a `.scm` of
        # the reader's registers whatever they wrote, and `uuidgen` on macOS
        # prints uppercase. Looking up what was typed refused `--report
        # 5123A759…` for the default report; lowercasing what was typed
        # refuses `'report-guid "B0DC…"` for theirs. A guid is hex, where case
        # carries no meaning at all, so neither refusal is telling the reader
        # anything true.
        #
        # Through the registry either way, and not straight to
        # `gnc:make-report-options`: a guid returned as it stands makes this
        # branch always truthy, so one nothing is registered under skipped the
        # refusal below and died inside `set-opt` on a `#f` options object, as
        # a raw `wrong-type-arg` naming none of what the reader typed.
        #
        # Every match collected and more than one refused, exactly as the name
        # branch does, and for the reason the two comments above give: two
        # registry entries can differ only in the case of their guid, because
        # the registry compares with `equal?` and this lookup does not. Kept
        # to the first the hash yielded, `--report 5123a759…` beside a `.scm`
        # registering `5123A759…` resolved two ways — the same command
        # splicing the registration numbers in or not, and enforcing the
        # heading check or not, a different document each way with nothing
        # saying which.
        # Both sides, not just the one that was typed. The registry keeps an
        # id exactly as the report registered it — dashes as much as case,
        # for the same `equal?` reason `_registered_ids` gives — so a `.scm`
        # saying `'report-guid "7cd07cd0-7cd0-…"` was unnameable by *either*
        # spelling: dashed, the comparison saw a stripped argument against a
        # dashed key; undashed, a stripped key was never made. Both refused,
        # and with the sentence about translated names, for a string plainly
        # a guid.
        # Compared stripped, quoted as typed. Every other refusal on this path
        # names what the reader wrote, and a message about the guid they gave
        # should not show them a spelling they did not use.
        return _one_matching_template(
            f'(and (string? id)'
            f'     (string-ci=? {_without_dashes("id")} '
            f'                  {_scheme_string(report)}))',
            'the guid', typed,
            _guid_collision_remedy(from_this_file, undashed))
    # Every match collected rather than the first kept, so two reports of one
    # name is a sentence instead of a coin toss. Written with `set!`, `null?`
    # and a named `let` and nothing from SRFI-1 or `(ice-9 …)`: this evaluates
    # on GnuCash 3.8's Guile 2.2 as well as 3.0, and only the report modules
    # are known to be loaded.
    # `string?` before `string=?`, because a template's name need not be one.
    # `gnc:define-report` refuses a definition with no `report-guid` and
    # accepts one with no `'name`, so a `.scm` that forgot it registers a
    # template whose name is `#f` — a plausible first attempt from exactly the
    # reader this flag is for. `(string=? #f "…")` then raises, and because
    # the walk visits every template, *any* later `--report <name>` in that
    # process died as a raw `wrong-type-arg` rather than a sentence about the
    # name it was asked for.
    return _one_matching_template(
        f'(let ((nm (gnc:report-template-name template)))'
        f'  (and (string? nm) (string=? nm {_scheme_string(report)})))',
        'the name', report,
        'name the one you mean by its guid instead')


def _without_dashes(expression: str) -> str:
    """Scheme reducing the string `expression` to its non-dash characters.

    `string->list`, `list->string`, `reverse` and `char=?` and nothing else,
    so it evaluates on GnuCash 3.8's Guile 2.2 as well as 3.0 — `string-delete`
    is SRFI-13 and only the report modules are known to be loaded.
    """
    return (f'(let strip ((rest (string->list {expression})) (kept (list)))'
            f'  (if (null? rest)'
            f'      (list->string (reverse kept))'
            f'      (strip (cdr rest)'
            f'             (if (char=? (car rest) #\\-)'
            f'                 kept'
            f'                 (cons (car rest) kept)))))')


def _guid_collision_remedy(from_this_file, undashed: str) -> str:
    """What to do when two registry entries answer to one guid.

    Two escapes, and the message offers whichever it can name:

    * **by name**, when the two reports are named differently — which they
      usually are, since the collision is between spellings of a guid and not
      of a name. This is the cheap one, and it keeps the reader's report file
      loaded, which they presumably want;
    * **by not loading the file**, which is the only way out when the names
      collide too.

    The offending guid is named outright rather than described by position.
    `matches` is built by walking a hash, so "the second of these" is
    whichever the hash happened to yield — the exact non-determinism the
    ambiguity refusal exists to prevent, and on a build that ordered them the
    other way it would have pointed at GnuCash's own report, which there is
    no file to stop loading.

    Named from the file's registrations that actually collide, not from all
    of them. A `.scm` holding several reports is ordinary, and listing the
    innocent ones sends the reader looking at reports that have nothing to do
    with it — and puts an unbounded list ahead of the matched ids, which are
    what the message's length limit was widened to keep.

    And the *fix* is named beside the two escapes, because neither is one. A
    name gets today's document printed and leaves the guid ambiguous for
    every run after it; not loading the file throws the report away. What
    ends it is the reader giving their own report a guid of its own — always
    possible here by construction, since every guid named is one their `.scm`
    chose. `_render` gives the same advice on the sibling refusal, where a
    duplicate guid registered nothing at all.

    The sentence built when nothing of the file's collides is not reachable
    through either command: one `--report-file` per invocation and one
    invocation per process, so the file named is the only file loaded and a
    collision is necessarily with something in it. A library caller can reach
    it — load file A, then name A's colliding guid while passing file B — and
    the sentence is right for them too, being the half that holds in every
    case.
    """
    colliding = sorted(guid for guid in from_this_file
                       if guid.replace('-', '').lower() == undashed.lower())
    # "every one of them" and not "both": a `.scm` taking a shipped guid in
    # capitals *and* in dashes makes three entries one spelling matches, and
    # the list below would then name three under a sentence saying two.
    escape = ('they differ only in case or dashes, so every spelling of it '
              'matches every one of them — ask for the one you want by its '
              'name instead')
    if not colliding:
        return escape
    return (f'{escape}, or stop loading the report file that registered '
            f'{", ".join(colliding)}. A report copied from one of GnuCash\'s '
            f'own needs a guid of its own, not that one in another case')


def _one_matching_template(test: str, what: str, wanted, remedy: str) -> str:
    """Scheme evaluating to the one template id `test` matches.

    `#f` if none matches, and an `error` naming every id if more than one
    does — for a name and for a guid alike, since both are looked up by
    walking `gnc:report-templates-for-each`, which walks a hash. Keeping the
    first match hands back whichever the hash happened to yield, and the two
    candidates are two different documents with nothing on the page saying
    which drew.

    `remedy` is what to do about it, and the two branches do not share one.
    A name that two reports answer to is escaped by naming a guid instead.
    A *guid* that two answer to is not escaped that way: they collided
    because they are equal once case and dashes are set aside, so every
    spelling the reader could type — including either id quoted back at them
    — comes back here. Their names are the way out of that one, since a
    collision between guid spellings usually leaves the names distinct; where
    those collide too, only not loading the file does. See
    `_guid_collision_remedy`.

    Written with `set!`, `null?` and a named `let` and nothing from SRFI-1 or
    `(ice-9 …)`, so it evaluates on GnuCash 3.8's Guile 2.2 as well as 3.0,
    where only the report modules are known to be loaded.
    """
    # Through `_scheme_string` like everything else that reaches an eval,
    # `what` and `remedy` included. Both are call-site literals today, and the
    # invariant is what stops the next one that is not from putting a bare `"`
    # into a Scheme literal — a *reader* error, which the `catch` in `_render`
    # is not there for.
    opening = _scheme_string(f'more than one report is registered under '
                             f'{what} ')
    advice = _scheme_string(f' — {remedy}:')
    return (f'(let ((matches (list)))'
            f'  (gnc:report-templates-for-each'
            f'    (lambda (id template)'
            f'      (if {test} (set! matches (cons id matches)))))'
            f'  (cond ((null? matches) #f)'
            f'        ((null? (cdr matches)) (car matches))'
            f'        (else'
            f'         (error'
            f'           (string-append'
            f'             {opening}'
            f'             {_scheme_string(wanted)}'
            f'             {advice}'
            f'             (let loop ((rest matches) (acc ""))'
            f'               (if (null? rest)'
            f'                   acc'
            f'                   (loop (cdr rest)'
            f'                         (string-append acc " "'
            f'                           (object->string (car rest))))))))))) ')


def _block_span(page: str, block: str):
    """`(start, end)` of the `<div class="…">` carrying `block`, or `None`.

    Found by counting `<div` against `</div>` from the opening tag, because
    these blocks contain divs of their own — the company name is one — so the
    first `</div>` after the anchor is not the block's. Well-formed markup is
    assumed, which is what GnuCash's html document writer emits.

    It exists so that what is spliced into a block goes *into* it. Bounded
    only by the anchor, the search for a place to put a row runs off the end
    of the block and into whatever comes next.
    """
    at = page.find(f'class="{block}"')
    if at < 0:
        return None
    start = page.rfind('<div', 0, at)
    if start < 0:
        return None

    depth = 0
    where = start
    while where < len(page):
        opening = page.find('<div', where)
        closing = page.find('</div>', where)
        if closing < 0:
            return None                     # unbalanced: no block to speak of
        if 0 <= opening < closing:
            depth += 1
            where = opening + len('<div')
        else:
            depth -= 1
            if depth == 0:
                return (start, closing)
            where = closing + len('</div>')
    return None


def _with_extra_row(page: str, block: str, text: str,
                    required: bool = True, on_drop=None) -> str:
    """`text` as one more row at the end of the report's `block`.

    The report builds its page in Scheme and has no template file to copy and
    edit, the way its Tax Invoice sibling does — so free text of ours is added
    to what it drew rather than woven into how it draws. It goes in as a row
    of the block it belongs beside: the seller's under the company's address,
    the owner's under theirs.

    The two blocks are `<div class="company-table">` and `class="client-table">`,
    each wrapping one table. Measured identical on GnuCash 3.8 and 5.10 —
    the whole page differs between them only in `cellspacing="0"` against
    `"0.0"` and an ellipsis spelled `...` against `…`.

    Nothing to add leaves the page alone.

    Something to add and nowhere to put it depends on whose layout it is,
    which is what `required` says.

    On the page this tool prints by default it **refuses the document**,
    because the seller's block carries the GST and each PST registration
    number — a Canadian invoice is required to state them, and one printed
    without them is not an invoice. A GnuCash newer than this project supports
    could rename either div, and the choice there is between a message naming
    what is missing and a document that looks right, goes to a customer, and
    is quietly non-compliant. Every supported build has both blocks, so that
    is reachable only on an eleventh.

    On a page the reader asked for by name it leaves the page alone, because
    the absence is then the report's own design rather than a build this tool
    does not know. Measured on GnuCash 5.10 and 3.8, of the reports `--report`
    offers:

    | report | the two blocks |
    |---|---|
    | Printable Invoice (the default) | both, each with a `</tbody>` |
    | Fancy Invoice | both |
    | Easy Invoice | both |
    | Tax Invoice | neither |
    | Australian Tax Invoice | neither |

    So the numbers still reach Fancy and Easy — the same page furniture drawn
    from the same `invoice.scm`, and a book carrying a GST number would
    otherwise have lost it by choosing a different one of GnuCash's own. The
    two tax invoices build their page from an eguile template instead and
    state the seller's details their own way; a reader who chose one gets that
    report, and is told on stderr what it had nowhere to put.
    """
    if not text:
        return page
    # Inside the block's own `<div>`, not merely after it starts. The first
    # `</tbody>` following the anchor is the right one only while the block
    # wraps a table — true of every report GnuCash ships, and not obliged of
    # anyone else's. A reader who keeps `company-table` and writes the seller
    # as text, with the line items in a table below, has no `</tbody>` of
    # their own: the row went into the *line items*, and neither the refusal
    # nor the warning fired, because both ask whether the anchor was found.
    # Measured on 5.10 with such a report — the GST and PST numbers came out
    # as the last row of the invoice's lines.
    span = _block_span(page, block)
    close = page.find('</tbody>', *span) if span else -1
    if close < 0:
        if not required:
            # Not an error, and not silent either — see `_render`, which
            # decides what to say from whether the block was there at all.
            #
            # `span is None` is also what an unbalanced `<div>` nesting gives,
            # which would read here as "no such block" and stay quiet for a
            # report of the reader's own. Every page goes through GnuCash's
            # html document writer, which closes what it opens, so a report
            # cannot be in that state — and a page that was would have worse
            # troubles than a missing row.
            if on_drop is not None:
                on_drop(block, text, span is not None)
            return page
        raise DocumentNotRenderedError(
            f'GnuCash drew the document with no `{block}` block able to hold '
            f'this, so it would have printed without it: {text[:120]!r}. This '
            f'build lays its page out differently from the ten this was '
            f'measured against.')

    body = '<br />'.join(html_escaping.escape(line)
                         for line in str(text).split('\n'))
    # `maybe-align-right`, the class the report puts on its own rows in these
    # two blocks: it is what right-aligns the company side and leaves the
    # client side alone, so our row sits where the rows above it do.
    row = (f'<tr><td><div class="maybe-align-right {block}-extra">'
           f'{body}</div></td></tr>\n')
    return page[:close] + row + page[close:]


def _defined(run, work: Path, symbol: str) -> bool:
    """Whether this build has `symbol`, asked of it rather than assumed."""
    probe = work / f'{symbol}.flag'
    try:
        run(f"(call-with-output-file {_scheme_string(probe)} (lambda (port) "
            f"(display (if (defined? '{symbol}) \"y\" \"n\") port)))")
    except DocumentNotRenderedError:
        return False
    finally:
        answer = probe.read_text().strip() if probe.exists() else 'n'
    return answer == 'y'


def _registered_ids(run, work: Path) -> set:
    """Every template guid the registry holds right now, as registered.

    Taken either side of a `(load …)` so the guids that file registered are
    the difference — known rather than guessed. Through a file for the reason
    `_registered` gives, one id per line because a guid contains no newline.

    Not lowercased, unlike everything that *compares* a guid here: the
    registry is keyed by `equal?`, so `5123A759…` and `5123a759…` are two
    entries and a file registering the second spelling of a shipped guid
    really does add one. Folding case here would have hidden that addition in
    the difference and handed the reader's page GnuCash's treatment.
    """
    probe = work / 'registry.ids'
    if probe.exists():
        probe.unlink()
    run(f'(call-with-output-file {_scheme_string(probe)}'
        f'  (lambda (port)'
        f'    (set-port-encoding! port "UTF-8")'   # read back as UTF-8
        f'    (gnc:report-templates-for-each'
        f'      (lambda (id template)'
        f'        (if (string? id) (begin (display id port) (newline port)))))))')
    if not probe.exists():
        return set()
    return {line.strip()
            for line in probe.read_text(encoding='utf-8').splitlines()
            if line.strip()}


def _registered(run, work: Path) -> bool:
    """Whether this build has the Printable Invoice report loaded.

    Answered through a file rather than the SCM ABI: a `SCM` is an opaque
    word, its truth test differs by Guile version, and a one-character file
    cannot be misread.
    """
    probe = work / 'registered.flag'
    try:
        run(f'(call-with-output-file {_scheme_string(probe)} (lambda (port) '
            f'(display (if (gnc:find-report-template '
            f'{_scheme_string(PRINTABLE_INVOICE_GUID)}) "y" "n") port)))')
    except DocumentNotRenderedError:
        return False
    finally:
        answer = probe.read_text().strip() if probe.exists() else 'n'
    return answer == 'y'
