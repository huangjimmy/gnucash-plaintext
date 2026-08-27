# Release Notes

## Unreleased

### Link an existing expense transaction to a bill payment

**A supplier paid before the bill was posted can now be linked to it.** The only entry available at the time puts the cost on an expense account — a director paying out of pocket, a purchase on the company card, the owner settling it as capital:

```
2026-02-10 * "Director paid the supplier"
	Expenses:Supplies:USD 100.00 USD
	Assets:Due From Director USD -100.00 USD
```

Posting the bill books that same cost again as `DR Expenses / CR A/P`, so the expense split is a second copy of the bill's own line. A `payment:` block applies it, and it becomes a split on the payable:

```
	payment:
		date: 2026-02-10
		amount: 100
		account: "Assets:Due From Director USD"
		txn_guid: "aa11bb22cc33dd44ee55ff6677889900"
		txn_split_guid: "bb22cc33dd44ee55ff6677889900aa11"
```

The bill is settled and the cost is recorded once, by the bill's own posting. The split must sit on an expense account this bill posts to; one it does not post to is somebody else's cost. The account may be in another currency than the bill. Income and equity are refused on both sides — a bill's line can be booked to either, and a cost is a cost in a way that revenue and capital are not.

**A bill may be paid from a liability account.** Paying a supplier on the company card settles the bill and leaves the company owing the card issuer; the money never passes through an asset. An asset and owner's equity still work as before. An invoice settled into a liability stays refused.

**A payment may apply more than one split of its transaction**, written as a `Transaction` block with a `PaymentSplit` line for each. A bill whose payment recorded the tax separately applies both; an invoice does the same where an arrival was recorded as two suspense splits.

**A posting transaction is refused as a payment.** Posting a bill records what is owed, so its splits are the debt and the cost and neither one pays anything — and that holds for any bill's posting, not only the one being paid. The export prints that guid as `posted_txn_guid:` a few lines above the `payment:` block that takes `txn_guid:`, so it is an ordinary thing to write by mistake.

**A payment block states where the money came from.** Every writer of one — `export`, `print-invoice`, `print-bill` — took the first split that was not on the receivable, which is the money only while the transaction carries nothing else. A bill part paid out of a transaction that also holds another supplier's cost kept that cost on the expense account, and the export wrote it as the payment account; re-imported, a bill payment does not take an expense account, so the book could not read its own export back.

### Undo an invoice's payment by unlinking the transaction that paid it: `unlink`

**An invoice paid without entering any money can be unpaid.** The bank feed arrived first, or a director paid a supplier out of pocket, so the transaction was already in the book and a `payment:` block naming it made one of its splits the settlement; there was no way back. `unlink` undoes that, and what it leaves is a payment with nothing to do with the invoice any more: the split comes off the receivable, leaves the record's lot, and takes the account `--to` gives, while the invoice owes again. The transaction itself survives whole — nothing is deleted, and the only thing that changes is the one split the link wrote on.

```bash
gnucash-plaintext unlink ledger.gnucash INV-2026-001 --to "Assets:Due From Director"
```

**And the figure is restated for the account it lands on.** This is a fix as much as a feature: `unapply-payment` set the account and nothing else, so a 100.00 USD settlement given a CAD account kept the figure 100.00 and became 100 Canadian dollars. Nothing disagreed, because the split's value — the transaction's own side — was never touched.

A split carries two figures — an amount, in the commodity of the account the split is on, and a value, in the currency the transaction is quoted in — so an account may be kept in one of two currencies and no others: the commodity the split already holds, or the book's own. Two need no rate at all: one kept in the commodity the split already holds takes the amount, and one kept in CAD, where the transaction is quoted in CAD, takes the value. The currency the transaction is quoted in is not a third option — it is one of those two or it is refused like any other. A CAD account where the transaction is quoted elsewhere genuinely converts and takes `--fx-rates`, read at the transaction's own date and rounded to the unit that account is kept to. Without a rates file that case is refused rather than guessed at.

**A third foreign currency is refused, rates file or no rates file.** The arithmetic is fine; what it would leave behind is not. A split that brings foreign currency into the book carries a `share_price:` and a `value:` in the currency the transaction is quoted in, and a cost basis is opened from the two — and restating a settlement states neither figure. Measured before this was refused: `--to` a yen account wrote −14946 JPY and `fx-balances` then listed the USD receivable and no JPY at all. Buying yen is a transaction of its own.

**Either command takes either kind of payment.** `unapply-payment` is the same operation under the name for a payment this tool created, and neither refuses the other's case, because nothing in the book says which one you have: a bank entry reads as no transaction type at all until a `payment:` block names it and `P` afterwards, which is exactly what GnuCash stamps on a payment its own machinery creates. Pick the name that describes what you did.

`unapply-payment` restates through the same function and takes the same `--fx-rates`, so the two commands cannot disagree. They answer a refused run out of one place too, in each command's own words: an id two records share sends you to `--by-guid` under either name, and a record with several payments lists their guids and asks for one.

### Refusal wording

**A guid is given, a split is applied, and a guid the book has nothing for matches nothing.** Saying a payment "names" a split told a reader nothing — every split has a name — and a payment does not choose or select one either. Every refusal that used the word has been reworded, including `posted_txn_guid '…' names no transaction in this book`, which now reads `matches no transaction in this book`.

## v0.4.0 - Identity for a line, a split and a credit, every column an invoice or bill line has, printing through GnuCash's own report (2026-08-21)

### A line, a split, a credit and a payment's memo each keep their own identity

**An invoice or bill line carries `guid:`, and it says which line a block edits.** Every other block in this format has had one — a customer, an invoice, a transaction, a split — and a line had none, so editing an invoice destroyed every line it had and built new ones. Correcting one word of one description therefore handed *both* lines guids GnuCash had just minted, and two consecutive exports of the same ledger disagreed about which line was which:

```
	entry:
		guid: "3f7a1c9e5b2d4a08b6c1e0d3a9f45721"
		date: 2026-01-01
		description: "Design"
		…
```

An edit now rewrites the lines the file's blocks give and leaves the rest of the invoice alone. A line no block gives is removed; a block giving no line is added.

**A hand-written file gives no guid, and that goes on working**: a block without one edits the line in the same position, so the second `entry:` block edits the second line. A file that mixes the two is read guid-first, the unnamed blocks taking whichever lines are left over in order — which is what a file edited by hand out of an export looks like when a guid is deleted along with the line it was on.

**Two files are refused rather than guessed at.** The same guid on two lines of one invoice: a guid is one line, so the second block would fall through to position and edit some other line, and the invoice would come out of the import stating something the file did not say. And a guid the book gave something else — another invoice's line, an account, a transaction: forcing it leaves two objects with one guid, and GnuCash finds an object by looking its guid up in a hash, so the loser is unreachable. The check that answers "is this guid free" now asks the collections a line, a split and an invoice live in; before, it asked about accounts, transactions, customers, vendors and tax tables only, and answered "free" about all three of those.

**A split block is matched by its `guid:` too.** Position decided it before, whatever the block said, so a transaction whose two `Expenses:Dining` blocks were rewritten the other way round moved the amounts between the two splits and reported `Updated: 1` — the book then contradicting the file just imported into it. Two splits of the same amount are the case that moved in silence: 15.00 for coffee and 15.00 for cake swap their *memos* and nothing else, so no total changes, no balance changes, and no figure looks wrong. Two blocks naming one split are refused, as two blocks naming one line are: the second would fall through to position and update a split the file never mentioned. So is a block naming a guid the book holds on something that is not a split of that transaction. And **a split keeps its guid when its account changes**: the blocks are paired within one account, so a block whose account line was changed used to find an empty group, build a new split with a guid GnuCash minted, and leave the split it named to be destroyed as an orphan of the account it had been in — the identity lost on the commonest edit anyone makes to an exported ledger. The split is moved to the account its block gives it, and pairs there. Not one sitting in a lot, which is settling an invoice or standing as an owner's credit: moving it, or dropping it because no block names it, takes a settlement out of its invoice's lot while the account's balance stays put — nothing looking wrong, and the invoice reading unpaid. Both are refused, naming the lot. **And a guid nothing can parse is refused** rather than read as a block naming no split at all: read that way it fell straight back to position, the pairing the guid is written to end, and a block creating a split lost the guid as quietly — the split came back under one GnuCash minted, and the next export contradicted the file that made it.

**A guid written without quotes works, all-digit ones included.** `guid: b2b3…b4` has always been read as written; `guid: 22222222222222222222222222222222` was refused, because the parser decodes an unquoted number as a number and a number keeps none of what makes a guid — `00000000000000000000000000000022` and `22` are both 22, the leading zeros and the digit count gone before any reader saw them. A value decoded that way now carries the characters it was written with, so all-digit hex names its object like any other guid. That is one rule fewer to know for a hand-written ledger, and it retires an error message that could not be written honestly: with the digits gone, every guid the message could suggest quoting was one nobody had written — padded to 32 characters in whichever base the message chose. What remains refused is a value that is no guid at all, `guid: 22`, and the message names those two characters rather than proposing a third thing.

**And the comparison that decides `unchanged` pairs the lines the same way the rebuild does**, which it has to. Compared by position while the rebuild paired by guid, a file whose `entry:` blocks were reordered read as a change to every line — refused outright on a posted invoice or bill, with a remedy that does not help, since the rebuild edits each line where it already is, the invoice's own order never changes, and the next import of the same file is refused again. The mirror is the silent one: two lines that trade only their `guid:` values match in every position, so the run reported `unchanged` over a book asserting the opposite of what the file said about which line is which.

**Changing a posted invoice or bill is refused**, and the message names the way through — `unpost-invoices <book> INV-2026-001`, then import. A posted invoice is one the book has already booked: rebuilding it from a file unposts it, destroys and rebuilds its lines, posts it again under a **new** transaction, and leaves its payments settling a transaction that no longer exists. Which edits an invoice takes now depends on whether it is posted, and the two states take opposite ones: **a posted invoice or bill takes a `payment:` block and nothing else, and an unposted one takes everything else and no payment.** So a changed line is refused; so is a changed `posted:` block — its date, its due date, its memo, its A/R or A/P account; and so is a changed invoice field, a `notes:` line, a billing id, a custom key. Each of those meant unposting and posting again on the strength of one edited word, reported as `updated`, and a line of prose that has nothing to do with the posting is no reason to destroy the transaction the book was booked through.

**And the two-step route keeps more than the rebuild it replaces.** Unposting destroys the posting transaction, so an invoice rebuilt in one step came back under a guid GnuCash had just minted — measured, bdfc62ec… became fb35b412… — and anything pointing at the old one, a reconciliation, a statement line, another ledger, pointed at nothing, with no figure disagreeing. Unposted out loud and then imported, the invoice goes back on the posting it was booked through: an export is the whole book, so that transaction is in the ledger's transaction section under its own guid and is restored before the invoices and bills are read. Its payments come back to it too, retargeted rather than applied again, keeping their own guids, descriptions and split memos.

**A `payment:` block's `memo:` reaches the book.** Nothing wrote it before: a block naming `txn_guid:` matches its payment on that guid alone, so a corrected memo left the invoice matching, the run reported `invoice "…": unchanged` and `Updated: 0`, and the correction was dropped without a word. The memo is the payment **transaction's** — `ApplyPayment` puts it on that transaction's splits and nothing about the invoice or the bill holds it — so it is written there, and the run counts it under `Updated:` with the transactions while the invoice goes on reading `unchanged`, which it is. It is the **settling split's** memo — the receivable or payable split in this invoice's lot, the one `txn_split_guid:` names — which is the split every writer reads it back from, so a correction lands where the next export looks for it. One block describes one settlement and states the memo of the one split that settlement is: a payment settling two invoices carries a split for each, its blocks name one apiece, and the bank split they share is neither block's. The bank split follows a correction only where it still holds what the settling split held — that is how `ApplyPayment` leaves the two sides of a payment — and not at all where it is shared, so the wording a bank feed gave a wire is what it keeps. Everything else on the transaction is left alone whatever its memo reads: the other invoice's portion, a wire fee, the residue of an overpayment. A payment is written out twice — as its invoice's block and as the transaction that block names — and where those two disagree the **block** wins: it is the invoice's own statement about its own settlement, and it is the memo a reader corrects. A ledger an earlier release wrote is the one file where they disagree by construction, its block carrying the bank split's wording while naming the receivable one; such a block is recognised by the wording being the one the file gives the bank split, and it changes nothing.

