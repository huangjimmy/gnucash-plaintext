"""Linking a bank transaction the book already holds to an invoice's payment.

A `payment:` block can point at money that is already in the book rather than
describe money to enter. The bank feed came in first, or somebody recorded the
deposit by hand; either way the transaction exists, and what the block does is
say which of its splits settles this invoice or bill.

Two things make that harder than it sounds, and both live here.

**The split may not be on the receivable yet.** Money can be booked wherever the
bookkeeper put it while working out what it was for — `Assets:Due From Director`
in the report this came from. When it turns out to have settled an invoice, that
split is what has to become the settlement. `txn_guid:` alone could always move
it, never having been filtered by account type; naming it outright could not.

**And the figure on it may mean nothing.** GnuCash quotes an entry in a currency
both sides can be expressed in, so 100.00 USD received into a USD bank and
booked against a CAD account makes the entry CAD and leaves 139.00 CAD on that
split, at whatever rate applied that day. That figure is an artefact of the
account it sits on, not a fact about the settlement, and it goes when the
account does. What the settlement *is* is what the bank received.

Q-039 is the whole reasoning, and what it cost before this: naming such a split
was refused outright, naming only its transaction was refused for a reason that
was untrue (139 CAD "exceeds" 100 USD, offering a `prepayment:` of 39 of
nothing), and where the two figures happened to be equal nothing refused at all
— the split changed account, kept its amount, and the book was left saying 139
USD for 139 CAD of money with every total still balancing.

Split out of `services/gnucash_importer.py`, which the import path had grown to
eleven thousand lines of. The importer-private helpers this needs are imported
inside the functions that use them, which is how the rest of this package breaks
the same cycle.
"""

from infrastructure.gnucash.utils import (
    get_account_full_name,
    numeric_to_fraction,
    qof_pointer,
)
from services.foreign_currency import split_guid
from services.plaintext_parser import DirectiveType


def the_records_own_account(kind: str) -> str:
    """`'payable'` for a bill, `'receivable'` for an invoice.

    A word a reader acts on, so it has to be theirs: told a split cannot be
    moved "onto the receivable", somebody holding a bill goes looking through
    a chart of accounts for one that is not in it.

    **Taken from the record's kind, which is its owner** — `kind_of` reads
    `GNC_OWNER_VENDOR` — and not from the type of the account it posted to.
    The two usually agree, and nothing makes them: `gncInvoicePostToAccount`
    validates nothing about the account it is handed and this tool's own
    posting check compares currencies only, so `ap_account:` naming a plain
    `type: Liability` is a book that gets built. Asked of the account there,
    this returned "receivable" for a bill — and every one of these messages
    says "bill" in the same breath, so the sentence contradicted itself.
    Asked of the kind, it cannot: one word drives both halves.

    Every refusal on this path that names the record's own account asks here,
    rather than each spelling it for itself — nine sites across this file and
    `gnucash_importer.py`. Written out at each, six said "receivable" to a
    bill and the others did not, and no site was wrong in a way its own reader
    could see; it took reading all nine together. Fixing them one at a time as
    they were noticed left the rest, twice.

    **Anything else raises rather than falling back**, and the callers take
    `kind` without a default for the same reason. A fallback here is the
    original defect rebuilt: "receivable" is the answer five of the nine gave
    by not thinking about it, and a caller that passed nothing, or `'Bills'`,
    would get it back silently with a bill's reader none the wiser. A wrong
    word cannot be seen in the message it comes out of; a raise can.
    """
    word = kind.strip().lower()
    if word not in ('bill', 'invoice'):  # pragma: no cover - a caller's error, no file reaches it
        raise ValueError(
            f'the_records_own_account was given {kind!r}, which is neither a '
            f'bill nor an invoice — the word a refusal uses for the record\'s '
            f'own account cannot be guessed from it.')
    return 'payable' if word == 'bill' else 'receivable'


def commodity_of(account) -> str:
    """An account's currency, as a mnemonic, or `''` where it has none."""
    if account is None:
        return ''
    commodity = account.GetCommodity()
    return commodity.get_mnemonic() if commodity is not None else ''


def the_split_on(transaction, account_name: str):
    """The transaction's split on the named account, or None."""
    for split in transaction.GetSplitList():
        account = split.GetAccount()
        if account is not None and get_account_full_name(account) == account_name:
            return split
    return None


