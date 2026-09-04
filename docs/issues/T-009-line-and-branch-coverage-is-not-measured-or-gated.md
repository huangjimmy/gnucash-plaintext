---
id: T-009
title: Line and branch coverage is measured by nothing, so unreachable code is found by review instead; ctypes signatures are declared per-caller
category: tests
severity: high
status: open
---

## Problem

Nothing measured coverage. `pytest-cov` was a declared dev dependency and `[tool.coverage.run]` was configured in `pyproject.toml`, but `scripts/test-in-docker.sh` ran `pytest tests/ -v --tb=short` — no `--cov`, no threshold, no report. The configuration had been sitting there unused, so a clean run said nothing about whether a line had ever executed.

The cost showed up during Q-035. An independent review of that change found lines that could not be reached at all: a guard on `remainder <= 0` where the caller's own condition makes the remainder positive always, a `named_txn_guid` check that could never be false, an unpost refusal that no export could satisfy. Each one is a defect — either the guard is in the wrong place or the code below it is dead — and each was caught by a person reading the diff. A branch counter would have flagged all three mechanically, before the review ever ran.

## What is in place now

`./scripts/coverage.sh` runs the suite on every supported distribution with coverage on, adds the runs together, and gates the union.

The union is the only figure that means anything here. The tree carries paths that only a particular GnuCash reaches — a slot read on 3.8 and 4.4 and derived from 4.13, a SWIG call that works on Debian and needs ctypes on Ubuntu — so a line can be untestable on the machine in front of you and ordinary on the next. A per-distribution gate would report those as gaps forever; the union reports only lines that **no** supported version reached.

- `[tool.coverage.run] branch = true` — an `if` whose false side never runs is untested, and a line count alone calls it covered.
- Each version writes `.coverage-data/.coverage.<version>`, so the parallel sweep's ten containers write side by side and `coverage combine` adds them up. Not `parallel = true`: pytest-cov combines a run's own files into the canonical name before exiting, which would have every container writing over the last one to finish.
- `relative_files = true` — the sweep copies the workspace per version, so the same module is at a different absolute path in each run.
- `GNC_COVERAGE=1 ./scripts/test.sh <version>` measures one version; plain runs stay as fast as they were.

## Measured baseline

Union of `latest` (debian:13, GnuCash 5.10), `debian12` (4.13), `debian11` (4.4), `ubuntu20` (3.8) and `arch` (5.15), 1476 tests, 2026-08-06:

**89%** — 1004 statements and 560 branches that no supported version executes. It read 88% (1023 lines, 566 branches) before the work below.

`repositories/` is measured with the rest. It was missing from `source`, which does not mean "reported as uncovered" — it means not reported at all, so the planned gate would have gone green over a whole layer. `repositories/gnucash_repository.py` turned out to be at 95%, but that is a fact the measurement had to establish rather than assume.

Combining the four moved the figure by ten lines against a single run, which settles a question worth recording: **the gap is not platform variance.** It is code the suite does not reach. The aggregate rule is still right — those ten lines are real, and more versions would add a few more — but it buys almost nothing, so the work below cannot be waved off as an artefact of the measurement.

| file | lines | branches | covered |
|---|---|---|---|
| `services/gnucash_importer.py` | 217 | 187 | 89% |
| `services/bill_renderer.py` | 69 | 15 | 74% |
| `use_cases/unpost_business_objects.py` | 64 | 26 | 80% |
| `infrastructure/gnucash/kvp.py` | 61 | 8 | 69% |
| `cli/import_beancount_cmd.py` | 55 | 0 | 15% |
| `cli/bill_print_cmd.py` | 48 | 13 | 63% |
| `services/foreign_currency.py` | 41 | 30 | 89% |
| `use_cases/export_beancount.py` | 28 | 10 | 79% |
| `infrastructure/gnucash/utils.py` | 28 | 11 | 82% |
| `cli/export_beancount_cmd.py` | 24 | 0 | 28% |
| `services/invoice_renderer.py` | 23 | 24 | 92% |
| `cli/invoice_print_cmd.py` | 20 | 7 | 84% |
| `use_cases/import_beancount.py` | 19 | 7 | 84% |
| `cli/import_cmd.py` | 19 | 8 | 90% |
| `use_cases/export_transactions.py` | 17 | 17 | 95% |
| `cli/report_cmd.py` | 17 | 5 | 74% |
| `use_cases/export_business_objects.py` | 15 | 15 | 94% |
| `services/ledger_validator.py` | 15 | 16 | 88% |
| `repositories/gnucash_repository.py` | 4 | 7 | 95% |