**A vendor bill written by an older release is repaired rather than fought with.** A bill line carries a bill-side owner pointer, and GnuCash writes a line's `b-taxable` / `b-taxincluded` only for lines that have one. A release before this tool wrapped vendor invoices and bills as `Bill` gave its lines the *invoice*-side pointer instead, so those flags were never written: `taxable: false` came back true and `tax_included: true` came back false, on every reload. Rebuilding an invoice used to heal that by accident, every line being destroyed and made again — and lines are edited in place now, so nothing would have. Such a bill would have differed from its own exported ledger on every single import: reported `updated` for ever while unposted, and refused with "unpost-bills first" once posted, an instruction that does not fix it either. The pointer is set where the line is edited, and the invoice-side one cleared with it — a line holding both is written twice and read back as two identical lines. What a person sees is a bill that finally reports `unchanged`, with the `taxable:` it was given.

**A printed page read into another book stays put.** Every guid a printed page carries names the *source* book — `posted_txn_guid:` its posting transaction, each payment's `txn_guid:` and `txn_split_guid:` the movement that settled it — and the book reading it has none of them, which is what handing an invoice to somebody else means. Read strictly, that invoice was out of date the moment it arrived: each import unposted it, destroyed its posting, orphaned the payment with a warning about the money still showing in the bank, and posted it again under a new transaction. Measured on the same unedited file read twice — the posting moved from bdfc62ec… to fb35b412…, and would have moved again on the third read. A guid this book does not hold is not a disagreement now, on the posted side as it already was on the payment side; a guid it *does* hold, naming some other transaction, still says the invoice is out of date. And the posting made in its place is announced rather than silent — `note: posted_txn_guid '…' names no transaction in this book — posting invoice 'INV-2026-001' afresh, under a new transaction of its own` — because that is the one line of the invoice that cannot be honoured, and a reader comparing the two books would otherwise meet a transaction with no way of knowing it was minted here.

**A credit says which credit it is: `lot_guid:` on the split.** `lot_owner:` says whose money a split is, and an owner may hold several credits — a deposit in January and another in February — so which lot a split joined was decided by the import rather than by the file: the oldest open lot the split would reduce. A refund written against February's deposit came off January's, and the export then described two credits the ledger just imported did not.

```
2026-03-05 * "Refund of the February deposit to Acme"
	Assets:Bank -40.00 CAD
	Assets:Accounts Receivable 40.00 CAD
		lot_owner: customer:C001:9f14a498cc894d50931f855a9a31d594
		lot_guid: "7c2f9a1b5e8d4c3a9016b7d2e4f80523"
```

Every split in a credit lot carries it on export, the deposit that opened the credit as well as whatever settles it, so a book rebuilt from an export holds the credits it came from rather than new ones GnuCash minted — a ledger kept beside the book goes on naming the same credits after a restore. A block naming none behaves as it did, which is what a hand-written file does. A named lot must be this owner's, on this account, open, and not a posted invoice or bill's, each refused by name; and a `lot_guid:` the book has no lot for opens the credit under that guid, or, on a clearing split, is refused rather than inventing a credit out of a typo. A split already in a lot stays there — an exported credit re-imported over itself must not open a second one — so editing the line to name another credit is refused rather than quietly doing nothing, and the message names the `payment:` block that does move money between credits.

**A lot's guid is one of two things that had to be measured before any of this could be written**, and both are in `tests/research/`: `GNC_ID_LOT` is `"Lot"` and its collection answers by guid, and a guid forced on a lot marks nothing dirty — so a session whose *only* change is one saves nothing at all and reports that it saved. Nothing here runs into that, because a lot is named only where the import has just created it and put a split in it.

**A tax table's `entry:` lines have no guid, and cannot**: measured on GnuCash 5.10, the whole of a `GncTaxTableEntry`'s API is its account, its amount, its type and the table it belongs to. Nothing is lost by that here — an existing tax table is skipped rather than updated, because posted invoices and bills hold pointers into it.

### An invoice or bill line carries every column GnuCash gives it

**A ledger used to lose a line's discount, its note, and a bill line's action, billable flag, chargeback customer and payment.** An entry was written with eight fields, and GnuCash's windows offer more than eight: the discount and the two choices that say what it means, a note per line, and — on a bill — whether the line is re-billed to a customer, which customer, and whether it was paid in cash or on a card. All of them survive a save in GnuCash, so a ledger that omitted them described an invoice the book did not hold, and re-importing that ledger took them out of the book.

```
	entry:
		date: 2026-02-01
		description: "Consulting, February"
		action: "Hours"
		account: "Income:Sales"
		quantity: 10
		price: 100
		taxable: false
		tax_included: false
		notes: "Agreed rate for the first quarter"
		discount: 10
		discount_type: percent
		discount_how: pretax
```

`discount_type` is `percent` or `value`, `discount_how` is `pretax`, `sametime` or `posttax`, and a bill line adds `billable: true`, `billable_to: "C001"` and `payment_type: cash|card`. Those are GnuCash's own words, the ones it writes in its file, and a word outside them is refused by name — the engine accepts any number there, warns about it on every read, and silently rewrites it on save, so a file asking for something GnuCash cannot name would have imported as a different discount from the one it asked for.

**`billable_to:` is what makes `billable:` worth carrying**, and it names a customer id — the same one a `customer` block declares. A line marked billable to nobody is one GnuCash cannot offer when that customer's invoice is created, so carrying the flag without its target would have been half the field. An id the book has not got is refused by name. GnuCash also lets a line be charged back to one of that customer's **jobs**, which this format has no key for: a book holding one is refused by `export --include-business-objects` and by `print-bill --format plaintext`, naming the line, rather than written as the customer behind the job — which would read back as a customer chargeback and quietly change the book.

**A file naming none of the new keys imports as it always did, and an export states them anyway.** An entry GnuCash has never been asked about holds an empty note, no discount, `percent`, `pretax`, not billable, billable to nobody and `cash`; an export writes each of those out rather than leaving the line off, so a ledger says what the invoice window and the bill window show and a reader does not have to know which absent line stands for which default.

**An `entry:` block describes the whole line**, every key of it, `action:` included. An unnamed key means the default rather than "leave it alone" — on a line being created and on a line being edited alike — and the comparison that decides `unchanged` reads the same defaults. Editing one field of a line means writing the rest of that line too, which an exported ledger already carries.

**Export before re-importing a ledger written by an earlier release.** Such a ledger names none of these keys, so importing it into a book whose lines carry a note, a discount, a billable flag or an action clears them, exactly as it always did for `action:`. On a **posted** invoice it does not clear them: naming none of the keys makes the file state different lines from the ones the book holds, and that is refused — `unpost-invoices` first, and the import after, which is what the message says. An export taken with this release carries every key, and re-imports as `unchanged`.

**A key belonging to the other kind of invoice is refused by name.** `discount:` on a bill entry, `billable:` or `payment_type:` on an invoice entry: GnuCash's window for that invoice has no such column, so the value would be read by nothing, stored nowhere, and reported `unchanged` on every later run — the same silence these keys were reserved to end.

**A printed invoice states what the book posts for a discounted line.** `entry_amount:`, `entry_tax:`, each `breakdown:` block and the three `invoice_*` totals were computed here as quantity × price, which ignores the discount — so an invoice handed to a customer said 1000.00 while its own A/R split said 990.00, and `--format pdf`, drawn by GnuCash's own report, printed the right figure beside the wrong one from the same command. Every figure is read from `gncEntryGetDocValue`, `gncEntryGetDocTaxValue` and `gncEntryGetDocTaxValues` now — the functions GnuCash posts from — because a discount lands by three different rules. Measured on 5.10, 10 × 100.00 less 10 per cent against a 10 per cent tax table:

| `discount_how` | posted |
|---|---|
| `pretax` | 900.00 + 90.00 tax |
| `sametime` | 900.00 + 100.00 tax |
| `posttax` | 890.00 + 100.00 tax |

**A page whose figures are not the book's is refused, on a bill as on an invoice, and whether or not anything else about it changed.** `print-bill --format plaintext` states `entry_amount:`, `entry_tax:`, a `breakdown:` per tax account and three `bill_*` totals, and the import read none of them — the bill half of that check was never wired. Nor did the invoice half fire on an invoice that matched in every other way: those figures are derived, so they are not part of what makes an invoice `unchanged`, and the run returned before anything looked at them. So a page printed by an earlier release re-imported quietly against a book that posts something else. Every figure is compared exactly, the per-line ones included: the import works the invoice out the way the writer did, fitting each line's tax to the invoice's, so what it compares against is the figure the page states rather than the line read on its own.

**A refused figure abandons the whole run, and the book on disk keeps everything.** A line's tax cannot be judged before its siblings exist — it is fitted to the invoice's — so the check runs once the invoice has been committed, where the per-entry half used to run inside the entry loop. On a file that states a wrong figure *and* changes something else, the invoice is therefore unposted, its entries rebuilt and its payments re-applied in memory before the figure is looked at. None of that is written: the refusal is raised out of the business-object pass, above the only save, so the run exits non-zero having saved nothing — not that invoice, and not the objects that came before it. Correct the file and import it again.

**And a printed page's columns add up.** A line's tax is rounded to fit the invoice's stated tax rather than on its own: three 100.00 lines at 15 per cent tax-included are 13.0434… of tax each, and rounded separately they print 13.04 apiece against a stated 39.13 — a column a reader cannot add. Fitted, one line carries the odd cent and the column reads as a column, each `breakdown:` block adding to its own line the same way. GnuCash's own page prints no per-line tax at all, so nothing here disagrees with it; the figures a book holds — the subtotal, the tax and the total — are the engine's own either way.

**A printed page's totals are the invoice's own**, `gncInvoiceGetTotalSubtotal`, `gncInvoiceGetTotalTax` and `gncInvoiceGetTotal`, rather than its lines added up — GnuCash rounds an invoice's tax once, not line by line. A bill of three 100.00 lines at 15 per cent tax-included posts 260.88 + 39.13 = **300.01**, where the rounded per-line tax adds to 39.12 and the page said 300.00 against its own A/P split of 300.01. This affects invoices and bills alike, and an invoice with one line or with figures that round exactly is unchanged.

**No figure is compared to another within a tolerance any more.** A page's `entry_amount:`, `entry_tax:`, each `breakdown:` amount and rate, and the three invoice totals are compared exactly, as the transaction side of the ledger always was. A cent of slack forgave a page stating a total the book contradicted — which is the whole of what these figures are for — and it forgave it in the one shape that actually occurs, an invoice printed by an earlier release sitting exactly one cent under a tax-included book. A ledger that states a figure now states the book's figure.

`AccountCategorizer.is_balanced_transaction` is gone with the same sweep. It took a `tolerance_numerator`, and behind that a worse fault — it added each split's numerator while ignoring the denominator under it, so a half and a hundredth counted the same — but no command ever called it, so neither fault could be reached and there was nothing to fix. Code no scenario reaches is deleted here rather than corrected.

The same went for a cost-basis sale, where `abs(stated − expected) <= half a cent` stood in for arithmetic nobody had done. `basis_cost × quantity` can land between cents, and the value on the split is what GnuCash booked — that figure rounded to the currency's unit — so the rounding is performed and the two compared exactly. A ledger this tool wrote states the figure the engine booked, so it is unaffected; a hand-written one that rounded a tie the other way is not, and that is under Breaking below.

**A credit note is carried, by one key on the block.** GnuCash's Business → New Credit Note makes a `gncInvoice` with a flag, storing its lines negated, and nothing else about it differs — so `credit_note: true` is the whole of what a ledger has to say:

```
invoice "CN-001"
	customer_id: "C001"
	currency: CAD
	date_opened: 2026-03-05
	credit_note: true
	entry:
		date: 2026-03-05
		description: "Two days of work, returned"
		account: "Income:Sales"
		quantity: -2
		price: 100
```

Measured on 5.10: that invoice's own totals answer +200.00 — positive, like an invoice's — and it posts `Income:Sales` +200.00 against the receivable −200.00, the mirror of the invoice it reverses. The quantities a ledger states are the ones the book holds either way, so nothing is reinterpreted on the way back in, and every figure a printed page states is read with the flag, which is what makes its column agree with its total. A vendor credit note is the same key on a `bill` block.

**Every command handles one**: `export --include-business-objects` writes the key, `print-invoice`/`print-bill` draw the invoice in all three formats, and `import` reads it — into a fresh book as readily as into the one it came from. Written without the key, as an earlier release wrote it, a credit note rebuilt as an ordinary invoice and posted against the receivable the wrong way round with nothing saying so; that is the defect this closes.

A block that leaves the key out is an ordinary invoice, which is what every ledger written before this release said, so no existing file reads differently.