def kind_of(record) -> str:
    """`invoice` or `bill`, for a sentence about this record."""
    # GnuCash's own constant rather than a 4 copied beside it: a `gncInvoice`
    # owned by a vendor is a bill.
    from gnucash.gnucash_business import GNC_OWNER_VENDOR

    return 'bill' if record.GetOwnerType() == GNC_OWNER_VENDOR else 'invoice'


def the_settlement_a_block_names(pay_dir):
    """The transaction and splits a `payment:` block's directives name.

    Returns `('', [])` where the block carries none, which is nearly every
    block: one settling split is written `txn_guid:` + `txn_split_guid:` and
    always will be.

    A `Transaction "…"` under the payment is for the other case — one payment
    whose transaction clears the record with more than one split. That is one
    payment, money having arrived once, so it is one block naming several
    splits rather than several blocks, which would read as several payments.

    Two `Transaction` blocks under one payment is a file saying the payment is
    two transactions, which is two payments; refused rather than guessed at.

    A `PaymentSplit` sitting beside the block's keys rather than under a
    `Transaction` is refused too, but by the parser rather than here: it names
    a split of nothing wherever it is written, including one level further out
    where there is no payment block to have caught it, so the check belongs
    where every such line passes. Kept here as well it was unreachable — the
    parser answers first, and its message is the one a reader actually earns.
    """
    children = list(getattr(pay_dir, 'children', []))
    named = [child for child in children
             if child.type == DirectiveType.PAYMENT_TRANSACTION]
    if not named:
        return '', []
    if len(named) > 1:
        raise Exception(
            'a payment block names more than one `Transaction`. One payment '
            'is one transaction — money arriving twice is two payments, so '
            'write a `payment:` block for each.')
    block = named[0]
    splits = [child.props['guid'] for child in block.children
              if child.type == DirectiveType.PAYMENT_SPLIT]
    # A `Transaction` with no splits under it says only what `txn_guid:` says,
    # and is then read by nobody: with no children the block scores a bare
    # slot, so the comparison pairs it on date, amount and memo, and an
    # otherwise-matching record reports `unchanged` before the override that
    # prefers the directive — or the note saying the keys went unread — has
    # run. The directive's children are what it is for.
    if not splits:
        raise Exception(
            f'`Transaction {block.props["guid"]!r}` names no `PaymentSplit`. '
            f'A `Transaction` block says which splits of it settle this '
            f'record, and its children are what say so:\n'
            f'\t\tTransaction "<the transaction>"\n'
            f'\t\t\tPaymentSplit "<a split of it>"\n'
            f'Name them, or say the same thing with `txn_guid:` and '
            f'`txn_split_guid:`.')
    # A name repeated is a copy-pasted line, and counted twice it is a
    # settlement the book does not have. `amount:` is weighed against the sum
    # of the names, so the file is *required* to state double what moved; the
    # attach is idempotent, so the book ends with one settlement against a
    # block asserting two; and the block then scores two slots against the one
    # split the lot holds, so the record is judged changed on every import of
    # an unedited file — unposted, its posting destroyed, rebuilt, for ever.
    # That is what slots exist to prevent, and two `Transaction` blocks are
    # refused just above for the same reason.
    # Compared as guids rather than as text, because a guid is written
    # hyphenated or not and means the same split either way — GnuCash's own
    # windows show the hyphenated form, so a reader copying from one and from
    # an export gets one of each. Everything else here normalises before
    # comparing; matching the raw strings let those two past.
    from services.gnucash_importer import _normalise_guid

    seen = set()
    for guid in splits:
        if _normalise_guid(guid) in seen:
            raise Exception(
                f'`PaymentSplit {guid!r}` is named twice by one payment. A '
                f'split settles a record once, so naming it again claims a '
                f'settlement the transaction does not carry — the figures '
                f'would state double what moved, and the block would go on '
                f'accounting for one settlement more than the lot holds. '
                f'Remove the repeated line.')
        seen.add(_normalise_guid(guid))
    return block.props['guid'], splits


