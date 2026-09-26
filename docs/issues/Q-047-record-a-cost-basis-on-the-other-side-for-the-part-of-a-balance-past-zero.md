# Q-047 — Record a cost basis on the other side for the part of a foreign-currency balance past zero

## What it should do

**An asset account below zero owes the currency, and a liability account above zero holds it.** The part of a balance past zero is on the other side of the book from the account's type, and it has a cost basis there:

- an asset account at −500.00 USD owes 500.00 USD, with a cost basis on the owed side;
- a liability account at +200.00 USD holds 200.00 USD, with a cost basis on the held side.

**A movement that crosses zero is two movements.** The part up to zero moves the side the balance is leaving, and the part past zero moves the other side:

| movement | held side | owed side |
|---|---|---|
| asset account A, 0.00 → −500.00 | nothing | +500.00: a cost basis opens on A |
| asset account A, −500.00 → 0.00 | nothing | −500.00: A's owed cost basis is drawn down, and the difference is realized |
| asset account A, −500.00 → +500.00 | +500.00: a cost basis opens on A | −500.00: A's owed cost basis is drawn down |
| liability account Card, 0.00 → +200.00 | +200.00: a cost basis opens on the card | nothing |
| liability account Card, +200.00 → 0.00 | −200.00: the card's held cost basis is drawn down | nothing |

**One split may cross zero.** A book made in GnuCash's own register holds 1,000.00 USD of income into an account at −500.00 as one split, and its export writes one split. So a split crossing zero is imported as one split, written as every disposal is: it states the cost basis it repays, it is valued at what it repaid at that cost basis's cost plus what it brought in at the rate it came at, and `$residual$` takes the difference.

```
2034-02-01 * "1,000.00 USD of income paid into A"
	currency.mnemonic: "CAD"
	Assets:USD A 1000.00 USD
		share_price: "11/8"
		value: "1375.00"
		cost_basis_split_guid: "<A's owed cost basis>"
	Income:Consulting -1400.00 CAD
	Income:FX Gain $residual$ CAD
```

The part up to zero, 500.00, draws down the owed cost basis the split states, at the 1.35 it cost: 675.00. The part past zero, 500.00, opens a held cost basis on the same split, costed from what is left of the value: 1,375.00 less 675.00 is 700.00, 1.40 each. `$residual$` takes the 25.00 lost on repaying at 1.40 a debt taken on at 1.35. Valued at 1,400.00, the day's rate throughout as GnuCash's register writes it, the split is refused, and the refusal states 1,375.00. Where the account has an owed cost basis, a split crossing zero that states no guid is refused, as every disposal that states none is: the cost basis is never chosen for the reader.

**A transfer out of an empty account is a borrowing.** 500.00 USD moved from A holding nothing to B is 500.00 arriving on the held side at B and 500.00 arriving on the owed side at A. If A held 200.00, then 200.00 is a transfer that moves no cost basis and 300.00 is a borrowing.

## What was reported

The user asked about an asset account taken below zero by a transfer: "What if has asset A and asset B, and transfer 500 USD from A to B such that A -500 Balance and B 500 Balance. the -500 in A is actually some kind of liability in -500 asset. If liability, it should create both cost basis in asset and liability, but we dont do minus cost basis for asset account A". Then: "Shall we model liability in asset minus balance? And asset in liability as minus balance?", and "A is -500 Asset, then the company earns income 1000 directly into A, how will this change?"

## What was investigated

On main at `937f477`, GnuCash 5.10 (Debian 13), with a probe that imports each book with the CLI and prints `fx-balances`, `--verify-integrity` and the balance sheet's gain lines. The book is kept in CAD and holds four USD accounts: bank accounts A, B and C, and a credit card. USD stands at 1.30 on 2034-01-05, 1.35 on 2034-01-10 and 1.40 on 2034-02-01.

**1. 500.00 USD moved from an empty A to B, stated in CAD at 1.35.** A reads −500.00 and B +500.00. No cost basis opens on either. `fx-balances` lists 500.00 held and 500.00 owed in accounts, `--verify-integrity` says the book is consistent and balanced, and the sheet values the currency at GnuCash's own revaluation (`measured_from: gnucash_revaluation`).

