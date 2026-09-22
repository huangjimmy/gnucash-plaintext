# Q-042 — Print the balance sheet and income statement as plaintext through a customized GnuCash report, in the currency the book is kept in

Every figure below was measured by running GnuCash itself. The report figures were measured on all eleven supported builds — 3.4, 3.8, 4.4, 4.8, 4.13, 5.5, 5.10, 5.13, 5.14, 5.15 and 5.16. Where a row gives fewer builds, those are the builds it was measured on.

## What it should do

A multi-currency book needs a balance sheet and an income statement a reader can trust, in the book's own currency.

- `balance-sheet`, `income-statement` and `report` print the statements as a plaintext block, through a customized GnuCash report: GnuCash's Balance Sheet and Income Statement reports, written to output this project's own format rather than a text rendering of their HTML page. GnuCash runs the report, adds up every figure, and converts it through the book's price database at the report's own price source. A user can be confident that no figure on the page is calculated by gnucash-plaintext.
- The statements are in the currency the book is kept in: a book kept in HKD is printed in HK$, with its USD and CAD converted into HKD by GnuCash.
- `--output-format html` and `pdf` give the page of GnuCash's Balance Sheet or Income Statement report as GnuCash ships it.
- A rates file or a prices file gives prices for one run, and GnuCash's report prices from them. A rate may be exact, as a fraction.

## The page it should print

The page is a plaintext block, the format this tool reads and writes everywhere else — not a text rendering of GnuCash's HTML page. A dated directive opens the block, and everything else is indented under it with tabs.

### The shape

```
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
	Assets:USD Bank 7480.00 USD
		account.commodity.mnemonic: "USD"
		share_price: "1.42"
		value: "10621.60"
	total_assets: 38532.80 CAD
	retained_earnings: 12679.60 CAD
```

The comment lines are written by the report itself, so a reader meeting a block has the distinction in front of them; `#`, `;` and `;;` all open a comment, and anything reading the block passes over them.

- **The directive** is the date the block is as of, then which statement it is: `balance-sheet` or `income-statement`. A balance sheet's date is the date it is drawn at; an income statement's is the day its period starts, and its `end:` key gives the day it ends, because a period needs both. ISO, always, because `qof-print-date` follows the locale of whoever ran the command (CLAUDE.md finding 15).
- **An account is a line**: its full path, its amount, its commodity — and the line is what that account **itself** holds, which is what GnuCash's own page reports. Measured on 5.10, a brokerage holding 3,000.00 USD with a share account under it prints `Brokerage $3,000.00 C$4,200.00` and `AMZN 10 AMZN C$3,640.00`, with `Total Assets C$21,340.00` a row of its own. Reading a parent's *recursive* balance onto its line instead — which this page did first — printed `Assets:Brokerage 7840.00 CAD`, a figure on no row of GnuCash's page, and lost both the US dollars the account holds and the price they were valued at; where the book priced nothing, the same line read `0.00 CAD` for real money. There are no section headings, because the path on every line already says which section it is in.
- **A section's total is a key**, since no account holds it: `total_assets`, `total_liabilities` and `total_equity` on the balance sheet, and `total_revenue` and `total_expenses` on the income statement. `total_equity` comes after the retained earnings, the trading gains and the gain figures, and includes the retained earnings, the trading gains and the unrealized total, as GnuCash's `Total Equity` row does. Q-043 divided the one gain figure into the realized and unrealized, FX and non-FX items, and the realized figures are stated beside the others and added into nothing — they are inside `retained_earnings` already. A section with no accounts still states its total, as GnuCash prints `Total Liabilities C$0.00`. There is no trading section on the income statement: GnuCash's own selects income and expense accounts and nothing else (`(list ACCT-TYPE-INCOME ACCT-TYPE-EXPENSE)` in `income-statement.scm` on 3.8 and 5.10), so a book's trading gains reach the reader through the balance sheet's `trading_gains` key.
- **Every account in the book is listed**, however deep. GnuCash's statements default `Accounts / Levels of Subaccounts` to 3 and fold anything deeper into its parent: measured on 5.10, a book whose `Assets:Bank:Chequing` holds 300.00 CAD with 700.00 in `Assets:Bank:Chequing:Payroll` prints one row, `Chequing C$1,000.00`, and no `Payroll` row. On a column page that is a reading convenience; in a block it is an account that does not appear, beside a line stating its child's money as its own. The block sets the depth to the tree's own.
- **An account holding something other than the block's currency** states three keys under it: `account.commodity.mnemonic:`, `share_price:` where the book prices it in the block's currency, and `value:`. They are read against `currency.mnemonic:` at the top of the block: `share_price: "1.42"` on a USD account in a CAD block is 1.42 CAD per USD, and `value: "10621.60"` is in CAD.
- **They are not a split's keys of the same name, and do not promise what those promise.** On a split, `share_price:` and `value:` are recorded together by whoever entered the transaction, and `value` is `share_price × amount` exactly. On a statement line the two come from different places: `share_price:` is the price the report read from the price database, written exactly — `2/11`, `50/71`, `37/30` — and `value:` is what GnuCash converted the holding to, at the currency's smallest unit, inside `gnc_pricedb_convert_balance_*`. So the product need not close: 19,840.00 CAD at `50/71` is 992000/71, and the page states `13971.83`. A split says what a transaction happened at, and never changes; a statement line says what the holding was valued at on a date, and states a different price as the date or the price database moves.
- **A figure no account holds** is a key of the block — the section totals above, and `retained_earnings`, `trading_gains`, the gain figures Q-043 sets out, `net_income`, `total_liabilities_and_equity`. Each states its currency, and none is quoted: quotes are for text, and a money figure in quotes reads as a string that happens to look like money. `value:` and `share_price:` are quoted, as this format writes a key's value. `retained_earnings` and `trading_gains` are written whenever the book holds the money behind them, and left off when it holds none of it at all, each being a thing the book either has or has not. Holding the money and valuing it are separate questions, and the key follows the first: a book earning only in a currency it holds no price for states `retained_earnings: 0.00 CAD`, because the earnings are there and GnuCash values what it cannot price at nothing. The totals and `net_income` are always written, a statement having a bottom line whatever it comes to.
- **One key whatever the sign.** GnuCash's page switches between `Gains` and `Losses` and between `Net income` and `Net loss`; a block is read by a program too, so the key stays put and the sign is in the figure.

