"""What GnuCash itself computes as a security's realized and unrealized gain.

Q-043 states `unrealized_gains_other` from GnuCash's own revaluation and leaves
`realized_gains_other` for later work. GnuCash does compute both, in its
**Advanced Portfolio** report — guid `21d7cfc59fc74f22887596ebde7e462d`, the
same guid on every supported build, at
`report/standard-reports/advanced-portfolio.scm` below 4.4 and
`reports/standard/advanced-portfolio.scm` from 4.4 on. It derives them from its
own basis logic rather than from anything the book booked, so the two can
disagree, and this prints them side by side so the doc can say which.

Two things about that report decide the answer, both read from its own Scheme:

- its options are registered under `General`, not `Commodities` — the date is
  `("General" "Date")` and the currency `("General" "Report's currency")`, where
  the Balance Sheet keeps its currency under `Commodities`. `_render` in
  `services/gnucash_statements.py` sets the Balance Sheet's spelling, so it
  cannot draw this report and this probe sets the options itself;
- **`Basis calculation method` defaults to `average-basis`**, the average cost
  of all shares, with `fifo-basis` and `filo-basis` the alternatives. On a book
  with one purchase lot all three agree. On a book with two lots bought at
  different prices they do not, and neither need agree with the figure the
  ledger booked, which is whatever its writer actually picked.

The book measured is the Q-042 fixture: 20 AMZN bought at 200.00 USD, 8 sold at
260.00 USD on 2026-06-30, and 12 held at the 280.00 USD of 2026-12-31 with US
dollars at 1.42. The ledger books 480.00 USD to `Income:Realized Gains` itself,
and the balance sheet states `unrealized_gains_other: 1363.20 CAD`.

Run it inside a container, from the repository root:

    python3 tests/research/what_gnucash_computes_as_a_securitys_realized_gain_probe.py
"""

import contextlib
import re
import sys
import tempfile
from datetime import date
from fractions import Fraction
from pathlib import Path

ADVANCED_PORTFOLIO = '21d7cfc59fc74f22887596ebde7e462d'
FIXTURE = 'tests/fixtures/a_cad_book_with_usd_hkd_and_shares_priced_in_its_price_database.txt'
CLEAN_BOUGHT = 'tests/fixtures/a_cad_book_that_bought_a_thousand_usd.txt'
CLEAN_SOLD = 'tests/fixtures/the_thousand_usd_sold_at_a_higher_rate.txt'
AS_OF = date(2026, 12, 31)
BOOKED_TO = 'Income:Realized Gains'