The whole transaction is read as a transfer within the held side: B's +500.00 against A's −500.00 nets to nothing, so nothing arrived. A's fall is below zero, and a fall below zero is not a disposal, so nothing left either.

**1b. Then 1,000.00 USD of income into A at 1.40, one split, A going −500.00 → +500.00.** One held cost basis of 1,000.00 at 1.40 opens on A, which holds 500.00. `--verify-integrity` says the book is consistent and balanced, because the held side adds up: A's 500.00 and B's 500.00 against 1,000.00 of cost basis. Realized and unrealized gains are both 0.00.

| | what it should be | main |
|---|---|---|
| A's 500.00 owed, taken on at 1.35 and repaid with dollars at 1.40 | owed cost basis drawn to 0.00, realized −25.00 | no owed cost basis ever existed; nothing realized |
| A's 500.00 held after the income | held cost basis of 500.00 at 1.40 | held cost basis of 1,000.00 at 1.40 |
| B's 500.00, from the transfer at 1.35 | held cost basis of 500.00 at 1.35, unrealized +25.00 | no cost basis; covered by A's at 1.40 |
| gains at 2034-02-01 | realized −25.00, unrealized +25.00 | realized 0.00, unrealized 0.00 |

The totals agree. Where the gain is recorded does not: main never realizes anything on the overdraft, and costs B's dollars at a rate they were never bought at.

**2. C holds 1,000.00 bought at 1.30, then the same transfer, then B's 500.00 sold at 1.40.** Selling B's dollars stating no guid is refused ("this transaction spends 500.00 USD the book held, which draws down a cost basis, but no split says which one"). The only guid the book has is C's, and stated, it is accepted: C's cost basis falls to 500.00 while C still holds 1,000.00. `--verify-integrity` says the book is consistent and balanced, and the sheet at 2034-02-01 states realized 50.00 and unrealized 50.00.

| | what it should be | main |
|---|---|---|
| B's 500.00, borrowed at 1.35 and sold at 1.40 | realized +25.00 | realized +50.00, measured against C's 1.30 |
| C's 1,000.00, bought at 1.30 | cost basis 1,000.00, unrealized +100.00 | cost basis 500.00, unrealized +50.00 |
| A's 500.00 owed, taken on at 1.35 | unrealized −25.00 | not on the page |

Both total 100.00, and the balance sheet balances at 10,100.00. The figures inside that total are wrong, and nothing reports it.

**3. Then A refilled with 500.00 USD from C, at 1.40.** Refused: "this transaction spends 500.00 USD the book held, which draws down a cost basis, but no split says which one". C's fall is a disposal on the held side. A's rise from −500.00 to 0.00 is not counted, because a rise below zero is neither an arrival nor a fall. So a transfer that repays A's overdraft reads as a sale, and A's side of it has no cost basis to state.

**4. A USD card owing nothing overpaid by 200.00 from C at 1.30, then 200.00 of travel charged to it at 1.40.** The overpayment imports and the card reads +200.00. The charge takes it back to 0.00, and opens **a new owed cost basis of 200.00 at 1.40 on the card**. `--verify-integrity` then reports: "the USD cost bases on the liability side hold 200.00, and the book owes 0.00".

| | what it should be | main |
|---|---|---|
| the card's 200.00 credit, paid at 1.30 and spent at 1.40 | held cost basis opened by the overpayment, drawn to 0.00 by the charge, realized +20.00 | no held cost basis; the charge opens an owed one |
| realized at 2034-02-01 | +20.00 | 0.00 |
| unrealized on the liability side | 0.00 | +20.00 |

## Why it happens

Two parts of the code read a balance past zero by its sign, and the rest reads it by the account's type:

- **By sign.** The disposal check floors each account at zero, so a fall below zero spends nothing. `--verify-integrity` counts an account below zero as owed.
- **By type.** Opening a cost basis (`record_cost_bases`, `establishes_cost_basis`), netting a transfer (`_only_moved_within_one_side`), and the check that a guid is a cost basis of the spending split's side (`_validate_pick`) all read the side from the account's type. So a fall below zero on an asset account opens nothing, and a charge on a liability account opens an owed cost basis whatever the card held.

Every case above breaks at that seam.

## What changes

