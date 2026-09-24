# Q-050 — Let a split draw on a cost basis by its position in the file being imported, so a transaction can spend currency it brings in and a file need not assign a guid

## What it should do

**A split gives the cost basis it draws on by the position of the split that opens it, in the file being imported.** Where `cost_basis_split_guid:` takes a guid, it also takes a variable:

```
2026-08-13 * "Received money, less the transfer fee"
	currency.mnemonic: "CAD"
	Assets:Wise USD 2720.00 USD
		value: "3800.00"
	Assets:Wise USD -0.72 USD
		value: "-1.01"
		cost_basis_split_guid: $transactions_to_import[0].splits[0].guid$
	Income:Sales -3800.00 CAD
	Expenses:Bank charges 1.01 CAD
```

- **Written unquoted, between `$`**, as `$residual$` is. Quoted, it is a string, read as a guid like any other, and refused because it matches no split.
- **Read only as `cost_basis_split_guid:` on a split of a transaction.** Written anywhere else — on a transaction's own line, or as the split a payment block settles from — the file is refused before any of it is applied, saying where a position is read.
- **Counted from 0, in the order the file writes them.** `transactions_to_import[n]` is the file's n-th transaction block; `open`, `commodity`, `price`, `invoice`, `bill` and `company` blocks are not counted. `splits[m]` is the block's m-th split line.
- **It points at a split in the same transaction or in one above it.** A transaction below has not been imported when the reference is read, so pointing at one is refused, saying to move that block above.
- **What is saved is the guid.** The import saves the guid GnuCash assigned that split in the `cost_basis_split_guid` KVP, exactly as though the file had written it. The variable is never saved, and `export` writes the guid.
- **Refused, giving the position**: a position past the end of the file or of the transaction, and a split there that opens no cost basis — the same refusal a guid giving such a split meets.
- **Under `--strategy update`** the position still counts the file's transactions. Every transaction there is one the book holds, so the reference is the `guid:` the line it points at gives, as an export writes one on every split; a line giving none, or a `guid:` that is no split of the transaction the book holds, is refused, since which split of the book it is cannot be read from the file. Under `--strategy update` that is found before any transaction is edited, so the file is applied whole or not at all. The same holds for a transaction an import passes over as already in the book.

**A split may draw on a cost basis its own transaction opens.** The arrival's cost basis is opened, with all it brings in, before the split drawing on it is checked and drawn, so 0.72 USD of a 2,720.00 USD arrival's fee leaves a balance of 2,719.28.

## What was reported

The user: "if a book has no cost basis at all, but the 1st import is 2720 USD income and at the same time, 0.72 incoming fee expense, then the 0.72 expense need to use the cost basis to be created. This operation should be supported!"

On how the file should say so: "you cannot force user to assign a guid! users should be able to ref that split for cost basis but still let gnucash auto generate the guid!" A new key on the arriving split is not the answer either: every key under a split is a KVP and is saved, and a key read but never saved breaks the format. The reference is "a special position ref … the position is a relative position of the imported plaintext", written `transactions_to_import[0].splits[1].guid` or the like, "remove the quotes, $$ is special".

## Why a change is needed

Before this change a file could spend currency its own import brings in only by writing a guid on the arriving split and the same guid on the split drawing on it, and only with the two in different transactions, the arrival above. Within one transaction it could not at all: the draw was checked before the arrival's cost basis was opened, and was refused as though the split had not been written by the import; and the splits of one account were netted before a cost basis was read, so an arrival spent to the last dollar in its own transaction was no cost basis at all.

## The scenarios, and the outcome of each

A split draws on a cost basis through `cost_basis_split_guid:`, written as a guid or as a position. Each case is one import that creates a cost basis and draws on it, with the book it leaves and what `fx-balances --verify-costs` then says.

