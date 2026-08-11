"""The blocks the plaintext format is made of, written in one place.

An owner block and a document's text lines are emitted by three writers — the
ledger export, `print-invoice` and `print-bill` — and every one of them is
read back by the same importer. Written three times, they drifted: the export
carried a vendor's address and the renderers did not, the invoice renderer
carried `notes:` and the bill renderer did not, and the export learned to fall
back to a legacy slot while neither renderer did.

Each of those was a separate defect with the same cause, and each was found
one at a time, after the previous fix had landed on one door and left the
others open. Written once, a mistake here is a mistake everywhere — which is
what makes it findable by one test instead of three.

**What is shared, and what is not.** `owner_block_lines`,
`document_text_lines`, `payment_amount_text`, `payment_residue`,
`payment_residue_text` and `split_was_applied_from_credit` are used by all
three writers. `payment_block_lines` and `posted_block_lines` are the
renderers' only; the ledger export still assembles its own `payment:` lines,
in its own order, but every figure in them now comes from here.

`prepayment:` was the last figure it did not, and the cost was silent: a
printed overpaid document stated the portion that settled it and nothing about
the residue, so read into a book that never held the deposit, a 250.00 payment
entered as 100.00 and the owner's 150.00 credit was never created — with the
run exiting 0. `test_a_printed_overpayment_keeps_the_credit.py` holds that, and
`test_a_printed_payment_says_what_the_export_says.py` the rest.

**What a printed block still cannot carry** is the rate a converting payment
settled at: a USD invoice paid into an HKD bank moved two figures and the page
shows one. Read back into its own book the guids resolve and no rate is
needed; read into a book that never held the settlement it is refused by name,
pointing at `settled_amount:` — loud rather than settled at a guess, which is
the right answer for a figure that is genuinely not in the document.
"""

from fractions import Fraction

from infrastructure.gnucash.kvp import get_custom_metadata, held_value
from infrastructure.gnucash.utils import (
    format_amount_for_commodity,
    money_text,
    numeric_to_fraction,
)

_ADDRESS_KEYS = ('addr1', 'addr2', 'addr3', 'addr4', 'email')


def owner_block_lines(kind: str, owner, known_keys, with_guid: bool = False,
                      with_custom_keys: bool = False):
    """A `customer` or `vendor` block: who they are, where they are, and
    whatever the format has no setter for.

    The address falls back to the slot beside the owner, because a book
    written before vendors had address setters keeps it there and has nothing
    on the field — so reading the field alone would carry no address at all,
    and the export is the only copy a rebuild gets. The same keys are filtered
    out of the slot dump, so the line is written once and cannot come back
    twice with the stale copy winning.

    `with_custom_keys` for the export and not for a printed document. The keys
    the format has no setter for are whatever the book's owner chose to write
    about this customer — `credit_rating: "poor - chase early"`, and anything
    else — and `print-invoice` hands its output to that customer. The export is
    the book in text and needs every one of them; the document does not, and
    printing without them loses nothing, because a block that omits a key
    leaves it alone on re-import (`_merge_custom_metadata` writes only what a
    block names).
    """
    addr = owner.GetAddr()
    held = get_custom_metadata(owner) or {}
    lines = [f'{kind} "{owner.GetID()}"']
    if with_guid:
        lines.append(f'\tguid: "{owner.GetGUID().to_string()}"')
    lines.append(f'\tname: "{owner.GetName()}"')
    lines.append(f'\tcurrency: {owner.GetCurrency().get_mnemonic()}')
    if not owner.GetActive():
        lines.append('\tactive: false')

    for key, value in zip(_ADDRESS_KEYS,
                          (addr.GetAddr1(), addr.GetAddr2(), addr.GetAddr3(),
                           addr.GetAddr4(), addr.GetEmail())):
        # `held` is already read above; without it each of these five keys
        # re-reads the same slot.
        value = held_value(owner, value, key, held)
        if value:
            lines.append(f'\t{key}: "{value}"')

    if with_custom_keys:
        for key, value in sorted(held.items()):
            if key not in known_keys:
                lines.append(f'\t{key}: "{value}"')
    return lines


def document_text_lines(document):
    """`billing_id:` and `notes:` for an invoice or a bill.

    Both are read by the comparison that decides whether a re-imported
    document is `unchanged`, so a writer that leaves them out produces a file
    its own importer cannot match: the document is rebuilt on every run, which
    for a posted one means unposting it — destroying the posting transaction
    and orphaning its payments — and posting it again.
    """
    lines = []
    for key, value in (('billing_id', document.GetBillingID()),
                       ('notes', document.GetNotes())):
        value = held_value(document, value, key)
        if value:
            lines.append(f'\t{key}: "{value}"')
    return lines