- **Side comes from the movement, not the account type.** A cost basis's side is the side of the movement that opened it. That is the part of the movement before zero or the part past it, not the type of the account it sits on. Opening, netting, the no-guid refusal and the side check all read it that way.
- **One split may both draw down and open.** A split stating a guid draws down that cost basis by the part up to zero. It opens a cost basis of its own for the part past zero, so one split can carry both `cost_basis_split_guid:` and a `cost_basis_balance:`, and the export writes both. A book rebuilt from that export holds the same cost bases: the owed cost basis the split repaid is exported with its balance stated, which a disposal does not lower again (case 11).
- **A transfer out of an empty account opens a cost basis on each side.** The part of the fall past zero arrives on the owed side, and the matching rise elsewhere arrives on the held side.

## Cases the tests cover

`tests/integration/test_a_balance_past_zero_has_a_cost_basis_on_the_other_side.py`, on the book `tests/fixtures/usd_moved_out_of_an_empty_account.txt` makes: C holds 1,000.00 USD bought at 1.30, and 500.00 USD moved from an empty A to B at 1.35.

1. The transfer out of an empty A: an owed cost basis of 500.00 at 1.35 on A and a held one of 500.00 at 1.35 on B. At 1.40 the owed side is revalued by −25.00 and the held side by +125.00.
2. 1,200.00 USD moved from C, holding 1,000.00, to B at 1.40: 1,000.00 moves with no cost basis, and 200.00 opens on each side, held at B and owed at C.
3. B's 500.00 sold at 1.40, stating B's cost basis: realized +25.00, and C's cost basis untouched at 1,000.00.
4. A refilled from C at 1.40: C's held cost basis and A's owed cost basis each drawn down by 500.00, realized +50.00 on C's dollars and −25.00 on A's debt.
5. 1,000.00 USD of income into A at −500.00, one split stating A's owed cost basis and valued at 1,375.00: realized −25.00, and a held cost basis of 500.00 at 1.40 on A. Stating no guid is refused.
6. A card owing nothing paid 200.00 from C, then 200.00 of travel charged to it at 1.40, stating C's cost basis. The payment moves 200.00 within the held side, from C to the card's credit, so it draws down no cost basis and opens none. The charge spends that credit, draws C's cost basis down to 800.00, realizes +20.00, and opens nothing on the owed side.
7. A credit card balance transfer, liability to liability. 300.00 USD charged to a card at 1.35, then the card's whole 300.00 transferred to a second card at 1.40: what is owed moves from one card to the other, so no guid is stated, nothing is drawn down and nothing opens, and the card's owed cost basis at 1.35 stands for what the second card now owes. This was already so on main.
8. The same card transferring 500.00, more than the 300.00 it owes: the card goes to +200.00, a credit it holds. 300.00 moves within the owed side, and 200.00 is a borrowing: an owed cost basis of 200.00 at 1.40 on the second card and a held one of 200.00 at 1.40 on the first. On main the transfer opened nothing, and the second card's 200.00 more owed and the first card's 200.00 held had no cost basis.
9. Paying off more than is owed, the mirror of 8. The card, owing 300.00 charged at 1.35, paid 500.00 from C: 300.00 repays the card, drawing its owed cost basis to nothing and C's held one down by 300.00 to 700.00, and 200.00 moves within the held side to the card's credit, drawing nothing down; 15.00 is realized. A at −500.00 refilled with 1,000.00 from C the same way: C's cost basis falls by the 500.00 the held side lost, not the 1,000.00 C sent, and 25.00 is realized. C's split is valued at what all it sent cost, and the part that moved arrives at that cost. Paid 250.00 from B and 250.00 from C, each stating its own cost basis, it is refused: nothing says which of the two the 200.00 that only moved came out of, and the refusal asks for what moved as a transaction of its own.
10. Both allowances hold only where the accounts moving on the other side are the ones crossing zero. 1,000.00 from C, which holds exactly that, and 200.00 charged to card 2, into B, adds up as a borrowing does, but no account crosses zero: it is a transfer sharing a transaction with an arrival, and it is refused as one.
11. The export of each book imports into a new book with the same cost bases.

## What the work settled

