"""
Foreign-currency cost bases and their balances (Q-035).

A split that brings foreign currency into the book — an invoice's A/R split, a
bill's A/P split, currency bought or borrowed — establishes a **cost basis**:
so many units of that currency, at what they cost in the book's own currency.
Two facts describe it:

- **the cost**, which the transaction already carries as `share_price`: on the
  split itself when the transaction is in the book's currency, or on the
  base-currency split facing it when the transaction is in the foreign one.
  Nothing is stored for it;
- **the balance of that cost basis**, how much of it has not yet been used. The
  `cost_basis_balance` KVP on the split is that balance: it opens at
  everything the split brought in, each sale lowers it, and giving a sale
  back — deleting it — raises it again.

The balance of a cost basis is not the balance of an account, and the two are
never interchangeable. An account balance is how much currency an account
holds right now; a cost basis's balance is how much of *one split's* currency,
at *that split's* cost, has not yet been sold. A USD invoice paid into a USD
bank leaves the bank holding the money while the A/R split remains the cost
basis that money carries, and one bank account can hold currency belonging to
several cost bases at different costs.

Selling foreign currency picks a cost basis: the sale's foreign-currency split
gives the guid of the cost basis split with `cost_basis_split_guid`, and its own amount is how
much of that cost basis the sale uses. A sale measured against two cost bases is written
as two foreign-currency splits, one giving each. A sale cannot pick more from a
cost basis than that cost basis has left.

**A cost basis is lowered only by something that gives it.** Currency can leave an
account without giving one — a bank fee taken in the foreign currency, a
payment block whose bank split GnuCash writes, an ordinary transfer — and
nothing draws the cost basis down for it. So what `fx-balances` reports is what the
book *acquired and has not sold against*, which is a different figure from what
the accounts hold, and it can be the larger of the two. Measured: an account
that received 60.00 USD and paid an 8.00 USD fee out of the same transaction
holds 52.00 and offers 60.00, and that book is correct by every rule here.

The consequence is worth stating plainly, because it is not obvious and it is
reachable by ordering alone: settle a bill out of a foreign account whose cost
bases have nothing left, then settle an invoice into the same account, and the
account nets to zero while the arriving side opens its full amount. A later
sale giving that cost basis is then accepted, and takes money the account does not
hold. `_refuse_a_payment_block_spending_a_cost_basis_balance` closes the door
the other way round — a payment block cannot spend a cost basis balance — but
no check at the moment cash leaves can see this one, because the outgoing
payment came first, out of an account whose cost bases were empty.

Nothing here treats that as an error, because "an account may not offer more
than it holds" is not an invariant this model keeps: the fee case above breaks
it legitimately, and a check on it would report ordinary books. Making the two
agree means deciding what an outflow that gives no cost basis does to the cost bases on
its account, which is a change to the model rather than a fix to it.
"""

from __future__ import annotations

import traceback
from datetime import datetime, timedelta
from fractions import Fraction
from typing import Dict, Iterator, List, Optional, Set

import gnucash.gnucash_core_c as _gc
from gnucash import GncLot
from gnucash.gnucash_core_c import (
    ACCT_TYPE_ASSET,
    ACCT_TYPE_BANK,
    ACCT_TYPE_CASH,
    ACCT_TYPE_CREDIT,
    ACCT_TYPE_EXPENSE,
    ACCT_TYPE_INCOME,
    ACCT_TYPE_LIABILITY,
    ACCT_TYPE_MUTUAL,
    ACCT_TYPE_PAYABLE,
    ACCT_TYPE_RECEIVABLE,
    ACCT_TYPE_STOCK,
)

from infrastructure.gnucash.kvp import (
    custom_key_changes,
    forget_custom_key_changes,
    get_custom_metadata,
    log_custom_key_changes,
    set_custom_metadata,
    watch_custom_key,
    watched_key_writes,
)
from infrastructure.gnucash.utils import (
    exact_text,
    get_account_full_name,
    is_power_of_ten,
    money_text,
    numeric_to_fraction,
    qof_instance,
    qof_pointer,
    to_money,
)
from repositories.gnucash_repository import WHAT_TO_FORGET_WHEN_A_BOOK_OPENS

# The currency the book reports in. Hardcoded tool-wide (see `services/fx_rates.py`,
# which quotes every rate in CAD).
BASE_CURRENCY = 'CAD'

# KVP on a foreign-currency split: how much of the cost basis it established is
# still available, in the split's own commodity. Named for the cost basis, not
# for the split's account: `balance:` on an exported split is that account's
# running balance, a different figure that this must never be read as.
COST_BASIS_BALANCE_KEY = 'cost_basis_balance'
# Whether a book keeps a cost basis is kept through an import and asked again
# after any write that sets or drops this key (`a_cost_basis_is_kept_for`).
watch_custom_key(COST_BASIS_BALANCE_KEY)

# KVP on a foreign-currency split whose account's balance crosses or lies past
# zero: how much of its amount arrived, on either side, as the import read the
# account's balance on the transaction's date (Q-047). Written only where that
# differs from what the account's type says — the whole amount for a split
# raising the account in its own direction, nothing otherwise — so a book
# written before it reads as it always did. The import writes it and never
# takes it from a file; the export leaves it out.
COST_BASIS_BROUGHT_IN_KEY = 'cost_basis_brought_in'

# KVP on a sale's foreign-currency split: the guid of the split whose cost
# basis this sale picks.
COST_BASIS_SPLIT_KEY = 'cost_basis_split_guid'
# Which splits draw on each cost basis is kept for the whole book, and brought
# up to date from each change of this key (`splits_drawing_on`).
log_custom_key_changes(COST_BASIS_SPLIT_KEY)

# KVP on a sale's foreign-currency split: measure against a receivable that has
# not been collected yet, deliberately.
COST_BASIS_FORCE_KEY = 'cost_basis_force'

# What a unit of this split's currency cost, in the book's currency, for the
# one case where the transaction cannot say it: both sides in the same foreign
# currency. USD paid into a USD bank — an overpaid invoice, or a USD borrowing
# held in an A/P USD account — has no base-currency figure anywhere in it,
# so there is no value to divide by an amount and `share_price` describes a
# USD/USD rate of 1. The cost is real all the same, and it is written here.
# Everywhere else it stays derived: a stored cost that could have been read
# from the transaction is a second copy waiting to disagree with it.
COST_BASIS_COST_KEY = 'cost_basis_cost'

# KVP on a split that settled an invoice or bill out of an owner's credit,
# rather than out of a bank. What it means for a cost basis: the credit was a
# pool of currency the book held at a known cost, and spending it ended that
# pool. A sale measured against it drew its currency out beforehand, so the
# guid it gives is a cost basis that was consumed rather than one that never was.
APPLIED_FROM_CREDIT_KEY = 'applied_from_credit'

# KVP on the split a transaction's `$residual$` line resolved to: the exchange
# difference a disposal realized, which the file declared and a saved book
# would otherwise have no record of.
#
# It cannot be worked out again afterwards. A disposal balances — what it
# fetched plus the difference it realized is what those units cost — so the
# arithmetic alone cannot say which of its splits is which, and neither can the
# account: 8.60 USD disposed of at 11.99 paid an 11.92 bank charge beside 0.07
# of exchange difference, both on expense accounts, and an account is not one
# or the other because of its name (docs/multi-currency.md). The file said
# which, and this is the book's record of it.
TOOK_THE_RESIDUAL_KEY = 'took_the_residual'

# The `company` block's key saying whether the book keeps cost bases (Q-049).
# Cost bases are gnucash-plaintext's, not GnuCash's: GnuCash asks no one which
# lot a dollar came out of. `cost_bases: "off"` keeps the book's foreign
# currency as GnuCash does, and `"on"`, or no line at all, keeps cost bases.
COST_BASES_KEY = 'cost_bases'

# The cost basis keys, which a book keeping no cost bases holds none of. Not
# `took_the_residual`: the realized gain a file states is the file's, and no
# cost basis decides it.
COST_BASIS_KEYS = (COST_BASIS_BALANCE_KEY, COST_BASIS_BROUGHT_IN_KEY,
                   COST_BASIS_SPLIT_KEY, COST_BASIS_FORCE_KEY, COST_BASIS_COST_KEY)


#: Each book's answer to `book_keeps_cost_bases`, by the book's address. Asked
#: for every split a cost basis writer is handed and every transaction the
#: realized gain walk reads, so the book's custom metadata is read and parsed
#: once per book rather than once per question. An address can be reused only
#: by a book opened after another was closed, and `GnuCashRepository.open`
#: forgets every answer.
_WHETHER_EACH_BOOK_KEEPS_COST_BASES: Dict[int, bool] = {}


def book_keeps_cost_bases(book) -> bool:
    """Whether the book keeps cost bases: the `company` block's `cost_bases:` is not `off` (Q-049)."""
    from infrastructure.gnucash.kvp import get_book_custom_metadata

    address = qof_pointer(book)
    if address not in _WHETHER_EACH_BOOK_KEEPS_COST_BASES:
        _WHETHER_EACH_BOOK_KEEPS_COST_BASES[address] = (
            str(get_book_custom_metadata(book).get(COST_BASES_KEY, '')).strip() != 'off')
    return _WHETHER_EACH_BOOK_KEEPS_COST_BASES[address]


def forget_whether_books_keep_cost_bases() -> None:
    """Forget each book's answer, once a `company` block has set `cost_bases:` or a book is opened (Q-049)."""
    _WHETHER_EACH_BOOK_KEEPS_COST_BASES.clear()


# What a run learned of a book it did not save is not what the file holds: a
# dry run or a rolled-back `--atomic` run of a `company` block setting
# `cost_bases:` leaves it behind. A book opened is asked afresh.
WHAT_TO_FORGET_WHEN_A_BOOK_OPENS.append(forget_whether_books_keep_cost_bases)


def refuse_a_cost_bases_setting_it_cannot_read(value) -> None:
    """Refuse a `cost_bases:` other than `on` or `off`; an empty one removes the line, which keeps them."""
    if value is None or str(value).strip() in ('', 'on', 'off'):
        return
    raise ValueError(
        f'cost_bases: "{value}" is neither "on" nor "off". "off" keeps the '
        f'book\'s foreign currency as GnuCash does, with no cost bases, and '
        f'"on", or no line, keeps them')


def refuse_turning_cost_bases_on_in_place(book, value) -> None:
    """Refuse a `company` block turning cost bases on in a book that keeps none (Q-049).

    `"on"`, or the line cleared, would turn them on in place, over a book
    whose disposals gave no cost basis and whose holdings no cost basis
    accounts for: the next spend refused for want of one, and `fx-balances`
    and the balance sheet reading cost bases that account for nothing. A
    book is never half on, so it is turned on by bringing it forward through
    its export into a new book, where every disposal gives its cost basis.
    """
    if book_keeps_cost_bases(book) or str(value or '').strip() == 'off':
        return
    raise ValueError(
        'this book keeps no cost bases, and turning them on in place would '
        'leave every earlier disposal with none to draw on. Bring the book '
        'forward through its export instead: remove the `cost_bases:` line '
        'and import the export into a new book, giving each disposal the '
        'cost basis it draws on (README, "A book that keeps no cost bases")')


def clear_every_cost_basis(book) -> int:
    """Take every cost basis key off the book's splits, for a book turned to keep none; how many splits held one (Q-049).

    A book keeping no cost bases holds none of their keys, so it is never half
    on: a figure left behind would be exported, and the import refuses a file
    stating one into such a book. Each transaction is edited on its own, since
    a KVP written outside an edit never reaches disk (CLAUDE.md finding 11).
    """
    cleared = 0
    for split in list(iter_splits(book)):
        metadata = dict(get_custom_metadata(split))
        if not any(key in metadata for key in COST_BASIS_KEYS):
            continue
        for key in COST_BASIS_KEYS:
            metadata.pop(key, None)
        transaction = split.GetParent()
        transaction.BeginEdit()
        set_custom_metadata(split, metadata)
        transaction.CommitEdit()
        cleared += 1
    if cleared:
        cost_bases_changed()
    return cleared


def refuse_a_cost_basis_key_where_none_is_kept(book, directive) -> None:
    """Refuse a transaction block stating a cost basis key into a book that keeps no cost bases (Q-049).

    Such a book records none, so a figure the file states would be recorded by
    nothing, and a book is never half on. A key stated empty says to clear it,
    which is what the book already is.
    """
    if book_keeps_cost_bases(book):
        return
    lines = [('the transaction', directive.metadata)] + [
        (f'the split on {child.props.get("account", "?")!r}', child.metadata)
        for child in directive.children]
    for where, metadata in lines:
        for key in COST_BASIS_KEYS:
            if key in metadata and str(metadata[key] or '').strip():
                raise ValueError(
                    f'{where} dated {directive.props.get("date", "?")} states '
                    f'{key}:, and this book keeps no cost bases '
                    f'(`cost_bases: "off"` in its company block), so nothing '
                    f'would record it. Remove the line, or turn cost bases on '
                    f'by bringing the book forward through its export (README, '
                    f'"A book that keeps no cost bases")')

# Account types whose balance a positive amount increases (assets, receivables)
# and those a negative amount increases (liabilities, payables). Used to tell a
# split that establishes a cost basis from one that spends the currency.
#
# Stock and mutual-fund accounts are here because the type is a classification
# and the commodity is what decides: an account typed `Stock` can be
# denominated in USD, and the currency in it is held and sellable like any
# other. Securities are excluded by the namespace guard in
# `establishes_cost_basis`, which is about what the account holds — dropping
# these two types instead left a USD holding in a `Stock` account with no cost
# basis at all.
#
# Receivable and payable appear for the sign convention they state; the branch
# for those two answers before these sets are consulted.
_DEBIT_TYPES = frozenset({
    ACCT_TYPE_BANK, ACCT_TYPE_CASH, ACCT_TYPE_ASSET,
    ACCT_TYPE_STOCK, ACCT_TYPE_MUTUAL, ACCT_TYPE_RECEIVABLE,
})
_CREDIT_TYPES = frozenset({
    ACCT_TYPE_LIABILITY, ACCT_TYPE_PAYABLE, ACCT_TYPE_CREDIT,
})

# Where a realized exchange difference can land. It is income when the book
# gained and an expense when it lost, and it is in the profit and loss either
# way.
_GAIN_TYPES = frozenset({ACCT_TYPE_INCOME, ACCT_TYPE_EXPENSE})


def _fraction(num) -> Fraction:
    """A GncNumeric as an exact Fraction."""
    return Fraction(num.num(), num.denom())


def split_guid(split) -> str:
    return split.GetGUID().to_string().replace('-', '').lower()


def split_commodity(split) -> str:
    """The mnemonic of the commodity this split's account is denominated in.

    A split with no account answers the empty string, which every caller reads
    as "not foreign currency". That is not the case CLAUDE.md §12 describes —
    a split whose `<split:account>` is missing from a *file* never reaches this
    code, because GnuCash 5.x drops the whole transaction while loading and 4.x
    and earlier segfault inside `qof_session_load`. This is a split GnuCash
    makes itself: committing a multi-currency transaction on a book with
    "Use Trading Accounts" on creates trading splits, and on GnuCash 4.8 one of
    them is in the transaction's split list before its account is attached.
    `record_cost_bases` walks every split of the transaction it has just
    committed, so it meets that split mid-commit and asked it what it holds.

    Measured on 4.8, importing a US dollar purchase funded from a Canadian
    bank into a trading-accounts book: `'NoneType' object has no attribute
    'GetCommodity'`, twice, and the import exits 1 having written the book.
    The same ledger and the same book import at exit 0 on 3.4, 3.8, 4.4, 4.13,
    5.5, 5.10, 5.13, 5.14, 5.15 and 5.16.
    """
    account = split.GetAccount()
    if account is None:
        return ''
    commodity = account.GetCommodity()
    return commodity.get_mnemonic() if commodity is not None else ''


def transaction_currency(transaction) -> str:
    commodity = transaction.GetCurrency()
    return commodity.get_mnemonic() if commodity is not None else ''


def iter_splits(book) -> Iterator:
    """Every split in the book, walking the account tree."""
    root = book.get_root_account()

    def walk(account):
        yield from account.GetSplitList()
        for child in account.get_children():
            yield from walk(child)

    yield from walk(root)


def cost_of(split) -> Optional[Fraction]:
    """What this split's currency cost, in the book's currency, per unit.

    Read from the transaction, never stored, and always from *this* split:
    its value divided by its amount, converted into the book's currency if the
    transaction is not already stated there.

    Where the transaction is stated in the book's own currency, nothing is
    added up: each split is already valued in CAD, so its own value over its
    own amount is its cost and nothing beside it can move that. One transaction
    can bring in two currencies at once — 99.90 CAD sold for both 40.00 USD
    and 261.63 HKD — and each has its own cost, 1.35 CAD/USD and 1/5.7
    CAD/HKD; charging either with the whole CAD that left would price it as if
    it had bought everything. Nor is every base-currency split part of what
    was bought: a 2.00 CAD bank fee is an expense, and adding it in would
    report 40.00 USD as costing 1.45 rather than 1.35, overstating the cost of
    that currency for as long as the cost basis lives.

    Where the transaction is stated in the *foreign* currency, this split's
    own value is in that currency too, and the rate has to come from the
    base-currency splits: their amounts added up, divided by what those
    amounts are worth added up (see `_base_per_unit_of`). All of them, because
    each is rounded on its own and reading whichever comes first makes the
    cost depend on split order. A CAD line
    converted at a different rate from its neighbours does move the result
    there; that is the aggregate of what the transaction did, and the fee
    belongs in its own transaction if it should not be part of it.

    A cost written on the split is consulted **last**, for the one shape whose
    transaction states none: every split in one foreign currency, with no
    base-currency figure to divide. Read first, it outranked the ledger — a
    split that paid 135.00 CAD for 100.00 USD reported whatever its KVP said,
    9.99 CAD/USD, and `fx-balances`, every realized gain and the cost every
    later sale must be valued at followed the copy rather than the money. A
    copy can be stale, hand-edited, or left behind by a correction; the
    transaction is what the book is.
    """
    derived = derived_cost_of(split)
    if derived is not None:
        return derived
    return stated_cost_of(split)


_being_priced: Set[str] = set()


def derived_cost_of(split) -> Optional[Fraction]:
    """What the transaction itself says this split's currency cost, or None.

    None when it says nothing: a split with no amount to divide by, or a
    transaction in the record's own currency with no base-currency figure
    anywhere in it. A zero cost is None as well — 100.00 USD stated as worth
    nothing prices no currency, and a cross-currency posting GnuCash wrote with
    amount 0 is exactly that shape.
    """
    amount = _fraction(split.GetAmount())
    if amount == 0:
        return None
    # A split in a book is always in a transaction.
    transaction = split.GetParent()
    tx_currency = transaction_currency(transaction)

    # `share_price` is value per unit, stated in the transaction's currency.
    per_unit = abs(_fraction(split.GetValue()) / amount)
    if tx_currency != BASE_CURRENCY:
        base_per_tx_currency = _base_per_unit_of(transaction)
        if base_per_tx_currency is None:
            return None
        per_unit *= base_per_tx_currency
    # A split crossing zero that gives a guid carries two things in one value:
    # what it repaid, at the cost of the cost basis it gives, and what it
    # brought in. 1,000.00 USD into an account at −500.00 valued at 1,375.00
    # repays 500.00 owed at 1.35, which is 675.00, so the 500.00 it brought in
    # cost 700.00, 1.40 each (Q-047).
    guid = cost_basis_guid_of(split)
    brought_in = (None if split_moves(split) is None else _stored_brought_in(split))
    if guid and brought_in:
        # A split already being priced prices nothing: one giving its own guid,
        # or two giving each other's, asked what they cost, went on asking
        # until Python gave up. A guid matching nothing, or a split with no
        # cost, prices nothing either; `_validate_pick` refuses all three and
        # says which.
        this = split_guid(split)
        if this in _being_priced:
            return None
        _being_priced.add(this)
        try:
            repaid = find_split_by_guid(split.GetBook(), guid)
            repaid_cost = cost_of(repaid) if repaid is not None else None
        finally:
            _being_priced.discard(this)
        if repaid_cost is None:
            return None
        whole = per_unit * abs(amount)
        left = (whole - repaid_cost * (abs(amount) - brought_in)) / brought_in
        # Valued under what it repaid cost, what is left for the part brought
        # in is below nothing, and prices no currency;
        # `_a_crossing_valued_against_another_cost` refuses it where the
        # transaction says what its currency fetched.
        per_unit = left if left > 0 else Fraction(0)
    return per_unit or None


def _base_per_unit_of(transaction) -> Optional[Fraction]:
    """What one unit of the transaction's currency is worth in the book's.

    Asked only of a transaction stated in another currency: in the book's own,
    a split's value over its amount already is the cost, and both callers
    check that first.

    Taken from the splits on base-currency accounts, whose amount over value
    is that same rate the other way up — all of them together, as one sum over
    another, not whichever happens to be first.

    They are all converted at the one rate the transaction was entered at, but
    each is rounded to the cent on its own, so individually they disagree in
    the last digit: a USD invoice with tax, posted at 1.4, books 46.66 CAD against 33.33
    USD and 4.66 against 3.33, which are 1.40006 and 1.39940. Reading one
    split answered with whichever of those it reached first — the tax line, on
    a book where the tax is listed before the income — and priced the whole
    basis at 1.3994. Summing cancels most of the rounding and cannot depend on
    order: 51.32 over 36.66 is 2566/1833, or 1.39989.

    Every base-currency split counts rather than some chosen subset. Where the
    transaction did convert at one rate — the ordinary case — a fee split
    changes the numerator and denominator together and cannot move the answer.
    Where its splits were converted at different rates, as
    `fx_two_base_splits_at_different_rates.txt` is, the fee does move it: a
    fee at 1.25 beside revenue at 1.4 adds up to 25/18, or 1.3889. That is the
    aggregate of what the transaction actually did, which is the most any
    single figure can be for such a book, and it is the same figure however
    the splits are ordered. Choosing one split instead would answer with
    whichever came first.
    """
    base_total = Fraction(0)
    value_total = Fraction(0)
    for other in transaction.GetSplitList():
        if split_commodity(other) != BASE_CURRENCY:
            continue
        base_amount = _fraction(other.GetAmount())
        tx_value = _fraction(other.GetValue())
        if base_amount == 0 or tx_value == 0:
            continue
        base_total += abs(base_amount)
        value_total += abs(tx_value)
    if value_total == 0:
        return None
    return base_total / value_total


def cost_basis_guid_of(split) -> str:
    """The guid of the split whose cost basis this split picks, or ''."""
    return _as_a_pick(get_custom_metadata(split).get(COST_BASIS_SPLIT_KEY, ''))


def _as_a_pick(value) -> str:
    return (str(value).replace('-', '').lower()
            if value and str(value) != PENDING else '')


# `cost_basis_split_guid: $pending$`: a disposal whose cost basis is not
# decided yet. It is imported drawing on none, so the book's cost bases offer
# currency its accounts no longer hold until an edit gives it one, and the
# book says so: `fx-balances` lists every pending disposal. Stored as the key's
# own value and read as no pick by everything that asks which cost basis a
# split draws on, so an edit giving the guid is read as a pick being given,
# and draws the cost basis down as a new transaction's does.
PENDING = '$pending$'


def is_pending(split) -> bool:
    """Whether this split gives `cost_basis_split_guid: $pending$`."""
    return str(get_custom_metadata(split).get(COST_BASIS_SPLIT_KEY, '')) == PENDING


def pending_disposals(book) -> List[Dict]:
    """Every split giving `cost_basis_split_guid: $pending$` that can stand, oldest first.

    The import refuses one that cannot (`why_a_pending_split_cannot_stand`),
    but a book can be changed elsewhere. One that cannot stand is left out
    here, since it would be taken off the cost bases wrong, and
    `--verify-costs` and `--verify-integrity` report it with the reason
    (`what_the_pending_disposals_get_wrong`).
    """
    found = []
    for split in iter_splits(book):
        if not is_pending(split) or why_a_pending_split_cannot_stand(split):
            continue
        transaction = split.GetParent()
        found.append({'date': transaction.GetDate().strftime('%Y-%m-%d'),
                      'when': transaction.GetDate().date(),
                      'account': get_account_full_name(split.GetAccount()),
                      'amount': drawn_by(split),
                      'unit': smallest_unit(split),
                      'currency': split_commodity(split),
                      'namespace': split.GetAccount().GetCommodity().get_namespace(),
                      'side': the_side_it_draws(split),
                      # What the transaction records it at in the book's own
                      # currency, which is what leaves the book's figures,
                      # since no cost basis was drawn at a cost. The import
                      # refuses `$pending$` where no figure says.
                      'recorded_at': _what_the_book_recorded_it_at(split),
                      'description': transaction.GetDescription() or ''})
    return sorted(found, key=lambda row: (row['date'], row['account']))


def why_a_pending_split_cannot_stand(split) -> str:
    """Why a split giving `$pending$` cannot be taken off the cost bases as pending, or `''`.

    Asked when its transaction is imported or edited. What the split moves on
    each side is recorded then (`_stored_brought_in`), so a transaction
    imported later and dated before it does not change the answer.
    """
    here = (f'the split on {get_account_full_name(split.GetAccount())} gives '
            f'`{COST_BASIS_SPLIT_KEY}: {PENDING}`')
    # Only on a split disposing of a holding. On one bringing currency in, or
    # on a receivable, it would be counted as a pending disposition of
    # nothing, and the balance sheet nets a pending disposition off its side.
    side = the_side_it_draws(split)
    if side is None:
        return (f'{here}, and it is no disposition: it disposes of nothing the '
                f'book holds or owes. `{PENDING}` stands for the cost basis of a '
                f'disposition not decided yet. Take it off that split.')
    # And only where the book keeps a cost basis of that currency on that
    # side, since the balance sheet takes a pending disposition off those; a
    # disposition where none is kept draws on nothing and needs no pick.
    # Kept on the split's own date: an edit giving `$pending$` to a sale
    # dated before any cost basis opened was accepted once one had opened
    # later, and the balance sheet took it off a cost basis it predates.
    commodity = split_commodity(split)
    book = split.GetAccount().get_book()
    when = split.GetParent().GetDate().date()
    if not (a_cost_basis_is_kept_for(book, commodity, side)
            and _a_cost_basis_opened_by(book, commodity, side, when)):
        held = 'holds' if side == 'asset' else 'owes'
        return (f'{here}, and the book keeps no cost basis of the {commodity} it '
                f'{held} opened by {when}, so there is none to decide. Take it '
                f'off that split.')
    # And only on a split whose whole amount is the disposition. One crossing
    # zero disposes of part and borrows the rest; one beside another account
    # of its side transfers part there. A pending row takes the split off
    # whole, at its whole value, so either would be taken off wrong.
    amount = abs(_fraction(split.GetAmount()))
    if not draws_down(split) == drawn_by(split) == amount:
        return (f'{here}, and it disposes of '
                f'{_format(draws_down(split), smallest_unit(split))} of the '
                f'{_format(amount, smallest_unit(split))} {split_commodity(split)} '
                f'on it: the rest is a borrowing, taking the account below zero, '
                f'or a transfer to another account on the same side. `{PENDING}` '
                f"stands for a disposition of a split's whole amount. Give this "
                f'one the cost basis it draws on.')
    # A pending disposition is taken off the cost bases at what its
    # transaction records it at in the book's own currency. Taken off at
    # nothing where none says, the whole of its cost stayed on what the cost
    # bases still hold, and the balance sheet overstated it.
    if _what_the_book_recorded_it_at(split) is None:
        return (f'{here}, and its transaction states no {BASE_CURRENCY} figure '
                f'for all it disposes of, or another of its splits draws on a '
                f'cost basis too and the transaction gives one figure for both: '
                f'a pending disposal is taken off the cost bases at what its '
                f'transaction records it at in {BASE_CURRENCY}. Give the cost '
                f'basis it draws on, or write the transaction in {BASE_CURRENCY}.')
    return ''


