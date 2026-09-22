# Q-044 — State a realized gain on a book whose splits carry no `took_the_residual`, and say on the balance sheet what GnuCash's balancing amount is

`realized_gains_fx` states `0.00` on a book that did take a gain. `gnucash_balancing_amount` states a number with nothing saying what it is. The same remedy for both: state what the book does not record, and show the arithmetic.

Reported from a real book and reproduced by the fixtures this issue adds, so nothing here is taken from the reported book. Measured on GnuCash 5.10 and 3.4 by running `balance-sheet` against those fixtures; the history was read with `git log -S`.

## What it should do

**A book created before gnucash-plaintext introduced the `took_the_residual` KVP key still keeps track of its realized gain.**

- A book imported from a plaintext file that used `$residual$`, before `took_the_residual` existed, states its realized gain once its FX gain/loss account is specified. `--fx-gain-account "Income:FX Gain"` tells `balance-sheet` which account those differences were booked to, which is the one thing such a book does not record.
- On `balance-sheet` and on `report`, repeatable, for a book keeping its gains and its losses in two accounts.
- The book is not written to: the option is read while the balance sheet is being produced.
- With an FX gain/loss account specified, `took_the_residual` is not consulted at all.
- The option says *which* split holds the difference, never *whether* a difference may exist. Three conditions the book answers for itself are unchanged: the split must be on an income or expense account, the transaction must be stated in the book's own currency, and one of its splits must give a cost basis guid. So the option counts nothing on a transaction that disposed of no currency. On a disposal it is believed — whatever sits on the stated account is taken for the difference, so a bank charge booked there is read as a loss, which is why the account has to come from someone who knows the book.

**The balance sheet says what `gnucash_balancing_amount` is on the book it was run against.**

- `gnucash_balancing_amount` is what GnuCash thinks is the unrealized gain, and it turns out not to be. The balance sheet states the subtraction GnuCash made rather than a verdict on it, commodity by commodity — **the commodities GnuCash's own figure is summed from**, read out of the collector it sums rather than grouped by anything this report decided. GnuCash merges the account balances, keyed by each account's own commodity, and subtracts the splits' values, keyed by the transaction's currency, so its figure spans both sets. Each group gives that commodity's own amount and the amount converted, with the splits and the balances beside them so a reader can see what went into it.
- A reader works out which of them it is on their own book from those figures. Where the splits and the balances come to the same amount the difference is `0.00`, and the group says so rather than the key going quiet.
- **The examples show the subtraction being made, on books a reader can run.** Every file under `examples/multi-currency/` carries a ledger and the balance sheet that ledger prints, the grouped block included, so the arithmetic can be followed on real figures rather than taken on trust. `a_us_supplier_paid_out_of_those_dollars.txt` states 19.86, `some_of_the_dollars_kept_back.txt` states 12.56, `us_dollars_borrowed_into_a_canadian_bank.txt` states -100.00, and `a_us_customer_invoiced_and_the_dollars_still_held.txt` states `0.00` with a group behind it. Each file's own header gives the two commands that rebuild it. `scripts/generate-multi-currency-examples.sh` writes all eleven from the fixtures and refuses to write one that does not import.

**`--itemize` lists the items a total is made of.**

The items are for reference. `--itemize` lists them, and the balance sheet states the same keys and the same figures without it.

Four keys carry items: `realized_gains_fx`, `unrealized_gains_assets_fx`, `unrealized_gains_other` and `gnucash_balancing_amount`. `unrealized_gains_fx`, `total_realized_gains` and `total_unrealized_gains` add up the keys above them, so each states its formula in a `#` comment and carries no items of its own.

The items go under the total they belong to, in the indentation the format already uses for `share_price:` and `value:` beneath an account line.

**What this buys a reader is the one figure on a balance sheet they could not previously check.** An account line can be checked against their own book and a section total by adding the lines above it, but a gain is measured against costs that appear on no line of the page. Now every gain figure can be reproduced from the lines beneath it — and where the tool cannot account for something, the page shows the disagreement rather than hiding it.

