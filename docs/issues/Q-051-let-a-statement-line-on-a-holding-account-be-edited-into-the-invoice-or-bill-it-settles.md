# Q-051 — Let a foreign-currency statement line imported against a holding account, with its bank fee in the same transaction, be edited later into the invoice or bill it settles

## What it should do

**A US dollar statement line imported against a holding account such as "Due from director", with the bank's fee in the same transaction, can be edited in place once the owner knows what it was.**

- **A deposit that was a customer paying an invoice**: the holding-account amount becomes the receivable settling the invoice, the fee's other side the bank charges expense, and the fee draws on the invoice's cost basis.
- **A withdrawal that was paying a supplier's bill**: the holding-account amount becomes the payable the bill is settled by, the fee's other side the bank charges expense, and the dollars and the fee go on drawing on the cost basis they left.
- The same holds when the line turns out to be income or an expense, dollars moved from another of the owner's US dollar accounts with the fee on a split of its own stating its cost basis, or dollars whose fee was part of the exchange spread.
- **A book need not be imported from the day its currency arrived.** Dollars already held when it is started are an opening balance against equity, valued at what they cost; that opens their cost basis, and a later transfer and its fee draw on it like any other.

The owner exports, edits the transaction, and imports it with `--strategy update` and the invoice's or bill's `payment:` block. The format gains no key, no command and no flag.

What makes that possible is how the edit is read: **as the transaction would be read if it were new, and accepted when the new version is a correct transaction and the book is correct afterwards.**

- The new version's cost bases are whatever its shape establishes, and its splits draw what they state, exactly as an import of that transaction into the book would. What the old version established and drew is undone first: a cost basis the old shape needed and the new one does not is not discarded, it is simply not established by the new version.
- The new version meets every check a new transaction meets. So an edit can turn a line that established a cost basis into one that consumes one: a withdrawal read as owed while it sat against the holding account, booked as an expense, states the cost basis its dollars came out of, as a new spend must.
- The book is correct afterwards: every other transaction that draws on a cost basis of this one still draws on a cost basis the new version establishes, at the figures it drew at. Where one does not, the edit is refused, listing that transaction, and the transaction is left exactly as it was.
- An edit that leaves every cost basis as it was is accepted as before (Q-048); that is the case where the new version establishes the same cost bases with the same figures.

## What was reported

The user: "users may import like this Due From -13 CAD Wise +10 USD Due From +1 CAD Wise -0.72 USD ---- later, their customers need to classify these two into A/R -10 USD Wise +10 USD Expense +1 CAD Wise -0.72 USD, which is not possible given current gnucash plaintext".

On what the change is: "The cost basis was created due to some precondition/scenario, after the edit, the new transaction is still in correct shape and book is correct, then we know this is a correct edit, so we dont drop cost basis, it is just that the cost basis was no longer needed in the new outcome!"

And on its reach: "bill and invoice both may face similar use cases!"

## The use case

A bank statement is imported before the owner knows what each line is. Each line's other side goes to a holding account, and the bank's fee comes out of the same line, in the same transaction, its other side on the holding account too. Later the owner learns what each line was and edits it into that.

### A deposit that collects an invoice

As imported:

```
2026-08-13 * "Received money from Example Customer Inc"
	currency.mnemonic: "CAD"
	Assets:Wise USD 2720.00 USD
		value: "3815.89"
	Assets:Due from director -3815.89 CAD
	Assets:Due from director 1.01 CAD
	Assets:Wise USD -0.72 USD
		value: "-1.01"
		cost_basis_split_guid: $transactions_to_import[0].splits[0].guid$
```

US dollars arriving against Canadian dollars leaving an asset is buying US dollars, so the arrival establishes a cost basis at 1.4029 and the fee draws 0.72 from it.

The receipt was the customer paying a 2,720.00 USD invoice posted at 1.393801. As the owner books it:

```
2026-08-13 * "Received money from Example Customer Inc"
	currency.mnemonic: "CAD"
	Assets:Wise USD 2720.00 USD
		value: "3815.89"
	Assets:Accounts receivable:USD -2720.00 USD
		value: "-3791.14"
	Expenses:Bank charges 1.01 CAD
	Assets:Wise USD -0.72 USD
		value: "-1.00"
		cost_basis_split_guid: "<the invoice's posting split>"
	Income:FX gain $residual$ CAD
```

with the invoice's `payment:` block stating the transaction and the receivable's split. The receivable is settled at what it was posted at, 3,791.14, and the fee is valued at what the invoice's cost basis costs; the one `$residual$` split states the difference both realize, −24.76. The new shape is the invoice's collection, which establishes no cost basis: the dollars' cost is the invoice's.

### A withdrawal that pays a bill

As imported, out of dollars the book holds at a cost of 1.35:

