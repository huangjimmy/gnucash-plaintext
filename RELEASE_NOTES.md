# Release Notes

## Unreleased

### Breaking: changes that affect ledgers and scripts that worked before

**`import` exits non-zero when it reports an error.** A run that collected per-object errors used to print `Errors: N` and still exit 0, so `gnucash-plaintext import book.gnucash ledger.txt && next-step` ran the next step over a partly-imported book — and the same command with `--include-business-objects` exited 1, so one file got two answers depending on a flag. The exit code now follows what the summary says. Scripts that chained on success will stop where they previously continued, which is the point; a script that wants the old behaviour should test the summary itself rather than the exit code.

This includes `import --dry-run`, which is the case likeliest to be scripted: a dry run over a file with per-object errors now exits 1, so `import --dry-run && import` stops rather than running the real import over exactly the file the dry run objected to. It still writes nothing — reporting and saving are separate — and a clean file's dry run still exits 0.

**`delete-transactions` exits non-zero when it could not write an undo copy.** The transaction is still removed — this command is the only way to remove one the format cannot write, and it warns on stderr and says so in the backup file itself. What changed is the exit code: `delete-transactions … -o undo.txt && next-step` chained on a backup holding nothing but comments, because the file existed and the run said it went fine. A script that wants the old behaviour should test for the transaction's absence rather than the exit code.

**A `payment:` block may no longer spend a foreign account whose cost bases still have a balance.** Cash leaving a foreign account is a disposal and has to name the cost basis it comes out of, and a payment block has nowhere to name one — GnuCash's own `ApplyPayment` writes the bank split. Such a payment is now refused, naming the account, what the payment spends, and what balance its bases still have between them.

This reaches ledgers that imported cleanly before, because settling *into* a foreign account is itself what opens a basis on it, and it is asked of every foreign bank rather than only one in a third currency — paying a USD bill out of a USD bank whose bases still have a balance drifts the same way and reaches none of the cross-currency arithmetic. Write the settlement as an ordinary transaction whose bank split carries `cost_basis_split_guid:`, and attach it to the document with `txn_guid:` / `txn_split_guid:`. README's foreign-currency section shows the shape, and [docs/multi-currency.md](docs/multi-currency.md) lists the refusal beside the others.

**`cost_basis_available:` is now `cost_basis_balance:`, and `--available-only` is now `--with-balance-only`.** *Available* named nothing — available for what, of what — and the figure it holds is a balance: how much of that cost basis has not been sold. The key, the `fx-balances` column (`AVAILABLE` → `BASIS BALANCE`), the totals line (`Available USD:` → `Total USD basis balance:`) and every refusal that mentioned it now say so.

A file still stating `cost_basis_available:` is **refused by name**, pointing at the new key. It is not accepted quietly: the old spelling is no longer a reserved key, so it would be kept as an ordinary custom key that nothing reads — the balance unchecked, the file's own sales not counted as already applied, and the basis re-opened at everything it brought in. That gives back currency the same file records as sold. The figure itself does not change; only the key.

Books already written carry the old KVP and are read as they stand — the balances are not lost and nothing has to be re-imported to recover them. `fx-balances` shows them, a sale can be measured against them, and the next write of a basis replaces the old key with the new one. It is only a *file* stating the old key that is refused, because a file is where the wrong reading would do damage. Scripts passing `--available-only` need the new flag; there is no alias.

**A booked amount is judged against the currency as well as the account, so some ledgers that imported cleanly are now refused.** An amount used to be measured against its account's own unit alone, so `Expenses:Fuel 1.819 CAD` on an account carrying `commodity_scu: 1000` imported without complaint. It is now measured against the coarser of the two — there is no such thing as a tenth of a cent of Canadian money, whatever account it sits in — and that file is refused:

```
error: the amount on split 'Expenses:Fuel' states 1.819 CAD, which is finer
than that currency: its smallest unit is 0.01, and a booked amount is a whole
number of those …
```

**A ledger that imported cleanly before may now be refused**, and for this one there is no correction that keeps the figure: 1.819 is not an amount of money, so the remedy is to round it (`1.82`) or split it across entries. What the finer account is still for is everything that is not a booked amount — a unit price, a quantity, a rate — and `commodity_scu:` still round-trips. The rule now runs both ways: an account kept to whole dollars refuses `18.19` too, rather than rounding it to 18 and leaving GnuCash to park the difference in `Imbalance-CAD`.

**`export` refuses a whole book over one figure the format cannot write.** A split holding a sub-cent amount — `1.819 CAD`, which GnuCash's own GUI stores happily on an account kept to thousandths — makes `export`, `export --include-business-objects` and `export-beancount` refuse the entire book rather than write a file the importer would reject on the way back in (see the amount rule above). Every offender is named in one run, so the book is fixed in one pass rather than one export at a time.

There is no `--skip-unwritable`: a partial export is a ledger that silently omits transactions, which is the failure the refusal exists to prevent. That leaves `export` unable to get such a book out of GnuCash and into this format at all, and the remedy is to correct the amount in GnuCash. `delete-transactions` is the one command that proceeds anyway, because refusing there would leave no way to remove the offending transaction from inside this tool; it warns that no undo copy could be written.

**`print-invoice --format plaintext` and `print-bill --format plaintext` refuse the same figures the export refuses, and write nothing when they do.** A printed document carries the guids that make it re-importable, so its `payment:` block states an amount another book will act on — and the renderer used to round what the export refused, printing `amount: 30.00` for a settling split of 30.005 on a receivable kept to thousandths. One book, one figure, and the answer decided by which command you asked. Both now give the export's answer, and a run that refuses leaves no file behind: with `-o out/` the documents are all rendered before any of them is written, so the directory is either every document or none, never the ones up to the offender.

**`export-beancount` refuses a whole book over a split whose value the format cannot state.** Two shapes, both coming down to the same property: the figure after `@@` is a *cost*, and a posting's sign comes from its units.

