---
id: Q-058
title: "A batch of read commands opens the book once, and writes each command's output to its own file"
category: quality
severity: enhancement
status: open
---

## What was asked

Another user of this tool builds one page from several read commands: two balance sheets (this year end and last year end), the income statement, an export, and a check of the book. Each command is a process of its own, and each opens the book, reads it and closes it. Their summary:

> Each engine call is one gnucash-plaintext process, and every command opens the book on its own. … No command takes a list of commands to run against one open book.

The author asked why gnucash-plaintext cannot open the book once, run a batch of read commands against it, and write each command's output to a file.

**This batch is read-only.** It is not `migrate` (Q-031), which runs commands that write to the book and saves once. No command in this batch writes to the book, and the book is never saved.

## The batch file and what the run prints

As the author stated it: "gnucash-plaintext takes a batch file, every two lines are 1 command first and then the path of output, console output is a summary of batch result, with each command result in output file."

```
gnucash-plaintext batch BOOK BATCH_FILE
```

```
# the T2 page
balance-sheet --as-of 2025-12-31
out/balance-sheet-2025.txt
balance-sheet --as-of 2024-12-31
out/balance-sheet-2024.txt
income-statement --start 2025-01-01 --end 2025-12-31
out/income-statement-2025.txt
export
out/ledger.txt
verify-integrity
out/integrity.txt
```

- Lines come in pairs: a command line without the book, then the path its output is written to. A command line is split as a shell splits it (`shlex`). Blank lines and lines starting with `#` are skipped before the lines are paired. A relative output path is relative to the current directory.
- Refused before the book is opened, every line at once: an odd number of lines, a command that is not a read command, an option the command does not take, a command line stating a book or an output file of its own, `account-balance --fx-rates` (which saves its rates to the book), the same output path twice, a path in a directory that does not exist, and a directory as the path of any command but `print-invoice` and `print-bill`, which take one ending in `/`. Without the last two, a path that cannot be written ended the batch with a traceback at the first command, with no count and the commands after it not run.
- Each output file holds exactly what the command prints when it runs alone, to stdout and to stderr: `find-transactions` says "No matching transactions found." on stderr, and `validate` says "✗ Ledger has errors" there. It is written only once the command has finished (finding 14). A file already there is replaced. Every command's result is written, whether it succeeded or not: nothing in a batch changes the book, so there is nothing a result left out would protect. A refusal is written as Click prints it alone, a usage error's `Usage:` lines included, and each command runs under the name it has alone so those lines read the same. A refusal raised below the CLI (a book that cannot be opened, a page GnuCash could not draw, no Guile, no PDF engine) is written as the group prints it, from the one list in `cli/_refusals.py` that the group and the batch both read. A directory holds no one file to write a refusal to, so `print-invoice` or `print-bill` refused for a directory says why on its console line.
- The console prints one line per command: whether it succeeded, the command, the path it wrote, and the code it exited with if it failed (`failed  verify-integrity, it exited 1 -> out/integrity.txt`). The command's error is in its file. Then a count (`3 commands: 1 succeeded, 2 failed`). A failed command does not stop the commands after it. The run exits 1 if any command failed, and 0 only if every command succeeded.

## What it saves, measured on all eleven builds

`tests/research/whether_read_commands_can_share_one_open_book_probe.py` builds a CAD book of 18,000 transactions over 2024 and 2025, 1.67 MB on disk, and runs six commands: two balance sheets, two income statements, an export and `verify-integrity`. It times them each in a process of its own, as six `gnucash-plaintext` runs, and as one `gnucash-plaintext batch` run, a process of its own as a person runs it. Measured 2026-10-31, one build at a time with nothing else running, with every fix below in place. The last two columns are `batch` in the two earlier runs: with the balance sheet's listing fixed and what a read reads kept, and with the listing fixed and nothing kept.