**A quoted value may hold a newline, and every value a writer writes is escaped.** `\"`, `\\`, `\n` and `\r` are the four escapes, and the last two are new. Values, and every reference is a value: `customer_id:`, `vendor_id:` and `tax_table:` are escaped like any other. What is **not** escaped is the block header that declares the name — `customer "…"`, `invoice "…"`, `taxtable "…"` — because a header is read by a regex that takes what sits between the quotes verbatim. The two agree for any name that fits on a line: the header pattern is anchored at the end, so it captures everything between the first quote and the last exactly as written, and unescaping the reference recovers that same text — checked against a name holding a backslash before a quote, where both sides read `A\"B`. What still cannot be carried is a name holding a newline, since the header line would end mid-name; that limit is the header's, and predates this release. The business-object writers — customer and vendor blocks, invoice and bill blocks, every `description:`, `action:`, `memo:`, `num:`, `notes:` and custom key on them — wrote their values raw, while the reader has always unescaped what it read. So a value holding a backslash came back a character short, and one holding a newline broke the block it was written in: the reader takes one key per line, so the tail of the note became a key of its own and the export was a file its own importer could not read. `export`'s transaction half has always escaped, which is why this showed on invoices and bills; the two side-file writers — the reconcile preview and the ready-to-import file — escaped quotes alone, and go through the same encoder now.

Because the comparison that decides `unchanged` reads those same fields, a value that came back changed made its invoice rebuild on every import — a posted one unposted, its entries destroyed and posted again under a new transaction, every run, for as long as the value held a backslash.

**One ledger reads differently than it used to, and it is worth checking for.** `\n` and `\r` mean a newline and a carriage return now, and they meant nothing before — the reader kept both characters. The writers that produced those files wrote their values raw, so a customer note, a description or a memo holding `see C:\notes` or `Order\ref` was exported exactly like that, and re-importing it now puts a newline where the `\n` was. `grep -nE '\\[nr]' ledger.txt` finds every such line; a value that meant a literal backslash wants it doubled, `C:\\notes`. Everything else is unchanged: `\\` has always meant one backslash, `\"` a quote, and a backslash before anything else is still left alone with both characters kept.

**A `_reconcile.txt` left over from the last release reads differently too.** That file is written and read by one pair, and the pair moved together: the writer escaped the quote alone and now escapes all four, and the reader undid the quote alone and now undoes all four. A file written before this release therefore holds its descriptions raw, so one containing `C:\name` comes back as `C:`, a newline, and `ame` — the ledger case above, in a file the ledger advice does not cover. They are regenerated from the statement PDFs, so the fix is to regenerate rather than to edit: re-run the reconcile step and the file is written in the new spelling. A `ready-to-import.txt` is not affected in this direction — `import` has always unescaped what it read, so the writer's change corrects that side rather than reinterpreting it.

**A bill entry's `action:` is written now**, on both `export` and `print-bill --format plaintext`. It was left out on the belief that GnuCash stored the action on the invoice side only; an entry given `Material`, saved and reopened, reads back `Material`.

### A printed PDF is the page GnuCash prints

**`print-invoice` and `print-bill` lay their PDF out with WebKit, the engine GnuCash's own Print Invoice button prints with.** WeasyPrint laid it out before, and a second engine reading the same HTML is a second answer to a question GnuCash has already answered — measured on one page: WebKit paints 97 rectangles and WeasyPrint none, because the table borders come from the HTML-4 presentational attributes GnuCash's report writes (`border`, `cellpadding`, `bgcolor`) which WeasyPrint does not implement. A printed invoice had no lines round anything.

The sheet follows the machine, as GnuCash's does: no paper size is named, so GTK takes the one the locale gives — A4 in most of the world, US Letter under `en_US` and `en_CA`. WeasyPrint used its own default instead, which is how the same book printed A4 here and Letter from GnuCash on a Canadian desktop.

**What this needs installed**: WebKit's library arrives with GnuCash, but its Python bindings and a display do not:

```bash
apt install python3-gi gir1.2-webkit2-4.1 xvfb xauth   # 4.0 on older Debian/Ubuntu
dnf install python3-gobject webkit2gtk4.1 xorg-x11-server-Xvfb xorg-x11-xauth
zypper install python3-gobject typelib-1_0-WebKit2-4_1 xorg-x11-server-Xvfb xauth
pacman -S python-gobject webkit2gtk-4.1 xorg-server-xvfb xorg-xauth
```

`xauth` is in each line on purpose: without it the display an invoice is drawn on takes a connection from any local user, and what is on it is a customer's name, address and balance. A machine without them is told which package to install rather than shown a traceback, and `--format html` and `--format plaintext` need none of it. WeasyPrint is still what `income-statement` lays out, that page being this project's own rather than GnuCash's.

**One deliberate difference from GnuCash's own engine: the printing page runs no JavaScript.** GnuCash's viewer leaves scripting on, being a browser as well as a printer, and a report interpolates book text — a customer's name, an entry description, a logo filename — into the page it draws. Nothing about laying an invoice out needs scripting and the page comes out the same without it. Remote images and stylesheets are still fetched, exactly as they were under WeasyPrint.

GnuCash's print dialog also offers PostScript and SVG. Neither is offered here: asking GTK's "Print to File" printer for either — same page, same code — ends with the print operation reporting *finished* and no file written, and an option that exits 0 and produces nothing is worse than one that is not there.

### A printed page uses the GnuCash settings on the machine printing

**Settings made in GnuCash now apply to `print-invoice` and `print-bill`.** GnuCash reads a user configuration at startup — stylesheet settings, and every report configuration saved from a report's options dialog — before drawing anything. Neither print command read the configuration files, so a page came out at built-in defaults: printing one invoice from GnuCash and from `print-invoice` gave `border="1.0"` against `border="0.0"`, a grey page against white, 12pt type against 10pt.

A stylesheet customised in GnuCash now applies to a printed page. A report configuration carrying a customised CSS is drawn by `--report "<the name saved under>"`, registered by the same read, with the options held in the configuration.

Those files are Scheme, and reading them evaluates them — which is what GnuCash does at startup, and what makes a saved configuration work at all. So `print-invoice` and `print-bill` now evaluate the Scheme in `stylesheets-2.0`, `saved-reports-2.4` and `saved-reports-2.8` under the *printing account's* GnuCash data directory (`$GNC_DATA_HOME`, else `$XDG_DATA_HOME/gnucash`, else `~/.local/share/gnucash`). On a personal machine those are the reader's own files; on a shared build account, whatever is in that account's home directory is what runs. A file that will not parse is passed over with a warning naming it, rather than costing the invoice.

**`GNUCASH_PLAINTEXT_NO_USER_CONFIG=1` skips the read**, drawing at GnuCash's built-in defaults exactly as before this release — for CI, a shared build account, or any run that wants the same page whatever is in the home directory it happens to have.

**And a book set to a different report prints with that report.** GnuCash 5 added a **Default Invoice Report** setting to File → Properties → Business. It decides what GnuCash draws with when the Print Invoice button is pressed on an open invoice, and a book that has never been given one prints with the Printable Invoice. `print-invoice` and `print-bill` read the same setting, so a book set to a saved report configuration needs no `--report` on the command line. GnuCash 3.8 and the 4.x line have no such setting, so the same book prints with its chosen report on a GnuCash 5 machine and with the Printable Invoice on an older one, and nothing is said there because there is no setting to read. Two consequences on a GnuCash 5 machine, each written to stderr as it happens:

- a page drawn by a saved configuration carries the options held in the configuration, and the three display switches `print-invoice` sets are not among the options — so a page can state one combined `Tax` figure where the Printable Invoice states GST and PST by name for the same book;
- a machine holding no such configuration prints with the Printable Invoice rather than refusing. A saved configuration is a file in the GnuCash the configuration was saved from, and a build server or a colleague's laptop holds no copy.

`--report` overrides the book for a single run. GnuCash 3.8 and the whole 4.x line have no such book option, and a book on either era prints as before.

**New: `set-invoice-style` sets the footer and the page's CSS.** The footer and the CSS are the two boxes GnuCash's report options give as Display → Extra Notes and Layout → CSS, and until now setting either meant opening GnuCash — no use on a machine printing from a script:

```bash
gnucash-plaintext set-invoice-style book.gnucash --note "Payment due in 30 days"
gnucash-plaintext set-invoice-style book.gnucash --note ""          # no footer
gnucash-plaintext set-invoice-style book.gnucash --clear-note       # the report's own
gnucash-plaintext set-invoice-style book.gnucash --css invoice.css
gnucash-plaintext set-invoice-style book.gnucash --show             # what is set
```

The footer has three states and `--show` names each: a book saying nothing prints the sentence the report carries, `--note ""` prints no footer at all, `--note "…"` prints the text. `--clear-note` and `--clear-css` take a setting off the book — the way back to the report's own footer on a localized build, where GnuCash's default is translated and cannot be retyped.

The book keeps the footer and the CSS, and `print-invoice` and `print-bill` apply both alike. A book holding neither setting prints the footer and styling the report itself carries — for the footer, GnuCash's "Thank you for your patronage!".

Neither setting is part of the plaintext format: no export writes the footer or the CSS and no import reads either, `set-invoice-style` being the one command holding both.


### Breaking: changes that affect ledgers and scripts that worked before

**Importing a file that changes anything about a posted invoice or bill except its payments fails**, where it used to unpost the invoice, rebuild it and post it again in one step. A run that did that destroyed the posting transaction the book was booked through, minted another, and left the invoice's payments settling a transaction that no longer existed — reported as `updated` and otherwise unsaid. Two steps now, each saying what it is doing: `unpost-invoices <book> INV-2026-001` (or `unpost-bills`), then the import — which puts the invoice back on the posting it already had, since the ledger carries that transaction in its transaction section.

What that covers is every part of an invoice that is not a payment: its **lines**, its **`posted:` block** (date, due date, memo, A/R or A/P account), its **`date_opened:`**, its **`credit_note:`** flag, its **`notes:`**, its **billing id** and its **custom keys**. A script that corrected any of those in one step now needs the unpost in front of it.

What still goes through in one step: a **`payment:` block** — recording money against an invoice the book has booked is what a posted invoice or bill is for — including `auto_apply_credit: true`, which asks for the owner's credit to settle it; and a file that says **`posted: none`**, which has asked for the unpost out loud and may change the lines in the same step.

**A file giving a guid the book gave to another object fails.** An `entry:` line giving another invoice's line, or the same guid on two lines of one invoice, was written into the book before, leaving two objects with one guid — GnuCash finds an object by looking its guid up in a hash, so one of the two became unreachable. The refusal names the guid and what the book has it on. Remove the `guid:` line to add the block as a new line instead. A guid the book simply has not got is not affected: that is the guid a new line asks for, and it is created with it.

**A split block is matched by its `guid:` rather than by its position**, so a ledger whose split blocks were reordered by hand imports differently than it did: each block now edits the split it names instead of the one in its place. Where that used to move amounts and memos between two splits of one account and report `Updated: 1`, it now leaves each split as its guid says. A hand-written file naming no guids is unaffected — position still decides there.

**A split in a lot that no block names fails**, where it used to be destroyed. That is a settlement taken out of its invoice's lot with no figure moving, so the invoice read unpaid while the balance stayed put; one mistyped hex digit in a `guid:` was enough. The refusal names the lot.

**`guid: 0`, `guid: 000` and thirty-two zeros fail.** The first two used to read as a block giving no guid at all — an unquoted number is a number and zero is falsy — so the block fell through to positional matching while `guid: "0"` was refused. Thirty-two zeros used to be accepted: that is GnuCash's null guid, meaning *no* guid, and every writer here treats it as absent, so a lot stamped with it exported without its `lot_guid:` line.

**`lot_guid` is a reserved split key now**, as `lot_owner` and `guid` are. A book that used `lot_guid` as an ordinary custom key on a split kept it in a slot and exported it as a custom line; that slot is no longer written out, and a ledger carrying `lot_guid:` with no `lot_owner:` beside it is refused rather than stored. Rename such a key — `credit_ref`, say — before importing a ledger that carries one.

**An invoice whose id is no filename at all prints as `untitled.pdf`**, where it printed `document.pdf`. `print-invoice`/`print-bill` with `-o dir/` name each file after its invoice's id; where nothing in that id may be written to a filename — every character stripped, or an id that is only separators — a fallback stem is used, and that stem is `untitled` now. An id with one usable character in it is unaffected, which is every id in an ordinary book. A script matching `document.pdf` in a printed directory needs the new name.

**A run whose only change is a `payment:` block's `memo:` writes the book**, where it used to write nothing. The correction lands on the payment transaction and the run counts it under `Updated:` with the transactions; the invoice goes on reporting `unchanged`, as it did, because it is. A script that read `Updated:` to decide whether to back up the file, or that relied on such an edit being a no-op, sees a run that changes something where it saw one that did not.