- **A return of capital** — zero shares against real money, which GnuCash's own investment documentation prescribes and which GnuCash stores as amount 0 with a value. Beancount weighs a posting by its units times its cost, so nothing times anything is nothing and there is nowhere to put the money.
- **A value opposing its units** — `+10 HOOL` worth `−50.00 USD`, which GnuCash keeps across a save and reload. `10 HOOL @@ 50.00 USD` weighs +50.00 and `-10 HOOL @@ 50.00 USD` weighs −50.00, so no total states this: written unsigned it came back with the sign of its units, silently, because the importer rebuilds the value as `amount × (total / |amount|)`.

Written anyway, each posting would lose the only figure that matters, so the split is named and the export refused. Unlike the sub-cent amount above, neither is a mistake to correct — the book is right and the format cannot hold it. Export such a book as plaintext, which states the units and the value separately and signs each; `export --include-business-objects` is unaffected.

**The sharpest version of this is a currency whose unit GnuCash changed under you.** The rule reads the fraction GnuCash holds *now*, and GnuCash disagrees with itself across versions: the won is 1/100 before GnuCash 5.15 and whole units after. So a book with sub-unit KRW amounts, written when they were legal, has every one of those splits refused the day it is opened on 5.15 or later — by `export`, `export --include-business-objects` and `export-beancount` alike, and for the whole book rather than the split. Re-importing cannot buy it back either: an amount is judged against the coarser of the account's unit and the currency's, so declaring `fraction: 100` in the file does not restore it.

That is the rule working — those amounts genuinely cannot round-trip on a version that has no sub-unit won — but it reaches ledgers whose figures were correct when written, and the remedy (round each amount in GnuCash) is one the new version will not let you undo. If you keep a book in a currency GnuCash has restated, export it on the version you wrote it with before upgrading. The same applies to any ISO currency whose fraction changes in a future GnuCash release.

**A block that omits what it would destroy is refused rather than obeyed.** A document and a transaction are both rebuilt from their block, so a line missing from the file is a line removed from the book — which is what lets a split be deleted by deleting a line, and also what a file cut short by a failed write or a half-finished edit looks like. Three shapes are now refused where they previously went through:

- an invoice or bill block with no `entry:` lines, against a document that has some — `INV-001 has no lines in this file and 1 in the book … would unpost it and leave it empty`;
- a transaction block with no split lines under `--strategy update`, against a transaction that has some — `has no splits in this file and 2 in the book … would leave it with no money in it`. This one previously rebuilt the transaction empty, and the transaction was then gone from the book entirely;
- `currency:` differing from what the book holds for an existing customer, vendor, invoice or bill — `C-001 is in CAD in this book and the file says USD`. Previously reported as `unchanged`, so the file and the book disagreed with no word said.

Each names the count on both sides, so a truncated file is distinguishable from a deliberate emptying. To empty a document deliberately, state the block without the lines you are removing; to leave it alone, remove the block from the file.

**Other refusals that reach ledgers which imported before.** Each replaces a silent wrong answer:

- **`tax_table:` naming a table the book does not hold** is refused. It used to be skipped in silence, so the document posted untaxed — and because a re-import then found the document differing from its file, it unposted and reposted it on every run.
- **A `commodity` in the `CURRENCY` namespace that is not ISO 4217** is refused. It previously "succeeded" and left a book GnuCash could not load.
- **A `fraction:` a file declares for an ISO currency no longer loosens the amount rule.** The declaration is still applied, so a book carried between two GnuCash versions stays the book it was — the yen and the won are shipped differently across supported distros. But GnuCash writes an ISO currency by code and looks its fraction up again when reading the book back, so a *finer* one lasts only as long as the import, and a booked amount is now judged against what the book will still hold afterwards. `fraction: 1000` for CAD beside `Expenses:Fuel 1.819 CAD` previously imported with `Errors: 0`; reopened, CAD was a hundredth again, the split was sub-cent, and `export` refused the whole book with nothing inside this tool able to correct it. That file is now refused at the amount, naming the figure. To keep a finer unit, put it on the account with `commodity_scu:`, which round-trips.
- **`prepayment:` on a `payment:` block must equal what the payment actually leaves.** `prepayment: 50` against a payment leaving 100.00 imported with `Errors: 0`, and the next export wrote `prepayment: 100.00` back over it.
- **A `txn_guid:` that names nothing, on a block describing money the book already holds**, is refused instead of paying twice. A guid that resolves to nothing has two readings the block cannot tell apart — a document being rebuilt into a fresh book, where the bank transaction genuinely is not there, and a retarget against the book that holds it, where the guid is simply a typo. The first must go through, because `print-invoice` names the transactions so the same book relinks rather than paying twice and a printed file has to be readable elsewhere; the second used to mint a second payment for money that had moved once, note it on stderr, and exit 0. What separates them is the book: the block's own date, amount, direction, account and memo are compared against what is there. A rebuild into a book that never held the money matches nothing and is unaffected. The refusal names the transaction it found — with its guid, and with the document that money already settles — so the remedy is either to correct the guid to it or to drop `txn_guid:`, which the message says.

  Two documents can describe the same movement in every field a block carries, and then the file says nothing that tells them apart, so the refusal fires on the second: one customer with two invoices for the same figure, paid on the same day into the same account, with the same memo on both bank lines. Give the second payment its own `memo:` — which is what a memo is for — and both import. Across two *different* owners it never fires, because correcting the guid there is not an operation at all: one customer's receipt cannot settle another's invoice.
- **`--include-business-objects` over a file the parser cannot read** is refused outright, and with `--new` the book it created is removed. Before, the run reported the parse error and saved whatever the business-object pre-pass had already made.
- **`find-transactions --amount` matches exactly**, where it used to be read as a float and matched within half a cent: on a fund account kept to thousandths, a search for 12.345 returned 12.346 and everything from 12.341 to 12.349 with it. **`--date` is validated** by the same callback every other command uses — `--date 3/2/2026` used to report no matches and exit 0, and is now `Date must be in YYYY-MM-DD format, got: 3/2/2026`.

