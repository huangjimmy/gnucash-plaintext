# Q-043 — State realized and unrealized gains separately, value foreign currency from the book's cost bases, and leave every other asset and liability to GnuCash's own revaluation

Reported from a real book, whose eight exported steps are under "User exported info" at the end. Every figure in this document was measured on GnuCash 5.10 (Debian 13) by running `balance-sheet`, `fx-balances` and the test suite; GnuCash's own report source was read on 3.8, 4.13 and 5.10.

## What it should do

The balance sheet states its gains as separate items, and states all of them.

- **Realized and unrealized are separate.** A gain on money the book has disposed of is realized; a gain on what it still holds is unrealized.
- **FX and non-FX are separate.** The gain on foreign currency and the gain on every other asset and liability are different things and never share a line.
- **gnucash-plaintext computes both gains itself.** GnuCash computes neither. It computes **one** figure, and that figure is not a gain of either kind: it is an amount GnuCash calculates just to balance the book. On the book below, which holds −12.56 realized and −7.30 unrealized at once, that amount is 12.56 and neither gain appears anywhere on the page.
- **GnuCash's own amount is still stated, under a label that says what it is.** `gnucash_balancing_amount` is the amount GnuCash calculates just to balance the book, carried onto the page as GnuCash gives it, sign included, so a reader with GnuCash's own page beside them can find that number here and see what it is.
- **Each kind has its total**, and GnuCash's balancing amount is stated, never added into anything.

Where each figure comes from:

- **the foreign-currency figures**, from the book's cost bases: what each cost basis still has against it, at the nearest price, less what that cost basis cost. **The two sides of the sheet are stated separately** — `unrealized_gains_assets_fx` for currency the book holds, `unrealized_gains_liabilities_fx` for currency it owes, and `unrealized_gains_fx` for the two added together. Each side is measured against its own cost bases and checked against its own balances: a book that holds a currency and owes it at once would otherwise match on neither. A currency the cost bases cannot speak for keeps GnuCash's own revaluation and is still stated on its side, because it is currency however it was measured — a disposal that gives no cost basis guid leaves a balance that is not what the book holds, and a borrowing stated wholly in the foreign currency carries no figure in the book's own for either side to be priced by;
- **every other asset and liability**, from GnuCash's own revaluation, unchanged — a stock, a mutual fund, any commodity counted in units and priced rather than converted from a currency. `unrealized_gains_other` states it, and it is added into `total_unrealized_gains`. **Planned, and not computed here**: `realized_gains_other`, the gain a disposal of one of those took. Why it is not computed is measured rather than assumed, below: GnuCash's own Advanced Portfolio states 0.00 for it on the book this issue's tests are drawn from, because a disposal written at what the units cost leaves nothing made on the disposal itself, and the gain the ledger booked is counted as income instead. What computing it would need is a record of which income split that gain is, the way `took_the_residual` records the currency side. While it is not computed, `total_realized_gains` is the foreign-currency figure alone.

**The two keys divide by what the money is, never by who measured it.** A currency that is not the book's own is `_fx` whether its figure came from a cost basis or from GnuCash's own revaluation; a security is `_other`. Sorting by the source instead would state an exchange loss under the key that says it is not one — a US dollar loan whose proceeds were banked in Canadian dollars is an exchange loss either way.

For step 7 of the example, where the book holds nothing and has lost 19.86 CAD on the dollars it disbursed:

```
	realized_gains_fx: -19.86 CAD
	total_realized_gains: -19.86 CAD
	unrealized_gains_assets_fx: 0.00 CAD
	unrealized_gains_liabilities_fx: 0.00 CAD
	unrealized_gains_fx: 0.00 CAD
	unrealized_gains_other: 0.00 CAD
	total_unrealized_gains: 0.00 CAD
	gnucash_balancing_amount: 19.86 CAD
```

**The realized figures are stated, not added in.** They are inside `retained_earnings` already, having gone through the income statement, so adding them to `total_equity` a second time is exactly what leaves 19.86 CAD of equity standing against 0.00 CAD of assets today. Only the unrealized total is equity the book has yet to take.

**The gains are at the book's own sign; GnuCash's amount is at GnuCash's.** A gain this tool computes is stated the way the book took it, so a loss reads negative. GnuCash's balancing amount is carried across unchanged — `19.86` on the book above, `12.56` on the partly spent book below, both positive where the book took a loss — because a reader looks it up to reconcile against GnuCash's own page, and a figure quietly re-signed on the way would not be found there.

### The page shows how each gain was worked out

Every other figure on the page can be checked by a reader. An account line is what that account holds, and they have the book. A section total is the lines above it added up. A gain can be checked against neither: it is measured against costs that appear on no line of the page at all. A total nobody can reproduce is a total nobody should trust, so the page states its working, and does so by default.

Under the keys, as comment lines, grouped by the key each list belongs to and **adding up to it**. From the book that earns US dollars three times and spends every one of them out in four payments, whose realized figure is 250.00:

```
	# realized_gains_fx:
	#   2026-07-01 Income:FX Gain 90.00 CAD
	#   2026-08-01 Income:FX Gain 80.00 CAD
	#   2026-09-01 Income:FX Gain 60.00 CAD
	#   2026-10-01 Income:FX Gain 20.00 CAD
```

and from the book holding Hong Kong dollars, US dollars and shares, which has realized nothing and says so:

```
	# realized_gains_fx:
	#   nothing
	#
	# unrealized_gains_assets_fx:
	#   asset 5500.00 HKD cost 1000.00 CAD, at 0.2 worth 1100.00 CAD = 100.00 CAD
	#   USD 840.00 CAD
	#
	# unrealized_gains_other:
	#   AMZN 1363.20 CAD
	#
	# gnucash_balancing_amount:
	#   AMZN 1363.20 CAD
	#   HKD 100.00 CAD
	#   USD 840.00 CAD
```

They are two books because no one book prints both: a page showing four disposals and those holdings together would be a page no reader could reproduce.

- **Both computations are shown.** A line reading `cost … at … worth …` is measured from the book's own cost bases and states its arithmetic; a line of a commodity and an amount is GnuCash's own revaluation of everything the book holds of it — what that is worth at the price nearest this date, less the sum of its splits' values. By commodity rather than by account, because GnuCash values a holding whole: it takes the quantity through the price once, so an account's share of that is a figure nobody computed, and rounding each share on its own put a sheet a cent out of balance on a book holding one security at two brokers. A reader can hold the two computations against each other, which is the whole reason for stating GnuCash's beside ours.
- **Grouped by key, never by source.** `unrealized_gains_assets_fx` above is 940.00, and it is HKD's 100.00 from a cost basis *plus* US dollars' 840.00 from GnuCash's revaluation, because that currency's cost basis balance is not what the book holds. Listing the two sources separately would leave no list adding up to the key, which is what the working exists to give.
- **A key with nothing behind it says `nothing`.** An answer a reader can check; silence is not.
- **Every gain list adds up to its key, and `gnucash_balancing_amount`'s does not.** Each gain figure is rounded term by term before the terms are added, so the lines beneath it come to it exactly — a working that does not add up to its own key is worse than no working, because the page says it does. GnuCash's own amount is the deliberate exception: GnuCash converts a whole holding at once, so two accounts in one foreign currency have their split values added before that conversion rounds them, and the same figures listed per account can come to a cent less. Rounding the key to match its lines would make it agree with the page and stop agreeing with GnuCash, which is the only reason the key is carried at all. The lines stay as GnuCash computes them and the page says they are not a total.
- **Comments, so the format is unchanged.** `#` opens a line every reader of this format skips, which is what lets the working be added without changing what a page means to a program. The page already explains its keys the same way.
- **`--no-itemize` turns it off**, on `balance-sheet` and on `report`. The keys are untouched either way.
- **The working is itself checked.** `tests/integration/test_the_sheet_shows_how_each_gain_was_worked_out.py` reads the page's working back, sums each group and compares it with the key above it, on a book of cost bases and a fallback and a security, a book of four disposals against three cost bases, and a book of four cost bases at four rates. An itemization nobody verifies is only more text.

**Where each half is computed, and why it is not arbitrary.** Facts held in KVP slots come from Python — a cost basis balance, what it cost, and the mark saying which split took a `$residual$` are all custom KVP this tool's own code owns, and `plaintext:set-cost-bases!` and `plaintext:set-realized-items!` carry them across. Facts held by GnuCash's engine — balances, prices, split values — are computed in the report, in Scheme. The unrealized working and GnuCash's per-account revaluation are engine facts; the realized items and the cost bases are KVP. One rule, both halves.

### The page says what the keys are

Seven keys with nothing to read them by are worse than one, so the report writes the explanation into the block's comment lines, beside the ones Q-042 already has it write. `#`, `;` and `;;` all open a comment in this format and anything reading a block passes over them; the lines already there use `#`, and these join them rather than forming a second block.

They have to cover four things: what separates a realized gain from an unrealized one, and where each has already been booked; what `_fx` and `_other` divide between them; that only the unrealized total reaches `total_equity`, a realized gain being in the income and expense accounts already; and that the last figure is GnuCash's own, neither gain, an amount it calculates just to balance the book. Each is worded without printing any key's own name, so a page can still be asked whether it carries a key.

These lines are the balance sheet's alone. The income statement states none of these keys, and the two statements otherwise share the comment lines they are written from, so the shared ones stay shared and these are added only where they mean something.

A CAD book posts a 2,720.00 USD invoice, receives payment to a US dollar bank account, and disburses those dollars again — every one of those transactions stated in US dollars, because that is the currency they happened in. By the year end the book holds no US dollars at all, and the 19.86 CAD it lost on them is on the income statement. The page still states `unrealized_gains: 19.86 CAD`, and 0.00 CAD of assets against 19.86 CAD of liabilities and equity.

## The book that started it

The book is one USD invoice, its collection, a transfer out and two bank charges, carried through the eight states a real workflow passes: posted, imported from the bank, linked to the payment, unlinked, linked again, and finally classified into fee and foreign-exchange accounts. The blocks are exported below, step by step.

### The 19.86 is a realized gain or loss

By step 7 all 2,720.00 USD have been spent. They went in three transactions, and gnucash-plaintext valued each disposal at what those dollars cost — 189557/136000 CAD/USD — and booked the difference between that and what they fetched to `Income:Non-farming revenue:Foreign exchange gains/losses`. Every figure here is on the step 7 blocks below:

| transaction | USD spent | valued at cost | what it fetched | to Foreign exchange gains/losses |
|---|---|---|---|---|
| Wise charge | 0.72 | 1.00 | 1.00 of bank charge | none |
| transfer to the payee | 2,710.68 | 3,778.15 | 3,758.36 | 19.79 |
| Wise charge | 8.60 | 11.99 | 11.92 of bank charge | 0.07 |
| | **2,720.00** | **3,791.14** | **3,771.28** | **19.86** |

Three disposals, and only two produce a gain or loss. The first produces none because 0.72 USD at that cost is 1.00 CAD, which is exactly what the charge was.

GnuCash works out 19.86 from the same three transactions, out of each split's CAD value. **It is the same 19.86, and it is the realized gain or loss.**

Step 7's own two pages show what that costs. The income statement has the loss, where it belongs:

```
	Income:Non-farming revenue:Foreign exchange gains/losses -19.86 CAD
	total_revenue: 3771.28 CAD
	net_income: 3758.36 CAD
```

and the balance sheet counts it a second time:

```
	total_assets: 0.00 CAD
	total_liabilities: 0.00 CAD
	Equity:Equity:Retained earnings/deficit -3758.36 CAD
	retained_earnings: 3758.36 CAD
	unrealized_gains: 19.86 CAD
	total_equity: 19.86 CAD
	total_liabilities_and_equity: 19.86 CAD
```

The book holds nothing at all — `total_assets: 0.00` — so there is nothing left for a gain to be on. The 19.86 is already inside `retained_earnings`, through the income statement above it. Printing it again as `unrealized_gains` leaves 19.86 of equity standing against 0.00 of assets.

## What was measured

### GnuCash restates a foreign acquisition's cost at the nearest price

Read from GnuCash's shipped `balance-sheet.scm`. The computation and the header comment below are the same on 3.8, 4.13 and 5.10, at two paths — `/usr/share/gnucash/scm/gnucash/report/standard-reports/` on 3.8, and `/usr/share/guile/site/3.0/gnucash/reports/standard/` from 4.13 on. (From 4.13 a deprecated copy of the same file name also ships, under `gnucash/deprecated/`, and it holds neither the computation nor the comment — a `find` that takes the first match reads the wrong file.)

```scheme
(unrealized-gain-collector
 (if use-trading-accts?
     (gnc:collector+)
     (gnc:collector- asset-balance
                     liability-balance
                     (gnc:accounts-get-comm-total-assets
                      (append asset-accounts liability-accounts)
                      get-total-value-fn))))

(define (get-total-value-fn account)
  (gnc:account-get-comm-value-at-date account reportdate #f))
```

The shape of the subtraction is right. What a holding is worth, less what it is carried at, is what an unrealized gain is, and taking what is left over is a fair way to get it. **The defect is in the second term.**

`gnc:account-get-comm-value-at-date` sums an account's split *values*, and a split's value is stated in its own transaction's currency. Where the transaction is in the book's currency that value **is** the carrying amount, and the term is exact. Where the transaction is in the foreign currency — a payment applied to a US dollar invoice and deposited to a US dollar bank, every split in US dollars — there is no CAD figure in it at all, so the report converts the foreign sum at the **nearest price**. The carrying amount of that acquisition is restated at the nearest price instead of staying at what the currency cost.

The rest is arithmetic. Measured on the partly spent book below, which holds 1,000.00 USD and has disposed of 1,720.00, the two collectors are:

| account | balance | its splits' values |
|---|---|---|
| `Assets:Bank` | 2,384.78 CAD | 2,384.78 CAD |
| `Assets:Bank:USD` | 1,000.00 USD | 2,720.00 USD, and −2,397.34 CAD |
| `Assets:Accounts Receivable USD` | 0.00 USD | 0.00 USD |
| | **CAD 2,384.78, USD 1,000.00** | **CAD −12.56, USD 2,720.00** |

The 2,720.00 USD in the value column is the acquisition — a payment applied to the invoice and deposited to the US dollar bank, every split in US dollars, so it carries no CAD figure and enters as US dollars. The −2,397.34 CAD is the disposal, recorded at what those dollars cost. Converting both collectors and subtracting gives the figure. What does the converting is the **nearest price**: what the report's `Commodities / Price Source` gives for US dollars at the sheet's date, which by default is `pricedb-nearest` — the price nearest that date in the book's price database. In these runs `--fx-rates` puts it there, in CAD per one US dollar:

```
(2,384.78 + 1,000.00 × nearest price) − (−12.56 + 2,720.00 × nearest price)  =  2,397.34 − 1,720.00 × nearest price
```