```
2026-08-20 * "Paid Example Supplier Inc"
	currency.mnemonic: "CAD"
	Assets:Wise USD -1000.00 USD
		value: "-1350.00"
		cost_basis_split_guid: "<the dollars held>"
	Assets:Due from director 1400.00 CAD
	Assets:Due from director 1.01 CAD
	Assets:Wise USD -0.72 USD
		value: "-0.97"
		cost_basis_split_guid: "<the dollars held>"
	Income:FX gain $residual$ CAD
```

US dollars leaving against Canadian dollars arriving on an asset is selling US dollars, so the withdrawal draws 1,000.00 from the dollars held and realizes the difference against the 1,400.00 the holding account received.

The withdrawal was paying a 1,000.00 USD bill posted at 1.38. As the owner books it:

```
2026-08-20 * "Paid Example Supplier Inc"
	currency.mnemonic: "CAD"
	Assets:Wise USD -1000.00 USD
		value: "-1350.00"
		cost_basis_split_guid: "<the dollars held>"
	Liabilities:Accounts payable:USD 1000.00 USD
		value: "1380.00"
	Expenses:Bank charges 1.01 CAD
	Assets:Wise USD -0.72 USD
		value: "-0.97"
		cost_basis_split_guid: "<the dollars held>"
	Income:FX gain $residual$ CAD
```

with the bill's `payment:` block stating the transaction and the payable's split. The dollars and the fee draw on the dollars held as before; the new shape also repays the bill's cost basis on the owed side, at the 1.38 it was posted at, and the `$residual$` split states the difference, −30.04, where the old shape stated −50.04.

The figures in these examples are the shape of the case; the tests fix each one.

## Why a change is needed

Investigated on 5.10 for the deposit, with the invoice of `tests/fixtures/fx_two_usd_invoices_posted.txt`. No route reaches the booked transaction:

- **The 1.01 moved to the expense on its own** is accepted: the cost basis is as it was (Q-048).
- **Linking the deposit to the invoice with a `payment:` block** is refused twice. Stating only the transaction, it asks which of the two holding-account splits is the payment. Stating the split, it cannot tell how much of the transaction settles the invoice, because the fee's splits are beside the 2,720.00.
- **The booked transaction as an edit in place** is refused: the fee would draw on the invoice's cost basis instead of the deposit's, and an edit in place does not change what a disposal draws on. The refusal says to delete the transaction and import it again.
- **Deleting it and importing the booked version with the `payment:` block** fails and saves a wrong book. Transactions are imported before the invoice's block, so the fee is refused for drawing on an invoice not yet collected, and the whole transaction with it. The `payment:` block then finds no transaction with that guid, records a payment of its own, and the run exits 1 having saved a 2,720.00 USD payment with no fee.
- **The booked version with `--atomic`** commits and saves a book whose cost bases count the same dollars twice: the invoice's 2,720.00 and the deposit's 2,719.28 both open, 6,459.28 USD of cost basis balance against 3,739.28 USD the accounts hold. `fx-balances --verify-costs` exits 0 on it.

The withdrawal booked as the bill's payment was refused before it reached any of that: the update path read no `$residual$` amount — "the amount on split 'Income:FX gain' must be a number, got '$residual$'" — and `$residual$` is how the booked version states what it realizes.

Before Q-050 a fee was a transaction of its own, so the owner could delete it, link the statement line, and import the fee again. With the fee in the line's own transaction there is no piece to take out first.

## The scenarios, and the outcome of each

Each is an edit in place of a transaction imported from a statement, with `--strategy update`.

### Invoices

| | case | outcome |
|---|---|---|
| E1 | The reported case: the deposit booked as the invoice's collection, the 1.01 as the bank charge, the fee drawing on the invoice's cost basis, with the `payment:` block | accepted; the invoice is paid; the arrival establishes no cost basis; the invoice's cost basis holds 2,719.28; the difference the collection and the fee realize is stated; `--verify-costs` clean and the totals level |
| E2 | E1 as a part payment: the deposit settles 2,720.00 of a 4,000.00 invoice | accepted; the invoice is still owed 1,280.00; the fee draws 0.72 of its cost basis, which holds what was collected of it |

### Bills

| | case | outcome |
|---|---|---|
| E4 | The withdrawal booked as the bill's payment, the 1.01 as the bank charge, the dollars and the fee drawing on the dollars held, with the `payment:` block | accepted; the bill is paid; the dollars held are drawn as before, leaving 999.28; the difference is stated as the new version states it; `--verify-costs` clean and the totals level |
| E5 | E4 as a part payment of a 1,500.00 bill | accepted; that bill is still owed 500.00, and the other bill is untouched |

### Either side

