"""Rates and prices given in a file, added to a book's price database for one report run.

Q-042: `--fx-rates` and `--prices` on `balance-sheet`, `income-statement` and
`report` are not multiplied by anything here. Each rate or price becomes a price
in the open book's price database, and GnuCash's report prices from it at the
report's own price source. The book is open read-only and is never saved, so
none of these prices is kept. Measured on GnuCash 5.10 and 3.8
(`tests/research/a_rates_file_as_prices_probe.py`): a price added this way at
the moment the report is for is the one GnuCash's Balance Sheet uses, whether
the book has no price that day, a price the same day, or a price twelve hours
away; and the book's prices read back unchanged after it is closed.

A file gives each commodity a price:

    USD: 1.40            # USD in the report's currency, at the moment the report is for
    HKD: 2/11            # a fraction, as `value:` in a `price` block may be
    USD/CAD:             # the currency stated; for a rate it must be the report's
      2026-01-05: 1.35   # a price on that day, timed as a `price` block's date is
    AMZN: 250            # a security, in the currency the book prices it in
    ACME/CAD: 60         # a security, in the currency stated

A security's price with no currency is in the currency of the book's own
prices of that security, or, where the book has none, the currency of the
transactions that hold it. Where either gives more than one currency, the file
has to state it.
"""

import datetime
from dataclasses import dataclass
from fractions import Fraction
from typing import List, Optional, Sequence, Tuple

import yaml

from infrastructure.gnucash.engine import load_gnc_engine
from infrastructure.gnucash.utils import qof_pointer
from services.prices import (
    PriceRefusedError,
    _create,
    _either_way,
    _exact_value,
    _moment,
    _Plan,
    prices_in_book,
)

# The source GnuCash's price editor gives a price. Measured with the book's own
# price on the same day, from the same source, at 1.40: the report used the
# file's 1.50.
_SOURCE = 'user:price-editor'
_TYPE = 'last'


class RatesFileError(Exception):
    """A rates or prices file that cannot price the report, carrying the sentence a reader is given."""


@dataclass(frozen=True)
class Quote:
    """One price a file gives."""

    file: str
    key: str                        # as the file writes it: "USD", "USD/CAD", "AMZN"
    mnemonic: str
    currency: Optional[str]         # the currency after the slash, when the key gives one
    day: Optional[datetime.date]    # None for a price at the moment the report is for
    value: Tuple[int, int]


def read_quotes(path) -> List[Quote]:
    """Every price the file at `path` gives, or the reason it gives none."""
    try:
        with open(path, encoding='utf-8') as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        raise RatesFileError(f'{path} is not YAML: {exc}') from exc
    except UnicodeDecodeError as exc:
        # PyYAML reads the stream itself, so the decode happens inside
        # `safe_load` and comes out as a `UnicodeDecodeError` — a `ValueError`,
        # which is neither a `YAMLError` nor an `OSError`, so it reached the
        # reader as a traceback. A file saved as UTF-16, or as Latin-1 with one
        # accented character in a comment, is the ordinary way to meet it.
        raise RatesFileError(f'{path} is not UTF-8 text: {exc}') from exc
    if not isinstance(data, dict) or not data:
        raise RatesFileError(f'{path} gives no prices; it gives each commodity its price, as "USD: 1.40"')
    quotes = []
    for key, given in data.items():
        written = str(key).strip()
        mnemonic, slash, currency = (part.strip() for part in written.partition('/'))
        if not mnemonic or (slash and not currency):
            raise RatesFileError(f'{path}: "{written}" is neither a commodity, as "USD", nor a '
                                 f'commodity and a currency, as "USD/CAD"')
        if isinstance(given, dict):
            if not given:
                raise RatesFileError(f'{path}: {written} gives no dated prices')
            for day, value in given.items():
                quotes.append(Quote(str(path), written, mnemonic, currency or None,
                                    _day(path, written, day), _value(path, written, value)))
        else:
            quotes.append(Quote(str(path), written, mnemonic, currency or None, None,
                                _value(path, written, given)))
    return quotes


def _day(path, key, given) -> datetime.date:
    if isinstance(given, datetime.datetime):
        return given.date()
    if isinstance(given, datetime.date):
        return given
    try:
        return datetime.datetime.strptime(str(given), '%Y-%m-%d').date()
    except ValueError:
        raise RatesFileError(f'{path}: {key}: "{given}" is not a date, "YYYY-MM-DD"') from None


def _value(path, key, given) -> Tuple[int, int]:
    if isinstance(given, bool) or not isinstance(given, (int, float, str)):
        raise RatesFileError(f'{path}: {key}: "{given}" is not a price, as "1.40" or "2/11"')
    try:
        num, denom = _exact_value(given)
    except PriceRefusedError as reason:
        raise RatesFileError(f'{path}: {key}: {reason}') from None
    if num <= 0:
        raise RatesFileError(f'{path}: {key}: a price is more than zero, and this one is {given}')
    return num, denom


