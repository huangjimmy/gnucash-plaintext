---
id: Q-036
title: A printed invoice was this project's own page, and stated the book's valuation of a foreign-currency document as the amount owed
category: bug
severity: high
status: closed
---

## Problem

Two problems, and the first is a wrong number on a document sent to a customer.

**A foreign-currency document was priced in the wrong currency.** A USD 100.00 invoice whose income account is CAD printed `USD 140.00` — the CAD the book valued the receivable at, under a USD label. The renderer summed the posting transaction's splits, by account type, using each split's **amount**; a split's amount is the figure in its own account's commodity, so the income split held CAD. The line rows above it read `$100.00`, because those are computed from the entries.

It was invisible to 2,300 tests because every render test built from `business_objects.txt`, which is CAD end to end — 14 `currency: CAD` lines and 10 CAD accounts. In a single-currency book a split's amount and its value are the same number, so reading the wrong one of the two cannot be seen.

**The page was ours, and GnuCash's is the one people expect.** The layout was a stylesheet written here: Description, Qty, Unit Price, Amount and Tax Applied, with tax broken out as named GST and PST rows. What GnuCash's own Print Invoice button draws is its **Printable Invoice** report: `Invoice #<id>` at the top left, the document's owner on one side and the seller on the other, then Date, Description, Action, Quantity, Unit Price, Discount, Taxable and Total, and Net Price, Tax, Total Price and Amount Due beneath. Ours matched none of it, and every difference was a thing to reimplement and keep in step.

## What it does now

The page is GnuCash's, drawn by GnuCash. `services/gnucash_report.py` hands GnuCash the book and the document's guid and asks a report to render it. `--report` and `--report-file` choose which; with neither, the **book** is asked — `qof_book_get_default_invoice_report_guid`, which is File → Properties → Business and what GnuCash's own Print Invoice button reads — and a book naming none is drawn by the Printable Invoice, report guid `5123a759ceb9483abf2182d01c140e8d`. Nothing here computes a layout, a column rule or a total.

**A guid the book names and this build has no report for is drawn with the Printable Invoice, warned about by guid, rather than refused.** The book usually names a configuration the reader saved, and a saved configuration is a file in the GnuCash that saved it — present on their laptop, absent on a build server and on a colleague's. Refusing there stops the book printing anywhere but on one machine, over a setting made in a dialog rather than on this command line, with a refusal naming a guid nobody typed. A name or guid the caller *did* type is still refused: they can see what they wrote.

The second consequence is written to stderr as well, nobody having typed the book option either: where the book names a report outside the five `print-invoice` advertises, the page carries the options saved in the configuration and the three switches below stay unset — so a page can state one combined `Tax` figure where the Printable Invoice states the breakdown for the same book.

The accessor arrived with GnuCash 5 — absent from `libgnc-engine.so` and from `qofbook.h` on 3.8 and the whole 4.x line, measured — so a book on those builds names no report here, which is what their own printing does. Nothing is written to stderr about it either: the two sentences below are about a setting that was read, and on those builds there is none to read. A book carrying the option therefore prints with its chosen report on a GnuCash 5 machine and with the Printable Invoice on an older one, in silence. It is declared through `getattr` for that reason: naming a symbol a library does not export raises in `load_gnc_engine` itself, which failed *every* command on those builds. And the string it returns is the caller's (`gchar *`, not `const char *`, and measurably a fresh pointer per call), so it is copied out and `g_free`d.

**Guile runs inside this process.** `scm_init_guile()` on the already-loaded libguile puts a Scheme interpreter in the process that has the book open, and because the Python bindings and Guile's are the same C library sharing the same globals, `gnc-get-current-session` answers with the session Python opened — after `gnc_set_current_session`, which the bindings do not call themselves. Nothing is shelled out to and no book is opened twice.

That is what makes every supported build work, GnuCash 3.8 included. Two other routes were tried and abandoned: `gnucash-cli --report` leaves 3.8 out, which has none; a standalone `guile` process leaves every build out, because `qof-session-begin` is exposed to Guile on no version, so a separate interpreter cannot open a book at all.

The two eras differ only in names — `use-modules` against `gnc:module-load`, `(gnucash reports standard invoice)` against `(gnucash report invoice)`, `gnc-set-option` against `gnc:option-set-value` — and the renderer asks the build which it has rather than inferring it from the version, because GnuCash 4.13 loads the modern module names and still wants the old option API.