| | case | outcome |
|---|---|---|
| E1 | The reported case: 2,720.00 USD in for 3,800.00 CAD and a 0.72 USD fee drawn on them, one transaction | a cost basis of 2,720.00 USD costing 3,800.00; the fee draws 0.72, valued 1.01; balance 2,719.28 |
| E2 | Dollars in, a fee, and the rest moved to chequing, one transaction | the fee draws 0.72, valued 1.01, and the rest, 2,719.28, is the last of the cost basis, valued at what is left, 3,798.99; balance 0.00 |
| E3 | The reported arrival stated in US dollars, with its fee | a cost basis of 2,720.00 USD, priced as any transaction stated in US dollars is, from its Canadian dollar splits; the fee draws 0.72, valued 0.72 USD, the transaction's own currency; balance 2,719.28 |
| E4 | Supplies of 2.01 CAD charged to a USD card as 2.00 USD, and 1.00 USD paid back for 1.40 CAD, one transaction | a cost basis of 2.00 USD owed, costing 2.01; the repayment draws 1.00, valued 1.01, a realized loss of 0.39; 1.00 USD still owed |
| E5 | Dollars in, 1,000.00 of them converted to 900.00 EUR, and a 1.00 EUR fee drawn on the euros, one transaction | the conversion draws 1,000.00 USD, valued 1,397.06, and opens a euro cost basis of 900.00 costing 1,397.06; the fee draws 1.00 EUR, valued 1.55; balances 1,720.00 USD and 899.00 EUR |
| E6 | E1 under `--atomic` | as E1, committed |
| E7 | A fee whose position is a transaction below it | refused before any of the file is applied, giving the position and saying to move that block above |
| E8 | The arrival in one transaction and the fee, giving its position, in a later one | as E1 |
| E9 | A fee added by `--strategy update` to an arrival the book holds | refused: an edit in place does not add a split drawing on a cost basis (Q-048) |
| E10 | The arrival and a fee giving no cost basis, one transaction | refused, as a spend giving no cost basis is anywhere, and the refusal gives the two ways to write it: the arrival net of the fee, which makes the fee part of what the dollars cost and records no fee; or the fee kept, giving its cost basis — the arrival's position in its own transaction, an arrival's position above, or the guid of a cost basis the book holds, each listed. It chooses none |
| E11 | The book holds 500.00 USD bought at 1.30; a transaction brings 2,720.00 USD in and pays its 0.72 USD fee from the 500.00, giving that cost basis's guid | the 500.00 falls to 499.28, valued 0.94; the arrival opens 2,720.00 whole |
| E12 | As E11, with a second 0.72 USD fee giving the arrival's position | each fee draws on the cost basis it gives: 499.28 and 2,719.28 left |
| E13 | A position pointing at the split that gives it | refused: a split does not draw on the currency it brings in |
| E14 | A position past the end of the file, or of its transaction | refused, giving the position and how many transactions, or splits, there are |
| E15 | A position pointing at a split that opens no cost basis, such as a Canadian dollar split | refused, as a guid giving such a split is |
| E16 | The variable written in quotes | a string: read as a guid, and refused as matching no split |
| E17 | The variable misspelt, such as `$transaction_to_import[0].splits[0].guid$` | refused before any of the file is applied: no variable this format knows, with the form it takes |
| E18 | A fee giving the position of an arrival whose transaction the same import refused | refused: that transaction was not imported, so no split of it has a guid to give |
| E19 | A fee giving the position of an arrival the import passes over as already in the book, by its transaction's guid or as a duplicate, whose line gives no `guid:`, or a `guid:` that is no split of the transaction the book holds | refused: which split of the book that line is cannot be read from the file |
| E21 | E12 with the second fee giving no cost basis | refused as E10: a fee giving a cost basis says nothing of a fee beside it |
| E23 | A position written anywhere but `cost_basis_split_guid:` on a transaction's split, such as the split a payment block settles from, or on a transaction's own line | refused before any of the file is applied, saying where a position is read |
| E24 | The book holds an open US dollar invoice, and a fee beside an arrival gives no cost basis | refused as E10, and the cost bases listed leave out the invoice's receivable: that cost basis is drawn down by settling the invoice, and a disposal giving its guid is refused |
| E22 | The arrival, a fee out of its account and a fee out of another US dollar account holding dollars, one transaction, neither fee giving a cost basis | refused as a transfer sharing a transaction: nothing says whether the other account's dollars left the book or moved into the arrival's |
| E20 | E19 under `--strategy update`, beside an edit to another transaction | refused before any transaction is edited, so the other keeps what it had: an update applies the whole file or none of it |

## The rules those outcomes follow

**Where the position points.**

- **The same transaction** (E1–E5): each split a position points at opens its cost basis with all it brings in, before any split of the transaction is checked or drawn, and the splits of one account are not netted where one of them draws on another of the transaction's splits.
- **A transaction above it** (E8), as a guid.
- **A transaction below it** (E7): refused, before anything of the file is applied. A position below cannot be the guid of a split that exists yet, and a file applied in part is worse than one refused whole.
- **The split itself** (E13), **past the end** (E14), **a split that opens no cost basis** (E15): refused.
- **A transaction the import refused** (E18): refused. Its splits were destroyed with it, so there is no guid to give, whatever point it was refused at, including part way through resolving its own positions.
- **A transaction the import passed over as already in the book** (E19): the `guid:` its line gives, where it is a split of the transaction the book holds, and refused otherwise.

