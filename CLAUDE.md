# AI Agent Rules for gnucash-plaintext Project

Project-specific rules and conventions for Claude Code and Gemini CLI assistance.

## Git Commit Rules

### ❌ NEVER Do These:
1. **No `git add -A` or `git add .`**
   - Always add files explicitly by name
   - Prevents accidentally committing temporary files, secrets, or reference materials

2. **No Co-Authored-By**
   - Do NOT include `Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>` or any Gemini equivalents in commits
   - Keep commit messages clean and professional

3. **No committing external reference files**
   - `convert_qfx.py`, `ledger.py` are external references (not part of repo)
   - `reference_file*.txt` are external test data (not part of repo)
   - Always check with user before committing untracked files

4. **No one-line commit messages for non-trivial changes**
   - Trivial changes (e.g. typos, single-line formatting) can be one line
   - Architectural, feature, or bugfix commits must NOT be a single line

### ✅ Always Do These:
1. **Stage files explicitly**
   ```bash
   git add Dockerfile migration_plan.md scripts/
   # NOT: git add -A
   ```

2. **Highly Detailed Commit Messages**
   - Subject line in the imperative, as long as it needs to be to say what the change does. Not 50 characters — this file used to say that and every commit in the history ignores it, running 160 to 300. A subject that fits in 50 says "fix cost basis handling", which tells a reader nothing; the real ones state the change and its clauses, joined with commas and "and". Write that.
   - Blank line after subject
   - **Detailed body** explaining *what* was changed and *why* (the context/rationale)
   - Use bullet points for multiple specific changes
   - Describe the end-state of the project, not the path that got there: don't reference old filenames being "renamed" or behaviour being "replaced" — the diff already shows that and the description ages badly
   - This provides critical context for future developers (and future AI sessions)

3. **Verify before commit**
   ```bash
   git status
   git diff --cached --name-only
   ```

## Feature Branch Workflow

This is an open-source project. **Never commit directly to `main`.**

### ✅ Always Do These for New Work:
1. **Create a new worktree + feature branch** for every feature, bugfix, or example addition:
   ```bash
   # Run from the repo root or any existing worktree
   git worktree add worktree/<branch-name> -b <branch-name>
   # Example:
   git worktree add worktree/feature/fava-viewer-example -b feature/fava-viewer-example
   ```

2. **Do all work inside `worktree/<branch-name>`** — `worktree/main` is always the main branch and must never be worked on directly

3. **Open a PR** from the feature branch to `main` when the work is ready

4. **Clean up** the worktree after the PR is merged:
   ```bash
   git worktree remove worktree/<branch-name>
   git branch -d <branch-name>
   ```

### ❌ NEVER Do These:
- Commit directly to `main`
- Do feature work inside `worktree/main` — it is reserved for the main branch only
- Delete the remote branch (`git push origin --delete <branch>`); the GitHub PR-merge UI handles remote cleanup

### After creating a worktree
- Run `git config --worktree core.bare false` inside the new worktree before any other git ops; otherwise commits fail with a bare-repo error.

---

## Docker Rules

### Supported Distributions (Verified)

The version each image carries, read from its own package database on
2026-08-09. The tag names and the versions are not interchangeable, and
guessing one from the other has been wrong: `ubuntu24` is 5.5, not the 4.9 it
was listed as, which put the only 4.x/5.x behavioural boundary this suite has
measured on the wrong side of two builds.

- debian:13 (GnuCash 5.10) - default, `latest`
- debian:12 (GnuCash 4.13)
- debian:11 (GnuCash 4.4)
- debian:10 (GnuCash 3.4) - minimum, Python 3.7
- ubuntu:26.04 (GnuCash 5.14)
- ubuntu:24.04 (GnuCash 5.5)
- ubuntu:22.04 (GnuCash 4.8)
- ubuntu:20.04 (GnuCash 3.8)
- arch (GnuCash 5.15)
- fedora:41 (GnuCash 5.13)
- opensuse (GnuCash 5.16)

**Two of these are past their end of life and are served from elsewhere.** The
Dockerfile points bullseye at `snapshot.debian.org` and buster at
`archive.debian.org`, both with `Acquire::Check-Valid-Until "false"`, and
buster needs `libxslt1-dev` where every other base wants `libxslt-dev` and has
no `weasyprint` package at all.

bullseye is the sharp one, because the mirror lies: `deb.debian.org` still
publishes a *valid* security index — measured 2026-09-05, `Valid-Until: Mon,
07 Sep 2026` — while deleting the package files that index lists, so apt reads
the list, asks for a file and is given a 404. No date check catches that.

**Debian 10 sets the Python floor at 3.7**, which is why `pyproject.toml` says
`requires-python = ">=3.7"` and ruff `target-version = "py37"`. It had been
supported before, as a CI job called `GnuCash-34_Debian-10`, and was dropped
on 2026-03-12 for the mirror reason; the walrus operator and `typing.Protocol`
then went in over the following three months with no build left to catch them.

### ❌ Do NOT Support
- debian:9 and older — GnuCash **2.6.15** there, read from stretch's own
  package index on `archive.debian.org`. Debian 10's 3.4 is the floor: 2.x is
  the generation before the business-object and KVP APIs this tool is built
  on, so it is not a matter of a few missing calls.

## File Organization

### External Reference Files (NOT in git)
- `convert_qfx.py` - reference for QFX parsing requirements
- `ledger.py` - reference for update workflow requirements
- `reference_file*.txt` - sample data for understanding format
- `.claude/` - Claude CLI directory, an agent's own state — **except `.claude/settings.json`**, which is tracked (`.gitignore` says `.claude/*` and then `!.claude/settings.json`) because it is what wires the `PreToolUse` guards that refuse a shell file-edit, an unscoped kill, and "name" used as a verb for something that has no name. `tests/unit/test_the_kill_guard_allows_one_id.py` and `tests/unit/test_the_name_guard_leaves_real_names_alone.py` read it to check each is still wired, and `scripts/test-all-versions-parallel.sh` rsyncs that one file into all eleven containers so the assertions have something to read. Re-ignoring or deleting it turns those tests red.

### Repository Layout
- `cli/` - Click-based CLI commands; `cli/main.py` is the entry point
- `services/` - business logic (importer, exporter, matcher, validator, renderer, statement-reconciler, ...)
- `use_cases/` - orchestration that composes services for a single CLI command
- `infrastructure/` - I/O adapters: `gnucash/` (engine bindings + ctypes wrappers), `plaintext/`, `pdf/`, `qfx/`
- `repositories/` - thin GnuCash session and query layer
- `tests/` - `unit/` (services / use cases / infrastructure / repositories) and `integration/` (CLI end-to-end); `research/` holds long-running scenario probes
- `docs/` - design notes, issue tracker (`docs/issues/`), research probes, post-mortems
- `templates/` - report templates; an invoice or bill is drawn by GnuCash's own Printable Invoice and has none

## Testing Philosophy

### Use Real GnuCash Files in Docker
- ✅ Create temp GnuCash files in pytest fixtures
- ✅ Test with real GnuCash Transaction/Account objects
- ❌ No mocking of GnuCash types
- ✅ All tests run in Docker containers