| CAD per USD at 2026-12-31 | the balances | the splits' own figures | difference |
|---|---|---|---|
| 1.3865 | 2,384.78 + 1,386.50 = 3,771.28 | −12.56 + 3,771.28 = 3,758.72 | **12.56** |
| 1.45 | 2,384.78 + 1,450.00 = 3,834.78 | −12.56 + 3,944.00 = 3,931.44 | **−96.66** |

The 12.56 is what GnuCash prints for this book.

So in general the figure is:

```
GnuCash's balancing amount = value of the disposals − amount disposed × nearest price
```

— here 2,397.34 CAD against 1,720.00 USD at the nearest price. The 1,000.00 USD still held drops out of it entirely: its balance and its acquisition are both revalued at that same nearest price and cancel each other, so nothing in the figure is about the currency the book is holding.

### Why the reported example's figure is its realized loss

The two figures are:

```
realized gain    = proceeds − value of the disposals
GnuCash's balancing amount = value of the disposals − amount disposed × nearest price
```

They come to the same thing exactly when `amount disposed × nearest price` equals the proceeds — that is, **when the nearest price is the rate the currency left at**.

In the reported book it is. The dollars left on 2026-08-13 and 2026-08-17, and the price the year-end sheet draws on is 1.3865, the rate of that transfer: 2,720.00 USD at 1.3865 is 3,771.28 CAD, and the disposals fetched 1.00 + 3,758.36 + 11.92 — the same 3,771.28. So GnuCash's balancing amount comes to 3,791.14 − 3,771.28, the 19.86 the book lost and booked to `Income:Non-farming revenue:Foreign exchange gains/losses`.

It is the book that makes them meet, not the report. Hold the year-end price away from the rate the currency left at and they part: the partly spent book at 1.45 gives −96.66 where its realized loss is still 12.56. A book whose foreign currency left at one rate and is priced at another on the report date gets a figure that is neither of its two gains.

**The customized report inherited the label rather than choosing it.** `infrastructure/gnucash/reports/balance-sheet-and-income-statement-as-text.scm` is written from `balance-sheet.scm` and transcribes that computation call for call, `gnc:account-get-comm-value-at-date` included, so it prints what GnuCash's own page prints and calls it what GnuCash calls it.

**GnuCash's own author does not vouch for the multicurrency case.** From the header of the same file:

> The multicurrency support has been tested, BUT IS ALPHA.  I *think* it works right, but can make no guarantees....  In particular, I have made the educated assumption \<grin\> that a decrease in the value of a liability or equity also represents an unrealized loss.  I *think* that is right, but am not sure.

Measured at step 2:

| account | balance at 2026-12-31 | valued at 1.3865 | the sum of its split values | GnuCash's cost |
|---|---|---|---|---|
| `Assets:Current assets:Accounts receivable:USD` | 2,720.00 USD | 3,771.28 | 2,720.00 USD | 3,771.28 |
| the USD bank | 0.00 USD | 0.00 | 0.00 USD | 0.00 |
| `Assets:Current assets:Due from shareholder(s)/director(s)` | −19.86 CAD | −19.86 | 0.00 USD | 0.00 |
| | | **3,751.42** | | **3,771.28** |

3,751.42 − 3,771.28 is the −19.86 the page prints, and the 3,791.14 the invoice actually cost appears nowhere in that column. The receivable's own split carries no CAD figure — the CAD is on the income split facing it — so there is nothing for GnuCash to read.

The last row is the second half of it. `Due from shareholder(s)/director(s)` is a **CAD** account, and it holds −19.86 CAD that needs no revaluing at all. Its splits sit in US dollar transactions, so their values are in US dollars and they sum to zero, and GnuCash therefore reconstructs its cost as 0.00 CAD. An account held in the book's own currency is not foreign money and must contribute nothing to this figure.

### A book holding both kinds of gain at once

The reported example spends every dollar, so it cannot tell the two apart. This one keeps 1,000.00 USD back: 1,720.00 USD leave, valued at what they cost, and 1,000.00 stay in the bank. The realized loss on what went is 12.56 CAD, which `Income:FX Gain` carries and `retained_earnings` therefore includes; the unrealized loss on what stays is 7.30 CAD.

What GnuCash's own Balance Sheet prints for that book as of 2026-12-31, read from its HTML page:

```
Total Assets                  C$3,771.28
Total Liabilities             C$0.00
Retained Earnings             C$3,778.58
Unrealized Gains              C$12.56
Total Equity                  C$3,791.14
Total Liabilities & Equity    C$3,791.14
```

**GnuCash states 12.56 as the unrealized gain**, and the unrealized loss — 7.30, on the 1,000.00 USD the book is still holding — appears nowhere on the page. Its own sheet does not balance either: 3,771.28 of assets against 3,791.14 of liabilities and equity, 19.86 apart.

12.56 is also what this book's realized loss comes to, and that is a coincidence of the rate rather than a rule: these dollars left at 1.3865, which is the price the sheet is drawn at. Measured on the same book at 1.45, GnuCash's balancing amount is −96.66 while the realized loss is still 12.56. It is neither gain — it is the disposal's recorded cost against those same dollars revalued at the nearest price, as the arithmetic above sets out.

Read from the book's cost bases instead, the same book gives the unrealized loss of −7.30, and equity of 3,778.58 − 7.30 = 3,771.28, the assets exactly.

### Securities revalue correctly, and are left for later work

Measured on two books built for it, each drawn at two prices, with a realized gain already taken out of both. The first holds no foreign currency at all:

| book, priced at the year end | unrealized | GnuCash's own page |
|---|---|---|
| 100 AMZN bought at 100.00 CAD, 40 sold at 200.00, priced 150.00 | 3,000.00 | 3,000.00 |
| the same, priced 250.00 | 9,000.00 | 9,000.00 |
| 100 AMZN bought at 100.00 USD with USD at 1.30, bought and sold through the CAD bank, 40 sold at 200.00 USD, priced 150.00 USD with USD at 1.50 | 5,700.00 | — |
| the same, priced 250.00 USD | 14,700.00 | — |

Every sheet balances, and `$residual$` booked the realized gain — 4,000.00 on the first book, 6,000.00 on the second. It comes out right because the cost was recorded in the book's own currency both times: 13,000.00 CAD on the purchase, 5,200.00 released by the sale. That is the same condition the currency path fails.

**A foreign-denominated security's gain is two movements in one figure.** Of the 5,700.00, 3,900.00 is the share price moving from 100.00 to 150.00 USD and 1,800.00 is the US dollar moving from 1.30 to 1.50. A security opens no cost basis, so that second part sits in none, and the `_fx` and `_other` division does not cut it cleanly. Nothing here computes it, and a security bought from a foreign bank — where the purchase carries no figure in the book's currency at all — is not measured.

### What GnuCash's own report makes of a security's two gains

GnuCash computes both figures itself, in its **Advanced Portfolio** report — report guid `21d7cfc59fc74f22887596ebde7e462d`, the same on every supported build, at `report/standard-reports/advanced-portfolio.scm` below 4.4 and `reports/standard/advanced-portfolio.scm` from 4.4 on. Its options sit under `General` rather than `Commodities`, so the date is `("General" "Date")` and the currency `("General" "Report's currency")`, and its `Basis calculation method` defaults to `average-basis` with `fifo-basis` and `filo-basis` the alternatives.

Measured on `tests/fixtures/a_cad_book_with_usd_hkd_and_shares_priced_in_its_price_database.txt` at 2026-12-31 in Canadian dollars, with that report's own defaults, by `tests/research/what_gnucash_computes_as_a_securitys_realized_gain_probe.py`:

| Advanced Portfolio column | AMZN |
|---|---|
| Basis | C$3,408.00 |
| Value | C$4,771.20 |
| Money In | C$5,680.00 |
| Money Out | C$2,272.00 |
| **Realized Gain** | **C$0.00** |
| **Unrealized Gain** | **C$1,363.20** |
| Income | C$681.60 |

**The unrealized figures agree exactly.** `unrealized_gains_other` states 1,363.20 CAD and so does GnuCash's own report, by a different route: the balance sheet takes the converted balances less the summed split values, and Advanced Portfolio takes value less basis. Two ways of asking give one answer.

**The realized figures do not, and GnuCash is not wrong.** The book sells 8 AMZN that cost 200.00 USD for 260.00 USD, and writes the disposal at what those shares cost:

```
Assets:AMZN -8.0000 AMZN
	share_price: "200"
	value: "-1600.00"
Assets:USD Bank 2080.00 USD
Income:Realized Gains -480.00 USD
```

That is the convention a currency disposal follows — the units leave at their cost and the difference is a split of its own — so GnuCash reads shares leaving at exactly the basis they carried, C$2,272.00 of Money Out against the C$2,272.00 of basis those 8 held, and finds nothing made on the disposal. The 480.00 USD is not lost: GnuCash counts it as **Income**, the C$681.60 above, which is 480.00 USD at 1.42.

**So `realized_gains_other` cannot be read off GnuCash's column**, and what it needs is what the currency side needed. The 480.00 is in the book and on the income statement already; what no saved transaction says is that *this* income split is a gain on a security rather than a dividend or any other income, and an account is not one or the other because of what it is called. The currency side answers that with `took_the_residual`, written where the file declared `$residual$`. A security disposal states its gain outright instead of declaring it, so there is no declaration to record — that is the gap, rather than any defect in GnuCash's figure.

### The same report asked for a currency account

Advanced Portfolio is not limited to securities. Its Accounts option permits `ACCT-TYPE-ASSET`, `ACCT-TYPE-BANK`, `ACCT-TYPE-STOCK` and `ACCT-TYPE-MUTUAL`; what leaves a bank account off is the option's *default value*, `(filter gnc:account-is-stock? …)`. Asked for one, it reports the currency as a commodity — `Listing CURRENCY`, the balance as its shares, the exchange rate as its price.

**Two things to know before repeating this.** An account holding nothing at the report date is left off unless `Include accounts with no shares` is on, and it defaults to off — so a book that spent every dollar prints an empty total, which reads as a computed zero rather than as the account never having been measured. And that phrase is the option's name: the sentence beside it in the Scheme is its help text, and setting the help text sets nothing and gives the same empty page.

Measured on a book holding nothing but the currency — 1,000.00 USD bought at 1.30 and every dollar sold at 1.40, from `tests/fixtures/a_cad_book_that_bought_a_thousand_usd.txt` and `the_thousand_usd_sold_at_a_higher_rate.txt`:

| | |
|---|---|
| Money In | C$1,300.00 |
| Money Out | C$1,300.00 |
| **Realized Gain** | **C$0.00** |
| Income | C$100.00 |
| `realized_gains_fx` on the same book | **100.00 CAD** |

**Its realized column is 0.00 on any book this tool writes, and that is structural rather than a disagreement.** A disposal here is valued at what the units cost, so Money Out equals Money In and nothing was made on the disposal as that report reads it. The gain sits in its Income column instead — the same 100.00. So its arithmetic cannot be borrowed to check the cost-basis figure: transcribed into this report it would compute zero on every book, and its Income column is the income splits, which is where the cost-basis figure already comes from.

**With nothing spent, the two agree exactly.** A disposal valued at what the units cost is the whole of what separates them, so a book that has disposed of nothing has nothing to separate. Measured on the same book before its dollars are sold — 1,000.00 USD bought at 1.30 and held, priced at 1.45 on the sheet's date:

| | gnucash-plaintext | Advanced Portfolio |
|---|---|---|
| what it cost | 1,300.00 | Basis C$1,300.00 |
| what it is worth | 1,450.00 | Value C$1,450.00 |
| **unrealized** | **150.00 CAD** | **C$150.00** |
| realized | 0.00 CAD | C$0.00 |

That is a real check on `unrealized_gains_fx`: two computations that share no code arriving at one figure, and the currency's counterpart of the 1,363.20 the securities case gives twice over.

**A figure that is not 0.00 there is measuring something else.** The same report gives C$167.25 for the US dollar account of the Q-042 fixture, and that book's own columns say why: C$142.00 of Brokerage Fees is the 100.00 USD of loan interest at 1.42, C$921.60 of Income is the 480.00 USD taken on the shares at 1.42 plus the 240.00 CAD taken on the currency, and the basis is averaged over every inflow — including 4,000.00 borrowed dollars that cost no Canadian dollars at all. That account carries a borrowing, loan interest and the proceeds of a share sale as well as its own currency movement, so no figure computed for it speaks for the currency alone.

### A cost basis balance is not an account balance, and a book can let the two disagree

`fx-balances` on the fixture the existing Q-042 expectations are measured on, `tests/fixtures/a_cad_book_with_usd_hkd_and_shares_priced_in_its_price_database.txt`:

| date | account | cost | brought in | cost basis balance | what that account holds at 2026-12-31 |
|---|---|---|---|---|---|
| 2025-05-05 | `Assets:USD Bank` | 1.3 CAD/USD | 10,000.00 USD | **10,000.00 USD** | **7,480.00 USD** |
| 2025-06-08 | `Assets:HKD Bank` | 2/11 CAD/HKD | 5,500.00 HKD | 5,500.00 HKD | 5,500.00 HKD |
| — | `Liabilities:USD Loan` | — | — | **no cost basis at all** | 2,500.00 USD owed |

The cost bases say the book holds 10,000.00 US dollars. The book holds 7,480.00 and owes 2,500.00. The 4,000.00 borrowed on 2025-07-12 opened no cost basis, because both of that transaction's splits are in US dollars and it states no CAD figure to price them by. None of the disposals lowered a balance, because a balance falls only where a disposal gives the guid of the cost basis it is measured against, and none of these do.

What `fx-balances` reports is what the book acquired and has not sold against. On a book whose disposals each give the cost basis they draw on, that is the currency the book still holds. On this fixture it is not, and the gap is the whole 3,000.00 USD sold on 2026-07-15.

### A borrowing stated wholly in US dollars opens no cost basis on either side

Borrowing 4,000.00 US dollars raises two balances in the same currency at once: 4,000.00 USD in the bank, and 4,000.00 USD owed. Neither was bought with Canadian dollars, so neither carries a figure in the book's own currency, and the two offset each other while both stand — the borrowing itself changes what the book is exposed to not at all. What it costs is settled later, when Canadian dollars are converted to repay, or US dollars are earned to repay, or more is borrowed.

Recording that needs a cost basis on **both** sides, the deposit and the debt, and the side is not what stands in the way. `establishes_cost_basis` in `services/foreign_currency.py` opens one for currency arriving on an asset and for currency owed on a liability or a payable alike — `_CREDIT_TYPES` holds `ACCT_TYPE_LIABILITY` — so a loan whose transaction states a Canadian figure for the debt gets a cost basis on it, and `unrealized_gains_liabilities_fx` is measured from that. `tests/fixtures/a_cad_book_that_borrowed_usd_into_its_cad_bank.txt` is that book, and its working reads `liability -1000.00 USD cost -1300.00 CAD, at 1.4 worth -1400.00 CAD = -100.00 CAD`.

