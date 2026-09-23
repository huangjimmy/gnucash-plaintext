# Q-046 — Give a security a cost basis in the book's own currency, so a sale realizes a gain the way a currency disposal does

Before this change, `realized_gains_other` was written on every balance sheet as `0.00 CAD # not yet supported`, and it was the last key on the page that stated no measured figure. Q-043 planned it and did not compute it; Q-045 puts it out of scope, being about the currency on either side of a share trade rather than the shares.

## What it should do

**Every commodity a book holds that is not its own currency is the same kind of thing**, and a share is not a special case of it. A holding is a quantity, a cost per unit in the book's own currency, and a price per unit in the book's own currency:

| holding | quantity | cost per unit, in CAD | price per unit, in CAD |
|---|---|---|---|
| US dollars | 10,000.00 | 1.30, the rate they were bought at | 1.42, the rate at the sheet's date |
| AMZN | 12.0000 | 260.00 — 200.00 USD at the 1.30 of the purchase day | 397.60 — 280.00 USD at the 1.42 of the sheet's date |

Both lines are the same arithmetic. What the holding is worth is quantity times price; what it cost is quantity times cost; the difference is the gain, unrealized while it is held and realized when it goes. A share is counted in shares and a dollar in dollars, and once both prices are converted that distinction has no consequence.

**Two rates, two days, and that is the whole of it.** The cost is converted at the rate on the day the units were bought and never moves again; the price is converted at the rate on the day the sheet is drawn. Putting the sheet's rate on both sides is the mistake this issue exists to correct: it cancels the currency out of the gain and leaves the share-price movement alone. On these 12 shares that is 3,408.00 of cost where 3,120.00 was paid, and a gain of 1,363.20 where the book made 1,651.20 — the 288.00 between them being 2,400 USD at the 0.12 the dollar rose.

**The pair price is the fact; the base-currency price is derived from it.** 200.00 USD per AMZN is what the book actually traded at, and 260.00 CAD per AMZN is that price carried through the 1.30 the US dollar stood at that day. A cost basis records both — the pair price because it is what happened, the Canadian figure because it is what the accounting is in — and the second is computed from the first rather than stored beside it as an independent number. Recorded the other way round, a correction to the day's USD/CAD rate leaves the Canadian cost saying what an old rate said, and nothing on the page would show it.

**So the itemized entry states all three**, because a reader cannot check the Canadian figure without the two it is made of. From `tests/fixtures/a_broker_fee_two_us_loans_and_part_of_the_shares_sold.txt`, whose share purchase is written wholly in US dollars, drawn at 2028-12-31:

```
	cost_bases:
		cost_basis:
			split_guid: a1a1a1a1a1a1a1a1a1a1a1a1a1a10003
			account: "Assets:Shares"
			cost_basis_balance: 3.0000
			cost_share_price: 99 # USD_CORP in USD, on the day it was bought
			cost_rate: 1.3 # CAD per USD, on that same day
			cost_share_price_in_base: 128.7 # cost_share_price * cost_rate
			cost_value: 386.10 # cost_basis_balance * cost_share_price_in_base
			value: 570.24 # cost_basis_balance * share_price
			unrealized_gains_other: 184.14 # value - cost_value
```

**`cost_share_price` is the price in the currency the transaction was stated in**, which is the only pair price the ledger holds. A purchase written wholly in US dollars states 99.00 USD a share and the entry says so. The same shares bought in a transaction stated in Canadian dollars state a Canadian price instead, and the entry then reads `cost_share_price: 260 # AMZN in CAD`, `cost_rate: 1` — the ledger's own figure either way, never a price fetched from elsewhere and presented as what the trade was at.

Where the security is held in the book's own currency there is no second rate, so `cost_rate` is 1 and `cost_share_price_in_base` is `cost_share_price` — the same three lines, saying the same thing about a simpler trade.

This is why the distinction has gone unnoticed so far: for US dollars bought with Canadian ones the pair *is* the book's currency against the foreign one, so the pair price and the base-currency price are the same number. A share bought in a transaction written wholly in US dollars is the first case where they are two.

