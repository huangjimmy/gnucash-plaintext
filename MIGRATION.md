# Migration Guide: v0.1.x → v0.2.0

This guide helps users upgrade from the old script-based system to the new unified CLI.

## Breaking Changes

### 1. Unified CLI Command

**Old (v0.1.x):**
```bash
python3 ledger.py mybook.gnucash transactions.txt
python3 convert_qfx.py input.qfx output.txt
```

**New (v0.2.x):**
```bash
gnucash-plaintext import mybook.gnucash transactions.txt
gnucash-plaintext qfx-to-plaintext input.qfx output.txt
```

All functionality is now accessed through the single `gnucash-plaintext` command.

### 2. Command Name Changes

| Old Script | New Command | Notes |
|------------|-------------|-------|
| `ledger.py` (import mode) | `gnucash-plaintext import` | Import plaintext to GnuCash |
| `ledger.py` (export mode) | `gnucash-plaintext export` | Export GnuCash to plaintext |
| `convert_qfx.py` | `gnucash-plaintext qfx-to-plaintext` | Convert QFX to plaintext |
| N/A (new) | `gnucash-plaintext export-beancount` | Export to beancount format |
| N/A (new) | `gnucash-plaintext import-beancount` | Import from GnuCash-Beancount |
| N/A (new) | `gnucash-plaintext validate` | Validate GnuCash file integrity |

### 3. Argument Order Changes

**Import command:**

Old:
```bash
python3 ledger.py <gnucash_file> <plaintext_file>
```

New:
```bash
gnucash-plaintext import <gnucash_file> <plaintext_file>
```

**Export command:**

Old:
```bash
python3 ledger.py <gnucash_file> <plaintext_file> --export
```

New:
```bash
gnucash-plaintext export <gnucash_file> <plaintext_file>
```

### 4. New Features

**Conflict Resolution:**
```bash
# Skip conflicts (default)
gnucash-plaintext import mybook.gnucash transactions.txt --strategy skip

# Keep existing on conflict
gnucash-plaintext import mybook.gnucash transactions.txt --strategy keep-existing

# Replace with incoming on conflict
gnucash-plaintext import mybook.gnucash transactions.txt --strategy keep-incoming
```

**Dry Run Mode:**
```bash
# Preview changes without modifying files
gnucash-plaintext import mybook.gnucash transactions.txt --dry-run
gnucash-plaintext import-beancount output.gnucash input.beancount --dry-run
```

**Validation:**
```bash
# Full validation report
gnucash-plaintext validate mybook.gnucash

# Quick check (errors only)
gnucash-plaintext validate mybook.gnucash --quick

# Show statistics
gnucash-plaintext validate mybook.gnucash --stats

# Save report to file
gnucash-plaintext validate mybook.gnucash --report validation.txt
```

**Date Range Filtering:**
```bash
# Export specific date range
gnucash-plaintext export mybook.gnucash output.txt \
  --date-from 2024-01-01 --date-to 2024-12-31

# Export specific account
gnucash-plaintext export mybook.gnucash output.txt \
  --account "Assets:Bank"
```

## Installation Changes

### Old Installation (v0.1.x)

```bash
# Clone and run directly
git clone https://github.com/yourusername/gnucash-plaintext.git
cd gnucash-plaintext
python3 ledger.py --help
```

### New Installation (v0.2.x)

**Development Mode:**
```bash
# Start Docker development environment
./scripts/dev-start.sh

# Access VS Code Server at https://localhost:8765 (password: 123456)
# Or run commands directly:
docker run --rm -v $(pwd):/workspace gnucash-dev gnucash-plaintext --help
```

**Production Installation (future):**
```bash
pip install gnucash-plaintext
gnucash-plaintext --help
```

## File Format Changes

### Plaintext Format

**No breaking changes** - All existing plaintext files work with v0.2.0.

The plaintext format remains compatible:
- Account declarations with metadata
- Commodity declarations
- Transaction format
- Split metadata

### New: GnuCash-Beancount Format

v0.2.0 introduces a new format for bidirectional conversion:

```bash
# Export to GnuCash-Beancount
gnucash-plaintext export-beancount mybook.gnucash output.beancount

# Import back
gnucash-plaintext import-beancount restored.gnucash output.beancount
```

See [docs/gnucash-beancount-format.md](docs/gnucash-beancount-format.md) for details.

## Architecture Changes

### Code Organization