The rest is a long tail of ten-or-fewer per file. `./scripts/coverage.sh --report-only --html` gives the line-by-line view.

The beancount subsystem stands out as a block rather than a tail: `import-beancount` at 15% and `export-beancount` at 28% are whole commands whose bodies never run, against one round-trip test that calls the use cases directly and skips the CLI entirely. Roughly 150 of the 1572 points are there, and a handful of command-level tests reach most of them.

## Where it stands now

Union of all ten supported builds — `latest` (5.10), `debian12` (4.13), `debian11` (4.4), `ubuntu26` (5.14), `ubuntu24` (5.5), `ubuntu22` (4.8), `ubuntu20` (3.8), `fedora41` (5.13), `arch` (5.15), `opensuse` (5.16) — 2312 tests, 2026-08-11:

**94%** — 504 statements and 439 branches that no supported version executes, against 1004 and 560 at the baseline. Thirty-nine files are at 100% and no longer appear in the report at all.

`THRESHOLD` in `scripts/coverage.sh` is 94, so the figure cannot slip back.

| file | lines | branches | covered |
|---|---|---|---|
| `services/gnucash_importer.py` | 242 | 201 | 90% |
| `use_cases/unpost_business_objects.py` | 43 | 29 | 88% |
| `services/foreign_currency.py` | 30 | 28 | 93% |
| `services/invoice_renderer.py` | 18 | 21 | 93% |
| `use_cases/export_transactions.py` | 17 | 26 | 95% |
| `infrastructure/gnucash/utils.py` | 17 | 9 | 89% |
| `use_cases/account_balance.py` | 10 | 7 | 92% |
| `use_cases/import_transactions.py` | 9 | 5 | 95% |
| `use_cases/export_business_objects.py` | 9 | 11 | 96% |
| `services/bill_renderer.py` | 9 | 10 | 95% |

The rest is a tail of eight-or-fewer per file. Two whole subsystems have left the table: `cli/import_beancount_cmd.py` and `cli/export_beancount_cmd.py`, at 15% and 28%, are now at 100% — the command bodies are exercised through the CLI, including every per-object failure path, and the refusals they grew along the way are each paired with a fixture and listed in `RELEASE_NOTES.md`.

**What closing the gap actually produced.** The lines were the instrument, not the goal: nearly every gap was a behaviour nothing had asked about, and asking found defects rather than merely covering statements. Among them — a payment block that entered the same money twice when its `txn_guid:` was mistyped; a book made unexportable by a currency GnuCash restated between versions; an import that rewrote the book on every run over a ledger that had not changed; a printed page that leaked its owner's private keys and reported a credit settlement as a bank payment; the `export` and `print-invoice` truncation described in CLAUDE.md finding 14; and a `payment:` block spending a foreign account whose cost bases still held a balance.

**What was deleted rather than covered**, in the same spirit as the ten branches Q-035 removed: `get_all_sub_accounts`, `to_string_in_fraction_format`, `render_to_pdf`, the `available_of`/`open_available` family, three duplicated copies of `holdable_unit`, a null-account guard in `cli/find_transactions_cmd.py` (finding 12 above is the measurement that settles it), and the `try`/`except` wrappers around SWIG calls that cannot raise on any supported build.

**What is listed rather than covered.** `cli/_saving.py:22-24` — the branch that swallows `ERR_FILEIO_BACKUP_ERROR` — is reachable only when two saves land inside the same second, which is the collision the suite deliberately sleeps a second to avoid. A test that depends on the timing going the other way is a flake, so the path is recorded here instead.

