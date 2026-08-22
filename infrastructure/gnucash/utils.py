"""
GnuCash utility functions

These utilities work with GnuCash Python binding objects (Account, Transaction, etc.)
Extracted from legacy utils.py and placed in new architecture.
"""

import copy
from contextlib import contextmanager, suppress
from decimal import Decimal
from fractions import Fraction
from typing import List, Optional, Union

from gnucash import Account, GncCommodity, GncNumeric, Transaction
from gnucash.gnucash_core_c import GNC_HOW_RND_ROUND_HALF_UP


@contextmanager
def transaction_under_construction(book):
    """A new transaction, open for editing, destroyed if the build refuses.

    Splits are attached one at a time and each figure is judged as it is
    reached, so a refusal on the second line lands with the first already
    attached. Left alone, that entry stays in the book: `Destroy` only marks
    a transaction, and the commit is what carries the mark out, so an
    abandoned build leaves both a half-written entry and an edit nothing
    closes.

    GnuCash does not write a transaction whose edit was never committed, so
    the saved file looks clean and the wreckage is invisible there. It is not
    invisible to the rest of the same run: duplicate matching, balances and
    cost bases all read the open book, and a phantom carrying one split is
    something for them to find. Measured — the entry is in the session's
    query results and absent from the file it saves.

    Written as a flag and a `finally` rather than `except Exception`, so a
    Ctrl-C part-way through takes the transaction with it too. A long import
    is the run most likely to be interrupted, and an open edit on an
    allocated transaction is exactly the state this exists to prevent.
    """
    transaction = Transaction(book)
    transaction.BeginEdit()
    finished = False
    try:
        yield transaction
        transaction.CommitEdit()
        finished = True
    finally:
        if not finished:
            # Suppressed, because this runs while the original exception is
            # in flight and that is the one the caller has to see. A destroy
            # that itself fails would otherwise replace the refusal that
            # explains what the reader has to fix.
            with suppress(Exception):
                transaction.Destroy()
                transaction.CommitEdit()


def qof_instance(obj):
    """What SWIG wants: the instance behind a wrapper, or the thing itself.

    ``Account.GetLotList()`` returns a raw ``SwigPyObject`` pointer on GnuCash
    3.8, 4.4, 4.8, 4.13, 5.5, 5.10, 5.13 and 5.14, and a wrapped ``GncLot`` on
    5.15 and 5.16 — measured on all ten
    (``tests/research/a_lot_can_be_named_probe.py``). ``int()`` refuses the
    wrapper outright, so a reader written against either half raises on the
    other while eight builds agree with each other, and the same three words
    were written out at fifteen call sites, each free to get it wrong on its
    own.

    So the difference is answered here, and asked for in the two shapes its
    callers need: this one for a SWIG call, ``qof_pointer`` for ctypes.
    """
    return getattr(obj, 'instance', obj)


def qof_pointer(obj) -> int:
    """What ctypes wants: the same instance as an integer."""
    return int(qof_instance(obj))


def wrap_invoice_or_bill(raw):
    """Wrap a ``gncInvoice`` QOF query result as the correct SWIG class:
    ``Bill`` for a vendor-owned record, ``Invoice`` for a customer-owned one.

    GnuCash stores customer invoices and vendor bills in one ``gncInvoice`` QOF
    type; only the Python class decides whether ``AddEntry`` / ``RemoveEntry``
    dispatch to the ``gncBill*`` functions (vendor bill) or the ``gncInvoice*``
    functions (customer invoice). A vendor bill MUST be wrapped as ``Bill`` so
    those operations — and the bill-side tax-flag persistence they drive — are
    correct. All read-only methods are inherited from ``Invoice``, so wrapping a
    bill as ``Bill`` never loses anything.
    """
    from gnucash.gnucash_business import GNC_OWNER_VENDOR, Bill, Invoice
    inv = Invoice(instance=raw)
    if inv.GetOwnerType() == GNC_OWNER_VENDOR:
        return Bill(instance=raw)
    return inv


def get_account_full_name(account: Account) -> str:
    """
    Get full hierarchical name of account (e.g., "Assets:Bank:Checking").

    Args:
        account: GnuCash Account object

    Returns:
        Full account name with hierarchy separated by colons
    """
    parent = account.get_parent()
    name = account.GetName()

    if parent is not None and (not parent.is_root()):
        name = ":".join([get_account_full_name(parent), name])
    return name


