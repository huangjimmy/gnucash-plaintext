# Q-045 — Draw a stock bought with foreign currency from that currency's cost basis, and open a cost basis for the foreign currency a stock sale brings in

Reported by a user probing cost bases on a Canadian book that trades US-listed shares. **Not measured here yet**: this records the report and what has to be run to pin it down. Everything under "What was reported" is the reporter's account, not a measurement of this tree.

## What it should do

**Buying a security with foreign currency spends that currency, and the cost basis it came from is drawn down like any other disposal.**

- A Canadian book holding 10,000.00 USD against a cost basis, buying shares for 3,000.00 USD, has spent 3,000.00 US dollars. The cost basis those dollars came from falls to 7,000.00, and what they cost is what the shares cost — the gain or loss on the currency is realized at that moment, exactly as it is when the same dollars pay a supplier.
- A purchase whose US dollar split gives `cost_basis_split_guid:` is accepted rather than refused. That line is asking for precisely this, and what it asks for is a disposal of currency whatever the money bought.

**Selling a security for foreign currency brings that currency in, and opens a cost basis for it.**

- The same book selling shares for 3,500.00 USD now holds 3,500.00 more US dollars, and what they cost is what the shares were worth when they were sold. That is a cost basis like any other arrival of foreign currency — an invoice collected, a currency bought, a loan drawn.
- Without one, those dollars are in the account and the cost bases do not know them, so `fx-balances` and the balance sheet disagree with the book about how many dollars it holds.

## What was reported

Two faults, on a CAD book that holds US dollars and trades US-listed shares.

**Buying a stock with US dollars is not read as consuming a cost basis, and the import refuses it.** The reporter's purchase gives the guid of the US dollar cost basis the money comes out of, and the run ends with an error rather than drawing that basis down.

**Selling a stock for US dollars opens no cost basis for the dollars received.** They arrive in the US dollar account and no cost basis is recorded against them.

## Why it matters

The two faults are opposite halves of the same gap, and a book that does both ends up with cost bases that do not match what it holds — currency spent that the bases still count, and currency received that they do not.

`tests/fixtures/a_cad_book_with_usd_hkd_and_shares_priced_in_its_price_database.txt` is a book in exactly that state: it buys 10,000.00 USD, which opens a cost basis, then buys and sells shares in US dollars, and not one of those transactions draws the basis down. It still reads 10,000.00 where the bank holds 7,480.00.

**The balance sheet reports that honestly and cannot repair it.** Q-044 gives such a currency GnuCash's own revaluation and says so on the page with `measured_from: gnucash_revaluation`, so the sheet states 940.00 and its items come to 940.00. What no figure on the page can do is put the missing 2,520.00 back on the cost basis, because the disposal that should have drawn it down was never recorded as one.

**This issue is that book's cause**, and fixing it changes what the cost bases hold rather than how the page reports them.

## What has to be measured before this is worked on

Nothing here is measured, and the first job is to make it so. Running, on the default build:

- **the refusal itself** — a ledger buying shares whose US dollar split gives `cost_basis_split_guid:`, imported into a book holding that basis, with the exact message and exit code captured. Without the message there is no telling a refusal from this cause apart from the refusals that are correct, such as a guid that matches no split in the book;
- **whether a purchase that gives no guid is accepted and silently leaves the basis alone**, which is the ordinary-transaction case and the one that put the Q-044 fixture into the state it is in;
- **what `fx-balances --verify-costs` says on such a book**, given that Q-044 measured it finding nothing where a disposal gives no guid — its per-currency question has neither side of such a subtraction to work on;
- **the sale side**: shares sold for US dollars, then `fx-balances`, to see what the dollars received have against them;
- **each of the eleven supported builds**, once the shape is known on one.

## Out of scope

`realized_gains_other` — what a disposal of the *security* made — is Q-043's, and is stated there as planned and not computed. This issue is about the currency on both sides of those trades, not the shares.
