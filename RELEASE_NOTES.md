# Release Notes

## v0.2.0 - Architecture Migration (2026-03-01)

**Major release** with complete architecture refactoring and new features.

### 🎉 Highlights

- **Unified CLI**: All functionality through single `gnucash-plaintext` command
- **GnuCash-Beancount Format**: Bidirectional conversion with zero data loss
- **Multi-Version Support**: Tested on GnuCash 3.8, 4.4, 4.13, 5.10
- **Comprehensive Testing**: 145 tests with 100% parity validation
- **Docker Development**: Cross-platform development environment

### ✨ New Features

#### 1. Bidirectional Beancount Conversion

Full round-trip conversion between GnuCash and beancount:

```bash
# Export to GnuCash-Beancount
gnucash-plaintext export-beancount mybook.gnucash output.beancount

# Import back to GnuCash
gnucash-plaintext import-beancount restored.gnucash output.beancount

# Full chain: Plaintext → GnuCash → Beancount → GnuCash → Plaintext
# All data preserved with zero loss
```

**Features:**
- Account name aliasing (spaces and special characters preserved via metadata)
- Complete GnuCash metadata preservation (GUIDs, types, placeholders, etc.)
- Strict validation (rejects standard beancount without metadata)
- Commodity symbol sanitization for beancount compatibility

See [docs/gnucash-beancount-format.md](docs/gnucash-beancount-format.md) for details.

#### 2. Ledger Validation

New `validate` command checks GnuCash file integrity:

```bash
# Full validation report
gnucash-plaintext validate mybook.gnucash

# Quick check (errors only)
gnucash-plaintext validate mybook.gnucash --quick

# Show statistics
gnucash-plaintext validate mybook.gnucash --stats
```

**Validates:**
- Account structure and types
- Transaction balance
- Commodity consistency
- Split reconciliation
- Date validity
- GUID uniqueness

#### 3. Conflict Resolution

Smart duplicate detection with resolution strategies:

```bash
# Skip conflicting transactions (default)
gnucash-plaintext import mybook.gnucash transactions.txt --strategy skip

# Keep existing on conflict
gnucash-plaintext import mybook.gnucash transactions.txt --strategy keep-existing

# Replace with incoming on conflict
gnucash-plaintext import mybook.gnucash transactions.txt --strategy keep-incoming
```

**Conflict detection:**
- By GUID (if present in plaintext)
- By transaction signature (date + accounts)
- Prevents accidental duplicates

#### 4. Dry Run Mode

Preview changes before applying:

```bash
gnucash-plaintext import mybook.gnucash transactions.txt --dry-run
gnucash-plaintext import-beancount output.gnucash input.beancount --dry-run
```

#### 5. Date Range and Account Filtering

Export specific subsets of data:

```bash
# Export date range
gnucash-plaintext export mybook.gnucash output.txt \
  --date-from 2024-01-01 --date-to 2024-12-31

# Export specific account
gnucash-plaintext export mybook.gnucash output.txt \
  --account "Assets:Bank"

# Also works with beancount export
gnucash-plaintext export-beancount mybook.gnucash output.beancount \
  --date-from 2024-01-01 --date-to 2024-12-31
```

**Note:** When filtering transactions, ALL commodities and ALL accounts are still exported (required for valid beancount).

### 🏗️ Architecture Changes

#### New Structure

```
gnucash-plaintext/
├── cli/                    # CLI commands
│   ├── main.py
│   ├── export_cmd.py
│   ├── import_cmd.py
│   ├── export_beancount_cmd.py
│   ├── import_beancount_cmd.py
│   ├── qfx_to_plaintext_cmd.py
│   └── validate_cmd.py
├── services/               # Business logic
│   ├── account_categorizer.py
│   ├── beancount_converter.py
│   ├── beancount_parser.py
│   ├── ledger_validator.py
│   ├── plaintext_formatter.py
│   ├── qfx_converter.py
│   └── transaction_matcher.py
├── use_cases/              # Orchestration
│   ├── export_beancount.py
│   ├── export_transactions.py
│   ├── import_beancount.py
│   ├── import_transactions.py
│   ├── qfx_to_plaintext.py
│   └── validate_ledger.py
├── infrastructure/         # I/O adapters
│   ├── gnucash/
│   │   ├── gnucash_importer.py
│   │   └── utils.py
│   ├── plaintext/
│   │   └── plaintext_parser.py
│   └── qfx/
│       └── qfx_parser.py
└── repositories/
    └── gnucash_repository.py
```

#### Benefits

