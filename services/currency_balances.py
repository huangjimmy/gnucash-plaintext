"""Each account's balance in every currency the book selects (Q-057).

A book that states `currency_balances: "CAD USD HKD CNY"` in its `company`
block keeps, beside what GnuCash keeps, an amount in each other selected
currency on every split and a balance in each on every account. GnuCash
already has a split's amount and an account's balance in the account's own
currency, and neither is stored again.

A US dollar account holding 100.00 USD also stores 130.00 CAD, 780.00 HKD
and 600.00 CNY. A split moving 10.00 USD out of it moves the same share of
each stored balance: 13.00 CAD, 78.00 HKD and 60.00 CNY. The split facing it
in another US dollar account takes exactly those, and nothing is realized. A
split facing it in a Canadian dollar account takes the amounts of the day,
and the transaction's `$residual$` split takes the difference in each
currency, which is the gain realized in that currency.

Every amount is worked out by `derive_every_balance`, which reads the whole
book in the order GnuCash keeps it, from its first transaction. An import
runs it on the finished book before saving, so a book with three years of
transactions that turns the setting on has every balance derived from its
first transaction, and a currency added to the selection later has its
balances worked out from the beginning as well.
"""

import contextlib
import functools
import re
import time
from fractions import Fraction
from typing import Dict, List, Optional, Tuple

from gnucash import ACCT_TYPE_PAYABLE, ACCT_TYPE_RECEIVABLE, ACCT_TYPE_TRADING

from infrastructure.gnucash.kvp import (
    get_book_custom_metadata,
    get_book_string_option,
    get_custom_metadata,
    set_custom_metadata,
    write_book_string_option,
)
from infrastructure.gnucash.utils import get_account_full_name, money_text, qof_pointer, to_money
from repositories.gnucash_repository import WHAT_TO_FORGET_WHEN_A_BOOK_OPENS
from services.foreign_currency import (
    _CREDIT_TYPES,
    _DEBIT_TYPES,
    _GAIN_TYPES,
    CURRENCY_BALANCES_KEY,
    TOOK_THE_RESIDUAL_KEY,
    iter_splits,
    states_the_residual_mark,
)
from services.prices import prices_in_book

# The currencies a book may select from.
THE_CURRENCIES_A_BOOK_MAY_SELECT = ('USD', 'CAD', 'HKD', 'CNY', 'EUR', 'JPY', 'GBP', 'KRW')

# On a split: what it moves in a selected currency other than its account's
# own, as `currency_amount.CAD: "13.00"`.
SPLIT_AMOUNT_KEY = 'currency_amount.'
# On an account: its balance in a selected currency other than its own, as
# `currency_balance.CAD: "117.00"`.
ACCOUNT_BALANCE_KEY = 'currency_balance.'

# An account's balance in its own currency as the derivation has read it so
# far, kept beside its balances in the selected currencies.
_OWN = ''

_HOLDING_TYPES = _DEBIT_TYPES | _CREDIT_TYPES


def currencies_stated(value) -> Tuple[str, ...]:
    """The currencies a `currency_balances:` value lists, such as `"CAD USD HKD CNY"`."""
    return tuple(str(value or '').replace(',', ' ').upper().split())


def selected_currencies(book) -> Tuple[str, ...]:
    """The currencies the book selected, and none where the setting is off."""
    return currencies_stated(get_book_custom_metadata(book).get(CURRENCY_BALANCES_KEY))


def refuse_a_selection_it_cannot_keep(book, value, base: str) -> None:
    """Refuse a `currency_balances:` the book cannot be kept by.

    Each currency is one of the eight a book may select from and is listed
    once, and the base currency is among them. A book kept this way stays
    kept this way: the setting is not removed, because the cost bases it
    stopped recording cannot be recorded afterwards.
    """
    stated = currencies_stated(value)
    if not stated:
        if selected_currencies(book):
            raise ValueError(
                f'this book keeps a balance in each of '
                f'{", ".join(selected_currencies(book))} on every account, and '
                f'`{CURRENCY_BALANCES_KEY}:` cannot be removed: a book migrated '
                f'away from cost bases cannot be migrated back to them')
        return
    unknown = [code for code in stated if code not in THE_CURRENCIES_A_BOOK_MAY_SELECT]
    if unknown:
        raise ValueError(
            f'{CURRENCY_BALANCES_KEY}: "{value}" lists {", ".join(unknown)}, and a '
            f'book selects from {", ".join(THE_CURRENCIES_A_BOOK_MAY_SELECT)}')
    if len(set(stated)) != len(stated):
        raise ValueError(f'{CURRENCY_BALANCES_KEY}: "{value}" lists a currency twice')
    if base not in stated:
        raise ValueError(
            f'{CURRENCY_BALANCES_KEY}: "{value}" leaves out {base}, the book\'s '
            f'base currency, which a realized gain is posted in')


