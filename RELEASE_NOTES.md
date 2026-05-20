# Release Notes

## v0.3.3 - Payment workflows, statement import, business-object round-trip hardening (2026-05-20)

This release closes the round-trip story for invoices, bills, and payments, and adds an end-to-end pipeline for reconciling raw bank statements into import-ready plaintext. Two months of bug fixes, format extensions, and new CLI subcommands.

### Payment workflows

Posted invoices and bills now accept incremental edits via re-import: append a `payment:` block to a posted record, re-import, and only the new payment is applied — the posting transaction, every entry, and the original bank-side payment transactions on the lot keep their GUIDs. Overpayments create an AR/AP credit lot for the owner; subsequent invoices/bills can consume the credit by setting `auto_apply_credit: true`. ([Q-015](docs/issues/Q-015-incremental-payment-reimport-rebuilds-destructively.md))

Single-invoice payment retarget and multi-invoice shared bank transactions now round-trip cleanly: both the bank-side transaction and the invoice's payment block emit the full transaction GUID plus per-split GUIDs, and the importer processes standalone transactions before business objects so `payment: txn_guid:` resolves on the first pass. ([Q-016](docs/issues/Q-016-full-guid-emission-and-import-order-for-payment-roundtrip.md))

```bash
# Append a payment to a posted invoice
$EDITOR ledger.txt   # add another payment: { ... } block
gnucash-plaintext import mybook.gnucash ledger.txt --include-business-objects
```

### New CLI subcommands

- `unpost-invoices` / `unpost-bills`: unpost without re-import. Warns about bank-side payment transactions that would become orphan if their lot is unposted. ([Q-014](docs/issues/Q-014-orphan-payment-warning-on-unpost.md))
- `delete-invoices` / `delete-bills`: remove unposted invoices and bills from the book (refuses posted records — unpost first). ([Q-013](docs/issues/Q-013-delete-unposted-invoice-bill.md))
- `find-orphan-payments`: list bank-side payment transactions whose AR/AP lot is no longer attached to any invoice or bill. Read-only.
- `find-prepayments`: list open AR/AP credit lots not yet consumed by an invoice or bill. Read-only.
- `find-transactions`: search transactions by account, date, or description.
- `delete-customers` / `archive-customers` / `archive-vendors`: retire owners by ID or `--by-guid`. Archive flips the `active` flag; delete refuses owners with open invoices, bills, or payments. ([F-011](docs/issues/F-011-customer-active-delete.md), [Q-007](docs/issues/Q-007-delete-archive-by-guid.md))

### Statement import pipeline

A four-stage pipeline takes a raw bank statement (CSV / OFX / QFX provider) through reconciliation against the book and produces an import-ready plaintext file with categorized splits.

1. `StatementProvider` — adapter protocol for statement sources.
2. `StatementReconciler` — matches statement rows against existing transactions in the book (by date + amount + memo signature).
3. `ReconcilePreviewWriter` / `ReconcilePreviewReader` — human-editable preview file lists matches, ambiguous rows, and unmatched rows.
4. `GnuCashFuzzyMatcher` + `ReadyToImportWriter` — suggests counter-accounts from history and emits import-ready plaintext.

See [docs/statement-import-pipeline.md](docs/statement-import-pipeline.md) and [docs/bank-import-workflow.md](docs/bank-import-workflow.md). ([F-005](docs/issues/F-005-data-models-and-provider-protocol.md)..[F-009](docs/issues/F-009-ready-to-import-writer.md))

### print-invoice: plaintext output and multi-invoice selection

`print-invoice` gained a plaintext renderer with audit-friendly tax totals (subtotal, per-tax-table breakdown, total) suitable for `git diff` review of quarterly invoices, and a `--template` flag for custom XSLT/Jinja templates. Multi-invoice selection by date range, customer, or glob produces either a combined PDF or one file per invoice. The `UNIT` column is hidden by default and the `action:` field is now optional. ([Q-011](docs/issues/Q-011-invoice-action-optional-and-custom-template.md), [Q-017](docs/issues/Q-017-print-invoice-plaintext-format-and-multi-invoice.md))

```bash
# Plaintext, all Q1 2026 invoices for one customer
gnucash-plaintext print-invoice mybook.gnucash \
  --customer C001 --date-from 2026-01-01 --date-to 2026-03-31 \
  --format plaintext -o q1-acme.txt

# One PDF per invoice, into a directory
gnucash-plaintext print-invoice mybook.gnucash \
  --customer C001 --date-from 2026-01-01 --date-to 2026-03-31 \
  --format pdf -o q1-acme/
```

