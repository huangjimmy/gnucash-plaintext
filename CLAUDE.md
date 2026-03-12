# Claude Code Rules for gnucash-plaintext Project

Project-specific rules and conventions for Claude Code assistance.

## Git Commit Rules

### ❌ NEVER Do These:
1. **No `git add -A` or `git add .`**
   - Always add files explicitly by name
   - Prevents accidentally committing temporary files, secrets, or reference materials

2. **No Co-Authored-By**
   - Do NOT include `Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>` in commits
   - Keep commit messages clean and professional

3. **No committing external reference files**
   - `convert_qfx.py`, `ledger.py` are external references (not part of repo)
   - `reference_file*.txt` are external test data (not part of repo)
   - Always check with user before committing untracked files

### ✅ Always Do These:
1. **Stage files explicitly**
   ```bash
   git add Dockerfile migration_plan.md scripts/
   # NOT: git add -A
   ```

2. **Clean commit messages**
   - Clear subject line (50 chars max)
   - Detailed body explaining what and why
   - No AI attribution

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

---

**Last Updated**: 2026-02-15
**Current Phase**: Phase 0 (Day 1 Complete, Day 2-3 Pending)
