
# gnucash-plaintext

gnucash plaintext is an app that can

* load a .gnucash file and then export a [GnuCash](https://www.gnucash.org/) plaintext ledger file
* load [GnuCash](https://www.gnucash.org/) plaintext ledger file and export a [beancount](https://github.com/beancount/beancount) compatible .beancount file
* read from a [GnuCash](https://www.gnucash.org/) plaintext transaction file and create transaction in .gnucash file

## Motivation

I have been using GnuCash to track my finance for several decades. At first, I was looking for a software that I could
use to track my spending. Now, GnuCash is a place where I keep track of my expenses, income and investment. There are 
commercial software and SaasS, people even mention notion as an online ledger, but I stick to GnuCash. I believe in one
thing that I need to own my financial data and I would use an open source tool like GnuCash.

At first I used Microsoft Money but then Microsoft discontinued this product. I then found GnuCash. I was not quite sure
how to use GnuCash in the very beginning. I had to learn accounting basic such as Assets, Liabilities, Income, Expense
and Equity. I had to admit that if it were not for GnuCash, I wouldn't have learnt bookkeeping and accounting and I would
not have reviewed my financial status regularly like a CFO of myself.

As my ledger grows, I start to worry, what if GnuCash become obsolete? The first commit of GnuCash was made in 1997 and
today GnuCash is still under active development. It seems unlikely that my worry will come true, but I want to always
prepare for such event.

Then I find [ledger-cli](https://ledger-cli.org/doc/ledger3.html) and [beancount](https://github.com/beancount/beancount).
I immediately feel that plaintext accounting is what I am looking for. It is in human readable text format and the content
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
in GnuCash plaintext but it will be interpreted as you open account `Liabilities:CreditCard:CapitalOne     USD` on 
2014-05-01.

Supported values of `type` are  6 asset accounts (Cash, Bank, Stock, Mutual Fund, Accounts Receivable, and Other Assets),
3 liability accounts (Credit Card, Accounts Payable, and Liability), 1 equity account (Equity), 1 income account (Income), and 1 expense account (Expenses).

Also, you cannot declare top level accounts such as `Expenses` in beancount but you 
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

## Features

### Export GnuCash data to GnuCash plaintext

```commandline
plaintext_from_gnucash.py -i path_to_gnucash_file.gnucash -o path_to_plaintext_file.txt
```

or

```commandline
plaintext_from_gnucash.py --input path_to_gnucash_file.gnucash --output path_to_plaintext_file.txt
```

### Convert GnuCash plaintext to beancount

TODO

### Create GnuCash XML file from GnuCash plaintext 

Read text content from `path_to_plaintext_file.txt` and create a new GnuCash XML file.
If `path_to_gnucash_file.gnucash` exists, this program will raise an exception and fail
to create GnuCash XML file

```commandline
plaintext_to_gnucash.py -i path_to_plaintext_file.txt -o path_to_gnucash_file.gnucash
```

or

```commandline
plaintext_to_gnucash.py --input path_to_plaintext_file.txt --output path_to_gnucash_file.gnucash
```

### Update an existing GnuCash XML according to plaintext

* Load and parse `path_to_plaintext_file.txt`, create accounts/transactions/splits that do not exist in `path_to_gnucash_file.gnucash`
* Update existing accounts/transactions/splits so that they are in sync with `path_to_plaintext_file.txt`

An account from plaintext exists in GnuCash if
* account guids equal
* account full names equal
* if no guids and full names not equal, will be considered a new account

A transaction from plaintext exists in GnuCash if
* transaction guids equal
* if no guid, will be considered a new transaction if no transactions exist on that day

A transaction split exists in GnuCash if
* the transaction of this split is an existing transaction
* split guids equal, or if no guid
* match by account associated with this split
* if two or more splits under the same transaction are associated with one account,
  * they will be matched in the order they appear in plaintext and GnuCash
  * if there are more splits in plaintext, new splits will be created
  * if there are more splits in GnuCash, non-matched splits will get deleted


#### Command line

```commandline
plaintext_edit_gnucash.py -i path_to_plaintext_file.txt -o path_to_gnucash_file.gnucash
```

or

```commandline
plaintext_edit_gnucash.py --input path_to_plaintext_file.txt --output path_to_gnucash_file.gnucash
```