def what_the_pending_disposals_get_wrong(book) -> List[Dict]:
    """A finding for each split giving `$pending$` that cannot stand, for `--verify-costs`.

    The import refuses such a split, so a book holds one only where it was
    changed elsewhere. Reported rather than left out in silence, it gives
    the reader the split and the reason.
    """
    found = []
    for split in iter_splits(book):
        wrong = why_a_pending_split_cannot_stand(split) if is_pending(split) else ''
        if not wrong:
            continue
        transaction = split.GetParent()
        found.append({'guid': split_guid(split),
                      'account': get_account_full_name(split.GetAccount()),
                      'date': transaction.GetDate().strftime('%Y-%m-%d'),
                      'description': transaction.GetDescription() or '',
                      'tx_guid': transaction.GetGUID().to_string(),
                      'problems': [wrong]})
    return found


def _says_which(split) -> bool:
    """Whether this split says which cost basis it draws on: a guid, or `$pending$`."""
    return bool(cost_basis_guid_of(split)) or is_pending(split)


def splits_drawing_on(book, basis_guid: str) -> list:
    """Every split in the book giving this cost basis, as `cost_basis_guid_of` reads it.

    From an index of the whole book, built by walking it once and then kept
    up to date from each change of `cost_basis_split_guid`, which
    `set_custom_metadata` logs. Walked again for each question, an update
    touching 800 transactions that draw on cost bases walked a book of 2,000
    transactions 800 times (`tests/research/how_long_an_unchanged_update_takes_as_a_book_grows_probe.py`).

    Each split the index gives is looked up and asked again, so a split
    destroyed since, whose pick no write took off, is not given.

    It rests on every pick being written through `set_custom_metadata`,
    which is how this tool writes each one. GnuCash writes none of its own.
    Where it divides a split, applying an owner's credit, the part keeping
    the split's guid keeps its KVPs, the pick among them, and the part it
    carves off holds none (CLAUDE.md finding 10), so nothing the engine
    does adds a pick the log misses. A pick written any other way would not
    be found until the next import walks the book again.
    """
    changes = custom_key_changes(COST_BASIS_SPLIT_KEY)
    kept = getattr(book, '_plaintext_drawn_on', None)
    if kept is None or kept[0] is not changes:
        index: Dict[str, set] = {}
        for split in iter_splits(book):
            picked = cost_basis_guid_of(split)
            if picked:
                index.setdefault(picked, set()).add(split_guid(split))
        kept = [changes, len(changes), index]
        book._plaintext_drawn_on = kept
    for guid, was, now in changes[kept[1]:]:
        guid = _as_a_pick(guid)
        kept[2].get(_as_a_pick(was), set()).discard(guid)
        if now:
            kept[2].setdefault(_as_a_pick(now), set()).add(guid)
    kept[1] = len(changes)
    found = (find_split_by_guid(book, guid) for guid in sorted(kept[2].get(basis_guid, ())))
    return [split for split in found
            if split is not None and cost_basis_guid_of(split) == basis_guid]


def takes_an_exchange_difference(account) -> bool:
    """True when a split on this account could be a realized exchange difference.

    `$residual$` is a balancing feature rather than a currency one: any
    transaction may write it, on any account whose commodity is the
    transaction's. But a residual that balances onto a bank or a receivable
    moved money, it did not measure a difference — counted as one, a disposal
    writing `Assets:CAD Bank $residual$ CAD` beside a stated gain put the
    1,400.00 the bank received into `realized_gains_fx` and stated it as the
    gain. So the mark goes on income and expense alone, which is the rule the
    payment path has required all along.

    It cannot tell an exchange difference from any other income or expense in
    the same disposal — a bank charge is an expense too, and 8.60 USD disposed
    of paid an 11.92 charge beside 0.07 of exchange difference. That is what
    the `$residual$` token and a stated `took_the_residual` are for; this only
    keeps the balance sheet out of it.
    """
    return account.GetType() in _GAIN_TYPES


def states_the_residual_mark(value) -> bool:
    """True when a `took_the_residual:` value states yes.

    One definition, because two places ask it. This module reads the key off a
    saved split, and the import counts the splits of one transaction that claim
    the residual, so that two cannot both claim it. Were the two to disagree, a
    file could state a key the import counted and the page did not, or the
    reverse. A value of `"false"`, `"no"`, `"0"` or nothing at all is a file
    saying no.
    """
    return str(value).strip().lower() not in ('', 'false', '0', 'no')


def took_the_residual(split) -> bool:
    """True when a transaction's `$residual$` line resolved to this split.

    The key alone does not decide it. It is an ordinary custom KVP, so a file
    can state `took_the_residual: "true"` on any split it likes, and the export
    writes it back out — measured, so it cannot simply be refused without
    breaking the round trip of every book that has a real one. Believed on its
    own word it let a file put any split into `realized_gains_fx`: stated on a
    Canadian rent line it booked an 800.00 CAD exchange loss on a book holding
    no foreign currency, and stated in a US dollar transaction that gives a
    real cost basis guid it added 20.00 US dollars into a Canadian total,
    itemised on the page as `2026-03-01 Assets:USD Savings -20.00 CAD`.

    So the ledger is asked as well, exactly as the importer asks it before
    writing the key: the transaction must be stated in the book's own currency,
    and must hold a disposal that gives the guid of the cost basis it draws on.
    That is the same rule a stored cost follows — the transaction outranks the
    copy — and it answers for books already written as well as for new files.
    """
    if not states_the_residual_mark(
            get_custom_metadata(split).get(TOOK_THE_RESIDUAL_KEY, '')):
        return False
    return _could_hold_an_exchange_difference(split)


def _could_hold_an_exchange_difference(split) -> bool:
    """The three facts a book answers for itself about an exchange difference.

    Shared, because two things stand as the fourth. The book states it with
    `took_the_residual`. A reader states it by giving the account their
    differences are booked to, for a book written before that key existed.
    Either way these three hold, so neither can widen where a difference may
    sit: a split on a bank or a receivable moved money rather than measuring a
    difference, a transaction stated in another currency would add that
    currency's units into a total kept in this one, and a transaction that
    draws on no cost basis disposed of nothing to make a difference on.
    """
    if not takes_an_exchange_difference(split.GetAccount()):
        return False
    # Every split a saved book yields has a parent: one with no account cannot
    # be loaded from a file on any supported version (CLAUDE.md §12), so there
    # is nothing here to guard against.
    transaction = split.GetParent()
    if transaction_currency(transaction) != BASE_CURRENCY:
        return False
    # What it disposed of, which in a book keeping no cost bases is read from
    # the splits in another commodity (Q-049).
    return bool(what_a_disposal_gave_up(transaction))


def counts_as_an_exchange_difference(split, gain_accounts=()) -> bool:
    """True where this split is a realized exchange difference.

    Two things can say which split of a disposal the difference is, and the
    book cannot work it out alone: a balanced transaction gives every one of
    its splits the same arithmetic, and the account type separates nothing —
    8.60 USD disposed of paid an 11.92 bank charge beside 0.07 of exchange
    difference, both on expense accounts.

    The book says it with `took_the_residual`, written where a plaintext file
    used `$residual$`. A reader says it by giving the accounts in `gain_accounts`,
    which is the only answer for a book written before that key existed: such a
    book stored the amount the token resolved to and had no key to write, so it
    states `realized_gains_fx: 0.00` while its own income statement carries the
    difference its income account holds.

    **With an FX gain/loss account specified, `took_the_residual` is not
    consulted at all.** The two are not added together, and this is deliberate:
    a reader who states where their differences are booked has answered the
    question for the whole book, and a page that then also counted whatever
    keys happened to be in it would give an answer depending on which release
    imported which transaction — a difference the reader cannot see and did not
    ask about. One rule per page. So a split carrying the key on an account not
    specified here is passed over, and a book wanting both counts specifies
    both accounts.

    What an account specified here cannot do is widen where a difference may sit.
    The conditions the book can check still hold, so an account specified by
    mistake counts nothing on a transaction that draws on no cost basis, or one
    stated in another currency.
    """
    if not gain_accounts:
        return took_the_residual(split)
    # The account first, because it is one string compare and settles most
    # splits: every bank line, every payable, every expense on an account the
    # reader did not state. `_could_hold_an_exchange_difference` walks the
    # transaction's splits looking for one that draws on a cost basis, so asking
    # it first walked the whole book's worth of transactions to reject splits an
    # account name rejects outright.
    if get_account_full_name(split.GetAccount()) not in gain_accounts:
        return False
    return _could_hold_an_exchange_difference(split)


def mark_as_having_taken_the_residual(split) -> None:
    """Record that a transaction's `$residual$` line resolved to this split.

    Its other keys are kept. **Call this while the transaction is open.** Both
    callers mark a split of a transaction they are still building, so the write
    lands inside that edit, which is what carries a KVP to disk (CLAUDE.md §11);
    marking a split of a committed transaction would leave the key in memory
    and lose it on save, so open the edit rather than relying on this to.
    """
    metadata = dict(get_custom_metadata(split))
    metadata[TOOK_THE_RESIDUAL_KEY] = 'true'
    set_custom_metadata(split, metadata)


def realized_fx_items_up_to(book, as_of, gain_accounts=()) -> list:
    """Each exchange difference the book realized by the end of `as_of`.

    `[(date, account full name, figure)]`, oldest first. The balance sheet
    states them one by one and totals `realized_gains_fx` from these same
    items, so the key and the working it is said to add up to are one walk of
    the book rather than two — a gain is measured against costs that appear on
    no line of the page, so without its working it is the one figure there that
    has to be taken on trust, and two passes could come to differ.

    A figure is the negative of the value on the marked split, because an
    income split carries a credit: a sale of 3,000.00 USD that gained 240.00
    CAD posts −240.00 to its income account, and a book that lost 19.86 posts
    +19.86.

    Cumulative to the date rather than for a period, because a balance sheet
    states what a book has taken by the day it is drawn. Read from the splits
    rather than from an income account's balance, which closing the books
    resets while leaving the splits where they are.

    `gain_accounts` are the full names of accounts a reader states their
    exchange differences are booked to, for a book that carries no
    `took_the_residual` of its own. A split on one of them counts as a
    difference where the book's own three conditions hold.
    """
    return _realized_items_up_to(book, as_of, 'CURRENCY', gain_accounts)


def realized_other_items_up_to(book, as_of) -> list:
    """Each difference the book realized on a security by the end of `as_of`.

    `realized_gains_other`, in the same shape and read the same way as
    `realized_fx_items_up_to` reads `realized_gains_fx`. What separates the two
    is the holding the disposal drew on: shares sold realize a gain on shares,
    dollars spent realize one on dollars, and a page that added them together
    would tell a filer one figure where their return wants two.

    Read from `took_the_residual` alone. `--fx-gain-account` exists for a book
    written before that key, and no such book holds a gain on shares: a share
    has a cost basis to draw down only where an import written with the key
    opened one, and that import marks the difference as it records it. So the
    accounts a reader gives for exchange differences say nothing here, and a
    sale whose difference sits on another account is still a gain on shares.
    """
    return _realized_items_up_to(book, as_of, 'security')


def is_a_currency(commodity) -> bool:
    """Whether this commodity is a currency rather than a security.

    The one place this distinction is spelled, because the two must be kept
    apart everywhere they meet and a comparison written out at each site is a
    chance for one of them to drift. A currency and a share are the same kind
    of holding to a cost basis — both have a quantity, a cost and a price
    (Q-046) — and they are not the same kind of thing to a reader: a gain on
    currency and a gain on shares are separate figures on a balance sheet and
    separate lines on a return, and a program reading gnucash-plaintext's pages
    may handle currency and not securities. So they share the machinery and
    never the key.

    GnuCash says it with the namespace: every currency is in `CURRENCY`, and a
    share is in its exchange's. `gnc-commodity-is-currency?` is the same
    question and is not bound in the Guile this project's reports run in.
    """
    return (commodity is not None
            and commodity.get_namespace() == 'CURRENCY')


def what_a_disposal_gave_up(transaction) -> set:
    """Which kinds of holding this transaction drew a cost basis down on.

    `{'CURRENCY'}`, `{'security'}`, both, or neither. Read from the splits that
    give a `cost_basis_split_guid:`, because a split giving one is the disposal
    and its own commodity says what was disposed of: `Assets:AMZN -8.0000 AMZN`
    gave up shares and `Assets:USD Bank -3,000.00 USD` gave up dollars. The
    splits on the other side of the entry are what the disposal fetched, and
    say nothing about what it was.

    A split carrying that key is one a file wrote onto an account it had to find
    first, so its account and commodity are there to read. The split GnuCash
    makes for itself with no account yet attached (CLAUDE.md finding 12) carries
    no key and is passed over by the line above.

    A book that keeps no cost bases (Q-049) gives none, so there the disposal
    is a split in anything other than the book's own currency: the only thing
    in such an entry that can have been given up for a difference to be
    realized on.
    """
    # Through a split: SWIG gives a transaction no `GetBook`.
    splits = transaction.GetSplitList()
    keeps = not splits or book_keeps_cost_bases(splits[0].GetBook())
    kinds = set()
    for split in splits:
        if not (cost_basis_guid_of(split) if keeps else _held_in_another_commodity(split)):
            continue
        commodity = split.GetAccount().GetCommodity()
        kinds.add('CURRENCY' if is_a_currency(commodity) else 'security')
    return kinds


def _held_in_another_commodity(split) -> bool:
    """Whether the split is on an account kept in anything but the book's own currency.

    In a book that keeps no cost bases (Q-049) the realized difference is what
    the file states with `$residual$`, which no cost basis decides: beside a
    split in another currency or a security it is that holding's realized
    difference, whichever way the split moves.
    """
    account = split.GetAccount()
    return account is not None and not is_the_books_own_currency(account.GetCommodity())


def is_the_books_own_currency(commodity) -> bool:
    """Whether the commodity is the currency cost bases are recorded in: the one place that is asked."""
    return is_a_currency(commodity) and commodity.get_mnemonic() == BASE_CURRENCY


def _realized_items_up_to(book, as_of, kind: str, gain_accounts=()) -> list:
    items = []
    for split in iter_splits(book):
        if not counts_as_an_exchange_difference(split, gain_accounts):
            continue
        # Every split a saved book yields has a parent and an account. A split
        # with no account cannot be loaded from a file on any supported version
        # — 5.x drops the whole transaction and 4.x and below segfault in the
        # loader (CLAUDE.md §12) — so there is nothing here to guard against.
        transaction = split.GetParent()
        # The one difference this entry states belongs to the one kind of
        # holding it disposed of. An entry giving up both is refused as it
        # lands (`refuse_a_disposal_of_two_kinds_at_once`), so nothing here has
        # to divide a figure the ledger states whole.
        if what_a_disposal_gave_up(transaction) != {kind}:
            continue
        when = transaction.GetDate().date()
        if when > as_of:
            continue
        items.append((when.isoformat(),
                      get_account_full_name(split.GetAccount()),
                      -_fraction(split.GetValue())))
    return sorted(items)


def refuse_a_disposal_of_two_kinds_at_once(transaction) -> None:
    """Refuse an entry that gives up currency and a security together.

    Such an entry realizes two differences — one on the currency and one on the
    shares — and states one figure between them. A balance sheet keeps the two
    apart, as a filer's return does, so counting the single figure as either
    states the other as nothing, and dividing it is `import` choosing a split
    the file never wrote.

    Written as two entries it is unambiguous: the shares sold for currency, and
    then the currency spent.
    """
    if what_a_disposal_gave_up(transaction) != {'CURRENCY', 'security'}:
        return
    if not any(counts_as_an_exchange_difference(split)
               for split in transaction.GetSplitList()):
        return
    raise Exception(
        'this transaction draws down a currency cost basis and a security '
        'cost basis at once, so it realizes a difference on each — and one '
        'split cannot state both, because a balance sheet keeps a gain on '
        'currency apart from a gain on shares. Write it as two transactions: '
        'the shares sold for what they fetched, and the currency spent.')


def refuse_a_transfer_sharing_a_transaction(transaction) -> None:
    """Refuse a transfer written in one transaction with a spend or an arrival.

    Units moved between two accounts on one side draw down no cost basis and
    open none, because the book holds every one it held before. Units spent
    draw one down by what was spent, and units bought open one for what
    arrived. In one transaction nothing says which is which: 4,010.00 USD
    leaving the bank and 4,000.00 arriving in savings does not say which
    10.00 was a fee, and a cost basis is never guessed.

    Imported regardless, each was sized by its split. The fee drew the whole
    4,010.00 off the cost basis, leaving it 4,000.00 below what the accounts
    hold; 3,000.00 moved with 1,000.00 bought opened a cost basis of 4,000.00,
    3,000.00 above. Written as two transactions, each is one of the shapes
    the rest of this module answers.

    **Between accounts, so each account is netted first.** 100.00 USD bought
    into a bank with the bank keeping 1.00 of it as a fee is +100.00 and −1.00
    on one account: 99.00 arriving, which `record_cost_bases` opens a cost
    basis for, with nothing moved anywhere. A transfer is one account rising
    while another on the same side falls.

    Only where the transaction touches a cost basis — a split giving a guid,
    or one that would open a basis. A book keeping none, as one whose accounts
    are all in a currency that is not the book's own, moves its money about as
    it likes. Business accounts are left out, for the reason
    `_what_left_each_side` leaves them out.
    """
    by_account: Dict[tuple, Fraction] = {}
    units_of: Dict[str, int] = {}
    for split in transaction.GetSplitList():
        split_move = split_moves(split)
        if split_move is None:
            continue
        commodity = split_commodity(split)
        units_of[commodity] = smallest_unit(split)
        for side, change in zip(('asset', 'liability'), split_move):
            key = (commodity, side, get_account_full_name(split.GetAccount()))
            by_account[key] = by_account.get(key, Fraction(0)) + change
    moves: Dict[tuple, Dict[str, Fraction]] = {}
    for (commodity, side, _account), change in by_account.items():
        figures = moves.setdefault(
            (commodity, side),
            {'rose': Fraction(0), 'fell': Fraction(0), 'unit': units_of[commodity]})
        if change > 0:
            figures['rose'] += change
        else:
            figures['fell'] -= change
    for (commodity, side), figures in moves.items():
        rose, fell = figures['rose'], figures['fell']
        if not rose or not fell or rose == fell:
            continue
        # A transfer out of an account holding less than it sends is a
        # borrowing for the rest: 1,200.00 USD out of an account holding
        # 1,000.00 moves 1,000.00 and owes 200.00, and the 200.00 more held is
        # the 200.00 more owed. Nothing there needs telling apart (Q-047).
        # And its mirror, paying off more than is owed: 500.00 USD out of an
        # account onto a card owing 300.00 repays 300.00 and moves 200.00 to
        # the card's credit, and the 300.00 less held is the 300.00 less owed.
        #
        # Only where every account moving on the other side crossed zero, moving
        # this side too. 1,000.00 from C and 200.00 charged to a card, into B,
        # adds up the same, and is a transfer sharing a transaction with a
        # borrowing: nothing says which of B's dollars moved and which arrived.
        other_side = 'liability' if side == 'asset' else 'asset'
        other = moves.get((commodity, other_side))
        crossed = all(by_account.get((commodity, side, account), Fraction(0)) != 0
                      for (each, on, account), change in by_account.items()
                      if each == commodity and on == other_side and change != 0)
        if other is not None and crossed and (
                (rose > fell and other['fell'] == 0 and other['rose'] == rose - fell)
                or (fell > rose and other['rose'] == 0 and other['fell'] == fell - rose)):
            drawing = [split for split in transaction.GetSplitList()
                       if split_commodity(split) == commodity and cost_basis_guid_of(split)
                       and the_side_it_draws(split) == side]
            if fell > rose and len(drawing) > 1:
                unit = figures['unit']
                held = 'held' if side == 'asset' else 'owed'
                raise Exception(
                    f'this transaction pays off {_format(fell - rose, unit)} '
                    f'{commodity} {"owed" if side == "asset" else "held"} and moves '
                    f'{_format(rose, unit)} {commodity} within the {held} side, and '
                    f'{len(drawing)} splits give a cost basis on the {held} side: '
                    f'nothing says which of them the {_format(rose, unit)} that only '
                    f'moved came out of, and a cost basis is never chosen for you. '
                    f'Write what moved as a transaction of its own.')
            continue
        if not any(split_commodity(split) == commodity
                   and split_moves(split) is not None
                   and split_moves(split)[0 if side == 'asset' else 1] != 0
                   and (cost_basis_guid_of(split) or establishes_cost_basis(split))
                   for split in transaction.GetSplitList()):
            continue
        # The splits giving a cost basis say they are what left. Where the
        # rest is a transfer — as much leaving one account of the side as
        # arrives in another — nothing is left unsaid: 2,720.00 USD moved from
        # savings into a bank, and a 0.72 USD fee out of the bank giving the
        # cost basis it spends. Refused, a book started part-way through its
        # life, its savings an opening balance, could not record a transfer
        # and its fee as the bank writes them (Q-051). Where the rest is not a
        # transfer, a split giving a cost basis carries units that only moved,
        # and nothing says which: 4,010.00 USD out of savings giving its cost
        # basis, 4,000.00 into the bank.
        if _the_rest_is_a_transfer(transaction, commodity, side):
            continue
        unit = figures['unit']
        held = 'held' if side == 'asset' else 'owed'
        what = (f'{_format(fell - rose, unit)} {commodity} leaves that side'
                if fell > rose else
                f'{_format(rose - fell, unit)} {commodity} arrives on that side')
        raise Exception(
            f'this transaction moves {_format(min(rose, fell), unit)} {commodity} '
            f'between accounts on the {held} side, and {what} as well. A '
            f'transfer draws down no cost basis and opens none, and nothing in '
            f'one transaction says which units moved and which did not. Write '
            f'the transfer as a transaction of its own, and what left or '
            f'arrived as another.')


def _the_rest_is_a_transfer(transaction, commodity: str, side: str) -> bool:
    """Whether, leaving out the splits that give a cost basis, this side only moves between accounts.

    Netted by account, as the transfer check nets them: what one account of
    the side gave up, another took, and something did.
    """
    at = 0 if side == 'asset' else 1
    by_account: Dict[str, Fraction] = {}
    for split in transaction.GetSplitList():
        moves = split_moves(split) if split_commodity(split) == commodity else None
        if moves is None or cost_basis_guid_of(split):
            continue
        name = get_account_full_name(split.GetAccount())
        by_account[name] = by_account.get(name, Fraction(0)) + moves[at]
    rose = sum((change for change in by_account.values() if change > 0), Fraction(0))
    fell = -sum((change for change in by_account.values() if change < 0), Fraction(0))
    return rose > 0 and rose == fell


def refuse_a_difference_no_split_can_state(book, transaction) -> None:
    """Refuse a disposal written wholly in a foreign currency that realizes a difference.

    Three shapes. A share sale always does: the shares leave at what they cost
    in the book's own currency and fetch something in another, and the dollars
    they bring in arrive with no cost to open a cost basis at. So does one
    currency held exchanged for another, for the same reason. A repayment does
    where the debt and the currency paying it cost different amounts a unit.

    Repaying a foreign loan out of foreign currency the book holds draws a cost
    basis down on each side: the currency leaves the bank and the debt it pays
    off goes. Where those units cost different amounts, the difference is
    realized — 1,500.00 USD of debt that cost 1.35 paid with dollars that cost
    1.30 makes 75.00 CAD — and `$residual$` is the split that states it, in the
    book's own currency. A transaction with no split in that currency has
    nowhere to put it.

    Imported regardless, the book was left holding a gain no account records,
    and the balance sheet stopped balancing from that transaction on by exactly
    that much. `--verify-integrity` found it afterwards, pointing at no
    transaction.

    Where the two sides cost the same a unit nothing is realized, and the
    transaction is imported: there is no figure to state.

    Runs after `apply_cost_basis_picks`, which has checked every guid given, so
    each matches a split with a cost.
    """
    if transaction_currency(transaction) == BASE_CURRENCY:
        return
    if any(split_commodity(split) == BASE_CURRENCY
           for split in transaction.GetSplitList()):
        return
    # A security leaving is the plainest case of it. Its cost basis is in the
    # book's own currency, what it fetched arrives in another with no cost to
    # open a basis at, and the gain between them has no split to state it.
    for split in transaction.GetSplitList():
        basis_guid = cost_basis_guid_of(split)
        if not basis_guid or is_a_currency(split.GetAccount().GetCommodity()):
            continue
        commodity = split_commodity(split)
        raise Exception(
            f'this transaction sells '
            f'{_format(abs(_fraction(split.GetAmount())), smallest_unit(split))} '
            f'{commodity}, which cost '
            f'{exact_text(cost_of(find_split_by_guid(book, basis_guid)))} '
            f'{BASE_CURRENCY}/{commodity}, and is written wholly in '
            f'{transaction_currency(transaction)}, so no split in it can state '
            f'what the sale realized. Write it in {BASE_CURRENCY}, the shares at '
            f'what they cost and the currency at what it fetched, and give the '
            f'difference to a `$residual$` split.')
    # So is one currency held exchanged for another: the first leaves at what
    # it cost, the second arrives with no cost to open a cost basis at, and
    # the cost the first gave up leaves the book with nothing to show for it.
    paying = [split for split in transaction.GetSplitList()
              if cost_basis_guid_of(split) and the_side_it_draws(split) == 'asset']
    spent = {split_commodity(split) for split in paying}
    # Currency arriving on the held side, read from what each split moves: a
    # card paid past zero brings a credit in there as a bank does.
    bought = [split for split in transaction.GetSplitList()
              if split_moves(split) is not None and split_moves(split)[0] > 0
              and is_a_currency(split.GetAccount().GetCommodity())
              and split_commodity(split) not in spent]
    if paying and bought:
        split, arrived = paying[0], bought[0]
        raise Exception(
            f'this transaction sells '
            f'{_format(abs(_fraction(split.GetAmount())), smallest_unit(split))} '
            f'{split_commodity(split)}, which cost '
            f'{exact_text(cost_of(find_split_by_guid(book, cost_basis_guid_of(split))))} '
            f'{BASE_CURRENCY}/{split_commodity(split)}, for '
            f'{_format(_fraction(arrived.GetAmount()), smallest_unit(arrived))} '
            f'{split_commodity(arrived)}, and is written wholly in '
            f'{transaction_currency(transaction)}, so no split in it can state '
            f'what the exchange realized, and the {split_commodity(arrived)} '
            f'arrive with no cost to open a cost basis at. Write it in '
            f'{BASE_CURRENCY}, each split valued at what it is worth in '
            f'{BASE_CURRENCY}, and give the difference to a `$residual$` split.')
    drawn: Dict[tuple, List[Fraction]] = {}
    units_of: Dict[str, int] = {}
    for split in transaction.GetSplitList():
        basis_guid = cost_basis_guid_of(split)
        if not basis_guid:
            continue
        # A split with no side — a receivable or a payable, settled through its
        # lot — is kept under None and never compared: only a held side against
        # an owed one realizes a difference here. The side is the one the split
        # draws on, whatever its account's type: 500.00 USD into a bank at
        # −500.00 pays off what the bank owed, and a refill written wholly in
        # US dollars out of dollars held at another cost realized a difference
        # no split stated, read by type as two held splits (Q-047).
        units = draws_down(split)
        cost = cost_of(find_split_by_guid(book, basis_guid))
        units_of[split_commodity(split)] = smallest_unit(split)
        figures = drawn.setdefault((split_commodity(split), the_side_it_draws(split)),
                                   [Fraction(0), Fraction(0)])
        figures[0] += units
        figures[1] += units * cost
    for (commodity, side), (owed_units, owed_cost) in drawn.items():
        if side != 'liability' or (commodity, 'asset') not in drawn:
            continue
        held_units, held_cost = drawn[(commodity, 'asset')]
        owed_rate = owed_cost / owed_units
        held_rate = held_cost / held_units
        if owed_rate == held_rate:
            continue
        realized = min(owed_units, held_units) * (owed_rate - held_rate)
        unit = units_of[commodity]
        base_unit = book.get_table().lookup(
            'CURRENCY', BASE_CURRENCY).get_fraction()
        raise Exception(
            f'this transaction pays off {_format(owed_units, unit)} {commodity} '
            f'owed, which cost {exact_text(owed_rate)} '
            f'{BASE_CURRENCY}/{commodity}, with {_format(held_units, unit)} '
            f'{commodity} held, which cost {exact_text(held_rate)} '
            f'{BASE_CURRENCY}/{commodity}, so it realizes a difference of '
            f'{_format(realized, base_unit)} {BASE_CURRENCY}. It is written wholly in '
            f'{transaction_currency(transaction)}, so no split in it can state '
            f'that figure. Write it in {BASE_CURRENCY}, each {commodity} split '
            f'valued at what its cost basis cost, and give the difference to a '
            f'`$residual$` split.')


