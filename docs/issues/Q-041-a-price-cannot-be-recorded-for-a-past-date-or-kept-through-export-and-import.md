# Q-041 — A price cannot be recorded for a past date, or kept through export and import

**Scope.** This issue covers prices, and also a memory fix found while testing them: the test suite kept every book it opened, until `GnuCashRepository.close` destroyed its session. The fix is recorded under "The test suite kept every book it opened", at the end; it was added to this issue's scope on request.

Every figure below was measured by running GnuCash itself on all eleven supported builds — 3.4, 3.8, 4.4, 4.8, 4.13, 5.5, 5.10, 5.13, 5.14, 5.15 and 5.16 — with the probes listed at the end. Nothing in the tables is read from GnuCash's source; the source was read only to find which function to drive.

## The business need

A multi-currency book values its foreign cash and its stocks through GnuCash's price database: one price per commodity, in a currency, at a time. Two things are needed:

- **Record a rate or a stock price for the date it applied**, for example USD in CAD on 2026-01-01, or NASDAQ:AMZN in USD on 2026-01-06.
- **Keep a book's prices through the export → edit → import cycle**, so a book rebuilt from its ledger values its holdings the way the original did.

Neither is possible today:

- `export` and `import` never read or write the price database.
- `account-balance` writes rates into it (`update_pricedb`, `use_cases/account_balance.py:377`), but only dated the day it runs, at 12:00 local, with source `user:price`, and it writes nothing when the latest rate is unchanged. It cannot record a past date.
- `--fx-rates` files are read by commands; they are never stored in the book.
- README.md:41 says prices round-trip through plaintext. They do not. `export-beancount` writes a price only as an annotation on a split (`use_cases/export_beancount.py:380`), and README.md:9 says prices round-trip through Beancount as well; that claim has not been measured here.

## Decisions

### Commands

| command | what it does with prices |
|---|---|
| `export mybook.gnucash ledger.txt` | writes none — the default, as for business objects, because a book can hold a great many prices |
| `export mybook.gnucash ledger.txt --include-prices` | writes the price blocks into the same ledger, after commodities and accounts, so one file holds the whole book |
| `export-prices mybook.gnucash prices.txt` | writes only price blocks, plus the commodity declarations those prices use so the file imports on its own; takes `--start-date`, `--end-date` and `--latest N`; each works on its own and none requires another, and any of them may be passed together |
| `import mybook.gnucash any.txt` | applies every price block the file holds; no flag and no new command. A file holding only prices imports and saves |

A full backup is one file. `export-prices` is for a list of prices on its own, not a second half of a backup.

- **Where price blocks go in `export --include-prices`:** after commodities and accounts, before business objects and transactions — the order `import` needs, since a price refers to a commodity.
- **`export`'s `--start-date` and `--end-date` filter prices as they filter transactions**, each on its own, by the same local day.
- **Both dates are included**, in `export` and `export-prices` alike: `--start-date 2026-01-01` keeps a price dated 2026-01-01, and `--end-date 2026-01-31` keeps a price dated 2026-01-31. A price belongs to no account, so `--account` does not affect which prices are written.
- **The commodity declarations `export-prices` writes** are the ones `export-accounts` writes, dated the same way.
- **The day a date option compares** is the day GnuCash shows for the price on the machine running the command, as `export --start-date`/`--end-date` compare a transaction's posted day. A price stored at 23:59:59 local on 2025-12-31 is kept by `--end-date 2025-12-31` although its UTC time is on 2026-01-01.
- **`--latest N` without `--end-date`** counts back from today, so a price dated in the future is not among the latest.

**`--latest N` keeps the N most recent prices of each commodity in each currency**, not N prices across the book: `--latest 1` is the current USD in CAD, the current HKD in CAD and the current NASDAQ:AMZN in USD, one price each. A book-wide count would keep only whichever pairs happened to be priced last.

- `--latest N` counts back from today. With `--end-date`, it counts back from that date instead, as if it were today: `--end-date 2025-12-31 --latest 1` is each pair's last price of 2025.
- With `--start-date`, no price from before that date is written, so a pair priced fewer than N times since then writes the prices it has: `--start-date 2026-01-01 --latest 5` is each pair's five most recent prices, or fewer where fewer fall on or after 2026-01-01.
- All three together are the N most recent prices of each pair inside the range, counting back from `--end-date`.
- GnuCash keeps one price per pair per local day (table 1), so the latest N are the N most recent days that pair has a price, and two prices of one pair never tie.
- A pair is a stored direction. A book can hold both USD in CAD and CAD in USD — the transfer dialog stores USD/CAD on 3.4 and CAD/USD from 3.8 on (table 2) — and `--latest 1` then writes one price for each.
- N is 1 or more; `--latest 0` and a negative N are refused.

