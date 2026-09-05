# Q-039 — linking a bank transaction whose other side is not on the receivable, in any currency

**Reported**: 2026-08-24, by a user with a USD invoice whose payment had been booked against a CAD "Due From Director" account while nobody yet knew what the money was.

Their book:

```
posting     Assets:Accounts Receivable   +1000.00 USD   (value +1400.00 CAD)
            Income:Sales                 -1400.00 CAD

money in    Assets:Bank USD              +1000.00 USD   (value +1399.00 CAD)
            Assets:Due From Director     -1399.00 CAD
```

The invoice is USD, the receivable is USD, the bank is USD. **The settlement does not convert**: 1000 USD arrived against 1000 USD owed. The 1399.00 CAD and the 1.399 under it are scaffolding — GnuCash had to balance the entry in the book's currency at a moment when the other side was `Assets:Due From Director`, which is CAD, and that account is not a party to the settlement. What the entry should become is

```
            Assets:Bank USD              +1000.00 USD
            Assets:Accounts Receivable   -1000.00 USD    (in the invoice's lot)
```

with no CAD in it and no rate anywhere.

## What the reporter's book did, measured

On GnuCash 5.10, through the CLI, in `tests/research/linking_a_bank_tx_whose_other_side_is_another_currency_probe.py`. An exchange rate appears once in that probe's *setup*, to mint the posting the reporter's book already has — a USD invoice booking to a CAD income account converts. Nothing about the link asks for one.

**Naming the split outright is refused.**

```
invoice "INV-USD-1000": txn_split_guid '…' on tx '…' does not live on an AR/AP account
```

That branch only attaches a split already sitting on the receivable to the lot. It never moves one, so it cannot reach this shape at all.

**Naming only the transaction is refused, for a reason that is not true.**

```
invoice "INV-USD-1000": tx '…' amount 1399.00 exceeds invoice remaining 1000.00; add `prepayment: 399.00` to the payment block to accept the residual as a pre-payment credit, …
```

This is the branch that does move the split. It measures `abs(counter_split.GetAmount())` — the parked split's 1399, in CAD — against the invoice's 1000 USD, and prints it through the receivable's formatting, so a CAD figure is quoted as though it were USD. There is no 399 of anything, and the remedy it offers would park a credit that does not exist.

**Where those two figures coincide, it is not refused — it corrupts the book.** The same setup with a USD 1399 invoice against the same CAD −1399 split imports cleanly and leaves:

```
Assets:Bank USD              amount  1000.00 USD   value  1399.00 CAD
Assets:Accounts Receivable   amount -1399.00 USD   value -1399.00 CAD   lot=True
```

The split changed account and kept its amount, so 1399 CAD is booked as 1399 USD. The invoice reads paid in full and nothing disagrees: the entry still balances at 0.00 in its CAD value. The move sets the account and nothing else — not the amount, not the value, not the transaction's currency.

## Why the figure on the split being applied is not the settlement

One thing, in three places: **the settlement is measured on the split that is about to be thrown away.**

The money that moved is the bank split. What the parked split says is an artefact of how the entry was balanced before anyone knew what it was, and once it is replaced that figure means nothing. Whether the settlement converts is a question about the *bank account's* currency against the record's — both USD here — and never about the denomination of the split being discarded.

## What must still be refused, and why

Rewriting which split is measured re-opens every guard that reads the old one.