def establishes_cost_basis(split) -> bool:
    """True when this split brings foreign currency into the book at a cost.

    An invoice's A/R split and currency bought or borrowed raise a debit-side
    balance; a bill's A/P split raises a credit-side one. Either way the book
    now carries that many units at what they cost. A split that spends foreign
    currency establishes nothing, and neither does a split that picks another's
    cost basis — that one is the use, not the source.

    A security too, and on the same terms: a share is a quantity that cost
    something in the book's own currency, so a purchase stating a figure in that
    currency opens a basis for it and a sale draws it down (Q-046). And a
    business account moved against its normal direction counts only when it is a
    prepayment — a lot with no invoice or bill against it — since the same shape is
    otherwise a settlement, money that has already gone.

    A business account can be raised on either side, but only one of them
    unconditionally. Its normal direction — a debit on a receivable, a credit
    on a payable — is what the record owes and always establishes a cost basis.
    The opposite direction is a prepayment *or* a settlement, which look
    identical as figures: a 200 USD payment against a 100 USD invoice leaves
    two A/R credits, one settling the invoice and one the customer's money
    held and owed back. Only the second is currency the book still has, and
    what separates them is the lot — a settlement belongs to the invoice it
    settles, a prepayment to nothing yet — so that side is gated on
    `_is_prepayment`. Counting only the normal direction opened a cost basis for
    100 USD of the 200 the bank held; counting both offered currency already
    sent.
    """
    commodity = split_commodity(split)
    if not commodity or commodity == BASE_CURRENCY:
        return False
    # A share is a holding with a cost like any other (Q-046), so the namespace
    # does not decide this — what decides it is the last line of this function,
    # whether the book's own currency can say what the units cost. A share
    # bought in a transaction stating a figure in that currency can; one bought
    # in a transaction written wholly in the currency it was paid in cannot,
    # until that currency hands its cost over
    # (`carry_the_cost_to_what_it_bought`).
    #
    # The account is there to be read: `split_commodity` above answered a
    # mnemonic, and it answers the empty string for a split that has none —
    # which the check above has already turned away.
    account = split.GetAccount()
    amount = _fraction(split.GetAmount())
    if amount == 0:
        return False
    # Where its account crossed or lay past zero, the import recorded what the
    # split brought in, and that decides it — a split giving a guid included,
    # since 1,000.00 into an account at −500.00 repays 500.00 owed out of the
    # cost basis it gives and brings the other 500.00 in (Q-047).
    brought_in = (None if account.GetType() in (ACCT_TYPE_RECEIVABLE, ACCT_TYPE_PAYABLE)
                  else _stored_brought_in(split))
    if brought_in is not None:
        if not brought_in:
            return False
    else:
        if cost_basis_guid_of(split):
            return False
        # Which way the split moves is asked before what it cost, because
        # reading the cost can raise — a `cost_basis_cost` that does not parse
        # is refused rather than ignored — and a split that establishes nothing
        # has no cost worth refusing over. Asked first, a spend carrying such a
        # line was reported as an unreadable cost basis, listing and all.
        if not _raises_a_foreign_balance(split, account, amount):
            return False
    if _only_moved_within_one_side(split, account, amount):
        return False
    return cost_of(split) is not None


def _only_moved_within_one_side(split, account, amount: Fraction) -> bool:
    """Whether this transaction only moves the commodity about within one side.

    4,000.00 USD sent from a US dollar chequing account to a US dollar savings
    account arrives nowhere: the book held 4,000.00 before it and holds
    4,000.00 after. Judged one split at a time it looks like every other
    arrival — a positive amount on a bank account, with a cost — so a cost
    basis was opened for it, and investigated on this tree a book with 15,000.00
    USD came out of one such transfer with 19,000.00 USD of cost bases against
    the same 15,000.00 in its accounts. A transfer invented basis; it did not
    merely fail to move any.

    **What settles it is the net across the transaction, for this commodity and
    this side.** Where the units leaving equal the units arriving, nothing came
    in. Where they do not, the difference did, and that is what a cost basis is
    opened for.

    The side matters as much as the commodity, which is what keeps a borrowing
    out of this: 5,000.00 USD drawn on a loan and paid into a US dollar bank is
    +5,000.00 to the held side and +5,000.00 to the owed side, so both sides
    gained and each opens a basis of its own. Netting the two together would
    read the borrowing as a transfer and open neither, leaving a book that owes
    money the cost bases know nothing about.

    Business accounts are left out of the sum for the reason
    `_currency_arrived_elsewhere` leaves them out: a receivable's settling
    split sits beside an overpayment's credit on the same account, and is the
    invoice's money rather than a movement of anybody's. Their direction is
    already decided, carefully, by `_raises_a_foreign_balance`.
    """
    # A business account is not asked at all. Whether its split brings currency
    # in is `_raises_a_foreign_balance`'s answer — a posting in the record's own
    # direction, a prepayment against it — and that answer is reached through
    # lots, not through arithmetic on the transaction. Asked here it came out
    # wrong in the worst way: the sum below skips receivable and payable
    # accounts, so for a split on one of them it skipped the split's own
    # account, the net never saw the units it brought in, and every invoice
    # posting stopped being a cost basis. Investigated: a USD invoice settled into
    # an HKD bank re-imported with `cost_basis_split_guid … matches a split
    # that is no USD cost basis`.
    if account.GetType() in (ACCT_TYPE_RECEIVABLE, ACCT_TYPE_PAYABLE):
        return False

    commodity = split_commodity(split)
    # The side this split brings its currency in on: what comes into an account
    # is held, and what goes out of one below zero is owed, whatever the
    # account's type (Q-047).
    at = 0 if amount > 0 else 1

    # Each split's move on that side, so an account taken below zero adds to
    # the owed side rather than taking off the held one: 500.00 moved from an
    # empty account to another is 500.00 more held and 500.00 more owed, a
    # borrowing, where netting the two amounts read it as a transfer.
    net = Fraction(0)
    here = {split_guid(each) for each in split.GetParent().GetSplitList()}
    for other in split.GetParent().GetSplitList():
        # A split drawing on a cost basis its own transaction opens is a
        # spend of what arrived, not a move of it. Netted with the rest, a
        # 2,720.00 USD arrival whose own transaction spent all of it — a fee
        # and the rest sent on, each drawing on the arrival — came to nothing
        # arriving, and was no cost basis for them to draw on (Q-050). One
        # drawing on a cost basis the book already held stays in: 500.00 USD
        # paid from C onto a card owing 300.00 draws C's cost basis down by
        # 300.00, and the 200.00 it only moved opens no second one. A split
        # giving its own guid draws on no other, and is refused for it.
        if split_commodity(other) != commodity or cost_basis_guid_of(other) in (
                here - {split_guid(other)}):
            continue
        # Dollars a customer paid off an invoice leave the receivable as they
        # arrive in the bank: collected, not bought. The invoice's posting is
        # their cost basis, so the arrival they make is no second one — as a
        # collection into a US dollar bank never was, being stated in the
        # dollars. Stated in Canadian dollars beside a bank charge, the
        # arrival read as dollars bought, and the book held two cost bases
        # for one lump of money (Q-051).
        if at == 0 and _settles_an_invoice(other):
            net += _fraction(other.GetAmount())
            continue
        moves = split_moves(other)
        if moves is None:
            continue
        net += moves[at]
    # `<= 0` rather than `== 0`: a transfer that also pays a fee out of the
    # same account leaves the side lower than it started, and a side that lost
    # units has nothing arriving on it to cost.
    return net <= 0 and amount != 0


def _settles_an_invoice(split) -> bool:
    """Whether this split takes currency off a receivable by settling an invoice that prices it.

    In the invoice's lot, or applied to an invoice by this file's `payment:`
    block, which puts it in that lot once the transaction it is in has been
    imported (Q-051). And only an invoice whose posting is a cost basis: one
    booked to an income account kept in its own currency prices nothing, and
    the deposit settling it is then the only cost the book has for that money.

    An invoice the same file creates is not in the book yet when its
    collection is read: the business objects come after the transactions.
    Its posting is, imported with them, and the file's `posted_txn_guid:`
    finds it. Read as dollars bought instead, a book rebuilt from an export
    kept a balance on the deposit that nothing reads.
    """
    from infrastructure.gnucash.utils import wrap_invoice_or_bill
    from services.gnucash_importer import (
        _POSTINGS_THE_FILE_STATES,
        _SPLITS_THE_FILES_PAYMENTS_APPLY,
        _find_invoices_by_id,
        _find_transaction_by_guid,
    )

    account = split.GetAccount()
    if (account is None or account.GetType() != ACCT_TYPE_RECEIVABLE
            or _fraction(split.GetAmount()) >= 0):
        return False
    book = account.get_book()
    applied = _SPLITS_THE_FILES_PAYMENTS_APPLY.get(split_guid(split))
    if applied is not None and applied[0] == 'invoice':
        found = _find_invoices_by_id(book, applied[1])
        if not found:
            stated = _POSTINGS_THE_FILE_STATES.get(applied)
            transaction = _find_transaction_by_guid(book, stated) if stated else None
            here = get_account_full_name(account)
            return _the_posting_prices(next(
                (each for each in (transaction.GetSplitList() if transaction else [])
                 if get_account_full_name(each.GetAccount()) == here), None))
        record = found[0] if len(found) == 1 else None
    else:
        raw_lot = split.GetLot()
        raw_invoice = (_gc.gncInvoiceGetInvoiceFromLot(qof_instance(raw_lot))
                       if raw_lot is not None else None)
        record = wrap_invoice_or_bill(raw_invoice) if raw_invoice else None
    if record is None or not record.IsPosted():
        return False
    posted = get_account_full_name(record.GetPostedAcc())
    return _the_posting_prices(next((each for each in record.GetPostedTxn().GetSplitList()
                                     if get_account_full_name(each.GetAccount()) == posted),
                                    None))


def _the_posting_prices(posting) -> bool:
    """Whether an invoice's posting split is a cost basis, so the invoice prices what collects it."""
    try:
        return posting is not None and establishes_cost_basis(posting)
    except Exception:
        # A stored cost that will not parse prices nothing here, as it counts
        # for nothing wherever these are added up; `--verify-costs` reports it.
        return False


def _raises_a_foreign_balance(split, account, amount: Fraction) -> bool:
    """Whether this split's direction is one that brings currency in."""
    account_type = account.GetType()
    if account_type in (ACCT_TYPE_RECEIVABLE, ACCT_TYPE_PAYABLE):
        raises_the_balance = (amount > 0 if account_type == ACCT_TYPE_RECEIVABLE
                              else amount < 0)
        if not raises_the_balance:
            # The other side of a business account is currency held only when
            # it is a prepayment — a customer's overpayment, or one made to a
            # vendor — which sits in a lot of its own with no invoice or bill
            # against it. The same shape is otherwise a settlement: money that has
            # gone, which would open a cost basis for currency the book no longer
            # has.
            #
            # And only when nothing else in the transaction already brought
            # that currency in. A prepayment paid into a foreign bank writes
            # two splits for one lump of money: the bank holds it, and this
            # credit says it is owed back. Counting both listed 100.00 USD
            # twice and offered 200.00 for sale from a bank holding 100.
            return _is_prepayment(split) and not _currency_arrived_elsewhere(split)
        # The normal direction — what a customer owes on a receivable, what is
        # owed to a vendor on a payable — but not everything shaped like it.
        # A refund is a debit on a receivable too, and it sends the customer's
        # money back rather than bringing any in. The lot separates them: a
        # posting sits in the lot its own invoice owns, while a refund
        # settles an owner lot no invoice owns, exactly as on the opposite
        # side. Returning True for the shape alone offered a third 100.00 USD
        # for a prepayment that had already been refunded.
        return not _is_prepayment(split)
    if account_type in _CREDIT_TYPES:
        return amount < 0
    if account_type in _DEBIT_TYPES:
        return amount > 0
    return False


def _currency_arrived_elsewhere(split) -> bool:
    """Whether another split in this transaction already brings this currency
    in, at a cost of its own.

    Asked only of a business account moved against its normal direction, where
    the split records an obligation rather than a holding: a customer's
    overpayment paid into a USD bank is one lump of money written twice, and
    the account that took it is where it can be sold from. Where the money
    arrives converted, or in the record's own currency — a USD invoice overpaid
    from a USD bank, whose splits carry no base-currency figure and so no cost
    — nothing else brings it in, and this credit carries the cost basis.

    Business accounts are not consulted: the settling split beside an
    overpayment is on the same receivable, and is the invoice's money, not a
    second arrival. That also keeps this from asking about a split whose own
    answer would ask back.
    """
    # A split in a book is always in a transaction. Not every split in that
    # transaction has an account: committing a multi-currency transaction on a
    # book using trading accounts makes trading splits, and on GnuCash 4.8 one
    # of them is in the split list before its account is attached. Such a split
    # is screened out below by its commodity — `split_commodity` answers the
    # empty string for it, which matches no real commodity — so nothing here
    # asks it for an account.
    transaction = split.GetParent()
    commodity = split_commodity(split)
    this_one = split_guid(split)
    for other in transaction.GetSplitList():
        if split_guid(other) == this_one:
            continue
        if split_commodity(other) != commodity:
            continue
        account = other.GetAccount()
        if account.GetType() in (ACCT_TYPE_RECEIVABLE, ACCT_TYPE_PAYABLE):
            continue
        # Which direction counts as an arrival is the account type's business,
        # and `establishes_cost_basis` already answers it: a positive amount
        # on a bank, a negative one on a credit line, whose balance rises as
        # it goes down. Filtering on the sign here first meant currency drawn
        # on a USD credit line was never seen to arrive, so a vendor
        # prepayment funded by it opened a second cost basis for the same lump.
        if establishes_cost_basis(other):
            return True
    return False


def _is_prepayment(split) -> bool:
    """Whether this split sits in a lot no invoice or bill owns.

    That is what tells a prepayment from a settlement: both move a business
    account against its normal direction, but a settlement belongs to the
    record it settles, and a prepayment belongs to nothing yet.

    Except where an unpost is what took that record away. That leaves a live
    lot naming nothing — the same three facts a prepayment has — and
    reading it as one had the FX layer offer an orphaned settlement as currency
    the book holds, listed as a cost basis at the rate of the day it settled, while
    every settlement path refused to call the same split a credit. Measured on
    a USD receivable paid out of a CAD bank: after `unpost-invoices` the orphan
    appeared as a 100.00 USD cost basis at 1.37, currency that had gone out rather
    than come in.

    Imported here rather than at the top: `gnucash_importer` reads this module
    for the cost-basis keys, so the other direction has to stay lazy.
    """
    from services.gnucash_importer import is_a_bank_paid_orphan
    if is_a_bank_paid_orphan(split):
        return False
    raw_lot = split.GetLot()
    if raw_lot is None:
        return False
    # Not wrapped in a catch-all: if the binding rejects this pointer on some
    # platform, that must surface. Swallowing it would turn every prepayment
    # into "not a cost basis" and under-report held currency with no error at all.
    return not _gc.gncInvoiceGetInvoiceFromLot(qof_instance(raw_lot))


def cost_basis_balance_of(split) -> Optional[Fraction]:
    """What this cost basis has left, or None when no balance is recorded.

    The KVP is the record of it: a cost basis opens with everything it brought in,
    each sale lowers it, and giving a sale back — deleting it — raises it
    again.

    A split carrying no KVP has no balance recorded, which is not the same as
    having nothing left. Its balance was never written by this tool — the
    split may have been created in the GnuCash GUI, or predate this feature —
    and sales may already have been measured against it that nothing wrote
    down. Reading the split's amount as its balance would re-open currency
    that is possibly long gone. Stating `cost_basis_balance:` on the split in
    an import file is how a balance is given to one.
    """
    raw = _stored_cost_basis_balance(split)
    if raw is None or raw == '':
        return None
    try:
        return Fraction(str(raw))
    except (ValueError, ZeroDivisionError):
        # A balance that cannot be read is not a balance, so this cost basis has
        # none for every purpose that needs a number — refused as a sale's
        # basis, left out of the totals. It is not the *same* as never having
        # had one, though, and `verify_cost_bases` says so through
        # `malformed_cost_basis_balance_of`.
        return None


def malformed_cost_basis_balance_of(split) -> str:
    """The text of a balance KVP that will not parse, or `''`.

    Split from `cost_basis_balance_of` because the two answer different
    questions: what the cost basis has left (nothing, since no figure reads) and
    whether something is wrong (yes, and here it is).
    """
    raw = _stored_cost_basis_balance(split)
    if raw is None or str(raw) == '':
        return ''
    try:
        Fraction(str(raw))
    except (ValueError, ZeroDivisionError):
        return str(raw)
    return ''


def stated_cost_of(split) -> Optional[Fraction]:
    """The cost written on a split, or None when it carries none.

    Written with its direction — `1.4 CAD/USD`, base currency over the split's
    own — and refused without it. A bare `1.4` reads either way round, and the
    two readings are a factor of two apart at that rate: the same number that
    prices 100 USD at 140.00 CAD prices it at 71.43 if taken the other way. The
    listing states the direction for exactly this reason, and what a file
    states has to be as unambiguous as what it shows.
    """
    raw = get_custom_metadata(split).get(COST_BASIS_COST_KEY)
    if raw is None or str(raw).strip() == '':
        return None
    return parse_stated_cost(raw, split_commodity(split),
                             f'split {split_guid(split)}')


def parse_stated_cost(raw, currency: str, where: str) -> Fraction:
    """A stated cost, checked the one way.

    Both the file being read and the file being written go through here: an
    update is checked before anything is committed, and the same text is read
    back afterwards, where a refusal could no longer undo the edit. A second,
    looser check in front of this one let three of its four refusals through —
    a wrong direction, a non-number, a negative — and each landed a
    half-committed transaction.
    """
    text = str(raw).strip()
    parts = text.split()
    expected = f'{BASE_CURRENCY}/{currency}'
    if len(parts) != 2:
        raise Exception(
            f'{COST_BASIS_COST_KEY} on {where} reads '
            f'{text!r} — state which way round it goes, as in '
            f'`{COST_BASIS_COST_KEY}: "1.4 {expected}"`')
    figure, direction = parts
    if direction != expected:
        raise Exception(
            f'{COST_BASIS_COST_KEY} on {where} is stated in '
            f'{direction}, but that split holds {currency} and the book counts '
            f'in {BASE_CURRENCY} — state it as {expected}')
    try:
        cost = Fraction(figure)
    except (ValueError, ZeroDivisionError) as exc:
        raise Exception(
            f'{COST_BASIS_COST_KEY} on {where} is not a '
            f'number: {figure!r}') from exc
    if cost <= 0:
        raise Exception(
            f'{COST_BASIS_COST_KEY} on {where} must be '
            f'positive, got {figure}')
    return cost


def smallest_unit(split) -> int:
    """How finely the split's own currency divides: 100 for CAD, 1 for JPY.

    GnuCash keeps this on the commodity, which is the only place it can be
    read from — a yen has no hundredths, so an amount written 103.00 is not a
    yen amount at all.
    """
    account = split.GetAccount()
    commodity = account.GetCommodity() if account is not None else None
    return commodity.get_fraction() if commodity is not None else 1


def _format(value: Fraction, unit: int) -> str:
    """An amount as text at its own currency's decimals — 60.00 CAD, 103 JPY.

    Exact throughout: the figure reaches its currency's smallest unit through
    GnuCash's own conversion, and an amount that unit cannot express is written
    as the fraction it is rather than quietly rounded to something the currency
    can hold.
    """
    if not is_power_of_ten(unit) or (value * unit).denominator != 1:
        return str(value)
    return money_text(value, unit)




#: Each cost basis balance this import run has written, as the book held it
#: before the run first wrote it (`balance_the_run_found`).
_balances_the_run_found: Dict[str, object] = {}


def balance_the_run_found(split):
    """This split's `cost_basis_balance` text as the book held it when the import run started.

    What a block restating the balance is compared with. An export writes
    every balance, and a block below one that drew on the cost basis
    restates the balance from before that draw: compared with the balance
    the draw had just left, it read as a figure the file changed, and was
    written back over the draw (Q-051).
    """
    guid = split_guid(split)
    if guid in _balances_the_run_found:
        return _balances_the_run_found[guid]
    return get_custom_metadata(split).get(COST_BASIS_BALANCE_KEY)


def note_the_balance_the_run_found(split) -> None:
    """Record this split's balance as the book holds it, unless the run has already.

    Asked by every write of a balance, and by every clearing of one: cleared
    first and written after, the balance the run found read as none.
    """
    _balances_the_run_found.setdefault(
        split_guid(split), get_custom_metadata(split).get(COST_BASIS_BALANCE_KEY))


def write_cost_basis_balance(split, available: Fraction) -> None:
    """Record a split's cost basis balance in its KVP, keeping its other keys.

    Nothing, in a book that keeps no cost bases (Q-049).
    """
    if not book_keeps_cost_bases(split.GetBook()):
        return
    note_the_balance_the_run_found(split)
    metadata = dict(get_custom_metadata(split))
    metadata[COST_BASIS_BALANCE_KEY] = _format(available, smallest_unit(split))
    transaction = split.GetParent()
    reopen = transaction is not None and not transaction.IsOpen()
    if reopen:
        transaction.BeginEdit()
    set_custom_metadata(split, metadata)
    if reopen:
        transaction.CommitEdit()


# Guids of cost bases whose cost basis balance the file being imported stated
# outright. Such a balance is authoritative and already net of every sale in
# that file — an export carries `cost_basis_balance: "60.00"` on a cost basis
# alongside the 40 USD sale that lowered it, and applying the sale again would
# leave 20. Reset at the start of each import.
_stated_in_file = set()


#: Whether `import --atomic` was passed for this run. Set at the start of each
#: import, and read by the cost-basis checks that run block by block.
_running_atomic = False

#: Whether that run has reached the edits no order of its blocks can apply,
#: which it applies in place (`defer_edits_in_place`).
_deferring_edits_in_place = False


def begin_import_run(atomic: bool = False) -> None:
    """Forget which balances the previous file stated, and whether this one is
    being applied with `--atomic`.

    And the changes of `cost_basis_split_guid` logged so far, so the log does
    not grow for as long as the process runs: `splits_drawing_on` walks the
    book once more instead. And the balances the previous run found, which
    `balance_the_run_found` answers for this one afresh.
    """
    global _running_atomic, _deferring_edits_in_place
    _stated_in_file.clear()
    _balances_the_run_found.clear()
    _running_atomic = atomic
    _deferring_edits_in_place = False
    forget_custom_key_changes()


def running_atomic() -> bool:
    """Whether this import was given `--atomic`, so the book is checked once the whole file is applied (Q-053)."""
    return _running_atomic


def defer_edits_in_place() -> None:
    """Let an `--atomic` run apply in place the edits no order of the file's blocks can apply.

    Called by `cli/import_cmd.py` once applying the refused blocks again has
    stopped applying anything (Q-053).
    """
    global _deferring_edits_in_place
    _deferring_edits_in_place = _running_atomic


def deferring_edits_in_place() -> bool:
    """Whether an edit moving a cost basis another transaction draws on is applied in place, and its checks asked of the finished book.

    Those checks exist because the rules governing a disposal read splits once
    they are book state, and an edit made in place has already overwritten what
    the old figures drew before anything can re-check them. That holds for a
    file applied one block at a time and kept in part, which is every ordinary
    import.

    Under `--atomic` the file commits or it rolls back, and `cli/import_cmd.py`
    reads the finished book before saving anything. Most blocks refused block
    by block are refused only because of where they sit in the file, and are
    applied once the rest of the file is in the book, through every check. What
    is left is a repair no order can make: two edits each refused while the
    other still reads as it was. Only those are applied in place, and asked at
    the end instead. Applied in place first, an edit kept a cost basis its new
    version does not establish, which the rest of the file then left behind.
    """
    return _deferring_edits_in_place


def note_stated_balance(split) -> None:
    """This cost basis arrived with its balance already written in the file."""
    _stated_in_file.add(split_guid(split))


def forget_stated_balance(split) -> None:
    """The file's statement of this balance did not stand: its edit was refused and put back (Q-051)."""
    _stated_in_file.discard(split_guid(split))


def balance_came_from_file(split) -> bool:
    return split_guid(split) in _stated_in_file


def open_cost_basis_balance(split) -> Fraction:
    """Open a cost basis: none of what it brought in has been charged against
    yet, so all of it is still there to measure a disposal against."""
    opening = brought_in_by(split)
    write_cost_basis_balance(split, opening)
    return opening


def total_cost_basis_balance_in(account) -> Fraction:
    """What the book still offers for sale out of one account.

    The sum across that account's cost bases of what each has left. A cost basis
    with no balance recorded counts for nothing: its balance was never
    written, so there is no number to add — which is what a `None` from
    `cost_basis_balance_of` means, and the same answer `fx-balances` gives by
    leaving those out of its totals.

    That leaves a hole, and it is the same one the module docstring records
    for a bank fee: an account whose cost bases were all made in the GnuCash GUI
    offers nothing here, so a payment block spending it is not refused. What
    the guard catches is an account this tool has been keeping the balances
    of, which is every account it wrote.

    Asked before a settlement spends foreign cash, to tell an account whose
    bases still have something left (where the disposal has to be measured
    against a named cost basis) from one whose cost bases are spent.

    Reads the account's own splits rather than walking the book. Every other
    caller of `iter_splits` is a one-shot command; this one is asked once per
    payment block with a foreign bank, and `GetSplitList()` builds a fresh
    wrapper for every split it returns — so walking the tree here would cost
    the whole book once per payment to answer a question about one account.

    Not memoised, though it is asked once per payment block and the answer
    rarely changes between two of them: importing *n* payments against an
    account of *m* splits costs n·m KVP reads. Deliberately, because the
    answer does change — a settlement into a foreign bank opens a cost basis and a
    disposal lowers one — and while every *write* goes through
    `write_cost_basis_balance`, a removal does not: `_strip_a_settlements_
    basis` and the applied-credit paths replace a split's whole slot frame. A
    memo would need clearing at each of those, and the one that was missed
    would refuse a payment the book can afford or allow one it cannot. That is
    a bad trade against a walk of one account, and there is no measurement
    saying the walk hurts.
    """
    total = Fraction(0)
    # No currency argument and no per-split commodity test: every split here
    # is on `account`, so every one is denominated in that account's own
    # commodity. The test was the same answer each time round, and never the
    # skipping one.
    for split in account.GetSplitList():
        try:
            if not establishes_cost_basis(split):
                continue
            balance = cost_basis_balance_of(split)
        except Exception:
            # A cost basis this cannot read is not a figure anyone can measure
            # against, and `fx-balances` already lists it as malformed.
            # Adding it here would refuse a settlement over a number nothing
            # can state, with no way for the reader to get out of it.
            continue
        if balance is not None:
            total += balance
    return total


def _drawn_down_after(book, as_of) -> dict:
    """Per cost basis guid, how much every disposal after `as_of` took from it.

    A `cost_basis_balance` says what a cost basis has left **now**, not what it
    had left on some earlier date, and a balance sheet drawn at an earlier date
    needs the second. What a disposal took is its own amount, and when it took
    it is its transaction's date, so the balance as of a date is what the KVP
    says plus everything drawn from it since.

    Gathered in one pass and keyed by guid. Asked per cost basis it would walk
    every split in the book once per basis, which is the same answer at the cost
    of squaring the work.
    """
    drawn: dict = {}
    for split in iter_splits(book):
        guid = cost_basis_guid_of(split)
        if not guid:
            continue
        when = split.GetParent().GetDate().date()
        if when <= as_of:
            continue
        drawn[guid] = drawn.get(guid, Fraction(0)) + draws_down(split)
    return drawn


