# Q-040 — A link leaves a cost basis behind, and no edit can pick it up

Reported from a real book. Every figure below was measured on GnuCash 5.10 with the fixtures listed at the end.

## The book that started it

A USD receivable, collected into a USD bank, with the transfer fees spent out of it. Exported, the collection reads:

```
2026-08-13 * "Received money from …"
	…Foreign Payments Provider Chequing… 2720.00 USD
		guid: "00e958a8d56547d484d7629000292dc3"
		cost_basis_balance: "2719.28"
	Assets:Current assets:Accounts receivable:USD -2720.00 USD
```

That split has a basis balance written on it and is not a cost basis. Both splits are USD, so the transaction states no CAD figure, so no cost per USD can be derived, so `establishes_cost_basis` is false. `fx-balances` never lists it, `--verify-costs` reports nothing, the 2,719.28 USD in that bank cannot be sold because it has no basis to be measured against, and a fee transaction elsewhere in the book still gives that split's guid in `cost_basis_split_guid:` — so the book's own export no longer re-imports.

## How the book got there

Four steps, each an ordinary thing to do.

1. Two USD invoices are posted. Each A/R posting split opens a basis: 2,720.00 at 381589/272000 CAD/USD, and 1,020.00 at 70691/51000.
2. The bank feed brings the deposit in against **Due from director**, which is CAD. The transaction is therefore stated in CAD, the USD split is given `share_price: "1.4029"`, and that rate is what says what the USD cost. The bank split opens a basis of 2,720.00. Total: 6,460.00 USD.
3. A 0.72 USD transfer fee is measured against that deposit. Its basis falls to **2,719.28**.
4. The deposit turns out to be INV-USD-001 being paid, and is linked to it with a `payment:` block that gives `txn_guid:`. The link moves the CAD Due-from-director split onto the receivable and restates it in USD.

The transaction was `Due From CAD / Bank USD` and is now `A/R USD / Bank USD`. Both splits are USD and so is the transaction, so the bank split has no `share_price:` and no `value:` at all — a split whose commodity is the transaction's own carries neither, and the export writes neither:

```
	…Foreign Payments Provider Chequing… 2720.00 USD
		guid: "00e958a8d56547d484d7629000292dc3"
		cost_basis_balance: "2719.28"
	Assets:Current assets:Accounts receivable:USD -2720.00 USD
```

The CAD side that said what the USD cost is gone, so the cost basis opened from that rate is nonsense: nothing in the transaction prices those USD any more, and the 2,719.28 left on the split is a figure nothing can read. `fx-balances` falls from 6,459.28 to 3,740.00 — 2,719.28 USD leaves the listing with nothing said — while the balance stays written and the fee goes on giving that split's guid.

## Why the import reads this as buying or borrowing USD

`Bank:USD +2720 / Due From −3815.89 CAD` debits a USD asset and credits a CAD asset. That is buying USD. Credit a CAD liability instead and it is borrowing USD. Either way the book gave up 3,815.89 CAD of value and holds 2,720.00 USD, at a cost the transaction states — and the transaction does not balance without a `share_price:` on the USD split, so that cost is always there to read.

**The tool never looks at what the other account is.** `establishes_cost_basis` is given the split that received the USD and asks three things about it:

| asked | of this transaction |
|---|---|
| is the commodity a currency other than CAD | USD, yes |
| is the split in the direction that increases that account's own balance — a debit on a bank, cash, asset, stock or receivable, a credit on a liability, payable or credit card | a debit on a USD bank, yes |
| can a cost be read | 3,815.89 / 2,720.00, yes |

The last one has two branches, because a split's `value:` is stated in the **transaction's** currency. Where the transaction is denominated in CAD, as this one is, `value:` over `amount:` is the cost. Where it is denominated in a foreign currency the same division gives a rate in that currency, and `_base_per_unit_of` converts it using the splits on CAD accounts in that transaction: their CAD amounts added up, divided by what those amounts are worth added up. Every one of them, summed — not whichever is read first, which would make the cost depend on the order the splits are in.

Measured, on a transaction denominated in USD:

