"""The balance sheet and income statement of an open book, printed by GnuCash reports.

`balance-sheet`, `income-statement` and `report` run GnuCash reports and
calculate no figure of their own (Q-042). The balances are GnuCash's, converted
by GnuCash's report through the book's price database, at the report's own
price source, in the currency the command gives. The report is drawn the way
`print-invoice` draws GnuCash's invoice report (`services/gnucash_report.py`):
the book's session made current, the book's date format set, the reader's own
GnuCash settings read, and everything process-wide put back afterwards.

Each statement has two pages. The plaintext page is printed by a customized
GnuCash report in
`infrastructure/gnucash/reports/balance-sheet-and-income-statement-as-text.scm`:
GnuCash's Balance Sheet or Income Statement written to output plain text, with
the same options and the same GnuCash calls for every figure. The HTML page is
GnuCash's Balance Sheet or Income Statement report as GnuCash ships it.

Measured on all eleven builds:

| | GnuCash 3.4, 3.8 | GnuCash 4.4 and later |
|---|---|---|
| module that registers both reports | `(gnucash report standard-reports)` | `(gnucash reports standard balance-sheet)`, `(gnucash reports standard income-statement)` |
| Balance Sheet template guid | `c4173ac99b2b448289bf4d11c731af13` | the same |
| Income Statement template guid | `0b81a3bdfd504aff849ec2e8630524bc` | the same |
| `Commodities / Price Source` choices | `average-cost`, `weighted-average`, `pricedb-latest`, `pricedb-nearest` (3.4, 3.8, 4.4) | the same and `pricedb-before` (4.8 and later) |

`Report's currency` is always set. Left alone, both reports are in USD on every
build, whatever currency the book is kept in.
"""

import contextlib
import tempfile
from datetime import date
from fractions import Fraction
from pathlib import Path
from typing import Callable, List, Optional, Tuple

import infrastructure.gnucash
from infrastructure.gnucash.engine import load_gnc_engine
from infrastructure.guile import load_guile
from services.gnucash_report import (
    PageNotRenderedError,
    _dialect,
    _make_current,
    _read_the_readers_own_gnucash,
    _restore_the_date_style,
    _say_nothing,
    _scheme_string,
    _under_a_utf8_ctype,
    _write_every_date_the_books_way,
)

BALANCE_SHEET = 'c4173ac99b2b448289bf4d11c731af13'
INCOME_STATEMENT = '0b81a3bdfd504aff849ec2e8630524bc'

# Package data of `infrastructure.gnucash` (`pyproject.toml`), so an installed
# package finds it beside that package's modules, as the source tree does.
TEXT_REPORTS = (Path(infrastructure.gnucash.__file__).resolve().parent
                / 'reports' / 'balance-sheet-and-income-statement-as-text.scm')
BALANCE_SHEET_AS_TEXT = '826cfa6cfe624263b4091d99483d9198'
INCOME_STATEMENT_AS_TEXT = '6c442542374e4f178318bb5d456d3cf9'

# Each tried in turn; a build has one spelling or the other, and loading the
# one it lacks raises, which is caught.
_REPORT_MODULES = (
    '(gnucash reports standard balance-sheet)',
    '(gnucash reports standard income-statement)',
    '(gnucash report standard-reports)',
)

# The names of the `Price Source` choices of the report option `option`, asked
# of the build by which option API it has rather than inferred from its
# version. 5.x lists the choices through the option itself; GnuCash 3.4 to 4.13
# keep each choice as a vector whose first element is its name.
_PRICE_SOURCE_NAMES = (
    "(cond ((defined? 'gnc-option-num-permissible-values)"
    "       (map (lambda (i) (gnc-option-permissible-value option i))"
    "            (iota (gnc-option-num-permissible-values option))))"
    "      ((defined? 'GncOption-num-permissible-values)"
    "       (map (lambda (i) (GncOption-permissible-value option i))"
    "            (iota (GncOption-num-permissible-values option))))"
    "      (else (map (lambda (choice) (vector-ref choice 0)) (gnc:option-data option))))"
)