class _NoPriceError(Exception):
    """The book has no price between two currencies."""


class _Prices:
    """The book's prices between currencies, read once."""

    def __init__(self, book, selected):
        self._selected = selected
        self._listed: Dict[Tuple[str, str], List[Tuple[int, Fraction]]] = {}
        # A security's prices as well as a currency's: shares arriving from
        # equity are so many of each selected currency on their day.
        for price in prices_in_book(book):
            self._listed.setdefault((price.mnemonic, price.currency_mnemonic), []).append(
                (price.time, price.value))
            self._listed.setdefault((price.currency_mnemonic, price.mnemonic), []).append(
                (price.time, 1 / price.value))

    def _direct(self, of: str, into: str, when: int) -> Optional[Fraction]:
        listed = self._listed.get((of, into))
        if not listed:
            return None
        return min(listed, key=lambda each: (abs(each[0] - when), each[0]))[1]

    def rate(self, of: str, into: str, when: int) -> Fraction:
        """How much of `into` one unit of `of` is, at the book's price nearest `when`.

        A pair the book has no price of is worked out through one selected
        currency it has a price of both in, as 14.00 CAD is 78.50 HKD through
        1.40 CAD/USD and 7.85 HKD/USD.
        """
        if of == into:
            return Fraction(1)
        direct = self._direct(of, into, when)
        if direct is not None:
            return direct
        for through in self._selected:
            first, second = self._direct(of, through, when), self._direct(through, into, when)
            if first is not None and second is not None:
                return first * second
        raise _NoPriceError(f'the book has no price of {of} in {into}')


class _Line:
    """One split, and what it moves in each selected currency other than its own."""

    def __init__(self, split, selected):
        self.split = split
        self.account = split.GetAccount()
        commodity = self.account.GetCommodity()
        self.code = commodity.get_mnemonic()
        self.key = self.account.GetGUID().to_string()
        self.holding = self.account.GetType() in _HOLDING_TYPES
        self.amount = _exact(split.GetAmount())
        self.value = _exact(split.GetValue())
        self.residual = states_the_residual_mark(
            get_custom_metadata(split).get(TOOK_THE_RESIDUAL_KEY, ''))
        self.moved = {code: Fraction(0) for code in selected if code != self.code}
        # What it drew out of its account's stored balances, and how much of
        # its own amount did that drawing.
        self.carried = dict(self.moved)
        self.given = Fraction(0)
        # How much of its own amount is still to be given its amounts.
        self.free = self.amount

    def free_weight(self) -> Fraction:
        """What the free part is worth in the transaction's currency, for dividing an amount between splits."""
        return abs(self.value * self.free / self.amount) or abs(self.free)

    def whole_weight(self) -> Fraction:
        return abs(self.value) or abs(self.amount)

    def in_currency(self, code: str) -> Fraction:
        return self.amount if code == self.code else self.moved[code]


def _exact(numeric) -> Fraction:
    return Fraction(numeric.num(), numeric.denom())


def _money(value: Fraction, unit: int) -> Fraction:
    return _exact(to_money(value, unit))


def _share(total: Fraction, lines: List[_Line], weights: List[Fraction], code: str, unit: int) -> None:
    """Add `total` of a currency to the splits by their weights; the last takes what rounding leaves."""
    total = _money(total, unit)
    whole = sum(weights)
    left = total
    for line, weight in list(zip(lines, weights))[:-1]:
        part = _money(total * weight / whole, unit)
        line.moved[code] += part
        left -= part
    lines[-1].moved[code] += left


