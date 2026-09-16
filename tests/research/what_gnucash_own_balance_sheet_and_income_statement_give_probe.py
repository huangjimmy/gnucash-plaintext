"""What GnuCash's own Balance Sheet and Income Statement reports give on a multi-currency book, on this build (Q-042).

The book is the one `what_gnucash_currency_conversion_calls_give_probe.py`
builds (USD Bank, HKD Bank, 10 AMZN bought in USD, USD in CAD prices on 01-02
and 02-02, HKD stored as CAD in HKD, AMZN in USD on 01-15 and 02-15), plus:

- CAD Bank: 1000.00 CAD opened on 01-03;
- Income:Consulting in USD: 500.00 USD received into USD Bank on 01-20;
- Expenses:Fees in CAD: 100.00 CAD paid from CAD Bank on 01-21.

Reports are loaded and rendered the way `services/gnucash_report.py` renders
an invoice: the same setup, the same option setter, the current session set.
Everything goes to files under the output directory given as the first
argument: the modules that loaded, the list of templates, each report's
options with their defaults, what setting each option did, and each page
GnuCash rendered.

Run: ./scripts/run.sh <tag> env PYTHONPATH=/workspace python3 tests/research/what_gnucash_own_balance_sheet_and_income_statement_give_probe.py <out-dir>
"""

import os
import sys
import tempfile
from pathlib import Path

from gnucash import (
    ACCT_TYPE_BANK,
    ACCT_TYPE_EXPENSE,
    ACCT_TYPE_INCOME,
    Account,
    GncNumeric,
    Split,
    Transaction,
)

# The suite's `_patch_session_save`: every save deletes the backup a save in
# the same second would collide with.
import tests.conftest  # noqa: F401
from infrastructure.guile import load_guile
from repositories.gnucash_repository import GnuCashRepository, SessionMode
from services import gnucash_report as gr
from tests.research import what_gnucash_currency_conversion_calls_give_probe as base

STANDARD_REPORT_MODULES = [
    '(gnucash reports)',
    '(gnucash reports standard balance-sheet)',
    '(gnucash reports standard income-statement)',
    '(gnucash report standard-reports)',
    '(gnucash report balance-sheet)',
    '(gnucash report income-statement)',
]


def extend(path):
    repo = GnuCashRepository(path)
    repo.open(SessionMode.NORMAL)
    book = repo.book
    table = book.get_table()
    cad = table.lookup('CURRENCY', 'CAD')
    usd = table.lookup('CURRENCY', 'USD')
    root = book.get_root_account()
    children = {child.GetName(): child for child in root.get_children()}

    def account(name, kind, commodity):
        made = Account(book)
        made.BeginEdit()
        made.SetName(name)
        made.SetType(kind)
        made.SetCommodity(commodity)
        root.append_child(made)
        made.CommitEdit()
        return made

    cad_bank = account('CAD Bank', ACCT_TYPE_BANK, cad)
    opening_cad = account('Opening CAD', children['Opening USD'].GetType(), cad)
    consulting = account('Consulting', ACCT_TYPE_INCOME, usd)
    fees = account('Fees', ACCT_TYPE_EXPENSE, cad)

    def transaction(day, month, currency, splits):
        made = Transaction(book)
        made.BeginEdit()
        made.SetCurrency(currency)
        made.SetDate(day, month, 2026)
        for target, value, amount in splits:
            split = Split(book)
            split.SetParent(made)
            split.SetAccount(target)
            split.SetValue(GncNumeric(*value))
            split.SetAmount(GncNumeric(*amount))
        made.CommitEdit()

    transaction(3, 1, cad, [(cad_bank, (100000, 100), (100000, 100)),
                            (opening_cad, (-100000, 100), (-100000, 100))])
    transaction(20, 1, usd, [(children['USD Bank'], (50000, 100), (50000, 100)),
                             (consulting, (-50000, 100), (-50000, 100))])
    transaction(21, 1, cad, [(fees, (10000, 100), (10000, 100)),
                             (cad_bank, (-10000, 100), (-10000, 100))])
    repo.save()
    repo.close()