With `--include-business-objects` the save is all-or-nothing, so any of these firing on the second invoice discards standalone transactions that imported fine earlier in the same file. That is not new, but there are more ways to reach it.

**`import-beancount` refuses files it used to read.** Hand-editing an export is the reason this format exists, so these are ordinary shapes to arrive at, and each previously produced a book that did not say what the file did. They fall into two groups by what they cost.

*The file is refused whole*, because the parser cannot get past the line and reading on would mean guessing:

- **a posting line it cannot read**, and **a posting that lost its indentation** — both previously dropped in silence, so the transaction imported with a split missing and GnuCash balanced the remainder into `Imbalance`. A posting whose amount is left out for beancount to infer is refused by the same message: this reads figures, it does not work them out;
- **`{}`**, which asks for the cost to be inferred from the lots the account already holds, and **a total stated against no units** (`0 HOOL @@ 50.00 CAD`), which beancount weighs as nothing times anything;
- **an amount, cost or rate that is not a number**, and **a date that does not exist** (`2026-02-30`) — previously a bare `ValueError` naming neither the file nor the line;
- **`open` with no currency constraint**, naming the line. Beancount leaves it optional and reads it as *any* currency; a GnuCash account is kept in exactly one, so there is nothing to write. It previously surfaced three directives later as `Cannot find commodity (CURRENCY, )` — a complaint about a commodity, on a line that names none. A trailing `;` comment on an `open` or a `commodity` is also a comment now, where before it was read as the currency itself;
- **a `gnucash-name` that names nothing** — empty, or ending in a `:` so one part of the path is blank.

*The object is refused and the rest of the file still imports* — the run reports the failure and exits 1, and, as before, saves nothing when anything failed:

- **a posting in a commodity its account does not hold**. The commodity on the posting line was read for the entry's currency and then never asked about again, so `Assets:Bank 50.00 USD` on a CAD account booked 50.00 CAD;
- **a posting in a different commodity from its transaction that says nothing about what it is worth in it** — previously valued at its own figure, leaving GnuCash to invent an `Imbalance` split;
- **a rate stated in a third commodity, or in shares**. A split's value is in the transaction's currency, so the rate has to be too: 15,000 yen quoted per USD inside a CAD entry was valued at 100.00 CAD instead of 135.00, and an exchange ratio (`-100 OLDCO @ 0.5 NEWCO`) valued the shares given up at 50.00 CAD — a figure with no source in the file;
- **a transfer in kind with no posting in a currency**. The only thing left to denominate the entry in is a security, and GnuCash does not keep such a transaction past a save: measured, it read back in the book's own currency with the units gone;
- **an amount finer than the unit its account is kept to** — `12.3456` on a thousandths fund account was stored as 12.346 with `Errors: 0`. This is the same rule the plaintext importer applies, through the same judge, so which format the reader edited no longer decides the answer;
- **a `commodity` in the `CURRENCY` namespace that is not ISO 4217**, as in plaintext above.

**`export-beancount` writes a different file, still valid beancount.** Two changes reach anything consuming that output outside this tool:

- a converted posting states its **total, in the transaction's currency** — `Assets:Bank:JPY 2000000 JPY @@ 18200.01 CAD` — rather than a per-unit `@ 0.00910001 CAD`. A rate is a division, so a per-unit figure has to be multiplied back to get the money, and at the eight places the exporter wrote it that error passes half a cent once the amount reaches about a million: ¥2,000,000 worth 18,200.01 CAD came back a cent out while its counterpart split came back exact, and GnuCash parked the difference in an `Imbalance` split. `@@` states the figure the book holds, so nothing is reconstructed;
- accounts kept to a finer unit than their currency carry `gnucash-scu: "1000"`, which is what lets `import-beancount` rebuild the account rather than silently coarsening it.

The round trip is tested both ways. A reader that parsed the old `@` form needs to handle `@@`, which beancount itself treats as the same fact stated differently.

**A printed document now carries the guids that make it re-importable.** `print-invoice`/`print-bill --format plaintext` emit `posted_txn_guid:`, and on each payment `txn_guid:`, `txn_split_guid:` and `num:`, where they previously emitted a date, an amount, an account and a memo and said so in a comment: *"the rendered file is for human consumption, not re-importing full lot structure."* That turned out to be the wrong half of the trade — a printed document read into the book it came from paid every invoice a second time, because nothing in it named the money that had already moved.

So it names it, and **the guids of your book travel with any document you hand to someone else**. They are opaque identifiers of transactions in your ledger, not figures, and they resolve to nothing in any other book — but they are there, and a reader sending documents outside the company should know it. In exchange the document is a ledger: read back into its own book it relinks rather than paying twice, and read into a fresh one it rebuilds the document and the payments it can describe.

A printed payment now also states `prepayment:`, the residue an overpayment leaves on the owner's account, which only the ledger export used to write. Without it a printed 250.00 deposit against a 100.00 invoice was rebuilt as a 100.00 payment — the bank short by 150.00, the customer's credit never created, and the run exiting 0. On a block that names a transaction, `amount:` is this document's own slice and `prepayment:` what the movement left over, so rebuilding one makes the whole movement; a block naming no transaction still reads `amount:` as the payment to make, unchanged.

The one thing a printed document cannot describe is the rate a **converting** payment settled at — a USD invoice paid into an HKD bank moved two figures and the page carries one. Read back into its own book the guids resolve and no rate is needed; read into a book that never held the settlement, it is refused by name and pointed at `settled_amount:`, rather than settled at a guess.

What a printed document no longer carries is **custom slot keys** — the arbitrary metadata a book may hold against a customer, vendor or document, which is internal and was being printed on the page. The owner's address is emitted instead, which is what a document is meant to show.

