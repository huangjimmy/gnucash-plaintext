"""Check whether a book is consistent and balanced, and report what is not.

It reads the finished book and prints what it found. Four things, each an
exact comparison:

* **The balance sheet balances.** `total_assets` equals
  `total_liabilities_and_equity`. Those two are built from figures GnuCash
  converts at the report-date price, and the only figure the page chooses is
  `total_unrealized_gains`, so a page that does not balance is a page stating
  an unrealized gain that contradicts everything around it.
* **The income statement accounts for the retained earnings.** Drawn over the
  book's whole life, `net_income` is `retained_earnings` on the sheet together
  with what closing entries moved into equity: the income statement leaves out
  every entry carrying GnuCash's closing flag, and the sheet's figure is only
  the profit not closed yet. The two come from two reports over two account
  sets, so they can differ, and a transaction the income statement takes for a
  closing entry that carries no closing flag is what makes them.
* **Every income and expense account is kept in the book's own currency.** An
  expense is what it cost on the day it was incurred, and its account's balance
  is a sum of amounts from many days, each of those days having had a rate of
  its own. No one rate turns that sum into the book's currency, so a statement
  converting it at the report date's rate states an expense at a rate it was
  never incurred at. gnucash-plaintext does not support such an account, and
  both statements print a warning listing it.
* **No cost basis holds more than the accounts do**, per currency and side.
  Cost bases falling short is an ordinary state — currency that arrived in a
  transaction stating no figure in the book's own currency has no cost, so no
  cost basis was opened for it, and the balance sheet says so with
  `measured_from: gnucash_revaluation`. Holding *more* is not: it is the book
  offering currency it does not have.

`verify_cost_bases` runs as well, so one pass reports everything: a balance
above what a cost basis brought in or below zero, and a stored cost that has
drifted from the transaction it was derived from.

**It is expensive**, which is why it is a flag rather than something every
command does. Each statement is a GnuCash report drawn through Guile, and the
cost-basis pass walks every split in the book.

Read-only, and reported rather than raised: it describes a book that already
exists, so a caller decides what to do about what it says.
"""

import re
from dataclasses import dataclass, field
from datetime import date
from fractions import Fraction
from typing import Dict, List, Optional

from gnucash import ACCT_TYPE_EXPENSE, ACCT_TYPE_INCOME
from gnucash.gnucash_core_c import xaccTransGetIsClosingTxn

from infrastructure.gnucash.utils import money_text, numeric_to_fraction
from services.book_currency import (
    BookCurrencyUnknownError,
    book_currency,
    the_books_own_currency_or,
)
from services.foreign_currency import (
    cost_basis_items_by_currency_and_side,
    foreign_currency_account_balances,
    iter_splits,
    profit_and_loss_accounts_in_another_currency,
    verify_cost_bases,
)
from services.gnucash_statements import (
    render_balance_sheet,
    render_income_statement,
)

A_KEY = r'^\t{name}: (-?[\d.]+)'


