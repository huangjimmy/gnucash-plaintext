# A balance in each currency, on every account

A book can keep, on every account, a balance in each of a set of currencies it selects. A US dollar bank account holding 1,000.00 USD also stores what those dollars are in Canadian dollars, in yuan, in euros and in each other selected currency, as if the bank held each of them.

With those balances the book can print its balance sheet and income statement in any selected currency, states a realized gain in each of them, and never asks which lot a dollar came out of.

This page follows one company, ACME LLC, through a year, and then a second company, ACMU LLC, that kept cost bases for five years and changed over. Both are tests in this repository, and every amount below is what gnucash-plaintext prints for them.

## Turning it on

The book selects its currencies in its `company` block:

```
company
	name: "ACME LLC"
	base_currency: "USD"
	fiscal_year_end: "06-30"
	currency_balances: "USD CAD CNY HKD EUR GBP"
```

- A book selects from USD, CAD, HKD, CNY, EUR, JPY, GBP and KRW.
- Each currency is listed once, and the base currency is among them.
- The setting is off unless the book states it.
- `set-book-key` refuses the key. It belongs in the `company` block, because the import that reads the block is what works the balances out.

A book keeps either these balances or [cost bases](multi-currency.md), one or the other at a time.

## The book needs a price for the day

To know what 1,000.00 USD are in yuan on 2020-01-01, the book needs a price for that day. It reads its own price database, which `price` blocks fill (README, "Export and import prices"):

```
price
	commodity.namespace: "CURRENCY"
	commodity.mnemonic: "USD"
	currency.mnemonic: "CAD"
	time: "2019-12-31 12:00:00 +0000"
	value: "1.2988"
	source: "user:price-editor"
	type: "last"
```

ACME's prices are the Bank of Canada's daily rates, each in Canadian dollars. On 2019-12-31, the last day it published before 2020-01-01, they were 1.2988 CAD/USD, 1.4583 CAD/EUR, 0.1865 CAD/CNY, 0.1668 CAD/HKD and 1.7174 CAD/GBP.

- **The price nearest the transaction's date is the one used.**
- **A pair the book has no price of is worked out through a selected currency it has a price of both in.** ACME has no price of USD in CNY. It has both in CAD, so 1,000.00 USD are 1,298.80 CAD, and 1,298.80 / 0.1865 = 6,964.08 CNY.
- **A transaction the book has no price for is not saved.** The import says which pair is missing, as `the book has no price of USD in HKD`, and saves nothing.

## What an account stores

ACME opens on 2020-01-01 with 1,000.00 USD in its bank:

```
2020-01-01 * "Opening balance"
	currency.mnemonic: "USD"
	Assets:Chase Chequing 1000.00 USD
	Equity:Opening Balances -1000.00 USD
```

`fx-balances` then lists each account with its balance in its own currency and in each other selected one:

```
This book keeps a balance in each of USD, CAD, CNY, HKD, EUR, GBP on every account (`currency_balances:` in its company block).
Assets:Chase Chequing: 1000.00 USD, 1298.80 CAD, 6964.08 CNY, 7786.57 HKD, 890.63 EUR, 756.26 GBP
Equity:Opening Balances: -1000.00 USD, -1298.80 CAD, -6964.08 CNY, -7786.57 HKD, -890.63 EUR, -756.26 GBP
```

GnuCash keeps the 1,000.00 USD. gnucash-plaintext keeps the other five, and every currency adds up to zero across the accounts.

These are balances, and none of them is a cost. The average the dollars were stored at is one balance divided by another, 1,298.80 CAD / 1,000.00 USD = 1.2988 CAD/USD, worked out when it is wanted. No rate is stored.

## The balances as of a date

`fx-balances --as-of 2022-05-15` lists what each account held at the end of that day, in every selected currency:

```
This book keeps a balance in each of CAD, USD, HKD, CNY, GBP, EUR on every account (`currency_balances:` in its company block).
As of 2022-05-15:
Assets:Chase USD: 2500.00 USD, 3177.00 CAD, 19490.79 HKD, 15932.79 CNY, 1847.84 GBP, 2214.40 EUR
Assets:Wise USD: 6055.65 USD, 7694.03 CAD, 47328.34 HKD, 38581.76 CNY, 4561.06 GBP, 5468.03 EUR
Assets:HSBC HKD: 84846.65 HKD, 13804.33 CAD, 10851.52 USD, 70183.79 CNY, 8291.04 GBP, 9891.66 EUR
Equity:Opening Balances: -24528.40 CAD, -19417.73 USD, -151489.60 HKD, -123575.52 CNY, -14397.47 GBP, -17264.48 EUR
Income:FX Gain: -146.96 CAD, 10.56 USD, -176.18 HKD, -1122.82 CNY, -302.47 GBP, -309.61 EUR
```

