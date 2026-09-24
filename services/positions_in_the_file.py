"""A split's position in the file being imported, standing where its guid would (Q-050).

`cost_basis_split_guid:` gives the split a cost basis sits on. A file that brings
currency in and spends it in one import has no guid to give, since GnuCash
assigns the arriving split's as the file is read, and a file need not assign
one. So the pick may be written as the arriving split's position instead:

    cost_basis_split_guid: $transactions_to_import[0].splits[0].guid$

Unquoted, between `$`, as `$residual$` is written in an amount. Counted from 0,
in the order the file writes them: the file's transaction blocks, and each
block's split lines. It points at a split in the same transaction or in one
above it, and what the book keeps is the guid of the split it points at — the
variable is never saved, so an export writes the guid.
"""

import re
from fractions import Fraction
from typing import List, Optional, Tuple

from gnucash.gnucash_core_c import ACCT_TYPE_PAYABLE, ACCT_TYPE_RECEIVABLE

from infrastructure.gnucash.kvp import get_custom_metadata, set_custom_metadata
from infrastructure.gnucash.utils import Variable, get_account_full_name, money_text
from services.foreign_currency import (
    COST_BASIS_SPLIT_KEY,
    _accounts_holding,
    _fraction,
    cost_basis_balance_of,
    establishes_cost_basis,
    smallest_unit,
    split_commodity,
    split_guid,
    transaction_currency,
)
from services.plaintext_parser import DirectiveType

_POSITION = re.compile(r'^\$transactions_to_import\[(\d+)\]\.splits\[(\d+)\]\.guid\$$')
THE_FORM = '$transactions_to_import[n].splits[m].guid$'


def the_position(value) -> Optional[Tuple[int, int]]:
    """The transaction and split a variable points at, or None where it is none."""
    if not isinstance(value, Variable):
        return None
    found = _POSITION.match(str(value))
    return (int(found.group(1)), int(found.group(2))) if found else None


def written(position: Tuple[int, int]) -> str:
    """A position as the file writes it."""
    return f'$transactions_to_import[{position[0]}].splits[{position[1]}].guid$'


def number_the_transactions(directives) -> List:
    """Give each transaction block its position in the file, and every one the list.

    Each keeps the list so a split of it can find the transaction a position
    points at, and `split_guids`, the guids of its splits in the order the
    block writes them once it is imported.
    """
    transactions = [child for child in directives
                    if child.type == DirectiveType.TRANSACTION]
    for position, transaction in enumerate(transactions):
        transaction.position_in_the_file = position
        transaction.transactions_in_the_file = transactions
        transaction.split_guids = None
    return transactions


def what_is_wrong_with_the_positions(transactions) -> List[str]:
    """Every position in the file that cannot be resolved, as a refusal each.

    Asked of the whole file before any of it is applied: a position pointing
    at a transaction below has no guid to be when its own transaction is
    imported, and applying the file up to it would leave half of it in the
    book.
    """
    wrong = []
    for here, transaction in enumerate(transactions):
        where = (f'transaction {here} of the file, {transaction.props.get("date", "?")} '
                 f'{transaction.props.get("tx_desc") or "(no description)"!r}')
        for line, split in enumerate(transaction.children):
            for key, value in split.metadata.items():
                if not isinstance(value, Variable):
                    continue
                position = the_position(value)
                if key != COST_BASIS_SPLIT_KEY or position is None:
                    wrong.append(
                        f'{where}, split {line}: `{key}: {value}` is no variable '
                        f'this format knows. A split gives the cost basis it draws '
                        f'on by position as `{COST_BASIS_SPLIT_KEY}: {THE_FORM}`, '
                        f'unquoted; written in quotes it is a string')
                    continue
                n, m = position
                # Past the end first: every transaction past the last is
                # below this one too, and there is none there to move.
                if n >= len(transactions):
                    wrong.append(
                        f'{where}, split {line}: {value} points past the end: '
                        f'the file has {len(transactions)} transaction(s)')
                elif n > here:
                    wrong.append(
                        f'{where}, split {line}: {value} points at transaction {n}, '
                        f'below it, which has not been imported when this one is. '
                        f'Move that transaction above this one')
                elif m >= len(transactions[n].children):
                    wrong.append(
                        f'{where}, split {line}: {value} points past the end: '
                        f'transaction {n} has {len(transactions[n].children)} split(s)')
                elif (n, m) == (here, line):
                    wrong.append(
                        f'{where}, split {line}: {value} points at the split that '
                        f'gives it. A split does not draw on the currency it brings in')
    return wrong