**What opens the cost basis.**

- **A split bringing currency in** — income into a foreign bank, a purchase, the arrival of a transfer (E1–E3, E5).
- **A split owing currency** — charged to a foreign card, a borrowing (E4), the split repaying it drawing from the owed side.
- **The part of a split past zero** (Q-047), the position pointing at the split whose part past zero is the cost basis.
- **A split opening a cost basis while drawing on another** — euros bought with dollars (E5), in either order within the transaction.
- **An invoice's or a bill's posting, or a payment's credit**: a position counts transaction blocks only, and GnuCash writes those splits when the record is posted or the payment applied, so no position points at them. A file draws on them by guid, from a later import.

**Which cost basis, where the book already holds some.** The owner chooses, and the file states the choice; nothing prefers a cost basis because it exists.

- A split may draw on a cost basis this import creates while the account already holds others: a position is honoured whatever the book holds, and no existing cost basis is taken first.
- One transaction may mix the two: a split giving a guid draws on a cost basis the book holds (E11), and another giving a position draws on one the transaction or a transaction above it opens (E12).
- A split draws on one cost basis. Currency taken from two — part from dollars the book held, part from dollars the transaction brings in — is written as two splits, each giving its own, and the import neither divides one split between them nor chooses which.

**What draws on it.** Any split that gives `cost_basis_split_guid:` — a fee, a sale, a withdrawal, a conversion, a repayment, a split crossing zero — and more than one in a transaction (E2), the last of a cost basis valued at what is left of its cost (Q-049).

**How the file is imported.** A new book, an existing one, and `--atomic` (E6) resolve a position the same way. Under `--strategy update`, and for a transaction the import passes over as already in the book, a position is the `guid:` the line it points at gives; an edit in place adds no split drawing on a cost basis (E9), by the rule of Q-048.

**What else reads the book.** The guid saved is the split's own, so `export` writes the guid and the ledger rebuilds the book; `delete-transactions` of a transaction whose only disposals are its own gives the cost basis back and deletes it; the balance sheet, `fx-balances` and `--verify-costs` read the draw as any other.

**A split spending currency and giving no cost basis is refused, beside an arrival as anywhere else** (E10). A fee taking 0.72 USD out of Wise USD is a spend, and since #110 every spend gives the cost basis it draws on. Netted against the arrival in its own transaction, it spent dollars without saying from where: the cost basis recorded 2,720.00 USD brought in and a balance of 2,719.28, nothing recorded the fee drawing on it, and `--verify-costs` warned that 0.72 USD was accounted for by no cost basis. Dollars moved between two US dollar accounts in one transaction are still no spend, as before: another US dollar split of the transaction takes them, and they stay on the side that held them. The fee's 0.72 USD is taken by no US dollar split; it leaves the side, for an expense.

The refusal does not stop at saying so: it gives the two ways the owner can write what they mean, in the file's own figures, and chooses neither. The first is given only on the held side: a spend of currency owed repays it, with money that left the book, so there is no charge net of it to write, and the refusal asks only for the cost basis it repays.

- **The fee as part of the exchange spread, not kept as a fee.** Drop the fee's two splits and write the arrival net of it:

  ```
  	Assets:Wise USD 2719.28 USD
  		value: "3800.00"
  	Income:Sales -3800.00 CAD
  ```

  The 3,800.00 then buys 2,719.28 USD, so the fee is in what the dollars cost, and no fee is recorded in the book. In a transaction stated in US dollars a US dollar split's value is its amount, so the refusal gives the arrival valued 2,719.28 and says the splits beside it are valued 2,719.28 between them in place of 2,720.00: the same Canadian dollars buy fewer US dollars.

- **The fee kept.** Keep `Assets:Wise USD -0.72 USD` and `Expenses:Bank charges 1.01 CAD`, and give the fee the cost basis its dollars came out of. The refusal lists every one it could give, each written as the line to add:
  - the arrival in its own transaction, `cost_basis_split_guid: $transactions_to_import[0].splits[0].guid$`;
  - an arrival in a transaction above it, by its position;
  - each cost basis of US dollars held that the book holds, by its guid, with its balance — not an invoice's or a bill's, on a receivable or a payable, which settling that record draws down (E24).

