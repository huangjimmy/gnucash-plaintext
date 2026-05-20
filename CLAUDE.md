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
   - Clear subject line (50 chars max, imperative mood)
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
- debian:13 (GnuCash 5.10) - default
- debian:12 (GnuCash 4.13)
- debian:11 (GnuCash 4.4)
- ubuntu:26.04 (GnuCash 5.14)
- ubuntu:24.04 (GnuCash 4.9)
- ubuntu:22.04 (GnuCash 4.8)
- ubuntu:20.04 (GnuCash 3.8) - minimum

### ❌ Do NOT Support
- debian:10 (EOL, broken dependencies)

## File Organization

### External Reference Files (NOT in git)
- `convert_qfx.py` - reference for QFX parsing requirements
- `ledger.py` - reference for update workflow requirements
- `reference_file*.txt` - sample data for understanding format
- `.claude/` - Claude CLI directory

### Repository Layout
- `cli/` - Click-based CLI commands; `cli/main.py` is the entry point
- `services/` - business logic (importer, exporter, matcher, validator, renderer, statement-reconciler, ...)
- `use_cases/` - orchestration that composes services for a single CLI command
- `infrastructure/` - I/O adapters: `gnucash/` (engine bindings + ctypes wrappers), `plaintext/`, `pdf/`, `qfx/`
- `repositories/` - thin GnuCash session and query layer
- `tests/` - `unit/` (services / use cases / infrastructure / repositories) and `integration/` (CLI end-to-end); `research/` holds long-running scenario probes
- `docs/` - design notes, issue tracker (`docs/issues/`), research probes, post-mortems
- `templates/` - Jinja/XSLT templates for invoice and report rendering

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
Test on all supported distributions:
- Debian 11 (GnuCash 4.4), 12 (4.13), 13 (5.10)
- Ubuntu 20.04 (GnuCash 3.8), 22.04 (4.8), 24.04 (4.9)

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

### 8. GnuCash does not persist `bill_taxable = false` to XML

GnuCash 5.x only writes `entry:b-taxable` to the XML file when the value is
`true`. When `false`, the field is omitted and defaults to `true` on reload.
Consequently, all bill entries always read as `taxable = true` after a
save/reload cycle, regardless of what `SetBillTaxable(False)` was called with.

**Impact on round-trip tests**: the reference fixture must use `taxable: true`
for all bill entries. Do NOT compare against `taxable: false` in bill export.

---

**Last Updated**: 2026-05-20