### Where each figure comes from

Nothing on the page is worked out by gnucash-plaintext.

| what | where it comes from |
|---|---|
| an account line's amount | GnuCash's account table — `account-bal`, the account's own balance, for every account including a parent |
| a section's total | the same collectors GnuCash's own renderer totals its `Total …` rows from |
| `share_price:` | `gnc:case-price-fn` from 4.4. On 3.4 and 3.8, which have no such helper, the same answer built the same way: `gnc-pricedb-lookup-latest` or `gnc-pricedb-lookup-nearest-in-time64` for the pair, in whichever direction the book prices it and inverted by `gnc-price-invert` where that is the other way round, and the two prices that reach it multiplied as exact rationals where the book prices the pair in neither direction. Never divided out of an amount, and omitted where nothing prices the pair |
| `value:` | GnuCash's own `exchange-fn` at the report's price source, which does the multiplication and rounds to the currency's smallest unit |
| the block's keys | the same calls GnuCash's `balance-sheet.scm` and `income-statement.scm` make, in the same order |

A figure is written exactly and never rounded here: padded to the commodity's own decimal places, and written as a fraction where no decimal states it exactly, as `share_price: "2/11"` on an HKD account in a CAD block.

## The figures it should print

The book used for these measurements is `tests/fixtures/a_cad_book_with_usd_hkd_and_shares_priced_in_its_price_database.txt`: one CAD book over two years, holding every figure the two statements have to print — a cost basis, currency bought and partly sold, shares bought and partly sold, business income billed right through both years and partly collected, opening capital, and a USD loan drawn and partly repaid with a residual still owed.

- 2025: 04-01 20,000.00 CAD of opening capital; 05-05 10,000.00 USD bought for 13,000.00 CAD at 1.30; 06-08 5,500.00 HKD bought for 1,000.00 CAD; 07-12 4,000.00 USD borrowed; 08-15 20 NASDAQ:AMZN bought at 200.00 USD; 12-20 50.00 CAD of fees.
- 2026: 06-30 8 AMZN sold at 260.00 USD, taking 480.00 USD; 07-15 3,000.00 USD sold at 1.38 that cost 1.30, taking 240.00 CAD; 09-30 1,500.00 USD of the loan repaid with 100.00 USD of interest; 12-20 150.00 CAD of fees.
- Consulting is billed every quarter and collected a month later, the last still owed: 1,000.00 on 2025-06-30, 1,200.00 on 09-30, 1,400.00 on 12-31, 1,600.00 on 2026-03-31, 900.00 on 04-10, 1,800.00 on 06-30, 2,000.00 on 09-30 and 2,200.00 on 12-31.
- Prices, all at 12:00 UTC: USD in CAD 1.30 on 2025-05-05, 1.35 on 2026-03-31, 1.38 on 2026-07-15 and 1.42 on 2026-12-31; CAD in HKD 5.5 on 2025-06-08 and 5.0 on 2026-12-31; AMZN in USD 200 on 2025-08-15, 260 on 2026-06-30 and 280 on 2026-12-31.