**Every entry is listed, however many there are, and `--max-items N` is how a reader asks for fewer.** A list with entries missing is one nobody can add up, so nothing is left out unless it is asked for. What that costs on a large book was measured by `tests/research/how_a_page_grows_with_the_splits_behind_it_probe.py`: 2,500 foreign purchases draw a page of 40,154 lines and 1.4 MB, of which 40,069 lines are the four itemized keys — about sixteen lines a transaction. `--max-items 5` draws the same book in 210 lines, and each shortened list says on its own line what it is not showing: `cost_bases: # 2500 cost bases, 5 listed and the rest under not_listed; --max-items -1 for all`.

**A shortened list carries what it left out, as one more entry.** Each of these keys ends in totals whose own comments state that they are the sum of the entries above them — `cost_basis_balance: 4000.00 # sum of each cost_basis's cost_basis_balance` — so a list that simply stopped after two made its own comment untrue, and left a reader adding two figures that come to 2,000.00 beneath a total of 4,000.00. The list ends with `not_listed:` instead, giving the count and what the rest come to:

```
					cost_basis:
						...
						cost_basis_balance: 1000.00
						cost_value: 1200.00
						unrealized_gains_assets_fx: 300.00
					cost_basis:
						...
						cost_basis_balance: 1000.00
						cost_value: 1300.00
						unrealized_gains_assets_fx: 200.00
					not_listed:
						count: 2
						cost_basis_balance: 2000.00
						cost_value: 2900.00
						value: 3000.00
						unrealized_gains_assets_fx: 100.00
				cost_basis_balance: 4000.00 # sum of each cost_basis's cost_basis_balance
				cost_value: 5400.00 # sum of each cost_basis's cost_value
```

It carries the fields that add, and no others: a guid, an account and a price differ from one entry to the next and have no sum, so a reader wanting those asks for the entries themselves.

**`-1` is no cap and is the default, `0` lists none, and every other number means itself.** Zero was the sentinel for "all" first and read backwards — a page saying `--max-items 0 for all` asks a reader to learn that nought means everything. With `0` meaning zero it becomes the useful thing it looks like: every key's totals with none of its entries under them, the whole list carried in `not_listed:`.

Grouping the entries instead was measured first and does not work. On a book whose purchases differ from one another — its own amount, rate and date each time, which is what a real book is — 2,500 cost bases fall into 2,500 distinct account-and-price groups, so rolling them up shortens nothing at all.

**A figure in these blocks is padded to its own commodity's places, and GnuCash decides how many.** `gnc-commodity-get-fraction` answers it, so a yen balance is written `250000` beside `2500.00` for what those yen cost. GnuCash's own Balance Sheet writes the same two figures as `JP¥250,000` and `C$2,500.00`; this page drops the symbol and the thousands separators, because `import` has to read the figure back. `tests/research/what_gnucashs_own_report_renders_a_figure_as_probe.py` draws both pages against one book so the two can be compared, and CLAUDE.md finding 30 records what that settled.

**The block below is a curated example, not one book's balance sheet.** Each key's items were measured by running `balance-sheet` against a fixture chosen to show that key at its fullest — four cost bases at four rates for `unrealized_gains_assets_fx`, four disposals for `realized_gains_fx`, a stock and a fund both priced for `unrealized_gains_other`, and a spent-out US dollar bank for `gnucash_balancing_amount`. No single book carries all four at once, and assembling them is what lets one block state the whole format.

So the figures are real and the arithmetic within each key holds — every item adds up to the total above it, and each total states the formula that reached it. The one exception is a cost basis line's `value:` and the gain worked out from it: a holding is converted once, at the commodity's price, so the commodity's `value:` is that single conversion and the per-basis lines each convert one basis and round on their own. They can come to a different figure, by a rounding step, and the commodity's line is the one the key is built from — the items are a reference, never the computation. What the block is not is a sheet any one book would print: the four keys describe four books, and a reader checking one of them against a fixture will find that key's figures and not its neighbours'.

