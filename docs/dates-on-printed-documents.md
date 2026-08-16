# Dates on printed invoices and bills

How to get the dates you want on a document `print-invoice` or `print-bill` produces, and why the obvious ways do not all work.

Everything quoted below — every ledger, every command, every date, the warning verbatim — was produced by running it against a real GnuCash book. Nothing here is illustrative. The behaviour is the same on GnuCash 5.10, 4.13 and 3.8.

---

## The short answer

Say it once, in the ledger's `company` block:

```
company
	name: "Maple Leaf Widgets Inc."
	date_format: "%Y-%m-%d"
```

Every date on the printed page is then ISO, on any machine, and it stays that way through an export and re-import.

**"The printed page" means the rendered document** — `--format html` and `--format pdf`, the thing a customer receives. `--format plaintext` writes `YYYY-MM-DD` whatever the book says, because that output is this ledger format rather than a document: it has to be re-importable, and a date this tool cannot read back is not a ledger. Every example below prints HTML for that reason. So a book set to `%d.%m.%Y` gives you `09.03.2026` on the invoice and `2026-03-09` in the plaintext of the same invoice, and both are right.

Four formats work like that. This table is the printed page for each, for the same invoice — dated 9 March 2026, printed on 15 August 2026 — with every column taken off a real document:

| `date_format` | document date | entry row | "printed on" | warns? |
|---|---|---|---|---|
| `%Y-%m-%d` | `2026-03-09` | `2026-03-09` | `2026-08-15` | no |
| `%m/%d/%Y` | `03/09/2026` | `03/09/2026` | `08/15/2026` | no |
| `%d/%m/%Y` | `09/03/2026` | `09/03/2026` | `15/08/2026` | no |
| `%d.%m.%Y` | `09.03.2026` | `09.03.2026` | `15.08.2026` | no |
| `%d %B %Y` | `09 March 2026` | `03/09/26` | `08/15/26` | **yes** |

The first four are consistent all the way across. The last is the case worth understanding, and it is the next section.

---

## A complete worked example

Save this as `ledger.txt`. It is a whole ledger — accounts, company, customer, one posted invoice — so you can run it as it stands:

```
2026-01-01 open Assets
	type: Asset
	commodity.namespace: "CURRENCY"
	commodity.mnemonic: "CAD"
2026-01-01 open Assets:Accounts Receivable
	type: Accounts Receivable
	commodity.namespace: "CURRENCY"
	commodity.mnemonic: "CAD"
2026-01-01 open Income
	type: Income
	commodity.namespace: "CURRENCY"
	commodity.mnemonic: "CAD"
2026-01-01 open Income:Sales
	type: Income
	commodity.namespace: "CURRENCY"
	commodity.mnemonic: "CAD"

company
	name: "Maple Leaf Widgets Inc."
	date_format: "%Y-%m-%d"

customer "C-001"
	name: "Northern Supplies Ltd."
	currency: CAD

invoice "INV-2026-001"
	customer_id: "C-001"
	currency: CAD
	date_opened: 2026-03-09
	entry:
		date: 2026-03-09
		description: "Consulting"
		action: "Hours"
		account: "Income:Sales"
		quantity: 2
		price: 100
		taxable: false
		tax_included: false
	posted:
		date: 2026-03-09
		due: 2026-04-09
		ar_account: "Assets:Accounts Receivable"
		memo: "Invoice INV-2026-001"
		accumulate: true
```

Build the book and print the invoice:

```bash
gnucash-plaintext import --new book.gnucash ledger.txt --include-business-objects
gnucash-plaintext print-invoice book.gnucash INV-2026-001 -o invoice.html --format html
```

The dates on that page:

```
document date : 2026-03-09
due date      : 2026-04-09
entry row     : 2026-03-09
printed on    : 2026-08-15
```

All four ISO, and nothing on stderr. That is the whole feature working.

### It comes back out again

```bash
gnucash-plaintext export book.gnucash --output exported.txt --include-business-objects
```

```
company
	name: "Maple Leaf Widgets Inc."
	date_format: "%Y-%m-%d"
```

So a book rebuilt from `exported.txt` prints the same dates. The format is part of the ledger, not part of the machine.

### The same book, European style

Nothing about the above is particular to ISO. Change the one line:

```
company
	name: "Maple Leaf Widgets Inc."
	date_format: "%d.%m.%Y"
```

```bash
gnucash-plaintext import book.gnucash change.txt --include-business-objects
gnucash-plaintext print-invoice book.gnucash INV-2026-001 -o invoice.html --format html
```

and the same page comes out:

```
document date : 09.03.2026
due date      : 09.04.2026
entry row     : 09.03.2026
printed on    : 15.08.2026
```

`%m/%d/%Y` and `%d/%m/%Y` behave the same way — see the table at the top for all four.

### Changing it, and clearing it

Both follow the rule every key on this block follows — a key you name is set, a key you name empty is cleared, a key you leave out is left alone:

```
company
	date_format: "%d.%m.%Y"     # change it
```

```
company
	date_format: ""             # clear it; the machine decides again
```

```bash
gnucash-plaintext import book.gnucash change.txt --include-business-objects
```

Note the `--include-business-objects` flag: a ledger holding only a `company` block does nothing without it, and says `✓ Nothing to import`.

---

## When your format is not one of the four

`%d %B %Y` is a perfectly reasonable thing to want. Set it and the run prints the document, and says this on stderr:

```
⚠ the book's date_format is '%d %B %Y', which GnuCash has no date style for — the document's
  date and due date will read that way and every other date on the page will follow this
  machine's locale. For one format throughout, use one of: %Y-%m-%d, %d.%m.%Y, %d/%m/%Y, %m/%d/%Y
```