Each split stores what it moved, so a balance as of a date is the amounts of the account's splits up to that day added up. Nothing is worked out again, and no price is read.

That listing is from a book of eighteen transactions among two US dollar accounts and a Hong Kong dollar account over 2022: money arriving, moves between the two US dollar accounts, and sales both ways. `tests/scenario/test_eighteen_transactions_among_three_accounts_in_six_currencies.py` states every account's balance in all six currencies after each of the eighteen.

`--as-of` is for a book that selected its currencies. A book keeping cost bases is refused it: a cost basis balance counts every disposal ever measured against it, whatever its date.

## What a split stores

Each split stores what it moved in each selected currency. A file does not state these amounts. The import works them out, and the export writes them:

```
2020-01-01 * "Opening balance"
	guid: "0d580000000000000000000000000001"
	Assets:Chase Chequing 1000.00 USD
		guid: "0d580000000000000000000000000011"
		currency_amount.CAD: "1298.80"
		currency_amount.CNY: "6964.08"
		currency_amount.EUR: "890.63"
		currency_amount.GBP: "756.26"
		currency_amount.HKD: "7786.57"
	Equity:Opening Balances -1000.00 USD
		guid: "0d580000000000000000000000000012"
		currency_amount.CAD: "-1298.80"
		currency_amount.CNY: "-6964.08"
		currency_amount.EUR: "-890.63"
		currency_amount.GBP: "-756.26"
		currency_amount.HKD: "-7786.57"
```

The export also writes each account's stored balances on its `open` block, as `currency_balance.CAD: "4044.90"`. Importing a book's own export back finds every transaction up to date.

## How the amounts are worked out

**Money arriving from income or equity takes the amounts of the day.** On 2021-01-01 ACME invoices ABC Europe 1,000.00 EUR. At the rates of 2020-12-31 that is 1,225.89 USD of sales, and the receivable stores 1,225.89 USD, 1,560.80 CAD, 8,008.21 CNY, 9,505.48 HKD and 897.99 GBP.

**Money moving between two accounts of one currency moves what was stored.** On 2021-03-03 ABC Europe pays the 1,000.00 EUR into Wise EUR. The payment empties the receivable, so it moves everything the receivable stored, and Wise EUR then stores the same five amounts. Nothing is realized. Where only part of an account moves, the same share of each balance moves: 10.00 USD of 100.00 USD storing 130.00 CAD move 13.00 CAD.

**Money exchanged for another currency realizes a gain in each currency, on the transaction's `$residual$` split.** On 2021-06-01 ACME sells the 1,000.00 EUR for 1,223.34 USD:

```
2021-06-01 * "Sell 1,000.00 EUR for 1,223.34 USD"
	currency.mnemonic: "USD"
	Assets:Chase Chequing 1223.34 USD
	Assets:Wise EUR -1000.00 EUR
		value: "-1225.89"
	Income:FX Gain $residual$ USD
```

- Wise EUR gives up what it stored: 1,000.00 EUR, 1,225.89 USD, 1,560.80 CAD, 8,008.21 CNY, 9,505.48 HKD and 897.99 GBP.
- Chase Chequing receives 1,223.34 USD, and with them the 1,000.00 EUR at that day's rates: 1,472.90 CAD, 7,805.51 CNY, 9,490.34 HKD and 863.52 GBP.
- `Income:FX Gain` takes the difference in each currency: a loss of 2.55 USD, 87.90 CAD, 202.70 CNY, 15.14 HKD and 34.47 GBP, and nothing in EUR.

The gain account is kept in the base currency, so the loss is posted as 2.55 USD, and the account stores the other five beside it. They are the amounts above, and are never the 2.55 USD converted at the rate of the day.

**A transaction with no `$residual$` split realizes nothing in any currency.** A currency or shares bought with no such split take what the account paying for them gave up, and no price is read. That is their cost in each currency.

**Foreign currency paying for shares realizes a gain on the currency where the file states one.** In a book whose base currency is CAD, 10.00 USD stored at 13.00 CAD buy 2 shares worth 14.00 CAD. With a `$residual$` split, the shares arrive at 14.00 CAD and at the day's amounts of the 10.00 USD, the split takes 1.00 CAD, and the balance sheet states it under `realized_gains_fx`, because the dollars were disposed of and the shares were not. Selling a share later states its gain under `realized_gains_other`.

**A currency and shares sold in one transaction state each its own gain.** One `$residual$` split takes both. The gain on the currency is what a sale of it alone would state: the currency at the book's price of the day, less what it was stored at. The rest is the gain on the shares. 1 share that cost 7.00 CAD and 10.00 USD storing 13.00 CAD sell together for 24.00 CAD, and the split takes 4.00 CAD. The 10.00 USD at 1.45 CAD/USD are 14.50 CAD, so the balance sheet states 1.50 CAD under `realized_gains_fx` and 2.50 CAD under `realized_gains_other`.

