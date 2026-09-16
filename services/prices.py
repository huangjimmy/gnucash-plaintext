"""A book's prices: read from GnuCash's price database, changed by `price` blocks, and written out.

Every rule here rests on a measurement, and the measurements are in
docs/issues/Q-041-a-price-cannot-be-recorded-for-a-past-date-or-kept-through-export-and-import.md.
The ones the code turns on:

- GnuCash keeps one price a local day for a commodity and a currency,
  whichever way round the price is written: USD in CAD and CAD in USD share
  the day. Adding a price, or editing a price's time, onto a day that already
  holds one quietly deletes the other or leaves the new one out (tables 1 and
  4). So a block that would put two prices of a pair on one day is refused
  here, before GnuCash is asked to do anything. Only a new price, or an edit
  changing a price's time, puts a price on a day: a book can already hold two
  prices of a pair on one local day of this machine, added where that day was
  two, and a block that moves neither is not refused for it.
- A guid is one object across the book, so a new price's stated guid is
  refused when another kind of object holds it.
- A source GnuCash does not define is stored as `invalid`, silently (table 5).
  So a stated source is set on a scratch price first, and refused when it does
  not read back as written.
- A price's commodity and currency are what the database files it under, so
  neither changes on a price that already exists.
- A price's value is set exactly as written — `"21845/100"` stays 21845/100 —
  so a ledger exported, imported and exported again reads the same.
"""

import calendar
import ctypes
import datetime
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Dict, List, Optional, Sequence, Tuple

from infrastructure.gnucash.engine import (
    PRICE_FOREACH_FUNC,
    GDateC,
    GncNumericC,
    guid_from_hex,
    load_gnc_engine,
)
from infrastructure.gnucash.utils import encode_value_as_string, qof_pointer
from services.gnucash_importer import _guid_in_use_anywhere, the_guid_a_block_names
from services.plaintext_parser import DirectiveType

# The source GnuCash gives a price nobody set one on, measured on every build.
GNUCASH_DEFAULT_SOURCE = 'invalid'

_RATIO = re.compile(r'([+-]?\d+)/(\d+)')
_DECIMAL = re.compile(r'([+-]?)(\d+)(?:\.(\d+))?')
_DATE = re.compile(r'\d{4}-\d{2}-\d{2}')
_INT64 = 2 ** 63


class PriceRefusedError(Exception):
    """A price block that cannot be applied, carrying the sentence a reader is given."""


@dataclass(frozen=True)
class BookPrice:
    """One entry of a book's price database, as read from it."""

    pointer: int
    guid: str
    commodity: int
    currency: int
    namespace: str
    mnemonic: str
    currency_namespace: str
    currency_mnemonic: str
    time: int
    num: int
    denom: int
    source: str
    type: Optional[str]

    @property
    def value(self) -> Fraction:
        return Fraction(self.num, self.denom)

    @property
    def pair(self) -> str:
        return f'{self.namespace}:{self.mnemonic} in {self.currency_mnemonic}'


def _either_way(commodity: int, currency: int) -> Tuple[int, int]:
    """A commodity and a currency as one key, whichever way round a price has them.

    GnuCash's one price a day holds for USD in CAD and CAD in USD together
    (Q-041, table 1), so every same-day question is asked of this key.
    """
    return (commodity, currency) if commodity <= currency else (currency, commodity)


def _text(raw: Optional[bytes]) -> Optional[str]:
    return raw.decode('utf-8') if raw is not None else None


def _guid_of(lib, pointer: int) -> str:
    buffer = ctypes.create_string_buffer(33)
    lib.guid_to_string_buff(lib.qof_instance_get_guid(pointer), buffer)
    return buffer.value.decode()


def _read(lib, pointer: int) -> BookPrice:
    commodity = lib.gnc_price_get_commodity(pointer)
    currency = lib.gnc_price_get_currency(pointer)
    value = lib.gnc_price_get_value(pointer)
    return BookPrice(
        pointer=pointer,
        guid=_guid_of(lib, pointer),
        commodity=commodity,
        currency=currency,
        namespace=_text(lib.gnc_commodity_get_namespace(commodity)),
        mnemonic=_text(lib.gnc_commodity_get_mnemonic(commodity)),
        currency_namespace=_text(lib.gnc_commodity_get_namespace(currency)),
        currency_mnemonic=_text(lib.gnc_commodity_get_mnemonic(currency)),
        time=lib.gnc_price_get_time64(pointer),
        num=value.num,
        denom=value.denom,
        source=_text(lib.gnc_price_get_source_string(pointer)) or '',
        type=_text(lib.gnc_price_get_typestr(pointer)),
    )