def _what_each_split_moves(transaction, selected, units, held, prices) -> List[_Line]:
    """Each split of a transaction with its amount in every selected currency.

    `held` is every account's balances before the transaction, and is brought
    up to what they are after it.
    """
    every_line = [_Line(split, selected) for split in transaction.GetSplitList()
                  if split.GetAccount() is not None and split.GetAccount().GetCommodity() is not None]
    # A split of 0.00 moves nothing in any currency, and is given 0.00 in
    # each with the rest. So is a split on a trading account, in a book that
    # uses GnuCash's trading accounts: GnuCash makes those splits itself to
    # balance each currency of a transaction, and they are no money moved.
    lines = [line for line in every_line
             if line.amount and line.account.GetType() != ACCT_TYPE_TRADING]
    currency = transaction.GetCurrency().get_mnemonic()
    when = int(time.mktime(transaction.GetDate().timetuple()))
    # In the transaction's own currency a split moves what the transaction
    # states, its value, and GnuCash has those add up to zero. A book that
    # kept cost bases valued each disposal at the cost basis it drew on, and
    # that stays what the disposal moved.
    others = [code for code in selected if code != currency]

    # A split lowering what its account holds or owes draws the same share
    # of each balance the account stores, and all of each where it empties
    # the account.
    for line in lines:
        balances = held.setdefault(line.key, {})
        own = balances.get(_OWN, Fraction(0))
        if line.holding and own and (own > 0) != (line.amount > 0):
            line.given = line.amount if abs(line.amount) <= abs(own) else -own
            for code in line.moved:
                stored = balances.get(code, Fraction(0))
                if code == currency:
                    drawn = line.value * line.given / line.amount
                elif line.given == -own:
                    drawn = -stored
                else:
                    drawn = _money(-stored * abs(line.given) / abs(own), units[code])
                line.carried[code] = drawn
                line.moved[code] = drawn
                balances[code] = stored + drawn
            line.free = line.amount - line.given
        if currency in line.moved:
            line.moved[currency] = line.value
        balances[_OWN] = own + line.amount

    # What was drawn moves to the splits of the same currency facing it, as
    # it was drawn. What they do not take is left to be exchanged.
    left: Dict[str, Fraction] = {}
    for code in sorted({line.code for line in lines if line.given}):
        givers = [line for line in lines if line.code == code and line.given]
        drawn = sum(line.given for line in givers)
        takers = [line for line in lines
                  if line.code == code and line.free and (line.free > 0) != (drawn > 0)]
        room = sum(abs(line.free) for line in takers)
        matched = min(abs(drawn), room)
        if matched:
            for other in others:
                if other == code:
                    continue
                carried = -sum(line.carried[other] for line in givers) * matched / abs(drawn)
                _share(carried, takers, [abs(line.free) for line in takers], other, units[other])
            for line in takers:
                line.free -= line.free * matched / room
        if matched != abs(drawn):
            left[code] = drawn * (1 - matched / abs(drawn))

    # A split bringing money to an account takes the amounts of the day: the
    # currency the transaction itself exchanged where it exchanged one, and
    # the book's price otherwise. Income and expense splits take them too
    # where a `$residual$` split is there to take the difference.
    #
    # Not where one currency was exchanged for another, or for shares, with
    # no `$residual$` split: such a purchase realizes nothing, so what it
    # bought takes what the account paying for it gave up, and no price is
    # read.
    residual = next((line for line in lines if line.residual), None)
    takes_the_days = residual is not None or not left
    priced = [line for line in lines if takes_the_days and line.free and not line.residual
              and (line.holding or residual is not None)]
    # Where one selected currency paid for what arrived, the day's amounts
    # are that currency's: 10.00 USD paying for 14.00 CAD, or for 2 shares,
    # is 78.50 HKD at 7.85 HKD/USD, and the price of the shares is not read.
    #
    # Where two things paid together, as 10.00 USD and 1 share sold for
    # 24.00 CAD, no one of them paid for all of it, and what arrived takes
    # the day's amounts of its own currency: 24.00 CAD at 1.45 CAD/USD are
    # 16.55 USD.
    paid_in = next(iter(left)) if len(left) == 1 else None
    paid_for = [line for line in priced if line.code != paid_in]
    for code in others:
        facing = [line for line in priced if line.code != code]
        if facing and code == paid_in:
            _share(-left[code], facing, [line.free_weight() for line in facing], code, units[code])
            continue
        for line in facing:
            if paid_in in selected and line in paid_for:
                paid = -left[paid_in] * line.free_weight() / sum(
                    each.free_weight() for each in paid_for)
                line.moved[code] += _money(paid * prices.rate(paid_in, code, when), units[code])
            else:
                line.moved[code] += _money(
                    line.free * prices.rate(line.code, code, when), units[code])

    # Every currency adds up to zero across the transaction. The `$residual$`
    # split takes what is left over, which is the gain realized in that
    # currency. Where there is none, nothing is realized, and a split kept in
    # another currency takes what is left. Where an account gave something
    # up, the account receiving for it does: a book written before
    # `took_the_residual` states its gain as an ordinary split, and 10.00 USD
    # exchanged for 14.00 CAD beside it arrive at the 78.00 HKD the dollars
    # stored, with nothing of them put on the gain account. Where nothing
    # was given up, money arrived from income or equity, and the income or
    # equity split takes it.
    gave_something_up = any(line.given for line in lines)
    for code in others:
        total = sum(line.in_currency(code) for line in lines)
        if not total:
            continue
        if residual is not None and residual.code != code:
            residual.moved[code] -= total
            continue
        facing = [line for line in lines if line.code != code]
        free = [line for line in facing if line.free]
        takers = ([line for line in free if line.holding == gave_something_up]
                  or free or facing)
        # None where every split is kept in this currency and the transaction
        # states unequal amounts of it, as 10.00 USD sent and 9.00 USD
        # received. Those amounts are GnuCash's, and stay as stated.
        if takers:
            _share(-total, takers, [line.whole_weight() for line in takers], code, units[code])

    for line in lines:
        balances = held[line.key]
        for code, amount in line.moved.items():
            balances[code] = balances.get(code, Fraction(0)) + amount - line.carried[code]
    return every_line


