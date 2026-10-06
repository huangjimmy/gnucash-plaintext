# Q-057 — Keep each account's balance in every currency the book supports, and move every balance with a transfer

Built: see "What was built" and the two sections after it. The scenario and the examples, and every amount in them, are the author's.


## Scenarios

### The user

A user U, with base currency as CAD, want to support only USD HKD CAD CNY for their business

### Money credit/debit between accounts

USD_A is an account in USD
USD_A1 is an account in USD
CAD_B is an account in CAD
HKD_C is an account in HKD
CNY_D is an account in CNY

At time 0, these accounts have balances
* USD_A, 100 USD, also stored the balances 130 CAD, 780 HKD, 600 CNY
* USD_A1, CAD_B and HKD_C and CNY_D are all 0s

U transfer 10 USD from A to A1,
this transaction is model as 
U transfers 10 USD (13 CAD, 78 HKD, 60 CNY) from A to A1, such that after the transaction
A has 100-10 USD, 780-78 HKD 600-60 CNY, 130-13 CAD
A1 has 10 USD, 78 HKD, 60 CNY, 13 CAD

if instead U does not transfer from A to A1 but A to B, and at the time of the transfer, the FX rate is
1 USD = 1.4 CAD, 1 USD = 7.85 HKD 1 USD = 6.5 CNY
then USD_A is credited 10 USD, 13 CAD, 60 CNY, 78 HKD
but CAD_B is debited 10 USD 14 CAD, 65 CNY 78.5 HKD, the extra 1 CAD 5 CNY 0.5 HKD are realized gains, 1 CAD 5 CNY 0.5 HKD will be recorded in a CAD income account as 1 CAD, and the income account will also store 5 CNY 0.5 HKD as the corresponding realized gain in HKD/CNY, not converting 1 CAD at the rate of the transaction day

### Balance sheet and income statement

U can ask gnucash plaintext to print/export balance sheet and income statement in CAD, USD, HKD, CNY.
They didn't initially setup the gnucash ledger to include other currencies, so balance sheet and income statement cannot be exported in other currencies.

### A 2nd user

U2 is a friend of U. U2 has a ledger that keeps 3 years of U2's transactions. U2 sees U's example, and U2 decides to make its own ledger selecting CAD USD and CNY as a set of currencies. Before, U2's ledger is a gnucash file with CAD as base currency and uses cost basis.

Gnucash plaintext runs the setting and rederive all balances from the beginning of very first transactions

Gnucash plaintext warns U2 that once they migrate away from cost basis, they wont be able to migrate back to cost basis.

## What it should do

The rules follow the parts of the scenario: the user and their book, money moved between accounts, the two statements, and a second user whose book already has a history.

### The book

**It is a setting of the book, off unless the book turns it on.** A book records either these balances or cost bases, one or the other at a time. No book is kept this way by default.

**The book selects the currencies it supports.** gnucash-plaintext supports a fixed set, so far USD, CAD, HKD, CNY, EUR, JPY, GBP and KRW, and a book selects a subset of them. U selects USD, HKD, CAD and CNY.

**The book states its base currency.** U's is CAD. A realized gain is posted to an income account kept in the base currency.

**A currency can be added to a book later.** Every balance in that currency is then worked out again from the beginning of the book.

### Money moved between accounts

**Every account holds a balance in each currency the book selected, whichever currency it is kept in.** USD_A holds 100.00 USD, and also 130.00 CAD, 780.00 HKD and 600.00 CNY. They are balances, kept as if the bank stored Canadian dollars, Hong Kong dollars and yuan beside the US dollars. CAD_B, HKD_C and CNY_D each hold a balance in all four currencies too.

**A transfer between two accounts of one currency moves the same share of every balance.** 10.00 USD is one tenth of USD_A's 100.00 USD, so the transfer to USD_A1 moves 10.00 USD, 13.00 CAD, 78.00 HKD and 60.00 CNY. USD_A then holds 90.00 USD, 117.00 CAD, 702.00 HKD and 540.00 CNY. USD_A1 holds 10.00 USD, 13.00 CAD, 78.00 HKD and 60.00 CNY. Nothing is realized.