# Loaded once per process: GnuCash refuses a second registration of a guid.
_text_reports_loaded = False


# The price sources a statement is printed from. Each reads the book's price
# database, so the `share_price:` on a line is a price the book records and a
# reader can find in it. `pricedb-before` arrived in GnuCash 4.8, so a run's
# choices are these narrowed to the ones the build has.
PRICE_SOURCES = ('pricedb-nearest', 'pricedb-latest', 'pricedb-before')


class PriceSourceNotOfferedError(PageNotRenderedError):
    """A price source that is not one of the choices."""


def render_balance_sheet(session, currency: str, as_of: date, page: str = 'text',
                         price_source: Optional[str] = None, warn=None,
                         itemize: bool = True) -> str:
    """The Balance Sheet of the open book at the end of `as_of`, in `currency`.

    `page` is `text` for the plain text report, `html` for GnuCash's own.
    `price_source` is one of the report's `Price Source` choices, or None for
    GnuCash's default.

    `itemize` shows how each gain figure was worked out, as comment lines. On
    by default: a gain is measured against costs that appear on no line of the
    page, so without its working it is a figure a reader cannot check.
    """
    end = load_gnc_engine().gnc_dmy2time64_end(as_of.day, as_of.month, as_of.year)
    return _render(session, _template(page, BALANCE_SHEET, BALANCE_SHEET_AS_TEXT),
                   'Balance Sheet', currency,
                   [('General', 'Balance Sheet Date', end)], price_source, warn,
                   realized_as_of=as_of, itemize=itemize)


def render_income_statement(session, currency: str, start: date, end: date,
                            page: str = 'text', price_source: Optional[str] = None,
                            warn=None) -> str:
    """The Income Statement of the open book from the start of `start` to the end of `end`.

    `page` is `text` for the plain text report, `html` for GnuCash's own.
    `price_source` is one of the report's `Price Source` choices, or None for
    GnuCash's default.
    """
    lib = load_gnc_engine()
    return _render(session, _template(page, INCOME_STATEMENT, INCOME_STATEMENT_AS_TEXT),
                   'Income Statement', currency,
                   [('General', 'Start Date', lib.gnc_dmy2time64(start.day, start.month, start.year)),
                    ('General', 'End Date', lib.gnc_dmy2time64_end(end.day, end.month, end.year))],
                   price_source, warn)


def _template(page: str, html: str, text: str) -> str:
    return text if page == 'text' else html


def _runner(lib, errors: Path) -> Callable[[str], None]:
    """Evaluate Scheme with every error caught and raised as `PageNotRenderedError`.

    As `_render` in `services/gnucash_report.py` does, and for its reason: an
    uncaught Guile exception aborts the process Guile is embedded in.
    """
    def run(scheme: str) -> None:
        wrapped = (f'(catch #t (lambda () {scheme} #t)'
                   f' (lambda (key . args)'
                   f'   (call-with-output-file {_scheme_string(errors)}'
                   f'     (lambda (port)'
                   f'       (set-port-encoding! port "UTF-8")'
                   f'       (display (list key args) port)))))')
        lib.scm_eval_string(lib.scm_from_utf8_string(wrapped.encode('utf-8')))
        if errors.exists() and errors.read_text(encoding='utf-8').strip():
            message = errors.read_text(encoding='utf-8').strip()
            errors.unlink()
            raise PageNotRenderedError(f'GnuCash could not render the report: {message[:900]}')
    return run


def _load_the_text_reports(run) -> None:
    """Register the plain text reports, once per process.

    With `%load-should-auto-compile` off, as `_read_the_readers_own_gnucash`
    loads a file and for its reason: Guile otherwise writes three lines about
    compiling it to stderr, where the command's warnings go.
    """
    global _text_reports_loaded
    if not _text_reports_loaded:
        run(f'(let ((was %load-should-auto-compile))'
            f'  (dynamic-wind'
            f'    (lambda () (set! %load-should-auto-compile #f))'
            f'    (lambda () (load {_scheme_string(TEXT_REPORTS)}))'
            f'    (lambda () (set! %load-should-auto-compile was))))')
        _text_reports_loaded = True


