"""A book's prices, read straight from the book, and prices written the way GnuCash writes them.

The price tests ask the book rather than an export, because an export is one
of the things under test. And the prices a book already holds came from
GnuCash's own dialogs, register and Finance::Quote, not from gnucash-plaintext,
so `add_prices` writes them through GnuCash's price API: an export is then
tested on prices it did not write.

A price's time is set with ctypes `gnc_price_set_time64`, never SWIG
`set_time64` with an integer, which GnuCash 3.4 misreads (CLAUDE.md finding
20). A brand-new book holding nothing but prices writes no file when saved
(Q-041, table 1), so `add_prices` adds an account to a new book as well.
"""

import calendar
import ctypes
import os
import time
from dataclasses import dataclass
from fractions import Fraction
from typing import Dict, List, Optional, Sequence

from gnucash import Account, GncCommodity
from gnucash.gnucash_core_c import ACCT_TYPE_BANK

from infrastructure.gnucash.engine import load_gnc_engine
from repositories.gnucash_repository import GnuCashRepository, SessionMode


class _Numeric(ctypes.Structure):
    _fields_ = [('num', ctypes.c_int64), ('denom', ctypes.c_int64)]


class _GDate(ctypes.Structure):
    _fields_ = [('julian_days', ctypes.c_uint), ('dmy', ctypes.c_uint)]


_EACH_PRICE = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
_LIB = None


def _lib():
    global _LIB
    if _LIB is None:
        load_gnc_engine()
        lib = ctypes.CDLL(None)
        c = ctypes
        for name, restype, argtypes in (
            ('gnc_pricedb_get_db', c.c_void_p, [c.c_void_p]),
            ('gnc_pricedb_add_price', c.c_int, [c.c_void_p, c.c_void_p]),
            ('gnc_pricedb_foreach_price', c.c_int, [c.c_void_p, _EACH_PRICE, c.c_void_p, c.c_int]),
            ('gnc_price_create', c.c_void_p, [c.c_void_p]),
            ('gnc_price_begin_edit', None, [c.c_void_p]),
            ('gnc_price_commit_edit', None, [c.c_void_p]),
            ('gnc_price_unref', None, [c.c_void_p]),
            ('gnc_price_set_commodity', None, [c.c_void_p, c.c_void_p]),
            ('gnc_price_set_currency', None, [c.c_void_p, c.c_void_p]),
            ('gnc_price_set_time64', None, [c.c_void_p, c.c_int64]),
            ('gnc_price_set_source_string', None, [c.c_void_p, c.c_char_p]),
            ('gnc_price_set_typestr', None, [c.c_void_p, c.c_char_p]),
            ('gnc_price_set_value', None, [c.c_void_p, _Numeric]),
            ('gnc_price_get_commodity', c.c_void_p, [c.c_void_p]),
            ('gnc_price_get_currency', c.c_void_p, [c.c_void_p]),
            ('gnc_price_get_time64', c.c_int64, [c.c_void_p]),
            ('gnc_price_get_value', _Numeric, [c.c_void_p]),
            ('gnc_price_get_source_string', c.c_char_p, [c.c_void_p]),
            ('gnc_price_get_typestr', c.c_char_p, [c.c_void_p]),
            ('gnc_commodity_get_namespace', c.c_char_p, [c.c_void_p]),
            ('gnc_commodity_get_mnemonic', c.c_char_p, [c.c_void_p]),
            ('qof_instance_get_guid', c.c_void_p, [c.c_void_p]),
            ('guid_to_string_buff', c.c_char_p, [c.c_void_p, c.c_char_p]),
            ('g_date_clear', None, [c.c_void_p, c.c_uint]),
            ('g_date_set_dmy', None, [c.c_void_p, c.c_uint8, c.c_int, c.c_uint16]),
            ('gdate_to_time64', c.c_int64, [_GDate]),
        ):
            function = getattr(lib, name)
            function.restype = restype
            function.argtypes = argtypes
        _LIB = lib
    return _LIB


def _pointer(obj) -> int:
    instance = getattr(obj, 'instance', obj)
    try:
        return int(instance)
    except TypeError:
        return int(instance.instance)


@dataclass(frozen=True)
class Price:
    guid: str
    commodity: str          # "NASDAQ:AMZN", "CURRENCY:USD"
    currency: str           # "USD"
    time: int               # seconds since the epoch
    value: Fraction
    source: str
    type: Optional[str]