**Where the receiving account already holds money, the balances are added.** The author's first example, on its own two US dollar accounts: one holds 100.00 USD and 130.00 CAD, the second holds 100.00 USD and 140.00 CAD. All 100.00 USD of the first is moved to the second. The second then holds 200.00 USD and 270.00 CAD: 130.00 CAD + 140.00 CAD.

**A transfer to an account kept in another currency realizes a gain in each currency.** 10.00 USD is moved from USD_A to CAD_B at 1.40 CAD/USD, 7.85 HKD/USD and 6.50 CNY/USD. USD_A gives up 10.00 USD, 13.00 CAD, 78.00 HKD and 60.00 CNY. CAD_B receives 14.00 CAD, and with it 10.00 USD, 78.50 HKD and 65.00 CNY. The realized gain is what CAD_B receives less what USD_A gives up, currency by currency: 1.00 CAD, 0.50 HKD, 5.00 CNY and 0.00 USD.

**The gain is recorded in one income account, which holds it in each currency.** The book's base currency is CAD, so the gain is posted to a Canadian dollar income account as 1.00 CAD. That account also stores 0.50 HKD and 5.00 CNY, the gain realized in each of those currencies. They are the amounts above, and are never the 1.00 CAD converted at the rate of the day.

**gnucash-plaintext keeps the balances itself, for every account.** Money that moves A → B → C → D → E is moved four times. At each transfer gnucash-plaintext moves the amount and the balance in each currency, and records what each account then holds. E's balances are then the ones carried through B, C and D.

**The average cost is one balance divided by another, worked out when it is wanted.**

- USD_A, before and after the transfer to USD_A1: 130.00 CAD / 100.00 USD = 117.00 CAD / 90.00 USD = 1.30 CAD/USD. In the other two currencies it is 780.00 HKD / 100.00 USD = 7.80 HKD/USD and 600.00 CNY / 100.00 USD = 6.00 CNY/USD.
- The second account of the author's first example: 270.00 CAD / 200.00 USD = 1.35 CAD/USD.

The book stores the balances, which are amounts of money, added and subtracted as money is. The average is always read from them, so it carries no rounding error from one transaction to the next.

**What it costs.** A book kept this way states a realized gain in each currency in use, on every transaction that crosses currencies. The author on it: "the bad thing about this mode, it is too verbose that it needs to keep track of realized gains of each currency in use".

### Balance sheet and income statement

**Each can be printed in any currency the book selected.** U can ask for the balance sheet and the income statement in CAD, USD, HKD or CNY.

**A currency the book did not select is refused.** U's book was set up with those four, so it holds a balance in no other currency, and neither statement can be printed in EUR, JPY, GBP or KRW.

### A book that already has a history

**A book with a history can turn the setting on, and so can a book that kept cost bases.** U2's book holds three years of transactions, has CAD as its base currency and kept cost bases. U2 selects CAD, USD and CNY.

**gnucash-plaintext then derives every balance from the book's first transaction.** It applies the setting and works out each account's balance in CAD, USD and CNY again, transaction by transaction, from the first one in the book to the last.

**The change away from cost bases is one way, and gnucash-plaintext warns of it.** It warns U2 that a book migrated away from cost bases cannot be migrated back to them.

**The cost bases the book recorded stay in it.** They are the book's history. U2's book keeps every cost basis its three years recorded, and from the migration on it records balances.

## What was reported

The author, 2026-10-05, starting the work:

> shall now start another fx options, not cost basis, but "cost balances"

> it is like this, 100 USD 130 CAD in A, 100 USD 140 CAD in B, if all 100 USD are transfered to B, then B becomes 200 USD (130+140=270 CAD)

> the cost is 270/200=1.35, but the 130 and 140 are not cost, but the amount of CAD that represent the CAD balance as if the bank stores CAD

> 100 USD (130 CAD, 780 HKD), then if I transfer 50 USD to another Bank, it is as if I transfer 50 USD (65 CAD, 390 HKD) to the other bank, this case, we dont actually store the avg cost, but represent the balance of each account in all supported currency, which in terms gives gnucash plaintext an easy way to compute the avg cost at no rounding errors!