The page is the same on every build. Measured across 3.8 and 5.10, the whole document differs in `cellspacing="0"` against `"0.0"` and an ellipsis spelled `...` against `…`, and in one figure: **the payment row**. A payment made through a transaction valued in another currency is stated in the transaction's currency on 3.8 — `-C$140.00` under totals that all read `$100.00` — and in the document's on 4.x and 5.x. That row is the report's, so the tests read the totals.

## The options that are set

Beyond the document's guid, three of the report's own switches are set. Each shows a field this format carries and GnuCash ships hidden:

| option | why |
|---|---|
| `Display/Invoice Notes` | the document's `notes:`, which this format carries and a document that dropped it would lose |
| `Display/Company contact` | the book's `contact:`, as GnuCash's "Please direct all enquiries to …" |
| `Display/Use Detailed Tax Summary` | one row per tax account — `GST` and `PST` by name and amount, not one combined `Tax` figure |

All three are set tolerantly: an option a build does not have raises "Attempt to write non-existent option", and a row missing on an older GnuCash must not cost that build its document.

`Display/Extra Notes` is not one of them, and the reason is below.

**The tax breakdown is not a formatting preference.** This change splices in the GST and PST registration numbers on the grounds that a Canadian invoice is required to state them; the same rules require it to state the GST/HST *amount*, and GST added to PST does not state it. A filer reclaims the GST and not the PST, so a document giving only their sum cannot be worked from. The format has carried the per-account breakdown since Q-019, the plaintext render still writes it, and the page would have quietly stopped agreeing with both.

**`Extra Notes` holds text rather than a switch, and no text is written by `print-invoice`.** The three options above turn *on* the display of a field the ledger already carries; `Extra Notes` holds a sentence somebody chose, and choosing the sentence belongs to the reader — through a configuration saved in GnuCash's report options dialog, or through `set-invoice-style` on the book. Where neither names a sentence, GnuCash's own default prints: "Thank you for your patronage!".

## The two additions

GnuCash's page has no row for two things, so two are added to what it drew. Both print as they stand; nothing is inferred from them.

* The **seller's**, under the company block: the GST and each PST registration number — GnuCash has no field for either, and a Canadian invoice is required to state the GST/HST number — then the book's `extra_text1:`, `extra_text2:` … lines.
* The **owner's**, under the client block: that owner's own `extra_text1:`, `extra_text2:` … lines.

One key is one printed line, numbered like the `addr1:`..`addr4:` keys already in this format, because a value here is one line: there is no escape for a newline and a quoted value does not span lines.

They go in as one more row of the block they belong beside. The Printable Invoice builds its page in Scheme and, unlike its Tax Invoice sibling, has no template file to copy and edit — so free text of ours is added to what it drew rather than woven into how it draws. The two blocks are `<div class="company-table">` and `<div class="client-table">`, present and identically shaped on 3.8 and 5.10.

**Whether a missing block refuses the document depends on whose layout it is.** On the default page it refuses: the seller's block carries the registration numbers a Canadian invoice is required to state, so the choice is between a message naming what is missing and a document that looks right, goes to a customer, and is quietly non-compliant. Every supported build has both blocks, so that is reachable only on an eleventh GnuCash that renamed them.

On a page named with `--report` or `--report-file` it prints unchanged, because the absence is then the report's own design. Measured on 5.10 and 3.8, of the reports `--report` offers:

| report | the two blocks | so a document printed with it |
|---|---|---|
| Printable Invoice (the default) | both | states your GST and PST numbers; refuses to print if it cannot |
| Fancy Invoice | both | the same |
| Easy Invoice | both | the same |
| Tax Invoice | neither | **states neither registration number**, and prints, saying so on stderr |
| Australian Tax Invoice | neither | the same — it arrives with Tax Invoice's module and is reachable by name |

So the numbers still reach Fancy and Easy, where a blanket "someone else's page, don't touch" would have dropped a Canadian book's GST number for choosing a different one of GnuCash's own; and a report of your own is never refused for lacking a `div` nobody asked its author for.

**What the two tax invoices cost is worth stating plainly**, because they are the shipped reports that drop something the default refuses to print without. They also state tax their own way — a Tax Rate and a Tax Amount column per line rather than a named GST and PST total, since neither has a `Use Detailed Tax Summary` option to turn on. A Canadian invoice has to state the GST/HST number and amount; those pages state neither. So the run says on stderr that it had nowhere to put those lines, naming the first of them — once per report and block, not once per document — and README says so where the flag is documented. Refusing was the alternative and is wrong: the report is doing what it was written to do, and a reader who asked for it by name asked for its layout.

