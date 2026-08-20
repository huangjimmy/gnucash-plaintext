"""The entry fields GnuCash keeps as something other than what a ledger says.

Three of them are integers in the engine and words everywhere a person looks,
and one is an owner. What they have in common is that a writer and the
importer must agree about the translation, so it lives here once.

The three integers are the kind of discount, when the discount applies, and
how a billable line was paid. GnuCash's own converters name them —
`gncAmountTypeToString`, `gncEntryDiscountHowToString`,
`gncEntryPaymentTypeToString` — and those names are what its XML file holds,
so the plaintext format uses the same words rather than inventing a second
vocabulary or writing the raw integers.

Read from the engine on 5.10, asked for 0 through 4:

    gncAmountTypeToString          1=VALUE    2=PERCENT
    gncEntryDiscountHowToString    1=PRETAX   2=SAMETIME   3=POSTTAX
    gncEntryPaymentTypeToString    1=CASH     2=CARD

**Zero is not a value any of them takes.** Setting one to 0 is accepted by
the setter and then warned about on every read — `[gncAmountTypeToString()]
asked to translate unknown amount type 0` — and GnuCash normalises it on
save: an entry written with type 0 and how 0 came back as `2` and `1`. So a
file naming a word this module does not know is refused rather than passed
through as a number.
"""

#: `discount_type:` — what the discount figure means.
DISCOUNT_TYPES = {'value': 1, 'percent': 2}

#: `discount_how:` — where the discount falls relative to tax.
DISCOUNT_HOWS = {'pretax': 1, 'sametime': 2, 'posttax': 3}

#: `payment_type:` on a bill entry — how a billable line was paid, which
#: decides whether re-billing it to a customer shows as cash or on a card.
#: Named `payment_type:` rather than `payment:` because a bill block already
#: has `payment:` blocks of its own, and one word under one document meaning
#: both "a payment made against this bill" and "how this line was paid" is
#: two things a reader cannot tell apart at a glance.
PAYMENT_TYPES = {'cash': 1, 'card': 2}


#: What an entry holds when a ledger names none of these keys, measured on
#: 5.10 by importing one that does not: `percent`, `pretax`, `cash`, beside a
#: discount of 0, an empty note and not billable. An entry block describes the
#: whole line — a re-imported document has its entries destroyed and rebuilt —
#: so these are what an unnamed key means, on the import and in the comparison
#: that decides `unchanged` alike.
DEFAULT_DISCOUNT_TYPE = 'percent'
DEFAULT_DISCOUNT_HOW = 'pretax'
DEFAULT_PAYMENT_TYPE = 'cash'


def _word_for(table: dict, value: int, absent: str) -> str:
    """The word for an engine value, and `absent` for a value with no word.

    Total on purpose, so a writer never has to decide what to do without a
    word. The only valueless value the engine produces is 0 — the state of a
    field nothing has set — and GnuCash rewrites 0 to exactly this default on
    save, so naming it here says what the book will hold rather than
    inventing something. A value from an enum some later GnuCash grows would
    read as the default too, and would want this table extended.
    """
    for word, known in table.items():
        if known == value:
            return word
    return absent


def discount_type_word(value: int) -> str:
    """`'percent'` or `'value'` — `percent` for a field nothing has set."""
    return _word_for(DISCOUNT_TYPES, value, DEFAULT_DISCOUNT_TYPE)


def discount_how_word(value: int) -> str:
    """`'pretax'`, `'sametime'` or `'posttax'` — `pretax` for an unset one."""
    return _word_for(DISCOUNT_HOWS, value, DEFAULT_DISCOUNT_HOW)


def payment_word(value: int) -> str:
    """`'cash'` or `'card'` — `cash` for a bill line nothing has set."""
    return _word_for(PAYMENT_TYPES, value, DEFAULT_PAYMENT_TYPE)


def billable_to(lib, entry_ptr):
    """`(customer_id, other_owner_id)` — whom a billable line is re-billed to.

    At most one is ever non-empty, and both are empty for a line billed to
    nobody. `customer_id` is what `billable_to:` states; `other_owner_id`
    names an owner this format has no key for, and answering rather than
    raising is what lets each caller decide:

    - a writer cannot state it, so it refuses — and refuses where it knows
      which document and which line it is writing, which is what a reader
      needs to find it;
    - the comparison that decides `unchanged` wants the plain answer. A file
      states a customer or nobody, so an entry billed to a job matches
      neither, and the rebuild that follows replaces it with what the file
      says. Raising there closed the ledger route to *fixing* such a line
      and left the GUI as the only way out of a book that could then be
      neither exported nor re-imported.

    GnuCash's Bill window calls it the chargeback project, and the engine
    keeps it as a `GncOwner` on the entry — a second owner beside the
    vendor's, which is what makes `billable:` worth anything: a line marked
    billable to nobody is one GnuCash cannot offer when the customer's
    invoice is raised. A job is its other chargeback target, persists as
    owner type 3, and is what `other_owner_id` names.

    **An owner is judged by what it names, not by its type.** `gncEntryCreate`
    initialises the field with `gncOwnerInitCustomer(..., NULL)`, so an entry
    nobody has touched reads as a *customer* owner with no customer behind it
    — measured on 3.8 and 5.10, type 2 and a null id, before a save and after
    one. The id is what answers, and an empty one is the absence, whatever
    the type says.
    """
    from gnucash.gnucash_business import GNC_OWNER_CUSTOMER

    from infrastructure.gnucash.engine import safe_ctypes_string

    owner = lib.gncEntryGetBillTo(entry_ptr)
    if not owner:
        return ('', '')
    named = safe_ctypes_string(lib.gncOwnerGetID, owner) or ''
    if not named:
        return ('', '')
    if lib.gncOwnerGetType(owner) == GNC_OWNER_CUSTOMER:
        return (named, '')
    return ('', named)


def set_billable_to(lib, entry_ptr, customer) -> None:
    """Re-bill this line to `customer`, or to nobody when it is `None`.

    `gncEntrySetBillTo` copies the owner it is handed — measured on 3.8 and
    5.10 by freeing the owner immediately afterwards and reading the id back
    — so the one allocated here is freed rather than kept alive for as long
    as the entry.

    Nobody is an owner initialised with no customer, which is what a fresh
    entry already holds: the field cannot be emptied by type, only by the
    customer behind it.
    """
    owner = lib.gncOwnerNew()
    try:
        lib.gncOwnerInitCustomer(
            owner, int(customer.instance) if customer is not None else None)
        lib.gncEntrySetBillTo(entry_ptr, owner)
    finally:
        lib.gncOwnerFree(owner)