| the CAD splits | cost opened on the USD split |
|---|---|
| one, 140.00 CAD for 100.00 USD | 1.4 CAD/USD |
| two at different rates: 2.00 CAD for 1.00 USD, and 142.00 CAD for 101.00 USD | 24/17 CAD/USD |

144 CAD over 102 USD is 24/17, so the second is the sum of both and not either split on its own — 2.00/1.00 is 2, and 142.00/101.00 is about 1.406. Each CAD figure was rounded to the cent separately, so the two disagree in the last digit even though one rate was used to write them.

The other splits are read for the rate and for nothing else.

**It could not look, even if it wanted to.** "Due From Director" is free text on an account of type Asset in CAD. GnuCash has no suspense or clearing account type — the type list is fixed and none of it means "temporary" — and `placeholder:` means something else, an account that takes no transactions of its own. Nothing in the book marks that account as a holding place rather than a real claim on a director.

**And knowing the account would not settle it.** A director who really owes the company 3,815.89 CAD, and settles it by wiring 2,720.00 USD, writes exactly these two lines. There the company did acquire USD at 1.4029 and the cost basis is right. The same transaction is a real settlement or a placeholder, and nothing written down separates them. Measured: a counter-side on `Liabilities:Due to director` gives the identical row.

So the reading is not a guess between alternatives. Guessing from account names is the only other option, and a tool that read "Due From" as temporary would refuse a cost basis to everyone who books real director loans there.

Booking the other side to a **USD** account gives no rate at all. Measured: `…Chequing… +2720.00 USD / Due from director USD −2720.00 USD` opens no basis, and a later link is harmless. This is worth documenting; nothing says it today.

**This is why the fix belongs at the link, not at the import.** The link is the first moment the book holds the missing fact — that the money was INV-USD-001 being paid. Until then the import has only the transaction, and the transaction says buying or borrowing. Once the link says otherwise, the basis the import opened is discarded, because the invoice's own posting split has had a cost basis for that same USD since it was posted.

## The bill side is the same defect with the opposite answer

Measured with a USD bill whose cost is booked to a CAD expense account, paid earlier on a **USD credit line** — the shape the bill-link feature exists for:

| after | listing |
|---|---|
| posting the bill | `Liabilities:Accounts Payable USD` 2,720.00; total 2,720.00 |
| the credit-line payment | `Liabilities:USD Credit Line` 2,720.00 added; total 5,440.00 |
| the link | credit line gone; total 2,720.00, and `cost_basis_balance: "2720.00"` stranded on it |

Mechanically identical — the link removes the only CAD split and the credit-line split loses its cost.

**But the correct end state is the other way round.** On the invoice side the deposit and the receivable are the same money arriving, so one basis survives and A6 below says which: the receivable's. On the bill side they are two different obligations — the credit line you drew on, and the supplier you owed — and the payment moves the obligation from one to the other. Afterwards the credit line is live and the payable is settled, so the credit line's basis is the one that must survive. The link kills exactly that one.

**The settled payable keeps its own balance**, as a collected receivable does. Consuming it was tried and is wrong: what a basis brought in and what it still holds are the two sides `currency_totals_that_disagree` compares, so lowering a balance with no disposal to account for it puts the book's own currency totals out by that amount. Measured — three tests failed, one of them the totals check itself, reporting 100 held against 200 arrived.

## Why no sequence of edits can repair any of it

Every path runs through a state some check refuses.

- `--strategy update` on a basis-touching transaction: *"its amounts, values, accounts, basis picks and the currency it is stated in cannot be edited in place"*. Measured — and it fires even when the edit **cannot** move the basis. Moving the deposit's other split from Due From to Income, with no disposal drawn and the USD split's amount, value and rate all unchanged, is refused. That is an ordinary correction and it is blocked.
- Take the basis off first and the fee points at a split that is no basis; re-point the fee first and its value no longer equals the new basis's cost, so `_require_stated_cost` refuses it.
- The overpaid bill link is refused with instructions to restructure that payment transaction into two A/P splits — and that restructuring is itself an edit to a basis-touching transaction, so the remedy the message gives is unreachable.
- Delete and re-import loses the guid other records give, and the OFX metadata with it.

## Correct behaviour

