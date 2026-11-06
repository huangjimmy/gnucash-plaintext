---
id: Q-059
title: "An itemized balance sheet listed the cost bases of the currency a book holds, and none of the currency it owes"
category: bug
severity: medium
status: closed
---

## What was reported

A user reported that `unrealized_gains_liabilities_fx` has no cost basis on the balance sheet, while the asset side's unrealized gain has one.

## What the page did

The two keys are measured the same way. Each takes the cost bases on its own side of the sheet, prices them at the sheet's date, and subtracts what they cost. A currency the cost bases cannot account for keeps GnuCash's own revaluation, on either side.

The page did not state them the same way. Measured on GnuCash 5.10, on a book that holds 500.00 USD and owes a 1,000.00 USD loan, both at 1.30 CAD/USD, priced at 1.40 CAD/USD on the sheet's date (`tests/fixtures/a_cad_book_that_borrowed_usd_and_kept_half_of_it_in_usd.txt`):

| | `--itemize`, the default | `--no-itemize` |
|---|---|---|
| `unrealized_gains_assets_fx` | a block: the 500.00 USD cost basis, its cost of 650.00 CAD, its value of 700.00 CAD, and the account holding it | `50.00 CAD` |
| `unrealized_gains_liabilities_fx` | **one line**: `-100.00 CAD` | `-100.00 CAD` |

So with `--itemize` a reader could check the 50.00 CAD gain on the dollars held, down to the cost basis, and could not check the 100.00 CAD loss on the loan. Nothing on the page said which loan it came from, what it was drawn at, or what it is worth now. `unrealized_gains_fx` is the two added together. Every figure was right. Only the working of the owed side was missing.

## Why

`--itemize` and `unrealized_gains_liabilities_fx` came in the same commit, 8883acb, on 2026-09-18. The block that itemizes a currency's cost bases was written for the asset key alone. Its comment said so: a loan's cost basis listed under the assets key had been added into it, stating 100.00 CAD of gain on a page whose total said the book had lost 100.00 CAD. Taking the loan out of that block fixed that. Nothing gave the owed side a block of its own, so it stayed one line.

The tests held it there. Thirteen assertions, in seven files, read the liability key as one line on an itemized page: twelve in six integration files, and one in the scenario test `tests/scenario/test_a_split_draws_on_a_cost_basis_by_its_position_in_the_file.py`, which passed `--itemize` beside the comment "The owed side is one line on the page". No test compared the two sides with each other.

## What was fixed

- `plaintext:cost-basis-block` in `infrastructure/gnucash/reports/balance-sheet-and-income-statement-as-text.scm` takes the side it lists. With `--itemize`, the balance sheet writes one block for each side, in the same shape: each cost basis, each commodity left to GnuCash's revaluation under `measured_from: gnucash_revaluation`, the accounts holding the currency, and the key's own figure at the end. With `--no-itemize` each key is one line, as before.
- The owed side's figures are negative, as GnuCash signs a liability's balance. The loan above reads `cost_basis_balance: -1000.00`, `cost_value: -1300.00`, `value: -1400.00` and `unrealized_gains_liabilities_fx: -100.00`. Its group says `type: liability`, and its price line says the price was set "on the day it came to be owed" rather than "on the day it was bought".
- A receivable or a payable whose lots are on both sides lists, on each side, only the lots on that side. Before, the asset block listed such an account at its whole balance, which is not the figure its cost bases are checked against. Measured on a receivable holding 2,500.00 USD of unpaid invoices and owing 1,500.00 USD of a customer's credit back: the asset block listed it at 1000.00 and stated `balance_value: 5898.34` beside 7398.34 of cost bases. It now lists 2500.00 and `balance_value: 7398.34`, and the owed block lists -1500.00.
- No total changed. Each block's total is the figure the key stated before, and only those account lines and their `balance_value` read differently.

## Tests

- `tests/integration/test_the_owed_side_lists_its_cost_bases_as_the_held_side_does.py`, on the book above: each side lists only its own cost basis, the two blocks have the same keys in the same order, the owed side states the loan's cost and value, and with `--no-itemize` each side is one line. `test_every_gain_key_is_a_block_itemized_and_one_line_without` checks every gain key on two books, the second being `tests/fixtures/a_usd_sale_spent_in_three_disposals_that_round_down.txt`, which states all six. Each key the page states is a block with `--itemize` and one line without, and each block's total is the one-line figure. Run against the report before this fix, it fails on `unrealized_gains_liabilities_fx` alone, so the other gain keys were already stated alike.
- `tests/integration/test_an_itemized_total_is_the_figure_the_key_states.py` checks the liability block's total against its key, on eight books.
- The scenario test above draws its book both ways and checks the two sides are stated alike in each.
- Passed on GnuCash 5.10 (Debian 13) and 3.4 (Debian 10). The tests it touches passed on 3.8 (Ubuntu 20.04) as well.

The worked examples in `examples/multi-currency/` were regenerated, and the passages in `docs/multi-currency.md` and Q-044 that quote an itemized page now quote the owed side's block. README's sheet and the passages in Q-042 and Q-043 are `--no-itemize` pages, where the two sides were already alike, and are unchanged.