**In the transaction's own currency a split moves the value the transaction states.**

## A book that uses GnuCash's trading accounts

A book with "Use Trading Accounts" on (File → Properties → Accounts in GnuCash) can select its currencies like any other. GnuCash adds its own trading splits to each transaction that crosses currencies. They are no money moved, and each stores 0.00 in every selected currency:

```
Assets:USD_A: 90.00 USD, 117.00 CAD, 702.00 HKD, 540.00 CNY
Assets:CAD_B: 14.00 CAD, 10.00 USD, 78.50 HKD, 65.00 CNY
Trading:CURRENCY:USD: -90.00 USD, 0.00 CAD, 0.00 HKD, 0.00 CNY
Trading:CURRENCY:CAD: 117.00 CAD, 0.00 USD, 0.00 HKD, 0.00 CNY
```

The other accounts store what they store in a book without trading accounts. A statement measures each gain from those stored balances, and states `realized_gains_fx` and the unrealized gains where a book using trading accounts otherwise states `trading_gains`.

## The statements, in any selected currency

`balance-sheet` and `income-statement` take `--currency`, and print in any currency the book selected. A currency it did not select is refused, because the book holds no balance in it:

```
Error: this book keeps a balance in each of USD, CAD, CNY, HKD, EUR, GBP on every account, and a statement is printed in one of those. It holds no balance in JPY
```

On a page in a currency:

- **An income, expense or equity account is read at what its splits moved in that currency on their own days.** ACME's 2,225.89 USD of sales are 2,834.00 CAD: 1,273.20 CAD for the US dollar invoice and 1,560.80 CAD for the euro one.
- **An account holding or owing money is valued at the book's price nearest the page's date.**
- **A receivable or a payable can be on both sides at once.** With an invoice not yet collected beside a customer's credit, the invoice is money held and the credit is money owed back, and each is measured against what it stores.
- **The unrealized gain is that value less the balance the account stores.**
- **The realized gain is what the `$residual$` splits took in that currency.**

ACME's balance sheet on 2021-06-01, in CAD, with `--no-itemize`:

```
	Assets:Chase Chequing 3223.34 USD
		account.commodity.mnemonic: "USD"
		share_price: "1.204"
		value: "3880.90"
	total_assets: 3880.90 CAD
	total_liabilities: 0.00 CAD
	Equity:Opening Balances 1298.80 CAD
	retained_earnings: 2746.10 CAD
```

The 3,223.34 USD are worth 3,880.90 CAD at 1.2040 CAD/USD and store 4,044.90 CAD, so the page states 164.00 CAD of unrealized loss, and 87.90 CAD of realized loss. 1,298.80 + 2,746.10 − 164.00 = 3,880.90, and the page balances. Without `--no-itemize` it shows the working, account by account:

```
				stored_balances:
					stored_balance:
						account_guid: d9ba993375274f6aae0ec8633a434c4b
						account: "Assets:Chase Chequing"
						balance: 3223.34
						stored_value: 4044.90 # what the account stores for its balance
						value: 3880.90 # balance * share_price
						unrealized_gains_assets_fx: -164.00 # value - stored_value
```

The same day in USD, the book's base currency, the page states 3,223.34 USD of assets, 2.55 USD of realized loss and no unrealized gain, since the book then holds only US dollars.

The income statement of the fiscal year ending 2021-06-30 states 2,225.89 USD of sales and a 2.55 USD loss in USD, and 2,834.00 CAD of sales and an 87.90 CAD loss in CAD.

**A page's unrealized gain depends on the prices the book holds.** Until 2020-02-02 ACME's book has no price later than 2019-12-31, so its balance sheet states no gain in any of the six currencies. Once the book holds the rates of 2020-12-31, the opening 1,000.00 USD are worth 1,273.20 CAD against the 1,298.80 CAD they store, and a page in CAD states 25.60 CAD of unrealized loss.

## A book that kept cost bases

A book with a history can turn the setting on, and so can a book that kept cost bases. ACMU LLC is kept in CAD and kept cost bases from 2020 to 2024: 21 transactions, with six invoices in USD, EUR and CAD, expenses paid in USD and EUR, and sales of both, each disposal stating the cost basis it drew on. Then it imports:

```
company
	currency_balances: "CAD USD CNY HKD EUR GBP"
```

- **Every amount and balance is derived from the book's first transaction**, in the order GnuCash keeps its transactions. An invoice's posting and a payment are transactions like any other.
- **The statements hold.** ACMU's balance sheet in CAD at each fiscal year end, and its income statement of each fiscal year, state the same amounts before the migration and after it. On 2024-12-31 both state 13,626.16 CAD of assets, 37.69 CAD of realized gain and 1,028.05 CAD of unrealized gain.
- **Each account stores in the base currency what its cost bases came to.** Chase Chequing's 4,898.34 USD store 6,254.11 CAD, which is what the four cost bases behind them cost.
- **The cost bases stay in the book**, and in its export. They are its history.
- **The change is one way.** The import says so, and `currency_balances: $None$` on such a book is refused:

```
  this book kept cost bases, and from now on it keeps a balance in each of CAD USD CNY HKD EUR GBP on every account instead. The cost bases it recorded stay in it. A book migrated away from cost bases cannot be migrated back to them.
```

After the migration a disposal states no cost basis. ACMU sells 500.00 of its 4,898.34 USD on 2025-02-01. They store 500.00 / 4,898.34 of 6,254.11 CAD, which is 638.39 CAD, and sell for 724.20 CAD at 1.4484 CAD/USD:

```
2025-02-01 * "Sell 500.00 USD for 724.20 CAD at 1.4484 CAD/USD"
	currency.mnemonic: "CAD"
	Assets:RBC Chequing 724.20 CAD
	Assets:Chase Chequing -500.00 USD
		value: "-638.39"
	Income:FX Gain $residual$ CAD
```

The sale realizes 85.81 CAD.

## Deleting a transaction

GnuCash lets any transaction be deleted, and every balance after it depends on it. `delete-transactions` works every amount and balance out again from the book's first transaction before it saves, as every command that saves the book does.

ACME deletes the 2021-03-03 payment of ABC Europe:

```
gnucash-plaintext delete-transactions acme.gnucash --by-guid 0d580000000000000000000000000024
```

- The receivable holds its 1,000.00 EUR again, with the 1,225.89 USD and 1,560.80 CAD it stored.
- Wise EUR never received them, so the sale of 2021-06-01 leaves it owing 1,000.00 EUR, at that day's 1,472.90 CAD.

```
Assets:Wise EUR: -1000.00 EUR, -1225.89 USD, -1472.90 CAD, -7805.51 CNY, -9490.34 HKD, -863.52 GBP
Assets:Accounts Receivable EUR: 1000.00 EUR, 1225.89 USD, 1560.80 CAD, 8008.21 CNY, 9505.48 HKD, 897.99 GBP
```

- The sale now exchanges euros the account did not hold for their worth of the day. In CAD it realizes nothing, where it realized a loss of 87.90 CAD. That 87.90 CAD is still lost, on the receivable, and not yet realized: the sheet in CAD on 2021-06-01 states 251.90 CAD of unrealized loss where it stated 164.00 CAD, and the same 3,880.90 CAD of assets.

ACMU deletes its 2021-11-15 software subscription, 300.00 USD that cost 389.64 CAD. Deleted before the migration or after it, the book comes out the same: Chase Chequing holds 5,198.34 USD storing 6,643.75 CAD, and each year end from 2022-06-30 has 389.64 CAD more of retained earnings.

## Changing the selection, and the other commands

- **A currency added to the selection** has its balances worked out from the book's first transaction as well, so the book needs prices for it from then on.
- **A currency left out of the selection** is no longer kept.
- **Every command that saves the book works the balances out again first.** `delete-transactions`, `unpost-invoices` and the rest leave them right.
- **`--verify-integrity`** checks that the balance sheet balances and that the income statement agrees with it, and lists the cost basis checks as not checked, with the reason. `fx-balances --verify-costs` says `No cost was checked: this book records no cost basis.`

## A book written before `took_the_residual`

A book an early release wrote states a gain as an ordinary split, with no mark saying it took a difference. Such a transaction realizes nothing in the stored balances: 10.00 USD storing 13.00 CAD, 78.00 HKD and 60.00 CNY exchanged for 14.00 CAD leave the Canadian dollar account storing 78.00 HKD and 60.00 CNY, and the gain account storing 0.00 in each.

The balance sheet states no realized gain for it until `--fx-gain-account "Income:FX Gain"` says where gains are booked, as for a book keeping cost bases. It then states the 1.00 CAD. The gain of such a book is known in its base currency and in no other.

## Where it is tested

- `tests/scenario/test_acme_keeps_a_balance_in_usd_cad_cny_hkd_eur_and_gbp_on_every_account.py` is ACME: the statements in all six currencies, before and after each date.
- `tests/scenario/test_acmu_migrates_from_cost_bases_after_five_years.py` is ACMU: the statements before and after the migration, and the first sale after it.
- `tests/scenario/test_eighteen_transactions_among_three_accounts_in_six_currencies.py` is eighteen transactions among three accounts, with every balance in six currencies after each.
- `tests/integration/test_a_book_selects_the_currencies_it_keeps_a_balance_in.py` holds the refusals, shares, a balance past zero, and a selection that changes.

The design, and what was found while building it, is in [docs/issues/Q-057](issues/Q-057-keep-each-accounts-balance-in-every-currency-the-book-supports.md).
