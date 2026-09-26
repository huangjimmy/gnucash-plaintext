# Q-049 — Let a book keep no cost bases, and measure its unrealized gains from GnuCash's own revaluation

## What it should do

**A book can turn cost bases off.** Cost bases are gnucash-plaintext's, not GnuCash's: GnuCash asks no one which lot a dollar came out of. A book whose owner does not want them keeps its foreign currency as GnuCash does, and gnucash-plaintext stops asking for them.

**The switch belongs to the book, not to a command.** The `company` block already keeps settings of the book's own, such as `base_currency: "CAD"`, as custom keys in the book. `cost_bases: "off"` sits beside it, so every command reads the same answer and no run depends on remembering a flag.

**With cost bases off, the import neither checks them nor records them.**

- No disposal is asked for the guid of the cost basis it draws on.
- None of the refusals built on cost bases runs: a transfer sharing a transaction with a spend or an arrival, a split crossing zero valued at anything but what it repaid and brought in, a disposal valued at anything but its cost basis's cost, a repayment written wholly in the foreign currency, an edit in place changing a cost basis.
- Nothing is recorded: no `cost_basis_balance`, no `cost_basis_brought_in`, no `cost_basis_cost`.
- A file stating a `cost_basis_*` key into such a book is refused, so a book is never half on.

**Realized gains stay what the file states.** `realized_gains_fx` and `realized_gains_other` are read from the splits that took a `$residual$` (`took_the_residual`), which no cost basis decides, so a book with cost bases off reports the realized gains its own entries record.

**Unrealized gains are measured from GnuCash's own revaluation.** The balance sheet already does this for a currency its cost bases do not account for (`measured_from: gnucash_revaluation`); with cost bases off it does it for every currency and security, and the page says it measured that way because the book keeps no cost bases, not because they disagree with the accounts. The unrealized figures are then GnuCash's, not what the book's own costs would make them.

**What else says so.**

- `fx-balances` says the book keeps no cost bases, and lists what the accounts hold.
- `--verify-integrity` lists the cost basis checks as not checked, with the reason.

**Turning cost bases on later** is bringing the book forward through its export, as a book imported before a disposal had to state its cost basis is (README, "A book that keeps no cost bases"): every disposal then states the cost basis it draws on.

## What was built

- **Turning cost bases off clears the keys earlier imports wrote**, in the same run, and the import says how many splits held one. A book keeping none holds none, so it is never half on: a key left behind would be exported, and the import refuses a file stating one into such a book.
- **A book that keeps none is not turned on in place.** `cost_bases: "on"`, or the line cleared, imported into such a book is refused: every earlier disposal stated no cost basis, and no cost basis accounts for what it holds. It is turned on by bringing it forward through its export.
- **Whether a book keeps cost bases is read once per book**, keyed by the book's address, and read again once a `company` block sets it or a book is opened: every cost basis writer and the realized gain walk ask it, and a dry run or a rolled-back run of a `company` block leaves nothing behind for the next book opened in the same process.
- **`set-book-key` refuses `cost_bases`.** Written there, the book would hold the keys earlier imports wrote and say it kept none.
- **A `$residual$` beside a split in another currency or a security is the realized difference.** In a book keeping cost bases, a `$residual$` split is read as a realized difference where a split in the transaction states the cost basis it draws on, because that makes the split a disposal. A book keeping none states none. So there the realized difference is what the file states: a `$residual$` beside a split in anything other than the book's own currency, whichever way that split moves, since a realized gain needs no cost basis. The balance sheet reads `realized_gains_fx` or `realized_gains_other` from that split, by the kind of holding beside it. The gain is the balance of the account the file posted it to, and in `retained_earnings`, whatever the keys list: a `$residual$` beside both a currency and a security is on neither key, since one split cannot say how much of it is which, and it is not refused, since the user records the gain and nothing about it is lost. A book keeping cost bases refuses such a transaction as it always has, because there each kind draws on a cost basis of its own.
- **The writers ask the book.** `unapply-payment`, `unlink` and `delete-transactions` write cost basis keys too, not only `import`, so whether to write one is read from the book each time rather than set for a run.