**`export --include-business-objects` states what it used to drop.** A `vendor` block carries `addr1:`…`email:` and a `bill` block carries `billing_id:` and `notes:`, both of which the customer and invoice blocks always had. A vendor's address and a bill's notes previously survived an import and vanished on the way back out, so a round trip through this format lost them.

**Other things a run says that it did not say before.** `fx-balances --verify-costs` also checks each currency as a whole — what its cost bases hold between them against what arrived less what was sold — and warns, naming the currency, both figures and the difference. It is a warning and not a refusal: the book is readable, and it is the book that needs looking at. And a book that will not open is answered in words rather than a traceback: GnuCash reports every such state as `call to begin resulted in the following errors, ERR_BACKEND_LOCKED`, which now reads as *"The book is locked, which means GnuCash has it open"* with what to do about it, and likewise for a read-only directory and for a path that is not a GnuCash XML book at all. A book open in GnuCash is the commonest situation there is, and it used to meet every command in this tool as a traceback with no message.

### Multi-currency: a third currency is supported and tested

A document in one currency settled into a bank in another — a USD invoice paid into an HKD account, a CAD invoice paid into one — is tested end to end, along with spending what such a settlement brought in. `--fx-rates` must carry the **bank's** currency as well as the document's: the CAD value of what landed cannot be derived from the document's rate alone, and a file missing it is refused by name rather than settled at a guess. `docs/multi-currency.md` previously said a third currency was untested and unclaimed; that is no longer true.

## v0.3.3 - Payment workflows, statement import, business-object round-trip hardening (2026-05-20)

This release closes the round-trip story for invoices, bills, and payments, and adds an end-to-end pipeline for reconciling raw bank statements into import-ready plaintext. Two months of bug fixes, format extensions, and new CLI subcommands.

### Payment workflows

Posted invoices and bills now accept incremental edits via re-import: append a `payment:` block to a posted record, re-import, and only the new payment is applied — the posting transaction, every entry, and the original bank-side payment transactions on the lot keep their GUIDs. Overpayments create an AR/AP credit lot for the owner; subsequent invoices/bills can consume the credit by setting `auto_apply_credit: true`. ([Q-015](docs/issues/Q-015-incremental-payment-reimport-rebuilds-destructively.md))

Single-invoice payment retarget and multi-invoice shared bank transactions now round-trip cleanly: both the bank-side transaction and the invoice's payment block emit the full transaction GUID plus per-split GUIDs, and the importer processes standalone transactions before business objects so `payment: txn_guid:` resolves on the first pass. ([Q-016](docs/issues/Q-016-full-guid-emission-and-import-order-for-payment-roundtrip.md))

```bash
# Append a payment to a posted invoice
$EDITOR ledger.txt   # add another payment: { ... } block
gnucash-plaintext import mybook.gnucash ledger.txt --include-business-objects
```

### New CLI subcommands

- `unpost-invoices` / `unpost-bills`: unpost without re-import. Warns about bank-side payment transactions that would become orphan if their lot is unposted. ([Q-014](docs/issues/Q-014-orphan-payment-warning-on-unpost.md))
- `delete-invoices` / `delete-bills`: remove unposted invoices and bills from the book (refuses posted records — unpost first). ([Q-013](docs/issues/Q-013-delete-unposted-invoice-bill.md))
- `find-orphan-payments`: list bank-side payment transactions whose AR/AP lot is no longer attached to any invoice or bill. Read-only.
- `find-prepayments`: list open AR/AP credit lots not yet consumed by an invoice or bill. Read-only.
- `find-transactions`: search transactions by account, date, or description.
- `delete-customers` / `archive-customers` / `archive-vendors`: retire owners by ID or `--by-guid`. Archive flips the `active` flag; delete refuses owners with open invoices, bills, or payments. ([F-011](docs/issues/F-011-customer-active-delete.md), [Q-007](docs/issues/Q-007-delete-archive-by-guid.md))

### Statement import pipeline

A four-stage pipeline takes a raw bank statement (CSV / OFX / QFX provider) through reconciliation against the book and produces an import-ready plaintext file with categorized splits.

1. `StatementProvider` — adapter protocol for statement sources.
2. `StatementReconciler` — matches statement rows against existing transactions in the book (by date + amount + memo signature).
3. `ReconcilePreviewWriter` / `ReconcilePreviewReader` — human-editable preview file lists matches, ambiguous rows, and unmatched rows.
4. `GnuCashFuzzyMatcher` + `ReadyToImportWriter` — suggests counter-accounts from history and emits import-ready plaintext.

See [docs/statement-import-pipeline.md](docs/statement-import-pipeline.md) and [docs/bank-import-workflow.md](docs/bank-import-workflow.md). ([F-005](docs/issues/F-005-data-models-and-provider-protocol.md)..[F-009](docs/issues/F-009-ready-to-import-writer.md))

### print-invoice: plaintext output and multi-invoice selection

`print-invoice` gained a plaintext renderer with audit-friendly tax totals (subtotal, per-tax-table breakdown, total) suitable for `git diff` review of quarterly invoices. Multi-invoice selection by date range, customer, or glob produces either a combined PDF or one file per invoice. The `action:` field is now optional. ([Q-011](docs/issues/Q-011-invoice-action-optional-and-custom-template.md), [Q-017](docs/issues/Q-017-print-invoice-plaintext-format-and-multi-invoice.md))

```bash
# Plaintext, all Q1 2026 invoices for one customer
gnucash-plaintext print-invoice mybook.gnucash \
  --customer C001 --date-from 2026-01-01 --date-to 2026-03-31 \
  --format plaintext -o q1-acme.txt

# One PDF per invoice, into a directory
gnucash-plaintext print-invoice mybook.gnucash \
  --customer C001 --date-from 2026-01-01 --date-to 2026-03-31 \
  --format pdf -o q1-acme/
```

Also: `print-invoice` no longer crashes on unposted invoices. ([Q-012](docs/issues/Q-012-print-invoice-on-unposted-invoice-crashes.md))

