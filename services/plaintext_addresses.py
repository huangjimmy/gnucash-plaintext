"""Which line of an address a key names.

An address is the only value in this format that is a list rather than a line,
and a list is written one key per line, the key carrying the line's number:
`addr[0]`, `addr[1]`, and upwards. Every writer here does that — an owner's
address and the book's company address alike — and every reader joins them
back up.

That is the format's syntax for a list, not a limit on what a value may hold.
A value *can* hold a newline: `\\n` is one of the four escapes, and writing an
address as one escaped value would round-trip. It is not written that way, and
the keys are what every ledger already carries.

**How many lines there are is a property of the object, not of this syntax**,
and the two addresses differ:

- an **owner's** is a `GncAddress` — `addr1` through `addr4`, four fields and
  no fifth — so a fifth key has nowhere to go and is refused;
- the **book's own**, File → Properties → Business, is a single option holding
  as many lines as are typed into it, and nothing caps it.

Reading the owner's limit off the book's address is what made a six-line
company address export as four with the rest gone in silence.

**Why the number is in brackets.** The keys used to be `addr1`..`addr4`, and
the obvious way to lift the limit of four was to keep counting: `addr5`,
`addr6`. That reserves a namespace nobody agreed to give up. A block's custom
keys are the book owner's to name, and `abc1`/`abc2` are two unrelated keys —
so `addr` plus a number would have meant an address line here and an ordinary
key there, with a book that used `addr7` for something of its own silently
losing it to the address. Bracketed, the list is a syntax rather than a
convention: `addr[7]` is the eighth line, `addr7` is a key like any other, and
neither can be mistaken for the other.

`addr1`..`addr4` are still read, because ledgers holding them exist and an
address is not a thing to drop on a spelling change. They mean what they always
did — `addr1` is the first line, which is `addr[0]` — and nothing writes them
any more. A block naming a line both ways is refused rather than resolved,
since the two spellings differ by one and a reader who mixed them did not mean
the same line twice.

**How long an address may be.** The book's own — GnuCash's `Company Address`
option, one free multi-line string — is as long as it is; nothing in File →
Properties → Business stops at four lines. A customer's or a vendor's is a
`GncAddress`, which has exactly four fields and no fifth, so `addr[4]` on one
of those blocks is refused: there is nowhere to put it, and putting it in the
object's custom metadata is how it used to be lost — round-tripping through
the ledger perfectly while never appearing on a printed invoice.
"""

import re

#: A `GncAddress` has four fields — `SetAddr1`..`SetAddr4`. The book's company
#: address has no such limit; it is one string with newlines in it.
OWNER_ADDRESS_LINES = 4

#: Not a limit on how long an address may be — GnuCash puts none there, the
#: option being one free-text box, and a book it holds is a book this has to
#: be able to state. Nothing caps what the export writes, and a book with a
#: long address exports every line of it.
#:
#: This is a guard on a *stated index*, and it exists because the index is a
#: position: `addr[10000000]` in a file asks for a ten-million-line address,
#: and taken at its word it writes ten megabytes of newlines into the book and
#: has every later export state them back. A wider one — `addr[10**20]` —
#: raises `MemoryError` from the allocation, which reaches the reader as a
#: sentence about index-sized integers.
#:
#: So the number is only large enough to be unmistakably a typo when passed. A
#: real address is under a dozen lines; ten thousand is past anything a paste
#: accident produces and far below where allocating hurts. A file naming a
#: line beyond it is refused, and a book holding one is not — the two are
#: different questions, and only the first is asking this tool to invent
#: something.
MOST_ADDRESS_LINES = 10_000

_INDEXED_ADDRESS_RE = re.compile(r'^addr\[(\d+)\]$')

#: The spelling before the index moved into brackets. Read, never written.
LEGACY_ADDRESS_KEYS = ('addr1', 'addr2', 'addr3', 'addr4')


def address_key(index: int) -> str:
    """The key naming line `index`, counting from zero."""
    return f'addr[{index}]'


def address_line_index(key: str):
    """The 0-based line `key` names, or None if it names no address line."""
    match = _INDEXED_ADDRESS_RE.match(key or '')
    if match:
        return int(match.group(1))
    if key in LEGACY_ADDRESS_KEYS:
        return int(key[-1]) - 1
    return None


def is_address_key(key: str) -> bool:
    """Whether `key` names an address line, in either spelling."""
    return address_line_index(key) is not None