| | case | outcome |
|---|---|---|
| E6 | The line booked as income or an expense not invoiced: only the Canadian dollar side moves | accepted as today: the same cost basis at the same figures (Q-048) |
| E7 | The deposit booked as 2,720.00 USD moved from the owner's savings account, whose dollars are an opening balance against equity in a book started part-way through its life, the fee still in the same transaction on a split of its own, drawing on the opening balance's cost basis | accepted, and imported as a new transaction too: the fee says it is what left, and the rest is a transfer, which draws down no cost basis and opens none; the opening balance's cost basis falls by the fee alone, to 2,999.28 |
| E7a | A withdrawal imported as `Due from director +0.72 CAD`, `Wise −1.00 USD`, which establishes a cost basis on the owed side, booked as `Expenses:Bank charges +0.72 CAD`, `Wise −1.00 USD`, stating with `cost_basis_split_guid:` the cost basis the dollars came out of | accepted; the new version establishes no cost basis and consumes the one it states, as a new spend would; the owed-side cost basis the old version established is not established |
| E7b | E7a with no `cost_basis_split_guid:` on the booked withdrawal | refused, as a new spend stating no cost basis is, with the ways to write it; the transaction is as it was |
| E8 | The fee booked as part of the exchange spread: its two splits dropped, the line written net | accepted; the line establishes or draws what the new version states, at its figures |
| E9 | E1, where a later transaction already drew on the deposit's cost basis | refused, listing that transaction: it would draw on a cost basis the new version does not establish; the transaction is as it was |
| E10 | E6, where a later transaction already drew on the deposit's cost basis | accepted: the cost basis it draws on is established with the same figures |
| E11 | A re-price of the deposit's cost basis, where a later transaction drew on it | refused, as today: that transaction drew at the old figures |
| E12 | A re-price where nothing else drew on it | accepted: the new figures are the cost basis's |
| E13 | A new version that would not be a correct new transaction: the fee's `cost_basis_split_guid:` left out, which keeps the pick it has on the deposit the new version establishes no cost basis for; or cleared with `""`, so the fee spends the collected dollars stating none | refused as a new import of it would be, with that import's reasons; the transaction is as it was, and the invoice unpaid |
| E13a | A new version that does not balance | refused before anything is written, and the refusal states what its values come to, which GnuCash would otherwise put on an Imbalance account |
| E13b | The deposit booked as collecting INV-USD-1, with the fee stating INV-USD-2's posting as its cost basis | refused: nothing of INV-USD-2 has been collected, by its lot or by this transaction, so its dollars are owed and the fee has none of them to spend |
| E14 | E1 under `--atomic` | as E1 |
| E15 | A file whose transaction is refused, with an invoice's `payment:` block stating that transaction's guid | the block is refused too, with the transaction's reason, rather than recording a payment of its own |
| E16 | E1 and E4, then `export`, and the ledger imported into a new book | the new book is the booked one |
| E17 | E1 imported without `--include-business-objects` | refused: no `payment:` block is applied, so nothing collects INV-USD-1, and the fee has no dollars of it to spend |
| E18 | E6 on a deposit whose balance a file stated as 2,000.00, or cleared; or with 2,000.00 stated in the edit's own block | accepted, and the balance is 2,000.00, or none recorded, after the edit as before it |
| E19 | E6 on a deposit whose balance a file stated as 0.00, with the fee restated as 1.00 USD | refused: the fee would draw 0.28 more than the cost basis holds once what was sold outside the book stays sold |

## The rule those outcomes follow

**When an edit is read as new.** Wherever it changes anything a cost basis rests on, on a transaction touching a cost basis, and, without `--atomic`, wherever it changes a split's account or amount there. A `$residual$` split's amount follows from the others, so it counts as moved only when its account does. A memo, a description or an unchanged figure is edited in place as before.

**The new version is read as new.** What the old version drew is put back on each cost basis holding a stored balance, and the stored balance of each cost basis it established that nothing else draws on is cleared. The new version is then checked and applied as `create_transaction` checks and applies a transaction: what each split brings in past zero, read afresh; the refusals of a new transaction; the cost bases its own splits draw on, opened first; the draws; the cost bases its shape establishes. `$residual$` is read as the create path reads it. The splits keep their guids and stay in the lots they are in, so a split settling an invoice or a bill is still that record's.

**A balance a file stated stays stated.** A stored balance can hold less than the transaction's own figures come to, because a file stated it: currency sold outside the book. Before the edit, the part of each balance the transaction's figures do not explain is read, and it is put back once the new version's cost bases are open. A deposit of 2,720.00 USD with a stated balance of 2,000.00, booked as income, still holds 2,000.00; opened afresh, it held 2,719.28 and offered again the 719.28 sold elsewhere. Where the new version's own splits then draw more than that leaves, the edit is refused. A cost basis that held no balance holds none after the edit. A balance the edit's own block states is kept as the block states it, and nothing is put back on it, because it is stated net of the file's own disposals.