### A printed invoice or bill is the page GnuCash prints

`print-invoice` and `print-bill` render through GnuCash's own **Printable Invoice** — the report its File → Print Invoice uses — so a document carries GnuCash's heading, columns, totals and wording rather than a layout of this project's. Every supported version draws it, GnuCash 3.8 included: a Guile interpreter runs inside this process and is handed the book already open. ([Q-036](docs/issues/Q-036-printed-documents-are-not-gnucashs-page.md))

**Fixed: a foreign-currency document printed the wrong amount.** Take a USD 100.00 invoice posted to a CAD income account, in a book where the rate that day was 1.40.

- **Before:** the printed invoice said `USD 140.00`. That is the CAD figure — what the book valued the receivable at — with `USD` in front of it. The customer was asked for the wrong amount.
- **Now:** the printed invoice says `USD 100.00`, which is what the invoice is for.

The line items were always right; it was the subtotal, tax and amount due that were wrong, so the page disagreed with itself.

**Changed: `--template` is replaced by `--report` and `--report-file`.** The old flag took an XSLT stylesheet for this project's own renderer, which was a second implementation of the same document and carried the same currency defect as the first. Both it and that renderer are gone; scripts passing `--template` will need updating.

Customising the page is now choosing or writing a GnuCash report, which is what the page is:

```bash
# one of the five reports GnuCash ships: Printable Invoice (the default),
# Fancy Invoice, Easy Invoice, Tax Invoice, Australian Tax Invoice
print-invoice book.gnucash INV-001 -o inv.pdf --report "Fancy Invoice"

# or one you wrote, in the language GnuCash's own are written in
print-invoice book.gnucash INV-001 -o inv.pdf \
    --report-file my-invoice.scm --report "My Invoice"
```

`--report-file` loads a `.scm` before the report is looked up, so a file calling `gnc:define-report` is registered by the time `--report` names it — GnuCash's own extension point, and the same report works from GnuCash's GUI. `tests/fixtures/a_report_of_your_own.scm` is a minimal one to start from; the README section "Changing the page means changing the report that draws it" has the details.

**What the printed document itself gained, against the last release:**

- free text of your own — the book's `extra_text1:`, `extra_text2:` … lines under your company, and the customer's or vendor's own under theirs. One key is one printed line, printed exactly as written. No other custom key reaches the page;
- GnuCash's "Invoice in progress…" on an unposted document, in place of this project's DRAFT badge and "figures are provisional" caption.

**What it lost:**

- the per-line **Tax Applied** column, which named each line's tax table (`GST 5% + PST 7%`, or `Exempt`). GnuCash's page marks a line `T` in a `Taxable` column instead, and names each tax with its own amount in the totals below;
- an unposted document's `due_date:` — GnuCash takes a document's dates from its posting, so an unposted one shows none. The key still round-trips through the format, and a report of your own can print it.

**What it kept** — worth saying, because these are what a filer checks for: the GST and each PST registration number, the seller's `contact:`, the document's `notes:`, and the tax named per account with its own amount. The old page carried all four and so does this one; two of them are GnuCash rows this tool switches on, because it ships them off.

Everything else on the page is GnuCash's own wording, columns and totals rather than this project's.

### Text files are read and written as UTF-8, whatever the machine's locale says

Every file this tool reads or writes as text — ledgers, beancount files, printed documents, exported accounts, reports, the FX-rates YAML — now states UTF-8 explicitly. It used to take whatever `locale.getpreferredencoding()` answered, which is UTF-8 on a desktop and often ASCII in a container, a cron job or CI with no `LANG` set.

Nothing changes for you if your locale is a UTF-8 one, which is the usual case. If it is not, and your book names anybody outside plain ASCII, then **before** this release:

- `export` truncated the destination file to empty and *then* raised `UnicodeEncodeError`, leaving a 0-byte ledger where a good one had been;
- `import` refused a ledger naming a customer `Éditions Cliché` with `'ascii' codec can't decode byte 0xc3`;
- `validate` — with no `--report`, which is the usual form — failed outright on a *valid* book, because the warning it was printing named an account like `Income:Dépenses accessoires`;
- `print-invoice` and `print-bill` failed the same way as `export` for `--format html` and `--format plaintext`: the destination truncated, then the write raised. Under a Latin-1 locale they wrote Latin-1 bytes instead, into a page whose own `<meta charset>` says UTF-8 — mojibake in the browser, with nothing reporting a problem. And where the page got as far as being drawn, GnuCash had already replaced each character its locale could not hold with `?`, silently and with a zero exit.

**Now** all of them work, and `export` → `import` round-trips such a book unchanged.

Two spellings of the same destination also disagreed: on `export-transaction` and `delete-transactions`, `-o file.txt` wrote UTF-8 while `-o -` wrote whatever the locale gave. Both write UTF-8 now, on those two and on the print commands, which matters because `-o -` is the form piped back into `import`.

### Cash-basis invoice KVP

Invoices can be tagged `cash_basis: true` to identify revenue that should be reported on the payment date rather than the invoice date — for cash-basis tax filers (Canadian small business below the CRA threshold, US Schedule C, single-entity service consultancies). The flag is descriptive metadata stored as a KVP slot; it round-trips and does not change accounting behaviour. ([Q-018](docs/issues/Q-018-cash-basis-invoice-kvp.md))

Its companion `due_date:` — for an unposted cash-basis invoice, which has no posting to take a due date from — still round-trips, and no longer appears on the printed page: GnuCash's report takes a document's dates from its posting and draws an unposted one as "Invoice in progress…". Putting it back is a change to that report rather than a flag here, since this tool passes no layout of its own; see "Changing the page means changing the report that draws it" in the README.

### Business-object round-trip correctness

