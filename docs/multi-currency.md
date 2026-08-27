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
| **Basis balance** | how much of *one split's* currency, at *that split's* cost, has not yet been sold | the `cost_basis_balance:` KVP on that split, `fx-balances` |

They move independently. A USD invoice paid into a USD bank leaves the bank holding the money while the A/R split remains the cost basis that money carries. One bank account can hold currency from several bases at different costs. Their totals need not agree, and neither is derivable from the other.

---

## Cost bases

Every split that brings foreign currency into the book establishes a **cost basis**: so many units, at what they cost in CAD.

| how the currency arrives | the split that establishes the basis | what it cost |
|---|---|---|
| customer invoiced in USD | the invoice's A/R split, `+100.00 USD` | the CAD income booked against it |
| billed by a US vendor | the bill's A/P split, `−100.00 USD` | the CAD expense booked against it |
| USD bought with CAD | the receiving bank split, `+100.00 USD` | the CAD paid |
| USD borrowed | the receiving bank split, `+100.00 USD` | the CAD value of the liability written |
| customer overpays in USD | the credit left on A/R, `−100.00 USD`, in its own lot — unless the money landed in a USD account, which then holds it | what the payment converted at when it converted; what the record was carried at when it did not |
| paid a US vendor beyond the bill | the debit left on A/P, `+100.00 USD`, in its own lot | the same |

The **cost is not stored** where the transaction already carries it, which is nearly everywhere: it is `share_price` on the split itself when the transaction is in CAD, and on the CAD split facing it when the transaction is in the foreign currency. A stored cost that could have been read from the transaction is a second copy waiting to disagree with it. Only the basis balance is stored, as a KVP on the split, because it is the one fact the ledger does not already carry.

The exception is a transaction with no CAD figure anywhere in it — a USD invoice overpaid from a USD bank, where every split is USD and `share_price` describes a rate of 1. The overpaid credit is currency the book holds and owes back, so its cost is real all the same; with nothing converted there is no rate in the transaction to read, and the rate the record was carried at is the one the book knows. It is written on the split as `cost_basis_cost`, with its direction:

```
	Assets:Accounts Receivable USD -100.00 USD
		cost_basis_cost: "1.4 CAD/USD"
```

Where the payment *did* convert — 200 USD arriving as 274.00 CAD — nothing is stored: the credit's own value over its amount says 1.37, the rate the money actually came in at, and that is read rather than copied.

The transaction always outranks the stored cost, which is consulted only where the transaction states none. A copy can be stale, hand-edited, or left behind by a correction, and the ledger is what the book is: read first, a KVP saying 9.99 made a split that paid 135.00 CAD for 100.00 USD report 9.99, and `fx-balances`, every realized gain and the cost each later sale had to be valued at all followed it. Stating a cost on a split the transaction already prices is refused for the same reason.

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

The A/R side is valued at the **cost basis it settles** (140.00 CAD), not at the rate the money came in at, so the entry balances only once the difference is placed — here a 3.00 CAD loss, a debit on the FX account. The basis it names drops to `0.00` available: that USD has been converted and cannot be sold again.

Where it goes is said with a **split line** in the payment block — the same syntax a transaction uses, with `$residual$` taking whatever the rest of the entry leaves over. No key names an account and nothing is configured anywhere:

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

One shape is not covered by it. Where a transaction is stated in the *foreign* currency, no split carries a CAD figure of its own except the CAD ones, and the rate has to come from those — pooled, because reading whichever comes first makes the cost depend on split order. A CAD line converted at a different rate from the others therefore does move the result: `fx_two_base_splits_at_different_rates.txt` books revenue at 1.4 and a fee at 1.25 and the basis costs 25/18, or 1.3889. That is the aggregate of what the transaction actually did; the alternative is a coin toss between 1.4 and 1.25, which is worse. Write the fee as its own transaction and the question does not arise.

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

A USD invoice paid into a **USD** bank needs no rate at all, and realizes nothing: both sides carry the same cost. The A/R split stays the cost basis of that 100 USD, still showing 100.00 available, and the bank split does **not** establish a second basis — the book holds 100 USD, not 200. The money has simply moved from the receivable to the bank, carrying its cost with it.

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

which imports as `Income:FX Gain -5.00 CAD` — a 5.00 CAD gain, because a liability carried at 140.00 CAD was extinguished with cash that cost 135.00 CAD. Both bases fall to zero available. Two monetary items acquired on different dates at different rates is what creates the gap; no conversion to CAD is involved.

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

