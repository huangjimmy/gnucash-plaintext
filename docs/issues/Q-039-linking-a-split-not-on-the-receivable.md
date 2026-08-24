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

## What was measured

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

## What is wrong

One thing, in three places: **the settlement is measured on the split that is about to be thrown away.**

The money that moved is the bank split. What the parked split says is an artefact of how the entry was balanced before anyone knew what it was, and once it is replaced that figure means nothing. Whether the settlement converts is a question about the *bank account's* currency against the record's — both USD here — and never about the denomination of the split being discarded.

## What must still be refused, and why

Rewriting which split is measured re-opens every guard that reads the old one.

| Case | | Reason it must give |
|---|---|---|
| Invoice USD, bank **CAD** | refuse | It genuinely converts, and only the payer knows the rate: the existing `settled_amount:` / `share_price:` refusal. Decided by the bank account's commodity, not the parked split's. |
| Bank moved **1200 USD**, invoice owes 1000 | refuse | A real overpayment — `prepayment: 200.00`, now quoting money that actually moved. |
| Bank moved **600 USD**, invoice owes 1000 | allow | An ordinary part payment. |
| Two or more non-bank splits, none named | refuse | Nothing can tell which settles the invoice, or whether several do. Ambiguity, pointing at the ways to name them — which have to work for a parked split for that advice to be worth anything. |
| The transaction carries anything besides the bank split and the one being placed, **where the settlement is read off the bank** | refuse | What that split is worth is read from what the bank received, and that is the settlement only while those two are the whole entry. A third split makes the same numbers mean more than one thing, and which is a decision. Shipped with an exception this table did not foresee: a split in the record's own currency states its settlement outright, so nothing is inferred from the bank and a fee beside it is accepted. |
| The block's `account:` names no split of the transaction | refuse **by name** | New. Today every split then reads as "not the bank" and it surfaces as ambiguity; once the bank split is the thing measured, failing to find it must say so rather than measure something else. |
| The transaction already settles another invoice | refuse to restate its currency | Restating would move that record's values too. |
| A named split is in a lot, is another owner's credit, or settles another record | refuse | Unchanged. Moving it robs that record. |
| A restated amount is finer than the currency's unit | refuse | The same sub-unit rule as everywhere else. |

**A fee split is a refusal, and not the one first supposed.** The bank credits 100.00 and keeps a 5.00 fee against a 105.00 receivable. Naming the settling split says which split is the settlement, but not what it is *worth* — and that is the question, because a parked split's own figure means nothing. The customer paid 105 and the fee is borne here, or they paid 100 and the fee is theirs; the book records neither, so the file has to state the amounts. This holds whatever currency the *fee* is in: a foreign one raises a rate question too, but the question before it is how much settles the invoice, and refusing on the rate would answer the second while the first is still open.

**What shipped bounds it by the currency of the split being placed**, which this paragraph did not foresee. The ambiguity is there only because the settlement is *inferred* from what the bank received; a split saying −105.00 on an account in the record's own currency has said which reading is meant, so a fee beside that one is accepted. Every fee fixture written for this issue parks in CAD, where the figure means nothing and the ambiguity is real, so the accepting path needed a fixture of its own.

The first attempt at this took the bank's figure less everything else in the entry, which is one of the two readings picked silently. That is the tool deciding something the book does not record, which it must not do.

## One payment may be more than one split

A hand-written entry can clear one receivable with five splits as readily as with one. That is *one* payment — money arrived once — whose transaction happens to have five splits in it, and it is a different fact from an invoice paid on five occasions.

The format does not tell those apart today, and the export gets it wrong. A `payment:` block is written per settling split (`services/invoice_renderer.py:928` loops the splits in the invoice's lot), so a single payment made of five splits exports as five `payment:` blocks and reads back as five payments. The block count is the payment count, and here it is five times the truth.

So the blocks group **by transaction**, not by split:

- settling splits from *different* transactions are different payments and keep a block each, as now;
- several splits of *one* transaction are one payment, and one block names them all.

Each named split carries its own amount, so the block needs the list of them and no per-split figure. One split per transaction — nearly every settlement there is — goes on being written `txn_guid:` + `txn_split_guid:` exactly as today, so no ledger anyone is holding changes.

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

## What restating takes, measured

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

## What it does now

The settlement is read off the **bank split** — the money that actually moved — wherever the split being placed is on an account in another currency than the receivable. The parked figure is read by nothing: not by the overpayment check, not by the move.

A split named this way is moved to the receivable **and restated**: `relink_a_parked_split` sets its amount and value from what the bank received, sets the bank split's value to its own amount, and requotes the transaction in the settlement's currency. Both ways of writing the link reach it — `txn_split_guid:` naming the parked split, and `txn_guid:` alone where the transaction has one side that is not the bank.

`Transaction "<guid>"` with `PaymentSplit "<guid>"` children is read under a `payment:` block, and the export writes it: settlements are grouped by transaction now, so one payment made of several splits is one block. Written per split, as it was, a single payment read back as several.

`services/payment_links.py` holds all of it. `services/gnucash_importer.py` was eleven thousand lines before this and the payment path is a service's worth of reasoning on its own; the importer keeps the branching and calls out to it.

Refused, each before anything moves: an `account:` naming no split of the transaction; anything in the entry besides the bank split and the one being placed **where the settlement is read off the bank**, since it is then more than one thing and the file has to say which — a split in the record's own currency states it outright, so a fee beside that one is accepted; a named split already in a lot, unless it is one this record's own unpost abandoned or one already settling this very record; a `PaymentSplit` on any account but the record's receivable; several named splits where **one or more** is parked in another currency — only a payment naming a single split restates it from what the bank received, so one among several is enough; named splits coming to more than the record still owes, since this spelling claims them all in one step and cannot place what is left over; an `amount:` that is not the sum of the splits the block names, since the same file would otherwise settle by the splits' figures in the book that holds them and by the stated one in a book that does not; a guid in either directive that will not parse, asked with the key spellings' own guard and so ahead of any unpost; and `account:` and `txn_split_guid:` naming each other's sides — the arrival and the split being placed — which every other guard here is symmetric in and none of them can catch, the sign of the settlement being the one thing that is not.

A `prepayment:` sits beside a `Transaction` block like any other, weighed against the receivable splits the block does not name — a residue is the payment's rather than any one split's. Refusing it there was the first answer and was wrong: a printed page has no transaction section, so that line is the only place it can say a residue exists, and a page of a two-split payment beside a loose 50.00 entered 100.00 for money that moved 150.00. Writing a block per split instead was wrong too, `payment_residue` being asked per block against the splits outside it: each skipped the other and counted the same 50.00, declaring 100.00 of residue for 50.00 of money.

## Naming

The code calls this "retarget" — in `_retarget_counter_split_to_lot`, `_retarget_choices`, `_refuse_an_ambiguous_retarget`, in the refusal quoted above, in `find-orphan-payments` and `unpost` output, and 34 times across README and docs. It is **linking a bank transaction to an invoice's payment**, and that is what it should be called wherever a reader can see it.