- Exported account-type short-forms (`A/Receivable`, `A/Payable`) no longer crash re-import. ([Q-003](docs/issues/Q-003-account-type-export-not-reimportable.md))
- Invoice payment blocks no longer create duplicate bank transactions when the same posted invoice is re-imported. ([Q-004](docs/issues/Q-004-payment-transaction-duplicates.md))
- Business-object IDs are enforced unique on re-import, and full GUIDs are exported so conflict detection works across export/import cycles. ([Q-006](docs/issues/Q-006-business-object-id-uniqueness-and-guid-export.md))
- Tax-table identity is enforced on import — re-importing a tax table with the same name no longer creates duplicates. ([Q-008](docs/issues/Q-008-taxtable-identity.md))
- Posted invoices and bills are now mutable via the unpost-rebuild-repost cycle the importer runs internally; `unchanged` status is reported strictly when no field differs. ([Q-010](docs/issues/Q-010-strict-updated-status-on-no-change-reimport.md))
- Import emits explicit create / update / unchanged / skip signals for every business object so re-imports are no longer silent. ([Q-009](docs/issues/Q-009-import-summary-business-objects.md))
- The `active` flag round-trips for customers and vendors. ([F-011](docs/issues/F-011-customer-active-delete.md))
- KVP custom-metadata round-trip is extended to every business-object type (was Transaction and Split only). ([F-010](docs/issues/F-010-kvp-metadata-all-object-types.md))
- Business objects imported into an existing file are now persisted correctly (a save-path regression that bypassed the repository layer).

### Error reporting

Import errors include the source directive's line number, the directive type, and a snippet of the offending block. Inconsistent CLI exception types were normalized to a single hierarchy. ([Q-005](docs/issues/Q-005-import-errors-no-context.md), [Q-001](docs/issues/Q-001-inconsistent-cli-exception-types.md))

### Platform support

- Ubuntu 26.04 LTS (GnuCash 5.14) added to the test matrix.
- Stale Windows scripts removed (Linux/macOS via Docker remains the supported development path).

### Security

- The `run` shim, which previously executed arbitrary scripts, is removed. ([S-001](docs/issues/S-001-run-command-executes-arbitrary-scripts.md))
- The broad `except Exception` in the gzip fallback path is narrowed to the specific exceptions GnuCash raises so real errors are no longer masked. ([S-002](docs/issues/S-002-broad-exception-in-gzip-fallback.md))

### Tests

Coverage expanded across services and use cases:

- Beancount round-trip data-fidelity tests.
- `update_transaction` covers duplicate-account splits (the "meal + tip" bug) and is no longer dropped by deduplication.
- Cross-currency split exports emit `@ price` annotations; multi-currency beancount export and close-books paths are now tested.
- Plaintext parser edge cases, KVP colon validation, FX-rates YAML error paths, invoice renderer, and `print-invoice` have dedicated test files.
- Disk-persistence tests for account-balance pricedb and close-books.
- Five-state scenario tests for bills (unposted, posted/unpaid, single full payment, two partials, two payments totalling full amount) plus contradiction-error tests.

### Documentation

- [docs/bank-import-workflow.md](docs/bank-import-workflow.md) — end-to-end walk-through of the statement reconciliation pipeline.
- [docs/invoice-payment-reconciliation.md](docs/invoice-payment-reconciliation.md) — invoice (Accounts Receivable) payment lifecycle, incremental edits, orphan recovery, prepayment consumption.
- [docs/bill-payment-reconciliation.md](docs/bill-payment-reconciliation.md) — vendor-bill (Accounts Payable) payments: partial payments, vendor credits, detecting paid/partial/overpaid state, and `unapply-payment` corrections.
- [docs/payment-manual-edit-behavior.md](docs/payment-manual-edit-behavior.md) — reference for what the importer does to a payment block under each kind of diff (entry change vs. payment-only change).
- [docs/research/2026-05-14-invoice-post-pay-unpost-cycle.md](docs/research/2026-05-14-invoice-post-pay-unpost-cycle.md) and [docs/post-mortems/2026-05-08-bill-postto-account-segfault.md](docs/post-mortems/2026-05-08-bill-postto-account-segfault.md) — research and post-mortem notes from this cycle.

---

## v0.3.2 - export-accounts command (2026-04-08)

### What's new

#### Export account structure without loading transactions

A new `export-accounts` command exports all accounts and commodities directly
from the book without scanning the transaction log. This is significantly
faster on large files when only the chart of accounts is needed.

```bash
gnucash-plaintext export-accounts mybook.gnucash accounts.txt
```

Use `--as-of` to stamp a specific date on every `open`/`commodity`
declaration (defaults to the file modification date):

```bash
gnucash-plaintext export-accounts mybook.gnucash accounts.txt --as-of 2024-01-01
```

---

## v0.3.1 - Bill payment bug fixes and test coverage (2026-04-02)

### Bug fixes

#### Bills now round-trip payments correctly

Three bugs in the bill import/export pipeline prevented vendor bill payments
from round-tripping:

1. **Importer used invoice-side Entry API for bills** — `import_bill` was
   calling `SetInvAccount`, `SetInvPrice`, `SetInvTaxable` instead of the
   bill-side equivalents (`SetBillAccount`, `SetBillPrice`, `SetBillTaxable`).
   This caused the AP posting split to have amount $0 and payments to land in
   the wrong GnuCash lot.

2. **Payment amount sign was wrong** — `bill.ApplyPayment(amount=+N)` created
   AP split = −N (wrong direction), so the payment split was placed in a new
   lot instead of the bill's posted lot and was invisible to the exporter.
   Fixed by passing a negated amount so GnuCash creates AP = +N (debit,
   reduces liability) and bank = −N (credit, money sent out).

3. **Exporter used invoice-side entry reader for bills** — `_export_bills` was
   calling `_format_inv_entry`, which reads invoice-side fields
   (`GetInvAccount`, `gncEntryGetInvPrice`). Added `_format_bill_entry` that
   uses the correct bill-side ctypes functions.