def main():
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp())
    path = os.path.join(tempfile.mkdtemp(), 'book.gnucash')
    base.build(path)
    extend(path)

    repo = GnuCashRepository(path)
    repo.open(SessionMode.NORMAL)
    lib = load_guile()
    gr._make_current(repo.session)
    errors = work / 'errors.txt'

    def run(scheme, label):
        if errors.exists():
            errors.unlink()
        wrapped = (f'(catch #t (lambda () {scheme} #t)'
                   f' (lambda (key . args)'
                   f'   (call-with-output-file {gr._scheme_string(str(errors))}'
                   f'     (lambda (port) (display (list key args) port)))))')
        lib.scm_eval_string(lib.scm_from_utf8_string(wrapped.encode('utf-8')))
        if errors.exists():
            message = errors.read_text(errors='replace')[:600]
            with (out / 'errors.log').open('a') as log:
                log.write(f'{label}: {message}\n')
            return False
        return True

    def run_or_raise(scheme):
        if not run(scheme, 'dialect'):
            raise gr.PageNotRenderedError((out / 'errors.log').read_text()[-600:])

    try:
        setter, find_report = gr._dialect(run_or_raise, work)
        loaded = [module for module in STANDARD_REPORT_MODULES
                  if run(f'(use-modules {module})', f'load {module}')]
        (out / 'modules.txt').write_text('\n'.join(loaded) + '\n')

        templates = out / 'templates.txt'
        run(f'(call-with-output-file {gr._scheme_string(str(templates))}'
            f'  (lambda (port)'
            f'    (gnc:report-templates-for-each'
            f'      (lambda (id template)'
            f'        (display id port) (display "\t" port)'
            f'        (display (gnc:report-template-name template) port)'
            f'        (newline port)))))', 'templates')

        wanted = {}
        for line in templates.read_text().splitlines() if templates.exists() else []:
            guid, _, title = line.partition('\t')
            if title in ('Balance Sheet', 'Income Statement', 'Profit & Loss'):
                wanted[title] = guid

        for title, guid in wanted.items():
            slug = title.lower().replace(' ', '-').replace('&', 'and')
            options_file = out / f'{slug}.options.txt'
            run(f'(let ((options (gnc:make-report-options {gr._scheme_string(guid)})))'
                f'  (call-with-output-file {gr._scheme_string(str(options_file))}'
                f'    (lambda (port)'
                f'      (gnc:options-for-each'
                f'        (lambda (option)'
                f'          (write (list (gnc:option-section option) (gnc:option-name option)'
                f'                       (catch #t (lambda () (gnc:option-value option))'
                f'                              (lambda i (quote no-value))))'
                f'                 port)'
                f'          (newline port))'
                f'        options))))', f'options {title}')

            for as_of in ((2026, 1, 25), (2026, 3, 1)):
                stamp = f'{as_of[0]}-{as_of[1]:02d}-{as_of[2]:02d}'
                end = base.utc(*as_of, 23, 59, 59)
                page = out / f'{slug}.{stamp}.html'
                done = out / f'{slug}.{stamp}.options-set.txt'
                run(f'''
(let* ((set-opt {setter})
       (options (gnc:make-report-options {gr._scheme_string(guid)}))
       (book (gnc-get-current-book))
       (cad (gnc-commodity-table-lookup (gnc-commodity-table-get-table book) "CURRENCY" "CAD"))
       (said '()))
  (define (try section key value)
    (if (gnc:lookup-option options section key)
        (catch #t
          (lambda () (set-opt options section key value)
                     (set! said (cons (list section key 'set) said)))
          (lambda args (set! said (cons (list section key 'refused args) said))))
        (set! said (cons (list section key 'no-such-option) said))))
  (try "General" "Balance Sheet Date" (cons 'absolute {end}))
  (try "General" "Start Date" (cons 'absolute {base.utc(2026, 1, 1)}))
  (try "General" "End Date" (cons 'absolute {end}))
  (try "Commodities" "Report's currency" cad)
  (try "Commodities" "Show Foreign Currencies" #t)
  (call-with-output-file {gr._scheme_string(str(done))}
    (lambda (port) (for-each (lambda (x) (write x port) (newline port)) (reverse said))))
  (let* ((report (gnc:make-report {gr._scheme_string(guid)} options))
         (page (gnc:report-render-html ({find_report} report) #t)))
    (call-with-output-file {gr._scheme_string(str(page))}
      (lambda (port) (set-port-encoding! port "UTF-8") (display page port)))))
''', f'render {title} {stamp}')
    finally:
        gr._make_current(None)
        repo.close()


if __name__ == '__main__':
    main()