def payment_slots(payment_dirs, book=None):
    """One slot per settlement the file accounts for.

    A `payment:` block is one payment, and nearly always one settling split, so
    nearly every block is one slot. A block whose `Transaction` names several
    splits is one payment made of several — the money arrived once — and it
    accounts for one settlement per split it names.

    Counting blocks instead read such a payment as one settlement while the lot
    held two, so an invoice exported and read straight back was judged changed:
    it was unposted, its posting destroyed, and the rebuild then refused the
    splits its own unpost had abandoned. Slots are what make the two sides count
    the same thing.

    Each slot of a naming block carries the guid it names, so it can only be
    matched by that split — **including a block that names exactly one.**
    Given a `None` slot instead, that one was paired on date/amount/memo, and
    its `amount:` is the settlement's share while the figure it was weighed
    against is the bank side of the transaction: a block settling 60.00 of a
    wire that moved 100.00 never matched its own payment, so every re-import
    of an unedited file unposted the record and rebuilt it. No export writes
    that shape — a single settlement is written `txn_guid:` +
    `txn_split_guid:` — so nothing that round-trips an export reached it.

    **`book` is what the guids are worth.** Where it is given and the named
    transaction is not in it, the block names splits of some other book: the
    import drops them and records one payment from the block with
    `ApplyPayment`, so it accounts for one settlement, not one per name. Asked
    syntactically, a printed page read into a fresh book left the lot holding
    one split against two slots for ever — judged changed by a file it already
    matched, unposted and rebuilt on every run. Left out (`book=None`) the
    count stays syntactic, which is right only where every guid is this book's.
    """
    from services.gnucash_importer import _normalise_guid

    slots = []
    for block in payment_dirs:
        txn, named = the_settlement_a_block_names(block)
        if named and book is not None and not _the_book_holds(book, txn):
            named = []
        if named:
            slots.extend((block, _normalise_guid(guid)) for guid in named)
        else:
            slots.append((block, None))
    return slots


def _the_book_holds(book, txn_guid: str) -> bool:
    """Whether this book has the transaction a block names.

    A guid that will not parse is treated as naming nothing, which is what it
    does. Refusing it is `_refuse_a_payment_guid_nothing_can_parse`'s to do,
    on the import path, where a reader can be told which line to fix; counting
    settlements is not the place to raise.

    `ValueError` and nothing wider, because that is the one thing being
    allowed for — `_find_transaction_by_guid` raises exactly it for a guid it
    cannot parse. Catching everything, any other failure became "the book does
    not have it", which collapses a naming block from one slot per split to
    one: the count then falls short of what the lot holds, the record is judged
    changed, and its posting is destroyed by an unpost nobody asked for. That
    is the failure slots exist to prevent, arriving through the guard meant to
    make them right.
    """
    from services.gnucash_importer import _find_transaction_by_guid

    if not txn_guid:
        return False
    try:
        return _find_transaction_by_guid(book, txn_guid) is not None
    except ValueError:
        return False


def the_settlement_amount(existing_tx, counter_split, post_acct,
                          bank_acct_name: str):
    """How much this transaction settles, in the record's own currency.

    Ordinarily the split about to become the receivable already carries it, and
    that is what is read. But a split parked on an account of another currency
    carries a figure that is not the settlement and never was.

    Measured against the invoice, 139 CAD against 100 USD owed reads as a 39
    overpayment and the run offers `prepayment: 39.00` — thirty-nine of nothing,
    the two being different currencies and the CAD one about to be discarded.
    Where the two happened to be equal it read as exact, and the book was left
    saying 139 USD for 139 CAD of money.

    So where the parked split is foreign to the receivable the figure comes
    from the split that received the money. Returns None where there is nothing to
    weigh, which the callers already treat as "no figure to check against".
    """
    if counter_split is None:
        return None
    parked = commodity_of(counter_split.GetAccount())
    settlement = commodity_of(post_acct)
    if not parked or not settlement or parked == settlement:
        return abs(numeric_to_fraction(counter_split.GetAmount()))
    bank_split = the_split_on(existing_tx, bank_acct_name)
    if bank_split is None or commodity_of(bank_split.GetAccount()) != settlement:
        # Nothing here can say what the settlement is worth, so it says so
        # rather than guessing. `refuse_when_the_amount_cannot_be_read` turns
        # both shapes away before anything moves; measuring the parked figure
        # would refuse first, for a reason that is not true.
        return None
    return abs(numeric_to_fraction(bank_split.GetAmount()))


