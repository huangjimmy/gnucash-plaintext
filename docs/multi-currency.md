# Multi-currency: invoicing, billing, and holding foreign currency

The book reports in CAD. This guide is the worked reference for everything that happens when money is denominated in something else: invoicing a US customer, being billed by a US vendor, paying either across a currency boundary, holding the USD that results, and selling it.

Every figure below was produced by running the commands against a real GnuCash book — the transactions are copied out of `export` output, and the errors out of the importer.

**Scope.** Nothing in the design is specific to USD and CAD: a cost basis at a cost, identified by a split guid, works the same in whatever currency the book reports in. Most of the worked examples below are USD against a CAD book, because that is the shape a reader is likeliest to be holding.

**A third currency is covered.** An invoice in one currency settled into a bank in another — a USD invoice paid into an HKD account, a CAD invoice paid into one — is tested end to end, and so is spending what such a settlement brought in. Three currencies are in play there and each is priced separately: the invoice's, the bank's, and the CAD the book reports in. What that costs the author is one more rate — `--fx-rates` must carry the **bank's** currency as well as the invoice's, since the CAD value of what landed cannot be worked out from the invoice's rate alone, and a file missing it is refused by name rather than settled at a guess.

---

## The two balances

Two different quantities are called a balance here, and conflating them is the fastest way to get this wrong.

| | what it is | where it lives |
|---|---|---|
| **Account balance** | how much currency an account holds right now | GnuCash's own balance, `account-balance`, the balance sheet |
| **Cost basis balance** | how much of *one split's* currency, at *that split's* cost, has not yet been sold | the `cost_basis_balance:` KVP on that split, `fx-balances` |

They move independently. A USD invoice paid into a USD bank leaves the bank holding the money while the A/R split remains the cost basis that money carries. One bank account can hold currency from several cost bases at different costs. Their totals need not agree, and neither is derivable from the other.

---

## Cost bases

Every split that brings foreign currency into the book establishes a **cost basis**: so many units, at what they cost in CAD.

| how the currency arrives | the split that establishes the cost basis | what it cost |
|---|---|---|
| customer invoiced in USD | the invoice's A/R split, `+100.00 USD` | the CAD income booked against it |
| billed by a US vendor | the bill's A/P split, `−100.00 USD` | the CAD expense booked against it |
| USD bought with CAD | the receiving bank split, `+100.00 USD` | the CAD paid |
| USD borrowed | the receiving bank split, `+100.00 USD` | the CAD value of the liability written |
| customer overpays in USD | the credit left on A/R, `−100.00 USD`, in its own lot — unless the money landed in a USD account, which then holds it | what the payment converted at when it converted; what the record was carried at when it did not |
| paid a US vendor beyond the bill | the debit left on A/P, `+100.00 USD`, in its own lot | the same |

The **cost is not stored** where the transaction already carries it, which is nearly everywhere: it is `share_price` on the split itself when the transaction is in CAD, and on the CAD split facing it when the transaction is in the foreign currency. A stored cost that could have been read from the transaction is a second copy waiting to disagree with it. Only the cost basis balance is stored, as a KVP on the split, because it is the one fact the ledger does not already carry.

The exception is a transaction with no CAD figure anywhere in it — a USD invoice overpaid from a USD bank, where every split is USD and `share_price` describes a rate of 1. The overpaid credit is currency the book holds and owes back, so its cost is real all the same; with nothing converted there is no rate in the transaction to read, and the rate the record was carried at is the one the book knows. It is written on the split as `cost_basis_cost`, with its direction:

```
	Assets:Accounts Receivable USD -100.00 USD
		cost_basis_cost: "1.4 CAD/USD"
```

Where the payment *did* convert — 200 USD arriving as 274.00 CAD — nothing is stored: the credit's own value over its amount says 1.37, the rate the money actually came in at, and that is read rather than copied.

The transaction always outranks the stored cost, which is consulted only where the transaction states none. A copy can be stale, hand-edited, or left behind by a correction, and the ledger is what the book is: read first, a KVP saying 9.99 made a split that paid 135.00 CAD for 100.00 USD report 9.99, and `fx-balances`, every realized gain and the cost each later sale had to be valued at all followed it. Stating a cost on a split the transaction already prices is refused for the same reason.

**A cost basis balance is what the book still holds of that currency**, on that side of the sheet: what came in, less what each disposal that gave its guid drew down. Sum the balances of one currency's cost bases **on one side** and you have what the accounts on that side hold of it, on a book whose disposals each say which cost basis they came out of. The two sides are not added together: a liability's balance is stored as a positive number — a 1,000.00 USD loan carries `cost_basis_balance: "1000.00"` against the −1,000.00 USD its account owes — so adding held to owed gives what the book has passed through that currency rather than what it is left carrying, which is why the balance sheet states the two sides as separate keys. `fx-balances` prints each cost basis with its balance and what it cost; what the accounts themselves hold is on the balance sheet's own lines, and comparing the two is what `fx-balances --verify-costs` does not do.

Where they disagree, currency was spent without saying which cost basis it came out of, and what is left of the balance stands for money the book no longer has. Pricing it would state a gain on dollars that are gone, so `balance-sheet` does not: that currency keeps GnuCash's own revaluation instead, and the disagreement stays visible rather than being priced in. It is a defect in the book rather than in the statement.

**The working on the page is what shows it.** A currency measured from its cost bases states its arithmetic — `cost … at … worth … = …` — while one left to GnuCash states a commodity and an amount.