**Half of this was on the page before this change.** `share_price: 397.6` for AMZN is in Canadian dollars — 280.00 USD at 1.42, converted by the report — and `unrealized_gains_other` was measured from it. What was missing was the other half: the cost, converted the same way. With it, `realized_gains_other` needs no machinery of its own:

- buying opens a cost basis on the security split, at what the units cost converted at the rate on the day they were bought;
- selling draws that basis down, and the difference between what the units cost and what they fetched is realized then — one subtraction, in the book's own currency;
- the file says which basis a sale drew on with `cost_basis_split_guid:`, and a sale that does not say is refused. Nothing is picked for the reader — which basis a disposal drew on decides the gain, the same reason it is never guessed for a currency;
- where a fee or a commission shares the transaction, `$residual$` and `took_the_residual` say which split is the difference, as they already do for a bank charge sitting beside an exchange difference;
- `realized_gains_other` is then the sum of those differences to the sheet's date, as `realized_gains_fx` is the sum of the currency ones.

**The gain that falls out carries both movements, and that is right.** Shares bought at 260.00 CAD and sold at 369.20 CAD made 109.20 CAD a share whether the share price rose, the dollar rose, or both. The book made that money; splitting it into a share part and a currency part is a presentation question, not a question of what the figure is, and no split in the book states such a division.

## What the same rule means for `unrealized_gains_other`

Every non-base commodity is measured the same way, so the unrealized figure for a security is measured from its cost bases too — `value − cost_value` over the bases, which is how `unrealized_gains_assets_fx` is measured — where they account for what the accounts hold, and from GnuCash's own revaluation where they do not, with `measured_from: gnucash_revaluation` on the page, as a currency's is.

Two things made that worth deciding rather than assuming:

- **The figure before this change agreed with GnuCash's own.** Q-043 investigated it and found `unrealized_gains_other` at 1,363.20 CAD with GnuCash's Advanced Portfolio agreeing exactly, by a different route. That agreement did not settle whether either was the cost the book paid: both convert the cost at the sheet's rate, so both leave the currency movement out of the gain, and they agreed because they make the same choice. Measured from the cost bases, the same 12 shares state 1,651.20.
- **It earns something on the books where the two part company.** GnuCash's revaluation is the converted balance less the summed split values, so it is the right answer only where every split carries a figure in the book's own currency. A security bought in a transaction stated wholly in US dollars is in exactly that position. Such a purchase now takes its cost from the dollars it spent: the cost basis those dollars came out of gives up what they cost, and it goes onto the shares, divided by each split's share of the dollars. `tests/fixtures/shares_bought_in_a_transaction_stating_no_canadian_figure.txt` buys two US-listed shares for 2,200.00 USD that cost 1.30, and prices them at 52.00 and 26.00 CAD a share.

## Why the code said otherwise

`establishes_cost_basis` was currency-only, and said so:

> Currency only: shares are counted in units and priced, not converted, so a security establishes nothing however its account is typed.

That reasoning is about **valuation**: a holding the book still has is priced at what a share fetches now. It does not carry over to **disposal**. A share that has been sold is not being priced; it is being compared with what it cost, and it cost something in Canadian dollars whatever it was counted in. So a security now opens a cost basis on the same terms as a currency.

## What was investigated

On `tests/fixtures/a_cad_book_with_usd_hkd_and_shares_priced_in_its_price_database.txt` as it stood before this change, which bought 20 AMZN at 200.00 USD and sold 8 at 260.00 USD in transactions written wholly in US dollars, drawn at 2026-12-31 on GnuCash 5.10:

```
	realized_gains_fx: 0.00 CAD
	realized_gains_other: 0.00 CAD # not yet supported
	total_realized_gains: 0.00 CAD # realized_gains_fx + realized_gains_other
	unrealized_gains_other: 1363.20 CAD
```

and the income statement of the same book for the same year:

```
	Income:Realized FX Gains 240.00 CAD
	Income:Realized Gains 480.00 USD
	total_revenue: 9421.60 CAD
	net_income: 9129.60 CAD
```