Each receiving split establishes its own basis — 100 USD at 1.35 and 100 USD at 1.30 — and the bank account now holds 200 USD carrying two different costs. Two bases at the *same* cost also stay two: each split is its own basis, with its own basis balance.

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

**One lump of currency is listed once.** Where the money lands decides which split carries the basis, and the credit on a receivable is not automatically it:

| how the prepayment arrives | the basis is on | why |
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

That receivable's basis was opened when the invoice was posted, so counting the credit as well would offer 200.00 USD from a book holding none.

**A refund is the mirror, and it needs `lot_owner:` for the same reason.** It is a debit on the receivable — the direction that normally establishes a basis — but it sends the customer's own money back rather than bringing any in. Naming the owner puts it in the lot no invoice owns, which is what marks it a refund, and it then establishes nothing; counting it because debits are the normal direction offered a third 100.00 USD that had already left the book.

Naming no owner, it is read as a receivable written by hand and does establish one — because that is the other thing those three lines are, exactly as a lot-less credit is read as a settlement. Neither side guesses: the file says which it is, or it gets the reading its shape gives it.

The payable side works the same way in reverse. What is owed to a vendor sits on the credit side and always establishes a basis; a **debit** on a payable is either money sent to settle a bill (establishes nothing — that currency has gone) or a prepayment to a vendor (a claim on them, which does). Again the lot decides, not the direction.

Prepaying a vendor out of USD the book already holds moves the basis across rather than adding one: the claim on the vendor is where that currency now is, and the bank split that sent it is a spend like any other, so it names the basis it spends and that basis goes to zero. Written without naming one, nothing is drawn down and the listing keeps offering the bank's basis — 200.00 USD against 100.00 held — which is the same rule as any sale that names no basis rather than an exception to it.

An update writes prepayments on the same terms: `lot_owner:` on a split an edit creates puts it in the owner's lot exactly as a fresh import would, and a split already in a lot keeps the one it has, so re-importing an exported prepayment over itself opens no second lot.

### Spending a credit on a later invoice

`auto_apply_credit: true` on an invoice pays it out of what the customer has already overpaid, and the basis follows what is left of that credit. GnuCash does not set the applied part aside: it reduces the credit's split to the part being spent and carves the rest into a new split of the same transaction, so 100.00 USD of credit meeting a 40.00 USD invoice becomes a 40.00 split and a 60.00 one.

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

`credit_dated:` is the day the currency arrived, not a day anything was paid — applying a credit writes no transaction, so the book has no date for it to state. That the split settled an invoice out of credit at all is recorded on it when the credit is applied (`applied_from_credit`), because nothing about the split afterwards distinguishes it from a bank payment's, and where a deposit is taken and an invoice posted against it the same day, not even the dates do. Re-importing that block attaches the same split to the same lot, which keeps the basis where the book put it; asking for the application again instead would let the engine choose a different credit, and re-applying one already applied leaves invoices whose lots GnuCash drops on load, taking their basis with them.

### Securities are not foreign currency

A basis is only ever established for a **currency**, and what decides that is the commodity the split holds — its namespace — not how its account is typed. Shares are counted in units and priced rather than converted, and a book holding them has no FX question to answer, so a security establishes nothing: testing "not the book's currency" alone swept them in, and a plain stock purchase in a single-currency book grew a cost-basis KVP, listed in `fx-balances` as `50 CAD/USTECH`, and could no longer be corrected with `--strategy update`.

The same rule read the other way: an account **typed** `Stock` or `Mutual Fund` but denominated in USD holds foreign currency, and its splits establish bases like any bank account's. Judging by account type instead left such a book reporting no cost basis at all with 100.00 USD in it.

---

## Listing what is held: `fx-balances`

```
$ gnucash-plaintext fx-balances book.gnucash
DATE         SPLIT GUID                         ACCOUNT                       COST       ACQUIRED  BASIS BALANCE
----------------------------------------------------------------------------------------------------------------
2026-01-10   6b2d279090974d34b37da8b1a62abfd8   Assets:Bank:USD       1.35 CAD/USD     100.00 USD     100.00 USD
             Buy 100 USD at 1.35
2026-01-20   ab1df82af72741038ad02564b97eb625   Assets:Bank:USD        1.3 CAD/USD     100.00 USD     100.00 USD
             Borrow 100 USD at 1.30

Total USD basis balance: 200.00 USD
```