def get_parent_accounts_and_self(account: Account) -> List[Account]:
    """
    Get list of all parent accounts plus the account itself.

    Args:
        account: GnuCash Account object

    Returns:
        List of accounts from root to this account (inclusive)
    """
    accounts = [account]
    parent = account.get_parent()
    while parent is not None and not parent.is_root():
        accounts.insert(0, parent)
        parent = parent.get_parent()

    return accounts


def find_account(account: Account, name: str) -> Optional[Account]:
    """
    Find account by full path (e.g., 'Assets:Bank:Checking').

    Args:
        account: Root account to start search from
        name: Account path separated by colons

    Returns:
        Account object if found, None otherwise
    """
    if name == "" or name == "Root Account":
        return account

    names = name.split(":")

    def find_child(account: Account, name: str) -> Optional[Account]:
        for child in account.get_children_sorted():
            child_name = child.GetName()
            if child_name == name:
                return child
        return None

    acc = account
    for n in names:
        acc = find_child(acc, n)
        if acc is None:
            break

    return acc


def get_commodity_ticker(commodity: GncCommodity) -> str:
    """
    Get commodity ticker in format 'NAMESPACE.MNEMONIC' or just 'MNEMONIC' for currencies.

    Args:
        commodity: GnuCash Commodity object

    Returns:
        Ticker string (e.g., 'CAD', 'NASDAQ.AAPL')
    """
    mnemonic = commodity.get_mnemonic()
    namespace = commodity.get_namespace()
    if namespace == 'CURRENCY':
        return mnemonic
    return f'{namespace}.{mnemonic}'


def string_to_gnc_numeric(s, currency: GncCommodity) -> GncNumeric:
    """A number the file states, as a GncNumeric, exactly.

    Denominated in the currency's smallest unit when the figure fits it, which
    is how GnuCash stores an ordinary amount (12.34 CAD as 1234/100). Nothing
    that passes through here silently loses precision: `int(Decimal(s) *
    fraction)` truncates toward zero, so a rate of 1.405 became 1.40 and a yen
    rate of 0.0093 became 0.00, and the split values derived from them were
    wrong by whatever was thrown away.

    A figure finer than its commodity is answered two ways, by what the
    commodity *is*. Money is refused: a booked amount is a whole number of the
    currency's own units, and one that is not is not an amount this book can
    record. A security is not money — fund units are quoted to three decimals
    and more — so a quantity keeps its own denominator rather than being cut
    down to one.

    Args:
        s: String representation of number (e.g., '123.45', '50/3')
        currency: Currency commodity for fraction info

    Returns:
        GncNumeric object
    """
    s = str(s)
    if '/' in s:
        return GncNumeric(s)

    exact = Fraction(Decimal(s.replace(',', '.')))
    fraction = currency.get_fraction()
    scaled = exact * fraction
    # Only money is held to a currency's unit. This is called with whatever
    # commodity the account is in, and for a securities account that is a
    # stock or a fund — units of which are commonly quoted to three decimals
    # or more. Refusing those would refuse an ordinary holding, and break the
    # beancount round trip besides: the export writes the quantity the book
    # holds, and the re-import would reject what it had just written. The
    # codebase draws this line already — shares are counted and priced, not
    # converted.
    is_currency = (currency.get_namespace() or '').upper() == 'CURRENCY'
    if is_currency and scaled.denominator != 1:
        # A booked amount is a whole number of the currency's own units.
        # `18.190` passes — it is `18.19` with a trailing zero, and scales to
        # 1819 hundredths exactly. `18.191` does not, and is refused rather
        # than stored.
        #
        # GnuCash itself would store it, because it keeps a smallest unit per
        # *account* as well as per commodity. This tool does not follow it
        # there, and the reason is what happened when it did: the amount kept
        # the account's finer unit while the value was rounded to the
        # currency's, so a split in the transaction's own currency came out
        # with an amount of 18.191 and a value of 18.190 — an invented
        # exchange rate of 1819000/1819100 between CAD and CAD, and the books
        # saying two different things about one figure. Nothing caught it:
        # both splits were wrong by the same factor in opposite directions, so
        # the values still summed to zero, and the value sum is the only thing
        # anything checks. Measured on GnuCash 5.10, the import reported
        # `Errors: 0` and saved.
        raise ValueError(
            f'amount {s} is finer than {currency.get_mnemonic()} can hold: '
            f'the smallest unit is 1/{fraction}, and this needs a smaller '
            f'one. A trailing zero is fine — 18.190 is 18.19 — but a figure '
            f'that really needs the extra digit is not an amount of money '
            f'this book can record. Round it, or split it across entries.')
    if scaled.denominator != 1:
        # A security quantity finer than its commodity's fraction, kept as the
        # ratio it is. Scaling and taking the numerator would drop the rest of
        # it — 12.3456 units of a fund whose fraction is 100 would become 1234.
        return GncNumeric(exact.numerator, exact.denominator)
    return GncNumeric(scaled.numerator, fraction)