## Closed as part of Q-035

Two branches in the credit-division machinery, both of which state a rule in a docstring that nothing checked:

- **A balance that will not parse, carried across a division.** `available_of` answers `None` for a balance that is absent and for one that is malformed alike, so inside a branch that has already found the key, `None` can only mean malformed. Read as absent, the largest figure the division could produce is written onto a cost basis nobody can vouch for, and the text `--verify-costs` exists to report is destroyed on the way — `20,00` for `20.00` comes back as a clean 70.00 available. Q-035 recorded this as "guarded by construction rather than by a failing test"; it is now `test_a_balance_that_will_not_parse_survives_a_division_as_it_reads`.
- **A credit with no recorded balance, divided.** A credit carrying a cost but no balance has none recorded — nothing wrote down what has already been sold from it — and reading the residue's own size as its balance would open a cost basis for currency that may be long gone. Now `test_dividing_a_credit_with_no_recorded_balance_records_none`.

Both build a book the importer would refuse to read, by writing the KVP directly, because how such a book is *read* is the thing under test.

Ten unreachable branches were deleted rather than covered, which is the answer whenever a branch cannot be taken:

- `_carry_basis_to_residue` and `_mark_spent_credit` each guarded their edit with "reopen the transaction if it is closed". Both are only ever called with a committed transaction, so the guard could take one of its two paths and never the other. They begin and commit the edit outright. (4 branches)
- Two copies of a hand-written ctypes walk up the account's parent pointers, in `_retarget_with_prepayment_split` and `_retarget_counter_split_to_lot`, each carrying three branches nothing can reach: an account with no name, one whose parent is null — that is the root, and no split is on it — and a loop that can only ever end by breaking. Both now name the account through `get_account_full_name`, the SWIG accessor every other reader in the file uses; only the *setter* still needs ctypes, for the const-type mismatch. (6 branches, and 30 lines)

What is left uncovered in that machinery is one defensive path reached three times — a payment transaction carrying no split other than the bank's, which no file can produce. Reachable only from a malformed book, so it is kept and listed rather than deleted.

## ctypes signatures declared per-caller

Found while covering the above, and the same shape of problem: a rule nothing checked.

`argtypes` must be set for every C function taking a pointer, or ctypes passes a Python integer as a C `int` and truncates a 64-bit pointer to 32 bits on x86_64 — a segfault, not a warning. `infrastructure/gnucash/engine.py` exists to declare them once, and `verify_ctypes_functions` checks at load that the build has them. But 36 declarations across 9 modules were being set beside their callers instead.

That is not merely untidy. `load_gnc_engine` is `lru_cache`d, so the handle is process-wide: a second declaration of a symbol rewrites what every earlier caller is holding. The lot block in `gnucash_importer.py` declared `gnc_lot_add_split` as `c_int` while the shared engine declares it `None`, on one function, with the winner decided by import order. Nothing read that return value, so it never showed — which is the point.

`tests/unit/infrastructure/gnucash/test_c_bindings_are_declared_once.py` reads the syntax tree of every module under `cli/`, `services/`, `use_cases/`, `infrastructure/` and `repositories/`, and fails on any `argtypes`/`restype` assignment or `ctypes.CDLL` call outside the shared engine that is not on its `KNOWN` list. It is a ratchet, failing in both directions: a new declaration is refused, and one that has been moved must be struck off the list, so it cannot go stale. A companion test asserts the shared handle really carries argtypes for the fifteen lot and owner functions the credit paths call.

Both spellings are counted. `lib.xaccSplitGetAmount.restype = …` names its symbol in the attribute chain, while the loop form — `f = getattr(lib, name); f.restype = …` — names only the local, so the symbols are read out of the list the loop iterates. Recorded by the local instead, one `'f'` entry exempted a whole loop: two files were covered by one such entry each, standing for 14 and 24 symbols between them, under which a new conflicting declaration would have passed silently and a removed one would have kept the entry alive. Those 38 are named individually now.