## Known, not yet investigated

- A book kept in another currency than CAD states no realized gain from a `$residual$`, whether it keeps cost bases or not: the realized difference is read only in a transaction stated in `BASE_CURRENCY`, which is CAD (Q-043, "A cost is recorded against a constant").

## Cases the tests cover

`tests/integration/test_a_book_can_keep_no_cost_bases.py`, on `a_usd_invoice_and_bill_for_statement_lines_on_a_holding_account.txt` with `a_company_that_keeps_no_cost_bases.txt`:

| case | test |
|---|---|
| a USD fee and a sale stating no cost basis are accepted | `test_a_spend_that_states_no_cost_basis_is_accepted` |
| a book keeping cost bases refuses the same spends | `test_a_book_keeping_cost_bases_refuses_the_same_spend` |
| no `cost_basis_*` key is in the export, with the invoices and bills posted into the book after it was turned off | `test_nothing_is_recorded` |
| a USD advance paid into a USD account records no cost | `test_dollars_paid_in_dollars_record_no_cost` |
| a fee's value restated in place is edited | `test_a_disposal_restated_in_place_is_edited` |
| a deposit and its fee in one transaction, an arrival and a spend stating no cost basis, edited in place | `test_a_deposit_and_its_fee_are_edited_as_they_were_created` |
| the `company` block imported again reports `unchanged` | `test_the_company_block_imported_again_changes_nothing` |
| `cost_bases: "on"` keeps the keys a book holds | `test_on_keeps_them` |
| `cost_bases: "on"` into a book that keeps none is refused, and the book file is unchanged | `test_a_book_that_keeps_none_is_not_turned_on_in_place` |
| a `$residual$` of −3.00 beside a USD purchase is `realized_gains_fx: -3.00`, as the file states it | `test_a_residual_beside_a_purchase_is_the_realized_difference_the_file_states` |
| a dry run turning cost bases off leaves the book keeping them, in the same process | `test_a_dry_run_turning_them_off_leaves_the_book_keeping_them` |
| 4 SHOP sold at a gain of 200.00 is `realized_gains_other: 200.00` | `test_a_share_sale_s_realized_gain_is_what_the_transaction_records` |
| `unlink` and `unapply-payment` write no `cost_basis_*` key | `test_unlink_writes_no_cost_basis_key`, `test_unapply_payment_writes_no_cost_basis_key` |
| `delete-transactions` deletes dollars a fee and a sale spent stating no cost basis, where a book keeping cost bases refuses while a disposal draws on them; there is nothing to put back | `test_delete_transactions_deletes_what_spends_dollars_stating_no_cost_basis` |
| a file stating `cost_basis_split_guid:` is refused | `test_a_file_stating_a_cost_basis_key_is_refused` |
| turning them off clears the keys a book held, and says so | `test_turning_them_off_clears_the_ones_the_book_held` |
| `cost_bases: "sometimes"` is refused | `test_a_setting_that_is_neither_on_nor_off_is_refused` |
| `set-book-key --key cost_bases` is refused | `test_set_book_key_leaves_it_to_the_company_block` |
| the export rebuilds the book in a new one, with `--include-business-objects` | `test_the_export_rebuilds_the_book_in_a_new_one` |
| the sale's `$residual$` of −50.00 is `realized_gains_fx: 50.00` | `test_the_realized_gain_is_what_the_transactions_record` |
| the balance sheet measures from GnuCash's revaluation and says why | `test_the_unrealized_gain_is_measured_from_gnucash_s_revaluation` |
| `fx-balances` says so and lists 999.28 USD held | `test_fx_balances_says_so_and_lists_what_the_accounts_hold` |
| `--verify-integrity` lists the cost basis checks as not checked | `test_verify_integrity_lists_the_cost_basis_checks_as_not_checked` |

