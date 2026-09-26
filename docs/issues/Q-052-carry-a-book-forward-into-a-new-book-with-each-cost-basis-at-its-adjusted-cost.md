# Q-052 — Carry a book forward into a new book, with each cost basis at its adjusted cost

## What it should do

**Carry a book forward into a new book.** The old book ends on a date. The new book begins on the day after it, holding the old book's balances as its opening balances, and nothing from before.

**Carry each cost basis forward.** Every cost basis the old book still holds a balance of moves to the new book. There it is opened from the opening balance, at its adjusted cost base: what is left of it, at what it cost. A disposal in the new book then draws on it and realizes the same gain it would have realized in the old book.

**Not "closing the book".** GnuCash's own Close Book (Actions → Close Book) writes closing entries inside the same book: it moves the period's income and expenses into equity, and every transaction stays. `close-books` (Q-032) does the same thing. Carrying a book forward comes after that close. The old book is left as it is, and the new book starts from its balances.

Recorded, not built. It is not part of the Q-051 branch.

## What was reported

The user, on a timing probe of a book of 5,000 transactions: "5000 transactions, if for SME that can be 10 years or 20 years of book. Then we face a problem, we need to support really closing book and create new book from last close. Then we need to allow moving cost basis to new book and new book need to create new cost basis from opening balance with adjusted cost base."

And on the name: "Gnucash has a close book feature, so our close book should use another name!"

## Why it matters

A small business can take 10 or 20 years to reach 5,000 transactions, and today a book only grows.

- Closing a book, in GnuCash or with `close-books`, leaves every transaction in it.
- Every run reads the whole book, and a statement line is booked by exporting the whole book and importing it again with `--strategy update`. An unchanged update of 5,000 transactions takes 2 to 4 s on every supported build, once no step walks the book per transaction and a transaction with no new changes is left alone (the section "How long an update takes as the book grows" of `docs/issues/Q-051-let-a-statement-line-on-a-holding-account-be-edited-into-the-invoice-or-bill-it-settles.md`).
- Importing into a new book still grows faster than the book: 0.7, 2.1 and 7.1 s for 500, 1,000 and 2,000 transactions, and 36.8 s for 5,000, on GnuCash 5.10. Each commit is GnuCash's own, and GnuCash pays it in proportion to the size of the accounts. That is the cost of rebuilding a book from its export, which is how the README says to bring an older book forward ("Bring it forward through its export").

A book that is carried forward stays the size of the years it covers.

## What is already known

- An opening balance against an equity account, valued at what the currency cost, already opens a cost basis. Q-051 relies on it for a book started part-way through its life (`TestATransferBesideItsFee` in `tests/integration/test_a_statement_line_on_a_holding_account_is_edited_into_what_it_settles.py`). A split has one amount and one value, so one opening split holding currency from two cost bases at two costs would open one cost basis at their average. Carrying each cost basis whole needs one opening split per cost basis.
- A cost basis is kept on the split that brought the currency in, with its balance, what it brought in and its cost as KVPs (`cost_basis_balance`, `cost_basis_brought_in`, `cost_basis_cost`). None of those splits is in the new book, so every disposal there must state a cost basis the new book's opening splits establish.

## Known, not yet investigated

- What the new book carries besides balances: open invoices and bills and their lots, an owner's credit, prices.
- How a disposal in the new book states the cost basis it draws on, where the cost basis started life in the old book.
- Whether the old book stays readable beside the new one for the reports that span both, such as a realized gain over a year that crosses the date the book was carried forward.
- What the command is called. It must not be "close", which GnuCash's Close Book and `close-books` already use.