Also: `print-invoice` no longer crashes on unposted invoices — they render as a draft watermark. ([Q-012](docs/issues/Q-012-print-invoice-on-unposted-invoice-crashes.md))

### Cash-basis invoice marker

Invoices can be tagged `cash_basis: true` to identify revenue that should be reported on the payment date rather than the invoice date — for cash-basis tax filers (Canadian small business below the CRA threshold, US Schedule C, single-entity service consultancies). The flag is descriptive metadata stored as a KVP slot; it round-trips and does not change accounting behaviour. ([Q-018](docs/issues/Q-018-cash-basis-invoice-marker.md))

### Business-object round-trip correctness

- Exported account-type short-forms (`A/Receivable`, `A/Payable`) no longer crash re-import. ([Q-003](docs/issues/Q-003-account-type-export-not-reimportable.md))
- Invoice payment blocks no longer create duplicate bank transactions when the same posted invoice is re-imported. ([Q-004](docs/issues/Q-004-payment-transaction-duplicates.md))
- Business-object IDs are enforced unique on re-import, and full GUIDs are exported so conflict detection works across export/import cycles. ([Q-006](docs/issues/Q-006-business-object-id-uniqueness-and-guid-export.md))
- Tax-table identity is enforced on import — re-importing a tax table with the same name no longer creates duplicates. ([Q-008](docs/issues/Q-008-taxtable-identity.md))
- Posted invoices and bills are now mutable via the unpost-rebuild-repost cycle the importer runs internally; `unchanged` status is reported strictly when no field differs. ([Q-010](docs/issues/Q-010-strict-updated-status-on-no-change-reimport.md))
- Import emits explicit create / update / unchanged / skip signals for every business object so re-imports are no longer silent. ([Q-009](docs/issues/Q-009-import-summary-business-objects.md))
- The `active` flag round-trips for customers and vendors. ([F-011](docs/issues/F-011-customer-active-delete.md))
- KVP custom-metadata round-trip is extended to every business-object type (was Transaction and Split only). ([F-010](docs/issues/F-010-kvp-metadata-all-object-types.md))
- Business objects imported into an existing file are now persisted correctly (a save-path regression that bypassed the repository layer).

### Error reporting

Import errors include the source directive's line number, the directive type, and a snippet of the offending block. Inconsistent CLI exception types were normalized to a single hierarchy. ([Q-005](docs/issues/Q-005-import-errors-no-context.md), [Q-001](docs/issues/Q-001-inconsistent-cli-exception-types.md))

### Platform support

- Ubuntu 26.04 LTS (GnuCash 5.14) added to the test matrix.
- Stale Windows scripts removed (Linux/macOS via Docker remains the supported development path).

### Security

- The `run` shim, which previously executed arbitrary scripts, is removed. ([S-001](docs/issues/S-001-run-command-executes-arbitrary-scripts.md))
- The broad `except Exception` in the gzip fallback path is narrowed to the specific exceptions GnuCash raises so real errors are no longer masked. ([S-002](docs/issues/S-002-broad-exception-in-gzip-fallback.md))

### Tests

Coverage expanded across services and use cases:

- Beancount round-trip data-fidelity tests.
- `update_transaction` covers duplicate-account splits (the "meal + tip" bug) and is no longer dropped by deduplication.
- Cross-currency split exports emit `@ price` annotations; multi-currency beancount export and close-books paths are now tested.
- Plaintext parser edge cases, KVP colon validation, FX-rates YAML error paths, invoice renderer, and `print-invoice` have dedicated test files.
- Disk-persistence tests for account-balance pricedb and close-books.
- Five-state scenario tests for bills (unposted, posted/unpaid, single full payment, two partials, two payments totalling full amount) plus contradiction-error tests.

### Documentation

- [docs/bank-import-workflow.md](docs/bank-import-workflow.md) — end-to-end walk-through of the statement reconciliation pipeline.
- [docs/invoice-payment-reconciliation.md](docs/invoice-payment-reconciliation.md) — payment lifecycle, incremental edits, orphan recovery, prepayment consumption.
- [docs/payment-manual-edit-behavior.md](docs/payment-manual-edit-behavior.md) — reference for what the importer does to a payment block under each kind of diff (entry change vs. payment-only change).
- [docs/research/2026-05-14-invoice-post-pay-unpost-cycle.md](docs/research/2026-05-14-invoice-post-pay-unpost-cycle.md) and [docs/post-mortems/2026-05-08-bill-postto-account-segfault.md](docs/post-mortems/2026-05-08-bill-postto-account-segfault.md) — research and post-mortem notes from this cycle.