## What was reported

The user, on the refusals Q-048 relaxes: "we impose cost basis on behalf of gnucash plaintext, not gnucash! a user may not want gnucash cost basis at all! then we should allow them to bypass cost basis feature and track the way they want! in this case, the gnucash plaintext balance sheet and unrealized gain will not be correct, but realized gain should still be the same! and in that case unrealized gain shall be calcuated by plaintext as is"

## Why it matters

Since #110 every foreign-currency spend states the cost basis it draws on, and Q-045 to Q-048 each added a refusal that keeps the cost bases consistent. For an owner who keeps foreign currency the way GnuCash does, every one of those is a refusal of a book GnuCash itself accepts, and there is no way to say that the book does not want them.

## A bug reported alongside: record the whole realized gain when disposals empty a cost basis, and state on the balance sheet a realized gain the book did not record

Fixed on the Q-048 branch.

### What was reported

A book's balance sheet at 2027-04-25, with USD at 1.4096 (`--fx-rates`, `--no-itemize`):

```
total_assets: 17373.89 CAD
total_liabilities: 476.00 CAD
total_unrealized_gains: 23.97 CAD
gnucash_balancing_amount: -18.23 CAD
total_equity: 16897.90 CAD
total_liabilities_and_equity: 17373.90 CAD
```

The page does not balance: it states 17,373.89 of assets against 17,373.90 of liabilities and equity.

### What was investigated

Invoice TERMINAL-001 is 2,720.00 USD, its sales split 3,815.89 CAD, so its cost basis cost 381589/272000 CAD per USD. The dollars were paid into a US dollar bank and spent in three transactions, each drawing on that cost basis and each valued, as the import requires, at the cost of what it drew rounded to the cent:

| spent | bought | exact cost | valued at | exchange split |
|---|---|---|---|---|
| 0.72 USD | a bank charge of 1.00 CAD | 1.0100… | 1.01 | 0.01 |
| 8.60 USD | a bank charge of 11.92 CAD | 12.0649… | 12.06 | 0.14 |
| 2,710.68 USD | 3,758.36 CAD | 3,802.8109… | 3,802.81 | 44.45 |
| **2,720.00 USD** | **3,771.28 CAD** | **3,815.89** | **3,815.88** | **44.60** |

**The first failure is the import's.** The realized loss is what the dollars cost less what they bought, 3,815.89 − 3,771.28 = 44.61. The three values add up to 3,815.88, not the 3,815.89 the dollars cost, so the three exchange splits add up to 44.60: a realized loss of 0.01 is not recorded.

**The second failure is the balance sheet's.** The unrealized gain is right: TERMINAL-002's 1,020.00 USD at 1.4096 less the 1,413.82 they cost, 1,020.00 × (1.4096 − 70691/51000) = 23.972, stated as 23.97. `retained_earnings` carries the realized loss the book recorded, 44.60. Nothing on the page stated the 0.01 of realized loss not recorded, so liabilities and equity came to 0.01 more than the assets.

**It happens the other way round too.** Rounding half up can make each value larger than its cost. 2.00 USD bought for 2.01 CAD, 1.005 per USD, sold 1.00 USD at a time for 1.40 CAD: each sale is valued at 1.01, the two at 2.02 of the 2.01 the dollars cost, and the exchange splits record a realized gain of 0.78 where it is 2.80 − 2.01 = 0.79. With a third dollar bought at 1.30 and still held, the page at 1.40 states 100.89 of assets against 100.88 of liabilities and equity.

**No test had it.** Several fixtures hold the same 2,720.00 USD at 3,815.89, and some the 0.72 USD fee drawn on it, but none spends the rest, and none draws a balance sheet on a cost basis whose disposals' rounding comes to a cent. It can come to one before the cost basis is empty: after the two bank charges, the book holds 3,802.82 of the cost of the 2,710.68 USD left, which cost 3,802.8109 at the cost basis's rate, 3,802.81 at the cent, and that page too stated 0.01 more of liabilities and equity than of assets.