def refuse_to_move_a_split_out_of_its_lot(split, declared: str,
                                          txn_guid: str, record=None,
                                          key: str = '`txn_split_guid:`') -> None:
    """A split already in a lot is somebody's settlement or credit.

    Moving it onto this record's receivable takes it off whatever it is on now,
    leaving that record unpaid or that owner's credit short with every figure in
    the book still balancing. The lot is named so a reader can go and look.

    Not the lot this record's own unpost just abandoned: `gncInvoiceUnpost`
    detaches the record but leaves its settlements sitting in the old lot
    (CLAUDE.md finding 10), so a rebuild meets its own splits still lotted, and
    refusing them would fail after the posting had already been destroyed.

    **And not this record's own live lot**, where `record` is given. A split
    sitting in it is this record's settlement already, so there is nothing to
    take it off and nothing left short — the case is re-stating a payment the
    book has, which is what re-importing an export does. The sibling refusal
    `_refuse_a_split_settling_another_record` has always exempted it for that
    reason; this one is asked first, so scoped to "any lot" it spoke over the
    exemption and described the record's own money as somebody else's, offering
    an `unapply-payment` that would be wrong to follow. Reachable by adding a
    second settling split to a transaction that already settles this record and
    naming both: the block classifies as an addition, so no unpost marks the
    first, and the legitimate edit was refused outright.

    Through `_lot_is_still_on_its_account`, as every reader of a lot pointer
    goes: a split can hold one the book has let go of, and asking a freed
    pointer for its guid to build this message is a segfault, not a refusal.
    """
    from services.gnucash_importer import (
        _lot_guid_str,
        _lot_is_still_on_its_account,
        _orphaned_from,
    )

    lot = split.GetLot()
    if lot is None or not _lot_is_still_on_its_account(split, lot):
        return
    if _orphaned_from(split):
        return
    if record is not None:
        mine = record.GetPostedLot()
        if mine is not None and qof_pointer(mine) == qof_pointer(lot):
            return
    raise Exception(
        f'{key} {declared!r} on tx {txn_guid!r} is in lot '
        f'{_lot_guid_str(lot)} already. A split in a lot is settling an '
        f'invoice or a bill, or standing as an owner\'s credit, so moving it '
        f'here would leave that one short with nothing saying so. Take it out '
        f'of the lot first (`unapply-payment`, or its own `payment:` block), '
        f'or name a split that is not spoken for.')


