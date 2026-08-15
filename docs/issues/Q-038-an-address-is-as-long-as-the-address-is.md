# Q-038 — an address is as long as the address is

**Reported**: 2026-08-15, by a reader asking why the `company` block splits an
address into `addr1`..`addr4` when GnuCash "stores addr1 to 4 separately".

The question was about the split. The answer turned out to be that the two
addresses in this format are different objects, and that treating them alike
was losing data in three ways.

## What was measured

On GnuCash 5.10, against books this tool wrote.

**A.** A `Company Address` of six lines, as File → Properties → Business takes
it:

```
the book holds 6 lines:
    '42 Example Street'  'Unit 5'  'Springfield ON'
    'A1A 1A1'  'CANADA'  'Attn: Accounts Payable'
what the export says:
    addr1 addr2 addr3 addr4          ← 'CANADA' and 'Attn:' are gone
```

Silently, and the export is the whole ledger: a book rebuilt from it has a
four-line address.

**B.** A ledger saying `addr5:` — the obvious way to write a fifth line:

```
Company Address holds 4 lines
book custom metadata: {'addr5': 'CANADA', 'addr6': 'Attn: Accounts Payable'}
```

It round-trips through the export perfectly and never reaches the address, so
a test asserting the ledger's own round trip passes while the printed invoice
shows four lines. The file says one thing and the document shows another.

**C.** A block naming one line:

```
company
	addr1: "9 New Road"
→ Company Address now holds 1 line: '9 New Road'
```

The other three are deleted. The block rewrote the whole slot from the keys it
named, which is the opposite of the rule the rest of the format follows and
that the *customer* address path has always followed (`if key in md`).

**D.** `addr5:` on a `customer` block was accepted and filed as that
customer's custom metadata — same shape as B, on an object that genuinely
cannot hold a fifth line.

## Why they differ

| whose address | GnuCash storage | length |
|---|---|---|
| the book's | one `Business` → `Company Address` option, newlines in the string | unbounded |
| a customer's / vendor's | a `GncAddress`: `SetAddr1`..`SetAddr4` | four, exactly |

The four-line cap was correct for the owner blocks and had been copied to the
book's, where nothing justifies it.

## What was decided

Lines are indexed, from zero, in brackets: `addr[0]`, `addr[1]`, … on every
block that has an address.

**Why brackets and not `addr5`, `addr6`.** Continuing the numbering would
reserve `addr` + any number for the format, and a block's custom keys are the
book owner's to name — `abc1` and `abc2` are two unrelated keys, and `addr7`
would have become an address line here and an ordinary key there. Bracketed,
the list is a syntax rather than a convention: `addr[7]` is the eighth line,
`addr7` is a key like any other, and neither can be mistaken for the other.
The parser's key grammar takes an optional trailing `[<digits>]`; only digits,
and only at the end, so a stray bracket stays an error rather than becoming a
key.

**Why `addr1`..`addr4` are still read.** Every export this tool wrote until
now used them, and an address is not a thing to drop over a spelling. They
mean what they always did — `addr1` is the first line, which is `addr[0]` —
nothing writes them any more, and a block spelling one line both ways is
refused rather than resolved, since the two differ by one and a reader who
mixed them did not mean the same line twice.

**Why a fifth line on an owner is refused.** There is nowhere in the book to
put it. Accepting it filed it where nothing prints it, which is D above: the
ledger and the document disagreeing with no word said.

## Where it lives

- `services/plaintext_addresses.py` — which line a key names, in either
  spelling; the four-line limit; and the positional merge that leaves unnamed
  lines alone.
- `services/gnucash_importer.py` — the `company` slot is rebuilt from its
  current lines plus the ones the block names; the owner path refuses index 4
  and above.
- `use_cases/export_business_objects.py` — every line the slot holds, and the
  legacy-blob fallback only where the book has no address at all.
- `tests/integration/test_a_company_address_of_any_length.py` — A, B, C, D and
  the spelling rules.