What stands in the way here is what the transaction is written in. Both of this borrowing's splits are in US dollars, so nothing in it says what those dollars cost, and a cost basis opens on neither side without one. The deposit and the debt each carry a balance the sheet cannot measure against, and the borrowed dollars have no cost basis for a disposal to draw on.

That is one of the two reasons this fixture's cost bases and its accounts disagree about how many US dollars it has. It is a gap in the cost basis machinery rather than in this report, and it is not closed here. What this report does about it is leave such a currency to GnuCash's own revaluation rather than measure it against cost bases the book itself contradicts. Measured on this fixture, the page comes out at 38,532.80 CAD on both sides with the fallback in play, and the disagreement stays visible in the working, which states GnuCash's revaluation of that account instead of a cost and a worth. **That is not a promise that every such book balances.** The fallback states what GnuCash states, and GnuCash reconstructs cost from the sum of an account's split values — so a book whose foreign splits carry no figure in the book's own currency gives that revaluation nothing to read, and its page can come out short by whatever the cost bases would have supplied. What the fallback guarantees is that the currency is stated rather than silently dropped, and that the working says which of the two measured it.

### What that disagreement costs

The book's one US dollar cost basis still has the whole 10,000.00 against it, because the 2026-07-15 sale of 3,000.00 USD gives no `cost_basis_split_guid:` and so drew nothing down. Those 3,000.00 dollars are gone, and the gain on them is booked already: the fixture's own ledger credits `Income:Realized FX Gains` with 240.00 CAD, which puts it inside the `retained_earnings` of the same sheet. A cost read from that basis is a cost for dollars the book no longer holds, and it states the 240.00 a second time.

GnuCash's own figures for this book are `unrealized_gains: 2303.20 CAD` against `total_assets: 38532.80 CAD`. `tests/integration/test_the_statements_are_printed_by_customized_gnucash_reports.py` still pins that total, and the 2,303.20 with it — as `total_unrealized_gains`, over the five keys this issue divides the single one into: 940.00 of currency, 1,363.20 of shares.

## What it should be

### What changes, and what does not

GnuCash's account lines, section totals, prices and conversions are right and stay exactly as they are. Two things change.

- **The cost the foreign-currency gain is measured against** comes from the book's cost bases. A transaction that brought currency in while stated in that currency carries no CAD figure for GnuCash to read, which is why its own reconstruction cannot answer.
- **What the page states.** One `unrealized_gains` key becomes the separate realized and unrealized, FX and non-FX items above, with their totals.

### What the gain on foreign money is

Per currency, and for each side of the sheet on its own, in the book's own currency:

```
value = that side's balance in that currency  ×  the nearest price
cost  = Σ over that side's cost bases of ( cost basis balance × what that cost basis cost )
gain  = value − cost
```

`unrealized_gains_assets_fx` is that gain totalled over every currency for the currency the book holds, `unrealized_gains_liabilities_fx` the same for the currency it owes, and `unrealized_gains_fx` the two added together. A loan drawn at 1.30 and worth 1.40 at the year end has cost the book the difference, and that is a figure of its own rather than one netted against what its bank holds.

**Each side is money before the two are added.** Every figure is rounded to the report currency's smallest unit on its own, so the three the page states come to one another exactly; added first and rounded once, two of them could differ from the third by a cent, and a reader adding up three printed lines would find them wrong.

**The sides are kept apart because each is checked against its own balances.** A cost basis balance is what the book still has of that currency on that side, and a book holding a currency and owing it at once would match on neither if a loan's balance were compared against a bank's as well.

**Currency only.** A stock, a mutual fund, or any other commodity that is not a currency keeps GnuCash's own revaluation, unchanged. A security is held in units and priced in a currency rather than converted from one; its gain is the price movement GnuCash already reads from the price database, and the book opens no cost basis for it. `unrealized_gains_other` states that gain on its own key and carries it into the unrealized total; `realized_gains_other`, what a disposal of one of them took, is left for later work.

The book records what foreign money cost: the Canadian dollars it took to get it, at the rate of the day it arrived. A balance sheet asks what that money is worth now, at the nearest price.

A cost basis already records what the currency cost. The posting of a 2,720.00 USD invoice has two splits: 2,720.00 USD on the receivable, and 3,791.14 CAD on `Income:Non-farming revenue:Trade sales of goods and services`. Those two splits are one rate — 189557/136000 CAD/USD — and it is the rate the `----- COST BASES` section of the export below prints for that receivable, and the one `fx-balances` prints in its `COST` column.

**One figure per currency, for the whole book.** Never per account: no account line on the page carries a gain of its own, and an account held in Canadian dollars takes no part in it.

Step 7 through it:

| | |
|---|---|
| the book's USD balance | 0.00 USD |
| value, at 1.3865 | 0.00 CAD |
| total USD cost basis balance | 0.00 USD |
| cost | 0.00 CAD |
| **`unrealized_gains_fx`** | **0.00 CAD** |

The dollars are gone, the cost basis that held them is spent to nothing, and the 19.86 they lost is on the income statement. Nothing is unrealized, and the page says so.

### Measured against every cost basis, and against nothing the book spends at home

`tests/fixtures/a_cad_book_that_bought_usd_at_four_rates_and_spends_only_cad.txt` buys 1,000.00 USD at each of 1.20, 1.30, 1.40 and 1.50 — four cost bases, none disposed of — and pays 1,200.00 of rent in Canadian dollars. 5,400.00 for 4,000.00 dollars is an average of exactly 1.35. Drawn at six prices, with `--fx-rates` supplying each:

| priced at | 1.00 | 1.20 | 1.35 | 1.40 | 1.45 | 1.50 |
|---|---|---|---|---|---|---|
| `unrealized_gains_fx` | −1,400.00 | −600.00 | **0.00** | 200.00 | 400.00 | 600.00 |
| `total_assets` | 7,400.00 | 8,200.00 | 8,800.00 | 9,000.00 | 9,200.00 | 9,400.00 |

Every figure is 4,000 × price − 5,400.00, so the gain is measured against the four cost bases added together rather than against any one of them, and it moves in both directions through the rates the dollars were bought at. At 1.35 it is 0.00 — a figure the book has, written because the book holds the money, not an absent one.

`total_assets` is 3,400.00 + 4,000 × price throughout: the rent is in every total and in none of the gains. A figure that counted Canadian movements is what charged 19.86 to `Due from shareholder(s)/director(s)` above, and it would show here.

**`gnucash_balancing_amount` is not compared with either gain, here or anywhere.** It is not a gain, and where it happens to come to the same number that is the book's shape rather than an agreement: every purchase in this one was made with Canadian dollars, so the split values GnuCash subtracts *are* what the currency cost. The book this issue was reported from is the case that matters, and there the dollars arrive in US dollar transactions carrying no Canadian figure at all, so the same subtraction answers something else. A check has to come from a computation that could disagree — which is what GnuCash's own Advanced Portfolio report gives, above.

### Two currencies at once, priced through the Hong Kong peg

Every book above holds one foreign currency, so a figure that added two currencies together, or measured one against another's cost basis, would pass all of them. `tests/fixtures/a_cad_book_earning_cad_usd_and_hkd.txt` cannot be passed that way: it earns Canadian, US and Hong Kong dollars, spends some of each, and is drawn twice.

The Hong Kong dollar is pegged to the US dollar between 7.75 and 7.85, which makes the Canadian figure for it exact at each end of the band with the US dollar at 1.30:

| peg | a Hong Kong dollar, in Canadian dollars |
|---|---|
| 7.80 | 1.30 / 7.80 = **1/6** — what 146,010.00 HKD was earned at |
| 7.75 | 1.30 / 7.75 = **26/155** |
| 7.85 | 1.30 / 7.85 = **26/157** |

Measured, with 600.00 USD costing 780.00 and 99,510.00 HKD costing 16,585.00 still held, at three dates:

| drawn at | US dollar | peg | the working | `unrealized_gains_assets_fx` |
|---|---|---|---|---|
| 2026-09-30 | 1.40 | 7.75 | `99510.00 HKD … at 28/155 worth 17976.00 CAD = 1391.00 CAD` | **1,451.00** |
| | | | `600.00 USD … at 1.4 worth 840.00 CAD = 60.00 CAD` | |
| 2026-11-30 | 1.30 | 7.85 | `99510.00 HKD … at 26/157 worth 16479.36 CAD = -105.64 CAD` | **−105.64** |
| | | | `600.00 USD … at 1.3 worth 780.00 CAD = 0.00 CAD` | |
| 2026-12-31 | 1.30 | 7.75 | `99510.00 HKD … at 26/155 worth 16692.00 CAD = 107.00 CAD` | **+107.00** |
| | | | `600.00 USD … at 1.3 worth 780.00 CAD = 0.00 CAD` | |

**At the first date both currencies have moved**, by different amounts and from different costs — 60.00 on the US dollars and 1,391.00 on the Hong Kong ones — which is the ordinary case and the one a figure that mixed two currencies up could still pass plausibly. 99,510 divides by 155, so that 1,391.00 is exact to the cent rather than rounded.

**At the other two the US dollar is a control, and it stays at 0.00.** The peg moves 0.05 either side of 7.80 and the Hong Kong figure changes sign, while the currency that did not move contributes nothing — which a book of one currency cannot demonstrate. The working states each currency on its own line, and the two add to the key.

The 1.40 price sits at 2026-09-30 so that a sheet drawn at 2026-11-30 still finds the year end's 1.30 nearer, 31 days against 61, leaving the control dates undisturbed by it.

`realized_gains_fx` is 110.00 at both dates: 60.00 on 400.00 USD disposed of at 1.45 against a 1.30 cost, and 50.00 on 46,500.00 HKD disposed of with the peg at 7.75 against the 7.80 it was earned at. Both are exact to the cent — 46,500 divides by 6 and by 155 — so the figures are what they are rather than what rounding left. The 5,000.00 of Canadian consulting and the 900.00 of Canadian rent move the totals and no gain.

### This needs the book's cost bases kept up

A cost basis falls only where a disposal gives its guid. A book that spends foreign currency without giving one keeps a cost basis balance larger than the currency it still holds, and the figure then states a gain on money that is gone.

The example is such a book at steps 2 to 6: the bank spent all 2,720.00 USD through the CAMT import, and its cost basis still reads 2,720.00 because none of those transactions gives one. Step 7 is where it is put right. It is a defect in the book rather than a figure for a statement to price in.

**What shows it is the balance sheet's own working**, where a currency measured from its cost bases states its arithmetic and one left to GnuCash states a commodity and an amount. `fx-balances --verify-costs` does not report it, and finding a great deal else is no help here: its per-currency question compares what a currency's cost bases hold between them against what the ledger says arrived, less what was sold *against a cost basis*, and a disposal that gives no guid is on neither side of that subtraction — so the two sides agree while the money is gone. Measured on the fixture below: no finding, exit 0.

The Q-042 fixture `tests/fixtures/a_cad_book_with_usd_hkd_and_shares_priced_in_its_price_database.txt` is in that state too, and this is measured: `fx-balances` reports 10,000.00 USD of cost basis balance on a book holding 7,480.00 and owing 2,500.00, because its USD sale, share purchase, share sale and loan repayment give no cost basis and its borrowing opened none. A cost read from those cost bases is a cost for 10,000.00 US dollars, on a book that holds 7,480.00 and owes 2,500.00.

### A book whose cost bases are kept up

`tests/fixtures/a_cad_book_that_borrowed_usd_into_its_cad_bank.txt` is one. Measured: `fx-balances` reports 1,000.00 USD at 1.3 CAD/USD against the 1,000.00 USD the loan owes, so the cost basis balance and the book's balance agree. −1,400.00 CAD of value against −1,300.00 CAD of cost gives `unrealized_gains_fx: -100.00 CAD` on 2026-01-25, and 0.00 CAD on the day it was drawn — the figures Q-042 pinned under the single `unrealized_gains` key that this issue divides into the keys above.

- **A key states its figure whenever the book has the thing behind it**, which is Q-042's rule, and the two totals are always stated. A book whose "Use Trading Accounts" option is on states `trading_gains:` and none of these, GnuCash having booked the revaluation into accounts of its own.
- **The realized keys do not enter `total_equity`.** They are inside `retained_earnings` already. Only `total_unrealized_gains` is equity the book has yet to take.
- **The comment block explains the FX keys**, worded without printing any key's own name, so a page can still be asked whether it carries one.
- **A gain is money.** A fraction is for a *price* — a cost basis's cost is a rate, and a rate may be exact, as `share_price:` is. A gain is an amount, and is stated at the smallest unit the commodity divides into, read from the commodity and never two decimal places assumed: a Japanese yen divides into 1, and a Korean won into 100 until GnuCash 5.15. So 1,000.00 USD costing 189557/136000 CAD/USD is carried at 1,393.80, and against the 1,386.50 it is worth the gain is −7.30.

### The realized figure on a page drawn in another currency is left off, and stating it is left for later work

Where the page is not in the currency the costs are recorded in, `realized_gains_fx` and `total_realized_gains` are not stated at all. What they used to do there was worse: a book that realized 100.00 CAD printed `realized_gains_fx: 0.00 USD` when its page was asked for in US dollars — a zero given as a fact about a book that had realized something. Leaving the keys off is what this change does, and it is not closed here.

The shape of the work is worth writing down, because the two cases differ and neither is unmeasurable:

- **A Canadian book drawn in US dollars.** The splits a `$residual$` resolved to carry Canadian values, so the sum is a CAD amount and wants converting at the report's date, through the same exchange function every account line uses. It has to be that function and that date: the gain is already inside `retained_earnings` on the same page, and that total *is* converted. A converted total whose component is missing cannot be reconciled against it, which is the whole use of the key.
- **A book kept in Hong Kong dollars.** Its disposals are stated in Hong Kong dollars, so their split values are too, and the sum is already in the page's own currency. Nothing needs converting — the figure was never unmeasurable, only turned away.

What turns both away is one guard asking `currency == BASE_CURRENCY`, which conflates two questions: whether the figure can be computed, and whether it is in the report's currency. The answer to the first is yes in both cases. Closing this means separating them — compute the figure from the currency it is denominated in, and convert only where that differs from the page's.

### A cost is recorded against a constant, and these tests are mainly Canadian

Nothing here is limited to Canadian books by design. The report currency is read from the book — `the_currency` in `cli/_gnucash_statements.py` resolves `--currency`, then the `company` block's `base_currency:`, then the top-level accounts — and `tests/fixtures/a_book_kept_in_hkd.txt` is drawn in Hong Kong dollars like any other.