### Opening a basis — unchanged

| # | case | basis |
|---|---|---|
| A1 | buy USD with CAD | on the USD split |
| A2 | borrow USD against a CAD loan | on the USD split |
| A3 | deposit against Due From director (asset) | on the bank split |
| A4 | deposit against Due To director (liability) | on the bank split, identical to A3 |
| A5 | USD invoice posted | on the A/R split |
| A6 | USD invoice collected into a USD bank by a `payment:` block | A/R keeps it; the bank split gets none |
| A7 | USD income booked straight to a USD bank | on the bank split |
| A8 | USD bill posted | on the A/P split |
| A9 | supplier paid on a USD credit line | on the credit-line split |

The basis is written on the split that received the currency. What the other side is never matters.

### Editing

| # | case | today | correct |
|---|---|---|---|
| B1 | description or memo only | allowed | unchanged |
| B2 | the **other** split's account changes; the basis split is untouched | refused | allow — same amount, same rate, same cost |
| B3 | the basis split's own amount, value or rate changes | refused | allow when nothing has drawn on it, restating the cost |
| B4 | an invoice link replaces the counter-split | leaves the basis behind | take it off: clear the balance, refuse while a disposal draws on it |
| B5 | a bill link replaces the expense split | leaves the basis behind | keep it — write the price onto the split, since the funding account is still owed |

B4 refuses rather than re-pointing the disposal because the two costs need not agree: the invoice posts at one rate and the deposit's USD split was given another, so moving the fee across would silently re-price it, and `_require_stated_cost` would reject that same fee on the next re-import.

Neither touches a split the block has already answered for. Applying a customer's credit takes the basis keys off the part that was spent and moves the balance onto the remainder, so that split stops being a basis with nothing left on it — which is the state this is trying to reach, arrived at by the path that knows how much of the credit was left. Asked without that, the check refused the application of a credit that had been part-sold.

### Advance mode — the escape hatch

For every case the tool does not cover, and for every book already stranded, there has to be a way to state the desired end state and have it applied. Not a batch: a batch still validates each step, and the whole difficulty is that no valid step order exists.

**What one file can already do, measured on the stranded book.** Three repairs, each attempted as a single file under `--strategy update`:

| repair | result |
|---|---|
| clear the stranded balance — `cost_basis_balance: ""` on the deposit split | **works today**, exit 0. That transaction has no split that establishes or picks a basis, so the in-place guard does not fire. Documented nowhere |
| re-point the fee at the receivable's basis | **refused** — its transaction picks a basis, so `_require_no_cost_basis_edit` stops it. This is the one that cannot be worked around |
| both in one file | refused for the fee — **and the book was saved anyway**, with the first transaction's change on disk: `Updated: 1`, `Errors: 1`, `Saving changes… ✓ Changes saved`, exit 1 |

The third is the one that matters most and is easy to miss. A file whose transactions all fail rolls back cleanly — `✗ Nothing was imported` — but a file mixing a success and a failure keeps the success. So a repair file that is half accepted leaves the book half repaired, which is worse than refusing it whole. That is general, not a cost-basis quirk: measured with an ordinary two-transaction file, one good and one posting to an account the book has not got, the good one is on disk at exit 1.

**Built as `import --atomic`, on the model of a database transaction.**

- **It commits or it rolls back.** The rollback costs nothing, because nothing has been written: the session is simply not saved, which is the mechanism every existing refusal already uses. Without the flag the old behaviour stands, because a bank feed wants it.
- **The per-block cost-basis checks are deferred to commit time**, as a database defers a constraint to the end of a transaction. `_require_no_cost_basis_edit` lets the edit through, so a transaction that has a cost basis on it can be restated and a disposal can be re-pointed at another basis. What it goes on refusing is a block restating what a disposal *takes*, for the reason under "One check is deferred" below. `running_atomic()` in `services/foreign_currency.py` is what those checks ask, set from `begin_import_run(atomic)`.
- **The finished book is read instead**, by `_what_the_book_gets_wrong` in `cli/import_cmd.py`, before a byte is saved: every question that sets `--verify-costs`'s exit code, including the ones no listing covers — a disposal drawing on a split that is no cost basis in the book the file leaves, valued against a cost that basis no longer has, or against a receivable nobody has collected. Every failure is listed, not the first. The per-currency totals are **not** among them: they are a warning that says on the page that nothing is refused over it, and a book with a divided credit cannot level them at all, the arrived side counting what the remainder holds while the sale that drew on the pool is still the size it was.
- **Exit 1 on rollback**, including where every block applied and only the result was wrong, which produces no per-block error at all.

