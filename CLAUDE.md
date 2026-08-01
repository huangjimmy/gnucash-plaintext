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
`_record_overpaid_basis` did exactly that and opened no basis at all for a
retargeted overpayment's residue, so the book offered 100.00 USD while its bank
held 200.00 and selling the rest was refused. The fix is to write to the split
the code already has rather than to search a lot for it; where a search is
unavoidable, walk the *account's* splits and filter by `split.GetLot()`.

### 10. Unposting leaves the lot behind, indistinguishable from a credit lot

Discovered 2026-08-06 while working out which splits a `txn_guid:` retarget may
move.

`gncInvoiceUnpost` detaches the document from its lot, but does **not** destroy
the lot or empty it. The lot stays on the account, still listed by
`xaccAccountGetLotList`, still holding whatever splits settled the document, and
`gncOwnerGetOwnerFromLot` still names the owner — because unposting re-attaches
the owner to it.

Measured on GnuCash 5.10: after `record.Unpost(False)` on a paid invoice, the
settling split's `GetLot()` returns the same lot as before, that pointer is
still in the account's lot list, `gncInvoiceGetInvoiceFromLot` returns NULL, and
the owner reads back as the invoice's customer.

**Consequence**: a lot abandoned by an unpost and an owner's parked prepayment
lot are the same thing as far as the book is concerned — live, documentless,
owner-attached. No property of either tells them apart, so code that must
distinguish them has to *record* the unpost rather than interrogate the lot
afterwards.

The record has to be **durable**, not in-process. The book is saved with the
orphan still in the abandoned lot, so the import that meets it may be days
later in another process — and the standalone `unpost-invoices` /
`unpost-bills` commands reach the state in one step with no import around them
at all. `services/gnucash_importer.py` writes `orphaned_by_unpost` on each
orphaned split, valued with the guid of the document that was unposted, from
`mark_splits_orphaned_by_unpost()`; both the importer's rebuild path and
`use_cases/unpost_business_objects.py` call it immediately before
`Unpost(False)`, while the lot still names the document.

Valued with a guid rather than `true` because a rebuild has to find the split
that was settling *it*: one transaction can carry orphans from two documents,
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
| carved remainder (a new split) | empty — no mark, no basis |

So the applied part is where the key survives into a state that no longer
matches it: it is another document's settlement now, not the first document's
orphan. `_mark_applied_from_credit` drops it alongside the basis keys. Nothing
is stripped from the remainder, because nothing arrives on it.

All three matter, and the import half is the sharpest. A split carrying the key
reads as *not* an owner's credit, so a settlement genuinely spent from a credit
would skip taking the basis off; and because a mark naming a document is
*preferred* over everything else placeable — which is how a rebuild finds its
own orphan — a file stating one could choose which of an owner's two credits a
document spends, past the guard that exists to stop split order deciding that.
On a foreign book those carry different costs, so it would pick the gain too.

What turns on the difference: moving a split out of a credit lot spends the
owner's money and must take the cost basis off it; moving one out of an
abandoned lot is the rebuild putting back what it just detached, and stripping
a basis there would lose currency the book still holds — the book then offering
less than its bank has, and the export writing that bank payment as
`from_credit:` with no account and no date.

**What makes an orphan credit is how it was paid, not whose it is.** The mark
names a document so a rebuild can find the settlement that was its own, but
whether the money is anybody's *credit* is a separate question, and the split
answers it: a settlement that came out of credit carries `applied_from_credit`,
and that survives the unpost.

- marked, and came from credit → credit still, loose again and spendable by
  anyone the owner owes;
- marked, and never came from credit → a bank paid it, and it is a settlement
  waiting to be put back, whichever document's unpost loosened it;
- unmarked, in a live documentless owner lot → an ordinary parked credit.

Reading the mark as "not credit to this document, credit to everyone else"
looks right and is not: `unpost-invoices B` then a file settling A off B's
deposit is one step, and it strips the basis off currency the bank still holds
while exporting a block that named an account and a date as `from_credit:`
carrying neither.

All three consumers ask the same question of the same split, and the guid is
consulted by none of them — only `_retarget_choices` uses it, to find the
settlement a rebuild is entitled to:

| where | what it does with a bank-paid orphan |
|---|---|
| `_sits_in_an_owners_credit` (`txn_guid:`, `txn_split_guid:`) | not a credit — no basis strip, no `applied_from_credit` |
| `_apply_credit_payment_directive` (`from_credit:`) | refused; the file is asserting what the book contradicts |
| `_mark_applied_from_credit` (`auto_apply_credit:`) | left unmarked; the engine may take it, but it is not written down as credit |

Scoping any one of them to the record reopens the hole in that spelling alone,
which is how the three came to disagree in the first place.

**Nothing in a file represents the mark**, so it cannot travel: a file may not
state it (that would let a file steer which credit a document spends), and the
export filters it out. What must not travel either is `lot_owner:` on such a
split — that line is a file saying "this is an owner's credit, put it in a lot
of theirs", and restoring an export into a fresh book then rebuilt a bank's
payment as spendable credit. So the export omits it for a bank-paid orphan, and
the split comes back loose: in no lot, nobody's credit invented. That is what
it is, the document it settled being unposted.

**Books unposted by an earlier version carry no mark**, and there is no way to
add one after the fact: an abandoned lot and a parked credit are the same three
facts, which is the whole finding. Such an orphan therefore reads as a credit.
Measured what that costs: the settlement split carries no cost basis of its own
— the basis sits on the document's posting split — so nothing is stripped and
`fx-balances` still matches the bank. What changes is the label: the export
writes the bank payment as `from_credit:` with no account and no date.
Unposting the document again under this version writes the mark and restores
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
  open, documentless, owner-attached lots, which is what the rebuild's own
  unpost left a moment earlier, so a re-imported document with no payment block
  is handed its own settlement back. Measured on GnuCash 5.10: without the
  check it exports as `from_credit: true` + `credit_dated:`, with no
  `bank_account:` and no date — the money's origin gone, with nothing in the
  file having asked for a credit at all.

---

**Last Updated**: 2026-08-06