### The block

```
price
  guid: "4a1a4c0c7328491fbde9f8099ba280c8"
  commodity.namespace: "NASDAQ"
  commodity.mnemonic: "AMZN"
  currency.mnemonic: "USD"
  time: "2026-01-06 21:00:00 +0000"
  value: "21845/100"
  source: "Finance::Quote"
  type: "last"
```

- **`time:` is a full timestamp, never only a date.** GnuCash stores a price's time to the second, and one book holds prices at 00:00 local, 10:59 UTC, 12:00 local, 16:00 local, 23:59:59 local and the moment a quote was fetched, side by side (tables 2 and 3). Export writes the time in UTC, so a ledger reads the same whichever machine exported it. Import takes any offset. A bare date, `time: "2026-01-06"`, is stored with `gdate_to_time64`, the call the transfer dialog and CSV price import use on every build: 10:59 UTC in Toronto.
- **`value:` is an exact fraction**, like `share_price:`.
- **`source:` and `type:` belong to the price.** A book's prices were written by GnuCash's dialogs, assistants, register and Finance::Quote, not by gnucash-plaintext. Export writes the source string exactly as the book holds it, and `type:` only when the price has one. Import stores exactly what the block states. gnucash-plaintext never puts a source of its own on a price.
  - A block creating a price with no `source:` leaves the source unset. GnuCash then holds `invalid`, and the next export writes `source: "invalid"`. A block with no `type:` leaves the type unset, and the next export writes no `type:` line.
  - A `source:` the running build cannot store is refused, and the refusal lists the block. Storing it would silently turn the price into `invalid` (table 5), the lowest rank, so any other price on that day would replace it. This covers `user:stock-transaction` on 3.4 to 4.8, `user:split-import` on 3.4 to 4.4, and any string GnuCash does not define on every build.
  - The file carries the source string and never its number: the numbers differ between versions (`temporary` is 7 on 3.4, 8 on 4.8 and 9 from 4.13 on).
- **`guid:` is the price's identity** (table 4).

### Import rules

- **A block whose guid the book holds** edits that price in place. The guid stays, even when `time:` moves the price to another day. A key the block leaves out changes nothing. Status `updated` or `unchanged`.
- **A block with no guid that states exactly a price the book holds** — the same commodity, currency, time, value, source and type — leaves it as it is. Status `unchanged`, so a hand-written file imported twice changes nothing.
- **A block whose guid the book does not hold, or with no guid,** creates a price, with the stated guid when there is one. Status `created`.
- **The book already holds another price for the same commodity and currency on the same local day.** The block is refused, and the refusal lists that price's guid, time and source; stating that guid edits it instead. `gnc_pricedb_add_price` is not called in that case, because it silently deletes the other price (table 1). Two times are on the same day when GnuCash's `gnc_time64_get_day_start` returns the same start for both: the local day of the process running the import, which is the day `gnc_pricedb_add_price` was measured to replace on (table 1).
- **The pair counts whichever way round it is written.** GnuCash keeps one price a day for USD in CAD and CAD in USD together: adding one on a day holding the other deletes the other, or is turned away when its source ranks lower (table 1). So a CAD in USD block on a day the book prices USD in CAD is refused the same way, and the refusal lists the USD in CAD price.
- **Two blocks in one file for the same commodity and currency on the same local day**, either way round, are refused for the same reason.
- **Two or more blocks in one file stating one guid** are all refused, before anything is applied. A guid is one price: applied in turn, two new prices would both take the guid, and of two edits the later would win (`test_one_guid_stated_in_two_price_blocks_is_refused.py`).
- **An edit whose `time:` moves a price onto a day another price of that pair already holds**, either way round, is refused for the same reason. `gnc_price_set_time64` moving a price onto such a day deletes the price already there (table 1).
- **Only a block that puts a price on a day is checked against it**: a new price, or an edit that changes `time:`. A block that changes nothing, or an edit to `value:`, `source:` or `type:`, moves no price. A book can hold two prices of a pair on one local day of the process importing: GnuCash replaces a price only on the local day of the process adding it, and a book built in Toronto with AMZN prices at 04:59:59 and 10:59 UTC on 2026-01-06, two days there, holds both when opened in UTC (`test_a_block_that_moves_no_price_is_not_checked_for_its_day.py`). Its own export imports back unchanged, and a corrected value is applied.
- **Edits are applied before new prices.** A file may move a price off a day and add a new price for that day, in either order in the file. An edit moving a price onto a day another edit in the file frees waits, and is applied once that edit is, so the order of the blocks decides nothing. Edits left waiting on each other, such as two prices swapping days, are refused, and the refusal says so.
- **A new price's guid must not be held by another kind of object.** GnuCash keeps a guid to one object across the book, and `_guid_in_use_anywhere` is asked before the guid is set, as it is for every other object `import` creates with a stated guid. It asks about prices too, so a customer, invoice or any other block stating a price's guid is refused.
- **An edit changing an existing price's commodity or currency** is refused. GnuCash's price database files each price under its commodity and currency, so changing either in place would leave the price filed under the wrong pair; a price in another currency is a price of its own.
- **`value:`** takes an exact fraction or a decimal, as `share_price:` does.
- **A key a price does not take** is refused, and the refusal lists it. A transaction or a business object keeps a key it does not read as custom metadata; a price has none, so the key would be dropped, and a correction written under a misspelled key lost with the price reported `unchanged` (`test_a_price_block_with_a_key_a_price_does_not_take_is_refused.py`).
- **Reporting.** Only refused blocks are listed one by one, each with its reason; everything else is counted in the summary. A book fetching quotes daily holds thousands of prices, and a line per price would bury the refusals.
- **Order.** Prices are applied after commodities and accounts, and before transactions.
- **Saving.** Prices created or updated count toward `has_changes` in `cli/import_cmd.py`, so a file holding only prices is saved, and an unchanged re-import does not save the book again.
- **Summary.** `Prices: n created, n updated, n unchanged, n refused`.