**A bill line charged back to a job cannot be exported**, and is refused rather than written without its chargeback: `export --include-business-objects` and `print-bill --format plaintext` refuse and name the line. GnuCash's Bill window offers a customer or one of that customer's jobs as the chargeback target; `billable_to:` states a customer and this format has no key for a job. Such a line used to export with no chargeback line at all, and the re-import cleared it — so this replaces a silent loss with a refusal. Two ways past it: `export` without `--include-business-objects` still writes the whole transaction half of the book, or change the line's chargeback to the customer itself in GnuCash, which this format does carry.

**`credit_note:` is reserved on an `invoice` or `bill` block, and used to be a custom key.** An invoice block does carry custom metadata, so a ledger using that name for something of its own stored it in the invoice's slot and got it back on export. The same ledger now sets GnuCash's flag with it and posts the invoice the other way round, and a value that is neither true nor false is refused by name. Nothing else changes for a book that never used the name.

**A ledger exported from a book holding a credit note now carries `credit_note: true`**, where an earlier release wrote that invoice as an ordinary `invoice` or `bill` block. A ledger written by an earlier release therefore describes the credit notes in it as ordinary invoices and bills, and re-importing one clears the flag and reposts the invoice the other way round — the same shape as every other key this release adds, and worth an export with this release before re-importing an old file.

**A sale must value what it sells at exactly what its cost basis makes it worth.** The check allowed half a cent either way; it rounds `basis_cost × quantity` the way the engine rounds and compares exactly now. Say that product works out to 1.005 — a figure no split can hold and no file may state, which is why it is rounded at all: the book makes the sale worth 1.01, half away from zero. A file stating `value: "1.00"` beside it was accepted before, being within half a cent, and is refused now with both figures named. A ledger this tool wrote is unaffected, since the value it states is the one the engine booked.

**`taxable: True`, `taxable: 1` and `taxable: yes` mean true now, and used to mean false.** The flag was compared against the string `true`, and a line is decoded before it is compared — `True` arrives as a boolean, `1` as an integer, neither equal to `"true"` — so all three read as **not taxable**, and so did `tax_included:` on an `entry:` block and `accumulate:` on a `posted:` block written the same ways. They are read as words now, so such a line becomes taxable: its tax, every `breakdown:` block, the invoice's three totals and its posting transaction all change, and the run reports `updated`. A `posted:` block spelled that way accumulates as it asked to, so its posting transaction carries one split per account where it used to carry one per line. Worth looking for before importing an existing ledger:

```bash
grep -niE '(taxable|tax_included|accumulate): *(#?true|1|yes)$' ledger.txt
```

`#?true` because `taxable: #True` had the same defect and is the likelier spelling to find: `#True` is what an export already wrote for `placeholder:` and `tax_related:`, so a hand-written file following that style decodes to a `bool` and lost the same comparison. `-i` because the reading is case-insensitive now and `TRUE` and `Yes` were as broken as `True` was. It over-matches by one spelling: a line reading exactly `true`, lower case, always meant true and still does — every *other* line it finds was doing nothing before and does something now. Only `taxable:`, `tax_included:` and `accumulate:` are affected; `billable:` is one of the keys this release adds, so no ledger written before it can carry one.

**Every flag an export writes is now `#True` or `#False`**, where nine of the twelve were written as bare `true`/`false`. `#` is this format's mark for a value that is not a string — `#None`, `#3/4`, `#100` — and a bare `true` is not a boolean at all: it decodes to the string `"true"`. That single fact is under most of this release's boolean bugs, `taxable: True` reading as false and `placeholder: false` killing the account it sat on among them. `taxable:`, `tax_included:`, `billable:`, `accumulate:`, `active:`, `credit_note:` and `from_credit:` therefore change spelling in exported and printed ledgers; `placeholder:`, `tax_related:` and `closing:` were already written this way. Nothing changes for reading — a ledger spelling them as words imports exactly as before — so the practical effect is that an export re-imported still reports `unchanged`, and a diff of two exports across this release shows those lines moving.

**A mistyped boolean is refused, wherever it is.** Every flag a ledger carries reads `true`/`1`/`yes` or `false`/`0`/`no` — and `#True`/`#False`, which is what they are written as — and anything else is named: `taxable:`, `tax_included:` and `billable:` on an `entry:`, `accumulate:` on a `posted:` block, `credit_note:` and `auto_apply_credit:` on an invoice, `from_credit:` on a payment, `active:` on a customer or vendor, `closing:` on a transaction, `placeholder:` and `tax_related:` on an `open` block, and `cost_basis_force:` on a split. A typo used to get whichever answer the key happened to be read with, and each was the costly one. Four — `active:`, `closing:`, `from_credit:` and `auto_apply_credit:` — read anything that was not a falsy word as **true**, so `auto_apply_credit: treu` spent the owner's credit against an invoice the file never asked to settle that way. Four more — `taxable:`, `tax_included:`, `accumulate:` and `cost_basis_force:` — compared against the truthy words and read a typo as **false**, so `cost_basis_force: treu` was silently *not* forced and the sale failed telling its author to add the key they had just added. And `placeholder:` and `tax_related:` got neither answer: they reached GnuCash as the string that was typed.

**An `open` block takes `placeholder: false` now, and used to refuse the account.** Those two keys were read straight off the decoder, which knows `#True`/`#False` — what an export writes — and not `true`/`false`, what a person writes. A bare `false` arrived as the *string* `"false"` and GnuCash refused it: `Failed to create account …: Python object passed to a gboolean argument was not True or False`, with the account then missing from the book and everything naming it failing after it. A hand-written ledger spelling these as words imports now; `#True`/`#False` mean what they always did. `taxable: treu` used to import as **not taxable** — the costly direction, and costlier now that the flag decides the line's tax, every `breakdown:` block and the invoice's totals, so a page printed after the typo agreed with itself and re-imported `unchanged` against a book that had quietly dropped the tax. `accumulate: treu` used to post a split per line where the invoice asked for one per account, which is what the ledger then exported and re-imported as `unchanged`. `billable:` is new here and takes the same words for the same reason.

**Seven keys on an `entry:` block are reserved now, and used to be ignored.** `notes:`, `discount:`, `discount_type:`, `discount_how:`, `billable:`, `billable_to:` and `payment_type:` write GnuCash's own entry fields from this release. An entry block has never carried custom metadata, so a key it did not recognise was neither stored nor reported — a ledger using one of these for something of its own imported cleanly and dropped the value in silence. The same ledger now writes it into the book, and where the value does not fit the field the import is refused by name rather than reinterpreted:

```
discount: "agreed in January" is not a number. This key sets the discount on an
invoice line, and takes a figure — `discount: 10` with `discount_type: percent`
or `discount_type: value`. It was ignored by earlier versions, so a ledger using
it for something else needs the line renamed
```

`discount_type:`, `discount_how:` and `payment_type:` take GnuCash's own words — `percent`/`value`, `pretax`/`sametime`/`posttax`, `cash`/`card` — and any other word is refused the same way. `billable:` takes `true`/`1`/`yes` or `false`/`0`/`no` and refuses anything else, rather than reading an unknown word as "not false" and re-billing a line to a customer nobody named. Nothing here changes a book that never used these key names.

**`import` exits non-zero when it reports an error.** A run that collected per-object errors used to print `Errors: N` and still exit 0, so `gnucash-plaintext import book.gnucash ledger.txt && next-step` ran the next step over a partly-imported book — and the same command with `--include-business-objects` exited 1, so one file got two answers depending on a flag. The exit code now follows what the summary says. Scripts that chained on success will stop where they previously continued, which is the point; a script that wants the old behaviour should test the summary itself rather than the exit code.

This includes `import --dry-run`, which is the case likeliest to be scripted: a dry run over a file with per-object errors now exits 1, so `import --dry-run && import` stops rather than running the real import over exactly the file the dry run objected to. It still writes nothing — reporting and saving are separate — and a clean file's dry run still exits 0.

**`--report "<a name>"` can now be refused as ambiguous where it worked before.** Reading the saved-report files registers every configuration saved in GnuCash, and GnuCash pre-fills "Save Report Configuration As…" with the name of the report being saved — so a configuration saved by pressing Enter is a second `Printable Invoice`, and `print-invoice book INV --report "Printable Invoice"` is refused rather than drawing whichever the hash yielded. The refusal names both guids, and `--report <guid>` is the way through; renaming the configuration in GnuCash is the other.

**Printed invoices and bills carry GnuCash's footer again: "Thank you for your patronage!"** The three `Extra Notes` writes that emptied the option are gone, so a book saying nothing about the footer prints the sentence GnuCash's report carries — on bills too, where the sentence thanks the supplier and reads oddly, that being what GnuCash prints for a bill. `Extra Notes` holds text somebody chose, and choosing belongs to the reader rather than to `print-invoice`: `set-invoice-style book.gnucash --note ""` prints no footer at all, `--note "…"` prints a sentence of the book's, and `--clear-note` goes back to GnuCash's.

**`delete-transactions` exits non-zero when it could not write an undo copy.** The transaction is still removed — this command is the only way to remove one the format cannot write, and it warns on stderr and says so in the backup file itself. What changed is the exit code: `delete-transactions … -o undo.txt && next-step` chained on a backup holding nothing but comments, because the file existed and the run said it went fine. A script that wants the old behaviour should test for the transaction's absence rather than the exit code.

**A `payment:` block may no longer spend a foreign account whose cost bases still have a balance.** Cash leaving a foreign account is a disposal and has to name the cost basis it comes out of, and a payment block has nowhere to name one — GnuCash's own `ApplyPayment` writes the bank split. Such a payment is now refused, naming the account, what the payment spends, and what balance its bases still have between them.

This reaches ledgers that imported cleanly before, because settling *into* a foreign account is itself what opens a basis on it, and it is asked of every foreign bank rather than only one in a third currency — paying a USD bill out of a USD bank whose bases still have a balance drifts the same way and reaches none of the cross-currency arithmetic. Write the settlement as an ordinary transaction whose bank split carries `cost_basis_split_guid:`, and attach it to the invoice with `txn_guid:` / `txn_split_guid:`. README's foreign-currency section shows the shape, and [docs/multi-currency.md](docs/multi-currency.md) lists the refusal beside the others.

**`date_format` on the `company` block is now a reserved key.** It used to be any other key, so a ledger naming it was kept as book-level custom metadata: round-tripped, never read, never printed. It is now GnuCash's own Fancy Date Format option, so a ledger that has been carrying `date_format` for something of its own will find that value moved into the GnuCash option its own reports read — and, if it is one of the four formats that map, deciding the dates on every printed page.

A book already holding it as a custom key is migrated on the next import **that carries a `company` block** — the migration lives in that block's import, so a run of transactions alone does not perform it, and a book whose ledgers never mention the company keeps the old copy indefinitely. When it does happen the value moves to the option and the custom copy is dropped, so nothing carries two answers. Until then, an export emits it once — from the option where this version keeps it, or from the custom copy where an older book still does — rather than twice. If you were using `date_format` to mean something else, rename your key before importing again — and see the note below, because the same now applies to every other name the `company` block owns.

**Every `company` field name is reserved, and a custom book key of the same name is now acted on.** The set is `name`, `contact`, `id`, `gst`, `pst`, `phone`, `fax`, `email`, `url`, `date_format` and the address lines — nine of them ordinary enough that a book may well have picked one for something of its own, through `set-book-key` or a `company` block written before the name meant anything.

Three new behaviours reach them. A block that *names* the key deletes the custom copy, where before both survived and the custom copy won the round trip. An import whose block does **not** name it moves the custom copy into GnuCash's own Business option, when that option is empty. And when that option is **not** empty, the custom copy is deleted — it is a second answer to a question the option already answers, and left in place it was written back over the option the next time someone cleared that field in GnuCash. That deletion is announced on stderr, naming the key and the value, because nothing else would say so: the writers prefer the option, so the value is not in your last export either. So `set-book-key --key id --value "ISO-9001"` — legal until now — becomes GnuCash's **Company ID** on the next import carrying a `company` block, and prints on invoices as the company registration number.

**This reaches migration files too.** `set-book-key` is a valid `migrate` operation, so a checked-in `migrations/00N-*.txt` line like `set-book-key --key id --value "ISO-9001"` now fails — and `migrate` stops at it. On books where that migration is already recorded as applied nothing changes, but building a *new* book from the migration set aborts partway. Edit the migration line to a name outside the set, or state the value in a `company` block instead; a migration already applied does not re-run, so changing the line does not re-apply it.

