# Bill Payment Reconciliation (Vendor Bills)

Covers linking bank transactions to vendor-bill payments on the **Accounts Payable** side — partial payments, overpayment (vendor credit), how to detect each state, and how to correct a mis-applied payment with `unapply-payment`.

This is the payable-side companion to [docs/invoice-payment-reconciliation.md](invoice-payment-reconciliation.md) (the receivable/invoice side). The two share the same plaintext shape (`payment:` blocks, `txn_guid:` / `txn_split_guid:`, the bank-feed-first workflow) — read that doc for the shared mechanics and the GUID / error / idempotency reference; this doc covers only what is different about bills. For the canonical end-to-end roundtrip across both sides, see [docs/comprehensive-roundtrip-example.md](comprehensive-roundtrip-example.md).

This page describes:

- [Background: bills mirror invoices on the payable side](#background-bills-mirror-invoices-on-the-payable-side)
- [Bill partial payments](#bill-partial-payments)
- [Bill overpayment (vendor credit)](#bill-overpayment-vendor-credit)
- [Detecting a vendor's bill payment state (paid / partial / overpaid)](#detecting-a-vendors-bill-payment-state-paid--partial--overpaid)
- [Correcting a mis-applied bill payment: fresh + linked, then unapply / re-link](#correcting-a-mis-applied-bill-payment-fresh--linked-then-unapply--re-link)
- [Managing a vendor credit: consume, refund, or write off](#managing-a-vendor-credit-consume-refund-or-write-off)

---

## Background: bills mirror invoices on the payable side

A bill's `payment:` block has the same *shape* as an invoice's — provide `bank_account` and `txn_guid` — but the accounting is the mirror image, not a copy. A bill posts as a **credit to Accounts Payable** (a liability going up) where an invoice posts a **debit to Accounts Receivable** (an asset going up); a bill payment sends money **out** (debit AP, credit Bank) where an invoice payment brings money **in**. Every sign in the bill examples below is flipped from the AR case. The plaintext still carries positive `amount:` values — the importer records the outgoing direction for bills internally.

Just like an invoice, a bill payment can **link an existing bank transaction** (e.g. one already loaded from a bank feed) instead of minting a new one: give the `payment:` block a `txn_guid:` (and optionally `txn_split_guid:`) naming that bank tx, and the importer retargets its AP-side split into the bill's posted lot rather than creating a duplicate:

```
vendor "VEND-001"
	guid: "f66df24e6e75424ba08c2b0a47ec292c"
	name: "Office Supplies Co."
	currency: CAD

bill "BILL-2026-001"
	vendor_id: "VEND-001"
	vendor_guid: "f66df24e6e75424ba08c2b0a47ec292c"
	currency: CAD
	date_opened: 2026-01-01
	entry:
		...
	posted:
		date: 2026-01-01
		due: 2026-01-31
		ap_account: "Liabilities:Accounts Payable"
		memo: "Bill BILL-2026-001"
		accumulate: true
	payment:
		bank_account: "Assets:Bank"
		txn_guid: "abc123def456abc123def456abc123de"
		txn_split_guid: "11223344556677889900aabbccddeeff"
```

Use `find-transactions` with a negative amount to find outgoing payments:

```bash
gnucash-plaintext find-transactions ledger.gnucash \
    --account "Assets:Bank" \
    --date 2026-01-25 \
    --amount 200
```

## Bill partial payments

A bill can carry several `payment:` blocks, one per instalment. A $100 bill paid $40 then $35 keeps a single open AP lot for the $25 still outstanding. Observed directly from the posted book — the posting transaction, then the lot's split list:

```
posting   Expenses:Supplies              +$100.00   (debit expense)
posting   Liabilities:Accounts Payable   -$100.00   (credit AP — the liability you owe)

AP lot (open, balance -$25.00):
  -$100.00  posting   2026-02-01  "Bill BILL-PARTIAL-100"
   +$40.00  payment   2026-02-10  "First instalment"
   +$35.00  payment   2026-02-20  "Second instalment"
```

The lot balance is **negative** (−$25) because it is an unpaid liability you still owe. The equivalent partly-paid *invoice* keeps its AR lot open at a **positive** balance (a receivable still owed to you) — same story, opposite sign. Exported, the bill carries one `payment:` block per instalment (positive `amount:` each):

```
bill "BILL-PARTIAL-100"
	...
	posted:
		ap_account: "Liabilities:Accounts Payable"
		memo: "Bill BILL-PARTIAL-100"
		accumulate: true
	payment:
		date: 2026-02-10
		amount: 40.00
		bank_account: "Assets:Bank"
		txn_guid: "792d3b1ba2bb40009129fd3ee9a70271"
		txn_split_guid: "5062327a7da743138c3011bd23a2046d"
		memo: "First instalment"
	payment:
		date: 2026-02-20
		amount: 35.00
		bank_account: "Assets:Bank"
		txn_guid: "563f541d5a60474885e0459d1fb174cb"
		txn_split_guid: "1f33738186034c9aa0c262654c0d520a"
		memo: "Second instalment"
```

Tax does not change the mechanics — it only raises the payable total. A taxed bill of net $1000 + GST 5% + PST 7% = **$1120** paid $60 stays open at **−$1052** (its posting is −$1120, the payment +$60); a shortfall is always measured against the tax-inclusive total.

## Bill overpayment (vendor credit)

Paying more than the bill total leaves an open AP credit lot — the vendor now owes you. A $100 bill paid $150 in one payment splits the AP side across the bill lot and a new pre-payment lot. Observed from the posted book:

```
payment tx 2026-01-10:
  Assets:Bank                    -$150.00   (cash sent to the vendor — money out)
  Liabilities:Accounts Payable   +$100.00   (bill lot — closes it at $0)
  Liabilities:Accounts Payable    +$50.00   (new pre-payment lot)

AP lot (closed, balance +$0.00):  posting -$100.00, payment +$100.00
AP lot (open,   balance +$50.00): payment +$50.00
```

The residual lot's **+$50** balance is a *vendor credit* — a positive (debit) balance on a liability account means the supplier owes you $50 toward a future bill. This is the sign-inverse of a *customer* overpayment, whose residual AR lot carries **−$50** (money you owe the customer). Export records the split allocation: `amount:` is the $100 that settled the bill lot and `prepayment:` is the $50 residual (together the full $150 that left the bank):

```
bill "BILL-OVERPAY-100"
	...
	posted:
		ap_account: "Liabilities:Accounts Payable"
		memo: "Bill BILL-OVERPAY-100"
		accumulate: true
	payment:
		date: 2026-01-10
		amount: 100.00
		bank_account: "Assets:Bank"
		txn_guid: "56d18d5680b04ce2889911901d6be753"
		txn_split_guid: "527be23007ac44daac35cf9cc177ae9d"
		memo: "Paid 150 on a 100 bill (overpaid 50)"
		prepayment: 50.00
```

For a taxed bill the residual is measured against the tax-inclusive total the same way: net $100 + 12% = $112 paid $150 leaves a **+$38** vendor credit and exports `prepayment: 38.00`.

Apply the credit to the next bill from the same vendor with `auto_apply_credit: true`, or list open vendor credits with `find-prepayments --vendor V001`.

A credit bigger than one bill is drawn down across several. Mark each bill `auto_apply_credit: true` and GnuCash consumes the credit in **posting order** (the order the bills appear on import) until it runs out. A $150 credit against two $100 bills settles the first in full and leaves the second **$50 outstanding** (its AP lot open at −$50), with the credit exhausted:

```
credit before: 150.00
BILL-MB-1 ($100, auto_apply_credit)  → lot 0.00     (settled from credit)
BILL-MB-2 ($100, auto_apply_credit)  → lot -50.00   (took the last 50; 50 still owed)
credit after: 0.00
```

The flag also composes with a cash `payment:` block on the same bill: the cash applies **first** and the credit covers the remainder. So if that second bill also carries a `payment: amount: 50`, the $50 cash plus the $50 of remaining credit settle it — both bills close and the credit reaches $0.

One further asymmetry with invoices: a bill payment's transfer account must be an asset or owner's-equity account — routing it to an expense or income is rejected (`bill payment must use an asset ...`). Writing an unpaid bill off is debt forgiveness (a gain), not bad debt; the bad-debt write-off to an expense exists only for invoices, i.e. money owed *to* you.

## Detecting a vendor's bill payment state (paid / partial / overpaid)

There is no single "list outstanding bills" command; you read each state off the tools below. The examples here use one vendor `V001` with three bills — `BILL-PAID-100` paid in full, `BILL-PART-100` paid $60 of $100, and `BILL-OVER-100` paid $150 on $100.

**Partial / outstanding bills — `print-bill --vendor`.** `print-bill` selects every bill for a vendor (also `--from` / `--to` / an id glob). Compare each `bill_total:` against the sum of its `payment:` `amount:` lines; any shortfall is still owed:

```
$ print-bill book.gnucash --vendor V001 --format plaintext -o -

bill "BILL-PAID-100"
	...
	payment:
		amount: 100.00
	bill_total: 100.00        → paid 100 of 100: settled
bill "BILL-PART-100"
	...
	payment:
		amount: 60.00
	bill_total: 100.00        → paid 60 of 100: $40 OUTSTANDING
bill "BILL-OVER-100"
	...
	payment:
		amount: 100.00
	bill_total: 100.00        → bill lot settled; the extra $50 is a separate vendor credit
```

The exact outstanding figure is the bill's posted AP-lot balance: `0.00` when settled and **negative** while still owed. For the three bills above the balances are `+0.00`, `−40.00`, and `+0.00` respectively (`gncInvoiceIsPaid` is `True`, `False`, `True`) — the overpaid bill's own lot closes at zero, and its $50 excess lives in a *separate* credit lot, which is why an overpayment never masks the settled bill.

**Overpayment / vendor credits — `find-prepayments --vendor`.** A vendor credit is an open AP lot attached to no bill, so scanning bills won't reveal it. `find-prepayments` surfaces every credit and totals it per vendor — this is also how you find credit that accumulated across *several* bills for the same supplier:

```
$ find-prepayments book.gnucash --vendor V001

Found 1 open pre-payment credit.

  • vendor V001 (Supplier Co.)  CAD 50.00  in Liabilities:Accounts Payable
    source bank tx: 2026-03-07 on Assets:Bank  "Supplier Co."
      memo: "Overpaid by 50"
      guid: ff7dd833-8680-45b2-93ba-e181825415eb
    ...
Total credit available: CAD 50.00 for vendor V001 (Supplier Co.).
```

The same credits are also written into every exported AP account as an `open_prepayment:` block, so a plain `export --include-business-objects` shows each account's outstanding credits at a glance:

```
2026-03-01 open Liabilities:Accounts Payable
	open_prepayment:
		vendor: "V001"
		vendor_guid: "3f6d4a17b218c47e85d290f3e9a2b1c4"
		amount: 50.00 CAD
```

From there, settle a partially-paid bill by appending another `payment:` block for the shortfall and re-importing (incremental — only the new payment is applied), and consume a vendor credit against the next bill with `auto_apply_credit: true` (which draws from the open credit across whichever bills it originated from), or refund it by deleting the source bank tx via `delete-transactions --by-guid`.

Credits are always owner-scoped. In a book with several suppliers each holding a credit, `find-prepayments --vendor V-2` returns only V-2's credit, and the unfiltered `find-prepayments` lists every credit under its owner with a per-owner total — so a $20 vendor credit is never confused with a $15 customer credit or another vendor's $30. Apply each only to the next bill/invoice for that same owner.

## Correcting a mis-applied bill payment: fresh + linked, then unapply / re-link

A single bill is often settled by a *mix* of payment kinds, and the fix for a mistake is `unapply-payment` (peel a payment; the bill stays posted, the bank tx is never deleted) rather than unpost. Worked on the taxed $1120 bill (net 1000 + GST 50 + PST 70), settled by two partial payments — a fresh $1000 (`ApplyPayment`, mints its own bank tx) plus a *linked* $120 (a `payment:` block whose `txn_guid:` retargets a pre-existing $120 bank tx):

```
bill "BILL-HERO-1120"      posted lot -1120
	payment: amount: 1000                       (fresh — no txn_guid)
	payment: amount: 120  txn_guid: "…the $120 bank tx…"   (linked)
→ posted lot balance 0.00 (settled)
```

Three corrections from that settled state, each observed:

- **Linked the wrong tx** — peel just the $120: `unapply-payment book BILL-HERO-1120 --bill --txn <120-bank-tx> --to "Liabilities:Due to vendor"`. The $1000 stays applied, the bill drops to **−$120** outstanding, and the $120 bank tx survives (only its split's account changed).
- **Pay from a prior credit instead** — peel everything: `unapply-payment book BILL-HERO-1120 --bill --all --to "Liabilities:Due to vendor"`. The bill returns to **−$1120** fully outstanding; re-import it with `auto_apply_credit: true` to settle it from an existing vendor credit rather than cash (the credit lot is consumed by the amount of the bill, any residual staying open).
- **Applied the wrong bank tx for the net** — peel the $1000 (`--txn <1000-bank-tx>`), leaving the $120 applied and **−$1000** outstanding; then import the correct $1000 bank tx and re-import the bill with a `payment:` block whose `txn_guid:` links it. The lot closes again (0.00), now settled by the corrected tx, and the original $1000 tx survives in your `--to` account.

On a bill with several payments, `unapply-payment` needs a selector (`--txn <bank-tx-guid>`, repeatable, or `--all`); omitting it on a multi-payment record is an error, never a guess. See the README's `unapply-payment` section for the full option reference.

## Managing a vendor credit: consume, refund, or write off

A vendor credit is money the supplier owes you back (you overpaid them) — GnuCash holds it as an open, **positive** AP lot attached to no bill. Managing it is therefore separate from any single bill: there are three dispositions, all non-destructive (none touches the original overpayment transaction), and the **counter account states the intent**:

| Disposition | How you record it | Counter account | Cash movement | What it means |
|---|---|---|---|---|
| **Consume** on the next bill | `auto_apply_credit: true` on that bill's header | — (internal lot move) | none | The vendor's next bill(s) draw the credit down |
| **Refund** (the vendor pays you back) | `lot_owner: vendor:V001` on an AP split | an **asset** (bank / cash) | **+ into the bank** | Collect the receivable in cash — **not an expense** |
| **Write off** (you'll never recover it) | `lot_owner: vendor:V001` on an AP split | an **expense** | none | Recognise the loss — the *only* case that hits an expense |

- **Consume it on the next bill** — `auto_apply_credit: true` (above). The usual path: GnuCash draws the credit into the vendor's next bill(s).
- **Refund** — the vendor returns the money. Record a normal transaction whose AP split carries a `lot_owner:` KVP; the counter account is the bank:

```
2026-02-15 * "Refund received from Supplier"
	currency.mnemonic: "CAD"
	Assets:Bank 50.00 CAD
	Liabilities:Accounts Payable -50.00 CAD
		lot_owner: vendor:V001
```

- **Write off** — you will never use it (e.g. the vendor ceased trading). Same shape, counter = an expense:

```
2026-02-15 * "Write off Supplier overpayment — ceased trading"
	currency.mnemonic: "CAD"
	Expenses:Supplies 50.00 CAD
	Liabilities:Accounts Payable -50.00 CAD
		lot_owner: vendor:V001
```

The `lot_owner: vendor:V001` KVP joins the AP split to the vendor's oldest open credit lot and reduces it — an exact amount closes the lot, a smaller amount leaves the residual credit open (a partial refund). A `vendor:` KVP must sit on an AP account (a `customer:` KVP on an AR account); the importer rejects the mismatch.

**What the refund moves, and why it is not an expense.** Observed from the book (bill $100 paid $150, then the vendor refunds $50): the $50 comes **out of the AP credit and into the bank** — `Liabilities:Accounts Payable` goes `+50 → 0` (the amount the vendor owed us is collected) and `Assets:Bank` rises by $50; the credit lot closes. Nothing else moves — the bill's original $100 expense is untouched. This matches the intuition that overpaying a vendor is, in effect, a **receivable** (the vendor owes you your money back): GnuCash carries it as a positive (debit) balance on Accounts Payable rather than in a separate asset account, and the refund collects it in cash. Only the **write-off** above hits an expense — that's the different case where the money is *gone*, not returned.

### The credit round-trips in the export — the "special directives"

You never have to re-derive an overpayment by hand: the credit state is carried by three exported directives, so it survives export → fresh-book re-import intact:

- **`prepayment: N`** on a bill's `payment:` block — the overpayment residual that opened the credit (see [Bill overpayment](#bill-overpayment-vendor-credit)).
- **`open_prepayment:`** block on each AP account — the owner, owner guid, and amount of every open credit (see [Detecting…](#detecting-a-vendors-bill-payment-state-paid--partial--overpaid)). It is informational: the importer rebuilds credits from the `lot_owner:` KVPs, not from this block, so a hand-edited summary that disagrees only prints a warning and is overwritten on the next export.
- **`lot_owner: vendor:ID[:guid]`** on the AP split of a disposal transaction — the durable link between a clearing / refund / write-off split and the vendor's credit lot. The trailing owner guid is emitted on export and optional by hand.

So the whole lifecycle lives in plaintext: `find-prepayments --vendor` (or the `open_prepayment:` blocks) to see credits, `auto_apply_credit:` to consume, or a `lot_owner:` transaction to refund / write off.
