---
id: Q-007
title: delete-customers / archive-customers / archive-vendors must accept GUID, not just user-facing id
category: quality
severity: medium
status: open
---

## Problem

After Q-006 the importer/exporter treat GUID as a first-class identifier
for customers, vendors, taxtables, invoices, and bills. The
delete/archive CLI commands still only accept the user-facing id
(customer number / vendor number) as the addressable handle:

```bash
gnucash-plaintext delete-customers   FILE CUST-001 CUST-002
gnucash-plaintext archive-customers  FILE CUST-001
gnucash-plaintext archive-vendors    FILE VEND-001
```

If two customers share an id (legacy data from before Q-006) the lookup
returns a non-deterministic match — the user has no way to address a
specific record. Also, scripts that already have a customer's GUID
(e.g. parsed out of an exported plaintext file) must do an extra
ID-lookup step before they can call delete/archive.

## Why auto-detect is wrong

We considered routing each arg through "looks like a 32-char hex →
treat as GUID, else treat as id". Rejected: nothing prevents a user
from naming a customer `9f14a498cc894d50931f855a9a31d594` (any non-empty
string is a legal customer number). Auto-detection would silently
misroute that arg.

## Proposed fix

Add an explicit `--by-guid` flag to each command:

```bash
gnucash-plaintext delete-customers   FILE [--by-guid] ID|GUID...
gnucash-plaintext archive-customers  FILE [--by-guid] ID|GUID...
gnucash-plaintext archive-vendors    FILE [--by-guid] ID|GUID...
```

Default behaviour (no flag) is unchanged: positional args are
customer/vendor numbers. With `--by-guid` they are GUIDs. Mixed forms
in one invocation are not supported — keeps the per-arg semantics
unambiguous and matches the "I'm operating on a list of one kind of
identifier" mental model.

GUID values follow the same rules as Q-006:

- 32-char lowercase hex
- UUID-with-hyphens accepted (normalised via `string_to_guid`)
- Any other format is an immediate `Invalid GUID format` error

## Per-record output always shows both id and guid

When a record is matched, the per-record summary line includes **both**
the user-facing id and the GUID, regardless of which form the user typed
on the command line:

```bash
$ gnucash-plaintext delete-customers FILE CUST-001
CUST-001 (9f14a498cc894d50931f855a9a31d594): deleted

$ gnucash-plaintext delete-customers FILE --by-guid 9f14a498cc894d50931f855a9a31d594
CUST-001 (9f14a498cc894d50931f855a9a31d594): deleted
```

This is also a small UX improvement on the existing id-only path: a
maintainer reading a deletion log can confirm exactly which record was
removed without having to cross-reference an export.

On a miss (record not found) only the typed input is shown — there's no
matched record to read a guid from:

```
DOES-NOT-EXIST: not found
deadbeefdeadbeefdeadbeefdeadbeef: not found
```

## Files to change

| File | Change |
|---|---|
| `cli/delete_cmd.py` | Add `--by-guid` flag to all three commands; in the dispatcher, route to a new `*_by_guid` use case when set. |
| `use_cases/delete_business_objects.py` | New `*ByGuidUseCase` variants (or a `lookup_mode` parameter on the existing ones) that resolve via a guid lookup instead of `book.CustomerLookupByID`. The resolver normalises via `_normalise_guid` so `string_to_guid` validates the format up-front. |
| `services/gnucash_importer.py` | Re-export `_normalise_guid`, `_find_customer_by_guid`, `_find_vendor_by_guid` to the use case layer (they're currently module-private to `gnucash_importer`). Or move them to a shared helper module. |
| `tests/integration/test_delete_business_objects.py` | New tests for `--by-guid`: happy path, unknown-guid not-found, malformed guid format error. |
| `README.md` | Document the new flag for delete-customers, archive-customers, archive-vendors. |

## Open questions

1. Should we also add `--by-guid` to a hypothetical future `delete-vendors`
   command? Not in scope here — `delete-vendors` is intentionally not
   implemented (vendor `Destroy()` is broken in the GnuCash XML backend
   per F-011 findings). If/when that's ever revisited, follow this
   pattern.
2. The existing `find-transactions` command takes a `--account` and
   filters; it doesn't take a transaction id at all, so no symmetry
   change needed there.

---

**Created**: 2026-05-07