def prices_in_book(book) -> List[BookPrice]:
    """Every price the book holds."""
    lib = load_gnc_engine()
    pointers = []

    def each(price, _data):
        pointers.append(price)
        return 1

    callback = PRICE_FOREACH_FUNC(each)
    lib.gnc_pricedb_foreach_price(lib.gnc_pricedb_get_db(qof_pointer(book)), callback, None, 1)
    return [_read(lib, pointer) for pointer in pointers]


def written_time(seconds: int) -> str:
    """A time as a `time:` line writes it: in UTC, to the second, with its offset."""
    return time.strftime('%Y-%m-%d %H:%M:%S +0000', time.gmtime(seconds))


def _day_text(lib, seconds: int) -> str:
    """The local day GnuCash reckons a moment to fall on, for a message."""
    return time.strftime('%Y-%m-%d', time.localtime(lib.gnc_time64_get_day_start(seconds)))


# ── Export ───────────────────────────────────────────────────────────────────

def select_prices(prices: Sequence[BookPrice], start_date: Optional[datetime.date] = None,
                  end_date: Optional[datetime.date] = None,
                  latest: Optional[int] = None) -> List[BookPrice]:
    """The prices `--start-date`, `--end-date` and `--latest` keep, in the order a ledger writes them.

    A day is the day GnuCash reckons where the command runs, from the start of
    `start_date` to the end of `end_date`. `latest` keeps the most recent prices
    of each commodity in each currency — each direction apart — counting back
    from the end of `end_date`, or from the end of today without one.
    """
    lib = load_gnc_engine()
    low = (lib.gnc_dmy2time64(start_date.day, start_date.month, start_date.year)
           if start_date is not None else None)
    if end_date is not None:
        high = lib.gnc_dmy2time64_end(end_date.day, end_date.month, end_date.year)
    elif latest is not None:
        high = lib.gnc_time64_get_today_end()
    else:
        high = None
    kept = [price for price in prices
            if (low is None or price.time >= low) and (high is None or price.time <= high)]
    if latest is not None:
        by_pair = defaultdict(list)
        for price in kept:
            by_pair[(price.commodity, price.currency)].append(price)
        kept = [price for group in by_pair.values()
                for price in sorted(group, key=lambda p: p.time, reverse=True)[:latest]]
    return sorted(kept, key=lambda p: (p.namespace, p.mnemonic, p.currency_mnemonic, p.time))


def format_price_blocks(prices: Sequence[BookPrice]) -> str:
    """The `price` blocks of a ledger, one per price, separated by a blank line."""
    blocks = []
    for price in prices:
        lines = [
            'price',
            f'\tguid: {encode_value_as_string(price.guid)}',
            f'\tcommodity.namespace: {encode_value_as_string(price.namespace)}',
            f'\tcommodity.mnemonic: {encode_value_as_string(price.mnemonic)}',
            f'\tcurrency.mnemonic: {encode_value_as_string(price.currency_mnemonic)}',
            f'\ttime: {encode_value_as_string(written_time(price.time))}',
            f'\tvalue: {encode_value_as_string(f"{price.num}/{price.denom}")}',
            f'\tsource: {encode_value_as_string(price.source)}',
        ]
        if price.type:
            lines.append(f'\ttype: {encode_value_as_string(price.type)}')
        blocks.append('\n'.join(lines))
    return '\n\n'.join(blocks) + '\n' if blocks else ''


def commodities_of(prices: Sequence[BookPrice], book) -> list:
    """The commodities and currencies the prices are of, once each, as the book holds them."""
    table = book.get_table()
    seen = set()
    commodities = []
    for price in prices:
        for namespace, mnemonic in ((price.namespace, price.mnemonic),
                                    (price.currency_namespace, price.currency_mnemonic)):
            if (namespace, mnemonic) in seen:
                continue
            seen.add((namespace, mnemonic))
            # Always found: a price's commodity and currency are the table's own.
            commodities.append(table.lookup(namespace, mnemonic))
    return commodities


