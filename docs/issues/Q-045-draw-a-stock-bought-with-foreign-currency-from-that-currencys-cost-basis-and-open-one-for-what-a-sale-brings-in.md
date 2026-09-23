# Q-045 — Draw a stock bought with foreign currency from that currency's cost basis, and open a cost basis for the foreign currency a stock sale brings in

Reported by a user probing cost bases on a Canadian book that trades US-listed shares. Everything under "What was reported" is the reporter's account. Everything under "What was investigated" was run against this tree on GnuCash 5.10 by `tests/research/whether_trading_a_stock_in_foreign_currency_moves_its_cost_basis_probe.py`, which builds one book with a cost basis on each side and puts ten transactions through it, each on a book of its own.

## What it should do

**Buying a security with foreign currency spends that currency, and the cost basis it came from is drawn down like any other disposal.**

- A Canadian book holding 10,000.00 USD against a cost basis, buying shares for 3,000.00 USD, has spent 3,000.00 US dollars. The cost basis those dollars came from falls to 7,000.00, and what they cost is what the shares cost — the gain or loss on the currency is realized at that moment, exactly as it is when the same dollars pay a supplier.
- A purchase whose US dollar split gives `cost_basis_split_guid:` is accepted rather than refused. That line is asking for precisely this, and what it asks for is a disposal of currency whatever the money bought.

**Selling a security for foreign currency brings that currency in, and opens a cost basis for it.**

- The same book selling shares for 3,500.00 USD now holds 3,500.00 more US dollars, and what they cost is what the shares were worth when they were sold. That is a cost basis like any other arrival of foreign currency — an invoice collected, a currency bought, a loan drawn.
- Without one, those dollars are in the account and the cost bases do not know them, so `fx-balances` and the balance sheet disagree with the book about how many dollars it holds.

**And the same wherever foreign currency goes out, because a stock is not what makes it a disposal.** The investigation below found the same fault on US dollars sold for Canadian ones and on US dollars sold for Hong Kong ones, so the rule has to be about the currency rather than about what it bought:

- currency leaving a side draws that side's cost bases down, and the difference between what it cost and what it fetched is realized there and then;
- currency arriving on a side opens a cost basis, costed in the book's own currency;
- **currency moving between two accounts of the same commodity does neither**, because the book still holds every unit of it. A rule that draws a basis down whenever a foreign split is negative destroys cost basis on a transfer, and one that opens a basis whenever a foreign split is positive invents it — `import` does the second today, which is what case 6 measures.

**A disposal that does not say which cost basis it came out of is refused.** Not picked for, by any rule — not the oldest basis, not the largest, not the one that makes the figures come out flattest. Which basis a disposal drew on decides the gain it realized, so choosing one on the reader's behalf is `import` inventing a figure their file never stated, and it would be undiscoverable afterwards because the resulting book is perfectly well-formed. That is the same rule `$residual$` and `took_the_residual` already follow on the currency side, and the same reason `--fx-gain-account` makes the reader state the account rather than guessing it from account types.

The file states it: `cost_basis_split_guid:` on the split that spent the currency. That is the one thing that settles which basis was drawn down, and a ledger without it is a ledger that has not said. What the import may not do is accept such a ledger, leave the bases untouched, and let a balance sheet discover months later that the book holds less currency than its cost bases claim.

## What was reported

Two faults, on a CAD book that holds US dollars and trades US-listed shares.

**Buying a stock with US dollars is not read as consuming a cost basis, and the import refuses it.** The reporter's purchase gives the guid of the US dollar cost basis the money comes out of, and the run ends with an error rather than drawing that basis down.

**Selling a stock for US dollars opens no cost basis for the dollars received.** They arrive in the US dollar account and no cost basis is recorded against them.

## Why it matters

The two faults are opposite halves of the same gap, and a book that does both ends up with cost bases that do not match what it holds — currency spent that the bases still count, and currency received that they do not.