If you have used any of those names for something of your own, rename the key before importing again. `gnucash-plaintext export --include-business-objects` shows what a book holds; a name outside the set is untouched, including one that merely looks like a reserved one (`addr7`, `company_id`, `url2`).

**`set-book-key` refuses those names outright.** `--key date_format`, `--key id`, `--key phone`, `--key addr[0]` and the rest of the set are stored in GnuCash's Business options now, and every reader looks for them there — so a write into the custom blob would report `created` and then be invisible to the export, to the printed page and to the reports, until the next import carrying a `company` block deleted it. The refusal names the block to state it in instead. Keys of your own are unaffected, including ones that merely look like a reserved name: `addr7` is yours.

**An address is written `addr[0]`, `addr[1]`, … and the `company` address is no longer cut off at four lines.** The lines of an address are numbered in brackets now, counting from zero, on the `company`, `customer` and `vendor` blocks alike. Two things this fixes, both measured on real books:

- **A company address longer than four lines was silently truncated.** GnuCash's File → Properties → Business address is one free-text box and takes as many lines as you type; the export wrote the first four. A six-line address came out of `export` with its country and its attention line missing, so a book rebuilt from that ledger had a four-line address and nothing said so. The `company` block now writes and reads every line the book holds.
- **A block naming one address line emptied the others.** `company` with `addr[0]:` alone rewrote the whole address from that one line — an address of four lines cut to one. It now follows the rule the rest of the format follows, and the customer address always did: what a block does not name, it is not asking to change. To empty a line, name it empty.

A customer's or a vendor's address is a GnuCash `GncAddress` and genuinely has four fields, so `addr[4]` on one of those blocks is **refused** rather than filed where nothing prints it. Only the book's own address takes more.

`addr1`–`addr4` are still read, so ledgers written before this keep importing, and mean what they always did — `addr1` is the first line, which is `addr[0]`. Nothing writes them any more, so a re-export of an existing book will show this as a diff. A block spelling one line both ways is refused rather than resolved. Scripts that grep exports for `addr1:` need the new spelling.

The brackets are what make this safe to extend: `addr[7]` is the eighth line of the address, while `addr7` is an ordinary custom key of yours. Numbering the keys `addr5`, `addr6` instead would have quietly taken every such name for the format.

**If you wrote `addr5:` to get a fifth line, rename it to `addr[4]:`.** It was the obvious thing to try and it never worked: the previous version filed it in the book's custom metadata, where it round-tripped through the export and never reached the address, so those books have a four-line address and a stray key beside it. This version does not change that — `addr5` is an ordinary key, by the rule above, and nothing migrates it, because the format cannot tell a line you meant from a key you named. Renaming it puts the line in the address; leaving it alone keeps it exactly as it is today, exported and never printed. The same applies to `addr6`, `addr7` and so on.

An index carries no leading zeros: `addr[07]` is refused, naming `addr[7]` as the line it meant, rather than being taken as a second name for the same line. And an index past ten thousand is refused as a typo — the index is a position, so `addr[10000000]` asks for a ten-million-line address built out of ten million empty ones. That is a limit on what a file may ask for; a book's own address is not capped, and however many lines GnuCash holds is what the export writes.

**A book holding its address in both places has them merged.** Typing an address into File → Properties → Business on a book whose address was still in the older custom slot leaves both populated; the option is the address as far as it goes, and the slot supplies only what lies past the end of it. The next import that carries a `company` block settles it onto the option and clears the slot's copies.

**`cost_basis_available:` is now `cost_basis_balance:`, and `--available-only` is now `--with-balance-only`.** *Available* named nothing — available for what, of what — and the figure it holds is a balance: how much of that cost basis has not been sold. The key, the `fx-balances` column (`AVAILABLE` → `BASIS BALANCE`), the totals line (`Available USD:` → `Total USD basis balance:`) and every refusal that mentioned it now say so.

A file still stating `cost_basis_available:` is **refused by name**, pointing at the new key. It is not accepted quietly: the old spelling is no longer a reserved key, so it would be kept as an ordinary custom key that nothing reads — the balance unchecked, the file's own sales not counted as already applied, and the basis re-opened at everything it brought in. That gives back currency the same file records as sold. The figure itself does not change; only the key.

Books already written carry the old KVP and are read as they stand — the balances are not lost and nothing has to be re-imported to recover them. `fx-balances` shows them, a sale can be measured against them, and the next write of a basis replaces the old key with the new one. It is only a *file* stating the old key that is refused, because a file is where the wrong reading would do damage. Scripts passing `--available-only` need the new flag; there is no alias.

**A booked amount is judged against the currency as well as the account, so some ledgers that imported cleanly are now refused.** An amount used to be measured against its account's own unit alone, so `Expenses:Fuel 1.819 CAD` on an account carrying `commodity_scu: 1000` imported without complaint. It is now measured against the coarser of the two — there is no such thing as a tenth of a cent of Canadian money, whatever account it sits in — and that file is refused:

```
error: the amount on split 'Expenses:Fuel' states 1.819 CAD, which is finer
than that currency: its smallest unit is 0.01, and a booked amount is a whole
number of those …
```

**A ledger that imported cleanly before may now be refused**, and for this one there is no correction that keeps the figure: 1.819 is not an amount of money, so the remedy is to round it (`1.82`) or split it across entries. What the finer account is still for is everything that is not a booked amount — a unit price, a quantity, a rate — and `commodity_scu:` still round-trips. The rule now runs both ways: an account kept to whole dollars refuses `18.19` too, rather than rounding it to 18 and leaving GnuCash to park the difference in `Imbalance-CAD`.

**`export` refuses a whole book over one figure the format cannot write.** A split holding a sub-cent amount — `1.819 CAD`, which GnuCash's own GUI stores happily on an account kept to thousandths — makes `export`, `export --include-business-objects` and `export-beancount` refuse the entire book rather than write a file the importer would reject on the way back in (see the amount rule above). Every offender is named in one run, so the book is fixed in one pass rather than one export at a time.

There is no `--skip-unwritable`: a partial export is a ledger that silently omits transactions, which is the failure the refusal exists to prevent. That leaves `export` unable to get such a book out of GnuCash and into this format at all, and the remedy is to correct the amount in GnuCash. `delete-transactions` is the one command that proceeds anyway, because refusing there would leave no way to remove the offending transaction from inside this tool; it warns that no undo copy could be written.

**`print-invoice --format plaintext` and `print-bill --format plaintext` refuse the same figures the export refuses, and write nothing when they do.** A printed page carries the guids that make it re-importable, so its `payment:` block states an amount another book will act on — and the renderer used to round what the export refused, printing `amount: 30.00` for a settling split of 30.005 on a receivable kept to thousandths. One book, one figure, and the answer decided by which command you asked. Both now give the export's answer, and a run that refuses leaves no file behind: with `-o out/` the invoices and bills are all rendered before any of them is written, so the directory is either every invoice or none, never the ones up to the offender.

**`export-beancount` refuses a whole book over a split whose value the format cannot state.** Two shapes, both coming down to the same property: the figure after `@@` is a *cost*, and a posting's sign comes from its units.

- **A return of capital** — zero shares against real money, which GnuCash's own investment documentation prescribes and which GnuCash stores as amount 0 with a value. Beancount weighs a posting by its units times its cost, so nothing times anything is nothing and there is nowhere to put the money.
- **A value opposing its units** — `+10 HOOL` worth `−50.00 USD`, which GnuCash keeps across a save and reload. `10 HOOL @@ 50.00 USD` weighs +50.00 and `-10 HOOL @@ 50.00 USD` weighs −50.00, so no total states this: written unsigned it came back with the sign of its units, silently, because the importer rebuilds the value as `amount × (total / |amount|)`.

Written anyway, each posting would lose the only figure that matters, so the split is named and the export refused. Unlike the sub-cent amount above, neither is a mistake to correct — the book is right and the format cannot hold it. Export such a book as plaintext, which states the units and the value separately and signs each; `export --include-business-objects` is unaffected.

**The sharpest version of this is a currency whose unit GnuCash changed under you.** The rule reads the fraction GnuCash holds *now*, and GnuCash disagrees with itself across versions: the won is 1/100 before GnuCash 5.15 and whole units after. So a book with sub-unit KRW amounts, written when they were legal, has every one of those splits refused the day it is opened on 5.15 or later — by `export`, `export --include-business-objects` and `export-beancount` alike, and for the whole book rather than the split. Re-importing cannot buy it back either: an amount is judged against the coarser of the account's unit and the currency's, so declaring `fraction: 100` in the file does not restore it.

That is the rule working — those amounts genuinely cannot round-trip on a version that has no sub-unit won — but it reaches ledgers whose figures were correct when written, and the remedy (round each amount in GnuCash) is one the new version will not let you undo. If you keep a book in a currency GnuCash has restated, export it on the version you wrote it with before upgrading. The same applies to any ISO currency whose fraction changes in a future GnuCash release.

**A block that omits what it would destroy is refused rather than obeyed.** An invoice and a transaction are both rebuilt from their block, so a line missing from the file is a line removed from the book — which is what lets a split be deleted by deleting a line, and also what a file cut short by a failed write or a half-finished edit looks like. Three shapes are now refused where they previously went through:

- an invoice or bill block with no `entry:` lines, against an invoice that has some — `INV-001 has no lines in this file and 1 in the book … would unpost it and leave it empty`;
- a transaction block with no split lines under `--strategy update`, against a transaction that has some — `has no splits in this file and 2 in the book … would leave it with no money in it`. This one previously rebuilt the transaction empty, and the transaction was then gone from the book entirely;
- `currency:` differing from what the book holds for an existing customer, vendor, invoice or bill — `C-001 is in CAD in this book and the file says USD`. Previously reported as `unchanged`, so the file and the book disagreed with no word said.

Each names the count on both sides, so a truncated file is distinguishable from a deliberate emptying. To empty an invoice deliberately, state the block without the lines you are removing; to leave it alone, remove the block from the file.

**Other refusals that reach ledgers which imported before.** Each replaces a silent wrong answer:

- **`tax_table:` naming a table the book does not hold** is refused. It used to be skipped in silence, so the invoice posted with no tax — and because a re-import then found the invoice differing from its file, it unposted and reposted it on every run.
- **A `commodity` in the `CURRENCY` namespace that is not ISO 4217** is refused. It previously "succeeded" and left a book GnuCash could not load.
- **A `fraction:` a file declares for an ISO currency no longer loosens the amount rule.** The declaration is still applied, so a book carried between two GnuCash versions stays the book it was — the yen and the won are shipped differently across supported distros. But GnuCash writes an ISO currency by code and looks its fraction up again when reading the book back, so a *finer* one lasts only as long as the import, and a booked amount is now judged against what the book will still hold afterwards. `fraction: 1000` for CAD beside `Expenses:Fuel 1.819 CAD` previously imported with `Errors: 0`; reopened, CAD was a hundredth again, the split was sub-cent, and `export` refused the whole book with nothing inside this tool able to correct it. That file is now refused at the amount, naming the figure. To keep a finer unit, put it on the account with `commodity_scu:`, which round-trips.
- **`prepayment:` on a `payment:` block must equal what the payment actually leaves.** `prepayment: 50` against a payment leaving 100.00 imported with `Errors: 0`, and the next export wrote `prepayment: 100.00` back over it.
- **A `txn_guid:` that matches nothing, on a block describing money the book already holds**, is refused instead of paying twice. A guid that resolves to nothing has two readings the block cannot tell apart — an invoice being rebuilt into a fresh book, where the bank transaction genuinely is not there, and a retarget against the book that holds it, where the guid is simply a typo. The first must go through, because `print-invoice` names the transactions so the same book relinks rather than paying twice and a printed file has to be readable elsewhere; the second used to mint a second payment for money that had moved once, note it on stderr, and exit 0. What separates them is the book: the block's own date, amount, direction, account and memo are compared against what is there. A rebuild into a book that never held the money matches nothing and is unaffected. The refusal names the transaction it found — with its guid, and with the invoice that money already settles — so the remedy is either to correct the guid to it or to drop `txn_guid:`, which the message says.

  Two invoices and bills can describe the same movement in every field a block carries, and then the file says nothing that tells them apart, so the refusal fires on the second: one customer with two invoices for the same figure, paid on the same day into the same account, with the same memo on both bank lines. Give the second payment its own `memo:` — which is what a memo is for — and both import. Across two *different* owners it never fires, because correcting the guid there is not an operation at all: one customer's receipt cannot settle another's invoice.