**The quarters differ so that a fiscal year ending anywhere cuts the trading rather than lining up with it**, which is what a Canadian filer's year does and what a period arithmetic defect hides behind. Measured:

| fiscal year ending | the block opens | consulting | net income |
|---|---|---|---|
| 2026-03-31 | 2025-04-01 | 5,200.00 CAD | 5,150.00 CAD |
| 2026-04-25 | 2025-04-26 | 6,100.00 CAD | 6,050.00 CAD |
| 2026-06-30 | 2025-07-01 | 6,900.00 CAD | 7,512.40 CAD |
| 2026-12-31 | 2026-01-01 | 8,500.00 CAD | 9,129.60 CAD |

The 06-30 year catches the share sale on its own last day, and values the 480.00 USD taken at the 1.38 nearest that day rather than at the calendar year end's 1.42 — `value: "662.40"` there and `681.60` in the 12-31 year.

`balance-sheet --as-of 2026-12-31` prints:

```
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
	Assets:AMZN 12.0000 AMZN
		account.commodity.mnemonic: "AMZN"
		share_price: "397.6"
		value: "4771.20"
	Assets:Receivable 2200.00 CAD
	Assets:CAD Bank 19840.00 CAD
	Assets:HKD Bank 5500.00 HKD
		account.commodity.mnemonic: "HKD"
		share_price: "0.2"
		value: "1100.00"
	Assets:USD Bank 7480.00 USD
		account.commodity.mnemonic: "USD"
		share_price: "1.42"
		value: "10621.60"
	total_assets: 38532.80 CAD
	Liabilities:USD Loan 2500.00 USD
		account.commodity.mnemonic: "USD"
		share_price: "1.42"
		value: "3550.00"
	total_liabilities: 3550.00 CAD
	Equity:Opening CAD 20000.00 CAD
	retained_earnings: 12679.60 CAD
	realized_gains_fx: 0.00 CAD
	total_realized_gains: 0.00 CAD
	unrealized_gains_assets_fx: 940.00 CAD
	unrealized_gains_liabilities_fx: 0.00 CAD
	unrealized_gains_fx: 940.00 CAD
	unrealized_gains_other: 1363.20 CAD
	total_unrealized_gains: 2303.20 CAD
	gnucash_balancing_amount: 2303.20 CAD
	total_equity: 34982.80 CAD
	total_liabilities_and_equity: 38532.80 CAD
```

The block is abridged: `balance-sheet` also prints, beneath each gain figure, the working that shows how it was reached, which `--no-itemize` leaves off.

`income-statement --fiscal-year-end 2026-12-31` prints:

```
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
	Income:Consulting 8500.00 CAD
	Income:Realized FX Gains 240.00 CAD
	Income:Realized Gains 480.00 USD
		account.commodity.mnemonic: "USD"
		share_price: "1.42"
		value: "681.60"
	total_revenue: 9421.60 CAD
	Expenses:Fees 150.00 CAD
	Expenses:Interest 100.00 USD
		account.commodity.mnemonic: "USD"
		share_price: "1.42"
		value: "142.00"
	total_expenses: 292.00 CAD
	net_income: 9129.60 CAD
```

`retained_earnings` is 12,679.60 CAD rather than the year's 9,129.60, because it is every income and expense the book has never closed — 2025's 3,550.00 as well, being 1,000.00 + 1,200.00 + 1,400.00 of consulting less 50.00 of fees.