`tests/fixtures/a_cad_book_with_usd_hkd_and_shares_priced_in_its_price_database.txt` was a book in exactly that state: it bought 10,000.00 USD, which opened a cost basis, then bought and sold shares in US dollars, and not one of those transactions drew the basis down. It read 10,000.00 where the bank held 7,480.00.

**The balance sheet reported that honestly and could not repair it.** Q-044 gives such a currency GnuCash's own revaluation and says so on the page with `measured_from: gnucash_revaluation`. What no figure on the page can do is put missing currency back on a cost basis, because the disposal that should have drawn it down was never recorded as one.

**This issue is that book's cause**, and fixing it changes what the cost bases hold rather than how the page reports them. The fixture now gives the guid of the cost basis each disposal draws on, and states its share purchase and sale in Canadian dollars. Its cost bases hold 3,480.00 USD against the 7,480.00 the bank holds, and the 4,000.00 between them is a borrowing written wholly in US dollars, which states no cost to open a cost basis at.

## What was investigated

**The invariant everything below is read against**: per currency and side, what the cost bases hold is what the accounts hold. Never added across currencies — US dollars and Hong Kong dollars in one figure is a quantity of nothing, which is why the balance sheet's own block states no `cost_basis_balance` above its commodity groups.

The book: 10,000.00 USD bought at 1.30 and held, 5,000.00 USD borrowed at 1.30 and owed. Both sides start in agreement.

| # | transaction | gives a guid | after |
|---|---|---|---|
| 1 | shares bought with USD | yes | ✓ USD asset bases 15,000 → 11,000, agrees |
| 4 | the loan repaid | yes | ✓ USD liability bases 5,000 → 3,000, agrees |
| 2 | shares bought with USD | no | ✗ bases 15,000, accounts 11,000 |
| 7 | the same, stated wholly in USD | no | ✗ bases 15,000, accounts 11,000 |
| 9 | 1,000 USD sold for CAD | no | ✗ bases 15,000, accounts 14,000 |
| 5 | the loan repaid | no | ✗ neither side drawn down |
| 3, 8 | shares sold for USD, stated in CAD and in USD | — | a 2,200 basis opens for the dollars received |
| 6 | 4,000 USD moved between two USD accounts | no | ✗ bases 19,000, accounts 15,000 |
| 10 | 1,000 USD sold for 7,800 HKD | no | ✗ USD bases 15,000 against 14,000; HKD 7,800 = 7,800 |

**Every arrival is handled, and handled correctly.** A currency coming in opens a cost basis whether it arrives from a share sale, from Canadian dollars, or from another foreign currency, and it is costed in the book's own currency: case 10 opened 7,800.00 HKD at 0.16667 CAD, which is the 1,300.00 CAD the dollars were worth. Neither side of that transaction is CAD — the figure comes from the `value:` its splits carry, which is there because the transaction is stated in CAD. Written wholly in USD or HKD there would be no CAD figure to cost either side from, which is the ground Q-044's `measured_from: gnucash_revaluation` fallback covers.

**No departure is handled at all.** Currency leaving draws nothing down unless the ledger hands over `cost_basis_split_guid:` by hand, and nothing refuses a ledger that does not. The realized gain on those disposals is never taken either.

**So the subject is wider than the title.** It is not stocks: case 9 is plain US dollars sold for Canadian ones and fails the same way, and case 10 fails between two foreign currencies. What the two faults have in common is a disposal of foreign currency that does not say which basis it came out of. Stocks are where the reporter met it.

**A transfer is the case that makes "just pick a basis" wrong.** Case 6 moves dollars between two accounts of the same currency: the book still holds every one of them. Both halves are mishandled in opposite directions — the receiving split reads as an arrival and opens a 4,000 basis, the paying split draws nothing down — so the bases are *inflated* by 4,000. Drawing one down there would destroy basis the book still owns.

**The rule that separates them is the net per side within the transaction**, and the guid-given path already computes exactly this, which is why cases 1 and 4 come out right:

| transaction | asset side | liability side | what has to happen |
|---|---|---|---|
| USD moved between two USD accounts | 0 | 0 | nothing |
| shares bought with USD | −4,000 | 0 | draw 4,000 from the asset bases |
| shares sold for USD | +2,200 | 0 | open a 2,200 basis |
| the loan repaid from the USD bank | −2,000 | −2,000 | draw both down |
| USD borrowed into the USD bank | +5,000 | +5,000 | open both |

Summing the splits cannot do it: a transfer is +4,000/−4,000 and a loan repayment is +2,000/−2,000, and both come to nothing. One holds all its dollars and the other has retired debt with dollars that are gone. Only the split by side tells them apart.

## What the refusal asks, worked out against the whole suite

Put in as "a side that lost units and gave no guid is refused", the check turned away 171 tests and 51 fixtures' worth of files that were not disposals at all. Three questions came out of reading them, each a case where nothing left:

**What the side holds has to fall, and an account below nothing holds nothing.** The sum of a transaction's amounts is not the fall in what a side holds, and the difference is every clearing account in the suite. `tests/fixtures/money_parked_in_usd_that_reached_a_cad_bank.txt` writes 139.00 CAD into a bank against −100.00 USD parked on a suspense account, for a `payment:` block to place on the receivable afterwards; the suspense account goes from 0.00 to −100.00, so read as a sum it spent a hundred dollars and read as a fall it spent none. It owes a hundred. The same rule answers `Imbalance-<CUR>`, which GnuCash makes for a transaction that does not add up and takes negative from nothing, and it needs no rule of its own: `tests/fixtures/account_balance_test_data.txt` left 6,640.00 HKD over in one and read as a disposal of 415.00 Hong Kong dollars nobody spent.

**Netted across the side**, so 4,000.00 USD moved between two US dollar accounts is no disposal — one account falls and the other rises by the same.

**A side the book keeps no cost basis for is left alone.** There is nothing to draw down and nothing to state, and `fx-balances` lists no row for the refusal to send its reader to. Asked without this, every book whose accounts are in one currency that is not the one gnucash-plaintext records costs in was refused its own payments: `tests/fixtures/beancount_export_edge_shapes.txt` keeps its bank and its expenses in East Caribbean dollars, and a 25.00 cheque out of that bank was turned away. A cost basis on a receivable or a payable does not count for this either — it is consumed by the settlement of the record it belongs to, through its lot, never by the arithmetic of a disposal — so a book whose only US dollars are an owner's credit is not asked about spending that credit.

With those three, the suite passes, and the files that then had to change are the ones that genuinely did dispose of currency without saying so.

## How a file refers to a cost basis it opens itself

Nothing had to be added to the format. A split block may state its own `guid:`, which the import obeys on a split it is creating — Q-016 added it so a payment block could refer to a split by guid — so a file that opens a cost basis and consumes it in the same run writes the guid on the arriving split and gives the same guid to the disposal below. `tests/fixtures/fx_sell_usd_half_cent_residual.txt` buys 45.00 USD and sells it in one file that way, and `tests/fixtures/account_balance_test_data.txt` opens 8,000.00 HKD and spends 300.00 of it.

The alternative, which every fixture layered on another book uses, is to read the guid out of `fx-balances` after the arrival is in the book and write it into the disposal's file.

## A balance sheet always balances, and what stops one is worth finding

A page balances when `total_unrealized_gains` is the difference the other three figures leave, and those three are GnuCash's: every account converted at the report-date price, and retained earnings from the income and expense totals. So the unrealized figure is not free, and a page that does not balance is a page stating an unrealized gain that contradicts the three figures around it.

**The way to find which transaction did it is to build the book one transaction at a time and draw both statements after each.** `tests/research/which_transaction_stops_a_balance_sheet_balancing_probe.py` does that, and prints beside each step what the cost bases hold against what the accounts hold, so the two questions are asked together. On the ledger as it stands, all 25 steps balance and this page's figure equals GnuCash's own at every one of them.

