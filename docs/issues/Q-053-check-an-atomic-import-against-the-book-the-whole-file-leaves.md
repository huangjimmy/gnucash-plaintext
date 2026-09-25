# Q-053 — Check an `--atomic` import against the book the whole file leaves, so a booking can be undone or done again in one file

## What it should do

**An `--atomic` import applies every block of the file and checks the book once, before it is saved.** A database transaction with every constraint deferred works this way: each statement runs, and the constraints are checked at commit. Nothing is refused because of the order the file's blocks are applied in. If the finished book is wrong, nothing is saved.

**An owner undoes a booking by importing the export they kept from before it.** A statement line was imported against a suspense account and later booked as the invoice it collected. The booking turns out wrong. The owner kept the export from before the booking, and imports it with `--strategy update --include-business-objects --atomic`. The deposit returns to the suspense account, the invoice to unpaid, and every cost basis to what it held.

gnucash-plaintext keeps no history, so it does not know the file is an undo. It applies the file and checks the book the file leaves. Importing the export taken after the booking books it again, the same way.

A block wrong in itself is still refused where it stands: an account the book has not got, a guid nothing can parse, a transaction that does not balance.

## What was reported

The user, on undo: "many users they need to support undo". And on the two-step route the tool offered, `unlink` and then an import: "this is bad, we force them to do 2 separate writes"; a delete and re-import "is a hack-workaround, not business workaround".

On what gnucash-plaintext can know: "gnucash plaintext dont keep the undo, the users keep, so gnucash plaintext dont know if it is undo! The only way gnucash plaintext can do is, leave the rejection/refuse at then end of operation before save!"

On what `--atomic` should be: "then --atomic should be all constraints deferred".

And on the tests: "gnucash plaintext dont know undo, but test case know what is undo!"

### The request this was for

A user's application links a US dollar deposit to the invoice it collected. The bank's export writes the deposit and its 0.72 USD fee as two transactions stated in US dollars, the fee drawing on the deposit's cost basis. The application imports the invoice's block with a `payment:` block giving the deposit's transaction and the bank account, and nothing else. Reproduced with the test book's names (`tests/fixtures/a_usd_deposit_and_its_fee_stated_in_usd_as_two_transactions.txt`, `tests/fixtures/inv_usd_1_paid_by_linking_the_deposit.txt`):

```
invoice "INV-USD-1"
	…
	payment:
		bank_account: "Assets:Wise USD"
		txn_guid: "0e530000000000000000000000000b21"
```

On #115 (`5cc252e`), with `--atomic`, it is refused: "linking this payment discards the cost basis on split … but 1 disposal(s) are measured against that cost basis: 2026-08-13 'Charges for the deposit' (0.72 USD)".

#115 did not record this request and did not test it. Its tests booked the deposit by editing the deposit's own transaction, its split moved onto the receivable, with a `payment:` block giving `txn_split_guid:`. The request links the deposit by `txn_guid:` and `bank_account:`, and that link is checked in the invoice's block, which read the fee as the book held it, and which is not applied again once refused.

What each file does:

- **The link alone.** Once the deposit pays the invoice, its dollars are the invoice's collected dollars, and the deposit's split is no cost basis. The fee still gives that split as the cost basis it draws on, and the import does not choose another for it: a cost basis is what the file gives. So the link alone is refused, and the refusal says what to add, the fee restated in the same file drawing on the invoice's cost basis, imported with `--atomic`.
- **The link and the fee restated, in one file, with `--atomic`.** Accepted. The link reads the fee's version in the file, so it does not count the fee as drawing on the deposit's cost basis, and it does not read the deposit's balance, short by the 0.72 the fee drew, as currency sold outside the book. The fee is applied again once the link has collected the invoice, drawing on the invoice's cost basis.

### A refusal says what kind of transaction it refused