def refuse_when_the_amount_cannot_be_read(
        existing_tx, parked_split, bank_split, post_acct,
        bank_acct_name: str, txn_guid: str, kind: str,
        key: str = '`txn_split_guid:`') -> None:
    """The two shapes whose settlement cannot be worked out.

    **No split on the account the block names.** What the parked split is worth
    is read off the bank split, so not finding one is not a detail to work
    around: the figure would come from somewhere else and the reader would never
    learn which. Said by name, the likeliest cause being a typo in `account:`.

    **Anything in the entry besides the bank and the split being placed.** The
    bank's figure is the settlement only while those two are the whole entry.
    Add a third split and the same numbers have more than one honest reading: a
    105 receivable against 100 in the bank and a 5 fee is a customer who paid
    105 with the fee borne here, or one who paid 100 with the fee theirs.
    Nothing in the book says which, and it is not this tool's to choose — so it
    asks, and the file answers by stating the amounts.

    Both are asked before anything moves, so a refused file has changed nothing.
    """
    from services.gnucash_importer import _account_money_str

    if bank_split is None:
        raise Exception(
            f'this block says the money is in '
            f'{bank_acct_name!r}, and tx {txn_guid!r} has no split on that '
            f'account. What a parked split is worth is read from the one that '
            f'received the money, so there is nothing here to read it from. '
            f'Check `account:` against the transaction, or name the '
            f'transaction the payment is really on.')
    settlement = commodity_of(post_acct)
    parked_currency = commodity_of(parked_split.GetAccount())
    # Whether the split being placed already states the settlement. Where it is
    # in the record's own currency both its figures are its own — an amount and
    # a value it was written with — and nothing has to be read off the bank, so
    # neither refusal below has anything to refuse. `the_settlement_amount` has
    # always answered this case that way; scoped to the bank's currency alone,
    # this disagreed with it and turned away a file the `txn_guid:`-only
    # spelling settles: a USD parked split behind a CAD bank, against a USD
    # invoice, refused as a conversion nobody wrote a rate for — and told, of a
    # split that states its own conversion, that what it carries "stood in for
    # the receivable, not a conversion of it".
    keeps_its_figure = bool(parked_currency) and parked_currency == settlement
    banked = commodity_of(bank_split.GetAccount())
    if banked != settlement and not keeps_its_figure:
        # Refused here, not left to the converting-payment refusal: that one
        # lives on the path that *records* a payment from the block, and every
        # branch that links an existing transaction returns before reaching it.
        # Left to it, a 139.00 CAD receipt against a USD receivable was written
        # onto that receivable as 139.00 USD and the entry requoted USD — an
        # implicit 1:1 nobody stated, on an invoice that then read over-settled
        # with no figure disagreeing.
        raise Exception(
            f'this {kind.lower()} is in {settlement} and the money reached '
            f'{bank_acct_name!r}, which is in {banked}, so the settlement '
            f'converts and only the payer knows what at. Nothing in tx '
            f'{txn_guid!r} states the rate: what the split being placed '
            f'carries is the figure that stood in for the '
            f'{the_records_own_account(kind)}, not a conversion of it. Write '
            f'the transaction out with both figures on '
            f'each split — an amount and a `value:` — or record the payment '
            f'with `settled_amount:` instead of linking this one.')
    others = [split for split in existing_tx.GetSplitList()
              if qof_pointer(split) not in (qof_pointer(parked_split),
                                            qof_pointer(bank_split))]
    # Nor does a third split make the settlement ambiguous where the split being
    # placed states it. The two honest readings of a fee exist because the
    # settlement is inferred from what the bank received; a split saying 105.00
    # in the record's own currency has said which reading is meant.
    if not others or keeps_its_figure:
        return
    listed = '; '.join(
        f'{get_account_full_name(split.GetAccount())} '
        f'{_account_money_str(numeric_to_fraction(split.GetAmount()), split.GetAccount())}'
        for split in others if split.GetAccount() is not None)
    got = _account_money_str(numeric_to_fraction(bank_split.GetAmount()),
                             bank_split.GetAccount())
    raise Exception(
        f'cannot tell how much of tx {txn_guid!r} settles '
        f'this {kind.lower()}. The bank received {got} and the transaction '
        f'carries {listed} besides, so this {kind.lower()} was settled by '
        f'{got}, or by {got} and that together — whoever bore it — and nothing '
        f'in the book says which. That is yours to state rather than this '
        f'tool\'s to guess: write the transaction out with an amount on every '
        f'split, so the one settling this {kind.lower()} says its own figure, '
        f'and name it with {key}.')


def refuse_several_splits_this_cannot_divide(book, txn_guid: str,
                                             named: list, record) -> None:
    """Several named splits have to carry their own figures.

    Where each is already on the receivable it does: two lines of one wire, 60
    and 40 of a 100, each saying what it is. Claiming them is only a question of
    which are this record's, which the block answers.

    A split parked on an account of another currency carries no such
    figure. One of those can be restated from what the bank received; two
    cannot, because dividing the settlement between them needs a ratio, and the
    only numbers on offer are the ones being discarded. Splitting 60/40 because
    the CAD happened to fall 90/49 is a rate invented out of scaffolding.
    """
    from services.gnucash_importer import (
        _find_transaction_by_guid,
        _normalise_guid,
    )

    if len(named) < 2:
        return
    existing_tx = _find_transaction_by_guid(book, txn_guid)
    if existing_tx is None:
        return
    settlement = commodity_of(record.GetPostedAcc())
    wanted = {_normalise_guid(guid) for guid in named}
    foreign = [(split_guid(split),
                get_account_full_name(split.GetAccount()),
                commodity_of(split.GetAccount()))
               for split in existing_tx.GetSplitList()
               if split_guid(split) in wanted
               and commodity_of(split.GetAccount())
               and settlement
               and commodity_of(split.GetAccount()) != settlement]
    if not foreign:
        return
    # Named, so a reader can go and look at them rather than counting their own
    # splits to work out which two were meant.
    which = '; '.join(
        f'{guid} on {account} ({currency})' for guid, account, currency in foreign)
    one = len(foreign) == 1
    raise Exception(
        f'this payment names '
        f'{len(named)} splits of tx {txn_guid!r}, and '
        f'{"one of them sits" if one else f"{len(foreign)} of them sit"} '
        f'on an account in another currency than {settlement} — {which}. '
        f'A payment naming its splits places each at the figure it carries, '
        f'and a split parked in another currency carries the one that stood '
        f'in for the {the_records_own_account(kind_of(record))}. Only a '
        f'payment naming a single split restates '
        f'it from what the bank received, and dividing a settlement between '
        f'several would need a ratio the book does not state. Put the amounts '
        f'on those splits in the transaction section, or name the one split '
        f'that settles this {kind_of(record)}.')


