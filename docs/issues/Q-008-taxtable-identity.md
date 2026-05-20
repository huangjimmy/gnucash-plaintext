---
id: Q-008
title: Tax-table identity not enforced on import; re-import duplicates
category: quality
severity: medium
status: closed
---

## Problem

`import_taxtable` calls `TaxTable(book, name, first_entry)` directly
with no precondition check. Re-importing a plaintext file that
contains a `taxtable "GST"` block creates a fresh tax table every
time, accumulating multiple tax tables with the same name and
different GUIDs.

Downstream impact: invoice/bill entries reference tax tables by name
(`tax_table: "GST"`) and the importer resolves that via
`gncTaxTableLookupByName(book, "GST")`, which returns the first
match. With duplicates in the book the choice is non-deterministic,
silently routing tax onto whichever rate the lookup happened to
return first.

The exporter already emits `guid: "<hex>"` on every taxtable block
(added in Q-006), so the round-trip carries the identity — the
importer just doesn't honour it.

## Why our existing tests miss it

`test_business_objects_persisted_when_imported_into_existing_file`
re-imports the full business-objects fixture (which contains a `GST`
tax table) but only asserts presence of customer/invoice/bill blocks,
never the count of tax tables.

## Proposed fix

Same shape as Q-006 (customer/vendor) and Q-007 (invoice/bill):

1. **Idempotent skip on re-import.** Look up by name first
   (`gncTaxTableLookupByName`); on a hit, skip — tax tables are
   referenced by existing invoices via stored pointers, mutating
   their entries mid-flight could corrupt those references.
2. **Honour the directive's `guid:` field.** When the directive
   provides a guid:
   - validate format via `string_to_guid`
   - look up the tax table by guid (Query iteration over
     `gncTaxTableGetTables` since QofQuery doesn't index tax tables)
   - apply the §2 resolution table from Q-006: id-vs-guid agreement
     is required, multiple-name match is an error, etc.
3. **Persist a user-supplied guid on a freshly created tax table**
   via `qof_instance_set_guid`, with a global-uniqueness check the
   way Q-006 does for customers/vendors (`_guid_in_use_anywhere`
   already covers transactions/accounts/customers/vendors; tax
   tables can join that list).

### Resolution table (mirrors Q-006 §2 with name-instead-of-id)

| `guid:` provided? | name lookup | guid lookup | action |
|---|---|---|---|
| no | not found | — | create |
| no | one match | — | skip |
| no | multiple matches | — | error: book has duplicates, resolve in GUI |
| yes | — | not found, name taken | error |
| yes | name matches resolved record | (same record) | skip |
| yes | name mismatches resolved record | — | error |

### Cross-reference (invoice/bill `tax_table: "GST"`) stays name-based

We already document in Q-007 that introducing a per-reference guid
field (`tax_table_guid:`) is out of scope — accounts/taxtables
reference each other by name and that's been good enough so far.
If a future bug shows the cross-reference itself is fragile, file
that separately.

## Files to change

| File | Change |
|---|---|
| `services/gnucash_importer.py` | Add `_find_taxtables_by_name` (Query-based since `gncTaxTableLookupByName` returns at most one), `_find_taxtable_by_guid`, `_swig_taxtable_guid_str` (ctypes — tax tables are only reachable via ctypes anyway). `import_taxtable` goes through `_resolve_existing_or_none` with skip-on-hit. `_set_object_guid` is called when the directive provides a guid for a fresh create. |
| `tests/integration/test_business_object_idempotent_reimport.py` | New `TestTaxTableIdentityEnforcement` class with: re-import same taxtable file is idempotent; re-import with matching guid is idempotent; re-import with mismatched guid errors; directive's guid resolves to a different taxtable name → error; same-file two `taxtable "GST"` blocks → either error or count == 1 in export. |
| `docs/DEBUGGING_GNUCASH_BINDINGS.md` | If we discover any further GnuCash quirks for tax tables (likely some — they're already the most ctypes-heavy area), document them in the existing business-object findings section. |

## Out of scope

- Cross-reference identity (`tax_table_guid:` on invoice/bill entries)
  — see Q-007 reasoning.
- Updating tax-table entries on re-import. They're effectively
  immutable once invoices reference the tax table, and an update
  would silently change accounting on past posted invoices.

---

**Created**: 2026-05-07