| GnuCash | image | one open and close | six processes | `batch` | saved | `batch`, before the export's reads were cut | `batch`, nothing kept |
|---|---|---|---|---|---|---|---|
| 3.4 | debian10 | 5.17 – 5.83 s | 43.26 s | 12.25 s | 31.01 s, 72% | 23.16 s | 153.70 s |
| 3.8 | ubuntu20 | 4.95 – 5.29 s | 41.62 s | 11.29 s | 30.33 s, 73% | 13.22 s | 15.20 s |
| 4.4 | debian11 | 4.85 – 5.51 s | 38.84 s | 10.39 s | 28.45 s, 73% | 12.73 s | 14.92 s |
| 4.8 | ubuntu22 | 3.80 – 5.16 s | 35.03 s | 9.71 s | 25.32 s, 72% | 11.49 s | 13.84 s |
| 4.13 | debian12 | 3.46 – 4.19 s | 31.87 s | 9.20 s | 22.67 s, 71% | 10.70 s | 12.38 s |
| 5.5 | ubuntu24 | 4.01 – 4.24 s | 41.09 s | 10.76 s | 30.33 s, 74% | 11.99 s | 13.98 s |
| 5.10 | latest | 0.74 – 0.76 s | 11.82 s | 5.41 s | 6.41 s, 54% | 6.60 s | 9.18 s |
| 5.13 | fedora41 | 0.86 – 0.87 s | 13.18 s | 6.13 s | 7.05 s, 53% | 7.53 s | 9.99 s |
| 5.14 | ubuntu26 | 0.70 – 0.71 s | 11.06 s | 5.24 s | 5.82 s, 53% | 6.66 s | 8.83 s |
| 5.15 | arch | 0.69 – 0.71 s | 11.72 s | 5.68 s | 6.04 s, 52% | 7.35 s | 9.76 s |
| 5.16 | opensuse | 0.72 – 0.73 s | 12.79 s | 6.61 s | 6.18 s, 48% | 8.39 s | 11.32 s |

Each command alone gains from the same fixes, so six processes are faster too where the open is not most of a command: on 3.4 they took 63.02 s before the export's reads were cut and 178.71 s with nothing kept, and from 5.10 13.06 to 14.65 s, then 14.17 to 17.04 s. From 3.8 to 5.5 they took 34.34 to 43.04 s before the export's reads were cut, about what they take now, because six opens are most of it.

**Where the time goes now.**

- **Opening the book.** It takes 3.5 to 5.8 s on every build up to 5.5, and 0.7 to 0.9 s from 5.10. The batch opens it once instead of six times, which is most of what it saves up to 5.5. The time is inside GnuCash, in a list search that grows with an account's splits (below).
- **Starting a process** and importing the CLI and GnuCash takes 0.12 to 0.20 s.
- **GnuCash's report system costs little to load.** It is loaded by the first command in a process that draws a GnuCash report. On a book of 300 transactions held open on 5.10, the first balance sheet took 0.32 s and each one after it 0.02 s. Measured on 5.10 only.
- **On the open book each command is mostly its own work.** On every build, the first balance sheet took 0.65 to 1.17 s, the second 0.35 to 0.55 s, an income statement 0.14 to 0.27 s, the export 1.98 to 2.88 s and `verify-integrity` 0.91 to 1.42 s. 3.4 is the slowest of each, and no longer by much. The first balance sheet walks the splits and keeps them; the second reads what the first kept.
- **The export is the largest command left.** It still walks the splits three times, once each to order the cost bases, to collect what the export lists and to write it: each split's account is asked for three times, its guid twice and each transaction's split list three times.

### Each split's slots were read again by every walk

Profiled on 5.10, the six commands made 810,000 reads of `get_custom_metadata` for 36,000 splits and 18,000 transactions. Each read fetched the slot from GnuCash through ctypes and parsed its JSON again:

- `cost_basis_guid_of`: 324,000 reads, from `_drawn_down_after`, `_disposals_by_cost_basis` and `what_the_disposals_get_wrong`;
- `took_the_residual`: 216,000, from `counts_as_an_exchange_difference`;
- `splits_drawing_on`: 144,000, from `pending_disposals`;
- the export: 36,000 for each split and 18,000 for each transaction.

Each of those functions walks every split of the book through `iter_splits` and asks each split for one key. A balance sheet makes about five such walks, `verify-integrity` most of them again, and the export one of its own. Each walk also asked GnuCash for every account's split list again, which on 3.4 was most of a command's time (below).

### What a read keeps

A book open only to read does not change, so what is read from it once is kept: each object's custom metadata as `get_custom_metadata` parsed it, by the object's address, and the book's splits as `iter_splits` first walked them. `infrastructure/gnucash/kept_while_reading.py` holds the switch and empties every store together.