Old structure:
```
gnucash-plaintext/
├── ledger.py
├── convert_qfx.py
├── editor/
│   ├── gnucash_editor.py
│   ├── plaintext_to_gnucash.py
│   └── gnucash_to_plaintext.py
├── parser/
│   └── plaintext_parser.py
└── utils.py
```

New structure:
```
gnucash-plaintext/
├── cli/              # Command-line interface
├── services/         # Business logic
├── use_cases/        # Orchestration
├── infrastructure/   # I/O adapters
│   ├── gnucash/
│   ├── plaintext/
│   └── qfx/
└── tests/           # Comprehensive test suite
```

### Benefits

1. **Better Testability**: 145 tests covering all functionality
2. **Multi-Version Support**: Tested on GnuCash 3.8, 4.4, 4.13, 5.10
3. **Cross-Platform**: Docker-based development works on Linux/macOS/Windows
4. **Extensibility**: Easy to add new formats and commands
5. **Maintainability**: Clear separation of concerns

## Common Migration Scenarios

### Scenario 1: Regular Import Workflow

**Old workflow:**
```bash
# Download bank QFX
# Convert to plaintext
python3 convert_qfx.py bank_2024.qfx transactions.txt

# Manually review and edit transactions.txt

# Import to GnuCash
python3 ledger.py mybook.gnucash transactions.txt
```

**New workflow:**
```bash
# Download bank QFX
# Convert to plaintext
gnucash-plaintext qfx-to-plaintext bank_2024.qfx transactions.txt

# Manually review and edit transactions.txt

# Preview import
gnucash-plaintext import mybook.gnucash transactions.txt --dry-run

# Import to GnuCash
gnucash-plaintext import mybook.gnucash transactions.txt
```

### Scenario 2: Export for Backup

**Old workflow:**
```bash
python3 ledger.py mybook.gnucash backup.txt --export
```

**New workflow:**
```bash
# Export to plaintext
gnucash-plaintext export mybook.gnucash backup.txt

# Or export to GnuCash-Beancount for full round-trip
gnucash-plaintext export-beancount mybook.gnucash backup.beancount
```

### Scenario 3: Periodic Export for Version Control

**Old workflow:**
```bash
python3 ledger.py mybook.gnucash ledger.txt --export
git add ledger.txt
git commit -m "Update ledger"
```

**New workflow:**
```bash
# Export to GnuCash-Beancount (better for version control)
gnucash-plaintext export-beancount mybook.gnucash ledger.beancount
git add ledger.beancount
git commit -m "Update ledger"

# Later: restore from version control
gnucash-plaintext import-beancount restored.gnucash ledger.beancount
```

## Troubleshooting

### Issue: Command not found

**Problem:**
```bash
$ gnucash-plaintext --help
-bash: gnucash-plaintext: command not found
```

**Solution:**
Use Docker for development:
```bash
./scripts/dev-start.sh
# Inside VS Code Server or container:
gnucash-plaintext --help
```

### Issue: Import conflicts

**Problem:**
Transactions from plaintext file conflict with existing transactions.

**Solution:**
Use conflict resolution strategies:
```bash
# Skip conflicting transactions
gnucash-plaintext import mybook.gnucash transactions.txt --strategy skip

# Or keep existing
gnucash-plaintext import mybook.gnucash transactions.txt --strategy keep-existing
```

### Issue: Python version compatibility

**Problem:**
Old scripts used Python 3.6+, new version requires Python 3.8+.

**Solution:**
v0.2.0 requires Python 3.8+ for compatibility with Ubuntu 20.04 LTS. Use Docker for consistent environment:
```bash
./scripts/dev-start.sh
```

## Getting Help

- **Documentation**: See [README.md](README.md) for detailed usage
- **Format Spec**: See [docs/gnucash-beancount-format.md](docs/gnucash-beancount-format.md)
- **Issues**: Report bugs at https://github.com/yourusername/gnucash-plaintext/issues
- **CLI Help**: Run `gnucash-plaintext --help` or `gnucash-plaintext <command> --help`

## Rollback Plan

If you encounter issues with v0.2.0, you can temporarily use v0.1.x:

```bash
# Switch to main branch (v0.1.x)
git checkout main

# Use old scripts
python3 ledger.py mybook.gnucash transactions.txt
```

However, we recommend reporting issues so they can be fixed in v0.2.x, as v0.1.x is no longer maintained.