The totals that add up other keys — `unrealized_gains_fx`, `total_realized_gains`, `total_unrealized_gains` — are computed from the keys as they stand here, so the block is consistent read top to bottom.

**A cost basis is listed by `fx-balances`, and this is what that looks like.** It is shown so a reader knows the shape of the listing the balance sheet's cost basis items correspond to — a date, the split's guid, the account, what the currency cost, what it brought in and what is left against it. Beneath the cost bases the listing states what the accounts hold of each currency, because the two are different figures: a cost basis balance is how much of one split's currency has not been sold, and an account balance is what an account holds. They agree here, and where they do not the page says so rather than leaving it to be worked out from a balance sheet. **What is held and what is owed are totalled apart**, because a cost basis balance is a magnitude whichever side it sits on while an account's balance carries its sign — netted together, a loan of 1,000.00 USD against a cost basis of 1,000.00 read as a 2,000.00 disagreement on a book where every figure is right. **The figures here are a different book's and appear nowhere below**; the block's `unrealized_gains_assets_fx` lists four cost bases at 1.2, 1.3, 1.4 and 1.5, where this book has two.

```
DATE         SPLIT GUID                         ACCOUNT                                      COST     BROUGHT IN COST BASIS BALANCE
-----------------------------------------------------------------------------------------------------------------------------------
2026-08-13   56eb3d422c834c0e8fe326c789be7127   Assets:Accounts Receivable USD 189557/136000 CAD/USD   2,720.00 USD       2,720.00 USD
             Invoice INV-USD-1
2026-02-01   f148619cdf5a473eb927c550aca03df8   Assets:USD Bank                       1.3 CAD/USD   1,000.00 USD       1,000.00 USD
             Buy 1,000.00 USD at 1.30

Total USD cost basis balance: 3,720.00 USD

ACCOUNT                                   BALANCE
-------------------------------------------------
Assets:Accounts Receivable USD           0.00 USD
Assets:Bank:USD                      2,720.00 USD
Assets:USD Bank                      1,000.00 USD

Total USD held in accounts: 3,720.00 USD
```