**The book is correct afterwards.** For each cost basis the old version established: every other transaction drawing on it still draws on a cost basis the new version establishes on the same split, at the figures it drew at. That is what makes E9 and E11 refusals and E10 an acceptance. A cost basis nothing else draws on may change or not be established at all (E1, E7a, E8, E12).

**A part payment is collected up to what it paid.** A receivable cost basis was sellable only once its invoice's lot was settled. What a part payment put in the lot is collected now, so the cost basis can be drawn on up to that much, as the file is imported and in the book `--verify-costs` reads. The draws counted are every split of the transaction stating that cost basis, together, and a split already in the lot is counted once, though an exported `payment:` block applies it again. A block stating `txn_split_guid:` for a split on the invoice's own receivable, with no `prepayment:`, attaches the whole split, so the whole split is what is counted collected.

**Such a block must state the amount the split carries.** It was accepted stating another: a block stating 1,000.00 against the 2,720.00 split left 2,720.00 in the lot and said nothing, and the export then wrote `amount: 2720.00`. Read into a book that never held the transaction, the same block enters a payment of 1,000.00, so the file had two meanings. It is refused now, and the refusal states both figures (`test_a_payment_block_stating_another_amount_than_the_split_it_states_is_refused`). An export states the split's own amount. Not weighed: a block with `prepayment:`, whose `amount:` states what moved through the bank, as the overpayment remedy states 120.00 beside a 100.00 split and `prepayment: 20`, and whose `prepayment:` is weighed against the transaction's other receivable splits, not taken out of the split the block states (`test_a_prepayment_beside_the_split_does_not_divide_it`); and a split parked on another account, which is moved onto the receivable and may be in another currency. The fixture `a_key_spelled_payment_misstating_its_split.txt`, 999 against a 60.00 split, was accepted by design until this change and is refused now.

**A refused edit leaves the transaction as it was.** A new version that does not balance, or that moves or removes a split in a lot, is refused before anything is written. The put-back sets no lot, and does not need to: no edit reaching the commit has taken a split out of one. A balance the refused version stated is not read as stated any more, so a block later in the file drawing on it lowers it. The transaction's type is put back too: the block sets it before the commit, and GnuCash 3.4 to 4.8 store it, so a refused edit stating `txn_type: P` saved a deposit as a payment there. Every other refusal comes after the commit, and the old version is put back as it stood — each split under its own guid, its figures and KVPs, and what it drew from other cost bases taken again.

**The cost bases are compared after the commit.** Until a transaction is committed, GnuCash still lists the splits the edit removes, and a cost read then counts them. Compared before the commit, an edit taking a fee's splits off a purchase read the purchase's cost as unchanged, and was accepted while a sale drew on that cost basis at 25/18 CAD/USD and the book now priced it at 1.4 (`TestWhereASaleDrawsOnTheCostBasis` in `tests/integration/test_an_update_restating_what_prices_a_cost_basis_is_read_as_new.py`).

**A transfer shares a transaction with a fee that states its cost basis.** Left out, the splits stating a cost basis leave the rest of a side to be read on its own: where that is a transfer — as much leaving one account as arrives in another — those splits are what left, and nothing is left unsaid. Where it is not, a split stating a cost basis carries units that only moved, and the transaction is still refused: 4,010.00 USD out of a bank on one split stating its cost basis, 4,000.00 into savings, does not say which 10.00 was the fee.

**Not supported yet: a transfer that carries its cost basis.** That 4,010.00 USD split could be read another way: 4,000.00 USD moved to savings at the cost it had, and 10.00 USD spent. Drawn from a cost basis of 500.00 CAD for 1,000.00 USD, the 4,000.00 would arrive in savings as a cost basis of its own at the same 0.50 CAD/USD, and only the 10.00 would be a disposal. A book could state that, but it would be a special operation, rarely used. It would have to be asked for explicitly on the arriving split, and the importer would never infer it from the shape. Until then the shape stays refused. The refusal says to write the transfer and the fee as two transactions, and one transaction is accepted when the fee is on a split of its own, 4,000.00 USD out of the bank beside 10.00 USD out of it stating the cost basis.