A stated `cost_basis_balance:` is the balance **after** the file has landed, net of its own disposals. So the reported book's repair is three blocks — the receivable at 2,719.28, the deposit's balance cleared, the fee re-pointed at the receivable — and no order of those three is legal one at a time.

**One transaction. Whatever a ledger file can express, it restates** — accounts, amounts, values, splits added and removed, and the cost-basis keys outright. It commits whole, or it rolls back and nothing changed.

**One check is deferred**, and it is the one that made the repair impossible: `_require_no_cost_basis_edit`, *"touches a cost basis … cannot be edited in place"*. `running_atomic()` has that single call site.

**And not where the finished book cannot ask the question it is standing in for.** `a_sale_valued_against_another_cost` answers only for a disposal stated in the book's own currency — a transaction between two foreign currencies states its values in neither — so a basis with only foreign-stated disposals beneath it had nothing checking it at commit time. Measured: a 100.00 USD purchase at 1.40 with a USD-stated 10.00 USD fee drawn on it, re-priced to 1.50 under `--atomic --strategy update`, exited 0, saved the book, and `--verify-costs` called it sound. `a_disposal_the_finished_book_cannot_value` is asked before the deferral is granted, and the refusal names the disposal that makes it so.

**It is deferred for the figures a cost basis rests on, and not for the figures a disposal takes.** A basis balance falls only where `apply_cost_basis_picks` draws it down, and that runs from `create_transaction` alone, so an edited disposal is never measured against what its basis holds — and the finished book cannot stand in, because the balance reads the same whether the edit landed or not. Measured: the 10.00 USD fee in `test_a_repriced_basis_is_caught_under_its_sales.py` restated as 400.00 USD valued at 560.00 CAD — 1.40 × 400, so the sale is valued at exactly what its basis cost — imported with `--strategy update --atomic`, exited 0, saved the book, and left a 400.00 USD disposal against a basis still offering 90.00, which `--verify-costs` called sound. So `_no_disposal_takes_a_new_figure` compares the rows for the splits that pick a basis and lets the *pick* differ: re-pointing the fee is what the repair does and moves no figure, while a restated one is refused as it lands, flag or no flag. Every disposal the book holds has to be one the file states, so dropping the `cost_basis_split_guid:` line is refused as well — "a sale that draws on nothing takes nothing" is true of the state the file asks for and says nothing about the state it leaves, the currency having come out of the basis when the sale was imported. `give_back_to_cost_bases` is called from the delete path and from nowhere else, so an edit cannot return it. `test_an_atomic_run_cannot_restate_what_a_disposal_takes.py` pins both halves.

The other per-block checks still fire wherever they ran before — `_require_stated_cost` and `_require_basis_collected`, both through `_validate_pick`, along with `_validate_pick`'s own refusal of a `cost_basis_split_guid:` that gives a split which is no cost basis. The per-sale drawdown is not deferred either: a file that states a balance is already exempt from it, through `_stated_in_file`, which predates this and is not part of `--atomic`.

**"Wherever they ran before" is narrower than it reads, and that is why the finished book is asked the same two questions.** `_validate_pick` is reached from `apply_cost_basis_picks`, which `update_transaction` never calls: on the update path those checks did not run at all, and `_require_no_cost_basis_edit` — the one thing `--atomic` defers — was what stood in their place. So a block editing a transaction under this flag could restate a basis's `value:` beneath the sales measured against it, or state a balance on a receivable the customer has not paid and sell against it, and nothing per-block would have looked. Both are among the questions asked of the finished book, which is what closes it.