| Case | | Reason it must give |
|---|---|---|
| Invoice USD, bank **CAD** | refuse | It genuinely converts, and only the payer knows the rate: the existing `settled_amount:` / `share_price:` refusal. Decided by the bank account's commodity, not the parked split's. |
| Bank moved **1200 USD**, invoice owes 1000 | refuse | A real overpayment — `prepayment: 200.00`, now quoting money that actually moved. |
| Bank moved **600 USD**, invoice owes 1000 | allow | An ordinary part payment. |
| Two or more non-bank splits, and the block gives no guid for any of them | refuse | Nothing can tell which settles the invoice, or whether several do. Ambiguity, pointing at the two ways to give a split's guid — which have to work for a parked split for that advice to be worth anything. |
| The transaction carries anything besides the bank split and the one being placed, **where the settlement is read off the bank** | refuse | What that split is worth is read from what the bank received, and that is the settlement only while those two are the whole entry. A third split makes the same numbers mean more than one thing, and which is a decision. Shipped with an exception this table did not foresee: a split in the record's own currency states its settlement outright, so nothing is inferred from the bank and a fee beside it is accepted. |
| The block's `account:` matches no split of the transaction | refuse, saying so | New. Today every split then reads as "not the bank" and it surfaces as ambiguity; once the bank split is the thing measured, failing to find it must say so rather than measure something else. |
| The transaction already settles another invoice | refuse to restate its currency | Restating would move that record's values too. |
| The split applied is in a lot, is another owner's credit, or settles another record | refuse | Unchanged. Moving it robs that record. |
| A restated amount is finer than the currency's unit | refuse | The same sub-unit rule as everywhere else. |

**A fee split is a refusal, and not the one first supposed.** The bank credits 100.00 and keeps a 5.00 fee against a 105.00 receivable. Giving the settling split's guid says which split is the settlement, but not what it is *worth* — and that is the question, because a parked split's own figure means nothing. The customer paid 105 and the fee is borne here, or they paid 100 and the fee is theirs; the book records neither, so the file has to state the amounts. This holds whatever currency the *fee* is in: a foreign one raises a rate question too, but the question before it is how much settles the invoice, and refusing on the rate would answer the second while the first is still open.

**What shipped bounds it by the currency of the split being placed**, which this paragraph did not foresee. The ambiguity is there only because the settlement is *inferred* from what the bank received; a split saying −105.00 on an account in the record's own currency has said which reading is meant, so a fee beside that one is accepted. Every fee fixture written for this issue parks in CAD, where the figure means nothing and the ambiguity is real, so the accepting path needed a fixture of its own.

The first attempt at this took the bank's figure less everything else in the entry, which is one of the two readings picked silently. That is the tool deciding something the book does not record, which it must not do.

## One payment may be more than one split

A hand-written entry can clear one receivable with five splits as readily as with one. That is *one* payment — money arrived once — whose transaction happens to have five splits in it, and it is a different fact from an invoice paid on five occasions.