Both kinds of gain are on the balance sheet at once, by different routes. A gain already taken is income, so it is inside `retained_earnings` — the 480.00 USD from the shares and the 240.00 CAD from the currency, each with its own line on the income statement. A gain on what is still held is held by no account, so it is a key: 2,303.20 CAD on the 7,480.00 USD, 5,500.00 HKD and 12 AMZN the book still has, against the 2,500.00 USD it still owes. Q-043 divided that figure into the 940.00 on the foreign currency and the 1,363.20 on the shares, and this book's realized figures are 0.00 because its two gains were written as stated splits rather than declared with `$residual$`.

**An account left holding nothing is left off**, which is this page's choice and not GnuCash's. That is the account the period never touched, and equally the account whose entries cancel each other out exactly — a receivable collected in full within the period is off the page as surely as one nobody billed. An account holding money the book cannot price stays on it, stating what it holds beside `value: "0.00"`, because it holds the money whatever the valuation comes to. With its shipped defaults — `Include accounts with zero total balances` on — GnuCash's own page prints such an account with a zero figure: measured on 5.10, its income statement for the year ending 2026-03-31 shows `Realized FX Gains`, `Realized Gains` and `Interest`, none of which that year touched. A line for one states nothing twice over: the figure is zero, and an empty balance knows no commodity, so a US dollar account would read `0.00 CAD` — a claim about the account that is false. A column page can carry such a row to line a heading up; a block is read by a program. So the block's year ending 2026-03-31 has no `Income:Realized FX Gains` and no `Expenses:Interest` line.

`report <book> income-statement balance-sheet` writes both blocks to one page, in the order the statements are given, separated by a blank line.

## What was measured

### GnuCash's reports run through the report engine `print-invoice` already uses

`services/gnucash_report.py` renders GnuCash's invoice report through Guile. The same setup renders GnuCash's Balance Sheet and Income Statement reports (`what_gnucash_own_balance_sheet_and_income_statement_give_probe.py`).

| | GnuCash 3.4, 3.8 | GnuCash 4.4 and later |
|---|---|---|
| module that registers the reports | `(gnucash report standard-reports)` | `(gnucash reports standard balance-sheet)`, `(gnucash reports standard income-statement)` |
| Balance Sheet template guid | `c4173ac99b2b448289bf4d11c731af13` | the same |
| Income Statement template guid | `0b81a3bdfd504aff849ec2e8630524bc` | the same |
| options the commands set | `General / Balance Sheet Date`; `General / Start Date` and `End Date`; `Commodities / Report's currency`; `Commodities / Price Source` | the same option names |

On the book above, every build gives the same figures: as of 2026-12-31, USD Bank 10,621.60 CAD, AMZN 4,771.20 CAD and total assets 38,532.80 CAD, with net income 9,129.60 CAD for that calendar year and 5,150.00 CAD for the fiscal year ending 2026-03-31.

### A customized report may output plain text

`gnc:report-render-html` applies a style sheet only to a document object. A renderer that returns a string has that string handed back unchanged, with no style sheet and no HTML: `((string? doc) doc)`, read in `report.scm` on 3.4 and 3.8 and in `report-core.scm` on 4.4 and 5.10. So a GnuCash report, customized, can output plain text.

What such a report can read from GnuCash:

| | where it was measured |
|---|---|
| GnuCash's account table gives each row `account-bal`, `recursive-bal`, `display-depth`, `row-type` and `account-name` | 3.4, 3.8, 5.10 |
| commodity collectors take `'add`, `'merge`, `'minusmerge` and `'format` | 3.4, 5.10 |
| `gnc:collector+` | absent on 3.4; present on 3.8, 4.4 and 5.10 |
| the Balance Sheet's and Income Statement's option names | the same on 3.4, 3.8, 4.4 and 5.10 |
| the Balance Sheet's figures: asset, liability, equity and income-and-expense balances as of the date, trading balances when the book uses trading accounts, and the assets and liabilities less their value at cost — which Q-043 states as `gnucash_balancing_amount`, being neither gain | the same arithmetic on 3.4, 3.8, 4.4 and 5.10, written with collector methods on 3.4 and `gnc:collector+` from 3.8 |

### How GnuCash's reports choose a price

Both reports have an option `Commodities / Price Source`, and both default it to `pricedb-nearest` on every build (`which_price_sources_the_reports_offer_probe.py`). Nearest in time, a later price included: a sheet as of 2026-01-12 prices the US dollars at the 1.35 of 2026-03-31, under three months ahead, rather than the 1.30 of 2025-05-05 some eight months behind.