def the_variables_where_none_is_read(root) -> List[str]:
    """Every unquoted `$…$` written anywhere but a transaction's split, as a refusal each.

    A position is read only as `cost_basis_split_guid:` on a split of a
    transaction, and `what_is_wrong_with_the_positions` asks about those. Read
    anywhere else, as the split a payment block settles from or on a
    transaction's own line, it was taken as a plain string, and refused later
    for matching no split, with nothing saying why.
    """
    wrong = []

    def walk(directive):
        for child in directive.children:
            if not (child.type == DirectiveType.SPLIT
                    and directive.type == DirectiveType.TRANSACTION):
                wrong.extend(
                    f'{child.line.strip()!r}: `{key}: {value}` is a variable, and a '
                    f'position is read only as `{COST_BASIS_SPLIT_KEY}:` on a split '
                    f'of a transaction; written in quotes it is a string'
                    for key, value in child.metadata.items()
                    if isinstance(value, Variable))
            walk(child)

    walk(root)
    return wrong


def give_the_positions_their_guids(directive, splits) -> None:
    """Replace each position this transaction's splits give with the guid it points at.

    `splits` are the transaction's splits in the order its block writes them,
    so a position in the same transaction is the guid GnuCash has just
    assigned, and one above is the guid recorded when that transaction was
    imported. Written over the variable the split was stored with, so only the
    guid is kept.
    """
    directive.split_guids = [split_guid(split) for split in splits]
    for line, (child, split) in enumerate(zip(directive.children, splits)):
        position = the_position(child.metadata.get(COST_BASIS_SPLIT_KEY))
        if position is None:
            continue
        guid = the_guid_at(directive, position, line)
        set_custom_metadata(split, {**get_custom_metadata(split), COST_BASIS_SPLIT_KEY: guid})


def the_guid_at(directive, position: Tuple[int, int], line: int) -> str:
    """The guid of the split at `position`, seen from `line` of `directive`."""
    n, m = position
    guids = directive.transactions_in_the_file[n].split_guids
    if guids is None:
        raise Exception(
            f'split {line} gives {written(position)}, and transaction {n} of the '
            f'file was not imported, so no split of it has a guid to give')
    guid = guids[m]
    if guid is None:
        raise Exception(
            f'split {line} gives {written(position)}, and that transaction was '
            f'already in the book and its split {m} gives no `guid:` of a split '
            f'the book holds for it, so which split of the book it is cannot be '
            f'read from the file')
    return guid


def record_the_guids_it_gives(directive, matched) -> None:
    """What a transaction the import passed over, or edits, offers a position below it.

    It is in the book already, as the transactions `matched`, so its splits
    have guids; where a line gives the `guid:` of one of their splits, that is
    the one. Where it gives none, or one that is no split of theirs, the book
    is not asked to choose, and a position pointing at that line is refused.
    """
    held = {split_guid(split) for transaction in matched
            for split in transaction.GetSplitList()}
    stated = [str(child.metadata['guid']).replace('-', '').lower()
              if child.metadata.get('guid') else None
              for child in directive.children]
    directive.split_guids = [guid if guid in held else None for guid in stated]