def _in_the_books_order(book) -> list:
    """Every transaction of the book, in the order GnuCash keeps them.

    The order is GnuCash's own, `xaccTransOrder`: by date, then by `num` read
    as a number, then by the moment each was entered, then by description.
    Number 9 comes before number 10 on one day, which a comparison of the two
    as text gets the other way round. An account's balance before a
    transaction is then the one GnuCash's register shows above it.
    """
    from gnucash.gnucash_core_c import xaccTransOrder

    found = {}
    for split in iter_splits(book):
        transaction = split.GetParent()
        found.setdefault(transaction.GetGUID().to_string(), transaction)
    return sorted(found.values(), key=functools.cmp_to_key(
        lambda one, other: xaccTransOrder(one.instance, other.instance)))


def _with_the_keys(metadata: dict, prefix: str, wanted: Dict[str, str]) -> Optional[dict]:
    """`metadata` holding exactly `wanted` under `prefix`, or None where it already does."""
    kept = {key: value for key, value in metadata.items() if not key.startswith(prefix)}
    kept.update({prefix + code: text for code, text in wanted.items()})
    return None if kept == metadata else kept


def derive_every_balance(book) -> Tuple[int, List[str]]:
    """Work out every split's amounts and every account's balances from the book's first transaction.

    Returns how many splits and accounts it changed, and what it could not
    work out: each transaction the book has no price for. A book that
    selected no currencies is left alone.
    """
    selected = selected_currencies(book)
    if not selected:
        return 0, []
    table = book.get_table()
    units = {code: table.lookup('CURRENCY', code).get_fraction() for code in selected}
    prices = _Prices(book, selected)
    held: Dict[str, Dict[str, Fraction]] = {}
    changed = 0
    problems: List[str] = []

    for transaction in _in_the_books_order(book):
        try:
            lines = _what_each_split_moves(transaction, selected, units, held, prices)
        except _NoPriceError as none:
            problems.append(
                f'{transaction.GetDate().strftime("%Y-%m-%d")} '
                f'"{transaction.GetDescription()}": {none}, so what its splits '
                f'move in each selected currency cannot be worked out. Add a '
                f'price for that pair')
            continue
        writes = []
        for line in lines:
            now = _with_the_keys(
                dict(get_custom_metadata(line.split)), SPLIT_AMOUNT_KEY,
                {code: money_text(amount, units[code]) for code, amount in line.moved.items()})
            if now is not None:
                writes.append((line.split, now))
        if writes:
            # A KVP written outside an edit never reaches disk (CLAUDE.md
            # finding 11).
            transaction.BeginEdit()
            for split, now in writes:
                set_custom_metadata(split, now)
            transaction.CommitEdit()
            changed += len(writes)

    for account in book.get_root_account().get_descendants():
        commodity = account.GetCommodity()
        # GnuCash's own top-level `Trading` account, in a book that uses
        # trading accounts, is kept in no currency and holds no split.
        if commodity is None:
            continue
        balances = held.get(account.GetGUID().to_string(), {})
        now = _with_the_keys(
            dict(get_custom_metadata(account)), ACCOUNT_BALANCE_KEY,
            {code: money_text(balances.get(code, Fraction(0)), units[code])
             for code in selected if code != commodity.get_mnemonic()})
        if now is not None:
            account.BeginEdit()
            set_custom_metadata(account, now)
            account.CommitEdit()
            changed += 1
    return changed, problems