The same application then imported the deposit and three lines after it with no `cost_basis_split_guid:` on any of them (`tests/fixtures/a_usd_deposit_and_three_sales_of_it_giving_no_cost_basis.txt`). Each line credits Wise USD, a Bank account, in US dollars and debits Assets:Due from director, an Asset account, in Canadian dollars: 0.72 USD for 1.00 CAD, 2,710.68 for 3,758.36, 8.60 for 11.92. So each is a sale, and a sale gives the cost basis it draws on. Each was refused, correctly, but the refusal said "this transaction spends 0.72 USD the book held", which read as an expense. The person refused could not see why it was refused, and asked why an asset and a liability were read as an expense. The application also cut the refusal where it listed the line to add, so what they had ended at "one of:".

The refusal now says what kind of disposition the transaction is, and the splits it read that from, each with its account type and currency and whether it is debited or credited:

```
this transaction is a sale of 0.72 USD the book held for 1.00 CAD:
Assets:Wise USD, a Bank account in USD, is credited 0.72 USD; Assets:Due from
director, an Asset account in CAD, is debited 1.00 CAD. A sale requires a
consumption of one or more cost bases, but no split says which.
```

There are only so many kinds, and the account types say which: a purchase, where a security is debited; a repayment, where a balance owed in the same currency is reduced; a payment, where a receivable or a payable in the same currency is debited; a sale, where a balance-sheet account in another currency is debited; an expense, where an expense account is debited; and a refund, where an income account is debited. An edit that makes a transaction one of these without giving a cost basis is refused the same way, as "this edit makes the transaction a sale of …".

### A disposal may be imported pending its cost basis

An application importing statement lines as they arrive does not always know yet which cost basis a line draws on: that is decided when the lines are reclassified. `cost_basis_split_guid: $pending$` says so, and the book is then in a known state, its disposals pending, which every check reads as pending rather than as wrong.

**How it is written and kept.** Unquoted, between `$`, as a position is (Q-050). Written in quotes it means the same, since no split's guid is `$pending$`. The split's `cost_basis_split_guid` KVP holds the string `$pending$`, the key a guid would be kept under. The export writes it back unquoted, so a book holding one is rebuilt from its export with it still pending.

**Where it may be given.** Only on a split disposing of a holding, and of all its amount: one bringing currency in, on a receivable or payable, or in the book's own currency is refused, since it would be counted as a pending disposition of nothing, and so is one crossing zero, a disposition of part and a borrowing of the rest, or beside another account of its side, a transfer of part, since the balance sheet takes a pending split off whole. Only where the book keeps a cost basis of that currency on that side, since the balance sheet takes a pending disposition off those, and a disposition where none is kept needs no pick; a book keeping no cost bases at all refuses the key as it refuses every cost basis key. And only where its transaction states a figure in CAD for all it disposes of, which is what the balance sheet takes it off the cost bases at: the second loan of `a_us_loan_repaid_in_a_transaction_stating_no_canadian_figure.txt`, repaid wholly in US dollars with the bank's pick made `$pending$`, is refused, where taken off at nothing it would have left its whole cost on what the cost bases still hold. An unchanged export imported again with `--strategy update` edits nothing and saves nothing: the file's side of the comparison reads `$pending$` as no pick, as the book's does. What a pending split moves on each side is recorded when it is imported, as it is for a split giving a guid, so a transaction imported later and dated before it leaves it as it was: 100.00 USD moved out of Wise on 14 August, before the pending sales of the 17th, leaves all three pending and `--verify-costs` passing.

**What is relaxed while it is pending.** Every reader of which cost basis a split draws on reads `$pending$` as no pick, so nothing is drawn down and no check of a pick is asked of it: which cost basis, its currency, its side, whether it holds enough, whether an invoice's was collected, whether the value is its cost. The refusal of a disposal giving no cost basis counts `$pending$` as said. `--atomic` accepts a file that leaves disposals pending.

**What is enforced once a cost basis is chosen.** An edit giving the split its guid is read as a new transaction is: what the old version drew is given back, every check a new transaction meets runs, and the cost basis the guid gives is drawn down. The fee given the deposit's cost basis this way drew it from 2,720.00 to 2,719.28. Made `$pending$` again by a later edit, it gives the 0.72 back, and the cost basis is at 2,720.00 again.