def the_ways_to_write_it(refused, directive, splits, book) -> str:
    """The refusal of a spend giving no cost basis, with the ways to write what the owner means.

    Only the owner knows which, so the refusal chooses none. Beside an arrival
    on the account the currency left, the spend may be no fee but part of the
    exchange spread: the arrival written net of it, so the currency cost what
    the book paid for what it kept. Or it is kept, giving the cost basis it
    came out of — an arrival in its own transaction or one above it, by its
    position, or a cost basis the book holds, by its guid.
    """
    commodity, side = refused.commodity, refused.side
    sign = 1 if side == 'asset' else -1
    here = directive.position_in_the_file
    spending = {split_guid(split) for split in refused.spending}
    lines = list(splits)
    spent_at = [line for line, split in enumerate(lines) if split_guid(split) in spending]
    unit = smallest_unit(refused.spending[0])

    def arrives(split) -> bool:
        return (establishes_cost_basis(split) and split_commodity(split) == commodity
                and _fraction(split.GetAmount()) * sign > 0)

    account = get_account_full_name(refused.spending[0].GetAccount())
    ways = []
    beside = [split for split in lines if arrives(split)
              and get_account_full_name(split.GetAccount()) == account]
    # Only on the held side. A spend of what is owed repays it, with money
    # that left the book, so there is no charge net of it to write.
    if side == 'asset' and len(beside) == 1:
        arrival = beside[0]
        # What left that account: another account falling beside an arrival
        # is refused as a transfer before this is reached, but what is taken
        # off an arrival is what its own account gave up.
        net = _fraction(arrival.GetAmount()) - sum(
            (abs(_fraction(split.GetAmount())) for split in refused.spending
             if get_account_full_name(split.GetAccount()) == account), Fraction(0))
        value = _fraction(arrival.GetValue())
        places = transaction_currency_unit(arrival)
        # Stated in another currency, the arrival keeps what it cost, and
        # that buys fewer units. Stated in its own, a split's value is its
        # amount, so the arrival's falls with it and what cost it is valued at
        # what was kept.
        stated_in_its_own = transaction_currency(arrival.GetParent()) == commodity
        kept_at = net if stated_in_its_own else value
        ways.append(
            f'- as part of the exchange spread, not a fee: drop the splits of '
            f'what was spent and write the arrival net of it, '
            f'`{account} {money_text(net, unit)} {commodity}` with its '
            f'`value: "{money_text(kept_at, places)}"`'
            + (f', and the splits beside it valued {money_text(net, places)} '
               f'{commodity} between them in place of {money_text(value, places)}'
               if stated_in_its_own else '')
            + f', so what was spent is in what the {commodity} cost and nothing is '
              f'recorded as spent')

    choices = []
    for line, split in enumerate(lines):
        if arrives(split):
            choices.append(
                f'`{COST_BASIS_SPLIT_KEY}: {written((here, line))}` — the '
                f'{money_text(abs(_fraction(split.GetAmount())), unit)} {commodity} '
                f'this transaction brings into {get_account_full_name(split.GetAccount())}')
    # Every cost basis of the currency with something left, from one walk of
    # the accounts holding it: the arrivals above are listed by position, the
    # rest by guid. Not on a receivable or a payable: that cost basis is drawn
    # down by settling its record, and giving its guid is refused.
    held = {split_guid(split): split
            for held_in in _accounts_holding(book, commodity)
            if held_in.GetType() not in (ACCT_TYPE_RECEIVABLE, ACCT_TYPE_PAYABLE)
            for split in held_in.GetSplitList()
            if arrives(split) and cost_basis_balance_of(split)}
    for n, above in enumerate(directive.transactions_in_the_file[:here]):
        for m, guid in enumerate(above.split_guids or []):
            split = held.pop(guid, None)
            if split is not None:
                choices.append(
                    f'`{COST_BASIS_SPLIT_KEY}: {written((n, m))}` — '
                    f'{money_text(cost_basis_balance_of(split), unit)} {commodity} '
                    f'left of what transaction {n} brought into '
                    f'{get_account_full_name(split.GetAccount())}')
    for split in lines:
        held.pop(split_guid(split), None)
    for split in held.values():
        choices.append(
            f'`{COST_BASIS_SPLIT_KEY}: "{split_guid(split)}"` — '
            f'{money_text(cost_basis_balance_of(split), unit)} {commodity} left on '
            f'{get_account_full_name(split.GetAccount())}, from '
            f'{split.GetParent().GetDate().strftime("%Y-%m-%d")} '
            f'{split.GetParent().GetDescription() or "(no description)"!r}')
    ways.append(
        f'- keeping it, giving on split {", ".join(str(line) for line in spent_at)} the '
        f'cost basis it came out of, one of:\n'
        + '\n'.join(f'    {choice}' for choice in choices))
    return (f'{refused} Split {", ".join(str(line) for line in spent_at)} of this '
            f'transaction, out of {account}, can be written one of these ways:\n'
            + '\n'.join(ways))


def transaction_currency_unit(split) -> int:
    """How finely the currency of a split's transaction, which its value is in, divides."""
    return split.GetParent().GetCurrency().get_fraction()


def resolve_for_an_edit(directive, existing) -> None:
    """Replace this block's positions with the guids its lines give, before an edit.

    Under `--strategy update` every transaction of the file is one the book
    holds, `existing` for this block, and an edit compares what each split
    picks with what the book holds before any split is written. So a position
    is resolved first, to the `guid:` the line it points at gives.
    """
    record_the_guids_it_gives(directive, [existing])
    for line, child in enumerate(directive.children):
        position = the_position(child.metadata.get(COST_BASIS_SPLIT_KEY))
        if position is not None:
            child.metadata[COST_BASIS_SPLIT_KEY] = the_guid_at(directive, position, line)
