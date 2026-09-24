# Q-048 — Accept an edit that leaves every cost basis as it was, and say what a refused edit would change and a route that works

## What it should do

**An edit in place with `--strategy update` stands wherever the cost bases are what they were.** Every cost basis the transaction opens keeps its split, its account, its currency and side, what it brought in, what it cost and its date; every disposal in it draws on the same cost basis, from the same side, by as much, at the same value, on the same date. Everything else in the transaction is the file's to correct: the account of a split in the book's own currency, how a rate's totals are divided between such splits, a memo, a description.

**A refused edit says what it would change**: which splits the book holds and the file states differently, and what that does to a cost basis or a disposal.

**And it gives a route that can be taken.** Where other transactions draw on the transaction's cost basis, it cannot be deleted before them, so the refusal lists them and gives one `delete-transactions --by-guid` command deleting them first and then it. It follows the chain: a conversion drawn on the transaction's dollars opens a euro cost basis, and a fee drawn on that keeps the conversion from being deleted in turn, so the fee is listed and deleted before the conversion. Each transaction is listed once, after everything drawing on it, with what it draws on any cost basis added up by currency.

## What was reported

A user moved the other split of a US dollar arrival from the director's account to income with `--strategy update`. The arrival, as the book held it:

```
2026-08-13 * "Received money from REDACTED PAYER with reference 091000014286964 | ..."
	guid: "e1d60fe6bc104e018c50c67dd61665ec"
	currency.mnemonic: "USD"
	Assets:...:Wise Payments Canada Inc. Chequing 170710882080137 2720.00 USD
		guid: "3cdacfb099e9c7fbe795b8aa317313bd"
		cost_basis_balance: "0.00"
	Assets:Current assets:Due from shareholder(s)/director(s) -3791.14 CAD
		guid: "6e1edce56a2f4ac8b84f15a96bd3ca56"
		account.commodity.mnemonic: "CAD"
		share_price: "272000/379114"
		value: "-2720.00"
```

The edit changed only the account of the Canadian dollar split, to `Income:Non-farming revenue:Sales`. It was refused: "transaction … touches a cost basis, so its amounts, values, accounts, cost basis picks and the currency it is stated in cannot be edited in place — a memo or description can. Delete it and import the new version instead: `delete-transactions --by-guid …`".

Their account of the second refusal: "the route that message tells us to take" was refused too — the transaction "cannot be deleted: it establishes a cost basis that 3 transaction(s) measure against … Delete those first." And: "What it does not state is which split or which field offended."

## What was investigated

On main at `40ec5dd`, GnuCash 5.10, with a probe importing `tests/fixtures/a_usd_arrival_booked_to_the_directors_account.txt` — the arrival with the reported figures and guids, and a 0.72 USD fee drawn on its cost basis — and applying each edit with `--strategy update`:

| edit | main |
|---|---|
| the Canadian dollar split moved to income, every figure the same | refused |
| that split divided, 2,000.00 CAD to income and 1,791.14 left on the director's account | refused |
| the US dollar split moved to a second US dollar bank | refused |
| the fee's expense moved to another expense account | accepted |
| the arrival's date moved from 2026-08-13 to 2026-08-14 | accepted |

**Why the first two were refused.** The guard compared a list of what each cost basis is read from, split by split with each split's account, and refused any change to the list. The transaction is stated in US dollars, so its cost basis is priced at the Canadian dollar splits' amounts added up over their values added up (`_base_per_unit_of`), and those splits were on the list with their accounts — though the account plays no part in the price. `_basis_relevant_accounts` described this very case, a deposit booked against the director's account and later moved to income, as a correction that should go through; it did only where the transaction was stated in Canadian dollars. The third is right to refuse: the cost basis sits on that split, and moved to the second bank it would leave the fee spending from the first bank while drawing on a cost basis kept on the second, the first bank at −0.72.

**The date edit went through, and it changes a cost basis.** With the arrival moved to the 14th, the fee on the 13th draws on a cost basis dated a day after it. `--verify-integrity` at 2026-08-13 found the book consistent and balanced, `--verify-costs` reported no fault, and the book's export rebuilt it with no error — a book of that shape is one this repository holds to be sound (`tests/integration/test_an_export_states_a_cost_basis_above_what_draws_on_it.py` keeps a fee dated 2026-08-12 drawn on a deposit dated 2026-08-13). But a cost basis's date is when its currency arrived, and a disposal's when it drew one down: what the cost bases held on every day between moves with it. The guard compared no date, so an edit moving one was never asked about at all.

