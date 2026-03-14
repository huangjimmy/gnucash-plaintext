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
   - This provides critical context for future developers (and future AI sessions)

3. **Verify before commit**
   ```bash
   git status
   git diff --cached --name-only
   ```

## Branch Strategy

### Working Branch: `architecture-migration`
- All Phase 0-6 work happens here
- Old code (`editor/`, `parser/`) stays in place until Phase 6
- New code (`cli/`, `services/`, `infrastructure/`, `use_cases/`) built alongside

### Merge to `main` ONLY After Phase 6
Merge criteria:
- ✅ All new tests pass in Docker
- ✅ Regression tests confirm same output as old code
- ✅ CLI commands work end-to-end
- ✅ Documentation updated
- ✅ Old code deleted
- ✅ Migration guide in README

## Docker Rules

### Supported Distributions (Verified)
- debian:13 (GnuCash 5.10) - default
- debian:12 (GnuCash 4.13)
- debian:11 (GnuCash 4.4)
- ubuntu:20.04 (GnuCash 3.8) - minimum
- ubuntu:22.04 (GnuCash 4.8)

### ❌ Do NOT Support
- debian:10 (EOL, broken dependencies)

## File Organization

### External Reference Files (NOT in git)
- `convert_qfx.py` - reference for QFX parsing requirements
- `ledger.py` - reference for update workflow requirements
- `reference_file*.txt` - sample data for understanding format
- `.claude/` - Claude CLI directory

### Migration Work (IN git, on architecture-migration branch)
- `Dockerfile` - unified Docker environment
- `migration_plan.md` - architecture and phase plan
- `migration_log.md` - progress tracking
- `scripts/` - helper scripts for all platforms
- `CLAUDE.md` - this file with project rules

### Future Work (will be added during Phases 1-6)
- `cli/` - CLI commands (Phase 4)
- `services/` - business logic (Phase 1)
- `infrastructure/` - I/O layers (Phase 2)
- `use_cases/` - orchestration (Phase 3)
- `tests/` - test suites (all phases)

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

1. **Committing too early** - Phase 0 has 3 days, only Day 1 is complete
2. **Adding reference files** - They're external, don't commit
3. **Using git add -A** - Stage files explicitly
4. **Skipping planning** - Follow the phase plan in migration_plan.md
5. **Working on main** - Use architecture-migration branch
6. **Merging too early** - Only after Phase 6 completion

## Useful Commands

### Check what's staged
```bash
git status
git diff --cached --name-only
```

### Verify branch
```bash
git branch --show-current  # Should be: architecture-migration
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

---

**Last Updated**: 2026-03-14
**Current Phase**: Phase 8 (Business Objects)