# ── Import ───────────────────────────────────────────────────────────────────

@dataclass
class PriceImportResult:
    """What an import did with the price blocks of one file."""

    seen: int = 0
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    refusals: List[str] = field(default_factory=list)

    @property
    def refused(self) -> int:
        return len(self.refusals)


@dataclass
class _Plan:
    label: str
    action: str                     # 'create', 'update' or 'unchanged'
    commodity: int
    currency: int
    pair: str
    time: int
    guid: Optional[str] = None
    existing: Optional[BookPrice] = None
    value: Optional[Tuple[int, int]] = None
    source: Optional[str] = None
    type: Optional[str] = None
    changes: Dict[str, object] = field(default_factory=dict)


def _stated(value) -> str:
    """A metadata value as the text the file wrote."""
    return str(getattr(value, 'source', value))


def _label(metadata) -> str:
    parts = ['price']
    if metadata.get('guid') not in (None, ''):
        parts.append(_stated(metadata['guid']))
    namespace = metadata.get('commodity.namespace')
    mnemonic = metadata.get('commodity.mnemonic')
    if mnemonic is not None:
        parts.append(f'{_stated(namespace)}:{_stated(mnemonic)}' if namespace is not None
                     else _stated(mnemonic))
    if metadata.get('currency.mnemonic') is not None:
        parts.append(f'in {_stated(metadata["currency.mnemonic"])}')
    if metadata.get('time') is not None:
        parts.append(f'at {_stated(metadata["time"])}')
    return ' '.join(parts)


def _exact_value(value) -> Tuple[int, int]:
    """A `value:` as the numerator and denominator it was written with, never through a float."""
    text = repr(value) if isinstance(value, float) else _stated(value).strip()
    ratio = _RATIO.fullmatch(text)
    if ratio:
        num, denom = int(ratio.group(1)), int(ratio.group(2))
    else:
        decimal = _DECIMAL.fullmatch(text)
        if not decimal:
            raise PriceRefusedError(f'value: "{text}" is not a number, a decimal such as '
                               f'"1.3642" or a fraction such as "21845/100"')
        sign, whole, digits = decimal.group(1), decimal.group(2), decimal.group(3) or ''
        num = int(sign + whole + digits)
        denom = 10 ** len(digits)
    if denom == 0:
        raise PriceRefusedError(f'value: "{text}" divides by zero')
    if abs(num) >= _INT64 or denom >= _INT64:
        raise PriceRefusedError(f'value: "{text}" is too large for GnuCash to store')
    return num, denom


def _moment(lib, value) -> int:
    """A `time:` as seconds since the epoch: a moment as written, or a date at the time GnuCash gives it."""
    text = _stated(value).strip()
    if _DATE.fullmatch(text):
        try:
            day = datetime.date(int(text[0:4]), int(text[5:7]), int(text[8:10]))
        except ValueError:
            raise PriceRefusedError(f'time: "{text}" is not a date') from None
        date = GDateC()
        lib.g_date_clear(ctypes.byref(date), 1)
        lib.g_date_set_dmy(ctypes.byref(date), day.day, day.month, day.year)
        return lib.gdate_to_time64(date)
    try:
        moment = datetime.datetime.strptime(text, '%Y-%m-%d %H:%M:%S %z')
    except ValueError:
        raise PriceRefusedError(f'time: "{text}" is neither a date, "YYYY-MM-DD", nor a moment, '
                           f'"YYYY-MM-DD HH:MM:SS +HHMM"') from None
    return calendar.timegm(moment.utctimetuple())


def _source_gnucash_stores(lib, book_ptr: int, source: str, known: Dict[str, bool]) -> bool:
    """Whether this GnuCash stores `source` as written, asked of a price that is then thrown away."""
    if source not in known:
        scratch = lib.gnc_price_create(book_ptr)
        lib.gnc_price_begin_edit(scratch)
        lib.gnc_price_set_source_string(scratch, source.encode('utf-8'))
        stored = _text(lib.gnc_price_get_source_string(scratch))
        lib.gnc_price_commit_edit(scratch)
        lib.gnc_price_unref(scratch)
        known[source] = stored == source
    return known[source]