### Test Coverage Requirements
- Domain/Services: 80%+
- Infrastructure: 60%+
- Use Cases: 60%+
- E2E: All scenarios

## Architecture Principles

### 1. Don't Duplicate GnuCash Types
- ✅ Use GnuCash's Account, Transaction, Split, Commodity directly
- ❌ Don't create parallel domain models
- ✅ Focus on what GnuCash doesn't have: formats, workflows, business logic

### 2. Business Logic in Services
- Extract matching, validation, categorization to services
- Services operate on GnuCash types
- Testable with temp GnuCash files

### 3. Thin Repository Layer
- Only session management and queries
- No business logic in repository

### 4. Format Adapters
- Each format (plaintext, QFX, beancount) has its own adapter
- Parsers convert format → GnuCash types
- Writers convert GnuCash types → format

## Common Mistakes to Avoid

1. **Adding reference files** - `convert_qfx.py`, `ledger.py`, `reference_file*.txt` are external; don't commit them
2. **Using `git add -A`** - Stage files explicitly so you don't sweep in untracked probes or secrets
3. **Working on main** - Always create a feature worktree + branch (see Feature Branch Workflow)
4. **Running pytest / python directly** - All tests must run via `./scripts/test.sh` in Docker so they hit a real GnuCash install
5. **Skipping lint before commit** - Run `./scripts/fix-lint.sh --unsafe` before staging, not after the pre-commit hook rejects you
6. **Editing a file from the shell** - `sed -i`, `perl -i`, a `python3 - <<EOF … write_text()` heredoc, `cat > file`: every one of these applies substitutions nobody reviewed, usually across several files in one call. Read the file, then Edit it; create one with Write. `scripts/refuse-bash-file-edits.sh` blocks the shell forms outright (wired in `.claude/settings.json`), and reading — `sed -n`, `grep`, `awk` to stdout — is untouched

7. **Writing "name" for something that has no name** - a guid is not a name and neither is a split, so "the message names the split" tells a reader something untrue and sends them looking for a name that is not there. What the message prints is a guid. Write what is actually there: a refusal **lists** the disposals, a report **prints** the split's guid, a block **gives** a guid, a payment **applies** a split, a guid **matches**. A real name is untouched — an account's, a customer's, `name:` in a block, `get_account_full_name`. `scripts/refuse-name-as-a-verb.sh` blocks the verb on Write and Edit, and it is a seatbelt rather than a sandbox: it catches the shapes that get typed, not every spelling. That script and `tests/unit/test_the_name_guard_leaves_real_names_alone.py` are exempt from it, because both quote the shape they refuse and could not otherwise be edited at all. This was in this file, agreed to, and broken again in the same session — twice in prose that had just been corrected for it — which is why it is a hook
8. **Killing anything you did not name** - this machine runs containers and processes that are not this project's. `docker ps -q | xargs docker kill` killed the author's web server, up since May, along with the ten test containers it meant. `scripts/refuse-unscoped-kills.sh` allows **one id, named, one per command** — `docker kill gnucash-dev-debian13`, `kill 1757608`, a signal being fine (`kill -9`, `kill -s TERM`, and `kill -0` to ask whether a pid is alive) — and refuses every other shape: `$( )`, `xargs`, `pkill`/`killall`, a negative pid (a process *group*), two ids, two kills in one command, `prune`, `compose down`, `docker-compose down`, and a kill inside a string handed to `bash -c` or `eval`. A kill is read at a command position — the start, after `|`, `;`, `&`, `(`, `)`, `{`, `&&`, `||` or a `find`'s `-exec`, and behind a path, a shell keyword (`do`, `then`, `while`, `if`, …) or one of the words that run another command (`sudo`, `doas`, `env`, `time`, `timeout`, `nice`, `ionice`, `stdbuf`, `nohup`, `setsid`, `xargs`, `exec`) with whatever arguments of their own they carry. So `for p in $(pgrep -f pytest); do kill $p; done` is the incident written longhand and is refused as such, as are `sudo -u jimmy kill -- -PID`, `case x in *) kill …`, `{ pkill …; }` and `find … -exec kill {} \;`. An environment assignment is a position too (`VAR=v pkill …`), as is a backquote. A program handed to a shell as a string is refused whole, with `-c` wherever the words before it put it (`bash -lc`, `bash -x -c`, `bash -o pipefail -c`). Docker's flags are read past, so `docker compose -f x.yml down` is refused like `docker compose down`. What that costs is reading: after a runner word, `sudo cat /tmp/kill` and `… | xargs grep -n kill` are refused as kills — drop the runner word, `grep -rn kill scripts/` passes. **It is a seatbelt, not a sandbox: the goal is not to close every loophole.** A quoted command word (`'pkill' -f x`) defeats any guard that reads text, and exotic spellings nobody types are answered by saying so rather than by another alternation — each one is a chance to refuse something real, which widening this has twice done (`docker image rm gnucash-dev:debian13`, `docker rm -f a b`). A shape it wrongly refuses is a defect; a shape nobody would type getting past it is not. Reading is allowed for the asking — `docker stop --help` and `docker kill -h` name nothing to kill and pass, since the reader looking one up is usually the one who just met a refusal — and every `"command"` field of the payload is judged, so a decoy can add a refusal and cannot hide one. A sweep rarely needs stopping at all: `scripts/test.sh` runs every container with `--rm`, so an abandoned one clears itself within minutes. Kill the detached `git commit` by its own pid and let its children finish

## Commit Messages Are Not Hard-Wrapped

One paragraph is one line, separated by blank lines. Breaking a paragraph at a column bakes the author's terminal width into the history: `git log`, every reader's terminal and every web view re-flow it, so a paragraph already broken at someone else's width reads as ragged half-lines everywhere. `scripts/hooks/commit-msg` refuses a wrapped message; lists, tables, quotes and fenced code are left alone, because their line breaks are the content.

Install both hooks with `./scripts/install-hooks.sh`.

## Useful Commands

### Check what's staged
```bash
git status
git diff --cached --name-only
```

### Verify branch
```bash
git branch --show-current  # main only when on worktree/main; a feature branch elsewhere
```

### Build and test
```bash
./scripts/build.sh
./scripts/shell.sh
./scripts/test.sh
```

## ctypes / GnuCash Bindings — Hard-Won Platform Findings

Discovered 2026-03-14 while fixing `test_business_objects_roundtrip` segfaults on Ubuntu 22/24.

### 1. Always set `argtypes` for every ctypes function that takes a pointer

Without `argtypes`, Python ctypes converts integer arguments to C `int` (32-bit). On x86_64, a 64-bit pointer like `0x7f1234567890` is silently truncated to `0x34567890` — a garbage address — causing a segfault inside the C function. This affects ALL platforms, so it is never optional.

```python
# WRONG — pointer silently truncated to 32-bit on x86_64
lib.gncTaxTableGetTables.restype = ctypes.c_void_p

# CORRECT
lib.gncTaxTableGetTables.restype  = ctypes.c_void_p
lib.gncTaxTableGetTables.argtypes = [ctypes.c_void_p]
```

### 2. Debian vs Ubuntu: RTLD_LOCAL causes library-instance mismatch