`--currency USD` narrows it; `--with-balance-only` hides exhausted bases. The listing is read-only and in no imposed order: a sale names the basis it measures against, so no basis is ahead of another and sorting by date would suggest an order of consumption that does not exist. The split guid is the handle a sale uses, and the cost carries its own direction — CAD per unit of the currency held — so it is never a bare number to be interpreted.

**`none recorded`** in the basis balance column means this tool never wrote a balance for that basis — the split was made in the GnuCash GUI, or predates this feature. It is not read as "all of it left": how much has already been sold is not known, and assuming the full amount would re-open currency that may be long gone. Selling against such a basis is refused and it is left out of the totals.

**`--verify-costs`** asks whether the book agrees with itself. A cost is derived from the ledger and never asserted by this tool, so it is exactly as right as the ledger is consistent. Two things are checked, and each can fail:

| checked | what a failure means |
|---|---|
| a basis balance is not above what its basis brought in, and not below zero, and reads as a number at all | a balance moves only by what a sale takes and what one gives back — so a balance above what arrived is currency offered that never did, and one below zero is a sale no ledger records. Two exact comparisons against figures the book holds, with no tolerance in them. A balance that will not parse lists as `none recorded`, because nothing can be sold against it either way — but it is not the same as never having had one, so `--verify-costs` reports it with the text it actually holds rather than passing over it |
| a stored `cost_basis_cost` parses, and agrees with the transaction | nothing writes one where the transaction states a cost, so both means a copy has drifted — and the transaction is what is used |

Both are questions about one split. A book can pass every one of them and still not add up, so the run also asks the book-wide one, **per currency**: what a currency's bases hold between them, against what the ledger says arrived less what was sold against a basis.

The two sides are written by different mechanisms — a KVP on each split, and the transactions themselves — so they can disagree, and neither is derived from the other. Take 80.00 USD off one basis of a book holding 200.00 and record no sale: every basis is still within its own bounds, `--verify-costs` says every cost agrees with the figures it is derived from, and 80.00 USD is accounted for by nothing.

```
warning: the USD cost bases hold 120.00 USD between them, and the ledger says
200.00 USD arrived and 0.00 USD was sold against a basis — leaving 200.00 USD.
  80.00 USD is accounted for by no basis. A balance was lowered without a sale
  to lower it, or a sale gave back less than it took.
  Nothing is refused: every basis is within its own bounds, and which side is
  right is not something the book records.
```

**A warning, and it does not set the exit code.** The book is readable and its figures are the ones it holds; what put the two sides out of step is not recorded anywhere, so the reader is the one who can say which is right. Both totals are printed rather than the difference alone, because the difference does not say where to look: short means a basis lost its balance, over means one gained currency that never arrived.

A basis with **no balance recorded** is left out of both sides. How much of it is unsold is not known — that is what `none recorded` means — so counting what it brought in would report every such book as short by exactly that; nothing can be sold against one either, so no sale goes missing with it.

Both per-basis checks are exact questions about figures the ledger states. Two inexact ones are deliberately **not** asked:

A split's `share_price` against its value. GnuCash stores no rate — `xaccSplitGetSharePrice` divides value by amount on demand — so the two are one number and comparing them always agrees. A check that cannot fail is worse than none: it reports agreement it never tested.

Whether a transaction's base-currency splits agree about its rate. **Rates run forward only.** A file states 1.405, 45.00 USD becomes 63.23 CAD, and the effective rate the ledger carries is then 6323/4500 — 1.405 plus 1/9000. That is the rounding working as it must, and reading the figure back to ask which rate produced it has no answer: many rates give 63.23, and the one the file stated is not among the things a book keeps. Every criterion tried in that direction reported correct books, so the pooled rate is used to derive a cost and nothing is inferred from it.

The run covers the whole book and exits 1 at the end if anything disagreed, rather than stopping at the first, and a basis whose own figures do not parse is reported with its traceback instead of ending the pass:

```
$ gnucash-plaintext fx-balances book.gnucash --verify-costs
…the listing…

Checked 2 cost basis(es); 1 disagree with their own figures:

2026-01-10  Assets:Bank:USD
    Buy 100 USD at 1.35
    split guid       31438b24314e495384989e74d13caa7f
    tx guid          9c0c4ce246794670856347aaf44cb69f
    amount           100.00 USD
    value            135.00 CAD   (the transaction's currency)
    available        100.00 USD
    value / amount   1.35
    computed cost    1.35 CAD/USD
    stored cost      9.99 CAD/USD
    used             1.35 CAD/USD
    - cost_basis_cost says 9.99 CAD/USD, but the transaction says 1.35 — the transaction is what is used
```

The factors listed are the ones the derivation multiplied, and only those: a transaction already in CAD has one, `value / amount`, while a USD-denominated one has that and the `CAD per USD` rate its CAD splits imply. Nothing is printed for a step that was not taken.

That rate is every base-currency split taken together — the CAD they carry over the foreign currency they are worth — not whichever split is read first. Each is rounded to the cent on its own, so an invoice's income and tax lines give slightly different ratios though both were converted at one rate: 33.33 USD at 10% tax, posted at 1.4, books 46.66 CAD over 33.33 and 4.66 over 3.33, which are 1.40006 and 1.39940. Reading one split priced the whole basis at whichever it happened to reach; summing cancels most of the rounding and cannot depend on order.

Nothing is inferred back out of those figures. A rate runs forward — the file states it, the foreign amount is multiplied by it, and the result is rounded to the unit the receiving account is held to. The effective rate the ledger then carries is that rounding's doing: 45.00 USD at a stated 1.405 books 63.23 CAD, whose ratio is 6323/4500, and that is correct rather than a discrepancy to be detected.

Where a basis is reported for something else, the splits its cost was pooled from are printed with it, at the unit each is held to — a fund account kept to thousandths carries 12.345 units, and the report says which unit that is, since three decimals otherwise read as a mistake.

Giving a basis a balance uses the mechanism that already exists — state it on the split in an import file, where a stated balance is authoritative:

```
	Assets:Bank:USD 100.00 USD
		guid: "6b2d279090974d34b37da8b1a62abfd8"
		cost_basis_balance: "100.00"
```

Authoritative, and therefore checked before it lands: it must be on a split that holds foreign currency, and then a number, not negative, no finer than the unit its own account is held to, and no more than that split brought in. Nothing downstream questions it — a sale is measured against it and valued at the basis cost — so 150.00 stated on a split that acquired 100.00 leaves 50.00 sellable that never arrived, with the gain on selling it computed against a cost that was paid. And one that does not parse states nothing: `60,00` for `60.00` used to leave the split marked as having stated a balance, so the sale below it was skipped as already accounted for while the basis opened at its full amount — forty sold USD back in the book from one wrong character.

---

## Selling foreign currency

A sale names the basis it is measured against and values what it sells at that basis's cost. What the sale fetched is on the other splits, and `$residual$` takes the difference:

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

40 USD that cost 54.00 CAD fetched 55.60, so the residual books `Income:FX Gain -1.60 CAD` — a 1.60 gain — and that basis drops to `60.00 USD` available while the other is untouched.

### Spreading a sale across several bases

The user decides which bases a sale draws on and in what amounts. Selling 200 USD can take all 200 from one basis, 100 from each of two, or 50 and 150 — one foreign-currency split per basis, each naming its own:

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

The cost consumed is 135.00 + 65.00 = 200.00 CAD against 208.50 of proceeds, so `Income:FX Gain -8.50 CAD`. The first basis has no balance left, the second keeps 50.00 USD available.

### You can only sell currency you actually hold

An invoice's A/R split states what a customer **owes**, not what the book has. Measuring a sale against it before the invoice is paid is selling money that has not arrived, so it is refused:

```
Error: cost basis <guid> is a split on 'Assets:Accounts Receivable USD', and
the invoice it belongs to has not been collected — that USD is owed, not held,
so there is none to sell. Record the payment first, or add
`cost_basis_force: true` to this split to measure against it anyway.
```

The lot is the test: it closes when the record is settled, so a paid invoice's basis is sellable with nothing extra, and a partly paid one is not. `cost_basis_force: true` on the selling split overrides it, for when the money is in hand and the record simply has not been marked paid yet.

This tool keeps books; it does not support trading a position the book does not hold. Currency bought or borrowed is in the account already and is never restricted, and a **payable** is not restricted either — its lot is open precisely until the bill is paid, and settling it with foreign cash is the ordinary way that happens.

### What is refused