| GnuCash | the choices `Price Source` offers |
|---|---|
| 3.4, 3.8, 4.4 | `average-cost`, `weighted-average`, `pricedb-latest`, `pricedb-nearest` |
| 4.8 and later | the same, and `pricedb-before` ("Last up through report date") |

GnuCash 3.4 to 4.13 give each choice as a vector whose first element is its name, and 5.x lists them through the option itself.

**A statement is printed from the choices that read the price database** — `pricedb-nearest`, `pricedb-latest` and, from 4.8, `pricedb-before` — so the `share_price:` on a line is a price the book records and a reader can find in it. A `--price-source` outside that list is refused, with the choices listed. What a purchase cost is on its own split, as `share_price:` and `value:`, and what the book still holds at cost is what `fx-balances` reports.

### A price added for the run

A price added to the price database of a book opened read-only, at `gnc_dmy2time64_end` of the report date, from the source `user:price-editor`, is the price GnuCash's Balance Sheet report uses (`a_rates_file_as_prices_probe.py`, measured on 5.10, 3.8 and 3.4). The page stated `share_price: "1.5"` and `value: "11220.00"` against Assets:USD Bank's 7,480.00 USD — the added price of 1.50 — in all three cases:

1. as of 2026-11-30, where the book has no USD price that day;
2. as of 2026-12-31, where the book already prices USD at 1.42 that day, from the same source;
3. as of 2026-12-30, where the book's nearest USD price is twelve hours after the end of the day.

After the book was closed, its prices read back as they were before.

### A book that uses trading accounts

A book with `Accounts / Use Trading Accounts` set, and the book above imported into it, holds the accounts GnuCash creates for trading splits: `Trading`, `Trading.NASDAQ.AMZN` and `Trading.CURRENCY.USD` (`what_the_balance_sheet_prints_for_a_book_using_trading_accounts_probe.py`, on 5.10). GnuCash's shipped Balance Sheet report then prints what the holdings have made as Trading Gains, with no Unrealized Gains line, and the plaintext page writes it as the `trading_gains:` key with none of the other gain figures beside it.

The two are the same money reached by different bookkeeping, and a book has one or the other, never both. With trading accounts off, no account holds that gain and the balance sheet derives it — the assets and liabilities less their value at cost. With them on, GnuCash books the revaluation into Trading accounts as each transaction happens, so the gain is an account balance, and the report reads it as one. The gain keys are computed only `unless use-trading-accounts?`, so a page carries either `trading_gains` or them, never both.

### GnuCash stores no currency for a book

On a book kept in HKD that also holds USD and CAD — top-level Assets and Equity in HKD, and an HKD, a USD and a CAD bank account beneath them (`what_currency_gnucash_says_a_book_is_kept_in_probe.py`, on 3.4, 3.8, 4.4 and 5.10):

| asked | answer |
|---|---|
| the root account's commodity | none |
| `gnc_book_get_book_currency_name` | none on 3.4 and 3.8; the call does not exist on 4.4 and 5.10 |
| `gnc_default_currency`, `gnc_default_report_currency` | USD on 3.4 and 3.8: GnuCash's preference, not the book; the calls do not exist on 4.4 and 5.10 |
| the Balance Sheet's `Report's currency` when nothing sets it | USD |

So GnuCash's report must always be told the currency, and gnucash-plaintext has to find the book's currency itself.

### GnuCash's account conversion calls do not give its reports' figures

`xaccAccountGetBalanceAsOfDateInCurrency` exists on every build, and does not give what GnuCash's own report gives: on 3.4, 3.8 and 4.4 it prices at the latest price whatever the date is asked for, and from 4.8 at the last price up to that date, where the report's default is the price nearest in time — which may be a later one. On a book holding several prices of a pair the three answers differ, and only the report's is what GnuCash shows a user, so a report is what the commands run (`which_calls_convert_a_balance_to_another_currency_probe.py`, `what_gnucash_currency_conversion_calls_give_probe.py`).

## Decisions

### The book's currency

The first of these that gives one:

1. `--currency HKD` on the command;
2. the `company` block's custom key `base_currency: "HKD"`, kept in the book with the block's other custom keys;
3. the currency of the book's top-level accounts, when every top-level account held in a currency is held in the same one. Accounts beneath them may hold any currency.

Where none of them gives one — no key, and top-level accounts in more than one currency or in none — the command is refused, and the refusal says how to state the currency. A currency GnuCash does not know is refused as well.

### Every figure comes from a GnuCash report

- `--output-format text`, the default, is printed by two customized GnuCash reports in `infrastructure/gnucash/reports/balance-sheet-and-income-statement-as-text.scm`, which the package ships as package data, "Balance Sheet (plain text)" and "Income Statement (plain text)". Each is written from GnuCash's `balance-sheet.scm` or `income-statement.scm`: registered with `gnc:define-report`, given GnuCash's own report's options, making the same GnuCash calls for every figure, and returning its page as plain text.
- The report file is package data of `infrastructure.gnucash`, so an installed package carries it. A wheel built from the tree and installed outside it printed the plaintext balance sheet on 5.10, with no source folder on the import path.
- `--output-format html` writes the page of GnuCash's Balance Sheet or Income Statement report as GnuCash ships it, and `pdf` prints that page through WebKit, as `print-invoice` prints an invoice.
- `Report's currency` is always set, to the book's currency.
- `Price Source` is GnuCash's own default unless `--price-source` gives one of the choices the build offers. A choice the build does not offer is refused, and the refusal lists the ones it does.