What has not been done is the cost side. `BASE_CURRENCY` in `services/foreign_currency.py` is the constant `'CAD'`, so a cost is recorded as Canadian dollars per unit of the currency held, and the guard that decides whether the cost bases are read at all compares the page's currency against that same constant. The books these tests are built on are Canadian, so that path is the one they exercise.

What it costs on a book kept in something else, measured on the Hong Kong book above: every gain key reads 0.00 and the realized keys are left off, while the account lines, the section totals and `retained_earnings` are GnuCash's own and the sheet balances at 37,330.00 HKD on both sides. So the page is not wrong, but it says nothing the cost bases know.

Closing it means recording a cost in the currency the book is kept in and reading it back the same way, and tests on a book that is not Canadian. It is not closed here.

## Tests

- `tests/integration/test_a_sheet_states_realized_and_unrealized_gains_separately.py`: the US dollar invoice collected into a US dollar account, drawn with every dollar still held, with every dollar spent, and with 1,000.00 kept back — the last of these the case the reported example cannot make, and the one that fails if the two gains are ever added into a single figure. Beside it: dollars earned three times and spent out in four payments, so four disposals draw on three cost bases and the first is emptied by the second payment against it; 1,000.00 USD bought and held; 1,000.00 bought at each of four rates with only Canadian dollars spent, drawn at six prices; a book billing in Canadian, US and Hong Kong dollars against the peg; and a sheet drawn between a collection and a later disposal, where a gain realized after the sheet's date must not appear on it. Each book is drawn at more than one price, so a figure that moves with the report price can be told from one that does not. A key's absence is read with `key_of`, never by looking for it in the page.
- `tests/integration/test_the_sheet_shows_how_each_gain_was_worked_out.py`: the working is read back off the page, each group summed and compared with the key above it, on a book of cost bases and a fallback and a security, a book of four disposals against three cost bases, and a book of four cost bases at four rates. `--no-itemize` leaves the keys and takes the working, the income statement carries none of it, and every working line is a comment inside the block. An itemization nobody verifies is only more text.
- `tests/integration/test_a_sheet_is_drawn_on_a_book_whose_cost_bases_cannot_be_read.py`: two books no file can produce — one whose cost basis has no balance recorded, one carrying a cost that will not parse — each drawn as a balance sheet. The page comes out and balances, and that cost basis counts for nothing rather than taking the command down with it.
- `tests/integration/test_the_statements_are_printed_by_customized_gnucash_reports.py`, `test_balance_sheet_account_types.py` and `test_a_rates_file_prices_gnucash_reports_for_the_run_only.py` updated for the new keys: every assertion on `unrealized_gains` becomes one on `unrealized_gains_fx`, `unrealized_gains_other` or `total_unrealized_gains`. The books behind them hold securities whose figures this issue does not change, so what those assertions move to is the key's new name rather than a new figure.
- The book kept in HKD is drawn as a balance sheet by `test_the_statements_are_printed_by_customized_gnucash_reports.py`, which pins the scope limit stated above rather than leaving it assumed.

## Probes

| probe | what it measures |
|---|---|
| `tests/research/how_gnucash_computes_unrealized_gains_probe.py` | the two collectors GnuCash's Balance Sheet subtracts — each account's balance, and the sum of its splits' values held per transaction currency — converted at a price given on the command line, so the figure GnuCash prints can be traced term by term, and at more than one price |
| `tests/research/what_gnucash_computes_as_a_securitys_realized_gain_probe.py` | what GnuCash's own Advanced Portfolio report makes of a disposal this tool wrote, beside what the ledger booked. A disposal valued at what the units cost leaves Money In equal to Money Out, so that report reads Realized Gain 0.00 and counts the gain as Income instead — which is why `realized_gains_other` is specified and not computed |
| `tests/research/whether_gnucash_agrees_on_the_gain_on_shares_still_held_probe.py` | the same report on a book that disposes of nothing and holds no foreign currency, so the shares' figure stands alone. Measured: Basis C$3,120.00, Value C$4,771.20, Unrealized Gain **C$1,651.20** against `unrealized_gains_other: 1651.20 CAD` — two arithmetics sharing no code, one answer |

## User exported info


################################ STEP: 0 — onboarded, accrual set, nothing else
----- TRANSACTIONS
----- COST BASES
(none)
----- INCOME STATEMENT
2026-01-01 income-statement
	# Every figure is GnuCash's own, from its Balance Sheet or Income
	# Statement report. An account line states what that account itself
	# holds — a parent's line is its own balance, not its children's.
	# A section's total, and any figure no account holds, is a key.
	#
	# share_price: and value: under an account line are what the report
	# valued that holding at on this date: the price read from the book's
	# price database, and what GnuCash converted the holding to. They are
	# not the keys of the same name on a transaction split, which record
	# the rate a transaction actually happened at and multiply out exactly.
	# A price here changes with the date and with the book's prices; a
	# split's does not change at all.
	end: "2026-12-31"
	currency.mnemonic: "CAD"
	total_revenue: 0.00 CAD
	total_expenses: 0.00 CAD
	net_income: 0.00 CAD
----- BALANCE SHEET
2026-12-31 balance-sheet
	# Every figure is GnuCash's own, from its Balance Sheet or Income
	# Statement report. An account line states what that account itself
	# holds — a parent's line is its own balance, not its children's.
	# A section's total, and any figure no account holds, is a key.
	#
	# share_price: and value: under an account line are what the report
	# valued that holding at on this date: the price read from the book's
	# price database, and what GnuCash converted the holding to. They are
	# not the keys of the same name on a transaction split, which record
	# the rate a transaction actually happened at and multiply out exactly.
	# A price here changes with the date and with the book's prices; a
	# split's does not change at all.
	currency.mnemonic: "CAD"
	total_assets: 0.00 CAD
	total_liabilities: 0.00 CAD
	total_equity: 0.00 CAD
	total_liabilities_and_equity: 0.00 CAD
################################ end 0 — onboarded, accrual set, nothing else

################################ STEP: 1 — USD invoice posted, BEFORE the CAMT import
----- TRANSACTIONS
2026-08-13 commodity USD
	mnemonic: "USD"
	fullname: "US Dollar"
	namespace: "CURRENCY"
	fraction: 100
2026-08-13 commodity CAD
	mnemonic: "CAD"
	fullname: "Canadian Dollar"
	namespace: "CURRENCY"
	fraction: 100
2026-08-13 open Assets
	guid: "<guid>"
	type: "Asset"
	placeholder: #True
	description: ""
	tax_related: #False
	commodity.namespace: "CURRENCY"
	commodity.mnemonic: "CAD"
2026-08-13 open Assets:Current assets
	guid: "<guid>"
	type: "Asset"
	placeholder: #True
	description: ""
	tax_related: #False
	commodity.namespace: "CURRENCY"
	commodity.mnemonic: "CAD"
2026-08-13 open Assets:Current assets:Accounts receivable
	guid: "<guid>"
	type: "A/Receivable"
	placeholder: #False
	description: "claims, dividends, royalties, and subsidies receivable"
	tax_related: #False
	commodity.namespace: "CURRENCY"
	commodity.mnemonic: "CAD"
2026-08-13 open Assets:Current assets:Accounts receivable:USD
	guid: "<guid>"
	type: "A/Receivable"
	placeholder: #False
	description: "Accounts receivable denominated in USD"
	tax_related: #False
	commodity.namespace: "CURRENCY"
	commodity.mnemonic: "USD"
2026-08-13 open Income
	guid: "<guid>"
	type: "Income"
	placeholder: #True
	description: ""
	tax_related: #False
	commodity.namespace: "CURRENCY"
	commodity.mnemonic: "CAD"
2026-08-13 open Income:Non-farming revenue
	guid: "<guid>"
	type: "Income"
	placeholder: #True
	description: ""
	tax_related: #False
	commodity.namespace: "CURRENCY"
	commodity.mnemonic: "CAD"
2026-08-13 open Income:Non-farming revenue:Trade sales of goods and services
	guid: "<guid>"
	type: "Income"
	placeholder: #False
	description: "For corporations or partnerships who are not involved in the resource industry (items 8040 to 8053) or the fishing industry (items 8160 to 8166), but whose main source of income is the sale of a product or service. Amounts may be reported net of discounts allowed on sales, sales rebates, volume discounts, returns, and allowances."
	tax_related: #False
	commodity.namespace: "CURRENCY"
	commodity.mnemonic: "CAD"
2026-08-13 * "USD-INV-<id>" "Invoice USD-INV-<id>"
	guid: "<guid>"
	currency.mnemonic: "USD"
	txn_type: I
	owner: customer:CUST-USD-INV-<id>
	business_generated: "true"
	Assets:Current assets:Accounts receivable:USD 2720.00 USD
		guid: "<guid>"
		action: "Invoice"
		memo:"Invoice USD-INV-<id>"
		cost_basis_balance: "2720.00"
	Income:Non-farming revenue:Trade sales of goods and services -3791.14 CAD
		guid: "<guid>"
		account.commodity.mnemonic: "CAD"
		share_price: "272000/379114"
		value: "-2720.00"
		action: "Invoice"
		memo:"Invoice USD-INV-<id>"
----- COST BASES
	Assets:Current assets:Accounts receivable:USD acquired 2,720.00 USD balance 2,720.00 USD cost 189557/136000 CAD/USD on 2026-08-13
----- INCOME STATEMENT
2026-01-01 income-statement
	# Every figure is GnuCash's own, from its Balance Sheet or Income
	# Statement report. An account line states what that account itself
	# holds — a parent's line is its own balance, not its children's.
	# A section's total, and any figure no account holds, is a key.
	#
	# share_price: and value: under an account line are what the report
	# valued that holding at on this date: the price read from the book's
	# price database, and what GnuCash converted the holding to. They are
	# not the keys of the same name on a transaction split, which record
	# the rate a transaction actually happened at and multiply out exactly.
	# A price here changes with the date and with the book's prices; a
	# split's does not change at all.
	end: "2026-12-31"
	currency.mnemonic: "CAD"
	Income:Non-farming revenue:Trade sales of goods and services 3791.14 CAD
	total_revenue: 3791.14 CAD
	total_expenses: 0.00 CAD
	net_income: 3791.14 CAD
----- BALANCE SHEET
2026-12-31 balance-sheet
	# Every figure is GnuCash's own, from its Balance Sheet or Income
	# Statement report. An account line states what that account itself
	# holds — a parent's line is its own balance, not its children's.
	# A section's total, and any figure no account holds, is a key.
	#
	# share_price: and value: under an account line are what the report
	# valued that holding at on this date: the price read from the book's
	# price database, and what GnuCash converted the holding to. They are
	# not the keys of the same name on a transaction split, which record
	# the rate a transaction actually happened at and multiply out exactly.
	# A price here changes with the date and with the book's prices; a
	# split's does not change at all.
	currency.mnemonic: "CAD"
	Assets:Current assets:Accounts receivable:USD 2720.00 USD
		account.commodity.mnemonic: "USD"
		share_price: "1.3938"
		value: "3791.14"
	total_assets: 3791.14 CAD
	total_liabilities: 0.00 CAD
	retained_earnings: 3791.14 CAD
	total_equity: 3791.14 CAD
	total_liabilities_and_equity: 3791.14 CAD
################################ end 1 — USD invoice posted, BEFORE the CAMT import

################################ STEP: 2 — AFTER the CAMT import
----- TRANSACTIONS
2026-08-13 commodity USD
	mnemonic: "USD"
	fullname: "US Dollar"
	namespace: "CURRENCY"
	fraction: 100
2026-08-13 commodity CAD
	mnemonic: "CAD"
	fullname: "Canadian Dollar"
	namespace: "CURRENCY"
	fraction: 100
2026-08-13 open Assets
	guid: "<guid>"
	type: "Asset"
	placeholder: #True
	description: ""
	tax_related: #False
	commodity.namespace: "CURRENCY"
	commodity.mnemonic: "CAD"
2026-08-13 open Assets:Current assets
	guid: "<guid>"
	type: "Asset"
	placeholder: #True
	description: ""
	tax_related: #False
	commodity.namespace: "CURRENCY"
	commodity.mnemonic: "CAD"
2026-08-13 open Assets:Current assets:Cash and deposits
	guid: "<guid>"
	type: "Asset"
	placeholder: #False
	description: "Include all amounts under items 1001 to 1007."
	tax_related: #False
	commodity.namespace: "CURRENCY"
	commodity.mnemonic: "CAD"
2026-08-13 open Assets:Current assets:Cash and deposits:Deposits in Canadian banks and institutions – Foreign currency
	guid: "<guid>"
	type: "Asset"
	placeholder: #False
	description: ""
	tax_related: #False
	commodity.namespace: "CURRENCY"
	commodity.mnemonic: "CAD"
2026-08-13 open Assets:Current assets:Cash and deposits:Deposits in Canadian banks and institutions – Foreign currency:Wise Payments Canada Inc. Chequing 170710882080137
	guid: "<guid>"
	type: "Asset"
	placeholder: #False
	description: ""
	tax_related: #False
	commodity.namespace: "CURRENCY"
	commodity.mnemonic: "USD"
2026-08-13 open Assets:Current assets:Due from shareholder(s)/director(s)
	guid: "<guid>"
	type: "Asset"
	placeholder: #False
	description: "Include all amounts here that would have otherwise been reported under items 1301 to 1303."
	tax_related: #False
	commodity.namespace: "CURRENCY"
	commodity.mnemonic: "CAD"
2026-08-13 open Assets:Current assets:Accounts receivable
	guid: "<guid>"
	type: "A/Receivable"
	placeholder: #False
	description: "claims, dividends, royalties, and subsidies receivable"
	tax_related: #False
	commodity.namespace: "CURRENCY"
	commodity.mnemonic: "CAD"
2026-08-13 open Assets:Current assets:Accounts receivable:USD
	guid: "<guid>"
	type: "A/Receivable"
	placeholder: #False
	description: "Accounts receivable denominated in USD"
	tax_related: #False
	commodity.namespace: "CURRENCY"
	commodity.mnemonic: "USD"
2026-08-13 open Income
	guid: "<guid>"
	type: "Income"
	placeholder: #True
	description: ""
	tax_related: #False
	commodity.namespace: "CURRENCY"
	commodity.mnemonic: "CAD"
2026-08-13 open Income:Non-farming revenue
	guid: "<guid>"
	type: "Income"
	placeholder: #True
	description: ""
	tax_related: #False
	commodity.namespace: "CURRENCY"
	commodity.mnemonic: "CAD"
2026-08-13 open Income:Non-farming revenue:Trade sales of goods and services
	guid: "<guid>"
	type: "Income"
	placeholder: #False
	description: "For corporations or partnerships who are not involved in the resource industry (items 8040 to 8053) or the fishing industry (items 8160 to 8166), but whose main source of income is the sale of a product or service. Amounts may be reported net of discounts allowed on sales, sales rebates, volume discounts, returns, and allowances."
	tax_related: #False
	commodity.namespace: "CURRENCY"
	commodity.mnemonic: "CAD"