```
unrealized_gains_assets_fx: # one row per cost basis, grouped by commodity and type, never added before the report sees them
	commodities:
		commodity:
			commodity.mnemonic: "USD"
			type: asset
			share_price: 1.5 # current price of commodity in balance sheet currency
			cost_bases:
				cost_basis:
					split_guid: 92b70580b62d447aa42940cd9d979db5
					account: "Assets:USD Bank"
					cost_basis_balance: 1000.00
					cost_share_price: 1.2
					cost_value: 1200.00 # cost_basis_balance * cost_share_price
					value: 1500.00 # cost_basis_balance * share_price
					unrealized_gains_assets_fx: 300.00 # value - cost_value
				cost_basis:
					split_guid: 3fc206d1f26e420daa6e4d71307e7d9f
					account: "Assets:USD Bank"
					cost_basis_balance: 1000.00
					cost_share_price: 1.3
					cost_value: 1300.00 # cost_basis_balance * cost_share_price
					value: 1500.00 # cost_basis_balance * share_price
					unrealized_gains_assets_fx: 200.00 # value - cost_value
				cost_basis:
					split_guid: 129fbc77e06340abb8cd1196beeb9163
					account: "Assets:USD Bank"
					cost_basis_balance: 1000.00
					cost_share_price: 1.4
					cost_value: 1400.00 # cost_basis_balance * cost_share_price
					value: 1500.00 # cost_basis_balance * share_price
					unrealized_gains_assets_fx: 100.00 # value - cost_value
				cost_basis:
					split_guid: 49214db17a66410aad0e852586e8c3c5
					account: "Assets:USD Bank"
					cost_basis_balance: 1000.00
					cost_share_price: 1.5
					cost_value: 1500.00 # cost_basis_balance * cost_share_price
					value: 1500.00 # cost_basis_balance * share_price
					unrealized_gains_assets_fx: 0.00 # value - cost_value
			cost_basis_balance: 4000.00 # sum of each cost_basis's cost_basis_balance
			cost_value: 5400.00 # sum of each cost_basis's cost_value
			accounts:
				account:
					guid: 2a4c4105fbf24dfe89e2885694469b3a
					name: "Assets:USD Bank"
					balance: 4000.00
			balance_value: 4000.00 # sum of account's balance for all accounts
			value: 6000.00 # cost_basis_balance * share_price
			unrealized_gains_assets_fx: 600.00 # value - cost_value
	cost_value: 5400.00 # sum of each commodity's cost_value
	value: 6000.00 # sum of each commodity's value
	unrealized_gains_assets_fx: 600.00 # value - cost_value

unrealized_gains_liabilities_fx: 0.00 CAD

unrealized_gains_fx: 600.00 CAD # unrealized_gains_assets_fx + unrealized_gains_liabilities_fx

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

unrealized_gains_other: # sum of unrealized_gains_other of all securities and funds
	securities: # security, fund, etc
		security:
			commodity.namespace: "NASDAQ"
			commodity.mnemonic: "ACME"
			quantity: 10.0000
			share_price: 60 # what price-fn gives for this commodity
			accounts:
				account:
					guid: 8a3f1c07d2b74e5fa91c6d4380be2f15
					name: "Assets:Brokerage:ACME"
					balance: 10.0000
					splits:
						split_amount 10.0000 | value 500.00 CAD
			value: 600.00 # the holding converted at the sheet's price
			cost_value: 500.00 # its splits' values, converted
			unrealized_gains_other: 100.00 # value - cost_value
		security:
			commodity.namespace: "FUND"
			commodity.mnemonic: "VGRO"
			quantity: 20.0000
			share_price: 30 # what price-fn gives for this commodity
			accounts:
				account:
					guid: 4d90e6b1385c42a7b0f27e5c1a836d94
					name: "Assets:Brokerage:VGRO"
					balance: 20.0000
					splits:
						split_amount 20.0000 | value 500.00 CAD
			value: 600.00 # the holding converted at the sheet's price
			cost_value: 500.00 # its splits' values, converted
			unrealized_gains_other: 100.00 # value - cost_value
	value: 1200.00 # sum of each security's value
	cost_value: 1000.00 # sum of each security's cost_value
	unrealized_gains_other: 200.00 # value - cost_value

total_unrealized_gains: 800.00 CAD # unrealized_gains_fx (600.00) + unrealized_gains_other (200.00)

gnucash_balancing_amount: # the commodities GnuCash's own figure is summed from
	commodities:
		commodity:
			commodity.mnemonic: "CAD"
			splits:
				split:
					split_guid: 3f09144435874cd79d377496d863218d
					account: "Assets:Bank"
					value: 3771.28
				split:
					split_guid: f92404223b5c4b0c8a50551c07626b0e
					account: "Assets:Bank:USD"
					value: -3791.14
			sum_value: -19.86 # sum of split's value of all splits
			accounts:
				account:
					guid: 8358132660024fe7ac0abbc3c71cee30
					name: "Assets"
					balance: 0.00
				account:
					guid: e7c821e0c3e34b71b41d17a32b42842b
					name: "Assets:Bank"
					balance: 3771.28
			balance_value: 3771.28 # sum of account's balance for all accounts
			gains_before_conversion: 3791.14 # what GnuCash's own figure holds for this commodity
			balance_sheet_value: 3791.14 # 3791.14 CAD at 1 CAD per CAD
		commodity:
			commodity.mnemonic: "USD"
			splits:
				split:
					split_guid: d67e964ec67546f8ba36a483bc9bec47
					account: "Assets:Accounts Receivable USD"
					value: -2720.00
				split:
					split_guid: 8447276e4dab457d9286e883f2e1b698
					account: "Assets:Accounts Receivable USD"
					value: 2720.00
				split:
					split_guid: 6a09761a598a49c1be97b58a78456416
					account: "Assets:Bank:USD"
					value: 2720.00
			sum_value: 2720.00 # sum of split's value of all splits
			accounts:
				account:
					guid: 1812b84a64a44a859a105b039cc184ff
					name: "Assets:Accounts Receivable USD"
					balance: 0.00
				account:
					guid: f2ba3e98a7cb4a82807ee633ab331c67
					name: "Assets:Bank:USD"
					balance: 0.00
			balance_value: 0.00 # sum of account's balance for all accounts
			gains_before_conversion: -2720.00 # what GnuCash's own figure holds for this commodity
			balance_sheet_value: -3771.28 # -2720.00 USD at 1.3865 CAD per USD
	gnucash_balancing_amount: 19.86 # sum of balance_sheet_value of all commodities
```