### Rates and prices given in a file

- `--fx-rates` and `--prices` are added to the book's price database for the run and never saved, and GnuCash's report prices from them.
- A rate is a price of a currency in the report's currency. `USD: 1.40` is USD in the report's currency. `USD/HKD` states both currencies, and is refused where HKD is not the report's currency.
- A rate or a price may be a fraction, `HKD: 2/11`, as `value:` in a `price` block may.
- A price with no date is added at the end of each day a statement of the run is for. A dated price is added at the time GnuCash gives its date, as a `price` block with a date is.
- A security's price with no currency is in the currency of the book's own prices of that security, or, where the book has none, the currency of the transactions that hold it. Where that is more than one currency, the file has to give it, as `AMZN/USD: 250`.

## Tests

- `tests/integration/test_the_currency_a_book_is_kept_in.py`: each source of the book's currency, the order they are tried in, and each refusal.
- `tests/integration/test_the_statements_are_printed_by_customized_gnucash_reports.py`: the block a statement is written as — its directive, its account lines found by path, the split keys under an account held in another commodity, and the block's own keys; the CAD book of one fiscal year above, whose figures are those GnuCash's reports give; a book kept in HKD that holds USD and CAD, whose statements are printed in HK$ with the USD and CAD converted; the HTML page; the PDF page read back as text; `--currency`; a net loss and retained losses; a book that uses trading accounts; a book with no accounts; `report`, which writes a block per statement.
- `tests/unit/test_every_file_in_a_shipped_package_is_shipped.py`: every file inside a package the wheel ships is matched by `package-data`, the report file included. The suite installs the project editable, which reads the source folder, so no other test can see a file the wheel leaves out.
- `tests/integration/test_a_rates_file_prices_gnucash_reports_for_the_run_only.py`: a rates file and a prices file change the figures GnuCash's report gives and leave the book's prices unchanged; dated rates, fractions, a same-day rate, refusals; `--price-source`.
- `tests/integration/test_reports.py`, `test_report_command_arguments.py`, `test_cli_income_statement.py`, `test_balance_sheet_account_types.py`: the commands' arguments and every account type, against the figures GnuCash's reports give.

## Probes

| probe | what it measures |
|---|---|
| `tests/research/what_gnucash_own_balance_sheet_and_income_statement_give_probe.py` | GnuCash's Balance Sheet and Income Statement reports as GnuCash ships them, on the book above: their options, and the pages they render |
| `tests/research/which_price_sources_the_reports_offer_probe.py` | the `Price Source` choices each report offers |
| `tests/research/a_rates_file_as_prices_probe.py` | whether a price added for the run is the one GnuCash's Balance Sheet report uses, and whether the book keeps it |
| `tests/research/what_the_balance_sheet_prints_for_a_book_using_trading_accounts_probe.py` | what GnuCash's Balance Sheet report and the plaintext page print for a book whose "Use Trading Accounts" option is on |
| `tests/research/what_currency_gnucash_says_a_book_is_kept_in_probe.py` | what GnuCash says a book's currency is, for a book kept in HKD that holds USD and CAD |
| `tests/research/which_calls_convert_a_balance_to_another_currency_probe.py` | which currency conversion calls each build has |
| `tests/research/what_gnucash_currency_conversion_calls_give_probe.py` | what those calls give on the book above |