---

## v0.3.2 - export-accounts command (2026-04-08)

### What's new

#### Export account structure without loading transactions

A new `export-accounts` command exports all accounts and commodities directly
from the book without scanning the transaction log. This is significantly
faster on large files when only the chart of accounts is needed.

```bash
gnucash-plaintext export-accounts mybook.gnucash accounts.txt
```

Use `--as-of` to stamp a specific date on every `open`/`commodity`
declaration (defaults to the file modification date):

```bash
gnucash-plaintext export-accounts mybook.gnucash accounts.txt --as-of 2024-01-01
```

---

## v0.3.1 - Bill payment bug fixes and test coverage (2026-04-02)

### Bug fixes

#### Bills now round-trip payments correctly

Three bugs in the bill import/export pipeline prevented vendor bill payments
from round-tripping:

1. **Importer used invoice-side Entry API for bills** — `import_bill` was
   calling `SetInvAccount`, `SetInvPrice`, `SetInvTaxable` instead of the
   bill-side equivalents (`SetBillAccount`, `SetBillPrice`, `SetBillTaxable`).
   This caused the AP posting split to have amount $0 and payments to land in
   the wrong GnuCash lot.

2. **Payment amount sign was wrong** — `bill.ApplyPayment(amount=+N)` created
   AP split = −N (wrong direction), so the payment split was placed in a new
   lot instead of the bill's posted lot and was invisible to the exporter.
   Fixed by passing a negated amount so GnuCash creates AP = +N (debit,
   reduces liability) and bank = −N (credit, money sent out).

3. **Exporter used invoice-side entry reader for bills** — `_export_bills` was
   calling `_format_inv_entry`, which reads invoice-side fields
   (`GetInvAccount`, `gncEntryGetInvPrice`). Added `_format_bill_entry` that
   uses the correct bill-side ctypes functions.

#### GnuCash behaviour: bill `taxable` field is always exported as `true`

GnuCash 5.x does not write `entry:b-taxable = false` to the XML file — the
field is omitted when false and defaulted to `true` on reload. Consequently,
exported bills always show `taxable: true` regardless of what was imported.
This is a GnuCash engine constraint, not a bug in this tool.

### Test coverage

Added dedicated bill state scenario tests in
`tests/integration/test_business_objects.py` covering all five states:
unposted, posted/unpaid, single full payment, two partial payments, and two
payments totalling full amount. Also added three contradiction-error tests for
bills (mirrors the existing invoice contradiction tests).

---

## v0.3.0 - Business Objects (2026-03-14)

### What's new

#### Import and export customers, vendors, tax tables, invoices, and bills

You can now round-trip GnuCash business objects through plaintext files:

```bash
gnucash-plaintext import --new mybook.gnucash ledger.txt --include-business-objects
gnucash-plaintext export mybook.gnucash ledger.txt --include-business-objects
```

Supported objects: `customer`, `vendor`, `taxtable`, `invoice` (with entries
and payments), `bill` (with entries and payments — see v0.3.1 for bug fixes).

Business objects use no date prefix in the plaintext format — they are master
data, not ledger events. GnuCash does not store a creation timestamp for
customers, vendors, or tax tables, so no meaningful date prefix exists.
Dates that belong to a record (e.g. `date_opened`) are declared as fields
inside the block.

#### Print invoices to PDF

Any posted invoice can be rendered to a PDF directly from the CLI:

```bash
gnucash-plaintext print-invoice mybook.gnucash --invoice-id INV-2026-001 -o invoice.pdf
```

The output is produced from `services/invoice.xslt`, which you can customise
to match your company's branding.

### Platform support expanded

Ubuntu 22.04 (GnuCash 4.8) and Ubuntu 24.04 (GnuCash 4.9) are now fully
supported and tested in CI.

Two bugs that caused segfaults on Ubuntu (but not Debian) were fixed:
- Missing `argtypes` caused ctypes to silently truncate 64-bit pointers to 32-bit
- Ubuntu loads GnuCash extensions with `RTLD_LOCAL`, so `CDLL(None)` could
  resolve symbols from the wrong library instance

On Ubuntu 22/24, `apt install weasyprint` only provides a CLI wrapper —
`import weasyprint` would fail. Fixed by installing weasyprint via pip.

### Bug fix

`create_account` was not idempotent: calling it twice for the same account
silently created duplicate children in GnuCash. Fixed with an existence check.

---

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
