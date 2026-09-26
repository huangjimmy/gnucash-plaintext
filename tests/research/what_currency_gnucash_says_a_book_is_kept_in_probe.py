"""What GnuCash says a book's currency is, on this build, for a book kept in HKD that holds USD and CAD too (Q-042).

The book's top-level accounts, Assets and Equity, are held in HKD. Beneath
them an HKD, a USD and a CAD bank account are each opened against an equity
account in the same currency. Asked:

- which book-currency and default-currency calls this build has, and what they
  return;
- the root account's commodity;
- the currency GnuCash's own Balance Sheet report puts in its "Report's
  currency" option when nothing sets it.

Output goes to the directory passed as the first argument.

Run: ./scripts/run.sh <tag> env PYTHONPATH=/workspace python3 tests/research/what_currency_gnucash_says_a_book_is_kept_in_probe.py <out-dir>
"""

import contextlib
import ctypes
import os
import sys
import tempfile
from pathlib import Path

import gnucash.gnucash_core_c as core
from gnucash import (
    ACCT_TYPE_ASSET,
    ACCT_TYPE_BANK,
    ACCT_TYPE_EQUITY,
    Account,
    GncNumeric,
    Split,
    Transaction,
)

from infrastructure.gnucash.engine import load_gnc_engine
from infrastructure.gnucash.utils import qof_pointer
from infrastructure.guile import load_guile
from repositories.gnucash_repository import GnuCashRepository, SessionMode
from services import gnucash_report as gr

BALANCE_SHEET = 'c4173ac99b2b448289bf4d11c731af13'


def build(path):
    repo = GnuCashRepository(path)
    repo.open(SessionMode.NEW)
    book = repo.book
    table = book.get_table()
    hkd = table.lookup('CURRENCY', 'HKD')

    def account(parent, name, kind, commodity):
        made = Account(book)
        made.BeginEdit()
        made.SetName(name)
        made.SetType(kind)
        made.SetCommodity(commodity)
        parent.append_child(made)
        made.CommitEdit()
        return made

    root = book.get_root_account()
    assets = account(root, 'Assets', ACCT_TYPE_ASSET, hkd)
    equity = account(root, 'Equity', ACCT_TYPE_EQUITY, hkd)
    for code, cents in (('HKD', 550000), ('USD', 100000), ('CAD', 200000)):
        currency = table.lookup('CURRENCY', code)
        bank = account(assets, f'{code} Bank', ACCT_TYPE_BANK, currency)
        opening = account(equity, f'Opening {code}', ACCT_TYPE_EQUITY, currency)
        made = Transaction(book)
        made.BeginEdit()
        made.SetCurrency(currency)
        made.SetDate(3, 1, 2026)
        for target, value in ((bank, cents), (opening, -cents)):
            split = Split(book)
            split.SetParent(made)
            split.SetAccount(target)
            split.SetValue(GncNumeric(value, 100))
            split.SetAmount(GncNumeric(value, 100))
        made.CommitEdit()
    repo.save()
    repo.close()


def mnemonic_of(lib, pointer):
    if not pointer:
        return None
    lib.gnc_commodity_get_mnemonic.restype = ctypes.c_char_p
    lib.gnc_commodity_get_mnemonic.argtypes = [ctypes.c_void_p]
    return (lib.gnc_commodity_get_mnemonic(pointer) or b'').decode()


def main():
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    lines = []
    lib = load_gnc_engine()
    lines.append(f'GnuCash {lib.gnc_version().decode()}, LANG={os.environ.get("LANG")!r}')
    path = os.path.join(tempfile.mkdtemp(), 'book.gnucash')
    build(path)

    repo = GnuCashRepository(path)
    repo.open(SessionMode.NORMAL)
    try:
        book = repo.book
        book_pointer = qof_pointer(book)
        process = ctypes.CDLL(None)
        for name in ('gnc_book_get_book_currency_name', 'gnc_book_get_book_currency',
                     'gnc_book_use_book_currency', 'gnc_default_currency', 'gnc_default_report_currency',
                     'gnc_account_get_currency_or_parent'):
            lines.append(f'{name}: swig={hasattr(core, name)} c={hasattr(process, name)}')
        for name in ('gnc_default_currency', 'gnc_default_report_currency'):
            if hasattr(process, name):
                fn = getattr(process, name)
                fn.restype = ctypes.c_void_p
                fn.argtypes = []
                lines.append(f'  {name}() -> {mnemonic_of(lib, fn())}')
        if hasattr(process, 'gnc_book_get_book_currency_name'):
            fn = process.gnc_book_get_book_currency_name
            fn.restype = ctypes.c_char_p
            fn.argtypes = [ctypes.c_void_p]
            lines.append(f'  gnc_book_get_book_currency_name(book) -> {fn(book_pointer)!r}')
        root = book.get_root_account()
        root_commodity = root.GetCommodity()
        lines.append(f'root account commodity: '
                     f'{root_commodity.get_mnemonic() if root_commodity is not None else None}')

        guile = load_guile()
        gr._make_current(repo.session)
        work = Path(tempfile.mkdtemp())
        errors = work / 'errors.txt'

        def run(scheme):
            if errors.exists():
                errors.unlink()
            wrapped = (f'(catch #t (lambda () {scheme} #t)'
                       f' (lambda (key . args)'
                       f'   (call-with-output-file {gr._scheme_string(str(errors))}'
                       f'     (lambda (port) (display (list key args) port)))))')
            guile.scm_eval_string(guile.scm_from_utf8_string(wrapped.encode('utf-8')))
            if errors.exists():
                raise gr.PageNotRenderedError(errors.read_text(errors='replace')[:400])

        gr._dialect(run, work)
        for module in ('(gnucash reports standard balance-sheet)', '(gnucash report standard-reports)'):
            with contextlib.suppress(gr.PageNotRenderedError):
                run(f'(use-modules {module})')
        answer = work / 'report-currency.txt'
        try:
            run(f'(let* ((options (gnc:make-report-options {gr._scheme_string(BALANCE_SHEET)}))'
                f'       (option (gnc:lookup-option options "Commodities" "Report\'s currency"))'
                f'       (value (if (defined? (quote gnc:option-value)) (gnc:option-value option)'
                f'                  (gnc-optiondb-lookup-value (gnc:optiondb options) "Commodities" "Report\'s currency"))))'
                f'  (call-with-output-file {gr._scheme_string(str(answer))}'
                f'    (lambda (port) (display (gnc-commodity-get-mnemonic value) port))))')
            lines.append(f"Balance Sheet 'Report's currency' default: {answer.read_text()}")
        except gr.PageNotRenderedError as error:
            lines.append(f"Balance Sheet 'Report's currency' default: not read — {error}")
        gr._make_current(None)
    finally:
        repo.close()
    (out / 'book-currency.txt').write_text('\n'.join(lines) + '\n')
    print('\n'.join(lines))


if __name__ == '__main__':
    main()