That is a real limit and it is worth stating plainly. The repair in `test_a_repair_with_no_legal_step_order.py` gets past `_require_stated_cost` only because the deposit and the invoice happen to cost the same figure — 2,720.00 × 1.4029 rounds to the 3,815.89 the deposit states — so a repair whose two rates differ is still refused, and the disposal has to be deleted and written again. Deferring those checks as well is the work this leaves undone.

**What is asked of the finished book**, after everything is applied and before anything is saved:

- every `cost_basis_split_guid:` gives a split that is a cost basis in the book the file leaves;
- that basis holds the currency the disposal sells;
- the disposal is still valued at what that basis cost, and a receivable it draws on has been collected;
- every basis balance is at least zero and no more than what its split brought in;
- every stated cost parses, and does not contradict a transaction that prices its own split;
- no `cost_basis_balance` on a split that is no cost basis.

The per-currency totals are **not** among them. `--verify-costs` prints those as a warning which says on the page that nothing is refused over it, and a book with a divided credit cannot level them at all — the arrived side counts what the remainder holds while the sale that drew on the pool is still the size it was — so rolling back on them would refuse ordinary work.

Every violation is listed, not the first. And only what this file **adds**: the same questions are asked before it is read, and a fault already in the book is not a reason to refuse a file that neither caused it nor claimed to fix it. A book being repaired is very often wrong somewhere else too, and refusing over that would leave it unable to accept any import at all.

**What is deliberately not asked** is whether the bases offer more than the accounts hold. That is not an invariant this model keeps — an account that received 60.00 USD and paid an 8.00 USD fee out of the same transaction holds 52.00 and offers 60.00, and that book is correct — and the module docstring of `services/foreign_currency.py` says so. A check on it reports ordinary books, which is what a first draft of this did.

### Reporting

`fx-balances --verify-costs` gains **two** checks, one for each half of the fault. The first is a `cost_basis_balance` stored on a split that is no cost basis, reported with the reason the split is not one, taken from `establishes_cost_basis`'s own tests in its own order. On the reported book:

> this split stores `cost_basis_balance: '2719.28'`, but it is no cost basis: nothing says what its currency cost: every split in its transaction is USD, so there is no CAD figure to divide, and no `cost_basis_cost` is stored on it either.

The **balance** alone. A stored `cost_basis_cost` on a split that is no basis is genuinely inert — `_stored_cost_is_ignorable` drops it from the export, so it neither travels nor round-trips — and reporting it would set the exit code over a figure the exported file does not contain. A credit the book has spent is the one split that keeps its cost through both, and it is not inert there: nothing reads it while the split settles the record, and it is what prices the split when that record is unposted. See "Spending an owner's credit" below. `test_verify_costs.py::test_a_spending_split_is_not_a_basis_however_its_cost_reads` pins that, and caught this check when it was first written too broadly.

The second check is a disposal whose `cost_basis_split_guid:` gives a split that is no cost basis, or no split at all. Clearing the stranded balance does not clear this: the guid stays on the sale below it, and once the balance is gone no figure is stored anywhere wrong, so every other check passes and the book reads sound while a sale is measured against something that is not a basis. It shows up on the way out — the export writes the guid, and re-importing that ledger is refused with "matches a split that is no USD cost basis" — so a book whose own export cannot rebuild it would otherwise be reported as sound. On the repair in "Why no sequence of edits can repair any of it", clearing the balance on its own is exactly the state it reports.

A basis the book **consumed** is not one of these, and telling the two apart is the whole difficulty. See "Spending an owner's credit" below.

The same walk asks the other half of the question: where the guid *does* give a cost basis, is the sale still valued at what that basis cost? `_require_stated_cost` asks this of every sale in a file and only of a file, so a sale already in the book is never asked again — and `--atomic` defers `_require_no_cost_basis_edit`, which is what otherwise stops a block restating a basis transaction's `value:`. A basis re-priced from 1.40 to 1.50 under a 10.00 USD fee valued at 14.00 CAD satisfies every other check: the balance is inside its bounds, there is no stored cost to disagree, the fee draws on a real basis, and the totals level. The book saves, `--verify-costs` says every cost agrees, and the export is refused on the way back in because 14.00 is not 1.50 × 10.

