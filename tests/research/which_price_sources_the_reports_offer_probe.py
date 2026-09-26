"""The choices GnuCash's Balance Sheet and Income Statement reports offer for "Price Source", on this build (Q-042).

Loaded the way `services/gnucash_report.py` loads reports. Written to the
output directory passed as the first argument, one file per report.

Run: ./scripts/run.sh <tag> env PYTHONPATH=/workspace python3 tests/research/which_price_sources_the_reports_offer_probe.py <out-dir>
"""

import contextlib
import sys
import tempfile
from pathlib import Path

import gnucash  # noqa: F401 — the report modules need GnuCash's own libraries loaded first

from infrastructure.gnucash.engine import load_gnc_engine
from infrastructure.guile import load_guile
from services import gnucash_report as gr

REPORTS = {
    'balance-sheet': 'c4173ac99b2b448289bf4d11c731af13',
    'income-statement': '0b81a3bdfd504aff849ec2e8630524bc',
}
MODULES = ['(gnucash reports standard balance-sheet)', '(gnucash reports standard income-statement)',
           '(gnucash report standard-reports)']


def main():
    load_gnc_engine()
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp())
    lib = load_guile()
    errors = work / 'errors.txt'

    def run(scheme):
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
                log.write(message + '\n')
            raise gr.PageNotRenderedError(message)

    gr._dialect(run, work)
    for module in MODULES:
        with contextlib.suppress(gr.PageNotRenderedError):
            run(f'(use-modules {module})')

    for slug, guid in REPORTS.items():
        answer = out / f'{slug}.price-source.txt'
        # The spellings of "the choices of a multichoice option", tried in turn;
        # whichever this build has writes the list.
        for spelling in (
                '(gnc:option-data option)',
                '(map (lambda (i) (list (gnc-option-permissible-value option i) '
                '(gnc-option-permissible-value-name option i))) '
                '(iota (gnc-option-num-permissible-values option)))',
                '(map (lambda (i) (list (GncOption-permissible-value option i) '
                '(GncOption-permissible-value-name option i))) '
                '(iota (GncOption-num-permissible-values option)))'):
            try:
                run(f'(let* ((options (gnc:make-report-options {gr._scheme_string(guid)}))'
                    f'       (option (gnc:lookup-option options "Commodities" "Price Source")))'
                    f'  (call-with-output-file {gr._scheme_string(str(answer))}'
                    f'    (lambda (port) (write {spelling} port) (newline port))))')
                break
            except gr.PageNotRenderedError:
                continue


if __name__ == '__main__':
    main()