### Decided in discussion

- A price's time is a full timestamp, not a date.
- Results come from running GnuCash on every build, not from reading its source.
- Prices are left out of `export` unless asked for, as business objects are; they are not moved to a file of their own.
- A price's source is never assigned by gnucash-plaintext.
- The work lives on `feature/record-past-exchange-rates-and-stock-prices-and-keep-them-through-export-and-import`, a name stating the need rather than the format.
- A date filter filters every dated record. `export --start-date`/`--end-date` keep only the prices inside the range, as they keep only the transactions inside it; this was never an open choice.
- The memory fix is part of this issue, and the profiling that found it stays in the repository: `scripts/profile-test-memory.sh`, `tests/research/memory_per_test_plugin.py`, and a memory cap on every test container.

## Measured

Toronto (`TZ=America/Toronto`, UTC−5 in January and February) unless a table says otherwise. Every price was read back after a save and reload, and from the saved file.

### 1. How GnuCash stores a price, and when a second price replaces the first

Probes: `when_a_price_replaces_a_price_probe.py`, `what_a_price_time_holds_probe.py`. All eleven builds agree.

| case | result |
|---|---|
| a price at 15:30:45 local | reads back as 15:30:45 after a reload |
| the saved file's `<ts:date>` | 3.4 writes the local offset, `2026-01-01 15:30:45 -0500`; every later build writes `2026-01-01 20:30:45 +0000` |
| two prices on different local days that share a UTC day (01-01 20:00 and 01-02 10:00 local) | both kept |
| two prices on the same local day but different UTC days (01-03 10:00 and 21:00 local) | only the later one kept — "the same day" is the local day of the process adding the price |
| `Finance::Quote`, then `user:price-editor`, same day | both adds return true; the price-editor price replaces the quote |
| `user:price-editor`, then `Finance::Quote`, same day | the second add returns false; the price-editor price stays |
| the same source twice, same second, a new value | the second replaces the first |
| USD in HKD, then HKD in USD, same day, same source | both adds return true; HKD in USD replaces USD in HKD |
| USD in SGD, then SGD in USD, on two days | both kept |
| USD in SEK `user:price-editor`, then SEK in USD `Finance::Quote`, same day | the second add returns false; USD in SEK stays |
| USD in NOK and NOK in USD on two days, then `gnc_price_set_time64` moves NOK in USD onto the USD in NOK day, same source | USD in NOK is deleted; NOK in USD is kept at its new time |
| NZD in HKD on two days, then `gnc_price_set_time64` moves one onto the other's day, same source | the price already on that day is deleted; the moved one is kept |
| NASDAQ:AMZN in USD on two days | both kept |
| a brand-new book holding nothing but prices | the book is not marked unsaved, and saving writes no file |
| an existing book where a price is the only change | marked unsaved, saved, and the price is there after a reload |

### 2. What time each GnuCash path stores for a price