`realized_gains_fx` states `0.00` and lists no transaction on a book that took none. `unrealized_gains_assets_fx` states `0.00` and lists no cost basis on a book holding no foreign currency. `unrealized_gains_other` states `0.00` and lists no security and no fund on a book holding neither. `gnucash_balancing_amount` states `0.00` and lists the commodity whose splits and balances came to the same amount, so a reader sees that the subtraction had figures to work on and came to nothing — which is a different thing from a book that holds no such currency at all, and lists no commodity.

## Why a book imported before `took_the_residual` existed states `realized_gains_fx: 0.00`

A plaintext file using `$residual$` and one stating the amount outright produce byte-identical splits: `import` calculates the residual as the negation of what the other splits come to, and stores that amount. The only difference is `took_the_residual`. `git log -S "took_the_residual"` finds it in exactly one commit, and the diff that introduced it is all additions: nothing was renamed, nothing lost, and the releases before it had no key to write.

The exchange gain or loss is still recorded in the book. The import posted it to an income or expense account, so the income statement shows it there.

`tests/fixtures/the_thousand_usd_sold_with_no_took_the_residual.txt` is that book: 1,000.00 USD bought at 1.30, sold for 1,400.00, the disposal valued at cost and giving the guid of the basis it draws on, and the 100.00 difference in `Income:FX Gain`, whose split carries no `took_the_residual`. As it stands `balance-sheet` states `0.00`; with `--fx-gain-account "Income:FX Gain"` it states `100.00`, which is what the identical sale states with no option at all when the book carries `took_the_residual`.

**The book cannot know which of a disposal's splits gives the realized gain, unless `took_the_residual` or `--fx-gain-account` says so.** A disposal balances, so the arithmetic gives every split the same answer, and the account type settles nothing: `tests/fixtures/the_thousand_usd_sold_less_a_charge_with_no_took_the_residual.txt` pays a 10.00 bank charge and leaves a 100.00 difference in one disposal, one on an expense account and one on an income account. Counting every income and expense split would state 110.00.

**`--fx-gain-account` overrides `took_the_residual` rather than adding to it.** A reader who states where their differences are booked has answered for the whole book; a balance sheet that also counted whatever keys happened to be in it would give an answer depending on which release imported which transaction.

## What GnuCash's balancing amount actually measures

**GnuCash treats `gnucash_balancing_amount` as the unrealized gain** — the gain on foreign money the book still holds. GnuCash's own balance sheet prints it under the heading `Unrealized Gains`, and adds it to equity, which is where an unrealized gain belongs. The `balance-sheet` command does the same thing with its own figure. The disagreement is not about where such a gain goes; it is about how the figure is arrived at.

GnuCash arrives at it by taking the summed values of the splits in a holding's own accounts away from what that holding is worth on the sheet's date. That gives the unrealized gain **only where every one of those splits carries a figure in the book's own currency.** Three scenarios, in round numbers: US dollars bought when the rate was 1.3, and a balance sheet produced later when the rate is 1.4. The measured figures from real books follow.

**Scenario 1 — A company buys US dollars with Canadian dollars and still holds them.** It pays 1,300.00 CAD out of its Canadian bank for 1,000.00 USD. At 1.4 they are worth 1,400.00, so the unrealized gain is 100.00 CAD. Both splits of that purchase carry Canadian figures, so GnuCash's subtraction has them to work on and it reports 100.00 CAD. It agrees with what the cost bases say, and it is correct.