- **Testability**: 145 tests with clear separation of concerns
- **Maintainability**: Single responsibility per module
- **Extensibility**: Easy to add new formats
- **Reusability**: Services can be composed in different ways

### 🔧 Improvements

#### Multi-Version GnuCash Support

Tested and working on:
- **Debian 13** (Python 3.12, GnuCash 5.10)
- **Debian 12** (Python 3.11, GnuCash 4.13)
- **Debian 11** (Python 3.9, GnuCash 4.4)
- **Ubuntu 20.04** (Python 3.8, GnuCash 3.8)

**Compatibility features:**
- Abstract version differences with try/except patterns
- Compatibility shims for SessionOpenMode, GetDocLink/GetAssociation
- No version checks - code adapts dynamically

#### Docker Development Environment

Cross-platform development with:
- VS Code Server at https://localhost:8765
- Live code sync
- Docker-in-Docker support (Linux/macOS/WSL2)
- Pre-installed GnuCash Python bindings
- Automated test scripts

```bash
# Start development environment
./scripts/dev-start.sh

# Run tests
./scripts/test.sh

# Test all versions
./scripts/test-all-versions.sh
```

#### Enhanced Test Coverage

- **139 tests** for core functionality
- **6 new tests** for beancount round-trip
- **100% parity** with legacy code
- **Multi-version testing** on 4 distributions
- **Integration tests** for full conversion chains

### 🚨 Breaking Changes

#### 1. Command Names

| Old | New |
|-----|-----|
| `python3 ledger.py <file> <output> --export` | `gnucash-plaintext export <file> <output>` |
| `python3 ledger.py <file> <input>` | `gnucash-plaintext import <file> <input>` |
| `python3 convert_qfx.py <qfx> <output>` | `gnucash-plaintext qfx-to-plaintext <qfx> <output>` |

#### 2. Python Version

- **Minimum**: Python 3.8+ (was 3.6+)
- **Reason**: Compatibility with Ubuntu 20.04 LTS

#### 3. Installation

Development now requires Docker:
```bash
./scripts/dev-start.sh
```

Production installation via pip (planned for future release).

### 📝 Migration Guide

See [MIGRATION.md](MIGRATION.md) for detailed upgrade instructions.

**Quick migration:**

Old:
```bash
python3 ledger.py mybook.gnucash transactions.txt
python3 convert_qfx.py input.qfx output.txt
```

New:
```bash
gnucash-plaintext import mybook.gnucash transactions.txt
gnucash-plaintext qfx-to-plaintext input.qfx output.txt
```

### 🐛 Bug Fixes

- Fixed commodity export to use ticker instead of mnemonic
- Fixed space handling in commodity symbols
- Fixed account name aliasing for spaces and special characters
- Fixed import to reuse GnuCashImporter infrastructure
- Fixed transaction signature matching for conflict detection

### 📚 Documentation

- **New**: [MIGRATION.md](MIGRATION.md) - Upgrade guide
- **New**: [docs/gnucash-beancount-format.md](docs/gnucash-beancount-format.md) - Format specification
- **Updated**: [README.md](README.md) - Comprehensive usage guide
- **Updated**: [scripts/README.md](scripts/README.md) - Development workflow

### 🔮 Future Plans

#### Phase 8: Close Books (Planned)

Year-end closing with multi-currency support:

```bash
# Close books per currency
gnucash-plaintext close-books mybook.gnucash --closing-date 2024-12-31

# Optional: Consolidate to book currency
gnucash-plaintext consolidate-equity mybook.gnucash --closing-date 2024-12-31
```

See [migration_plan.md](migration_plan.md) for details.

### 👏 Acknowledgments

- **GnuCash Team**: For the excellent Python bindings
- **Beancount Community**: For inspiration on plaintext accounting
- **Contributors**: Testing, feedback, and bug reports

### 📊 Statistics

- **Development Time**: 11.5 days (estimated 22-30 days, 48-62% ahead of schedule)
- **Tests**: 145 tests (was 17 legacy tests)
- **Code Removed**: 4,418 lines of legacy code
- **Code Added**: New clean architecture
- **Files Changed**: 35 files deleted, new structure added
- **Supported Versions**: 4 GnuCash versions (3.8, 4.4, 4.13, 5.10)

---

## Previous Releases

### v0.1.x - Initial Implementation

- Basic plaintext import/export
- QFX conversion
- Script-based interface
- Single GnuCash version support

**Note:** v0.1.x is no longer maintained. Please upgrade to v0.2.0.

---

**Full Changelog**: https://github.com/yourusername/gnucash-plaintext/compare/v0.1.0...v0.2.0