def cost_basis_items_by_currency_and_side(book, as_of) -> List[Dict]:
    """Every cost basis the book holds as a row of its own, pruned to `as_of`.

    One row per basis, never a total: three arrivals at 1.30, 1.35 and 1.40 are
    three rows, and two bases at the same rate stay two — a matching cost merges
    nothing. The balance sheet prints one figure per currency and side, and adds
    these up to reach it; a page that also lists what that figure is made of
    needs the rows, and a row can be tied back to a basis the book holds where a
    sum cannot.

    **Adding these up merges no cost bases either.** Two incomes of 1,000.00 USD
    at 1.30 are two cost bases, with two balances and two guids: `fx-balances`
    lists each, and a disposal draws on the one whose guid it gives. Nothing here
    averages a cost or pools one basis into another — a disposal is measured
    against the basis it picks, which is what decides the gain it realizes.

    `as_of` reads the cost bases as they stood at the end of that date rather
    than as they stand now: a basis opened later is not counted at all, and one
    drawn down later gets that back. Without it a sheet drawn at an earlier date
    measures the currency it held then against costs it did not yet have.
    Measured on a book that bought 1,000.00 USD at 1.30 in January, sold it all
    on 1 August and bought 1,000.00 more at 1.50: a 30 June sheet priced at 1.35
    stated a loss of 150.00, against the 50.00 gain those January dollars
    actually stood at, because the quantities matched while the costs did not —
    so nothing refused it and the page showed its working for a cost basis the
    book had not yet opened.

    A date is required. Every page that reads the cost bases is drawn at one, so
    reading them as they stand now is an answer nothing asks for.

    **A currency with no rows here is one the cost bases say nothing about**, and
    a balance sheet must leave it to GnuCash — no rows is not a cost of zero,
    which is the distinction that reported a bank's whole balance as a gain when
    the book happened to keep no basis for it. A basis spent to nothing
    contributes nothing: once the money is gone its gain or loss is realized and
    sits in an income account, and counting it here as well would state the same
    money twice.

    This is what a balance sheet needs and what GnuCash cannot work out. GnuCash
    reconstructs cost from the sum of an account's split *values*, which is the
    cost only where every split was valued in the book's own currency — and a
    foreign inflow recorded in its own currency, as an invoice collected into a
    foreign bank is, carries no such value. Its reconstruction then misses by
    whatever the report-date price differs from the real one, in either
    direction: on a book still holding the money it omits the gain and leaves the
    sheet unbalanced, and on a book that has spent it, it states the realized
    gain over again as an unrealized one.

    Grouping by currency and side belongs to the reader of these rows: US dollars
    and Hong Kong dollars are separate holdings priced separately, a balance
    sheet states a gain for each side, and a book that holds a currency and owes
    it at once matches neither side's holdings if the two are put together — a
    cost basis balance is checked against what the book holds, and checking a
    loan's balance against a bank's as well answers for a figure neither of them
    has. Each row carries both, so the grouping is done from the rows rather than
    before them.

    **The side is the sign of what the basis brought in, not the type of the
    account holding it**, and that is measured rather than assumed. Currency
    arriving on a debit — a bank, a receivable's posting — is held, and currency
    on a credit — a loan drawn, a payable's posting — is owed. Classifying by
    account type instead, so that a receivable goes with the assets the way
    `gnc:decompose-accountlist` groups it, puts an overpaid invoice's two bases
    on one side: the posting's +100.00 USD and the overpayment's −100.00 net to
    nothing, that nothing matches no holding, so both sides fall back to
    GnuCash's revaluation and the gain vanishes. On
    `fx_invoice_usd_overpaid_into_usd_bank.txt` it turned
    `unrealized_gains_assets_fx: -3.00` and a page that balanced into 0.00, with
    137.00 of assets against 140.00 of liabilities and equity. The sign keeps the
    two bases apart, which is what lets each be checked against the holdings it
    can actually account for.

    The balance and cost here stay positive and the side is a field, so whatever
    adds these up applies the owed side's sign itself.

    A basis whose balance or cost cannot be read counts for nothing, as it does
    in `total_cost_basis_balance_in` and in what `fx-balances` totals.
    """

    rows: List[Dict] = []
    drawn_since = _drawn_down_after(book, as_of)
    disposals = _disposals_by_cost_basis(book, as_of)
    for split in iter_splits(book):
        try:
            if not establishes_cost_basis(split):
                continue
            # A cost basis the book had not opened yet says nothing about what
            # it held then. Counted anyway, an August purchase priced the
            # dollars a June sheet was holding.
            if split.GetParent().GetDate().date() > as_of:
                continue
            balance = cost_basis_balance_of(split)
            if balance is None:
                continue
            # What it had left then: what it has left now, plus whatever was
            # taken from it since.
            balance += drawn_since.get(split_guid(split), Fraction(0))
            cost = cost_of(split)
            amount = _fraction(split.GetAmount())
            currency = split_commodity(split)
            in_pair, rate, pair_currency = what_a_unit_cost_in_its_pair(split, cost)
        except Exception:
            # A cost that will not parse raises rather than reading as nothing,
            # and `establishes_cost_basis` is where it is read — so a book
            # carrying `cost_basis_cost: "oops"`, as one edited elsewhere can,
            # arrives here. That basis counts for nothing, as it does in what
            # `fx-balances` totals, rather than taking the whole page down.
            continue
        # Outside that: its disposals are read with a cost that parsed, and
        # one that raised there would drop the cost basis from the page with
        # nothing to say so, where every other figure of it is sound.
        drawing = disposals.get(split_guid(split), [])
        # Only where every disposal is valued as the import requires —
            # its own share rounded, or what is left for the last — is the
            # difference a realized gain not recorded: the values' rounding.
        # Otherwise it is a disposal valued against another cost, or a cost
        # stated wrong, which `--verify-costs` reports; stated here, the whole
        # of it would read as a gain and balance a page that should not
        # balance. So the cost held is then what the currency still held
        # cost, and no gain is stated. The question is asked of the book as
        # it stands, not as of the sheet's date, and the answer is the same: a
        # disposal valued at what is left took the balance to zero, so it is
        # the last there will ever be, and a later one cannot change whether
        # it stands.
        held = balance * cost + (
            what_the_disposals_left_unrecorded(split, drawing)
            if not any(a_sale_valued_against_another_cost(
                each, split, split_guid(split), in_the_book=True)
                for each in drawing)
            else Fraction(0))
        # Neither `cost` nor `currency` is asked about again: a split gets past
        # `establishes_cost_basis` only when it has a commodity and a cost that
        # reads, since that function ends by returning `cost_of(split) is not
        # None`. Asking twice reads as though one of them could still be
        # missing here, and nothing could reach it.
        rows.append({
            'guid': split_guid(split),
            'account': get_account_full_name(split.GetAccount()),
            'currency': currency,
            # The namespace beside the mnemonic, because the two together are
            # what finds a commodity in GnuCash's table and a mnemonic alone
            # is not: a page looking `USCO` up under `CURRENCY` finds nothing
            # and leaves every security to GnuCash's revaluation.
            'namespace': split.GetAccount().GetCommodity().get_namespace(),
            'side': 'asset' if amount > 0 else 'liability',
            'unit': smallest_unit(split),
            'balance': balance,
            'cost': cost,
            # What the trade happened at, and the rate that turns it into the
            # book's currency. `cost` is the two multiplied out, and it is the
            # figure every gain is measured against; these two are what a reader
            # checks it by (Q-046).
            'cost_in_pair': in_pair,
            'cost_rate': rate,
            'pair_currency': pair_currency,
            # What the book still holds of its cost: what it cost less what
            # its disposals were valued at. `balance × cost` is what the
            # currency still held cost, and the two differ where the
            # disposals' values, each rounded to the cent, add up to more or
            # less than what they drew cost: that difference is a realized
            # gain the book did not record.
            'cost_held': held,
        })
    # The disposals pending their cost basis, one row per currency and side,
    # negative. Each drew on no cost basis, so the rows above still hold what
    # they took; this row takes it off, at what their transactions recorded,
    # so what a currency and side add up to is what the accounts hold, and no
    # gain is stated for a disposal whose cost is not decided yet.
    pending: Dict[tuple, List[Dict]] = {}
    for row in pending_disposals(book):
        if row['when'] <= as_of:
            pending.setdefault((row['currency'], row['side']), []).append(row)
    for (currency, side), taken in sorted(pending.items()):
        amount = sum((row['amount'] for row in taken), Fraction(0))
        recorded = sum((row['recorded_at'] for row in taken), Fraction(0))
        cost = recorded / amount
        rows.append({'guid': PENDING, 'account': 'pending their cost basis',
                     'currency': currency, 'namespace': taken[0]['namespace'],
                     'side': side, 'unit': taken[0]['unit'], 'balance': -amount,
                     'cost': cost, 'cost_in_pair': Fraction(1), 'cost_rate': cost,
                     'pair_currency': currency, 'cost_held': -recorded})
    return rows


def _disposals_by_cost_basis(book, as_of) -> dict:
    """Per cost basis guid, every disposal dated on or before `as_of` that draws on it."""
    found: dict = {}
    for split in iter_splits(book):
        guid = cost_basis_guid_of(split)
        if guid and split.GetParent().GetDate().date() <= as_of:
            found.setdefault(guid, []).append(split)
    return found


def what_a_unit_cost_in_its_pair(split, cost: Fraction):
    """What one unit cost in the transaction's own currency, and that day's rate.

    Three things: the price per unit as the transaction states it, the rate from
    the transaction's currency into the book's, and the mnemonic of the currency
    the price is in. Multiplied out they are `cost`, which is what a gain is
    measured against.

    **The pair price is the fact and the book-currency cost is derived from it.**
    A share bought at 99.00 USD on a day the dollar stood at 1.30 cost 128.70,
    and a reader cannot check the 128.70 without the two figures it is made of.
    Where the transaction is stated in the book's own currency there is no
    second rate: the price is already in it, so the rate is 1 and the two
    figures are the same number, which is why a currency bought with the book's
    own money has never needed this told apart.

    A split with no value to divide — GnuCash writes one on a cross-currency
    posting — states no price of its own, so the cost stands as both and the
    rate is 1.
    """
    amount = abs(_fraction(split.GetAmount()))
    value = abs(_fraction(split.GetValue()))
    pair_currency = transaction_currency(split.GetParent())
    if amount == 0 or value == 0:
        return cost, Fraction(1), BASE_CURRENCY
    in_pair = value / amount
    return in_pair, cost / in_pair, pair_currency


def lower_cost_basis_balance(split, amount: Fraction) -> Fraction:
    """Charge `amount` against a cost basis and record what is left.

    Both callers refuse a cost basis with no balance recorded before they
    charge it, so there is always a balance here to lower.
    """
    current = cost_basis_balance_of(split)
    remaining = current - amount
    write_cost_basis_balance(split, remaining)
    return remaining


def raise_cost_basis_balance(split, amount: Fraction) -> Fraction:
    """Give `amount` back to a cost basis — a sale measured against it is gone.

    Capped at what the cost basis brought in, so it can never come to hold more
    than the currency the split actually carried.
    """
    if open_cost_basis_balance_if_none_is_stored(split) is not None:
        return cost_basis_balance_of(split) or Fraction(0)
    current = cost_basis_balance_of(split)
    if current is None:
        # A figure is stored and will not parse. Opening the cost basis at its full
        # amount would re-open currency that may have been sold and destroy
        # the text `--verify-costs` exists to report — the same reading
        # `_carry_basis_to_residue` refuses. Leave it as it is; the fault is
        # reported, and correcting the figure is what unblocks it.
        return Fraction(0)
    restored = min(current + amount, brought_in_by(split))
    write_cost_basis_balance(split, restored)
    return restored


def _stored_cost_basis_balance(split):
    """The `cost_basis_balance` text as the split holds it, or None.

    An empty string answers None: a file states `cost_basis_balance: ""` to
    take a balance off, and a split that has had one taken off has none.
    """
    raw = get_custom_metadata(split).get(COST_BASIS_BALANCE_KEY)
    return None if raw in (None, '') else raw


def has_cost_basis_balance(split) -> bool:
    """Whether this split has a `cost_basis_balance` written on it at all,
    whatever that figure says.

    Distinct from what the cost basis has left, which is
    `cost_basis_balance_of`. This asks whether the book holds a figure; the
    callers that need it are the ones deciding whether to write one.
    """
    raw = _stored_cost_basis_balance(split)
    return raw is not None and raw != ''


def open_cost_basis_balance_if_none_is_stored(split):
    """Open this cost basis's balance, unless the book already records one.

    The one place that decision is made. Four callers needed it — opening a
    transaction's cost bases, opening a borrowed one, opening what an edit turned
    into a cost basis, and giving a sale back — and each asked it themselves, which
    is how three of them came to ask it the new way and the fourth kept the
    old one. Asked in four places it can be answered three ways; asked here it
    cannot.

    Never a second time, and that is the whole point: a cost basis already carrying
    a figure has had disposals charged against it, and opening it again would
    put that currency back. A figure that will not parse counts as stored —
    something wrote it, and overwriting it would destroy what `--verify-costs`
    reports.

    Returns the opening balance when it opened one, or None when it left a
    stored figure alone.
    """
    if has_cost_basis_balance(split):
        return None
    return open_cost_basis_balance(split)


def record_cost_bases(book, transaction) -> None:
    """Open every cost basis this transaction establishes, for what arrived.

    Nothing has been charged against it yet, so what it brought in is still
    there — less what the same transaction took back out without giving a
    cost basis, which only moved: 1,200.00 USD sent out of an account holding
    1,000.00 into another opens a cost basis for the 200.00 borrowed, not the
    1,200.00 that arrived (Q-047). A split taking units back out that gives a
    cost basis is a disposal drawing on it, and is left to it — a fee drawing
    on the dollars its own transaction brings in gives the arrival's position
    (Q-050), and a spend giving none is refused before this is reached.

    What was taken back comes off the arriving splits in turn, each giving up
    what it can.
    """
    still_to_take: Dict[tuple, Fraction] = {}
    for split in transaction.GetSplitList():
        if not establishes_cost_basis(split):
            continue
        # A balance the file stated is written with the split, not here, and
        # is a cost basis the book did not keep a moment ago all the same.
        cost_bases_changed()
        opened = open_cost_basis_balance_if_none_is_stored(split)
        if opened is None:
            continue
        at, taken_back = _what_the_transaction_took_back(transaction, split)
        if at not in still_to_take:
            still_to_take[at] = taken_back()
        taken = min(opened, still_to_take[at])
        if taken:
            write_cost_basis_balance(split, opened - taken)
            still_to_take[at] -= taken


def what_a_new_import_would_open(transaction) -> Dict[str, Fraction]:
    """What each cost basis this transaction establishes would open at, were it imported new.

    The figures `open_the_cost_bases_its_own_splits_draw_on` and
    `record_cost_bases` write on a book holding no balance for any of them:
    everything brought in where another of its splits draws on the cost
    basis, and otherwise less what the transaction took back out. Written
    nowhere. An edit reads it of the old version, so the part of a stored
    balance these figures do not explain, which a file stated, is kept when
    the new version opens its cost bases (Q-051).
    """
    drawn_on = {cost_basis_guid_of(split) for split in transaction.GetSplitList()}
    opened: Dict[str, Fraction] = {}
    still_to_take: Dict[tuple, Fraction] = {}
    for split in transaction.GetSplitList():
        if not establishes_cost_basis(split):
            continue
        brought = brought_in_by(split)
        if split_guid(split) in drawn_on:
            opened[split_guid(split)] = brought
            continue
        at, taken_back = _what_the_transaction_took_back(transaction, split)
        if at not in still_to_take:
            still_to_take[at] = taken_back()
        taken = min(brought, still_to_take[at])
        still_to_take[at] -= taken
        opened[split_guid(split)] = brought - taken
    return opened


def open_the_cost_bases_its_own_splits_draw_on(transaction) -> None:
    """Open, first, each cost basis this transaction opens that another of its splits draws on.

    A fee drawing on the dollars its own transaction brings in is checked
    against that cost basis's balance, and the balance is written when the
    transaction's cost bases are opened, which is after the draws. So the
    fee found no balance and was refused as though the arrival were a split
    the import had not written (Q-050). What such an arrival brings in is all
    it moved: the splits drawing on it are spends, and `record_cost_bases`
    does not take them back off it.
    """
    drawn_on = {cost_basis_guid_of(split) for split in transaction.GetSplitList()}
    for split in transaction.GetSplitList():
        if split_guid(split) in drawn_on and establishes_cost_basis(split):
            cost_bases_changed()
            open_cost_basis_balance_if_none_is_stored(split)


def _what_the_transaction_took_back(transaction, split):
    """Where what an arriving split opens is reduced from, and by how much.

    A key shared by every arriving split that draws on the same figure, and a
    function working the figure out, so it is worked out once per key.

    On a receivable or a payable, what the same account took back out. Anywhere
    else, what left the side the split arrives on, from any account, and not
    by a disposal giving a guid: that much of what arrived only moved. 1,200.00
    USD out of an account holding 1,000.00 and into another is 1,000.00 moved
    and 200.00 borrowed, so the account it went into opens a cost basis for
    200.00 (Q-047).

    Across accounts this is reached only by that borrowing:
    `refuse_a_transfer_sharing_a_transaction` turns away every other
    transaction in which one account on a side rises while another falls and a
    cost basis is touched, so a purchase into one account beside a move out of
    another never gets here.
    """
    arriving = _fraction(split.GetAmount())
    if split_moves(split) is None:
        account = get_account_full_name(split.GetAccount())
        return (account,), lambda: sum(
            (abs(_fraction(other.GetAmount()))
             for other in transaction.GetSplitList()
             if get_account_full_name(other.GetAccount()) == account
             and _fraction(other.GetAmount()) * arriving < 0
             and not cost_basis_guid_of(other)),
            Fraction(0))
    commodity = split_commodity(split)
    side = 0 if arriving > 0 else 1
    return (commodity, side), lambda: sum(
        (max(-moves[side], Fraction(0))
         for other in transaction.GetSplitList()
         if split_commodity(other) == commodity and not cost_basis_guid_of(other)
         for moves in [split_moves(other)] if moves is not None),
        Fraction(0))


def carry_the_cost_to_what_it_bought(book, transaction) -> None:
    """Give what the spent currency cost to the holding it bought.

    Twenty shares bought for 4,000.00 US dollars that cost 1.30 cost the book
    5,200.00 CAD, whatever the transaction is written in. That figure is not in
    the transaction where the transaction is written wholly in US dollars — the
    splits then say 4,000.00 and nothing else — and it is not a price to be
    looked up either. It is the cost the currency's own cost basis gives up as
    it is drawn down, so it travels out of that cost basis and onto the shares,
    and `cost_basis_cost` on the security split is where it lands.

    Without it the shares are valued from their US dollar figure, converted at
    whatever rate the sheet is drawn at, which puts the day's rate on the cost
    as well as on the worth and so cancels the currency out of the gain. On 20
    AMZN bought at 200.00 USD when the dollar stood at 1.30 and held to a sheet
    priced at 1.42, that is 5,680.00 of cost where 5,200.00 was paid, and a
    balance sheet 480.00 short of balancing.

    What the currency gave up is read from the splits that spent it, each giving
    the guid of the cost basis it came out of — not from what
    `apply_cost_basis_picks` lowered. A cost basis whose balance the file states
    is not lowered, because the stated figure is already net of this purchase,
    and the dollars still left it at what they cost. Every export states that
    balance, so a book exported and imported again held its shares at no cost
    when the carrying read only what was lowered. This runs after
    `apply_cost_basis_picks`, which has checked every guid given, and before
    `record_cost_bases` opens the balance on what it writes.

    **The total is divided by value**, so a fee sharing the purchase takes its
    own share of it. A broker charging 1.00 USD on a 991.00 USD purchase of
    shares leaves 990.00 USD for the shares, and of the 1,288.30 CAD those
    dollars cost that is 1,287.00 on the shares and 1.30 on the fee. Handing
    the whole 1,288.30 to the shares would price them at 128.83 where they
    cost 128.70, and would put the broker's charge inside the holding. Each
    split's value over the value of what paid is its share, in whatever
    currency the transaction is stated in — a purchase stated in Hong Kong
    dollars divides the same 2,600.00 CAD by its Hong Kong dollar figures.

    Nothing is written where the transaction already states a figure in the
    book's own currency for the holding: that figure is the ledger, and a cost
    written beside it would be a copy that can drift from it.
    """
    arriving = [split for split in transaction.GetSplitList()
                if _is_a_holding_arriving_uncosted(split)]
    # What paid is what left a held cost basis. A debt a transaction pays off
    # draws its own cost basis down too, and it bought nothing.
    paying = [split for split in transaction.GetSplitList()
              if cost_basis_guid_of(split) and the_side_it_draws(split) == 'asset']
    if not arriving or not paying:
        return
    # `apply_cost_basis_picks` found and checked every guid given before it
    # lowered the first balance — the stated ones as well, which it then leaves
    # alone — so each guid matches a split and each split has a cost. A figure
    # missing here would be that check having let something through, which is
    # worth the raise it would get rather than a holding quietly left uncosted.
    given_up = sum(draws_down(split)
                   * cost_of(find_split_by_guid(book, cost_basis_guid_of(split)))
                   for split in paying)
    # Divided by value, in whatever currency the transaction is stated in: a
    # split's value is its share of what was paid, and that holds whether the
    # transaction is stated in the currency spent or in a third one. Units
    # would not do — two currencies spent at once add up to nothing, and a
    # purchase stated in Hong Kong dollars would count its values as US ones.
    paid = sum(abs(_fraction(split.GetValue())) for split in paying)
    if not paid:
        raise Exception(
            'the currency that paid for what this transaction buys is valued at '
            'nothing in it, so nothing says how what that currency cost divides '
            'across what it bought. State each split at what it is worth.')
    for split in arriving:
        share = abs(_fraction(split.GetValue())) / paid
        write_cost_basis_cost(split, given_up * share / abs(_fraction(split.GetAmount())))


def _is_a_holding_arriving_uncosted(split) -> bool:
    """A split bringing in units the transaction gives no book-currency figure for.

    A security rather than a currency: currency that arrives states its cost in
    the transaction or has none, and `establishes_cost_basis` already answers
    for it. What this finds is the share side of a purchase written wholly in
    the currency it was paid in.
    """
    # The account is there to read. The one split known to lack one is the
    # trading split GnuCash 4.8 lists before attaching its account (CLAUDE.md
    # finding 12), and it is met by `record_cost_bases`, not here: a US dollar
    # purchase funded from a Canadian bank in a book with trading accounts
    # reaches this on every build and never hands it such a split.
    if is_a_currency(split.GetAccount().GetCommodity()):
        return False
    if _fraction(split.GetAmount()) <= 0:
        return False
    return derived_cost_of(split) is None and stated_cost_of(split) is None


def the_bases_a_transaction_has(transaction) -> set:
    """The guids of the splits that are cost bases as the transaction stands.

    Read before a transaction is edited, and handed back afterwards to
    `open_what_an_edit_made_a_basis`.
    """
    return {split_guid(split) for split in transaction.GetSplitList()
            if establishes_cost_basis(split)}


def open_what_an_edit_made_a_basis(transaction, bases_before) -> None:
    """Open a balance on every split this edit turned into a cost basis.

    An edit can bring foreign currency into the book — a CAD placeholder
    corrected into `Assets:Bank:USD 100.00 USD`, a wrongly linked deposit
    restated back into the purchase it was — and that currency needs a cost basis
    like any other. Whether the transaction was created, corrected by a file
    or restated by a command does not come into it: what it is now is what
    decides, which is the same question `record_cost_bases` asks on the way
    in.

    **Only what this edit made a cost basis**, which is what `bases_before` is for.
    Not the splits that already existed: a split matched by account and
    corrected keeps its guid while becoming a cost basis it was not, and skipping
    it for having existed left that currency with no cost basis at all. And not a
    split that was already a cost basis carrying no balance — that one was made in
    the GnuCash GUI, or predates this, and how much of its currency has been
    sold is not recorded, so opening it at its full amount would offer
    currency that may be long gone. Correcting a description was enough to do
    that to every such cost basis in a book.

    That last one holds for an edit, and not across a link. A deposit reading
    `none recorded`, linked to an invoice and then unlinked, comes back
    holding all of what it brought in: the link makes the split a settlement,
    which is no cost basis, so by the time the payment comes off there is
    nothing left to tell a balance this tool removed from one that was never
    written. It is the answer the importer gives for the same transaction, and
    `test_a_basis_that_had_no_balance_comes_back_holding_all_of_it` pins it.
    Telling the two apart would mean recording what the link took, which no
    file may state and no export can carry.

    Measured on the writer that did not ask: `unapply-payment` on a deposit
    linked to the wrong invoice left the split reading `none recorded` while a
    book rebuilt from that book's own ledger read the whole 2,720.00 USD, the
    listing saying "this tool never wrote one for them" about a split this
    tool had written one for and taken it off.
    """
    cost_bases_changed()
    for split in transaction.GetSplitList():
        if split_guid(split) in bases_before:
            continue
        if establishes_cost_basis(split):
            open_cost_basis_balance_if_none_is_stored(split)


def record_borrowed_basis(split, cost: Fraction) -> None:
    """Open a cost basis for currency the book now holds and owes back, at a cost
    its own transaction cannot state.

    An overpaid invoice settled in its own currency is the case: 200.00 USD
    against a 100.00 USD invoice leaves the customer's money in the bank and a
    credit balance on the receivable, with no base-currency figure anywhere in
    that payment to price it by. The cost is the one the record was carried
    at, written on the split so it reads back like any other. Counting only
    the settling split opened a cost basis for 100.00 USD of the 200.00 the bank
    holds, and a sale of the rest was refused for exceeding a cost basis that was
    never opened.
    """
    if _fraction(split.GetAmount()) == 0:
        # A split of nothing holds no currency, so there is none owed back and
        # nothing for a later sale to be measured against. It is a book a
        # person can make rather than a shape this tool writes: GnuCash's
        # View → Lots puts a 0.00 split in a record's lot, and
        # `unapply-payment --all` takes every split the lot holds, with no
        # figure deciding which. Opening a cost basis here would record 0.00
        # units as available and then price them, dividing the base-currency
        # value by the units the split does not hold.
        return
    if has_cost_basis_balance(split):
        return
    if cost_of(split) is not None:
        # The transaction already says what it cost: a converting payment
        # values this credit at the rate it was received at. Writing a cost
        # beside it would state a second, different one — the record's — on a
        # split whose own figures contradict it.
        open_cost_basis_balance(split)
        return
    write_cost_basis_cost(split, cost)
    open_cost_basis_balance(split)


def write_cost_basis_cost(split, cost: Fraction) -> None:
    """Store `cost_basis_cost` on a split whose transaction cannot price it.

    This is the cost basis cost — CAD per unit of the split's own currency —
    and not `share_price:`, which is a figure of the transaction and is
    computed by GnuCash as value over amount. The two answer different
    questions and only this one is stored in a slot.

    Two things need this. A prepayment left by an overpayment settled in the
    record's own currency has no base-currency figure anywhere in its
    transaction to be priced by. And a payment block that links an existing
    transaction can *take* that figure away: replacing the split that held it
    leaves the rest of the transaction stated in one currency, so a cost basis that
    was priced a moment ago no longer is. Written here, the price survives the
    replacement and the cost basis goes on being one.

    The cost stored is the one the money actually came in at, not the rate it was
    quoted at — the same way `share_price` comes back as the value over the
    amount. 45.00 USD at 1.405 is 63.225 CAD, which reaches the cent as 63.23,
    so the cost is 6323/4500 (1.405 + 1/9000). Storing the quoted rate instead
    would price this cost basis at 63.225, which no CAD figure in the book equals
    — the book holds 63.23 — so the stored cost would be 1/9000 of a dollar per
    dollar lower than what those dollars actually cost. A gain is what the
    currency fetched less what it cost, so every gain measured against that cost
    would be larger than the truth by the same 1/9000 a dollar: 0.005 CAD on
    these 45.00 USD.

    Nothing, in a book that keeps no cost bases (Q-049).
    """
    if not book_keeps_cost_bases(split.GetBook()):
        return
    currency = split_commodity(split)
    # Each caller refuses a split of nothing before reaching here, and has to:
    # `record_borrowed_basis` returns early for one, and the importer's link
    # path walks only splits that were cost bases a moment earlier, which a
    # 0.00 split is not (`establishes_cost_basis`). A split holding no units
    # would divide by zero below — `unapply-payment --all` on a lot GnuCash's
    # View → Lots put a 0.00 split in reached exactly that, and is the reason
    # the first of those guards exists.
    #
    # The base currency is always in the book's table, which GnuCash fills
    # with every ISO currency when it makes a book.
    units = abs(_fraction(split.GetAmount()))
    base = split.GetAccount().get_book().get_table().lookup(
        'CURRENCY', BASE_CURRENCY)
    base_value = numeric_to_fraction(to_money(units * cost, base.get_fraction()))
    effective = base_value / units

    metadata = dict(get_custom_metadata(split))
    metadata[COST_BASIS_COST_KEY] = f'{exact_text(effective)} {BASE_CURRENCY}/{currency}'
    # Bracketed whether or not the caller already has the transaction open:
    # GnuCash counts nested edits and commits only at the outermost, and a
    # slot written outside any edit never reaches disk (CLAUDE.md finding 11).
    transaction = split.GetParent()
    transaction.BeginEdit()
    set_custom_metadata(split, metadata)
    transaction.CommitEdit()