2026-08-13 * "Received money from REDACTED PAYER with reference 091000014286964 | Received money from REDACTED PAYER with reference 091000014286964"
	guid: "<guid>"
	currency.mnemonic: "USD"
	doc_link: "juneworks:ofx:Wise Payments Canada Inc.:170710882080137:TRANSFER-2308077507"
	gnucash.tx.imported_at: "<ts>"
	gnucash.tx.updated_at: "<ts>"
	Assets:Current assets:Cash and deposits:Deposits in Canadian banks and institutions – Foreign currency:Wise Payments Canada Inc. Chequing 170710882080137 2720.00 USD
		guid: "<guid>"
		cost_basis_balance: "2720.00"
	Assets:Current assets:Due from shareholder(s)/director(s) -3791.14 CAD
		guid: "<guid>"
		account.commodity.mnemonic: "CAD"
		share_price: "272000/379114"
		value: "-2720.00"
2026-08-13 * "Wise Charges for: TRANSFER-2308077507 | Wise Charges for: TRANSFER-2308077507"
	guid: "<guid>"
	currency.mnemonic: "USD"
	doc_link: "juneworks:ofx:Wise Payments Canada Inc.:170710882080137:FEE-TRANSFER-2308077507"
	gnucash.tx.imported_at: "<ts>"
	gnucash.tx.updated_at: "<ts>"
	Assets:Current assets:Due from shareholder(s)/director(s) 1.00 CAD
		guid: "<guid>"
		account.commodity.mnemonic: "CAD"
		share_price: "0.72"
		value: "0.72"
	Assets:Current assets:Cash and deposits:Deposits in Canadian banks and institutions – Foreign currency:Wise Payments Canada Inc. Chequing 170710882080137 -0.72 USD
		guid: "<guid>"
2026-08-13 * "USD-INV-<id>" "Invoice USD-INV-<id>"
	guid: "<guid>"
	currency.mnemonic: "USD"
	txn_type: I
	owner: customer:CUST-USD-INV-<id>
	business_generated: "true"
	Assets:Current assets:Accounts receivable:USD 2720.00 USD
		guid: "<guid>"
		action: "Invoice"
		memo:"Invoice USD-INV-<id>"
		cost_basis_balance: "2720.00"
	Income:Non-farming revenue:Trade sales of goods and services -3791.14 CAD
		guid: "<guid>"
		account.commodity.mnemonic: "CAD"
		share_price: "272000/379114"
		value: "-2720.00"
		action: "Invoice"
		memo:"Invoice USD-INV-<id>"
2026-08-17 * "REDACTED PAYEE | Sent money to REDACTED PAYEE (fee: 8.60 USD)"
	guid: "<guid>"
	currency.mnemonic: "USD"
	doc_link: "juneworks:ofx:Wise Payments Canada Inc.:170710882080137:TRANSFER-2316634310"
	gnucash.tx.imported_at: "<ts>"
	gnucash.tx.updated_at: "<ts>"
	Assets:Current assets:Due from shareholder(s)/director(s) 3758.36 CAD
		guid: "<guid>"
		account.commodity.mnemonic: "CAD"
		share_price: "271068/375836"
		value: "2710.68"
	Assets:Current assets:Cash and deposits:Deposits in Canadian banks and institutions – Foreign currency:Wise Payments Canada Inc. Chequing 170710882080137 -2710.68 USD
		guid: "<guid>"
2026-08-17 * "Wise | Wise Charges for: TRANSFER-2316634310"
	guid: "<guid>"
	currency.mnemonic: "USD"
	doc_link: "juneworks:ofx:Wise Payments Canada Inc.:170710882080137:FEE-TRANSFER-2316634310"
	gnucash.tx.imported_at: "<ts>"
	gnucash.tx.updated_at: "<ts>"
	Assets:Current assets:Due from shareholder(s)/director(s) 11.92 CAD
		guid: "<guid>"
		account.commodity.mnemonic: "CAD"
		share_price: "860/1192"
		value: "8.60"
	Assets:Current assets:Cash and deposits:Deposits in Canadian banks and institutions – Foreign currency:Wise Payments Canada Inc. Chequing 170710882080137 -8.60 USD
		guid: "<guid>"
----- COST BASES
	Assets:Current assets:Cash and deposits:Deposits in Canadian banks and institutions – Foreign currency:Wise Payments Canada Inc. Chequing 170710882080137 acquired 2,720.00 USD balance 2,720.00 USD cost 189557/136000 CAD/USD on 2026-08-13
	Assets:Current assets:Accounts receivable:USD acquired 2,720.00 USD balance 2,720.00 USD cost 189557/136000 CAD/USD on 2026-08-13
----- INCOME STATEMENT
2026-01-01 income-statement
	# Every figure is GnuCash's own, from its Balance Sheet or Income
	# Statement report. An account line states what that account itself
	# holds — a parent's line is its own balance, not its children's.
	# A section's total, and any figure no account holds, is a key.
	#
	# share_price: and value: under an account line are what the report
	# valued that holding at on this date: the price read from the book's
	# price database, and what GnuCash converted the holding to. They are
	# not the keys of the same name on a transaction split, which record
	# the rate a transaction actually happened at and multiply out exactly.
	# A price here changes with the date and with the book's prices; a
	# split's does not change at all.
	end: "2026-12-31"
	currency.mnemonic: "CAD"
	Income:Non-farming revenue:Trade sales of goods and services 3791.14 CAD
	total_revenue: 3791.14 CAD
	total_expenses: 0.00 CAD
	net_income: 3791.14 CAD
----- BALANCE SHEET
2026-12-31 balance-sheet
	# Every figure is GnuCash's own, from its Balance Sheet or Income
	# Statement report. An account line states what that account itself
	# holds — a parent's line is its own balance, not its children's.
	# A section's total, and any figure no account holds, is a key.
	#
	# share_price: and value: under an account line are what the report
	# valued that holding at on this date: the price read from the book's
	# price database, and what GnuCash converted the holding to. They are
	# not the keys of the same name on a transaction split, which record
	# the rate a transaction actually happened at and multiply out exactly.
	# A price here changes with the date and with the book's prices; a
	# split's does not change at all.
	currency.mnemonic: "CAD"
	Assets:Current assets:Accounts receivable:USD 2720.00 USD
		account.commodity.mnemonic: "USD"
		share_price: "1.3865"
		value: "3771.28"
	Assets:Current assets:Due from shareholder(s)/director(s) -19.86 CAD
	total_assets: 3751.42 CAD
	total_liabilities: 0.00 CAD
	retained_earnings: 3791.14 CAD
	unrealized_gains: -19.86 CAD
	total_equity: 3771.28 CAD
	total_liabilities_and_equity: 3771.28 CAD
################################ end 2 — AFTER the CAMT import

################################ STEP: 3 — BEFORE the link
----- TRANSACTIONS
2026-08-13 commodity USD
	mnemonic: "USD"
	fullname: "US Dollar"
	namespace: "CURRENCY"
	fraction: 100
2026-08-13 commodity CAD
	mnemonic: "CAD"
	fullname: "Canadian Dollar"
	namespace: "CURRENCY"
	fraction: 100
2026-08-13 open Assets
	guid: "<guid>"
	type: "Asset"
	placeholder: #True
	description: ""
	tax_related: #False
	commodity.namespace: "CURRENCY"
	commodity.mnemonic: "CAD"
2026-08-13 open Assets:Current assets
	guid: "<guid>"
	type: "Asset"
	placeholder: #True
	description: ""
	tax_related: #False
	commodity.namespace: "CURRENCY"
	commodity.mnemonic: "CAD"
2026-08-13 open Assets:Current assets:Cash and deposits
	guid: "<guid>"
	type: "Asset"
	placeholder: #False
	description: "Include all amounts under items 1001 to 1007."
	tax_related: #False
	commodity.namespace: "CURRENCY"
	commodity.mnemonic: "CAD"
2026-08-13 open Assets:Current assets:Cash and deposits:Deposits in Canadian banks and institutions – Foreign currency
	guid: "<guid>"
	type: "Asset"
	placeholder: #False
	description: ""
	tax_related: #False
	commodity.namespace: "CURRENCY"
	commodity.mnemonic: "CAD"
2026-08-13 open Assets:Current assets:Cash and deposits:Deposits in Canadian banks and institutions – Foreign currency:Wise Payments Canada Inc. Chequing 170710882080137
	guid: "<guid>"
	type: "Asset"
	placeholder: #False
	description: ""
	tax_related: #False
	commodity.namespace: "CURRENCY"
	commodity.mnemonic: "USD"
2026-08-13 open Assets:Current assets:Due from shareholder(s)/director(s)
	guid: "<guid>"
	type: "Asset"
	placeholder: #False
	description: "Include all amounts here that would have otherwise been reported under items 1301 to 1303."
	tax_related: #False
	commodity.namespace: "CURRENCY"
	commodity.mnemonic: "CAD"
2026-08-13 open Assets:Current assets:Accounts receivable
	guid: "<guid>"
	type: "A/Receivable"
	placeholder: #False
	description: "claims, dividends, royalties, and subsidies receivable"
	tax_related: #False
	commodity.namespace: "CURRENCY"
	commodity.mnemonic: "CAD"
2026-08-13 open Assets:Current assets:Accounts receivable:USD
	guid: "<guid>"
	type: "A/Receivable"
	placeholder: #False
	description: "Accounts receivable denominated in USD"
	tax_related: #False
	commodity.namespace: "CURRENCY"
	commodity.mnemonic: "USD"
2026-08-13 open Income
	guid: "<guid>"
	type: "Income"
	placeholder: #True
	description: ""
	tax_related: #False
	commodity.namespace: "CURRENCY"
	commodity.mnemonic: "CAD"
2026-08-13 open Income:Non-farming revenue
	guid: "<guid>"
	type: "Income"
	placeholder: #True
	description: ""
	tax_related: #False
	commodity.namespace: "CURRENCY"
	commodity.mnemonic: "CAD"
2026-08-13 open Income:Non-farming revenue:Trade sales of goods and services
	guid: "<guid>"
	type: "Income"
	placeholder: #False
	description: "For corporations or partnerships who are not involved in the resource industry (items 8040 to 8053) or the fishing industry (items 8160 to 8166), but whose main source of income is the sale of a product or service. Amounts may be reported net of discounts allowed on sales, sales rebates, volume discounts, returns, and allowances."
	tax_related: #False
	commodity.namespace: "CURRENCY"
	commodity.mnemonic: "CAD"
2026-08-13 * "Received money from REDACTED PAYER with reference 091000014286964 | Received money from REDACTED PAYER with reference 091000014286964"
	guid: "<guid>"
	currency.mnemonic: "USD"
	doc_link: "juneworks:ofx:Wise Payments Canada Inc.:170710882080137:TRANSFER-2308077507"
	gnucash.tx.imported_at: "<ts>"
	gnucash.tx.updated_at: "<ts>"
	Assets:Current assets:Cash and deposits:Deposits in Canadian banks and institutions – Foreign currency:Wise Payments Canada Inc. Chequing 170710882080137 2720.00 USD
		guid: "<guid>"
		cost_basis_balance: "2720.00"
	Assets:Current assets:Due from shareholder(s)/director(s) -3791.14 CAD
		guid: "<guid>"
		account.commodity.mnemonic: "CAD"
		share_price: "272000/379114"
		value: "-2720.00"
2026-08-13 * "Wise Charges for: TRANSFER-2308077507 | Wise Charges for: TRANSFER-2308077507"
	guid: "<guid>"
	currency.mnemonic: "USD"
	doc_link: "juneworks:ofx:Wise Payments Canada Inc.:170710882080137:FEE-TRANSFER-2308077507"
	gnucash.tx.imported_at: "<ts>"
	gnucash.tx.updated_at: "<ts>"
	Assets:Current assets:Due from shareholder(s)/director(s) 1.00 CAD
		guid: "<guid>"
		account.commodity.mnemonic: "CAD"
		share_price: "0.72"
		value: "0.72"
	Assets:Current assets:Cash and deposits:Deposits in Canadian banks and institutions – Foreign currency:Wise Payments Canada Inc. Chequing 170710882080137 -0.72 USD
		guid: "<guid>"
2026-08-13 * "USD-INV-<id>" "Invoice USD-INV-<id>"
	guid: "<guid>"
	currency.mnemonic: "USD"
	txn_type: I
	owner: customer:CUST-USD-INV-<id>
	business_generated: "true"
	Assets:Current assets:Accounts receivable:USD 2720.00 USD
		guid: "<guid>"
		action: "Invoice"
		memo:"Invoice USD-INV-<id>"
		cost_basis_balance: "2720.00"
	Income:Non-farming revenue:Trade sales of goods and services -3791.14 CAD
		guid: "<guid>"
		account.commodity.mnemonic: "CAD"
		share_price: "272000/379114"
		value: "-2720.00"
		action: "Invoice"
		memo:"Invoice USD-INV-<id>"
2026-08-17 * "REDACTED PAYEE | Sent money to REDACTED PAYEE (fee: 8.60 USD)"
	guid: "<guid>"
	currency.mnemonic: "USD"
	doc_link: "juneworks:ofx:Wise Payments Canada Inc.:170710882080137:TRANSFER-2316634310"
	gnucash.tx.imported_at: "<ts>"
	gnucash.tx.updated_at: "<ts>"
	Assets:Current assets:Due from shareholder(s)/director(s) 3758.36 CAD
		guid: "<guid>"
		account.commodity.mnemonic: "CAD"
		share_price: "271068/375836"
		value: "2710.68"
	Assets:Current assets:Cash and deposits:Deposits in Canadian banks and institutions – Foreign currency:Wise Payments Canada Inc. Chequing 170710882080137 -2710.68 USD
		guid: "<guid>"
2026-08-17 * "Wise | Wise Charges for: TRANSFER-2316634310"
	guid: "<guid>"
	currency.mnemonic: "USD"
	doc_link: "juneworks:ofx:Wise Payments Canada Inc.:170710882080137:FEE-TRANSFER-2316634310"
	gnucash.tx.imported_at: "<ts>"
	gnucash.tx.updated_at: "<ts>"
	Assets:Current assets:Due from shareholder(s)/director(s) 11.92 CAD
		guid: "<guid>"
		account.commodity.mnemonic: "CAD"
		share_price: "860/1192"
		value: "8.60"
	Assets:Current assets:Cash and deposits:Deposits in Canadian banks and institutions – Foreign currency:Wise Payments Canada Inc. Chequing 170710882080137 -8.60 USD
		guid: "<guid>"