#### GnuCash behaviour: bill `taxable` field is always exported as `true`

GnuCash 5.x does not write `entry:b-taxable = false` to the XML file — the
field is omitted when false and defaulted to `true` on reload. Consequently,
exported bills always show `taxable: true` regardless of what was imported.
This is a GnuCash engine constraint, not a bug in this tool.

### Test coverage

Added dedicated bill state scenario tests in
`tests/integration/test_business_objects.py` covering all five states:
unposted, posted/unpaid, single full payment, two partial payments, and two
payments totalling full amount. Also added three contradiction-error tests for
bills (mirrors the existing invoice contradiction tests).

---

## v0.3.0 - Business Objects (2026-03-14)

### What's new

#### Import and export customers, vendors, tax tables, invoices, and bills

You can now round-trip GnuCash business objects through plaintext files:

```bash
gnucash-plaintext import --new mybook.gnucash ledger.txt --include-business-objects
gnucash-plaintext export mybook.gnucash ledger.txt --include-business-objects
```

Supported objects: `customer`, `vendor`, `taxtable`, `invoice` (with entries
and payments), `bill` (with entries and payments — see v0.3.1 for bug fixes).

Business objects use no date prefix in the plaintext format — they are master
data, not ledger events. GnuCash does not store a creation timestamp for
customers, vendors, or tax tables, so no meaningful date prefix exists.
Dates that belong to a record (e.g. `date_opened`) are declared as fields
inside the block.

#### Print invoices to PDF

Any posted invoice can be rendered to a PDF directly from the CLI:

```bash
gnucash-plaintext print-invoice mybook.gnucash --invoice-id INV-2026-001 -o invoice.pdf
```

The output was produced from `services/invoice.xslt`, which you could customise to match your company's branding. **Superseded:** a printed document is now GnuCash's own Printable Invoice, that stylesheet and the `--template` flag are gone, and what a page shows is what GnuCash shows — see "A printed invoice or bill is the page GnuCash prints" above.

### Platform support expanded

Ubuntu 22.04 (GnuCash 4.8) and Ubuntu 24.04 (GnuCash 5.5 — listed as 4.9 here
until the images were re-probed) are now fully supported and tested in CI.

Two bugs that caused segfaults on Ubuntu (but not Debian) were fixed:
- Missing `argtypes` caused ctypes to silently truncate 64-bit pointers to 32-bit
- Ubuntu loads GnuCash extensions with `RTLD_LOCAL`, so `CDLL(None)` could
  resolve symbols from the wrong library instance

On Ubuntu 22/24, `apt install weasyprint` only provides a CLI wrapper —
`import weasyprint` would fail. Fixed by installing weasyprint via pip.

### Bug fix

`create_account` was not idempotent: calling it twice for the same account
silently created duplicate children in GnuCash. Fixed with an existence check.

---

## v0.2.0 - Architecture Migration (2026-03-01)

**Major release** with complete architecture refactoring and new features.

### 🎉 Highlights

- **Unified CLI**: All functionality through single `gnucash-plaintext` command
- **GnuCash-Beancount Format**: Bidirectional conversion with zero data loss
- **Multi-Version Support**: Tested on GnuCash 3.8, 4.4, 4.13, 5.10
- **Comprehensive Testing**: 145 tests with 100% parity validation
- **Docker Development**: Cross-platform development environment

### ✨ New Features

#### 1. Bidirectional Beancount Conversion

Full round-trip conversion between GnuCash and beancount:

```bash
# Export to GnuCash-Beancount
gnucash-plaintext export-beancount mybook.gnucash output.beancount

# Import back to GnuCash
gnucash-plaintext import-beancount restored.gnucash output.beancount

# Full chain: Plaintext → GnuCash → Beancount → GnuCash → Plaintext
# All data preserved with zero loss
```

**Features:**
- Account name aliasing (spaces and special characters preserved via metadata)
- Complete GnuCash metadata preservation (GUIDs, types, placeholders, etc.)
- Strict validation (rejects standard beancount without metadata)
- Commodity symbol sanitization for beancount compatibility

See [docs/gnucash-beancount-format.md](docs/gnucash-beancount-format.md) for details.

#### 2. Ledger Validation

New `validate` command checks GnuCash file integrity:

```bash
# Full validation report
gnucash-plaintext validate mybook.gnucash

# Quick check (errors only)
gnucash-plaintext validate mybook.gnucash --quick

# Show statistics
gnucash-plaintext validate mybook.gnucash --stats
```

**Validates:**
- Account structure and types
- Transaction balance
- Commodity consistency
- Split reconciliation
- Date validity
- GUID uniqueness

#### 3. Conflict Resolution

Smart duplicate detection with resolution strategies:

```bash
# Skip conflicting transactions (default)
gnucash-plaintext import mybook.gnucash transactions.txt --strategy skip

# Keep existing on conflict
gnucash-plaintext import mybook.gnucash transactions.txt --strategy keep-existing

# Replace with incoming on conflict
gnucash-plaintext import mybook.gnucash transactions.txt --strategy keep-incoming
```

**Conflict detection:**
- By GUID (if present in plaintext)
- By transaction signature (date + accounts)
- Prevents accidental duplicates

#### 4. Dry Run Mode

Preview changes before applying:

```bash
gnucash-plaintext import mybook.gnucash transactions.txt --dry-run
gnucash-plaintext import-beancount output.gnucash input.beancount --dry-run
```

#### 5. Date Range and Account Filtering

Export specific subsets of data:

```bash
# Export date range
gnucash-plaintext export mybook.gnucash output.txt \
  --date-from 2024-01-01 --date-to 2024-12-31

# Export specific account
gnucash-plaintext export mybook.gnucash output.txt \
  --account "Assets:Bank"

# Also works with beancount export
gnucash-plaintext export-beancount mybook.gnucash output.beancount \
  --date-from 2024-01-01 --date-to 2024-12-31
```

