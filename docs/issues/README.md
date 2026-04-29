# Issue Tracking

Known issues, gaps, and planned enhancements identified by code review.
Each file follows the naming convention `<category>-<NNN>-<slug>.md`.

When a fix is merged, update `status: open` → `closed` in the file's frontmatter.

## Tests

| ID | Title | Severity |
|----|-------|----------|
| [T-001](T-001-print-invoice-no-dedicated-tests.md) | print-invoice command has no dedicated test file | high |
| [T-002](T-002-invoice-renderer-no-unit-tests.md) | invoice_renderer.py has no unit tests | medium |
| [T-003](T-003-kvp-colon-validation-untested.md) | KVP metadata colon validation is untested | medium |
| [T-004](T-004-multi-currency-beancount-export-untested.md) | Multi-currency beancount export has no integration test | medium |
| [T-005](T-005-multi-currency-close-books-untested.md) | Multi-currency close-books path has no test | medium |
| [T-006](T-006-fx-rates-yaml-error-paths-untested.md) | FX rates YAML error paths are untested | low |
| [T-007](T-007-plaintext-parser-edge-cases-untested.md) | Plaintext parser edge cases are not tested | medium |

## Security

| ID | Title | Severity |
|----|-------|----------|
| [S-001](S-001-run-command-executes-arbitrary-scripts.md) | run command executes arbitrary scripts without documented risk | low |
| [S-002](S-002-broad-exception-in-gzip-fallback.md) | Broad except-Exception in gzip fallback masks real errors | low |

## Features

| ID | Title | Severity |
|----|-------|----------|
| [F-001](F-001-qfx-dependency-declared-but-not-implemented.md) | QFX/OFX dependency declared but feature not implemented | medium |
| [F-002](F-002-balance-sheet-command-missing.md) | No balance-sheet command | enhancement |
| [F-003](F-003-export-date-range-filter-missing.md) | export command has no date-range filter | enhancement |
| [F-004](F-004-no-search-find-transaction-command.md) | No search / find-transaction command | enhancement |

## Quality

| ID | Title | Severity |
|----|-------|----------|
| [Q-001](Q-001-inconsistent-cli-exception-types.md) | Inconsistent exception types across CLI commands | low |
| [Q-002](Q-002-read-book-company-info-bypasses-repo-layer.md) | read_book_company_info bypasses the repository layer | low |