Moved as part of Q-035 (they are what the credit machinery calls): `xaccSplitSetAccount`, `xaccSplitGetParent`, `xaccSplitGetAmount`, `xaccTransGetDate`, `gnc_lot_new`, `gnc_lot_add_split`, `gnc_lot_get_balance`, `gnc_lot_is_closed`, `gnc_lot_get_earliest_split`, `xaccAccountInsertLot`, `xaccAccountGetLotList`, `gncInvoiceGetInvoiceFromLot`, `gncOwnerInitCustomer`, `gncOwnerInitVendor`, `gncOwnerAttachToLot`.

Left on the list, each a line of work:

| file | what it declares |
|---|---|
| `use_cases/unpost_business_objects.py` | 24 owner, lot, split and transaction functions, in the loop form |
| `use_cases/unapply_payment.py` | 14, likewise |
| `services/gnucash_importer.py` | GUID plumbing (`qof_instance_get_guid`, `guid_to_string_buff`, `string_to_guid`, `xaccAccountLookup`, `qof_instance_set_guid`) in four places, on a bare `ctypes.CDLL(None)` |
| `infrastructure/gnucash/kvp.py` | a second engine loader of its own, plus a GObject handle and six KVP functions |
| `services/transaction_matcher.py` | three owner functions |
| `use_cases/export_business_objects.py`, `use_cases/account_balance.py`, `cli/find_transactions_cmd.py` | two or fewer each |

| `use_cases/export_transactions.py` | nine owner, lot and transaction functions on a `_lib` of its own |

What Q-035 removed from that file is the two *lot-reading* loops, not the file: `open_prepayments_for_account` and `_ownerless_open_credit_lots` declared nothing after it, including `gnc_lot_get_balance` as a locally defined struct while the shared engine declares it as `GncNumericC` — agreeing only because the two have the same fields, which is the `gnc_lot_add_split` story repeating. Five of those went with the stale lot reading that called them, two moved to the shared engine, and the rest were already there. The nine in the transaction-export path above are untouched and still on the ratchet's list.

The bare `CDLL(None)` handles matter most. The shared loader promotes the library to `RTLD_GLOBAL` by its known path *before* calling `CDLL(None)`, which is what guarantees the same instance the GnuCash Python extension is using. A module loading its own handle skips that, and on Ubuntu — where the extension loads with `RTLD_LOCAL` — can bind a different copy of the library than the one holding the book.

## Remaining work

Reach 100% line and branch on the union, then turn the gate on:

1. Cover or delete what the "Where it stands now" table lists, file by file. Where a line cannot be reached, deleting it is the answer — an unreachable line is the defect, and a test that reaches it by contortion only hides that. `services/gnucash_importer.py` is half of what is left on its own.
2. Raise `THRESHOLD` in `scripts/coverage.sh` as each file is closed — it stands at 94 — and at 100 move it to `fail_under` in `[tool.coverage.report]`. It tracks the measured floor rather than the destination so that the bare command passes and refuses to let the figure slip; a default of 100 today would fail on every run, and a gate that always fails is a gate somebody turns off.
3. `scripts/hooks/pre-commit` runs `test-all-versions-parallel.sh` already; run it under `GNC_COVERAGE=1` and gate on the combined figure there, so a commit that adds an unreached line is blocked the way a lint failure is.
4. Empty the `KNOWN` list in `test_c_bindings_are_declared_once.py`, file by file, starting with the two bare `CDLL(None)` handles.

The gate is deliberately not switched on yet: a gate that fails on the first commit after it lands is turned off again by the next person who needs to commit.

`# pragma: no cover` stays rare and reasoned. A defensive `raise` for a SWIG symbol whose absence means a broken install is a fair use; "hard to test" is not.

## Related

- [Q-035](Q-035-usd-multi-currency-invoices-and-bills-unsupported.md) — where the unreachable branches were found by review, which is what this exists to replace
- [T-008](T-008-tax-included-and-payment-reconciliation-coverage.md) — an untested branch that turned out to be hiding a production bug, found the same way