> this feature cannot co exist with cost basis, but looks like a perfect solution if we decided that we supported a fixed number of currencies, so far, it should be USD CAD HKD CNY EUR JPY GBP KRW, but users can select a subset, and if they want to expand to more currencies, it is still possible but need to recompute all from the beginning of book.

> if there are A -> B -> C -> D -> E tranfers, you must keep track of each currency balance and amount!!!! otherwise it will be complete mess

> each supported currency, not just base currency. It is as if each account has balance in CAD USD CNY HKD GBP, etc. So that we can track the transfer amount in each currency!!! 100 USD from A to B, if both A and B have different avg cost, then we need this to recompute the actual avg cost!!   but if 100 USD from A to C where C is only CAD, then there will be realized gain and the CAD in C will have different amounts in each suppored currency!

> then this is a special feature, because it cannot be enabled by default, it must be explicitly enabled, and even if it is a book with long history, a user can enable this feature but the first check will need to derive all supported currency balance from a specific date!

## What the repo already says about the behaviour this changes

- **A transfer moves only the currency today.** In a book keeping cost bases, 4,000.00 USD moved from one US dollar account to another "draws down no cost basis and opens none" (README, "A transfer shares a transaction only with a fee written as a split of its own that states its cost basis").
- **So an account and the cost bases behind it can disagree.** Q-047, case 2: C holds 1,000.00 USD bought at 1.30 CAD/USD, 500.00 USD is moved from A to B, and B's 500.00 USD is sold. The sale has to state C's cost basis, and C's cost basis falls to 500.00 USD while C still holds 1,000.00 USD. Q-043 has a section on it, "A cost basis balance is not an account balance, and a book can let the two disagree".
- **Q-051 recorded a transfer that carries its cost basis.** Under "Not supported yet: a transfer that carries its cost basis", 4,000.00 USD arrives in savings as a cost basis of its own, at the cost it had, asked for on the arriving split.
- **GnuCash keeps an amount and a value on every split.** The amount is in the account's currency, and the value is in the transaction's currency. Q-043 measured "the sum of its split values" for an account, under its heading "Why the reported example's figure is its realized loss". That sum is in the currency each transaction was stated in.
- **A book states its settings in its `company` block.** `base_currency: "HKD"` (Q-056) and `cost_bases: "off"` (Q-049) are both there, kept as keys of the book, so every command reads the same answer.

## What was built

In `services/currency_balances.py`, run by `import` on the finished book before it is saved.