**Dollars collected are not dollars bought.** A split taking currency off a receivable by settling an invoice whose posting is a cost basis — in the invoice's lot, or applied to it by the file's own `payment:` block in a run with `--include-business-objects`, which applies the blocks after the transactions and saves nothing if one is refused — counts. An invoice the same file creates is not in the book when its collection is read, and its posting is, found by the invoice block's `posted_txn_guid:`; read as dollars bought, a book rebuilt from an export kept a balance on the deposit that nothing reads. Such a split counts as that currency leaving the held side, so the bank's arrival beside it only moved and establishes no cost basis. An invoice whose posting prices nothing, booked to an income account kept in its own currency, leaves the deposit's cost basis as the only cost the book has for the money (Q-040), and a stored cost that will not parse prices nothing. A spend beside such a collection states its cost basis, the invoice's, as any spend of held currency does, and the collection in its own transaction is what makes the invoice's cost basis collected for it: up to what the invoice's lot and the transaction have collected between them, so a part payment holds what was paid and no more.

**A restated balance the book holds states nothing.** An export writes every cost basis's balance, so an owner editing one transaction of it restates the rest as the book holds them. Only a figure the file changes is read as a balance stated net of the file's own disposals; noted unchanged, those figures told the fee's new draw on the invoice's cost basis to leave the balance alone. The figure is compared with the balance as the book held it when the run started, and a restated figure is not written. A block earlier in the file may have drawn on the cost basis since: compared with the balance that draw left, the export's figure read as changed, and written back, it undid the draw (`test_a_balance_restated_below_a_sale_that_changed_it_is_not_read_as_stated`).

**`--atomic` defers only where no single block can be right.** The refusal to edit a transaction whose cost basis another transaction draws on is deferred to the finished book, as before, because a repair of it runs through states each block alone is refused in. It is deferred only when what the transaction itself draws, its currency and its date are unchanged. A deferred edit is applied in place, and a disposal applied in place draws nothing. So an edit that re-points or restates a disposal of its own would leave one cost basis short and another undrawn, and it is refused at once. An edit changing a cost basis fact nothing else rests on is read as new, under `--atomic` as without it: deferred, a re-pointed disposal left the cost basis it came from short and the one it joined undrawn, and E1 under `--atomic` left the book counting the collected dollars twice. An edit that only moves a split's account or amount, changing no cost basis fact, is read as new only without the flag. Under `--atomic` it is edited in place and left to the finished book, as every edit was before (`TestTheSameCostBasis::test_booked_as_income_under_atomic`).

**A `payment:` block stating a transaction the run refused is refused.** The money moved in that transaction as the file writes it, so recording a payment from the block would enter it a second way, and settling from the version the book still holds would settle from one the file replaces.

## Other outcomes this changes

Edits Q-048 refused, where nothing else draws on the cost basis, are now read as new, and accepted where the new version is correct. Each test that asserted the refusal now asserts the outcome:

- adding a Canadian dollar split, or restating the transaction's currency, re-prices a cost basis nothing else draws on (`tests/integration/test_an_update_restating_what_prices_a_cost_basis_is_read_as_new.py`); a euro split added to a purchase opens its own cost basis, where it was left `none recorded`;
- a fee with a second split added, or moved a day later, draws what it now states; an arrival moved a day later is still refused while its fee draws on it (`test_an_edit_may_move_the_split_that_sets_the_rate.py`);
- a purchase written with its signs reversed, and a share count, are corrected by an edit in place rather than by delete-and-import (`test_update_strategy_respects_cost_basis.py`, `test_a_security_gets_a_cost_basis_in_the_books_own_currency.py`);
- a disposal restated under `--atomic` draws what it now takes — 400.00 USD out of an account holding 100.00 draws all of it and owes 300.00 — and one re-pointed moves what it drew (`test_an_atomic_run_reads_a_restated_disposal_as_new.py`);
- the Q-040 repair of a deposit an older link left priced can re-point the fee in place and then clear the balance, two runs, as well as one file under `--atomic` (`test_a_book_an_older_link_left_wrong_is_repaired_in_one_file_or_two_runs.py`, `test_recovering_a_book_linked_by_an_earlier_version.py`);
- a disposal edited on a book an earlier import left a cent short, which the edit's own draw now empties, takes what is left of the cost, and the book records the whole realized loss (`test_the_last_disposal_of_a_cost_basis_takes_what_is_left_of_its_cost.py`);
- a fee added by an edit draws on the arrival (Q-050 E9).

Refusals that remain are worded as for a new transaction: a cleared pick is a spend stating no cost basis, a value neither the share nor what is left is refused stating what is left, and a sale beyond what the account holds is refused for the value its past-zero reading requires.

## How long an update takes as the book grows

A statement line is booked by exporting the book, editing the line, and importing the file with `--strategy update`. So the update reads the whole book's export, and its time has to grow in step with the book, not faster. 5,000 transactions can be 10 or 20 years of a small business's book (Q-052).

### What was measured

Two probes drive the real `import` and `export` commands:

- `tests/research/how_long_an_unchanged_update_takes_as_a_book_grows_probe.py` builds books of 500, 1,000 and 2,000 transactions and times the update of each book's own export, unchanged. It profiles the 2,000-transaction run.
- `tests/research/how_long_an_edit_read_as_new_takes_on_a_large_book_probe.py` builds one book of 5,000 transactions and times the update of its export unchanged, with 1, 10, 50 and 200 descriptions changed, and with 1, 10, 50 and 200 statement lines booked as income, which is read as new. It profiles the 200-line run.

Both books hold the same mix, in counts of transactions: three fifths office supplies paid in Canadian dollars only, one fifth purchases of US dollars (each a cost basis), four twenty-fifths sales drawing on those purchases, and one twenty-fifth statement lines, each a deposit against `Assets:Due from director` with its fee drawing on it.

Times are wall clock on one host. The runs on all eleven builds ran four at a time, so a build's times there are a little longer than when it ran alone.

### What was wrong

Profiled at 2,000 transactions on Debian 13 (GnuCash 5.10), the unchanged update took 216.3 s:

| where | time | why |
|---|---|---|
| `transactions_drawing_on` | 169 s | called for each of the 800 transactions touching a cost basis, and each call walked every split in the book: 3.6 million KVP reads |
| `kvp._load_gnc_engine`, inside those reads | 120 s | every KVP read opened the GnuCash library again with `ctypes.CDLL`: 11 million `dlopen` calls |
| `what_each_account_held_without` | 30 s | once per transaction, it summed every split of each account the transaction is on |

`find_split_by_guid` walked the whole book too, on every pick checked and every draw put back. And every block of the file was edited and committed, including every block stating its transaction as the book already holds it. GnuCash pays each commit in proportion to the size of the accounts.

The walks were already on `main`: its unchanged update took the same 9.2 s at 500 transactions. Two steps this branch adds, `_cost_bases_moved_under_other_transactions` and `_clear_what_the_old_version_opened`, walked the book once per edit read as new as well.

### What changed

1. `kvp._load_gnc_engine` is cached, as `_load_gobject` already was.
2. `find_split_by_guid` asks GnuCash's `xaccSplitLookup`, present on 3.4, 5.10 and 5.15, and still returns only a split on an account.
3. Which splits draw on each cost basis is an index of the book (`splits_drawing_on`). It is built by walking the book once, and kept up to date from each change of `cost_basis_split_guid`, which `set_custom_metadata` logs. Each split it returns is looked up and asked again, so a split destroyed since is not returned. `transactions_drawing_on` and the two per-edit steps ask it.
4. `what_each_account_held_without` takes off only the splits of this transaction and of those drawing on it, read from those transactions.
5. **A transaction the file states as the book holds it is up to date, and is not edited.** Up to date means importing the block would write nothing. The transaction's fields, its splits by guid, and each split's account, amount, value, memo, action and KVPs are what the book holds. It is decided against the book's own export: a block reading line for line as the export writes that transaction, blank lines and comments aside. A block stating the same figures written another way (`5.0` for `5.00`, `$residual$`, a position instead of a guid) is edited, as every block was before. Such transactions are reported as `Up to date:   N (no new changes, not edited)` and not as updated, and a file with no new changes saves nothing (`tests/integration/test_an_update_leaves_a_transaction_the_file_states_as_the_book_holds_it_alone.py`).

### Before and after, step by step

The unchanged update, Debian 13 (GnuCash 5.10), new book / update:

| transactions | before | after 1 and 2 | after 3 and 4 |
|---|---|---|---|
| 500 | 1.5 / 9.2 s | 0.7 / 2.5 s | 0.7 / 1.1 s |
| 1,000 | 3.3 / 34.8 s | 2.1 / 9.0 s | 2.1 / 3.2 s |
| 2,000 | 9.7 / 216.3 s | 6.9 / 76.8 s | 7.1 / 15.8 s |

Before, each doubling of the book multiplied the update by about four to six; after 3 and 4, by about three to five. What was left at 2,000 transactions was GnuCash's own `xaccTransCommitEdit` (5.3 s) and `xaccAccountGetBalanceAsOfDate` (3.4 s), paid for every block, which 5 removes for a block with no new changes.

5,000 transactions, Debian 13 alone:

| run | before | after 1 to 4 | after 1 to 5 |
|---|---|---|---|
| new book | 46.3 s | 36.8 s | 36.8 s |
| unchanged update | over 8 minutes, stopped | 58.2 s | 2.2 s |
| 1 / 10 / 50 / 200 descriptions changed | not reached | 58.4 / 58.9 / 59.5 / 59.0 s | 2.4 / 2.6 / 3.0 / 4.8 s |
| 1 / 10 / 50 / 200 lines read as new | not reached | 58.6 / 59.0 / 59.7 / 61.3 s | 2.4 / 2.6 / 3.6 / 7.6 s |

The "after 1 to 5" column is from the run on all eleven builds, four at a time.

### Every supported build, after 1 to 4

