"""
Beancount parser service for importing GnuCash-compatible beancount files.

Parses beancount files with GnuCash metadata and validates them for import.
"""

import re
from dataclasses import dataclass
from datetime import datetime
from fractions import Fraction
from typing import Dict, List, Optional


@dataclass
class BeancountCommodity:
    """Beancount commodity with GnuCash metadata"""
    date: datetime
    symbol: str
    gnucash_mnemonic: str
    gnucash_namespace: str
    gnucash_fullname: Optional[str] = None
    gnucash_fraction: int = 100


@dataclass
class BeancountAccount:
    """Beancount account with GnuCash metadata"""
    date: datetime
    account: str
    commodity: str
    gnucash_name: str
    gnucash_guid: str
    gnucash_type: str
    gnucash_placeholder: str
    gnucash_code: Optional[str] = None
    gnucash_description: Optional[str] = None
    gnucash_tax_related: str = "False"
    # The account's own smallest unit when it differs from its commodity's.
    # Absent means "the commodity's", which is what most accounts have.
    gnucash_scu: Optional[str] = None


@dataclass
class BeancountPosting:
    """Beancount posting with GnuCash metadata"""
    account: str
    amount: str
    commodity: str
    gnucash_memo: Optional[str] = None
    gnucash_action: Optional[str] = None
    # Beancount's `@ <rate> <commodity>` — what one unit of this posting's
    # commodity is worth in the transaction's. A cross-commodity posting has
    # two figures, and this is the second one.
    price: Optional[str] = None
    price_commodity: Optional[str] = None


@dataclass
class BeancountTransaction:
    """Beancount transaction with GnuCash metadata"""
    date: datetime
    flag: str
    payee: Optional[str]
    narration: Optional[str]
    gnucash_guid: str
    postings: List[BeancountPosting]
    gnucash_notes: Optional[str] = None
    gnucash_doclink: Optional[str] = None


# What a posting line looks like. Compiled once and named, because it is asked
# in two places: to read a posting, and to tell an unindented posting from the
# next top-level directive.
#
# `@@ <total>` states outright what a cross-commodity posting is worth in the
# transaction's currency — the form this exporter writes, because a rate is a
# quotient that has to be rounded to write down. `@ <rate>` is the per-unit
# form, which hand-written files use and beancount's own docs lead with, and
# `{…}` is a cost basis, which says the same thing a third way. Dropped on the
# way in, a split was valued at its own amount instead — 12.345 units of a fund
# entered as 12.345 CAD against 1,234.50 of cash — and GnuCash balanced the
# difference into an `Imbalance-FUNDX` account it invented, in units of the
# fund.
#
# A cost basket may carry a date and a label after its figure —
# `{1.35 CAD, 2024-01-01}`, `{1.35 CAD, "lot-a"}` — which is how beancount's
# own documentation writes one. Those say which lot, and GnuCash has no
# per-lot cost on a split to put them on, so they are read and dropped rather
# than refused. A leading `!` or `*` flags the posting, and says nothing
# GnuCash keeps, so it goes the same way; refused, it took the whole file with
# it.
#
# The closing braces are made to match the opening, because the doubled form
# means the total and the single form means the rate: accepting
# `{{135.00 CAD}` read a total as a per-unit price, a hundredfold error from
# one missing character.
_POSTING = re.compile(
    r'(?:[!*]\s+)?'
    # `\S+` for the account, not `\S+(?::\S+)*`. The two match the same
    # strings — a colon is not a space — but the second can decompose a
    # k-colon token 2^k ways, and this pattern is deliberately run against
    # lines that *fail* it: the unreadable-posting refusal and the
    # unindented-directive check both ask it about text that is not a
    # posting. A failing match is where a regex does its backtracking.
    r'(\S+)\s+([-+\d.]+)\s+(\S+?)'
    r'(?:\s*(?:(\{\{)\s*(?:([-+\d.]+)\s+([^\s,}]+))?'
    r'\s*(?:,[^}]*)?\}\}'
    r'|(\{)(?!\{)\s*(?:([-+\d.]+)\s+([^\s,}]+))?'
    r'\s*(?:,[^}]*)?\}))?'
    # `\s*` on *both* sides of the sigil, because beancount reads `@` and `@@`
    # as tokens of their own: `@1.35`, `@ 1.35`, `USD@1.35` and `USD@ 1.35`
    # are one thing written four ways, and a person writing by hand writes all
    # of them. Spelled with the space after optional and the space before
    # required, this was one rule answered two ways — `USD @1.35 CAD` read and
    # `USD@1.35 CAD` matched nothing at all, because the currency group
    # `(\S+?)` then has to swallow the sigil and the rate, leaving ` CAD` for
    # an anchored `\s*$`.
    #
    # A posting this parser cannot read is refused rather than skipped, on the
    # reasoning that skipping it would import the entry short and let GnuCash
    # scrub in an Imbalance — so the cost was never the posting, it was the
    # whole ledger. The cost basket already tolerated the same shape, which is
    # what makes the difference an oversight rather than a rule.
    #
    # Safe against the currency group: a commodity cannot contain `@`, so the
    # only way `(\S+?)` reaches one is by over-running the currency, and
    # backtracking hands it back. The amount group cannot start with `@`
    # either, so nothing else changes shape.
    r'(?:\s*(@@?)\s*([-+\d.]+)\s+(\S+))?\s*$')