----- COST BASES
	Assets:Current assets:Cash and deposits:Deposits in Canadian banks and institutions – Foreign currency:Wise Payments Canada Inc. Chequing 170710882080137 acquired 2,720.00 USD balance 2,720.00 USD cost 189557/136000 CAD/USD on 2026-08-13
	Assets:Current assets:Accounts receivable:USD acquired 2,720.00 USD balance 2,720.00 USD cost 189557/136000 CAD/USD on 2026-08-13
----- INCOME STATEMENT
2026-01-01 income-statement
	# Every figure is GnuCash's own, from its Balance Sheet or Income
	# Statement report. An account line states what that account itself
	# holds — a parent's line is its own balance, not its children's.
	# A section's total, and any figure no account holds, is a key.
	#
	# share_price: and value: under an account line are what the report
	# valued that holding at on this date: the price read from the book's
	# price database, and what GnuCash converted the holding to. They are
	# not the keys of the same name on a transaction split, which record
	# the rate a transaction actually happened at and multiply out exactly.
	# A price here changes with the date and with the book's prices; a
	# split's does not change at all.
	end: "2026-12-31"
	currency.mnemonic: "CAD"
	Income:Non-farming revenue:Trade sales of goods and services 3791.14 CAD
	total_revenue: 3791.14 CAD
	total_expenses: 0.00 CAD
	net_income: 3791.14 CAD
----- BALANCE SHEET
2026-12-31 balance-sheet
	# Every figure is GnuCash's own, from its Balance Sheet or Income
	# Statement report. An account line states what that account itself
	# holds — a parent's line is its own balance, not its children's.
	# A section's total, and any figure no account holds, is a key.
	#
	# share_price: and value: under an account line are what the report
	# valued that holding at on this date: the price read from the book's
	# price database, and what GnuCash converted the holding to. They are
	# not the keys of the same name on a transaction split, which record
	# the rate a transaction actually happened at and multiply out exactly.
	# A price here changes with the date and with the book's prices; a
	# split's does not change at all.
	currency.mnemonic: "CAD"
	Assets:Current assets:Accounts receivable:USD 2720.00 USD
		account.commodity.mnemonic: "USD"
		share_price: "1.3865"
		value: "3771.28"
	Assets:Current assets:Due from shareholder(s)/director(s) -19.86 CAD
	total_assets: 3751.42 CAD
	total_liabilities: 0.00 CAD
	retained_earnings: 3791.14 CAD
	unrealized_gains: -19.86 CAD
	total_equity: 3771.28 CAD
	total_liabilities_and_equity: 3771.28 CAD
################################ end 3 — BEFORE the link

################################ STEP: 4 — AFTER the link (deposit pays the invoice)
----- TRANSACTIONS
2026-08-13 commodity USD
	mnemonic: "USD"
	fullname: "US Dollar"
	namespace: "CURRENCY"
	fraction: 100
2026-08-13 commodity CAD
	mnemonic: "CAD"
	fullname: "Canadian Dollar"
	namespace: "CURRENCY"
	fraction: 100
2026-08-13 open Assets
	guid: "<guid>"
	type: "Asset"
	placeholder: #True
	description: ""
	tax_related: #False
	commodity.namespace: "CURRENCY"
	commodity.mnemonic: "CAD"
2026-08-13 open Assets:Current assets
	guid: "<guid>"
	type: "Asset"
	placeholder: #True
	description: ""
	tax_related: #False
	commodity.namespace: "CURRENCY"
	commodity.mnemonic: "CAD"
2026-08-13 open Assets:Current assets:Cash and deposits
	guid: "<guid>"
	type: "Asset"
	placeholder: #False
	description: "Include all amounts under items 1001 to 1007."
	tax_related: #False
	commodity.namespace: "CURRENCY"
	commodity.mnemonic: "CAD"
2026-08-13 open Assets:Current assets:Cash and deposits:Deposits in Canadian banks and institutions – Foreign currency
	guid: "<guid>"
	type: "Asset"
	placeholder: #False
	description: ""
	tax_related: #False
	commodity.namespace: "CURRENCY"
	commodity.mnemonic: "CAD"
2026-08-13 open Assets:Current assets:Cash and deposits:Deposits in Canadian banks and institutions – Foreign currency:Wise Payments Canada Inc. Chequing 170710882080137
	guid: "<guid>"
	type: "Asset"
	placeholder: #False
	description: ""
	tax_related: #False
	commodity.namespace: "CURRENCY"
	commodity.mnemonic: "USD"
2026-08-13 open Assets:Current assets:Accounts receivable
	guid: "<guid>"
	type: "A/Receivable"
	placeholder: #False
	description: "claims, dividends, royalties, and subsidies receivable"
	tax_related: #False
	commodity.namespace: "CURRENCY"
	commodity.mnemonic: "CAD"
2026-08-13 open Assets:Current assets:Accounts receivable:USD
	guid: "<guid>"
	type: "A/Receivable"
	placeholder: #False
	description: "Accounts receivable denominated in USD"
	tax_related: #False
	commodity.namespace: "CURRENCY"
	commodity.mnemonic: "USD"
2026-08-13 open Assets:Current assets:Due from shareholder(s)/director(s)
	guid: "<guid>"
	type: "Asset"
	placeholder: #False
	description: "Include all amounts here that would have otherwise been reported under items 1301 to 1303."
	tax_related: #False
	commodity.namespace: "CURRENCY"
	commodity.mnemonic: "CAD"
2026-08-13 open Income
	guid: "<guid>"
	type: "Income"
	placeholder: #True
	description: ""
	tax_related: #False
	commodity.namespace: "CURRENCY"
	commodity.mnemonic: "CAD"
2026-08-13 open Income:Non-farming revenue
	guid: "<guid>"
	type: "Income"
	placeholder: #True
	description: ""
	tax_related: #False
	commodity.namespace: "CURRENCY"
	commodity.mnemonic: "CAD"
2026-08-13 open Income:Non-farming revenue:Trade sales of goods and services
	guid: "<guid>"
	type: "Income"
	placeholder: #False
	description: "For corporations or partnerships who are not involved in the resource industry (items 8040 to 8053) or the fishing industry (items 8160 to 8166), but whose main source of income is the sale of a product or service. Amounts may be reported net of discounts allowed on sales, sales rebates, volume discounts, returns, and allowances."
	tax_related: #False
	commodity.namespace: "CURRENCY"
	commodity.mnemonic: "CAD"
2026-08-13 * "Received money from REDACTED PAYER with reference 091000014286964 | Received money from REDACTED PAYER with reference 091000014286964"
	guid: "<guid>"
	doc_link: "juneworks:ofx:Wise Payments Canada Inc.:170710882080137:TRANSFER-2308077507"
	txn_type: P
	owner: customer:CUST-USD-INV-<id>
	gnucash.tx.imported_at: "<ts>"
	gnucash.tx.updated_at: "<ts>"
	Assets:Current assets:Cash and deposits:Deposits in Canadian banks and institutions – Foreign currency:Wise Payments Canada Inc. Chequing 170710882080137 2720.00 USD
		guid: "<guid>"
	Assets:Current assets:Accounts receivable:USD -2720.00 USD
		guid: "<guid>"
2026-08-13 * "Wise Charges for: TRANSFER-2308077507 | Wise Charges for: TRANSFER-2308077507"
	guid: "<guid>"
	currency.mnemonic: "USD"
	doc_link: "juneworks:ofx:Wise Payments Canada Inc.:170710882080137:FEE-TRANSFER-2308077507"
	gnucash.tx.imported_at: "<ts>"
	gnucash.tx.updated_at: "<ts>"
	Assets:Current assets:Due from shareholder(s)/director(s) 1.00 CAD
		guid: "<guid>"
		account.commodity.mnemonic: "CAD"
		share_price: "0.72"
		value: "0.72"
	Assets:Current assets:Cash and deposits:Deposits in Canadian banks and institutions – Foreign currency:Wise Payments Canada Inc. Chequing 170710882080137 -0.72 USD
		guid: "<guid>"
2026-08-13 * "USD-INV-<id>" "Invoice USD-INV-<id>"
	guid: "<guid>"
	currency.mnemonic: "USD"
	txn_type: I
	owner: customer:CUST-USD-INV-<id>
	business_generated: "true"
	Assets:Current assets:Accounts receivable:USD 2720.00 USD
		guid: "<guid>"
		action: "Invoice"
		memo:"Invoice USD-INV-<id>"
		cost_basis_balance: "2720.00"
	Income:Non-farming revenue:Trade sales of goods and services -3791.14 CAD
		guid: "<guid>"
		account.commodity.mnemonic: "CAD"
		share_price: "272000/379114"
		value: "-2720.00"
		action: "Invoice"
		memo:"Invoice USD-INV-<id>"
2026-08-17 * "REDACTED PAYEE | Sent money to REDACTED PAYEE (fee: 8.60 USD)"
	guid: "<guid>"
	currency.mnemonic: "USD"
	doc_link: "juneworks:ofx:Wise Payments Canada Inc.:170710882080137:TRANSFER-2316634310"
	gnucash.tx.imported_at: "<ts>"
	gnucash.tx.updated_at: "<ts>"
	Assets:Current assets:Due from shareholder(s)/director(s) 3758.36 CAD
		guid: "<guid>"
		account.commodity.mnemonic: "CAD"
		share_price: "271068/375836"
		value: "2710.68"
	Assets:Current assets:Cash and deposits:Deposits in Canadian banks and institutions – Foreign currency:Wise Payments Canada Inc. Chequing 170710882080137 -2710.68 USD
		guid: "<guid>"
2026-08-17 * "Wise | Wise Charges for: TRANSFER-2316634310"
	guid: "<guid>"
	currency.mnemonic: "USD"
	doc_link: "juneworks:ofx:Wise Payments Canada Inc.:170710882080137:FEE-TRANSFER-2316634310"
	gnucash.tx.imported_at: "<ts>"
	gnucash.tx.updated_at: "<ts>"
	Assets:Current assets:Due from shareholder(s)/director(s) 11.92 CAD
		guid: "<guid>"
		account.commodity.mnemonic: "CAD"
		share_price: "860/1192"
		value: "8.60"
	Assets:Current assets:Cash and deposits:Deposits in Canadian banks and institutions – Foreign currency:Wise Payments Canada Inc. Chequing 170710882080137 -8.60 USD
		guid: "<guid>"
----- COST BASES
	Assets:Current assets:Accounts receivable:USD acquired 2,720.00 USD balance 2,720.00 USD cost 189557/136000 CAD/USD on 2026-08-13
----- INCOME STATEMENT
2026-01-01 income-statement
	# Every figure is GnuCash's own, from its Balance Sheet or Income
	# Statement report. An account line states what that account itself
	# holds — a parent's line is its own balance, not its children's.
	# A section's total, and any figure no account holds, is a key.
	#
	# share_price: and value: under an account line are what the report
	# valued that holding at on this date: the price read from the book's
	# price database, and what GnuCash converted the holding to. They are
	# not the keys of the same name on a transaction split, which record
	# the rate a transaction actually happened at and multiply out exactly.
	# A price here changes with the date and with the book's prices; a
	# split's does not change at all.
	end: "2026-12-31"
	currency.mnemonic: "CAD"
	Income:Non-farming revenue:Trade sales of goods and services 3791.14 CAD
	total_revenue: 3791.14 CAD
	total_expenses: 0.00 CAD
	net_income: 3791.14 CAD
----- BALANCE SHEET
2026-12-31 balance-sheet
	# Every figure is GnuCash's own, from its Balance Sheet or Income
	# Statement report. An account line states what that account itself
	# holds — a parent's line is its own balance, not its children's.
	# A section's total, and any figure no account holds, is a key.
	#
	# share_price: and value: under an account line are what the report
	# valued that holding at on this date: the price read from the book's
	# price database, and what GnuCash converted the holding to. They are
	# not the keys of the same name on a transaction split, which record
	# the rate a transaction actually happened at and multiply out exactly.
	# A price here changes with the date and with the book's prices; a
	# split's does not change at all.
	currency.mnemonic: "CAD"
	Assets:Current assets:Due from shareholder(s)/director(s) 3771.28 CAD
	total_assets: 3771.28 CAD
	total_liabilities: 0.00 CAD
	retained_earnings: 3791.14 CAD
	unrealized_gains: 0.00 CAD
	total_equity: 3791.14 CAD
	total_liabilities_and_equity: 3791.14 CAD
################################ end 4 — AFTER the link (deposit pays the invoice)

################################ STEP: 5 — AFTER the unlink
----- TRANSACTIONS
2026-08-13 commodity USD
	mnemonic: "USD"
	fullname: "US Dollar"
	namespace: "CURRENCY"
	fraction: 100
2026-08-13 commodity CAD
	mnemonic: "CAD"
	fullname: "Canadian Dollar"
	namespace: "CURRENCY"
	fraction: 100
2026-08-13 open Assets
	guid: "<guid>"
	type: "Asset"
	placeholder: #True
	description: ""
	tax_related: #False
	commodity.namespace: "CURRENCY"
	commodity.mnemonic: "CAD"
2026-08-13 open Assets:Current assets
	guid: "<guid>"
	type: "Asset"
	placeholder: #True
	description: ""
	tax_related: #False
	commodity.namespace: "CURRENCY"
	commodity.mnemonic: "CAD"
2026-08-13 open Assets:Current assets:Cash and deposits
	guid: "<guid>"
	type: "Asset"
	placeholder: #False
	description: "Include all amounts under items 1001 to 1007."
	tax_related: #False
	commodity.namespace: "CURRENCY"
	commodity.mnemonic: "CAD"
2026-08-13 open Assets:Current assets:Cash and deposits:Deposits in Canadian banks and institutions – Foreign currency
	guid: "<guid>"
	type: "Asset"
	placeholder: #False
	description: ""
	tax_related: #False
	commodity.namespace: "CURRENCY"
	commodity.mnemonic: "CAD"
2026-08-13 open Assets:Current assets:Cash and deposits:Deposits in Canadian banks and institutions – Foreign currency:Wise Payments Canada Inc. Chequing 170710882080137
	guid: "<guid>"
	type: "Asset"
	placeholder: #False
	description: ""
	tax_related: #False
	commodity.namespace: "CURRENCY"
	commodity.mnemonic: "USD"
2026-08-13 open Assets:Current assets:Due from shareholder(s)/director(s)
	guid: "<guid>"
	type: "Asset"
	placeholder: #False
	description: "Include all amounts here that would have otherwise been reported under items 1301 to 1303."
	tax_related: #False
	commodity.namespace: "CURRENCY"
	commodity.mnemonic: "CAD"
2026-08-13 open Assets:Current assets:Accounts receivable
	guid: "<guid>"
	type: "A/Receivable"
	placeholder: #False
	description: "claims, dividends, royalties, and subsidies receivable"
	tax_related: #False
	commodity.namespace: "CURRENCY"
	commodity.mnemonic: "CAD"