_ANY_INDEXED_RE = re.compile(r'^([a-z_][a-zA-Z0-9_\-.]*)\[(\d+)\]$')


def refuse_an_index_on_a_key_that_has_no_list(key: str) -> None:
    """A bracketed key is a list element, and the address is the only list.

    The brackets exist to keep the format's own numbering out of the names a
    book owner may choose — `addr7` is theirs, `addr[7]` is ours. Letting
    `note[0]` or `line[2]` become an ordinary custom key gives that away
    again for the next list-valued key this format grows: the name would
    already be taken, in books written before it meant anything, which is
    exactly the position `addr5` left us in.

    Nothing loses a key to this. The parser has never accepted a bracket
    before now, so no ledger and no book holds one — the shape is refused the
    day it becomes writable, rather than reserved after the fact.
    """
    match = _ANY_INDEXED_RE.match(key or '')
    if match and not is_address_key(key):
        raise ValueError(
            f'{key!r}: an index in brackets names a line of a list, and the '
            f'address is the only list this format has. Write '
            f'{match.group(1) + match.group(2)!r} if it is a key of your own')


def named_address_lines(md: dict) -> dict:
    """`{line index: value}` for the address lines a block names.

    Only the lines it names. An absent key is not an instruction — README's
    rule for every key in this format — so what a block leaves out is left as
    it is, and a line is emptied by naming it empty.
    """
    lines = {}
    spelled = {}
    for key, value in md.items():
        index = address_line_index(key)
        if index is None:
            refuse_an_index_on_a_key_that_has_no_list(key)
            continue
        # One spelling per line, so `addr[07]` is refused rather than quietly
        # meaning `addr[7]`. Two keys for one line is the shape below, and a
        # padded index is that shape without even looking like it: the block
        # would name line eight twice and read as though it named two lines.
        if key not in LEGACY_ADDRESS_KEYS and key != address_key(index):
            raise ValueError(
                f'states an address line as {key!r} — an index carries no '
                f'leading zeros, so this line is {address_key(index)!r}')
        if index >= MOST_ADDRESS_LINES:
            raise ValueError(
                f'states an address line as {key!r}, which is line '
                f'{index + 1}. The index is the line\'s position, so this '
                f'asks for an address of {index + 1} lines — past anything '
                f'this reads as a typo rather than an address. Nothing caps '
                f'an address the book already holds; this is a file naming a '
                f'line that would be built out of {index} empty ones')
        if index in lines:
            first, second = sorted((spelled[index], key))
            raise ValueError(
                f'names one address line twice, as {first!r} and {second!r}: '
                f'both are line {index + 1} of the address. `addr1` counts '
                f'from one and `addr[0]` from zero, so they meet at every '
                f'line')
        lines[index] = '' if value is None else str(value)
        spelled[index] = key
    return lines


def address_lines_from(lines: list, named: dict) -> list:
    """`lines` with the lines `named` names replaced, and the rest untouched.

    The index is the line's position, not its order of appearance, so naming
    line five of a three-line address lengthens it and naming line three of a
    six-line address leaves the country on line five where the rest of the
    address expects it.
    """
    result = list(lines)
    if named:
        needed = max(named) + 1
        if len(result) < needed:
            result += [''] * (needed - len(result))
        for index, value in named.items():
            result[index] = value
    while result and not result[-1]:
        result.pop()
    return result


def address_lines_beyond(lines: list, carried: dict) -> list:
    """`lines`, with `carried`'s lines appended past the end of it.

    For a book holding an address in *both* places — the GnuCash option and
    the older custom slot, which is reachable by typing an address into File →
    Properties → Business on a book that already had one in the slot. The
    option is the address as far as it goes; the slot's surplus tail is lines
    the option never learnt, and is kept.

    Only past the end, never inside. A line the option does not have *within*
    its own length is a line that was cleared — by a block naming it empty, or
    in GnuCash — and a slot copy putting one of those back is the export
    disagreeing with the book it was taken from, which is the whole reason
    this is not a per-line fallback.

    Whole-address it was worse: the slot was read only when the book had no
    address at all, so lines three and four of a four-line slot vanished from
    every export the moment the option held a two-line address, and no import
    could recover them.
    """
    result = list(lines)
    for index in sorted(k for k in carried if k >= len(lines)):
        result += [''] * (index - len(result))
        result.append(carried[index])
    return result