The unchanged update, new book / update:

| build | 500 | 1,000 | 2,000 | GnuCash commit at 2,000 | GnuCash balance reads at 2,000 |
|---|---|---|---|---|---|
| Debian 10 (3.4) | 1.0 / 1.4 s | 2.2 / 3.4 s | 5.5 / 13.0 s | 2.9 s | 2.5 s |
| Ubuntu 20.04 (3.8) | 0.9 / 1.3 s | 2.1 / 3.5 s | 6.0 / 15.1 s | 5.0 s | 2.8 s |
| Debian 11 (4.4) | 1.0 / 1.4 s | 2.6 / 4.5 s | 6.5 / 17.1 s | 5.9 s | 3.2 s |
| Ubuntu 22.04 (4.8) | 0.9 / 1.3 s | 2.4 / 4.2 s | 6.1 / 16.7 s | 5.3 s | 3.0 s |
| Debian 12 (4.13) | 0.8 / 1.4 s | 2.0 / 3.6 s | 5.7 / 18.3 s | 5.9 s | 3.3 s |
| Ubuntu 24.04 (5.5) | 0.8 / 1.2 s | 2.0 / 3.6 s | 5.7 / 16.1 s | 5.2 s | 3.2 s |
| Debian 13 (5.10) | 0.8 / 1.2 s | 2.2 / 3.5 s | 7.4 / 18.5 s | 6.4 s | 4.1 s |
| Fedora 41 (5.13) | 0.8 / 1.3 s | 2.3 / 3.8 s | 7.8 / 19.2 s | 6.4 s | 4.1 s |
| Ubuntu 26.04 (5.14) | 0.8 / 1.1 s | 2.0 / 3.2 s | 6.5 / 15.7 s | 4.8 s | 3.3 s |
| Arch (5.15) | 0.8 / 1.2 s | 2.2 / 3.3 s | 6.5 / 16.2 s | 4.7 s | 2.9 s |
| openSUSE (5.16) | 0.9 / 1.4 s | 2.5 / 3.8 s | 7.6 / 16.7 s | 5.2 s | 3.0 s |

No build walks the whole book once per transaction any more. The two largest costs on every build are GnuCash's own.

### Every supported build, after 1 to 5, 5,000 transactions

| build | new book | unchanged | 1 / 10 / 50 / 200 descriptions | 1 / 10 / 50 / 200 read as new |
|---|---|---|---|---|
| Debian 10 (3.4) | 21.8 s | 3.8 s | 4.6 / 4.8 / 5.2 / 7.1 s | 4.7 / 4.9 / 5.5 / 8.4 s |
| Ubuntu 20.04 (3.8) | 27.0 s | 3.4 s | 4.3 / 3.8 / 4.2 / 5.8 s | 3.7 / 3.9 / 4.8 / 8.2 s |
| Debian 11 (4.4) | 34.5 s | 3.5 s | 3.8 / 3.9 / 4.4 / 7.7 s | 3.8 / 4.0 / 5.3 / 9.0 s |
| Ubuntu 22.04 (4.8) | 30.7 s | 3.3 s | 3.5 / 3.7 / 4.1 / 6.3 s | 3.6 / 3.8 / 4.8 / 8.9 s |
| Debian 12 (4.13) | 28.8 s | 2.8 s | 3.0 / 3.2 / 3.6 / 5.4 s | 3.1 / 3.3 / 4.3 / 7.9 s |
| Ubuntu 24.04 (5.5) | 28.3 s | 3.0 s | 3.1 / 3.3 / 3.7 / 5.5 s | 3.1 / 3.4 / 4.4 / 8.2 s |
| Debian 13 (5.10) | 45.4 s | 2.2 s | 2.4 / 2.6 / 3.0 / 4.8 s | 2.4 / 2.6 / 3.6 / 7.6 s |
| Fedora 41 (5.13) | 46.6 s | 2.6 s | 2.8 / 3.0 / 3.5 / 5.6 s | 2.8 / 3.1 / 4.1 / 8.6 s |
| Ubuntu 26.04 (5.14) | 39.6 s | 2.2 s | 2.3 / 3.5 / 2.9 / 4.3 s | 2.4 / 2.6 / 3.5 / 6.6 s |
| Arch (5.15) | 37.1 s | 2.5 s | 3.6 / 2.8 / 3.2 / 4.9 s | 2.6 / 2.8 / 3.7 / 7.4 s |
| openSUSE (5.16) | 39.0 s | 2.9 s | 3.0 / 3.2 / 3.7 / 5.5 s | 3.1 / 3.3 / 4.3 / 7.6 s |