**One transaction breaks both, and it is a security bought with foreign currency.** Investigated on the same book with the borrowing restated in Canadian dollars, so the owed side had a cost to be measured from. Steps 4 to 6 balance; step 7 does not:

```
  #         assets   liab+equity  difference  unrealized     gnucash   transaction
  6       27980.00      27980.00        0.00     1300.00     1300.00   Consulting collected, Q1
  7       30252.00      29772.00     -480.00     3092.00     3572.00   Buy 20 AMZN at 200.00 USD
```

480.00 is 4,000 × (1.42 − 1.30). The purchase spends 4,000.00 US dollars that **cost 5,200.00 CAD**, and draws that cost basis down by exactly that — but the shares are recorded as 4,000.00 USD, and every conversion afterwards re-prices that figure at the report-date rate, 5,680.00. The cost that left the currency is not the cost that arrived on the shares, and the difference is what the page cannot carry.

**The 12.00 further down is the same fault on an expense.** `Expenses:Interest` is kept in US dollars: 100.00 USD of interest paid with dollars that cost 130.00 CAD, which the income statement converts at the report-date price to 142.00.

So it is one defect in two places, and it is [Q-046](Q-046-give-a-security-a-cost-basis-in-the-books-own-currency-so-a-sale-realizes-a-gain-the-way-a-currency-disposal-does.md)'s: when foreign currency is spent, what it cost goes with it. This issue's own opening says the same thing — *what they cost is what the shares cost* — which is why the two are worked in one change.

**Both are settled by that change.** The shares now take the 5,200.00 CAD the dollars cost, so on the same variant, with the borrowing stated in Canadian dollars at 1.35, step 7 balances and the cost bases agree with the accounts:

```
  #         assets   liab+equity  difference  unrealized     gnucash    retained  bases/accounts         transaction
  6       27980.00      27980.00        0.00     1300.00     1300.00     1000.00  agree                  2025-07-30 * "Consulting collected, Q1"
  7       30252.00      30252.00        0.00     3572.00     3572.00     1000.00  agree                  2025-08-15 * "Buy 20 AMZN at 200.00 USD"
```

The interest is the other place, and an expense account kept in US dollars is one gnucash-plaintext does not support: Q-046 says why, and both statements warn about it.

**The same variant found one more transaction, and it is refused now.** Its loan repayment is written wholly in US dollars. It pays off debt that cost 1.35 a dollar with dollars that cost 1.30, so it realizes a difference, and a transaction with no split in Canadian dollars cannot state one. Imported as written, it left the page unbalanced from that step on by exactly the difference: 75.00 on 1,500.00 USD repaid, investigated with the interest taken out. So such a repayment is refused as it lands, and told to state itself in Canadian dollars with a `$residual$` split. Where both sides cost the same a dollar nothing is realized, and it is imported. `tests/fixtures/a_us_loan_repaid_in_a_transaction_stating_no_canadian_figure.txt` writes all three.

## Known, not yet investigated

- **The reporter's refusal.** It does not reproduce: the purchase that gives the guid exits 0 and draws the basis down, stated in CAD and stated in USD, on the asset side and on the liability side. Either their ledger differs from anything built here or it was fixed between their run and this investigation. Their file settles it in one run.

Everything above was investigated on GnuCash 5.10. The integration tests written from it run on all eleven supported builds.

## Out of scope

`realized_gains_other` — what a disposal of the *security* made — is [Q-046](Q-046-give-a-security-a-cost-basis-in-the-books-own-currency-so-a-sale-realizes-a-gain-the-way-a-currency-disposal-does.md). This issue is about the currency on both sides of those trades, not the shares.

**The two share one mechanism**, which is why they are worked together: once a share's cost is held in the book's own currency, a security is a holding with a cost basis exactly as a foreign currency is, and both are drawn down by a disposal that says which basis it came out of. A book that buys shares with US dollars makes two disposals — the dollars leaving, and later the shares — and the change these two issues are worked in handles both.