**Scenario 2 — A company is paid in US dollars and still holds them.** The 1,000.00 USD comes in on a US dollar invoice, posted at 1.3, straight into a US dollar bank. The unrealized gain at 1.4 is the same 100.00 CAD. But **both splits of that invoice are in US dollars**, so there is no Canadian figure for GnuCash to take away, and it reports `0.00` where the gain is 100.00 CAD.

**Scenario 3 — A company is paid in US dollars and later spends them.** An unrealized gain belongs in equity, as though the book had an unrealized gain account, and GnuCash works out an amount to put there. On this book that amount is the **realized** gain, which the income accounts have already put into equity. The same amount reaches equity twice, and GnuCash's balance sheet is out of balance by exactly that amount.

**Scenario 3 goes wrong only because the company was paid in US dollars.** Where it bought that currency with its own money instead, both splits of the purchase record a Canadian amount, so GnuCash's subtraction has what it needs: it states `0.00` and its balance sheet balances. `examples/multi-currency/every_dollar_bought_and_sold_again.txt` buys 1,000.00 USD at 1.30 and sells it at 1.40 for a realized gain of 100.00 CAD, and its balancing amount is `0.00`.

**The example below comes from a real book of Scenario 3's shape.** A company invoices a US customer for 2,720.00 US dollars. The invoice is posted on a day when the USD/CAD rate is 1.393801, so the receivable is recorded at 3,791.14 CAD. The customer pays in US dollars, and the company receives them into its US dollar bank account without converting them to Canadian dollars.

The company then spends all 2,720.00 US dollars on a day when the rate is 1.3865, so its Canadian bank account receives 3,771.28 CAD. Those US dollars had cost 3,791.14 CAD, so the disposal results in a gain of 3,771.28 − 3,791.14 = −19.86 CAD — a loss of 19.86 CAD. This amount is usually recorded in an income account as the realized foreign exchange gain or loss, −19.86. The company is left holding no US dollars.

Assume the book holds nothing else — no other transactions, no opening balances.

**With the year-end rate at 1.3865**, the rate those dollars were actually spent at, `balance-sheet` states `gnucash_balancing_amount` among the other gain figures. This is that book, and `examples/multi-currency/a_us_supplier_paid_out_of_those_dollars.txt` is it as an example a reader can import and draw for themselves — the block below is what that file's own statement holds, guids and all:

```
gnucash_balancing_amount: # the commodities GnuCash's own figure is summed from
	commodities:
		commodity:
			commodity.mnemonic: "CAD"
			splits:
				split:
					split_guid: 3f09144435874cd79d377496d863218d
					account: "Assets:Bank"
					value: 3771.28
				split:
					split_guid: f92404223b5c4b0c8a50551c07626b0e
					account: "Assets:Bank:USD"
					value: -3791.14
			sum_value: -19.86 # sum of split's value of all splits
			accounts:
				account:
					guid: 8358132660024fe7ac0abbc3c71cee30
					name: "Assets"
					balance: 0.00
				account:
					guid: e7c821e0c3e34b71b41d17a32b42842b
					name: "Assets:Bank"
					balance: 3771.28
			balance_value: 3771.28 # sum of account's balance for all accounts
			gains_before_conversion: 3791.14 # what GnuCash's own figure holds for this commodity
			balance_sheet_value: 3791.14 # 3791.14 CAD at 1 CAD per CAD
		commodity:
			commodity.mnemonic: "USD"
			splits:
				split:
					split_guid: d67e964ec67546f8ba36a483bc9bec47
					account: "Assets:Accounts Receivable USD"
					value: -2720.00
				split:
					split_guid: 8447276e4dab457d9286e883f2e1b698
					account: "Assets:Accounts Receivable USD"
					value: 2720.00
				split:
					split_guid: 6a09761a598a49c1be97b58a78456416
					account: "Assets:Bank:USD"
					value: 2720.00
			sum_value: 2720.00 # sum of split's value of all splits
			accounts:
				account:
					guid: 1812b84a64a44a859a105b039cc184ff
					name: "Assets:Accounts Receivable USD"
					balance: 0.00
				account:
					guid: f2ba3e98a7cb4a82807ee633ab331c67
					name: "Assets:Bank:USD"
					balance: 0.00
			balance_value: 0.00 # sum of account's balance for all accounts
			gains_before_conversion: -2720.00 # what GnuCash's own figure holds for this commodity
			balance_sheet_value: -3771.28 # -2720.00 USD at 1.3865 CAD per USD
	gnucash_balancing_amount: 19.86 # sum of balance_sheet_value of all commodities
```