**A third check was written and removed**, and the reason is worth keeping. It compared, per currency, what the bases on holding accounts offer against what those accounts hold — on the reported book, 3,740.00 against 3,739.28, a 0.72 gap that points straight at the split with the stranded balance. It reports ordinary books. An account that received 60.00 USD and paid an 8.00 USD fee out of the same transaction holds 52.00 and offers 60.00, because a basis is lowered only by a disposal that gives its guid; the module docstring of `services/foreign_currency.py` sets that out and says in as many words that a check on it would report ordinary books. The check's own test built exactly that shape — a bank fee with no `cost_basis_split_guid:` — and asserted the warning, which should have been the signal. It cannot tell a stranded basis from an ordinary fee, so it is not a check.

## Taking a wrong link off

Discarding the basis has to be reversible, because the person who linked the wrong transaction only finds out afterwards. What they run is `unapply-payment <book> <invoice> --to <account>`: it takes the settling split off the receivable and gives it the account `--to` states, restated into that account's currency. Write the base-currency account the money came from there and the transaction is `Due From CAD / Bank USD` again, which is a purchase of USD.

The split that holds the foreign currency is a cost basis again the moment that happens, and nothing has to be written for it: the transaction prices it as it did before. Where the account `--to` states is another USD account instead, both sides are USD, nothing says what the currency cost, and it is no basis — also right.

**The balance does not come back, and nothing opens one.** Opening it at the split's full amount was written and taken out again. Nothing here can tell a balance this tool removed from one that was never written: a deposit entered in the GnuCash GUI is a cost basis reading `none recorded`, a link leaves it alone because there is no stored balance to take, and opening one on the way back would offer currency that may be long since spent. `update_transaction` refuses exactly this, and its comment records what it cost when it did not — "Correcting a description was enough to do that to every such basis in a book."

So the split comes back listed and priced with no balance recorded, and the listing already says what to do: state `cost_basis_balance:` on it in an import file. On the reported book that is one line, against a figure the listing is printing two columns to the left, and the USD total then reads 6,460.00 again — what it was before the link.

**The rate does not survive, and that is worth stating plainly.** The link overwrote the base-currency amount that held it — 3,815.89 CAD — so nothing in the book says 1.4029 any more. The unapply restates the split from `--fx-rates` at the transaction's own date, and the reopened basis is priced at whatever that file says. Measured with a rates file stating 1.20 for 2026-08-13: the split comes back as −3,264.00 CAD and the basis at 1.2 CAD/USD, so what the director is owed moves with it.

**A rate is carried forward where the file quotes nothing for the day, and the run says so.** `rate_fraction` takes the most recent quote on or before the date — `usable = [d for d in quotes if d <= as_of]`, then `quotes[max(usable)]` — so a file quoting 2026-07-31 and 2026-08-31 answers for 2026-08-13 with a figure thirteen days old. That is why the first measurement of this looked lossless: 2026-07-31's 1.4029 happens to be the deposit's own rate, and it matched to the cent by coincidence.

Refusing would be wrong — a rates file states the days it states, and demanding a quote for every date would stop ordinary unapplies dead — so the run warns instead, on stderr, saying which day the rate came from and which day it was asked for. What turns on it is the base-currency amount written into the book and the price of the basis reopened above it, and nothing else on the page would have said the figure was not a rate for that day. `FxRates.quote_date` is what answers it; it asks only whether a dated quote was involved, so no currency is assumed to be the book's own.

## Spending an owner's credit, and the sale already measured against it

The disposal check found a second book this tool wrote and could not read back, in a place unrelated to the reported one. Spending part of a customer's credit divides the split it comes from: the part applied keeps the source split's guid and settles the record, and the currency still unsold moves to a remainder, which is a new split with a guid of its own. A sale already measured against that credit kept giving the old guid — and the old guid matched the settlement.

Measured, on a 100.00 USD credit with 80.00 sold against it and 30.00 then applied to an invoice: `--verify-costs` reported the sale, the listing counted `0.00 USD was sold against a basis` where 80.00 had been, and re-importing the book's own export was refused. The fix is that the sale goes to the remainder, because that is where the pool it drew on continues. Both ways a credit is divided do it: a `txn_split_guid:` block giving the credit's guid, which this tool divides, and `auto_apply_credit: true`, which GnuCash divides.