Only the `extra_text` keys are read. The rest of what those slots hold is the book owner's own — a `fiscal_year_end:`, a customer's `credit_rating:` — and the document goes to the other party.

## What the report cannot see

A key that has since become a field of its own still sits in the slot of every book written before it was one — a bill's notes, a vendor's address. Every reader in this tool knows that and asks `held_value`; GnuCash's report cannot, because it reads its own engine's fields. So a bill whose ledger states notes printed the line blank.

`carry_slot_values_onto_the_fields` writes what the book holds onto the in-memory objects before rendering. Printing opens the book read-only and never saves, so this is the same migration `held_value` performs for every other reader, done where the report can see it; a field that already says something is left alone.

## PDF

**The PDF is laid out by WebKit, which is what GnuCash prints with.** Its Print Invoice button hands the report's HTML to WebKit, so anything else laying that HTML out is a second answer to a question already answered — and the two answers differ on the page. Measured on one document, same HTML both ways: WebKit paints 97 rectangles and WeasyPrint none, the borders coming from the HTML-4 presentational attributes GnuCash's report writes (`border`, `cellpadding`, `bgcolor`) which WeasyPrint does not implement. The reader's printed invoice had no lines round anything.

**Two things are deliberately not named here, both being the machine's**: the paper size, which GTK takes from the locale exactly as GnuCash does — naming one printed every reader's document on the author's paper — and, in the other direction, the *message* catalogue, which is forced to `C` for the child alone. GTK's file printer is asked for by name and that name is translated (`Imprimer dans un fichier` under `fr_FR`), and WebKit answers `Printer not found (500)` for a name it does not hold. Only `LC_MESSAGES` is neutralised, because `LC_PAPER` is what decides the sheet — and `LC_ALL` takes care, glibc resolving every category through it first: a reader whose only locale variable is `LC_ALL=en_US.UTF-8` loses US Letter to the `C` fallback if it is simply removed, measured as `na_letter 612 792` becoming `iso_a4 595 842`. So what `LC_ALL` was deciding is written into each category before it goes. No test reaches any of this: the images carry `C`, `C.utf8` and `POSIX` and nothing else.

`infrastructure/pdf/webkit_page.py` is a child process — `WebKit2.PrintOperation` with GTK's "Print to File" printer. A child, because a GTK main loop inside the process holding an open book and an initialised Guile is two event loops over the same ctypes-shared globals; and because a machine printing from a script has no display to give it. One is arranged by `a_display`: the reader's own `DISPLAY` where there is one, else an `Xvfb` started for the run and shared across every document in it, else `xvfb-run` on a machine carrying the wrapper and no server.

**The page runs no JavaScript**, which is a deliberate difference from GnuCash's own viewer — a viewer being a browser as well as a printer. The report interpolates book text into the page, so a field it does not escape is script executing during a print; nothing about laying out an invoice needs scripting, and the page draws the same without it. Remote images and stylesheets are still fetched, as they were under WeasyPrint: closing that is a network policy rather than a flag.

PostScript and SVG are what GnuCash's dialog offers beside PDF, and neither is offered here: asking GTK for either ends with the operation reporting *finished* and no file written, measured on 5.10.

The PDF's text is text: `tests/integration/test_a_printed_pdf_can_be_selected_and_copied.py` reads the file back with a PDF reader and looks for what the page says, because select-and-copy is what a customer does with an invoice and the HTML proves nothing about it. A combined print is one file with one document per page, and each page is read back on its own.

## The second renderer is gone

`--template`, `services/invoice.xslt`, `services/bill.xslt` and the `invoice_to_xml` / `bill_to_xml` builders behind them are deleted. They were a whole second implementation of the same document — its own columns, its own tax rows, its own totals — and keeping it meant keeping it correct: the FX defect above was in *both*, and the fix to the XSLT half could have been reverted with the suite still green, because every book that reached it was single-currency. One page, drawn by GnuCash, is the point of this change; a `--template` that quietly gave you the old wrong one is not a feature.

What replaces it is a wider seam rather than a smaller one. The company block comes from File → Properties → Business and the two `extra_text` blocks carry what GnuCash has no field for; beyond those, `--report` picks any of the five reports GnuCash ships and `--report-file` loads a `.scm` of your own, so the whole page is yours to write — in the language GnuCash's own pages are written in, drawn by the same machinery, and working from GnuCash's GUI too if you install it there. A stylesheet over an XML shape this project invented was less than that, not more. See README, "Changing the page means changing the report that draws it".