# Every key a `price` block may give. A price has no custom metadata, so a key
# outside these would be dropped, and a correction written under a misspelled
# key lost with the price reported unchanged.
_KEYS_A_PRICE_TAKES = ('guid', 'commodity.namespace', 'commodity.mnemonic', 'currency.mnemonic',
                       'time', 'value', 'source', 'type')


def _plan(lib, book, book_ptr, table, index, block, known_sources) -> _Plan:
    """What one block asks of the book, or the reason it cannot be done."""
    metadata = block.metadata
    label = _label(metadata)

    def refused(reason):
        return PriceRefusedError(f'{label}: refused — {reason}')

    unknown = sorted(key for key in metadata if key not in _KEYS_A_PRICE_TAKES)
    if unknown:
        raise refused(f'a price takes only {", ".join(_KEYS_A_PRICE_TAKES)}, and this block also '
                      f'gives {", ".join(unknown)}, which a price has nowhere to keep')

    try:
        guid = the_guid_a_block_names(metadata)
    except Exception as exc:
        raise refused(str(exc)) from None

    namespace = metadata.get('commodity.namespace')
    mnemonic = metadata.get('commodity.mnemonic')
    if (namespace is None) != (mnemonic is None):
        raise refused('commodity.namespace and commodity.mnemonic are given together, or neither')
    commodity = None
    if mnemonic is not None:
        found = table.lookup(_stated(namespace), _stated(mnemonic))
        if found is None:
            raise refused(f'{_stated(namespace)}:{_stated(mnemonic)} is not a commodity in the '
                          f'book, and the file declares none')
        commodity = qof_pointer(found)
    currency = None
    if metadata.get('currency.mnemonic') is not None:
        found = table.lookup('CURRENCY', _stated(metadata['currency.mnemonic']))
        if found is None:
            raise refused(f'{_stated(metadata["currency.mnemonic"])} is not a currency GnuCash knows')
        currency = qof_pointer(found)
    try:
        moment = _moment(lib, metadata['time']) if metadata.get('time') is not None else None
        value = _exact_value(metadata['value']) if metadata.get('value') is not None else None
    except PriceRefusedError as reason:
        raise refused(str(reason)) from None
    source = _stated(metadata['source']) if metadata.get('source') is not None else None
    type_ = _stated(metadata['type']) if metadata.get('type') is not None else None
    if source is not None and not _source_gnucash_stores(lib, book_ptr, source, known_sources):
        raise refused(f'this GnuCash cannot store source "{source}": it would keep it as '
                      f'"{GNUCASH_DEFAULT_SOURCE}", the source it keeps last. The sources GnuCash '
                      f'defines are listed in the README under "source: and type: belong to the price"')

    existing = None
    if guid is not None:
        pointer = lib.gnc_price_lookup(ctypes.byref(guid_from_hex(guid)), book_ptr)
        if pointer:
            existing = _read(lib, pointer)
        else:
            in_use = _guid_in_use_anywhere(book, guid)
            if in_use is not None:
                raise refused(f'guid {guid} is already used by an existing {in_use} in this book, '
                              f'and GnuCash keeps a guid to one object; give the price another '
                              f'guid, or leave guid: out to let GnuCash assign one')

    if existing is not None:
        if commodity is not None and commodity != existing.commodity:
            raise refused(f'guid {guid} is a price of {existing.pair}, and a price\'s commodity '
                          f'does not change; a price of {_stated(namespace)}:{_stated(mnemonic)} '
                          f'is recorded as a price of its own')
        if currency is not None and currency != existing.currency:
            raise refused(f'guid {guid} is a price of {existing.pair}, and a price\'s currency does '
                          f'not change; a price in {_stated(metadata["currency.mnemonic"])} is '
                          f'recorded as a price of its own')
        changes = {}
        if moment is not None and moment != existing.time:
            changes['time'] = moment
        if value is not None and Fraction(*value) != existing.value:
            changes['value'] = value
        if source is not None and source != existing.source:
            changes['source'] = source
        if type_ is not None and type_ != (existing.type or ''):
            changes['type'] = type_
        return _Plan(label=label, action='update' if changes else 'unchanged',
                     commodity=existing.commodity, currency=existing.currency, pair=existing.pair,
                     time=changes.get('time', existing.time), guid=guid, existing=existing,
                     changes=changes)

    missing = [key for key, given in (('commodity.namespace', namespace),
                                      ('commodity.mnemonic', mnemonic),
                                      ('currency.mnemonic', metadata.get('currency.mnemonic')),
                                      ('time', metadata.get('time')),
                                      ('value', metadata.get('value')))
               if given is None]
    if missing:
        held = f'; the book holds no price with guid {guid}' if guid is not None else ''
        raise refused(f'a new price needs {", ".join(missing)}{held}')

    pair = f'{_stated(namespace)}:{_stated(mnemonic)} in {_stated(metadata["currency.mnemonic"])}'
    if guid is None:
        for held in index.get(_either_way(commodity, currency), []):
            if (held.commodity == commodity and held.currency == currency
                    and held.time == moment and held.value == Fraction(*value)
                    and held.source == (source if source is not None else GNUCASH_DEFAULT_SOURCE)
                    and (held.type or '') == (type_ or '')):
                return _Plan(label=label, action='unchanged', commodity=commodity,
                             currency=currency, pair=pair, time=moment, existing=held)
    return _Plan(label=label, action='create', commodity=commodity, currency=currency, pair=pair,
                 time=moment, guid=guid, value=value, source=source, type=type_)