def posted_block_lines(document, account_key: str, account_name: str):
    """The `posted:` block, with the guid that makes it re-readable.

    `posted_txn_guid:` is what lets a re-import relink the posting the book
    already has instead of posting again. A writer that leaves it out produces
    a document that cannot be read back into the same book: the rebuild
    orphans the original posting and makes another.

    Asked only of a posted document. Both callers write `posted: none`
    themselves for an unposted one and reach here in the other arm, having
    already read `GetPostedAcc()` to pass the account name in — so a
    `posting is None` branch here was a way out that neither could take, and
    a branch nothing can take is a claim about the book that nothing checks.
    """
    posting = document.GetPostedTxn()
    return [
        '\tposted:',
        f'\t\tdate: {document.GetDatePosted().strftime("%Y-%m-%d")}',
        f'\t\tdue: {document.GetDateDue().strftime("%Y-%m-%d")}',
        f'\t\t{account_key}: "{account_name}"',
        f'\t\tmemo: "{posting.GetDescription()}"',
        f'\t\tposted_txn_guid: "{posting.GetGUID().to_string()}"',
        '\t\taccumulate: true',
    ]


def split_was_applied_from_credit(split) -> bool:
    """True iff this split settled its document out of the owner's credit
    rather than being paid to it.

    The split says so itself, because the import that applied the credit wrote
    it there. Nothing else in the book can answer it: once applied, a consumed
    credit's split sits in the document's lot exactly as a bank payment's split
    does, GnuCash keeps no record of the lot it came from, and on the day a
    deposit is taken and an invoice raised against it even the dates are the
    same.

    Two things were tried before this and both misread ordinary books. Asking
    the *transaction* whether it still touches a leftover credit lot gives one
    answer for every document that transaction settles — so the invoice a bank
    transfer paid claimed a credit had paid it — and says no for a credit
    consumed to the last cent, which leaves no residual behind. Asking whether
    the transaction predates the document's posting is right for every case but
    the same-day one, where a genuine payment cannot be told from an
    application by any figure in the book.

    A split with nothing written on it — a book from the GnuCash GUI, or one
    written before this — reads as a payment, which is what it was before this
    tool had anything to say about it.

    Here rather than in the exporter, because it decides which block is
    written and the block writers are what this module is.
    """
    return str(get_custom_metadata(split).get('applied_from_credit', '')
               ).strip().lower() == 'true'


def payment_residue(transaction, in_lot_split):
    """What this payment left over when it was made, as a Fraction.

    A payment can be larger than the document it settles — 250.00 against a
    100.00 invoice — and `amount:` states this document's own slice, because
    one deposit can settle several documents and the bank figure would
    over-report every one of them. The rest is the owner's credit, and
    `prepayment:` is where a block says so.

    Read off the payment transaction's other receivable/payable splits, and
    each is asked what it is:

    - a slice sitting in another *document's* lot is that document's portion
      and was never residual;
    - unless it settled that document out of credit, which means it was the
      owner's money on the day this payment landed — and a rebuild reaches
      this block before anything has taken it;
    - what an unpost left loose is not residual either. `prepayment:` says
      "park this much as the owner's credit", and a file saying it makes a
      bank's payment into spendable credit (CLAUDE.md finding 10).

    A document *posted after this payment* is the case that decides the shape:
    its slice was the owner's credit on the day the money arrived, and only
    later settled anything. Reading the book as it stands today would call a
    150.00 payment against a 100.00 invoice a residue of 20.00, because a
    later invoice has since taken 30.00 — while a rebuild reaches this payment
    before that invoice exists and finds 50.00 sitting loose, which is what
    the payment really left.

    Here rather than in either writer. The export computed it and the printed
    block did not, and a printed block is re-importable: read into a book that
    never held the deposit, `amount: 100` alone entered a 100.00 bank movement
    for money that moved 250.00, left the owner's 150.00 uncreated, marked the
    invoice settled and exited 0.
    """
    import gnucash.gnucash_core_c as gc

    from services.gnucash_importer import is_a_bank_paid_orphan

    in_lot_guid = in_lot_split.GetGUID().to_string()
    residue = Fraction(0)
    for i in range(transaction.CountSplits()):
        split = transaction.GetSplit(i)
        if split.GetGUID().to_string() == in_lot_guid:
            continue
        account = split.GetAccount()
        if account is None:
            continue
        if gc.xaccAccountGetType(account.instance) not in (
                gc.ACCT_TYPE_RECEIVABLE, gc.ACCT_TYPE_PAYABLE):
            continue
        lot = split.GetLot()
        if (lot is not None and gc.gncInvoiceGetInvoiceFromLot(lot)
                and not split_was_applied_from_credit(split)):
            continue
        if is_a_bank_paid_orphan(split):
            continue
        residue += abs(numeric_to_fraction(split.GetAmount()))
    return residue