Probes: `how_the_gui_times_a_price_probe.py`, `how_the_register_times_a_price_probe.py`, `how_the_stock_assistant_times_a_price_probe.py`, `how_the_split_and_csv_assistants_time_a_price_probe.py`, `how_a_quote_is_timed_probe.py`.

| where the price comes from | source stored | 3.4, 3.8, 4.4, 4.8 | 4.13 | 5.5 – 5.16 |
|---|---|---|---|---|
| Price Editor, a new price, date typed into its date field | `user:price-editor` | 00:00:00 local | 10:59:00 UTC | 10:59:00 UTC |
| Price Editor, an existing price opened and OK pressed with nothing changed | the price's own, kept | time rewritten to 00:00:00 local | rewritten to 10:59:00 UTC | rewritten to 10:59:00 UTC |
| Transfer dialog, a rate typed | `user:price` | 10:59:00 UTC | 10:59:00 UTC | 10:59:00 UTC |
| Transfer dialog, a to-amount typed | `user:xfer-dialog` | 10:59:00 UTC | 10:59:00 UTC | 10:59:00 UTC |
| Posting a foreign-currency invoice: the exchange-rate dialog it opens | `user:price`, on the post date | 10:59:00 UTC | 10:59:00 UTC | 10:59:00 UTC |
| Register, a stock purchase entered and the row left (`gnc_split_register_save`) | `user:split-register` | 00:00:00 local on 3.4, 3.8, 4.4 (from the register's date cell); 10:59:00 UTC on 4.8 | 10:59:00 UTC | 10:59:00 UTC |
| Stock split assistant | `user:stock-split` | 00:00:00 local | 10:59:00 UTC | 10:59:00 UTC |
| Stock transaction assistant | `user:stock-transaction` | not in these builds | 10:59:00 UTC | 23:59:59 local — 04:59:59 UTC on the next UTC day |
| CSV price import | `user:price` | 10:59:00 UTC | 10:59:00 UTC | 10:59:00 UTC |
| Finance::Quote, a quote carrying a date | `Finance::Quote` | 12:00:00 local, or the quote's own time (16:00:00 local) | as 3.4 – 4.8 | 10:59:00 UTC; the quote's time is dropped |
| Finance::Quote, a quote with no date, and every currency rate | `Finance::Quote` | the moment of the fetch | the moment of the fetch | the moment of the fetch |

More from the same runs:

- **Opening a price in the Price Editor and pressing OK rewrites its time.** A Finance::Quote price at 15:30:45 local became 00:00:00 local or 10:59:00 UTC, depending on the build, with nobody changing it.
- **The transaction each path creates is dated 10:59:00 UTC on every build**, including where the price is not: the register on 3.4 to 4.4 and the stock transaction assistant on 5.5 to 5.16.
- **An invoice's own rate, a `temporary` price added with `gncInvoiceAddPrice`, reaches neither the price database nor the saved file** on any build; the file carries no `invoice:prices` element. No code in 3.4 to 5.16 sets `user:invoice-post`.
- **A price's direction and precision depend on the build and the path.** The same transfer was stored as USD/CAD `13699/10000` on 3.4, CAD/USD `7300/10000` on 3.8 and CAD/USD `73/100` from 4.4 on. The register stores `218450000/1000000`. CSV import stores `2184500/10000` on 3.4 and `218450000/1000000` on 5.10 and 5.13. Finance::Quote values arrive as `4369/20` through 3.x and 4.x and `21845/100` through 5.x.
- **`xaccTransRecordPrice`**, the call the register makes when saving from 4.8 on, is absent from 3.4, 3.8 and 4.4.

### 3. The time a date-only field stores, in other timezones

Probe: `how_the_gui_times_a_price_probe.py` with `ONLY_DATES=1`, and `how_a_quote_is_timed_probe.py`. Inputs were 2026-01-01 at 00:30, 15:30:45 and 23:30 local; all three stored the same times.

| zone | `gnc_date_edit_get_date` (Price Editor, stock split, invoice post date) | `gdate_to_time64` (transfer dialog, CSV import) |
|---|---|---|
| Toronto, UTC−5 | 00:00 local on 3.4 – 4.8; 10:59Z from 4.13 | 10:59Z on every build |
| Tokyo, UTC+9 | 00:00 local (15:00Z the day before) on 3.4 – 4.8; 10:59Z from 4.13 | 10:59Z on every build |
| Kiritimati, UTC+14 | 00:00 local on 3.4 – 4.8; 09:59Z (23:59 local) from 4.13 | 07:59Z (21:59 local) on 3.4 and 3.8; 09:59Z from 4.4 |
| Pago Pago, UTC−11 | 00:00 local (11:00Z) on 3.4 – 4.8; 11:59Z (00:59 local) from 4.13 | 11:59Z on every build |

- `gnc_date_edit_get_date_end` (stock transaction assistant) returns 23:59:59 local on every build in every zone.
- The register's date cell stores 00:00:00 local on every build in every zone.
- Finance::Quote under UTC+14, measured on 3.4, 4.13 and 5.10: a dated quote is stored at 12:00 local on 3.4 and 4.13, which is 22:00 UTC on the previous UTC day, and at 23:59 local (09:59 UTC) on 5.10.

### 4. Whether a price can be matched by its guid

Probe: `how_a_price_keeps_its_guid_probe.py`. All eleven builds agree.

| question | answer |
|---|---|
| does a price keep its guid through a save and reload | yes |
| can a stated guid be set on a new price (`qof_instance_set_guid`) before it is added | yes, and it reaches disk — in a new book, and in an existing book where that price is the only change |
| does `gnc_price_lookup` find a price by guid after a reload | yes |
| does editing a price in place persist | yes — the value, and the time moved to another day; the guid stays |
| does `gnc_pricedb_remove_price` persist | yes |
| `gnc_pricedb_add_price` meeting another price on the same local day | an equal-ranked source replaces it: the older price and its guid are gone, and a lookup of that guid returns nothing. A lower-ranked source is refused: the add returns 0 and the price is not kept |

### 5. Whether a price's source and type round-trip

Probe: `what_a_price_source_keeps_probe.py`. Each value was set, read at once, read after a save and reload, and read from the file's `<price:source>` and `<price:type>`; all three readings agreed on every build.

| source string set | 3.4, 3.8, 4.4 | 4.8 | 4.13 – 5.16 |
|---|---|---|---|
| `user:price-editor`, `Finance::Quote`, `user:price`, `user:xfer-dialog`, `user:split-register`, `user:stock-split`, `user:invoice-post`, `temporary`, `invalid` | kept | kept | kept |
| `user:split-import` | stored as `invalid` | kept | kept |
| `user:stock-transaction` | stored as `invalid` | stored as `invalid` | kept |
| a string GnuCash does not define | stored as `invalid` | stored as `invalid` | stored as `invalid` |

- Every type string came back exactly on every build — `bid`, `ask`, `last`, `nav`, `transaction`, `unknown`, `pricedb`, and one GnuCash does not use.
- A price created with no source and no type reads back with source `invalid` and no type; the file writes `<price:source>invalid</price:source>` and no `<price:type>` element.

## How the GUI paths were driven

GnuCash's GUI libraries were loaded into a Python process under Xvfb and their own functions called: the dialogs opened, fields filled, OK or Apply signalled, and the book saved and read back. What that needed, found by running it:

- `scm_init_guile()` before anything else. An amount field holding "10" runs `gnc_exp_parser_parse`, which segfaulted in `scm_primitive_load_path` while Guile was not started; the backtrace came from gdb installed in the container. The gnucash program starts Guile itself.
- The register's cell types added first — `gnucash_register_add_cell_types()` from 4.x on, `libgncmod_register_gnome_gnc_module_init(0)` on 3.x — or the ledger's layout has no cells. In the one-line ledger the Transfer column is the `transfer` cell; `account` is the split's own account, and setting it moved the stock split onto the bank account.
- Widgets walked with `gtk_container_forall`: `GNCDateEdit` overrides `forall`, so `gtk_container_get_children` never returns its entry.
- The stock transaction and stock split assistants finish on the GtkAssistant's `close` signal and CSV price import on `apply`, as their glade files connect them.
- A modal error dialog waits for a click for ever, so each probe exits through `faulthandler.dump_traceback_later`.
- Finance::Quote replaced by a stand-in module on `PERL5LIB`, so GnuCash's own `gnc-fq-helper` (3.x, 4.x) or `finance-quote-wrapper` (5.x) runs with no network. Arch and openSUSE also lack Perl's `JSON` and `JSON::Parse`, which the stand-in supplies over `JSON::PP`.
- A price's time set through ctypes `gnc_price_set_time64`, never SWIG `set_time64` with an integer, which 3.4 misreads (CLAUDE.md finding 20).
- On Fedora 41 the stock split assistant segfaulted once while its window was being destroyed, after the price had been added; run again under gdb it exited normally with the same price.

## Work

The README comes first, so the commands are described the way a reader meets them; tests are written against it and each must be seen to fail; the implementation comes last.

0. README: the `Prices` format section, `Export and import prices` under Usage, the round-trip claim at the top corrected, and the note under `account-balance`.
1. The probes below committed under `tests/research/`.
2. Parser: a `price` block.
3. Import: create, update in place, the same-day refusal, the source refusal, a bare-date and a full `time:`, a file holding only prices saving, and an unchanged re-import not saving — fixtures in `tests/fixtures/*.txt`.
4. Export: `--include-prices`, `export-prices` with `--start-date`, `--end-date` and `--latest N` (a date range; `--latest N` on its own, with `--end-date`, with `--start-date` where a pair has fewer than N prices since that date, and with both; both directions of one pair; N refused below 1), and a round trip into a fresh book matching price by price, guid included.
5. Docs: a README section for the price block, README.md:41 corrected, and a CLAUDE.md finding recording tables 2 and 3.
6. The memory fix: `GnuCashRepository.close` destroys its session, `_attach_split_to_lot` uses `gnc_lot_add_split`, the regression tests, the profiling script and the memory cap, and CLAUDE.md findings 9 and 26.

## Probes

All in `tests/research/`. The GUI and quote probes run under Xvfb with the stand-in Finance::Quote:

```
docker run --rm -e TZ=America/Toronto -e TAG=<tag> -v "$PWD:/workspace" -w /workspace \
    gnucash-dev:<tag> sh tests/research/run_a_gui_probe_under_xvfb.sh tests/research/<probe>.py
```

| probe | tables |
|---|---|
| `when_a_price_replaces_a_price_probe.py`, `what_a_price_time_holds_probe.py` | 1 |
| `how_the_gui_times_a_price_probe.py` (`ONLY_DATES=1` for table 3) | 2, 3 |
| `how_the_register_times_a_price_probe.py` | 2 |
| `how_the_stock_assistant_times_a_price_probe.py` | 2 |
| `how_the_split_and_csv_assistants_time_a_price_probe.py` (`SKIP_SPLIT=1` for CSV import alone) | 2 |
| `how_a_quote_is_timed_probe.py` | 2, 3 |
| `how_a_price_keeps_its_guid_probe.py` | 4 |
| `what_a_price_source_keeps_probe.py` | 5 |
| `what_a_closed_book_keeps_in_memory_probe.py` | the memory fix (run with `-e PYTHONPATH=/workspace`, no Xvfb) |
| `whether_a_split_put_in_a_lot_survives_destroying_the_book_probe.py` | the memory fix (run the same way) |

## The test suite kept every book it opened

### How it was found

The full suite was run on all eleven builds at once, to check the price work. The host has 8 CPUs, 24 GB of memory and no swap, and it also runs other services. Load reached 43–52 and free memory fell to 241 MB. Containers had to be killed, and the builds left running took 3 hours 7 minutes each, where one build alone takes 70–150 seconds.

### What was measured

**Where the memory went.** A pytest plugin recorded resident memory before and after every test (`tests/research/memory_per_test_plugin.py`, now run by `scripts/profile-test-memory.sh`). On Debian 13 the process grew from 94 MB to 1729 MB. Of the 1634 MB added, 1413 MB came from tests adding under 2 MB each: the growth was spread over the whole suite, not caused by a few tests. The largest single tests were page printing: 67 MB and 35 MB.

**Not caused by the price work.** Run side by side on Debian 13, `main` (#103) peaked at 1638 MB and this branch at 1690 MB, with 69 more tests.

**A memory cap does not find the cause.** Capped at 1 GB, the Debian 13 run was killed at 48%, in `test_gnucash_renders_the_page.py`, where the running total crossed 1 GB. That test was not the cause.

**Sessions.** The suite created 12,056 GnuCash sessions, ended all of them, and destroyed 15. `GnuCashRepository.close` called `session.end()` and never `session.destroy()`.

| 100 opens of one book of 300 transactions (`what_a_closed_book_keeps_in_memory_probe.py`) | resident memory |
|---|---|
| `end()` alone | 35 MB → 84 MB, about +0.5 MB per open |
| `end()` then `destroy()` | flat |
| `destroy()` alone, GnuCash 3.8, where `end()` alone went from 59.9 MB to 110.8 MB | flat: 111.4 MB → 111.7 MB |

**Why nothing destroyed a session.** Destroying one on close, in the test process only, crashed 42 of 296 test files. A gdb backtrace, from gdb installed in the container, showed the same frames each time: `qof_session_destroy` → `qof_book_destroy` → `xaccTransCommitEdit` → `xaccTransClearSplits` → `xaccSplitCommitEdit` → `gnc_lot_remove_split` → `g_list_remove`, SIGSEGV. The importer's `_attach_split_to_lot` put a split in a lot with `xaccSplitSetLot`, which does not add the split to the lot's own split list (CLAUDE.md finding 9).

| a split put in a lot, then the session ended and destroyed (`whether_a_split_put_in_a_lot_survives_destroying_the_book_probe.py`, GnuCash 5.10) | result |
|---|---|
| with `xaccSplitSetLot` | segfault, exit -11 |
| with `xaccSplitSetLot`, saved first | segfault, exit -11 |
| with `gnc_lot_add_split` | destroyed cleanly |
| with `gnc_lot_add_split`, the split from another account than the lot's | nothing attached and nothing said: the split is in no lot, and the lot lists no split |

**Ending before destroying closes a file twice on 3.4, 3.8 and 4.4.** With `close` calling `end()` and then `destroy()`, the commit gate failed once on Ubuntu 20.04: a test opened the page it had just printed, and reading it raised `OSError: [Errno 9] Bad file descriptor`. `destroy()` ends the session itself, and on those three builds a second end closes the lock file again, by its number (`whether_ending_a_session_twice_closes_a_file_twice_probe.py`):

| GnuCash | `end()`, a file opened, then `destroy()` | `destroy()` alone |
|---|---|---|
| 3.4, 3.8, 4.4 | the file is closed from under the process: `[Errno 9] Bad file descriptor` | lock file closed once, `.LCK` removed, the book opens again at once |
| 4.8, 4.13, 5.5, 5.10, 5.13, 5.14, 5.15, 5.16 | the file stays open | the same |

Under `strace -f` on 3.8, the printed-page test file started 164 processes and threads, among them the thread that writes a book, which opens and closes files while the main thread carries on; every book closed showed `close(lock) = 0` and then `close(lock) = -1 EBADF`. The same test file passed 25 of 25 runs on Ubuntu 20.04 from `main`, where no session is destroyed.

With `close` calling `destroy()` alone, the trace shows no lock file closed twice, but the same test failed once more in 14 full runs on Ubuntu 20.04, as Guile writing the page (`fport_write … Bad file descriptor`), and another printed-page test failed on Debian 11, as a child `print-invoice` whose stdout was closed. Waiting for the race did not reproduce it: 16 full runs and 20 runs of the 457 tests up to the failing one passed.

**A session that took no lock closes a file of the process's on 3.4, 3.8 and 4.4.** Found by preloading a library into a full run that logged every `close()` failing with EBADF, with its backtrace. On 3.8 the pytest process made 2,388 of them from `GncXmlBackend::session_end`, under `qof_session_destroy`, on descriptors 16 and 23 and on values such as 874559168: the lock field of a backend that never took a lock, holding what the previous backend at that address used. Whenever that number is open, the same close takes the file that has it. Every one came from a read-only command closing its book. Measured by opening a book for writing and closing it, opening a file on the freed number, doing the step, and asking whether the file is still open, five times each (`whether_closing_a_read_only_book_closes_a_file_it_never_opened_probe.py`, `whether_a_book_that_fails_to_open_closes_a_file_it_never_opened_probe.py`):

| the step | 3.4 | 3.8 | 4.4 |
|---|---|---|---|
| a book opened read-only, then closed | closed 5 of 5 | 5 of 5 | 5 of 5 |
| a missing book | 5 of 5 | 4 or 5 of 5 | 0 |
| a locked book, for writing | 0 in the probe, and the regression test failed | 4 or 5 of 5 | 0 |
| a new book where a file already is | 5 of 5 | 5 of 5 | 0 |
| a new book in a directory that does not exist | 5 of 5 | 4 of 5 | 0 |
| a file that is not a book; a directory; a directory the process cannot write | 0 | 0 | 0 |

The read-only case was measured on all eleven builds and never closed the file on 4.8 or later. This is the "Bad file descriptor" `tests/conftest.py` absorbs in five pytest paths, and it is older than destroy on close: `end()` runs the same `session_end` (CLAUDE.md finding 27).

**Both changes together**, tried in the test process before the code changed: no crash, 3639 passed and 2 failed, and memory at the end 415 MB. The 2 failures were tests reading accounts after their `with` block had closed the book, which only the leak had kept working.

### The fix

- `GnuCashRepository.close` destroys the session, which ends it and frees the book. It does not call `end()` first.
- `_attach_split_to_lot` uses `gnc_lot_add_split`. Every caller puts the split on the invoice's or bill's posted account first, or refuses a split that is not on it. The set of lots whose split lists were short, and the account walk that made up for it, are gone.
- `test_export_accounts.py` reads accounts and commodities while the book is open.
- Comments that described attaching with `xaccSplitSetLot` as current behaviour are corrected. The guards against a split pointing at a freed lot are kept.
- Every test opens a book through `GnuCashRepository` rather than creating `Session(...)` itself (210 sessions in about 40 files), and `GnuCashFuzzyMatcher` closes its repository instead of ending the session. After the repository fix those still kept about 680 books a run; now a run destroys every session it creates.
- On a GnuCash below 4.8, read from `gnc_version()`, `GnuCashRepository.open` makes no session that takes no lock. A book to read is copied into a private directory and opened for writing there, so its backend closes only its own lock; the book gets no lock, `save()` refuses, and `close()` removes the copy. A missing book, a locked book opened for writing, and a new book where a file already is or in a directory that does not exist are refused before GnuCash is asked, with the sentence GnuCash's own refusal is translated to on every build.

Tests, each seen to fail first:

- `test_c_bindings_are_declared_once.py::test_no_split_is_put_in_a_lot_with_xaccSplitSetLot` — nothing calls `xaccSplitSetLot`; it failed on `services/gnucash_importer.py:2041`.
- `test_a_closed_book_releases_its_memory.py::TestABookOpenedAndClosedAgainAndAgain` — 100 opens and closes keep under 10 MiB; it failed with 48.5 MiB kept.
- `test_a_closed_book_releases_its_memory.py::TestABookAPaymentWasLinkedInto` — an import that links a deposit to an invoice, run in a child process, exits cleanly. It passed before `close` destroyed the session, failed with exit -11 once it did, and passed again with `gnc_lot_add_split`.
- `test_a_book_is_opened_only_through_the_repository.py` — no `Session(...)` outside the repository, in the application or in any file pytest collects; it failed listing 210.
- `test_gnucash_fuzzy_matcher.py::test_the_book_is_closed_once_indexed` — the repository handed to the matcher is closed once the index is built; it failed with the ended session still held.
- `test_a_session_is_destroyed_without_being_ended_first.py` — no `end()` on a session, in the application or in any file pytest collects; it failed on `repositories/gnucash_repository.py:132`.
- `test_closing_a_book_closes_no_file_but_its_own.py` — a file opened on the number a book's lock just freed stays open through a read-only book closed; a missing book, a locked book, a directory and a book in an unwritable directory refused; and a new book refused where a file already is, in a missing directory, and in an unwritable one. Before the fix, six of its tests failed on 3.4 and 3.8 and one on 4.4.

### After the fix

Full suite, every test passing and every session a run creates destroyed, run by `scripts/profile-test-memory.sh`:

| build | GnuCash | tests | memory at the start | at most |
|---|---|---|---|---|
| Debian 13 | 5.10 | 3645 passed, 1 skipped | 95 MB | 343 MB |
| Debian 12 | 4.13 | 3637 passed, 9 skipped | 95 MB | 338 MB |
| Debian 11 | 4.4 | 3637 passed, 9 skipped | 83 MB | 362 MB |
| Debian 10 | 3.4 | 3636 passed, 10 skipped | 130 MB | 341 MB |
| Ubuntu 26.04 | 5.14 | 3645 passed, 1 skipped | 105 MB | 383 MB |
| Ubuntu 24.04 | 5.5 | 3645 passed, 1 skipped | 93 MB | 330 MB |
| Ubuntu 22.04 | 4.8 | 3637 passed, 9 skipped | 84 MB | 317 MB |
| Ubuntu 20.04 | 3.8 | 3637 passed, 9 skipped | 113 MB | 345 MB |
| Fedora 41 | 5.13 | 3645 passed, 1 skipped | 91 MB | 338 MB |
| Arch | 5.15 | 3645 passed, 1 skipped | 98 MB | 393 MB |
| openSUSE | 5.16 | 3645 passed, 1 skipped | 95 MB | 337 MB |

### Kept for the next time

- `scripts/profile-test-memory.sh [tag] [path]` prints the result, memory at the start, end and peak, the session counts, and the test files that added the most memory, and keeps one row per test in `.memory-profile/<tag>.tsv`.
- `scripts/test.sh` caps each container at 1 GB, about two and a half times the highest peak. A run that keeps memory it should not stops with exit 137 and points to the profile script. `GNC_TEST_MEMORY` changes the cap.