def _another_on_that_day(lib, index, plan: _Plan) -> Optional[BookPrice]:
    """A price of the same two, either way round, already on the plan's local day."""
    day = lib.gnc_time64_get_day_start(plan.time)
    for held in index.get(_either_way(plan.commodity, plan.currency), []):
        if plan.existing is not None and held.pointer == plan.existing.pointer:
            continue
        if lib.gnc_time64_get_day_start(held.time) == day:
            return held
    return None


def _create(lib, book_ptr, db, plan: _Plan) -> int:
    price = lib.gnc_price_create(book_ptr)
    if plan.guid is not None:
        lib.qof_instance_set_guid(price, ctypes.byref(guid_from_hex(plan.guid)))
    lib.gnc_price_begin_edit(price)
    lib.gnc_price_set_commodity(price, plan.commodity)
    lib.gnc_price_set_currency(price, plan.currency)
    lib.gnc_price_set_time64(price, plan.time)
    lib.gnc_price_set_value(price, GncNumericC(*plan.value))
    if plan.source is not None:
        lib.gnc_price_set_source_string(price, plan.source.encode('utf-8'))
    if plan.type is not None:
        lib.gnc_price_set_typestr(price, plan.type.encode('utf-8'))
    lib.gnc_price_commit_edit(price)
    # Always added. GnuCash turns a price away only where the day already
    # holds a price of the pair (CLAUDE.md finding 25), and a block that puts
    # a new price on such a day is refused before it gets here.
    lib.gnc_pricedb_add_price(db, price)
    lib.gnc_price_unref(price)
    return price


def _update(lib, plan: _Plan) -> None:
    price = plan.existing.pointer
    lib.gnc_price_begin_edit(price)
    if 'time' in plan.changes:
        lib.gnc_price_set_time64(price, plan.changes['time'])
    if 'value' in plan.changes:
        lib.gnc_price_set_value(price, GncNumericC(*plan.changes['value']))
    if 'source' in plan.changes:
        lib.gnc_price_set_source_string(price, plan.changes['source'].encode('utf-8'))
    if 'type' in plan.changes:
        lib.gnc_price_set_typestr(price, plan.changes['type'].encode('utf-8'))
    lib.gnc_price_commit_edit(price)