def the_account_the_amount_came_from(counter_split, post_acct):
    """Which account `the_settlement_amount` weighed, so a guard can say so.

    Its own, ordinarily. Where the split is parked in another currency the
    figure came off the bank instead, and it is in the record's currency — so
    the record's account is what describes it.

    It matters because `_refuse_a_payment_that_would_fall_short` skips itself
    when the account it is handed is not the record's currency. Handed the
    account the parked split sits on, it skipped for exactly the case this path
    was taught to read: measured, a block stating `amount: 100` against a bank
    that received 60 settled the invoice by 60 and said nothing.
    """
    if commodity_of(counter_split.GetAccount()) == commodity_of(post_acct):
        return counter_split.GetAccount()
    return post_acct


def refuse_an_overpayment_this_cannot_carve(counter_split, post_acct, carried,
                                            outstanding, txn_guid: str,
                                            kind: str, doc_id: str,
                                            carves: bool = True,
                                            key: str = '`txn_split_guid:`') -> None:
    """More arrived than is owed, out of a split not on the receivable.

    Two different reasons a residue cannot be worked out, and `carves` says
    which caller is asking.

    **The carve reads the split's own figure.** Parked in another currency,
    that figure is what stood in for the receivable, so both halves would come
    out of a number that means nothing. Measured: bank +1200.00 USD, the parked
    split −1668.00 CAD, a 1000.00 USD invoice. The run asked for
    `prepayment: 200.00`, accepted it, and then carved the CAD split —
    settling 1000 and parking **668**, both on the USD receivable, from a file
    it had just told the residue was 200. The values still summed to zero in
    CAD and nothing disagreed. That holds for either caller.

    **And `carves=False` says this spelling divides nothing at all.** Naming a
    parked split says which one settles the record; a residue beside it has to
    be its own split already, which is what the `prepayment:` check further
    down weighs against the loose siblings on the receivable — and after a
    relink there are none, so a reader declaring one is told the siblings sum
    to 0.00. The `txn_guid:`-alone branch does carve, and asks for
    `prepayment:` when it needs to, which is why it passes `carves=True` and
    same-currency overpayments go through it as they always have.

    Scoped to the currency alone this skipped the commoner shape entirely: a
    USD split against a USD invoice. Whether a split still has to be moved is
    decided by its account, not by its currency, so that split takes the
    naming branch like any other, and nothing else on that branch weighs what
    arrived against what is owed — 120.00 parked settled a 100.00 invoice with
    the lot at −20, the invoice reading paid, the customer's 20.00 in no
    credit lot, at exit 0.

    Asked before anything moves, so a refused file has changed nothing.
    """
    from services.gnucash_importer import _account_money_str

    if carried is None or carried <= outstanding:
        return
    on = get_account_full_name(counter_split.GetAccount())
    parked = commodity_of(counter_split.GetAccount())
    differs = bool(parked) and parked != commodity_of(post_acct)
    # The caller that carves has nothing to answer for where the figure is
    # sound: it asks for `prepayment:` and divides the split itself.
    if carves and not differs:
        return
    if differs:
        why = (f'That split is in {parked}, so the only figure it carries is '
               f'the one that stood in for the '
               f'{the_records_own_account(kind)}, and dividing it '
               f'would take both halves out of a number that means nothing.')
    else:
        why = (f'Naming a split says which one settles this {kind.lower()}; '
               f'it does not say how to divide it, and this spelling carves '
               f'nothing.')
    raise Exception(
        f'{kind} {doc_id}: tx {txn_guid!r} brought in '
        f'{_account_money_str(carried, post_acct)} against '
        f'{_account_money_str(outstanding, post_acct)} owed, and the split '
        f'being placed is on {on!r}. {why} Write the transaction out with the '
        f'settlement and the residue as two splits **on '
        f'{get_account_full_name(post_acct)}**, each stating its amount, name '
        f'the settling one with {key}, and declare the rest with '
        f'`prepayment: '
        f'{_account_money_str(carried - outstanding, post_acct)}`. The residue '
        f'has to be on that account: a `prepayment:` is reconciled against the '
        f'loose splits there, so one left on {on!r} is counted as 0.00 and '
        f'refused for not matching.')