**A split stating a guid crosses zero only where it draws on the side it leaves.** 40.00 USD sold out of an empty bank against an invoice not yet collected, with `cost_basis_force`, states the invoice's guid for all 40.00. Recorded as crossing zero as well, it also opened an owed cost basis of 40.00 for the bank's overdraft, and counted the 40.00 twice. So a split stating a guid that draws nothing on the side it leaves stays a disposal as written, and its guid decides what it drew. `tests/integration/test_cost_basis_must_be_collected.py` and `tests/integration/test_unpost_foreign_currency.py` hold it.

**A purchase written with its signs reversed is a borrowing until it is corrected.** `tests/fixtures/usd_purchase_with_sign_error.txt` takes the bank to −100.00, which owes 100.00 and opens an owed cost basis. The correction is then an edit of a transaction touching a cost basis, which is refused in place and sent to `delete-transactions --by-guid` and a fresh import, as every such edit is. `tests/integration/test_update_strategy_respects_cost_basis.py` follows that route to a held cost basis of 100.00 and nothing owed.

**A split crossing zero is valued at what it repaid and what it brought in, and anything else is refused.** Its value holds both: the part repaid at the cost of the cost basis it states, and the part brought in at the rate the transaction's book-currency splits fetched, the `$residual$` split aside. 1,000.00 USD of income worth 1,400.00 CAD into A at −500.00 is worth 675.00 + 700.00 = 1,375.00. Valued at 1,400.00, the day's rate throughout as GnuCash's register writes it, the 25.00 the repayment lost would sit in the held cost basis, costing the 500.00 at 1.45 with no gain or loss stated; valued at 600.00, the part brought in would cost less than nothing. Both are refused, and the refusal states 1,375.00. Where another split in the transaction moves the same currency and states the cost basis it came out of, the part brought in only moved from it, at that cost basis's cost: the card owing 300.00 paid 500.00 from C is worth 300.00 at 1.35 plus 200.00 at C's 1.30, 665.00, and valued at 700.00 it is refused. Where the split shares its transaction with another foreign currency, the Canadian dollar figures price that currency rather than this one, so the value is the file's statement of it: 1,000.00 USD bought into A with 7,800.00 HKD and valued at 1,375.00 costs the 500.00 brought in at 1.40.

**What a split brought in is recorded by the import, in `cost_basis_brought_in`, and a file may not state it.** It is written only on a split whose account crosses or lies past zero, where it differs from what the account's type says, so a book written before this change reads as it always did, and it is taken off again when an edit leaves the split short of zero: 150.00 USD of fees out of savings holding 100.00 records 50.00 brought in owed, and corrected with `--strategy update` to 80.00 records nothing. The export leaves it out and the import works it out again. A file stating it on any split, or on a transaction, is refused, as `orphaned_by_unpost` is: the import passes a receivable over, so a receivable's 100.00 USD stating `cost_basis_brought_in: "1.00"` would have kept the key and opened a cost basis of 1.00.

**The splits one transaction puts on one account are read in an order of the import's own.** GnuCash does not keep a transaction's splits in the order a file lists them, so each account's splits are read with those moving it the way it moves overall first, then the rest, each in guid order. A card owing nothing charged 150.00 USD and refunded 100.00 in one transaction reads the charge first whichever the file lists first: 150.00 owed, 100.00 of it repaid, and neither split crossing zero. Read refund first, it was a credit of 100.00 brought in and then a charge crossing zero, for a card that went from owing nothing to owing 50.00.

**A split crossing zero that states its own guid is refused for the guid.** What it brought in is costed from the cost basis it repays, which is itself; asked what it cost, it went on asking until Python hit its recursion limit, and the import reported "maximum recursion depth exceeded". A split already being priced now prices nothing, so it is refused as a guid matching no cost basis is, and two splits stating each other's guids the same way.

**A cost basis repaid across zero and then deleted in GnuCash leaves the book readable.** GnuCash does not check what draws on a split before deleting its transaction. With the transfer that opened A's owed cost basis deleted, the income that crossed zero states a guid matching nothing, and what it brought in, costed from the cost basis it repaid, has no cost. It is then no cost basis, and `fx-balances` lists C's 1,000.00 alone.

