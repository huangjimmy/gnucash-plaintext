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
| the fee restated onto the invoice at 1.01 CAD, where 0.72 of the invoice's dollars cost 1.00: refused, saying 1.00. Accepted on #115, and `--verify-costs` reported nothing: a disposal in a transaction stated in US dollars was not valued against its cost basis | `…::test_the_fee_restated_onto_the_invoice_at_another_cad_figure_is_refused` |
| the fee corrected to 0.73 USD at the invoice's cost, 1.02 CAD: accepted, Wise USD and the invoice's cost basis both at 2,719.27 | `…::test_the_fee_restated_onto_the_invoice_drawing_another_amount_at_its_cost_is_accepted` |
| the fee restated onto INV-USD-2, not collected: refused | `…::test_the_fee_restated_onto_an_invoice_not_collected_is_refused` |
| the fee restated onto BILL-USD-1, dollars the book owes: refused, saying the bank's dollars are held. Accepted on #115, leaving Wise USD at 2,719.28 while INV-USD-1's cost basis offered 2,720.00, and the bill's cost basis at 999.28 against 1,000.00 owed | `…::test_the_fee_restated_onto_a_bill_is_refused` |
| the link giving the fee's transaction, another bank account, or the deposit's bank split as `txn_split_guid:`: refused | `…::test_the_link_giving_the_fee_s_transaction_is_refused`, `…::test_the_link_giving_another_bank_account_is_refused`, `…::test_the_link_giving_the_deposit_s_bank_split_is_refused` |
| a book kept in HKD, holding USD and CAD, its deposit on a suspense account booked as INV-HK-1's collection, undone and booked again | `TestABookKeptInHongKongDollars` |

Each undo asserts the export after it holds the blocks of the export from before the booking, but for the two `memo:` lines, and that `fx-balances --verify-costs` lists the same cost bases, with no warning.