On **Debian**, the GnuCash Python extension loads `libgnc-engine.so` with `RTLD_GLOBAL`, so `ctypes.CDLL(None)` sees its symbols — calling functions from the *same* instance that created `QofBook*`. On **Ubuntu**, the extension uses `RTLD_LOCAL` (Python's default for extension modules), so `CDLL(None)` may resolve symbols from a *different* globally-visible copy, or not find them at all.

**Fix**: always promote the known `.so` path to `RTLD_GLOBAL` *before* calling `CDLL(None)`:

```python
ctypes.CDLL('/usr/lib/x86_64-linux-gnu/gnucash/libgnc-engine.so', mode=ctypes.RTLD_GLOBAL)
lib = ctypes.CDLL(None)   # now guaranteed to use the same instance
```

`dlopen` reuses the already-loaded mapping (same inode) and promotes it to global — no second copy is created.

### 3. Tax tables CANNOT be fetched via QOF Query

`q.search_for('gncTaxTable')` returns nothing. Tax tables are stored in a per-book hash table via `qof_book_get_data(book, "gncTaxTable")`, not in the QOF entity collection that queries iterate. The only correct API is `gncTaxTableGetTables(QofBook*)` via ctypes.

Do **not** try to replace this with `Query` — a previous session confirmed it returns zero results.

### 4. `weasyprint` apt package on Ubuntu does not expose `import weasyprint`

On Debian, `apt install weasyprint` installs `python3-weasyprint` and `import weasyprint` works. On Ubuntu 22/24, the same apt package only installs the CLI wrapper — `import weasyprint` raises `ModuleNotFoundError`.

**Fix**: install via pip (works on all distros):
```dockerfile
RUN python3 -m pip install weasyprint --break-system-packages ...
```

### 5. GnuCash Python Bindings: Practical Guidelines

#### No Decision Matrix, Only Testing
There is **no predictable decision matrix** for when to use SWIG vs ctypes. Platform-specific bugs and missing functions are discovered through testing, not predicted.

**Workflow**:
1. **Try SWIG first** - it's cleaner when it works
2. **Fall back to ctypes** when SWIG fails on some platform
3. **Document the failure** in code comments so others know why ctypes was chosen

#### Reading vs Writing Asymmetry
GnuCash Python bindings have different reliability for reading vs writing:

**Writing (Import) - SWIG Usually Works**:
- `Customer()`, `Vendor()`, `Invoice()` constructors work
- `SetName()`, `SetAddress()`, `SetCurrency()` work reliably
- **Exception**: Tax table entries need `gnucash_core_c` helpers

**Reading (Export) - Often Needs ctypes**:
- `gncTaxTableGetTables()`: Missing from SWIG (always ctypes)
- `gncEntryGetDescription()`, `gncEntryGetAction()`: SWIG has const-type bugs
- `xaccAccountGetName()`: Works in ctypes, SWIG version buggy on Ubuntu

#### Pointer Lifetime Rules
1. **Once ctypes, stay ctypes**: If you get a pointer from ctypes, use ctypes to read from it:
   ```python
   # ✅ CORRECT
   acct_ptr = lib.gncTaxTableEntryGetAccount(tte_ptr)  # ctypes
   name = safe_ctypes_string(lib, lib.xaccAccountGetName, acct_ptr)

   # ❌ WRONG - SWIG may not wrap raw pointers safely
   account = Account(instance=acct_ptr)  # Dangerous!
   ```

2. **SWIG ↔ ctypes bridge via `.instance`**:
   ```python
   # Safe: SWIG object → ctypes pointer
   entry_ptr = int(entry.instance)  # Get raw pointer from SWIG
   desc = lib.gncEntryGetDescription(entry_ptr)  # Use ctypes
   ```

#### Always Test All Platforms
Test on all supported distributions — the list and the version each carries is
the one under "Supported Distributions" above, which is read from the images
themselves:
- Debian 10 (GnuCash 3.4), 11 (4.4), 12 (4.13), 13 (5.10)
- Ubuntu 20.04 (GnuCash 3.8), 22.04 (4.8), 24.04 (5.5), 26.04 (5.14)
- Fedora 41 (5.13), Arch (5.15), openSUSE Tumbleweed (5.16)

**Common pattern**: Works on Debian, segfaults on Ubuntu → RTLD_LOCAL issue.

#### Use `engine.py` Utilities
- `load_gnc_engine()`: Handles RTLD_GLOBAL promotion and argtypes
- `iterate_glist()`: Safe GList traversal (replaces raw pointer arithmetic)
- `safe_ctypes_string()`: Null-safe string decoding
- `verify_ctypes_functions()`: Runtime validation of required functions

## GnuCash Business Object Quirks — Hard-Won Findings

Discovered 2026-04-02 while adding bill state tests.

### 6. Bill Entry API vs Invoice Entry API

GnuCash has **separate setter/getter functions** for invoice-side and
bill-side entry fields. Using the wrong side produces silent data corruption:

| Invoice side | Bill side |
|---|---|
| `entry.SetInvAccount(acct)` | `entry.SetBillAccount(acct)` |
| `entry.SetInvPrice(price)` | `entry.SetBillPrice(price)` |
| `entry.SetInvTaxable(bool)` | `entry.SetBillTaxable(bool)` |
| `entry.SetInvTaxTable(tt)` | `entry.SetBillTaxTable(tt)` |
| `gncEntryGetInvPrice(ptr)` | `gncEntryGetBillPrice(ptr)` |
| `gncEntryGetInvTaxable(ptr)` | `gncEntryGetBillTaxable(ptr)` |

Symptom of using the wrong side: AP posting split has amount $0, and
payments land in a new lot instead of the bill's posted lot.

### 7. Bill payment amount must be negated before calling `ApplyPayment`

**Accounting reasoning** (why, not just what):

Double-entry accounting has opposite sign conventions for AR (asset) and AP
(liability) accounts:

| Event | Invoice (AR) | Bill (AP) |
|---|---|---|
| Posting | DR AR +N (asset up) | CR AP −N (liability up) |
| Payment | CR AR −N (asset down) | DR AP +N (liability down) |
| Bank | DR Bank +N (receive) | CR Bank −N (send) |

GnuCash lots close when splits sum to zero. The posting split and the payment
split must have opposite signs:

- Invoice lot: posting = +N, payment AR split = −N → sum = 0 ✓
- Bill lot: posting = −N, payment AP split = +N → sum = 0 ✓

`ApplyPayment(amount=+N)` produces bank = +N, AP/AR = −N — correct for
invoices (receive money, reduce receivable) but **wrong for bills** (should
send money, reduce payable). Passing −N flips both splits:

```python
# amount_str is the text from the fixture, e.g. "200"
neg_amount = string_to_gnc_numeric_quantity(f'-{amount_str}')
bill.ApplyPayment(None, bank_account, neg_amount, ...)
# → AP split = +N  (debit AP, reduces liability, same lot as posting)
# → Bank split = −N (credit bank, money sent out)
```

Symptom of using positive amount: payment AP split = −N (same sign as
posting), so GnuCash puts it in a **new lot** instead of the bill's lot.
`inv.GetPostedLot().get_split_list()` then returns only 1 split (the posting)
and the exporter emits `payment: none` for a paid bill.

### 8. Vendor bills MUST be wrapped/constructed as the `Bill` class, not `Invoice`

GnuCash stores customer invoices and vendor bills in one `gncInvoice` QOF type
(distinguished by owner). The Python bindings expose **two** classes:
`Invoice`, and `Bill(Invoice)` — a real subclass (`Bill.add_methods_with_prefix('gncBill')`).
The only methods `Bill` overrides are `AddEntry` → `gncBillAddEntry` and
`RemoveEntry` → `gncBillRemoveEntry`; everything else is inherited, so a `Bill`
is a strict, safe superset of `Invoice` for a vendor bill.

A `GncEntry` carries two owner pointers, and GnuCash's entry XML writer
serialises the bill-side tax flags only inside `if (gncEntryGetBill(entry))`:

- entry added via `Invoice.AddEntry` (`gncInvoiceAddEntry`) sets the entry's
  *invoice* pointer → the file gets `<entry:invoice>` + `i-taxincluded`, and
  **omits** `entry:b-taxable` / `entry:b-taxincluded`. On reload those default
  (`b-taxable`→true, `b-taxincluded`→false), so `taxable: false` flips to `true`
  and `tax_included: true` is lost (the bill is over-taxed).
- entry added via `Bill.AddEntry` (`gncBillAddEntry`) sets the *bill* pointer →
  `<entry:bill>` + `b-taxable` / `b-taxincluded`, round-tripping as authored.

**The fix is the Python class, not ctypes.** Construct new bills with
`Bill(book, id, currency, vendor)` and wrap every `gncInvoice` query result with
`wrap_invoice_or_bill(raw)` (`infrastructure/gnucash/utils.py`), which returns a
`Bill` for a vendor owner (`GetOwnerType() == GNC_OWNER_VENDOR`) and an `Invoice`
otherwise. Then `bill.AddEntry` / `bill.RemoveEntry` dispatch correctly and no
ctypes helper is needed. A vendor bill wrapped as `Invoice` and mutated via
`Invoice.RemoveEntry` was also the real cause of the GnuCash-3.8 rebuild
segfault (wrong function → dangling entry pointers); `Bill.RemoveEntry` avoids
it — verified on Ubuntu 20.04 (GnuCash 3.8).

**Impact on round-trip tests**: bill export reflects the source `taxable:` /
`tax_included:` values verbatim (e.g. `taxable: false` stays `false`). This
supersedes the earlier belief that GnuCash could not persist
`bill_taxable = false`; the real cause was handling bills with the
customer-invoice class.

**A book already holding such a line is repaired on import**, and the repair
is not `AddEntry`. Editing an invoice rebuilt every line until Q-038, so a
pointer-less entry was healed by accident on the first re-import; lines are
edited in place now and `AddEntry` is called only for a line being created,
so nothing heals it. Such a bill compares unequal against its own exported
ledger on every run — `updated` for ever while unposted, refused with
"unpost-bills first" once posted, and that unpost does not fix the pointer
either. Measured on 5.10, in `tests/research/a_legacy_bills_entry_owner_probe.py`:

| call | result |
|---|---|
| `gncBillAddEntry` on a pointer-less entry | returns early only when the pointer already names this bill, so it sets the pointer **and** adds a second reference to the bill's list |
| `gncEntrySetBill` alone | pointer set, list untouched — but the entry still carries its **invoice** pointer, the writer emits a reference per pointer, and the reloaded bill lists the one entry **twice** |
| `gncEntrySetBill` + `gncEntrySetInvoice(entry, NULL)` | one entry, and the `b-taxable` / `b-taxincluded` written beside it survive the save |

SWIG has no `Entry.SetBill` or `Entry.SetInvoice` on any supported build, so
both are ctypes, declared in `infrastructure/gnucash/engine.py`.
`_give_the_line_its_bill_pointer` does it inside the entry's own
`BeginEdit`/`CommitEdit`, which is what finally carries the flags to disk
(finding 11).

### 9. `xaccSplitSetLot` does not put the split in the lot's split list

Discovered 2026-08-05 while opening a cost basis for the credit a retargeted
overpayment leaves.

Two functions put a split in a lot and they are not equivalent:

| call | sets `split->lot` | appends to the lot's split list |
|---|---|---|
| `xaccSplitSetLot(split, lot)` | yes | **no** |
| `gnc_lot_add_split(lot, split)` | yes | yes |

After `xaccSplitSetLot`, `split.GetLot()` returns the lot — so anything asking
the *split* sees it — while `gnc_lot_get_split_list(lot)` does not include it,
and `gnc_lot_get_balance(lot)` therefore does not count it. The list is
reconstructed from the account's splits when the book is written and read
back, so the two views agree again after a save/reload and the discrepancy is
invisible to any test that reopens the file.

Measured: a 200.00 USD payment retargeted onto a 100.00 USD invoice, where the
settling split is attached with `xaccSplitSetLot`. Immediately afterwards the
invoice's lot listed one split, the posting's, though the settling split's own
`GetLot()` was the invoice lot.

**Consequence**: any logic that finds splits by walking a lot — "which
transaction joined this lot?", "what does this lot hold now?" — silently sees
nothing for a split attached this way, in the same session that attached it.
`_record_overpaid_basis` did exactly that and opened no cost basis at all for a
retargeted overpayment's residue, so the book offered 100.00 USD while its bank
held 200.00 and selling the rest was refused. The fix is to write to the split
the code already has rather than to search a lot for it; where a search is
unavoidable, walk the *account's* splits and filter by `split.GetLot()`.

### 10. Unposting leaves the lot behind, indistinguishable from a credit lot

Discovered 2026-08-06 while working out which splits a `txn_guid:` retarget may
move.

`gncInvoiceUnpost` detaches the invoice from its lot, but does **not** destroy
the lot or empty it. The lot stays on the account, still listed by
`xaccAccountGetLotList`, still holding whatever splits settled the invoice, and
`gncOwnerGetOwnerFromLot` still names the owner — because unposting re-attaches
the owner to it.

Measured on GnuCash 5.10: after `record.Unpost(False)` on a paid invoice, the
settling split's `GetLot()` returns the same lot as before, that pointer is
still in the account's lot list, `gncInvoiceGetInvoiceFromLot` returns NULL, and
the owner reads back as the invoice's customer.

**Consequence**: a lot abandoned by an unpost and an owner's parked prepayment
lot are the same thing as far as the book is concerned — live, naming nothing,
owner-attached. No property of either tells them apart, so code that must
distinguish them has to *record* the unpost rather than interrogate the lot
afterwards.

The record has to be **durable**, not in-process. The book is saved with the
orphan still in the abandoned lot, so the import that meets it may be days
later in another process — and the standalone `unpost-invoices` /
`unpost-bills` commands reach the state in one step with no import around them
at all. `services/gnucash_importer.py` writes `orphaned_by_unpost` on each
orphaned split, valued with the guid of the invoice that was unposted, from
`mark_splits_orphaned_by_unpost()`; both the importer's rebuild path and
`use_cases/unpost_business_objects.py` call it immediately before
`Unpost(False)`, while the lot still names the invoice.

Valued with a guid rather than `true` because a rebuild has to find the split
that was settling *it*: one transaction can carry orphans from two records,
and "which of these was mine" is then answerable without the file saying so.

The key never leaves the book, and never enters one from a file. It is filtered
out of plaintext export beside `lot_owner`, cleared in `_attach_split_to_lot` —
which every path this tool takes to put a split in a lot goes through — and a
file stating it is refused by `refuse_a_stated_orphan_mark`, on the create and
the update arm both, before either touches the book.

The engine's own attach needs its own clearing. Applying a credit, GnuCash
reduces the source split and carves the rest into a new one, and the two halves
come out differently — measured on GnuCash 5.10, 4.13, 4.4, 3.8 and 5.15:

| half | slot frame |
|---|---|
| applied part (keeps the source split's guid) | the source's slots, **mark included** |
| carved remainder (a new split) | empty — no mark, no cost basis |

So the applied part is where the key survives into a state that no longer
matches it: it is another invoice's settlement now, not the first invoice's
orphan. `_mark_applied_from_credit` drops it alongside the cost basis keys. Nothing
is stripped from the remainder, because nothing arrives on it.

All three matter, and the import half is the sharpest. A split carrying the key
reads as *not* an owner's credit, so a settlement genuinely spent from a credit
would skip taking the cost basis off; and because a mark giving an invoice's guid is
*preferred* over everything else placeable — which is how a rebuild finds its
own orphan — a file stating one could choose which of an owner's two credits an
invoice spends, past the guard that exists to stop split order deciding that.
On a foreign book those carry different costs, so it would pick the gain too.

What turns on the difference: moving a split out of a credit lot spends the
owner's money and must take the cost basis off it; moving one out of an
abandoned lot is the rebuild putting back what it just detached, and stripping
a cost basis there would lose currency the book still holds — the book then offering
less than its bank has, and the export writing that bank payment as
`from_credit:` with no account and no date.

**What makes an orphan credit is how it was paid, not whose it is.** The mark
names an invoice so a rebuild can find the settlement that was its own, but
whether the money is anybody's *credit* is a separate question, and the split
answers it: a settlement that came out of credit carries `applied_from_credit`,
and that survives the unpost.

- marked, and came from credit → credit still, loose again and spendable by
  anyone the owner owes;
- marked, and never came from credit → a bank paid it, and it is a settlement
  waiting to be put back, whichever invoice's unpost loosened it;
- unmarked, in a live owner lot naming nothing → an ordinary parked credit.

Reading the mark as "not credit to this invoice, credit to everyone else"
looks right and is not: `unpost-invoices B` then a file settling A off B's
deposit is one step, and it strips the cost basis off currency the bank still holds
while exporting a block that named an account and a date as `from_credit:`
carrying neither.

All three consumers ask the same question of the same split, and the guid is
consulted by none of them — only `_retarget_choices` uses it, to find the
settlement a rebuild is entitled to:

| where | what it does with a bank-paid orphan |
|---|---|
| `_sits_in_an_owners_credit` (`txn_guid:`, `txn_split_guid:`) | not a credit — no cost basis strip, no `applied_from_credit` |
| `_apply_credit_payment_directive` (`from_credit:`) | refused; the file is asserting what the book contradicts |
| `_mark_applied_from_credit` (`auto_apply_credit:`) | left unmarked; the engine may take it, but it is not written down as credit |

Scoping any one of them to the record reopens the hole in that spelling alone,
which is how the three came to disagree in the first place.

**Nothing in a file represents the mark**, so it cannot travel: a file may not
state it (that would let a file steer which credit an invoice spends), and the
export filters it out. What must not travel either is `lot_owner:` on such a
split — that line is a file saying "this is an owner's credit, put it in a lot
of theirs", and restoring an export into a fresh book then rebuilt a bank's
payment as spendable credit. So the export omits it for a bank-paid orphan, and
the split comes back loose: in no lot, nobody's credit invented. That is what
it is, the invoice it settled being unposted.

**Books unposted by an earlier version carry no mark**, and there is no way to
add one after the fact: an abandoned lot and a parked credit are the same three
facts, which is the whole finding. Such an orphan therefore reads as a credit.
Measured what that costs: the settlement split carries no cost basis of its own
— the cost basis sits on the invoice's posting split — so nothing is stripped and
`fx-balances` still matches the bank. What changes is the label: the export
writes the bank payment as `from_credit:` with no account and no date.
Unposting the invoice again under this version writes the mark and restores
the right answer.

Every path that can consume such a lot honours it, not just the one that reads
it most obviously:

- the bare `txn_guid:` retarget, via `_sits_in_an_owners_credit`;
- `txn_split_guid:`, which names the split outright — a guid says *which*
  split, not where the money came from, so one landing on a parked credit
  spends it like any other. This is also the route the ambiguity refusal sends
  readers down by name, so a transaction carrying two of an owner's credits is
  meant to be settled through it;
- `auto_apply_credit: true`, via `_mark_applied_from_credit` — and this one
  matters most, because the *engine* chooses. `AutoApplyPayments` searches for
  open, owner-attached lots naming nothing, which is what the rebuild's own
  unpost left a moment earlier, so a re-imported invoice with no payment block
  is handed its own settlement back. Measured on GnuCash 5.10: without the
  check it exports as `from_credit: true` + `credit_dated:`, with no
  `bank_account:` and no date — the money's origin gone, with nothing in the
  file having asked for a credit at all.

### 11. A KVP written outside `BeginEdit`/`CommitEdit` never reaches disk

Discovered 2026-08-08 while covering the re-import comparisons.

`set_custom_metadata` writes through `qof_instance` and marks the instance dirty, and that is enough for an object being created — the backend serialises a new object whole. It is not enough for one the book already had:

```python
customer.SetName(...)        # inside BeginEdit/CommitEdit — persists
customer.CommitEdit()
set_custom_metadata(customer, {'department': 'east'})   # outside — lost on save
```

Measured on GnuCash 5.10: the slot reads back as `{"department": "east"}` for the rest of the session and as its **previous** value after a save and reload. Wrapping the write in `customer.BeginEdit()` / `customer.CommitEdit()` persists it.

What that cost: every change to a custom key on an object the book already held — a changed value, a removed key — was dropped in silence. And because the stored slot never changed, the object stayed different from the file for good, so each re-import compared unequal, reported `updated`, and saved the book again. An unchanged ledger imported twice wrote the book twice.

The same rule applies to every business object, not just customers: `import_customer`, `import_vendor`, `import_invoice` and `import_bill` all bracket the write now.

**Corollary for `set_custom_metadata(obj, {})`**: an empty dict is how the slot is emptied. That is not the same as "write it whenever the file names none", which was tried and is worse: the slot is written from a *block*, most blocks are partial — a person names what they are changing, a printed page carries less than that — and replacing the slot wholesale made every one of them a delete.

So the slot is merged rather than replaced, and follows the rule the address lines follow:

- a key the block does not name says nothing about it;
- a key named empty (`department: ""`) is removed;
- a key that has since become a field of its own (`addr1` on a vendor, once vendors gained address setters) is dropped from the slot on the next import, and filtered out of every writer — emitted from both the slot and the field, the line appeared twice and the stale copy came second, which is the one a re-import keeps.

**The rule is in README under "What a key says, and what leaving it out says"** — that is where the format is defined, and the code follows it: `key: "value"` sets, `key: ""` clears (and removes a custom key), an absent line says nothing. It holds for reserved fields and custom metadata alike, on every block, in both the writer and the comparison that decides `unchanged`.

**The general rule this is one case of**: on the import side, an absent key is not an instruction. `if 'notes' in metadata` is the shape — the transaction and split paths have always used it — and `md.get('notes', '')` is the shape that erases. Whatever the comparison that decides `unchanged` reads, the writer must write, and neither may read a field the block did not name.

### 12. A split with no account: GnuCash 5.x drops the transaction, 4.x segfaults on load

Discovered 2026-08-09 while measuring the coverage union.

A split whose `<split:account>` element is missing is not a book this tool can write, but it is a book it can be handed. What happens then is GnuCash's answer, not ours, and it is not the same answer on every supported version. Measured on a book saved by this tool and then edited to remove one `<split:account>`:

| GnuCash | what `qof_session_load` does |
|---|---|
| 5.5, 5.10, 5.13, 5.14, 5.15, 5.16 | drops the whole transaction; the book that comes back is short an entry and every split in it has an account |
| 4.13, 4.8, 4.4, 3.8 | **segfault**, inside `qof_session_load`, before any of this tool's code is given control |

**What it settles**: a split with no account cannot reach a command on any supported version, so a null-account check in the reading path is dead code on all ten. `cli/find_transactions_cmd.py` carried one in its ctypes walk and it is gone, on this evidence rather than on the 5.x half alone.

**What it costs**: nothing this tool does can prevent the 4.x crash — it happens while the file is being parsed, several frames below `GnuCashRepository.open`. There is no `try` that catches it and no state to check first.

**And a rule for the suite**: a test may not feed the loader a corrupt book. A segfault does not fail a test, it kills the interpreter, taking the other 2025 tests in that run with it and leaving `./scripts/coverage.sh` unable to report a union at all — which is how this was found. The measurement lives here and in the module docstring of `tests/integration/test_finding_a_transaction_by_its_amount.py`, and is asserted nowhere. Version-gating it with `skipif` was the alternative and was refused: the suite has no version-gated test in it, deliberately — the union model is that every version runs everything — and the first one would be guarding GnuCash's own loader rather than any behaviour of this tool.

### 13. An invoice has no `GetGUID`, and `Invoice` is not on the `gnucash` package

Discovered 2026-08-11 while comparing the invoice a payment already settles against the one being paid.

Finding 5 above says SWIG `Invoice.GetGUID()` is "missing on some platforms". It is missing on **all** of them. Probed on every supported build — 3.8, 4.4, 4.8, 4.13, 5.5, 5.10, 5.13, 5.14, 5.15, 5.16:

| asked of the bindings | answer, on all ten |
|---|---|
| `hasattr(gnucash, 'Invoice')` | `False` — the class lives in `gnucash.gnucash_business`, not on the package |
| `hasattr(Invoice, 'GetGUID')` | `False` |
| `hasattr(Bill, 'GetGUID')` | `False` |
| `hasattr(Invoice, 'GetOwnerType')` | `True` |
| `gnucash_core_c.gncInvoiceGetInvoiceFromLot` | present |

`Customer` and `Vendor` *do* carry `GetGUID` — `gnucash_importer.py` reads both that way and the suite passes on all ten — so the absence is a property of the invoice classes, not of the bindings in general. `add_methods_with_prefix('gncInvoice')` picks up what the C header names `gncInvoice*`, and the guid accessor is not one of those.

**So an invoice's identity is read through ctypes, and `_swig_invoice_guid_str(record)` is the one way to do it**: `qof_instance_get_guid` + `guid_to_string_buff`, off `record.instance`. It takes anything with an `.instance`, including the raw pointer out of `gncInvoiceGetInvoiceFromLot` once `wrap_invoice_or_bill` has wrapped it.

The failure this hides is quiet, because the two obvious spellings fail differently. `Invoice(instance=raw).GetGUID()` raises `AttributeError`, and a `try`/`except` around it — which is how these lookups are usually written here — swallows that into "no answer", so the comparison silently says *not the same invoice* for every invoice. `from gnucash import Invoice` raises `ImportError` inside the same `try` and reads the same way.

### 14. Render every invoice before opening any destination

Not a GnuCash finding — a rule this repo learned twice, once per command family.

Formatting can refuse. A split holding a figure finer than its currency cannot be written as plaintext, and a printed `payment:` block states its amount at the unit its account is kept to and refuses the same figures the export refuses. So the write step can raise partway through, and where the file was already open, or the earlier invoices and bills already on disk, what is left behind is a partial answer that reads as a whole one:

- `export` opened the target, then rendered — so an export that refused had already truncated yesterday's ledger, leaving a 0-byte file where a good one had been;
- `print-invoice`/`print-bill` with `-o out/` wrote each invoice inside the loop — so a refusal left the invoices and bills before the offender in the directory and the ones after it missing, with nothing saying which.

Both now build the complete output first and touch the destination only once it exists in full; the per-invoice form makes the directory only when there is something to put in it. `_write_combined` was always right, because it concatenates into a list before writing — which is why the combined form never showed the defect and the per-invoice form did.

### 15. Dates: two settings decide them, and one is a process global the GUI fills in

Discovered 2026-08-15, from a user printing with a report of their own.

A date on a printed page comes from one of two places, and which one depends on *which* date it is:

| date | written by | reads |
|---|---|---|
| the invoice's posted date and due date | `gnc-print-time64 date (gnc:options-fancy-date book)` | a **book option** — `("Business" ("Fancy Date Format" "custom"))`, via `gnc:fancy-date-info` |
| every entry's date, every payment's date, "printed on" | `qof-print-date` | a **process global**, `qof_date_format_get()` |

**The process global is the trap.** GnuCash's GUI sets it at startup from its GSettings preference. A process that only loaded the library sets nothing, so it holds its compiled default `QOF_DATE_FORMAT_LOCALE` (`4`) and those dates follow the *locale of whoever ran the command*. Measured on 5.10, 4.13 and 3.8: it reads `4` in this tool's process no matter what the GnuCash preference says, and setting that preference — through GSettings' keyfile backend, since the images have neither dconf nor a session bus — changes nothing on the page. **`Edit → Preferences → Date/Time` does not reach anything this project prints.**

Consequences worth knowing before touching any printed date:

- setting only the book option gives a page with **two date formats on it** — measured, `09 March 2026` at the top and `03/09/26` in the entry rows;
- setting *neither* is uniform, because both halves then fall back to the same locale — so adding the book option is what introduces the split, and `services/gnucash_report.py` sets the global from the same key to close it;
- `qof_date_format_set` takes **a style, not a format string**: `US=0, UK=1, CE=2, ISO=3` from `gnc-date.h`, whose own comment says it "checks to make sure it's a legal value". `QOF_DATE_FORMAT_CUSTOM` is the check printer's and there is no public setter for a custom string, so a format like `%d %B %Y` cannot reach the entry rows at all — the run warns rather than pretending;
- it is a **global**, so anything that sets it must put it back. One command printing one book must not leave the next book, or the next test in the same pytest process, reading the first book's format.

### 16. A book's address is one string; an owner's is four fields

Discovered 2026-08-15, from a user asking why a company address was being split at all.

The two look alike in the format and are different objects in GnuCash:

| whose | how GnuCash stores it | how long it may be |
|---|---|---|
| the book's own (File → Properties → Business) | **one** option, `Business` → `Company Address`, a single string with `\n` in it | as long as it is — the dialog is a free-text box |
| a customer's or a vendor's | a `GncAddress` — four separate fields, `SetAddr1`..`SetAddr4` | exactly four, and there is no fifth to set |

Measured on 5.10, from a book this tool wrote:

```
book option Business/'Company Address':
    '42 Example Street\nUnit 5\nSpringfield ON\nA1A 1A1'
book option Business/'Company Address 1':  None      ← no such option
customer C-ADDR address fields:
    ['1 Customer Way', 'Suite 9', '', '']
```

and in the saved XML the book's is one slot whose value spans lines.

**What that cost.** The `company` block wrote four numbered keys and the export split the slot into four, so a six-line address — a unit number, a country, an "attention" line, which is not an unusual address — exported as four lines with the rest silently gone. The export is the whole ledger, so a book rebuilt from one had a shorter address than the book it came from, with nothing said. The four-line cap was right for the owner blocks and wrong for the book's, because it was copied from the object that has four fields to the one that has none.

**And a second, from the same confusion**: the company path rewrote the whole slot from whatever keys the block named, so a block correcting the street deleted the postcode. The owner path never did — it writes `if key in md` — and the rule (an absent key is not an instruction, finding 11) applies to both.

`services/plaintext_addresses.py` holds the parsing and the limit now, so there is one answer to "which line is this key" and one place that knows a `GncAddress` has four of them.

### 17. `Account.GetLotList()` hands back two different things, and the version decides which

Discovered 2026-08-20 while giving a credit lot an identity.

The same call yields a raw `SwigPyObject` pointer on some builds and a wrapped `GncLot` on others. Measured on all ten, from a book holding one credit lot:

| GnuCash | `type(acct.GetLotList()[0]).__name__` |
|---|---|
| 3.8, 4.4, 4.8, 4.13, 5.5, 5.10, 5.13, 5.14 | `SwigPyObject` |
| 5.15, 5.16 | `GncLot` |

It is a version boundary — 5.14 raw, 5.15 wrapped — not a distribution's doing, and `int()` refuses the wrapper outright (`TypeError: int() argument must be … not 'GncLot'`). So a reader written against either half raises on the other, and a suite run on Debian says nothing about it: eight of the ten agree with each other.

`infrastructure/gnucash/utils.py` answers it once, in the two shapes callers need — `qof_instance(obj)` for a SWIG call, `qof_pointer(obj)` for ctypes — and every reader asks. The three words were written out at fifteen call sites before that, each free to get it wrong on its own, and one of the comments beside them recorded the version split backwards. The ctypes route is unaffected either way: `xaccAccountGetLotList` through `iterate_glist` hands back plain integers on every build, and that is what the importer's lot search and the export use.

### 18. Forcing a guid marks nothing dirty, so a run that only forces one saves nothing

Discovered 2026-08-20, from a lot that kept its old guid across a save.

`qof_instance_set_guid` moves the entity in its collection and changes the instance, and that is all: it does not mark the instance dirty, and nothing marks the book dirty either. `qof_session_save` then writes **nothing** — not the object, not the file — while the new guid reads back for the rest of the session, so the run looks as though it worked.

Measured on 5.10, in one book: a lot given a guid inside `gnc_lot_begin_edit` / `gnc_lot_commit_edit` and nothing else came back from a save and a reload with its **original** guid; the same guid, in a session where something else had written to the book, came back as the forced one — the XML backend rewrites the whole file, so the change goes out with everything else.

The bracket is not what makes it persist, which is the trap: a real write somewhere in the session is. `_force_the_lot_guid` is safe because it only ever names a lot the import has just created and is about to put a split in. A command that meant to *rename* something and did nothing else would report success and change nothing on disk.

This is finding 11 one level up — there the object was not serialised, here the file is not written at all.

### 19. GnuCash 4.x and below re-value a foreign credit at par when the engine applies it

Discovered 2026-09-03 while covering a credit an unpost hands back.

`AutoApplyPayments` does not leave a foreign-currency credit alone on 4.x or 3.8. Applying it to an invoice rewrites the credit split's **value** to equal its amount — as though the currency were the book's own — and adds a split to cover what that no longer balances.

Measured on the same book, built the same way, one build at a time. A 200.00 USD overpayment arrives from a CAD bank for 274.00 CAD and this tool carves it into a 100.00 settlement and a 100.00 credit, each valued at 137.00 CAD. **Every build agrees up to that point** — the carve this tool does itself is the same everywhere. A second invoice then takes the whole credit with `auto_apply_credit: true`:

| GnuCash | the overpayment's splits afterwards |
|---|---|
| 5.5, 5.10, 5.15 | unchanged — Bank +274.00 CAD, A/R −100.00 USD (−137.00), A/R −100.00 USD (−137.00) |
| 3.8, 4.4, 4.13 | the credit's value becomes **−100.00**, and a fourth split appears: A/R −37.00 USD (−37.00) |

That is a 4.x/5.x boundary, the second this suite has measured, and it falls between 4.13 and 5.5. The probe is `tests/research/where_the_credit_loses_its_value_probe.py`, which dumps the transaction after each step, so the remaining builds can be read off in one run each.

274 − 137 − 100 − 37 = 0, so the transaction balances and nothing reports it. What it costs is the customer's credit: 137.00 CAD of value recorded as 100.00, and 37.00 USD on the receivable that no money brought in.

**Why it is not caught by a figure.** `cost_of` then reads that credit at 1 CAD/USD, honestly — value over amount is what a cost is. A cost of 1 is a legitimate figure, at parity or from an amount small enough to round there, so no check can refuse a 1 without refusing real books. Nothing distinguishes this from a correct par-valued credit.

**What follows for the suite**: a test that needs a foreign credit spent in full gives it by guid, with `txn_guid:` and `txn_split_guid:` on a `from_credit:` payment block, so this tool carves it. `tests/fixtures/fx_invoice_spending_a_cad_paid_credit_whole.txt` says so where it is written. `auto_apply_credit: true` reaches the same state on every build from 4.4 up, and a different book on 3.8.

### 20. A date given as epoch seconds lands in the wrong millennium on 3.4

Discovered 2026-09-05, restoring Debian 10.

GnuCash's date setters take a `time64` from version 4 on. On 3.4 the same
call, given the same integer, stores something else entirely — and stores it
without complaint:

| call | 3.4 | 5.10 |
|---|---|---|
| `Transaction.SetDatePostedSecs(1776211200)` | **4753-05-01** | 2026-04-15 |
| `gncInvoiceSetDatePosted(inst, 1767571200)` | **5373-05-01** | 2026-01-05 |
| `Invoice.SetDatePosted(datetime(2026, 1, 5))` | 2026-01-05 | 2026-01-05 |
| `Transaction.SetDateDue(datetime)` | correct | correct |

**So a date is set by passing a `datetime` to the wrapper class**, never by
passing seconds to `gnucash_core_c`. The wrapper's typemap does the conversion
the build wants; the raw call does not.

What it cost: a posted invoice round-tripped its `date:` and `due:` as
5373-05-01 and 6710-05-01, and two test fixtures built books whose
transactions were filed under 4753 — where the fuzzy matcher indexes by
`(date, amount)`, so every lookup missed and every match came back `NEW` with
no candidate at all.

The version-guard those fixtures used, `gnucash.GncDateTime(...) if
hasattr(gnucash, 'GncDateTime') else int(d.strftime('%s'))`, never took its
first arm: `GncDateTime` is absent from the `gnucash` package on **both** 3.4
and 5.10, so the seconds path always ran. Probes:
`tests/research/what_a_posted_date_reads_back_as_probe.py` and
`what_an_invoice_date_setter_takes_probe.py`.

### 21. `qof_book_set_string_option` takes a path from 4.x and a slot name on 3.4

Discovered 2026-09-05.

The same function reads its `opt_name` argument two ways. Writing
`options/Business/Company Name`:

| GnuCash | what it stores |
|---|---|
| 4.x, 5.x | the nested frames `options` → `Business` → `Company Name` |
| 3.4 | **nothing at all** — the saved book holds no slots whatever |

So on 3.4 every company field — name, address, tax numbers, the date format,
the invoice footer and CSS — was not written, and read back empty. Silently:
the call returns void and reports nothing.

**Its getter is not the same.** `qof_book_get_string_option` resolves the
nested path on 3.4 as it does everywhere — measured against a slot written
only by `qof_instance_set_kvp` — so the read side needs no fallback and the
write side can tell whether the engine call landed simply by asking for the
value back. Only the setter is two-faced, and only when the name has a slash
in it: given a bare `Company Name` the same call stores and reads back fine on
3.4, as one top-level slot.

`services/gnucash_report.py` and the company blocks are unaffected on 4.x and
5.x, because `write_book_string_option` still calls it there **first**. That
matters beyond the storage: from 4.x on the call also refreshes the book's
live option database, which is what GnuCash's own report engine reads in the
same process. Writing the slot directly instead — which was tried — leaves the
file right and the running report showing the *old* date format.

The fallback is `qof_instance_set_kvp` over the path segments, reached only
when reading the value back shows the engine call did not land. Two things it
must get right, both learned the hard way:

- **`options`, the section, and every slash-separated part of the name.** The
  date format's name is `Fancy Date Format/custom`, so its path is four deep,
  not three — passed as one segment it becomes a slot whose key contains a
  slash, which nothing reads.
- **`qof_book_mark_session_dirty`, not just `qof_instance_set_dirty`.** With
  only the instance marked, `qof_session_save` writes nothing: the value reads
  back for the rest of the session and is gone after a reload. That is finding
  18 one object along.

**And clearing goes through it too.** Writing an option empty is how the
engine removes it, and `services/invoice_style.py` keeps a prefix on its text
precisely so "set to nothing" stays distinguishable from "never set". On 3.4
the engine call does nothing for a slashed name, so a clear reaches the
fallback — which unsets its `GValue` rather than setting it to `""`, so the
slot is removed. Otherwise a book written on Debian 10 would be the only one
carrying empty slots.

**Whatever fetches a `GValue` must `g_value_init(…, G_TYPE_STRING)` first.**
An absent slot otherwise leaves the value holding nothing, and
`g_value_get_string` then writes `assertion 'G_VALUE_HOLDS_STRING (value)'
failed` to stderr — one line per call, no exception — which lands in whatever
output the caller was reading. That is how it was found: a test asserting on
stderr, on 4.4, where the fallback runs only for an option that is genuinely
absent.

Probes: `what_path_a_book_option_wants_probe.py`,
`what_3_4_stores_for_a_book_option_probe.py`,
`whether_a_kvp_path_can_be_three_deep_probe.py`,
`whether_kvp_writes_a_book_option_the_same_probe.py`,
`whether_the_option_getter_walks_a_path_probe.py`.

### 22. Half-up rounding loses the sign of a negative exact half on 3.4

Discovered 2026-09-05.

| GnuCash | `GncNumeric(-5, 1000).convert(100, GNC_HOW_RND_ROUND_HALF_UP)` | `(+5, 1000)` |
|---|---|---|
| 3.4 | **+1/100** | +1/100 |
| 5.10 | −1/100 | +1/100 |

The magnitude is right and the sign is dropped. A closing entry of two
half-cents came out with every sign inverted on Debian 10 — the expense
accounts credited where they should be debited — and it *balanced*, so nothing
else in the book reported it.

`to_money` rounds `abs(value)` and puts the sign back. Half-up is symmetric
about zero, so that is the same answer on every build rather than a
workaround, and it is on the path of every money figure this tool writes.

### 23. WeasyPrint must be imported before GnuCash on Debian 10

Discovered 2026-09-05.

WeasyPrint draws through `cairocffi`, which opens its own libcairo and makes a
surface while being imported. GnuCash's bindings have already opened libcairo
through GTK. Measured on Debian 10, one process each way:

```
import gnucash; import weasyprint   ->  Segmentation fault
import weasyprint; import gnucash   ->  fine
```

Not an exception — SIGSEGV, which no Python frame can catch, and which under
pytest ends the run rather than failing a test (finding 12's hazard, from a
library rather than a book).

`infrastructure/pdf/cairo_before_gnucash.py` loads it first, called from
`cli/__init__.py` — which runs before any `cli.*` module — and from
`tests/conftest.py`, since a test can reach `import gnucash` without the CLI.
It is a no-op above Python 3.7. It lives in `cli/__init__.py` rather than
`main.py` because as an import there, isort sorts `infrastructure` after `cli`
and puts it back too late.

**Two pins go with it**, both in `pyproject.toml` and the Dockerfile, both
because pip picks a version that cannot work: `weasyprint<53` below Python 3.8
(53.0 wants a Pango symbol buster has not, and what pip picks unpinned
segfaults on import), and `pypdf>=3.0,<4.4` below 3.8 (pypdf 5.0.0's wheel
claims 3.7 and its `_protocols.py` imports `typing.Protocol`). Naming either
package bare — which `scripts/test-in-docker.sh` did — bypasses the markers
entirely; it installs `.[dev,statement]` now.

### 24. GnuCash 3.4 ships "Display → Payments" off, and mangles a book option under a non-UTF-8 locale

Discovered 2026-09-05, both from the same printed page.

**The switch.** `invoice.scm` registers `Display / Payments` with a default of
`#f` on 3.4 and `#t` from 4.x — read out of the shipped Scheme. A paid invoice
printed on Debian 10 therefore showed its full total as due and no payment
row at all. `services/gnucash_report.py` sets it alongside the three switches
it already sets, because what a printed page says is owed should not depend on
which GnuCash drew it.

**The locale.** Telling the output port `UTF-8` is not enough on 3.4: the
company name is mangled before it reaches the port, when GnuCash turns the
option's C string into a Scheme string through the locale's codeset. Measured
under `LC_ALL=C`, with the book holding the name intact:

```
3.4    any-name">??ditions Clich?? Inc.<     one ? per UTF-8 byte
5.10   any-name">\xc3\x89ditions Clich\xc3\xa9 Inc.<
```

The customer's Japanese name came through the same page unharmed, so it is
that one accessor rather than the page. The render sets `C.UTF-8` for its own
length, caught, because a build without that locale must still draw its page.

---

**Last Updated**: 2026-09-05