- **Only while every book open in the process is open to read.** The repository counts open sessions by whether they may change their book, turns keeping on or off as each opens and closes, and empties every store each time, because a freed object's address can be another's.
- **`import --dry-run` opens as `SessionMode.DRY_RUN`**, read from disk as `READ_ONLY` is and never saved, because it changes the book in memory. It was the one read-only open that changes its book.
- **Writing an object's metadata drops what was kept of it.**
- **One store for every command.** The walks inside one command share it, and in a batch every command borrows the held session, so the next command uses it too. The reopen after a rates file's line empties it.

Measured on the 18,000 transactions before the export's reads were cut, each command opening the book itself, keeping off and on in two processes run one after the other:

| command | 5.10 off | 5.10 on | 3.4 off | 3.4 on |
|---|---|---|---|---|
| balance sheet, 2025-12-31 | 2.35 s | 1.81 s | 40.69 s | 13.17 s |
| balance sheet, 2024-12-31 | 1.76 s | 1.39 s | 43.86 s | 13.31 s |
| income statement, 2025 | 1.20 s | 1.14 s | 7.95 s | 7.45 s |
| income statement, 2024 | 1.18 s | 1.12 s | 7.44 s | 7.90 s |
| export | 4.38 s | 4.30 s | 19.08 s | 19.66 s |
| verify-integrity | 2.90 s | 2.00 s | 105.48 s | 18.14 s |
| `batch` of all six | 8.75 s | 6.64 s | 225.25 s | 28.98 s |

The export read each split's slots once, so keeping gained it nothing; its time was in its own repeated reads of each split's account (below). On both builds every page and every file was the same, byte for byte, with keeping off and on. So were eleven read commands on two books holding cost bases (USD and EUR, and a USD deposit with three sales each stating its cost basis), measured on 5.10 with the metadata kept and the split lists not yet kept.

### The export asked GnuCash for the same account facts several times a split

Profiled on 5.10 by counting every call through GnuCash's SWIG wrappers, by function and by the line it was called from: the export made 2,322,105 calls for 36,000 splits. For each split it asked for the account 4 times, the account's commodity 4 times, the commodity's mnemonic and namespace 5 to 6 times, and the account's full name twice. The amount of every split was also rounded by the engine, through `money_text`, though it was already a whole number of the currency's smallest unit.

- **Each account's facts are read once a pass.** `_AccountFacts` in `use_cases/export_transactions.py` holds an account's full name, commodity, mnemonic, namespace, ticker, fraction and smallest unit, kept by the account's address for one formatting pass. A transaction's splits are matched to their facts once, and each split is written from them.
- **`money_text` rounds through the engine only an amount finer than its currency's smallest unit**, and the refusal of such an amount is asked only for one.
- **After it, the export made 1,008,240 calls.** What is left is the three walks above.

Measured with each command in a process of its own, main against this branch, every output byte for byte the same as main's:

- 3.4: export 12.89 s → 8.82 s, export `--with-balance` 14.24 s → 9.03 s, `verify-integrity` 81.58 s → 7.91 s, balance sheet as of 2025-12-31 60.85 s → 7.35 s, income statement 6.62 s → 6.45 s;
- 5.10: export 4.58 s → 3.15 s, `verify-integrity` 3.29 s → 2.17 s, balance sheet 15.99 s → 2.01 s, income statement 1.49 s → 1.36 s.

The balance sheet's figures include its quadratic listing and the kept splits, below; the export's are the account facts and, on 3.4, the lists.

### On 3.4, turning GnuCash's list into a Python list takes seconds

Before the split lists were kept, `batch` on 3.4 took 153.70 s against 178.71 s for six processes, 14% less. On the open book a balance sheet took 44.7 s there and `verify-integrity` 103.2 s. cProfile on 3.4, the book held open: for the balance sheet, 32.87 s of 34.89 s were in 36 calls of `Account.GetSplitList`; for `verify-integrity`, 77.13 s of 81.07 s were in 84 calls of it. The export spent 2.52 s of its run in `Query.run`, under cProfile.

The time is in 3.4's Python bindings turning GnuCash's list into a Python list, not in GnuCash: `xaccAccountGetSplitList` returns at once. Timed on the same book, each list turned into SWIG objects through the bindings, and walked from ctypes with each object looked up by its guid:

| list | 3.4, bindings | 3.4, ctypes | 3.8, bindings | 3.8, ctypes | 5.10, bindings | 5.10, ctypes |
|---|---|---|---|---|---|---|
| Bank's splits, 18,000 | 4.64 s | 0.089 s | 0.018 s | 0.087 s | 0.011 s | 0.057 s |
| every transaction, `Query.run` | 2.57 s | 0.121 s | | | | |

Both give the same objects in the same order. From 3.8 the bindings are faster, so `splits_of_the_account` and `transactions_the_query_finds` in `infrastructure/gnucash/utils.py` walk the list from ctypes only below 3.8, read from `gnc_version()`. `iter_splits`, `_walk_the_splits` in `services/foreign_currency.py`, and the repository's `get_all_transactions` and `get_transactions_by_account` use them. `iter_splits` also keeps the splits (above), so a command lists them once, and a batch once in all.

### A balance sheet took time in the square of the splits it lists

Before the fix, the batch saved 19% to 47%, and a balance sheet on the open book took 10.9 to 13.5 s as of 2025-12-31 on 5.10. Profiled on 5.10:

- **cProfile** of that balance sheet: 13.52 s of 15.04 s were inside the Scheme report (`services/gnucash_statements.py`, `run`).
- **Guile's `statprof`** around `gnc:report-render-html`: 53% of the samples were in garbage collection (`reclaim-owners`, the hook GnuCash runs after each collection) and 41% in `append`.
- **The cause** was in our own text report, `infrastructure/gnucash/reports/balance-sheet-and-income-statement-as-text.scm`. It built each split listing with `(append lines-so-far (list …))`, which copies every line already listed for each new split. The 2025-12-31 sheet lists every split up to the date: 72,050 lines, 1.9 MB.
- **Confirmed by capping the listing.** With `--max-items 0` the same sheet took 0.73 s instead of 14.17 s. As of 2024-12-31, half the splits, it took 2.85 s: twice the splits took five times as long.

The fix is `plaintext:push`, which puts each entry at the front of the list. The list is reversed once at the end. It is used in the seven loops that list one entry per split or per cost basis. Measured on 5.10, the same book, every page byte for byte the same as before:

- balance sheet as of 2025-12-31: 14.99 s → 1.33 s;
- balance sheet as of 2024-12-31: 2.79 s → 0.83 s;
- `report`, both statements: 10.27 s → 1.30 s;
- an income statement, and a balance sheet with `--max-items 3`: unchanged.

### Up to 5.5, opening a book takes time in the square of an account's splits

Profiled on 4.13 and 5.10, opening the book read-only and closing it: all of it is inside GnuCash. On 4.13 `qof_session_load` took 5.78 s and `qof_session_destroy` 1.59 s; on 5.10 0.79 s and 0.09 s.

- **Not the compression.** Saved uncompressed, 23.99 MB, the book took 4.45 s to load on 4.13, 4.96 s on 3.4 and 0.53 s on 5.10.
- **Sampled with gdb** while the book loaded and was freed, about three samples a second. On 4.13, 46 of 60 samples were in `g_list_find`: 31 under `gnc_account_insert_split`, which `xaccTransCommitEdit` calls for each transaction as the XML is read (`dom_tree_to_transaction`), and 15 under `gnc_account_remove_split`, as `qof_book_destroy` frees it. On 3.4, 25 of 40 were in `g_list_find`, and on 5.5 32 of 40. On 5.10 none of 7 were.

So up to 5.5, putting a split in its account searches the account's list of splits first, and taking one out searches it again. The bank account holds all 18,000 splits. Nothing this tool calls can avoid that; the batch makes it happen once.

## What the batch must handle

**A rates file's prices reach the next command.** `--fx-rates` and `--prices` add their prices to the open book for the run (`add_for_the_run` in `services/report_prices.py`, finding 28), and nothing takes them off, because today the book is closed straight afterwards. Measured on all eleven builds, on a book holding USD and EUR:

- `balance-sheet` alone states 4,050.20 CAD of assets;
- `balance-sheet --fx-rates` states 7,000.00 CAD;
- the next `balance-sheet`, with no rates file, on the shared book, states 7,000.00 CAD where it states 4,050.20 CAD alone;
- the book on disk is unchanged.

So the batch must keep a command's added prices from reaching the next command, and a test must show the next command reading 4,050.20 CAD again.