2026-08-13 open Assets:Current assets:Accounts receivable:USD
	guid: "<guid>"
	type: "A/Receivable"
	placeholder: #False
	description: "Accounts receivable denominated in USD"
	tax_related: #False
	commodity.namespace: "CURRENCY"
	commodity.mnemonic: "USD"
2026-08-13 open Income
	guid: "<guid>"
	type: "Income"
	placeholder: #True
	description: ""
	tax_related: #False
	commodity.namespace: "CURRENCY"
	commodity.mnemonic: "CAD"
2026-08-13 open Income:Non-farming revenue
	guid: "<guid>"
	type: "Income"
	placeholder: #True
	description: ""
	tax_related: #False
	commodity.namespace: "CURRENCY"
	commodity.mnemonic: "CAD"
2026-08-13 open Income:Non-farming revenue:Trade sales of goods and services
	guid: "<guid>"
	type: "Income"
	placeholder: #False
	description: "For corporations or partnerships who are not involved in the resource industry (items 8040 to 8053) or the fishing industry (items 8160 to 8166), but whose main source of income is the sale of a product or service. Amounts may be reported net of discounts allowed on sales, sales rebates, volume discounts, returns, and allowances."
	tax_related: #False
	commodity.namespace: "CURRENCY"
	commodity.mnemonic: "CAD"
2026-08-13 * "Received money from REDACTED PAYER with reference 091000014286964 | Received money from REDACTED PAYER with reference 091000014286964"
	guid: "<guid>"
	currency.mnemonic: "USD"
	doc_link: "juneworks:ofx:Wise Payments Canada Inc.:170710882080137:TRANSFER-2308077507"
	gnucash.tx.imported_at: "<ts>"
	gnucash.tx.updated_at: "<ts>"
	Assets:Current assets:Cash and deposits:Deposits in Canadian banks and institutions – Foreign currency:Wise Payments Canada Inc. Chequing 170710882080137 2720.00 USD
		guid: "<guid>"
		cost_basis_balance: "2720.00"
	Assets:Current assets:Due from shareholder(s)/director(s) -3791.14 CAD
		guid: "<guid>"
		account.commodity.mnemonic: "CAD"
		share_price: "272000/379114"
		value: "-2720.00"
2026-08-13 * "Wise Charges for: TRANSFER-2308077507 | Wise Charges for: TRANSFER-2308077507"
	guid: "<guid>"
	currency.mnemonic: "USD"
	doc_link: "juneworks:ofx:Wise Payments Canada Inc.:170710882080137:FEE-TRANSFER-2308077507"
	gnucash.tx.imported_at: "<ts>"
	gnucash.tx.updated_at: "<ts>"
	Assets:Current assets:Due from shareholder(s)/director(s) 1.00 CAD
		guid: "<guid>"
		account.commodity.mnemonic: "CAD"
		share_price: "0.72"
		value: "0.72"
	Assets:Current assets:Cash and deposits:Deposits in Canadian banks and institutions – Foreign currency:Wise Payments Canada Inc. Chequing 170710882080137 -0.72 USD
		guid: "<guid>"
2026-08-13 * "USD-INV-<id>" "Invoice USD-INV-<id>"
	guid: "<guid>"
	currency.mnemonic: "USD"
	txn_type: I
	owner: customer:CUST-USD-INV-<id>
	business_generated: "true"
	Assets:Current assets:Accounts receivable:USD 2720.00 USD
		guid: "<guid>"
		action: "Invoice"
		memo:"Invoice USD-INV-<id>"
		cost_basis_balance: "2720.00"
	Income:Non-farming revenue:Trade sales of goods and services -3791.14 CAD
		guid: "<guid>"
		account.commodity.mnemonic: "CAD"
		share_price: "272000/379114"
		value: "-2720.00"
		action: "Invoice"
		memo:"Invoice USD-INV-<id>"
2026-08-17 * "REDACTED PAYEE | Sent money to REDACTED PAYEE (fee: 8.60 USD)"
	guid: "<guid>"
	currency.mnemonic: "USD"
	doc_link: "juneworks:ofx:Wise Payments Canada Inc.:170710882080137:TRANSFER-2316634310"
	gnucash.tx.imported_at: "<ts>"
	gnucash.tx.updated_at: "<ts>"
	Assets:Current assets:Due from shareholder(s)/director(s) 3758.36 CAD
		guid: "<guid>"
		account.commodity.mnemonic: "CAD"
		share_price: "271068/375836"
		value: "2710.68"
	Assets:Current assets:Cash and deposits:Deposits in Canadian banks and institutions – Foreign currency:Wise Payments Canada Inc. Chequing 170710882080137 -2710.68 USD
		guid: "<guid>"
2026-08-17 * "Wise | Wise Charges for: TRANSFER-2316634310"
	guid: "<guid>"
	currency.mnemonic: "USD"
	doc_link: "juneworks:ofx:Wise Payments Canada Inc.:170710882080137:FEE-TRANSFER-2316634310"
	gnucash.tx.imported_at: "<ts>"
	gnucash.tx.updated_at: "<ts>"
	Assets:Current assets:Due from shareholder(s)/director(s) 11.92 CAD
		guid: "<guid>"
		account.commodity.mnemonic: "CAD"
		share_price: "860/1192"
		value: "8.60"
	Assets:Current assets:Cash and deposits:Deposits in Canadian banks and institutions – Foreign currency:Wise Payments Canada Inc. Chequing 170710882080137 -8.60 USD
		guid: "<guid>"
----- COST BASES
	Assets:Current assets:Cash and deposits:Deposits in Canadian banks and institutions – Foreign currency:Wise Payments Canada Inc. Chequing 170710882080137 acquired 2,720.00 USD balance 2,720.00 USD cost 189557/136000 CAD/USD on 2026-08-13
	Assets:Current assets:Accounts receivable:USD acquired 2,720.00 USD balance 2,720.00 USD cost 189557/136000 CAD/USD on 2026-08-13
----- INCOME STATEMENT
2026-01-01 income-statement
	# Every figure is GnuCash's own, from its Balance Sheet or Income
	# Statement report. An account line states what that account itself
	# holds — a parent's line is its own balance, not its children's.
	# A section's total, and any figure no account holds, is a key.
	#
	# share_price: and value: under an account line are what the report
	# valued that holding at on this date: the price read from the book's
	# price database, and what GnuCash converted the holding to. They are
	# not the keys of the same name on a transaction split, which record
	# the rate a transaction actually happened at and multiply out exactly.
	# A price here changes with the date and with the book's prices; a
	# split's does not change at all.
	end: "2026-12-31"
	currency.mnemonic: "CAD"
	Income:Non-farming revenue:Trade sales of goods and services 3791.14 CAD
	total_revenue: 3791.14 CAD
	total_expenses: 0.00 CAD
	net_income: 3791.14 CAD
----- BALANCE SHEET
2026-12-31 balance-sheet
	# Every figure is GnuCash's own, from its Balance Sheet or Income
	# Statement report. An account line states what that account itself
	# holds — a parent's line is its own balance, not its children's.
	# A section's total, and any figure no account holds, is a key.
	#
	# share_price: and value: under an account line are what the report
	# valued that holding at on this date: the price read from the book's
	# price database, and what GnuCash converted the holding to. They are
	# not the keys of the same name on a transaction split, which record
	# the rate a transaction actually happened at and multiply out exactly.
	# A price here changes with the date and with the book's prices; a
	# split's does not change at all.
	currency.mnemonic: "CAD"
	Assets:Current assets:Accounts receivable:USD 2720.00 USD
		account.commodity.mnemonic: "USD"
		share_price: "1.3865"
		value: "3771.28"
	Assets:Current assets:Due from shareholder(s)/director(s) -19.86 CAD
	total_assets: 3751.42 CAD
	total_liabilities: 0.00 CAD
	retained_earnings: 3791.14 CAD
	unrealized_gains: -19.86 CAD
	total_equity: 3771.28 CAD
	total_liabilities_and_equity: 3771.28 CAD
################################ end 5 — AFTER the unlink

################################ STEP: 6 — AFTER the second link
----- TRANSACTIONS
2026-08-13 commodity USD
	mnemonic: "USD"
	fullname: "US Dollar"
	namespace: "CURRENCY"
	fraction: 100
2026-08-13 commodity CAD
	mnemonic: "CAD"
	fullname: "Canadian Dollar"
	namespace: "CURRENCY"
	fraction: 100
2026-08-13 open Assets
	guid: "<guid>"
	type: "Asset"
	placeholder: #True
	description: ""
	tax_related: #False
	commodity.namespace: "CURRENCY"
	commodity.mnemonic: "CAD"
2026-08-13 open Assets:Current assets
	guid: "<guid>"
	type: "Asset"
	placeholder: #True
	description: ""
	tax_related: #False
	commodity.namespace: "CURRENCY"
	commodity.mnemonic: "CAD"
2026-08-13 open Assets:Current assets:Cash and deposits
	guid: "<guid>"
	type: "Asset"
	placeholder: #False
	description: "Include all amounts under items 1001 to 1007."
	tax_related: #False
	commodity.namespace: "CURRENCY"
	commodity.mnemonic: "CAD"
2026-08-13 open Assets:Current assets:Cash and deposits:Deposits in Canadian banks and institutions – Foreign currency
	guid: "<guid>"
	type: "Asset"
	placeholder: #False
	description: ""
	tax_related: #False
	commodity.namespace: "CURRENCY"
	commodity.mnemonic: "CAD"
2026-08-13 open Assets:Current assets:Cash and deposits:Deposits in Canadian banks and institutions – Foreign currency:Wise Payments Canada Inc. Chequing 170710882080137
	guid: "<guid>"
	type: "Asset"
	placeholder: #False
	description: ""
	tax_related: #False
	commodity.namespace: "CURRENCY"
	commodity.mnemonic: "USD"
2026-08-13 open Assets:Current assets:Accounts receivable
	guid: "<guid>"
	type: "A/Receivable"
	placeholder: #False
	description: "claims, dividends, royalties, and subsidies receivable"
	tax_related: #False
	commodity.namespace: "CURRENCY"
	commodity.mnemonic: "CAD"
2026-08-13 open Assets:Current assets:Accounts receivable:USD
	guid: "<guid>"
	type: "A/Receivable"
	placeholder: #False
	description: "Accounts receivable denominated in USD"
	tax_related: #False
	commodity.namespace: "CURRENCY"
	commodity.mnemonic: "USD"
2026-08-13 open Assets:Current assets:Due from shareholder(s)/director(s)
	guid: "<guid>"
	type: "Asset"
	placeholder: #False
	description: "Include all amounts here that would have otherwise been reported under items 1301 to 1303."
	tax_related: #False
	commodity.namespace: "CURRENCY"
	commodity.mnemonic: "CAD"
2026-08-13 open Income
	guid: "<guid>"
	type: "Income"
	placeholder: #True
	description: ""
	tax_related: #False
	commodity.namespace: "CURRENCY"
	commodity.mnemonic: "CAD"
2026-08-13 open Income:Non-farming revenue
	guid: "<guid>"
	type: "Income"
	placeholder: #True
	description: ""
	tax_related: #False
	commodity.namespace: "CURRENCY"
	commodity.mnemonic: "CAD"
2026-08-13 open Income:Non-farming revenue:Trade sales of goods and services
	guid: "<guid>"
	type: "Income"
	placeholder: #False
	description: "For corporations or partnerships who are not involved in the resource industry (items 8040 to 8053) or the fishing industry (items 8160 to 8166), but whose main source of income is the sale of a product or service. Amounts may be reported net of discounts allowed on sales, sales rebates, volume discounts, returns, and allowances."
	tax_related: #False
	commodity.namespace: "CURRENCY"
	commodity.mnemonic: "CAD"
2026-08-13 * "Received money from REDACTED PAYER with reference 091000014286964 | Received money from REDACTED PAYER with reference 091000014286964"
	guid: "<guid>"
	doc_link: "juneworks:ofx:Wise Payments Canada Inc.:170710882080137:TRANSFER-2308077507"
	txn_type: P
	owner: customer:CUST-USD-INV-<id>
	gnucash.tx.imported_at: "<ts>"
	gnucash.tx.updated_at: "<ts>"
	Assets:Current assets:Cash and deposits:Deposits in Canadian banks and institutions – Foreign currency:Wise Payments Canada Inc. Chequing 170710882080137 2720.00 USD
		guid: "<guid>"
	Assets:Current assets:Accounts receivable:USD -2720.00 USD
		guid: "<guid>"
2026-08-13 * "Wise Charges for: TRANSFER-2308077507 | Wise Charges for: TRANSFER-2308077507"
	guid: "<guid>"
	currency.mnemonic: "USD"
	doc_link: "juneworks:ofx:Wise Payments Canada Inc.:170710882080137:FEE-TRANSFER-2308077507"
	gnucash.tx.imported_at: "<ts>"
	gnucash.tx.updated_at: "<ts>"
	Assets:Current assets:Due from shareholder(s)/director(s) 1.00 CAD
		guid: "<guid>"
		account.commodity.mnemonic: "CAD"
		share_price: "0.72"
		value: "0.72"
	Assets:Current assets:Cash and deposits:Deposits in Canadian banks and institutions – Foreign currency:Wise Payments Canada Inc. Chequing 170710882080137 -0.72 USD
		guid: "<guid>"
2026-08-13 * "USD-INV-<id>" "Invoice USD-INV-<id>"
	guid: "<guid>"
	currency.mnemonic: "USD"
	txn_type: I
	owner: customer:CUST-USD-INV-<id>
	business_generated: "true"
	Assets:Current assets:Accounts receivable:USD 2720.00 USD
		guid: "<guid>"
		action: "Invoice"
		memo:"Invoice USD-INV-<id>"
		cost_basis_balance: "2720.00"
	Income:Non-farming revenue:Trade sales of goods and services -3791.14 CAD
		guid: "<guid>"
		account.commodity.mnemonic: "CAD"
		share_price: "272000/379114"
		value: "-2720.00"
		action: "Invoice"
		memo:"Invoice USD-INV-<id>"
2026-08-17 * "REDACTED PAYEE | Sent money to REDACTED PAYEE (fee: 8.60 USD)"
	guid: "<guid>"
	currency.mnemonic: "USD"
	doc_link: "juneworks:ofx:Wise Payments Canada Inc.:170710882080137:TRANSFER-2316634310"
	gnucash.tx.imported_at: "<ts>"
	gnucash.tx.updated_at: "<ts>"
	Assets:Current assets:Due from shareholder(s)/director(s) 3758.36 CAD
		guid: "<guid>"
		account.commodity.mnemonic: "CAD"
		share_price: "271068/375836"
		value: "2710.68"
	Assets:Current assets:Cash and deposits:Deposits in Canadian banks and institutions – Foreign currency:Wise Payments Canada Inc. Chequing 170710882080137 -2710.68 USD
		guid: "<guid>"
