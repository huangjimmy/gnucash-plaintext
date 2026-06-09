
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

Supported values of `type` are  6 asset accounts (Cash, Bank, Stock, Mutual Fund, Accounts Receivable, and Other Assets),
3 liability accounts (Credit Card, Accounts Payable, and Liability), 1 equity account (Equity), 1 income account (Income), and 1 expense account (Expenses).

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

### Custom Metadata

GnuCash supports arbitrary key-value pairs (KVP slots) on all its object types.
gnucash-plaintext exposes this as **custom metadata**: any field in a block that is
not a reserved field (see tables below) is automatically stored in the GnuCash KVP
layer and round-trips through export/import without loss.

This applies to **every object type** — transactions, splits, accounts, customers,
vendors, invoices, and bills — making the format directly comparable to beancount's
open-ended metadata model.

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
```

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

A single book-level `company` directive round-trips the seller identity that
`print-invoice` / `print-bill` show in the "From" / "Bill To" block. These are
GnuCash's own **File → Properties → Business** options — they were rendered
before but never exported or imported, so a roundtrip into a fresh book used to
lose them. The directive has no id and no date; it is master data for the whole
book:

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

The same applies symmetrically to bills (AP, opposite signs): overpaying a $100 bill by $50 produces an open AP lot with **+$50** balance — a vendor credit you can apply against the next bill from the same supplier.

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

On import the invoice is posted normally, then `gncInvoiceAutoApplyPayments` runs and takes from the open prepay lot(s) toward the invoice's outstanding balance. If credit ≥ invoice the lot closes via consumption; the residual stays open as a smaller credit (split in-place by GnuCash). If credit < invoice the full credit consumes; the invoice stays partially open. The flag composes with cash `payment:` blocks — cash goes first, credit auto-applies for any remainder. The exporter detects the post-auto-apply book state and emits `auto_apply_credit: true` again on round-trip; identical re-import is a no-op.

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
  b) **Refund, write off, or forfeit** — record a normal `transaction:` whose AR/AP split carries a `lot_owner:` marker for the owner; the counter account decides the intent (bank ⇒ refund, expense ⇒ vendor bad debt, income ⇒ customer forfeit). This is the canonical non-destructive disposal — see [Disposing of a credit](#disposing-of-a-credit-refund-write-off-or-forfeit-lot_owner) below. It never touches the original payment, and a partial amount leaves the residual credit open.
  c) **Delete the source bank tx** — only safe for standalone-payment credits (the source bank tx has just the bank-side split and the AR/AP credit split, nothing else). `delete-transactions --by-guid <source-bank-tx>` drops the tx and produces a plaintext backup. Not safe for overpayment-residual credits, where the source tx also carries the original invoice payment.

When the book and the plaintext have diverged (the user hand-edited the `.gnucash` file in the GnuCash UI, or hand-edited the `.txt` file before re-importing, or a third-party tool modified the book), the importer's recovery behaviour per scenario is documented in [`docs/payment-manual-edit-behavior.md`](docs/payment-manual-edit-behavior.md).

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
- The `lot_owner:` split's own account fixes the owner type: a `customer` marker must sit on an AR account and a `vendor` marker on an AP account, and the importer rejects that mismatch (e.g. a `customer` marker on an AP split). The counter account is not otherwise constrained on this path — it simply records which of the operations above this is.
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

It is informational and derived: the importer rebuilds the credits from the per-split `lot_owner:` markers, not from this summary, so the block is parsed and otherwise ignored. If a hand-edited summary disagrees with the book's actual lots, import prints a warning to stderr and still succeeds — the next export rewrites the correct figure.

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

`find-orphan-payments` scans the book and lists every orphan with its GUID, date, bank account, amount, currency, the customer/vendor it was originally paying, and the bank-side split memo. Per-bank-account totals at the end. Read-only — the command never deletes or modifies anything; the user picks the cleanup path per orphan.

```bash
# Whole-book sweep:
gnucash-plaintext find-orphan-payments ledger.gnucash