- **The setting.** `currency_balances: "CAD USD HKD CNY"` in the `company` block. Each currency is one of the eight, is listed once, and the base currency is among them. Stated on a book that has it, `currency_balances: $None$` is refused: the setting cannot be removed.
- **On each split,** its amount in each selected currency other than its account's own, as `currency_amount.CAD: "13.00"`. GnuCash already has the amount in the account's own currency. `export` writes these keys on each split.
- **On each account,** its balance in each selected currency other than its own, as `currency_balance.CAD: "117.00"`. GnuCash already has the balance in the account's own currency.
- **A split lowering what its account holds** draws the same share of each stored balance, rounded as gnucash-plaintext rounds money, and all of each balance where it empties the account.
- **A split of the same currency facing it** takes exactly what was drawn, and nothing is realized.
- **A split bringing money into an account kept in another currency** takes the amounts of the day. The currency the transaction itself exchanged is taken as exchanged, so CAD_B's 14.00 CAD is 10.00 USD. Each other currency is read from the book's price nearest the transaction's date, through a third currency where the book has no price of the pair, so 14.00 CAD is 78.50 HKD through 1.40 CAD/USD and 7.85 HKD/USD.
- **The `$residual$` split takes what is left in each currency,** which is the gain realized in that currency. A transaction with no `$residual$` split realizes nothing in any currency: a currency or shares bought with no such split take what the account paying for them gave up, and no price is read. The first version read a price there, and refused 20 AMZN bought with US dollars for want of a price of AMZN in HKD.
- **US dollars paying for shares** are written either way, and the file decides. With no `$residual$` split, the shares take what the USD account gave up, which is their cost in each currency, and nothing is realized. With a `$residual$` split, in a book whose base currency is not USD, the US dollars realize a gain: 10.00 USD stored at 13.00 CAD buy 2 shares worth 14.00 CAD, the shares arrive at 14.00 CAD, 10.00 USD, 78.50 HKD and 65.00 CNY at the day's prices of the US dollar, and the split takes 1.00 CAD, 0.50 HKD and 5.00 CNY. The balance sheet states that under `realized_gains_fx`, and a later sale of a share under `realized_gains_other`. The author on it: "that cost dont realize any yet", and "that USD buys AMZN, it only realize FX gain/loss when base currency is not USD".
- **In the transaction's own currency a split moves its value,** as the transaction states it.
- **A book with a history** has every amount and balance derived from its first transaction, in the order GnuCash keeps its transactions. An invoice's posting and a payment are transactions like any other. The import prints the warning that the book cannot be migrated back, and the cost bases stay in the book and in its export.
- **`fx-balances`** lists each account with its balance in each selected currency.
- **The balance sheet and the income statement** are printed in any selected currency with `--currency`, and refused in any other. For the length of the statement, each income, expense and equity account is read as kept in the page's currency, each split at the amount it stored, and the book is put back afterwards with nothing saved. An account holding or owing money is valued at the price of the page's date, and its unrealized gain is that value less the balance it stores. The realized gain is what the `$residual$` splits stored in that currency. U's book after the transfer to CAD_B states, in HKD, 785.00 HKD of assets against 780.00 HKD of equity, 0.50 HKD realized and 4.50 HKD unrealized. Before the accounts were read that way the same page stated 785.00 HKD of assets against 739.04 HKD of liabilities and equity, because GnuCash converted the 130.00 CAD of opening equity at the price of the page's date.
- **The balance sheet's working is in its own words**: `stored_balances:`, `stored_balance:`, `account_guid:`, `balance:` and `stored_value:` under each currency, an account and the balance it stores. The page is the one a book keeping cost bases prints, handed one row per account, and its working would otherwise arrive in a cost basis's words.
- **Only a key and a comment of the page are reworded.** An account's name is printed as the book has it, on its own line and wherever it is quoted. The first version reworded the whole page, and printed an account called `Assets:USD kept at cost basis` as `Assets:USD kept at stored balance`. The second review of the commit raised it.
- **A split of 0.00 stores 0.00 in each selected currency.** The first version passed such a split over and wrote it no amount. The second review raised that too.
- **The transactions are read in GnuCash's own order**, `xaccTransOrder`: by date, then by `num` as a number, then by the moment entered, then by description. The first version sorted `num` as text, and with number 9 and number 10 on one day, number 9 moving 100.00 USD to USD_A1 and number 10 moving 40.00 USD back, it read number 10 first and left USD_A storing 53.14 CAD where the 40.00 USD store 52.00 CAD. The review of the commit raised it.
- **Every command that saves the book derives the balances first**, through a list in `repositories/gnucash_repository.py` that `save` runs. `delete-transactions` on the transfer to USD_A1 gives USD_A its 100.00 USD, 130.00 CAD, 780.00 HKD and 600.00 CNY back.
- **A currency added to the selection** is worked out from the first transaction, and one left out of it is no longer kept.
- **`set-book-key`** refuses `currency_balances` and leaves it to the `company` block.
- **`--verify-integrity`** lists the cost basis checks as not checked, with the reason that the book keeps a balance in each selected currency.
- **The export** writes each split's amounts and each account's balances, and importing it back finds every transaction up to date.
- **README**, "A book that keeps a balance in each currency it selects".

`tests/integration/test_u_keeps_a_balance_in_cad_usd_hkd_and_cny_on_every_account.py` states U's three cases with the amounts of the scenario above. `tests/integration/test_a_book_that_kept_cost_bases_selects_its_currencies.py` turns the setting on in the Hong Kong company's book of Q-056, which holds invoices, a bill, sales of currency and cost bases. Its 7,000.00 USD stores 54,350.00 HKD and its 50,000.00 CNY stores 54,000.00 HKD, which is what its cost bases recorded they cost, and every currency adds up to zero across the accounts. Both files pass on GnuCash 3.4, 3.8, 4.8, 5.10 and 5.15.