def to_money(value: Fraction, scu: int) -> GncNumeric:
    """`value` as a GnuCash amount in units of `scu` — cents for an ordinary
    currency — rounded the way money rounds.

    The rounding is GnuCash's own: `GNC_HOW_RND_ROUND_HALF_UP` sends an exact
    half away from zero, so 63.225 becomes 63.23. Python's `round` is banker's
    rounding and answers 63.22, a cent adrift — which is why the arithmetic is
    handed to the engine rather than done here.

    """
    exact = GncNumeric(Fraction(value).numerator, Fraction(value).denominator)
    return exact.convert(scu, GNC_HOW_RND_ROUND_HALF_UP)


def money_text(value: Fraction, scu: int) -> str:
    """An amount as text at its own currency's decimals — 63.23 CAD, 103 JPY.

    Every amount this tool writes goes through here, and every caller passes
    the smallest unit from the commodity that owns the amount — 100 where
    there are hundredths, 1 for a yen. The commodity is the only authority for
    how many decimals a currency has; the denominator a particular numeric
    happens to carry is not.

    The engine still decides the value: `to_money` rounds to that unit with
    `gnc_numeric_convert`, which answers identically on all seven supported
    distros. Writing it out is the part GnuCash does not lend us — its own
    amount printer (`xaccPrintAmount`, `gnc_commodity_print_info`) is absent
    from the Python bindings on every one of them — so the point is placed
    from the scu here.

    Inferring it from the numeric instead is what broke: `gnc_numeric_to_decimal`
    on GnuCash 3.8 (Ubuntu 20.04) reduces 0/100 to 0/1 where every later
    version keeps 0/100, so a zero wrote itself `0` on that one distro and
    `0.00` on the rest, in exports and on printed invoices alike. Probed on
    Debian 11/12/13 and Ubuntu 20.04/22.04/24.04/26.04: only 3.8 reduces, and
    only for zero.
    """
    minor = numeric_to_fraction(to_money(value, scu)) * scu
    if not is_power_of_ten(scu) or minor.denominator != 1:
        # A commodity whose fraction is not tenths, hundredths, … has no
        # decimal form at all; the amount is written as the fraction it is.
        return exact_text(value)

    places = len(str(scu)) - 1
    sign = '-' if minor < 0 else ''
    digits = str(abs(minor.numerator)).rjust(places + 1, '0')
    if places == 0:
        return sign + digits
    return f'{sign}{digits[:-places]}.{digits[-places:]}'


def is_power_of_ten(unit: int) -> bool:
    """Whether a commodity's smallest unit has a decimal form at all — tenths,
    hundredths, thousandths. Every ISO currency does; an exotic fraction does
    not, and an amount in one is written as the fraction it is."""
    return unit > 0 and str(unit) == '1' + '0' * (len(str(unit)) - 1)


def exact_text(value: Fraction) -> str:
    """A figure as text that says exactly what it is — 1.35, 103, or 4/3.

    For something that is not money and so has no smallest unit of its own — a
    rate, a quantity, a recomputed figure in an error message — written at
    however many decimals it actually needs, and as the fraction it is when no
    decimal says it exactly.
    """
    value = Fraction(value)
    unit = 1
    while unit <= 10 ** 9:
        if (value * unit).denominator == 1:
            return money_text(value, unit)
        unit *= 10
    return str(value)


def numeric_to_fraction(number) -> Fraction:
    """A GnuCash numeric as an exact Fraction, however it arrives.

    Most bindings hand back a wrapped `GncNumeric`, whose `num()`/`denom()` are
    methods. A few — `xaccAccountGetNoclosingBalanceChangeForPeriod` among them
    — hand back the bare `_gnc_numeric` struct, where the same two are plain
    integer attributes. Calling one on the other raises
    `TypeError: 'int' object is not callable`.
    """
    raw_num = number.num
    raw_denom = number.denom
    numerator = raw_num() if callable(raw_num) else raw_num
    denominator = raw_denom() if callable(raw_denom) else raw_denom
    return Fraction(int(numerator), int(denominator))