The two groups are what the 19.86 is made of, and they say where it came from. The Canadian group holds the disposal: its splits come to −19.86 against a bank holding 3,771.28, a difference of 3,791.14 needing no conversion. The US dollar group holds the invoice and its collection, whose splits are all in US dollars: they come to 2,720.00 while the accounts now hold nothing, so the difference is −2,720.00, converted at the sheet's rate to −3,771.28. The two converted figures added together are 19.86.

**The commodities are GnuCash's own, in the order its collector holds them, and each group's figure is read out of it.** They are not grouped here by anything this report decided: GnuCash merges the account balances, keyed by each account's own commodity, and subtracts the splits' values, keyed by the transaction's currency, so its figure spans both sets. `sum_value` and `balance_value` are printed beside each amount because they are what went into it — a reader can see the subtraction — but the amount itself is the collector's, so the groups come to the key rather than being made to.

**With the year-end rate at 1.45**, the book stays the same, and `gnucash_balancing_amount` states `-152.86 CAD`.

**With the year-end rate at 1.2**, the book stays the same, and `gnucash_balancing_amount` states `527.14 CAD`.

The arithmetic behind the three:

```
at 1.3865   2,720 × 1.3865 = 3,771.28   less 3,791.14 =  -19.86   so gnucash_balancing_amount states   19.86
at 1.45     2,720 × 1.45   = 3,944.00   less 3,791.14 =  152.86   so gnucash_balancing_amount states -152.86
at 1.2      2,720 × 1.2    = 3,264.00   less 3,791.14 = -527.14   so gnucash_balancing_amount states  527.14
```

**At 1.3865 that is the realized loss, and the arithmetic shows why.** 1.3865 is the rate those dollars were actually spent at, so 2,720 × 1.3865 is exactly the 3,771.28 CAD the company received. The subtraction is then what those US dollars cost less what it received for them, which is the realized gain or loss by definition. That holds at 1.3865 and at no other rate: at 1.45 or at 1.2 the 2,720.00 US dollars are converted at a rate nothing in this book ever happened at, and the result is neither gain.

GnuCash treats this amount as an unrealized gain. It is in fact the negative of the realized loss above: the loss is −19.86 and the amount is +19.86. That loss is already counted in equity — it went through the income accounts, so `retained_earnings` carries it and `total_equity` carries it in turn. Adding +19.86 on top cancels the loss rather than doubling it, which is why GnuCash's own balance sheet states 3,771.28 of assets against 3,791.14 of liabilities and equity — equity above the assets, not below. The `balance-sheet` command adds the unrealized gain measured from the cost bases instead — `0.00` here, since the company holds no US dollars — and balances at 3,771.28 at all three rates.

## Why two books with the same balancing amount are not the same case

Two books give a balancing amount equal to their own realized loss, and they are not the same case.

`the_usd_bank_spent_out_against_its_basis.txt` spends all 2,720.00 USD: its balancing amount is 19.86 and its realized loss is 19.86. `the_usd_bank_partly_spent_leaving_a_thousand.txt` spends 1,720.00 and keeps 1,000.00: its balancing amount is 12.56 and its realized loss is 12.56. Both agree because both balance sheets use the same rate those dollars were spent at.