| the file says | the importer says |
|---|---|
| a sale of 150 USD against a basis of 100 | `150.00 USD against cost basis <guid> exceeds its basis balance by 50.00 USD (the basis is 100.00 USD and 0.00 was already used)` |
| a sale against an invoice that is not yet paid | `cost basis <guid> is a split on 'Assets:Accounts Receivable USD', and the invoice it belongs to has not been collected — that USD is owed, not held, so there is none to sell…` |
| a cost other than the basis's | `this split sells 100.00 USD valued at 120.00 CAD, but cost basis <guid> cost 1.35 CAD per USD, i.e. 135.00 CAD — value what is sold at the basis it picks, so the CAD the sale fetched and the residual gain or loss stand apart` |
| a guid matching no split | `cost_basis_split_guid '<guid>' matches no split in the book` |
| a guid matching a split that holds no foreign currency | `cost_basis_split_guid '<guid>' matches a split that is no USD cost basis — a basis is a split that brought USD into the book (an invoice, a bill, a purchase or a borrowing)` |
| a basis with no balance recorded | `cost basis <guid> has no balance recorded — the split was not written by this tool, so how much of its USD is still unsold is not known and cannot be assumed to be all of it…` |
| a `payment:` block spending a foreign account whose bases still have a balance | `this bill pays 100.00 USD out of 'Assets:Bank:USD', whose cost bases still have 200.00 USD of balance between them, and spending that has to say which cost basis it comes out of. A payment block cannot — GnuCash writes its bank split. Write the settlement as an ordinary transaction with cost_basis_split_guid: on the bank line and attach it with txn_guid: / txn_split_guid:` |
| a settlement into a foreign bank with no rate for **that bank's** currency | `this invoice is in USD and settles into HKD, so valuing the cash needs the HKD/CAD rate on 2026-02-25, which the rates file does not carry: …` |
| a CAD invoice settled into a foreign bank | `invoice INV-…: this payment settles a CAD invoice into a HKD account. Nothing is realized — CAD does not move against itself — and what the HKD cost belongs to that account, recorded where the currency was bought, not to this invoice. Settle it from a CAD account, or record the HKD purchase as its own transaction.` |

The first of those three is the one most likely to meet an existing ledger, and it is asked of **every** foreign bank rather than only one in a third currency — paying a USD bill out of a USD bank whose bases still have a balance reaches none of the cross-currency arithmetic and drifts just the same, so the question is asked before it. A foreign account gets its first basis as soon as something opens one, and a settlement landing in it is one such thing; README's foreign-currency section shows the ordinary transaction that replaces the payment block.

Nothing is written when a sale is refused: the bases keep their balances. Every figure a file states about a cost basis is checked before any balance moves — a stated cost and a stated basis balance are both parsed before the transaction is even created, every pick is validated before the first drawdown, and a payment's split lines are judged before the settlement draws anything down — so a refused sale leaves the ledger exactly as it was.

A refusal that can only come later is caught by one of two different mechanisms, depending on what was being imported, and it is worth knowing which:

| what is refused | what happens to what it drew |
|---|---|
| a **transaction** | it is destroyed and what it drew is given back with it, and the rest of the file lands as normal |
| a **payment inside an invoice or bill** | the whole import is abandoned: the book is left exactly as it was found, and nothing else from that file is written either |

Both leave every basis where it was, which is the guarantee that matters, but they are not the same behaviour and a file half-lands in neither case. The second is the blunter of the two — a settlement values itself against the basis it consumes, so what a refusal after that point would have to give back is not one drawdown but everything the invoice has done, and abandoning the book is the only answer that cannot leave the two disagreeing.

Measured on a book holding 200.00 USD across two bases: a file carrying an invoice whose converting payment realizes 3.00 CAD with no split to take it, and an ordinary CAD transaction beside it, is refused with `settling this USD invoice into CAD realizes 3.00 CAD … add a split to the payment block`. Afterwards `fx-balances` reports the same 200.00 USD across the same two bases, and the ordinary transaction is not in the book either — the file landed in full or not at all.

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
DATE         SPLIT GUID                         ACCOUNT                       COST       ACQUIRED  BASIS BALANCE
----------------------------------------------------------------------------------------------------------------
2026-01-10   6b2d279090974d34b37da8b1a62abfd8   Assets:Bank:USD       1.35 CAD/USD     100.00 USD     100.00 USD
             Buy 100 USD at 1.35