def gnc_numeric_to_fraction_or_decimal(number: GncNumeric) -> Union[Fraction, Decimal]:
    """
    Convert GncNumeric to Python Fraction or Decimal.

    Args:
        number: GnuCash numeric value

    Returns:
        Fraction if denominator is not power of 10, otherwise Decimal
    """
    number = copy.copy(number)
    numerator = int(number.num())
    denominator = int(number.denom())
    denom_str = str(denominator)

    # Check if denominator is power of 10 (1, 10, 100, 1000, etc.)
    if denom_str[0] == '1' and all(c == '0' for c in denom_str[1:]):
        num_decimal = Decimal(numerator)
        denom_decimal = Decimal(denominator)
        return num_decimal / denom_decimal
    else:
        return Fraction(numerator, denominator)


def to_string_with_decimal_point_placed(number: GncNumeric) -> str:
    """A figure whose own denominator says how many decimals it has — a rate or
    a quantity — as text, or as the fraction it is when it has no decimal form.

    Not for money. An amount's decimals come from the commodity that owns it,
    never from the numeric it happens to be carried in: that is `money_text`,
    which takes the smallest unit and is what every amount this tool writes
    goes through. GnuCash 3.8 reduces 0/100 to 0/1 here, so an amount written
    this way loses its decimals on that engine and keeps them on every other.

    Args:
        number: GnuCash numeric value

    Returns:
        String representation with decimal point (e.g., '123.45') or fraction (e.g., '50/3')
    """
    number = copy.copy(number)
    if not number.to_decimal(None):
        return str(number)

    numerator = str(number.num())
    point_place = str(number.denom()).count('0')  # How many zeros in the denominator?

    if point_place == 0:
        return numerator
    elif len(numerator) > point_place:
        return numerator[:-point_place] + '.' + numerator[-point_place:]
    else:
        return '0.' + '0' * (point_place - len(numerator)) + numerator


def format_amount_for_commodity(number, commodity) -> str:
    """Exact amount string at the commodity's own decimal count.

    GnuCash records each commodity's smallest unit as `get_fraction()` (100 for
    a 2-decimal currency like CAD, 1 for JPY/0-decimal, 1000 for 3-decimal). We
    read the value exactly via num()/denom() (or numerator/denominator for a
    Fraction) into a Decimal and quantize to that many places — never via
    `to_double()` (precision loss) and never guessing decimals from the
    numeric's own denominator (which may not be the commodity's SCU)."""
    frac = commodity.get_fraction() if commodity is not None else 100
    places = max(0, len(str(int(frac))) - 1)
    if isinstance(number, Fraction):
        d = Decimal(number.numerator) / Decimal(number.denominator)
    else:
        d = Decimal(number.num()) / Decimal(number.denom())
    return str(d.quantize(Decimal(1).scaleb(-places)))


#: Every key this format reads as a boolean, wherever it sits.
#:
#: A boolean is written `#True` / `#False` — the same `#` that marks `#None`
#: and `#3/4`, and what `encode_value_as_string` produces for a `bool`. It is
#: the only spelling that survives the round trip: a bare `true` decodes to
#: the *string* `'true'`, which is why `taxable: True` once read as false
#: (the flag was compared against `'true'` while `True` decoded to a bool)
#: and why `placeholder: false` reached SWIG as a string and killed the
#: account it was on.
#:
#: **This is a roster, not a switch.** Nothing in the reading or writing
#: path consults it: each writer calls `encode_value_as_string` on its own
#: flag and each reader calls `_a_yes_or_no` with its own key name. The one
#: consumer is `tests/integration/test_a_written_flag_is_a_typed_literal.py`,
#: which exports real books and asks of every line whose key is named here
#: whether the value is a typed literal — so adding a key to this list
#: widens that check and wires up nothing. A new flag needs its writer and
#: its reader written too, and belongs here so the check covers it.
#:
#: Reading is looser than writing on purpose: `_a_yes_or_no` also takes the
#: words a person writes by hand — `true`/`1`/`yes` and `false`/`0`/`no`, in
#: any case — so no ledger ever written stops importing.
FLAG_KEYS = frozenset({
    'placeholder', 'tax_related',           # an `open` block
    'closing',                              # a transaction
    'active',                               # a customer or a vendor
    'credit_note', 'auto_apply_credit',     # an invoice or a bill
    'accumulate',                           # a `posted:` block
    'taxable', 'tax_included', 'billable',  # an `entry:` block
    'from_credit',                          # a `payment:` block
    'cost_basis_force',                     # a split
})


def escape_string(s: str) -> str:
    """Escape the four characters a quoted plaintext value cannot hold raw.

    A quote and a backslash corrupt the *value*: the reader slices a quoted
    line from its first quote to its last and then unescapes it, so a
    backslash written raw is eaten and one written doubled comes back single.

    A newline corrupts the *block*, which is worse and is why escaping three
    of the four would be worse than escaping none: the reader is a line per
    key, so a raw newline ends the value mid-word and offers the rest of it
    to the parser as a key of its own. Escaped, the value stays on one line
    and the block is still a block.

    `str.maketrans` translates in one pass, so the backslashes this emits are
    not themselves escaped again.
    """
    if s is None:
        return s

    translation_table = str.maketrans({
        '"': '\\"',
        '\\': '\\\\',
        '\n': '\\n',
        '\r': '\\r',
    })
    return s.translate(translation_table)