## What changes

The guard's list still decides when no figure it reads has moved. Where something has, the edit is applied inside GnuCash's open edit, the cost bases are read again, and the two readings are compared before the edit is committed. Different, and `RollbackEdit` undoes it all (checked on 5.10 with a probe: a split's account and a custom key written during the edit both come back as they were). The facts compared are `cost_basis_facts`:

- a cost basis: its split, its account, its currency and side, what it brought in, what it cost, and its date;
- a disposal: its split, its account, the cost basis it gives, the side it draws on, what it draws down, its value, and its date.

A date moving is reason enough to compare, on a transaction touching a cost basis; one touching none may still be edited into one that opens a cost basis, as before.

**A refusal says why.** Each change it lists carries its reason: a date, that a cost basis is dated when its currency arrived and a disposal when it drew one down, so what the cost bases held on every day between would change; a cost, that every disposal already drawn on it was valued at what it cost; an account, that a split spending from the first account would draw on a cost basis kept on the second; a disposal restated, that what it took stays off the cost basis balance and the new amount is taken off none. And it says why the route is to delete and import again: an edit in place runs none of the checks a new transaction meets, and gives a cost basis balance no amount back that a disposal took.

What a split brought in past zero (Q-047) is read again from what its account held without the transaction before the edit was opened — inside the open edit GnuCash still counts each split where it was. It is read again for every split on an account where the edit changed, added or removed one, because the others then start from a different place. Where the edit leaves every split on an account as it was — the same splits, amounts and date — they keep what they recorded: read again, a fee of 0.72 USD dated the same day and imported after the arrival made the arrival read as bringing in 2,719.28 USD, and moving only its other split then read as changing the cost basis.

Two things follow from that rule, and both leave every cost basis as it was:

- A split imported before Q-047 has no record of what it brought in, and is read as having brought in its whole amount. An edit that leaves its account's splits as they were does not write the record, so it goes on reading as before. Writing it would change the cost basis on an edit that left every figure of it as it was.
- A split on a foreign currency account that neither opens a cost basis nor gives one — a spend from a book older than #110, before a pick was required — is not among the facts compared, so re-amounting it is accepted where the cost bases stay as they were. Every split on its account is read again with it, so where a split beside it opens a cost basis and now brings in something else, that is a change, and the edit is refused.

A figure the edit cannot apply — a `value:` of `eight`, an amount of `--10.00`, a `$residual$` amount, a `share_price:` of `abc` — is refused for itself, giving the split and the field, where it was refused as an edit to a cost basis.

## Cases the tests cover

`tests/integration/test_an_edit_may_move_the_split_that_sets_the_rate.py`, on `tests/fixtures/a_usd_arrival_booked_to_the_directors_account.txt`:

1. The Canadian dollar split moved to income: the edit goes through, and the cost basis is priced as it was.
2. That split divided between income and the director's account: the edit goes through, and the cost basis is priced as it was.
3. The US dollar split moved to another bank: refused, saying cost basis `3cdacfb099e9c7fbe795b8aa317313bd` on the first bank would be on the second.
4. The arrival moved from 2026-08-13 to 2026-08-14, and the fee moved the same way: each refused, saying it is dated 2026-08-13 and would be dated 2026-08-14, and giving the delete that works.
5. The Canadian dollar split restated at 3,800.00: refused, saying the book holds −3,791.14 CAD on the director's account valued at −2,720.00 and the file states −3,800.00; listing the fee drawn on the cost basis; and giving `delete-transactions --by-guid <fee> <arrival>`, which deletes both. With 1,000.00 of the dollars converted into euros and a fee of 1.00 EUR and 0.10 USD drawn on both cost bases, the command gives the arrival's fee, the euro fee, the conversion and the arrival, in that order, and deletes all four.

Existing tests whose refusals changed: `test_an_added_cad_split_cannot_reprice_a_basis.py` — two added 0.00 CAD splits under `--atomic` leave the cost basis as it was and go through, and unreadable figures are refused for themselves; `test_an_atomic_run_cannot_restate_what_a_disposal_takes.py` — a block that leaves a disposal's `cost_basis_split_guid:` line out goes through with the pick kept, and one clearing it with `cost_basis_split_guid: ""` is refused.