**Anything else a command sets for its own run** must be put back the same way. The date format global is already restored by `services/gnucash_report.py` (finding 15).

## What was built

- **`gnucash-plaintext batch BOOK BATCH_FILE`**, in `cli/batch_cmd.py`.
- **One session for every command.** `one_open_book_for_reading` in `repositories/gnucash_repository.py` opens the book read-only and holds it. A command opens the book read-only as it does alone, and `GnuCashRepository.open` hands it the held session. Its `close` leaves that session open for the next command. No command was changed.
- **Each command is parsed before the book is opened**, by Click, with the command's own options. Every line that cannot run is listed in one refusal:
  - a command the batch does not run;
  - an option the command does not take;
  - a command stating a book or an output file of its own;
  - `account-balance --fx-rates`, which saves its rates to the book;
  - two commands writing to one path.
- **Every command that only reads the book is run**: `export`, `export-accounts`, `export-prices`, `export-beancount`, `export-transaction`, `balance-sheet`, `income-statement`, `report`, `print-invoice`, `print-bill`, `fx-balances`, `account-balance`, `verify-integrity`, `validate` and the three `find-*` commands. Each opens the book read-only through `GnuCashRepository`, so each is handed the held session unchanged.
- **The path is handed to a command that writes a file of its own**: after the book for `export`, `export-accounts`, `export-prices` and `export-beancount`, and as `--output` for `export-transaction`, `balance-sheet`, `income-statement`, `report`, `print-invoice` and `print-bill`. So a statement or an invoice in HTML or PDF is written as it is alone. Every other command's printed output is written to the path, including what `validate` writes to `sys.stdout.buffer`, in the order it came.
- **Every command writes its result, whether it succeeded or not.** `verify-integrity` on a book with something wrong writes its list and exits 1, and a command refused writes the refusal it prints alone. Its line on the console says it failed and the code it exited with. The commands after it still run, and the batch exits 1. The first version wrote nothing for a command that did not exit 0, as an import must not leave half a result; a read has nothing to protect, and the person lost the list that says what is wrong. Running the scenarios' reads through `batch` found it: `fx-balances --verify-costs` reporting a `$pending$` that disposes of nothing, and `verify-integrity` reporting a balance that does not parse, each left no file.
- **A rates file prices only its own line.** After a command given `--fx-rates` or `--prices`, the book is read from disk again for the commands after it. Taking the added prices off would not do: GnuCash keeps one price a day for a pair, so an added price can displace one the book holds, and removing ours would not bring the book's back (finding 25).
- **What a read reads is kept**, the export reads each account's facts once a pass, and below 3.8 lists are walked from ctypes (above). These shorten every read command, alone or in a batch.
- `tests/integration/test_a_batch_of_read_commands_reads_one_open_book.py` shows:
  - every file equals what the command writes alone, for each of the seventeen commands;
  - the balance sheet after the rates file's line states 4,050.20 CAD again;
  - the later commands still run after a refused command or one exiting 1, and each of the two writes what it prints alone;
  - every refusal, the book left unopened.
- `tests/scenario/test_a_batch_reads_the_books_the_other_scenarios_build.py` is the batch's scenario, and its cases are the other scenarios'. It builds ACMU's, ACME's, the Hong Kong company's and the US company's books with those scenarios' own builders and fixtures, and runs in one batch on each the read commands that scenario runs. ACMU's balance sheets and income statements state the figures its scenario states, and every file holds what the command writes alone.

**`batch` takes about as long as the same commands on one open book inside the probe's process.** The probe also runs the six commands that way. From 5.10, `batch` took between 0.13 s less and 0.25 s more. Up to 5.5 it took 1.56 to 3.51 s less, because the probe's own open was slower (4.95 to 6.88 s) than the open `batch` made.

**Output is the same.** On every build, every file `batch` wrote was the same, byte for byte, as what the command writes alone.

## Not measured

- A batch with no command that draws a report. Its saving would be the opens alone: 0.7 to 0.9 s a command from 5.10, 3.5 to 5.8 s up to 5.5.
- What the report system costs to load on any build but 5.10.
- Each command with keeping off against keeping on, on any build but 5.10 and 3.4. The eleven-build table compares `batch` only.
- One walk of the splits for what the balance sheet's five walks and the export's three ask. Not built.