def refuse_a_settlement_read_off_the_wrong_split(settled, parked_split,
                                                 post_acct, bank_split,
                                                 key: str = '`txn_split_guid:`',
                                                 *, posted, kind: str) -> None:
    """The two sides of the link swapped: `account:` on the parked split's
    account and `txn_split_guid:` on the bank's.

    One mistake, and every other guard is symmetric in the two splits, so none
    of them can catch it. The parked split is on an asset, so the account-type
    check passes. The bank split is not on a receivable, so it reads as parked.
    It is in no lot. `refuse_when_the_amount_cannot_be_read` excludes *both*
    named splits when it looks for a third and so finds none — it is symmetric
    in exactly the two fields that were swapped. And where the currencies agree
    the conversion arm is silent too.

    Measured on a USD bank, a USD `Assets:Suspense USD` and a USD invoice owing
    100: the settlement was read as the negation of what the *parked* split did, so
    the **bank** split was moved onto the receivable at +100.00. The deposit
    left the bank account altogether, the lot held the posting's +100 and this
    +100 so the invoice read as owing 200, and the entry still balanced — at
    exit 0, with nothing anywhere disagreeing.

    **The sign is what is not symmetric.** A settlement cancels what the record
    posted, so its sign is the posting's reversed — negative on the receivable
    of an ordinary invoice, positive on a credit note's, positive on a bill's
    payable. A figure read off the wrong split comes out the wrong way round.

    From the posting rather than from the account's type, because the type says
    only half of it: "a settlement of a receivable is negative" is true of an
    invoice and the reverse of a credit note, and asserting it turned away a
    refund that had always linked.

    Asked before `BeginEdit`, and inside the function that computes the figure
    rather than beside the call, so that no caller can reach the restatement
    without it. The same-currency `txn_guid:`-alone path does not reach the
    restatement at all, and asks it directly for that reason.
    """
    from services.gnucash_importer import _account_money_str

    amount = numeric_to_fraction(settled)
    # The opposite of the posting's, which is the whole of what a settlement
    # is: it cancels what the record put on the account. `_still_owed` has
    # always read it this way. Taken from the account's *type* instead, "a
    # settlement of a receivable is negative on it" is true of an invoice and
    # the reverse of a credit note — which posts −100.00 where an invoice posts
    # +100.00, and is settled by a refund of +100.00 — so this refused a link
    # that had always worked, and told the reader to correct an `account:` that
    # was right.
    # Abstain where the posting cannot be read, rather than assume a
    # direction. Folded into the invoice's, a `None` would have refused every
    # *bill* reaching it — a payable posts negative and settles positive — and
    # told the reader to correct an `account:` that was right. `_still_owed`
    # meets the same `None` and falls back rather than guessing; there is
    # nothing here to fall back to, so the question goes unasked and the
    # guards around it stand. Measured: the `txn_guid:`-alone branch on a bill
    # reaches this with a posting in hand, so no supported path takes the
    # abstention today.
    #
    # `posted` is keyword-only and has no default for that reason: `None` here
    # turns the whole sign check off, so a caller has to say it means to, the
    # way `kind` has to be said rather than guessed. The difference is that
    # `None` is a real answer for this one — there are postings that cannot be
    # read — where for `kind` there was none.
    if posted is None:
        return
    toward_settlement = -1 if posted >= 0 else 1
    if amount * toward_settlement > 0:
        return
    wanted = 'negative' if toward_settlement < 0 else 'positive'
    raise Exception(
        f'the settlement works out to '
        f'{_account_money_str(amount, post_acct)} on '
        f'{get_account_full_name(post_acct)!r}, and this record is settled by '
        f'a {wanted} figure there — a settlement cancels what the posting put '
        f'on the account, so it is the posting\'s sign reversed'
        f'. `account:` names '
        f'{get_account_full_name(bank_split.GetAccount())!r}, which is where '
        f'the money arrived, and {key} names the split on '
        f'{get_account_full_name(parked_split.GetAccount())!r}, which is the '
        f'one that becomes the settlement. Swapped, the settlement is read off '
        f'the split being replaced and comes out the wrong way round — the '
        f'arrival is moved onto the {the_records_own_account(kind)} and '
        f'leaves the account it arrived in. Give `account:` the account the '
        f'money moved through.')