def derive_before_a_save(book) -> int:
    """Derive every balance of a book about to be saved, whichever command changed it; how many it changed.

    `unpost-invoices`, `delete-transactions`, `unlink` and the rest change or
    remove transactions, and every balance after them with it. A book whose
    balances cannot be worked out is not saved.
    """
    changed, not_worked_out = derive_every_balance(book)
    if not_worked_out:
        raise ValueError(
            'Nothing was saved: this book keeps a balance in each selected '
            f'currency, and {len(not_worked_out)} transaction(s) cannot be '
            'given theirs: ' + '; '.join(not_worked_out))
    _DERIVED_AND_NOT_YET_SAVED.add(qof_pointer(book))
    return changed


#: The books a command derived the balances of itself and has yet to save, by
#: address. `import` derives before it saves, to refuse in its own words, and
#: the save that follows would walk the whole book a second time to change
#: nothing. An address is forgotten once its book is saved, and all of them
#: when a book opens.
_DERIVED_AND_NOT_YET_SAVED: set = set()
WHAT_TO_FORGET_WHEN_A_BOOK_OPENS.append(_DERIVED_AND_NOT_YET_SAVED.clear)


def derive_for_a_save(book) -> None:
    """What every save runs: derive the balances, unless the command saving the book has just done it."""
    if qof_pointer(book) not in _DERIVED_AND_NOT_YET_SAVED:
        derive_before_a_save(book)
    _DERIVED_AND_NOT_YET_SAVED.discard(qof_pointer(book))


def _moved_in(split, code: str) -> Fraction:
    """What a split moved in a selected currency: GnuCash's amount in its account's own, and the stored one otherwise."""
    if split.GetAccount().GetCommodity().get_mnemonic() == code:
        return _exact(split.GetAmount())
    return Fraction(str(get_custom_metadata(split).get(SPLIT_AMOUNT_KEY + code) or 0))