The page it produced:

```
document date : 09 March 2026     ← your format
due date      : 09 April 2026     ← your format
entry row     : 03/09/26          ← this machine's locale
```

That is not a bug and the document is fine to send; it is simply a page with two date formats on it, which you should know about rather than discover. If you need `09 March 2026` on the line items too, [write your own report](#if-you-need-a-format-the-four-do-not-cover).

---

## Choosing what to do

| what you want | do this |
|---|---|
| one format everywhere, and it is one of the four | `date_format` in the `company` block. Nothing else. |
| one format everywhere, and it is **not** one of the four | write your own report — `--report-file` |
| the document's dates in an unusual format, and the line items may differ | `date_format`, and take the warning as information |
| whatever the machine is set to | say nothing. Without `date_format` the page is uniform anyway — it all comes from the locale |
| to change it for one run only | `LC_TIME=en_GB.UTF-8 gnucash-plaintext print-invoice …`, with no `date_format` in the book |

---

## Why there are two settings at all

A document has dates in two groups, and GnuCash writes them from different places.

| on the page | written from |
|---|---|
| the document's **posted date** and **due date**, at the top | a **book option** — GnuCash's *Fancy Date Format*, File → Properties → Business |
| each **entry's date**, each **payment's date**, and **"printed on"** | a **process-wide setting**, the one `qof-print-date` reads |

`date_format` sets both, which is what this tool adds: writing the book option was impossible from a ledger, and the process-wide setting was never set at all by a command-line run — it is GnuCash's *GUI* that fills that one in, at startup.

The consequence is backwards from what people expect:

* a book with **no** `date_format` prints a **uniform** page: both groups fall back to the same place, the machine's locale;
* setting **only** the book option — which is all the GnuCash GUI does — gives a page with **two formats on it**, `09 March 2026` at the top and `03/09/26` in the line items.

So stating the format is what makes a page consistent. Avoiding it is not.

## Why only four formats

The process-wide setting takes **a style, not a format string**. From GnuCash's `gnc-date.h`, `qof_date_format_set` "checks to make sure it's a legal value", and the legal values are:

```
US   mm/dd/yyyy       CE   dd.mm.yyyy
UK   dd/mm/yyyy       ISO  yyyy-mm-dd
```

There is a `CUSTOM` value, but it belongs to the check-printing code and no public function sets a custom string through it. So a format string can reach the document's own dates — the book option really is a format string — and can never reach the line items.

---

## What does *not* work, and why

**GnuCash's own preference — Edit → Preferences → Date/Time.** No effect on anything this tool prints. That preference is read by the GnuCash GUI when it starts; `print-invoice` is not the GUI and never reads it. Measured: setting it changes nothing on the page. It remains a preference for how the GnuCash application shows dates to *you*.

**Setting it in the GUI's File → Properties → Business.** This is the same book option `date_format` writes, and a format set there does reach the document's own dates — that half is measured, since it is the option this tool reads and writes. What is *not* measured, and so is not claimed here, is the other direction: what GnuCash's dialog shows for an option this tool wrote, and what it writes back if you press OK. These containers have no GUI to measure it in.

What the GUI setting cannot do either way is travel: an export and re-import will not carry it unless the ledger says it, and it only ever covers the document's own dates, never the line items. Prefer the ledger, and if you do set it in GnuCash, put it in the ledger too so the next import restores it.

**`LC_TIME` together with a `date_format`.** They govern different dates, so neither overrides the other. With `date_format: "%Y-%m-%d"` under a UK locale you get ISO at the top and `09/03/2026` in the rows. `LC_TIME` is the whole answer only when the book states nothing.

---

## If you need a format the four do not cover

Write the report. A report of your own — `--report-file`, see README's "Changing the page means changing the report that draws it" — formats every date it prints, from whatever source it likes, so one page has one format and nothing is left to the machine that ran the command. That is the only route to `09 March 2026` on the line items, and it travels with your ledger.

---

## The tests, if you want to see it proved

`tests/integration/test_a_book_says_how_its_dates_are_written.py` is the executable version of this document. Each class answers one of the questions above:

| test | what it shows |
|---|---|
| `TestThePrintedPage::test_one_format_on_the_whole_page` | ISO everywhere, and nothing left reading the machine's way |
| `TestThePrintedPage::test_a_format_gnucash_has_no_style_for_says_so` | the warning above, and that the document still prints |
| `TestThePrintedPage::test_it_reaches_the_documents_own_dates_and_not_the_entry_dates` | which dates each setting governs |
| `TestThePrintedPage::test_and_not_the_way_it_would_have_been_without_one` | that a book naming no format is dated some other way |
| `TestTheBookOption::test_gnucash_reads_it_back` | GnuCash's own `gnc:options-fancy-date` returns what the ledger set |
| `TestItSurvivesTheRoundTrip` | the export states it, and a book rebuilt from that export prints the same dates |
| `TestChangingItAndClearingIt` | changing it, clearing it with `""`, and that a block not naming it leaves it alone |
| `TestABookThatUsedItAsACustomKey` | books written before `date_format` was a field of its own |

Run them with `./scripts/test.sh latest tests/integration/test_a_book_says_how_its_dates_are_written.py`.

---

## See also

* [Q-037](issues/Q-037-a-printed-document-is-dated-by-the-machine-that-printed-it.md) — the measurements behind all of the above, including the negative results.
* README, the `company` directive — the key's reference entry.
* `CLAUDE.md` finding 15 — the platform behaviour, for anyone adding a feature that prints a date.