class BeancountValidationError(Exception):
    """Exception raised when beancount file fails validation"""
    pass


def _without_trailing_comment(line: str) -> str:
    """A posting line with beancount's `; …` comment taken off the end.

    Counted rather than matched, because both sides of the question carry the
    other's character: a lot label may hold a semicolon (`{1.35 CAD, "a;b"}`)
    and a comment may hold a quote (`; against "March statement"`). Cutting at
    the first `;` broke the first; cutting only when no quote followed broke
    the second, and the file went with it either way.

    A `\\"` is a quote inside the string, not the end of it — the same rule
    `_STRING` reads by, and the two have to agree. Counting the escaped one as
    a terminator, `* "Paid \\"Acme; Ltd\\""` looked closed at `Acme`, so the
    `;` read as a comment, the line was cut inside its own string, and the
    header that was left did not parse: the whole ledger refused over a
    description this tool had just written.
    """
    in_quotes = False
    skip = False
    for position, character in enumerate(line):
        if skip:
            skip = False
        elif character == '\\':
            skip = True
        elif character == '"':
            in_quotes = not in_quotes
        elif character == ';' and not in_quotes:
            return line[:position].strip()
    return line.strip()


def _figure(raw: str, what: str, posting_line: str, date_str: str) -> Fraction:
    """One figure off a posting line, as a number, or a refusal that says so.

    The posting regex asks only for digits, dots and a sign, so `5.0.0`, `.`
    and `--` all get past it and fail in the arithmetic below. Left to fail
    there they surfaced as a bare `ValueError: Invalid literal for Fraction:
    '5.0.0'` — no file, no line, no posting quoted — and as a `ValueError`
    they escaped the per-object handler too, taking the whole run out through
    the CLI's blanket catch.
    """
    try:
        return Fraction(raw)
    except (ValueError, ZeroDivisionError) as exc:
        raise BeancountValidationError(
            f"Transaction at {date_str}: the posting {posting_line!r} states "
            f"{what} that is not a number: {raw!r}") from exc


# What stands where a transaction's flag goes. `*` is settled and `!` is
# flagged-for-review, and beancount's own documentation gives `txn` as the
# third spelling — `2014-05-05 txn "Cafe Mogador" "Lamb tagine"`. Recognised on
# `[*!]` alone, a `txn` entry matched nothing and was skipped in silence with
# its metadata and its postings; its accounts never reached the used-account
# set either, so the file passed validation with the entry simply gone.
#
# The word boundary belongs to `txn` alone: `*` is not a word character, so a
# `\b` after the group would need one next to it and `2024-02-01 * "Grocer"`
# would stop matching.
_FLAG = r'(txn\b|[*!])'


# A beancount double-quoted string, escapes and all. `[^"]*` stops at the
# first inner quote, which is where a description like `Paid "Acme" Ltd` — a
# supplier named in quotes, ordinary in a book — took the header apart: the
# rest of the line was then not a header, and a header that does not parse
# takes the whole ledger with it.
_STRING = r'"((?:[^"\\]|\\.)*)"'