**And whether or not the credit carries a basis key**, which is the shape both paths were reading by. A credit overpaid from a CAD bank stores no cost, being priced by its own transaction; spending it on an invoice takes its balance; and an unpost hands it back carrying neither key, with the sale still giving its guid. `_carry_basis_to_residue` returned before the move where there were no keys to carry, and `_basis_splits_on` — which is what the engine-carve walk is given — collected only the splits carrying a key or a bank-paid orphan mark, so that credit was never looked at at all. It walks the whole posted account now, and both paths move the disposals whatever the split carried: what has to follow a carve is not always written on the split being carved. Left as it was, the sale ended up drawing on the part that settles the invoice — marked as a credit the book consumed, which is exactly what stops `--verify-costs` reporting it and makes the export drop the guid, so the fault could only be seen by rebuilding the book and finding the whole remainder offered as unsold.

**Spending a credit in full is not a fault, and is not refused.** A credit is money owed back to the owner, not a particular pile of currency, so an overpayment settling that customer's next invoice in full is the commonest thing an overpayment is for, and whether the company converted some of that currency in the meantime has no bearing on whether the credit can be applied. Refusing it was written and backed out: it would have blocked ordinary bookkeeping to satisfy a check.

What that case needs instead is for the book to be able to state it. Nothing is left for the sale to move to, so it keeps giving the credit's guid — a basis the book **consumed**, rather than one that never was. `establishes_cost_basis` says no to both, so `is_a_spent_credit` is what tells them apart — and it is asked on the way **out**, not on the way in. `_validate_pick` refuses a guid that gives a split which is no cost basis, whatever is written beside it, and there is no exception: believing `applied_from_credit` there would let a file write that key onto any split and have a sale skip the drawdown, the over-sell refusal, `_require_basis_collected` and `_require_stated_cost` together. Instead the export drops the guid for a pool the book consumed (`_the_basis_it_gives_was_spent`), exactly as it drops a `cost_basis_cost` on a split that is no basis, so the file never carries a line the import would refuse. `what_the_disposals_get_wrong` asks the same question, and does not report the book for keeping the guid it dropped.

It asks two things, and the `applied_from_credit` mark alone is not one of them. The export emits that key and fixtures state it, so unlike `orphaned_by_unpost` it is not something only the book can know — and what it decides here is whether a sale's guid is taken or refused. So the book is asked as well: the split has to sit in a lot a record owns, which is what settling an invoice or a bill with a credit does and what no file can assert on its own behalf. Unposting that record empties the lot of its invoice again, and the answer is then no, which is right — the credit is loose and spendable once more, and every check applies to it.

Accepting it is no weaker than what the format already allows. A sale may leave `cost_basis_split_guid:` out entirely and draw on nothing — that is what an ordinary bank fee does — so a guid that gives a pool since used up buys nothing a blank line does not. A guid that was never a basis is still refused, and `test_a_guid_that_was_never_a_basis_is_still_refused` pins it by pointing a sale at the first invoice's settlement, which sits in the same transaction on the same account and lowers its USD the same way.

The two paths that spend a credit write the same thing, which is why one test answers for both: `_mark_spent_credit` for a block giving the credit's guid and `_mark_applied_from_credit` for the engine's own application each take `cost_basis_balance` off and write `applied_from_credit: true`. So neither leaves a stranded balance for the first check to find, and both leave the mark the second one reads.

**The cost stays where the balance goes.** A balance is how much of the currency is still there to sell, which spending ends; a cost is what the currency was acquired for, which spending does not change, and it is the only thing that can price the split again if the record it settles is later unposted — a credit paid in the record's own currency carries no base-currency figure anywhere in its transaction. Stripped, an unpost handed back a split that was neither a cost basis nor a spent credit. The export keeps it for the same reason: `_stored_cost_is_ignorable` drops a stored cost from any split that is no cost basis, and a credit settling a record is not one, so a ledger written while the credit was spent carried no cost at all and the book rebuilt from it could not price the split at all. `is_a_spent_credit` is the exemption, beside the one `_the_basis_it_gives_was_spent` already makes for the guid.