def relink_a_parked_split(lib, existing_tx, parked_split, post_acct,
                          bank_split,
                          key: str = '`txn_split_guid:`',
                          *, posted, kind: str) -> None:
    """Make a split that stood in for the receivable *be* the receivable.

    Replace the account and nothing else and the parked figure stays, now read
    against an account of another currency: measured, 139.00 CAD becomes 139.00
    USD, the invoice reads paid in full, and the entry still balances — in CAD —
    so nothing anywhere disagrees.

    So the split is restated from what the bank received: same figure, other
    sign. Then the entry is requoted, because both remaining sides are the
    settlement's currency once the parked split has moved, and each value
    equals its amount — no rate, nothing having converted.

    `xaccSplitSetAccount` has a SWIG const-type mismatch, so the account is set
    through ctypes. See docs/DEBUGGING_GNUCASH_BINDINGS.md.
    """
    # Only where the figure on it means nothing. A split parked in the
    # record's *own* currency states the settlement outright — an amount and a
    # value it was written with — and restating it from the bank would replace
    # a true figure with one in the wrong currency: a USD parked split behind
    # a CAD bank would land on the USD receivable carrying the bank's 139. So
    # that one only changes account, and the entry keeps its quote, the bank
    # being the foreign side there rather than the split being moved.
    parked_currency = commodity_of(parked_split.GetAccount())
    keeps_its_figure = (bool(parked_currency)
                        and parked_currency == commodity_of(post_acct))
    # Whole, because `refuse_when_the_amount_cannot_be_read` has already turned
    # away anything else in the entry. There is nothing here to apportion and
    # nothing to decide, which is the point.
    settled = (parked_split.GetAmount() if keeps_its_figure
               else bank_split.GetAmount().neg())
    # Of whichever figure will land on the receivable, so the swapped-sides
    # mistake is caught on both paths — naming the bank split puts it in the
    # record's own currency too, which is what makes this the arm that would
    # otherwise wave it through.
    refuse_a_settlement_read_off_the_wrong_split(
        settled, parked_split, post_acct, bank_split, key,
        posted=posted, kind=kind)
    # And a figure the receivable's currency cannot state is refused here
    # rather than by the export that meets it later. Every sibling path in this
    # file asks it, and asked at the end the answer arrives after the split has
    # been moved and restated — a book this tool wrote and cannot read back.
    #
    # No file can reach it: a booked amount is judged against the currency
    # whatever unit the account is kept to, so a transaction carrying 100.005
    # USD is refused before any invoice sees it (measured, in
    # `TestAFigureFinerThanTheCurrency`). What can is a book GnuCash itself
    # wrote, on an account kept finer than its currency — which this tool
    # reads and must not make worse.
    from use_cases.export_transactions import (
        refuse_a_figure_the_currency_cannot_hold,
    )
    refuse_a_figure_the_currency_cannot_hold(
        numeric_to_fraction(settled), post_acct, 'the settlement')
    existing_tx.BeginEdit()
    lib.xaccSplitSetAccount(int(parked_split.instance), int(post_acct.instance))
    if not keeps_its_figure:
        # The currency first, then the figures. `xaccSplitSetValue` rounds to
        # the transaction's *current* currency as it is set, so setting values
        # while the entry is still quoted in the parked split's own currency
        # rounds them through that unit — and where it is the coarser of the
        # two, the cent is gone before the requote can convert it back. The
        # importer's own update path sets the currency first for this reason.
        #
        # Not reproduced: with the split parked on a JPY account (a yen being
        # its own smallest unit) against a 100.50 USD invoice, both figures came
        # back 100.50 either way round, so the rounding this guards against is
        # not one this tool has been shown to do. `TestAParkedCurrencyCoarser`
        # `ThanTheRecords` pins the invariant rather than a defect.
        commodity = post_acct.GetCommodity()
        if commodity is not None:
            existing_tx.SetCurrency(commodity)
        parked_split.SetAmount(settled)
        parked_split.SetValue(settled)
        bank_split.SetValue(bank_split.GetAmount())
    existing_tx.CommitEdit()