def encode_value_as_string(value) -> str:
    """
    Encode value as string for plaintext format with proper quoting.

    Args:
        value: Value to encode (None, bool, int, float, Fraction, or str)

    Returns:
        Encoded string representation
    """
    if value is None:
        return '#None'
    if isinstance(value, bool):
        return f'#{value}'
    if isinstance(value, (int, float)):
        return f'{value}'
    if isinstance(value, Fraction):
        return f'#{value.numerator}/{value.denominator}'
    if isinstance(value, str):
        return f'"{escape_string(value)}"'
    # Fallback for other types
    return f'"{escape_string(str(value))}"'


def unescape_string(s: str) -> str:
    r"""Undo `escape_string`, reading left to right.

    One pass rather than a chain of `replace` calls, because a chain stops
    being right as soon as there is more than one escape: `C:\\name`
    unescaped by `\\`→`\` and then `\n`→newline gives `C:` and a newline,
    having read as an escape a backslash that was already part of the value.
    Scanning left to right, a backslash consumes exactly the character after
    it and no character can be read twice.

    A backslash before anything else — `\q`, or one ending the string —
    keeps both characters, so text a hand-written file never meant as an
    escape survives instead of being dropped.
    """
    if s is None:
        return s

    known = {'"': '"', '\\': '\\', 'n': '\n', 'r': '\r'}
    out = []
    index = 0
    while index < len(s):
        char = s[index]
        if char == '\\' and index + 1 < len(s) and s[index + 1] in known:
            out.append(known[s[index + 1]])
            index += 2
        else:
            out.append(char)
            index += 1
    return ''.join(out)


class NumberAsWritten(int):
    """A whole number decoded from a file, carrying the digits it was written with.

    `int('00000000000000000000000000000022')` is 22, and the digits the
    file wrote are gone with it — `0000…0022` and `22` decode alike. That
    matters where the value is not really a number: a `guid:` written
    without quotes is all-digit hex, and read as a number it can neither be
    used nor quoted back in a message, because nothing is left to quote.

    So the digits stay on the value. Readers that want the number are
    unaffected — this *is* an `int`, and compares, hashes and arithmetics
    as one — and a reader that needs the text the file carried asks for
    `.source`.
    """

    # No `__slots__`: `int` is a variable-length type, and a subclass of one
    # cannot declare a non-empty set — `TypeError: nonempty __slots__ not
    # supported for subtype of 'int'`, measured on Python 3.9 and 3.13.
    def __new__(cls, source: str):
        made = super().__new__(cls, source)
        made.source = source
        return made


def decode_value_from_string(s: str):
    """
    Decode value from plaintext string representation.

    Handles:
    - None values (#None)
    - Integers (123)
    - Floats (123.45)
    - Booleans (True, False, #True, #False)
    - Quoted strings ("...")
    - Numbers with # prefix (#100)

    Args:
        s: String representation

    Returns:
        Decoded value (int, float, bool, str, or None)
    """

    if s is None or s == '#None':
        return None
    if s == 'True' or s == '#True':
        return True
    if s == 'False' or s == '#False':
        return False
    if s.startswith('#'):
        s_no_hash = s[1:].strip()
        if s_no_hash.isnumeric():
            return NumberAsWritten(s_no_hash)
        try:
            return float(s_no_hash)
        except ValueError:
            pass
    elif s.startswith('"'):
        content = s[1:-1]
        return unescape_string(content)
    else:
        # Bare integer (e.g. fraction: 100) or bare float (e.g. fraction: 1)
        # All unquoted non-keyword values in the plaintext format are numbers.
        # The digits stay on the value: an unquoted `guid:` is all-digit hex
        # and `int` of it keeps none of what makes it a guid.
        if s.lstrip('-').isnumeric():
            return NumberAsWritten(s)
        try:
            return float(s)
        except ValueError:
            pass
    return s


def number_in_string_format_is_1(s: str) -> bool:
    """
    Check if a number string represents 1 (handles decimals like '1.0', '1.00').

    Args:
        s: String representation of number

    Returns:
        True if number represents 1
    """
    if '.' in s:
        return s.rstrip('0').rstrip('.') == '1'
    else:
        return s == '1'