`fx-balances --verify-costs` will not find this one, though it finds a great deal else — see [its own section](#listing-what-is-held-fx-balances) for everything it does ask. Its per-currency question compares what a currency's cost bases hold between them against what the ledger says arrived, less what was sold *against a cost basis*. A disposal that gives no guid is on neither side of that subtraction, so the two sides agree while the money is gone. What it catches is a balance that moved without a sale; what it cannot catch is currency that left without one.

A bare `1.4` is refused: read the other way round it prices 100 USD at 71.43 CAD rather than 140.00, and the two readings are a factor of two apart at that rate. So is a cost on a CAD split, which holds no foreign currency to have one — both ways in, so the same file cannot mean two things. What is stored is the cost the money actually carries, not the rate it was quoted at: 45.00 USD at 1.405 CAD/USD reaches the cent as 63.23 CAD, so the stored cost is `6323/4500`, the same way `share_price` comes back as a value over an amount rather than as typed.

---

## Invoicing in USD

### Posting

An invoice posts only to an A/R account **in its own currency**. This is the rule GnuCash's own post dialog enforces — it builds the post-to picker from `gncOwnerGetCommoditiesList()`, so an account in another currency is never offered. That filter lives in the GUI; `gncInvoicePostToAccount` takes no exchange rate and validates nothing, so a tool driving the engine directly must enforce it:

```
$ gnucash-plaintext import --new book.gnucash usd-invoice.txt --include-business-objects --fx-rates rates.yaml
Error: invoice "INV-USD-BAD": invoice 'INV-USD-BAD' is in USD but A/R account
'Assets:Accounts Receivable' is in CAD — a record posts only to an A/R account
denominated in its own currency. Post it to a USD A/R account, or issue the
invoice in CAD.
```

Posting across the boundary is not merely unsupported, it is destructive: GnuCash writes the A/R split with amount `0.00` while the value carries the full total, so the transaction still balances and nothing downstream objects — but a lot closes when its splits' amounts sum to zero, so the lot closes the instant the invoice is posted. The invoice reads as settled on its own posting date, and a later payment finds no open lot to join.

### Revenue in CAD at the posting-date rate

The entry's income account is an ordinary CAD account. GnuCash values an entry whose account is in another currency from a price attached to the invoice itself — `gncInvoicePostAddSplit` looks the account's commodity up in the invoice's own price list and aborts the entire posting when it finds none (`Multiple commodities with no price`), writing nothing while still reporting the invoice created. So the rate is attached before posting, and it comes from `--fx-rates`:

```yaml
# rates.yaml — 1 USD = N CAD
USD/CAD:
  2026-01-05: 1.40
  2026-02-20: 1.37
```

```
2026-01-05 * "INV-USD-001" "Invoice INV-USD-001"
	currency.mnemonic: "USD"
	Assets:Accounts Receivable USD 100.00 USD
		action: "Invoice"
		cost_basis_balance: "100.00"
	Income:Sales -140.00 CAD
		account.commodity.mnemonic: "CAD"
		share_price: "10000/14000"
		value: "-100.00"
		action: "Invoice"
```

100.00 USD invoiced on a day quoted at 1.40 recognises **140.00 CAD** of revenue — the figure a CRA filing needs — and leaves an open A/R lot of 100.00 USD. The A/R split is now a cost basis: 100 USD at 1.40 CAD/USD.

**Which way round the rates read.** A `share_price:` is always *transaction currency per unit of the split's account commodity*, so on this CAD income split inside a USD transaction it is `10000/14000` = **0.714 USD/CAD** — the inverse of the 1.40 CAD/USD you gave in the rates file. That is GnuCash's own convention, not a restatement of your rate. `fx-balances` never shows it that way round: a cost there is always the book's currency per unit of the currency held, and is printed with its direction attached (`1.35 CAD/USD`), so nothing has to be inferred. A rate below 1 is not a sign of an inverted quote — `0.172 CAD/HKD` is simply what a Hong Kong dollar costs.

Importing that invoice without a rate is an error, naming the flag and the date, rather than a posting the engine silently abandons:

```
Error: invoice "INV-USD-001": invoice 'INV-USD-001' is in USD and books to a CAD
account, so posting it needs the USD/CAD rate on 2026-01-05 — pass --fx-rates <file>
```

A date earlier than every quote in the file is likewise an error rather than an extrapolation backwards:

```
Error: invoice "INV-USD-001": invoice 'INV-USD-001' posts on 2026-01-05 and books
to a CAD account: No USD rate on or before 2026-01-05; the earliest quote in the
rates file is 2026-06-01. Add a USD rate covering 2026-01-05 — rates are not
extrapolated backwards.
```

### Payment

A payment states its `amount:` in the record's own currency — `amount: 100` is 100 USD — so when the money lands in a CAD account something has to say what that side received. 100 USD could arrive as 137.00 CAD or 139.00. Write what the bank statement shows:

```
	payment:
		date: 2026-02-25
		amount: 100                 # 100.00 USD off the invoice
		account: "Assets:Bank"
		settled_amount: 137.00      # what the bank actually credited
		memo: "Payment for INV-USD-PAY"
		Income:FX Gain $residual$ CAD
```

`settled_amount:` is the form you usually have: a statement shows the deposit, not the rate the bank used. The rate is derived from it — 137.00 / 100 — and passed to `gncOwnerApplyPaymentSecs` as its `exch` argument, which is the parameter that made the old 1:1 default possible in the first place.

The same payment may instead state the rate directly, with `share_price:` meaning what it means on any split — one unit of the record's currency in units of the account's:

```
		share_price: "1.37"
```

Either one is required when the currencies differ; both are rejected when they match; and giving both is accepted only if they agree:

```
Error: invoice "INV-USD-PAY": payment declares settled_amount: 137.00 and
share_price: 1.39, but 100 USD at 1.39 is 139.00 CAD, not 137.00 — they must agree
```

The bank is credited what it actually gave — `Assets:Bank 137.00 CAD` — and the invoice reads as paid rather than orphaning the payment.

### What a settlement at another rate realizes

The revenue was recognised at 1.40; 137.00 CAD arrived. The 3.00 CAD difference is realized **on the settlement date**, and settling the receivable into CAD is a disposal of the USD it stood for. Both facts are recorded:

```
2026-02-25 * "US Customer"
	currency.mnemonic: "CAD"
	Assets:Bank 137.00 CAD
		action: "Payment"
	Income:FX Gain 3.00 CAD
	Assets:Accounts Receivable USD -100.00 USD
		share_price: "1.4000"
		value: "-140.00"
		action: "Payment"
		cost_basis_split_guid: "06498ad3598349c9a9c405537fdeb797"
```

The A/R side is valued at the **cost basis it settles** (140.00 CAD), not at the rate the money came in at, so the entry balances only once the difference is placed — here a 3.00 CAD loss, a debit on the FX account. The cost basis it names drops to `0.00` available: that USD has been converted and cannot be sold again.

Where it goes is said with a **split line** in the payment block — the same syntax a transaction uses, with `$residual$` taking whatever the rest of the entry leaves over. No key gives an account and nothing is configured anywhere:

```
	payment:
		…
		Income:FX Gain $residual$ CAD
```

**That line is the only one a payment block may carry.** The difference a settlement realizes is the one figure in the entry that nobody moved — it is what the rate did, and no bank statement has a line for it. Everything else in a payment did move money, with its own date and its own counterparty, and arrives as its own transaction like anything else a bank import brings in. A wire fee is a bank debit, so it is imported as one:

```
Error: split on 'Expenses:Bank Fees' in this invoice payment is not $residual$.
A payment block carries only the difference the settlement realizes — the one
figure in it that moved no money. Anything that did move money is its own
transaction, with its own date, and leaves the rate this settlement converted
at alone.
```

Nothing in that decides what the line *is*: an account is not a charge because of its name, and this tool never reads one that way. The only test is whether the line is `$residual$`.

The rate is why it matters and not only tidiness. A figure taken out of the settlement changes what the currency converted at: 274.00 CAD produced with 2.00 kept and 272.00 credited would price it at 272/200 rather than 1.37, so a payment that overpays would carry that 2.00 into the cost basis of the credit it leaves — where every later sale of that currency is measured against it. A fee is an expense, not a worse rate, which is the same rule `fx-balances` applies to a purchase stated in CAD: 40.00 USD bought for 54.00 CAD with a 2.70 fee costs 1.35, not 1.4175 — each split there is valued in CAD already, so its own value over its own amount is its cost and nothing beside it can move that.

One shape is not covered by it. Where a transaction is stated in the *foreign* currency, no split carries a CAD figure of its own except the CAD ones, and the rate has to come from those: their amounts added up, divided by what those amounts are worth added up. All of them, because reading whichever comes first makes the cost depend on split order. A CAD line converted at a different rate from the others therefore does move the result: `fx_two_base_splits_at_different_rates.txt` books revenue at 1.4 and a fee at 1.25 and the cost basis costs 25/18, or 1.3889. That is the aggregate of what the transaction actually did; the alternative is a coin toss between 1.4 and 1.25, which is worse. Write the fee as its own transaction and the question does not arise.

**And the residual lands in the profit and loss.** A realized difference is income when the book gained and an expense when it lost, so `$residual$` must post to an income or expense account. Sent to a bank or another asset the entry still balances — a residual absorbs whatever is left wherever it is put — and the difference never reaches the income statement, sitting in the balance sheet as though the money had merely moved. The account's type decides that, not its name.

The same rules as anywhere else apply: at most one `$residual$`, nothing for it to take is an error, and a split on an account in another currency is refused. (There is no amount to get wrong here — `$residual$` states none. The rule that a stated figure its currency cannot hold is refused rather than rounded applies where such a figure can be written, which is a transaction: see [Money, to the smallest unit its currency has](#money-to-the-smallest-unit-its-currency-has).)

Split lines belong to the converting settlement, which is the entry with a realized difference for them to sit in. A payment that settles in the record's own currency has no such entry, and one attached with `txn_guid:` already has its transaction, splits and all; carrying split lines there is refused rather than accepted-and-dropped:

```
Error: invoice "INV-CAD-FEE": this invoice payment carries 1 split line(s)
(Expenses:Bank Fees), but it settles in the invoice's own currency (CAD) and so
realizes nothing, so nothing would place them. Write the payment as an ordinary
transaction — where any number of splits is ordinary — and attach it with
`txn_guid:` / `txn_split_guid:`, or drop the split line(s) from the payment
block.
```

A settlement that realizes something with no split to take it is refused too:

```
Error: invoice "INV-USD-NOFX": settling this USD invoice into CAD realizes 3.00
CAD against the 1.4000 CAD/USD it was booked at — add a split to the payment
block saying where that belongs, e.g. `Income:FX Gain $residual$ CAD`
```

Left to GnuCash alone, none of this happens: `gncOwnerApplyPaymentSecs` values the A/R side at the settlement rate, the entry balances, and the 3.00 CAD simply vanishes — 140.00 CAD of revenue against 137.00 CAD of assets, with nothing recording the difference and the cost basis still claiming 100 USD available.

The bill side is the mirror, and the sign flips with it: a payable booked at 140.00 CAD settled with 137.00 CAD of cash writes `Income:FX Gain -3.00 CAD`, a **gain**, because less cash extinguished more liability.

The entry is written in the book's currency because that is the currency the gain is in. A split's value is stated in its transaction's currency, so a CAD gain cannot live inside a USD-denominated entry — and GnuCash 3.8 writes the payment in the record's currency where 4.x and later use the transfer account's. The importer states the currency and all three values explicitly, so the entry reads the same on every supported version.

### Two ways to write a converting payment

`settled_amount:` exists because a `payment:` block is not a transaction: it is an instruction to `gncOwnerApplyPaymentSecs`, which builds the transaction itself. The block carries one amount — in the record's currency — and an account name, so there is no second split in which to write what the other side received. An ordinary transaction needs no such field precisely because it states both numbers already, and `share_price` is then just `value / amount`.

If you would rather use only keys that already existed, write the settlement as an ordinary transaction and attach it, which is the Q-016 linking path:

```
2026-02-25 * "Acme pays INV-USD-001"
	guid: "…"
	currency.mnemonic: "CAD"
	Assets:Bank 137.00 CAD
	Assets:Accounts Receivable USD -100.00 USD
		share_price: "1.40"
		value: "-140.00"
		cost_basis_split_guid: "<the invoice's A/R split>"
	Income:FX Gain $residual$ CAD
```

```
	payment:
		date: 2026-02-25
		amount: 100
		account: "Assets:Bank"
		txn_guid: "…"
		txn_split_guid: "…"
		memo: "Payment for INV-USD-001"
```

Here both amounts are written out, so nothing is derived and no `settled_amount:` is needed. The trade-off is length against control: the payment block is a few lines and lets the engine build the entry, the written-out transaction is the whole entry in your hands.

Omitting both, or stating either where nothing converts, is refused:

```
Error: invoice "INV-USD-NORATE": this invoice is in USD but the payment settles
into 'Assets:Bank', which is in CAD — add `settled_amount:` to the payment block
stating how much CAD actually moved (or `share_price:` if you would rather state
the rate). Neither is looked up: only the payer knows what the payment actually
converted at.

Error: invoice "INV-USD-SAME": payment declares share_price: 1.37 but the invoice
and 'Assets:Bank:USD' are both in USD — there is nothing to convert
```

There is deliberately no fallback to a published rate. A payment records what actually happened; substituting a mid-market rate would book a plausible-but-wrong bank balance and invent a gain that never occurred — the same quiet wrongness as the 1:1 default it replaces.

A USD invoice paid into a **USD** bank needs no rate at all, and realizes nothing: both sides carry the same cost. The A/R split stays the cost basis of that 100 USD, still showing 100.00 available, and the bank split does **not** establish a second cost basis — the book holds 100 USD, not 200. The money has simply moved from the receivable to the bank, carrying its cost with it.

---

## Being billed in USD

Everything above holds in mirror. A bill posts only to an A/P account in its own currency:

```
Error: bill "BILL-USD-BAD": bill 'BILL-USD-BAD' is in USD but A/P account
'Liabilities:Accounts Payable' is in CAD — a record posts only to an A/P account
denominated in its own currency. Post it to a USD A/P account, or issue the bill
in CAD.
```

and books its expense in CAD at the posting-date rate, against a USD payable:

```
2026-01-05 * "BILL-USD-001" "Bill BILL-USD-001"
	currency.mnemonic: "USD"
	Expenses:Supplies 140.00 CAD
		account.commodity.mnemonic: "CAD"
		share_price: "10000/14000"
		value: "100.00"
		action: "Bill"
	Liabilities:Accounts Payable USD -100.00 USD
		action: "Bill"
		cost_basis_balance: "100.00"
```

The A/P split is a cost basis in exactly the way the invoice's A/R split is: 100 USD, at the 1.40 the expense was booked at. It is what you owe, at what it was recorded to cost you.

Paying it out of a CAD bank takes what the bank actually gave — `settled_amount: 137.00` writes `Assets:Bank -137.00 CAD` — and the same rules apply: one of `settled_amount:` / `share_price:` is required across currencies and refused within one. `settled_amount:` is always a positive figure; which way the money moves comes from the record, not from a sign.

### Settling a USD bill with USD cash

This is the case with **no CAD in it at all**, and it is why cost bases matter. A 100 USD payable booked at 1.40 settled with USD cash that cost 1.35 realizes 5.00 CAD, and the transaction does not balance without it:

```
2026-03-01 * "Pay US vendor with USD cash"
	currency.mnemonic: "CAD"
	Liabilities:Accounts Payable USD 100.00 USD
		share_price: "1.40"
		value: "140.00"
		cost_basis_split_guid: "598cc18c074b4e8784eea8a6373f1c02"
	Assets:Bank:USD -100.00 USD
		share_price: "1.35"
		value: "-135.00"
		cost_basis_split_guid: "a0941ac334c44a31ba0120a0493c931c"
	Income:FX Gain $residual$ CAD
```

which imports as `Income:FX Gain -5.00 CAD` — a 5.00 CAD gain, because a liability carried at 140.00 CAD was extinguished with cash that cost 135.00 CAD. Both cost bases fall to zero available. Two monetary items acquired on different dates at different rates is what creates the gap; no conversion to CAD is involved.

---

## Currency that arrives without an invoice

```
2026-01-10 * "Buy 100 USD at 1.35"
	currency.mnemonic: "CAD"
	Assets:Bank:USD 100.00 USD
		share_price: "1.35"
		value: "135.00"
	Assets:Bank -135.00 CAD

2026-01-20 * "Borrow 100 USD at 1.30"
	currency.mnemonic: "CAD"
	Assets:Bank:USD 100.00 USD
		share_price: "1.30"
		value: "130.00"
	Liabilities:Loan -130.00 CAD
```

Each receiving split establishes its own cost basis — 100 USD at 1.35 and 100 USD at 1.30 — and the bank account now holds 200 USD carrying two different costs. Two cost bases at the *same* cost also stay two: each split is its own cost basis, with its own cost basis balance.

Which of the two the transaction was — a purchase or a borrowing — is not asked and does not matter. The cost basis is written on the split that **received** the currency, and what the other side is never changes it: 100 USD arrived and it cost what the split says it cost, whether the CAD went out of a bank, off a claim on someone, or onto a loan.

### The rate you write is what opens the cost basis

A USD deposit whose other side is booked to a CAD account needs a `share_price:` on the USD split, or the transaction does not balance — and that rate is what says what the USD cost, so it opens a cost basis:

```
2026-08-13 * "Received money from a customer"
	currency.mnemonic: "CAD"
	Assets:Bank:USD 2720.00 USD
		share_price: "1.4029"
		value: "3815.89"
	Assets:Due from director -3815.89 CAD
```

That is correct for what it says. A USD asset is debited and a CAD asset is credited, which is buying USD; credit a CAD liability instead and it is borrowing USD. Either way the book gave up 3,815.89 CAD of value and holds 2,720.00 USD at a cost the transaction states. It is also a price you may not have meant to give, and the CAD account on the other side is what obliged you to give it.

**Nothing here reads what the other account is for.** `establishes_cost_basis` is given the split that received the USD and asks three things: is its commodity a currency other than CAD; is the split in the direction that increases that account's own balance (a debit on a bank, cash, asset, stock or receivable, a credit on a liability, payable or credit card); and can a cost be read. That last one has two branches, because a split's `value:` is stated in the transaction's own currency: where the transaction is denominated in CAD, `value:` over `amount:` is the cost; where it is denominated in a foreign currency, the same division gives a rate in that currency and it is converted using the splits on CAD accounts in that transaction — their CAD amounts added up, divided by what those amounts are worth added up, so the order the splits are in cannot change the answer. The other splits are read for the rate and for nothing else.

It could not read more. An account called "Due from director" is free text on an account of type Asset in CAD. GnuCash has no suspense or clearing account type, and `placeholder:` means an account that takes no transactions of its own. Nothing in the book marks such an account as a holding place. And nothing could: a director who really owes you 3,815.89 CAD and settles it by wiring 2,720.00 USD writes exactly these two lines, and there the cost basis is right. Guessing from account names is the only alternative, and it would refuse a cost basis to everyone who books real director loans there.

Book the other side to an account kept in the **same** currency and there is no rate to write:

```
2026-08-13 * "Received money from a customer"
	Assets:Bank:USD 2720.00 USD
	Assets:Due from director USD -2720.00 USD
```

No rate, no cost, no cost basis, and nothing to unwind when the deposit turns out to be an invoice's collection.

### A transaction that pays an invoice is not a borrowing

Link such a deposit to an invoice with `txn_guid:` and the invoice is paid in full. The transaction is neither a purchase nor a borrowing any more, so the cost basis the import opened is discarded — and it must be, or the same 2,720.00 USD has two cost bases: this one and the invoice's own posting split, which has had one since it was posted. The receivable is the single cost basis from then on, which is the state a `payment:` block reaches when it pays a foreign invoice in full from an account kept in the same currency.

Refused while a disposal already draws on the cost basis being discarded, and the refusal lists those disposals with their dates and amounts. The `share_price:` on the USD split and the rate the invoice was posted at need not agree — the invoice was posted on one day and the deposit entered at whatever rate the person entering it used — so a disposal valued against the first cannot be pointed at the second without silently re-pricing it. Delete those disposals, link the payment, and import them again measured against the invoice's cost basis.

**Refused too where the balance being discarded is below what the split brought in.** A balance a file states is authoritative, and it is how a book carrying sales this tool never saw gets one — so a deposit that brought in 2,720.00 USD and reads 2,000.00 has had 720.00 sold somewhere the book does not record. Discarding that balance destroys the only statement of the 720.00 there is: the split becomes a settlement, which is no cost basis, and taking the payment off later opens it at the whole 2,720.00, offering currency that is gone. The refusal gives both figures and their difference, and says to write `cost_basis_balance: ""` on that split first if the difference is not currency this book should account for.

A **bill** is the other way round, because that transaction is still a borrowing. Linking an expense transaction to a bill moves its expense split onto the payable, and the account the payment was funded from — a USD credit line, say — is a different obligation from the payable: the payable is paid and the credit line is still owed. So its cost basis is kept rather than discarded, by writing the price onto the split, and that USD goes on being sellable. The paid payable keeps its own balance too, exactly as a paid invoice's receivable does.

### Recovering a book linked by an earlier version

An earlier version replaced the split and left the balance behind: unlisted, unreadable, and still given by any disposal that had drawn on it. Such books exist. `--verify-costs` is what finds them, and it prints the split's guid:

```
    split guid         00e958a8d56547d484d7629000292dc3
    - this split stores cost_basis_balance: '2719.28', but it is no cost
      basis: nothing says what its currency cost: every split in its
      transaction is USD, so there is no CAD figure to divide, and no
      `cost_basis_cost` is stored on it either.
```

Which repair a book needs depends on whether anything drew on that cost basis before it was stranded.

**Nothing drew on it.** One file, and the balance comes off:

```
2026-08-13 * "Received money from a customer"
	guid: "15f40458487e434abd1d9a95c46a7041"
	…Chequing… 2720.00 USD
		guid: "00e958a8d56547d484d7629000292dc3"
		cost_basis_balance: ""
	Assets:Current assets:Accounts receivable:USD -2720.00 USD
```

`import --strategy update`. The receivable's posting split is then the single cost basis for that money, which is where the link should have left the book. Export the transaction and edit that one line rather than writing the block by hand, so the figures are the ones the book holds.

**Something drew on it** — a transfer fee spent out of the deposit, say. Re-pointing it at the receivable's cost basis in place is refused, because its transaction picks a cost basis:

```
Error: transaction <guid> touches a cost basis, so its amounts, values,
accounts, cost basis picks and the currency it is stated in cannot be edited
in place …
```

so it is deleted and written again, in three steps:

1. `delete-transactions <book> <fee-tx-guid> --by-guid -o fee.txt` — which gives the stranded cost basis back exactly what the fee took, and saves the transaction as plaintext so you have it;
2. clear the stranded balance as above;
3. import `fee.txt` with `cost_basis_split_guid:` changed to the receivable's cost basis — where the money it spent actually is.

The fee's value has to be what the receivable's cost basis costs times what it takes, as any disposal's does, so check it after the change rather than assuming: the deposit was entered at whatever rate its author used, and the invoice at its posting-date rate. Where the two differ the fee's `value:` changes with the cost basis it draws on.

Both routes end with `--verify-costs` clean and the account totals level, which is how you know the book is out of it.

**Or commit it as one transaction.** `import --atomic` applies the file and then reads the book it left, instead of checking each block as it is applied. It all commits or it all rolls back, and one cost-basis check is deferred to the end the way a database defers a constraint — the refusal to edit a transaction a cost basis rests on. It is deferred for a transaction that holds a cost basis, and for a disposal re-pointed at another one; a block that restates what a disposal takes, or drops the line giving its cost basis, is refused as it lands whether the flag is passed or not, because nothing on that path draws a cost basis down or gives one back. The other checks still run block by block. That is what the two-step method above exists to work around. What a rollback answers for is what the file introduces: the same questions are asked of the book before it is read, and a fault already there is not this file's to answer for. The repair is then three blocks stating one end state:

```
2026-07-31 * "INV-USD-001" …          the receivable's cost basis, at 2719.28
2026-08-13 * "Received money …"       the deposit, cost_basis_balance: ""
2026-08-13 * "Charges for: …"         the fee, cost_basis_split_guid: <the receivable's>
```

No order of those three is legal one at a time: clear the deposit first and the fee draws on a split that is no cost basis, re-point the fee first and it is refused before its figures are even read. Committed together they are fine, and the finished book is checked before anything is saved.

The receivable states **2719.28**, not 2720.00, because a stated balance is what that cost basis holds once the file has landed — net of the file's own disposals. State 2720.00 and nothing refuses it: the balance is inside what the cost basis brought in, which is what the finished book is asked, and the per-currency totals that would notice are a warning `--verify-costs` prints and refuses nothing over. The book then offers 0.72 USD the fee has already taken, and the listing goes on saying so.

### Prepayments, refunds, and the lot

A customer's overpayment is a borrowing: currency held and owed back, sellable like any other. A settlement is the same shape — both move a receivable against its normal direction, both are a credit of 100.00 USD — and what separates them is the **lot**. A settlement belongs to the invoice it settles; a prepayment belongs to a lot no invoice owns. Neither the direction nor the figures can tell them apart, which is why the lot decides.

A payment written as a `payment:` block gets that lot from the engine. A prepayment written as an ordinary transaction has to name its owner:

```
2026-02-01 * "Customer prepaid 100 USD, arriving as CAD"
	currency.mnemonic: "CAD"
	Assets:Bank 137.00 CAD
	Assets:Accounts Receivable USD -100.00 USD
		share_price: "1.37"
		value: "-137.00"
		lot_owner: "customer:C-US"
```

`fx-balances` lists that credit — 100.00 USD at 1.37 CAD/USD — even though no account in the book holds a USD balance: the bank took CAD, and the receivable is the only record of the currency owed.

**One lump of currency is listed once.** Where the money lands decides which split carries the cost basis, and the credit on a receivable is not automatically it:

| how the prepayment arrives | the cost basis is on | why |
|---|---|---|
| into a CAD bank (arrives converted) | the A/R credit, `−100.00 USD` | nothing else in the book holds that USD; the credit is the only record of it |
| into a USD bank, written by hand with CAD values | the bank split, `+100.00 USD` | the bank holds it and it is sellable from there; the credit facing it records the obligation |
| into a USD bank, paid on a USD invoice (`payment:` block) | the A/R credit, `−100.00 USD` | every split is USD, so none carries a base-currency figure to derive a cost from — the credit is the only one that can be given one, as `cost_basis_cost` |

`lot_owner:` says which side of a receivable a split is, not how much currency the book holds: adding it to a prepayment paid into a USD bank does not make the money two lumps. Counting both listed the same 100.00 USD twice and offered 200.00 for sale from a bank holding 100.

Without `lot_owner:`, a hand-written credit belongs to no lot, which is how a settlement looks, and it establishes nothing. That is deliberate rather than an oversight — the settlement of a USD invoice whose money arrives as CAD is written with exactly the same three lines:

```
2026-02-01 * "Customer settles, the money arriving as CAD"
	currency.mnemonic: "CAD"
	Assets:Bank 137.00 CAD
	Assets:Accounts Receivable USD -100.00 USD
		share_price: "1.37"
		value: "-137.00"
```

That receivable's cost basis was opened when the invoice was posted, so counting the credit as well would offer 200.00 USD from a book holding none.

**A refund is the mirror, and it needs `lot_owner:` for the same reason.** It is a debit on the receivable — the direction that normally establishes a cost basis — but it sends the customer's own money back rather than bringing any in. Naming the owner puts it in the lot no invoice owns, which is what marks it a refund, and it then establishes nothing; counting it because debits are the normal direction offered a third 100.00 USD that had already left the book.

Naming no owner, it is read as a receivable written by hand and does establish one — because that is the other thing those three lines are, exactly as a lot-less credit is read as a settlement. Neither side guesses: the file says which it is, or it gets the reading its shape gives it.

The payable side works the same way in reverse. What is owed to a vendor sits on the credit side and always establishes a cost basis; a **debit** on a payable is either money sent to settle a bill (establishes nothing — that currency has gone) or a prepayment to a vendor (a claim on them, which does). Again the lot decides, not the direction.

Prepaying a vendor out of USD the book already holds moves the cost basis across rather than adding one: the claim on the vendor is where that currency now is, and the bank split that sent it is a spend like any other, so it gives the guid of the cost basis it spends and that cost basis goes to zero. Written without giving one, nothing is drawn down and the listing keeps offering the bank's cost basis — 200.00 USD against 100.00 held — which is the same rule as any sale that gives no cost basis rather than an exception to it.

An update writes prepayments on the same terms: `lot_owner:` on a split an edit creates puts it in the owner's lot exactly as a fresh import would, and a split already in a lot keeps the one it has, so re-importing an exported prepayment over itself opens no second lot.

### Spending a credit on a later invoice

`auto_apply_credit: true` on an invoice pays it out of what the customer has already overpaid, and the cost basis follows what is left of that credit. GnuCash does not set the applied part aside: it reduces the credit's split to the part being spent and carves the rest into a new split of the same transaction, so 100.00 USD of credit meeting a 40.00 USD invoice becomes a 40.00 split and a 60.00 one.

The 60.00 is what the customer still holds and the book still owes, so it takes the cost the credit was acquired at — 1.4 CAD/USD, the figure already on the split it was carved from, not a fresh rate for a day on which nothing was bought. The 40.00 has become a settlement and holds nothing.

```
2026-02-25 * "US Customer"
	Assets:Accounts Receivable USD -40.00 USD
	Assets:Accounts Receivable USD -60.00 USD
		cost_basis_balance: "60.00"
		cost_basis_cost: "1.4 CAD/USD"
```

Rebuilding a payment, GnuCash copies the source split's stored figures onto every split it makes, so the settlement of the earlier invoice comes out of the engine claiming the credit's balance and cost as well. Those copies are taken off: three splits each offering 100.00 USD listed 200.00 that the book never held, and the 60.00 the customer had left was a prepayment with no cost at all — listed nowhere, and sellable not at all.

The payable side is the mirror. What the book overpaid a vendor is its own currency sitting with them, at what it cost to send, and a later bill spending 40.00 of it leaves 60.00 that is still the book's at that same cost.

Applying a credit is asked for with `auto_apply_credit: true` and nothing else. What the *export* then says is which credit settled the invoice, in a payment block that names it rather than a bank account — a block to read, not one to write:

```
	payment:
		amount: 40.00
		from_credit: true
		credit_dated: 2026-02-25
		txn_guid: "…"
		txn_split_guid: "…"
```

A credit bigger than the invoice is divided the way a bank transfer bigger than the invoice it pays has always been: the split the block gives settles what is owed, and the rest is parked as the owner's credit in a lot of its own, carrying what is left of the cost the credit was acquired at. Two shapes are refused rather than divided: a credit in no lot, since nothing records whose the leftover would be and every listing of credits reads lots (`lot_owner:` gives it an owner first), and a block on an invoice that owes nothing, since there is nothing left for the credit to settle.

`credit_dated:` is the day the currency arrived, not a day anything was paid — applying a credit writes no transaction, so the book has no date for it to state. That the split settled an invoice out of credit at all is recorded on it when the credit is applied (`applied_from_credit`), because nothing about the split afterwards distinguishes it from a bank payment's, and where a deposit is taken and an invoice posted against it the same day, not even the dates do. Re-importing that block attaches the same split to the same lot, which keeps the cost basis where the book put it; asking for the application again instead would let the engine choose a different credit, and re-applying one already applied leaves invoices whose lots GnuCash drops on load, taking their cost basis with them.

### Securities are not foreign currency

A cost basis is only ever established for a **currency**, and what decides that is the commodity the split holds — its namespace — not how its account is typed. Shares are counted in units and priced rather than converted, and a book holding them has no FX question to answer, so a security establishes nothing: testing "not the book's currency" alone swept them in, and a plain stock purchase in a single-currency book grew a cost-basis KVP, listed in `fx-balances` as `50 CAD/USTECH`, and could no longer be corrected with `--strategy update`.

The same rule read the other way: an account **typed** `Stock` or `Mutual Fund` but denominated in USD holds foreign currency, and its splits establish cost bases like any bank account's. Judging by account type instead left such a book reporting no cost basis at all with 100.00 USD in it.

---

## Listing what is held: `fx-balances`

```
$ gnucash-plaintext fx-balances book.gnucash
DATE         SPLIT GUID                         ACCOUNT                       COST     BROUGHT IN COST BASIS BALANCE
--------------------------------------------------------------------------------------------------------------------
2026-01-10   6b2d279090974d34b37da8b1a62abfd8   Assets:Bank:USD       1.35 CAD/USD     100.00 USD         100.00 USD
             Buy 100 USD at 1.35
2026-01-20   ab1df82af72741038ad02564b97eb625   Assets:Bank:USD        1.3 CAD/USD     100.00 USD         100.00 USD
             Borrow 100 USD at 1.30

Total USD cost basis balance: 200.00 USD
```

`--currency USD` narrows it; `--with-balance-only` hides exhausted cost bases. The listing is read-only and in no imposed order: a sale gives the guid of the cost basis it measures against, so no cost basis is ahead of another and sorting by date would suggest an order of consumption that does not exist. The split guid is the handle a sale uses, and the cost carries its own direction — CAD per unit of the currency held — so it is never a bare number to be interpreted.

**`none recorded`** in the cost basis balance column means this tool never wrote a balance for that cost basis — the split was made in the GnuCash GUI, or predates this feature. It is not read as "all of it left": how much has already been sold is not known, and assuming the full amount would re-open currency that may be long gone. Selling against such a cost basis is refused and it is left out of the totals.

**`--verify-costs`** asks whether the book agrees with itself. A cost is derived from the ledger and never asserted by this tool, so it is exactly as right as the ledger is consistent. Six things are checked, and each can fail:

| checked | what a failure means |
|---|---|
| a cost basis balance is not above what its cost basis brought in, and not below zero, and reads as a number at all | a balance moves only by what a sale takes and what one gives back — so a balance above what arrived is currency offered that never did, and one below zero is a sale no ledger records. Two exact comparisons against figures the book holds, with no tolerance in them. A balance that will not parse lists as `none recorded`, because nothing can be sold against it either way — but it is not the same as never having had one, so `--verify-costs` reports it with the text it actually holds rather than passing over it |
| a stored `cost_basis_cost` parses, and agrees with the transaction | nothing writes one where the transaction states a cost, so both means a copy has drifted — and the transaction is what is used |
| no split stores a `cost_basis_balance:` while being no cost basis | the fault hardest to notice. The listing walks the cost bases, so a figure on a split that is not one never appears there; the two checks above walk the same cost bases, so they call the book sound; and the export writes the key back out, so a book rebuilt from this one's ledger holds the same figure in the same place — the fault travels rather than being cleared, and only `cost_basis_balance: ""` on that split takes it off. The finding says *why* the split is not a cost basis — its currency is the book's own, it spends rather than brings in, it picks another cost basis, or nothing in its transaction says what its currency cost. A stored `cost_basis_cost` in the same place is **not** reported: the export drops it, so it neither travels nor round-trips |
| no disposal gives a `cost_basis_split_guid:` that matches a split which is no cost basis, or no split at all | the other half of the one above, and what survives it being fixed. Clearing a stranded balance leaves the sale below it still giving that guid, and then no figure is stored anywhere wrong, so every check above passes while a sale is measured against something that is not a cost basis. The export writes the guid, and re-importing that ledger is refused — so a book whose own export cannot rebuild it would otherwise read as sound. A cost basis the book **consumed** is not reported: an owner's credit spent on their next invoice or bill ends the pool it was, and the sale that drew on it beforehand goes on giving its guid, which is the book's record of where that currency came from. The file does not carry it — the export leaves it out, the way it leaves out a `cost_basis_cost` on a split that is no cost basis — so the ledger rebuilds the book without a line the import would refuse |
| every disposal that *does* give a cost basis draws on one holding the currency it sells | a cost basis is a pool of one currency and a sale takes units out of it, so the two have to agree or the subtraction means nothing — 10.00 USD taken out of a pool of euros. `_validate_pick` refuses this of a sale in a file, and an `--atomic` run may re-point a disposal in place: the figures do not move, so the deferred guard passes it, and nothing on the update path draws a cost basis down and looks. Where the two cost bases cost the same figure, the valuation row below has nothing to say about it either |
| every disposal that *does* give a cost basis is still valued at what that cost basis cost, and the receivable it draws on has been collected | the two questions `_validate_pick` asks of a sale in a file, asked of the sales already in the book — which is the only way either is asked of a sale nobody is importing. `import --atomic` defers the guard that otherwise stops a block restating a cost basis transaction's `value:`, and on the update path that guard was standing in for both: `update_transaction` never draws down a cost basis, so `_validate_pick` runs on the create path alone. A cost basis moved from 1.40 to 1.50 under a 10.00 USD fee valued at 14.00 CAD passes every other check, and so does 40.00 USD sold against an invoice the customer has not paid. `cost_basis_force: true` on the sale is the deliberate override of the collected question — the valuation one does not read it and never has — and a sale carrying it is not reported for selling against an uncollected receivable |

All six are questions about one split. A book can pass every one of them and still not add up, so the run also asks a book-wide one.

It is asked **per currency**: what a currency's cost bases hold between them, against what the ledger says arrived less what was sold against a cost basis.

The two sides are written by different mechanisms — a KVP on each split, and the transactions themselves — so they can disagree, and neither is derived from the other. Take 80.00 USD off one cost basis of a book holding 200.00 and record no sale: every cost basis is still within its own bounds, `--verify-costs` says every cost agrees with the figures it is derived from, and 80.00 USD is accounted for by nothing.

```
warning: the USD cost bases hold 120.00 USD between them, and the ledger says
200.00 USD arrived and 0.00 USD was sold against a cost basis — leaving 200.00 USD.
  80.00 USD is accounted for by no cost basis. A balance was lowered without a sale
  to lower it, or a sale gave back less than it took.
  Nothing is refused: every cost basis is within its own bounds, and which side is
  right is not something the book records.
```

**A warning, and it does not set the exit code.** The book is readable and its figures are the ones it holds; what put the two sides out of step is not recorded anywhere, so the reader is the one who can say which is right. Both totals are printed rather than the difference alone, because the difference does not say where to look: short means a cost basis lost its balance, over means one gained currency that never arrived.

**What is not compared is the cost bases against the account balances.** It is the obvious next check and it does not work: an account may hold less than its cost bases offer and be perfectly correct, because a cost basis is lowered only by a disposal that gives its guid. An account that received 60.00 USD and paid an 8.00 USD fee out of the same transaction holds 52.00 and offers 60.00. A check on that reports ordinary books, so there is none.

A cost basis with **no balance recorded** is left out of both sides. How much of it is unsold is not known — that is what `none recorded` means — so counting what it brought in would report every such book as holding exactly that much less than arrived; nothing can be sold against one either, so no sale goes missing with it.

Both per-basis checks are exact questions about figures the ledger states. Two inexact ones are deliberately **not** asked:

A split's `share_price` against its value. GnuCash stores no rate — `xaccSplitGetSharePrice` divides value by amount on demand — so the two are one number and comparing them always agrees. A check that cannot fail is worse than none: it reports agreement it never tested.

Whether a transaction's base-currency splits agree about its rate. **Rates run forward only.** A file states 1.405, 45.00 USD becomes 63.23 CAD, and the effective rate the ledger carries is then 6323/4500 — 1.405 plus 1/9000. That is the rounding working as it must, and reading the figure back to ask which rate produced it has no answer: many rates give 63.23, and the one the file stated is not among the things a book keeps. Every criterion tried in that direction reported correct books, so the rate the base-currency splits add up to is used to derive a cost, and nothing is inferred from it.

The run covers the whole book and exits 1 at the end if anything disagreed, rather than stopping at the first, and a cost basis whose own figures do not parse is reported with its traceback instead of ending the pass:

```
$ gnucash-plaintext fx-balances book.gnucash --verify-costs
…the listing…

Checked 2 cost basis(es), and found 1 thing(s) that do not hold:

2026-01-10  Assets:Bank:USD
    Buy 100 USD at 1.35
    split guid         31438b24314e495384989e74d13caa7f
    tx guid            9c0c4ce246794670856347aaf44cb69f
    amount             100.00 USD
    value              135.00 CAD   (the transaction's currency)
    cost basis balance 100.00 USD
    value / amount     1.35
    computed cost      1.35 CAD/USD
    stored cost        9.99 CAD/USD
    used               1.35 CAD/USD
    - cost_basis_cost says 9.99 CAD/USD, but the transaction says 1.35 — the transaction is what is used
```

The factors listed are the ones the derivation multiplied, and only those: a transaction already in CAD has one, `value / amount`, while a USD-denominated one has that and the `CAD per USD` rate its CAD splits imply. Nothing is printed for a step that was not taken.

That rate is every base-currency split taken together — the CAD they carry over the foreign currency they are worth — not whichever split is read first. Each is rounded to the cent on its own, so an invoice's income and tax lines give slightly different ratios though both were converted at one rate: 33.33 USD at 10% tax, posted at 1.4, books 46.66 CAD over 33.33 and 4.66 over 3.33, which are 1.40006 and 1.39940. Reading one split priced the whole cost basis at whichever it happened to reach; summing cancels most of the rounding and cannot depend on order.

Nothing is inferred back out of those figures. A rate runs forward — the file states it, the foreign amount is multiplied by it, and the result is rounded to the unit the receiving account is held to. The effective rate the ledger then carries is that rounding's doing: 45.00 USD at a stated 1.405 books 63.23 CAD, whose ratio is 6323/4500, and that is correct rather than a discrepancy to be detected.

Where a cost basis is reported for something else, the splits its cost was added up from are printed with it, at the unit each is held to — a fund account kept to thousandths carries 12.345 units, and the report says which unit that is, since three decimals otherwise read as a mistake.

Giving a cost basis a balance uses the mechanism that already exists — state it on the split in an import file, where a stated balance is authoritative:

```
	Assets:Bank:USD 100.00 USD
		guid: "6b2d279090974d34b37da8b1a62abfd8"
		cost_basis_balance: "100.00"
```

Authoritative, and therefore checked before it lands: it must be on a split that holds foreign currency, and then a number, not negative, no finer than the unit its own account is held to, and no more than that split brought in. Nothing downstream questions it — a sale is measured against it and valued at the cost basis cost — so 150.00 stated on a split that acquired 100.00 leaves 50.00 sellable that never arrived, with the gain on selling it computed against a cost that was paid. And one that does not parse states nothing: `60,00` for `60.00` used to leave the split marked as having stated a balance, so the sale below it was skipped as already accounted for while the cost basis opened at its full amount — forty sold USD back in the book from one wrong character.

---

## Selling foreign currency

A sale gives the guid of the cost basis it is measured against and values what it sells at that cost basis's cost. What the sale fetched is on the other splits, and `$residual$` takes the difference:

```
2026-02-01 * "Sell 40 USD"
	currency.mnemonic: "CAD"
	Assets:Bank:USD -40.00 USD
		share_price: "1.35"
		value: "-54.00"
		cost_basis_split_guid: "a0941ac334c44a31ba0120a0493c931c"
	Assets:Bank 55.60 CAD
	Income:FX Gain $residual$ CAD
```

40 USD that cost 54.00 CAD fetched 55.60, so the residual books `Income:FX Gain -1.60 CAD` — a 1.60 gain — and that cost basis drops to `60.00 USD` available while the other is untouched.

### Spreading a sale across several cost bases

The user decides which cost bases a sale draws on and in what amounts. Selling 200 USD can take all 200 from one cost basis, 100 from each of two, or 50 and 150 — one foreign-currency split per cost basis, each giving its own:

```
2026-03-01 * "Sell 150 USD"
	currency.mnemonic: "CAD"
	Assets:Bank:USD -100.00 USD
		share_price: "1.35"
		value: "-135.00"
		cost_basis_split_guid: "a0941ac334c44a31ba0120a0493c931c"
	Assets:Bank:USD -50.00 USD
		share_price: "1.30"
		value: "-65.00"
		cost_basis_split_guid: "3d86b7fde164480d83902eb96e8d3642"
	Assets:Bank 208.50 CAD
	Income:FX Gain $residual$ CAD
```

The cost consumed is 135.00 + 65.00 = 200.00 CAD against 208.50 of proceeds, so `Income:FX Gain -8.50 CAD`. The first cost basis has no balance left, the second keeps 50.00 USD available.

### You can only sell currency you actually hold

An invoice's A/R split states what a customer **owes**, not what the book has. Measuring a sale against it before the invoice is paid is selling money that has not arrived, so it is refused:

```
Error: cost basis <guid> is a split on 'Assets:Accounts Receivable USD', and
the invoice it belongs to has not been collected — that USD is owed, not held,
so there is none to sell. Record the payment first, or add
`cost_basis_force: true` to this split to measure against it anyway.
```

The lot is the test: it closes when the record is settled, so a paid invoice's cost basis is sellable with nothing extra, and a partly paid one is not. `cost_basis_force: true` on the selling split overrides it, for when the money is in hand and the record simply has not been marked paid yet.

This tool keeps books; it does not support trading a position the book does not hold. Currency bought or borrowed is in the account already and is never restricted, and a **payable** is not restricted either — its lot is open precisely until the bill is paid, and settling it with foreign cash is the ordinary way that happens.

### What is refused

| the file says | the importer says |
|---|---|
| a sale of 150 USD against a cost basis of 100 | `150.00 USD against cost basis <guid> exceeds its cost basis balance by 50.00 USD (the cost basis brought in 100.00 USD and has 100.00 left)` |
| a sale against an invoice that is not yet paid | `cost basis <guid> is a split on 'Assets:Accounts Receivable USD', and the invoice it belongs to has not been collected — that USD is owed, not held, so there is none to sell…` |
| a cost other than the cost basis's | `this split sells 100.00 USD valued at 120.00 CAD, but cost basis <guid> cost 1.35 CAD per USD, i.e. 135.00 CAD — value what is sold at the cost basis it picks, so the CAD the sale fetched and the residual gain or loss stand apart` |
| a guid matching no split | `cost_basis_split_guid '<guid>' matches no split in the book` |
| a guid matching a split that holds no foreign currency | `cost_basis_split_guid '<guid>' matches a split that is no USD cost basis — a cost basis is a split that brought USD into the book (an invoice, a bill, a purchase or a borrowing)` |
| a cost basis with no balance recorded | `cost basis <guid> has no balance recorded — the split was not written by this tool, so how much of its USD is still unsold is not known and cannot be assumed to be all of it…` |
| a `payment:` block spending a foreign account whose cost bases still have a balance | `this bill pays 100.00 USD out of 'Assets:Bank:USD', whose cost bases still have 200.00 USD of balance between them, and spending that has to say which cost basis it comes out of. A payment block cannot — GnuCash writes its bank split. Write the settlement as an ordinary transaction with cost_basis_split_guid: on the bank line and attach it with txn_guid: / txn_split_guid:` |
| a settlement into a foreign bank with no rate for **that bank's** currency | `this invoice is in USD and settles into HKD, so valuing the cash needs the HKD/CAD rate on 2026-02-25, which the rates file does not carry: …` |
| a CAD invoice settled into a foreign bank | `invoice INV-…: this payment settles a CAD invoice into a HKD account. Nothing is realized — CAD does not move against itself — and what the HKD cost belongs to that account, recorded where the currency was bought, not to this invoice. Settle it from a CAD account, or record the HKD purchase as its own transaction.` |

The first of those three is the one most likely to meet an existing ledger, and it is asked of **every** foreign bank rather than only one in a third currency — paying a USD bill out of a USD bank whose cost bases still have a balance reaches none of the cross-currency arithmetic and leaves the cost bases claiming currency the account no longer holds just the same, so the question is asked before it. A foreign account gets its first cost basis as soon as something opens one, and a settlement landing in it is one such thing; README's foreign-currency section shows the ordinary transaction that replaces the payment block.

Nothing is written when a sale is refused: the cost bases keep their balances. Every figure a file states about a cost basis is checked before any balance moves — a stated cost and a stated cost basis balance are both parsed before the transaction is even created, every pick is validated before the first drawdown, and a payment's split lines are judged before the settlement draws anything down — so a refused sale leaves the ledger exactly as it was.

A refusal that can only come later is caught by one of two different mechanisms, depending on what was being imported, and it is worth knowing which:

| what is refused | what happens to what it drew |
|---|---|
| a **transaction** | it is destroyed and what it drew is given back with it, and the rest of the file lands as normal |
| a **payment inside an invoice or bill** | the whole import is abandoned: the book is left exactly as it was found, and nothing else from that file is written either |

Both leave every cost basis where it was, which is the guarantee that matters, but they are not the same behaviour and a file half-lands in neither case. The second is the blunter of the two — a settlement values itself against the cost basis it consumes, so what a refusal after that point would have to give back is not one drawdown but everything the invoice has done, and abandoning the book is the only answer that cannot leave the two disagreeing.

Measured on a book holding 200.00 USD across two cost bases: a file carrying an invoice whose converting payment realizes 3.00 CAD with no split to take it, and an ordinary CAD transaction beside it, is refused with `settling this USD invoice into CAD realizes 3.00 CAD … add a split to the payment block`. Afterwards `fx-balances` reports the same 200.00 USD across the same two cost bases, and the ordinary transaction is not in the book either — the file landed in full or not at all.

---

## Worked example: buy USD, borrow USD, sell some of each

The whole cycle for currency that arrives without an invoice, start to finish.

**1. Buy 100 USD at 1.35 and borrow 100 USD at 1.30.** Two transactions, no rates file needed — each states its own rate as `share_price`:

```
2026-01-10 * "Buy 100 USD at 1.35"
	currency.mnemonic: "CAD"
	Assets:Bank:USD 100.00 USD
		account.commodity.mnemonic: "USD"
		share_price: "1.35"
		value: "135.00"
	Assets:Bank -135.00 CAD

2026-01-20 * "Borrow 100 USD at 1.30"
	currency.mnemonic: "CAD"
	Assets:Bank:USD 100.00 USD
		account.commodity.mnemonic: "USD"
		share_price: "1.30"
		value: "130.00"
	Liabilities:Loan -130.00 CAD
```

```bash
gnucash-plaintext import --new book.gnucash buy-and-borrow.txt
```

**2. See what is held, and at what.** The bank now holds 200 USD carrying two different costs:

```
$ gnucash-plaintext fx-balances book.gnucash
DATE         SPLIT GUID                         ACCOUNT                       COST     BROUGHT IN COST BASIS BALANCE
--------------------------------------------------------------------------------------------------------------------
2026-01-10   6b2d279090974d34b37da8b1a62abfd8   Assets:Bank:USD       1.35 CAD/USD     100.00 USD         100.00 USD
             Buy 100 USD at 1.35
2026-01-20   ab1df82af72741038ad02564b97eb625   Assets:Bank:USD        1.3 CAD/USD     100.00 USD         100.00 USD
             Borrow 100 USD at 1.30

Total USD cost basis balance: 200.00 USD
```

**3. Sell 150 USD at 1.39, taking all of the bought USD and half the borrowed.** Which cost bases the sale is measured against is the user's choice, and it is what decides the gain — the same 150 USD taken entirely from the 1.35 cost basis would realize less:

```
2026-03-01 * "Sell 150 USD"
	currency.mnemonic: "CAD"
	Assets:Bank:USD -100.00 USD
		account.commodity.mnemonic: "USD"
		share_price: "1.35"
		value: "-135.00"
		cost_basis_split_guid: "6b2d279090974d34b37da8b1a62abfd8"
	Assets:Bank:USD -50.00 USD
		account.commodity.mnemonic: "USD"
		share_price: "1.30"
		value: "-65.00"
		cost_basis_split_guid: "ab1df82af72741038ad02564b97eb625"
	Assets:Bank 208.50 CAD
	Income:FX Gain $residual$ CAD
```

```bash
gnucash-plaintext import book.gnucash sell-150.txt
```

**4. What the ledger now says.** 200.00 CAD of cost consumed against 208.50 of proceeds, so the residual booked `Income:FX Gain -8.50 CAD` — an 8.50 CAD gain — and the cost bases record what is left:

```
$ gnucash-plaintext fx-balances book.gnucash --with-balance-only
DATE         SPLIT GUID                         ACCOUNT                       COST     BROUGHT IN COST BASIS BALANCE
--------------------------------------------------------------------------------------------------------------------
2026-01-20   ab1df82af72741038ad02564b97eb625   Assets:Bank:USD        1.3 CAD/USD     100.00 USD          50.00 USD
             Borrow 100 USD at 1.30

Total USD cost basis balance: 50.00 USD
```

The bank account holds 50 USD and the one remaining cost basis has 50 USD available — here they agree, because every USD in the account came from a cost basis in the account. They would not agree if a USD invoice were still outstanding: that A/R cost basis holds USD the bank has not received yet.

**5. Repaying the borrowing** with the USD still held is the same shape as settling a USD bill with USD cash, above: name the cost basis the cash comes from, value it at that cost basis's cost, and let `$residual$` book the difference against what the loan was written at.

---

## `$residual$`

A split may write `$residual$` in place of an amount and take whatever the others leave over, the way GnuCash's editor fills an Imbalance line once an account is chosen. Requiring a hand-computed FX gain would be asking for arithmetic the transaction already determines, where a slip is a misstated tax figure.

It is a **token, not an omitted amount**: inferring a residual from a missing field would mean any truncated line inside a transaction silently became a residual split. And it is **sigil-delimited, not a bare word**, so `residual` stays usable as an account name or a commodity.

| the file says | the importer says |
|---|---|
| two `$residual$` splits | `2 splits ask for $residual$ — only one split per transaction can take the residual, because two cannot be resolved` |
| `$residual$` where the splits already balance | `$residual$ on 'Income:FX Gain' has nothing to take — the other splits already balance` |
| `$residual$` on an account in another currency | `$residual$ on 'Assets:Bank:USD' is a USD account but the transaction is in CAD — the residual is a CAD figure, and writing it as an amount in another currency would invent a 1:1 rate` |

It is not specific to currency: any transaction may use it.

**The book records which split took it**, in a `took_the_residual` KVP on that split. Nothing in a saved transaction could be asked afterwards. A disposal balances — what it fetched plus the difference it realized is what those units cost — so the arithmetic alone cannot say which of its splits is which, and neither can the account: 8.60 USD disposed of at a cost of 11.99 paid an 11.92 bank charge beside 0.07 of exchange difference, both on expense accounts, and an account is not one or the other because of its name. The file said which, and the key is what keeps that.

**So there are two ways to write a disposal, and they produce the same book.** `$residual$` has the import work the figure out and record the key. Working it out yourself gives the same transaction — the same accounts, the same amounts, the same values — because the token resolves to nothing more than the negation of what the other splits come to. What a written-out figure has to state as well is which split is the difference, since the numbers cannot say: a balanced transaction gives every one of its splits that same arithmetic. So state `took_the_residual: "true"` on it, and the page states the same gain:

```
	Income:FX Gain $residual$ CAD          # the import works it out and marks the split
```
```
	Income:FX Gain -100.00 CAD             # you work it out
		took_the_residual: "true"          # and say which split it is
```

The key is honoured where the ledger bears it out, exactly as the import requires before writing one itself: the transaction must be stated in the book's own currency, it must hold a split giving the guid of the cost basis it draws on, and the marked split must be on an **income or expense** account. A realized difference is a gain or a loss, so it belongs in the profit and loss; one balancing onto a bank or a receivable moved money rather than measuring a difference, and counted as one it put the whole receipt into the figure — a disposal writing `Assets:CAD Bank $residual$ CAD` beside a stated gain stated the 1,400.00 the bank took as a 1,400.00 loss. `$residual$` itself is unchanged and still writes on any account whose commodity is the transaction's, on any transaction; what is restricted is which split is read as the difference.

**What none of that can do is tell one income or expense from another in the same disposal.** A bank charge is an expense too — 8.60 USD disposed of at a cost of 11.99 paid an 11.92 charge beside 0.07 of exchange difference, both on expense accounts. Where a disposal carries both, the `$residual$` token or a stated `took_the_residual` is the only thing that says which is which, and a file that puts either on the wrong line is believed.

**One split per transaction may take it, whichever way it is claimed.** Two stated keys, or a key stated beside a `$residual$` token, are refused — a transaction has one exchange difference, and counting two on a sale of 1,000.00 USD that cost 1,300.00 and fetched 1,400.00 would state the 1,400.00 the bank received as a gain beside the 100.00 that was one.

**The export carries the key**, because it cannot carry the token. An exported split states the figure the residual resolved to, not `$residual$`, so a book rebuilt from its own ledger would otherwise have no record of which split was the difference. It is the same key a file may state, so an exported disposal re-imports as the disposal it was.

**A book imported before this key existed carries none**, and nothing adds one after the fact: the import writes it, and only where the file wrote the token. So a disposal already in such a book states no realized difference at all — `realized_gains_fx` reads `0.00` and its items say `splits: # there is no split` — however plainly the plaintext file that made it stated one with `$residual$`. Re-exporting does not mend it either, for the same reason the export carries the key rather than the token: what comes out is the figure, and a figure says nothing about which split it is.

**`--fx-gain-account` reads such a book without changing it.** State the account the book's exchange differences are booked to, and the sheet takes them from there:

```
gnucash-plaintext balance-sheet book.gnucash --as-of 2026-12-31 \
    --fx-gain-account "Income:Non-farming revenue:Foreign exchange gains/losses"
```

It is repeatable, for a book that keeps its gains and its losses in two accounts, and `report` takes it too. On `tests/fixtures/the_thousand_usd_sold_less_a_charge_with_no_took_the_residual.txt` it turns `realized_gains_fx: 0.00` into `100.00` — the exchange difference alone — while the 10.00 bank charge on that same disposal stays out.

**Given any account, the key is not consulted at all.** The two are not added together. A reader who states where their differences are booked has answered the question for the whole book, and a page that also counted whatever keys happened to be in it would give an answer depending on which release imported which transaction — a difference the reader cannot see and did not ask about. So a marked split on an account you did not state is passed over, and a book that wants both counts states both accounts.

What the option cannot do is widen where a difference may sit. The three conditions the book answers for itself hold either way — the transaction stated in the book's own currency, a split giving the guid of the cost basis it draws on, and the split itself on an income or expense account — so an account specified by mistake counts nothing on a transaction that disposed of no currency.

What mends the book itself is the second way of writing a disposal, above. Export the book, add `took_the_residual: "true"` to the gain split of each disposal, and import that back with `--strategy update`. The key is honoured on the same terms as any other, so what you are doing is stating by hand what a `$residual$` would have recorded at the time.

**The balance sheet reads it.** `realized_gains_fx` is the total, up to the sheet's date, of the splits the book marks — or of the splits on the accounts `--fx-gain-account` specifies, where it is used — at the book's own sign — a gain is a credit on an income account, so the figure is the negative of the value on them. See [Q-043](issues/Q-043-state-realized-and-unrealized-gains-separately-and-value-foreign-currency-from-the-cost-bases.md).

---

## Money, to the smallest unit its currency has

Every figure here — amounts, rates, tax, and each intermediate — is an exact rational. No money passes through a float, and nothing is compared with an epsilon: an open lot's balance is zero or it is not, and a stated prepayment matches what the book holds or it does not.

A figure reaches its currency's smallest unit through **GnuCash's own conversion**, `GNC_HOW_RND_ROUND_HALF_UP`, which sends a half away from zero — downward for a negative figure, not up. Python's `round` is banker's rounding and answers differently on exactly the figures that matter: 45.00 USD settled at 1.405 costs 63.225 CAD, an exact half-cent, which GnuCash books as 63.23 and `round` as 63.22. That single cent is in the ledger and in the gain reported for the year.

Two rules follow, and they are opposite sides of one principle:

- A **computed** figure is rounded. Units × rate simply is what it is, and something must take it to the cent. What the ledger then carries is the rounded figure, and the residual gain is derived from *that*, so the entry balances exactly even when the cost does not divide into cents.
- A **stated** figure is honoured or refused, never adjusted. `Expenses:Bank Fees 2.005 CAD` is half a cent and no CAD split can hold it; booking 2.01 would put a number in your books you never wrote.

```
error: the amount on split 'Expenses:Bank Fees' states 2.005 CAD, which is
finer than that currency: its smallest unit is 0.01, and a booked amount is a
whole number of those. A trailing zero is fine — 18.190 is 18.19 — but a
figure that needs the extra digit is not money this book can record.
```

**How many decimals a currency has is read from the commodity, never assumed.** The yen's smallest unit is the yen itself, so a JPY book reads back whole — in the ledger and on the printed invoice alike — and 2070 JPY of tax at 5% is 103.5, which GnuCash books as 104. The won is the case that makes the point: its fraction changed with the engine version, so the answer comes from whatever GnuCash is installed rather than from a table in this tool.

An **account** can be denominated more finely than its commodity, and this tool round-trips that as `commodity_scu:` — but a *booked amount* is judged against the coarser of the two, the account's unit and the currency's. A money figure is a whole number of the currency's smallest unit whatever account it sits in: there is no such thing as a tenth of a cent of Canadian money, so `1.819 CAD` is refused on an account kept to thousandths exactly as it is anywhere else.

What the finer account is for is everything that is *not* a booked amount — a unit price, a quantity, a rate. Fuel at 1.819 a litre is a price, and it is stated at that precision; what the split books is 10 litres at 18.19, and that is the figure the currency has to be able to hold.

**A split that states both amounts has the price they give.** GnuCash's transfer dialog takes one amount and then either the rate or the other amount. A block may state all three, and every export does: it writes `share_price:` beside `value:` as the price those two give, `6323/4500` for 45.00 USD valued at 63.23 CAD. Where a file's `share_price:` is not that price, the two amounts decide, on a new transaction and under `--strategy update` alike, and the import warns:

```
warning: the share_price on split 'Expenses:Travel USD' states 1.5, and its
amount and value give 6323/4500: the price is the one the two amounts give
```

A split that states an amount and a `share_price:` and no `value:` is valued at the amount times the price, rounded by GnuCash to the smallest unit of the transaction's currency.

The coarser of the two, in both directions. An account kept to whole dollars refuses 18.19 as well — a fine number of Canadian dollars and not a number of *those* — rather than rounding it to 18 and leaving GnuCash to park the difference in `Imbalance-CAD` under a summary reporting no errors.

---

## Correcting things

**Deleting a sale gives the currency back.** The delete reads what the transaction took from each cost basis it named, then raises those balances by exactly that much — capped at what the cost basis brought in, so a balance can never exceed the currency the split carried:

```bash
gnucash-plaintext delete-transactions book.gnucash --by-guid <the sale>
```

```
Total USD cost basis balance: 200.00 USD          # was 160.00 while the 40 USD sale existed
```

The cost basis is immediately sellable in full again. This is what makes the feature safe to experiment with: any sale can be undone, and the deletion prints a plaintext copy of what it removed so it can be re-imported.

**Unposting a record whose cost basis is in use is refused.** A posted record's A/R or A/P split *is* the cost basis, and unposting destroys the posting transaction:

```
Error: invoice 'INV-USD-001' cannot be unposted: its cost basis is what 1
transaction(s) measure against — 2026-02-01 'Sell 40 USD' (40.00 USD).
Unposting destroys the split that cost basis lives on, and re-posting creates a new
one with the whole amount available again, so those transactions would be
measured against a cost basis the book no longer has. Remove or re-point them
first.
```

Without that guard, unposting and re-posting silently reset a cost basis to its full amount — a book that had sold 40 of 100 USD would claim 100 USD available, currency it no longer has. Delete the sales first (they come back as plaintext), then unpost; the order is: undo the sales, undo the payment, unpost. A cost basis nothing measures against unposts freely, and single-currency records are unaffected.

**Deleting the transaction that establishes a cost basis in use is refused** for the same reason: the sales measuring against it would be left giving a guid the book no longer holds.

### Editing with `--strategy update`

`import --strategy update` is the export → edit → re-import loop, and it is the path the tool itself recommends whenever a guid-matched transaction's content differs. Every rule that governs a sale on the way in governs it on the way back, so what an edit may change depends on whether a cost basis rests on it:

| the edit | what happens |
|---|---|
| a memo, description, action, date or doc_link | goes through — none of them can change what a cost basis holds or what it cost |
| the amount, value, rate, account, or cost basis pick of a split a cost basis rests on | refused, giving the transaction's guid and the way through that works |
| the account of a split no cost basis rests on | goes through |
| a transaction that touches no cost basis at all | ordinary; the update path is unrestricted |

**Which splits a cost basis rests on** is its own split — the amount that arrived, the value it arrived at, the rate between them — and, where the transaction is stated in a *foreign* currency, every CAD split too, because the rate is worked out by adding all of them up. Nothing else. So a USD deposit whose other split is on a CAD account can have that split moved to income, or to another CAD account: the USD split keeps its amount, its `value:` and its `share_price:`, so its cost is the same figure before and after. Comparing every split instead refused that, which is an ordinary correction to have to make.

State the rate the book holds, not the one you first typed. A value that reached the cent leaves an effective rate of its own — 2,720.00 USD booked at 1.4029 is 3,815.89 CAD, a rate of 381589/272000 — and that is what the split holds and what the export writes. Editing an export gets this right for free; a block written by hand from the original rate reads as a changed figure and is refused.

```
Error: transaction <guid> touches a cost basis, so its amounts, values,
accounts, cost basis picks and the currency it is stated in cannot be edited
in place — a memo or description can. Delete it and import the new version
instead: `delete-transactions --by-guid <guid>` gives the cost basis back
exactly what this transaction took, and the fresh import checks the new
figures against it.
```

The reason is that the checks governing a sale run over a transaction's splits once they are book state, and an in-place edit has already overwritten what the old amounts drew before anything can re-check them. Left alone, that accepted a sale of 400.00 USD against a cost basis holding 60.00, reported `Updated: 1`, and left the cost basis still reading 60.00. Delete-and-reimport reaches the same end state with every check applied.

An update can also *bring currency into the book* — a CAD placeholder corrected into `Assets:Bank:USD 100.00 USD`, or reversed signs fixed so a split becomes a purchase — and that currency opens a cost basis exactly as a fresh transaction's would. What matters is whether the split was a cost basis before the edit, not whether the split existed: splits are matched by account, so correcting reversed signs reuses the very same split, same guid. A split that was already there and carries no balance keeps **none recorded** — correcting a description was once enough to open every such cost basis in a book at its full amount.

`--strategy update` requires a `guid:` on every transaction in the file, so an edited export can be re-imported wholesale but a file cannot mix edits with newly written transactions. A transaction whose guid the book does not hold is refused rather than created, which is what stops a deleted sale from being re-imported and taking its cost basis down a second time.

## Round-trip

A realized settlement round-trips without restating anything: the export writes the payment as a link to the transaction it already emitted (`txn_guid:` + `txn_split_guid:`), so the fresh book inherits the FX split, the A/R value at cost, and the cost basis at zero available — and needs no rates file to rebuild them.

`cost_basis_split_guid:` and `cost_basis_balance:` are ordinary KVP slots, so they survive export → fresh-book re-import like any other custom metadata. **A balance stated in a file is authoritative and already net of that file's own sales** — an export carries `cost_basis_balance: "60.00"` on a cost basis alongside the 40 USD sale that lowered it — so re-importing an export leaves it at 60.00 rather than taking the 40 again. A sale imported against a cost basis the book already held is a new sale and does lower it. A stated balance only counts once its transaction is actually in the book: a transaction that fails and rolls back takes its splits' guids with it, so a sale further down the same file giving that cost basis is refused for a cost basis the book does not have.

`txn_type: P` round-trips on every supported version, which matters because a re-imported payment that is not a payment to the engine is invisible to `find-orphan-payments`. The importer writes it onto the transaction with `xaccTransSetTxnType`, which stores it in a KVP slot; GnuCash 3.8 and 4.4 read that slot back, while from 4.13 `xaccTransGetTxnType` derives the type from the transaction's splits and lots and never consults it. So the export takes the C field when it is set and falls back to the slot when it is not, and a type GnuCash does not know (`txn_type: Z`) is refused rather than written into engine state, where a typo would export straight back out.

An export that carries business objects emits the book's whole chart of accounts, so it is always re-importable — an invoice reaches accounts no transaction split touches, and an unposted one has no posting transaction to drag them in.

---

## Reports

| command | what it does with foreign currency |
|---|---|
| `income-statement` | reports the CAD revenue and expense already booked — 140.00 CAD for the USD invoice above. No rate needed for that figure |
| `balance-sheet` | consolidates each account's own-currency balance at the `--fx-rates` rate: 200 USD held reads 274.00 CAD at 1.37. It also states what the currency has gained or lost against what it cost — separately, in the keys below, and not in the account lines |
| `account-balance` | same, per account: `Assets:Bank:USD 274.00 CAD`, showing the 200.00 USD original |

Each reads the **amount** on a split — the figure in the account's own commodity — not its value, which is stated in the transaction's currency. Those differ the moment a transaction crosses currencies: a CAD income account credited by a USD invoice holds a split whose amount is the CAD revenue and whose value is the USD invoice total.

### What the balance sheet says about a gain

A gain the book has **taken** and a gain it has **yet to take** are different things, and one line cannot carry both: the first is taxable when it is realized, the second is not. The sheet states them apart, and states foreign currency apart from everything else (Q-043):

A book owing 1,000.00 USD borrowed at 1.30, drawn when the nearest price is 1.40 — `tests/fixtures/a_cad_book_that_borrowed_usd_into_its_cad_bank.txt`, as of 2026-01-25:

```
	total_assets: 1300.00 CAD
	Liabilities:USD Loan 1000.00 USD
		account.commodity.mnemonic: "USD"
		share_price: "1.4"
		value: "1400.00"
	total_liabilities: 1400.00 CAD
	unrealized_gains_assets_fx:
		commodities: # there is no cost basis on the asset side
		cost_value: 0.00 # sum of each commodity's cost_value
		value: 0.00 # sum of each commodity's value
		unrealized_gains_assets_fx: 0.00 # value - cost_value
	unrealized_gains_liabilities_fx: -100.00 CAD
	unrealized_gains_fx: -100.00 CAD # unrealized_gains_assets_fx + unrealized_gains_liabilities_fx
	realized_gains_fx:
		realized_gains_fx: 0.00
		splits: # there is no split
	realized_gains_other: 0.00 CAD # not yet supported
	total_realized_gains: 0.00 CAD # realized_gains_fx + realized_gains_other
	unrealized_gains_other: # sum of unrealized_gains_other of all securities and funds
		securities: # there is no security or fund
		value: 0.00 # sum of each security's value
		cost_value: 0.00 # sum of each security's cost_value
		unrealized_gains_other: 0.00 # value - cost_value
	total_unrealized_gains: -100.00 CAD # unrealized_gains_fx + unrealized_gains_other
	gnucash_balancing_amount: # the commodities GnuCash's own figure is summed from
		commodities:
			commodity:
				commodity.mnemonic: "USD"
				splits:
				sum_value: 0.00 # sum of split's value of all splits
				accounts:
					account:
						guid: 82736d199a34454a93997ec9ae29169c
						name: "Liabilities:USD Loan"
						balance: -1000.00
				balance_value: -1000.00 # sum of account's balance for all accounts
				gains_before_conversion: -1000.00 # what GnuCash's own figure holds for this commodity
				balance_sheet_value: -1400.00 # -1000.00 USD at 1.4 CAD per USD
			commodity:
				commodity.mnemonic: "CAD"
				...
				balance_sheet_value: 1300.00 # 1300.00 CAD at 1 CAD per CAD
		gnucash_balancing_amount: -100.00 # sum of balance_sheet_value of all commodities
	total_equity: -100.00 CAD
	total_liabilities_and_equity: 1300.00 CAD
```

The debt was drawn at 1.30 and is worth 1.40 a dollar now, so it has cost the book 100.00 CAD that it has not paid yet. The figures on the owed side are negative — a cost basis there is currency the book owes rather than holds — and the two sides add to `unrealized_gains_fx` as they stand, without either being re-signed.

- **`realized_gains_fx`** is what the book took when currency left it. A disposal is valued at what those units cost, so the splits facing it state what they fetched and the difference is the gain — the split the file marked `$residual$`. These are in the income and expense accounts already, so the sheet states them and adds them into nothing; adding them to equity a second time leaves equity standing against money that is gone.
- **`unrealized_gains_assets_fx`** and **`unrealized_gains_liabilities_fx`** are what the currency still held, and still owed, are worth at the price nearest the sheet's date, less what the cost bases say they cost. They add to `unrealized_gains_fx`, and only that total reaches `total_equity`.
- **`unrealized_gains_other`** is everything that is not a currency — a stock, a mutual fund — at GnuCash's own revaluation, since a security opens no cost basis.
- **`gnucash_balancing_amount` is an amount GnuCash adds to equity as the unrealized gain, and it is not always the unrealized gain** — which is why it is stated here under a name saying whose figure it is rather than under a name of its own. GnuCash reaches it by taking the summed values of the splits in a holding's own accounts from what that holding is worth at the sheet's date. That is the unrealized gain only where every one of those splits carries a figure in the book's own currency. Where foreign currency arrived carrying no figure in the book's own currency and was later spent, GnuCash's amount comes out as the negative of the gain or loss already taken: that money is in the income and expense accounts, so `retained_earnings` carries it already, and adding an amount of the opposite sign cancels it rather than leaving it, so GnuCash's own page then states more liabilities and equity than it has assets. Currency bought with the book's own money and sold again does not do this — both splits carry the book's own figures, so GnuCash's subtraction cancels exactly and states `0.00`. This page adds the gain measured from the cost bases instead, and balances. The amount is carried across so a reader with GnuCash's page beside them can find the same number, and nothing adds it in. Beneath it the page states the subtraction GnuCash made rather than a verdict on it, commodity by commodity — the commodities its own figure is summed from, read out of the collector GnuCash sums rather than grouped by anything this page decided. Each group gives that commodity's amount and the amount converted, with the splits valued in it and the accounts holding it beside them, so a reader can see what went into the figure. Which of the cases above a book is in is worked out from those figures, and every example under `examples/multi-currency/` carries the block for its own book, so the arithmetic can be followed rather than taken on trust. [Q-044](issues/Q-044-state-a-realized-gain-with-no-took-the-residual-key-and-say-what-the-balancing-amount-is.md) has the measurements.

**A currency the cost bases cannot speak for keeps GnuCash's own revaluation**, and is still stated under `_fx`, because it is currency however it was measured.

**Every one of those figures shows its working**, by default, as the items the key is made of, indented beneath it the way `share_price:` and `value:` are indented beneath an account line, with the arithmetic in a trailing `#` comment. A gain is the one figure on the page a reader cannot check by inspection — an account line can be checked against the book, a section total by adding the lines above it, but a gain is measured against costs on no line at all:

From [`billed_in_us_and_hong_kong_dollars.txt`](../examples/multi-currency/billed_in_us_and_hong_kong_dollars.txt), whose US dollar group is left out here and is in the file. The guids are that generated book's own; a reader running the ledger into a book of their own gets different ones:

```
	unrealized_gains_assets_fx:
		commodities:
			commodity:
				commodity.mnemonic: "HKD"
				type: asset
				share_price: 26/155 # current price of commodity in balance sheet currency
				cost_bases:
					cost_basis:
						split_guid: 06f38d6ed30745c8be16b4481d6902da
						account: "Assets:HKD Bank"
						cost_basis_balance: 99510.00
						cost_share_price: 1/6
						cost_value: 16585.00 # cost_basis_balance * cost_share_price
						value: 16692.00 # cost_basis_balance * share_price
						unrealized_gains_assets_fx: 107.00 # value - cost_value
				cost_basis_balance: 99510.00 # sum of each cost_basis's cost_basis_balance
				cost_value: 16585.00 # sum of each cost_basis's cost_value
				accounts:
					account:
						guid: d6e2b43bba8a4659832a6d5843d8fefa
						name: "Assets:HKD Bank"
						balance: 99510.00
				balance_value: 99510.00 # sum of account's balance for all accounts
				value: 16692.00 # cost_basis_balance * share_price
				unrealized_gains_assets_fx: 107.00 # value - cost_value
			...
		cost_value: 17365.00 # sum of each commodity's cost_value
		value: 17472.00 # sum of each commodity's value
		unrealized_gains_assets_fx: 107.00 # value - cost_value
	realized_gains_fx:
		realized_gains_fx: 110.00
		splits:
			split:
				date: 2026-07-01
				account: "Income:FX Gain"
				amount: 60.00
			split:
				date: 2026-08-01
				account: "Income:FX Gain"
				amount: 50.00
```

Each currency lists every cost basis it is measured against and the accounts holding it, so the two can be read side by side: `cost_basis_balance` is how much of that currency its cost bases still account for, and `balance_value` is what the accounts actually hold. Where those two disagree the currency keeps GnuCash's own revaluation, is listed under `measured_from: gnucash_revaluation` instead of under its cost bases, and states the cost and the worth GnuCash's own subtraction used — [Q-044](issues/Q-044-state-a-realized-gain-with-no-took-the-residual-key-and-say-what-the-balancing-amount-is.md) covers that case.

A price is stated exactly, as `26/155` above, because a rate rounded to the currency's places would not multiply out to the value beside it; a figure in money is stated at the places its own commodity is kept to, which is what GnuCash's page states it at.

**`cost_basis_balance` and `cost_value` add up down the listing; `value` and the gain do not.** A holding is converted once, at the commodity's price, and that is the commodity's own `value:` and what the key is built from. Each cost basis line converts that basis by itself and rounds to the commodity's places, so several of them need not come to one conversion of the whole holding — two 1.00 USD bases priced at 1.3833 print `value: 1.38` apiece against the commodity's `2.77`. Converting basis by basis and adding is what left a sheet stating 100.17 of assets against 100.16 of equity, so the page converts once and lists the per-basis figure for reference.

`--no-itemize` turns the items off, on `balance-sheet` and on `report`, leaving each key as the single figure it was. `--max-items N` keeps them and shortens each list to `N` entries, and a shortened list ends with `not_listed:`, carrying how many were left out and what they come to, so the entries still add up to the total beneath them. `-1` is the default and caps nothing; `0` lists none.

---

### What a company does, and what the sheet then says

The cases below are things a Canadian company does, written as ledgers it would actually keep. The later ones are the earlier ones put together: a company that bills abroad, pays abroad, keeps some of what it is paid, and does all three in more than one currency.

**Each has a ledger you can run yourself**, in [`examples/multi-currency/`](../examples/multi-currency/) — the whole book: accounts, transactions, prices, and the customer and invoice where there is one, with the statement it produces commented at the end. Import one into an empty book and draw it, and you get that statement back, with no rates file:

```bash
gnucash-plaintext import --new /tmp/check.gnucash \
    examples/multi-currency/every_dollar_bought_and_sold_again.txt
gnucash-plaintext balance-sheet /tmp/check.gnucash --as-of 2026-12-31
```

Those files are not test fixtures and nothing asserts against them. They are written from the fixtures in `tests/fixtures/` and from what the tool prints, by `scripts/generate-multi-currency-examples.sh`, which imports every file it writes and stops if one does not come back. The figures below are read off those same pages, and `tests/integration/test_a_sheet_states_realized_and_unrealized_gains_separately.py` is what holds them.

#### A Canadian company invoices a US customer, and is later paid

*[`a_us_customer_invoiced_and_the_dollars_still_held.txt`](../examples/multi-currency/a_us_customer_invoiced_and_the_dollars_still_held.txt)*

It bills 2,720.00 USD, and the payment lands in a US dollar account. Every transaction that brings those dollars in is stated in US dollars, so none of them carries a Canadian figure at all — which is what makes this the case GnuCash cannot report on. What the dollars cost is the rate the invoice was posted at, 189557/136000 CAD/USD, so 3,791.14.

By the year end the company still holds all of them, and the dollar has slipped to 1.3865:

```
	realized_gains_fx: 0.00 CAD
	unrealized_gains_fx: -19.86 CAD
	gnucash_balancing_amount: 0.00 CAD
```

Nothing has been realized, because no dollar has left. The 19.86 is what the holding has lost against what it cost, and **GnuCash states nothing at all** — 0.00 — because the splits that brought the dollars in are valued in US dollars and its subtraction comes to nothing. Priced at 1.45 instead the figure is a gain of 152.86, and at 1.2 a loss of 527.14; GnuCash's amount is 0.00 at every one of them.

#### …and then pays a US supplier out of those dollars

*[`a_us_supplier_paid_out_of_those_dollars.txt`](../examples/multi-currency/a_us_supplier_paid_out_of_those_dollars.txt)*

The same company now spends all 2,720.00 — a transfer to a payee and two bank charges. Each disposal is valued at what those dollars cost, so the splits facing it state what they fetched and `$residual$` takes the difference, which is the loss realized that day.

```
	realized_gains_fx: -19.86 CAD
	unrealized_gains_fx: 0.00 CAD
	gnucash_balancing_amount: 19.86 CAD
```

The 19.86 has moved from unrealized to realized, and nothing is unrealized because nothing is held. **GnuCash's amount is 19.86 here only because the sheet is drawn at 1.3865, which is the rate the dollars happened to leave at.** Draw the same book at 1.45 and it says −152.86 while the realized loss is still 19.86. It is the book that makes them meet, not the report.

#### …and keeps some of the money back

*[`some_of_the_dollars_kept_back.txt`](../examples/multi-currency/some_of_the_dollars_kept_back.txt)*

The same again, except 1,000.00 USD stays in the account. Now the company has both kinds of gain at once, and they behave differently:

```
	realized_gains_fx: -12.56 CAD
	unrealized_gains_fx: -7.30 CAD
```

Priced at 1.45 the realized loss is **still 12.56** — it was settled when the dollars left — while the 7.30 becomes a gain of 56.20; at 1.2 it becomes a loss of 193.80. A realized figure does not move with the report price and an unrealized one does, which is why they cannot share a line.

#### A company that bought US dollars and sold every one of them

*[`every_dollar_bought_and_sold_again.txt`](../examples/multi-currency/every_dollar_bought_and_sold_again.txt)*

The simplest case there is, and a good one to run first: 1,000.00 USD bought at 1.30 and sold at 1.40, with nothing held afterwards.

```
	realized_gains_fx: 100.00 CAD
	unrealized_gains_fx: 0.00 CAD
	total_assets: 5100.00 CAD
```

It is also the case that shows what GnuCash's own Advanced Portfolio report makes of a book this tool writes. That report gives **Money In C$1,300.00 and Money Out C$1,300.00** — because the disposal is valued at what the dollars cost — so it sees nothing made on the disposal, reads **Realized Gain C$0.00**, and counts the 100.00 under **Income** instead.

#### A company paid in US dollars several times, paying several US bills

*[`paid_in_dollars_three_times_and_three_bills_paid.txt`](../examples/multi-currency/paid_in_dollars_three_times_and_three_bills_paid.txt)*

Consulting collected three times — 1,000.00 USD at 1.30, 2,000.00 at 1.35, 1,000.00 at 1.40 — and four subcontractors paid out of it at 1.45, 1.50, 1.38 and 1.42. Three cost bases, four disposals, and the first basis is emptied by the second payment made against it, so the figure has to add up across both:

```
	unrealized_gains_fx: 0.00 CAD # unrealized_gains_assets_fx + unrealized_gains_liabilities_fx
	realized_gains_fx:
		realized_gains_fx: 250.00
		splits:
			split:
				date: 2026-07-01
				account: "Income:FX Gain"
				amount: 90.00
			split:
				date: 2026-08-01
				account: "Income:FX Gain"
				amount: 80.00
			split:
				date: 2026-09-01
				account: "Income:FX Gain"
				amount: 60.00
			split:
				date: 2026-10-01
				account: "Income:FX Gain"
				amount: 20.00
	realized_gains_other: 0.00 CAD # not yet supported
	total_realized_gains: 250.00 CAD # realized_gains_fx + realized_gains_other
```

#### A company holding US dollars while paying its own bills at home

*[`dollars_held_while_the_bills_are_paid_at_home.txt`](../examples/multi-currency/dollars_held_while_the_bills_are_paid_at_home.txt)*

It buys 1,000.00 USD at each of 1.20, 1.30, 1.40 and 1.50 — 5,400.00 for 4,000.00 dollars — and pays its rent in Canadian dollars. Nothing foreign is ever spent, so nothing is realized, and the holding is measured against all four purchases together. The last price the book holds is the 1.50 it bought at in August, so that is what the year-end sheet prices the whole holding at:

```
	realized_gains_fx: 0.00 CAD
	unrealized_gains_fx: 600.00 CAD
	total_assets: 9400.00 CAD
```

4,000.00 dollars that cost 5,400.00 are worth 6,000.00 at 1.50, and the 600.00 is that difference. Price the same book at its own average cost instead — 5,400.00 for 4,000.00 is 1.35 — and the figure is exactly 0.00; at 1.00 it is a loss of 1,400.00. `--fx-rates` states any of those without touching the book, which is how one ledger shows all three. A zero there would be a figure the book has, not one it is missing: the key is written because the company holds the money, whatever the money has done. The rent moves `total_assets` every time and moves no gain at all — a figure that counted Canadian movements would show here.

#### A company billing in both US and Hong Kong dollars

*[`billed_in_us_and_hong_kong_dollars.txt`](../examples/multi-currency/billed_in_us_and_hong_kong_dollars.txt)*

It invoices in Canadian, US and Hong Kong dollars and pays suppliers in each. The Hong Kong dollar is pegged to the US dollar between 7.75 and 7.85, so its Canadian rate is the US rate divided by the peg — and with the US dollar at 1.30 that is exact at each end of the band. Those are the prices the book holds, written as the fractions they are:

```
price
	commodity.namespace: "CURRENCY"
	commodity.mnemonic: "HKD"
	currency.mnemonic: "CAD"
	time: "2026-03-01 12:00:00 +0000"
	value: "1/6"
	source: "user:price-editor"

price
	commodity.namespace: "CURRENCY"
	commodity.mnemonic: "HKD"
	currency.mnemonic: "CAD"
	time: "2026-12-31 12:00:00 +0000"
	value: "26/155"
	source: "user:price-editor"
```

1/6 is the peg at 7.80, 26/155 at 7.75, 26/157 at 7.85. Holding 600.00 USD and 99,510.00 HKD at the year end, the page states each currency on its own line and adds them:

```
	unrealized_gains_assets_fx:
		commodities:
			commodity:
				commodity.mnemonic: "HKD"
				type: asset
				share_price: 26/155 # current price of commodity in balance sheet currency
				cost_bases:
					cost_basis:
						split_guid: 06f38d6ed30745c8be16b4481d6902da
						account: "Assets:HKD Bank"
						cost_basis_balance: 99510.00
						cost_share_price: 1/6
						cost_value: 16585.00 # cost_basis_balance * cost_share_price
						value: 16692.00 # cost_basis_balance * share_price
						unrealized_gains_assets_fx: 107.00 # value - cost_value
				cost_basis_balance: 99510.00 # sum of each cost_basis's cost_basis_balance
				cost_value: 16585.00 # sum of each cost_basis's cost_value
				...
				value: 16692.00 # cost_basis_balance * share_price
				unrealized_gains_assets_fx: 107.00 # value - cost_value
			commodity:
				commodity.mnemonic: "USD"
				type: asset
				share_price: 1.3 # current price of commodity in balance sheet currency
				cost_bases:
					cost_basis:
						split_guid: 905f723f4b024759bbb624d9e3d877ea
						account: "Assets:USD Bank"
						cost_basis_balance: 600.00
						cost_share_price: 1.3
						cost_value: 780.00 # cost_basis_balance * cost_share_price
						value: 780.00 # cost_basis_balance * share_price
						unrealized_gains_assets_fx: 0.00 # value - cost_value
				cost_basis_balance: 600.00 # sum of each cost_basis's cost_basis_balance
				cost_value: 780.00 # sum of each cost_basis's cost_value
				...
				value: 780.00 # cost_basis_balance * share_price
				unrealized_gains_assets_fx: 0.00 # value - cost_value
		cost_value: 17365.00 # sum of each commodity's cost_value
		value: 17472.00 # sum of each commodity's value
		unrealized_gains_assets_fx: 107.00 # value - cost_value
	unrealized_gains_liabilities_fx: 0.00 CAD
	unrealized_gains_fx: 107.00 CAD # unrealized_gains_assets_fx + unrealized_gains_liabilities_fx
	realized_gains_fx:
		realized_gains_fx: 110.00
		splits:
			split:
				date: 2026-07-01
				account: "Income:FX Gain"
				amount: 60.00
			split:
				date: 2026-08-01
				account: "Income:FX Gain"
				amount: 50.00
```

The US dollar is priced at what it was earned at, so it has gained nothing while the Hong Kong dollar has gained 107.00 — and the same book drawn a month earlier, with the peg at 7.85, shows the Hong Kong figure at −105.64 and the US dollar still at 0.00. Drawn at a date where the US dollar is 1.40 as well, the two come to 60.00 and 1,391.00. Each currency is measured against its own cost basis and no other, which a book of one currency cannot demonstrate.

#### A Canadian company that borrows US dollars and banks the money at home

*[`us_dollars_borrowed_into_a_canadian_bank.txt`](../examples/multi-currency/us_dollars_borrowed_into_a_canadian_bank.txt)*

It borrows 1,000.00 USD and the money lands in its Canadian bank as 1,300.00 CAD, so the debt is in US dollars while the cash is in Canadian ones. The loan is still outstanding when the sheet is drawn, by which time the dollar has gone from 1.30 to 1.40.

The transaction states a Canadian figure for the debt — `value: "-1300.00"` on the loan split — and that is what lets a cost basis open on it, so what the debt has cost is measured like anything else. The figures are negative, because there a cost basis is currency owed rather than held:

```
	unrealized_gains_assets_fx:
		commodities: # there is no cost basis on the asset side
		cost_value: 0.00 # sum of each commodity's cost_value
		value: 0.00 # sum of each commodity's value
		unrealized_gains_assets_fx: 0.00 # value - cost_value
	unrealized_gains_liabilities_fx: -100.00 CAD
	unrealized_gains_fx: -100.00 CAD # unrealized_gains_assets_fx + unrealized_gains_liabilities_fx
```

The debt was drawn at 1.30 and takes 1.40 a dollar to repay, so it has cost the company 100.00 it has not paid out yet. Drawn on the day it was borrowed, both keys are 0.00: cost and value are the same figure that day.

#### …and the same loan written into the book in Canadian dollars instead

*[`a_us_loan_recorded_in_canadian_dollars.txt`](../examples/multi-currency/a_us_loan_recorded_in_canadian_dollars.txt)*

Nothing obliges a company to carry the debt in US dollars. It can write the loan into the book in its own currency, at what it was worth the day it was drawn — 100.00 USD borrowed, recorded as **130.00 CAD owed** — and plenty of books are kept exactly that way.

The liability then holds no foreign currency, so it opens no cost basis, and for as long as the loan stands the sheet says nothing about the exposure at all. Draw this book with `--as-of 2026-11-30`, the day before it is repaid, and every gain figure on the page reads zero while 130.00 CAD sits in the liabilities:

```
	unrealized_gains_liabilities_fx: 0.00 CAD
	unrealized_gains_fx: 0.00 CAD
	total_unrealized_gains: 0.00 CAD
```

The exposure has not gone anywhere. It arrives in a single entry, on the day the debt is settled — and the dollars to settle it need not be bought. A company that invoices US customers **earns** them, and what it earns carries a cost basis like anything else. This one collects 100.00 USD when the dollar is 1.40, recognising 140.00 CAD of revenue and opening a cost basis of 100.00 USD at 1.40, then settles the loan with those dollars:

```
	unrealized_gains_fx: 0.00 CAD # unrealized_gains_assets_fx + unrealized_gains_liabilities_fx
	realized_gains_fx:
		realized_gains_fx: -10.00
		splits:
			split:
				date: 2026-12-01
				account: "Expenses:Foreign exchange loss"
				amount: -10.00
	realized_gains_other: 0.00 CAD # not yet supported
	total_realized_gains: -10.00 CAD # realized_gains_fx + realized_gains_other
```

140.00 CAD of dollars extinguished a debt carried at 130.00, so the 10.00 is a loss, and the working gives the entry it came from. Drawn a day earlier, before the repayment, `realized_gains_fx` is 0.00. That one entry is the only place this book ever says the loan was foreign.

#### A company that spent US dollars without recording which purchase they came from

*[`dollars_spent_without_recording_the_purchase.txt`](../examples/multi-currency/dollars_spent_without_recording_the_purchase.txt)*

This is a bookkeeping mistake rather than a kind of trade, and it is the common one. Two separate things put this book's cost bases out of step with what it holds, and the sheet has to cope with both.

**A disposal draws a cost basis down only when it gives that basis's guid.** This company sells 3,000.00 USD as an ordinary transaction — the dollars valued at what they cost, and the 240.00 CAD it made booked straight to an income account rather than written with `$residual$` — and it gives no guid, so nothing is drawn down. Nothing refuses that: an ordinary transaction is never obliged to give one, which is why the mistake is an easy one to make. A `payment:` block spending a foreign account whose cost bases still hold a balance *is* refused, because GnuCash writes that bank split and a payment block has no way to say which cost basis it comes out of.

**An arrival opens a cost basis only where the transaction says what it cost.** The 4,000.00 USD this company borrows and the 2,080.00 USD its share sale brings in are both stated wholly in US dollars, with no Canadian figure anywhere in them and no cost written on either split, so neither opens one. `fx-balances` finds exactly two cost bases in the whole book: the 5,500.00 HKD, and the 10,000.00 USD that was bought with Canadian dollars and so says what it cost.

Between them the book claims 10,000.00 USD against its cost bases while the accounts hold 7,480.00 and owe 2,500.00.

The sheet does not price what is not there. That currency keeps GnuCash's own revaluation instead, and the working shows which figure came from where:

```
	unrealized_gains_assets_fx:
		commodities:
			commodity:
				commodity.mnemonic: "HKD"
				...
				cost_basis_balance: 5500.00 # sum of each cost_basis's cost_basis_balance
				cost_value: 1000.00 # sum of each cost_basis's cost_value
				accounts:
					account:
						guid: 7ca52b000919455bade465f3a1254114
						name: "Assets:HKD Bank"
						balance: 5500.00
				balance_value: 5500.00 # sum of account's balance for all accounts
				value: 1100.00 # cost_basis_balance * share_price
				unrealized_gains_assets_fx: 100.00 # value - cost_value
			commodity:
				commodity.mnemonic: "USD"
				type: asset
				measured_from: gnucash_revaluation # its cost bases do not account for what the accounts hold
				cost_value: 9781.60 # what its splits were recorded at, converted
				value: 10621.60 # what the accounts hold, at the sheet's price
				unrealized_gains_assets_fx: 840.00 # value - cost_value
		cost_value: 10781.60 # sum of each commodity's cost_value
		value: 11721.60 # sum of each commodity's value
		unrealized_gains_assets_fx: 940.00 # value - cost_value
	unrealized_gains_liabilities_fx: 0.00 CAD
	unrealized_gains_fx: 940.00 CAD # unrealized_gains_assets_fx + unrealized_gains_liabilities_fx
```

The Hong Kong dollars agree with their cost basis, so they are measured from it. The US dollars do not, so they are not.

**The items are what tell you which happened**, and they are on the page by default. A currency measured from its own cost bases states what they still account for as `cost_basis_balance` beside what the accounts hold as `balance_value`, and lists each basis and each account — the Hong Kong dollars above, agreeing at 5,500.00. A currency the bases cannot speak for states **`measured_from: gnucash_revaluation`** and none of those: no cost bases, no accounts, no `cost_basis_balance` and no `balance_value`, because a group with no basis behind it has nothing to put in them. It gives the cost and the worth GnuCash's own subtraction used instead, so the items still come to the 940.00 the key states.

So the line that identifies the case is `measured_from:`, not a disagreement a reader has to spot between two figures — those two figures are not on this page at all. Where you want them, `fx-balances` prints them: on this book its cost bases hold 10,000.00 USD while the accounts hold 7,480.00. [Q-044](issues/Q-044-state-a-realized-gain-with-no-took-the-residual-key-and-say-what-the-balancing-amount-is.md) says what that measurement can and cannot answer for.

**`fx-balances --verify-costs` will not find this one**, though it finds a great deal else. Its per-currency question compares what a currency's cost bases hold between them against what the ledger says arrived, less what was sold *against a cost basis* — and a disposal that gives no guid is on neither side of that subtraction, so the two agree while the dollars are gone. Run on the book above, it reports no finding and exits 0. What it catches is a balance that moved without a sale, not currency that left without one. The fix is in the ledger — give each disposal the cost basis it came out of.

#### A Canadian company that bought US-listed shares and still holds them

*[`us_listed_shares_bought_and_still_held.txt`](../examples/multi-currency/us_listed_shares_bought_and_still_held.txt)*

It buys 12 NASDAQ:AMZN at 200.00 USD when the US dollar is 1.30, so 3,120.00 CAD leaves the bank — 260.00 CAD a share — and holds every one of them at the year end, by which time the share is 280.00 USD and the dollar is 1.42. The share is priced in US dollars and the book is kept in Canadian ones, so the sheet reaches its figure through both: 280.00 USD at 1.42 is 397.60 CAD.

Shares are counted in units and priced, not converted, so they open no cost basis and keep GnuCash's own revaluation. This book holds no foreign currency at all, which is what lets the two kinds of gain be seen apart:

```
	realized_gains_fx: 0.00 CAD
	unrealized_gains_fx: 0.00 CAD
	unrealized_gains_other: 1651.20 CAD
	total_unrealized_gains: 1651.20 CAD
```

That figure can be checked against GnuCash itself. Its **Advanced Portfolio** report, run on this same book, states **Basis C$3,120.00, Value C$4,771.20 and Unrealized Gain C$1,651.20** — by arithmetic this shares no code with, value less basis where the sheet takes converted balances less summed split values. Two ways of asking, one answer.

A security's *realized* gain is a different matter: it is specified and not computed, for a reason that shows up on a book which actually sells something — see [What is not covered](#what-is-not-covered).

---

## What is not covered

- **Booking a year-end retranslation into the accounts.** `balance-sheet` states what currency still held is worth against what it cost — that is `unrealized_gains_fx`, above — but it only states it. Nothing is written to the book, no transaction is made, and the income and expense accounts are untouched. Under IAS 21 and ASPE 1651 an exchange difference on a monetary item belongs in profit or loss, so a filer who wants it booked writes that entry themselves; until they do it is a figure on the sheet and no account holds it, which is what the key exists to say.
- **A security's realized gain.** `realized_gains_other` is specified and not computed. A security disposal states its gain outright rather than using `$residual$`, so nothing in the saved transaction says which income split is that gain rather than a dividend — and an account is not one or the other because of what it is called. GnuCash's own Advanced Portfolio report gives 0.00 for it on a book this tool writes, for the same reason: a disposal valued at what the units cost leaves nothing made on the disposal, and the gain lands in that report's Income column.
- **A borrowing stated wholly in the foreign currency.** US dollars borrowed straight into a US dollar account carry no figure in the book's own currency for either side, so neither side opens a cost basis and neither the cost bases nor GnuCash can say what the debt has cost. Borrowing with Canadian dollars does open one, and is measured normally.
- **A sale that gives no cost basis.** It imports as an ordinary transaction; no cost basis is touched and no gain is computed. Name the cost basis to have the ledger check the arithmetic. `--verify-costs` does not report it either: the per-currency check compares the cost bases against what arrived less what was sold *against a cost basis*, and such a sale is on neither side — so the currency leaves the account while the cost bases go on holding it, and both sides still agree. What that check finds is a balance that moved without a sale, not currency that left without one.

---

## Related

- [`docs/issues/Q-035-usd-multi-currency-invoices-and-bills-unsupported.md`](issues/Q-035-usd-multi-currency-invoices-and-bills-unsupported.md) — the issue this implements
- [`docs/invoice-payment-reconciliation.md`](invoice-payment-reconciliation.md), [`docs/bill-payment-reconciliation.md`](bill-payment-reconciliation.md) — the single-currency payment workflows these extend
