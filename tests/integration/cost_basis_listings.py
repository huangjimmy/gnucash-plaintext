"""Reading an `fx-balances` listing in a test.

The listing states two things. First every foreign-currency cost basis — one
row per split, with what it cost and what is left against it. Then, beneath
them, what the book's accounts actually hold of each of those currencies.

Both name accounts, and they answer different questions. "This split
established no cost basis" is about the first, and asserting it against the
whole output cannot fail: an account that correctly has no cost basis is still
listed in the second, because the book holds currency in it. So a test that
means the cost bases reads the cost bases.
"""


def cost_basis_rows(listing: str) -> str:
    """The listing down to the account-balances block, which is left out.

    The block opens with its own `ACCOUNT ... BALANCE` header. The cost-basis
    header cannot be mistaken for it: that one opens with `DATE`, and it is the
    start of the line that tells them apart rather than the `BALANCE` both end
    with.

    A listing with no such block — a book holding no foreign currency in any
    account — comes back whole, so this is safe to wrap any listing in.
    """
    lines = listing.splitlines()
    for index, line in enumerate(lines):
        if line.startswith('ACCOUNT ') and line.rstrip().endswith('BALANCE'):
            return '\n'.join(lines[:index]).rstrip() + '\n'
    return listing