@dataclass
class IntegrityReport:
    """What the check looked at, and what it found wrong."""

    as_of: Optional[date] = None
    currency: Optional[str] = None
    checked: List[str] = field(default_factory=list)
    findings: List[str] = field(default_factory=list)
    not_checked: List[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        """True where the book is consistent and balanced."""
        return not self.findings


def _figure(page: str, name: str) -> Optional[Fraction]:
    """A top-level key's figure from a plaintext statement, exactly."""
    found = re.search(A_KEY.format(name=re.escape(name)), page, re.M)
    return Fraction(found.group(1)) if found else None


def last_transaction_date(book) -> Optional[date]:
    """The date of the last transaction in the book, or None for an empty one.

    The statements are drawn to this rather than to today, so every transaction
    the book holds is on the page. Drawn to today, a book whose last entry is
    dated next month would be checked against a page that leaves that entry
    off, and the two figures either side of it would disagree for a reason that
    is not a fault.
    """
    latest = None
    for split in iter_splits(book):
        when = split.GetParent().GetDate().date()
        if latest is None or when > latest:
            latest = when
    return latest


def _holdings(book, as_of: date, units: Dict[str, int]) -> Dict[tuple, Fraction]:
    """Per commodity and side, what the accounts held at the end of `as_of`.

    The same shape `cost_basis_items_by_currency_and_side` answers in, so the
    two can be compared entry by entry: a cost basis balance is stored positive
    whichever side it sits on, and what the accounts hold is read the same way.

    To the same date as the cost bases, because the comparison is of one book at
    one moment. Read whole against bases read to a date, a book checked at
    2028-06-30 reported cost bases holding a loan it repaid in December and
    seven shares it sold there.
    """
    held: Dict[tuple, Fraction] = {}
    for row in foreign_currency_account_balances(book, as_of):
        units[row['currency']] = row['unit']
        balance = row['balance']
        if balance == 0:
            continue
        at = (row['currency'], 'asset' if balance > 0 else 'liability')
        held[at] = held.get(at, Fraction(0)) + abs(balance)
    return held


def _cost_bases(book, as_of: date, units: Dict[str, int]) -> Dict[tuple, Fraction]:
    totals: Dict[tuple, Fraction] = {}
    for row in cost_basis_items_by_currency_and_side(book, as_of):
        units[row['currency']] = row['unit']
        at = (row['currency'], row['side'])
        totals[at] = totals.get(at, Fraction(0)) + row['balance']
    return totals


def _money(figure: Fraction, unit: int) -> str:
    """A figure at its commodity's own decimals, grouped in thousands, exactly.

    `unit` is the commodity's smallest unit — 100 for a dollar, 1 for a yen,
    10000 for a share counted to four places — so a figure is never padded or
    cut to a number of places another commodity uses.
    """
    text = money_text(figure, unit)
    sign = '-' if text.startswith('-') else ''
    whole, point, decimals = text.lstrip('-').partition('.')
    return f'{sign}{int(whole):,}{point}{decimals}'


def check_a_book(session, book, as_of: Optional[date] = None,
                 currency: Optional[str] = None) -> IntegrityReport:
    """Run every check, and report what the book got wrong.

    `as_of` defaults to the date of the book's last transaction, and `currency`
    to the currency the book is kept in. A book that states neither is checked
    for what can be checked without them, and the report lists what was left
    out and why.
    """
    report = IntegrityReport()

    report.as_of = as_of or last_transaction_date(book)
    if report.as_of is None:
        report.not_checked.append(
            'the book holds no transaction, so neither statement was drawn')
    else:
        _check_the_statements(session, book, report, currency)

    _check_the_cost_bases(book, report)
    return report


def _check_the_statements(session, book, report: IntegrityReport,
                          currency: Optional[str]) -> None:
    # A currency given with `--currency` is looked up as `balance-sheet` looks
    # it up. Handed to GnuCash unchecked, 5.x refuses to render and 4.13 and
    # older draw both pages in it and report the book balanced.
    try:
        report.currency = book_currency(book, currency)
    except BookCurrencyUnknownError as unknown:
        report.not_checked.append(
            f'neither statement was drawn: {unknown}')
        return

    own = the_books_own_currency_or(book, report.currency)
    all_in_one_currency = _check_the_profit_and_loss_currency(book, own, report)
    if own != report.currency:
        # Drawn in a currency that is not the book's own, both statements
        # convert every income and expense account at their own date's rate,
        # and a balance summed over many days has no one rate — so the page
        # cannot balance on the book's own figures, and a finding here would
        # blame the book for the currency the reader chose to read it in.
        report.not_checked.append(
            f'the balance sheet and the income statement: drawn in '
            f'{report.currency}, and the book is kept in {own}, so every income '
            f'and expense account is converted at the rate of the page\'s own '
            f'date. Check the book in {own}.')
        return

    first = date(report.as_of.year - 200, 1, 1)
    sheet = render_balance_sheet(session, report.currency, report.as_of,
                                 itemize=False)
    statement = render_income_statement(session, report.currency,
                                        first, report.as_of)

    unit = book.get_table().lookup('CURRENCY', report.currency).get_fraction()
    report.checked.append(f'the balance sheet as of {report.as_of} balances')
    # Both keys are on every page that is drawn at all — a statement has a
    # bottom line whatever it comes to, and a book with no accounts to total is
    # turned away before this by having no currency and no transaction.
    assets = _figure(sheet, 'total_assets')
    both = _figure(sheet, 'total_liabilities_and_equity')
    if assets != both:
        report.findings.append(
            f'the balance sheet does not balance: it states '
            f'{_money(assets, unit)} of assets against {_money(both, unit)} of '
            f'liabilities and equity. Every other figure on that page is '
            f'GnuCash\'s own, so the one it chooses — '
            f'total_unrealized_gains — is what disagrees with them. Build '
            f'the book one transaction at a time and draw the sheet after '
            f'each to find which transaction it starts at.')

    if not all_in_one_currency:
        # What a closing entry moved out of such an account is in that
        # account's currency, and both statements convert its balance at a rate
        # it was never incurred at — the finding above — so there is no figure
        # to compare.
        report.not_checked.append(
            "the income statement's net income against the sheet's retained "
            "earnings: the income and expense accounts above are not kept in "
            f"{own}")
        return
    closed = _closed_into_equity(book, report.as_of)
    report.checked.append(
        "the income statement's net income is the sheet's retained earnings "
        "and what closing entries moved into equity")
    # A key the page leaves off states nothing: a sheet drawn the day the
    # books were closed has no profit left unclosed to report.
    kept = _figure(sheet, 'retained_earnings') or Fraction(0)
    earned = _figure(statement, 'net_income') or Fraction(0)
    if kept + closed != earned:
        report.findings.append(
            f'the income statement for the whole book states net_income '
            f'{_money(earned, unit)}, and the balance sheet states '
            f'retained_earnings {_money(kept, unit)}, with '
            f'{_money(closed, unit)} moved into equity by closing entries. The '
            f'income statement leaves out every closing entry, so the first '
            f'figure is the other two added together, and it is not: it left '
            f'out a transaction no closing entry accounts for — one whose '
            f'description matches its Closing Entries pattern without being a '
            f'closing entry.')


def _closed_into_equity(book, as_of: date) -> Fraction:
    """What the book's closing entries moved out of income and expense by `as_of`.

    A closing entry carries GnuCash's closing flag, which is what `close-books`
    sets and what the income statement leaves out. Its splits on income and
    expense accounts empty them, debiting an income account by the profit it
    held, so their sum is the profit moved into equity. Asked only of a book
    whose income and expense accounts are all in its own currency, so every
    amount summed here is in that currency.
    """
    closed = Fraction(0)
    for split in iter_splits(book):
        account = split.GetAccount()
        if account.GetType() not in (ACCT_TYPE_INCOME, ACCT_TYPE_EXPENSE):
            continue
        transaction = split.GetParent()
        if not xaccTransGetIsClosingTxn(transaction.instance):
            continue
        if transaction.GetDate().date() > as_of:
            continue
        closed += numeric_to_fraction(split.GetAmount())
    return closed


def _check_the_profit_and_loss_currency(book, own: str,
                                        report: IntegrityReport) -> bool:
    """Whether every income and expense account is in the book's own currency.

    The book's, not the one the statements are drawn in: a Canadian book drawn
    in US dollars keeps its accounts in Canadian dollars, which is right, and
    reading the rule against the page's currency listed every one of them and
    told the reader to keep them in US dollars.
    """
    report.checked.append(
        "every income and expense account is kept in the book's own currency")
    wrong = profit_and_loss_accounts_in_another_currency(book, own)
    if not wrong:
        return True
    listed = ', '.join(f'{row["account"]} ({row["currency"]})' for row in wrong)
    report.findings.append(
        f'these income and expense accounts are not kept in '
        f'{own}: {listed}. gnucash-plaintext does not support one. '
        f'Such a balance is a sum of amounts from many days, each of those days '
        f'having had a rate of its own, and no one rate turns that sum into '
        f'{own}. Both statements convert it at the report date\'s '
        f'rate, which states an expense at a rate it was never incurred at, so '
        f'a page drawn a month later states the same expense differently. Keep '
        f'the account in {own}, and record a payment made in '
        f'another currency at what that currency cost on the day it was spent.')
    return False


def _check_the_cost_bases(book, report: IntegrityReport) -> None:
    if report.as_of is not None:
        report.checked.append(
            'no cost basis holds more of a currency than the accounts do')
        units: Dict[str, int] = {}
        held = _holdings(book, report.as_of, units)
        for at, balance in sorted(_cost_bases(book, report.as_of, units).items()):
            commodity, side = at
            theirs = held.get(at, Fraction(0))
            if balance > theirs:
                what = 'holds' if side == 'asset' else 'owes'
                report.findings.append(
                    f'the {commodity} cost bases on the {side} side hold '
                    f'{_money(balance, units[commodity])}, and the book {what} '
                    f'{_money(theirs, units[commodity])}. A cost basis standing for currency '
                    f'that is gone offers what cannot be sold: a disposal '
                    f'drew it down by less than it spent, or drew nothing '
                    f'down at all.')

    report.checked.append('every cost basis agrees with the ledger it comes from')
    verified = verify_cost_bases(book, totals=False)
    for finding in verified['findings']:
        for problem in finding['problems']:
            report.findings.append(
                f'{finding["date"]} {finding["account"]} '
                f'{finding["guid"]}: {problem}')


def say_what_it_found(report: IntegrityReport) -> str:
    """The report, as a page for a person to read."""
    lines = ['', 'Integrity check']
    if report.as_of is not None:
        drawn = f'  as of {report.as_of}'
        if report.currency:
            drawn += f', in {report.currency}'
        lines.append(drawn)
    lines.append('')
    for checked in report.checked:
        lines.append(f'  checked: {checked}')
    for left in report.not_checked:
        lines.append(f'  not checked: {left}')
    lines.append('')
    if report.passed:
        lines.append('  The book is consistent and balanced.')
    else:
        lines.append(f'  {len(report.findings)} thing(s) are wrong with this book:')
        lines.append('')
        for finding in report.findings:
            lines.append(f'    - {finding}')
    lines.append('')
    return '\n'.join(lines)