`tests/scenario/test_acme_keeps_a_balance_in_usd_cad_cny_hkd_eur_and_gbp_on_every_account.py` is the author's second case: ACME LLC, base currency USD, fiscal year ending 06-30, selecting USD, CAD, CNY, HKD, EUR and GBP. It opens with 1,000.00 USD, invoices 1,000.00 USD and 1,000.00 EUR, is paid in full, and sells the 1,000.00 EUR for 1,223.34 USD. Its balance sheets and income statements are stated in all six currencies, before and after each date.

**Each rate is the Bank of Canada's for the day of the transaction.** The author: "if you know the tx date, you should know the rate on that day". The book's prices are the bank's daily rates, each in Canadian dollars, read from its published observations (`https://www.bankofcanada.ca/valet/observations/FXUSDCAD,FXEURCAD,FXCNYCAD,FXHKDCAD,FXGBPCAD/csv`). It publishes none on a holiday or a weekend, so such a day takes the last rate before it, 2019-12-31 for 2020-01-01. A rate between two other currencies is one divided by the other, and the statements print in every selected currency from rates quoted in CAD alone, on GnuCash 3.4, 3.8 and 5.10. Every expected amount was worked out from those rates apart from gnucash-plaintext, and all 42 of ACME's balance sheets and its income statements agreed with what gnucash-plaintext printed.

That case found one defect, with the rates the fixtures first held. After ACME sold all its EUR, Wise EUR held nothing, and the balance sheet was handed no row for it. The page then measured EUR from GnuCash's revaluation and stated the loss on the sale a second time, as an unrealized gain, and did not balance. An account emptied by the page's date is now listed, holding nothing and storing nothing.

`tests/scenario/test_acmu_migrates_from_cost_bases_after_five_years.py` is the author's third case: ACMU LLC, kept in CAD with cost bases for five years, then migrated to keep a balance in CAD, USD, CNY, HKD, EUR and GBP. Its 21 transactions include six invoices in USD, EUR and CAD, one of them unpaid at the migration, expenses paid in USD and EUR, and sales of USD and EUR, each disposal stating its cost basis. The case gives "many transactions including invoices" and a 1,000.00 CAD invoice. Which transactions, and their dates and amounts, are the fixtures', and the test's docstring lists them. Each rate is the Bank of Canada's for the day, as ACME's are.

- The balance sheet in CAD at each fiscal year end and on 2024-12-31, and the income statement of each fiscal year, state the same amounts before the migration and after it. On 2024-12-31: 13,626.16 CAD of assets, 37.69 CAD of realized gain and 1,028.05 CAD of unrealized gain. Each was worked out lot by lot from the bank's rates, apart from gnucash-plaintext.
- After the migration each account stores in CAD what its cost bases came to: Chase Chequing's 4,898.34 USD store 6,254.11 CAD and Wise EUR's 800.00 EUR store 1,048.80 CAD.
- `--verify-integrity` finds the migrated book consistent and balanced, every currency adds up to zero across its accounts, and its balance sheet balances in each of the six currencies at each year end.
- The cost bases stay in the export, and importing the export back finds all 21 transactions up to date.
- ACMU's first three steps, which are ACME's, store after migrating exactly what ACME's accounts store.
- The first sale after the migration states no cost basis: 500.00 USD of 4,898.34 USD storing 6,254.11 CAD leave at 638.39 CAD, sell for 724.20 CAD at 1.4484 CAD/USD and realize 85.81 CAD.

## A transaction deleted from the middle of a year

The author, after the commit had passed: "gnucash allow deletion of any transactions, but the scenario test dont cover this!!!, must extend the ACME and ACMU scenaris with deleting 1 transaction in the middle of the year, then what happen? there will be cascading effect to all balances!!!"

Only an integration test of U's book deleted a transaction until then. Both scenario tests now do, with `delete-transactions`, which derives every balance again from the first transaction before it saves.