**What each check says.**

- `fx-balances` lists each pending disposal and what they add up to, per currency: `3 disposal(s) pending their cost basis, drawing on none until an edit gives it: 2,720.00 USD`, then one line each.
- `fx-balances --verify-costs` exits 0 and ends `Checked 5 cost basis(es): every cost agrees with the figures it is derived from. 3 disposal(s) are pending their cost basis.` A pending disposal is counted, and is no finding.
- `--verify-integrity` exits 0. Before this, it reported two things wrong with the book holding the three pending sales: the USD cost bases on the held side held 9,440.00 against the 6,720.00 the accounts held, and the balance sheet did not balance, since its unrealized gain was worked out from cost bases still counting the 2,720.00 the sales took. The cost bases are now counted net of the pending disposals, and the check reads `checked: no cost basis holds more of a currency than the accounts do, beside 3 disposal(s) pending their cost basis: 2,720.00 USD, which drew on none`.
- The balance sheet takes the pending disposals off the cost bases as a row of their own per currency and side, at what their transactions recorded in CAD, so no gain is stated for a disposal whose cost is not decided. With `--itemize` it lists the row as `split_guid: $pending$`, `account: "pending their cost basis"`, `cost_basis_balance: -2720.00`, `cost_value: -3771.28`.

**Once every pending disposal is given its cost basis, the book is consistent.** Giving the three sales the deposit's cost basis leaves nothing pending, the cost basis at 0.00 against the 0.00 Wise USD holds, and `--verify-costs` and `--verify-integrity` passing with no pending line. A pending sale given BILL-USD-1's cost basis, dollars owed, is refused and stays pending, and so is one given INV-USD-1's while that invoice has not been collected.

That last test found a fault older than `$pending$`. The same three sales imported with their picks, as the application sends them, failed `--verify-integrity` on `main`: "the balance sheet does not balance: it states -19.86 of assets against 0.00 of liabilities and equity". Their Canadian dollar splits state what the dollars fetched, 3,771.28, and the dollars cost 3,791.14; the 19.86 lost is in no split, since a transaction stated in US dollars cannot hold a Canadian figure there, and the balance sheet read each sale as having taken exactly its cost. It now reads such a sale at what its Canadian dollar splits record, where it is the only split of its transaction drawing on a cost basis and they value the whole of it, and states the 19.86 as `realized_gains_not_recorded: -19.86`, the key a realized gain the book did not record is stated under. The page balances. That figure is the balance sheet's only: the rule that values the last disposal of a cost basis at what is left of its cost counts the rounding of the disposals before it and not this, so a last sale written in CAD at its own cost, 11.99 for 8.60 USD, is accepted after the 2,710.68 sold in US dollars, and the 19.79 that sale lost is not put on it.

**A pending split that cannot stand is reported, whoever put it there.** The import refuses one, but a book can be changed elsewhere. `--verify-costs` and `--verify-integrity` ask the same questions of every pending split in the book and report each that fails, with its reason, and the balance sheet leaves it out rather than take it off the cost bases wrong. `$pending$` written onto the deposit's own arrival through GnuCash's bindings is reported as "it is no disposition: it disposes of nothing the book holds or owes", both checks exiting 1.

**Nothing makes a pending disposal be resolved.** The book stays pending, and `fx-balances` and `--verify-integrity` say so, until an edit gives each its cost basis.

## Why a block was refused over its place in the file

An import applies the transactions first and the invoice and bill blocks after them. Read one block at a time, each of these is refused:

| the file | the block refused | why |
|---|---|---|
| a deposit and its fee, two transactions, booked as INV-USD-1's collection, the fee moved onto the invoice's cost basis | the fee | the invoice's `payment:` block, applied after the transactions, has not collected it yet: "the invoice it belongs to has not been collected … Record the payment first" |
| the same | the deposit | the fee's old version, still in the book, draws on the deposit's cost basis, which the deposit's new version does not establish |
| the same | INV-USD-1's `payment:` block | the deposit it gives was not imported |
| the export from before the booking: the deposit back on the suspense account, INV-USD-1 with `payment: none` | the deposit | its split is still in INV-USD-1's lot: "take it out of the lot first" |
| the same | INV-USD-1 | it cannot be unposted while the deposit's fee draws on its cost basis |