The sale itself, which carries every figure the subtraction needs:

```
2026-06-30 * "Sell 8 AMZN at 260.00 USD"
	currency.mnemonic: "USD"
	Assets:AMZN -8.0000 AMZN
		account.commodity.mnemonic: "AMZN"
		share_price: "200"
		value: "-1600.00"
	Assets:USD Bank 2080.00 USD
	Income:Realized Gains -480.00 USD
```

**The shares leave at what they cost** — 200.00 USD each, the price they were bought at, not the 260.00 they fetched — which is the same convention a currency disposal follows. So the 1,600.00 is the cost and the 2,080.00 is the proceeds, both in US dollars, and 480.00 is the difference the book already booked to income.

**`total_realized_gains` stated 0.00 for a book that realized 480.00 USD on its shares**, while the income statement beside it carried that 480.00. Two pages from one tool disagreed about whether anything was realized; the currency half of that was Q-044's subject.

**The fixture now states both trades in Canadian dollars**, the purchase at the 5,200.00 CAD the dollars cost and the sale at the 2,808.00 CAD the 2,080.00 USD fetched at 1.35, so the shares leave at 260.00 CAD each and `Income:Realized Gains` takes the difference as `$residual$`:

```
2026-06-30 * "Sell 8 AMZN at 260.00 USD"
	currency.mnemonic: "CAD"
	Assets:AMZN -8.0000 AMZN
		account.commodity.mnemonic: "AMZN"
		share_price: "260"
		value: "-2080.00"
		cost_basis_split_guid: "dddddddddddddddddddddddddddd0004"
	Assets:USD Bank 2080.00 USD
		account.commodity.mnemonic: "USD"
		share_price: "27/20"
		value: "2808.00"
	Income:Realized Gains $residual$ CAD
```

Both pages now say the same thing. The balance sheet at 2026-12-31:

```
	realized_gains_fx: 0.00 CAD
	realized_gains_other: 728.00 CAD
	total_realized_gains: 728.00 CAD # realized_gains_fx + realized_gains_other
	unrealized_gains_other: 1651.20 CAD
```

and the income statement for 2026:

```
	Income:Realized FX Gains 240.00 CAD
	Income:Realized Gains 728.00 CAD
	total_revenue: 9468.00 CAD
	net_income: 9176.00 CAD
```

**Q-043 investigated why GnuCash's own report cannot supply the figure**: Advanced Portfolio reads C$2,272.00 of Money Out against C$2,272.00 of basis and finds nothing made on the disposal, counting the 480.00 USD as Income instead — C$681.60 at 1.42. GnuCash is not wrong; shares leaving at their cost is what the book wrote.

## An income or expense account is kept in the book's own currency, and one kept in another is warned about rather than supported

A holding has a cost and a price, and the difference between them is a gain. An expense has neither: it is what it cost on the day it was incurred, and nothing that happens to a rate afterwards changes it. So the account it lands in is kept in the book's own currency, and a payment made in another currency is recorded at what that currency cost — which is the figure the cost basis it came out of gives up.

**A foreign income or expense account cannot be converted at all, because its balance has no one rate.** The balance is a sum of amounts from many days, and each of those days had a rate of its own; there is no single rate that turns the sum into a Canadian figure, and the sheet's own rate is simply the last of them applied to all. A balance sheet drawn a month later would report the same expense differently.

Investigated on two books:

| the account | what it cost | what the page reports | the page is short by |
|---|---|---|---|
| `Expenses:Brokerage` 1.00 USD | 1.30 CAD, the rate the dollars that paid it cost | 1.20 CAD, the sheet's rate | 0.10 |
| `Expenses:Interest` 100.00 USD | 130.00 CAD | 142.00 CAD | 12.00 |

`tests/fixtures/a_broker_fee_two_us_loans_and_part_of_the_shares_sold.txt` keeps its broker fee expense account in Canadian dollars for that reason, and its page balances at every one of its seven transactions. The second row is `a_cad_book_with_usd_hkd_and_shares_priced_in_its_price_database.txt`, whose `Expenses:Interest` is kept in US dollars, and which is the book the warning is shown on.