2026-08-17 * "Wise | Wise Charges for: TRANSFER-2316634310"
	guid: "<guid>"
	currency.mnemonic: "USD"
	doc_link: "juneworks:ofx:Wise Payments Canada Inc.:170710882080137:FEE-TRANSFER-2316634310"
	gnucash.tx.imported_at: "<ts>"
	gnucash.tx.updated_at: "<ts>"
	Assets:Current assets:Due from shareholder(s)/director(s) 11.92 CAD
		guid: "<guid>"
		account.commodity.mnemonic: "CAD"
		share_price: "860/1192"
		value: "8.60"
	Assets:Current assets:Cash and deposits:Deposits in Canadian banks and institutions – Foreign currency:Wise Payments Canada Inc. Chequing 170710882080137 -8.60 USD
		guid: "<guid>"
----- COST BASES
	Assets:Current assets:Accounts receivable:USD acquired 2,720.00 USD balance 2,720.00 USD cost 189557/136000 CAD/USD on 2026-08-13
----- INCOME STATEMENT
2026-01-01 income-statement
	# Every figure is GnuCash's own, from its Balance Sheet or Income
	# Statement report. An account line states what that account itself
	# holds — a parent's line is its own balance, not its children's.
	# A section's total, and any figure no account holds, is a key.
	#
	# share_price: and value: under an account line are what the report
	# valued that holding at on this date: the price read from the book's
	# price database, and what GnuCash converted the holding to. They are
	# not the keys of the same name on a transaction split, which record
	# the rate a transaction actually happened at and multiply out exactly.
	# A price here changes with the date and with the book's prices; a
	# split's does not change at all.
	end: "2026-12-31"
	currency.mnemonic: "CAD"
	Income:Non-farming revenue:Trade sales of goods and services 3791.14 CAD
	total_revenue: 3791.14 CAD
	total_expenses: 0.00 CAD
	net_income: 3791.14 CAD
----- BALANCE SHEET
2026-12-31 balance-sheet
	# Every figure is GnuCash's own, from its Balance Sheet or Income
	# Statement report. An account line states what that account itself
	# holds — a parent's line is its own balance, not its children's.
	# A section's total, and any figure no account holds, is a key.
	#
	# share_price: and value: under an account line are what the report
	# valued that holding at on this date: the price read from the book's
	# price database, and what GnuCash converted the holding to. They are
	# not the keys of the same name on a transaction split, which record
	# the rate a transaction actually happened at and multiply out exactly.
	# A price here changes with the date and with the book's prices; a
	# split's does not change at all.
	currency.mnemonic: "CAD"
	Assets:Current assets:Due from shareholder(s)/director(s) 3771.28 CAD
	total_assets: 3771.28 CAD
	total_liabilities: 0.00 CAD
	retained_earnings: 3791.14 CAD
	unrealized_gains: 0.00 CAD
	total_equity: 3791.14 CAD
	total_liabilities_and_equity: 3791.14 CAD
################################ end 6 — AFTER the second link

################################ STEP: 7 — AFTER classifying the fees and the distribution
----- TRANSACTIONS
2026-08-13 commodity USD
	mnemonic: "USD"
	fullname: "US Dollar"
	namespace: "CURRENCY"
	fraction: 100
2026-08-13 commodity CAD
	mnemonic: "CAD"
	fullname: "Canadian Dollar"
	namespace: "CURRENCY"
	fraction: 100
2026-08-13 open Assets
	guid: "<guid>"
	type: "Asset"
	placeholder: #True
	description: ""
	tax_related: #False
	commodity.namespace: "CURRENCY"
	commodity.mnemonic: "CAD"
2026-08-13 open Assets:Current assets
	guid: "<guid>"
	type: "Asset"
	placeholder: #True
	description: ""
	tax_related: #False
	commodity.namespace: "CURRENCY"
	commodity.mnemonic: "CAD"
2026-08-13 open Assets:Current assets:Cash and deposits
	guid: "<guid>"
	type: "Asset"
	placeholder: #False
	description: "Include all amounts under items 1001 to 1007."
	tax_related: #False
	commodity.namespace: "CURRENCY"
	commodity.mnemonic: "CAD"
2026-08-13 open Assets:Current assets:Cash and deposits:Deposits in Canadian banks and institutions – Foreign currency
	guid: "<guid>"
	type: "Asset"
	placeholder: #False
	description: ""
	tax_related: #False
	commodity.namespace: "CURRENCY"
	commodity.mnemonic: "CAD"
2026-08-13 open Assets:Current assets:Cash and deposits:Deposits in Canadian banks and institutions – Foreign currency:Wise Payments Canada Inc. Chequing 170710882080137
	guid: "<guid>"
	type: "Asset"
	placeholder: #False
	description: ""
	tax_related: #False
	commodity.namespace: "CURRENCY"
	commodity.mnemonic: "USD"
2026-08-13 open Assets:Current assets:Accounts receivable
	guid: "<guid>"
	type: "A/Receivable"
	placeholder: #False
	description: "claims, dividends, royalties, and subsidies receivable"
	tax_related: #False
	commodity.namespace: "CURRENCY"
	commodity.mnemonic: "CAD"
2026-08-13 open Assets:Current assets:Accounts receivable:USD
	guid: "<guid>"
	type: "A/Receivable"
	placeholder: #False
	description: "Accounts receivable denominated in USD"
	tax_related: #False
	commodity.namespace: "CURRENCY"
	commodity.mnemonic: "USD"
2026-08-13 open Expenses
	guid: "<guid>"
	type: "Expense"
	placeholder: #True
	description: ""
	tax_related: #False
	commodity.namespace: "CURRENCY"
	commodity.mnemonic: "CAD"
2026-08-13 open Expenses:Non-farming expenses – Operating expenses
	guid: "<guid>"
	type: "Expense"
	placeholder: #True
	description: ""
	tax_related: #False
	commodity.namespace: "CURRENCY"
	commodity.mnemonic: "CAD"
2026-08-13 open Expenses:Non-farming expenses – Operating expenses:Bank charges
	guid: "<guid>"
	type: "Expense"
	placeholder: #False
	description: ""
	tax_related: #False
	commodity.namespace: "CURRENCY"
	commodity.mnemonic: "CAD"
2026-08-13 open Income
	guid: "<guid>"
	type: "Income"
	placeholder: #True
	description: ""
	tax_related: #False
	commodity.namespace: "CURRENCY"
	commodity.mnemonic: "CAD"
2026-08-13 open Income:Non-farming revenue
	guid: "<guid>"
	type: "Income"
	placeholder: #True
	description: ""
	tax_related: #False
	commodity.namespace: "CURRENCY"
	commodity.mnemonic: "CAD"
2026-08-13 open Income:Non-farming revenue:Trade sales of goods and services
	guid: "<guid>"
	type: "Income"
	placeholder: #False
	description: "For corporations or partnerships who are not involved in the resource industry (items 8040 to 8053) or the fishing industry (items 8160 to 8166), but whose main source of income is the sale of a product or service. Amounts may be reported net of discounts allowed on sales, sales rebates, volume discounts, returns, and allowances."
	tax_related: #False
	commodity.namespace: "CURRENCY"
	commodity.mnemonic: "CAD"
2026-08-17 open Equity
	guid: "<guid>"
	type: "Equity"
	placeholder: #True
	description: ""
	tax_related: #False
	commodity.namespace: "CURRENCY"
	commodity.mnemonic: "CAD"
2026-08-17 open Equity:Equity
	guid: "<guid>"
	type: "Equity"
	placeholder: #True
	description: ""
	tax_related: #False
	commodity.namespace: "CURRENCY"
	commodity.mnemonic: "CAD"
2026-08-17 open Equity:Equity:Retained earnings/deficit
	guid: "<guid>"
	type: "Equity"
	placeholder: #False
	description: ""
	tax_related: #False
	commodity.namespace: "CURRENCY"
	commodity.mnemonic: "CAD"
2026-08-17 open Income:Non-farming revenue:Foreign exchange gains/losses
	guid: "<guid>"
	type: "Income"
	placeholder: #False
	description: "amortization of deferred exchange gains and losses and realized gains and losses on foreign currency"
	tax_related: #False
	commodity.namespace: "CURRENCY"
	commodity.mnemonic: "CAD"
2026-08-13 * "Received money from REDACTED PAYER with reference 091000014286964 | Received money from REDACTED PAYER with reference 091000014286964"
	guid: "<guid>"
	doc_link: "juneworks:ofx:Wise Payments Canada Inc.:170710882080137:TRANSFER-2308077507"
	txn_type: P
	owner: customer:CUST-USD-INV-<id>
	gnucash.tx.imported_at: "<ts>"
	gnucash.tx.updated_at: "<ts>"
	Assets:Current assets:Cash and deposits:Deposits in Canadian banks and institutions – Foreign currency:Wise Payments Canada Inc. Chequing 170710882080137 2720.00 USD
		guid: "<guid>"
	Assets:Current assets:Accounts receivable:USD -2720.00 USD
		guid: "<guid>"
2026-08-13 * "USD-INV-<id>" "Invoice USD-INV-<id>"
	guid: "<guid>"
	currency.mnemonic: "USD"
	txn_type: I
	owner: customer:CUST-USD-INV-<id>
	business_generated: "true"
	Assets:Current assets:Accounts receivable:USD 2720.00 USD
		guid: "<guid>"
		action: "Invoice"
		memo:"Invoice USD-INV-<id>"
		cost_basis_balance: "0.00"
	Income:Non-farming revenue:Trade sales of goods and services -3791.14 CAD
		guid: "<guid>"
		account.commodity.mnemonic: "CAD"
		share_price: "272000/379114"
		value: "-2720.00"
		action: "Invoice"
		memo:"Invoice USD-INV-<id>"
2026-08-13 * "Wise Charges for: TRANSFER-2308077507 | Wise Charges for: TRANSFER-2308077507"
	guid: "<guid>"
	currency.mnemonic: "CAD"
	doc_link: "juneworks:ofx:Wise Payments Canada Inc.:170710882080137:FEE-TRANSFER-2308077507"
	gnucash.tx.imported_at: "<ts>"
	gnucash.tx.updated_at: "<ts>"
	Expenses:Non-farming expenses – Operating expenses:Bank charges 1.00 CAD
		guid: "<guid>"
	Assets:Current assets:Cash and deposits:Deposits in Canadian banks and institutions – Foreign currency:Wise Payments Canada Inc. Chequing 170710882080137 -0.72 USD
		guid: "<guid>"
		account.commodity.mnemonic: "USD"
		share_price: "100/72"
		value: "-1.00"
		cost_basis_split_guid: "<guid>"
2026-08-17 * "REDACTED PAYEE | Sent money to REDACTED PAYEE (fee: 8.60 USD)"
	guid: "<guid>"
	currency.mnemonic: "CAD"
	doc_link: "juneworks:ofx:Wise Payments Canada Inc.:170710882080137:TRANSFER-2316634310"
	gnucash.tx.imported_at: "<ts>"
	gnucash.tx.updated_at: "<ts>"
	Equity:Equity:Retained earnings/deficit 3758.36 CAD
		guid: "<guid>"
	Income:Non-farming revenue:Foreign exchange gains/losses 19.79 CAD
		guid: "<guid>"
	Assets:Current assets:Cash and deposits:Deposits in Canadian banks and institutions – Foreign currency:Wise Payments Canada Inc. Chequing 170710882080137 -2710.68 USD
		guid: "<guid>"
		account.commodity.mnemonic: "USD"
		share_price: "377815/271068"
		value: "-3778.15"
		cost_basis_split_guid: "<guid>"
2026-08-17 * "Wise | Wise Charges for: TRANSFER-2316634310"
	guid: "<guid>"
	currency.mnemonic: "CAD"
	doc_link: "juneworks:ofx:Wise Payments Canada Inc.:170710882080137:FEE-TRANSFER-2316634310"
	gnucash.tx.imported_at: "<ts>"
	gnucash.tx.updated_at: "<ts>"
	Expenses:Non-farming expenses – Operating expenses:Bank charges 11.92 CAD
		guid: "<guid>"
	Income:Non-farming revenue:Foreign exchange gains/losses 0.07 CAD
		guid: "<guid>"
	Assets:Current assets:Cash and deposits:Deposits in Canadian banks and institutions – Foreign currency:Wise Payments Canada Inc. Chequing 170710882080137 -8.60 USD
		guid: "<guid>"
		account.commodity.mnemonic: "USD"
		share_price: "1199/860"
		value: "-11.99"
		cost_basis_split_guid: "<guid>"
----- COST BASES
	Assets:Current assets:Accounts receivable:USD acquired 2,720.00 USD balance 0.00 USD cost 189557/136000 CAD/USD on 2026-08-13
----- INCOME STATEMENT
2026-01-01 income-statement
	# Every figure is GnuCash's own, from its Balance Sheet or Income
	# Statement report. An account line states what that account itself
	# holds — a parent's line is its own balance, not its children's.
	# A section's total, and any figure no account holds, is a key.
	#
	# share_price: and value: under an account line are what the report
	# valued that holding at on this date: the price read from the book's
	# price database, and what GnuCash converted the holding to. They are
	# not the keys of the same name on a transaction split, which record
	# the rate a transaction actually happened at and multiply out exactly.
	# A price here changes with the date and with the book's prices; a
	# split's does not change at all.
	end: "2026-12-31"
	currency.mnemonic: "CAD"
	Income:Non-farming revenue:Trade sales of goods and services 3791.14 CAD
	Income:Non-farming revenue:Foreign exchange gains/losses -19.86 CAD
	total_revenue: 3771.28 CAD
	Expenses:Non-farming expenses – Operating expenses:Bank charges 12.92 CAD
	total_expenses: 12.92 CAD
	net_income: 3758.36 CAD
----- BALANCE SHEET
2026-12-31 balance-sheet
	# Every figure is GnuCash's own, from its Balance Sheet or Income
	# Statement report. An account line states what that account itself
	# holds — a parent's line is its own balance, not its children's.
	# A section's total, and any figure no account holds, is a key.
	#
	# share_price: and value: under an account line are what the report
	# valued that holding at on this date: the price read from the book's
	# price database, and what GnuCash converted the holding to. They are
	# not the keys of the same name on a transaction split, which record
	# the rate a transaction actually happened at and multiply out exactly.
	# A price here changes with the date and with the book's prices; a
	# split's does not change at all.
	currency.mnemonic: "CAD"
	total_assets: 0.00 CAD
	total_liabilities: 0.00 CAD
	Equity:Equity:Retained earnings/deficit -3758.36 CAD
	retained_earnings: 3758.36 CAD
	unrealized_gains: 19.86 CAD
	total_equity: 19.86 CAD
	total_liabilities_and_equity: 19.86 CAD
################################ end 7 — AFTER classifying the fees and the distribution