def _unescape(text):
    """What a beancount string says, with its escapes read.

    One left-to-right pass, because an escape may produce the character the
    next pass looks for. `C:\\name` is written `C:\\\\name`, and read as three
    replacements the `\\n` pass fired on the second backslash and the `n`: the
    text came back as `C:\\` + a newline + `ame`, and the `\\\\` pass had
    nothing left to undo. Silent, and permanent after one round trip.

    `None` through unchanged: the header's two strings are optional, and which
    of them is absent is the difference between a payee and a narration.
    """
    if text is None:
        return None
    return re.sub(r'\\(.)',
                  lambda m: '\n' if m.group(1) == 'n' else m.group(1),
                  text)


def _a_date(date_str: str, directive: str):
    """A `YYYY-MM-DD` off a directive, as a date, or a refusal naming it.

    The pattern every directive is recognised by admits `2024-02-30`, which
    `strptime` then refuses two lines later — as a bare `ValueError: day is
    out of range for month`, which is neither the refusal the import collects
    per object nor a message that says which line.
    """
    try:
        return datetime.strptime(date_str, '%Y-%m-%d')
    except ValueError as exc:
        raise BeancountValidationError(
            f"{directive}: {date_str} is not a date") from exc


def a_whole_number(raw: str, what: str, directive: str) -> int:
    """One of the counted values off a directive, as a number, or a refusal.

    Public because the import use case reads the same values off directives
    this parser produced and has to refuse them the same way — a fraction and
    an SCU written as `1,000` or `1.0` are one mistake with one message,
    wherever the reader of the file happens to be standing.
    """
    try:
        return int(raw)
    except ValueError as exc:
        raise BeancountValidationError(
            f"{directive}: {what} is not a whole number: {raw!r}") from exc


def _metadata_line(stripped: str) -> bool:
    """Whether this line is still part of the metadata block above it.

    Metadata is one form everywhere in beancount — `key: "value"` under a
    commodity, an `open`, a transaction header or a posting alike — and
    nothing orders it. Editors write their own keys into it: fava puts `name:`
    and `color:` on accounts. This tool keeps only the `gnucash-*` ones, so
    the block is read to its end and they are picked out of it.

    Read only until the first key it does not keep, a foreign line hid every
    key below it, and what that cost depended on where the person typed it: a
    file refused for a `gnucash-guid` it plainly carries, or a note, a
    document link, an account's own unit or a commodity's fraction dropped
    without a word.

    The test is the shape of a metadata line, which no directive and no
    posting has: a directive opens with its date, and a posting's account
    holds no `key:` followed by a space (`Assets:Bank` is one word to the
    colon and `Bank` after it).
    """
    return bool(stripped) and re.match(r'^[\w-]+:\s', stripped) is not None


def _metadata_block(lines: List[str], start: int) -> tuple:
    """Every `key: "value"` under a directive, and the line the block ends on.

    One walk for all four — a commodity, an `open`, a transaction header and a
    posting — because it is one form in beancount and they were four copies
    that drifted apart. A comment is taken in its stride: beancount allows one
    anywhere, and above the line it is about is where a person annotating an
    export puts it, so stopping there dropped every key below it.
    """
    metadata = {}
    i = start
    while i < len(lines):
        raw = lines[i].strip()
        if raw.startswith(';'):
            i += 1
            continue
        line = _without_trailing_comment(raw)
        if not _metadata_line(line):
            break

        # A quoted string, or the rest of the line. Beancount types its
        # metadata values and a number is written bare, which is how a person
        # widening an account's unit writes it: `gnucash-scu: 1000`. Read only
        # as a string, such a line was recognised as metadata, consumed, and
        # dropped without a word — the account stayed at its commodity's
        # fraction and GnuCash rounded every amount to it on save.
        match = re.match(r'([\w-]+):\s+' + _STRING + r'\s*$', line)
        if match:
            key, value = match.groups()
            metadata[key] = _unescape(value)
        else:
            key, _, value = line.partition(':')
            metadata[key] = value.strip()
        i += 1
    return metadata, i