def amounts_by_cost_basis(transaction) -> Dict[str, Fraction]:
    """How much this transaction takes from each cost basis it names.

    Read before the transaction is deleted, so the amounts can be given back
    afterwards — undoing a sale is how a user corrects one, and the balance has
    to follow it.
    """
    taken: Dict[str, Fraction] = {}
    for split in transaction.GetSplitList():
        guid = cost_basis_guid_of(split)
        if not guid:
            continue
        taken[guid] = taken.get(guid, Fraction(0)) + draws_down(split)
    return taken


def give_back_to_cost_bases(book, taken: Dict[str, Fraction]) -> Set[str]:
    """Raise each cost basis's balance by what was taken from it.

    Returns the guids whose balance actually came back, which is not always
    all of them: the cost basis split may be gone from the book, and
    `raise_cost_basis_balance` writes nothing when the stored text will not
    parse — the fault `--verify-costs` exists to report, which no give-back
    may paper over.

    A caller that records the drawdown somewhere needs to know which: the
    unapply path drops `cost_basis_split_guid` from the settlement, and
    dropping it where the balance did not come back would destroy the only
    thing saying which cost basis that settlement drew from, leaving the cost basis
    short with nothing able to say by how much.
    """
    restored: Set[str] = set()
    for guid, amount in taken.items():
        basis = find_split_by_guid(book, guid)
        if basis is None:
            continue
        raise_cost_basis_balance(basis, amount)
        # Reads back as a figure only where one was written: an unparseable
        # balance answers `None` before and after.
        if cost_basis_balance_of(basis) is not None:
            restored.add(guid)
    return restored


def find_split_by_guid(book, guid: str):
    """The split with this guid, or None.

    Looked up in the book's own table of splits, as `_find_transaction_by_guid`
    looks up a transaction. Walked instead, every pick checked and every
    draw given back walked the whole book, once each.

    Only a split on an account, as the walk of the accounts found: GnuCash
    4.8 lists a trading split before its account is attached (CLAUDE.md
    finding 12).
    """
    from gnucash import Split
    from gnucash.gnucash_core_c import GncGUID, string_to_guid, xaccSplitLookup
    wanted = GncGUID()
    if not string_to_guid(guid.replace('-', '').lower(), wanted):
        return None
    raw = xaccSplitLookup(wanted, book.instance)
    split = None if raw is None else Split(instance=raw)
    return split if split is not None and split.GetAccount() is not None else None


def refuse_a_disposal_that_gives_no_cost_basis(book, transaction) -> None:
    """Refuse a transaction that spends foreign currency without saying whose.

    Currency leaving the book is a disposal: the cost basis it came out of
    falls by what went, and the difference between what those units cost and
    what they fetched is realized then. Which basis it came out of decides that
    difference, so the file states it with `cost_basis_split_guid:` and this
    tool never picks one — not the oldest, not the largest, not the one that
    makes the figures come out flattest. A guessed basis states a gain the
    reader never gave, in a book that afterwards looks perfectly correct.

    **Silence was the old answer and it is the worst of the three.** Investigated on
    this tree before this check: 4,000.00 USD spent on shares out of a bank
    holding 15,000.00 left the cost bases claiming 15,000.00, at exit 0, and
    the balance sheet only reports that months later — Q-044's
    `measured_from: gnucash_revaluation` exists to describe such a book, and
    can do nothing to repair it. Q-045 has the measurements.

    **What counts as leaving is the net for a commodity and a side**, not a
    negative split. 4,000.00 USD moved from one US dollar account to another is
    +4,000.00 and −4,000.00 on the held side and nothing has gone; a loan
    repaid out of a US dollar bank is −2,000.00 held and −2,000.00 owed and two
    things have. Both come to nothing if the splits are simply added, which is
    why the sum is taken per side.

    **And a side the book keeps no cost basis for is left alone**, because
    there is nothing there to draw down and nothing to state. A cost basis is
    opened by an arrival stated in the book's own currency, which is the only
    statement of what the units cost; a book whose dollars all arrived stated
    in dollars holds none, and `fx-balances` lists none for the refusal to send
    its reader to. Such a book is the one Q-044's `measured_from:
    gnucash_revaluation` describes, and spending out of it misstates no cost
    basis because it has none to misstate. Asked without that, every book whose
    accounts are in one currency that is not this one was refused its own
    payments: `tests/fixtures/beancount_export_edge_shapes.txt` keeps its bank
    and its expenses in East Caribbean dollars, and a 25.00 cheque out of that
    bank was turned away with a refusal telling its reader to pick from a list
    with nothing in it.
    """
    for split in transaction.GetSplitList():
        wrong = why_a_pending_split_cannot_stand(split) if is_pending(split) else ''
        if wrong:
            raise Exception(wrong)
    # A guid is wanted for each side that lost units, not one for the
    # transaction. Repaying a foreign loan out of a foreign bank consumes a
    # cost basis on both: the dollars leave the bank and the debt they pay off
    # goes, and the two were taken on at different rates, so each realizes a
    # difference of its own. Investigated on the worked case in Q-045 — 1,000 USD
    # borrowed at 1.30, 1,010 earned at 1.35, all of it repaid at 1.40 — the
    # asset side makes 50.50 CAD and the owed side loses 100.00, and one guid
    # cannot say both. Asked per commodity rather than per side, a repayment
    # giving only the loan's guid passed this check while the bank's dollars
    # went unaccounted for.
    for (commodity, side), gone in _what_left_each_side(transaction).items():
        # The splits taking units off that side, whatever their account's type:
        # 200.00 charged to a card holding a credit of 200.00 spends what was
        # held, and 1,000.00 into an account at −500.00 pays off 500.00 owed.
        on_that_side = [split for split in transaction.GetSplitList()
                        if split_commodity(split) == commodity
                        and the_side_it_draws(split) == side]
        # What the splits giving a guid take off the side, against what left
        # it. Enough to cover the fall and the disposal has said where all of
        # it came from; short, and the rest came out of a cost basis no split
        # gives. Asked as "does any split give one", 100.00 USD out of one
        # bank giving its cost basis let 50.00 out of a second bank through
        # with none, and the cost bases held 600.00 against 550.00. A split
        # giving `$pending$` has said, too: that its cost basis is not decided.
        given = sum((drawn_by(split)
                     for split in on_that_side if _says_which(split)),
                    Fraction(0))
        # What the splits giving a cost basis drew comes off the fall of the
        # side, not off what the splits giving none spent: that already leaves
        # them out, and a fee giving one says nothing of a fee beside it.
        not_given = max(-gone - given, _spent_where_nothing_took_it(transaction, commodity, side))
        if not_given <= 0:
            continue
        # The book is walked last, because it is the dear question and the two
        # cheap ones above turn away every transaction that moves no currency
        # and every disposal that has already said which basis it draws on. A
        # cost basis the transaction opens itself counts as one kept: a fee
        # beside the arrival it came out of spends the arrival's dollars. So
        # does an invoice the transaction collects: a fee beside a customer's
        # payment spends dollars whose cost is that invoice's (Q-051).
        if not (a_cost_basis_is_kept_for(book, commodity, side)
                or any(establishes_cost_basis(split) and split_commodity(split) == commodity
                       and _fraction(split.GetAmount()) * (1 if side == 'asset' else -1) > 0
                       for split in transaction.GetSplitList())
                or (side == 'asset'
                    and any(_settles_an_invoice(split) and split_commodity(split) == commodity
                            for split in transaction.GetSplitList()))):
            continue
        raise SpendGivingNoCostBasisError(
            commodity, side, not_given,
            [split for split in on_that_side if not _says_which(split)],
            transaction)


def what_a_disposal_is(commodity: str, side: str, spent: str, giving: list, others: list):
    """What kind of disposition a transaction makes of a holding, and the splits that say so.

    `spent` is what it disposes of, written. `giving` are the splits disposing
    of the holding and `others` the rest, each `(account full name, account
    type, account type as the ledger writes it, mnemonic, is a currency,
    amount, smallest unit, what it repays)`, the last being what it takes off
    a balance owed in its own commodity.

    There are only so many dispositions, and the account types of the splits
    say which: a security debited is a purchase, a balance owed in the same
    currency falling a repayment, the same currency debited to a receivable or
    a payable a payment, another currency debited to a balance-sheet account a
    sale, and an expense account debited an expense. Called "spends"
    whichever it was, US dollars sold onto a Canadian dollar account read as
    an expense to the person refused, who could not see why it was refused.

    Returns the kind — `('a sale', 'of 0.72 USD the book held for 1.00 CAD')`
    — and the splits the kind was read from, each described by its account,
    its type, its currency and whether it is debited or credited.
    """
    held = 'held' if side == 'asset' else 'owed'

    def total(parts):
        return _format(sum((abs(each[5]) for each in parts), Fraction(0)), parts[0][6])

    gone = f'{spent} {commodity} the book {held}'

    def described(part, extra=''):
        article = 'an' if part[2][0] in 'AEIOU' else 'a'
        entered = 'debited' if part[5] > 0 else 'credited'
        return (f'{part[0]}, {article} {part[2]} account in {part[3]}, is {entered} '
                f'{total([part])} {part[3]}{extra}')

    def taking(parts):
        return [described(each) for each in parts]

    def paying_off(parts):
        return [described(each, f', {_format(each[7], each[6])} of it repaying what it owed')
                for each in parts]

    if side == 'liability':
        return ('a repayment', f'of {gone}', paying_off(giving))
    # A split of the same holding disposing of it beside these, and giving its
    # cost basis, is part of the same transaction: what it fetched was
    # fetched by both, so it is listed, and no figure is put on the part.
    beside = [each for each in others if each[3] == commodity and each[5] < 0]
    gave = [described(each) for each in giving + beside]
    fetched_by = '' if beside else ' for {}'
    received = [each for each in others if each[5] > 0]
    security = [each for each in received if not each[4]]
    if security:
        return ('a purchase', f'of {total(security[:1])} {security[0][3]} with {gone}',
                gave + taking(security[:1]))
    repaid = [each for each in others if each[3] == commodity and each[7] > 0]
    if repaid:
        return ('a repayment', f'of {commodity} the book owed with {gone}',
                gave + paying_off(repaid))
    onto_a_record = [each for each in received if each[3] == commodity
                     and each[1] in (ACCT_TYPE_RECEIVABLE, ACCT_TYPE_PAYABLE)]
    if onto_a_record:
        return ('a payment', f'of {gone}', gave + taking(onto_a_record))
    # A sale for the book's own currency, for another, or of a security for a
    # currency: what it fetched is in the currency coming in, the book's own
    # where it comes in at all.
    kept = [each for each in received
            if each[1] not in _GAIN_TYPES and each[3] != commodity]
    fetched_in = BASE_CURRENCY if any(each[3] == BASE_CURRENCY for each in kept) else (
        kept[0][3] if kept else '')
    fetched = [each for each in kept if each[3] == fetched_in]
    if fetched:
        return ('a sale', f'of {gone}' + fetched_by.format(f'{total(fetched)} {fetched_in}'),
                gave + taking(fetched))
    # An expense account debited is an expense; an income account debited, as
    # a refund to a customer debits the sale it returns, is a refund.
    expensed = [each for each in received if each[1] == ACCT_TYPE_EXPENSE]
    refunded = [each for each in received if each[1] == ACCT_TYPE_INCOME]
    return ('a refund' if refunded and not expensed else 'an expense', f'of {gone}',
            gave + taking(expensed or refunded))


def a_part(account, amount: Fraction, pays_off: Fraction) -> tuple:
    """A split on `account` of `amount`, as `what_a_disposal_is` reads it."""
    from services.account_categorizer import AccountCategorizer
    commodity = account.GetCommodity()
    return (get_account_full_name(account), account.GetType(),
            AccountCategorizer().get_type_name(account), commodity.get_mnemonic(),
            is_a_currency(commodity), amount, commodity.get_fraction(), pays_off)


def _as_parts(splits) -> list:
    """`splits` as `what_a_disposal_is` reads them."""
    parts = []
    for split in splits:
        moves = split_moves(split)
        parts.append(a_part(split.GetAccount(), _fraction(split.GetAmount()),
                            -moves[1] if moves is not None and moves[1] < 0 else Fraction(0)))
    return parts


def why_it_consumes_a_cost_basis(kind, subject: str = 'this transaction is') -> str:
    """The sentence saying what a transaction is, from the splits that say so."""
    noun, detail, splits = kind
    return (f'{subject} {noun} {detail}: {"; ".join(splits)}. '
            f'{noun[0].upper()}{noun[1:]} requires a consumption of one or more '
            f'cost bases, but no split says which.')


class SpendGivingNoCostBasisError(Exception):
    """A transaction disposing of a holding of the book's, no split saying from which cost basis.

    Carries what it disposes of so the import can give the owner the ways to
    write it, in the file's own positions: the importer knows where each split
    stands in the file, and this does not.
    """

    def __init__(self, commodity: str, side: str, spent: Fraction, spending: list,
                 transaction):
        self.commodity = commodity
        self.side = side
        self.spent = spent
        self.spending = spending
        leaving = {split_guid(split) for split in spending}
        kind = what_a_disposal_is(
            commodity, side, _format(spent, smallest_unit(spending[0])),
            _as_parts(spending),
            _as_parts(split for split in transaction.GetSplitList()
                      if split_guid(split) not in leaving))
        super().__init__(
            f'{why_it_consumes_a_cost_basis(kind)} '
            f'State `{COST_BASIS_SPLIT_KEY}:` on the split that disposes of it, '
            f'giving the guid of the cost basis the {commodity} came out of — '
            f'`fx-balances` lists them. A cost basis is never chosen for you: '
            f'which one a disposal draws on decides the gain it realized.')


def _spent_where_nothing_took_it(transaction, commodity: str, side: str) -> Fraction:
    """What left accounts of a side, giving no cost basis, that no other account of it took.

    Netting a side finds what left it, and misses a spend beside an arrival on
    the same account: 2,720.00 USD in and a 0.72 USD fee out of the same bank
    leave the side 2,719.28 up, and the fee spent dollars without saying from
    where (Q-050). What another account of the side took only moved, as
    4,000.00 USD sent from a chequing account to a savings account does, and
    is no spend.
    """
    at = 0 if side == 'asset' else 1
    out: Dict[str, Fraction] = {}
    into: Dict[str, Fraction] = {}
    for split in transaction.GetSplitList():
        moves = split_moves(split) if split_commodity(split) == commodity else None
        if moves is None or _says_which(split):
            continue
        account = get_account_full_name(split.GetAccount())
        if moves[at] < 0:
            out[account] = out.get(account, Fraction(0)) - moves[at]
        else:
            into[account] = into.get(account, Fraction(0)) + moves[at]
    left = sum(out.values(), Fraction(0))
    elsewhere = sum((taken for account, taken in into.items() if account not in out),
                    Fraction(0))
    return left - min(left, elsewhere)


def a_cost_basis_is_kept_for(book, commodity: str, side: str) -> bool:
    """Whether the book holds a cost basis of this commodity a disposal can consume.

    A balance of nothing counts for nothing, the way it counts for nothing on
    the balance sheet: a cost basis spent to the last unit stays on the book as
    a row reading 0.00, and a side holding only those has no units left to draw
    on. The side is the sign of what the basis brought in rather than the type
    of the account holding it, which is how `cost_basis_items_by_currency_and_side`
    reads it and why an overpaid invoice's two bases stay apart.

    **A cost basis on a receivable or a payable is passed over**, for the reason
    `_what_left_each_side` passes those accounts over: what draws one of them
    down is the settlement of the record it belongs to, through its lot, and
    never the arithmetic of a disposal. So it is not a cost basis a disposal can
    consume, and a side holding nothing else has none to offer.

    Counted, a book whose only US dollars are an owner's credit turned away the
    spending of that credit. Investigated on two: a sale of 80.00 USD out of a
    customer's 100.00 USD credit, and a credit an unpost hands back and a rebuilt
    book then spends — both refused, and both sent their reader to a listing
    holding one row they could not have used, because a credit is spent through
    its lot and the guid would have been refused as well.
    """
    # Asked once for every disposal that gives no guid, so the answer is kept
    # on the book for as long as no cost basis changes: a book kept wholly in
    # East Caribbean dollars keeps none, and without it every payment walked
    # every earlier one. It is asked afresh after any write that sets or drops
    # a `cost_basis_balance` — counted where every such write passes, in
    # `set_custom_metadata` — and after any split becomes a cost basis, which
    # an edit can do without writing a balance.
    #
    # An edit, a deleted transaction and one the import destroys on refusing it
    # forget it too (`cost_bases_changed`), each able to take a cost basis away
    # without writing a balance.
    written = (_cost_bases_written, watched_key_writes())
    kept = getattr(book, '_plaintext_cost_bases_kept', None)
    if kept is None or kept[0] != written:
        kept = (written, {})
        book._plaintext_cost_bases_kept = kept
    if (commodity, side) not in kept[1]:
        kept[1][(commodity, side)] = _walk_for_a_kept_cost_basis(book, commodity, side)
    return kept[1][(commodity, side)]


_cost_bases_written = 0


def cost_bases_changed() -> None:
    """Forget every kept answer to whether a book keeps a cost basis.

    Called wherever a cost basis can appear or go without a balance being
    written: a split becoming one, an edit removing splits, a transaction
    deleted, and one the import refuses and destroys.
    """
    global _cost_bases_written
    _cost_bases_written += 1


def _walk_for_a_kept_cost_basis(book, commodity: str, side: str) -> bool:
    # Only the accounts holding this commodity are walked, and of their splits
    # only one carrying a stored balance is asked whether it is a cost basis —
    # one KVP read turns the rest away.
    for account in _accounts_holding(book, commodity):
        if account.GetType() in (ACCT_TYPE_RECEIVABLE, ACCT_TYPE_PAYABLE):
            continue
        for split in account.GetSplitList():
            try:
                balance = cost_basis_balance_of(split)
                if not balance or not establishes_cost_basis(split):
                    continue
            except Exception:
                # A cost or a balance that will not parse counts for nothing
                # here as it does everywhere else that adds these up.
                # `--verify-costs` is what reports such a figure.
                continue
            if ('asset' if _fraction(split.GetAmount()) > 0 else 'liability') == side:
                return True
    return False


def _a_cost_basis_opened_by(book, commodity: str, side: str, when) -> bool:
    """Whether a cost basis of `commodity` on `side` was opened on or before `when`.

    Asked of a split giving `$pending$`, whose cost basis has to be one the
    book held on its date. Receivables and payables are passed over, as
    `_walk_for_a_kept_cost_basis` passes them over.
    """
    for account in _accounts_holding(book, commodity):
        if account.GetType() in (ACCT_TYPE_RECEIVABLE, ACCT_TYPE_PAYABLE):
            continue
        if any(split.GetParent().GetDate().date() <= when
               and establishes_cost_basis(split)
               and ('asset' if _fraction(split.GetAmount()) > 0 else 'liability') == side
               for split in account.GetSplitList()):
            return True
    return False


def _accounts_holding(book, commodity: str) -> Iterator:
    """Every account in the book whose commodity has this mnemonic.

    An account can have no commodity at all: the top-level `Trading` account
    GnuCash makes for a book using trading accounts has none.
    """
    def walk(account):
        for child in account.get_children():
            held = child.GetCommodity()
            if held is not None and held.get_mnemonic() == commodity:
                yield child
            yield from walk(child)

    yield from walk(book.get_root_account())


def account_side(account) -> Optional[str]:
    """Which side of the book an account sits on: 'asset', 'liability' or None.

    None for a receivable or a payable, settled through its lots, and for an
    income, expense or equity account, which holds no currency.
    """
    account_type = account.GetType()
    if account_type in (ACCT_TYPE_RECEIVABLE, ACCT_TYPE_PAYABLE):
        return None
    if account_type in _DEBIT_TYPES:
        return 'asset'
    if account_type in _CREDIT_TYPES:
        return 'liability'
    return None


def _what_left_each_side(transaction) -> Dict[tuple, Fraction]:
    """Per commodity and side, the change this transaction makes to what is held.

    Negative where units left that side, which is what a disposal is.

    **The fall in what the accounts hold, not the sum of the amounts**, and the
    two differ wherever an account goes below nothing. An account in overdraft
    holds no units of its currency — it owes them — so a split that takes one
    from 0.00 to −100.00 US dollars has spent no dollars the book had. That is
    the shape a parked settlement takes: money reaches a Canadian bank and the
    US dollars it stands for are written on a suspense account as −100.00,
    waiting for a `payment:` block to place them on the receivable. Read as a
    sum of amounts, the parking was a disposal of a hundred dollars that never
    happened, and the file was turned away for not stating which cost basis
    those dollars came out of. So what is asked of each account is the fall
    between what it held without this transaction and what it holds with it,
    each figure floored at nothing.

    **A share counts as much as a dollar**, because a share is a holding with a
    cost basis of its own (Q-046). Selling 8 of 20 shares draws that cost basis
    down by 8 and realizes what those 8 made, so the file says which cost basis
    they came out of, exactly as a currency disposal does.

    **Then netted across the side**, which is what keeps a transfer out: 4,000.00
    USD moved from one US dollar account to another takes 4,000.00 off the first
    and puts 4,000.00 on the second, and the book holds every dollar it held
    before.

    Business accounts are left out for the reason `_only_moved_within_one_side`
    leaves them out: a receivable's settlement and a prepayment's credit sit on
    one account and are told apart by their lots, not by arithmetic.

    **`Imbalance-<CUR>` and `Orphan-<CUR>` are counted**, though GnuCash rather
    than a ledger made them, because they are accounts holding units of the
    currency and `fx-balances` lists what they hold beside every other account.
    A transaction that does not add up has its difference parked in one of them,
    so the units really did move there. The overdraft rule is what keeps that
    harmless: such an account starts at nothing and goes negative, so nothing
    falls. A trading account needs no rule of its own — its type is neither a
    debit nor a credit one, so the loop below passes it over.
    """
    # Each split's own move on each side, which `mark_what_arrives_past_zero`
    # has already read from the account's balance on the transaction's date.
    net: Dict[tuple, Fraction] = {}
    for split in transaction.GetSplitList():
        # `split_commodity` answers the empty string for a split with no
        # account, which is the shape GnuCash makes for itself on a
        # trading-accounts book (CLAUDE.md finding 12), so this turns that one
        # away and `split_moves` has an account to read.
        commodity = split_commodity(split)
        if not commodity or commodity == BASE_CURRENCY:
            continue
        moves = split_moves(split)
        if moves is None:
            continue
        for side, change in zip(('asset', 'liability'), moves):
            net[(commodity, side)] = net.get((commodity, side), Fraction(0)) + change
    return net


def what_each_account_held_without(book, transaction, accounts, when,
                                   came_after=frozenset()) -> Dict[str, Fraction]:
    """What each account held at the end of `when` before this transaction.

    Read before an edit opens the transaction: inside an open edit GnuCash
    still counts each split on the account it was on before, so a balance read
    there is a balance of the transaction as it was. The transaction's own
    splits are taken off where it is dated on or before `when`, since only
    then does the balance count them.

    `came_after` is the guids of transactions drawing on this one's cost
    bases, directly or down the chain. Each was imported after it, since it
    could not draw on a cost basis the book did not yet hold, so its splits
    dated on or before `when` are taken off too: read with them, a fee of 0.72
    USD dated the same day as a 2,720.00 USD arrival made the account read as
    holding -0.72 before the arrival, and the arrival as bringing in 2,719.28.
    """
    # The splits taken off are those of these transactions, read from each,
    # not searched for among every split of the account: that search, once
    # per transaction an update touches, grew with the book times the file.
    from services.gnucash_importer import _find_transaction_by_guid
    dated = [transaction] + [each for each in (_find_transaction_by_guid(book, guid)
                                               for guid in sorted(came_after))
                             if each is not None]
    dated = [each for each in dated if each.GetDate().date() <= when]
    day_after = datetime.combine(when + timedelta(days=1), datetime.min.time())
    held: Dict[str, Fraction] = {}
    for account in accounts:
        here = account.GetGUID().to_string()
        taken_off = sum((_fraction(split.GetAmount()) for each in dated
                         for split in each.GetSplitList()
                         if split.GetAccount() is not None
                         and split.GetAccount().GetGUID().to_string() == here),
                        Fraction(0))
        held[get_account_full_name(account)] = (
            _fraction(account.GetBalanceAsOfDate(day_after)) - taken_off)
    return held


def mark_what_arrives_past_zero(transaction, held_without=None, as_it_was=None,
                                leaving=frozenset()) -> None:
    """Record, on each split whose account crosses or lies past zero, what it brought in.

    An asset account below zero owes its currency and a liability account above
    zero holds it (Q-047). So a split is read against its account's balance on
    the transaction's date: the part of its move above zero is on the held
    side, the part below zero on the owed side. 500.00 USD out of a bank holding
    nothing brings 500.00 in on the owed side; 1,000.00 into it at −500.00
    repays 500.00 owed and brings 500.00 in on the held side; 200.00 charged
    to a card holding 200.00 spends what it held and brings nothing in.

    Written only where that differs from what the account's type says, and
    removed where it does not, so a file cannot state it: a split that raises
    its account in its own direction from zero or beyond brought its whole
    amount in, as it always did.

    Read at the transaction's own date, as the book holds it when this runs.
    It is already committed, so taking its own splits back off is what each
    account held without it. A file's transactions are imported in the order
    the file gives them, which is the order its writer meant.

    `as_it_was` is given on an edit: each split's guid, with the account,
    amount and date it had before the edit. Where the edit left every split
    on an account as it was, those splits keep what they recorded; moved to
    another date, or beside a split that changed, they are read again. `leaving` is the guids of splits an open edit has destroyed,
    which GnuCash lists until the commit.
    """
    # GnuCash's own balance as of a moment counts every split dated before it,
    # so the start of the next day counts everything on the transaction's own
    # date. Handed a `datetime`, as every date is handed to GnuCash here
    # (CLAUDE.md finding 20).
    day_after = datetime.combine(transaction.GetDate().date() + timedelta(days=1),
                                 datetime.min.time())
    here = {split_guid(split) for split in transaction.GetSplitList()}
    on_each_account: Dict[str, list] = {}
    for split in transaction.GetSplitList():
        commodity = split_commodity(split)
        if not commodity or commodity == BASE_CURRENCY or split_guid(split) in leaving:
            continue
        account_type = split.GetAccount().GetType()
        if account_type not in (_DEBIT_TYPES | _CREDIT_TYPES) or account_type in (
                ACCT_TYPE_RECEIVABLE, ACCT_TYPE_PAYABLE):
            continue
        # Currency alone. A share account below zero is shares sold that were
        # never bought, or bought in a book this one never saw, not shares
        # owed; read as owing, 10 shares sold out of an account holding none
        # opened an owed cost basis the next purchase had to give the guid of.
        if not is_a_currency(split.GetAccount().GetCommodity()):
            continue
        on_each_account.setdefault(get_account_full_name(split.GetAccount()), []).append(split)

    for name, splits in on_each_account.items():
        account = splits[0].GetAccount()
        moved = sum((_fraction(split.GetAmount()) for split in splits), Fraction(0))
        # Given on an edit, read before it opened (`what_each_account_held_without`):
        # while it is open the balances are the transaction's as it was, and
        # after its commit they count what came after it the same day.
        position = (held_without[name] if held_without is not None
                    else _fraction(account.GetBalanceAsOfDate(day_after)) - moved)
        # In an order of the import's own, not the transaction's: GnuCash does
        # not keep a transaction's splits in the order a file gives them. The
        # splits moving the account the way it moves overall come first, then
        # the rest, each in guid order. A card owing nothing, charged 150.00 and
        # refunded 100.00 in one transaction, reads the charge first either
        # way: 150.00 owed, 100.00 of it repaid. Read refund first, it was a
        # credit of 100.00 brought in and then a charge crossing zero, for a
        # card that went from owing nothing to owing 50.00.
        # And a split drawing on another of this transaction's splits after
        # it: the fee and the rest sent on out of a 2,720.00 USD arrival leave
        # the account where it was, and read first they took it below zero,
        # so the arrival read as repaying what they borrowed and brought
        # nothing in to draw on (Q-050).
        splits.sort(key=lambda split: (
            cost_basis_guid_of(split) in here,
            0 if _fraction(split.GetAmount()) * moved > 0 else 1, split_guid(split)))
        # An edit that leaves every split on this account as it was — the
        # same splits, at the same amounts, on the same date — leaves them
        # keeping what they recorded when they were imported. Read again, a
        # fee of 0.72 USD dated the same day and imported after a 2,720.00 USD
        # arrival made the arrival read as bringing in 2,719.28, and an edit
        # moving only the arrival's other split left the cost basis's price as
        # it was yet changed what it brought in. Every split on the account or none: where one is
        # added, removed or re-amounted, the others start from a different
        # place, and are read again with it.
        when = transaction.GetDate().date()
        kept = (as_it_was is not None
                and {guid for guid, was in as_it_was.items() if was[0] == name}
                == {split_guid(split) for split in splits}
                and all(as_it_was[split_guid(split)] == (name, _fraction(split.GetAmount()), when)
                        for split in splits))
        for split in splits:
            if not kept:
                _record_what_it_brought_in(transaction, split, position)
            position += _fraction(split.GetAmount())