- **`--include-business-objects` over a file the parser cannot read** is refused outright, and with `--new` the book it created is removed. Before, the run reported the parse error and saved whatever the business-object pre-pass had already made.
- **`find-transactions --amount` matches exactly**, where it used to be read as a float and matched within half a cent: on a fund account kept to thousandths, a search for 12.345 returned 12.346 and everything from 12.341 to 12.349 with it. **`--date` is validated** by the same callback every other command uses — `--date 3/2/2026` used to report no matches and exit 0, and is now `Date must be in YYYY-MM-DD format, got: 3/2/2026`.

With `--include-business-objects` the save is all-or-nothing, so any of these firing on the second invoice discards standalone transactions that imported fine earlier in the same file. That is not new, but there are more ways to reach it.

**`import-beancount` refuses files it used to read.** Hand-editing an export is the reason this format exists, so these are ordinary shapes to arrive at, and each previously produced a book that did not say what the file did. They fall into two groups by what they cost.

*The file is refused whole*, because the parser cannot get past the line and reading on would mean guessing:

- **a posting line it cannot read**, and **a posting that lost its indentation** — both previously dropped in silence, so the transaction imported with a split missing and GnuCash balanced the remainder into `Imbalance`. A posting whose amount is left out for beancount to infer is refused by the same message: this reads figures, it does not work them out;
- **`{}`**, which asks for the cost to be inferred from the lots the account already holds, and **a total stated against no units** (`0 HOOL @@ 50.00 CAD`), which beancount weighs as nothing times anything;
- **an amount, cost or rate that is not a number**, and **a date that does not exist** (`2026-02-30`) — previously a bare `ValueError` naming neither the file nor the line;
- **`open` with no currency constraint**, naming the line. Beancount leaves it optional and reads it as *any* currency; a GnuCash account is kept in exactly one, so there is nothing to write. It previously surfaced three directives later as `Cannot find commodity (CURRENCY, )` — a complaint about a commodity, on a line that names none. A trailing `;` comment on an `open` or a `commodity` is also a comment now, where before it was read as the currency itself;
- **a `gnucash-name` that names nothing** — empty, or ending in a `:` so one part of the path is blank.

*The object is refused and the rest of the file still imports* — the run reports the failure and exits 1, and, as before, saves nothing when anything failed:

- **a posting in a commodity its account does not hold**. The commodity on the posting line was read for the entry's currency and then never asked about again, so `Assets:Bank 50.00 USD` on a CAD account booked 50.00 CAD;
- **a posting in a different commodity from its transaction that says nothing about what it is worth in it** — previously valued at its own figure, leaving GnuCash to invent an `Imbalance` split;
- **a rate stated in a third commodity, or in shares**. A split's value is in the transaction's currency, so the rate has to be too: 15,000 yen quoted per USD inside a CAD entry was valued at 100.00 CAD instead of 135.00, and an exchange ratio (`-100 OLDCO @ 0.5 NEWCO`) valued the shares given up at 50.00 CAD — a figure with no source in the file;
- **a transfer in kind with no posting in a currency**. The only thing left to denominate the entry in is a security, and GnuCash does not keep such a transaction past a save: measured, it read back in the book's own currency with the units gone;
- **an amount finer than the unit its account is kept to** — `12.3456` on a thousandths fund account was stored as 12.346 with `Errors: 0`. This is the same rule the plaintext importer applies, through the same judge, so which format the reader edited no longer decides the answer;
- **a `commodity` in the `CURRENCY` namespace that is not ISO 4217**, as in plaintext above.

**`export-beancount` writes a different file, still valid beancount.** Two changes reach anything consuming that output outside this tool:

- a converted posting states its **total, in the transaction's currency** — `Assets:Bank:JPY 2000000 JPY @@ 18200.01 CAD` — rather than a per-unit `@ 0.00910001 CAD`. A rate is a division, so a per-unit figure has to be multiplied back to get the money, and at the eight places the exporter wrote it that error passes half a cent once the amount reaches about a million: ¥2,000,000 worth 18,200.01 CAD came back a cent out while its counterpart split came back exact, and GnuCash parked the difference in an `Imbalance` split. `@@` states the figure the book holds, so nothing is reconstructed;
- accounts kept to a finer unit than their currency carry `gnucash-scu: "1000"`, which is what lets `import-beancount` rebuild the account rather than silently coarsening it.

The round trip is tested both ways. A reader that parsed the old `@` form needs to handle `@@`, which beancount itself treats as the same fact stated differently.

**A printed page now carries the guids that make it re-importable.** `print-invoice`/`print-bill --format plaintext` emit `posted_txn_guid:`, and on each payment `txn_guid:`, `txn_split_guid:` and `num:`, where they previously emitted a date, an amount, an account and a memo and said so in a comment: *"the rendered file is for human consumption, not re-importing full lot structure."* That turned out to be the wrong half of the trade — a printed page read into the book it came from paid every invoice a second time, because nothing in it named the money that had already moved.

So it names it, and **the guids of your book travel with any invoice you hand to someone else**. They are opaque identifiers of transactions in your ledger, not figures, and they resolve to nothing in any other book — but they are there, and a reader sending invoices and bills outside the company should know it. In exchange the invoice is a ledger: read back into its own book it relinks rather than paying twice, and read into a fresh one it rebuilds the invoice and the payments it can describe.

A printed payment now also states `prepayment:`, the residue an overpayment leaves on the owner's account, which only the ledger export used to write. Without it a printed 250.00 deposit against a 100.00 invoice was rebuilt as a 100.00 payment — the bank short by 150.00, the customer's credit never created, and the run exiting 0. On a block that names a transaction, `amount:` is this invoice's own slice and `prepayment:` what the movement left over, so rebuilding one makes the whole movement; a block naming no transaction still reads `amount:` as the payment to make, unchanged.

The one thing a printed page cannot describe is the rate a **converting** payment settled at — a USD invoice paid into an HKD bank moved two figures and the page carries one. Read back into its own book the guids resolve and no rate is needed; read into a book that never held the settlement, it is refused by name and pointed at `settled_amount:`, rather than settled at a guess.

What a printed page no longer carries is **custom slot keys** — the arbitrary metadata a book may hold against a customer, vendor or invoice, which is internal and was being printed on the page. The owner's address is emitted instead, which is what an invoice is meant to show.

**`export --include-business-objects` states what it used to drop.** A `vendor` block carries `addr1:`…`email:` and a `bill` block carries `billing_id:` and `notes:`, both of which the customer and invoice blocks always had. A vendor's address and a bill's notes previously survived an import and vanished on the way back out, so a round trip through this format lost them.

**Other things a run says that it did not say before.** `fx-balances --verify-costs` also checks each currency as a whole — what its cost bases hold between them against what arrived less what was sold — and warns, naming the currency, both figures and the difference. It is a warning and not a refusal: the book is readable, and it is the book that needs looking at. And a book that will not open is answered in words rather than a traceback: GnuCash reports every such state as `call to begin resulted in the following errors, ERR_BACKEND_LOCKED`, which now reads as *"The book is locked, which means GnuCash has it open"* with what to do about it, and likewise for a read-only directory and for a path that is not a GnuCash XML book at all. A book open in GnuCash is the commonest situation there is, and it used to meet every command in this tool as a traceback with no message.

### Multi-currency: a third currency is supported and tested

An invoice in one currency settled into a bank in another — a USD invoice paid into an HKD account, a CAD invoice paid into one — is tested end to end, along with spending what such a settlement brought in. `--fx-rates` must carry the **bank's** currency as well as the invoice's: the CAD value of what landed cannot be derived from the invoice's rate alone, and a file missing it is refused by name rather than settled at a guess. `docs/multi-currency.md` previously said a third currency was untested and unclaimed; that is no longer true.

## v0.3.3 - Payment workflows, statement import, business-object round-trip hardening (2026-05-20)

This release closes the round-trip story for invoices, bills, and payments, and adds an end-to-end pipeline for reconciling raw bank statements into import-ready plaintext. Two months of bug fixes, format extensions, and new CLI subcommands.

### Payment workflows

Posted invoices and bills now accept incremental edits via re-import: append a `payment:` block to a posted record, re-import, and only the new payment is applied — the posting transaction, every entry, and the original bank-side payment transactions on the lot keep their GUIDs. Overpayments create an AR/AP credit lot for the owner; subsequent invoices/bills can consume the credit by setting `auto_apply_credit: true`. ([Q-015](docs/issues/Q-015-incremental-payment-reimport-rebuilds-destructively.md))

Single-invoice payment retarget and multi-invoice shared bank transactions now round-trip cleanly: both the bank-side transaction and the invoice's payment block emit the full transaction GUID plus per-split GUIDs, and the importer processes standalone transactions before business objects so `payment: txn_guid:` resolves on the first pass. ([Q-016](docs/issues/Q-016-full-guid-emission-and-import-order-for-payment-roundtrip.md))

```bash
# Append a payment to a posted invoice
$EDITOR ledger.txt   # add another payment: { ... } block
gnucash-plaintext import mybook.gnucash ledger.txt --include-business-objects
```

### New CLI subcommands

- `unpost-invoices` / `unpost-bills`: unpost without re-import. Warns about bank-side payment transactions that would become orphan if their lot is unposted. ([Q-014](docs/issues/Q-014-orphan-payment-warning-on-unpost.md))
- `delete-invoices` / `delete-bills`: remove unposted invoices and bills from the book (refuses posted records — unpost first). ([Q-013](docs/issues/Q-013-delete-unposted-invoice-bill.md))
- `find-orphan-payments`: list bank-side payment transactions whose AR/AP lot is no longer attached to any invoice or bill. Read-only.
- `find-prepayments`: list open AR/AP credit lots not yet consumed by an invoice or bill. Read-only.
- `find-transactions`: search transactions by account, date, or description.
- `delete-customers` / `archive-customers` / `archive-vendors`: retire owners by ID or `--by-guid`. Archive flips the `active` flag; delete refuses owners with open invoices, bills, or payments. ([F-011](docs/issues/F-011-customer-active-delete.md), [Q-007](docs/issues/Q-007-delete-archive-by-guid.md))

### Statement import pipeline

A four-stage pipeline takes a raw bank statement (CSV / OFX / QFX provider) through reconciliation against the book and produces an import-ready plaintext file with categorized splits.

1. `StatementProvider` — adapter protocol for statement sources.
2. `StatementReconciler` — matches statement rows against existing transactions in the book (by date + amount + memo signature).
3. `ReconcilePreviewWriter` / `ReconcilePreviewReader` — human-editable preview file lists matches, ambiguous rows, and unmatched rows.
4. `GnuCashFuzzyMatcher` + `ReadyToImportWriter` — suggests counter-accounts from history and emits import-ready plaintext.

See [docs/statement-import-pipeline.md](docs/statement-import-pipeline.md) and [docs/bank-import-workflow.md](docs/bank-import-workflow.md). ([F-005](docs/issues/F-005-data-models-and-provider-protocol.md)..[F-009](docs/issues/F-009-ready-to-import-writer.md))

### print-invoice: plaintext output and multi-invoice selection

`print-invoice` gained a plaintext renderer with audit-friendly tax totals (subtotal, per-tax-table breakdown, total) suitable for `git diff` review of quarterly invoices. Multi-invoice selection by date range, customer, or glob produces either a combined PDF or one file per invoice. The `action:` field is now optional. ([Q-011](docs/issues/Q-011-invoice-action-optional-and-custom-template.md), [Q-017](docs/issues/Q-017-print-invoice-plaintext-format-and-multi-invoice.md))

```bash
# Plaintext, all Q1 2026 invoices for one customer
gnucash-plaintext print-invoice mybook.gnucash \
  --customer C001 --date-from 2026-01-01 --date-to 2026-03-31 \
  --format plaintext -o q1-acme.txt

# One PDF per invoice, into a directory
gnucash-plaintext print-invoice mybook.gnucash \
  --customer C001 --date-from 2026-01-01 --date-to 2026-03-31 \
  --format pdf -o q1-acme/
```

Also: `print-invoice` no longer crashes on unposted invoices. ([Q-012](docs/issues/Q-012-print-invoice-on-unposted-invoice-crashes.md))

### Printing into a directory no longer loses an invoice

`print-invoice` / `print-bill` with `-o dir/` name each file after its invoice, and an invoice's id is free text.

**Before:** the id was used verbatim as the file name. Two invoices sharing an id produced **one** file — the second overwrote the first — while the run reported `✓ Wrote 2 invoice(s)`; GnuCash does not require ids to be unique and both of them survive a save and reload, so this was reachable in an ordinary book. An id holding a separator, such as `2026/001`, addressed a directory that did not exist and the run died with a `FileNotFoundError` traceback, having rendered every invoice and written none.

**Now:** a separator is written as `-` (`2026-001.pdf`, in the directory you named, and nothing can address a path outside it), and a repeated id takes the invoice's guid — `<id>_<guid>.pdf` on **both** of the two sharing it, so neither is the one that quietly kept the plain name. An id that is unique and path-free names its file exactly as before, which is nearly all of them.

