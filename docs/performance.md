# What the commands cost, and how the GnuCash version changes it

Every figure here was measured on 2026-09-16, on one 8-core host, in the project's own Docker images, with the versions CLAUDE.md lists. They are single runs rather than averages, so read them as shapes rather than benchmarks: the differences below are large enough to act on, and a 10% difference in any row is not.

Reproduce them with the probes in this repository's scratchpad pattern — a container per build, the package installed with `pip install -e '.[dev]'`, and the timings taken with `time.perf_counter()` around `GnuCashRepository` calls and around `CliRunner().invoke(cli, ...)`.

## The short of it

**Newer GnuCash reads faster and writes slower.** Reading a book, comparing a ledger against it and reporting on it all get quicker with every version. Writing a book of a few thousand transactions gets slower: the same 2,000-transaction import takes 2.8 s on GnuCash 3.4 and 5.2 s on 5.16.

**Nothing here is the Python version.** The interpreters differ across the images — 3.7 on Debian 10 through 3.14 on Arch — and a fixed arithmetic loop takes 0.08 s on 3.7 against 0.10 s on 3.14. The differences below are GnuCash's, not Python's.

## The commands, on 2,000 transactions

A 217 KB ledger of 2,000 two-split transactions, imported into a fresh book of 183 KB, then read again, exported, and reported on:

| command | GnuCash 3.4 | GnuCash 4.8 | GnuCash 5.16 |
|---|---|---|---|
| `import --new` | 2.8 s | 3.6 s | 5.2 s |
| `import` again, nothing changed | 1.1 s | 0.9 s | 0.6 s |
| `export` | 1.3 s | 1.1 s | 1.0 s |
| `fx-balances --verify-costs` | 0.8 s | 0.5 s | 0.4 s |
| `find-transactions --amount` | 0.3 s | 0.2 s | 0.1 s |

The first row is the one to plan around. An import that creates transactions writes the whole book, and that write is where the newer engine costs more. Everything that only reads — a re-import that finds nothing changed, an export, a cost basis report, a search — is faster on the newer engine, by roughly two to three times between 3.4 and 5.16.

## The operations underneath

300 rounds against a small book (about 1 KB), so these are the fixed costs of getting at a book at all:

| operation | GnuCash 3.4 | GnuCash 4.8 | GnuCash 5.16 |
|---|---|---|---|
| open read-only, then close | 2.0 ms | 1.4 ms | 1.1 ms |
| open, save, close | 1.9 ms | 1.4 ms | 1.2 ms |
| copy the book file | 0.2 ms | 0.2 ms | 0.2 ms |

Below GnuCash 4.8 this tool copies a book into a private directory before opening it to read, because on 3.4, 3.8 and 4.4 a session that takes no lock closes a file descriptor of the process when it ends (CLAUDE.md finding 27). That copy is the third row: 0.2 ms, about a tenth of what an open costs there. It is a real cost and a small one.

**A compressed book is decompressed twice.** GnuCash writes books gzipped unless the preference is turned off, and before GnuCash is asked to parse one this tool reads its first and last kilobyte, to tell a whole book from one that stops partway through — a file GnuCash 4.4 and later open as an empty book with no error at all. A gzip stream cannot be seeked to its end, so that check walks the whole stream. Measured on 5.10, per open:

| the book | the check | a read-only open | the check's share |
|---|---|---|---|
| 500 transactions, 44 KB gzipped | 1.64 ms | 23.0 ms | 7.1% |
| 2,000 transactions, 171 KB gzipped | 2.61 ms | 93.7 ms | 2.8% |
| the same books uncompressed | 0.06 ms | 16.1 and 65.4 ms | 0.1–0.3% |

It is a few per cent of an open, and a smaller share the larger the book, because GnuCash's own parse grows faster than the decompression does.

## The test suite, for contributors

The suite is 4,091 tests, almost all of which open, change and re-read real books, so it magnifies the read-side costs above. One build at a time, from the union sweep of 2026-09-16:

| build | GnuCash | suite |
|---|---|---|
| ubuntu26 | 5.14 | 1:30 |
| arch | 5.15 | 1:34 |
| latest (debian13) | 5.10 | 1:59 |
| debian12 | 4.13 | 2:03 |
| ubuntu22 | 4.8 | 2:04 |
| fedora41 | 5.13 | 2:06 |
| opensuse | 5.16 | 2:08 |
| ubuntu24 | 5.5 | 2:17 |
| debian11 | 4.4 | 2:52 |
| ubuntu20 | 3.8 | 3:22 |
| debian10 | 3.4 | 3:31 |

Those runs share the host two at a time. Run alone, the same suite takes 183.5 s on 3.4 and 96.6 s on 4.8, and the slowest twenty tests are the same tests on both, each about 1.5 to 2 times slower on 3.4. They account for around 20 s of the 87 s difference, so the rest is spread evenly across the other four thousand: it is the cost of every engine call, not one slow corner.

## What this means in practice

- **Importing a large ledger is the slow operation, and it is slowest on the newest GnuCash.** If a run imports tens of thousands of transactions, the engine version decides the wait more than anything this tool does.
- **Reporting, searching and re-importing an unchanged ledger are cheap**, and cheaper the newer the engine. A re-import that changes nothing costs about half an import that creates everything.
- **Debian 10 and Ubuntu 20.04 are the slow builds for contributors**, by about a factor of two on the suite. They are supported because they carry GnuCash 3.4 and 3.8, which behave differently in ways this project measures (CLAUDE.md findings 19, 20, 22, 24, 26 and 27), not because anyone runs them for speed.