def _price_sources(run, work: Path, template: str) -> List[str]:
    """The `Price Source` choices the report `template` offers on this build."""
    answer = work / 'price-sources.txt'
    run(f'(let* ((options (gnc:make-report-options {_scheme_string(template)}))'
        f'       (option (gnc:lookup-option options "Commodities" "Price Source")))'
        f'  (call-with-output-file {_scheme_string(answer)}'
        f'    (lambda (port)'
        f'      (for-each (lambda (name) (display name port) (newline port))'
        f'                {_PRICE_SOURCE_NAMES}))))')
    return answer.read_text(encoding='utf-8').split()


def _render(session, template: str, called: str, currency: str,
            dates: List[Tuple[str, str, int]], price_source: Optional[str], warn,
            realized_as_of=None, itemize: bool = True) -> str:
    from services.foreign_currency import (
        BASE_CURRENCY,
        cost_basis_totals_by_currency_and_side,
        realized_fx_items_up_to,
    )

    warn = warn or _say_nothing
    lib = load_guile()
    _make_current(session)
    # What the book has already taken on foreign currency by the report's date.
    # The balance sheet states it and adds it into nothing — it is inside
    # `retained_earnings` already, having gone through the income statement —
    # so a reader can tell it from the gain the book has yet to take.
    takes_the_cost_bases = realized_as_of is not None and currency == BASE_CURRENCY
    # The differences one by one, for the page to show its working, and the key
    # totalled from those same items. One walk of the book: asking a second
    # time cost twice and let the key and the working it is said to add up to
    # come to differ.
    realized_items = (realized_fx_items_up_to(session.book, realized_as_of)
                      if takes_the_cost_bases else [])
    realized = sum((figure for _when, _account, figure in realized_items),
                   Fraction(0))
    # What the foreign money the book still holds cost, in the book's own
    # currency, for the report to measure its value against. GnuCash works cost
    # out from the sum of an account's split values, which is not what the
    # money cost wherever a foreign inflow was recorded in its own currency —
    # an invoice collected into a foreign bank carries no figure in the book's
    # currency at all. The cost bases are what this tool keeps for that
    # question, and `fx-balances` reports the same numbers.
    # Read as they stood at the end of the report's date, not as they stand now:
    # the same date the sheet is drawn at, which `render_balance_sheet` passes
    # as `realized_as_of`. A page drawn at an earlier date otherwise measures
    # the currency the book held then against costs it had not yet paid.
    #
    # Asked only where the page will use it. Reading the cost bases walks every
    # split in the book, and again to see what each has since been drawn down
    # by, while `costed` hands over an empty list wherever
    # `takes_the_cost_bases` is false — so those two walks were work whose
    # answer was thrown away. That is every income statement, which passes no
    # date and whose renderer reads none of these bindings, and every page
    # asked for in a currency other than the one costs are recorded in. An HTML
    # or PDF balance sheet is not spared: it passes the same date as the text
    # one, so it still reads them, even though GnuCash's own renderer draws it.
    foreign_cost = (cost_basis_totals_by_currency_and_side(
        session.book, realized_as_of) if takes_the_cost_bases else {})
    was = None
    try:
        was = _write_every_date_the_books_way(session.book, warn)
        with tempfile.TemporaryDirectory(prefix='gnucash-statement-') as work:
            work = Path(work)
            run = _runner(lib, work / 'errors.txt')
            setter, find_report = _dialect(run, work)
            _read_the_readers_own_gnucash(run, work, warn)
            for module in _REPORT_MODULES:
                with contextlib.suppress(PageNotRenderedError):
                    run(f'(use-modules {module})')
            if template in (BALANCE_SHEET_AS_TEXT, INCOME_STATEMENT_AS_TEXT):
                _load_the_text_reports(run)
            # A choice the build offers is a bare Scheme name, so it is written
            # into the Scheme below only once it is known to be one.
            priced = ''
            if price_source is not None:
                offered = [name for name in _price_sources(run, work, template)
                           if name in PRICE_SOURCES]
                if price_source not in offered:
                    raise PriceSourceNotOfferedError(
                        f'The {called} has no price source "{price_source}"; '
                        f'the choices are {", ".join(offered)}')
                priced = f"    (set-opt options \"Commodities\" \"Price Source\" '{price_source})"
            # Only the text reports carry the setter, so only they are told —
            # and only when the page is drawn in the currency the cost bases
            # are kept in. `cost_of` measures every basis against
            # `BASE_CURRENCY`, so on a book kept in anything else the totals
            # would be figures in the wrong currency; that book keeps GnuCash's
            # own reconstruction until the cost bases learn the book's currency.
            #
            # Set on every render, because the variable lives as long as the
            # Guile process: a page that left it alone inherited the cost of
            # whichever book was drawn before it, and `report` draws two
            # statements in one process.
            costed = ''
            if template in (BALANCE_SHEET_AS_TEXT, INCOME_STATEMENT_AS_TEXT):
                bases = '(list)'
                if currency == BASE_CURRENCY:
                    bases = '(list ' + ' '.join(
                        f'(list "{held}" {quantity.numerator}/{quantity.denominator}'
                        f' {cost.numerator}/{cost.denominator} "{side}")'
                        for held, sides in sorted(foreign_cost.items())
                        for side, (quantity, cost) in sorted(sides.items())) + ')'
                items = '(list ' + ' '.join(
                    f'(list {_scheme_string(when)} {_scheme_string(account)}'
                    f' {figure.numerator}/{figure.denominator})'
                    for when, account, figure in realized_items) + ')'
                costed = (f'(plaintext:set-cost-bases! {bases})'
                          f'(plaintext:set-realized-fx! '
                          f'{realized.numerator}/{realized.denominator})'
                          f'(plaintext:set-realized-items! {items})'
                          # Whether that figure was worked out at all. Where it
                          # was not, the zero above means "not measured", and
                          # the page leaves the two realized keys off rather
                          # than stating a zero as a fact — a book that realized
                          # 100.00 CAD said `realized_gains_fx: 0.00 USD` when
                          # its page was asked for in US dollars. Written on
                          # every render for the same reason as the rest: the
                          # variable outlives the page, and `report` draws two.
                          f'(plaintext:set-realized-known! '
                          f'{"#t" if takes_the_cost_bases else "#f"})'
                          f'(plaintext:set-itemize! '
                          f'{"#t" if itemize else "#f"})')
            page = work / 'page'
            dated = '\n'.join(
                f'    (set-opt options {_scheme_string(section)} {_scheme_string(name)}'
                f" (cons 'absolute {moment}))"
                for section, name, moment in dates)
            run(_under_a_utf8_ctype(f'''
{costed}
(let* ((set-opt {setter})
       (template {_scheme_string(template)})
       (book (gnc-get-current-book))
       (currency (gnc-commodity-table-lookup
                   (gnc-commodity-table-get-table book) "CURRENCY" {_scheme_string(currency)})))
  (if (not (gnc:find-report-template template))
      (error "the {called} report is not registered on this build"))
  (if (not currency)
      (error (string-append "GnuCash knows no currency " {_scheme_string(currency)})))
  (let ((options (gnc:make-report-options template)))
{dated}
    (set-opt options "Commodities" "Report's currency" currency)
{priced}
    (let* ((report (gnc:make-report template options))
           (page (gnc:report-render-html ({find_report} report) #t)))
      (call-with-output-file {_scheme_string(page)}
        (lambda (port)
          (set-port-encoding! port "UTF-8")
          (display page port)))
      (catch #t (lambda () (gnc-report-remove-by-id report)) (lambda i #f)))))
'''))
            return page.read_text(encoding='utf-8')
    finally:
        try:
            _make_current(None)
        finally:
            _restore_the_date_style(was)