def _refuse_a_total_against_no_units(posting_line: str, date_str: str):
    """`@@ total` and `{{total}}` both state a total, and neither can be nil.

    There is no rate to derive and nothing to spread the figure over, so
    reading it as unpriced dropped the total: the split was valued at zero and
    GnuCash scrubbed the whole figure into an Imbalance, with the run
    reporting success. The export refuses to write this shape for the same
    reason — beancount weighs a posting by its units times its cost — so the
    import says so rather than losing it.

    Both spellings, because they say the same thing: refusing only `@@` left
    the same statement, written `{{...}}`, going the other way.
    """
    raise BeancountValidationError(
        f"Transaction at {date_str}: the posting {posting_line!r} states a "
        f"total against no units, which beancount has nowhere to attach — a "
        f"posting is weighed by its units times its cost. State the units, or "
        f"drop the total if the posting is worth nothing")


class BeancountParser:
    """
    Parse GnuCash-compatible beancount files.

    This parser is specialized for beancount files exported from GnuCash
    with all gnucash-* metadata present. It validates that all required
    metadata exists and no implicit accounts are used.
    """

    def __init__(self):
        self.commodities: List[BeancountCommodity] = []
        self.accounts: List[BeancountAccount] = []
        self.transactions: List[BeancountTransaction] = []
        self.opened_accounts: set = set()
        self.used_accounts: set = set()

    def parse_file(self, file_path: str):
        """
        Parse beancount file and extract all directives.

        Args:
            file_path: Path to beancount file

        Raises:
            BeancountValidationError: If file has validation errors
        """
        # UTF-8, which is what beancount files are and what this tool writes.
        with open(file_path, encoding='utf-8') as f:
            content = f.read()

        self.parse(content)

    def parse(self, content: str):
        """
        Parse beancount content string.

        Args:
            content: Beancount file content

        Raises:
            BeancountValidationError: If content has validation errors
        """
        lines = content.split('\n')
        i = 0

        while i < len(lines):
            line = lines[i].strip()

            # Skip empty lines and comments
            if not line or line.startswith(';'):
                i += 1
                continue

            # What a line is, is decided by where the keyword sits — after the
            # date and nowhere else. Asked as `' commodity ' in line`, the test
            # read the payee and the narration too, so an ordinary entry
            # described as "Bought a commodity for resale" was taken for a
            # commodity declaration, failed to parse as one, and refused the
            # whole file. Same for `' open '`, and both were asked ahead of the
            # anchored test for a transaction below, so neither could be
            # corrected by it.
            # The keyword is what makes it one of these, and the shape of the
            # rest is the sub-parser's to judge. Asked for the whole shape
            # here, a directive with the symbol or the account edited off it
            # matched nothing and was skipped in silence — the `commodity`
            # came back as "Cannot find commodity" from an account three
            # directives later, and the `open` as "Implicit accounts not
            # allowed" against a file that plainly opens the account.
            if re.match(r'^\d{4}-\d{2}-\d{2}\s+commodity\b', line):
                commodity, lines_consumed = self._parse_commodity(lines, i)
                self.commodities.append(commodity)
                i += lines_consumed
                continue

            # Parse open account
            if re.match(r'^\d{4}-\d{2}-\d{2}\s+open\b', line):
                account, lines_consumed = self._parse_account(lines, i)
                self.accounts.append(account)
                self.opened_accounts.add(account.account)
                i += lines_consumed
                continue

            # Parse transaction
            if re.match(r'^\d{4}-\d{2}-\d{2}\s+' + _FLAG, line):
                transaction, lines_consumed = self._parse_transaction(lines, i)
                self.transactions.append(transaction)
                for posting in transaction.postings:
                    self.used_accounts.add(posting.account)
                i += lines_consumed
                continue

            i += 1

        # Validate after parsing
        self._validate()

    def _parse_commodity(self, lines: List[str], start_idx: int) -> tuple:
        """Parse commodity directive and its metadata"""
        # Comment off first, as the transaction header does it. Left on, it is
        # read as part of the directive — and what a directive says is what
        # everything downstream is told, so the complaint arrives somewhere
        # else about something else.
        line = _without_trailing_comment(lines[start_idx].strip())
        match = re.match(r'(\d{4}-\d{2}-\d{2})\s+commodity\s+(\S+)', line)
        if not match:
            raise BeancountValidationError(f"Invalid commodity directive: {line}")

        date_str, symbol = match.groups()
        date = _a_date(date_str, f'Commodity {symbol}')

        metadata, i = _metadata_block(lines, start_idx + 1)

        # Validate required metadata
        if 'gnucash-mnemonic' not in metadata:
            raise BeancountValidationError(
                f"Commodity {symbol} missing required gnucash-mnemonic metadata"
            )
        if 'gnucash-namespace' not in metadata:
            raise BeancountValidationError(
                f"Commodity {symbol} missing required gnucash-namespace metadata"
            )

        commodity = BeancountCommodity(
            date=date,
            symbol=symbol,
            gnucash_mnemonic=metadata['gnucash-mnemonic'],
            gnucash_namespace=metadata['gnucash-namespace'],
            gnucash_fullname=metadata.get('gnucash-fullname'),
            gnucash_fraction=a_whole_number(
                metadata.get('gnucash-fraction', '100'),
                'gnucash-fraction', f'Commodity {symbol}')
        )

        return commodity, i - start_idx

    def _parse_account(self, lines: List[str], start_idx: int) -> tuple:
        """Parse account open directive and its metadata"""
        # And here, where it costs the most: the currency constraint is
        # optional, so `open Assets:Bank  ; opened in March` read the comment
        # as the currency and opened the account in `;`. Nothing refused it —
        # it surfaced three directives later as `Cannot find commodity
        # (CURRENCY, ;)`, against a line that names no commodity at all.
        line = _without_trailing_comment(lines[start_idx].strip())
        match = re.match(r'(\d{4}-\d{2}-\d{2})\s+open\s+(\S+)(?:\s+(\S+))?', line)
        if not match:
            raise BeancountValidationError(f"Invalid open directive: {line}")

        date_str, account, commodity = match.groups()
        # Beancount's currency constraint is optional and means "any"; a
        # GnuCash account is kept in exactly one commodity, so there is
        # nothing to write. Said here rather than three directives later,
        # where it read `Cannot find commodity (CURRENCY, )` — a complaint
        # about a commodity, on a line that names none. Guessing the book's
        # own currency instead would open the account in it silently, and an
        # account's currency is not something to be wrong about quietly.
        if not commodity:
            raise BeancountValidationError(
                f"Invalid open directive: {line} — this format needs the "
                f"currency the account is kept in, as `open {account} CAD`. "
                f"Beancount leaves it optional and reads it as any currency; "
                f"a GnuCash account has exactly one.")
        date = _a_date(date_str, f'Account {account}')

        metadata, i = _metadata_block(lines, start_idx + 1)

        # Validate required metadata
        required = ['gnucash-name', 'gnucash-guid', 'gnucash-type', 'gnucash-placeholder']
        for key in required:
            if key not in metadata:
                raise BeancountValidationError(
                    f"Account {account} missing required {key} metadata"
                )

        # Present and empty is not the same as present, and a name is empty in
        # parts as well as whole. `gnucash-name` is the account the postings
        # mean, and both shapes were taken:
        #
        #   - `""` — looking an empty path up answers with the root account
        #     (`find_account` reads `''` as "the tree itself"), so the creation
        #     took that for "already there" and skipped. The book came back an
        #     account short of what the file declared, with the run counting it
        #     and reporting success.
        #   - `"Assets:Bank:"` — measured, it made the nothing it names: a
        #     child with no name at all under Assets:Bank, which GnuCash shows
        #     as an empty row and every export writes back as the same typo.
        #
        # Said here, where the rest of the shape of an `open` is judged.
        if not all(part.strip()
                   for part in metadata['gnucash-name'].split(':')):
            raise BeancountValidationError(
                f"Account {account} has a gnucash-name that names nothing: "
                f"{metadata['gnucash-name']!r} — that is the GnuCash account "
                f"its postings mean, and every part of it has to name one"
            )

        account_obj = BeancountAccount(
            date=date,
            account=account,
            commodity=commodity or "",
            gnucash_name=metadata['gnucash-name'],
            gnucash_guid=metadata['gnucash-guid'],
            gnucash_type=metadata['gnucash-type'],
            gnucash_placeholder=metadata['gnucash-placeholder'],
            gnucash_code=metadata.get('gnucash-code'),
            gnucash_description=metadata.get('gnucash-description'),
            gnucash_tax_related=metadata.get('gnucash-tax-related', 'False'),
            gnucash_scu=metadata.get('gnucash-scu')
        )

        return account_obj, i - start_idx

    def _parse_transaction(self, lines: List[str], start_idx: int) -> tuple:
        """Parse transaction and its postings"""
        # The comment off first, as every other line of the file has it taken
        # off: a header read to the end of the line without it was refused for
        # `; from the March statement`, and the header is where a person is
        # likeliest to write one — which statement the entry came off.
        line = _without_trailing_comment(lines[start_idx].strip())

        # Parse transaction header, to the end of the line. Left unanchored it
        # read as far as it could and called the rest agreement: `2024-02-01 *
        # Payee Lunch` — the quotes forgotten, which is the commonest thing to
        # forget — matched with both strings unread, and the entry imported
        # with no payee and no description at all. Beancount's own tags and
        # links may follow the strings, and do not carry over to GnuCash.
        match = re.match(
            r'(\d{4}-\d{2}-\d{2})\s+' + _FLAG +
            r'(?:\s+' + _STRING + r')?(?:\s+' + _STRING + r')?'
            r'(?:\s+[#^][^\s]+)*\s*$', line)
        if not match:
            raise BeancountValidationError(
                f"Invalid transaction: {line} — a transaction is a date, a "
                f"flag, and a payee and a narration in double quotes")

        date_str, flag, payee, narration = match.groups()
        payee = _unescape(payee)
        narration = _unescape(narration)
        date = _a_date(date_str, 'Transaction')

        # One string is beancount's narration, not its payee. How many strings
        # there are, not whether they say anything: asked the second way, a
        # header carrying a number and an empty description — `* "CHK-1001"
        # ""`, which is what a cheque written before anyone said what it was
        # for exports as — swapped too, and the number came back as the
        # description with the number gone. That is the shape the plaintext
        # export met under Q-020 and answers the same way.
        if payee is not None and narration is None:
            narration = payee
            payee = None

        tx_metadata, i = _metadata_block(lines, start_idx + 1)

        # Validate required transaction metadata
        if 'gnucash-guid' not in tx_metadata:
            raise BeancountValidationError(
                f"Transaction at {date_str} missing required gnucash-guid metadata"
            )

        # Parse postings
        postings = []
        while i < len(lines):
            posting_line = lines[i].strip()

            # Stop at empty line (end of transaction)
            if not posting_line:
                break

            # Normalised before anything is asked of it, because two questions
            # are asked and they have to see the same string: "is this a
            # posting that lost its indent?" below, and "read this posting"
            # further down. Asked of the raw line, the first missed exactly
            # the two spellings this parser had just learned — a de-indented
            # `Assets:Bank -1,050.00 CAD` or one carrying a `; note` matched
            # nothing, so the transaction imported a posting short and GnuCash
            # scrubbed in the Imbalance.
            #
            # A trailing `; …` comment is beancount's, not part of the
            # posting, and only outside quotes, so a lot label may hold one:
            # `{1.35 CAD, "a;b"}` was cut mid-brace and then reported as
            # unreadable. Commas between digit groups are beancount's own
            # number grammar — `1,234.50` is what its documentation and every
            # hand-kept ledger use — and go only between digits, so the same
            # lot label keeps its comma.
            posting_line = _without_trailing_comment(posting_line)
            posting_line = re.sub(r'(?<=\d),(?=\d\d\d(?:\D|$))', '',
                                  posting_line)
            if not posting_line:
                i += 1
                continue

            # A line at column zero is the next top-level directive, and
            # beancount does not require a blank line before one. That is a
            # legitimate end of this transaction, not an unreadable posting —
            # treated as the latter, a file whose entries simply run on was
            # refused outright, and so was one carrying `option`, `plugin`,
            # `include` or `poptag` after its last posting.
            #
            # Indentation is beancount's own discriminator: postings and their
            # metadata are indented, directives are not. A date test alone
            # covered only the entries.
            if lines[i][:1] not in (' ', '\t'):
                # Unless it is a posting that lost its indentation, which is
                # the commonest hand-edit slip there is. Ending the
                # transaction there dropped it and everything below it in
                # silence — the outer loop matches none of the three directive
                # forms and skips on, GnuCash scrubs in an Imbalance for what
                # is missing, and the run reports success. That is the failure
                # the refusal below exists to stop, arriving through the door
                # the indentation rule opened.
                if _POSTING.match(posting_line):
                    raise BeancountValidationError(
                        f"Transaction at {date_str}: the posting "
                        f"{posting_line!r} is not indented, so it reads as a "
                        f"new directive and the transaction would import "
                        f"without it — indent it under its transaction")
                break

            # What a cross-commodity posting is worth in the transaction's
            # currency. `@@ <total>` states it outright — the form this
            # exporter writes, because a rate is a quotient that has to be
            # rounded to write down. `@ <rate>` is the per-unit form, which
            # hand-written files use and beancount's own docs lead with, and
            # `{…}` is a cost basis, which says the same thing a third way.
            #
            # Dropped on the way in, the split was valued at its own amount
            # instead — 12.345 units of a fund entered as 12.345 CAD against
            # 1,234.50 of cash — and GnuCash balanced the difference into an
            # `Imbalance-FUNDX` account it invented, in units of the fund.
            # A cost basket may carry a date and a label after its figure —
            # `{1.35 CAD, 2024-01-01}`, `{1.35 CAD, "lot-a"}` — which is how
            # beancount's own documentation writes one. Those say which lot,
            # and GnuCash has no per-lot cost on a split to put them on, so
            # they are read and dropped rather than refused: the figure is
            # what this needs, and refusing the ordinary spelling of a form
            # the error message advertises is the worse answer.
            # A leading `!` or `*` flags the posting — beancount's way of
            # marking one for attention, and a form a person writes. It says
            # nothing GnuCash keeps, so it is read and dropped; refused, it
            # took the whole file with it.
            #
            # The closing braces are made to match the opening, because the
            # doubled form means the total and the single form means the rate:
            # accepting `{{135.00 CAD}` read a total as a per-unit price, a
            # hundredfold error from one missing character.
            match = _POSTING.match(posting_line)
            if not match:
                # Not "end of transaction" — a line inside one that this
                # cannot read. Treated as the end, the postings below it were
                # dropped in silence and the transaction imported short, so
                # GnuCash balanced what was left with an Imbalance split and
                # the run reported success. Say so instead.
                #
                # This costs the whole file rather than the one transaction,
                # unlike a bad account or a bad entry. The parse runs over the
                # file before anything is built, and what it cannot read it
                # cannot skip either: the postings below the line are what
                # would be lost, and losing them silently is the failure this
                # exists to stop.
                raise BeancountValidationError(
                    f"Transaction at {date_str}: cannot read the posting line "
                    f"{posting_line!r} — a posting is "
                    f"`Account amount COMMODITY`, optionally followed by "
                    f"`@ rate CUR`, `@@ total CUR`, or `{{cost CUR}}`. The "
                    f"amount is not optional: beancount lets one posting "
                    f"leave it out and take whatever balances the entry, and "
                    f"this reads figures rather than working them out")

            (account, amount, commodity,
             double_brace, total_cost, total_cost_commodity,
             single_brace, unit_cost, unit_cost_commodity,
             price_kind, price_figure, price_commodity) = match.groups()
            braces = double_brace or single_brace
            cost = total_cost if total_cost is not None else unit_cost
            cost_commodity = total_cost_commodity or unit_cost_commodity

            # Read here rather than left to `string_to_gnc_numeric` further
            # down, because a total has to be divided by it. A figure the
            # regex admits but arithmetic does not — `5.0.0`, `.`, `--` —
            # would otherwise surface as `Invalid literal for Fraction:
            # '5.0.0'` with no file, no line and no posting quoted, two
            # branches away from a refusal that quotes all three.
            # Every figure on the line, not only the amount: the same regex
            # class admits the same garbage in the rate and the cost, and both
            # of those reach `Fraction` too — one here, one further down in
            # the importer. Guarded separately, `@@ 1.2.3 CAD` escaped as a
            # bare `ValueError` past the per-object handler, which is the
            # shape this exists to remove.
            units = abs(_figure(amount, 'an amount', posting_line, date_str))
            if price_figure is not None:
                _figure(price_figure, 'a price', posting_line, date_str)
            if cost is not None:
                _figure(cost, 'a cost', posting_line, date_str)

            # A total restated as a rate, so `price` means one thing to
            # everything downstream — it multiplies the amount by it. Zero
            # units have no rate, and no total to spread over them either.
            #
            # A cost basket wins over a price, and both may be on one line.
            # That is beancount's own rule: a posting held at cost balances at
            # `units × cost`, and `@ price` beside it is what the units are
            # worth today, which the entry does not balance at. Read the other
            # way round, the standard spelling of a disposal at a gain —
            # `-10 HOOL {500.00 USD} @ 550.00 USD` — valued the holding at
            # 5,500.00 instead of the 5,000.00 it cost, the splits summed to
            # the gain, and GnuCash scrubbed in `Imbalance-USD 500.00` while
            # the run reported one transaction and no error. It also let
            # `{} @ 1.35` past the empty-basket refusal below.
            if cost is not None:
                # `{cost}` is per unit and `{{cost}}` is the total, the same
                # distinction `@` and `@@` draw — including what a total
                # against no units means, which is nothing statable. The
                # per-unit form against no units is honest: it weighs
                # `units × cost`, which is 0, and loses no figure doing it.
                if braces == '{{':
                    if not units:
                        _refuse_a_total_against_no_units(posting_line, date_str)
                    price = str(Fraction(cost) / units)
                else:
                    price = cost
                price_commodity = cost_commodity
            elif braces is not None:
                # An empty basket. In beancount `{}` means "held at cost, and
                # the cost is to be inferred" — inferred by a booking algorithm
                # against the lots the account already holds, which is a thing
                # this tool does not have and GnuCash does not keep the state
                # for. Read as an unpriced posting it would be silently wrong
                # in the one place it matters: a genuine conversion, valued at
                # its own amount, with GnuCash inventing an Imbalance for the
                # difference. So it is said rather than guessed at.
                raise BeancountValidationError(
                    f"Transaction at {date_str}: the posting "
                    f"{posting_line!r} holds its cost at `{{}}`, which asks "
                    f"for the cost to be inferred from the lots the account "
                    f"already holds — this reads a cost, it does not work one "
                    f"out. State it: `{{rate CUR}}`, `{{{{total CUR}}}}`, "
                    f"`@ rate CUR` or `@@ total CUR`")
            elif price_kind == '@@':
                if not units:
                    _refuse_a_total_against_no_units(posting_line, date_str)
                price = str(Fraction(price_figure) / units)
            elif price_kind == '@':
                price = price_figure
            else:
                price = None

            posting_metadata, j = _metadata_block(lines, i + 1)

            posting = BeancountPosting(
                account=account,
                amount=amount,
                commodity=commodity,
                gnucash_memo=posting_metadata.get('gnucash-memo'),
                gnucash_action=posting_metadata.get('gnucash-action'),
                price=price,
                price_commodity=price_commodity
            )
            postings.append(posting)

            i = j

        transaction = BeancountTransaction(
            date=date,
            flag=flag,
            payee=payee,
            narration=narration,
            gnucash_guid=tx_metadata['gnucash-guid'],
            postings=postings,
            gnucash_notes=tx_metadata.get('gnucash-notes'),
            gnucash_doclink=tx_metadata.get('gnucash-doclink')
        )

        return transaction, i - start_idx

    def _validate(self):
        """Validate parsed beancount file for GnuCash import"""
        errors = []

        # Check for implicit accounts
        implicit_accounts = self.used_accounts - self.opened_accounts
        if implicit_accounts:
            errors.append(
                f"Implicit accounts not allowed: {', '.join(sorted(implicit_accounts))}. "
                f"All accounts must have 'open' directives with gnucash-* metadata."
            )

        if errors:
            raise BeancountValidationError("\n".join(errors))

    def get_account_mapping(self) -> Dict[str, str]:
        """
        Get mapping from beancount account names to GnuCash account names.

        Returns:
            Dict mapping beancount name -> gnucash name
        """
        return {acc.account: acc.gnucash_name for acc in self.accounts}
