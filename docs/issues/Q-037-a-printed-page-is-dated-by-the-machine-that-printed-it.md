# Q-037 — A printed page is dated by the machine that printed it

**Reported by users**, against `--report-file`: a report of their own fell back to the book's date format and found none, because nothing in this tool could set one.

## What was wrong

Two separate settings decide the dates on a printed invoice or bill, and a ledger could reach neither.

**The invoice's own dates** — its posted date and its due date — are written by the report from a *book option*: `gnc:fancy-date-info`, which resolves to `(gnc:book-get-option-value book "Business" '("Fancy Date Format" "custom"))`. `invoice.scm` reads it at line 237 (`gnc:options-fancy-date`), so it is not a field this project invented for its own page — it is the field GnuCash's own reports already read. No command here could write it, so the only way to set it was File → Properties → Business in the GnuCash GUI, on every machine that prints, and an export and re-import lost it.

**Every other date on the page** — each entry's, each payment's, and "printed on" — is written by `qof-print-date`, which reads a **process-wide** setting rather than anything in the book. GnuCash's GUI fills that in at startup from its own preference. A process that only loaded the library fills in nothing, so it sits at its compiled default, `QOF_DATE_FORMAT_LOCALE`, and those dates follow the locale of whoever ran the command.

So a book had no say in either half, and the two halves could disagree with each other.

## What was measured

On GnuCash 5.10, 4.13 and 3.8 unless noted.

| asked | answer |
|---|---|
| `qof_date_format_get()` in this tool's process | `4` — `QOF_DATE_FORMAT_LOCALE`, always |
| the same, after setting GnuCash's GSettings preference | `4`. **The preference is never read here**; setting it changed nothing on the page (5.10, through GSettings' keyfile backend) |
| `qof_date_format_set(3)` then print | entry rows become `2026-03-09`; the invoice's own dates unchanged |
| `qof_date_format_set(1)` then print | entry rows become `09/03/2026`; the invoice's own dates unchanged |
| book option set, QOF left alone | invoice `09 March 2026`, entry rows `03/09/26` — one page, two formats |
| book option absent, QOF left alone | every date `03/09/26` — uniform, because both halves fall back to the same place |

`QofDateFormat` from `gnc-date.h`: `US=0, UK=1, CE=2, ISO=3, LOCALE=4, UTC=5, CUSTOM=6, UNSET=7`. The header's own comment on `qof_date_format_set` is that it "sets date format to one of US, UK, CE, OR ISO. Checks to make sure it's a legal value" — so `CUSTOM`, which is the check printer's, cannot be set through it and **there is no public setter for a custom format string**.

## What it does now

`company` takes `date_format`, an `strftime` format, and the print path sets *both* halves from it: the book option, so the invoice's own dates carry it; and QOF's process-wide setting, so every other date on the page follows too. The option is the one GnuCash's own reports read — `gnc:options-fancy-date` resolves to that exact sub-key — which is measured. What GnuCash's *dialog* shows for it, and writes back, is not: there is no GUI in these containers, so no claim is made about it.

Four formats are matchable, because QOF takes a style and not a string:

| `date_format` | QOF style | whole page |
|---|---|---|
| `%Y-%m-%d` | ISO | `2026-03-09` |
| `%m/%d/%Y` | US | `03/09/2026` |
| `%d/%m/%Y` | UK | `09/03/2026` |
| `%d.%m.%Y` | CE | `09.03.2026` |

**Any other format is still accepted and the run warns.** `%d %B %Y` is a reasonable thing to want on a page and QOF has no style for it, so the entry rows keep following the machine's locale. Printing anyway is right — the report is doing what it was asked — but silently would not be: the reader gets a page with two date formats and nothing saying why. The warning names the four that can be matched, once per run.

The QOF setting is restored after each render. It is a global of the whole process, and a command printing one book must not leave the next one — or the next test in the file — reading its format.

## Why the key is not two keys

An earlier draft had a second key naming the QOF style, so the two halves could be set independently. There is no reason to want them to differ, and it invents vocabulary GnuCash does not use. One key, and the style is derived from the format.

## What a ledger still cannot say

The GnuCash *application* preference (Edit → Preferences → Date/Time, GSettings `org.gnucash.GnuCash date-format`). It is not in the `.gnucash` file, so no ledger can carry it and `export` cannot emit it — and it does not affect this tool at all, measured above. It remains what it always was: a per-machine preference for the GnuCash GUI.