**Note:** When filtering transactions, ALL commodities and ALL accounts are still exported (required for valid beancount).

### 🏗️ Architecture Changes

#### New Structure

```
gnucash-plaintext/
├── cli/                    # CLI commands
│   ├── main.py
│   ├── export_cmd.py
│   ├── import_cmd.py
│   ├── export_beancount_cmd.py
│   ├── import_beancount_cmd.py
│   ├── qfx_to_plaintext_cmd.py
│   └── validate_cmd.py
├── services/               # Business logic
│   ├── account_categorizer.py
│   ├── beancount_converter.py
│   ├── beancount_parser.py
│   ├── ledger_validator.py
│   ├── plaintext_formatter.py
│   ├── qfx_converter.py
│   └── transaction_matcher.py
├── use_cases/              # Orchestration
│   ├── export_beancount.py
│   ├── export_transactions.py
│   ├── import_beancount.py
│   ├── import_transactions.py
│   ├── qfx_to_plaintext.py
│   └── validate_ledger.py
├── infrastructure/         # I/O adapters
│   ├── gnucash/
│   │   ├── gnucash_importer.py
│   │   └── utils.py
│   ├── plaintext/
│   │   └── plaintext_parser.py
│   └── qfx/
│       └── qfx_parser.py
└── repositories/
    └── gnucash_repository.py
```

#### Benefits

- **Testability**: 145 tests with clear separation of concerns
- **Maintainability**: Single responsibility per module
- **Extensibility**: Easy to add new formats
- **Reusability**: Services can be composed in different ways

### 🔧 Improvements

#### Multi-Version GnuCash Support

Tested and working on:
- **Debian 13** (Python 3.12, GnuCash 5.10)
- **Debian 12** (Python 3.11, GnuCash 4.13)
- **Debian 11** (Python 3.9, GnuCash 4.4)
- **Ubuntu 20.04** (Python 3.8, GnuCash 3.8)

**Compatibility features:**
- Abstract version differences with try/except patterns
- Compatibility shims for SessionOpenMode, GetDocLink/GetAssociation
- No version checks - code adapts dynamically

#### Docker Development Environment

Cross-platform development with:
- VS Code Server at https://localhost:8765
- Live code sync
- Docker-in-Docker support (Linux/macOS/WSL2)
- Pre-installed GnuCash Python bindings
- Automated test scripts

```bash
# Start development environment
./scripts/dev-start.sh

# Run tests
./scripts/test.sh

# Test all versions
./scripts/test-all-versions.sh
```

#### Enhanced Test Coverage

- **139 tests** for core functionality
- **6 new tests** for beancount round-trip
- **100% parity** with legacy code
- **Multi-version testing** on 4 distributions
- **Integration tests** for full conversion chains

### 🚨 Breaking Changes

#### 1. Command Names

| Old | New |
|-----|-----|
| `python3 ledger.py <file> <output> --export` | `gnucash-plaintext export <file> <output>` |
| `python3 ledger.py <file> <input>` | `gnucash-plaintext import <file> <input>` |
| `python3 convert_qfx.py <qfx> <output>` | `gnucash-plaintext qfx-to-plaintext <qfx> <output>` |

#### 2. Python Version

- **Minimum**: Python 3.8+ (was 3.6+)
- **Reason**: Compatibility with Ubuntu 20.04 LTS

#### 3. Installation

Development now requires Docker:
```bash
./scripts/dev-start.sh
```

Production installation via pip (planned for future release).

### 📝 Migration Guide

See [MIGRATION.md](MIGRATION.md) for detailed upgrade instructions.

**Quick migration:**

Old:
```bash
python3 ledger.py mybook.gnucash transactions.txt
python3 convert_qfx.py input.qfx output.txt
```

New:
```bash
gnucash-plaintext import mybook.gnucash transactions.txt
gnucash-plaintext qfx-to-plaintext input.qfx output.txt
```

### 🐛 Bug Fixes

- Fixed commodity export to use ticker instead of mnemonic
- Fixed space handling in commodity symbols
- Fixed account name aliasing for spaces and special characters
- Fixed import to reuse GnuCashImporter infrastructure
- Fixed transaction signature matching for conflict detection

### 📚 Documentation

- **New**: [MIGRATION.md](MIGRATION.md) - Upgrade guide
- **New**: [docs/gnucash-beancount-format.md](docs/gnucash-beancount-format.md) - Format specification
- **Updated**: [README.md](README.md) - Comprehensive usage guide
- **Updated**: [scripts/README.md](scripts/README.md) - Development workflow

### 🔮 Future Plans

#### Phase 8: Close Books (Planned)

Year-end closing with multi-currency support:

```bash
# Close books per currency
gnucash-plaintext close-books mybook.gnucash --closing-date 2024-12-31

# Optional: Consolidate to book currency
gnucash-plaintext consolidate-equity mybook.gnucash --closing-date 2024-12-31
```

See [migration_plan.md](migration_plan.md) for details.

### 👏 Acknowledgments

- **GnuCash Team**: For the excellent Python bindings
- **Beancount Community**: For inspiration on plaintext accounting
- **Contributors**: Testing, feedback, and bug reports

### 📊 Statistics

- **Development Time**: 11.5 days (estimated 22-30 days, 48-62% ahead of schedule)
- **Tests**: 145 tests (was 17 legacy tests)
- **Code Removed**: 4,418 lines of legacy code
- **Code Added**: New clean architecture
- **Files Changed**: 35 files deleted, new structure added
- **Supported Versions**: 4 GnuCash versions (3.8, 4.4, 4.13, 5.10)

---

## Previous Releases

### v0.1.x - Initial Implementation

- Basic plaintext import/export
- QFX conversion
- Script-based interface
- Single GnuCash version support

**Note:** v0.1.x is no longer maintained. Please upgrade to v0.2.0.

---

**Full Changelog**: https://github.com/yourusername/gnucash-plaintext/compare/v0.1.0...v0.2.0