def _cells(html):
    """Every table row of the page, as a list of its cells' text."""
    rows = []
    for row in re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.S | re.I):
        cells = [re.sub(r'<[^>]+>', '', cell)
                 for cell in re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', row, re.S | re.I)]
        cells = [cell.replace('&nbsp;', ' ').replace('&#160;', ' ').strip()
                 for cell in cells]
        if any(cells):
            rows.append(cells)
    return rows


def _render_advanced_portfolio(session, currency, as_of, select_leaf=None):
    """The Advanced Portfolio page for the open book, as HTML.

    The same shape as `_render` in `services/gnucash_statements.py` — the
    session made current, the reader's own GnuCash read, the report modules
    loaded, the page written to a file and read back — with this report's own
    option spellings and everything process-wide put back afterwards.

    `select_leaf` replaces the Accounts option with the accounts of that leaf
    name. The option permits `ACCT-TYPE-ASSET`, `ACCT-TYPE-BANK`,
    `ACCT-TYPE-STOCK` and `ACCT-TYPE-MUTUAL`, so a bank account is eligible,
    but its default value is `(filter gnc:account-is-stock? …)` — stock
    accounts only. A currency account therefore never appears unless it is
    asked for, which is what this argument does.

    By leaf name rather than by path: `gnc-account-lookup-by-full-name` wants
    the book's own separator, a dot in these images, and a path written with
    the wrong one selects nothing and reads as "GnuCash reports no gain".
    """
    from infrastructure.gnucash.engine import load_gnc_engine
    from infrastructure.guile import load_guile
    from services.gnucash_report import (
        PageNotRenderedError,
        _read_the_readers_own_gnucash,
        _restore_the_date_style,
        _say_nothing,
        _scheme_string,
        _under_a_utf8_ctype,
        _write_every_date_the_books_way,
    )
    from services.gnucash_statements import (
        _REPORT_MODULES,
        _dialect,
        _make_current,
        _runner,
    )

    lib = load_guile()
    _make_current(session)
    end = load_gnc_engine().gnc_dmy2time64_end(as_of.day, as_of.month, as_of.year)
    was = None
    try:
        was = _write_every_date_the_books_way(session.book, _say_nothing)
        with tempfile.TemporaryDirectory(prefix='advanced-portfolio-') as work:
            work = Path(work)
            run = _runner(lib, work / 'errors.txt')
            setter, find_report = _dialect(run, work)
            _read_the_readers_own_gnucash(run, work, _say_nothing)
            modules = _REPORT_MODULES + (
                '(gnucash reports standard advanced-portfolio)',)
            for module in modules:
                with contextlib.suppress(PageNotRenderedError):
                    run(f'(use-modules {module})')
            page = work / 'page'
            selected = ''
            if select_leaf:
                selected = (
                    '    (set-opt options "Accounts" "Accounts"\n'
                    '      (filter (lambda (a) (string=? (xaccAccountGetName a) '
                    f'{_scheme_string(select_leaf)}))\n'
                    '              (gnc-account-get-descendants-sorted\n'
                    '               (gnc-get-current-root-account))))\n'
                    # Without this the report drops an account holding nothing,
                    # and a book that sold every dollar has exactly that — the
                    # page then prints an empty Total, which reads as a
                    # computed zero rather than as the account never being
                    # measured. The option's name is this; the sentence beside
                    # it in the Scheme is its help text.
                    '    (set-opt options "Accounts"'
                    ' "Include accounts with no shares" #t)')
            run(_under_a_utf8_ctype(f'''
(let* ((set-opt {setter})
       (template {_scheme_string(ADVANCED_PORTFOLIO)})
       (book (gnc-get-current-book))
       (currency (gnc-commodity-table-lookup
                   (gnc-commodity-table-get-table book) "CURRENCY"
                   {_scheme_string(currency)})))
  (if (not (gnc:find-report-template template))
      (error "the Advanced Portfolio report is not registered on this build"))
  (if (not currency)
      (error (string-append "GnuCash knows no currency " {_scheme_string(currency)})))
  (let ((options (gnc:make-report-options template)))
    (set-opt options "General" "Date" (cons 'absolute {end}))
    (set-opt options "General" "Report's currency" currency)
{selected}
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


def _what_the_ledger_booked(book):
    """The balance of the account the ledger booked its realized gain to."""
    from infrastructure.gnucash.utils import get_account_full_name

    def walk(account):
        for child in account.get_children():
            yield child
            yield from walk(child)

    for account in walk(book.get_root_account()):
        if get_account_full_name(account) == BOOKED_TO:
            balance = account.GetBalance()
            return (-Fraction(balance.num(), balance.denom()),
                    account.GetCommodity().get_mnemonic())
    return None, None


def main():
    from click.testing import CliRunner

    from cli.main import cli
    from repositories.gnucash_repository import GnuCashRepository

    work = Path(tempfile.mkdtemp(prefix='advanced-portfolio-book-'))
    book_path = work / 'book.gnucash'
    made = CliRunner().invoke(cli, ['import', '--new', str(book_path), FIXTURE])
    if made.exit_code != 0:
        print(made.output)
        return 1
    # The backup a second save would collide with, the way conftest does it:
    # two saves in one second otherwise fail with ERR_FILEIO_BACKUP_ERROR.
    for stale in work.glob('book.gnucash.2*'):
        stale.unlink()

    repo = GnuCashRepository(str(book_path))
    repo.open()
    try:
        booked, booked_in = _what_the_ledger_booked(repo.book)
        html = _render_advanced_portfolio(repo.session, 'CAD', AS_OF)
    finally:
        repo.close()

    print('=== what the ledger booked itself ===')
    print(f'  {BOOKED_TO}: {float(booked):.2f} {booked_in}'
          if booked is not None else f'  no {BOOKED_TO} account')
    print()
    print("=== what GnuCash's Advanced Portfolio computes, its own defaults ===")
    if _report(html) != 0:
        return 1

    # The same report asked for the currency account, which its default
    # Accounts selection leaves out. The book sells 3,000.00 USD at 1.38 that
    # cost 1.30 and books 240.00 CAD to `Income:Realized FX Gains`, so if this
    # report computes a realized gain for currency at all, it is here.
    repo = GnuCashRepository(str(book_path))
    repo.open()
    try:
        usd = _render_advanced_portfolio(repo.session, 'CAD', AS_OF,
                                         select_leaf='USD Bank')
    finally:
        repo.close()
    print()
    print('=== the same report, asked for Assets:USD Bank ===')
    _report(usd)

    # That US dollar account carries a borrowing, loan interest and the
    # proceeds of a share sale as well as its own currency movement, so no
    # figure computed for it speaks for the currency alone. The books below
    # hold nothing else.
    #
    # First with nothing spent at all. No disposal means nothing valued at what
    # it cost, so the one thing that makes the realized columns disagree is
    # absent, and both computations come down to the same subtraction: what the
    # dollars are worth now, less what they cost.
    print()
    print('=== nothing spent: 1,000.00 USD bought at 1.30, held at 1.45 ===')
    held = work / 'held.gnucash'
    bought = CliRunner().invoke(cli, ['import', '--new', str(held), CLEAN_BOUGHT])
    if bought.exit_code != 0:
        print(bought.output)
        return 1
    for stale in work.glob('held.gnucash.2*'):
        stale.unlink()
    standing = CliRunner().invoke(
        cli, ['balance-sheet', str(held), '--as-of', '2026-12-31'])
    if standing.exit_code != 0:
        print(standing.output)
        return 1
    print('  --- what gnucash-plaintext states, from the cost bases ---')
    for line in standing.output.splitlines():
        if 'gains' in line or 'balancing' in line:
            print(f'    {line.strip()}')
    repo = GnuCashRepository(str(held))
    repo.open()
    try:
        still = _render_advanced_portfolio(repo.session, 'CAD', AS_OF,
                                           select_leaf='USD Bank')
    finally:
        repo.close()
    print('  --- what Advanced Portfolio computes for the same account ---')
    _report(still)

    print()
    print('=== a book holding nothing but the currency: 1,000.00 USD bought at'
          ' 1.30, every dollar sold at 1.40 ===')
    clean = _a_book_that_sold_every_dollar(work)
    sheet = CliRunner().invoke(
        cli, ['balance-sheet', str(clean), '--as-of', '2026-12-31'])
    if sheet.exit_code != 0:
        print(sheet.output)
        return 1
    print('  --- what gnucash-plaintext states, from the cost bases ---')
    for line in sheet.output.splitlines():
        if 'gains' in line or 'balancing' in line:
            print(f'    {line.strip()}')
    repo = GnuCashRepository(str(clean))
    repo.open()
    try:
        page = _render_advanced_portfolio(repo.session, 'CAD', AS_OF,
                                          select_leaf='USD Bank')
    finally:
        repo.close()
    print('  --- what Advanced Portfolio computes for the same account ---')
    return _report(page)


def _a_book_that_sold_every_dollar(work):
    """A CAD book that bought 1,000.00 USD at 1.30 and sold every dollar at 1.40.

    The cost basis guid is made fresh on each import, so the sale carries a
    placeholder and it is read from `fx-balances` here, as the cost-basis tests
    do.
    """
    from click.testing import CliRunner

    from cli.main import cli

    book = work / 'clean.gnucash'
    bought = CliRunner().invoke(
        cli, ['import', '--new', str(book), CLEAN_BOUGHT])
    assert bought.exit_code == 0, bought.output
    for stale in work.glob('clean.gnucash.2*'):
        stale.unlink()
    listing = CliRunner().invoke(cli, ['fx-balances', str(book)])
    assert listing.exit_code == 0, listing.output
    guid = re.search(r'\b([0-9a-f]{32})\b', listing.output)
    assert guid is not None, listing.output
    ledger = work / 'sold.txt'
    with open(CLEAN_SOLD, encoding='utf-8') as source:
        ledger.write_text(source.read().replace('{usd_basis}', guid.group(1)),
                          encoding='utf-8')
    sold = CliRunner().invoke(cli, ['import', str(book), str(ledger)])
    assert sold.exit_code == 0, sold.output
    for stale in work.glob('clean.gnucash.2*'):
        stale.unlink()
    return book


def _report(html):
    rows = _cells(html)
    heading = next((row for row in rows if 'Realized Gain' in row), None)
    if heading is None:
        print('  the page states no Realized Gain column:')
        print('\n'.join(f'  {row}' for row in rows[:12]))
        return 1
    realized = heading.index('Realized Gain')
    unrealized = heading.index('Unrealized Gain')
    for row in rows:
        if row is heading or len(row) <= max(realized, unrealized):
            continue
        label = row[0] or (row[1] if len(row) > 1 else '')
        if not label:
            continue
        # Every column, because what separates "GnuCash disagrees" from
        # "GnuCash filed the same money under another heading" is Money Out,
        # Basis and Income beside the two gain columns.
        print(f'  {label}')
        for name, value in zip(heading, row):
            if name and value:
                print(f'      {name:18s} {value}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