**Three places take a spent credit's keys off, and the third is the one to watch.** `_mark_spent_credit` and `_mark_applied_from_credit` are the two a reader finds by name; `_carry_basis_across_applied_credit` is the third, and it writes the applied part's slot before `_mark_applied_from_credit` re-reads it, so a cost dropped there is dropped for good and the reader of the other two sees a rule that is not being kept. All three take the balance and leave the cost now. Measured on the shape that shows it: a 100.00 USD credit priced only by a stored cost, 40.00 of it carved onto a second invoice by `auto_apply_credit:`, that invoice then unposted — the applied part came back neither a cost basis nor a spent credit, and `fx-balances` listed 40.00 USD of currency nothing could price.

## The order a ledger states its transactions in

The last book this found is the one the fixtures below build, sound, with nothing wrong in it at all. The deposit of step 2 and the fee of step 3 share the day they are posted, carry no `num`, and are entered a moment apart by two import commands — so GnuCash orders them by description, which is the register's own order and puts "Charges for: TRANSFER-0000001" above "Received money from Example Customer Inc". The export wrote them that way, and `cost_basis_split_guid:` is resolved as each block is applied: the fee gives the guid of a split no block above it has created, so the ledger was refused with "matches no split in the book". Every figure in that book agrees and `--verify-costs` reports nothing, because nothing in the book is wrong — the file is.

Measured in `tests/research/what_order_a_book_keeps_same_day_transactions_in_probe.py`, which also settles where the order comes from: `qof_query_run` hands transactions over in `xaccTransOrder` already, so sorting by the posted date alone was the same order arrived at by accident. The export sorts on `xaccTransOrder` now and says so.

The exception is stated in README under "What order an export writes transactions in": a transaction holding a cost basis is written above any transaction that draws on it. It does not ask which of the two is dated first, so a basis dated after its sale is written above the sale and the file goes out of date order rather than out of readability; where two transactions draw on each other no order reads back and the book's own is written, holding every transaction it holds. A running balance is added up over the book in its own order regardless, because a balance is a figure as at a date.

**The same guarantee belongs to every command that writes a ledger.** `export-transaction --guid` takes the guids in the order they are typed, and asking for a fee and then the deposit it draws on is the natural way to ask. The undo copy `delete-transactions -o` writes is worse than out of order: a cost basis cannot be deleted while a sale measures against it, so the guids *have* to be given sale-first, and the copy came out in that order with the transactions it was the only copy of already gone.

That copy had a second fault of the same shape. Deleting a sale gives its currency back to the cost basis it drew on, so the deposit, written out after the fee had gone, stated 2720.00 USD — the whole of what it brought in, rather than the 2719.28 the book held while both existed. A balance a file states is taken as already net of the sales below it, so re-importing the copy left the book offering 0.72 USD the bank does not hold. Every transaction such a run deletes is written out before any of them is deleted now, and the run holds each transaction's guid rather than the transaction, so a guid named twice is refused the second time by the book instead of being destroyed twice.

## Fixtures

- `fx_two_usd_invoices_posted.txt` — step 1
- `fx_usd_deposit_against_due_from_director.txt` — step 2
- `fx_fee_drawn_from_the_deposits_basis.txt` — step 3
- `fx_rates_usd_two_invoice_dates.yaml` — the two posting rates
- `fx_usd_bill_with_a_cad_expense.txt` and `fx_supplier_paid_on_a_usd_credit_line.txt` — the bill side
- `fx_invoice_spending_a_part_sold_credit_in_full.txt` and `fx_invoice_auto_applying_the_whole_credit.txt` — a credit spent in full, named by guid and left to the engine

Step 4 is not a fixture: the test exports the book and puts the `payment:` block into the invoice's own block, which is what a person does and what makes the rates match — a hand-written rate of 1.4029 is not the 381589/272000 the book holds once the value has reached the cent.

A6 is unchanged and already covered, by `fx_invoice_usd_paid_from_usd_bank.txt`.

All anonymised: the account numbers, the payment provider, the customer and the supplier are invented; the dates, the amounts and the rates are the ones the book held.
