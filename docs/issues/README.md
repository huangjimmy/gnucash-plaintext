# Issue Tracking

Known issues, gaps, and planned enhancements identified by code review.
Each file follows the naming convention `<category>-<NNN>-<slug>.md`.

When a fix is merged, update `status: open` → `closed` in the file's frontmatter
and in the **Status** column below.

## Tests

| ID | Title | Severity | Status |
|----|-------|----------|--------|
| [T-001](T-001-print-invoice-no-dedicated-tests.md) | print-invoice command has no dedicated test file | high | closed |
| [T-002](T-002-invoice-renderer-no-unit-tests.md) | invoice_renderer.py has no unit tests | medium | closed |
| [T-003](T-003-kvp-colon-validation-untested.md) | KVP metadata colon validation is untested | medium | closed |
| [T-004](T-004-multi-currency-beancount-export-untested.md) | Multi-currency beancount export has no integration test | medium | closed |
| [T-005](T-005-multi-currency-close-books-untested.md) | Multi-currency close-books path has no test | medium | closed |
| [T-006](T-006-fx-rates-yaml-error-paths-untested.md) | FX rates YAML error paths are untested | low | closed |
| [T-007](T-007-plaintext-parser-edge-cases-untested.md) | Plaintext parser edge cases are not tested | medium | closed |

## Security

| ID | Title | Severity | Status |
|----|-------|----------|--------|
| [S-001](S-001-run-command-executes-arbitrary-scripts.md) | run command executes arbitrary scripts without documented risk | low | closed |
| [S-002](S-002-broad-exception-in-gzip-fallback.md) | Broad except-Exception in gzip fallback masks real errors | low | closed |

## Features

| ID | Title | Severity | Status |
|----|-------|----------|--------|
| [F-001](F-001-qfx-dependency-declared-but-not-implemented.md) | QFX/OFX dependency declared but feature not implemented | medium | open |
| [F-002](F-002-balance-sheet-command-missing.md) | No balance-sheet command | enhancement | open |
| [F-003](F-003-export-date-range-filter-missing.md) | export command has no date-range filter | enhancement | closed |
| [F-004](F-004-no-search-find-transaction-command.md) | No search / find-transaction command | enhancement | closed |
| [F-005](F-005-data-models-and-provider-protocol.md) | Statement import: data models and StatementProvider protocol | feature | closed |
| [F-006](F-006-statement-reconciler.md) | Statement import: StatementReconciler (depends on F-005) | feature | closed |
| [F-007](F-007-writer-and-preview-reader.md) | Statement import: ReconcilePreviewWriter and ReconcilePreviewReader (depends on F-006) | feature | closed |
| [F-008](F-008-gnucash-fuzzy-matcher.md) | Statement import: GnuCashFuzzyMatcher (depends on F-007) | feature | closed |
| [F-009](F-009-ready-to-import-writer.md) | Statement import: ReadyToImportWriter and end-to-end test (depends on F-008) | feature | closed |
| [F-010](F-010-kvp-metadata-all-object-types.md) | KVP custom metadata for all GnuCash object types | high | closed |
| [F-011](F-011-customer-active-delete.md) | Customer/vendor active flag round-trip and safe deletion | high | closed |

## Quality

| ID | Title | Severity | Status |
|----|-------|----------|--------|
| [Q-001](Q-001-inconsistent-cli-exception-types.md) | Inconsistent exception types across CLI commands | low | closed |
| [Q-002](Q-002-read-book-company-info-bypasses-repo-layer.md) | read_book_company_info bypasses the repository layer | low | closed |
| [Q-003](Q-003-account-type-export-not-reimportable.md) | Exported account types (A/Receivable, A/Payable) crash re-import | high | closed |
| [Q-004](Q-004-payment-transaction-duplicates.md) | Invoice payment blocks create duplicate bank transactions (Cases B and C) | high | closed |
| [Q-005](Q-005-import-errors-no-context.md) | Import errors show raw exception with no directive context | high | closed |
| [Q-006](Q-006-business-object-id-uniqueness-and-guid-export.md) | Business-object IDs are not unique on re-import; GUIDs are not exported | high | closed |
| [Q-007](Q-007-delete-archive-by-guid.md) | delete/archive accept GUIDs; invoice/bill identity enforced on import | medium | closed |
| [Q-008](Q-008-taxtable-identity.md) | Tax-table identity not enforced on import; re-import duplicates | medium | closed |
| [Q-009](Q-009-import-summary-business-objects.md) | Business-object import is silent — re-import gives no signal of skip vs. create vs. update | medium | closed |
| [Q-010](Q-010-strict-updated-status-on-no-change-reimport.md) | `'updated'` is liberal — reports updated for no-change re-imports; posted invoices/bills can't be edited via re-import | low | closed |
| [Q-011](Q-011-invoice-action-optional-and-custom-template.md) | Invoice `action` field forces a hardcode; UNIT column shows nonsense; no template override | low | closed |
| [Q-012](Q-012-print-invoice-on-unposted-invoice-crashes.md) | `print-invoice` on an unposted invoice crashes with NoneType error | medium | closed |
| [Q-013](Q-013-delete-unposted-invoice-bill.md) | No way to delete an unposted invoice or bill from the CLI | medium | closed |
| [Q-014](Q-014-orphan-payment-warning-on-unpost.md) | `unpost-invoices` / `unpost-bills` don't warn about soon-to-be-orphan bank payments | medium | closed |
| [Q-015](Q-015-incremental-payment-reimport-rebuilds-destructively.md) | Incremental + overpayment + credit-consumption payment workflows on re-import | high | closed |
| [Q-016](Q-016-full-guid-emission-and-import-order-for-payment-roundtrip.md) | Full GUID emission and import-order swap for clean payment roundtrip | high | closed |
| [Q-017](Q-017-print-invoice-plaintext-format-and-multi-invoice.md) | `print-invoice` plaintext format with tax totals; multi-invoice selection | low | closed |
| [Q-018](Q-018-cash-basis-invoice-marker.md) | `cash_basis: true` invoice marker for cash-basis tax filing | low | closed |
| [Q-019](Q-019-draft-tax-render-and-two-sided-bill-rendering.md) | Draft tax breakdown + `print-bill` + two-sided rendering with company info | medium | closed |
| [Q-020](Q-020-num-only-roundtrip-and-import-dedup-signature.md) | Num-only roundtrip relabels Num as Description; `import_from_file` dedup ignores `doc_link` / `tx_num` / `owner` | high | open |