No order suits every file. A booking wants the transactions first, and the file that undoes it wants the payment blocks first. The first three refusals are also a cycle: each block waits for another.

## What `--atomic` does

**A refused transaction block is applied again once the rest of the file is in the book.** Passes repeat for as long as one applies something. Each pass runs the same path and the same checks as the first, so the fee is applied once INV-USD-1's `payment:` block has collected the invoice.

**What depends on another block is asked of the book the file leaves.**

- A split drawing on a cost basis draws on what the file's version of its transaction gives. When the deposit is edited, the fee's old version is still in the book, drawing on the deposit's cost basis, but the file's version of the fee draws on the invoice's. So the deposit may stop establishing its own.
- A split settling an invoice or a bill, given another account, is taken off that record first, as `unapply-payment` takes it off, and the import says which record and which transaction. That happens only where the file states the record and none of its `payment:` blocks gives that transaction. A record the file does not state, one it still pays with that transaction, the record's own posting and an owner's credit are not taken off, and the edit is refused as it is without the flag.
- An account's balance, read to see whether an arrival crosses zero (Q-047), leaves out the transactions whose version in the file draws on the arrival. Otherwise the fee's booked version, still in the book when the deposit is put back, made Wise USD read −0.72 without the deposit. The deposit was then read as repaying 0.72 and bringing in 2,719.28.

**What no order can apply is applied in place, and checked at the end.** That is two edits each refused while the other still reads as it was: a cost basis another transaction draws on, and that transaction's draw, restated together. The in-place edit runs only after a pass applies nothing. Run first, as it was before this change, it kept the cost basis the deposit's old version had, 2,720.00 on a split that is no longer a cost basis, and the finished book was refused over it.

## What stays

**The memo a `payment:` block wrote.** Booking INV-USD-1's collection writes the block's memo, "Received money from Example Customer Inc", onto the deposit's bank split and receivable split. The export from before the booking has no `memo:` line on either. A line a file leaves out says nothing about it (README, "What a key says, and what leaving it out says"), so the memo stays after the undo. Every other line of the export is as it was.

## An edit keeps the moment a transaction was posted at, where the day stays

The export writes a day's transactions in GnuCash's own order, `xaccTransOrder`, which reads the moment each was posted at. An edit set the posted date from the file's day with `SetDatePostedSecsNormalized`, which puts it at 10:59 UTC, even where the day did not change.

GnuCash 3.8 posts an invoice at midnight. The undo edits INV-USD-1's posting block, since the file restates its cost basis balance, and on 3.8 that moved the posting from 00:00:00 to 10:59:00 on 2026-07-31, the same day. It then came after INV-USD-2's posting, so the export after the undo held every line it held before in another order, and `fx-balances` listed the two cost bases in another order too. On 5.10 every posting is at 10:59 already, and nothing moved. The same held for any transaction entered at another time, in GnuCash's own register for one.

An edit sets the posted date only where the file moves the day. `test_the_export_keeps_its_order` asserts that the export after the undo is the export from before, line for line, but for the memo, and failed on 3.8 before the change. The other tests compare the export's blocks and the listing's rows in no order, so a failure there says the book changed, and a failure of the order test says the order did.

## Known, not yet investigated

- An invoice or bill block is applied once, after the transactions, and the first one refused ends the run. So a `payment:` block giving a transaction refused in the first pass is refused ("is a transaction this file states, and it was not imported") even where a later pass applies that transaction. In the booking above, INV-USD-1's block is not refused because the deposit is applied in the first pass: its check reads the fee's version in the file. Applying invoice and bill blocks again is not done, because a refused invoice or bill can leave part of its change in the book, which a transaction block's own edit does not.

## Cases the tests cover