The format does not tell those apart today, and the export gets it wrong. A `payment:` block is written per settling split (`services/invoice_renderer.py:928` loops the splits in the invoice's lot), so a single payment made of five splits exports as five `payment:` blocks and reads back as five payments. The block count is the payment count, and here it is five times the truth.

So the blocks group **by transaction**, not by split:

- settling splits from *different* transactions are different payments and keep a block each, as now;
- several splits of *one* transaction are one payment, and one block applies them all.

Each split applied carries its own amount, so the block needs the list of their guids and no per-split figure. One split per transaction — nearly every settlement there is — goes on being written `txn_guid:` + `txn_split_guid:` exactly as today, so no ledger anyone is holding changes.

**Splits are children of a transaction, and the advanced form says so.**

```
	payment:
		date: 2026-02-25
		amount: 1000
		account: "Assets:Bank USD"
		Transaction "c9f27c2b2f324117aa17c7c1f48fbafd"
			PaymentSplit "614b338df4f94c359aa35ffacc2dadcf"
			PaymentSplit "8d1c0a44b7e2411f9c33e5a7b6104fe2"
```

`Transaction "<guid>"` is the format's `keyword "identifier"` grammar, the shape `customer "C-USD"` and `invoice "INV-1"` already have, and its children are its splits — which is where a split lives everywhere else in this format. Directives here are capitalised, which tells them apart from the lower-case keywords a block already carries and from an account path opening a split line.

Nothing repeats a key, so none of this reaches key handling. `services/plaintext_parser.py:381` is `parent_directive.metadata[key] = value`, a plain dict assignment, so a key stated twice keeps the last and says nothing; that stands, and no key becomes multi-valued. The parse loop appends a child per recognised directive line and makes it current, so repetition is native to a directive and impossible for a key — which is the whole reason this is one.

Four key-shaped spellings were considered and rejected. Each makes the one-split case choose a spelling, which every export ever written has already made, and none of them can grow a child line if a settling split ever needs to say something about itself:

- `txn_split_guid:` stated twice — needs keys to collect, which would open the same door for `memo:` and `amount:`;
- `txn_split_guid[0]:` — brackets appear nowhere in this format;
- `txn_split_guid1:` — numbering is the shape Q-038 found wrong. It was copied onto the book's address, which is unbounded, and silently dropped everything past the fourth line; that address is one value with newlines in it now. A settlement's splits are unbounded the same way, and an export would have to invent an order to number them in;
- `txn_split_guids: [a, b, c]` — the first array in the format, for one key, needing a delimiter and escaping rules of its own beside the `"…"` / `\n` / `\"` scheme already there.

**The simple form stays.** `txn_guid:` and `txn_split_guid:` are what one settling split is written with, which is nearly every settlement and what every export so far emits.

**Where a block carries both, the `Transaction` directive decides** and the `txn_guid:` / `txn_split_guid:` keys beside it are not read. A strict override rather than a refusal: someone correcting an exported block adds the advanced form to it, and having to remember to delete two keys first is a step that earns nothing. It also gives a file carrying both one defined reading rather than an error a writer has to resolve by hand.

**And the run says so**, so precedence is never silent — the keys being read by nothing is exactly the state a reader cannot see in the book afterwards:

```
note: invoice "INV-USD-1000": `txn_guid:` and `txn_split_guid:` are not read where a `Transaction` block names the settlement — the block decides. Remove the two keys, or the block.
```

It matters most where the two disagree, `txn_guid:` naming one transaction and `Transaction "…"` another: the directive's is used, the key's is ignored, and without the note nothing in the book afterwards distinguishes that from a file that only ever named one.

## What moving and restating a split costs, measured

In `tests/research/restating_a_split_that_moves_between_currencies_probe.py`, against the engine directly, on GnuCash 5.10. The all-version sweep is what decides whether this holds everywhere; nothing is relied on until it does.

**`xaccTransSetCurrency` works on a committed transaction**, and the entry survives a save and a reload as restated. Moving the account, setting the moved split's amount and value, setting the bank split's value and setting the transaction's currency gives exactly the target:

```
Bank USD     amount  1000.00 USD   value  1000.00      currency USD
Receivable   amount -1000.00 USD   value -1000.00      balances
```

The same probe shows the defect on its own: **the move alone** leaves

```
Bank USD     amount  1000.00 USD   value  1399.00      currency CAD
Receivable   amount -1399.00 USD   value -1399.00      balances
```

— which balances, in CAD, while saying 1399 USD.

**A fee in another currency shows what requoting would cost**, and is why the refusal above is not narrowed to it. With a CAD fee left in the entry the transaction stays CAD-quoted, so the receivable split has to carry `amount -1000.00 USD, value -1420.00 CAD` for the entry to balance — an implied 1.42 that nobody wrote down. But a same-currency fee is refused too, and for the earlier reason: the rate is only a problem once you have decided how much settles the invoice, and that decision is the one this cannot make.

**Bounded, in what shipped, by the currency of the split being placed rather than of the fee.** Where that split is in the record's own currency it states the settlement, the decision is already made, and the fee beside it is no obstacle — see the paragraph on the design table above.

## How a payment block links a transaction now

The settlement is read off the **bank split** — the money that actually moved — wherever the split being placed is on an account in another currency than the receivable. The parked figure is read by nothing: not by the overpayment check, not by the move.

A split applied this way is moved to the receivable **and restated**: `relink_a_parked_split` sets its amount and value from what the bank received, sets the bank split's value to its own amount, and requotes the transaction in the settlement's currency. Both ways of writing the link reach it — the parked split's guid in `txn_split_guid:`, and `txn_guid:` alone where the transaction has one side that is not the bank.

`Transaction "<guid>"` with `PaymentSplit "<guid>"` children is read under a `payment:` block, and the export writes it: settlements are grouped by transaction now, so one payment made of several splits is one block. Written per split, as it was, a single payment read back as several.

`services/payment_links.py` holds all of it. `services/gnucash_importer.py` was eleven thousand lines before this and the payment path is a service's worth of reasoning on its own; the importer keeps the branching and calls out to it.

Refused, each before anything moves: an `account:` that matches no split of the transaction; anything in the entry besides the bank split and the one being placed **where the settlement is read off the bank**, since it is then more than one thing and the file has to say which — a split in the record's own currency states it outright, so a fee beside that one is accepted; a split already in a lot, unless it is one this record's own unpost abandoned or one already settling this very record; a `PaymentSplit` on an account a settlement cannot be moved off — this record's own receivable or payable, an account money passes through, and for a bill an account its own posting books, are the three kinds that can be, and the split on the account `account:` states is refused whichever kind that account is; several splits applied where **one or more** is parked in another currency — only a payment that applies a single split restates it from what the bank received, so one among several is enough; splits coming to more than the record still owes, since this spelling claims them all in one step and cannot place what is left over; an `amount:` that is not the sum of the splits the block applies, since the same file would otherwise settle by the splits' figures in the book that holds them and by the stated one in a book that does not; a guid in either directive that will not parse, asked with the key spellings' own guard and so ahead of any unpost; and `account:` and `txn_split_guid:` pointing at each other's sides — the arrival and the split being placed — which every other guard here is symmetric in and none of them can catch, the sign of the settlement being the one thing that is not.

A `prepayment:` sits beside a `Transaction` block like any other, weighed against the receivable splits the block does not apply — a residue is the payment's rather than any one split's. Refusing it there was the first answer and was wrong: a printed page has no transaction section, so that line is the only place it can say a residue exists, and a page of a two-split payment beside a loose 50.00 entered 100.00 for money that moved 150.00. Writing a block per split instead was wrong too, `payment_residue` being asked per block against the splits outside it: each skipped the other and counted the same 50.00, declaring 100.00 of residue for 50.00 of money.

## Link an existing expense transaction to a bill payment

A user could not link a transaction of two splits — one on an asset, liability or equity account, the other on an expense account — to a bill's payable. Three shapes, all ordinary for a small company, all refused:

| The other side | The transaction |
|---|---|
| asset | `DR Expenses:Supplies:USD / CR Assets:Due From Director USD` — a director paid the supplier from their own pocket |
| liability | `DR Expenses:Supplies:USD / CR Liabilities:Credit Card USD` — paid on the company card |
| equity | `DR Expenses:Supplies:USD / CR Equity:Owner Contributions USD` — the owner settled it and put it in as capital |

In each the supplier was paid before the bill was posted, so the only entry available at the time put the cost straight on an expense account. Posting the bill books that same cost again as `DR Expenses / CR A/P`, so the expense split is a second copy of the bill's own line. Moving it to the payable settles the bill and leaves the cost booked once.

Two guards stood in the way, and a third followed from fixing them.

**The account-type refusal.** Income, expense and equity were refused outright, and the message ended by asking for the guid of the split that received the money — which is no split here, none having received any. That refusal exists for a cash sale, where `txn_guid:` alone makes the run pick the income split by elimination and turn revenue into a settlement. What separates the two is whether the bill's own posting books the same account: it does for these three, so the split is a duplicate of a line the book already has. That is asked of the posting transaction rather than of the entry lines, because the posting is what the book holds — entry accounts, the payable, and any tax lines.

**Bills only, and the account match is a condition rather than proof.** A cost is a cost whichever entry carries it, so removing a duplicate loses nothing. Revenue is not: an invoice posting to the same income account as a cash sale would, on identical reasoning, take the sale off the profit and loss — the failure this issue was reported for. Measured before the check was scoped to bills: such an invoice imported at exit 0 and moved the revenue onto the receivable. And even for a bill, matching the account cannot tell this bill's own line from an unrelated purchase on the same account; a guid is the file asserting which split settles the record, as it is for every other account type.

Both surviving refusal fixtures are near misses on purpose and say so: the invoice posts to `Income:Sales` while the cash sale sits on `Income:Sales USD`, and the bill posts to `Expenses:Supplies` while the purchase sits on `Expenses:Supplies:USD`.

**A bill carrying GST works.** The natural entry records the payment as one gross expense, because when it is paid nothing yet says how much of it was tax — `DR Expenses:Supplies 113 / CR Credit Card −113`. That is two splits, the shape this branch handles: the gross split moves to the payable at 113.00, and the bill's own posting books 100.00 of cost and 13.00 of GST, leaving the expense account at the net figure. Measured, and it is the ordinary Canadian case, so it has a test of its own. Separating the tax at payment time is a choice rather than a requirement; somebody not claiming the credit has nothing to separate then.

**An account the bill posts to may not be left out of the payment whole**, and that refusal had to be added. Measured on `DR Expenses 100 / DR GST 13 / CR Card −113` before it existed: applying the 100.00 cost split moved it to the payable, the GST stood at 26.00 for one 13.00 charge, the bill read 13.00 still owing, and every figure balanced, at exit 0.

Each account the posting books is asked one question: does the payment apply anything on it? The tax account answers no, so the payment is refused.

Two shapes answer yes and are allowed. One transaction paying two suppliers, 100.00 and 200.00 on the same expense account, where each bill applies its own split. And a part payment — 60.00 paid toward a bill owing 100.00, beside another supplier's 200.00 on that account — where the remaining 40.00 is simply unpaid.

Asking instead whether what was applied *came to* what the posting booked refused that part payment, with a message saying the rest would be recorded twice, which is untrue. It also made the answer turn on the other supplier: the same 60.00 was accepted where nothing else shared the account, because then no split was left over to compare against.

Accounts are all this compares, so it can go no further. Another supplier's split and an unpaid remainder of this bill's cost look exactly the same, and where the payment has applied something on the account the file has said which split there is this bill's.

This check leaves out splits on the record's own receivable or payable. Every posting books that account, and several splits on it are one wire settling more than one record — settlements rather than duplicates. Counting them refused a payment applying its share of a four-split wire.

**And this allowance is closed to income and to equity, on both sides.** The rationale is that a cost is a cost whichever entry carries it, which says nothing about revenue and nothing about capital. `Entry.SetBillAccount` places no restriction on the account, so a bill's line may be booked to either — a vendor rebate is booked to income — and "it is a bill" therefore does not imply "it is a cost". Measured on a bill whose line is booked to `Equity:Owner Contributions USD`, before equity was closed: the capital moved onto the payable at exit 0, off the balance sheet, with every figure still balancing.

Equity remains a payment *account*, which is one of the three shapes this branch supports. That is the side `account:` states, and it is never the side that moves.

**A units split is refused whatever the posting books**, so its message does not offer the posting as a way out. The combination is unreachable in any case — a bill cannot post to a securities account without a rate for the security, which the posting check demands first — so there is no fixture for it, only this note.

**The payment account.** A bill payment accepted an asset or owner's equity only, so the credit-card case was refused before the split was even looked at. A liability is allowed for a bill now: paying a supplier on the card settles the bill and leaves the company owing the card issuer instead, and the money never passes through an asset. An invoice settled into a liability is a different thing and stays refused.

**And the split already on the payable.** Whether a split still has to be moved asks the same question as the refusal, so that the two cannot disagree. Widening one widened the other, and because a posting books its own payable, every split already settling a record read as one still needing to be moved — measured, three tests failed on it. The record's own receivable and payable are turned away before the posting is consulted.

**A posting transaction is not a payment of anything.** Posting a bill writes `DR Expenses / CR A/P`. That transaction has a split on the expense account, and the bill's own posting books that account, so it satisfies the test this branch added. Its payable split is already in the bill's lot, so the split left for `txn_guid:` to find is the expense one. Every other check passes it: the sign is right, the amount is what the bill owes, and nothing is left out, there being nothing else on that account.

Measured on a USD bill posting 100.00 to a USD expense account, before the check existed: the import ran at exit 0, the expense account went from 100.00 to nil, the payable rose by 100.00, the bill read as paid, no money moved anywhere, and every figure balanced. It is an ordinary thing to write by mistake, the export printing that guid as `posted_txn_guid:` a few lines above the `payment:` block that takes `txn_guid:`.

**Any record's posting, not only the one being paid.** Where a second bill posts to the same expense account, the first bill's posting passes the same tests for it — the payable split sits in the first bill's lot and is skipped, leaving the expense split, whose sign and amount suit the second bill exactly. Measured the same way: exit 0, the first bill's cost moved onto the second bill's payable, no money moved. The first version of this check asked only about the record being paid and closed one of the two.

The refusal is for the transaction rather than for the split, because no split of a posting pays the record it posts: the payable split is the debt and the expense split is the cost. That answers every spelling in one place — `txn_guid:` alone, `txn_split_guid:` beside it, and a `Transaction` block with `PaymentSplit` lines all resolve the same transaction, and the check runs where they resolve it. GnuCash answers whose posting it is: `gncInvoiceGetInvoiceFromTxn` reads the slot posting writes, and returns nothing for an ordinary bank payment.

**A refusal may not tell a posted bill it has posted to nothing.** The message offering the posting as a way out lists the accounts a split could be moved off, which leaves out the payable and any income account. A bill whose only entry is a rebate posts to those two and to nothing else, so the list is empty. Printed anyway it read "This one posts to nothing yet", which describes a bill that has not been posted; that bill had been. Where the list is empty the advice is dropped, and the message asks for the guid of the split that received the money.

## Rename "retarget" to "link" everywhere a reader sees it

The code calls this "retarget" — in `_retarget_counter_split_to_lot`, `_retarget_choices`, `_refuse_an_ambiguous_retarget`, in the refusal quoted above, in `find-orphan-payments` and `unpost` output, and 34 times across README and docs. It is **linking a bank transaction to an invoice's payment**, and that is what it should be called wherever a reader can see it.

## Undoing it: `unlink`

A link had no way back. `unapply-payment` was the nearest thing and it set the account and nothing else, which is this issue's own defect running backwards: a 100.00 USD settlement given a CAD account kept the figure 100.00 and became 100 Canadian dollars, with nothing disagreeing because the split's *value* was never touched.

`unlink` is the undo, and `unapply-payment` restates through the same function, so the two cannot differ. The split comes off the receivable, leaves the record's lot, and takes the account `--to` gives — restated for that account, since a split carries an amount in the commodity of the account it is on and a value in the currency the transaction is quoted in. The transaction itself survives whole.

Neither command can refuse the other's case, because the book does not record which it holds: measured on 5.10, a bank entry reads as no transaction type at all until a `payment:` block gives its guid and `'P'` afterwards, which is exactly what the engine stamps on a payment it creates. `tests/research/what_tells_a_linked_payment_from_an_applied_one_probe.py` is the measurement.

What both refuse: an account in a third foreign currency, whatever rates are passed — the converted amount would be currency in the book with no cost basis behind it — and an account kept too coarse to state the figure, which would round it in silence.

And what a settlement drew out of a cost basis comes back when it is taken off. A converting settlement lowers the receivable's cost basis balance by the units it converted; leaving that spent made the record unsettleable, since re-applying the money hit "that USD has already been sold against it" about currency the book had just gone back to being owed.

**The `Income:FX Gain` split is not deleted, and cannot be.** A settlement that converts at a rate other than the `share_price:` of the split that opened the cost basis realizes a difference, and the payment block is required to say where it belongs — the import refuses the block otherwise, naming `Income:FX Gain $residual$ CAD`. That split is the file's own, in the transaction the file wrote, and surviving the undo whole is what these commands promise. Measured on `fx_invoice_usd_paid_from_cad_bank.txt`: after the give-back the cost basis reads 100.00 USD undisposed while the income statement carries −3.00 CAD realized on disposing of it. Both describe what happened, and nothing here can decide whose line to rewrite. Applying the money to another record with another `$residual$` line records the difference twice; the first line is the reader's to remove. `test_a_settlements_cost_basis_comes_back.py` pins the measurement.