**ACME, the 2021-03-03 payment of ABC Europe.** The receivable holds its 1,000.00 EUR again. Wise EUR never received them, so the sale of 2021-06-01 takes it to 1,000.00 EUR owed, at that day's 1,472.90 CAD. The sale then exchanges euros the account did not hold for their worth of the day, and in CAD realizes nothing where it realized a loss of 87.90 CAD. The 87.90 CAD is still lost, on the receivable, and not yet realized: the sheet in CAD on 2021-06-01 states 0.00 CAD realized and 251.90 CAD of unrealized loss, where it stated 87.90 CAD and 164.00 CAD. Its assets are the same 3,880.90 CAD. In USD the sale states what it stated and still realizes the 2.55 USD. All 12 balance sheets after the deletion, six currencies on 2021-03-03 and 2021-06-01, agreed with amounts worked out apart from gnucash-plaintext.

**ACMU, the 2021-11-15 software subscription of 300.00 USD that cost 389.64 CAD.** Deleted before the migration and deleted after it, the book comes out the same, every account storing the same in all six currencies. Chase Chequing holds 5,198.34 USD storing 6,643.75 CAD. Each year end from 2022-06-30 has 389.64 CAD more of retained earnings and 14.13 CAD more of realized gain, and values 300.00 USD more: on 2024-12-31, 14,057.83 CAD of assets, 51.82 CAD realized and 1,070.08 CAD unrealized. The book stays consistent and balanced, and its balance sheet balances in each of the six currencies at each year end.

## A long case among three accounts, and the balances as of a date

The author, after the deletions were tested: "no enough, you need to have a very detail and long test cases, with a series of transactions, and the currencies have CAD USD HKD CNY GBP EUR, it must be a long list of transactions among 3 accounts, and assert the balances. Also, need to be able to get balance as of date"

**`fx-balances --as-of DATE`** lists what each account held at the end of a day, in every selected currency. Each split stores what it moved, so the balance is the amounts of the account's splits up to that day added up, with nothing worked out again and no price read. On a book that selected no currencies it is refused: a cost basis balance counts every disposal ever measured against it, whatever its date.

**`tests/scenario/test_eighteen_transactions_among_three_accounts_in_six_currencies.py`** is a book kept in CAD selecting CAD, USD, HKD, CNY, GBP and EUR, with eighteen transactions over 2022 among Chase USD, Wise USD and HSBC HKD: three arrivals, seven moves between the two US dollar accounts, and eight sales between US dollars and Hong Kong dollars, among them an amount of 1,234.56 USD, one of 33,333.33 HKD, and two that empty an account. The case gives the six currencies, three accounts and a long list; which accounts and which transactions are the fixtures'. Each rate is the Bank of Canada's for the day. The test states each account's balance in all six currencies at the end of the day of each transaction, that every currency adds up to zero across the accounts on each of those days, and that the book is consistent and balanced. Every amount was worked out from the rates apart from gnucash-plaintext, and all of them agreed with what it printed on the first run.

## Five behaviours no test stated, and what testing them found

The sixth review of the commit listed five behaviours the message stated and no test exercised. The author: "it is bad with test gaps, need to add". `tests/integration/test_each_command_that_saves_leaves_the_currency_balances_right.py` and two assertions in the tests beside it now state each, on ACMU's migrated book where it applies.

- **`unpost-invoices`.** Unposting the unpaid INV-ABC-4 takes its 1,000.00 USD off the receivable and 1,350.40 CAD off the sales, and the sheet on 2024-12-31 states 12,187.26 CAD of assets and 939.55 CAD unrealized.
- **`unapply-payment`, which found a defect.** Unapplying the payment of INV-ABC-3 leaves 1,500.00 USD owing again and the 1,500.00 USD paid as the customer's credit. No money moved and every account stored what it stored, but `--verify-integrity` then reported that the balance sheet did not balance: 13,105.68 of assets against 12,860.48 of liabilities and equity. The page reads a receivable lot by lot, each lot above zero held and each below zero owed back, and it was handed one row for the account's net of 1,000.00 USD where it counted 2,500.00 USD held and 1,500.00 USD owed. The two did not match, and it measured US dollars from GnuCash's revaluation. A receivable or a payable holding both is now handed a row for each side: what is owed stores what its own lots stored, and what is held stores the rest of the account's. The sheet states the same 13,626.16 CAD of assets and 1,028.05 CAD unrealized as before the payment was unapplied, with a loss of 121.35 CAD on the owed side: the credit stores 2,037.00 CAD and is worth 2,158.35 CAD.
- **A missing price in a command other than `import`.** 50.00 of 100.00 USD buy 45.00 EUR in a book with no price of the euro, which needs none while the dollars paid for the euros. Deleting the arrival of the 100.00 USD leaves the euros to be given the day's amounts of their own currency. `delete-transactions` exits 1 with `Failed to save: Nothing was saved: … the book has no price of EUR in USD`, and the book is as it was.
- **The exit code of an import refused for a missing price** is 1.
- **`fx-balances --verify-costs` on the migrated book** says no cost was checked, and exits 0.
- **The income statement of a book using trading accounts** states the gain as without them, 1.00 CAD and 0.50 HKD, and no section for the trading accounts.