def what_each_account_stores(book, as_of, code: str) -> List[Dict]:
    """Each account holding or owing another currency or a security at the end of `as_of`, with what it stores in `code`.

    What a balance sheet printed in `code` measures an unrealized gain
    against: the account's balance at the price of the day, less the balance
    it stores in `code`. One row per account, in the fields a cost basis row
    has, which is what the page reads.
    """
    rows = []
    for account in book.get_root_account().get_descendants():
        commodity = account.GetCommodity()
        if (commodity is None or account.GetType() not in _HOLDING_TYPES
                or commodity.get_mnemonic() == code):
            continue
        splits = [split for split in account.GetSplitList()
                  if split.GetParent().GetDate().date() <= as_of]
        if not splits:
            continue
        # An account emptied by then is listed too, holding nothing and
        # storing nothing. Left out, the page has no row for a currency the
        # book held and sold, and measures it from GnuCash's revaluation: a
        # book that sold its 1,000.00 EUR for 50.00 USD less than they were
        # stored at then stated that 50.00 USD again as an unrealized gain.
        own = sum((_exact(split.GetAmount()) for split in splits), Fraction(0))
        stored = sum((_moved_in(split, code) for split in splits), Fraction(0))
        sides = [(own, stored)]
        if account.GetType() in (ACCT_TYPE_RECEIVABLE, ACCT_TYPE_PAYABLE):
            # A receivable or a payable is on both sides at once where it
            # holds an invoice not collected beside a customer's credit, and
            # the page reads it lot by lot: each lot above zero is held and
            # each below zero is owed back. Handed one row for the account's
            # net, the page found 1,000.00 USD where it counted 2,500.00 USD
            # held and 1,500.00 USD owed, and measured US dollars from
            # GnuCash's revaluation. What is owed stores what its own lots
            # stored, and what is held stores the rest of the account's.
            lots: Dict[object, List[Fraction]] = {}
            for split in splits:
                lot = split.GetLot()
                of_the_lot = lots.setdefault(None if lot is None else qof_pointer(lot),
                                             [Fraction(0), Fraction(0)])
                of_the_lot[0] += _exact(split.GetAmount())
                of_the_lot[1] += _moved_in(split, code)
            owed = [each for each in lots.values() if each[0] < 0]
            held = [each for each in lots.values() if each[0] > 0]
            if owed and held:
                owed_own, owed_stored = (sum(each[at] for each in owed) for at in (0, 1))
                sides = [(own - owed_own, stored - owed_stored), (owed_own, owed_stored)]
        for of_the_side, stored_for_it in sides:
            each = abs(stored_for_it) / abs(of_the_side) if of_the_side else Fraction(0)
            rows.append({
                'guid': account.GetGUID().to_string().replace('-', ''),
                'account': get_account_full_name(account),
                'currency': commodity.get_mnemonic(),
                'namespace': commodity.get_namespace(),
                'side': 'liability' if of_the_side < 0 or (
                    not of_the_side and account.GetType() in _CREDIT_TYPES) else 'asset',
                'unit': commodity.get_fraction(),
                'balance': abs(of_the_side),
                'cost': each,
                'cost_in_pair': each,
                'cost_rate': Fraction(1),
                'pair_currency': code,
                'cost_held': abs(stored_for_it),
            })
    return rows


def _what_it_disposed_of(transaction) -> List[Tuple[object, str]]:
    """Each split of a transaction that lowered a holding, with its kind: `CURRENCY` or `security`.

    10.00 USD paying for 2 shares disposes of the US dollars and of no
    shares, so the gain its `$residual$` split takes is a gain on currency.
    A split lowers a holding where it credits an account that holds, or
    debits one that owes.
    """
    lowered = []
    for split in transaction.GetSplitList():
        account = split.GetAccount()
        amount = _exact(split.GetAmount())
        if ((account.GetType() in _DEBIT_TYPES and amount < 0)
                or (account.GetType() in _CREDIT_TYPES and amount > 0)):
            lowered.append((split, 'CURRENCY' if account.GetCommodity().get_namespace() == 'CURRENCY'
                            else 'security'))
    return lowered