def _record_what_it_brought_in(transaction, split, before: Fraction) -> None:
    """Write or remove `cost_basis_brought_in` on one split, its account at `before`; nothing, in a book that keeps no cost bases (Q-049)."""
    if not book_keeps_cost_bases(split.GetBook()):
        return
    account_type = split.GetAccount().GetType()
    amount = _fraction(split.GetAmount())
    after = before + amount
    held = max(after, Fraction(0)) - max(before, Fraction(0))
    owed = max(-after, Fraction(0)) - max(-before, Fraction(0))
    brought_in = max(held, Fraction(0)) + max(owed, Fraction(0))
    by_type = (amount if account_type in _DEBIT_TYPES and amount > 0 else
               -amount if account_type in _CREDIT_TYPES and amount < 0 else
               Fraction(0))
    # A split giving a guid says where its units came from. It brings anything
    # in only where it crosses zero, drawing on the side it leaves and arriving
    # past it; one that draws nothing on the side it leaves is a disposal as the
    # reader wrote it, and its guid decides what it drew. 40.00 USD sold out of
    # an empty bank against an invoice not yet collected gives the invoice's
    # guid, and opening a cost basis owed for the 40.00 as well counted it
    # twice (Q-047).
    if cost_basis_guid_of(split) and not (held < 0 if amount < 0 else owed < 0):
        brought_in = by_type
    metadata = dict(get_custom_metadata(split))
    if brought_in == by_type:
        if COST_BASIS_BROUGHT_IN_KEY not in metadata:
            return
        del metadata[COST_BASIS_BROUGHT_IN_KEY]
    else:
        metadata[COST_BASIS_BROUGHT_IN_KEY] = _format(brought_in, smallest_unit(split))
    transaction.BeginEdit()
    set_custom_metadata(split, metadata)
    transaction.CommitEdit()


def _stored_brought_in(split) -> Optional[Fraction]:
    """What `mark_what_arrives_past_zero` recorded this split brought in, or None."""
    raw = get_custom_metadata(split).get(COST_BASIS_BROUGHT_IN_KEY)
    if raw is None or raw == '':
        return None
    return Fraction(str(raw))


def split_moves(split) -> Optional[tuple]:
    """What this split moves on each side: (held, owed), each + for in and − for out.

    None for a split on a receivable or a payable, settled through its lots,
    and for one on an account holding no currency.

    Where the import recorded what the split brought in, the move is read from
    that and the amount: 1,000.00 into an account at −500.00 brought 500.00 in
    on the held side and took 500.00 off the owed side. Where it recorded
    nothing, the account's type decides, as it always did: a bank's split moves
    the held side by its amount and a loan's split the owed side.
    """
    account = split.GetAccount()
    account_type = account.GetType()
    if account_type in (ACCT_TYPE_RECEIVABLE, ACCT_TYPE_PAYABLE):
        return None
    if account_type not in (_DEBIT_TYPES | _CREDIT_TYPES):
        return None
    amount = _fraction(split.GetAmount())
    brought_in = _stored_brought_in(split)
    if brought_in is None:
        if account_type in _DEBIT_TYPES:
            return amount, Fraction(0)
        return Fraction(0), -amount
    if amount > 0:
        return brought_in, brought_in - amount
    return amount + brought_in, brought_in


def brought_in_by(split) -> Fraction:
    """How much of its currency a cost basis split brought in.

    Its whole amount, except where its account crossed zero: 1,000.00 USD into
    an account at −500.00 brought 500.00 in, and repaid the other 500.00.
    """
    brought_in = _stored_brought_in(split)
    return abs(_fraction(split.GetAmount())) if brought_in is None else brought_in


def drawn_by(split) -> Fraction:
    """How much of the cost basis it gives a disposal split draws down.

    Its whole amount, except where it crosses zero: 1,000.00 USD into an
    account at −500.00 repays 500.00 of what the account owed, and the other
    500.00 arrives. A split on a receivable or a payable is its whole amount.
    """
    moves = split_moves(split)
    whole = abs(_fraction(split.GetAmount()))
    if moves is None:
        return whole
    held, owed = moves
    drawn = -held if _fraction(split.GetAmount()) < 0 else -owed
    return drawn if drawn > 0 else whole


def draws_down(split) -> Fraction:
    """How far a disposal split lowers the cost basis it gives.

    What it draws (`drawn_by`), except where it is the only split drawing on
    its side and the side lost less than that: the rest of what it sent only
    moved to another account on the same side. 500.00 USD out of C onto a card
    owing 300.00 repays 300.00 and moves 200.00 onto the card's credit, so C's
    cost basis falls by 300.00, the held side's loss, where drawn down by the
    500.00 C sent it would stand for 200.00 fewer dollars than the held side
    holds (Q-047).

    The split is still valued at what all it sent cost, as every disposal is:
    the part that moved leaves at what it cost and arrives at the same.
    """
    drawn = drawn_by(split)
    at = {'asset': 0, 'liability': 1}.get(the_side_it_draws(split))
    if at is None:
        return drawn
    commodity = split_commodity(split)
    moving = [(other, split_moves(other)) for other in split.GetParent().GetSplitList()
              if split_commodity(other) == commodity and split_moves(other) is not None]
    lost = -sum((moves[at] for _other, moves in moving), Fraction(0))
    # A split giving `$pending$` counts as drawing, so what it would draw
    # down is read the same way before its cost basis is decided.
    drawing = [other for other, moves in moving
               if _says_which(other) and moves[at] < 0]
    return lost if len(drawing) == 1 and 0 < lost < drawn else drawn


def the_side_it_draws(split) -> Optional[str]:
    """The side a disposal split draws from: 'asset', 'liability', or None.

    The side it takes units off, whatever the account's type: a card holding a
    credit of 200.00 spends what it held when 200.00 is charged to it, and
    500.00 into a bank at −500.00 pays off what the bank owed. Read from the
    amount's sign alone, money into a bank holding some read as paying off
    what is owed. A split taking nothing off either side draws on neither, and
    so does one on a receivable or a payable, whose lots settle them.
    """
    moves = split_moves(split)
    if moves is None:
        return None
    held, owed = moves
    return 'asset' if held < 0 else 'liability' if owed < 0 else None


def apply_cost_basis_picks(book, transaction) -> Dict[str, Fraction]:
    """Check everything this transaction picks, then lower those balances.

    Every check runs before any balance is written, so a sale that is refused
    leaves no cost basis half-lowered.

    Returns what was taken, keyed by cost basis guid, because the transaction can
    still be refused after this — everything read from it afterwards is
    checked too — and a drawdown that outlives its transaction is currency the
    book can no longer sell and no longer accounts for. The caller destroys
    the transaction and gives this back together (`give_back_to_cost_bases`).

    Amounts are summed per cost basis first: two splits giving the same cost basis for 60
    USD each pass individually against a 100 USD balance but together exceed
    it, so it is the total that is checked.
    """
    wanted: Dict[str, Fraction] = {}
    for split in transaction.GetSplitList():
        basis_guid = cost_basis_guid_of(split)
        if not basis_guid:
            continue
        basis = _validate_pick(book, split, basis_guid)
        if basis is None:                     # stated in the file; already net
            continue
        wanted[basis_guid] = wanted.get(basis_guid, Fraction(0)) + draws_down(split)

    checked = []
    for basis_guid, total in wanted.items():
        basis = find_split_by_guid(book, basis_guid)
        available = cost_basis_balance_of(basis)
        currency = split_commodity(basis)
        if available is None:
            raise Exception(
                f'cost basis {basis_guid} has no balance recorded — the split '
                f'was not written by this tool, so how much of its {currency} '
                f'is still unsold is not known and cannot be assumed to be all '
                f'of it. State `{COST_BASIS_BALANCE_KEY}:` on that split in an '
                f'import file to give it a balance.')
        if total > available:
            held = brought_in_by(basis)
            unit = smallest_unit(basis)
            raise Exception(
                f'{_format(total, unit)} {currency} against cost basis {basis_guid} '
                f'exceeds its cost basis balance by '
                f'{_format(total - available, unit)} {currency} (the cost basis brought '
                f'in {_format(held, unit)} {currency} and has '
                f'{_format(available, unit)} left)')
        checked.append((basis, total))

    # Nothing is left to refuse by here: every balance was read and checked
    # above, before the first one moves, so the loop below cannot stop
    # part-way through.
    taken: Dict[str, Fraction] = {}
    for basis, total in checked:
        lower_cost_basis_balance(basis, total)
        taken[split_guid(basis)] = total
    return taken


def _validate_pick(book, selling_split, basis_guid: str):
    """Check one picking split, without writing anything.

    Returns the cost basis split, or None when the file stated that cost basis's balance
    — such a balance is already net of this sale and must not be lowered again.

    Raises when the cost basis cannot be found, is in another currency, is not a
    cost basis at all, has not been collected, or is valued at the wrong cost.
    """
    basis = find_split_by_guid(book, basis_guid)
    if basis is None:
        raise Exception(
            f'{COST_BASIS_SPLIT_KEY} {basis_guid!r} matches no split in the book')

    selling_currency = split_commodity(selling_split)
    basis_currency = split_commodity(basis)
    if selling_currency != basis_currency:
        raise Exception(
            f'{COST_BASIS_SPLIT_KEY} {basis_guid!r} is a {basis_currency} split '
            f'but this split sells {selling_currency}')

    if not establishes_cost_basis(basis):
        # No exemption here, for any split, however it is marked. A file that
        # gives a guid this cannot measure against is refused, and that is the
        # whole of the rule.
        #
        # A sale whose pool has since been spent — an owner's credit settling
        # their next invoice — is answered on the way out instead: the export
        # drops the guid, exactly as it drops a `cost_basis_cost` on a split
        # that is no cost basis, and for the same reason. Writing either produces a
        # file this tool refuses to read. Answered here instead, the check
        # would have to believe `applied_from_credit`, which a file may write,
        # and a sale could then give any split's guid at all and skip the
        # drawdown, the over-sell refusal, `_require_basis_collected` and
        # `_require_stated_cost` together.
        raise Exception(
            f'{COST_BASIS_SPLIT_KEY} {basis_guid!r} matches a split that is no '
            f'{basis_currency} cost basis — a cost basis is a split that brought '
            f'{basis_currency} into the book (an invoice, a bill, a purchase or '
            f'a borrowing)')

    # Dollars leaving a bank draw on a cost basis of dollars held, and a debt
    # paid off on one of dollars owed. Given the loan's cost basis, 100.00 USD
    # sold out of a bank lowered what the book owed and left the bank's cost
    # basis whole, holding 1,500.00 against the 1,400.00 the bank had left.
    #
    # A cost basis on a receivable or a payable has no side here, and neither
    # does a split on one: an overpayment's credit sits on the receivable as
    # money owed back, and the dollars it brought in are in the bank, costed by
    # that credit. Selling them out of the bank gives the credit's guid.
    #
    # Each side is read from which way the money moves, not from the account's
    # type (Q-047): an account below zero owes, so what goes into it pays off
    # a cost basis of dollars owed, and a card above zero holds a credit, so
    # what is charged to it spends a cost basis of dollars held.
    wrong_side = a_sale_against_a_basis_on_the_other_side(selling_split, basis, basis_guid)
    if wrong_side:
        raise Exception(wrong_side)

    _require_basis_collected(selling_split, basis, basis_guid)
    _require_stated_cost(selling_split, basis, basis_guid)

    # The file stated this cost basis's balance, so it already accounts for this
    # sale — re-importing an export must not lower it a second time.
    if balance_came_from_file(basis):
        return None
    return basis


def a_sale_against_an_uncollected_receivable(selling_split, basis, basis_guid: str,
                                             in_the_book: bool = False) -> Optional[str]:
    """A receivable that has not been collected holds no currency to sell.

    An invoice's A/R split states currency the customer owes, not currency the
    book has. Selling against it before the invoice is paid is selling money
    that has not arrived — this tool keeps books, it does not support trading a
    position it does not hold. The lot is the test: it closes when the record
    is settled, and what a part payment put in it is collected, and can be
    sold up to that much (Q-051).

    `in_the_book` is for a sale the book already holds, whose draw the cost
    basis's stored balance already reflects.

    A payable is not restricted. Its lot is open precisely until the bill is
    paid, and settling it with foreign cash is the ordinary way that happens.

    `cost_basis_force: true` on the selling split overrides it, for the case
    where the user knows the money is in hand and the record simply has not
    been marked paid yet.

    It is read first, before any of the reasons below to return early. Read
    where it is *used*, a mistyped one on a split this function lets past —
    a settled lot, a payable, an overpayment — was never looked at, so the
    same typo was named on one sale and ignored on the next. A flag a file
    states is read wherever the file states it.
    """
    # Read as a word, like every other flag a ledger carries: compared
    # against a list of the truthy spellings, `cost_basis_force: treu` was
    # silently *not* forced, and the sale then failed with a message telling
    # its author to add the key they had already added.
    #
    # Imported here rather than at the top for the reason given above
    # `is_a_bank_paid_orphan`: `gnucash_importer` reads this module.
    from services.gnucash_importer import _a_yes_or_no

    forced = _a_yes_or_no(
        get_custom_metadata(selling_split).get(COST_BASIS_FORCE_KEY, 'false'),
        COST_BASIS_FORCE_KEY, 'a split')

    account = basis.GetAccount()
    if account is None or account.GetType() != ACCT_TYPE_RECEIVABLE:
        return

    # A split on the receivable itself is the collection, not a sale of what
    # has not been collected: it is the entry that settles the invoice, and
    # refusing it would forbid the very thing that makes the cost basis sellable.
    # Selling is a split somewhere else — a bank account paying the currency
    # out — measured against this cost basis.
    selling_account = selling_split.GetAccount()
    if (selling_account is not None
            and get_account_full_name(selling_account) == get_account_full_name(account)):
        return

    # A credit balance on the receivable is money already in hand — an
    # overpayment, held and owed back — so there is nothing uncollected about
    # it. Its lot stays open because the debt runs the other way now, which is
    # the opposite of an invoice waiting to be paid.
    if _fraction(basis.GetAmount()) < 0:
        return

    raw_lot = basis.GetLot()
    if raw_lot is None:
        return
    # `xaccSplitGetLot` hands back a raw pointer; a bare SwigPyObject has no
    # lot methods.
    lot = raw_lot if hasattr(raw_lot, 'get_balance') else GncLot(instance=raw_lot)
    balance = lot.get_balance()
    if Fraction(balance.num(), balance.denom()) == 0:      # settled
        return
    if forced:
        return
    if _collected_for_what_is_drawn(selling_split, basis, raw_lot, in_the_book):
        return
    currency = split_commodity(basis)
    return (
        f'cost basis {basis_guid} is a split on '
        f'{get_account_full_name(account)!r}, and the invoice it belongs to '
        f'has not been collected — that {currency} is owed, not held, so '
        f'there is none to sell. Record the payment first, or add '
        f'`{COST_BASIS_FORCE_KEY}: true` to this split to measure against it '
        f'anyway.')


def _collected_for_what_is_drawn(selling_split, basis, raw_lot, in_the_book: bool) -> bool:
    """Whether what has been collected of the invoice covers what is drawn on its cost basis.

    What is collected counts: the invoice's settlements in its lot, and,
    while a file is imported, the splits of the sale's transaction the file's
    `payment:` block applies to it. A deposit booked as an invoice's
    collection, its bank fee in the same transaction drawing on the invoice's
    cost basis, is imported before the block puts its receivable split in the
    invoice's lot, so the lot still reads unpaid while the fee is checked
    (Q-051).

    What was drawn counts too: what the cost basis gave up already, and what
    this split draws, which `in_the_book` says the stored balance already
    reflects. So a part payment of 2,720.00 of a 4,000.00 invoice holds
    2,720.00 and no more, as the file is imported and in the book it leaves.
    """
    # Imported here, as `_a_yes_or_no` is above: `gnucash_importer` reads
    # this module.
    from infrastructure.gnucash.utils import wrap_invoice_or_bill
    from services.gnucash_importer import _SPLITS_THE_FILES_PAYMENTS_APPLY

    brought_in = _fraction(basis.GetAmount())
    lot = raw_lot if hasattr(raw_lot, 'get_balance') else GncLot(instance=raw_lot)
    left = lot.get_balance()
    collected = brought_in - Fraction(left.num(), left.denom())
    if _SPLITS_THE_FILES_PAYMENTS_APPLY:
        # A lot linked to no invoice, which GnuCash allows on a receivable,
        # has no record a block of the file applies a split to.
        raw_invoice = _gc.gncInvoiceGetInvoiceFromLot(qof_instance(raw_lot))
        record = ('invoice', wrap_invoice_or_bill(raw_invoice).GetID()) if raw_invoice else None
        account = get_account_full_name(basis.GetAccount())
        # Not a split already in the lot: the lot's balance counts it above,
        # and an export applies it again by its block, so an edit of a part
        # payment read 2,720.00 collected as 5,440.00.
        # The whole split: the block applies all of it, whatever `amount:` it
        # states, and a block stating 1,000.00 against a 2,720.00 split
        # leaves 2,720.00 in the invoice's lot.
        in_the_lot = qof_pointer(raw_lot)
        collected += sum((-_fraction(split.GetAmount())
                          for split in selling_split.GetParent().GetSplitList()
                          if _SPLITS_THE_FILES_PAYMENTS_APPLY.get(split_guid(split)) == record
                          and get_account_full_name(split.GetAccount()) == account
                          and (split.GetLot() is None
                               or qof_pointer(split.GetLot()) != in_the_lot)),
                         Fraction(0))
    if collected <= 0:
        return False
    # Every split of the sale's transaction giving this cost basis, not this
    # one alone: each is checked before any is drawn, and two sales of
    # 1,400.00 each passed against 2,720.00 collected.
    held = cost_basis_balance_of(basis)
    drawn = ((brought_in - held if held is not None else Fraction(0))
             + (Fraction(0) if in_the_book else
                sum((draws_down(split) for split in selling_split.GetParent().GetSplitList()
                     if cost_basis_guid_of(split) == split_guid(basis)), Fraction(0))))
    return drawn <= collected


def _require_basis_collected(selling_split, basis, basis_guid: str) -> None:
    """Refuse a sale in the file against a receivable not yet collected."""
    wrong = a_sale_against_an_uncollected_receivable(
        selling_split, basis, basis_guid)
    if wrong:
        raise Exception(wrong)


def a_sale_against_another_currencys_basis(selling_split, basis,
                                           basis_guid: str) -> Optional[str]:
    """What is wrong where a sale draws on a cost basis holding another currency.

    A cost basis holds units of one currency, and a sale takes units out of it, so
    the two have to be the same currency or the subtraction means nothing —
    50.00 EUR taken out of a pool of US dollars.

    `_validate_pick` refuses this of a sale in a file. Asked here as well, of
    the sales already in the book, because an `--atomic` run may re-point a
    disposal at another cost basis in place: the figures do not move, so the
    deferred `_require_no_cost_basis_edit` lets it through, and
    `update_transaction` calls nothing that draws a cost basis down, so the pick is
    read by nothing else. The valuation question catches such a re-point only
    where the two cost bases happen to have cost different figures, and only where
    the sale is stated in the book's own currency — this one is the question
    that exists for it.
    """
    selling_currency = split_commodity(selling_split)
    basis_currency = split_commodity(basis)
    if selling_currency == basis_currency:
        return None
    return (
        f'this split sells {selling_currency} and draws on cost basis '
        f'{basis_guid}, which holds {basis_currency} — a cost basis is a pool of '
        f'one currency, and nothing can be taken out of it in another. Point '
        f'it at a {selling_currency} cost basis, or drop the line and let the '
        f'sale '
        f'draw on nothing')


def a_sale_against_a_basis_on_the_other_side(selling_split, basis,
                                             basis_guid: str) -> Optional[str]:
    """What is wrong where a split spends currency held and draws on a cost basis of currency owed, or the reverse.

    `_validate_pick` refuses it of a sale in a file.

    A cost basis on a receivable or a payable has no side, because an owner's
    credit sits there as money owed back while the dollars it brought in are
    in the bank. A record's posting is not a credit: a bill's is dollars the
    book owes, and an invoice's dollars it is owed, which are held once
    collected, so each is read as that side. Read as no
    side, a bank's fee restated onto a bill's cost basis, linked in the same
    `--atomic` file as the deposit it came out of, left the bank holding
    2,719.28 USD while the invoice's cost basis offered 2,720.00, and the
    bill owing 1,000.00 while its cost basis read 999.28, and nothing
    reported it.
    """
    spending_side = the_side_it_draws(selling_split)
    basis_side = (None if split_moves(basis) is None
                  else 'asset' if _fraction(basis.GetAmount()) > 0 else 'liability')
    # A record's posting in its normal direction, in a lot an invoice or a
    # bill owns.
    posted = {ACCT_TYPE_PAYABLE: 'liability', ACCT_TYPE_RECEIVABLE: 'asset'}.get(
        basis.GetAccount().GetType())
    normal = _fraction(basis.GetAmount()) * (1 if posted == 'asset' else -1) > 0
    raw_lot = basis.GetLot()
    in_a_records_lot = raw_lot is not None and bool(
        _gc.gncInvoiceGetInvoiceFromLot(qof_instance(raw_lot)))
    if basis_side is None and posted and normal and in_a_records_lot:
        basis_side = posted
    if None in (spending_side, basis_side) or spending_side == basis_side:
        return None
    spent = 'held' if spending_side == 'asset' else 'owed'
    stands_for = 'held' if basis_side == 'asset' else 'owed'
    currency = split_commodity(basis)
    return (f'{COST_BASIS_SPLIT_KEY} {basis_guid!r} is a cost basis of '
            f'{currency} the book {stands_for}, but this split spends '
            f'{split_commodity(selling_split)} the book {spent}. Give a cost '
            f'basis of {currency} the book {spent} — `fx-balances` lists them.')


def a_sale_valued_against_another_cost(selling_split, basis, basis_guid: str,
                                       in_the_book=False) -> Optional[str]:
    """What is wrong where a sale's value is not what its cost basis cost, or None.

    A sale must value what it sells at the cost of the cost basis it picks. That is
    what makes the residual split the realized gain or loss: the currency
    leaves at what it cost, the other splits state what it fetched, and the
    difference is what was made or lost on it. Valuing it at the sale rate
    instead balances the transaction with nothing left over, and the gain
    silently disappears.

    Only asked of a sale priced in the book's own currency. In a transaction
    stated in another currency, a Canadian dollar split states what the
    currency fetched that day, not what it cost, and the transaction has no
    split that can record the difference in Canadian dollars; the balance
    sheet states it as a realized gain the book did not record. Asked of such
    a sale as well, it refused a bank statement's 2,710.68 USD sent at
    3,758.36 CAD, dollars that cost 3,778.15, which is how a bank exports
    every line (`a_usd_deposit_and_three_sales_of_it_each_giving_its_cost_basis.txt`).

    Written as a question rather than a refusal because it is asked twice, of
    two different things. `_require_stated_cost` asks it of a sale in the file
    being imported and refuses. `what_the_disposals_get_wrong` asks it of
    every sale already in the book, which is the only way a cost basis that
    has been re-priced under the sales below it can be caught: those sales are
    in no file, so nothing else looks at them again.
    """
    transaction = selling_split.GetParent()
    if transaction is None or transaction_currency(transaction) != BASE_CURRENCY:
        return None
    if split_moves(selling_split) is not None and _stored_brought_in(selling_split):
        return _a_crossing_valued_against_another_cost(selling_split, basis, basis_guid)
    # Priced: both callers ask this only of a split that establishes a cost
    # basis, and a split establishes one only once something says its cost.
    basis_cost = cost_of(basis)
    sold = drawn_by(selling_split)
    stated = abs(_fraction(selling_split.GetValue()))
    currency = split_commodity(selling_split)
    base_unit = transaction.GetCurrency().get_fraction()
    # Rounded the way the engine rounds before comparing, and then compared
    # exactly. `basis_cost × sold` is a rate times a quantity and lands
    # between cents; the value on the split is what GnuCash booked, which is
    # that figure rounded to the currency's smallest unit. Held apart by half
    # a cent instead — the width of one rounding — the check was an epsilon
    # standing in for arithmetic nobody had done, and it forgave a sale
    # valued half a cent off its cost basis on purpose as readily as one off by
    # accident.
    expected = numeric_to_fraction(to_money(basis_cost * sold, base_unit))
    # Asked of a book, the last disposal is not known: the book keeps no
    # record of the order they were imported in. Nor is it from a file that
    # states the cost basis's balance, as every export does: the balance is
    # what the whole file leaves, 0.00 once it is spent, so every disposal in
    # the file would read as the last, and one in the middle valued at its
    # own share was refused — a book could not be rebuilt from its export. So
    # there one valued at its own share stands, and one valued at what is
    # left, which is looked for only then: it walks the book.
    either = in_the_book or balance_came_from_file(basis)
    if either and stated == expected:
        return None
    left = what_is_left_of_the_cost(selling_split, basis, basis_guid,
                                    draws_down(selling_split), base_unit,
                                    in_the_book)
    if left is not None and not either:
        # The last disposal of a cost basis takes what is left of its cost, so
        # the values of all of them add up to what the currency cost and the
        # residual splits beside them to the realized gain or loss. Each
        # valued at its own share rounded instead, 2,720.00 USD that cost
        # 3,815.89 CAD left at 1.01, 12.06 and 3,802.81, which is 3,815.88,
        # and the book recorded a realized loss of 44.60 where it was 44.61.
        if stated == left:
            return None
        return (
            f'this split sells the last {_format(sold, smallest_unit(selling_split))} '
            f'{currency} of cost basis {basis_guid}, valued at '
            f'{_format(stated, base_unit)} {BASE_CURRENCY}, but cost basis '
            f'{basis_guid} cost {exact_text(basis_cost)} {BASE_CURRENCY} per '
            f'{currency}, and what is left of cost basis {basis_guid} is what '
            f'the last of it cost plus what the rounding of the disposals before '
            f'it left, i.e. {_format(left, base_unit)} '
            f'{BASE_CURRENCY} — value the last of it at that, so the values of '
            f'all of them add up to what the {currency} cost and the residual '
            f'splits to the realized gain or loss')
    if stated in (expected, left):
        return None
    return (
        f'this split sells {_format(sold, smallest_unit(selling_split))} '
        f'{currency} valued at '
        f'{_format(stated, base_unit)} {BASE_CURRENCY}, but cost basis {basis_guid} cost '
        f'{exact_text(basis_cost)} {BASE_CURRENCY} per {currency}, i.e. '
        f'{_format(expected, base_unit)} {BASE_CURRENCY} — value what is sold '
        f'at the cost basis it picks, so the {BASE_CURRENCY} the sale fetched '
        f'and the '
        f'residual gain or loss stand apart')