def payment_block_lines(transaction, in_lot_split, bank_account: str,
                        memo: str, where: str, num: str = ''):
    """A `payment:` block, with the guids that name the money it refers to.

    `txn_guid:` and `txn_split_guid:` are what make a payment refer to the
    bank transaction the book already holds rather than describe a new one.
    Without them, re-importing a document that had to be rebuilt made a second
    payment for money that had moved once — measured, on a bill printed,
    corrected and read back: the bank held two 400.00 payments and the run
    reported success.

    The amount is worked out here, not handed in. Passed in, the export
    computed it at the account's own unit and refused a figure the currency
    cannot hold, while the renderers rounded the same split to the currency's
    places and printed it: 30.005 CAD on a receivable kept to thousandths was
    refused by `export` and written by `print-invoice` as `amount: 30.00`.
    A printed block is re-importable, so that figure becomes a payment in
    another book for money the source book never held. One function so a
    mistake here is a mistake everywhere — which only holds for what the
    function actually decides.

    `where` names the document for that refusal.

    A settlement that came out of the owner's credit is a different block —
    no bank, because no bank was involved — and which one to write is decided
    here rather than by each caller. Deciding it outside, the export wrote
    `from_credit: true` while the renderers walked the payment transaction for
    a non-receivable split, found the one the *credit* arrived through, and
    printed `bank_account: "Assets:Bank"` with that transaction's date: a
    document telling its reader a bank paid an invoice a credit settled, and a
    block that would make a bank payment in any book it was read into.
    """
    if split_was_applied_from_credit(in_lot_split):
        return [
            '\tpayment:',
            f'\t\tamount: {payment_amount_text(in_lot_split, where)}',
            '\t\tfrom_credit: true',
            f'\t\tcredit_dated: {transaction.GetDate().strftime("%Y-%m-%d")}',
            f'\t\tmemo: "{in_lot_split.GetMemo() or ""}"',
            f'\t\ttxn_guid: "{transaction.GetGUID().to_string()}"',
            f'\t\ttxn_split_guid: "{in_lot_split.GetGUID().to_string()}"',
        ]
    lines = [
        '\tpayment:',
        f'\t\tdate: {transaction.GetDate().strftime("%Y-%m-%d")}',
        f'\t\tamount: {payment_amount_text(in_lot_split, where)}',
        f'\t\tbank_account: "{bank_account}"',
        f'\t\tmemo: "{memo}"',
    ]
    # The cheque number, where the payment carries one. The export wrote it
    # and the printed block did not, so a document read into a fresh book —
    # where the guids name nothing and the payment is made from the block —
    # lost it.
    if num:
        lines.append(f'\t\tnum: "{num}"')
    lines += [
        f'\t\ttxn_guid: "{transaction.GetGUID().to_string()}"',
        f'\t\ttxn_split_guid: "{in_lot_split.GetGUID().to_string()}"',
    ]
    # And what the payment left over, where it left anything. `amount:` is
    # this document's own slice, so a block without this line says a 250.00
    # deposit against a 100.00 invoice moved 100.00 — which is what a printed
    # overpayment read into a book that never held the deposit entered, with
    # the owner's 150.00 never created and the run exiting 0.
    residue = payment_residue(transaction, in_lot_split)
    if residue > 0:
        lines.append(f'\t\tprepayment: {payment_residue_text(residue, in_lot_split, where)}')
    return lines


def payment_residue_text(residue, in_lot_split, where: str) -> str:
    """The residue at the unit its account is kept to, or a refusal.

    At the account's unit, like the `amount:` above it: both are compared
    exactly on the way back in, and a residual of 20.005 written as 20.00
    makes a file its own book cannot read — failing on the rebuild, after the
    document has been unposted.
    """
    from use_cases.export_transactions import (
        refuse_a_figure_the_currency_cannot_hold,
    )

    account = in_lot_split.GetAccount()
    refuse_a_figure_the_currency_cannot_hold(
        residue, account, 'the prepayment', where)
    # Not guarded against a split with no account: a book holding one cannot
    # reach a command on any supported version (CLAUDE.md finding 12), and a
    # guard on the first read alone would fall through the `or` into the
    # second and dereference it anyway — which is not a guard, only the look
    # of one.
    unit = account.GetCommoditySCU() or account.GetCommodity().get_fraction()
    return money_text(residue, unit)


def payment_amount_text(split, where: str) -> str:
    """A payment's own allocation, at the unit its account is kept to.

    The AR/AP split in the document's lot, not the bank-side total, which
    would over-report when one bank transaction pays several documents.

    Refused rather than rounded where the currency cannot hold it: this figure
    is read back as `amount:`, and the importer judges it against the same
    rule — so a rounded one is a block this tool writes and then refuses.
    """
    from use_cases.export_transactions import (
        refuse_a_figure_the_currency_cannot_hold,
    )

    account = split.GetAccount()
    refuse_a_figure_the_currency_cannot_hold(
        abs(numeric_to_fraction(split.GetAmount())), account,
        'the payment amount', where)
    scu = account.GetCommoditySCU() if account is not None else None
    if not scu:
        return format_amount_for_commodity(
            split.GetAmount().abs(),
            account.GetCommodity() if account is not None else None)
    return money_text(abs(numeric_to_fraction(split.GetAmount())), scu)