`tests/integration/test_an_atomic_import_brings_a_book_back_to_a_state_it_exported.py`, on `a_usd_invoice_and_bill_for_statement_lines_on_a_holding_account.txt`. Every case of an undo, a booking in one file, or a booking done again failed on `main`.

| case | test |
|---|---|
| a deposit and its fee as two transactions, booked as INV-USD-1's collection in one file | `TestTheFeeAsATransactionOfItsOwn::test_the_booking_is_accepted_in_one_file` |
| that booking undone by the export kept from before it | `TestTheFeeAsATransactionOfItsOwn::test_the_export_kept_from_before_brings_the_book_back` |
| booked again by the export taken after it | `TestTheFeeAsATransactionOfItsOwn::test_the_booking_imported_again_books_it_again` |
| the fee left drawing on the deposit's cost basis: refused, and the book file unchanged byte for byte | `TestTheFeeAsATransactionOfItsOwn::test_a_file_whose_finished_book_is_wrong_changes_nothing` |
| two fees of one day on the same accounts, the second drawing on dollars bought below it and applied in a later pass: both imported, the second not taken for a duplicate of the first | `test_a_block_applied_again_is_no_duplicate_of_one_the_run_created` |
| a new transaction whose `guid:` nothing can parse: refused, applied again, refused again, and listed in the summary, with the book file unchanged | `test_a_block_whose_guid_nothing_can_parse_is_refused_and_listed` |
| an undo whose fee gives a cost basis the book has not got: rolled back, and it says no payment was taken off | `TestTheFeeAsATransactionOfItsOwn::test_a_rolled_back_undo_says_no_payment_was_taken_off` |
| the fee in the deposit's own transaction (Q-051 E1), undone and booked again | `TestTheFeeInTheDepositsOwnTransaction` |
| a withdrawal booked as BILL-USD-1's payment (Q-051 E4), undone and booked again | `TestAWithdrawalBookedAsTheBillItPaid` |
| a split in a lot the file does not take off: the invoice not stated, still paid by the transaction, the invoice's own posting, an owner's credit | `TestASplitInALotTheFileDoesNotTakeOff` |
| the export after an undo is the export from before, line for line and in the same order, but for the memo; failed on 3.8 before an edit kept the moment a transaction was posted at | `test_the_export_keeps_its_order` |
| the request this was for: a deposit and its fee stated in US dollars as two transactions, the invoice's `payment:` block linking the deposit by `txn_guid:` and `bank_account:`, and nothing else: refused, saying to restate the fee in the same file, and the book file unchanged | `test_a_deposit_linked_to_its_invoice_with_its_fee_restated_in_one_file.py::test_the_link_alone_is_refused_saying_to_restate_the_fee_in_the_same_file` |
| the same link with the fee restated in the same file, drawing on the invoice's cost basis: accepted, and `fx-balances --verify-costs` finds nothing wrong. Refused on #115: the link read the fee as the book held it, and the deposit's cost basis, short by the fee's 0.72, was read as currency sold outside the book | `…::test_the_link_and_the_fee_restated_in_one_file_are_accepted` |
| the same link with the fee restated keeping its US dollar split and giving no cost basis: the fee is a spend refused for that, the whole file is rolled back, and the book file is unchanged | `…::test_the_link_and_the_fee_restated_giving_no_cost_basis_are_refused` |
| the deposit and three sales of it, each stated in US dollars with its Canadian dollar split at the day's rate and giving the deposit's cost basis, as the application sends them: imported. #116 valued such a sale against its cost basis through its Canadian dollar split and refused 2,710.68 USD sent at 3,758.36 CAD, dollars that cost 3,778.15. That split states what the dollars fetched, not what they cost, and a transaction stated in US dollars has no split that can record the difference in Canadian dollars, so the check was taken out: the balance sheet states that difference as a realized gain the book did not record | `…::test_three_sales_of_the_deposit_each_giving_its_cost_basis_are_imported` |
| the fee corrected to 0.73 USD at the invoice's cost, 1.02 CAD: accepted, Wise USD and the invoice's cost basis both at 2,719.27 | `…::test_the_fee_restated_onto_the_invoice_drawing_another_amount_at_its_cost_is_accepted` |
| the fee restated onto INV-USD-2, not collected: refused | `…::test_the_fee_restated_onto_an_invoice_not_collected_is_refused` |
| the fee restated onto BILL-USD-1, dollars the book owes: refused, saying the bank's dollars are held. Accepted on #115, leaving Wise USD at 2,719.28 while INV-USD-1's cost basis offered 2,720.00, and the bill's cost basis at 999.28 against 1,000.00 owed | `…::test_the_fee_restated_onto_a_bill_is_refused` |
| the link giving the fee's transaction, another bank account, or the deposit's bank split as `txn_split_guid:`: refused | `…::test_the_link_giving_the_fee_s_transaction_is_refused`, `…::test_the_link_giving_another_bank_account_is_refused`, `…::test_the_link_giving_the_deposit_s_bank_split_is_refused` |
| the deposit and three sales of it giving no cost basis: each refused as a sale, listing Wise USD, a Bank account, credited in US dollars and Due from director, an Asset account, debited in Canadian dollars | `…::test_three_sales_of_the_deposit_giving_no_cost_basis_are_refused_as_sales` |
| the deposit and three sales of it each giving `cost_basis_split_guid: $pending$`: imported drawing on nothing, the deposit's cost basis still at 2,720.00, `fx-balances` listing 3 pending disposals of 2,720.00 USD, and the export writing `$pending$` back; the fee then given the deposit's cost basis by an edit, which draws it to 2,719.28; and the book rebuilt from its export, the three still pending; `--verify-costs` and `--verify-integrity` pass and count the three as pending, and the balance sheet balances, listing them as their own row | `…::test_sales_pending_their_cost_basis_are_imported_drawing_on_nothing`, `…::test_a_pending_sale_given_its_cost_basis_by_an_edit_draws_it_down`, `…::test_a_book_holding_pending_sales_is_rebuilt_from_its_export`, `…::test_verifying_the_costs_counts_the_pending_sales_and_finds_nothing_wrong`, `…::test_verifying_the_book_counts_the_pending_sales_and_finds_nothing_wrong`, `…::test_the_balance_sheet_lists_the_pending_sales_at_what_they_were_recorded_at`, `…::test_a_balance_sheet_drawn_before_a_pending_sale_leaves_it_out` |
| every pending sale then given the deposit's cost basis: nothing pending, the cost basis spent to what Wise holds, `--verify-costs` and `--verify-integrity` passing, and the balance sheet stating `realized_gains_not_recorded: -19.86`; a pending sale given a bill's cost basis, or an uncollected invoice's, refused and still pending | `…::test_every_pending_sale_given_its_cost_basis_leaves_the_book_consistent`, `…::test_a_pending_sale_given_a_bill_s_cost_basis_is_refused_and_stays_pending`, `…::test_a_pending_sale_given_a_cost_basis_holding_less_is_refused_and_stays_pending` |
| `$pending$` on 3,000.00 USD credited to Wise holding 2,710.68 refused, a disposition of part and a borrowing of the rest; on 100.00 USD credited to Wise of which 60.00 is debited to USD Savings refused, a transfer of part; a transfer dated before the pending sales leaving all three as they were imported | `…::test_pending_on_a_sale_of_more_than_the_account_holds_is_refused`, `…::test_pending_on_a_split_beside_a_transfer_is_refused`, `…::test_a_transfer_dated_before_the_pending_sales_leaves_them_as_they_were_imported` |
| an edit refused for giving no cost basis, with a typo in the account of either of its splits: refused as "Account not found", the book file unchanged, before its splits are read for the kind of disposition | `test_an_edit_that_adds_a_disposal_is_refused.py::test_the_same_edit_with_a_split_on_an_account_the_book_does_not_have_is_refused` |
| 50.00 USD refunded out of Wise, Income:Sales debited, giving no cost basis: refused as a refund, listing the income account; the 8.60 USD fee booked with its 0.07 CAD loss on Income:FX gain at a value of nothing: only the transfer's 19.79 stated as not recorded, `--verify-integrity` passing; a card repayment giving `$pending$`: the owed side netted to 1.00 USD, `--verify-integrity` passing; `$pending$` added by an edit to the deposit's arrival refused | `…::test_a_refund_giving_no_cost_basis_is_refused_as_a_refund`, `…::test_a_loss_a_sale_stated_in_usd_records_on_a_split_of_no_value_is_not_stated_again`, `test_a_split_draws_on_a_cost_basis_by_its_position_in_the_file.py::…::test_a_repayment_pending_its_cost_basis_is_taken_off_the_owed_side`, `…::test_pending_added_by_an_edit_to_the_deposit_s_arrival_is_refused` |
| `$pending$` written onto the deposit's arrival outside this tool: `--verify-costs` and `--verify-integrity` exit 1 with the reason, the three pending sales still listed | `…::test_pending_written_into_the_book_elsewhere_where_it_cannot_stand_is_reported` |
| `$pending$` added by an edit, as the only change, to the Canadian dollar split of "Sent money" refused as no disposition; added by an edit to a sale dated before any US dollar cost basis opened, once one has opened later, refused, the check asking what was kept on the sale's own date | `…::test_pending_added_by_an_edit_to_a_sale_s_canadian_dollar_split_is_refused`, `…::test_pending_added_by_an_edit_to_a_sale_dated_before_any_cost_basis_is_refused` |
| `$pending$` on a sale before any US dollar cost basis is kept refused; the pending file into the reported book with `cost_bases: "off"` refused, the book file unchanged; the fee restated onto the invoice at 1.01 CAD, where its dollars cost 1.00, accepted and stated as `realized_gains_not_recorded: 0.01`, `--verify-integrity` passing | `…::test_pending_where_no_cost_basis_is_kept_is_refused`, `…::test_pending_in_a_book_keeping_no_cost_bases_is_refused`, `…::test_a_fee_restated_onto_the_invoice_at_another_cad_figure_states_what_it_realized` |
| `$pending$` in a repayment written wholly in US dollars refused; the pending book's unchanged export imported with `--strategy update`, `Updated: 0` and the book file unchanged; `--verify-costs --currency HKD` counting no pending USD disposal | `…::test_pending_in_a_transaction_stating_no_canadian_figure_is_refused`, `…::test_a_book_holding_pending_sales_imported_again_from_its_export_is_left_alone`, `…::test_verifying_the_costs_counts_the_pending_sales_and_finds_nothing_wrong` |
| `$pending$` on the deposit's own arrival refused; `"$pending$"` in quotes read as pending and exported unquoted; the fee given its cost basis and made pending again giving the 0.72 back; the last 8.60 USD written in CAD at its cost after 2,710.68 sold in US dollars, accepted at 11.99 with `--verify-integrity` passing and `realized_gains_not_recorded: -19.79` | `…::test_pending_given_on_a_split_bringing_dollars_in_is_refused`, `…::test_pending_written_in_quotes_is_pending_too`, `…::test_a_sale_given_its_cost_basis_and_made_pending_again_gives_it_back`, `…::test_the_last_sale_stated_in_cad_after_one_stated_in_usd_is_valued_at_its_own_cost` |
| the README's balance sheet book with one disposal's `cost_basis_split_guid:` taken off: shares bought refused as a purchase, shares sold and US dollars sold for Canadian ones as sales, a US dollar loan repaid out of dollars held as a repayment | `test_a_disposal_giving_no_cost_basis_is_refused_as_what_its_splits_show.py` |
| a book kept in HKD, holding USD and CAD, its deposit on a suspense account booked as INV-HK-1's collection, undone and booked again | `TestABookKeptInHongKongDollars` |

Each undo asserts the export after it holds the blocks of the export from before the booking, but for the two `memo:` lines, and that `fx-balances --verify-costs` lists the same cost bases, with no warning.