def what_is_left_of_the_cost(selling_split, basis, basis_guid: str, drawn: Fraction,
                             base_unit: int, drawn_already=False) -> Optional[Fraction]:
    """What is left of a cost basis's cost for the disposal that takes the last of it, or None.

    The disposal takes the last of it where it draws down all the cost basis
    had left before it. On an import that is the balance as it stands, since
    the disposal has not drawn yet. In a book, in an edit of one, or where the
    file stated the balance, it has drawn already, and it is the last where
    nothing is left and no other disposal of the cost basis is dated after it.

    What is left of the cost is what the last of the currency cost, plus what
    each other disposal drew at the cost less what it was valued at — the part
    of the cost the rounding of their values left behind — rounded to the
    cent. None for a disposal that is not the last.
    """
    balance = cost_basis_balance_of(basis)
    if balance is None:
        return None
    drawn_already = drawn_already or balance_came_from_file(basis)
    # Drawn already, the balance is what every disposal left, this one and
    # any after it. So it is the last only where nothing is left and no other
    # disposal is dated after it: once a cost basis is empty, every disposal
    # of it would otherwise read as its last, and the 0.72 USD charge of the
    # 13th could take the rounding of the two dated the 17th. Two of the same
    # day may each be the last, since a book keeps no order within a day.
    if balance != (0 if drawn_already else drawn):
        return None
    this = split_guid(selling_split)
    others = [split for split in iter_splits(selling_split.GetBook())
              if cost_basis_guid_of(split) == basis_guid and split_guid(split) != this]
    when = selling_split.GetParent().GetDate().date()
    if drawn_already and any(other.GetParent().GetDate().date() > when for other in others):
        return None
    return numeric_to_fraction(to_money(
        drawn * cost_of(basis) + what_the_rounding_left(basis, others), base_unit))


def what_the_rounding_left(basis, disposals) -> Fraction:
    """What `disposals` drew at the cost basis's cost, less what they were valued at.

    What each was valued at is its value where its transaction is stated in
    the book's own currency and it lowers the cost basis by all it sends,
    which is the figure the book records it leaving at. Otherwise no figure of
    the book's own says what it took of this cost basis — stated in another
    currency, its value is in none; crossing zero, its value covers what it
    brought in too; sending more than it draws down, the rest moved to another
    account on the same side and still stands on this cost basis — and it took
    exactly what it drew at the cost, which leaves nothing.

    Each value is its share of the cost rounded to the cent, so this is a
    fraction of a cent per disposal: 0.72, 8.60 and 2,710.68 USD at
    381589/272000 valued at 1.01, 12.06 and 3,802.81 leave 0.01 of the
    3,815.89 the dollars cost.
    """
    basis_cost = cost_of(basis)
    return sum((draws_down(split) * basis_cost - abs(_fraction(split.GetValue()))
                for split in disposals
                if transaction_currency(split.GetParent()) == BASE_CURRENCY
                and not (split_moves(split) is not None and _stored_brought_in(split))
                and draws_down(split) == drawn_by(split)), Fraction(0))


def what_the_disposals_left_unrecorded(basis, disposals) -> Fraction:
    """What `disposals` drew at the cost basis's cost, less what the book recorded them at.

    For the balance sheet's `realized_gains_not_recorded`, and nothing else.
    Beside the rounding `what_the_rounding_left` gives, it counts a disposal
    in a transaction stated in another currency, whose Canadian dollar split
    states what it fetched and whose transaction has no split that can record
    the difference. That difference is a realized gain, not rounding, so the
    rule valuing the last disposal of a cost basis at what is left of its
    cost does not read this: it would put one sale's gain on a later one.
    """
    basis_cost = cost_of(basis)
    left = Fraction(0)
    for split in disposals:
        valued = _what_the_book_recorded_it_at(split)
        if (valued is not None
                and not (split_moves(split) is not None and _stored_brought_in(split))
                and draws_down(split) == drawn_by(split)):
            left += draws_down(split) * basis_cost - valued
    return left


def _what_the_book_recorded_it_at(split) -> Optional[Fraction]:
    """What a disposal left the book at in its own currency, or None where no figure says.

    Its value, where its transaction is stated in the book's own currency. In
    one stated in another, the base-currency splits say what it fetched, as
    they price a cost basis there (`_base_per_unit_of`), where it is the only
    split drawing on a cost basis and they value the whole of what it sold.
    Left out, a bank's 2,710.68 USD sent at 3,758.36 CAD and 8.60 at 11.92,
    dollars that cost 3,778.15 and 11.99, were read as having taken exactly
    their cost: the 19.86 CAD they lost was in no figure, and the balance
    sheet stated 19.86 more assets than the book held and did not balance.
    Beside another split drawing on a cost basis the one rate is the average
    of both and says nothing of either, and beside a transfer of the rest
    they value only a fee.
    """
    transaction = split.GetParent()
    value = abs(_fraction(split.GetValue()))
    if transaction_currency(transaction) == BASE_CURRENCY:
        return value
    drawing = sum(1 for each in transaction.GetSplitList() if _says_which(each))
    in_base = [each for each in transaction.GetSplitList()
               if split_commodity(each) == BASE_CURRENCY]
    valued = sum((abs(_fraction(each.GetValue())) for each in in_base), Fraction(0))
    # The base-currency amounts added up, a split of no value among them: a
    # gain or loss booked beside the sale at a value of nothing is part of
    # what the transaction records, and left out it was stated again as a
    # gain not recorded, beside the income account already holding it.
    return (abs(sum((_fraction(each.GetAmount()) for each in in_base), Fraction(0)))
            if drawing == 1 and valued == value else None)


def _a_crossing_valued_against_another_cost(split, basis, basis_guid: str) -> Optional[str]:
    """What is wrong with a split crossing zero valued at anything but what it repaid and brought in.

    Such a split values two things in one figure: what it repaid, at the cost
    of the cost basis it gives, and what it brought in, at the rate the
    transaction fetched it at. 1,000.00 USD of income worth 1,400.00 CAD into
    an account at −500.00 repays 500.00 owed at 1.35, 675.00, and brings in
    500.00 at 1.40, 700.00, so it is valued at 1,375.00 and `$residual$` takes
    the 25.00 the repayment lost (Q-047).

    Valued at 1,400.00 — the day's rate throughout, as GnuCash's register
    writes it — the 25.00 would sit in the held cost basis, costing the 500.00
    at 1.45, and no gain or loss would be stated. Valued at 600.00, what is
    left for the 500.00 brought in is a cost below nothing.

    What the part brought in came at is read from the transaction. Where this
    is its one foreign-currency split, it is what the book-currency splits
    fetched for the whole amount, the `$residual$` split aside. Where another
    split moves the same currency, the part brought in only moved from it, and
    came at the cost of the cost basis that split gives: 500.00 USD from C onto
    a card owing 300.00 repays 300.00 at the card's 1.35 and moves 200.00 at
    C's 1.30, so the card's split is worth 665.00. Beside a second currency,
    or beside splits of this one giving no single cost basis, nothing here can
    say what the part brought in came at, and the value is the file's
    statement of it.
    """
    transaction = split.GetParent()
    currency = split_commodity(split)
    # By guid: GnuCash hands back a new wrapper for the same split on every
    # call, so `is` never matches it.
    this = split_guid(split)
    others = [each for each in transaction.GetSplitList()
              if split_guid(each) != this and split_commodity(each)
              and split_commodity(each) != BASE_CURRENCY]
    same = [each for each in others if split_commodity(each) == currency]
    sources = [each for each in same if cost_basis_guid_of(each)]
    if len(others) != len(same) or (same and len(sources) != 1):
        return None
    amount = abs(_fraction(split.GetAmount()))
    if same:
        source = find_split_by_guid(split.GetBook(), cost_basis_guid_of(sources[0]))
        rate = (cost_of(source) if source is not None else None) or Fraction(0)
    else:
        fetched = abs(sum((_fraction(each.GetValue()) for each in transaction.GetSplitList()
                           if split_commodity(each) == BASE_CURRENCY
                           and not took_the_residual(each)),
                          Fraction(0)))
        rate = fetched / amount
    repaid = drawn_by(split)
    brought_in = brought_in_by(split)
    basis_cost = cost_of(basis)
    base_unit = transaction.GetCurrency().get_fraction()
    expected = numeric_to_fraction(to_money(repaid * basis_cost + brought_in * rate, base_unit))
    stated = abs(_fraction(split.GetValue()))
    if stated == expected:
        return None
    unit = smallest_unit(split)
    return (
        f'this split repays {_format(repaid, unit)} {currency} from cost basis '
        f'{basis_guid} at {exact_text(basis_cost)} {BASE_CURRENCY}/{currency} and '
        f'brings {_format(brought_in, unit)} {currency} in at the '
        f'{exact_text(rate)} {BASE_CURRENCY}/{currency} it came at, '
        f'i.e. {_format(expected, base_unit)} {BASE_CURRENCY}, but is valued at '
        f'{_format(stated, base_unit)} {BASE_CURRENCY} — value it at that, so '
        f'what the repayment realized stands apart in the residual and what it '
        f'brought in is costed at the rate it came at')


def _require_stated_cost(selling_split, basis, basis_guid: str) -> None:
    """Refuse a sale in the file that is valued against another cost."""
    wrong = a_sale_valued_against_another_cost(selling_split, basis, basis_guid)
    if wrong:
        raise Exception(wrong)


def cost_basis_users(book, record) -> List[str]:
    """Descriptions of the transactions measured against this record's cost
    basis, or [] when it has none or nothing has picked it.

    Unposting destroys the posting transaction, and with it the split that *is*
    the cost basis. Anything already measured against it would then name a guid
    the book no longer holds, and re-posting mints a new split with the whole
    amount available again — so a sale of 40 of 100 USD silently becomes 100
    USD available, currency the book no longer has.

    Asked only of a posted record: the importer and `unpost-invoices` /
    `unpost-bills` each check that before they ask.
    """
    posting_txn = record.GetPostedTxn()
    posted_name = get_account_full_name(record.GetPostedAcc())

    basis = next((split for split in posting_txn.GetSplitList()
                  if get_account_full_name(split.GetAccount()) == posted_name),
                 None)
    if basis is None or not establishes_cost_basis(basis):
        return []

    guid = split_guid(basis)
    users = []
    for split in iter_splits(book):
        if cost_basis_guid_of(split) != guid:
            continue
        transaction = split.GetParent()
        label = transaction.GetDescription() or '(no description)'
        date = transaction.GetDate().strftime('%Y-%m-%d')
        users.append(f'{date} {label!r} '
                     f'({_format(abs(_fraction(split.GetAmount())), smallest_unit(split))} '
                     f'{split_commodity(split)})')
    return users


def disposals_drawing_on(book, basis_split, still_draws=lambda split: True) -> List[str]:
    """Descriptions of every disposal measured against this one cost basis.

    `transactions_measuring_against` asks the same question of a whole
    transaction, for the delete guard. Linking a payment discards the cost basis on
    a single split, so it has to ask about that split by itself.

    `still_draws` leaves out a disposal that will not draw on it once the file
    is applied: under `--atomic`, a fee the same file restates onto another
    cost basis (Q-053).

    Read from `splits_drawing_on`'s index of the book rather than a walk of
    every split, once for each cost basis a link discards.
    """
    found = []
    for split in splits_drawing_on(book, split_guid(basis_split)):
        if not still_draws(split):
            continue
        parent = split.GetParent()
        label = parent.GetDescription() or '(no description)'
        found.append(f"{parent.GetDate().strftime('%Y-%m-%d')} {label!r} "
                     f'({_format(abs(_fraction(split.GetAmount())), smallest_unit(split))} '
                     f'{split_commodity(split)})')
    return found


def is_a_spent_credit(split) -> bool:
    """Was this split an owner's credit that has since settled a record?

    A credit is money owed back to a customer or a vendor, and settling their
    next invoice or bill with it is ordinary bookkeeping — the commonest thing
    an overpayment is for. The split that was the credit becomes that
    settlement, so it stops being a cost basis, and a sale already measured
    against the credit is left giving its guid.

    That is a cost basis which was consumed, not one that never was, and the two
    have to be told apart: the first is history and the second is a mistake.

    **Two things are asked, and the mark alone is not enough.** A file may
    write `applied_from_credit` — the export emits it and fixtures state it, so
    unlike `orphaned_by_unpost` it is not a key only this book can know.

    What this decides is not whether a sale is refused: `_validate_pick`
    refuses a guid that gives a split which is no cost basis whatever is
    written beside it. It decides whether the export leaves that guid out of
    the file, and whether `--verify-costs` reports the sale. Believed on the
    mark alone, a file could write it onto any split and have this tool omit a
    guid that does measure against something, and go quiet about a sale that
    draws on nothing.

    So the book is asked too: the split has to be in a lot that a record owns,
    which is what settling an invoice or a bill with a credit does and what no
    file can assert on its own behalf. Unposting that record empties the lot of
    its invoice again (CLAUDE.md finding 10), and the answer is then no — which
    is right, because the credit is loose and spendable once more.
    """
    if str(get_custom_metadata(split).get(APPLIED_FROM_CREDIT_KEY, '')
           ).strip().lower() != 'true':
        return False
    raw_lot = split.GetLot()
    if raw_lot is None:
        return False
    # Not wrapped in a catch-all, for `_is_prepayment`'s reason: a binding that
    # rejects this pointer must surface rather than turn every spent credit
    # into a refusal.
    return bool(_gc.gncInvoiceGetInvoiceFromLot(qof_instance(raw_lot)))


def move_disposals_to_the_new_basis(book, spent_guid: str, remainder) -> int:
    """Give every disposal that draws on the spent split the remainder's guid.

    Spending part of an owner's credit divides the split it comes from. The
    part applied keeps the source split's guid and is a settlement afterwards,
    so it is no cost basis; the currency still unsold moves to the remainder,
    which is a new split with a guid of its own. A disposal already measured
    against that credit still gives the old guid, and that guid now matches a
    settlement.

    Nothing about the disposal itself changes. It sold the currency it sold, at
    the cost it sold it at, out of the same pool — only the split holding what
    is left of that pool is a different one now, so the disposal is given its
    guid.

    Left undone, the disposal draws on a split that is no cost basis:
    `what_the_disposals_get_wrong` reports it, `--verify-costs` exits 1, and
    the export writes the old guid into `cost_basis_split_guid:`, so the book's
    own ledger is refused on the way back in.

    **It walks the book, once per credit divided**, and no index is kept
    across those walks. A disposal drawing on the credit can be any split in
    the book — that is the difference from `_priced_bases_in`, which was
    narrowed to the transactions a payment block touches — so the walk itself
    cannot be scoped. An index built at the start of a run would be stale in
    the one place it matters: a file may write a sale against a credit in one
    block and spend that credit in a later one, and a lookup that had not seen
    the sale would leave it drawing on the settlement, which is the fault this
    exists to prevent. Keeping one correct means every writer of
    `cost_basis_split_guid:` updating it, and the file-stated keys go through
    the generic custom-metadata path, which knows nothing about cost bases.

    What a walk costs is one commodity read per split, and a slot read only
    for the splits holding the currency this credit is in — a disposal takes
    units out of the pool it draws on, so the two are the same currency, and
    a book's splits are mostly in the book's own. A disposal that gives a
    basis of another currency is a fault `--verify-costs` reports by itself
    (`a_sale_against_another_currencys_basis`); it is not repaired here, and
    following it onto the remainder would not make it right.

    Returns how many disposals were given the new guid.
    """
    new_guid = split_guid(remainder)
    currency = split_commodity(remainder)
    moved = 0
    for split in iter_splits(book):
        if split_commodity(split) != currency:
            continue
        if cost_basis_guid_of(split) != spent_guid:
            continue
        transaction = split.GetParent()
        metadata = dict(get_custom_metadata(split))
        metadata[COST_BASIS_SPLIT_KEY] = new_guid
        # Bracketed, like every other KVP write: one written outside an edit
        # does not mark the transaction dirty, so it never reaches disk.
        transaction.BeginEdit()
        set_custom_metadata(split, metadata)
        transaction.CommitEdit()
        moved += 1
    return moved


def transactions_measuring_against(book, transaction) -> List[str]:
    """Descriptions of what measures against any cost basis this transaction
    establishes — what would be orphaned if it were deleted."""
    basis_guids = {split_guid(split) for split in transaction.GetSplitList()
                   if establishes_cost_basis(split)}
    if not basis_guids:
        return []

    users = []
    for split in iter_splits(book):
        if cost_basis_guid_of(split) not in basis_guids:
            continue
        parent = split.GetParent()
        if parent.GetGUID().to_string() == transaction.GetGUID().to_string():
            continue
        label = parent.GetDescription() or '(no description)'
        users.append(f"{parent.GetDate().strftime('%Y-%m-%d')} {label!r} "
                     f'({_format(abs(_fraction(split.GetAmount())), smallest_unit(split))} '
                     f'{split_commodity(split)})')
    return users


def transactions_drawing_on(book, transaction, bases) -> List[tuple]:
    """`(guid, description)` of each transaction that must be deleted before this one.

    `bases` is the guids of this transaction's cost bases, as the book holds
    them. They are given rather than read here, because a transaction still
    open for an edit reads as the edit leaves it: a split moved onto a
    Canadian dollar account opens no cost basis there, and whatever draws on
    it would be missed.

    Every transaction drawing on this one's cost bases, and every transaction
    drawing on theirs, and so on: a conversion drawn on this one's dollars
    opens a cost basis of its own, and a fee drawn on that keeps the
    conversion from being deleted in turn. Listed in an order
    `delete-transactions` accepts, each after everything drawing on it, and
    each once. A description gives what each draws on any cost basis, added
    up by currency across its splits.
    """
    ordered: Dict[str, str] = {}
    visiting = {transaction.GetGUID().to_string()}

    def delete_before(its_bases) -> None:
        drawers = {split.GetParent().GetGUID().to_string(): split.GetParent()
                   for basis in its_bases for split in splits_drawing_on(book, basis)}
        for guid, parent in sorted(drawers.items(), key=lambda item: item[1].GetDate()):
            # A transaction drawing on two cost bases of the chain is reached
            # twice, and is listed once; the transaction the chain starts from
            # is not listed at all.
            if guid in visiting or guid in ordered:
                continue
            visiting.add(guid)
            delete_before(split_guid(split) for split in parent.GetSplitList()
                          if establishes_cost_basis(split))
            by_commodity: Dict[str, list] = {}
            for split in parent.GetSplitList():
                if cost_basis_guid_of(split):
                    by_commodity.setdefault(split_commodity(split), []).append(split)
            drawn = ', '.join(
                f'{_format(sum(abs(_fraction(s.GetAmount())) for s in splits), smallest_unit(splits[0]))} '
                f'{commodity}' for commodity, splits in sorted(by_commodity.items()))
            label = parent.GetDescription() or '(no description)'
            ordered[guid] = f"{parent.GetDate().strftime('%Y-%m-%d')} {label!r} ({drawn})"

    delete_before(bases)
    return list(ordered.items())


def cost_basis_facts(transaction) -> List[tuple]:
    """What this transaction's cost bases are and what its disposals draw, as facts to compare.

    An edit in place is accepted when these are the same after it as before
    it: the edit then leaves what each cost basis holds and cost as it was,
    and what each disposal draws and is valued at, and every other figure in the transaction
    is the file's to correct.

    - A cost basis: its split, the account it sits on, its currency and side,
      what it brought in, what it cost, and its date. The account counts,
      because the accounts drawn on a cost basis hold what it stands for:
      moved to another bank, it would leave a disposal spending from the
      first drawing on a cost basis kept on the second. The date counts, because it is when the currency
      arrived, and every reading of the cost bases as of a day turns on it.
    - A disposal: its split, its account, the cost basis it gives, the side it
      draws on, what it draws down, its value, which is what that cost basis
      cost, and its date, which is when it drew the cost basis down.

    Everything else is left out: the account of a split in the book's own
    currency that sets a rate, how the rate's totals are divided between such
    splits, a memo, a description.

    Read on a committed transaction: until the commit, GnuCash still lists
    the splits an open edit has destroyed.
    """
    facts = []
    when = transaction.GetDate().strftime('%Y-%m-%d')
    for split in transaction.GetSplitList():
        guid = split_guid(split)
        name = get_account_full_name(split.GetAccount())
        commodity = split_commodity(split)
        if establishes_cost_basis(split):
            facts.append(('basis', guid, name, commodity,
                          'asset' if _fraction(split.GetAmount()) > 0 else 'liability',
                          brought_in_by(split), cost_of(split), when))
        picked = cost_basis_guid_of(split)
        if picked:
            facts.append(('draws', guid, name, commodity, picked, the_side_it_draws(split),
                          draws_down(split), abs(_fraction(split.GetValue())), when))
    return sorted(facts, key=str)


def a_disposal_the_finished_book_cannot_value(book, transaction) -> str:
    """A disposal on this transaction's cost bases that no later check can value.

    `a_sale_valued_against_another_cost` is what asks, of a book rather than of
    a file, whether a disposal is still valued at what its cost basis cost — and it
    answers only for a disposal stated in the book's own currency, because a
    transaction between two foreign currencies states its values in neither.

    That matters to one caller. `--atomic` defers the refusal to edit a
    transaction a cost basis rests on, on the understanding that the finished
    book asks the same questions afterwards; where every disposal beneath a
    basis is foreign-stated, it cannot. Measured: a 100.00 USD purchase at
    1.40 with a USD-stated 10.00 USD fee drawn on it, re-priced to 1.50 under
    `--atomic --strategy update`, exited 0, saved, and `--verify-costs` called
    the book sound.

    Returns the first such disposal, described the way the delete guard
    describes them, or `''`.

    It walks the book, and it is asked once per transaction an `--atomic` run
    edits that holds a cost basis — so a repair of three blocks walks it three
    times. The transaction's own currency is read before the KVP, because a
    disposal stated in the book's own currency cannot be one of these however
    it is measured, and a book's transactions are mostly in that currency.

    A disposal in the edited transaction itself is not one of them. Its value
    is read through the same base-currency splits that price the cost basis it
    draws on, so the file states both, and a re-price moves them together.
    """
    here = {split_guid(split) for split in transaction.GetSplitList()}
    # Asked only of a transaction whose cost basis another draws on, so there
    # is a cost basis to walk for.
    basis_guids = {split_guid(split) for split in transaction.GetSplitList()
                   if establishes_cost_basis(split)}
    for split in iter_splits(book):
        parent = split.GetParent()
        if parent is None or transaction_currency(parent) == BASE_CURRENCY:
            continue
        if cost_basis_guid_of(split) not in basis_guids or split_guid(split) in here:
            continue
        label = parent.GetDescription() or '(no description)'
        return (f"{parent.GetDate().strftime('%Y-%m-%d')} {label!r} "
                f'({_format(abs(_fraction(split.GetAmount())), smallest_unit(split))} '
                f'{split_commodity(split)}, stated in '
                f'{transaction_currency(parent)})')
    return ''


def require_no_cost_basis_dependents(book, transaction, label: str) -> None:
    """Refuse to delete a transaction whose cost basis something measures against.

    Deleting it destroys the split the cost basis lives on, leaving those
    transactions giving a guid the book no longer holds — the export then fails
    to re-import, and nothing gives them their currency back. The mirror of the
    unpost guard, for the other way a cost basis can be destroyed.
    """
    users = transactions_measuring_against(book, transaction)
    if not users:
        return
    listed = '; '.join(sorted(users))
    raise ValueError(
        f'{label} cannot be deleted: it establishes a cost basis that '
        f'{len(users)} transaction(s) measure against — {listed}. Deleting it '
        f'would leave them giving a split the book no longer holds. Delete '
        f'those first.')


def require_cost_basis_unused(book, record, kind: str, ident: str) -> None:
    """Refuse to unpost a record whose cost basis something is measured against."""
    users = cost_basis_users(book, record)
    if not users:
        return
    listed = '; '.join(sorted(users))
    raise Exception(
        f'{kind} {ident!r} cannot be unposted: its cost basis is what '
        f'{len(users)} transaction(s) measure against — {listed}. Unposting '
        f'destroys the split that cost basis lives on, and re-posting creates a new '
        f'one with the whole amount available again, so those transactions '
        f'would be measured against a cost basis the book no longer has. '
        f'Remove or re-point them first.')


def what_the_disposals_get_wrong(book) -> List[Dict]:
    """Findings for every disposal the book can no longer justify.

    Two questions, asked of each sale that gives a `cost_basis_split_guid:`,
    and only ever one of them per sale: what the guid gives either is a cost
    basis or is not, and each answer has its own question to follow.

    **Where it is not a cost basis, or no split at all.**

    The other half of `_a_figure_on_a_split_that_is_no_basis`. That one finds a
    balance left where nothing reads it; this finds what was drawing on it,
    which survives the balance being cleared and is invisible once it is: no
    figure is stored anywhere wrong, so every other check passes, and the book
    reads sound while a disposal is measured against something that is not a
    cost basis.

    It shows up on the way out. The export writes the guid, and re-importing
    that ledger is refused by `_validate_pick` — so a book whose own export
    cannot rebuild it would otherwise be reported as sound.

    A cost basis the book consumed is not one of these. An owner's credit spent on
    their next invoice or bill ends the pool it was, and the sale that drew on
    it beforehand keeps giving its guid — the book's own record of where that
    currency came from, and not a fault.

    The import is not asked to take it. `_validate_pick` refuses a guid that
    gives a split which is no cost basis, for any split however it is marked,
    and the file carries no such guid to refuse: the export drops it
    (`_the_basis_it_gives_was_spent`), the way it drops a `cost_basis_cost` on
    a split that is no cost basis. So the ledger rebuilds the book without the
    line, and what `is_a_spent_credit` decides here is only whether this
    reports — a pool that was used up, against a guid that was never a cost basis.

    **Where it is a cost basis, the questions `_validate_pick` asks of a sale
    in a file, asked of the sales already in the book**: that the cost basis holds
    the currency the sale sells, that the sale is still valued at what that
    basis cost, and that a receivable it draws on has been collected. All are
    asked of a file and only of a file, so a sale already in the book is never
    asked again — and `import --atomic` defers `_require_no_cost_basis_edit`,
    which on the update path was the only thing standing in their place,
    `update_transaction` never calling `apply_cost_basis_picks` at all.

    So a block may restate a cost basis transaction's `value:` under the sales below
    it, or state a balance on a receivable the customer has not paid and sell
    against it. A 10.00 USD fee valued at 14.00 CAD against a cost basis re-priced
    from 1.40 to 1.50 leaves every other check satisfied — the balance is
    within its bounds, no stored cost disagrees, the cost basis is real, the totals
    level — while the book's own export is refused on re-import because 14.00
    is not 1.50 × 10. Selling 40.00 USD against an uncollected invoice levels
    the totals too, and is currency the book does not hold. And a block may
    re-point a disposal at a cost basis holding another currency: the figures do
    not move, which is what the deferred guard reads, so a 10.00 USD fee ends
    up drawing on a EUR pool — and where the two cost bases cost the same figure
    the valuation question has nothing to say about it either.

    One walk, and the splits are indexed by guid rather than searched per
    disposal: a book with many disposals and many splits would otherwise cost
    the product of the two.
    """
    by_guid = {split_guid(split): split for split in iter_splits(book)}
    found: List[Dict] = []
    for split in by_guid.values():
        picked = cost_basis_guid_of(split)
        if not picked:
            continue
        basis = by_guid.get(picked)
        try:
            if basis is not None and (establishes_cost_basis(basis)
                                      or is_a_spent_credit(basis)):
                # The currency question is asked of a pool the book consumed
                # as well. What that exempts a spent credit from is being
                # reported as no cost basis — it was one, and the sale that
                # drew on it is history rather than a fault — and a pool of
                # euros still has no US dollars in it to have sold. Asked
                # only of a live cost basis, a re-point onto a spent credit of
                # another currency committed under `--atomic` while the same
                # re-point onto a live one was rolled back, and the book was
                # left mismatched with nothing having said so.
                wrong = a_sale_against_another_currencys_basis(
                    split, basis, picked)
                if not wrong and establishes_cost_basis(basis):
                    wrong = (
                        a_sale_valued_against_another_cost(
                            split, basis, picked, in_the_book=True)
                        or a_sale_against_an_uncollected_receivable(
                            split, basis, picked, in_the_book=True))
                if not wrong:
                    continue
                problem = wrong
            else:
                reason = ('which matches no split in the book' if basis is None
                          else f'which is no cost basis: '
                               f'{why_it_is_no_basis(basis)}')
                problem = (
                    f'this split draws on cost basis {picked}, {reason}. '
                    f'Nothing can be measured against it, and the export '
                    f'writes that guid out, so this book\'s own ledger will '
                    f'not re-import.')
        except Exception as unreadable:
            # The exception's own words, because not every failure here is a
            # basis whose figures will not read: `cost_basis_force:` on the
            # sale is checked by `_a_yes_or_no`, which refuses a mistyped
            # flag, and reported as an unreadable cost basis that reader would go
            # and look at the wrong split.
            problem = (f'this split draws on cost basis {picked}, and what is '
                       f'measured against it could not be read: {unreadable}. '
                       f'The export writes that guid out, so this book\'s own '
                       f'ledger will not re-import.')
        transaction = split.GetParent()
        found.append({
            'guid': split_guid(split),
            'account': get_account_full_name(split.GetAccount()),
            'date': (transaction.GetDate().strftime('%Y-%m-%d')
                     if transaction is not None else ''),
            'description': (transaction.GetDescription() or ''
                            if transaction is not None else ''),
            'tx_guid': (transaction.GetGUID().to_string()
                        if transaction is not None else ''),
            'problems': [problem],
        })
    return found