The difference is what each book still holds. The first holds 0.00 USD, so its unrealized gain is 0.00 CAD. The second holds 1,000.00 USD with 7.30 of loss not yet taken, and a reader who took the matching figures to mean the whole 12.56 was already accounted for would be wrong about it. The groups are what tell them apart: on the second book the US dollar group's accounts hold 1,000.00 where the first book's hold nothing, so the difference converted is −2,384.78 rather than −3,771.28. Nothing on the page asserts which case it is; the figures do.

`_resolve_residual` refuses a residual with nothing to take — "asking for one where the splits already balance is an error rather than a silent zero" — so a plaintext file using `$residual$` cannot produce a disposal whose difference is nothing. Every disposal such a file writes moves the figures, so a book carrying one always has something in its groups for a reader to read. A hand-written `took_the_residual: "true"` on a `0.00` income split is a different path and is **not measured here**.

## What this does not handle yet

**A US dollar cost basis in a book that also trades a security in US dollars.** `tests/fixtures/a_cad_book_with_usd_hkd_and_shares_priced_in_its_price_database.txt` buys 10,000.00 USD with Canadian dollars, which opens a cost basis, and then buys shares, sells shares, borrows and repays a loan — every one of those in a transaction stated wholly in US dollars, so not one of them gives that cost basis's guid and the basis is never drawn down. It still reads 10,000.00 against a bank holding 7,480.00.

**What the page does about it is settled; what the book records is not.** A currency whose cost bases do not account for what the accounts hold keeps GnuCash's own revaluation, and is listed under `measured_from: gnucash_revaluation` with the cost and the worth that revaluation used in place of cost bases it cannot speak for. So the page states 940.00 and its items come to 940.00 — it does not disagree with itself, and `tests/integration/test_an_itemized_total_is_the_figure_the_key_states.py` holds that on this fixture among seven.

What is still wrong is upstream of the page: the basis should have been drawn down by the share purchase and was not, so 10,000.00 USD stands against a bank holding 7,480.00. The fallback reports honestly on that book rather than repairing it, and no figure on the page can repair it — only the import can, by recognising a stock bought with US dollars as consuming a US dollar cost basis. [Q-045](Q-045-draw-a-stock-bought-with-foreign-currency-from-that-currencys-cost-basis-and-open-one-for-what-a-sale-brings-in.md) records that, and until it is done this book's US dollars are measured GnuCash's way and say so on the page.

## Tests

`tests/integration/test_specifying_the_gain_account_states_a_gain_with_no_took_the_residual.py` holds eleven, including the book whose splits carry no `took_the_residual` stating nothing on its own, the charge left out of `realized_gains_fx`, two accounts specified at once, and `took_the_residual` passed over once an account is specified.

`tests/integration/test_the_sheet_says_what_gnucashs_balancing_amount_is.py` holds ten, one per situation, at three rates for the disposal case.

## Deliberate choices

**`--fx-gain-account` applies to the run it is specified on, and the GnuCash book keeps whatever it already holds.** A GnuCash book imported before 2026-09-18, when #108 added `took_the_residual`, is still accounting-correct: the foreign currency is removed at its carrying cost, the proceeds are recorded against it, and the difference is booked to an income or expense account as a realized exchange gain or loss. It lacks only what `took_the_residual` states: which split holds that difference. So the option has to be specified on every run. To put `took_the_residual` into the GnuCash book instead, export the ledger, add `took_the_residual: "true"` to that split, and import it again — the route `docs/multi-currency.md` sets out.

**An account the book does not have is warned about. An account the book does have that took no exchange difference is not.** `--fx-gain-account "Income:FX Gian"` on a book holding no such account warns `--fx-gain-account "Income:FX Gian" matches no account in this book, so no split counts against it and it adds nothing to realized_gains_fx`, and the balance sheet is printed all the same. Where the account is in the book and no transaction against it yields a realized exchange gain or loss, `realized_gains_fx` states `0.00` and the balance sheet says nothing further — refusing there would refuse correct balance sheets, since a balance sheet dated before that account took anything has no such transaction either.