### What changes

- **The disposal that takes the last of a cost basis is valued at what is left of its cost**: 3,815.89 − 1.01 − 12.06 = 3,802.82, and 2.01 − 1.01 = 1.00. The exchange splits then add up to the realized gain or loss, 44.61 and 0.79. A last disposal valued at its own share rounded is refused, and the refusal states what is left.
- **The balance sheet states the realized gain not recorded**, `realized_gains_not_recorded`, and adds it into `total_equity`. Per cost basis it is, over the disposals drawn on it, what each drew at the cost less what it was valued at: the part of the cost the rounding of their values left. The reported page states `unrealized_gains_assets_fx: 23.97`, `realized_gains_not_recorded: -0.01` and 17,373.89 on both sides. The key is left off where it is zero, a note beside the others says it reaches `total_equity`, and the itemized page lists each cost basis it comes from. It is stated only for a cost basis whose disposals are each valued as the import requires: a disposal valued against another cost, or a cost stated wrong, is not a rounding, `--verify-costs` reports it, and the page does not balance.
- **A book already holding such a last disposal is corrected in place.** A `--strategy update` block restating it at what is left, 3,802.82, with its exchange split at 44.46, goes through: it draws the same currency from the same cost basis on the same date, and only the value moves, to the one figure an import of it would require. A value moved to any other figure is refused as before.
- **Where the book came from does not matter.** An earlier import wrote the reported book, and an owner writing a ledger by hand can write the same figures. A file stating them is refused, and the refusal states what is left; a book already holding them is drawn right and can be corrected in place.
- **A book is rebuilt from its own export as it was.** An export states each cost basis's balance, 0.00 once it is spent, so from it every disposal would read as the last one, and a disposal in the middle valued at its own share was refused. Where the file states the balance, a disposal is taken at its own share or at what is left, as `--verify-costs` takes one in a book, and the rebuilt book states the realized gain it does not record.

### Cases the tests cover

`tests/integration/test_the_last_disposal_of_a_cost_basis_takes_what_is_left_of_its_cost.py`, on `a_usd_sale_spent_in_three_disposals_that_round_down.txt` (the reported figures) and `two_usd_bought_for_2_01_cad_and_sold_a_dollar_at_a_time.txt` (the reverse):

1. The last disposal valued at what is left goes through, and the exchange account records a loss of 44.61 and a gain of 0.79.
2. The last disposal valued at its own share rounded is refused, and the refusal states 3,802.82 and 1.00.
3. A book holding the last disposal at its own share is corrected with `--strategy update` to what is left, and then records 44.61 and 0.79.
4. Moved in place to 3,802.80, neither figure, it is refused, and the book keeps 44.60.
5. The 0.72 USD charge of the 13th restated in place at 1.02 is refused: it is not the last disposal, since two are dated after it. A book keeps no order within a day, so of two disposals dated the same last day, either may be taken as the last.

`tests/integration/test_a_balance_sheet_states_the_realized_gain_the_book_did_not_record.py`, on the same two books:

6. A book whose last disposal holds its own share rounded, as the reported book does, states an unrealized gain of 23.97 and 0.10, a realized gain not recorded of −0.01 and 0.01, and balances.
7. Itemized, it lists the cost basis the −0.01 comes from, with its cost value and the cost held.
8. Before the last disposal, with 2,710.68 USD still held, the two charges' rounding already states −0.01, and the page balances.
9. A book recording the whole realized gain states the same unrealized gains, no realized gain not recorded, and balances.
10. Exported and imported into a new book, the reported book and its reverse are rebuilt, and state −0.01 and 0.01.
11. On a currency owed — 2.00 USD owed on a card for 2.01 CAD and paid off at 1.01 and 1.01 — it states −0.01, a loss, and balances (`two_usd_owed_on_a_card_for_2_01_cad_and_paid_off_a_dollar_at_a_time.txt`).