**That second book is corrected by moving the account.** Its whole US dollar side falls back to GnuCash's revaluation — the loan was drawn in a transaction stated wholly in US dollars, so the debt has no Canadian cost and the cost bases cannot account for what the accounts hold. As it stands, that fallback prices the 100.00 USD of interest at the sheet's 1.42 along with the rest, `cost_value: 10116.00` for `value: 10621.60`, and the page balances at 38,532.80 with the expense stated as 142.00. With `Expenses:Interest` kept in Canadian dollars and the repayment written in them — the 1,600.00 USD leaving the bank at the 1.30 they cost, the interest at 130.00 CAD, and the debt they pay off at the same 1.30 — it still balances at 38,532.80: `retained_earnings` is 12,738.00, 12.00 more with the expense at what it cost, and `unrealized_gains_fx` is 593.60, 12.00 less, because the fallback's cost moves with the repayment as it is written.

The fixture keeps the account in US dollars all the same, being the book the warning is shown on, and the page says what it is: a book gnucash-plaintext does not support, whose figures can be wrong.

**gnucash-plaintext does not support such an account, and both statements say so on the page rather than refusing to draw it.** The warning lists each account and the currency it is kept in, and says that every figure those accounts reach can be wrong:

```
	# ############################ WARNING ############################
	# These income and expense accounts are not kept in CAD:
	#
	#   Expenses:Interest — USD
	#
	# gnucash-plaintext does not support that, and every figure on this
	# page those accounts reach can be wrong.
```

The page is drawn because every other figure on it is right, and because what it prints is the material a reader needs to work the expense out: the account line states what the account holds in its own currency and the rate the page converted it at.

```
	Expenses:Interest 100.00 USD
		account.commodity.mnemonic: "USD"
		share_price: "1.42"
		value: "142.00"
```

A reader who knows the dollars that paid the interest cost 1.30 can read 130.00 off those three lines. The page cannot, because once the amounts are summed nothing in the book says which day each of them belongs to.

`--verify-integrity` reports the same accounts as a finding, so a book holding one exits 1.

## What the change settles

- **Which rate the cost is converted at.** Where the purchase states a figure in the book's own currency, the cost is read from the transaction: the shares' value over their amount. Where it states none, the cost comes from the cost basis the currency was spent out of, at what those units cost, and it is divided across what they bought by each split's share of them — a broker fee takes its own share, and a cost basis whose balance the file states gives up its cost as one it lowers does. Nothing is fetched from the price database for it.
- **Partial sales.** `tests/fixtures/a_broker_fee_two_us_loans_and_part_of_the_shares_sold.txt` sells 7 of 10 shares and realizes 429.66 CAD, and its page balances at every one of its seven transactions.
- **The eleven supported builds.** Everything above was investigated on GnuCash 5.10, and the integration tests written from it run on all eleven.

## Known, not yet investigated

- **A sale carrying a fee or a commission**, to confirm `$residual$` answers it the way it answers a bank charge beside an exchange difference, and that nothing has to be added for it.
- **Repeated purchases**, where several cost bases of one security exist at different costs and a sale gives the guid of the one it drew on.
- **A stock split, a merger and a return of capital**, where units or cost change without a disposal, so that none of them is read as one.
- **A security held in the book's own currency**, which has a cost basis and no currency movement, so the gain is the share movement alone.

## Out of scope

The currency on either side of a share trade — the dollars a purchase spends and a sale brings in — is [Q-045](Q-045-draw-a-stock-bought-with-foreign-currency-from-that-currencys-cost-basis-and-open-one-for-what-a-sale-brings-in.md). A book that buys shares with US dollars makes two disposals in one transaction: the dollars leaving, and later the shares. Both are cost bases in the book's own currency being drawn down, which is why the two issues share one mechanism and are worked together.

Nothing here is out of scope of the change this issue is worked in: `unrealized_gains_other` stated 1,363.20 CAD before it, converting the cost at the sheet's rate, and states 1,651.20 CAD measured from the shares' own cost bases.