def realized_items_up_to(book, as_of, code: str, kind: str, gain_accounts=()) -> list:
    """Each gain a `$residual$` split took by the end of `as_of`, in `code`: its date, its account and the gain.

    `kind` is `CURRENCY` for a gain on currency and `security` for one on
    shares, by what the transaction disposed of.

    `gain_accounts` is `--fx-gain-account`, for a book written before
    `took_the_residual`: its gain splits carry no mark, and the reader says
    which accounts they are booked to. With any stated, a split counts by its
    account and the mark is not consulted, as for a book keeping cost bases.
    Such a split realized its own amount in the base currency. In each other
    currency it stores 0.00, since nothing marked it as taking a difference.

    A transaction disposing of both, as 1 share and 10.00 USD sold together
    for 24.00 CAD, has one `$residual$` split for the two gains. The gain on
    the currency is what a sale of it alone would state: the currency at the
    book's price of the day, less what it was stored at. 10.00 USD at 1.45
    CAD/USD are 14.50 CAD, stored at 13.00 CAD, so 1.50 CAD is the gain on
    currency. The rest of the split, 2.50 CAD, is the gain on the share.
    """
    selected = selected_currencies(book)
    unit = book.get_table().lookup('CURRENCY', code).get_fraction()
    prices = None
    items = []
    for split in iter_splits(book):
        if gain_accounts:
            if (split.GetAccount().GetType() not in _GAIN_TYPES
                    or get_account_full_name(split.GetAccount()) not in gain_accounts):
                continue
        elif not states_the_residual_mark(get_custom_metadata(split).get(TOOK_THE_RESIDUAL_KEY, '')):
            continue
        transaction = split.GetParent()
        when = transaction.GetDate().date()
        lowered = _what_it_disposed_of(transaction)
        kinds = {each for _split, each in lowered}
        if when > as_of or kind not in kinds:
            continue
        gain = -_moved_in(split, code)
        if len(kinds) == 2:
            prices = prices or _Prices(book, selected)
            moment = int(time.mktime(transaction.GetDate().timetuple()))
            on_currency = sum(
                (_moved_in(sold, code) - _money(
                    _exact(sold.GetAmount()) * prices.rate(
                        sold.GetAccount().GetCommodity().get_mnemonic(), code, moment), unit)
                 for sold, each in lowered if each == 'CURRENCY'), Fraction(0))
            gain = on_currency if kind == 'CURRENCY' else gain - on_currency
        items.append((when.isoformat(), get_account_full_name(split.GetAccount()), gain))
    return sorted(items)


# The balance sheet shows how each unrealized gain was worked out. The page
# is the one a book keeping cost bases prints, and it is handed one row per
# account in a cost basis row's fields (`what_each_account_stores`), so its
# working arrives in a cost basis's words. These put it in the words of what
# such a book has: an account, its balance, and the balance it stores.
_ITS_OWN_WORDS = (
    (' # cost_basis_balance * cost_share_price_in_base', ' # what the account stores for its balance'),
    (' # its cost bases do not account for what the accounts hold', ' # no account holds or owes it'),
    ('cost_bases:', 'stored_balances:'),
    ('cost_basis:', 'stored_balance:'),
    ("cost_basis's", "stored_balance's"),
    ('cost_basis_balance', 'balance'),
    ('cost_value', 'stored_value'),
    ('cost bases', 'stored balances'),
    ('cost basis', 'stored balance'),
)
# A line of the page that is a key or a comment: tabs, then `key:` or `#`.
# Any other line is the block's own opening line or an account's line, which
# is the account's name and what it holds.
_A_KEY_OR_A_COMMENT = re.compile(r'^\t+(?:[A-Za-z_.]+:(?: |$)|#)')
_A_LINE_OF_ONE_COST = re.compile(r'^\t+cost_(?:share_price|rate|share_price_in_base): ')
_IN_QUOTES = re.compile(r'"[^"]*"')


def in_its_own_words(page: str) -> str:
    """A statement's plaintext page with its working in the words of a stored balance.

    Only a key and a comment are reworded. An account's name is the
    account's: on its own line and wherever it is quoted it is printed as the
    book has it, so `Assets:USD kept at cost basis` stays that.
    """
    worded = []
    opens_an_entry = False
    for line in page.split('\n'):
        if not _A_KEY_OR_A_COMMENT.match(line):
            worded.append(line)
            continue
        if _A_LINE_OF_ONE_COST.match(line):
            continue
        if opens_an_entry:
            line = line.replace('split_guid: ', 'account_guid: ', 1)
        opens_an_entry = line.strip() == 'cost_basis:'
        quoted = _IN_QUOTES.findall(line)
        line = _IN_QUOTES.sub('\0', line)
        for words, its_own in _ITS_OWN_WORDS:
            line = line.replace(words, its_own)
        for each in quoted:
            line = line.replace('\0', each, 1)
        worded.append(line)
    return '\n'.join(worded)