Any spend giving no cost basis is refused with the same list, wherever it stands: the arrivals above it in the file by their positions, beside the cost bases the book holds by their guids, so a file whose dollars arrive in its own import is never told only of the book's.

**Re-pricing, under `--atomic`, a transaction whose own split draws on it.** `--atomic` defers the refusal to edit a transaction a cost basis rests on only where the finished book can check every disposal on it, and a disposal stated in a foreign currency is one it cannot (Q-048). A disposal in the edited transaction itself is not one of those: its value is read through the same Canadian dollar splits that price the cost basis, so the file states both and a re-price moves them together. The deferral is granted for it; a disposal in another transaction, stated in US dollars, still refuses it.

## Cases the tests cover

`tests/integration/test_a_split_draws_on_a_cost_basis_by_its_position_in_the_file.py`, one fixture per case in `tests/fixtures/`. Every test but the ones for a refusal the old code also gave failed on `main`.

| case | test |
|---|---|
| E1 | `test_the_reported_fee_draws_on_the_dollars_its_own_transaction_brings_in`, `test_what_is_kept_is_the_guid_and_never_the_variable` |
| E2 | `test_a_fee_and_the_rest_sent_on_spend_the_arrival_to_nothing` |
| E3 | `test_a_transaction_stated_in_us_dollars` |
| E4 | `test_currency_owed_and_part_of_it_repaid` |
| E5 | `test_a_conversion_opening_a_cost_basis_its_own_transaction_draws_on` |
| E6 | `test_under_atomic` |
| E7 | `test_a_transaction_below_refuses_the_whole_file` |
| E8 | `test_a_transaction_above` |
| E9 | `test_a_fee_added_by_an_edit_is_refused` |
| E10 | `test_it_is_refused`, `test_the_refusal_gives_the_arrival_net_of_the_fee`, `test_stated_in_us_dollars_the_splits_beside_the_arrival_are_valued_at_what_is_kept`, `test_the_arrival_written_as_the_refusal_says_imports` (stated in each currency), `test_the_refusal_gives_the_position_of_the_arrival`, `test_the_refusal_lists_the_cost_bases_the_book_holds` |
| E11 | `test_a_fee_paid_from_dollars_held_leaves_the_arrival_whole` |
| E12 | `test_one_fee_from_each_draws_on_the_one_it_gives` |
| E13–E17 | `test_a_position_that_cannot_be_resolved_is_refused`, one parameter each, and two for E14: past the last split of a transaction and past the last transaction |
| E18 | `test_a_transaction_the_import_refused_gives_no_guid`, `test_a_transaction_refused_after_its_own_position_resolved_gives_no_guid` |
| E19 | `test_a_transaction_passed_over_whose_line_gives_no_guid`, `test_a_transaction_passed_over_whose_line_gives_a_guid_it_does_not_hold` (by its guid, and as a duplicate) |
| E20 | `test_a_position_at_a_line_giving_no_guid_refuses_the_whole_file` |
| E21 | `test_one_fee_giving_a_cost_basis_does_not_let_another_give_none` |
| E22 | `test_fees_from_two_accounts_beside_an_arrival_are_refused_as_a_transfer` |
| E23 | `test_a_position_where_none_is_read_refuses_the_whole_file`, in a payment block and on a transaction |
| E24 | `test_the_refusal_lists_no_cost_basis_of_a_receivable` |
| E10, owed side | `test_a_repayment_is_offered_no_net_charge` |
| export | `test_the_export_writes_the_guid_and_rebuilds_the_book` |

Fixtures that spent currency their own transaction brings in and gave no cost basis now give the arrival's position: `usd_bought_with_the_bank_keeping_part_as_its_fee_drawn_on_the_purchase.txt` (with `tests/integration/test_a_purchase_whose_fee_draws_on_it_leaves_what_the_account_holds.py`), `fx_two_base_splits_at_different_rates.txt`, and the two card fixtures of `tests/integration/test_a_balance_past_zero_has_a_cost_basis_on_the_other_side.py`. The re-pricing rule above is covered by the two `--atomic` tests of `tests/integration/test_an_added_cad_split_cannot_reprice_a_basis.py`, and its limit by `tests/integration/test_a_repriced_basis_is_caught_under_its_sales.py`.