def apply_price_blocks(directives, book) -> PriceImportResult:
    """Apply the `price` blocks among a file's top-level directives to the book."""
    result = PriceImportResult()
    blocks = [directive for directive in directives if directive.type == DirectiveType.PRICE]
    result.seen = len(blocks)
    if not blocks:
        return result

    lib = load_gnc_engine()
    book_ptr = qof_pointer(book)
    db = lib.gnc_pricedb_get_db(book_ptr)
    table = book.get_table()
    index = defaultdict(list)
    for held in prices_in_book(book):
        index[_either_way(held.commodity, held.currency)].append(held)
    known_sources: Dict[str, bool] = {}

    plans = []
    for block in blocks:
        try:
            plans.append(_plan(lib, book, book_ptr, table, index, block, known_sources))
        except PriceRefusedError as refusal:
            result.refusals.append(str(refusal))

    # One guid is one price. Two blocks of one file giving the same guid would
    # both be applied: two new prices would both take it, and of two edits the
    # later would win.
    crowded = set()
    by_guid = defaultdict(list)
    for plan in plans:
        if plan.guid is not None:
            by_guid[plan.guid].append(plan)
    for guid, group in by_guid.items():
        if len(group) > 1:
            for plan in group:
                crowded.add(id(plan))
                result.refusals.append(
                    f'{plan.label}: refused — this file gives guid {guid} in {len(group)} price '
                    f'blocks, and a guid is one price, so what the book kept would depend on '
                    f'their order in the file')

    # Only a new price, or an edit changing a price's time, puts a price on a
    # day, so only those are checked against their day. A book can already hold
    # two prices of a pair on one local day of this machine, when they were
    # added where that day was two; a block that changes nothing about them, or
    # corrects a value, moves neither.
    def puts_a_price_on_a_day(plan):
        return plan.action == 'create' or 'time' in plan.changes

    # Two blocks of one file putting prices of one pair, either way round, on
    # one day: GnuCash would keep one, and which one would depend on the order
    # of the file.
    by_day = defaultdict(list)
    for plan in plans:
        if id(plan) not in crowded and puts_a_price_on_a_day(plan):
            day = lib.gnc_time64_get_day_start(plan.time)
            by_day[(_either_way(plan.commodity, plan.currency), day)].append(plan)
    for group in by_day.values():
        if len(group) > 1:
            pairs = ' and '.join(sorted({plan.pair for plan in group}))
            for plan in group:
                crowded.add(id(plan))
                result.refusals.append(
                    f'{plan.label}: refused — this file gives {len(group)} prices of {pairs} '
                    f'on {_day_text(lib, plan.time)}, and GnuCash keeps one price a day for a '
                    f'commodity and a currency, whichever way round it is written, so which one '
                    f'it kept would depend on their order in the file')

    def held(other):
        return f'guid {other.guid}, time "{written_time(other.time)}", source "{other.source}"'

    # Edits first, so an edit moving a price off a day frees that day for a new
    # price in the same file. An edit moving a price onto a day another price
    # still holds waits, and is tried again after the other edits, in case one
    # of them moves that price away: the order of the blocks decides nothing.
    waiting = []
    for plan in plans:
        if id(plan) in crowded:
            continue
        if plan.action == 'unchanged':
            result.unchanged += 1
        elif plan.action == 'update':
            waiting.append(plan)
    applied_one = True
    while waiting and applied_one:
        applied_one = False
        for plan in list(waiting):
            if puts_a_price_on_a_day(plan) and _another_on_that_day(lib, index, plan) is not None:
                continue
            _update(lib, plan)
            # Where the price is now, so the edits still waiting ask about the
            # day it moved to and not the day it left.
            key = _either_way(plan.commodity, plan.currency)
            pointer = plan.existing.pointer
            index[key] = [entry for entry in index[key] if entry.pointer != pointer]
            index[key].append(_read(lib, pointer))
            result.updated += 1
            waiting.remove(plan)
            applied_one = True
    still_moving = {plan.existing.pointer for plan in waiting}
    for plan in waiting:
        other = _another_on_that_day(lib, index, plan)
        reason = (f'{plan.label}: refused — at "{written_time(plan.time)}" it would fall on '
                  f'{_day_text(lib, plan.time)}, where the book already holds a price of '
                  f'{other.pair}: {held(other)}. GnuCash keeps one price a day for a commodity '
                  f'and a currency, whichever way round it is written')
        if other.pointer in still_moving:
            reason += ('. This file moves that price as well, and the two edits wait on each '
                       'other, so neither can go first; move one of the prices to a free day in '
                       'one import and the other in the next')
        result.refusals.append(reason)

    for plan in plans:
        if id(plan) in crowded or plan.action != 'create':
            continue
        other = _another_on_that_day(lib, index, plan)
        if other is not None:
            result.refusals.append(
                f'{plan.label}: refused — the book already holds a price of {other.pair} on '
                f'{_day_text(lib, plan.time)}: {held(other)}. GnuCash keeps one price a day for a '
                f'commodity and a currency, whichever way round it is written; to change that '
                f'price, give its guid')
            continue
        price = _create(lib, book_ptr, db, plan)
        index[_either_way(plan.commodity, plan.currency)].append(_read(lib, price))
        result.created += 1
    return result