def add_for_the_run(book, rates: Sequence[Quote], prices: Sequence[Quote], report_currency: str,
                    report_days: Sequence[datetime.date]) -> None:
    """Add every rate and price to the open book's price database.

    A price with no date is added at the end of each day in `report_days`, the
    moment a report for that day is for. Every quote is checked before any is
    added, so a refused file adds nothing.
    """
    lib = load_gnc_engine()
    table = book.get_table()
    report_commodity = table.lookup('CURRENCY', report_currency)
    planned = []
    for quote in rates:
        commodity = table.lookup('CURRENCY', quote.mnemonic.upper())
        if commodity is None:
            raise RatesFileError(f'{quote.file}: {quote.key}: GnuCash knows no currency {quote.mnemonic}')
        if quote.currency is not None and quote.currency.upper() != report_currency:
            raise RatesFileError(
                f'{quote.file}: {quote.key} is a price in {quote.currency}, and a rate is a price '
                f'in the report\'s currency, {report_currency}; write it as '
                f'"{quote.mnemonic}/{report_currency}", or leave the currency out')
        if quote.mnemonic.upper() == report_currency:
            if Fraction(*quote.value) != 1:
                raise RatesFileError(f'{quote.file}: {quote.key}: {report_currency} is the report\'s '
                                     f'currency, and its price in itself is 1')
            continue
        planned.append((quote, commodity, report_commodity))
    if prices:
        held = prices_in_book(book)
        for quote in prices:
            commodity = _the_security(book, quote)
            planned.append((quote, commodity, _the_price_currency(book, table, held, commodity, quote)))

    book_pointer = qof_pointer(book)
    db = lib.gnc_pricedb_get_db(book_pointer)
    end_of_each_day = sorted({lib.gnc_dmy2time64_end(day.day, day.month, day.year)
                              for day in report_days})
    wanted = []
    for quote, commodity, currency in planned:
        moments = [_moment(lib, quote.day.isoformat())] if quote.day is not None else end_of_each_day
        for moment in moments:
            wanted.append((quote, commodity, currency, moment))

    # One price a day, per pair, whichever way round it is written (Q-041,
    # table 1). Adding a second displaces the first, and the source these are
    # given — the price editor's — outranks every other, so the quote written
    # last would simply win and the other would be dropped with nothing said.
    # The `price` block importer refuses that shape out loud, and a file read
    # for one run gets the same answer rather than a page whose figures depend
    # on the order its rates were typed in.
    #
    # Asked of the moments rather than of the quotes: an undated quote lands
    # at the end of every day the run reports for, so it is legitimately on
    # several days, and what collides is two quotes landing on one.
    first_on_a_day = {}
    for quote, commodity, currency, moment in wanted:
        key = (_either_way(qof_pointer(commodity), qof_pointer(currency)),
               lib.gnc_time64_get_day_start(moment))
        first = first_on_a_day.setdefault(key, quote)
        if first is not quote:
            raise RatesFileError(
                f'{quote.file}: {first.key} and {quote.key} are both prices of '
                f'{commodity.get_mnemonic()} in {currency.get_mnemonic()} on one day. '
                f'GnuCash keeps one price a day for a commodity and a currency, whichever '
                f'way round it is written, so which one the report used would depend on '
                f'their order in the file. Give one of them.')

    for quote, commodity, currency, moment in wanted:
        _create(lib, book_pointer, db, _Plan(
            label=quote.key, action='create', commodity=qof_pointer(commodity),
            currency=qof_pointer(currency), pair=quote.key, time=moment, value=quote.value,
            source=_SOURCE, type=_TYPE))


def _accounts_holding(book, commodity):
    namespace, mnemonic = commodity.get_namespace(), commodity.get_mnemonic()
    for account in book.get_root_account().get_descendants():
        held = account.GetCommodity()
        if held is not None and (held.get_namespace(), held.get_mnemonic()) == (namespace, mnemonic):
            yield account


def _the_security(book, quote: Quote):
    found = {}
    for account in book.get_root_account().get_descendants():
        commodity = account.GetCommodity()
        if (commodity is not None and commodity.get_namespace() != 'CURRENCY'
                and commodity.get_mnemonic() == quote.mnemonic):
            found[(commodity.get_namespace(), commodity.get_mnemonic())] = commodity
    if not found:
        raise RatesFileError(f'{quote.file}: {quote.key}: no account in the book holds a security '
                             f'{quote.mnemonic}')
    if len(found) > 1:
        both = ' and '.join(f'{namespace}:{mnemonic}' for namespace, mnemonic in sorted(found))
        raise RatesFileError(f'{quote.file}: {quote.key}: the book holds {both}, and a prices file '
                             f'cannot tell them apart')
    return next(iter(found.values()))


def _the_price_currency(book, table, held, commodity, quote: Quote):
    if quote.currency is not None:
        currency = table.lookup('CURRENCY', quote.currency.upper())
        if currency is None:
            raise RatesFileError(f'{quote.file}: {quote.key}: GnuCash knows no currency {quote.currency}')
        return currency
    namespace, mnemonic = commodity.get_namespace(), commodity.get_mnemonic()
    priced_in = {price.currency_mnemonic for price in held
                 if (price.namespace, price.mnemonic) == (namespace, mnemonic)
                 and price.currency_namespace == 'CURRENCY'}
    if priced_in:
        where = f'the book prices {mnemonic} in'
    else:
        priced_in = {split.GetParent().GetCurrency().get_mnemonic()
                     for account in _accounts_holding(book, commodity)
                     for split in account.GetSplitList()}
        where = f'the book prices {mnemonic} in no currency, and its transactions are in'
    if len(priced_in) == 1:
        return table.lookup('CURRENCY', priced_in.pop())
    currencies = ', '.join(sorted(priced_in)) or 'none'
    raise RatesFileError(f'{quote.file}: {quote.key}: {where} {currencies}, so the price\'s currency '
                         f'is not known; give it, as "{mnemonic}/USD"')