### A book says how its dates are written

The `company` directive takes **`date_format`**, an `strftime` format saying how dates are written on the invoices and bills this tool prints.

```
company
  name: "Maple Leaf Widgets Inc."
  date_format: "%Y-%m-%d"
```

**Before:** nothing in a ledger could say. A printed page took its own posted and due dates from a GnuCash book option — one no command here could write, so the only way to set it was the GnuCash GUI, on every machine that prints, and an export and re-import lost it. Every other date on the page — each entry's, each payment's, "printed on" — came from a process-wide setting that GnuCash's GUI fills in at startup and a command-line process never does, so those followed the locale of whoever ran the command. Two people printing one invoice got two differently-dated invoices and bills, and a page could carry two date formats at once.

**Now:** the ledger says it once and both follow. `date_format` writes the book option *and* sets the process-wide format, so an invoice printed on any machine reads the same way throughout. It exports with the rest of the `company` block and survives a round trip. `date_format: ""` clears it, and the book goes back to being dated by the machine.

**Four formats match exactly** — `%Y-%m-%d`, `%m/%d/%Y`, `%d/%m/%Y`, `%d.%m.%Y` — because the process-wide setting takes a style rather than a format string. Any other format still works on the invoice's own dates and **now warns** that the rest of the page cannot follow it, naming the four that can. `%d %B %Y` prints `09 March 2026` at the top and leaves the entry rows to the machine, which is a fine thing to choose and no longer a thing to discover.

Note that GnuCash's own Edit → Preferences → Date/Time never affected this command — it is read by the GnuCash GUI at startup, and `print-invoice` is not the GUI. Measured on 5.10: changing it changes nothing on the page. Reports of your own see the book's format too, through `gnc:options-fancy-date`. [docs/dates-on-printed-pages.md](docs/dates-on-printed-pages.md) is the worked guide — a runnable ledger, the page it prints, and what to do when your format is not one of the four. ([Q-037](docs/issues/Q-037-a-printed-page-is-dated-by-the-machine-that-printed-it.md))

### A printed invoice or bill is the page GnuCash prints

`print-invoice` and `print-bill` render through GnuCash's own **Printable Invoice** — the report its Print Invoice button uses — so an invoice carries GnuCash's heading, columns, totals and wording rather than a layout of this project's. Every supported version draws it, GnuCash 3.8 included: a Guile interpreter runs inside this process and is handed the book already open. ([Q-036](docs/issues/Q-036-printed-pages-were-not-gnucashs-own.md))

**Fixed: a foreign-currency invoice printed the wrong amount.** Take a USD 100.00 invoice posted to a CAD income account, in a book where the rate that day was 1.40.

- **Before:** the printed invoice said `USD 140.00`. That is the CAD figure — what the book valued the receivable at — with `USD` in front of it. The customer was asked for the wrong amount.
- **Now:** the printed invoice says `USD 100.00`, which is what the invoice is for.

The line items were always right; it was the subtotal, tax and amount due that were wrong, so the page disagreed with itself.

**Changed: `--template` is replaced by `--report` and `--report-file`.** The old flag took an XSLT stylesheet for this project's own renderer, which was a second implementation of the same invoice and carried the same currency defect as the first. Both it and that renderer are gone; scripts passing `--template` will need updating.

Customising the page is now choosing or writing a GnuCash report, which is what the page is:

```bash
# one of the five reports GnuCash ships: Printable Invoice (the default),
# Fancy Invoice, Easy Invoice, Tax Invoice, Australian Tax Invoice
print-invoice book.gnucash INV-001 -o inv.pdf --report "Fancy Invoice"

# or one you wrote, in the language GnuCash's own are written in
print-invoice book.gnucash INV-001 -o inv.pdf \
    --report-file my-invoice.scm --report "My Invoice"
```

`--report-file` loads a `.scm` before the report is looked up, so a file calling `gnc:define-report` is registered by the time `--report` names it — GnuCash's own extension point, and the same report works from GnuCash's GUI. `tests/fixtures/a_report_of_your_own.scm` is a minimal one to start from; the README section "Changing the page means changing the report that draws it" has the details.

**What the printed page itself gained, against the last release:**

- free text of your own — the book's `extra_text1:`, `extra_text2:` … lines under your company, and the customer's or vendor's own under theirs. One key is one printed line, printed exactly as written. No other custom key reaches the page;
- GnuCash's "Invoice in progress…" on an unposted invoice, in place of this project's DRAFT badge and "figures are provisional" caption.

**What it lost:**

- the per-line **Tax Applied** column, which named each line's tax table (`GST 5% + PST 7%`, or `Exempt`). GnuCash's page marks a line `T` in a `Taxable` column instead, and names each tax with its own amount in the totals below;
- an unposted invoice's `due_date:` — GnuCash takes an invoice's dates from its posting, so an unposted one shows none. The key still round-trips through the format, and a report of your own can print it.

**What it kept** — worth saying, because these are what a filer checks for: the GST and each PST registration number, the seller's `contact:`, the invoice's `notes:`, and the tax named per account with its own amount. The old page carried all four and so does this one; two of them are GnuCash rows this tool switches on, because it ships them off.

Everything else on the page is GnuCash's own wording, columns and totals rather than this project's.

### Text files are read and written as UTF-8, whatever the machine's locale says

Every file this tool reads or writes as text — ledgers, beancount files, printed pages, exported accounts, reports, the FX-rates YAML — now states UTF-8 explicitly. It used to take whatever `locale.getpreferredencoding()` answered, which is UTF-8 on a desktop and often ASCII in a container, a cron job or CI with no `LANG` set.

Nothing changes for you if your locale is a UTF-8 one, which is the usual case. If it is not, and your book names anybody outside plain ASCII, then **before** this release:

- `export` truncated the destination file to empty and *then* raised `UnicodeEncodeError`, leaving a 0-byte ledger where a good one had been;
- `import` refused a ledger naming a customer `Éditions Cliché` with `'ascii' codec can't decode byte 0xc3`;
- `validate` — with no `--report`, which is the usual form — failed outright on a *valid* book, because the warning it was printing named an account like `Income:Dépenses accessoires`;
- `print-invoice` and `print-bill` failed the same way as `export` for `--format html` and `--format plaintext`: the destination truncated, then the write raised. Under a Latin-1 locale they wrote Latin-1 bytes instead, into a page whose own `<meta charset>` says UTF-8 — mojibake in the browser, with nothing reporting a problem. And where the page got as far as being drawn, GnuCash had already replaced each character its locale could not hold with `?`, silently and with a zero exit.

**Now** all of them work, and `export` → `import` round-trips such a book unchanged.

Two spellings of the same destination also disagreed: on `export-transaction` and `delete-transactions`, `-o file.txt` wrote UTF-8 while `-o -` wrote whatever the locale gave. Both write UTF-8 now, on those two and on the print commands, which matters because `-o -` is the form piped back into `import`.

### Cash-basis invoice KVP

Invoices can be tagged `cash_basis: true` to identify revenue that should be reported on the payment date rather than the invoice date — for cash-basis tax filers (Canadian small business below the CRA threshold, US Schedule C, single-entity service consultancies). The flag is descriptive metadata stored as a KVP slot; it round-trips and does not change accounting behaviour. ([Q-018](docs/issues/Q-018-cash-basis-invoice-kvp.md))

Its companion `due_date:` — for an unposted cash-basis invoice, which has no posting to take a due date from — still round-trips, and no longer appears on the printed page: GnuCash's report takes an invoice's dates from its posting and draws an unposted one as "Invoice in progress…". Putting it back is a change to that report rather than a flag here, since this tool passes no layout of its own; see "Changing the page means changing the report that draws it" in the README.

### Business-object round-trip correctness

- Exported account-type short-forms (`A/Receivable`, `A/Payable`) no longer crash re-import. ([Q-003](docs/issues/Q-003-account-type-export-not-reimportable.md))
- Invoice payment blocks no longer create duplicate bank transactions when the same posted invoice is re-imported. ([Q-004](docs/issues/Q-004-payment-transaction-duplicates.md))
- Business-object IDs are enforced unique on re-import, and full GUIDs are exported so conflict detection works across export/import cycles. ([Q-006](docs/issues/Q-006-business-object-id-uniqueness-and-guid-export.md))
- Tax-table identity is enforced on import — re-importing a tax table with the same name no longer creates duplicates. ([Q-008](docs/issues/Q-008-taxtable-identity.md))
- Posted invoices and bills are now mutable via the unpost-rebuild-repost cycle the importer runs internally; `unchanged` status is reported strictly when no field differs. ([Q-010](docs/issues/Q-010-strict-updated-status-on-no-change-reimport.md))
- Import emits explicit create / update / unchanged / skip signals for every business object so re-imports are no longer silent. ([Q-009](docs/issues/Q-009-import-summary-business-objects.md))
- The `active` flag round-trips for customers and vendors. ([F-011](docs/issues/F-011-customer-active-delete.md))
- KVP custom-metadata round-trip is extended to every business-object type (was Transaction and Split only). ([F-010](docs/issues/F-010-kvp-metadata-all-object-types.md))
- Business objects imported into an existing file are now persisted correctly (a save-path regression that bypassed the repository layer).

### Error reporting

Import errors include the source directive's line number, the directive type, and a snippet of the offending block. Inconsistent CLI exception types were normalized to a single hierarchy. ([Q-005](docs/issues/Q-005-import-errors-no-context.md), [Q-001](docs/issues/Q-001-inconsistent-cli-exception-types.md))

### Platform support

- Ubuntu 26.04 LTS (GnuCash 5.14) added to the test matrix.
- Stale Windows scripts removed (Linux/macOS via Docker remains the supported development path).

### Security

- The `run` shim, which previously executed arbitrary scripts, is removed. ([S-001](docs/issues/S-001-run-command-executes-arbitrary-scripts.md))
- The broad `except Exception` in the gzip fallback path is narrowed to the specific exceptions GnuCash raises so real errors are no longer masked. ([S-002](docs/issues/S-002-broad-exception-in-gzip-fallback.md))

### Tests

Coverage expanded across services and use cases:

- Beancount round-trip data-fidelity tests.
- `update_transaction` covers duplicate-account splits (the "meal + tip" bug) and is no longer dropped by deduplication.
- Cross-currency split exports emit `@ price` annotations; multi-currency beancount export and close-books paths are now tested.
- Plaintext parser edge cases, KVP colon validation, FX-rates YAML error paths, invoice renderer, and `print-invoice` have dedicated test files.
- Disk-persistence tests for account-balance pricedb and close-books.
- Five-state scenario tests for bills (unposted, posted/unpaid, single full payment, two partials, two payments totalling full amount) plus contradiction-error tests.

### Documentation

- [docs/bank-import-workflow.md](docs/bank-import-workflow.md) — end-to-end walk-through of the statement reconciliation pipeline.
- [docs/invoice-payment-reconciliation.md](docs/invoice-payment-reconciliation.md) — invoice (Accounts Receivable) payment lifecycle, incremental edits, orphan recovery, prepayment consumption.
- [docs/bill-payment-reconciliation.md](docs/bill-payment-reconciliation.md) — vendor-bill (Accounts Payable) payments: partial payments, vendor credits, detecting paid/partial/overpaid state, and `unapply-payment` corrections.
- [docs/payment-manual-edit-behavior.md](docs/payment-manual-edit-behavior.md) — reference for what the importer does to a payment block under each kind of diff (entry change vs. payment-only change).
- [docs/research/2026-05-14-invoice-post-pay-unpost-cycle.md](docs/research/2026-05-14-invoice-post-pay-unpost-cycle.md) and [docs/post-mortems/2026-05-08-bill-postto-account-segfault.md](docs/post-mortems/2026-05-08-bill-postto-account-segfault.md) — research and post-mortem notes from this cycle.

---

## v0.3.2 - export-accounts command (2026-04-08)

### What's new

#### Export account structure without loading transactions

A new `export-accounts` command exports all accounts and commodities directly
from the book without scanning the transaction log. This is significantly
faster on large files when only the chart of accounts is needed.

```bash
gnucash-plaintext export-accounts mybook.gnucash accounts.txt
```

Use `--as-of` to stamp a specific date on every `open`/`commodity`
declaration (defaults to the file modification date):

```bash
gnucash-plaintext export-accounts mybook.gnucash accounts.txt --as-of 2024-01-01
```

---

## v0.3.1 - Bill payment bug fixes and test coverage (2026-04-02)

### Bug fixes

#### Bills now round-trip payments correctly

Three bugs in the bill import/export pipeline prevented vendor bill payments
from round-tripping:

1. **Importer used invoice-side Entry API for bills** — `import_bill` was
   calling `SetInvAccount`, `SetInvPrice`, `SetInvTaxable` instead of the
   bill-side equivalents (`SetBillAccount`, `SetBillPrice`, `SetBillTaxable`).
   This caused the AP posting split to have amount $0 and payments to land in
   the wrong GnuCash lot.

2. **Payment amount sign was wrong** — `bill.ApplyPayment(amount=+N)` created
   AP split = −N (wrong direction), so the payment split was placed in a new
   lot instead of the bill's posted lot and was invisible to the exporter.
   Fixed by passing a negated amount so GnuCash creates AP = +N (debit,
   reduces liability) and bank = −N (credit, money sent out).

3. **Exporter used invoice-side entry reader for bills** — `_export_bills` was
   calling `_format_inv_entry`, which reads invoice-side fields
   (`GetInvAccount`, `gncEntryGetInvPrice`). Added `_format_bill_entry` that
   uses the correct bill-side ctypes functions.

#### GnuCash behaviour: bill `taxable` field is always exported as `true`

GnuCash 5.x does not write `entry:b-taxable = false` to the XML file — the
field is omitted when false and defaulted to `true` on reload. Consequently,
exported bills always show `taxable: true` regardless of what was imported.
This is a GnuCash engine constraint, not a bug in this tool.

### Test coverage

Added dedicated bill state scenario tests in
`tests/integration/test_business_objects.py` covering all five states:
unposted, posted/unpaid, single full payment, two partial payments, and two
payments totalling full amount. Also added three contradiction-error tests for
bills (mirrors the existing invoice contradiction tests).

---

## v0.3.0 - Business Objects (2026-03-14)

### What's new

#### Import and export customers, vendors, tax tables, invoices, and bills

You can now round-trip GnuCash business objects through plaintext files:

```bash
gnucash-plaintext import --new mybook.gnucash ledger.txt --include-business-objects
gnucash-plaintext export mybook.gnucash ledger.txt --include-business-objects
```

Supported objects: `customer`, `vendor`, `taxtable`, `invoice` (with entries
and payments), `bill` (with entries and payments — see v0.3.1 for bug fixes).

Business objects use no date prefix in the plaintext format — they are master
data, not ledger events. GnuCash does not store a creation timestamp for
customers, vendors, or tax tables, so no meaningful date prefix exists.
Dates that belong to a record (e.g. `date_opened`) are declared as fields
inside the block.

#### Print invoices to PDF

Any posted invoice can be rendered to a PDF directly from the CLI:

```bash
gnucash-plaintext print-invoice mybook.gnucash --invoice-id INV-2026-001 -o invoice.pdf
```

The output was produced from `services/invoice.xslt`, which you could customise to match your company's branding. **Superseded:** a printed page is now GnuCash's own Printable Invoice, that stylesheet and the `--template` flag are gone, and what a page shows is what GnuCash shows — see "A printed invoice or bill is the page GnuCash prints" above.

### Platform support expanded

Ubuntu 22.04 (GnuCash 4.8) and Ubuntu 24.04 (GnuCash 5.5 — listed as 4.9 here
until the images were re-probed) are now fully supported and tested in CI.

Two bugs that caused segfaults on Ubuntu (but not Debian) were fixed:
- Missing `argtypes` caused ctypes to silently truncate 64-bit pointers to 32-bit
- Ubuntu loads GnuCash extensions with `RTLD_LOCAL`, so `CDLL(None)` could
  resolve symbols from the wrong library instance

On Ubuntu 22/24, `apt install weasyprint` only provides a CLI wrapper —
`import weasyprint` would fail. Fixed by installing weasyprint via pip.

### Bug fix

`create_account` was not idempotent: calling it twice for the same account
silently created duplicate children in GnuCash. Fixed with an existence check.

---

## v0.2.0 - Architecture Migration (2026-03-01)

**Major release** with complete architecture refactoring and new features.

### 🎉 Highlights

- **Unified CLI**: All functionality through single `gnucash-plaintext` command
- **GnuCash-Beancount Format**: Bidirectional conversion with zero data loss
- **Multi-Version Support**: Tested on GnuCash 3.8, 4.4, 4.13, 5.10
- **Comprehensive Testing**: 145 tests with 100% parity validation
- **Docker Development**: Cross-platform development environment

### ✨ New Features

#### 1. Bidirectional Beancount Conversion

Full round-trip conversion between GnuCash and beancount:

```bash
# Export to GnuCash-Beancount
gnucash-plaintext export-beancount mybook.gnucash output.beancount

# Import back to GnuCash
gnucash-plaintext import-beancount restored.gnucash output.beancount

# Full chain: Plaintext → GnuCash → Beancount → GnuCash → Plaintext
# All data preserved with zero loss
```

**Features:**
- Account name aliasing (spaces and special characters preserved via metadata)
- Complete GnuCash metadata preservation (GUIDs, types, placeholders, etc.)
- Strict validation (rejects standard beancount without metadata)
- Commodity symbol sanitization for beancount compatibility

See [docs/gnucash-beancount-format.md](docs/gnucash-beancount-format.md) for details.

#### 2. Ledger Validation

New `validate` command checks GnuCash file integrity:

```bash
# Full validation report
gnucash-plaintext validate mybook.gnucash

# Quick check (errors only)
gnucash-plaintext validate mybook.gnucash --quick

# Show statistics
gnucash-plaintext validate mybook.gnucash --stats
```

**Validates:**
- Account structure and types
- Transaction balance
- Commodity consistency
- Split reconciliation
- Date validity
- GUID uniqueness

#### 3. Conflict Resolution

Smart duplicate detection with resolution strategies:

```bash
# Skip conflicting transactions (default)
gnucash-plaintext import mybook.gnucash transactions.txt --strategy skip

# Keep existing on conflict
gnucash-plaintext import mybook.gnucash transactions.txt --strategy keep-existing

# Replace with incoming on conflict
gnucash-plaintext import mybook.gnucash transactions.txt --strategy keep-incoming
```

**Conflict detection:**
- By GUID (if present in plaintext)
- By transaction signature (date + accounts)
- Prevents accidental duplicates

#### 4. Dry Run Mode

Preview changes before applying:

```bash
gnucash-plaintext import mybook.gnucash transactions.txt --dry-run
gnucash-plaintext import-beancount output.gnucash input.beancount --dry-run
```

#### 5. Date Range and Account Filtering

Export specific subsets of data:

```bash
# Export date range
gnucash-plaintext export mybook.gnucash output.txt \
  --date-from 2024-01-01 --date-to 2024-12-31

# Export specific account
gnucash-plaintext export mybook.gnucash output.txt \
  --account "Assets:Bank"

# Also works with beancount export
gnucash-plaintext export-beancount mybook.gnucash output.beancount \
  --date-from 2024-01-01 --date-to 2024-12-31
```

**Note:** When filtering transactions, ALL commodities and ALL accounts are still exported (required for valid beancount).

### 🏗️ Architecture Changes

#### New Structure

```
gnucash-plaintext/
├── cli/                    # CLI commands
│   ├── main.py
│   ├── export_cmd.py
│   ├── import_cmd.py
│   ├── export_beancount_cmd.py
│   ├── import_beancount_cmd.py
│   ├── qfx_to_plaintext_cmd.py
│   └── validate_cmd.py
├── services/               # Business logic
│   ├── account_categorizer.py
│   ├── beancount_converter.py
│   ├── beancount_parser.py
│   ├── ledger_validator.py
│   ├── plaintext_formatter.py
│   ├── qfx_converter.py
│   └── transaction_matcher.py
├── use_cases/              # Orchestration
│   ├── export_beancount.py
│   ├── export_transactions.py
│   ├── import_beancount.py
│   ├── import_transactions.py
│   ├── qfx_to_plaintext.py
│   └── validate_ledger.py
├── infrastructure/         # I/O adapters
│   ├── gnucash/
│   │   ├── gnucash_importer.py
│   │   └── utils.py
│   ├── plaintext/
│   │   └── plaintext_parser.py
│   └── qfx/
│       └── qfx_parser.py
└── repositories/
    └── gnucash_repository.py
```

#### Benefits

- **Testability**: 145 tests with clear separation of concerns
- **Maintainability**: Single responsibility per module
- **Extensibility**: Easy to add new formats
- **Reusability**: Services can be composed in different ways

### 🔧 Improvements

#### Multi-Version GnuCash Support

Tested and working on:
- **Debian 13** (Python 3.12, GnuCash 5.10)
- **Debian 12** (Python 3.11, GnuCash 4.13)
- **Debian 11** (Python 3.9, GnuCash 4.4)
- **Ubuntu 20.04** (Python 3.8, GnuCash 3.8)

**Compatibility features:**
- Abstract version differences with try/except patterns
- Compatibility shims for SessionOpenMode, GetDocLink/GetAssociation
- No version checks - code adapts dynamically

#### Docker Development Environment

Cross-platform development with:
- VS Code Server at https://localhost:8765
- Live code sync
- Docker-in-Docker support (Linux/macOS/WSL2)
- Pre-installed GnuCash Python bindings
- Automated test scripts

```bash
# Start development environment
./scripts/dev-start.sh

# Run tests
./scripts/test.sh

# Test all versions
./scripts/test-all-versions.sh
```

#### Enhanced Test Coverage

- **139 tests** for core functionality
- **6 new tests** for beancount round-trip
- **100% parity** with legacy code
- **Multi-version testing** on 4 distributions
- **Integration tests** for full conversion chains

### 🚨 Breaking Changes

#### 1. Command Names

| Old | New |
|-----|-----|
| `python3 ledger.py <file> <output> --export` | `gnucash-plaintext export <file> <output>` |
| `python3 ledger.py <file> <input>` | `gnucash-plaintext import <file> <input>` |
| `python3 convert_qfx.py <qfx> <output>` | `gnucash-plaintext qfx-to-plaintext <qfx> <output>` |

#### 2. Python Version

- **Minimum**: Python 3.8+ (was 3.6+)
- **Reason**: Compatibility with Ubuntu 20.04 LTS

#### 3. Installation

Development now requires Docker:
```bash
./scripts/dev-start.sh
```

Production installation via pip (planned for future release).

### 📝 Migration Guide

See [MIGRATION.md](MIGRATION.md) for detailed upgrade instructions.

**Quick migration:**

Old:
```bash
python3 ledger.py mybook.gnucash transactions.txt
python3 convert_qfx.py input.qfx output.txt
```

New:
```bash
gnucash-plaintext import mybook.gnucash transactions.txt
gnucash-plaintext qfx-to-plaintext input.qfx output.txt
```

### 🐛 Bug Fixes

- Fixed commodity export to use ticker instead of mnemonic
- Fixed space handling in commodity symbols
- Fixed account name aliasing for spaces and special characters
- Fixed import to reuse GnuCashImporter infrastructure
- Fixed transaction signature matching for conflict detection

### 📚 Documentation

- **New**: [MIGRATION.md](MIGRATION.md) - Upgrade guide
- **New**: [docs/gnucash-beancount-format.md](docs/gnucash-beancount-format.md) - Format specification
- **Updated**: [README.md](README.md) - Comprehensive usage guide
- **Updated**: [scripts/README.md](scripts/README.md) - Development workflow

### 🔮 Future Plans

#### Phase 8: Close Books (Planned)

Year-end closing with multi-currency support:

```bash
# Close books per currency
gnucash-plaintext close-books mybook.gnucash --closing-date 2024-12-31

# Optional: Consolidate to book currency
gnucash-plaintext consolidate-equity mybook.gnucash --closing-date 2024-12-31
```

See [migration_plan.md](migration_plan.md) for details.

### 👏 Acknowledgments

- **GnuCash Team**: For the excellent Python bindings
- **Beancount Community**: For inspiration on plaintext accounting
- **Contributors**: Testing, feedback, and bug reports

### 📊 Statistics

- **Development Time**: 11.5 days (estimated 22-30 days, 48-62% ahead of schedule)
- **Tests**: 145 tests (was 17 legacy tests)
- **Code Removed**: 4,418 lines of legacy code
- **Code Added**: New clean architecture
- **Files Changed**: 35 files deleted, new structure added
- **Supported Versions**: 4 GnuCash versions (3.8, 4.4, 4.13, 5.10)

---

## Previous Releases

### v0.1.x - Initial Implementation

- Basic plaintext import/export
- QFX conversion
- Script-based interface
- Single GnuCash version support

**Note:** v0.1.x is no longer maintained. Please upgrade to v0.2.0.

---

**Full Changelog**: https://github.com/yourusername/gnucash-plaintext/compare/v0.1.0...v0.2.0
