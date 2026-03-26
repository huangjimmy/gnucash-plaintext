
# gnucash-plaintext

gnucash plaintext is an app that can

* load a .gnucash file and then export a [GnuCash](https://www.gnucash.org/) plaintext ledger file
* load [GnuCash](https://www.gnucash.org/) plaintext ledger file and export a [beancount](https://github.com/beancount/beancount) compatible .beancount file
* read from a [GnuCash](https://www.gnucash.org/) plaintext transaction file and create transaction in .gnucash file
* bidirectional conversion between GnuCash and [GnuCash-Beancount](docs/gnucash-beancount-format.md) format with zero data loss

## Motivation

I have been using GnuCash to track my finance for several decades. At first, I was looking for a software that I could
use to track my spending. Now, GnuCash is a place where I keep track of my expenses, income and investment. There are 
commercial software and SaasS, people even mention notion as an online ledger, but I stick to GnuCash. I believe in one
thing that I need to own my financial data and I would use an open source tool like GnuCash.

At first, I used Microsoft Money but then Microsoft discontinued this product. I then found GnuCash. I was not quite sure
how to use GnuCash in the very beginning. I had to learn accounting basic such as Assets, Liabilities, Income, Expense
and Equity. I had to admit that if it were not for GnuCash, I wouldn't have learnt bookkeeping and accounting and I would
not have reviewed my financial status regularly like a CFO of myself.

As my ledger grows, I start to worry, what if GnuCash become obsolete? The first commit of GnuCash was made in 1997 and
today GnuCash is still under active development. It seems unlikely that my worry will come true, but I want to always
prepare for such event.

Then I find [ledger-cli](https://ledger-cli.org/doc/ledger3.html) and [beancount](https://github.com/beancount/beancount).
I immediately feel that plaintext accounting is what I am looking for. It is in human-readable text format and the content
will be readable by others even without any software.

However, when I dive deeper into ledger-cli and beancount, I know I cannot migrate my ledger to either of them. There are
features of GnuCash that I use and are not supported any of the two. Also, I have lots of reports in GnuCash that will
take me lots of time to migrate. What's more, my account names are highly flexible, e.g., they include spaces, CJK and, 
punctuations. 

I do agree with the author of beancount that GnuCash's UIs are inconvenient. Suddenly, I ask myself, why can't I build
a plaintext language that is similar to beancount and compatible with GnuCash. I can edit my ledger in GnuCash UIs and
then export to a text file. I can also edit my text file and then a cli will parse the text file and create transactions
and/or accounts in GnuCash? I can also export a beancount compatible text file to use against [beancount](https://github.com/beancount/beancount) and [fava](https://github.com/beancount/fava).

I explore GnuCash python bindings and beancount documentations. Now I am pretty sure that my idea is both viable and valuable. 

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

GnuCash supports arbitrary key-value pairs (KVP slots) on any transaction or split.
gnucash-plaintext exposes this as **custom metadata**: any tag in a transaction or
split block that is not a reserved field (see tables below) is automatically stored
in the GnuCash KVP layer and round-trips through export/import without loss.

This makes the format directly comparable to beancount's open-ended metadata model.

#### Reserved transaction fields (stored via dedicated GnuCash setters)

| Field | GnuCash field |
|-------|--------------|
| `guid` | Transaction GUID |
| `currency.namespace` | Transaction currency namespace |
| `currency.mnemonic` | Transaction currency mnemonic |
| `doc_link` | Document link / association |
| `notes` | Transaction notes |

#### Reserved split fields (stored via dedicated GnuCash setters)

| Field | GnuCash field |
|-------|--------------|
| `share_price` | Share price |
| `value` | Split value |
| `action` | Split action |
| `memo` | Split memo |
| `account.commodity.mnemonic` | Account commodity mnemonic |
| `account.commodity.namespace` | Account commodity namespace |

#### Any other key → KVP slot

Any key not in the tables above is stored in GnuCash's KVP slot system as a JSON
blob under the `plaintext_metadata` slot name. Multiple custom keys on the same
object are stored together in a single JSON object.

**Key naming rules:**
- Colons (`:`) are **not allowed** in custom metadata key names. The plaintext
  format uses `key: value` syntax, so a colon inside a key name would create
  parsing ambiguity. An error is raised at import time if a colon is found.
- Use **dots** for hierarchical keys (e.g. `tax.category`, `receipt.id`).
  Dots are already used by convention in the reserved fields above.

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

In the example above:
- `guid`, `notes` → stored via dedicated GnuCash API (reserved fields)
- `tax_category`, `receipt_id` → stored in the transaction's KVP slot
- `vendor`, `approved_by` → stored in the Dining split's KVP slot

When you export this transaction back to plaintext, all four custom keys will
appear in the output exactly as written.

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

KVP metadata works on all supported GnuCash versions:

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

### Export a single transaction by GUID

Export one specific transaction to plaintext (useful for AI-assisted editing or review):

```bash
gnucash-plaintext export-transaction mybook.gnucash --guid 317c8ae6e0084c33951d052b9f1b9f23
```

The output is self-contained — it includes the commodity and account declarations needed to re-import or process the transaction independently. Output goes to stdout by default; use `-o` to write to a file:

```bash
gnucash-plaintext export-transaction mybook.gnucash --guid 317c8ae6e0084c33951d052b9f1b9f23 -o tx.txt
```

`--guid` is required. Omitting it prints an error with usage guidance.

### Delete a transaction by GUID

Delete a single transaction permanently. The transaction is exported to plaintext **before** deletion so you always have a backup copy:

```bash
# Delete and print backup to stdout
gnucash-plaintext delete-transaction-by-guid mybook.gnucash 317c8ae6e0084c33951d052b9f1b9f23

# Delete and save backup to a file
gnucash-plaintext delete-transaction-by-guid mybook.gnucash 317c8ae6e0084c33951d052b9f1b9f23 -o backup.txt
```

The command fails immediately (non-zero exit) if the GUID is not found — it will never silently do nothing.

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

**Note:** The exported file is in [GnuCash-Beancount format](docs/gnucash-beancount-format.md), a special beancount format with GnuCash metadata that enables bidirectional conversion with zero data loss.

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

### Import and export business objects

Customers, vendors, tax tables, invoices, and bills can be round-tripped
through plaintext alongside your accounts and transactions.

```bash
# Import a file that contains business objects as well as transactions
gnucash-plaintext import --new mybook.gnucash ledger.txt --include-business-objects

# Export everything — accounts, business objects, then transactions
gnucash-plaintext export mybook.gnucash ledger.txt --include-business-objects
```

Business objects use no date prefix — they are master data, not ledger
events. Dates that belong to a record (e.g. `date_opened` on an invoice) are
declared as fields inside the block:

```
customer "CUST-001"
  name: "Acme Corp"
  currency: CAD

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
  posted:
    date: 2026-01-15
    due: 2026-02-14
    ar_account: "Assets:Accounts Receivable"
    memo: "Invoice INV-2026-001"
    accumulate: true

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
```

### Print an invoice to PDF

Generate a PDF for any posted invoice:

```bash
gnucash-plaintext print-invoice mybook.gnucash --invoice-id INV-2026-001 -o invoice.pdf
```

The PDF is rendered using the XSLT template at `services/invoice.xslt`, which
you can customise to match your company's branding.

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
- Transaction signature matches: (date, [split account 1, ..., split account N])
- If no GUID and signature doesn't match, it's considered a new transaction

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
# Linux/macOS
./scripts/dev-start.sh

# Windows (PowerShell)
.\scripts\dev-start.ps1

# Windows (CMD)
scripts\dev-start.bat
```

**What you get:**
- VS Code Server at https://localhost:8765 (password: `123456`)
  - **Note**: Uses self-signed SSL certificate - browser will show security warning
  - Click "Advanced" → "Proceed to localhost (unsafe)" to continue (safe for local dev)
- GnuCash Python bindings pre-installed and ready to use
- Python package installed with all dependencies
- Docker-in-Docker support (Linux/macOS/WSL2) - run test scripts from anywhere
- Live code sync - changes reflect immediately
- Git hooks automatically installed (linting + tests before commit)

**Inside VS Code Server terminal**, you can:
```bash
# Run tests directly (faster)
pytest tests/
pytest tests/unit/ -v

# Or use the same scripts as on host (Docker-in-Docker on Linux/macOS/WSL2)
./scripts/test.sh
./scripts/test.sh debian12  # Test on different GnuCash version

# Use the CLI
gnucash-plaintext --help
gnucash-plaintext export myfile.gnucash output.txt
```

To stop the environment:
```bash
# Linux/macOS
./scripts/dev-stop.sh

# Windows (PowerShell)
.\scripts\dev-stop.ps1

# Windows (CMD)
scripts\dev-stop.bat
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

- **Linux/macOS/WSL2**: Full Docker-in-Docker support - same commands work on host and inside container
- **Windows (PowerShell/CMD)**: VS Code Server works, but use `pytest` directly inside container (Docker-in-Docker not supported on native Windows)

### Running Tests

```bash
# From host machine (Linux/macOS/WSL2)
./scripts/test.sh           # Run all tests with default image
./scripts/test.sh debian12  # Run with Debian 12 (GnuCash 4.13)
./scripts/test.sh latest tests/unit/  # Run specific test directory

# From Windows (PowerShell)
.\scripts\test.ps1
.\scripts\test.ps1 debian12

# Inside VS Code Server (all platforms)
pytest tests/               # Direct execution (faster)
./scripts/test.sh          # Via Docker wrapper (Linux/macOS/WSL2 only)
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
- Cross-platform script usage (Linux/macOS/Windows)
- Troubleshooting Docker socket permissions
- Fixing path mounting issues in Docker-in-Docker
- VS Code Server configuration and settings persistence