An update now costs about the reading of the file and the book, plus a few milliseconds for each transaction the file changes. On Debian 13 at 5,000 transactions, a line read as new costs about 27 ms and a changed description about 13 ms: (7.6 − 2.2) s and (4.8 − 2.2) s over 200. Profiled, 200 lines read as new spend 7.5 s of 14.5 s in `update_transaction` under the profiler, the largest part writing cost basis balances (2.0 s).

### Known, not yet investigated

- Importing into a new book still grows faster than the book: 0.7, 2.1 and 7.1 s for 500, 1,000 and 2,000 transactions on Debian 13. Each commit is GnuCash's own, and GnuCash pays it in proportion to the size of the accounts. This is the create path, unchanged by this branch.
- A block that states the same figures written another way is edited and committed. An export written by an earlier release can differ from today's export in how it writes a figure, and each such block then costs a commit.

## Cases the tests cover

`tests/integration/test_a_statement_line_on_a_holding_account_is_edited_into_what_it_settles.py`, onto `tests/fixtures/a_usd_invoice_and_bill_for_statement_lines_on_a_holding_account.txt` posted at `tests/fixtures/usd_at_the_rates_the_statement_lines_records_were_posted_at.yaml`. Every test of an edit failed on `main`; the tests of E6, E10 and the fee's owed-side reading as imported passed there, as outcomes that stand.

| case | test |
|---|---|
| E1 | `TestADepositBookedAsTheInvoiceItCollected::test_it_is_accepted_and_the_invoice_is_paid`, `::test_the_deposit_establishes_no_cost_basis_and_the_fee_draws_on_the_invoices` |
| E2 | `test_a_deposit_booked_as_part_payment_of_a_larger_invoice` |
| E4 | `TestAWithdrawalBookedAsTheBillItPaid::test_it_is_accepted_and_the_bill_is_paid` |
| E5 | `TestAWithdrawalBookedAsTheBillItPaid::test_as_part_payment_of_a_larger_bill` |
| E6, E10 | `TestTheSameCostBasis` |
| E7 | `TestATransferBesideItsFee`, the opening balance, the transfer imported new, and the deposit edited into it |
| E7a, E7b | `TestAnOwedFeeBookedAsASpend` |
| E8 | `test_the_fee_booked_as_part_of_the_exchange_spread` |
| E9 | `test_booked_as_the_invoice_after_a_sale_drew_on_the_deposit_is_refused` |
| E11 | `test_an_edit_may_move_the_split_that_sets_the_rate.py::TestRestatingWhatSetsTheRate` |
| E12 | `test_an_update_restating_what_prices_a_cost_basis_is_read_as_new.py::test_adding_a_cad_split_re_prices_a_cost_basis_nothing_else_draws_on` |
| E13 | `test_a_new_version_that_is_not_a_correct_transaction_is_refused`, the pick left out and cleared |
| E13a | `test_an_update_restating_what_prices_a_cost_basis_is_read_as_new.py`, the price stated without a value and a new amount with no value |
| E13b | `test_the_fee_stating_an_invoice_the_transaction_does_not_collect_is_refused` |
| E14 | `TestADepositBookedAsTheInvoiceItCollected::test_under_atomic` |
| E15 | `test_a_payment_block_stating_a_transaction_the_import_refused_records_no_payment` |
| E16 | `TestADepositBookedAsTheInvoiceItCollected::test_the_export_rebuilds_the_book`, `TestAWithdrawalBookedAsTheBillItPaid::test_the_export_rebuilds_the_book` |
| E17 | `TestADepositBookedAsTheInvoiceItCollected::test_without_the_business_objects_the_fee_is_refused` |
| E18 | `TestTheSameCostBasis::test_booked_as_income_keeps_the_balance_a_file_stated`, `::test_booked_as_income_holds_no_balance_where_a_file_cleared_it`, `::test_booked_as_income_with_a_balance_its_own_block_states` |
| E19 | `TestTheSameCostBasis::test_a_fee_drawing_more_than_the_stated_balance_leaves_is_refused` |
| E6, deposited into two accounts | `TestTheSameCostBasis::test_a_deposit_into_two_accounts_booked_as_income` |
| E6, on a balance that will not parse | `TestTheSameCostBasis::test_booked_as_income_on_a_balance_that_will_not_parse_is_refused`: the balance is neither cleared nor reopened, so the fee meets no balance it can read, and the old version is put back |
| E2 edited again, with two sales on the invoice's cost basis | `test_a_second_edit_counts_the_part_payment_once`: 2,720.00 collected, counted once, against the 2,800.72 the fee and both sales draw together |
| a refused edit stating a balance, then a sale restated below it | `test_a_balance_a_refused_edit_states_is_not_read_as_stated` |
| a split in a lot | `TestADepositBookedAsTheInvoiceItCollected::test_booked_back_onto_the_holding_account_is_refused_and_the_invoice_stays_paid` |