2026-01-20   ab1df82af72741038ad02564b97eb625   Assets:Bank:USD        1.3 CAD/USD     100.00 USD     100.00 USD
             Borrow 100 USD at 1.30

Total USD basis balance: 200.00 USD
```

**3. Sell 150 USD at 1.39, taking all of the bought USD and half the borrowed.** Which bases the sale is measured against is the user's choice, and it is what decides the gain — the same 150 USD taken entirely from the 1.35 basis would realize less:

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

**4. What the ledger now says.** 200.00 CAD of cost consumed against 208.50 of proceeds, so the residual booked `Income:FX Gain -8.50 CAD` — an 8.50 CAD gain — and the bases record what is left:

```
$ gnucash-plaintext fx-balances book.gnucash --with-balance-only
DATE         SPLIT GUID                         ACCOUNT                       COST       ACQUIRED  BASIS BALANCE
----------------------------------------------------------------------------------------------------------------
2026-01-20   ab1df82af72741038ad02564b97eb625   Assets:Bank:USD        1.3 CAD/USD     100.00 USD      50.00 USD
             Borrow 100 USD at 1.30

Total USD basis balance: 50.00 USD
```

The bank account holds 50 USD and the one remaining basis has 50 USD available — here they agree, because every USD in the account came from a basis in the account. They would not agree if a USD invoice were still outstanding: that A/R basis holds USD the bank has not received yet.

**5. Repaying the borrowing** with the USD still held is the same shape as settling a USD bill with USD cash, above: name the basis the cash comes from, value it at that basis's cost, and let `$residual$` book the difference against what the loan was written at.

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

The coarser of the two, in both directions. An account kept to whole dollars refuses 18.19 as well — a fine number of Canadian dollars and not a number of *those* — rather than rounding it to 18 and leaving GnuCash to park the difference in `Imbalance-CAD` under a summary reporting no errors.

---

## Correcting things

**Deleting a sale gives the currency back.** The delete reads what the transaction took from each basis it named, then raises those balances by exactly that much — capped at what the basis brought in, so a balance can never exceed the currency the split carried:

```bash
gnucash-plaintext delete-transactions book.gnucash --by-guid <the sale>
```

```
Total USD basis balance: 200.00 USD          # was 160.00 while the 40 USD sale existed
```

The basis is immediately sellable in full again. This is what makes the feature safe to experiment with: any sale can be undone, and the deletion prints a plaintext copy of what it removed so it can be re-imported.

**Unposting a record whose basis is in use is refused.** A posted record's A/R or A/P split *is* the cost basis, and unposting destroys the posting transaction:

```
Error: invoice 'INV-USD-001' cannot be unposted: its cost basis is what 1
transaction(s) measure against — 2026-02-01 'Sell 40 USD' (40.00 USD).
Unposting destroys the split that basis lives on, and re-posting creates a new
one with the whole amount available again, so those transactions would be
measured against a cost basis the book no longer has. Remove or re-point them
first.
```

Without that guard, unposting and re-posting silently reset a basis to its full amount — a book that had sold 40 of 100 USD would claim 100 USD available, currency it no longer has. Delete the sales first (they come back as plaintext), then unpost; the order is: undo the sales, undo the payment, unpost. A basis nothing measures against unposts freely, and single-currency records are unaffected.

**Deleting the transaction that establishes a basis in use is refused** for the same reason: the sales measuring against it would be left naming a guid the book no longer holds.

### Editing with `--strategy update`

`import --strategy update` is the export → edit → re-import loop, and it is the path the tool itself recommends whenever a guid-matched transaction's content differs. Every rule that governs a sale on the way in governs it on the way back, so what an edit may change depends on whether a cost basis rests on it:

| the edit | what happens |
|---|---|
| a memo, description, action, date or doc_link | goes through — none of them can change what a basis holds or what it cost |
| an amount, value, account, or the basis a split picks | refused, naming the transaction and the route that works |
| a transaction that touches no basis at all | ordinary; the update path is unrestricted |

```
Error: transaction <guid> touches a cost basis, so its amounts, values,
accounts and basis picks cannot be edited in place — a memo or description
can. Delete it and import the new version instead: `delete-transactions
--by-guid <guid>` gives the basis back exactly what this transaction took, and
the fresh import checks the new figures against it.
```

The reason is that the checks governing a sale run over a transaction's splits once they are book state, and an in-place edit has already overwritten what the old amounts drew before anything can re-check them. Left alone, that accepted a sale of 400.00 USD against a basis holding 60.00, reported `Updated: 1`, and left the basis still reading 60.00. Delete-and-reimport reaches the same end state with every check applied.

An update can also *bring currency into the book* — a CAD placeholder corrected into `Assets:Bank:USD 100.00 USD`, or reversed signs fixed so a split becomes a purchase — and that currency opens a basis exactly as a fresh transaction's would. What matters is whether the split was a basis before the edit, not whether the split existed: splits are matched by account, so correcting reversed signs reuses the very same split, same guid. A split that was already there and carries no balance keeps **none recorded** — correcting a description was once enough to open every such basis in a book at its full amount.

`--strategy update` requires a `guid:` on every transaction in the file, so an edited export can be re-imported wholesale but a file cannot mix edits with newly written transactions. A transaction whose guid the book does not hold is refused rather than created, which is what stops a deleted sale from being re-imported and taking its basis down a second time.

## Round-trip

A realized settlement round-trips without restating anything: the export writes the payment as a link to the transaction it already emitted (`txn_guid:` + `txn_split_guid:`), so the fresh book inherits the FX split, the A/R value at cost, and the basis at zero available — and needs no rates file to rebuild them.

`cost_basis_split_guid:` and `cost_basis_balance:` are ordinary KVP slots, so they survive export → fresh-book re-import like any other custom metadata. **A balance stated in a file is authoritative and already net of that file's own sales** — an export carries `cost_basis_balance: "60.00"` on a basis alongside the 40 USD sale that lowered it — so re-importing an export leaves it at 60.00 rather than taking the 40 again. A sale imported against a basis the book already held is a new sale and does lower it. A stated balance only counts once its transaction is actually in the book: a transaction that fails and rolls back takes its splits' guids with it, so a sale further down the same file naming that basis is refused for a basis the book does not have.

`txn_type: P` round-trips on every supported version, which matters because a re-imported payment that is not a payment to the engine is invisible to `find-orphan-payments`. The importer writes it onto the transaction with `xaccTransSetTxnType`, which stores it in a KVP slot; GnuCash 3.8 and 4.4 read that slot back, while from 4.13 `xaccTransGetTxnType` derives the type from the transaction's splits and lots and never consults it. So the export takes the C field when it is set and falls back to the slot when it is not, and a type GnuCash does not know (`txn_type: Z`) is refused rather than written into engine state, where a typo would export straight back out.

An export that carries business objects emits the book's whole chart of accounts, so it is always re-importable — an invoice reaches accounts no transaction split touches, and an unposted one has no posting transaction to drag them in.

---

## Reports

| command | what it does with foreign currency |
|---|---|
| `income-statement` | reports the CAD revenue and expense already booked — 140.00 CAD for the USD invoice above. No rate needed for that figure |
| `balance-sheet` | consolidates each account's own-currency balance at the `--fx-rates` rate: 200 USD held reads 274.00 CAD at 1.37, and the sheet balances |
| `account-balance` | same, per account: `Assets:Bank:USD 274.00 CAD`, showing the 200.00 USD original |

Each reads the **amount** on a split — the figure in the account's own commodity — not its value, which is stated in the transaction's currency. Those differ the moment a transaction crosses currencies: a CAD income account credited by a USD invoice holds a split whose amount is the CAD revenue and whose value is the USD invoice total.

---

## What is not covered

- **Year-end retranslation of held currency.** Currency still held has not been converted; the cost basis is what it cost. `balance-sheet` presents holdings at the rate you give it, which is a presentation choice, not a booked gain.
- **A sale that names no cost basis.** It imports as an ordinary transaction; no basis is touched and no gain is computed. Name the basis to have the ledger check the arithmetic. `--verify-costs` does not report it either: the per-currency check compares the bases against what arrived less what was sold *against a basis*, and such a sale is on neither side — so the currency leaves the account while the bases go on holding it, and both sides still agree. What that check finds is a balance that moved without a sale, not currency that left without one.

---

## Related

- [`docs/issues/Q-035-usd-multi-currency-invoices-and-bills-unsupported.md`](issues/Q-035-usd-multi-currency-invoices-and-bills-unsupported.md) — the issue this implements
- [`docs/invoice-payment-reconciliation.md`](invoice-payment-reconciliation.md), [`docs/bill-payment-reconciliation.md`](bill-payment-reconciliation.md) — the single-currency payment workflows these extend