# Scope to a single customer (orphan must carry that customer's KVP backref):
gnucash-plaintext find-orphan-payments ledger.gnucash --customer C001

# Scope to a single vendor (bill-side orphans):
gnucash-plaintext find-orphan-payments ledger.gnucash --vendor V001
```

Exit code 0 whether or not any orphans are found — the command is informational. A clean book reports `No orphan bank-side payment transactions found.` and exits 0.

Cleanup options the command points at, per orphan:

  a) `gnucash-plaintext delete-transactions <book> --by-guid <guid>` — drop the orphan (with a plaintext backup written), then re-import the invoice/bill with a fresh `payment:` block.
  b) Re-import the invoice/bill with a `payment:` block carrying `txn_guid: "<orphan-guid>"` — retargets the existing bank tx into the new posted lot (Q-004).

Detection criteria (so the user can trust the result): payment-class transactions (`txn_type == 'P'`) whose KVP customer/vendor backref is intact and whose AR/AP-side split's lot has no invoice attached. The KVP backref survives unpost authoritatively (set by `gncOwnerApplyPayment` when the payment was first recorded), so each orphan can be pinned to a specific customer/vendor — though not to a specific invoice, since the lot → invoice link is destroyed by unpost.

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

See **[docs/comprehensive-roundtrip-example.md](docs/comprehensive-roundtrip-example.md)** for the canonical end-to-end roundtrip walkthrough — a single source book exercising every plaintext surface (accounts, customers, vendors, tax tables, invoices and bills, all payment shapes: cash, retarget, overpayment with prepayment credit, credit consumption via `auto_apply_credit`, and the multi-invoice-one-bank-tx shape) exported and re-imported into a fresh book with semantic identity preserved down to per-split GUIDs. And **[docs/invoice-payment-reconciliation.md](docs/invoice-payment-reconciliation.md)** for the bank-feed-first workflow, bill examples, error reference, and the invoice-first alternative.

#### Cash-basis sales (Q-018)

For cash-basis tax filers who want each sale's posted date to match the cash-receipt date, the workflow is the bank-feed-first pattern with three constraints: `posted.date == payment.date == bank-tx.date`, a single `payment:` block carrying `txn_guid:` + `txn_split_guid:` to retarget the existing bank tx, and an optional `cash_basis: true` line on the invoice header as a tax-method marker. The flag is descriptive (purely a label for the issuer's tax filing — partial / installment payments are still allowed alongside it) and does not expose the tax-method classification in customer-facing rendering. For invoices that are issued but not yet paid, setting `cash_basis: true` on an unposted invoice renders an **UNPAID** badge instead of DRAFT, and an optional `due_date: YYYY-MM-DD` header field supplies the customer-facing due date. See **[docs/invoice-payment-reconciliation.md § Cash-basis sales](docs/invoice-payment-reconciliation.md#cash-basis-sales-q-018-same-day-post--pay)** for the worked example.

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

`--format {pdf,html,plaintext}` selects the output format (defaults to `pdf`). The PDF/HTML paths render via the XSLT template at `services/invoice.xslt`. The default template covers Description, Qty, Unit Price, Amount, and Tax Applied columns. A "Unit" column appears only if at least one entry on the invoice has a non-empty `action:` field — e.g. `"Hours"`, `"Project"`, `"Material"`. For goods/items invoices the column stays hidden (Q-011).

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

**Custom templates**: pass `--template <path>` to use your own XSLT (custom columns, branding, multi-language). The XML schema the template receives is documented at the top of `services/invoice.xslt`.

```bash
gnucash-plaintext print-invoice mybook.gnucash INV-2026-001 \
    -o invoice.pdf --template my-invoice-template.xslt
```

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
| Ubuntu 24.04 | 4.9 | `ubuntu24` |
| Ubuntu 22.04 | 4.8 | `ubuntu22` |
| Ubuntu 20.04 | 3.8 | `ubuntu20` |

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