def why_it_is_no_basis(split) -> str:
    """Why this split is not a cost basis.

    Asked of two splits, and of any split either way. Of one carrying a
    cost-basis figure, where the answer is about a figure someone meant to be
    read; and of whatever split a disposal draws on, which need carry no
    cost-basis key at all. The reasons are `establishes_cost_basis`'s own, in
    its order, each said as the thing to go and look at rather than as the
    predicate that failed.
    """
    account = split.GetAccount()
    commodity = account.GetCommodity()
    if commodity is None:
        # A book GnuCash loads and keeps can hold a split on an account with
        # no commodity
        # (tests/research/whether_a_reload_keeps_a_security_currency_or_an_account_with_no_commodity_probe.py).
        return (f'its account {get_account_full_name(account)!r} has no '
                f'commodity, so the split holds no currency for a cost basis '
                f'to be about')
    currency = commodity.get_mnemonic()
    if currency == BASE_CURRENCY:
        return (f'it is a {currency} split, and a cost basis is about '
                f'currency the book does not count in')
    if cost_basis_guid_of(split):
        return ('it picks another split\'s cost basis, so it is a disposal '
                'rather than a source')
    amount = _fraction(split.GetAmount())
    if amount == 0:
        return 'it moves nothing, so it brought no currency in'
    account_type = account.GetType()
    if account_type in (ACCT_TYPE_RECEIVABLE, ACCT_TYPE_PAYABLE):
        # A business account is the one place where direction alone does not
        # answer it, so saying "it lowers this account's currency" here is
        # sometimes the opposite of what the split does. A refund is a debit
        # on a receivable, exactly like a posting, and it sends the customer's
        # money back; a prepayment is a credit on one, exactly like a
        # settlement, and it is currency the book holds.
        moves_the_normal_way = (amount > 0
                                if account_type == ACCT_TYPE_RECEIVABLE
                                else amount < 0)
        if moves_the_normal_way and _is_prepayment(split):
            return (f'it settles an owner\'s credit rather than posting a '
                    f'record, so it sends {currency} back rather than '
                    f'bringing any in')
        if (not moves_the_normal_way and _is_prepayment(split)
                and _currency_arrived_elsewhere(split)):
            return (f'another split in its transaction already brings that '
                    f'{currency} in, at a cost of its own, so counting this '
                    f'one as well would offer the same money twice')
    if not _raises_a_foreign_balance(split, account, amount):
        return (f'it lowers this account\'s {currency} rather than raising it, '
                f'so it spends currency rather than bringing it in')
    # A cost it has, and still no cost basis: what it brought onto its side of
    # the book, the same transaction took off it.
    if cost_of(split) is not None and _only_moved_within_one_side(split, account, amount):
        return (f'it moves {currency} between accounts on one side of the book, '
                f'and no more arrived on that side than left it, so there is '
                f'nothing to open a cost basis for. A spend out of this account '
                f'gives the guid of the cost basis the {currency} came from')
    # The one question `establishes_cost_basis` asks after all of the above,
    # and both callers ask this only of a split it said no to — so its cost is
    # what is missing.
    return ('nothing says what its currency cost: every split in its '
            f'transaction is {currency}, so there is no {BASE_CURRENCY} '
            f'figure to divide, and no `{COST_BASIS_COST_KEY}` is stored '
            f'on it either')


def _a_figure_on_a_split_that_is_no_basis(split) -> Optional[Dict]:
    """A finding for a cost basis balance stored where nothing will read it.

    This is the fault hardest to notice, and every other check misses
    it by construction: `fx-balances` lists cost bases, so a balance on a split
    that is not one never appears; the checks below walk the same cost bases, so
    they call the book sound; and the export writes the key back out, so the
    ledger will not rebuild the book it came from — a re-import either refuses
    the line or opens a cost basis nobody asked for. The reported Q-040 book held
    2,719.28 USD this way.

    The balance alone. A stored `cost_basis_cost` on a split that is no
    basis is genuinely inert: `_stored_cost_is_ignorable` drops it from the
    export, so it neither travels nor round-trips, and reporting it would set
    the exit code over a figure the file it produces does not contain.
    """
    metadata = dict(get_custom_metadata(split))
    if metadata.get(COST_BASIS_BALANCE_KEY) in (None, ''):
        return None
    stated = f'{COST_BASIS_BALANCE_KEY}: {metadata[COST_BASIS_BALANCE_KEY]!r}'
    transaction = split.GetParent()
    return {
        'guid': split_guid(split),
        'account': get_account_full_name(split.GetAccount()),
        'date': (transaction.GetDate().strftime('%Y-%m-%d')
                 if transaction is not None else ''),
        'description': (transaction.GetDescription() or ''
                        if transaction is not None else ''),
        'tx_guid': (transaction.GetGUID().to_string()
                    if transaction is not None else ''),
        'problems': [
            f'this split stores {stated}, but it is no cost basis: '
            f'{why_it_is_no_basis(split)}. Nothing reads that figure — it is '
            f'absent from the listing and from every check below — and the '
            f'export writes it back out, so a book rebuilt from this one\'s '
            f'ledger holds the same figure in the same place. Nothing clears '
            f'it but saying so: `cost_basis_balance: ""` on this split in a '
            f'`--strategy update` file.'],
    }


def verify_cost_bases(book, totals: bool = True) -> Dict:
    """Check every cost basis against the ledger, and report what disagrees.

    Returns `{'checked': n, 'findings': [...]}` — how many cost bases were examined,
    which is the whole book regardless of what a listing filters to, and one
    entry per cost basis with something wrong with it.

    `totals=False` leaves `currency_totals` empty and skips the walk that
    fills it. That comparison is a warning `--verify-costs` prints and nothing
    refuses over, so the caller that asks whether a file may be committed does
    not read it — and it is its own pass over every split in the book, run
    twice on an `--atomic` run, once before the file and once after.

    A cost is derived from the ledger, so it is only ever as right as the
    ledger is consistent. Two things can be checked, and each can fail:

    * **A cost basis balance is not above what its cost basis brought in, nor below
      zero.**
      Two exact comparisons against figures the book holds — zero, and the
      amount the split brought in — not a tolerance or a window. Balances move
      only by what a sale takes and what one gives back, so a balance above
      what arrived is currency offered that never did, and one below zero is a
      sale no ledger records.
    * **A stored `cost_basis_cost` agrees with the transaction, and parses.**
      Nothing writes one where the transaction states a cost, so finding both
      means a copy has drifted — and since the transaction is what is
      believed, the copy would otherwise sit unread and unnoticed.

    Both are exact questions about figures the ledger states. Two inexact ones
    were tried here and removed, because a check that reports correct books is
    worse than no check:

    * a split's `share_price` against its value. GnuCash stores no rate —
      `xaccSplitGetSharePrice` computes value over amount on demand — so the
      comparison was one number against itself and could not fail.
      (`SetSharePrice(1.405)` on 45.00 USD writes value 63.23 and reads the
      rate back as 6323/4500; set the value to 63.00 and it reads 6300/4500.)
    * whether a transaction's base-currency splits agree about its rate. Rates
      run **forward only**. A file states 1.405, 45.00 USD becomes 63.23 CAD,
      and the effective rate the ledger then carries is 6323/4500 — 1.405 plus
      1/9000. That is the rounding working, not a discrepancy, and asking
      whether 6323/4500 maps back to 1.405 is a question with no answer: many
      rates produce the same rounded figure, and the one the file stated is
      not among the things the ledger keeps. Every criterion tried in that
      backwards direction reported correct books — the splits' ratios against
      each other (every foreign invoice with tax), each against the rate the
      splits add up to (a bill of 1.819 CAD for 1.30 USD beside 5.00 for 3.57,
      which 1.3992 produces exactly), and the windows the rounding leaves.
      That added-up rate is still what a cost is derived from, because it does
      not depend on split order; it is simply not evidence about itself.

    Read-only, and reported rather than raised: this answers "is what the book
    says internally consistent", which is a question to ask of a book already
    written, not a reason to refuse to read it.
    """
    checked = 0
    found: List[Dict] = []
    for split in iter_splits(book):
        # Every split is checked and every finding kept: a book is verified to
        # learn everything wrong with it, so stopping at the first — or letting
        # one split's failure end the pass — would hide the rest behind it.
        try:
            if not establishes_cost_basis(split):
                stranded = _a_figure_on_a_split_that_is_no_basis(split)
                if stranded is not None:
                    found.append(stranded)
                continue
        except Exception:
            # Deciding whether this is a cost basis at all is what failed, so
            # nothing further about it can be said. It counts as one cost basis
            # examined, once.
            checked += 1
            found.append({
                'guid': split_guid(split),
                'account': get_account_full_name(split.GetAccount()),
                'date': '', 'description': '', 'tx_guid': '',
                'problems': ['this cost basis could not be read at all'],
                'traceback': traceback.format_exc(),
            })
            continue

        checked += 1
        # Not guarded: every figure the trace reads was read without failing
        # a moment ago to decide this is a cost basis, and the one that can
        # fail — a stored cost that will not parse — the trace catches itself.
        row = cost_trace(split)

        problems = []

        if row['malformed_balance']:
            # Reported rather than silently read as an empty cost basis, which is
            # what a balance that will not parse otherwise becomes: the
            # listing would say nothing is left, about a split whose balance
            # something wrote and something has since broken. A stored *cost*
            # that will not parse has always been reported; this is the same
            # fault on the other key.
            problems.append(
                f"{COST_BASIS_BALANCE_KEY} reads "
                f"{row['malformed_balance']!r}, which is not a number — nothing "
                f"can be sold against this cost basis until it is corrected, and "
                f"it reads as empty meanwhile")

        available = row['balance']
        brought_in = brought_in_by(split)
        if available is not None and (available < 0 or available > brought_in):
            # Written exactly, not through the currency's smallest unit: the
            # figure is being reported *because* it is past one of those two
            # bounds, and rounding it to the cent is how "100.001 against
            # 100.00" became a message saying 100.00 against 100.00.
            problems.append(
                f"cost basis balance is "
                f"{_format(available, row['unit'])} {row['currency']} "
                f"against the {_format(brought_in, row['unit'])} this "
                f"cost basis brought in — a balance can only fall by what a "
                f"sale "
                f"takes and rise by what one gives back")

        if row['stored_error']:
            problems.append(
                f"{row['stored_error']}. The transaction says "
                f"{exact_text(row['derived'])} "
                f"{BASE_CURRENCY}/{row['currency']}, which is what is used"
                if row['derived'] is not None else row['stored_error'])
        elif (row['stored'] is not None and row['derived'] is not None
                and row['stored'] != row['derived']):
            problems.append(
                f"{COST_BASIS_COST_KEY} says {exact_text(row['stored'])} "
                f"{BASE_CURRENCY}/{row['currency']}, but the transaction says "
                f"{exact_text(row['derived'])} — the transaction is what is used")

        if problems:
            found.append({**row, 'problems': problems, 'traceback': None})

    # Asked of the disposals rather than of the cost bases, so it is outside the
    # walk above: what is wrong is the split doing the drawing, and the split
    # it draws on may not be a cost basis to have been walked at all.
    found.extend(what_the_disposals_get_wrong(book))
    found.extend(what_the_pending_disposals_get_wrong(book))

    return {'checked': checked, 'findings': found,
            'currency_totals':
                currency_totals_that_disagree(book) if totals else []}


def currency_totals_that_disagree(book) -> List[Dict]:
    """Per currency: what its cost bases hold between them against what the ledger
    says arrived and was sold. One entry per currency where the two differ.

    The book-wide question, which no per-basis check can answer. Every cost basis
    can pass on its own — a balance between zero and what it brought in — while
    the currency does not add up: take 80.00 off one cost basis of a book holding
    200.00 and record no sale, and each cost basis is still within its own bounds
    while 80.00 USD is accounted for by nothing.

    The two sides are written by different mechanisms, which is what makes the
    comparison worth anything. What the cost bases hold is a KVP on each split; what
    arrived and what was sold are the transactions themselves — a cost basis's own
    amount, and the amount of every split giving one. Neither is derived from
    the other, so they can disagree.

    A cost basis with no balance recorded is left out of both sides. Nothing knows
    how much of it is unsold — that is what `none recorded` means — so counting
    what it brought in would report every such book as holding exactly that
    much less than arrived.
    Nothing can be sold against one either, so no sale is dropped with it.

    Reported rather than refused: this says a book needs looking at, and the
    listing beside it is the thing to look at. What put the two out of step is
    not something the book records.
    """
    held: Dict[str, Fraction] = {}
    arrived: Dict[str, Fraction] = {}
    sold: Dict[str, Fraction] = {}
    units: Dict[str, int] = {}
    sales = []
    counted: set = set()
    for split in iter_splits(book):
        currency = split_commodity(split)
        if not currency or currency == BASE_CURRENCY:
            continue
        named = cost_basis_guid_of(split)
        # A split giving a guid is a sale of what it draws, and a split crossing
        # zero is an arrival of what it brought in besides (Q-047), so one
        # split can be counted on both sides below.
        if named:
            sales.append((currency, draws_down(split), named))
        try:
            if not establishes_cost_basis(split):
                continue
            amount = brought_in_by(split)
            balance = cost_basis_balance_of(split)
        except Exception:
            # A cost basis whose own figures cannot be read is reported by the
            # per-basis pass with its traceback. Counting it here would put what
            # it brought in on the arrived side with no balance to set against
            # it, so what the cost bases hold would come to less than what
            # arrived, and the currency would be blamed for the gap.
            continue
        if balance is None:
            continue
        held[currency] = held.get(currency, Fraction(0)) + balance
        arrived[currency] = arrived.get(currency, Fraction(0)) + amount
        units.setdefault(currency, smallest_unit(split))
        counted.add(str(split_guid(split)).replace('-', '').lower())

    # A sale counts only where the cost basis it names is one of the cost bases counted
    # above. Counted unconditionally, a sale against a cost basis left out of the
    # other side — one with no balance recorded, or one whose figures do not
    # read — took the ledger figure down while nothing took the cost basis's own
    # arrival down with it, and the run warned that currency was accounted for
    # by no cost basis on a book that is perfectly consistent. Both sides skip the
    # same cost bases or neither does.
    for currency, amount, named in sales:
        if named in counted:
            sold[currency] = sold.get(currency, Fraction(0)) + amount

    out: List[Dict] = []
    for currency in sorted(set(held) | set(arrived)):
        ledger = (arrived.get(currency, Fraction(0))
                  - sold.get(currency, Fraction(0)))
        between_them = held.get(currency, Fraction(0))
        if between_them == ledger:
            continue
        out.append({
            'currency': currency,
            'unit': units.get(currency, 100),
            'held': between_them,
            'arrived': arrived.get(currency, Fraction(0)),
            'sold': sold.get(currency, Fraction(0)),
            'ledger': ledger,
            'difference': ledger - between_them,
        })
    return out


def cost_trace(split) -> Dict:
    """Every figure this split's cost is computed from, and what came out.

    The record a reader needs to judge a disagreement: the two guids to open
    the book at, the amount and value the ledger carries, each factor of the
    derivation, every rate the transaction's base-currency splits imply, and
    both answers — the one derived and the one stored — with which is used.
    """
    transaction = split.GetParent()
    currency = transaction.GetCurrency() if transaction is not None else None
    tx_currency = transaction_currency(transaction) if transaction is not None else ''
    tx_unit = currency.get_fraction() if currency is not None else 100
    amount = abs(_fraction(split.GetAmount()))
    value = abs(_fraction(split.GetValue()))

    # The factors the derivation actually multiplied, in order, and only
    # those. A transaction already in the book's currency needs no second
    # factor — its splits are valued in CAD, so `value / amount` is the whole
    # cost — and reporting a 1 there would be stating something the code never
    # computed. Where a second factor is needed and missing, it is listed as
    # missing rather than left out, because that is why no cost came of it.
    tx_rate = (_base_per_unit_of(transaction)
               if transaction is not None and tx_currency != BASE_CURRENCY
               else None)
    # Never a zero amount: this is asked only of a split that establishes a
    # cost basis, and one that moves nothing establishes none.
    factors = [('value / amount', value / amount)]
    if tx_currency != BASE_CURRENCY:
        factors.append((f'{BASE_CURRENCY} per {tx_currency}', tx_rate))
    derived = derived_cost_of(split)
    # `cost_of` never reaches a stored cost on a split the transaction prices,
    # so a malformed one there is inert to everything else — but this reads it
    # deliberately, and a cost basis that is otherwise entirely readable must not
    # become "could not be read at all" over a line nothing uses. What went
    # wrong is carried as a finding instead, on a row that still has the
    # derived cost, the amounts and the rate in it.
    stored, stored_error = None, ''
    try:
        stored = stated_cost_of(split)
    except Exception as exc:
        stored_error = str(exc)
    return {
        'guid': split_guid(split),
        'tx_guid': (transaction.GetGUID().to_string().replace('-', '').lower()
                    if transaction is not None else ''),
        'account': get_account_full_name(split.GetAccount()),
        'date': (transaction.GetDate().strftime('%Y-%m-%d')
                 if transaction is not None else ''),
        'description': (transaction.GetDescription()
                        if transaction is not None else ''),
        'currency': split_commodity(split),
        'unit': smallest_unit(split),
        'tx_currency': tx_currency,
        'tx_unit': tx_unit,
        'amount': amount,
        'value': value,
        'factors': factors,
        'tx_rate': tx_rate,
        'base_figures': _base_figures_of(transaction, tx_currency),
        'balance': cost_basis_balance_of(split),
        'malformed_balance': malformed_cost_basis_balance_of(split),
        'derived': derived,
        'stored': stored,
        'stored_error': stored_error,
        'used': derived if derived is not None else stored,
    }


def _base_figures_of(transaction, tx_currency: str) -> List:
    """Each base-currency split's own figures.

    `(account, its base-currency amount, the foreign value it is worth, the
    unit it is held to, the unit its currency has)` per split.

    Shown when a cost basis is reported, because the cost is derived from these and
    a reader looking at a finding wants to see what it came from. Not checked
    against each other: a rate runs forward into a figure, and the figure does
    not run back into the rate. 1.405 applied to 45.00 USD gives 63.23 CAD,
    whose effective rate is 6323/4500 — reading that back and asking whether
    it "is" 1.405 has no answer, since many rates give 63.23 and the stated
    one is not kept. Each of these figures is rounded to its own unit that
    way, so an invoice's income and tax lines differ in the last digits
    though one rate produced both.

    Empty for a transaction in the book's own currency, which converts nothing.
    """
    if transaction is None or tx_currency == BASE_CURRENCY:
        return []
    figures = []
    for other in transaction.GetSplitList():
        if split_commodity(other) != BASE_CURRENCY:
            continue
        base_amount = abs(_fraction(other.GetAmount()))
        base_value = abs(_fraction(other.GetValue()))
        if base_amount == 0 or base_value == 0:
            continue
        # The account's own unit, not its currency's: an account can be kept
        # finer than the cent — fuel at 1.819 a litre — and its splits are
        # written at that unit, so printing one at the cent shows a figure the
        # ledger does not hold.
        account = other.GetAccount()
        unit = (account.GetCommoditySCU() if account is not None
                else smallest_unit(other))
        figures.append((get_account_full_name(other.GetAccount()),
                        base_amount, base_value, unit, smallest_unit(other)))
    return figures


def cost_bases(book) -> List[Dict]:
    """Every foreign-currency cost basis in the book with its cost and
    basis balance — what `fx-balances` lists.

    Listed as the book holds them, in no imposed order: a sale gives the guid of the cost basis
    it measures against, so no cost basis is ahead of another and sorting by date
    would suggest an order of consumption that does not exist.

    A cost basis this cannot read — a `cost_basis_cost` that is not a cost, most
    likely written by hand — is listed as unreadable rather than ending the
    listing. One such split used to take the whole command down with it, so a
    book could not be inspected at exactly the moment there was something in
    it to inspect. `verify_cost_bases` says why, with the traceback.
    """
    rows: List[Dict] = []
    for split in iter_splits(book):
        try:
            if not establishes_cost_basis(split):
                continue
            row = {
                'currency': split_commodity(split),
                # The listing is rendered after the book is closed, so each row
                # carries how finely its currency divides rather than the
                # commodity it would have to read that from.
                'unit': smallest_unit(split),
                'cost': cost_of(split),
                'brought_in': brought_in_by(split),
                'balance': cost_basis_balance_of(split),
                'malformed': False,
            }
        except Exception:
            row = {
                'currency': split_commodity(split),
                # From the commodity like any other row, not a hundredth
                # assumed: the amount is still printed, and a yen cost basis given
                # two invented decimals is wrong however unreadable the rest
                # of it is.
                'unit': smallest_unit(split),
                'cost': None,
                'brought_in': abs(_fraction(split.GetAmount())),
                'balance': None,
                'malformed': True,
            }
        transaction = split.GetParent()
        rows.append({
            'guid': split_guid(split),
            'date': (transaction.GetDate().strftime('%Y-%m-%d')
                     if transaction is not None else ''),
            'description': (transaction.GetDescription()
                            if transaction is not None else ''),
            'account': get_account_full_name(split.GetAccount()),
            **row,
        })
    return rows


def foreign_currency_account_balances(book, as_of=None) -> List[Dict]:
    """What each account holds of a currency that is not the book's own.

    `fx-balances` prints these beside the cost basis balances, as a block of
    their own. The two answer different questions — a cost basis balance is how
    much of *one split's* currency has not been sold, an account balance is
    what an account holds — and a reader comparing them needs both, because one
    currency can be spread across several accounts while its cost bases sit on
    others. A receivable's cost basis whose money is now in two banks has no
    single account to put in its own row.

    **The whole balance unless `as_of` is given.** A cost basis balance counts
    every disposal ever measured against it, whatever its date, so a
    date-bounded figure beside it would be answering a different question.
    Measured on a book posting on 2026-12-31 and drawn while today is
    2026-09-19: `GetBalanceAsOfDate` for today gives its US dollar bank
    9,080.00 where the account holds 7,480.00, and read against a cost basis
    balance of 10,000.00 that is simply the wrong comparison.

    `as_of` is for the one caller that reads the cost bases as of a date too:
    `--verify-integrity` compares the two, and both have to be as they stood at
    the end of the same day or the comparison is across two books. Checked at
    2028-06-30 against whole balances, a book that later repays a loan and sells
    part of its shares reported its cost bases holding 1,010.00 USD it no longer
    owed and 10 shares where 3 were left — both of them movements the date
    excludes on one side and not the other.

    Each row carries its own figures rather than the commodity it would have to
    read them from, as `cost_bases` does and for the same reason: the listing
    is rendered after the book has been closed.
    """
    rows: List[Dict] = []
    for account in book.get_root_account().get_descendants():
        commodity = account.GetCommodity()
        if commodity is None:
            continue
        # Securities are listed beside currencies, as `establishes_cost_basis`
        # counts them: a share is a holding with a cost basis of its own
        # (Q-046), so there is a cost basis balance here for what the accounts
        # hold to stand against, and leaving the shares out of one half of the
        # listing while the other half counted them said a book holding 12
        # AMZN held none.
        # What the book holds and owes, which is what a cost basis balance can
        # be read against. An income or expense account can be denominated in a
        # foreign currency too — this book's `Income:Realized Gains` is in US
        # dollars — but its balance is what passed through the profit and loss,
        # not currency the book has. Counted, they made a book holding 7,480.00
        # USD against 2,500.00 owed report 4,600.00 instead of 4,980.00.
        if account.GetType() not in (_DEBIT_TYPES | _CREDIT_TYPES):
            continue
        mnemonic = commodity.get_mnemonic()
        if not mnemonic or mnemonic == BASE_CURRENCY:
            continue
        fraction = commodity.get_fraction()
        rows.append({
            'account': get_account_full_name(account),
            'currency': mnemonic,
            'unit': fraction if fraction and fraction > 0 else 1,
            'balance': (_held_up_to(account, as_of) if as_of is not None
                        else numeric_to_fraction(account.GetBalance())),
        })
    return rows


def _held_up_to(account, as_of) -> Fraction:
    """What the account held at the end of `as_of`, summed from its own splits.

    Summed rather than asked of GnuCash, because the answer has to be the
    amount in the account's own commodity and has to be exact: what it is read
    against is a cost basis balance, which is a count of units.
    """
    total = Fraction(0)
    for split in account.GetSplitList():
        if split.GetParent().GetDate().date() <= as_of:
            total += _fraction(split.GetAmount())
    return total


def profit_and_loss_accounts_in_another_currency(book, currency: str) -> List[Dict]:
    """The income and expense accounts this book does not keep in `currency`.

    gnucash-plaintext does not support one. A holding has a cost and a price,
    and the difference between them is a gain; an expense has neither, being
    what it cost on the day it was incurred, and a rate that moves afterwards
    does not change it. Such an account's balance is a sum of amounts from many
    days, each of those days having had a rate of its own, and no one rate
    turns that sum into the book's own currency. A statement converts it at the
    report date's rate, which is the last of those rates applied to all of
    them, so the same expense is stated differently on a page drawn a month
    later.

    Both statements still print, with a warning listing these accounts and
    saying which figures carry the error: every account line states what the
    account holds in its own currency and the rate the page converted it at, so
    a reader who knows what each amount cost on its own day can work the right
    figure out.
    """
    rows: List[Dict] = []
    for account in book.get_root_account().get_descendants():
        if account.GetType() not in _GAIN_TYPES:
            continue
        commodity = account.GetCommodity()
        mnemonic = commodity.get_mnemonic() if commodity is not None else ''
        if not mnemonic or mnemonic == currency:
            continue
        rows.append({
            'account': get_account_full_name(account),
            'currency': mnemonic,
        })
    return rows