def prices_in(book_path) -> List[Price]:
    """Every price the book holds, ordered by commodity, currency and time."""
    repo = GnuCashRepository(str(book_path))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        lib = _lib()
        found = []

        def each(price, _data):
            buffer = ctypes.create_string_buffer(33)
            lib.guid_to_string_buff(lib.qof_instance_get_guid(price), buffer)
            commodity = lib.gnc_price_get_commodity(price)
            currency = lib.gnc_price_get_currency(price)
            value = lib.gnc_price_get_value(price)
            type_ = lib.gnc_price_get_typestr(price)
            found.append(Price(
                guid=buffer.value.decode(),
                commodity=(f'{lib.gnc_commodity_get_namespace(commodity).decode()}'
                           f':{lib.gnc_commodity_get_mnemonic(commodity).decode()}'),
                currency=lib.gnc_commodity_get_mnemonic(currency).decode(),
                time=lib.gnc_price_get_time64(price),
                value=Fraction(value.num, value.denom),
                source=lib.gnc_price_get_source_string(price).decode(),
                type=type_.decode() if type_ else None,
            ))
            return 1

        callback = _EACH_PRICE(each)
        lib.gnc_pricedb_foreach_price(
            lib.gnc_pricedb_get_db(_pointer(repo.book)), callback, None, 1)
        return sorted(found, key=lambda p: (p.commodity, p.currency, p.time))
    finally:
        repo.close()


def add_prices(book_path, prices: Sequence[Dict]) -> None:
    """Add prices through GnuCash's price API, creating the book if it is not there.

    Each price is a dict: `commodity` ("NASDAQ:AMZN"), `currency` ("USD"),
    `time` (seconds since the epoch), `value` (a Fraction, or text a Fraction
    reads), and optionally `source` and `type`, which are left unset when
    absent. A commodity the book does not hold is created with a fraction of
    10000.
    """
    path = str(book_path)
    new = not os.path.exists(path)
    repo = GnuCashRepository(path)
    repo.open(mode=SessionMode.NEW if new else SessionMode.NORMAL)
    try:
        lib = _lib()
        book = repo.book
        table = book.get_table()
        if new:
            bank = Account(book)
            bank.BeginEdit()
            bank.SetName('Bank')
            bank.SetType(ACCT_TYPE_BANK)
            bank.SetCommodity(table.lookup('CURRENCY', 'USD'))
            book.get_root_account().append_child(bank)
            bank.CommitEdit()
        db = lib.gnc_pricedb_get_db(_pointer(book))
        for spec in prices:
            namespace, mnemonic = spec['commodity'].split(':')
            commodity = table.lookup(namespace, mnemonic)
            if commodity is None:
                table.insert(GncCommodity(book, mnemonic, namespace, mnemonic, '', 10000))
                commodity = table.lookup(namespace, mnemonic)
            value = Fraction(spec['value'])
            price = lib.gnc_price_create(_pointer(book))
            lib.gnc_price_begin_edit(price)
            lib.gnc_price_set_commodity(price, _pointer(commodity))
            lib.gnc_price_set_currency(price, _pointer(table.lookup('CURRENCY', spec['currency'])))
            lib.gnc_price_set_time64(price, spec['time'])
            if spec.get('source') is not None:
                lib.gnc_price_set_source_string(price, spec['source'].encode())
            if spec.get('type') is not None:
                lib.gnc_price_set_typestr(price, spec['type'].encode())
            lib.gnc_price_set_value(price, _Numeric(value.numerator, value.denominator))
            lib.gnc_price_commit_edit(price)
            lib.gnc_pricedb_add_price(db, price)
            lib.gnc_price_unref(price)
        repo.save()
    finally:
        repo.close()


def utc(year, month, day, hour=0, minute=0, second=0) -> int:
    """Seconds since the epoch for a UTC time."""
    return calendar.timegm((year, month, day, hour, minute, second, 0, 0, 0))


def day_neutral(year, month, day) -> int:
    """The time GnuCash's own `gdate_to_time64` returns for a date, which a bare-date `time:` is stored at."""
    lib = _lib()
    date = _GDate()
    lib.g_date_clear(ctypes.byref(date), 1)
    lib.g_date_set_dmy(ctypes.byref(date), day, month, year)
    return lib.gdate_to_time64(date)


def as_written(seconds: int) -> str:
    """A time the way a `time:` line writes it: UTC, to the second, with its offset."""
    return time.strftime('%Y-%m-%d %H:%M:%S +0000', time.gmtime(seconds))


def price_blocks(text: str) -> List[Dict[str, str]]:
    """The `price` blocks of a ledger, each as its keys and unquoted values."""
    blocks = []
    current = None
    for line in text.splitlines():
        if line == 'price':
            current = {}
            blocks.append(current)
        elif current is not None and line.startswith('\t') and not line.startswith('\t\t'):
            key, _, value = line.strip().partition(':')
            current[key.strip()] = value.strip().strip('"')
        elif line.strip():
            current = None
    return blocks