## A book written before `took_the_residual`, and `fx-balances --verify-costs`

The fourth review of the commit observed both, and neither was built until then.

**`--fx-gain-account` is read on a page of such a book.** A book written before `took_the_residual` states a gain as an ordinary split with no mark. With an account passed, a split counts by its account and the mark is not consulted, as for a book keeping cost bases, and an account that is no income or expense account counts nothing. 10.00 USD storing 13.00 CAD exchanged for 14.00 CAD beside an unmarked 1.00 CAD gain: the page states 0.00 CAD realized, and 1.00 CAD with `--fx-gain-account "Income:FX Gain"`.

Building it found what such a transaction stored. With no `$residual$` split nothing is realized, and the first version put what the US dollars gave up, 78.00 HKD and 60.00 CNY, on the gain account, leaving the Canadian dollar account storing nothing in them. Where an account gave something up, the account receiving for it now takes what is left: CAD_B's 14.00 CAD store 78.00 HKD and 60.00 CNY, and the gain account stores 0.00 in each. So such a book's gain is known in its base currency and in no other.

**`fx-balances --verify-costs`** says `No cost was checked: this book records no cost basis.` after the listing, where it said nothing.

## A currency and shares sold in one transaction, and a book that uses trading accounts

Both were first left out, the first as a case no stated case had and the second as "not tried". The author: "this is non sense, if it can be supported as two separate transactions, why cant it be supported in 1 tx? also why not try trading account?"

**A currency and shares sold in one transaction.** One `$residual$` split takes the gain of both, and the first version listed it under neither `realized_gains_fx` nor `realized_gains_other`. The gain on the currency is now what a sale of it alone would state: the currency at the book's price of the day, less what it was stored at. The rest of the split is the gain on the shares. 1 share that cost 7.00 CAD and 10.00 USD storing 13.00 CAD sold together for 24.00 CAD: the 10.00 USD at 1.45 CAD/USD are 14.50 CAD, so 1.50 CAD is on the currency and 2.50 CAD on the share. Writing the test found that the first version also gave the receiving account only the 10.00 USD as its US dollar amount, as if the dollars had paid for all 24.00 CAD. Where two things pay together, what arrives now takes the day's amounts of its own currency: 24.00 CAD are 16.55 USD.

**A book that uses GnuCash's trading accounts.** Tried, it failed three ways, each fixed:

- The import stopped with `'NoneType' object has no attribute 'get_mnemonic'`. GnuCash's top-level `Trading` account is kept in no currency. Such an account is passed over.
- A statement ended the process with a bus error. Reading an income account in the page's currency set split amounts, each of which committed its transaction, and on a commit GnuCash destroys and remakes the trading splits of the transaction. Putting an amount back on a split it had destroyed crashed. A statement now opens each transaction, leaves it open, and rolls it back afterwards, so nothing is committed, in any book.
- The balance sheet in HKD stated 785.00 HKD of assets against 830.96 HKD. With the option on, the page takes the trading accounts' balances as the gain and converts them at the price of the page's date. The book is now read as one that does not use trading accounts for the length of a statement, so each gain is measured from what the accounts store, and the page states the same 0.50 HKD realized and 4.50 HKD unrealized as without trading accounts.

GnuCash's trading splits are no money moved, and store 0.00 in each currency. The accounts of U's book with trading accounts on store what they store without. Checked on GnuCash 3.4, 4.8, 5.10 and 5.15.