@contextlib.contextmanager
def read_in(book, code: str):
    """For the length of a statement, have every income, expense and equity account read in `code`.

    GnuCash's report converts an account kept in another currency at the
    price of the statement's date. A book keeping a balance in each selected
    currency has what each split of such an account moved in `code`, on the
    day it moved, so the account is read as kept in `code` and each split as
    that amount. 130.00 CAD of opening equity that was 780.00 HKD on its day
    is 780.00 HKD on a page in HKD, where the price of the page's date makes
    it 728.93 HKD and the page then does not balance.

    Nothing of it is saved: the book is put back before the statement's
    command reads it again, and a statement's book is opened to be read.
    An account holding or owing money stays in its own currency, and the
    page values it at the price of its date.
    """
    wanted = book.get_table().lookup('CURRENCY', code)
    changed = []
    # Each transaction is opened for editing before a split of it is
    # changed, left open for the length of the statement, and rolled back
    # afterwards, so nothing is committed. A commit is where GnuCash
    # rebalances the trading splits of a book that uses trading accounts: it
    # destroys and remakes them, and putting an amount back on a split it had
    # destroyed ended the process with a bus error.
    opened = {}
    # A book that uses GnuCash's trading accounts is read as one that does
    # not, for the length of the statement. With the option on, the page
    # takes the trading accounts' balances as the book's gain. Those are
    # converted at the price of the page's date like any account, and a page
    # in a currency other than the base then does not balance: U's book in
    # HKD stated 785.00 HKD of assets against 830.96 HKD. With it off, the
    # page measures each gain from what the accounts store, as it does for
    # any book kept this way.
    uses_trading_accounts = get_book_string_option(book, 'Accounts', 'Use Trading Accounts') == 't'
    try:
        if uses_trading_accounts:
            write_book_string_option(book, 'Accounts', 'Use Trading Accounts', '')
        for account in book.get_root_account().get_descendants():
            commodity = account.GetCommodity()
            # A trading account is GnuCash's own, and stays as GnuCash keeps it.
            if (commodity is None or account.GetType() in _HOLDING_TYPES
                    or account.GetType() == ACCT_TYPE_TRADING
                    or commodity.get_mnemonic() == code):
                continue
            moved = [(split, _moved_in(split, code)) for split in account.GetSplitList()]
            for split, _amount in moved:
                transaction = split.GetParent()
                if transaction.GetGUID().to_string() not in opened:
                    transaction.BeginEdit()
                    opened[transaction.GetGUID().to_string()] = transaction
            changed.append((account, commodity))
            account.BeginEdit()
            account.SetCommodity(wanted)
            account.CommitEdit()
            for split, amount in moved:
                split.SetAmount(to_money(amount, wanted.get_fraction()))
        yield
    finally:
        for account, commodity in changed:
            account.BeginEdit()
            account.SetCommodity(commodity)
            account.CommitEdit()
        for transaction in opened.values():
            transaction.RollbackEdit()
        if uses_trading_accounts:
            write_book_string_option(book, 'Accounts', 'Use Trading Accounts', 't')


def balances_by_account(book, as_of=None) -> List[Dict]:
    """Each account holding anything, with its balance in its own currency and in each other selected one.

    As the book stands, or at the end of `as_of`: what the account's splits
    dated on or before that day moved, in its own currency and in each
    other. Each split stores what it moved, so a balance as of a date is
    those amounts added up, with nothing worked out again.

    Each row carries text, not what it would have to be read from: the
    listing is printed after the book is closed.
    """
    selected = selected_currencies(book)
    table = book.get_table()
    rows = []
    for account in book.get_root_account().get_descendants():
        commodity = account.GetCommodity()
        if commodity is None:
            continue
        codes = [code for code in selected if code != commodity.get_mnemonic()]
        if as_of is None:
            stored = get_custom_metadata(account)
            own = _exact(account.GetBalance())
            others = {code: str(stored.get(ACCOUNT_BALANCE_KEY + code, '')) for code in codes}
        else:
            splits = [split for split in account.GetSplitList()
                      if split.GetParent().GetDate().date() <= as_of]
            own = sum((_exact(split.GetAmount()) for split in splits), Fraction(0))
            others = {code: money_text(sum((_moved_in(split, code) for split in splits), Fraction(0)),
                                       table.lookup('CURRENCY', code).get_fraction())
                      for code in codes}
        if not own and not any(Fraction(text or 0) for text in others.values()):
            continue
        rows.append({
            'account': get_account_full_name(account),
            'currency': commodity.get_mnemonic(),
            'balance': money_text(own, commodity.get_fraction()),
            'others': others,
        })
    return rows
