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
| [T-008](T-008-tax-included-and-payment-reconciliation-coverage.md) | tax_included pricing untested; bill tax flags not persisted; payment/credit reconciliation gaps | high | open |
| [T-009](T-009-line-and-branch-coverage-is-not-measured-or-gated.md) | Coverage is measured by nothing, so unreachable code is found by review; ctypes signatures declared per-caller | high | closed |

## Security

| ID | Title | Severity | Status |
|----|-------|----------|--------|
| [S-001](S-001-run-command-executes-arbitrary-scripts.md) | run command executes arbitrary scripts without documented risk | low | closed |
| [S-002](S-002-broad-exception-in-gzip-fallback.md) | Broad except-Exception in gzip fallback masks real errors | low | closed |

## Features

| ID | Title | Severity | Status |
|----|-------|----------|--------|
| [F-001](F-001-qfx-dependency-declared-but-not-implemented.md) | QFX/OFX dependency declared but feature not implemented | medium | closed |
| [F-002](F-002-balance-sheet-command-missing.md) | No balance-sheet command | enhancement | closed |
| [F-003](F-003-export-date-range-filter-missing.md) | export command has no date-range filter | enhancement | closed |
| [F-004](F-004-no-search-find-transaction-command.md) | No search / find-transaction command | enhancement | closed |
| [F-005](F-005-data-models-and-provider-protocol.md) | Statement import: data models and StatementProvider protocol | high | closed |
| [F-006](F-006-statement-reconciler.md) | Statement import: StatementReconciler (depends on F-005) | high | closed |
| [F-007](F-007-writer-and-preview-reader.md) | Statement import: ReconcilePreviewWriter and ReconcilePreviewReader (depends on F-006) | high | closed |
| [F-008](F-008-gnucash-fuzzy-matcher.md) | Statement import: GnuCashFuzzyMatcher (depends on F-007) | high | closed |
| [F-009](F-009-ready-to-import-writer.md) | Statement import: ReadyToImportWriter and end-to-end test (depends on F-008) | high | closed |
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
| [Q-009](Q-009-import-summary-business-objects.md) | Business-object import is silent — re-import does not say whether it skipped, created or updated | medium | closed |
| [Q-010](Q-010-strict-updated-status-on-no-change-reimport.md) | `'updated'` is liberal — reports updated for no-change re-imports; posted invoices/bills can't be edited via re-import | low | closed |
| [Q-011](Q-011-invoice-action-optional-and-custom-template.md) | Invoice `action` field forces a hardcode; UNIT column shows nonsense; no template override | low | closed |
| [Q-012](Q-012-print-invoice-on-unposted-invoice-crashes.md) | `print-invoice` on an unposted invoice crashes with NoneType error | medium | closed |
| [Q-013](Q-013-delete-unposted-invoice-bill.md) | No way to delete an unposted invoice or bill from the CLI | medium | closed |
| [Q-014](Q-014-orphan-payment-warning-on-unpost.md) | `unpost-invoices` / `unpost-bills` don't warn about soon-to-be-orphan bank payments | medium | closed |
| [Q-015](Q-015-incremental-payment-reimport-rebuilds-destructively.md) | Incremental + overpayment + credit-consumption payment workflows on re-import | high | closed |
| [Q-016](Q-016-full-guid-emission-and-import-order-for-payment-roundtrip.md) | Full GUID emission and import-order swap for clean payment roundtrip | high | closed |
| [Q-017](Q-017-print-invoice-plaintext-format-and-multi-invoice.md) | `print-invoice` plaintext format with tax totals; multi-invoice selection | low | closed |
| [Q-018](Q-018-cash-basis-invoice-kvp.md) | `cash_basis: #True` invoice KVP for cash-basis tax filing | low | closed |
| [Q-019](Q-019-draft-tax-render-and-two-sided-bill-rendering.md) | Draft tax breakdown + `print-bill` + two-sided rendering with company info | medium | closed |
| [Q-020](Q-020-num-only-roundtrip-and-import-dedup-signature.md) | Num-only roundtrip relabels Num as Description; `import_from_file` dedup ignores `doc_link` / `tx_num` / `owner` | high | open |
| [Q-021](Q-021-return-of-credit-bad-debt-and-prepayment-clearing.md) | Return of credit (refund), bad-debt write-off, and prepayment clearing via `lot_owner` | high | closed |
| [Q-022](Q-022-payment-transfer-account-allows-owner-equity.md) | Invoice/bill payment validation rejects owner's-equity deposit accounts | medium | closed |
| [Q-023](Q-023-retarget-prepayment-residual-credit-owner.md) | Retarget-with-prepayment residual credit is not owner-attached, invisible to the open_prepayment summary | medium | closed |
| [Q-024](Q-024-unapply-payment.md) | Unapply a payment from a posted invoice/bill without unposting it | medium | closed |
| [Q-025](Q-025-edited-guid-match-skipped-silently.md) | Editing a transaction by re-import is silently skipped as a "duplicate" | low | closed |
| [Q-026](Q-026-multi-invoice-payment-amount-allocation.md) | One bank tx paying multiple invoices/bills exports the bank total as each record's payment amount | medium | closed |
| [Q-027](Q-027-account-guid-not-preserved-on-import.md) | Account GUIDs are not preserved on import, so they drift every roundtrip | medium | closed |
| [Q-028](Q-028-company-info-gst-pst-roundtrip.md) | Company info (incl. GST/PST registration numbers) is not round-tripped, and there is nowhere to record GST/PST | medium | closed |
| [Q-029](Q-029-company-arbitrary-book-keys.md) | company directive only round-trips known seller-identity keys; no way to store arbitrary book-level data | medium | closed |
| [Q-030](Q-030-rename-account.md) | No way to rename an account; the full round-trip can't express it | enhancement | closed |
| [Q-031](Q-031-migrate-batch-operations.md) | No batch operations or migrations — every surgical command is one-op-per-save | enhancement | closed |
| [Q-032](Q-032-closing-entries-and-report.md) | Income statement breaks once books are closed; no balance sheet; no combined report | high | closed |
| [Q-033](Q-033-natural-account-type-strings-rejected.md) | Natural Receivable/Payable account-type strings are rejected, silently dropping accounts | high | closed |
| [Q-034](Q-034-uncached-ctypes-library-loads-degrade-import-performance.md) | Uncached ctypes library loads and account-name walks degrade import performance linearly with transaction count | medium | closed |
| [Q-035](Q-035-usd-multi-currency-invoices-and-bills-unsupported.md) | No multi-currency support — foreign-currency invoices, bills, payments and conversions are written wrong, silently | high | closed |
| [Q-036](Q-036-printed-pages-were-not-gnucashs-own.md) | A printed invoice was this project's own page, and stated the book's valuation of a foreign-currency invoice as the amount owed | high | closed |
| [Q-037](Q-037-a-printed-page-is-dated-by-the-machine-that-printed-it.md) | A printed page is dated by the machine that printed it | — | closed |
| [Q-038](Q-038-an-address-is-as-long-as-the-address-is.md) | An address is as long as the address is | — | closed |
| [Q-039](Q-039-linking-a-split-not-on-the-receivable.md) | Linking a bank transaction whose other side is not on the receivable, in any currency | — | closed |
| [Q-040](Q-040-a-link-leaves-a-cost-basis-behind.md) | A link leaves a cost basis behind, and no edit can pick it up | — | closed |
| [Q-041](Q-041-a-price-cannot-be-recorded-for-a-past-date-or-kept-through-export-and-import.md) | A price cannot be recorded for a past date, or kept through export and import | — | closed |
| [Q-042](Q-042-print-the-balance-sheet-and-income-statement-as-plaintext-through-a-customized-gnucash-report.md) | Print the balance sheet and income statement as plaintext through a customized GnuCash report, in the currency the book is kept in | — | closed |
| [Q-043](Q-043-state-realized-and-unrealized-gains-separately-and-value-foreign-currency-from-the-cost-bases.md) | State realized and unrealized gains separately, value foreign currency from the book's cost bases, and leave every other asset and liability to GnuCash's own revaluation | — | closed |
| [Q-044](Q-044-state-a-realized-gain-with-no-took-the-residual-key-and-say-what-the-balancing-amount-is.md) | State a realized gain on a book whose splits carry no `took_the_residual`, and say on the balance sheet what GnuCash's balancing amount is | — | closed |
| [Q-045](Q-045-draw-a-stock-bought-with-foreign-currency-from-that-currencys-cost-basis-and-open-one-for-what-a-sale-brings-in.md) | Draw a stock bought with foreign currency from that currency's cost basis, and open a cost basis for the foreign currency a stock sale brings in | — | closed |
| [Q-046](Q-046-record-a-securitys-cost-basis-in-the-books-own-currency-so-a-sale-realizes-a-gain-the-way-a-currency-disposal-does.md) | Record a security's cost basis in the book's own currency, so a sale realizes a gain the way a currency disposal does | — | closed |
| [Q-047](Q-047-record-a-cost-basis-on-the-other-side-for-the-part-of-a-balance-past-zero.md) | Record a cost basis on the other side for the part of a foreign-currency balance past zero | — | closed |
| [Q-048](Q-048-accept-an-edit-that-leaves-every-cost-basis-as-it-was.md) | Accept an edit that leaves every cost basis as it was, and say what a refused edit would change and a route that works | — | closed |
| [Q-049](Q-049-let-a-book-keep-no-cost-bases.md) | Let a book keep no cost bases, and measure its unrealized gains from GnuCash's own revaluation | — | closed |
| [Q-050](Q-050-let-a-split-draw-on-a-cost-basis-by-its-position-in-the-file-being-imported.md) | Let a split draw on a cost basis by its position in the file being imported, so a transaction can spend currency it brings in and a file need not assign a guid | — | closed |
| [Q-051](Q-051-let-a-statement-line-on-a-holding-account-be-edited-into-the-invoice-or-bill-it-settles.md) | Let a foreign-currency statement line imported against a holding account, with its bank fee in the same transaction, be edited later into the invoice or bill it settles | — | closed |
| [Q-052](Q-052-carry-a-book-forward-into-a-new-book-with-each-cost-basis-at-its-adjusted-cost.md) | Carry a book forward into a new book, with each cost basis at its adjusted cost | — | open |
| [Q-053](Q-053-check-an-atomic-import-against-the-book-the-whole-file-leaves.md) | Check an `--atomic` import against the book the whole file leaves, so a booking can be undone or done again in one file | — | closed |
| [Q-054](Q-054-pending-counts-every-cost-basis-and-a-cost-basis-a-command-destroys-leaves-its-disposals-pending.md) | `$pending$` counts every cost basis, on its own side and never below nothing, and a command that destroys a cost basis leaves what drew on it pending | — | closed |
| [Q-055](Q-055-only-none-between-dollar-signs-removes-a-key-and-the-tool-s-own-keys-hold-one-type-each.md) | Only `$None$` removes a key, a custom key holds what the file states, and gnucash-plaintext's own keys hold one type each | medium | closed |
| [Q-056](Q-056-measure-a-book-in-the-base-currency-it-states.md) | A book is measured in the base currency it states, not in CAD | high | closed |
| [Q-057](Q-057-keep-each-accounts-balance-in-every-currency-the-book-supports.md) | Keep each account's balance in every currency the book supports, and move every balance with a transfer | — | closed |
| [Q-058](Q-058-run-a-batch-of-read-commands-against-one-open-book.md) | A batch of read commands opens the book once, and writes each command's output to its own file | enhancement | open |
