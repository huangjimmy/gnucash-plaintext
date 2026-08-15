
# gnucash-plaintext

gnucash plaintext is an app that can

* load a .gnucash file and then export a [GnuCash](https://www.gnucash.org/) plaintext ledger file
* load [GnuCash](https://www.gnucash.org/) plaintext ledger file and export a [beancount](https://github.com/beancount/beancount) compatible .beancount file
* read from a [GnuCash](https://www.gnucash.org/) plaintext transaction file and create transaction in .gnucash file
* bidirectional conversion between GnuCash and [GnuCash-Beancount](docs/gnucash-beancount-format.md) format with zero data loss for accounts, transactions, splits, commodities, and prices (business objects and custom KVP slots are not preserved; see [Limitations](docs/gnucash-beancount-format.md#limitations))

## Motivation

### The everyday problem: GnuCash is great for entry, painful for bulk work

I have used GnuCash for decades to track expenses, income, and investments. The
GUI is excellent for the way most transactions actually arrive in your life —
you sit down, enter a few items, reconcile a statement. But the moment the work
is *bulk* or *programmatic*, the GUI becomes the bottleneck:

- Importing a month of QFX entries and re-categorising 80 of them
- Renaming an account that's used in thousands of splits
- Fixing a typo across every invoice from a single vendor
- Generating recurring bills from a spreadsheet
- Asking an AI to clean up memos, propose categorisations, or sanity-check a
  reconciliation

For all of these, you want **text**. You want grep, sed, scripts, diffs,
version control, and nowadays an LLM that can read and edit your ledger
directly. GnuCash's XML file is technically text, but it's not
human-editable — one wrong tag and the whole file is unusable.

### The fix: a stable Export → edit → Import cycle

`gnucash-plaintext` gives you a round-trippable plaintext format for your
GnuCash file. The workflow is:

1. **Export** your `.gnucash` file to plaintext.
2. **Edit** the text however you like — by hand, with a script, by piping it
   through an LLM, or as part of a larger tool chain.
3. **Import** back into GnuCash. Accounts, transactions, splits, commodities,
   prices, customers, vendors, invoices, bills, and payments all round-trip
   without loss.

Because every object carries its GnuCash GUID through the cycle, edits target
the *same* underlying objects on re-import — no duplicates, no orphaned
records. You keep using the GnuCash GUI for day-to-day entry, and reach for
plaintext only when the job is bigger than a few clicks.

### Bonus: Fava visualisation and long-term portability

Two further things fall out of this design almost for free:

- **Fava in your browser.** The same tool can export to a beancount-compatible
  format, so you can point [Fava](https://github.com/beancount/fava) at your
  GnuCash data and get a modern web UI for analysis and reporting without
  leaving GnuCash for entry.
- **A future-proof copy of your data.** GnuCash was first committed in 1997
  and is still actively developed, but if it ever did go away, a plaintext
  ledger remains readable by humans and by every accounting tool that supports
  beancount-like formats. The same cycle that powers your weekly bulk edits
  doubles as a long-term escape hatch.

### How this came about

I tried [ledger-cli](https://ledger-cli.org/doc/ledger3.html) and
[beancount](https://github.com/beancount/beancount) when I first wanted
plaintext accounting, but neither was a clean migration target. Beancount in
particular has gaps that matter for a GnuCash user: business objects
(customers, vendors, invoices, bills, payments) have no equivalent, GnuCash's
KVP slots and multi-namespace commodities don't map cleanly, and I have years
of GnuCash reports I'm unwilling to redo.

Account names with spaces and CJK characters used to be a hard blocker too —
beancount v2 rejects them — but that's no longer true in v3, which uses a
UTF-8-aware scanner ([beancount#398](https://github.com/beancount/beancount/issues/398)).
[rustledger](https://github.com/rustledger/rustledger), a Rust implementation
of beancount, has landed the same support
([rustledger#817](https://github.com/rustledger/rustledger/pull/817)). So if
your only need is "let me edit my ledger as text", a beancount-native workflow
is now genuinely viable.

What's still missing from a beancount-only setup is the GnuCash side itself:
the entry GUI, the business objects, the existing reports, the on-disk format
my partner and accountant already know. Instead of migrating *away* from
GnuCash, I built a plaintext layer *on top of* it — close enough to beancount
that Fava and related tooling still work, but lossless against GnuCash so the
GUI remains the source of truth.

## Concepts


| Concept                                             | Description                                                                                                    |
|-----------------------------------------------------|----------------------------------------------------------------------------------------------------------------|
| .gnucash file                                       | An XML file with extension .gnucash that GnuCash stores accounts and transactions information                  |
| GnuCash plaintext ledger file                       | Introduced by gnucash plaintext, It is a beancount-like bookkeeping language in a text file.                   |
| [beancount](https://github.com/beancount/beancount) | A double-entry bookkeeping computer language that lets you define financial transaction records in a text file |
| [GnuCash-Beancount](docs/gnucash-beancount-format.md) | A special beancount format with GnuCash metadata that enables bidirectional conversion with zero data loss |

## GnuCash plaintext

GnuCash plaintext is inspired by beancount, and it aims to be compatible with beancount as much as possible.

Right now, GnuCash plaintext supports GnuCash `Account`, `Commodity`, `Transaction`, and `Split`.

| GnuCash concept supported by GnuCash plaintext    | beancount corresponding concept                   |
|---------------------------------------------------|---------------------------------------------------|
| Account                                           | Account                                           |
| Commodity / Currency                              | Commodities / Currencies                          |
| Transaction                                       | Transaction                                       |
| Split                                             | Posting (of Transaction)                          |
| Document Link (of a transaction)                  | N/A                                               |
| N/A                                               | Documents (attached to the journal of an account) |
| Properties of Account/Commodity/Transaction/Split | Metadata                                          |
| Custom metadata (KVP slots)                       | Metadata (open-ended key: value pairs)            |



### Accounts

Like beancount, you can `open` and account with open directive. 
You also open an account with `open` but in GnuCash plaintext, 
you need to specify additional attributes, a.k.a. metadata in beancount.

These attributes are required in GnuCash plaintext.

Unlike beancount, accounts are not inferred from its prefix to determine its type. 
You shall specify Account type in `type` attribute.

Also, GnuCash allow spaces, tabs and special chars in account names, so anything after the `open` directive will be considered
account name. You will not be able to use `USD` at the end of account name to define constraint currency of accounts
like you do in beancount `2014-05-01 open Liabilities:CreditCard:CapitalOne     USD`. This is still valid
in GnuCash plaintext, but it will be interpreted as you open account `Liabilities:CreditCard:CapitalOne     USD` on
2014-05-01.

Supported `type` values are the GnuCash account types (case-sensitive):

- Asset side: `Asset`, `Bank`, `Cash`, `Stock`, `Mutual Fund`, `Accounts Receivable`
- Liability side: `Liability`, `Credit Card`, `Accounts Payable`
- `Equity`, `Income`, `Expense`

`Accounts Receivable` and `Accounts Payable` also accept the GnuCash short forms `A/Receivable` / `A/Payable` and the bare `Receivable` / `Payable`. An unrecognised `type` is reported in the import summary (and the account is skipped), so a typo never silently lands an account with no type.

Also, you cannot declare top level accounts such as `Expenses` in beancount, but you
need to `open` `Expenses` account first before you can open `Expenses:Groceries & Household` in GnuCash plaintext.

```
2012-11-02 open Expenses:Groceries & Household
	type: "Expense"
	placeholder: #False
	code: ""
	description: "Groceries"
	color: #None
	notes: #None
	tax_related: #False
	commodity.namespace: "CURRENCY"
	commodity.mnemonic: "CNY"
```

### Commodities and Currencies

You can also declare commodities similar to beancount, 
but you need to declare additional attributes.

Since GnuCash by default include many currencies, you do not need to declare
many currencies explicitly.

```
2010-06-30 commodity CNY
	mnemonic: "CNY"
	fullname: "Yuan Renminbi"
	namespace: "CURRENCY"
	fraction: 100
```

For `namespace: "CURRENCY"` commodities, the importer honors your declared `fraction` in memory, but GnuCash 5.15+ subsequently normalises ISO 4217 currencies to their official smallest-unit value on save. The most visible case is KRW (Korean Won): old GnuCash shipped it with `fraction: 100`, but [GnuCash 5.15 corrected it to `fraction: 1`](https://github.com/Gnucash/gnucash/releases/tag/5.15) (Bug 666536 — KRW has no sub-units per ISO 4217). On 5.15+, declaring `KRW fraction: 100` parses successfully but the saved book will hold `fraction: 1`. If you genuinely need a non-ISO precision (e.g. a points/rewards "currency"), use a custom `namespace:` (anything other than `CURRENCY`) — GnuCash never normalises user namespaces.

However, if you need to support Stocks, for example, 
your broker supports fractional trading of AMZN.

Below declaration support trading of AMZN stock at 0.000001 share.

```
1997-06-30 commodity AMZN
	mnemonic: "AMZN"
	fullname: "Amazon Inc"
	namespace: "NASDAQ"
	fraction: 100000
```

You may declare Bitcoin like below

```
2010-06-06 commodity BTC
	mnemonic: "BTC"
	fullname: "Bitcoin"
	namespace: "Crypto"
	fraction: 100000000
```

### Transactions

A transaction is also declared similar to beancount, but with some differences.

* You need to use `*` to follow date, you will not be able to use `txn`.
* Beancount calls `Transaction Num` as `Payee`, `Transaction Description` as `Narration`
* You are required to specify `currency.mnemonic` as each GnuCash transaction has its `transaction currency`
* Each Split has its own `account.commodity.mnemonic`, `share_price`, `value`, etc. `account.commodity.mnemonic`, `share_price`, and `value` are optional if `account.commodity.mnemonic` is the same as `currency.mnemonic` and `share_price` equals 1
* Split action and memo are optional

```
2024-03-14 * "Transaction Num" "Transaction Description"
	currency.mnemonic: "CAD"
	notes: "Transaction Notes"
	Expenses-CAN:Groceries 29.27 CAD
		account.commodity.mnemonic: "CAD"
		share_price: "1"
		value: "29.27"
		action: "Split Action"
		memo:"Split Memo"
	Liabilities:Credit Card:PC-1010 -29.30 CAD
		account.commodity.mnemonic: "CAD"
		share_price: "1"
		value: "29.27"
		action: "Split Action"
		memo:"Transaction: Mar 14, 2024 9:34 PM Posted: Mar 15, 2024"
	Expenses-CAN:Sales Tax:GST 0.01 CAD
		account.commodity.mnemonic: "CAD"
		share_price: "1"
		value: "0.01"
	Expenses-CAN:Sales Tax:BC PST 0.02 CAD
		account.commodity.mnemonic: "CAD"
		share_price: "1"
		value: "0.02"
```

### Splits

A split is part of a transaction that associated with one account.
Please note that a transaction has its own currency and each split has its own currency too.

You are required to declare `currency`, `share_price` and `value`
in GnuCash plaintext, otherwise, GnuCash plaintext may not be able to correctly create transactions in GnuCash Xml File ( .gnucash )
You do not need to provide `account.currency` since it is inferred from the associated account.

There are two splits in the following transaction.

please note that share_price in first split "368/2170" means 

1 (share_price) `HKD` ( account.commodity.mnemonic ) = 368/2170 `CAD` ( currency.mnemonic )

The second split has the same account.currency CAD as currency, so

1 ( share_price ) `CAD` ( account.commodity.mnemonic ) = 1 `CAD` ( currency.mnemonic )

Formula `value` = `share_price` * Split_Amount, e.g., 3.68 = 368/2170 * 21.70

```
2023-06-30 * "CITYBUS 03700 HKG HKD 21.70"
	guid: "b1fd9fb8359043dc8802a5f6b530bd9c"
	currency.mnemonic: "CAD"
	Expenses-HK:Public Transportation 21.70 HKD
		guid: "90ed3907566242e6a06b711317e29e2b"
		account.commodity.mnemonic: "HKD"
		share_price: "368/2170"
		value: "3.68"
	Liabilities:Credit Card:HSBC-Premier -3.68 CAD
		guid: "094beddc459148d78a514c48b0c3a91b"
		account.commodity.mnemonic: "CAD"
		share_price: "1"
		value: "-3.68"
```

### Foreign currency

The book reports in CAD. Currency in any other denomination is held at a **cost basis**: so many units, at what they cost in CAD. Every split that brings foreign currency in establishes one — an invoice's A/R split, a bill's A/P split, currency bought or borrowed — and selling that currency is measured against the bases it came from.

**Invoicing in USD.** An invoice posts only to an A/R account in its own currency (the rule GnuCash's own post dialog enforces); posting a USD invoice to a CAD A/R is refused, because the engine takes no exchange rate and would write an A/R split of zero whose lot closes on its own posting date. The revenue is still recognised in CAD, at the invoice's posting-date rate, which is what a CRA filing needs:

```
2026-01-05 * "INV-USD-001" "Invoice INV-USD-001"
	currency.mnemonic: "USD"
	Assets:Accounts Receivable USD 100.00 USD
		cost_basis_balance: "100.00"
	Income:Sales -140.00 CAD
		share_price: "10000/14000"
		value: "-100.00"
```

That rate comes from `--fx-rates` on `import`, and importing a foreign-currency invoice or bill without one is an error rather than a posting the engine silently abandons. Bills work the same way in mirror: a USD bill posts to a USD A/P account and books its expense in CAD.

**Paying across a currency boundary.** A payment states its `amount:` in the record's own currency, so when the money lands in another currency something must say what that side received. Write what your bank statement shows:

```
	payment:
		date: 2026-02-25
		amount: 100                         # 100.00 USD off the invoice
		account: "Assets:Bank"
		settled_amount: 137.00              # what actually landed in the CAD bank
		memo: "Payment for INV-USD-001"
		Income:FX Gain $residual$ CAD       # where the 3.00 CAD realized loss lands
```

`share_price: "1.37"` states the same thing as a rate, meaning what it means on any split — one unit of the record's currency in units of the account's. Either one is required when the two currencies differ, both are rejected when they match, and giving both is fine only if they agree. Nothing is looked up: a payment records what actually happened, and only the payer knows what their money converted at.

Settling at a rate other than the one the record was booked at **realizes a gain or loss**: revenue recognised at 1.40 against 137.00 CAD received is a 3.00 CAD loss on the settlement date. The A/R side of the payment is valued at the cost basis it settles, so the entry balances only once that difference is placed — which the block does with an ordinary **split line**, the same syntax a transaction uses, and `$residual$` works there exactly as it does anywhere else. No key names an account and nothing is configured. That line is the only one a payment block may carry: the realized difference is the one figure in the entry that moved no money, and anything that did — a wire fee is a bank debit — is imported as its own transaction, so it cannot quietly change the rate the settlement converted at. `$residual$` must post to an income or expense account, since a realized difference is a gain or a loss; anywhere else absorbs it into the balance sheet. A settlement that realizes something without a split to take it is refused. The basis it settles drops to zero available — that currency has been converted and cannot be sold again. Settling in the record's own currency realizes nothing, and split lines belong to the cross-currency settlement alone: a payment that settles in its own currency, or one attached to an existing transaction with `txn_guid:`, is refused if it carries them rather than accepting the file and dropping them. Write that payment as an ordinary transaction, where any number of splits is ordinary, and attach it. On a transaction, where a split line does state an amount, one its currency cannot hold — `2.005 CAD`, half a cent — is refused rather than rounded on your behalf: a figure the file states is honoured or refused, which is the opposite side of the same rule that has GnuCash round a *computed* figure like 45.00 USD at 1.405 to the cent.

**Selling foreign currency.** The sale names the cost basis it is measured against, on its own foreign-currency split, and values what it sells at that basis's cost. What the sale fetched is on the other splits, and `$residual$` takes the difference — the realized gain or loss:

```
2026-03-01 * "Sell 100 USD"
	currency.mnemonic: "CAD"
	Assets:Bank:USD -100.00 USD
		share_price: "1.40"                        # the cost the basis carries
		value: "-140.00"
		cost_basis_split_guid: "c4ccb16d7be34e15a112d903319c5267"
	Assets:Bank 139.00 CAD                         # what the sale fetched
	Income:FX Gain and Loss $residual$ CAD         # the 1.00 CAD loss falls out
```

A sale measured against two bases carries two foreign-currency splits, one naming each, and each split's amount is how much of that basis it uses — 200 USD can be taken entirely from one basis, 100 from each of two, or 50 and 150. Selling more than a basis has available is refused on import, and so is selling against an **unpaid invoice**: an A/R split states what a customer owes, not currency the book holds, so it must be collected first (or carry `cost_basis_force: true`). Deleting a sale gives its currency straight back to the bases it measured against, and a record whose basis is in use cannot be unposted until those sales are removed.

`cost_basis_balance:` on a split is how much of *that basis* has not yet been sold; it is not the balance of an account. One bank account can hold currency from several bases at different costs, and a paid invoice's basis keeps its balance after the money has moved to the bank. The KVP is the record of that balance: it opens at everything the split brought in, each sale lowers it, and deleting a sale raises it again. A file that states a balance is stating it net of that file's own sales, so re-importing an export never counts a sale twice. A basis carrying no such KVP — one written in the GnuCash GUI, or predating this — reads as `none recorded` rather than as its full amount, because how much of it was already sold is not known. Writing `cost_basis_balance:` on that split in an import file is how it gets a balance — checked as it lands, since nothing after that questions it: it must be on a split that holds foreign currency, and then a number, not negative, no finer than the unit its own account is held to, and no more than that split brought in.

**Paying out of a foreign account whose cost bases still have a balance.** Cash leaving a foreign account is a disposal like any other, so it has to say which cost basis it comes out of — and a `payment:` block has nowhere to say it, because GnuCash's own `ApplyPayment` writes the bank split and `cost_basis_split_guid:` cannot be put on it. Such a payment is therefore **refused**, and the message names the account, what the payment spends, and what balance its bases still have between them.

This is asked of every foreign bank, not only one in a third currency. Paying a USD bill out of a USD bank whose bases still have a balance is the commoner shape and drifts the same way — the basis goes on offering currency the account no longer holds, and the cash leaves valued at the payment day's rate instead of at what it cost — so the question is asked before the cross-currency arithmetic, which that case never reaches.

A foreign account has no basis on it until something opens one: currency bought or borrowed into it, or a settlement landing in it. Until then there is nothing to measure against and a payment out of it is ordinary. **A ledger that imported cleanly before may now be refused**, because settling into a foreign account is itself what opens the basis.

The way to spend a basis balance is the way every other foreign disposal is written — an ordinary transaction whose bank split names its basis, attached to the document by `txn_guid:` / `txn_split_guid:`:

```
2026-03-01 * "Pay BILL-USD-001"
	currency.mnemonic: "CAD"
	Assets:Bank:USD -100.00 USD
		share_price: "1.40"
		value: "-140.00"
		cost_basis_split_guid: "c4ccb16d7be34e15a112d903319c5267"
	Liabilities:Accounts Payable USD 100.00 USD
		share_price: "1.40"
		value: "140.00"
```

`share_price:` is the cost the basis carries, and `cost_basis_split_guid:` names the basis this cash comes out of. Both lines state what their USD is worth in the book's currency, because a split that says nothing is valued at its own figure — 100.00 CAD against the 140.00 beside it, a rate of 1 — and GnuCash puts the 40.00 difference in `Imbalance-CAD`. Where the two rates differ the entry realizes a gain or a loss, and an `Income:FX Gain $residual$ CAD` line takes it, exactly as in the settlement examples above.

Then the bill's own block attaches that transaction — `txn_guid:` is the transaction above, `txn_split_guid:` its A/P split, and `account:` the bank it moved through:

```
	payment:
		date: 2026-03-01
		amount: 100
		account: "Assets:Bank:USD"
		txn_guid: "3f7b21c8de4a4f9e8a15b0c7d2e64913"
		txn_split_guid: "9f0a4c2e1b7d40a8b2c3d4e5f6a7b8c9"
```

Three different guids: the basis the cash comes out of, the transaction that spends it, and that transaction's payable split. `find-transactions` prints the first two and the export prints all three.

(Both blocks are written without trailing `#` comments because the plaintext format has none: a `#` starts a comment only at the beginning of a line, so anything after a value is read as part of it.)

**`$residual$`** is available on any transaction, not only a currency sale: one split may write it in place of an amount and take what the others leave over, the way GnuCash's editor fills an Imbalance line once an account is chosen. It is a token rather than an omitted amount, so a truncated line cannot silently become a residual split. At most one per transaction; asking for one where the splits already balance is an error, and so is asking for one on an account whose commodity differs from the transaction currency — the residual is a transaction-currency figure, and writing it as an amount in another currency would invent a 1:1 rate.

See **[Listing foreign-currency cost bases](#listing-foreign-currency-cost-bases-fx-balances)** for the command that shows every basis with its cost and basis balance, and **[docs/multi-currency.md](docs/multi-currency.md)** for the full reference — invoicing and billing side by side, buying, borrowing and selling, every error with what it means, and how the reports treat foreign currency.

### Custom Metadata

GnuCash supports arbitrary key-value pairs (KVP slots) on all its object types.
gnucash-plaintext exposes this as **custom metadata**: any field in a block that is
not a reserved field (see tables below) is automatically stored in the GnuCash KVP
layer and round-trips through export/import without loss.

This applies to **every object type** — transactions, splits, accounts, customers,
vendors, invoices, and bills — making the format directly comparable to beancount's
open-ended metadata model.

#### What a key says, and what leaving it out says

One rule, the same for reserved fields and custom metadata, on every block that is
read against something the book already holds — transactions and their splits,
customers and vendors, invoices and bills:

| In the block | What it means |
|---|---|
| `key: "value"` | set the field to that value |
| `key: ""` | clear the field — and for a custom key, remove it |
| *(the line is absent)* | say nothing: the book keeps what it has |

**`open` is the exception, and it is not a partial-update rule at all.** An `open`
for an account the book already has is a no-op: the account is found by name and the
block is skipped whole, so neither `description: "…"` nor `description: ""` nor any
custom key changes anything. An `open` creates an account or does nothing. To change
one that exists, use `rename-account` or edit it in GnuCash.

Leaving a line out is not an instruction, because most blocks are partial. A person
editing a name writes the name; `print-invoice --format plaintext` writes a document
block, not a transcript of the book; an export taken before a field existed has no
line for it. A block that named only what it was changing used to empty everything it
did not name.

Two consequences worth stating:

- To clear something, say so: `addr1: ""` empties an address line, and
  `department: ""` takes a custom key off. There is no spelling that means "remove"
  by omission, and there cannot be one — omission is how a partial block stays safe.
- A comparison follows the same rule. A field the block does not name cannot make a
  re-import report `updated`, which is what keeps an unchanged ledger from rewriting
  the book on every run.

Blocks that carry *lines* — an invoice's or bill's `entry:` lines, a transaction's
splits — are different, and deliberately: the block is the whole truth about them, so
removing a line removes it from the book. A block with **no** lines at all is refused
rather than obeyed, because a file cut short by a failed write looks exactly like one
that meant it.

#### Reserved fields per object type

**Transaction** — reserved fields use dedicated GnuCash setters:

| Field | GnuCash field |
|-------|--------------|
| `guid` | Transaction GUID |
| `currency.namespace` | Transaction currency namespace |
| `currency.mnemonic` | Transaction currency mnemonic |
| `doc_link` | Document link / association |
| `notes` | Transaction notes |

**Split** — reserved fields use dedicated GnuCash setters:

| Field | GnuCash field |
|-------|--------------|
| `share_price` | Share price |
| `value` | Split value |
| `action` | Split action |
| `memo` | Split memo |
| `account.commodity.mnemonic` | Account commodity mnemonic |
| `account.commodity.namespace` | Account commodity namespace |

**Account** (`open` directive) — reserved fields:

| Field | GnuCash field |
|-------|--------------|
| `guid` | Account GUID |
| `type` | Account type |
| `placeholder` | Placeholder flag |
| `code` | Account code |
| `description` | Account description |
| `color` | Account color |
| `notes` | Account notes |
| `tax_related` | Tax-related flag |
| `commodity.namespace` | Commodity namespace |
| `commodity.mnemonic` | Commodity mnemonic |
| `commodity_scu` | Commodity smallest currency unit |

**Customer** — reserved fields:

| Field | GnuCash field |
|-------|--------------|
| `guid` | Customer GUID (32-char hex; emitted on export, optional on import) |
| `name` | Customer name |
| `currency` | Customer currency |
| `active` | Active flag (`true`/`false`; defaults `true`) |
| `addr1`–`addr4` | Billing address lines |
| `email` | Contact email |

**Vendor** — reserved fields:

| Field | GnuCash field |
|-------|--------------|
| `guid` | Vendor GUID (32-char hex; emitted on export, optional on import) |
| `name` | Vendor name |
| `currency` | Vendor currency |
| `active` | Active flag (`true`/`false`; defaults `true`) |

**Invoice** — reserved fields:

| Field | GnuCash field |
|-------|--------------|
| `guid` | Invoice GUID (32-char hex; emitted on export, optional on import) |
| `customer_id` | Customer reference (by user-facing customer number) |
| `customer_guid` | Customer reference (by GUID; must agree with `customer_id` when both present) |
| `currency` | Invoice currency |
| `date_opened` | Invoice open date |
| `billing_id` | Billing ID |
| `notes` | Invoice notes |
| `posted` | Posted block / sentinel |
| `payment` | Payment block / sentinel |

**Bill** — reserved fields:

| Field | GnuCash field |
|-------|--------------|
| `guid` | Bill GUID (32-char hex; emitted on export, optional on import) |
| `vendor_id` | Vendor reference (by user-facing vendor number) |
| `vendor_guid` | Vendor reference (by GUID; must agree with `vendor_id` when both present) |
| `currency` | Bill currency |
| `date_opened` | Bill open date |
| `posted` | Posted block / sentinel |
| `payment` | Payment block / sentinel |

**Tax table** — reserved fields:

| Field | GnuCash field |
|-------|--------------|
| `guid` | Tax-table GUID (32-char hex; emitted on export, optional on import) |

#### Any other key → KVP slot

Any key not in the tables above is stored in GnuCash's KVP slot system as a JSON
blob under the `plaintext_metadata` slot name. Multiple custom keys on the same
object are stored together in a single JSON object.

**Key naming rules:**
- Colons (`:`) are **not allowed** in custom metadata key names. The plaintext
  format uses `key: value` syntax, so a colon inside a key name would create
  parsing ambiguity. An error is raised at import time if a colon is found.
- Use **dots** for hierarchical keys (e.g. `tax.category`, `jw.country`).
  Dots are already used by convention in the reserved fields above.

**Transaction / split example:**

```
2024-06-15 * "Dinner with client"
	guid: "317c8ae6e0084c33951d052b9f1b9f23"
	notes: "Team dinner Q2"
	tax_category: "meals_entertainment"
	receipt_id: "RCP-2024-0615"
	Expenses:Dining 85.00 CAD
		vendor: "The Keg Steakhouse"
		approved_by: "Alice"
	Assets:Bank:Checking -85.00 CAD
```

- `guid`, `notes` → reserved fields, stored via dedicated GnuCash API
- `tax_category`, `receipt_id` → stored in the transaction's KVP slot
- `vendor`, `approved_by` → stored in the Dining split's KVP slot

**Customer / account example:**

```
customer "CUST-001"
  name: "Acme Logistics"
  currency: CAD
  addr1: "2000 McGill College Ave"
  addr3: "Montreal"
  addr4: "QC"
  jw.country: "CA"
  jw.postal_code: "H3A 3H3"

2024-01-01 open Assets:Bank:Checking
	type: "BANK"
	commodity.namespace: CURRENCY
	commodity.mnemonic: CAD
	erp.cost_centre: "DEPT-42"
```

- `name`, `currency`, `addr1`–`addr4` → reserved customer fields
- `jw.country`, `jw.postal_code` → stored in the customer's KVP slot
- `type`, `commodity.*` → reserved account fields
- `erp.cost_centre` → stored in the account's KVP slot

All custom keys are emitted after the standard fields on export, preserving the
round-trip exactly.

#### Update merges custom metadata

When using `--strategy update`, custom metadata is **merged** — new keys are added
and existing keys are overwritten, but keys not mentioned in the incoming directive
are preserved from the existing GnuCash object. This means you can add or update
custom tags without wiping out tags set in a previous pass.

```
# First import: stores receipt_id and tax_category
2024-06-15 * "Dinner"
	guid: "317c8ae6e0084c33951d052b9f1b9f23"
	receipt_id: "RCP-001"
	tax_category: "meals"
	Expenses:Dining 85.00 CAD

# Second import (--strategy update): adds approved_by, preserves receipt_id and tax_category
2024-06-15 * "Dinner"
	guid: "317c8ae6e0084c33951d052b9f1b9f23"
	approved_by: "Alice"
	Expenses:Dining 85.00 CAD
```

After the second import the transaction carries all three keys: `receipt_id`,
`tax_category`, and `approved_by`.

#### Cross-version compatibility

KVP metadata works on all supported GnuCash versions for all object types:

| GnuCash version | OS | API used |
|---|---|---|
| 4.x+ | Debian 11/12/13, Ubuntu 22/24 | SWIG `KvpFrame.set_slot_path` |
| 3.8 | Ubuntu 20.04 | ctypes `qof_instance_set_kvp` + GLib `GValue` |

## Usage

The gnucash-plaintext CLI provides commands to work with GnuCash files:

### Export GnuCash to plaintext format

Export all transactions, accounts, and commodities to a plaintext file:

```bash
gnucash-plaintext export mybook.gnucash transactions.txt
```

Export with filters:

```bash
# Export date range
gnucash-plaintext export mybook.gnucash transactions.txt \
  --date-from 2024-01-01 --date-to 2024-12-31

# Export specific account
gnucash-plaintext export mybook.gnucash transactions.txt \
  --account "Assets:Bank"
```

### Export account structure only

Export all accounts and commodities without loading any transactions.
Useful when you need the chart of accounts for reference or bootstrapping
another tool, and don't want to wait for a full transaction scan:

```bash
gnucash-plaintext export-accounts mybook.gnucash accounts.txt
```

By default the open date on each account/commodity declaration is taken from
the GnuCash file's modification time. Supply `--as-of` to use a specific date
instead:

```bash
gnucash-plaintext export-accounts mybook.gnucash accounts.txt --as-of 2024-01-01
```

### Rename an account

Rename an account, identified by its GUID. `--to` is the account's new full
name, so a single rename can change the leaf, the parent, or both at once:

```bash
# New leaf, same parent: Assets:Bank:Checking → Assets:Bank:Chequing
gnucash-plaintext rename-account mybook.gnucash \
    --guid 51359958977a4ca88ec927c2958b3d8b --to "Chequing"

# New parent, same leaf → Assets:Checking
gnucash-plaintext rename-account mybook.gnucash \
    --guid 51359958977a4ca88ec927c2958b3d8b --to "Assets:Checking"

# New parent and new leaf together → Assets:Cash:Petty
gnucash-plaintext rename-account mybook.gnucash \
    --guid 51359958977a4ca88ec927c2958b3d8b --to "Assets:Cash:Petty"
```

This is a targeted operation, not something the full export/edit/import cycle can
do — every transaction names its account by full path, so renaming an account in
the text would mean rewriting every transaction that references it. GnuCash keeps
splits attached to accounts by reference, so renaming the account in place carries
all its transactions with it; the next export prints the new path everywhere
automatically. The account is found by GUID (run `export-accounts` to see each
account's `guid:`), never by its old name. Any named parent must already exist.
Renaming an account under itself or a descendant, a name collision under the
target parent, or an unknown GUID/parent are all refused with an explicit message
and leave the book untouched.

### Migrations: batch operations with `migrate`

Surgical commands (`rename-account`, …) each open the book, do one change, and
save. Because a GnuCash save writes a backup whose filename has a *second*
timestamp, two saves in the same second collide — so back-to-back operations
must be ≥1s apart, and renaming 200 accounts takes 200+ seconds. `migrate`
applies many operations to one open book and saves **once**.

A migration is a versioned file of **operation** lines. Each line uses CLI
syntax — an operation command and its arguments, minus the book (the book is
`migrate`'s target) — but a migration line is *not* "any CLI command": only the
mutating operations (`rename-account`, `set-book-key`) are allowed. Read/meta
commands (`export`, `import`, `print-invoice`, and `migrate` itself) are refused,
so a migration only changes the target book and **migrations cannot nest**.

```
# migrations/0002_restructure.txt
rename-account --guid 51359958977a4ca88ec927c2958b3d8b --to "Assets:Current:Chequing"
rename-account --guid 0409000f1f9c4374aa1651b6c42ed919 --to "Assets:Current:Savings"
set-book-key --key schema_version --value 2
```

```bash
gnucash-plaintext migrate mybook.gnucash migrations/
# applied 1 migration(s) in 1 save; head: 0002_restructure

gnucash-plaintext migrate mybook.gnucash migrations/ --status   # applied vs pending
gnucash-plaintext migrate mybook.gnucash migrations/ --dry-run  # show, change nothing
```

Files apply in filename order (the zero-padded prefix is the version). Each is
applied **atomically**: if any operation fails, `migrate` aborts before saving —
nothing persists and nothing is recorded — and the message names the migration,
the failing line, and that command's own error.

**History is tracked in two places.** The book itself records which migrations
were applied (in `options/Plaintext/Migrations`, the source of truth that travels
with the file). A cheap, readable sidecar — `mybook.gnucash.migrate-state.json` —
mirrors it and is stamped with the book's size+mtime, so a re-run with nothing
pending answers `up to date … book not opened` **without opening the (expensive)
GnuCash file** — safe to run on every deploy. Applied migrations are immutable:
editing one after it ran is rejected (write a new migration instead). `--verify`
ignores the sidecar and checks the book directly.

A migration can also stamp your **own** version key with `set-book-key`
(e.g. `--key schema_version --value 2`), stored as book metadata that round-trips
via the `company` directive — separate from the tool's automatic
applied-migrations log.

### Export transactions by GUID

Export one or more transactions to plaintext (useful for AI-assisted editing or review):

```bash
# Single transaction
gnucash-plaintext export-transaction mybook.gnucash --guid 317c8ae6e0084c33951d052b9f1b9f23

# Multiple transactions in one pass
gnucash-plaintext export-transaction mybook.gnucash \
    --guid 317c8ae6e0084c33951d052b9f1b9f23 \
    --guid a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4
```

The output is self-contained — it includes the commodity and account declarations needed to re-import or process the transactions independently. When multiple GUIDs are given, shared commodities and accounts are emitted only once. Output goes to stdout by default; use `-o` to write to a file:

```bash
gnucash-plaintext export-transaction mybook.gnucash \
    --guid 317c8ae6e0084c33951d052b9f1b9f23 \
    --guid a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4 \
    -o batch.txt
```

At least one `--guid` is required. Omitting it prints an error with usage guidance.

### Delete transactions by GUID

Delete one or more transactions permanently. Each transaction is exported to plaintext **before** deletion so you always have a backup copy. `--by-guid` is required (it's the only addressing scheme currently supported for transactions; the flag is explicit for consistency with `delete-customers --by-guid`, `delete-invoices --by-guid`, etc.):

```bash
# Delete one and print backup to stdout
gnucash-plaintext delete-transactions mybook.gnucash --by-guid \
    317c8ae6e0084c33951d052b9f1b9f23

# Delete one, save backup to a file
gnucash-plaintext delete-transactions mybook.gnucash --by-guid \
    317c8ae6e0084c33951d052b9f1b9f23 -o backup.txt

# Delete several in one call, single concatenated backup
gnucash-plaintext delete-transactions mybook.gnucash --by-guid \
    317c8ae6e0084c33951d052b9f1b9f23 \
    589d2f1c7a1b4e5a803b1ce9a72f0344 \
    -o batch_backup.txt
```

Per-GUID status is reported on stderr; the overall exit code is 1 if any GUID failed (e.g. not found), and successfully-deleted transactions in the same batch are still saved.

The backup plaintext is self-contained (commodity + account declarations + transaction) and looks like this:

```
2024-06-15 commodity CAD
	mnemonic: "CAD"
	fullname: "Canadian Dollar"
	namespace: "CURRENCY"
	fraction: 100
2024-06-15 account Assets:Checking
	commodity: "CAD"
	type: "BANK"
2024-06-15 account Expenses:Dining
	commodity: "CAD"
	type: "EXPENSE"
2024-06-15 * "Dinner out"
	guid: "317c8ae6e0084c33951d052b9f1b9f23"
	Assets:Checking  -45.00 CAD
	Expenses:Dining  45.00 CAD
```

**Undo:** re-import the backup plaintext to restore the transaction:

```bash
gnucash-plaintext import mybook.gnucash -f backup.txt
```

Only transactions are deleted. Accounts and commodities are not affected.

### Export GnuCash to GnuCash-Beancount format

Export to [GnuCash-Beancount](docs/gnucash-beancount-format.md) format:

```bash
gnucash-plaintext export-beancount mybook.gnucash output.beancount
```

With filters:

```bash
# Export date range
gnucash-plaintext export-beancount mybook.gnucash output.beancount \
  --date-from 2024-01-01 --date-to 2024-12-31

# Export specific account
gnucash-plaintext export-beancount mybook.gnucash output.beancount \
  --account "Assets:Bank"
```

**Note:** The exported file is in [GnuCash-Beancount format](docs/gnucash-beancount-format.md), a special beancount format with GnuCash metadata that enables bidirectional conversion with zero data loss for accounts, transactions, splits, commodities, and prices. Business objects (customers, vendors, invoices, bills) and custom KVP slots are dropped during export — see [Limitations](docs/gnucash-beancount-format.md#limitations).

### View GnuCash data in Fava web UI

[Fava](https://github.com/beancount/fava) is a modern web interface for beancount files. The `examples/fava-viewer.sh` script exports your GnuCash file and launches Fava in one step:

```bash
./examples/fava-viewer.sh ~/finances/mybook.gnucash
```

Then open http://localhost:5000 in your browser (or whichever port you specified with `--port`).

Options:

```bash
# Use a different port
./examples/fava-viewer.sh ~/finances/mybook.gnucash --port 5001

# Filter by date range
./examples/fava-viewer.sh ~/finances/mybook.gnucash \
  --date-from 2024-01-01 --date-to 2024-12-31

# Filter by account
./examples/fava-viewer.sh ~/finances/mybook.gnucash --account "Assets"

# Use a specific Docker image tag
./examples/fava-viewer.sh ~/finances/mybook.gnucash --tag debian12
```

The script uses Docker — no local GnuCash or Fava installation required. The exported `.beancount` file is written alongside your `.gnucash` file.

### Import from GnuCash-Beancount format

Import from [GnuCash-Beancount](docs/gnucash-beancount-format.md) format:

```bash
gnucash-plaintext import-beancount output.gnucash input.beancount
```

Validate without importing (dry run):

```bash
gnucash-plaintext import-beancount output.gnucash input.beancount --dry-run
```

**Note:** Only GnuCash-Beancount files (with required metadata) can be imported. Standard beancount files will be rejected. See the [format documentation](docs/gnucash-beancount-format.md) for details.

### Import plaintext transactions to GnuCash

Import transactions from a plaintext file:

```bash
gnucash-plaintext import mybook.gnucash transactions.txt
```

Preview without making changes (dry run):

```bash
gnucash-plaintext import mybook.gnucash transactions.txt --dry-run
```

Exit code 1 if the run reported any error, whether or not the rest imported: what did import is saved first, and the exit code is how the run says the rest did not. A file the parser could not read at all imports nothing and is refused outright. A book `--new` created for a run that saved *nothing* is removed again, so a retry is not blocked by a file you never made — but a run that saved some of the file keeps its book, because that book now holds work, and the fix is to import the corrected ledger into it rather than to start again. Exit code 0 means nothing was reported as an error — read `Skipped:` for objects that matched an existing GUID and were left as they were, which under the default strategy includes a transaction you edited and re-imported without `--strategy update`.

#### Capturing GUIDs of newly imported transactions

When importing new transactions, GnuCash assigns a GUID to each one. Use
`--output-new` to capture those transaction blocks (with their `guid:` fields)
immediately after import — without a separate export step:

```bash
# Write new transactions to a file
gnucash-plaintext import mybook.gnucash transactions.txt --output-new new.txt

# Print to stdout
gnucash-plaintext import mybook.gnucash transactions.txt --output-new -
```

The output contains only the transaction blocks (no commodity or account
preamble). Each block includes the `guid:` field assigned by GnuCash, which
you can use later with `--strategy update` to edit those transactions
in-place, or with `get-transaction` / `delete-transactions --by-guid` to
look them up directly.

If all transactions in the file are duplicates and none are imported, no
output is written (the option is silently ignored).

### Import and export business objects

Customers, vendors, tax tables, invoices, and bills can be round-tripped
through plaintext alongside your accounts and transactions.

```bash
# Import a file that contains business objects as well as transactions
gnucash-plaintext import --new mybook.gnucash ledger.txt --include-business-objects

# Export everything — accounts, business objects, then transactions
gnucash-plaintext export mybook.gnucash ledger.txt --include-business-objects

# A foreign-currency invoice or bill needs the rate its revenue is booked at
gnucash-plaintext import mybook.gnucash ledger.txt --include-business-objects --fx-rates rates.yaml
```

An export carrying business objects emits the book's whole chart of accounts, so it is always re-importable: an invoice reaches accounts no transaction split touches — its entries' income accounts, its `posted:` block's A/R account, a tax table's tax account — and an unposted one has no posting transaction to drag them in.

`--fx-rates` takes the same file every reporting command takes, in either form — flat, or a rate per day:

```yaml
HKD: 0.172                  # 1 HKD = 0.172 CAD, undated
USD/CAD:
  2026-01-05: 1.35          # 1 USD = 1.35 CAD from that day
  2026-02-20: 1.37
```

A dated lookup takes the most recent quote on or before the date asked for; a date earlier than every quote is an error rather than an extrapolation. Rates are held as exact fractions, never rounded to a float.

The importer prints a per-directive status line as each business object
is processed, plus an aggregate summary at the end:

```
Importing business objects...
customer "C001": created
customer "C002": unchanged
vendor "V001": updated
taxtable "GST": skipped
invoice "INV-2026-001": unchanged
bill "BILL-2026-001": created

...

Business Objects:
  Customers:   1 created, 0 updated, 1 unchanged, 0 skipped
  Vendors:     0 created, 1 updated, 0 unchanged, 0 skipped
  Tax tables:  0 created, 0 updated, 0 unchanged, 1 skipped
  Invoices:    0 created, 0 updated, 1 unchanged, 0 skipped
  Bills:       1 created, 0 updated, 0 unchanged, 0 skipped
```

The four-status model:

| Status | Meaning |
|---|---|
| `created` | Fresh record created — no record with this id existed. |
| `updated` | Existing record had at least one mutable field changed. For posted invoices/bills this includes the unpost-edit-repost cycle (matches GnuCash's own UI behaviour). |
| `unchanged` | Existing record matches the directive byte-for-byte — no work performed. The happy path for an idempotent re-run. |
| `skipped` | Existing record is immutable for this directive; the importer refused to mutate it. Currently only **tax tables** report `skipped` — they're referenced by pointer from past posted invoices, so changing their entries would silently rewrite past accounting. |

See "Re-import semantics" below for the full state matrix.

Business objects use no date prefix — they are master data, not ledger
events. Dates that belong to a record (e.g. `date_opened` on an invoice) are
declared as fields inside the block:

```
customer "CUST-001"
  name: "Acme Corp"
  currency: CAD

customer "CUST-002"
  name: "Retired Client"
  currency: CAD
  active: false

vendor "VEND-001"
  name: "Office Supplies Co."
  currency: CAD

taxtable "GST"
  entry:
    account: "Liabilities:Tax:GST Collected"
    rate: 5.0%
    type: PERCENT

invoice "INV-2026-001"
  customer_id: "CUST-001"
  currency: CAD
  date_opened: 2026-01-15
  entry:
    date: 2026-01-15
    description: "Consulting services"
    account: "Income:Consulting"
    quantity: 10
    price: 150
    taxable: true
    tax_table: "GST"
  posted: none
  payment: none

invoice "INV-2026-002"
  customer_id: "CUST-001"
  currency: CAD
  date_opened: 2026-01-15
  entry:
    date: 2026-01-15
    description: "Consulting services"
    account: "Income:Consulting"
    quantity: 10
    price: 150
    taxable: true
    tax_table: "GST"
  posted:
    date: 2026-01-15
    due: 2026-02-14
    ar_account: "Assets:Accounts Receivable"
    memo: "Invoice INV-2026-002"
    accumulate: true
  payment: none

invoice "INV-2026-003"
  customer_id: "CUST-001"
  currency: CAD
  date_opened: 2026-01-15
  entry:
    date: 2026-01-15
    description: "Consulting services"
    account: "Income:Consulting"
    quantity: 10
    price: 150
    taxable: true
    tax_table: "GST"
  posted:
    date: 2026-01-15
    due: 2026-02-14
    ar_account: "Assets:Accounts Receivable"
    memo: "Invoice INV-2026-003"
    accumulate: true
  payment:
    date: 2026-01-30
    amount: 1575
    bank_account: "Assets:Bank"
    memo: "Payment received"

bill "BILL-2026-001"
  vendor_id: "VEND-001"
  currency: CAD
  date_opened: 2026-01-20
  entry:
    date: 2026-01-20
    description: "Office supplies"
    account: "Expenses:Office"
    quantity: 1
    price: 200
    taxable: false
  posted:
    date: 2026-01-20
    due: 2026-02-19
    ap_account: "Liabilities:Accounts Payable"
    memo: "Bill BILL-2026-001"
    accumulate: true
  payment:
    date: 2026-02-05
    amount: 200
    bank_account: "Assets:Bank"
    memo: "Payment for BILL-2026-001"
```

> **Note:** GnuCash does not persist `taxable: false` for bill entries — the
> field is omitted in the XML file and defaults to `true` on reload. Exported
> bills therefore always show `taxable: true` regardless of what was imported.

#### Your own company info: the `company` directive

A single book-level `company` directive round-trips the seller identity
`print-invoice` / `print-bill` head the page with. These are GnuCash's own
**File → Properties → Business** options — they were rendered before but never
exported or imported, so a roundtrip into a fresh book used to lose them. The
directive has no id and no date; it is master data for the whole book:

```
company
  name: "Maple Leaf Widgets Inc."
  contact: "Jane Doe"
  id: "123456789RT0001"
  gst: "123456789RT0001"
  pst: "BC PST-1234-5678; SK 9012-3456"
  addr1: "42 Example Street, Unit 5"
  addr2: "Springfield ON A1A 1A1"
  phone: "+1-555-0100"
  fax: "+1-555-0199"
  email: "billing@example.com"
  url: "https://example.com"
```

`name`, `contact`, `id`, `phone`, `fax`, `email`, `url`, and `addr1..4` map
directly to GnuCash's native Business fields. The address lines are stored in
GnuCash's single multi-line `Company Address` slot.

`gst` and `pst` are **registration numbers GnuCash has no field for** — there is
only one generic `Company ID`. This tool stores them as extra Business slots
alongside it, so you no longer have to cram a tax number into the company name
or address. `gst` is a single number; `pst` may hold **several** numbers (e.g.
for multiple provinces) in one value separated by `;` — each is rendered on its
own row in the invoice/bill. All of these are additive: `id` is preserved
unchanged.

Only non-empty fields are emitted on export. On import the directive is the
source of truth for the fields it names; it reports `created` / `updated` /
`unchanged` like other business objects.

Beyond the fields above, the `company` directive accepts **any key** — like
`customer`, `vendor`, and account `open` directives do. Keys it doesn't
recognise are kept as book-level data that round-trips but is **never rendered**
on an invoice or bill (it is private to you, not the recipient):

```
company
  name: "Acme Inc."
  id: "123456789RT0001"
  fiscal_year_end: "12-31"
  province: "British Columbia"
  entity_type: "T2 Corporation"
  ledger_locale: "en_CA"
```

This is the place for book-level facts GnuCash itself has no field for — a
fiscal year end, entity type, locale. (GnuCash's accounting-period dates, for
instance, are an application preference, not stored in the file, so there is no
native slot to map them to.) These custom keys are stored together in the book
and re-emitted on export; they never reach the rendered seller block.

Importing a `company` directive is a **partial update** — for the custom keys as
well as the known fields. Keys you list are set, keys you omit are **kept**, and
a key given the null value `#None` is **removed** (JSON Merge Patch semantics):

```
company
  province: "Ontario"      # set/update province
  entity_type: #None       # remove the entity_type key
  # any custom key not listed here is left untouched
```

So a small edit never wipes the rest of your book metadata. (`set-book-key`,
used in migrations, upserts the same way through the same code.)

**Invoice and bill status fields**

The `posted:` and `payment:` fields are always present in exported output.
`none` is an explicit sentinel meaning "not applicable":

| `posted:` value | `payment:` value | Meaning |
|---|---|---|
| `none` | `none` | Invoice/bill created but not yet posted to AR/AP |
| data block | `none` | Posted, no payments received/made yet |
| data block | data block(s) | Posted with one or more payments applied |

On **import**, `posted: none` and `payment: none` are no-ops — they produce the same result as omitting the field entirely. The following combinations are rejected with a clear error (for both invoices and bills):

- `posted: none` together with a `posted:` block (contradictory)
- More than one `posted:` block (can only be posted once)
- `payment: none` together with a `payment:` block (contradictory)
- A `payment:` block when `posted: none` (cannot pay an unposted invoice or bill)

#### Posted-tx linkage: `posted_txn_guid:`

Every exported `posted:` block carries a `posted_txn_guid:` line — the GUID of the AR/AP posting transaction that GnuCash created. Two reasons it's there:

* **External cross-reference.** Scripts, bank-reconciliation tools, and audit pipelines that already track transactions by GUID get a stable handle from the invoice/bill block to "the transaction that recorded this posting". Edit the resulting tx directly in GnuCash and the same GUID survives.
* **Roundtrip integrity.** The exporter also emits the posting transaction as a normal `* "INV-NNN"` standalone block with the same GUID + `txn_type: I` + owner backref. On re-import, the standalone-tx pass creates that tx first; the invoice's `posted:` handler then finds it by `posted_txn_guid:` and *attaches* it (`gncInvoiceAttachToTxn` + lot creation) instead of calling `PostToAccount`. Without `posted_txn_guid:` the importer would call `PostToAccount`, which always mints a fresh tx — leaving the standalone-imported original orphan (AR/AP split with no lot) and doubling the AR/AP and income/expense balances on every roundtrip.

`posted_txn_guid:` is optional on hand-authored plaintext. When absent, the importer falls back to `PostToAccount` (the original code path) — fine for plaintext that doesn't also include a matching standalone `*` block for the posting tx.

An invoice or bill with **multiple partial payments** can have multiple `payment:` blocks — one per payment transaction:

```
invoice "INV-2026-004"
  ...
  posted:
    date: 2026-02-01
    due: 2026-03-03
    ar_account: "Assets:Accounts Receivable"
    memo: "Invoice INV-2026-004"
    accumulate: true
  payment:
    date: 2026-02-10
    amount: 500
    bank_account: "Assets:Bank"
    memo: "First instalment"
  payment:
    date: 2026-02-20
    amount: 500
    bank_account: "Assets:Bank"
    memo: "Second instalment"
```

A **vendor bill** takes multiple `payment:` blocks the same way, on Accounts Payable with the signs flipped. A $100 bill paid in two instalments of $40 and $35 leaves one open AP lot for the $25 still owed:

```
bill "BILL-PARTIAL-100"
  ...
  posted:
    date: 2026-02-01
    due: 2026-03-03
    ap_account: "Liabilities:Accounts Payable"
    memo: "Bill BILL-PARTIAL-100"
    accumulate: true
  payment:
    date: 2026-02-10
    amount: 40
    bank_account: "Assets:Bank"
    memo: "First instalment"
  payment:
    date: 2026-02-20
    amount: 35
    bank_account: "Assets:Bank"
    memo: "Second instalment"
```

That bill's AP lot holds the posting (−$100) plus both payments (+$40, +$35) and stays open at a **−$25** balance — a still-owed liability. It is the sign-inverse of a partly-paid *invoice*, whose AR lot stays open at a **positive** balance (the receivable you're still owed). Each `amount:` in a bill's `payment:` block is written positive in plaintext; the importer records it as money leaving the bank (a debit to AP, a credit to Bank), the opposite direction to an invoice payment.

To find which bills are still outstanding, render a whole vendor at once with `print-bill <book> --vendor V001 --format plaintext -o -` and compare each bill's `bill_total:` to the sum of its `payment:` `amount:` lines — a shortfall is unpaid (its posted AP lot stays open at a negative balance). Overpayment credit is separate: it lives in its own AP lot attached to no bill, so surface it with `find-prepayments --vendor V001` (below), which totals a vendor's credit even when it accumulated across several bills. See **[docs/bill-payment-reconciliation.md § Detecting a vendor's bill payment state](docs/bill-payment-reconciliation.md#detecting-a-vendors-bill-payment-state-paid--partial--overpaid)** for the worked paid / partial / overpaid example.

**Adding a payment via re-import is incremental.** If a posted invoice is already in the book with one `payment:` block, editing the plaintext to append a second `payment:` block and re-importing applies *only* the new payment on the still-posted invoice. Two sub-paths, both incremental:

* The new payment block has no `txn_guid:` — the importer calls `ApplyPayment` to create a fresh bank-side transaction.
* The new payment block has `txn_guid: "..."` pointing at a pre-existing bank transaction (e.g. one already loaded from a QFX import) — the importer retargets that transaction's counter-split into the invoice's posted lot (the Q-004 mechanism), no new bank transaction created. Original tx GUID, notes, and KVP preserved. Exported payment blocks always include `txn_guid:` and `txn_split_guid:` so the same retarget is reproducible on a fresh re-import; see [Reconciling invoice and bill payments with a bank feed](#reconciling-invoice-and-bill-payments-with-a-bank-feed) below for the multi-invoice variant.

Either way the posting transaction, every entry, and the original bank-side payment transactions already on the invoice's lot are left untouched (same GUIDs throughout) — no orphan is created and the bank balance reflects exactly the payments the user recorded. Any other shape of diff (entry add/remove/modify, posted block change, payment field edited or removed) still takes the GnuCash-UI-equivalent unpost-rebuild-repost path, and any payment-side bank transactions about to be orphaned by that rebuild are listed in the import output with the same warning block `unpost-invoices` / `unpost-bills` emit (see the unpost section below).

#### Overpayment / pre-payment credit: `prepayment:`

When the customer pays more than the invoice total, GnuCash splits the single payment into two AR-side splits and routes them to two separate lots on the AR account, [exactly as the GnuCash manual describes](https://www.gnucash.org/docs/v5/C/gnucash-manual/busnss-ar-payment.html): the invoice lot (closes at $0) and a new pre-payment lot that stays open as a credit available against the next invoice.

For a $100 invoice paid $150 the plaintext is:

```
invoice "INV-2026-005"
  ...
  posted:
    date: 2026-03-01
    ar_account: "Assets:Accounts Receivable"
    memo: "Invoice INV-2026-005"
    accumulate: true
  payment:
    date: 2026-03-10
    amount: 150
    bank_account: "Assets:Bank"
    memo: "Overpaid by 50"
    prepayment: 50
```

What that creates in the book (one payment transaction, three splits across two accounts and two AR lots):

```
Transaction 2026-03-10 — "Acme Customer" (payment)
  Assets:Bank                    +$150.00   (the cash you received)
  Assets:Accounts Receivable     -$100.00   (in invoice lot — closes INV-2026-005)
  Assets:Accounts Receivable      -$50.00   (in NEW pre-payment lot — customer credit)
```

After the payment, `Assets:Accounts Receivable` shows a net **-$50** for this customer — that's the pre-payment credit. The invoice itself is marked paid (its lot's balance is zero). The next invoice you post for the same customer can consume the credit via Process Payment in GnuCash's UI, or via a `payment:` block on the next invoice that uses `txn_guid:` to retarget the customer's existing pre-payment bank tx into the new invoice's lot.

For the `txn_guid:` retarget path (Q-004), when the pre-existing bank transaction's counter-split is larger than the invoice's remaining balance, the `prepayment:` field is **required**. The importer splits the counter-split into the invoice-portion (closes the lot) and the residual (new pre-payment lot on AR/AP). Omitting `prepayment:` on an over-sized retarget is rejected with an explicit error that names the bank tx, the counter-split amount, the invoice's remaining, and the expected `prepayment` value.

**Vendor bills are the mirror image (Accounts Payable, opposite signs).** A bill posts as a *credit* to AP — a liability going up — which is the sign-inverse of an invoice's *debit* to AR (an asset going up), so every split below flips sign relative to the invoice case. Overpaying a $100 bill by $50 (one $150 payment *out* of the bank) creates one payment transaction with three splits across two accounts and two AP lots:

```
Transaction 2026-01-10 — payment on BILL-OVERPAY-100
  Assets:Bank                    -$150.00   (the cash you sent the vendor)
  Liabilities:Accounts Payable   +$100.00   (in bill lot — closes BILL-OVERPAY-100 at $0)
  Liabilities:Accounts Payable    +$50.00   (in NEW pre-payment lot — vendor credit)
```

The bill lot nets to zero (posting −$100 + payment +$100) and the $50 residual opens a second AP lot whose balance is **+$50** — a positive (debit) balance on a liability, i.e. a *vendor credit*: the supplier now owes you $50 toward a future bill. That is the exact inverse of a customer overpayment, where the residual AR lot carries **−$50** (money you owe the customer). The exported bill records the two allocations separately — `amount:` is the $100 that settled the bill lot and `prepayment:` is the $50 residual, and the two together account for the full $150 that left the bank:

```
bill "BILL-OVERPAY-100"
  ...
  posted:
    ap_account: "Liabilities:Accounts Payable"
    memo: "Bill BILL-OVERPAY-100"
    accumulate: true
  payment:
    date: 2026-01-10
    amount: 100
    bank_account: "Assets:Bank"
    memo: "Paid 150 on a 100 bill (overpaid 50)"
    prepayment: 50
```

Consume the credit on the next bill from `V001` with `auto_apply_credit: true` (below), or list it with `find-prepayments --vendor V001`.

#### Bad debt: writing off an uncollectable invoice via `payment:` to an expense

When an invoice will never be paid, write it off instead of receiving cash by giving the `payment:` block an expense account. The transfer account is named by `account:` (the canonical key) or its alias `bank_account:` — despite the legacy name the account need not be a bank. For an **invoice** the account may be an asset (cash actually received), an owner's-equity deposit account ([below](#sole-proprietor-deposit-account-paying-into-owners-equity)), or an expense (the bad-debt write-off); the importer infers the intent from the account type, so no separate keyword is needed.

```
invoice "INV-2026-007"
  ...
  posted:
    date: 2026-06-01
    ar_account: "Assets:Accounts Receivable"
    memo: "Invoice INV-2026-007"
    accumulate: true
  payment:
    date: 2026-06-30
    amount: 100
    account: "Expenses:Bad Debt"
    memo: "Write off INV-2026-007 — uncollectable"
```

The AR lot closes (the invoice reads paid) and the $100 lands in the expense rather than a bank account. **Bills are different**: a bill payment must use an asset or owner's-equity account, never an expense. An unpaid bill *you* owe is debt forgiveness — a gain, not bad debt — which is out of scope, so an expense (or income) on a bill payment is rejected with a clear error. Bad debt only exists for money owed *to* you.

#### Sole-proprietor deposit account: paying into owner's equity

A Canadian sole proprietor often has no separate business bank account — the business tax return reports only income and expense, and money the owner receives or spends personally is tracked in owner's equity (drawings / contributions). So a customer's payment can land directly in an owner's-equity deposit account instead of a bank:

```
invoice "INV-2026-008"
  ...
  posted:
    ar_account: "Assets:Accounts Receivable"
  payment:
    date: 2026-02-01
    amount: 100
    account: "Equity:Owner equity:Owner's equity"
    memo: "Customer paid — deposited to owner's equity"
```

A vendor bill paid out of the owner's personal funds (an owner contribution) works the same way — give the bill's `payment:` an `account:` on owner's equity. So a payment's transfer account may be an asset (bank / cash), owner's equity, or — for an invoice only — an expense (bad-debt write-off). Income is rejected (it would double-count the revenue already booked at posting), as is the AR/AP account itself. (A corporation that routes receipts through a shareholder loan models "due from director" as an *asset*, already covered by the asset case.)

#### Consuming an existing credit on the next invoice / bill: `auto_apply_credit:`

When the customer (or vendor) already has an open pre-payment credit on AR/AP, the *next* invoice or bill for that owner can consume the credit automatically — add `auto_apply_credit: true` to the invoice/bill header:

```
invoice "INV-2026-006"
  customer_id: "C001"
  currency: CAD
  date_opened: 2026-04-01
  auto_apply_credit: true
  entry:
    date: 2026-04-01
    description: "Service C"
    action: "Hours"
    account: "Income:Sales"
    quantity: 1
    price: 30
    taxable: false
    tax_included: false
  posted:
    date: 2026-04-01
    due: 2026-04-30
    ar_account: "Assets:Accounts Receivable"
    memo: "Invoice INV-2026-006"
    accumulate: true
```

On import the invoice is posted normally, then `gncInvoiceAutoApplyPayments` runs and takes from the open prepay lot(s) toward the invoice's outstanding balance. If credit ≥ invoice the lot closes via consumption; the residual stays open as a smaller credit (split in-place by GnuCash). If credit < invoice the full credit consumes; the invoice stays partially open. The flag composes with cash `payment:` blocks — cash goes first, credit auto-applies for any remainder.

##### What the export says a credit settled: `from_credit:`

**You do not write this block.** `auto_apply_credit: true` on the header, above, is the whole of what a file needs to spend an owner's credit — nothing below names a guid, a split or a date. What follows is what comes back **out** of an export, so read it when you are reading an exported book (or re-importing one), not when you are writing an invoice.

`auto_apply_credit:` is a request — apply whatever credit this owner has — and what the book holds afterwards is an outcome: this much, out of that split. The export records the outcome, as a payment block carrying `from_credit: true`:

```
  payment:
    amount: 30.00
    from_credit: true
    credit_dated: 2026-01-10
    memo: "Overpaid"
    txn_guid: "5ce645159f594b1cb9017df94fd8fd94"
    txn_split_guid: "f792882e159c4cb0b6bab44ec1479f51"
```

Which of a document's payments is a credit is **recorded when the credit is applied**, as `applied_from_credit: "true"` on the split the application moves into the document's lot (visible on that split in the transaction section of an export). It cannot be worked out afterwards: a consumed credit's split sits in the lot exactly as a bank payment's split does, GnuCash keeps no record of the lot it came from, one payment commonly settles the invoice it was made against *and*, months later, a second invoice that took what it left over — and when a deposit is taken and an invoice raised against it the same day, even the dates agree. A split with nothing recorded on it, such as one written in the GnuCash GUI, reads as a payment. The invoice the bank really paid keeps its `bank_account:`, `date:` and `prepayment:` lines.

`prepayment:` on that bank-paid invoice is what the payment left over **when it was made**, not what is left today: a 150.00 payment against a 100.00 invoice writes `prepayment: 50.00` even after a later invoice has taken 30.00 of it, because a rebuild reaches that payment before the later invoice exists. It is decided by the same recorded fact, so the two cannot disagree.

A credit block names no account, because no bank moved anything: the currency was already in the book, on the split `txn_split_guid:` names. It has no date of its own either — GnuCash records none for applying a credit, writing no transaction for it — so `credit_dated:` gives the date of the transaction the credit arrived in, which on a bill is the day the money was sent to the vendor. `amount:` is this document's own slice, not the credit's full size.

Importing one attaches that split to this document's lot, which is what settles it. A credit smaller than the document is an ordinary part-payment and leaves the rest owing. One larger is divided: attaching it whole would take the lot past zero — measured, a 50.00 credit named against a 30.00 invoice leaves the lot at −20.00 with `IsPaid` false and the customer's 20.00 gone from `find-prepayments`, which lists only lots no document owns — so the block divides it, from the figures it names. This is the same thing that happens to a bank transfer bigger than the invoice it pays, and it is done the same way: the named split settles the document with 30.00, and 20.00 is parked as the customer's credit in a lot of its own. The export says `amount: 30.00`, which is what that split took. The engine is not asked to do it: `AutoApplyPayments` takes the owner's open credits in its own order — so a file naming one of two could have the other carved — and divides differently by version, carving the split on GnuCash 5.10 and moving it whole into the document's lot on 4.13 and 3.8.

A credit **in no lot** can be attached whole but not divided, and the refusal names `lot_owner:` as the remedy: parking what is left over means opening a credit in somebody's name, and a lot is the only thing that records whose a split is — a deposit paying several owners cannot be asked. Attaching such a split whole opens no new credit and stays ordinary. A block on a document that **owes nothing** — cash has already settled it in full — is refused for the same reason it cannot be attached: the lot would go past zero.

**Whose money it is is checked** too, and what is asked depends on what the file names. Where a block names a split, that split's **lot** must belong to this document's owner — one customer's credit cannot settle another's invoice. Where it names only `txn_guid:`, the retarget moves whichever counter split the transaction carries, so the **transaction's** owner is asked instead. The two are deliberately not combined: one deposit can settle documents of several owners at once, each block naming its own portion, and the transaction reports whichever owner GnuCash recorded on it — asking it there would refuse the second document for the first one's owner. A split in no lot has no owner of its own; its transaction answers for it where that transaction carries a single receivable or payable split — a payment GnuCash wrote for one owner — and where it carries several, nothing is refused, because none of them can be shown to be the one. Nor is a transaction off a bank feed, which records no owner and is what the retarget workflow exists to attach.

Nothing is re-decided: re-running the original request against a book that has moved on could apply a different credit, and re-applying an already-applied one leaves every document of that owner with a lot GnuCash discards on load (`invoice_postlot_handler: assertion 'lot' failed`), so a rebuilt book came back with nothing paid. Everything the block states is checked — the split must be on the named transaction and on this document's own posted account, carry the amount claimed with the sign a credit has on that side, and still be the owner's to spend — and a block that cannot be honoured is refused rather than half-applied. Writing `from_credit: true` beside a `bank_account:` or a `date:` is refused too, naming the key to drop.

A credit larger than one document is drawn down across several: mark each invoice/bill `auto_apply_credit: true` and GnuCash consumes the credit in **posting order** until it runs out. A $150 credit against two $100 documents settles the first in full and leaves the second **$50 outstanding** (its lot open at +$50 for an invoice, −$50 for a bill), with the credit at $0. Because cash applies before credit on each document, that second document can also carry a `payment: amount: 50` — the $50 cash plus the $50 of remaining credit close it. This works identically on the receivable (invoice) and payable (bill) sides, sign-flipped.

#### Listing open credits: `find-prepayments`

After a series of overpayments (or standalone pre-payments), the book may carry open AR / AP credit lots that aren't yet attached to any invoice or bill. `find-prepayments` walks the book and lists them — read-only, parallel to `find-orphan-payments`:

```bash
gnucash-plaintext find-prepayments ledger.gnucash
gnucash-plaintext find-prepayments ledger.gnucash --customer C001
gnucash-plaintext find-prepayments ledger.gnucash --vendor V001
```

Example output for a book where Acme (C001) overpaid INV-001 by $50:

```
Found 1 open pre-payment credit.

  • customer C001 (Acme)  CAD 50.00  in Assets:Accounts Receivable
    source bank tx: 2026-01-10 on Assets:Bank  "Acme"
      memo: "Overpaid"
      guid: e9a2b1c4-3f6d-4a17-b218-c47e85d290f3
      NOTE: this is the parent bank tx of the credit lot's split.
      Deleting it via `delete-transactions --by-guid` may also remove other
      splits on the same tx (e.g. the original invoice payment if this credit
      came from an overpayment). Consuming via `auto_apply_credit` on the next
      invoice/bill is the non-destructive option.
    why classified as a pre-payment (AR credit):
      - the lot lives on an AR/AP account and is open (balance != 0),
      - gncInvoiceGetInvoiceFromLot returned NULL — no invoice / bill
        owns this lot, so the credit is unconsumed,
      - parent tx owner backref points at customer C001.

Total credit available: CAD 50.00 for customer C001 (Acme).
```

The `guid` field is the **source bank transaction** of the credit lot — i.e. the original payment that left the residual. For a customer overpayment, that's the same tx that paid the original invoice, so deleting it would also drop the invoice payment. For a standalone customer pre-payment (no invoice attached at the time the payment was recorded), the bank tx only carries this credit, so deleting it cleanly refunds.

The same shape applies to vendor credits (`AP credit`, account is `Liabilities:Accounts Payable`, owner is the vendor). Per-owner totals at the end. Exit code is 0 whether or not any credits are found.

What to do with each credit:

  a) **Consume** against the next invoice/bill for that owner — add `auto_apply_credit: true` to that invoice/bill (above). Non-destructive; the only safe option for credits that came from invoice overpayment.
  b) **Refund, write off, or forfeit** — record a normal `transaction:` whose AR/AP split carries a `lot_owner:` KVP for the owner; the counter account decides the intent (bank ⇒ refund, expense ⇒ vendor bad debt, income ⇒ customer forfeit). This is the canonical non-destructive disposal — see [Disposing of a credit](#disposing-of-a-credit-refund-write-off-or-forfeit-lot_owner) below. It never touches the original payment, and a partial amount leaves the residual credit open.
  c) **Delete the source bank tx** — only safe for standalone-payment credits (the source bank tx has just the bank-side split and the AR/AP credit split, nothing else). `delete-transactions --by-guid <source-bank-tx>` drops the tx and produces a plaintext backup. Not safe for overpayment-residual credits, where the source tx also carries the original invoice payment.

When the book and the plaintext have diverged (the user hand-edited the `.gnucash` file in the GnuCash UI, or hand-edited the `.txt` file before re-importing, or a third-party tool modified the book), the importer's recovery behaviour per scenario is documented in [`docs/payment-manual-edit-behavior.md`](docs/payment-manual-edit-behavior.md).

#### Listing foreign-currency cost bases: `fx-balances`

Every split that brought foreign currency into the book, with what one unit cost in CAD and how much of that basis is still available to sell. The split guid is what a sale names in `cost_basis_split_guid:` (see [Foreign currency](#foreign-currency)).

```bash
gnucash-plaintext fx-balances ledger.gnucash
gnucash-plaintext fx-balances ledger.gnucash --currency USD
gnucash-plaintext fx-balances ledger.gnucash --with-balance-only
gnucash-plaintext fx-balances ledger.gnucash --verify-costs
```

```
DATE         SPLIT GUID                         ACCOUNT                                      COST       ACQUIRED  BASIS BALANCE
-------------------------------------------------------------------------------------------------------------------------------
2026-01-05   c4ccb16d7be34e15a112d903319c5267   Assets:Accounts Receivable USD        1.4 CAD/USD     100.00 USD     100.00 USD
             Invoice INV-USD-001
2026-01-10   a0941ac334c44a31ba0120a0493c931c   Assets:Bank:USD                      1.35 CAD/USD     100.00 USD      60.00 USD
             Buy 100 USD at 1.35

Total USD basis balance: 160.00 USD
```

Read-only. The cost is stated with its direction — CAD per unit of the currency held — and the basis balance shown is the basis's own, not any account's balance.

`--verify-costs` re-checks every cost against the ledger it is derived from: that no basis balance is above what its basis brought in or below zero, and that any stored `cost_basis_cost` parses and agrees with the transaction. It runs the whole book, prints each basis that disagrees with the full computation behind it — both guids, the amount and value, every factor multiplied, and both answers with the one used — and exits 1 at the end if anything did. A basis whose figures cannot be read is reported with its traceback rather than ending the run. Rates are not checked, because rates run forward only: a file states one, the amount is multiplied by it and rounded, and the effective rate the ledger then carries — 45.00 USD at 1.405 books 63.23 CAD, a ratio of 6323/4500 — is that rounding rather than a discrepancy. Reading a figure back to ask which rate produced it has no answer. (Nor is a split's `share_price` checked against its value: GnuCash computes the rate *as* value over amount, so the comparison is one number against itself.)

```
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

#### Disposing of a credit: refund, write-off, or forfeit (`lot_owner:`)

A credit isn't attached to any document, so clearing one is just a normal ledger transaction: a counter account plus an AR/AP split that reduces the owner's open credit lot. Tag that AR/AP split with `lot_owner: kind:id[:guid]` and the importer joins it to the owner's oldest open credit lot. The counter account states the intent — no extra keyword:

| Owner + counter account | Operation |
|---|---|
| customer + bank/asset | refund the overpayment |
| customer + income | forfeit (customer abandons the credit) |
| vendor + bank/asset | vendor returns the overpayment |
| vendor + expense | vendor bad debt (overpayment you'll never get back) |

Refund a customer's $50 credit:

```
2026-02-15 * "Refund of overpayment to Acme"
  currency.mnemonic: "CAD"
  Assets:Bank -50.00 CAD
  Assets:Accounts Receivable 50.00 CAD
    lot_owner: customer:C001:9f14a498cc894d50931f855a9a31d594
```

Write a vendor's $50 credit off as bad debt:

```
2026-02-15 * "Vendor bad debt — V001 overpayment not returned"
  currency.mnemonic: "CAD"
  Expenses:Bad Debt 50.00 CAD
  Liabilities:Accounts Payable -50.00 CAD
    lot_owner: vendor:V001:3f6d4a17b218c47e85d290f3e9a2b1c4
```

Details:

- The trailing guid is the **owner's** authoritative key; it is always emitted on export and optional hand-written (`lot_owner: customer:C001` works). When present it must resolve to the same owner as the id — a mismatch is a hard error, never a warning.
- The `lot_owner:` split's own account fixes the owner type: a `customer` KVP must sit on an AR account and a `vendor` KVP on an AP account, and the importer rejects that mismatch (e.g. a `customer` KVP on an AP split). The counter account is not otherwise constrained on this path — it simply records which of the operations above this is.
- **Partial** is just a smaller amount — the residual credit stays open; an exact amount closes the lot.
- If the owner has no open credit to reduce and the split is itself credit-shaped (AR-negative / AP-positive), the importer instead **creates** a new credit lot and attaches the owner — this is how a *standalone* credit (money received with no invoice) is represented in plaintext. A clearing-shaped split with no credit to reduce is an error.
- This is the canonical, non-destructive way to dispose of a credit and works on every supported GnuCash version (it uses a primitive lot-split close, not the owner-level auto-apply that crashes on some builds).

#### Open-credit summary on AR/AP accounts: `open_prepayment:`

Exported AR and AP accounts carry an `open_prepayment:` block per open credit — the owner, owner guid, and amount — so the file shows each account's outstanding prepayments at a glance:

```
2026-01-01 open Assets:Accounts Receivable
  open_prepayment:
    customer: "C001"
    customer_guid: "9f14a498cc894d50931f855a9a31d594"
    amount: 50.00 CAD
```

It is informational and derived: the importer rebuilds the credits from the per-split `lot_owner:` KVPs, not from this summary, so the block is parsed and otherwise ignored. If a hand-edited summary disagrees with the book's actual lots, import prints a warning to stderr and still succeeds — the next export rewrites the correct figure.

### Identity and round-trip: `guid:`, `customer_guid:`, `vendor_guid:`

Every business-object block (`customer`, `vendor`, `taxtable`, `invoice`,
`bill`) carries a `guid:` field on export. The user-facing id (e.g.
`customer "C001"`) is the human handle; the guid is GnuCash's internal
primary key. Both are immutable once assigned.

```
customer "C001"
	guid: "9f14a498cc894d50931f855a9a31d594"
	name: "Acme Customer"
	currency: CAD

invoice "INV-001"
	guid: "b61b7b200f5b41ad97a8f775e8ef6156"
	customer_id: "C001"
	customer_guid: "9f14a498cc894d50931f855a9a31d594"
	currency: CAD
	date_opened: 2026-01-01
	...
```

**Hand-written files** can omit `guid:` entirely — GnuCash will assign a
fresh one on first import. On subsequent re-imports (after the first export
has put guids in the file) the importer uses the guid as the precise
identity key.

**Quote guid values.** Always quote: `guid: "abcd…"`. Mixed-hex unquoted
forms (`guid: b2b3…b4`) work because the parser treats them as strings,
but unquoted all-digit values like `guid: 22222222222222222222222222222222`
are auto-converted to a number and lose their digit count. The exporter
always emits quoted form.

**Cross-references** (`customer_guid:` on invoices, `vendor_guid:` on
bills) carry the *referenced* object's guid. `customer_id`/`vendor_id`
keep the file readable; the guid is the authoritative key. When both are
present they must resolve to the same record — otherwise the importer
errors with the conflict spelled out.

#### Re-import semantics: idempotent, per object type

Re-importing the same file is **idempotent** — and the importer
distinguishes between "no change needed" (`unchanged`) and "I refused
your change" (`skipped`) so a re-run reports something meaningful:

| Block | Directive matches existing | Directive differs from existing |
|---|---|---|
| `customer`, `vendor` | `unchanged` (no-op) | `updated` (mutable fields refreshed: name, address, active flag, custom KVP). |
| `taxtable` | `skipped` (refused) | `skipped` (refused). Tax tables are referenced by stored pointers from posted invoices/bills; mutating their entries would silently change accounting on past posted records. |
| `invoice`, `bill` (unposted) | `unchanged` | `updated` (entries rebuilt; if the directive carries a real `posted:` block the record is posted in the same import). |
| `invoice`, `bill` (posted) | `unchanged` | `updated` via **unpost → rebuild → repost**. Mirrors what the GnuCash UI itself supports: opening a posted invoice, unposting, editing, and reposting. The directive is the source of truth for the new posted state. As an optimisation: when the *only* difference is `posted: { ... }` → `posted: none` (entries and payments otherwise match), the importer takes a minimal-unpost path that preserves entry GUIDs (no destroy + recreate). |

#### Unposting without re-importing: `unpost-invoices` / `unpost-bills`

When you want to unpost without consulting any plaintext file (e.g. the
`.txt` is stale, or you just need a one-shot operation), use the
dedicated CLI commands:

```
gnucash-plaintext unpost-invoices ledger.gnucash INV-2026-001
gnucash-plaintext unpost-bills    ledger.gnucash BILL-2026-001
gnucash-plaintext unpost-invoices ledger.gnucash --by-guid 9f14a498cc894d50931f855a9a31d594
```

Behaviour:

- Calls GnuCash's `Unpost(False)` directly. The posting transaction is destroyed; payment transactions in the bank account remain but are no longer linked to a lot. (Same end state as the GnuCash UI's Unpost menu item.)
- **Entry GUIDs are preserved** — entries are not destroyed and recreated. External references to entries by GUID still resolve.
- Per-record line: `<id> (<guid>): unposted` (or `not posted`, `not found`, or `failed — multiple records share this id`).
- **Orphan-payment warning**: when the record being unposted was paid, the CLI lists each bank-side payment transaction that is about to be orphaned — with the orphan's GUID, date, bank account, amount, currency, customer/vendor name, and memo. The warning steers the user toward the two safe cleanup paths: `delete-transactions --by-guid <orphan-guid>` (drop the orphan, then re-import with a fresh `payment:` block), or a `payment:` block carrying `txn_guid: "<orphan-guid>"` on re-import (retargets the existing bank tx into the new posted lot — see [Q-004](docs/issues/Q-004-payment-transaction-duplicates.md)). Doing neither, then re-paying via a fresh `payment:` block, leaves the orphan in place alongside the new payment and silently doubles the recorded bank balance.
- Exit code 1 if any record was not found, not posted, or ambiguous; successful unposts are still saved.

For after-the-fact recovery — auditing a book that's already accumulated orphans from prior unpost runs — use `find-orphan-payments` (next section).

#### Unapplying a payment without unposting: `unapply-payment`

When a payment was applied to the wrong invoice (or a deposit turned out not to be a payment at all), you want to peel that payment off **without** touching the document — the invoice stays posted and simply returns to Outstanding. That is different from unpost (which drops the document to Draft and destroys the posting). Use `unapply-payment`:

```
# INV has ONE payment — no selector needed. That payment is detached and
# the freed amount moved to the named liability; INV returns to Outstanding.
gnucash-plaintext unapply-payment ledger.gnucash INV-2026-001 --to "Liabilities:Due to customer"

# INV has SEVERAL payments — peel exactly one, named by its bank-tx GUID.
# The other payments stay applied (INV becomes partially-paid). Here the
# freed amount is routed to income (e.g. it was really interest income).
gnucash-plaintext unapply-payment ledger.gnucash INV-2026-001 --txn <bank-tx-guid> --to "Income:Misc"

# THREE payments, two of them wrong — repeat --txn to peel just those two.
# The third payment stays applied; INV's Outstanding rises by the two amounts.
gnucash-plaintext unapply-payment ledger.gnucash INV-2026-001 \
    --txn <wrong-tx-1> --txn <wrong-tx-2> --to "Liabilities:Due to customer"

# Peel EVERY payment — INV returns to fully Outstanding (just-posted state).
gnucash-plaintext unapply-payment ledger.gnucash INV-2026-001 --all --to "Liabilities:Due to customer"

# A vendor bill instead of a customer invoice.
gnucash-plaintext unapply-payment ledger.gnucash BILL-2026-001 --bill --to "Liabilities:Due to vendor"
```

What it does: detaches the named payment's AR/AP split from the invoice/bill's posted lot — so the lot reopens (Outstanding, or partially-paid if other payments remain) — and moves that freed split to the account you name with `--to`. The document stays **posted**; the bank/income transaction is **never deleted** (the money still happened); only the freed split's account changes, so the transaction stays balanced.

- **`--to` is required**, and accepts **any** account type. The payment's prior account was overwritten when it was applied and isn't recorded, so only you know where the freed money belongs. Money you received that is no longer applied to an invoice is, in accounting terms, a payable you may owe back — typically a liability such as `Liabilities:Due to customer` / `Due to shareholder` (which need not be a GnuCash *A/Payable*-type account); you may equally route it to income, a clearing account, or an asset carried negative. It is your call.
- **Which payment(s)**: one payment → no selector needed; several → `--txn <bank-tx-guid>` to peel one, **repeat `--txn`** to peel a subset (two of three), or `--all` for every payment. On a multi-payment record, omitting all selectors is an error — never an implicit "all". Payments are identified by transaction GUID, so two payments of the same amount are unambiguous.
- `--bill` targets a vendor bill; `--by-guid` resolves the id argument as an invoice/bill GUID.

To find a payment's bank-tx GUID, run `find-orphan-payments` or read it from the invoice's exported `payment:` blocks (`txn_guid:`).

After unapplying, the freed amount sits in your `--to` account. To re-link it to the *correct* invoice, apply it there as you would any payment (e.g. a `payment:` block with `txn_guid:` retargeting that transaction, or `auto_apply_credit:` if you routed it to an AR credit).


Compared to the re-import path:

| | Re-import (`posted: { ... }` → `posted: none`) | `unpost-invoices` / `unpost-bills` |
|---|---|---|
| Reads .txt? | Yes — directive entries replace existing | No |
| Entry GUIDs | Preserved when only the posted block toggles; otherwise rebuilt | Always preserved |
| Use when... | The .txt is your source of truth and may also edit fields | The .txt is stale/absent and you only want the unpost |

#### Listing orphan bank-side payments: `find-orphan-payments`

After a series of unposts, the book may have payment-class bank transactions whose AR/AP-side split's lot is no longer attached to any invoice or bill — orphans. The live `unpost-invoices` / `unpost-bills` flow warns about each orphan it's about to create, but if those messages were missed (a prior session, an inherited book, etc.) the orphans accumulate silently and cause the re-pay-after-unpost duplicate-bank-balance trap.

`find-orphan-payments` scans the book and lists every orphan with its GUID, date, amount, currency, the customer/vendor it was originally paying, and the split memo. One row per orphaned payment, not per transaction: a deposit whose portions settled two documents, both since unposted, carries two orphans and each is its own row, with its own owner read from its own split. The figure is named against the account it is *of* — on a USD document settled out of a CAD bank that is the receivable, and the bank it was paid through is named on the line below. Totals per account at the end. Read-only — the command never deletes or modifies anything; the user picks the cleanup path per orphan.

Each row also prints the evidence it was classified on, and prints only what actually held: the engine's `xaccTransGetTxnType(tx) == 'P'`, the `txn_type: P` a previous export wrote, the `orphaned_by_unpost` note this tool writes on the split, and where the owner came from — the split's own lot, `gncOwnerGetOwnerFromTxn`, the exported `owner:` line, or a sibling orphan's lot on the same transaction.

```bash
# Whole-book sweep:
gnucash-plaintext find-orphan-payments ledger.gnucash

# Scope to a single customer (matched on the owner resolved for each row):
gnucash-plaintext find-orphan-payments ledger.gnucash --customer C001

# Scope to a single vendor (bill-side orphans):
gnucash-plaintext find-orphan-payments ledger.gnucash --vendor V001
```

Exit code 0 whether or not any orphans are found — the command is informational. A clean book reports `No orphan bank-side payment transactions found.` and exits 0.

Cleanup options the command points at, per orphan:

  a) `gnucash-plaintext delete-transactions <book> --by-guid <guid>` — drop the orphan (with a plaintext backup written), then re-import the invoice/bill with a fresh `payment:` block.
  b) Re-import the invoice/bill with a `payment:` block carrying `txn_guid: "<orphan-guid>"` — retargets the existing bank tx into the new posted lot (Q-004).

Option (a) is withdrawn for a GUID that carries money beyond the row naming it — another orphan on the same transaction, or a portion nobody has claimed yet — because deleting is by transaction and would take that with it. Those GUIDs are named at the end; where *every* GUID in the listing is one, the option is not offered at all. Option (b) moves a single split and is always available.

Detection criteria (so the user can trust the result). A transaction is examined when **either** reading answers: it is payment-class — `xaccTransGetTxnType(tx) == 'P'`, or the `txn_type: P` a previous export wrote — **or** one of its splits carries the `orphaned_by_unpost` note this tool writes on every split it is about to orphan. Either alone is enough, and the second is what finds a settlement attached by retargeting an existing bank transaction (`txn_guid:`), which is not payment-class and carries no owner backref: before the note existed such a settlement was listed by nothing at all. The note is needed because nothing in the book itself distinguishes the two shapes — unposting leaves the lot on the account, live and owner-attached, exactly like an owner's parked credit (CLAUDE.md finding 10).

Within an examined transaction, every marked split is reported as its own row. Where none is marked — a payment-class transaction on a book unposted by a version of this tool that predates the note — the row is the first AR/AP-side split whose lot has no invoice or bill attached. So a pre-note book lists what it always did; what it cannot do is separate a bank-paid orphan from an owner's credit on the same transaction, and unposting such a document again marks it.

Each orphan is pinned to a specific customer/vendor, though not to a specific invoice, since the lot → invoice link is destroyed by unpost.

#### Deleting unposted invoices/bills: `delete-invoices` / `delete-bills`

Hard-delete an unposted customer invoice or vendor bill by ID (or GUID
with `--by-guid`). Refuses posted records — to delete a previously
posted record, run the two-step:

```bash
gnucash-plaintext unpost-invoices ledger.gnucash INV-2026-001
gnucash-plaintext delete-invoices ledger.gnucash INV-2026-001
```

The explicit two-step keeps the destruction of the posting transaction
(and the orphaning of payment splits) under its own command rather
than as a silent side effect of `delete-*`.

```bash
gnucash-plaintext delete-invoices ledger.gnucash INV-DRAFT-001
gnucash-plaintext delete-bills    ledger.gnucash BILL-DRAFT-001 BILL-DRAFT-002
gnucash-plaintext delete-invoices ledger.gnucash --by-guid 9f14a498cc894d50931f855a9a31d594
```

Per-record output mirrors `delete-customers` / `unpost-invoices`:

```
INV-DRAFT-001 (abc123…): deleted
INV-POSTED-002 (def456…): failed — posted; run unpost-invoices first, then delete-invoices
INV-MISSING: not found
INV-DUPLICATE-ID: failed — multiple records share this id; rerun with --by-guid
```

Exit code 1 if any record was not found, was posted, or had a duplicate
id; successful deletes are still saved.

In all cases the importer first verifies that the directive's identity
agrees with whatever's already in the book. The following are caught
with a clear error rather than silently doing the wrong thing:

- the directive's `guid:` resolves to a record whose `id` (or name, for
  tax tables) doesn't match — refusing to silently rename, since
  invoices may reference the old id
- the directive's `guid:` is unknown but its `id` is taken — refusing
  to rebuild because we cannot assign the new guid without overwriting
  the existing record
- the book already contains multiple records with the same `id` —
  legacy data needs cleanup in the GnuCash GUI before re-import
- an invoice/bill cross-reference has both `customer_id` (or
  `vendor_id`) and the matching `_guid` field but they resolve to
  different records
- the requested guid is already used by a different entity type
  (transaction, account, customer, vendor, tax table) — GnuCash GUIDs
  are unique book-wide

### Reconciling invoice and bill payments with a bank feed

When a bank feed (QFX, CSV, HTML) is imported **before** the matching invoice or bill, you can link them without creating a duplicate bank entry using `txn_guid:` in the `payment:` block. Exported `payment:` blocks always carry both `txn_guid:` and `txn_split_guid:` so the importer can deterministically rebuild the same bank-tx-to-invoice routing in a fresh book:

```
payment:
  bank_account: "Assets:Bank"
  txn_guid: "317c8ae6e0084c33951d052b9f1b9f23"
  txn_split_guid: "b6b63193116644cbb33cd72b53980011"
```

Use `find-transactions` to look up the GUID:

```bash
gnucash-plaintext find-transactions ledger.gnucash \
    --account "Assets:Bank" --date 2026-01-15 --amount 500
```

The importer looks up the existing bank transaction by `txn_guid:`, finds the specific AR-side split named by `txn_split_guid:`, and attaches it to the invoice's posted lot in-place — no new transaction is created and all original bank metadata is preserved.

`txn_split_guid:` is optional in hand-written plaintext (the importer falls back to the iterative-retarget mechanism that walks the bank tx's counter-splits in plaintext order). It is **always** emitted on export so every round-trip is order-independent and unambiguous.

**A `txn_guid:` that names nothing has two readings**, and the block cannot tell them apart on its own: a document being rebuilt into a fresh book, where the bank transaction genuinely is not there yet, and a retarget against the book that holds it, where the guid is simply mistyped. The first has to go through — a printed document carries the guids of the book it came from precisely so that book relinks rather than paying twice, and it still has to be readable elsewhere. The second must not: recording the payment from the block enters money that has already moved.

What separates them is the book. Where the block's own `date:`, `amount:`, direction, account and `memo:` describe a transaction the book already has, the money is here and the guid is wrong, and the run is refused — naming that transaction, its guid, and the document it already settles, so you can either correct the guid to it or drop `txn_guid:`. A rebuild into a book that never held the money matches nothing and is untouched.

Two payments can agree on every one of those fields, and then nothing in the file tells them apart: one customer with two invoices for the same figure, paid on the same day into the same account, with the same memo on both bank lines. Give the second its own `memo:` — naming the movement is what a memo is for — and both import. Between two *different* owners the check never fires, because the remedy it offers does not exist there: one customer's receipt cannot settle another's invoice, so a match across owners can only be coincidence.

#### One bank transaction covering multiple invoices or bills

When a single bank deposit covers several invoices (or one cheque pays several bills), each invoice's `payment:` block names the same `txn_guid:` and its own `txn_split_guid:` — pointing at the specific AR/AP-side split that belongs to that invoice. The bank tx itself is emitted once as a standalone `*` transaction with `guid:` and per-split `guid:` so the per-invoice references resolve cleanly:

```
2026-05-15 * "Acme — wire covering INV-A/B/C"
  guid: "31f0b8e6c5a14df8b29a4d8e9c3471f2"
  Assets:Bank 400.00 CAD
    guid: "f3c561adfe1c4296bd6ed114773b7518"
  Assets:Accounts Receivable -100.00 CAD
    guid: "b6b63193116644cbb33cd72b53980011"
  Assets:Accounts Receivable -120.00 CAD
    guid: "67550ad77789476eb9dcd30982cffde7"
  Assets:Accounts Receivable -180.00 CAD
    guid: "aa746aa94e1d48118ec16d0fc31479d6"

invoice "INV-EX-A-100"
  ...
  payment:
    bank_account: "Assets:Bank"
    txn_guid: "31f0b8e6c5a14df8b29a4d8e9c3471f2"
    txn_split_guid: "b6b63193116644cbb33cd72b53980011"
```

The same `txn_guid:` appears on the other two invoices' payment blocks, each with its own `txn_split_guid:`.

#### Import order guarantee

A single `import --include-business-objects` call processes directives in this order:

```
accounts → customers/vendors/taxtables → standalone transactions → invoices/bills
```

Standalone transactions are created (with their declared `guid:` on both the transaction and each split) **before** any invoice or bill is processed, so the `payment:` blocks' `txn_guid:`/`txn_split_guid:` references always resolve in the same import call — no two-step import needed, even for a fresh book.

See **[docs/comprehensive-roundtrip-example.md](docs/comprehensive-roundtrip-example.md)** for the canonical end-to-end roundtrip walkthrough — a single source book exercising every plaintext surface (accounts, customers, vendors, tax tables, invoices and bills, all payment shapes: cash, retarget, overpayment with prepayment credit, credit consumption via `auto_apply_credit`, and the multi-invoice-one-bank-tx shape) exported and re-imported into a fresh book with semantic identity preserved down to per-split GUIDs. And **[docs/invoice-payment-reconciliation.md](docs/invoice-payment-reconciliation.md)** for the bank-feed-first workflow, error reference, and the invoice-first alternative, plus **[docs/bill-payment-reconciliation.md](docs/bill-payment-reconciliation.md)** for the vendor-bill (Accounts Payable) side — partial payments, vendor credits, detection, and `unapply-payment` corrections.

#### Cash-basis sales (Q-018)

For cash-basis tax filers who want each sale's posted date to match the cash-receipt date, the workflow is the bank-feed-first pattern with three constraints: `posted.date == payment.date == bank-tx.date`, a single `payment:` block carrying `txn_guid:` + `txn_split_guid:` to retarget the existing bank tx, and an optional `cash_basis: true` line on the invoice header as a tax-method KVP. The flag is descriptive (purely a label for the issuer's tax filing — partial / installment payments are still allowed alongside it) and does not expose the tax-method classification in customer-facing rendering. For invoices that are issued but not yet paid, setting `cash_basis: true` on an unposted invoice renders an **UNPAID** badge instead of DRAFT, and an optional `due_date: YYYY-MM-DD` header field supplies the customer-facing due date. See **[docs/invoice-payment-reconciliation.md § Cash-basis sales](docs/invoice-payment-reconciliation.md#cash-basis-sales-q-018-same-day-post--pay)** for the worked example.

### Retiring customers and vendors (archive)

Use `archive-customers` or `archive-vendors` to soft-hide one or more
entities by setting them inactive (`SetActive(False)`). Archived entities
are hidden from the GnuCash UI but remain in the book with all their invoice
and bill history intact. The `active: false` field is preserved on export and
restored on import.

```bash
# Archive one or more customers
gnucash-plaintext archive-customers mybook.gnucash CUST-001 CUST-002

# Archive one or more vendors
gnucash-plaintext archive-vendors mybook.gnucash VEND-001
```

Per-ID status is printed for every ID requested. Each line shows both
the user-facing id and the matched record's GUID so you can correlate the
output with whatever you have on hand:

```
CUST-001 (9f14a498cc894d50931f855a9a31d594): archived
CUST-002 (b02d3aa7df3a4f0a8e7c1cda5e88a3a1): archived — 5 invoice(s) linked
CUST-003 (47b9c5e0b7e44b53b4d9f2c8e1e8a3b1): already archived
CUST-004: not found
```

The "not found" line has no GUID because no record was matched.

The linked invoice/bill count is informational — archiving always succeeds for
a found, currently-active entity. Exit code 1 if any ID was not found or
already archived.

#### Addressing by GUID instead of customer/vendor number

Both `archive-customers` and `archive-vendors` accept a `--by-guid` flag.
With it set, positional args are interpreted as GUIDs (32-char hex, with or
without UUID hyphens) instead of customer/vendor numbers. The output format
is the same `<id> (<guid>)` regardless of which form you used as input:

```bash
gnucash-plaintext archive-customers mybook.gnucash --by-guid \
    9f14a498cc894d50931f855a9a31d594
```

```
CUST-001 (9f14a498cc894d50931f855a9a31d594): archived
```

Use this when you have an entity's GUID (e.g. parsed from an exported
plaintext file) and don't want the extra ID-lookup step. Mixing GUIDs and
numbers in one invocation isn't supported — pick one form per call.

A malformed GUID (e.g. wrong length, not hex) is rejected up-front with a
clear error rather than producing a confusing "not found".

### Deleting customers permanently

`delete-customers` hard-deletes a customer from the book. This is irreversible.
**Archiving is almost always the better choice** — it preserves all invoice
history and can be undone by re-importing the record without `active: false`.

Use `delete-customers` only for customers created by mistake that have **never
had any invoices raised against them**. Deletion is blocked if any invoices
exist (paid or unpaid, posted or unposted):

```bash
gnucash-plaintext delete-customers mybook.gnucash CUST-001 CUST-002
```

To clean up a customer whose only invoices were also mistakes, drop the
invoices first with [`delete-invoices`](#deleting-unposted-invoicesbills-delete-invoices--delete-bills)
(running `unpost-invoices` first if any were posted), then re-run
`delete-customers`.

```
CUST-001 (9f14a498cc894d50931f855a9a31d594): deleted
CUST-002 (b02d3aa7df3a4f0a8e7c1cda5e88a3a1): failed — cannot delete, 3 invoice(s) linked
CUST-003: not found
```

Exit code 1 if any ID failed or was not found.

`delete-customers` also accepts `--by-guid` to address records by GUID
(same semantics as `archive-customers --by-guid` above):

```bash
gnucash-plaintext delete-customers mybook.gnucash --by-guid \
    9f14a498cc894d50931f855a9a31d594
```

> **Note:** Vendor deletion is not supported. GnuCash's vendor entity does not
> persist correctly through the XML backend when `Destroy()` is called — the
> vendor reappears after save/reload. Use `archive-vendors` instead.

### Print an invoice (PDF, HTML, or plaintext)

Generate a PDF for any posted invoice:

```bash
gnucash-plaintext print-invoice mybook.gnucash INV-2026-001 -o invoice.pdf
```

> **Needs Guile and WeasyPrint.** GnuCash's own report draws the page and that report is Scheme, so a `libguile` has to be installed — most distributions pull it in with `gnucash` itself, but Fedora and openSUSE do not, and there `dnf install guile` / `zypper install guile` is the fix. PDF output additionally needs WeasyPrint (`pip install weasyprint`). Neither is needed for `--format plaintext`, and a missing one is reported by name rather than as a traceback.

`--format {pdf,html,plaintext}` selects the output format (defaults to `pdf`). **The PDF and HTML pages are GnuCash's own.** By default they are drawn by GnuCash's **Printable Invoice** — the report its own File → Print Invoice uses — so a printed document is the document GnuCash prints: its heading, its columns, its totals, its wording. `--report` and `--report-file` choose another, including one you wrote; see "Changing the page means changing the report that draws it" below. Every supported version renders it, GnuCash 3.8 included; a Guile interpreter runs inside this process and is handed the book this process already has open.

What that means for the page: `Invoice #<id>` at the top left, the customer on one side and your company on the other, then Date, Description, Action, Quantity, Unit Price, Discount, Taxable and Total, and Net Price, one row per tax account, Total Price and Amount Due beneath. An unposted document is priced from its entries and marked "Invoice in progress…"; a paid one lists its payments and an amount due of zero. A bill is a vendor's invoice and is drawn by the same report, with the vendor as the document's owner.

Four of the report's own switches are set, and nothing else — and only on the reports listed under `--report` below, never on one you wrote. (The last of the four is spelled differently by different reports, so it is written out more than once.) Two carry fields this format has and GnuCash ships hidden — the document's `notes:`, and the seller's `contact:` (which GnuCash prints as "Please direct all enquiries to …"). One asks for the tax **per account**, so a page states GST and PST by name and by amount rather than adding them into a single `Tax` figure: a filer reclaims the one and not the other, and a Canadian invoice has to state the GST/HST amount, which their sum does not. The last empties `Extra Notes`, whose default is the literal "Thank you for your patronage!" — uninvited on an invoice of yours, and backwards on a bill, where it would thank the supplier for their patronage of you.

Every figure is in the **document's** currency: a USD invoice on a CAD income account states USD throughout, never the book's valuation of it.

**Multi-invoice selection (Q-017)**: `print-invoice` accepts any combination of positional IDs, glob patterns, a `--from`/`--to` date range, or a `--customer` filter:

```bash
# Combined multi-page PDF
gnucash-plaintext print-invoice mybook.gnucash INV-001 INV-002 INV-003 -o combined.pdf

# All Q1 invoices for one customer, one PDF per invoice in a directory
gnucash-plaintext print-invoice mybook.gnucash --from 2026-01-01 --to 2026-03-31 \
    --customer C-001 -o q1/

# Glob pattern, plaintext output to stdout
gnucash-plaintext print-invoice mybook.gnucash 'INV-2026-*' --format plaintext -o -
```

Output composition is `-o file.ext` (single combined file), `-o dir/` (one file per invoice), or `-o -` (stdout, plaintext only).

**Plaintext format (Q-017)**: `--format plaintext` emits the same canonical plaintext syntax used by `export`, populated with **informational** totals — `entry_amount` and `entry_tax` per line, repeatable `breakdown:` sub-blocks showing which tax account got which dollar (audit-friendly for combined HST = GST + PST), and invoice-level `invoice_subtotal`, `invoice_tax_total`, `invoice_total`. The exporter never emits these (round-trip stays minimal); the renderer does. On re-import the values are recomputed from the source-of-truth fields (`quantity × price × tax_table`) and the importer errors loudly on any mismatch — so you get tamper detection automatically when sharing rendered plaintext files. Draft (unposted) invoices emit only `invoice_subtotal` since per-entry tax requires posting.

**Free text of your own, without a template of your own.** GnuCash's page has no row for two things people want on a document, so two rows are added to it and nothing else:

* the **seller's** block, under your company's address: your GST and each PST registration number (GnuCash has no field for either — this tool keeps them in book options), followed by the book's `extra_text1:`, `extra_text2:` … lines;
* the **owner's** block, under the customer or vendor address: *their* `extra_text1:`, `extra_text2:` … lines.

The report builds its page in Scheme and has no template file to edit, so these go in as one more row of the block they belong beside — added to what GnuCash drew, never woven into how it draws it.

One key is one printed line, numbered like the `addr1:`..`addr4:` keys elsewhere in this format, and they print exactly as written. Nothing is interpreted, so "a different website for wholesale customers" is something you write on the customer rather than a template you maintain:

```
company
  extra_text1: "Payment by e-transfer to pay@example.test"
  extra_text2: "Net 30"

customer "C-001"
  extra_text1: "Order through wholesale.example.test"
  extra_text2: "Account manager: Jane"
```

They are ordinary custom keys, so they export and re-import with everything else. Other custom keys are **not** printed: the seller's `fiscal_year_end:` and a customer's `credit_rating:` are the book owner's business, and the document goes to the other party.

#### Changing the page means changing the report that draws it

In rising order of effort:

1. **The book's own fields.** The company block comes from **File → Properties → Business**; the customer's or vendor's block comes from their address. Most of what people want changed is here.
2. **The two `extra_text` blocks above**, for what GnuCash keeps no field for at all.
3. **A different report GnuCash already ships.** `--report` takes the report's English name — `Printable Invoice` (the default), `Fancy Invoice`, `Easy Invoice`, `Tax Invoice` or `Australian Tax Invoice` — or a template guid, in either case and with or without `uuidgen`'s dashes. All five draw on every supported version:

   ```bash
   gnucash-plaintext print-invoice mybook.gnucash INV-2026-001 \
       -o invoice.pdf --report "Fancy Invoice"
   ```

   `Fancy Invoice` and `Easy Invoice` lay out the same company and client blocks as the default, so everything this tool adds to the seller's block comes with you — **your GST and PST registration numbers** and the `extra_text` lines — and each tax is still named and totalled separately.

   **`Tax Invoice` and `Australian Tax Invoice` carry none of that.** They build their page from their own template with no such blocks, so a document printed with either states neither registration number, and they total tax their own way — a Tax Rate and a Tax Amount column per line, rather than a named GST and PST total. If you are invoicing in Canada, that page is missing something the CRA requires you to state. It still prints — the report is doing what it was written to do — but the run says on stderr that it could not place those lines, naming the first of them, so a document that lost your GST number does not leave silently.

   A report registers its **English** name, and GnuCash translates only when it draws its own menus — so a French GnuCash lists `Facture améliorée` for the report that is `Fancy Invoice` here. Naming a report by its guid works in every language.

4. **A report of your own.** `--report-file` loads a `.scm` before the report is looked up, so a file of yours calling `gnc:define-report` is registered by the time `--report` names it:

   ```bash
   gnucash-plaintext print-invoice mybook.gnucash INV-2026-001 \
       -o invoice.pdf --report-file my-invoice.scm --report "My Invoice"
   ```

   This is GnuCash's own extension point, not one invented here: your report is written the way every report GnuCash ships is written, runs in the same machinery, and works from GnuCash's GUI too if you install it there. Start from `invoice.scm` in GnuCash's report directory — `/usr/share/guile/site/*/gnucash/reports/standard/` on 4.x and 5.x, `/usr/share/gnucash/scm/gnucash/report/` on 3.8 — and `tests/fixtures/a_report_of_your_own.scm` is a minimal one to read first, including the one thing to know: the options API changed between 3.8 and 4.x, so a report meant to run on both asks `(defined? 'gnc-new-optiondb)` and declares its options either way.

   **If you copy one of GnuCash's, give your report a `report-guid` of its own** — `uuidgen` prints one, in any case and with or without its dashes. Keeping the guid you copied is the mistake this warns about twice: registered under a guid GnuCash already has, your report is refused as a duplicate and never registers at all, so `--report` cannot find it by name; registered under that guid in another case, both answer to every spelling of it and `--report <that guid>` is refused as ambiguous. Give it a name of its own too, unless you mean to name it by guid from then on: GnuCash accepts a report that reuses another's *name* — the guids differ, so both register — but two of them then answer to it, and `--report "<that name>"` is refused as ambiguous, for the report you copied as well as yours.

   Your report is handed the document through the `General / Invoice Number` option, which this tool sets — a report without that option is refused by name, since there is no way to tell it which document to draw. None of the display switches above is set on a report of yours: those belong to the reports listed under 3, and your options are yours.

   The seller's and owner's blocks follow your layout rather than being required of it. If your report keeps `make-company-table` and `make-client-table` — which it will if you started from `invoice.scm` — the registration numbers and `extra_text` lines are added to those blocks as they are on GnuCash's own page. If it lays the page out some other way, they are simply left out — no refusal and no warning, where GnuCash's own page would have been refused for the same absence. Your page is yours, and the numbers are on the book (`Business/Company GST Number` and the `extra_text` keys) for your report to read if it wants them.

   Keeping the block but not a table inside it — the seller written out as text, say — is the case in between, and the run says so on stderr rather than staying quiet: the rows go in at the end of the block's own table, so a block without one has nowhere to hold them. Nothing is refused and the document prints; you are told which lines it could not place.

So a field this format carries that GnuCash's page has no row for — an unposted document's `due_date:` is the one such case — prints only if your own report prints it. It round-trips through the ledger either way.

**The `action:` field on invoice entries** is optional. Omitting the line is equivalent to `action: ""` — the entry's action is set to empty. If you want to preserve a non-empty action (e.g. "Hours") across re-imports, you must include `action: "Hours"` in the directive every time; the importer treats each entry directive as the full source of truth, not a partial patch.

**Back-compat**: the original `--invoice-id <ID>` flag is still accepted and behaves as a single-value alias for a positional ID.

Handle conflicts with resolution strategies:

```bash
# Skip conflicting transactions (default)
gnucash-plaintext import mybook.gnucash transactions.txt --strategy skip

# Keep existing transactions on conflict
gnucash-plaintext import mybook.gnucash transactions.txt --strategy keep-existing

# Replace with incoming transactions on conflict
gnucash-plaintext import mybook.gnucash transactions.txt --strategy keep-incoming

# Update existing transactions in-place by GUID (preserves GUID)
gnucash-plaintext import mybook.gnucash transactions.txt --strategy update
```

**`--strategy update`: stable edit-and-reimport workflow**

When a transaction in the plaintext file carries a `guid:` metadata field that matches
an existing transaction in the book, `--strategy update` modifies that transaction
in-place — description, date, amounts, splits, notes, doc_link, and custom KVP
metadata — without destroying or recreating it. Custom metadata is **merged**: new
keys are added and existing keys are overwritten, but keys absent from the directive
are preserved unchanged. Because the GnuCash object itself is never replaced, its GUID is
preserved. This makes the workflow stable across multiple runs:

```
export → edit plaintext → re-import --strategy update → export again …
```

Each re-import finds the same GUID and updates the same transaction. No phantom
duplicates are created regardless of how many times you repeat the cycle.

**`--strategy update` is strict:** every transaction in the plaintext file must have a
`guid:` field, and every GUID must match an existing transaction in the book. The command
fails immediately if either condition is not met — it will never silently create a new
transaction. All GUIDs are validated before any changes are applied, so a file with one
bad GUID leaves the book untouched.

**`update` strategy — field update semantics:**

When using `--strategy update`, each field is updated only if it is explicitly present in the plaintext file. The rules for `memo` (and `action`) on splits are:

| Plaintext value | Effect on existing GnuCash memo |
|---|---|
| Field omitted entirely | Left unchanged |
| `memo: ""` (empty string) | Cleared (set to empty) |
| `memo: "some text"` | Replaced with new text |

In other words, **omitting a field means "leave it alone"**, while supplying an empty string means "clear it". This applies to both split `memo` and split `action`.

**How conflicts are detected:**

An account from plaintext exists in GnuCash if:
- Account GUIDs are equal, or
- Account full names are equal
- If no GUID and names don't match, it's considered a new account

A transaction from plaintext exists in GnuCash if:
- Transaction GUIDs are equal, or
- Transaction signature matches: `(date, [split account 1, …, split account N], doc_link, tx_num, owner)` — two same-day same-account transactions that differ on any of `doc_link`, `tx_num`, or `owner` are treated as distinct, so a second grocery trip on the same day with a different receipt link or a different check number is not skipped as a duplicate.
- If no GUID and signature doesn't match, it's considered a new transaction

When a candidate transaction is skipped as a duplicate, `gnucash-plaintext import` logs a `WARNING` line spelling out the matched signature components and the GUID of the existing transaction it matched against, so you can see *why* an import was skipped without enabling verbose logging.

### Generate an income statement

Generate an income statement for a fiscal period, with optional multi-currency FX conversion to CAD (for CRA T2 filing).

A date range is required — use one of:

```bash
# Fiscal year end (start is auto-computed as end − 1 year + 1 day)
gnucash-plaintext income-statement mybook.gnucash --fiscal-year-end 2024-12-31

# Explicit date range
gnucash-plaintext income-statement mybook.gnucash --start 2023-04-01 --end 2024-03-31
```

Output formats — text (default), HTML, or PDF:

```bash
# Text to stdout (default)
gnucash-plaintext income-statement mybook.gnucash --fiscal-year-end 2024-12-31

# HTML report
gnucash-plaintext income-statement mybook.gnucash \
    --fiscal-year-end 2024-03-31 \
    --output-format html --output report.html

# PDF report (requires WeasyPrint)
gnucash-plaintext income-statement mybook.gnucash \
    --fiscal-year-end 2024-03-31 \
    --output-format pdf --output report.pdf
```

Multi-currency FX conversion to CAD (required for CRA T2 totals):

```bash
gnucash-plaintext income-statement mybook.gnucash \
    --fiscal-year-end 2024-03-31 \
    --fx-rates rates.yaml \
    --output-format pdf --output report.pdf
```

The `rates.yaml` file maps currency codes to their CAD rates:

```yaml
USD: 1.36
HKD: 0.17
CNY: 0.19
```

The income statement **excludes closing entries**, so it reports the true period
result whether or not the books have been closed for the year (see "Closing the
books" below). Close the books and re-run it — the statement is unchanged.

### Generate a balance sheet

Assets / Liabilities / Equity as of a date, with a **Current Year Earnings** line
so it balances whether or not the books are closed (before closing, net income
shows as Current Year Earnings; after closing, it sits in Equity: Retained
Earnings):

```bash
gnucash-plaintext balance-sheet mybook.gnucash --as-of 2024-12-31
gnucash-plaintext balance-sheet mybook.gnucash --as-of 2024-03-31 --fx-rates rates.yaml
```

Every asset and liability account type is reported — Bank, Cash, Stock, Mutual
Fund, Accounts Receivable on the asset side; Credit Card, Accounts Payable and
the rest on the liability side. Foreign-currency accounts stay in their own
currency unless you pass `--fx-rates` to consolidate to CAD.

**Securities: cost by default, market with `--prices`.** A Stock or Mutual Fund
holding is shown at its **cost basis** (what you paid, in the transaction
currency) unless you supply current prices. Only you know the price that's
current, so pass a `--prices` file — same shape as `--fx-rates`, one
`MNEMONIC: price` line per security — and each holding is valued at
**shares × price**:

```yaml
# prices.yaml — price per unit in the security's own trading currency,
# as of the balance-sheet date
ACME: 60     # a CAD-bought holding → priced in CAD
USTECH: 95   # a USD-bought holding → priced in USD (needs --fx-rates, below)
```

```bash
gnucash-plaintext balance-sheet mybook.gnucash --as-of 2024-12-31 --prices prices.yaml
```

The price is read in the **same currency the holding was bought in**: a
CAD-purchased stock is priced in CAD, a USD-purchased one in USD. For a
foreign-currency holding, also pass `--fx-rates` so its market value can be
converted to CAD — otherwise the command stops and tells you exactly which rate
to add, rather than mis-valuing the holding.

The gain or loss versus cost isn't booked on any account, so the balance sheet
adds a single **Unrealized Gains** line to Equity to absorb it — exactly as
GnuCash's own market-value balance sheet does — and the statement still balances.
A security with no entry in the prices file stays at cost. `--prices` works on
`report` too.

### Both statements at once: `report`

T2/GIFI prep needs the income statement and the balance sheet for the same
period. `report` runs the statements you **name** against a single (expensive)
book open, output combined — `report` being GnuCash's own term for these:

```bash
gnucash-plaintext report mybook.gnucash income-statement balance-sheet \
    --fiscal-year-end 2024-12-31
```

You list the statements explicitly (`income-statement`, `balance-sheet`) — no
hidden bundle. The income statement covers the fiscal period; the balance sheet
is as of the period end (override with `--as-of`). `--fx-rates` and `--output`
apply across both. It is read-only.

### Closing the books

`close-books` zeroes Income/Expense at year end into `Equity: Retained Earnings:
{currency}`, marking each closing transaction with GnuCash's closing-transaction
flag (so GnuCash's reports, the income statement above, and `--force` re-close
all recognise it — not a fragile description match). The flag round-trips through
plaintext export/import (`closing: #True`), so a roundtrip never silently
un-closes the books.

```bash
gnucash-plaintext close-books mybook.gnucash --closing-date 2024-12-31
gnucash-plaintext close-books mybook.gnucash --closing-date 2024-12-31 --status
gnucash-plaintext close-books mybook.gnucash --closing-date 2024-12-31 --force   # re-close
```

### Export account balances

Output account balances as of a given date in balance directive format.
Each account balance is the **recursive cumulative sum** of the account and all its sub-accounts.

```bash
# Whole book: every account with its recursive total (requires FX rates for multi-currency books)
gnucash-plaintext account-balance mybook.gnucash --as-of 2024-12-31 --fx-rates rates.yaml

# Single account total only
gnucash-plaintext account-balance mybook.gnucash "Assets:Bank" --as-of 2024-12-31

# Single account + sub-account breakdown
gnucash-plaintext account-balance mybook.gnucash "Assets:Bank" --as-of 2024-12-31 --with-children

# Single-currency account (no FX needed)
gnucash-plaintext account-balance mybook.gnucash "Expenses:Food" --as-of 2024-12-31

# Save to file
gnucash-plaintext account-balance mybook.gnucash "Assets:Bank" --as-of 2024-12-31 -o balances.txt
```

**Without ACCOUNT_PREFIX**: outputs every account in the book. Multi-currency books require
`--fx-rates` (or rates already in the GnuCash pricedb); otherwise an error is raised.

**With ACCOUNT_PREFIX** (default): outputs only the matched account's recursive total.

**With ACCOUNT_PREFIX + `--with-children`**: outputs the matched account and each
sub-account, each showing its own recursive total.

Output format (balance directive):

```
2024-12-31 balance
	Assets:Bank  4899.00 CAD
	Assets:Bank:Checking  3420.00 CAD
	Assets:Bank:HKD  1479.00 CAD
		share_price: "17/100"
		original: "8700.00 HKD"
```

With `--fx-rates`: consolidate all accounts to CAD and update the GnuCash pricedb for any
currencies whose rate has changed (only when the rate differs from the current pricedb entry):

```bash
gnucash-plaintext account-balance mybook.gnucash \
    --as-of 2024-12-31 \
    --fx-rates rates.yaml
```

Non-CAD leaf accounts include `share_price` (exchange rate used) and `original` (amount in
the native currency) metadata lines, matching the transaction plaintext format.

### Validate GnuCash ledger

Check ledger integrity:

```bash
# Full validation report
gnucash-plaintext validate mybook.gnucash

# Quick check (errors only)
gnucash-plaintext validate mybook.gnucash --quick

# Show statistics
gnucash-plaintext validate mybook.gnucash --stats

# Save report to file
gnucash-plaintext validate mybook.gnucash --report validation.txt
```

## Development

This project uses Docker for development to ensure a consistent environment across all platforms. GnuCash Python bindings are system-dependent and cannot be installed via pip, so Docker provides a reliable way to develop and test the application.

**Using Podman?** See [PODMAN.md](PODMAN.md) for Podman-specific instructions and compatibility notes.

### Getting Started

After cloning the repository, start the dev environment:

```bash
./scripts/dev-start.sh
```

**Windows users**: run from WSL2. Native PowerShell / CMD wrappers were
removed because Docker-in-Docker depends on the host's Unix socket;
WSL2 also gives meaningfully better Docker performance on Windows.

**What you get:**
- VS Code Server at https://localhost:8765 (password: `123456`)
  - **Note**: Uses self-signed SSL certificate - browser will show security warning
  - Click "Advanced" → "Proceed to localhost (unsafe)" to continue (safe for local dev)
- GnuCash Python bindings pre-installed and ready to use
- Python package installed with all dependencies
- Docker-in-Docker support — run test scripts from anywhere
- Live code sync - changes reflect immediately
- Git hooks automatically installed (linting + tests before commit)

**Inside VS Code Server terminal**, you can:
```bash
# Run tests directly (faster)
pytest tests/
pytest tests/unit/ -v

# Or use the same scripts as on host (Docker-in-Docker)
./scripts/test.sh
./scripts/test.sh debian12  # Test on different GnuCash version

# Use the CLI
gnucash-plaintext --help
gnucash-plaintext export myfile.gnucash output.txt
```

To stop the environment:
```bash
./scripts/dev-stop.sh
```

### Git Hooks

Git hooks are installed automatically when you run `./scripts/dev-start.sh`.

The pre-commit hook runs before every commit and checks:
- Code linting with `ruff check .`
- All tests with `./scripts/test.sh`

Commits are blocked if checks fail. To manually install hooks (if needed):

```bash
./scripts/install-hooks.sh
```

### Platform Support

- **Linux** and **macOS**: Full Docker-in-Docker support — same commands
  work on host and inside container.
- **Windows**: run from **WSL2**. Native PowerShell / CMD wrappers were
  removed (see "Getting Started" above for the rationale).

### Running Tests

```bash
# From host machine
./scripts/test.sh           # Run all tests with default image
./scripts/test.sh debian12  # Run with Debian 12 (GnuCash 4.13)
./scripts/test.sh latest tests/unit/  # Run specific test directory

# Inside VS Code Server
pytest tests/               # Direct execution (faster)
./scripts/test.sh           # Via Docker wrapper (Docker-in-Docker)
```

### Code Quality & Linting

This project uses [Ruff](https://docs.astral.sh/ruff/) for linting and formatting.

```bash
# Inside VS Code Server or dev container
# Check code for issues
ruff check .

# Auto-fix issues
ruff check --fix .

# Format code
ruff format .

# Check and format together
ruff check --fix . && ruff format .
```

**VS Code Integration**: Ruff extension is pre-installed in the dev environment. Code will be automatically formatted on save and imports will be organized.

### Supported GnuCash Versions

The project is tested against multiple GnuCash versions using different Docker base images:

| Distribution | GnuCash Version | Tag |
|--------------|----------------|-----|
| Debian 13 | 5.10 | `latest` |
| Debian 12 | 4.13 | `debian12` |
| Debian 11 | 4.4 | `debian11` |
| Ubuntu 26.04 | 5.14 | `ubuntu26` |
| Ubuntu 24.04 | 5.5 | `ubuntu24` |
| Ubuntu 22.04 | 4.8 | `ubuntu22` |
| Ubuntu 20.04 | 3.8 | `ubuntu20` |
| Fedora 41 | 5.13 | `fedora41` |
| Arch Linux | 5.15 | `arch` |
| openSUSE Tumbleweed | 5.16 | `opensuse` |

Ten builds, and the version is what each image's own package database reports rather than what the base distribution is expected to ship — `ubuntu24` carries 5.5, not the 4.9 it was listed as for a long time. The last three build from their own Dockerfiles (`Dockerfile.fedora`, `Dockerfile.arch`, `Dockerfile.opensuse`) rather than from a `BASE_IMAGE` build argument.

### Interactive Development Shell

```bash
# Start interactive bash shell in container
./scripts/shell.sh          # Use latest image
./scripts/shell.sh debian12 # Use Debian 12 image

# Inside container
cd /workspace
python3 -c "import gnucash; print('GnuCash available!')"
gnucash-plaintext --help
```

### Running Arbitrary Commands

```bash
# Run any command in Docker container
./scripts/run.sh python3 --version
./scripts/run.sh debian12 python3 script.py
./scripts/run.sh gnucash-plaintext --help
```

### More Information

For comprehensive documentation on Docker development, helper scripts, troubleshooting, and advanced usage, see [`scripts/README.md`](scripts/README.md).

Key topics covered:
- Docker Compose architecture (base image, dev image, volumes, DinD)
- Cross-platform script usage (Linux/macOS native; Windows via WSL2)
- Troubleshooting Docker socket permissions
- Fixing path mounting issues in Docker-in-Docker
- VS Code Server configuration and settings persistence