**The export writes a transaction's currency whenever its splits are all in another one.** 500.00 USD moved between two US dollar accounts in a transaction stated in Canadian dollars was exported with no `currency.mnemonic:` line, because the export wrote one only for splits in more than one currency. The import then read it as a US dollar transaction and each split's 675.00 CAD value as its amount, so the book rebuilt from the export moved 675.00 USD. This was already so on main; case 7 found it.

**An edit in place is read against zero too.** `--strategy update` runs none of the checks a new transaction meets, and the guard that refuses an edit adding a disposal read a split's side from its account's type, so an edit could repay an overdraft or spend a card's credit stating no guid: a Canadian dollar income edited into 1,000.00 USD paid into A at −500.00 left A's owed cost basis standing for a debt that was repaid. The guard reads a currency split against its account's balance on the transaction's date, without the transaction's own splits on it, and refuses both, sending them to delete-and-import. A share's side is still its account's type.

**Currency alone.** A share account below zero is shares sold that were never bought, or bought in a book this one never saw, not shares owed. 10 shares sold out of an account holding none opened an owed cost basis the next purchase would have had to state the guid of, so what a split brings in past zero is read for currency only, and the balance sheet keeps a share account on its type's side.

## Bringing a book imported before this change forward

A book imported before this change has no owed cost basis for an account an earlier import took below zero, because nothing then opened one. The next transaction into that account repays what it owes and draws on no cost basis: 1,000.00 USD bought into A at −500.00 opens 500.00 held for the part past zero, and the 500.00 it repaid is accounted for nowhere. Brought forward through its export, the transfer that took A below zero opens A's owed cost basis in the new book, and that deposit is refused for stating no guid ("this transaction spends 500.00 USD the book owed, which draws down a cost basis, but no split says which one"). It is written as every repayment is: the guid of A's owed cost basis, which `fx-balances` lists, the split valued at what it repaid at its cost and what it brought in at its rate, and a `$residual$` split for the difference.

## Known, not yet investigated

- **A file that lists a later-dated deposit before an earlier overdraft builds cost bases its dates contradict.** `tests/fixtures/usd_parked_on_a_clearing_account_before_the_day_it_held_any.txt` deposits 500.00 USD dated 2032-06-01, then parks −100.00 dated 2032-03-01. Imported first, the deposit opens 500.00 held. The parking, read at its own date, takes the account from 0.00 to −100.00 and opens 100.00 owed. By date, the deposit repaid that 100.00 and left 400.00 held, so the cost bases hold 500.00 and owe 100.00 against the 400.00 the account holds. Before this change the same book held 500.00 against 400.00 and opened nothing owed. A file's transactions are imported in the order the file lists them, which is the order its writer meant.
- **An edit putting two splits on one account reads each from the same balance.** The guard on an edit in place reads each edited split against the account's balance on the transaction's date without the transaction's own splits on it, not one after the other as the import records them once they land, in an order of its own. A charge and a refund on one card, edited in, can be guarded differently from how the import then records them. Every edit the tests make puts one split on an account.
- **A `payment:` block's transaction is not read against zero.** What each split brought in is recorded on a transaction block, on import and on an edit; the transaction GnuCash writes for a `payment:` block goes to `record_cost_bases` without it, so a US dollar bank paying a bill for more than it holds is read by its account's type, as before this change. That transaction is stated in the record's currency, so its bank split carries no figure in the book's currency and opens no cost basis either way.
- **A transaction imported later, dated before a split that crossed zero, leaves what that split brought in as it was recorded.** What a split brought in is read from its account's balance when the split is imported, and nothing reads it again when an earlier-dated transaction is imported afterwards, edited in place with `--strategy update`, or deleted, here or in GnuCash. An edit re-reads the transaction it edits and none after it: correcting fees of 150.00 to 80.00 raises the account's balance on every later date, and a later split recorded as crossing zero keeps what it recorded. With 500.00 USD bought into A on 2034-01-05 and imported after the 2034-01-10 transfer out of it, the transfer still records 500.00 owed on A and 500.00 held on B, though by date A held what it sent. `--verify-integrity` reports both sides: the USD cost bases on the asset side hold 2,000.00 against the 1,500.00 the book holds, and on the liability side 500.00 against nothing owed (`tests/fixtures/usd_moved_out_of_an_empty_account_then_a_deposit_dated_before_it.txt`).
