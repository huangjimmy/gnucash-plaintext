---
id: Q-009
title: Business-object import is silent — re-import gives no signal of skip vs. create vs. update
category: quality
severity: medium
status: closed
---

## Problem

After Q-006 / Q-007 / Q-008, business-object imports do the *right*
thing on re-import:

| Block | On hit |
|---|---|
| customer / vendor | update mutable fields in place |
| taxtable / invoice / bill | skip (no mutation) |

…but the CLI gives **zero signal** about which path was taken. A user
running `gnucash-plaintext import …` against an already-populated book
sees:

- `exit_code == 0` (same as a fresh-create import)
- `stdout`: byte-identical to a fresh import (just the
  transaction-side import summary)
- `stderr`: empty

Reported by another user via private review:

> Real create: delta=+514 bytes (file grew by 514 bytes)
> Q-007 skip: delta=+0 bytes (file unchanged)
> stdout: byte-identical
> stderr: byte-identical
>
> The CLI gives zero signal in stdout/stderr. The size delta is the
> only reliable post-hoc signal we have without making an extra query.

That's a UX bug. A user shouldn't have to diff file sizes to know
whether their import did anything.

## Proposed fix: both per-directive output AND aggregate counts

Two complementary signals:

### 1. Per-directive output, inline as the import runs

Mirrors the per-record output of `delete-customers` /
`archive-customers` / etc. (added in Q-007):

```
customer "C001": updated
customer "C002": created
vendor "V001": skipped (already exists)        ← actually no, vendors update too
taxtable "GST": skipped (already exists)
invoice "INV-001": skipped (already exists)
invoice "INV-002": created
bill "BILL-001": skipped (already exists)
```

Per-directive lines give exact detail without the user having to
guess. They're noisier on large imports but match the format users
already know from delete/archive.

### 2. Aggregate counts in the import summary at the end

Same shape as the existing transaction-side summary:

```
Business Objects:
  Customers:  1 created, 1 updated, 0 skipped
  Vendors:    0 created, 1 updated, 0 skipped
  Tax tables: 0 created, 0 updated, 1 skipped
  Invoices:   1 created, 1 skipped
  Bills:      0 created, 1 skipped
```

Aggregate counts are easier to scan on big imports and easy to assert
on in scripts (e.g. CI).

### Why both, not one or the other

Per-directive lines tell the user *which* records changed. Counts
tell them *how many*. A user investigating "did my edit propagate?"
wants per-directive detail; a CI pipeline asserting "exactly N
customers were updated" wants counts. Both are cheap to plumb because
the resolver already knows the answer for free.

## Implementation sketch

### `import_business_objects` returns a result, not nothing

Currently the method has no return value. Introduce
`BusinessObjectImportResult`:

```python
@dataclass
class BusinessObjectImportResult:
    customers_created:  int = 0
    customers_updated:  int = 0
    customers_skipped:  int = 0   # if we ever add skip-on-customer
    vendors_created:    int = 0
    vendors_updated:    int = 0
    vendors_skipped:    int = 0
    taxtables_created:  int = 0
    taxtables_skipped:  int = 0
    invoices_created:   int = 0
    invoices_skipped:   int = 0
    bills_created:      int = 0
    bills_skipped:      int = 0
```

Each `import_customer` / `import_vendor` / `import_taxtable` /
`import_invoice` / `import_bill` returns one of three statuses
(`'created'`, `'updated'`, `'skipped'`); `import_business_objects`
aggregates.

### CLI emits per-directive lines as it goes

The CLI receives the per-directive status from the importer. Easiest
plumbing: add an optional `on_directive_status` callback parameter
to `import_business_objects`:

```python
self.importer.import_business_objects(
    directives, book,
    on_directive_status=lambda kind, id_, status: click.echo(
        f'{kind} "{id_}": {status}'
    ),
)
```

Default no-op so library callers don't get unwanted output.

### Final summary printed by CLI after import completes

Same place we already print the transaction summary:

```
Business Objects:
  Customers:  1 created, 1 updated, 0 skipped
  Vendors:    0 created, 1 updated, 0 skipped
  ...
```

Skipped lines emitted only when count > 0 (less noise on fresh
imports).

## Files to change

| File | Change |
|---|---|
| `services/gnucash_importer.py` | Per-method status return; `import_business_objects` aggregates into a result and invokes the optional `on_directive_status` callback. |
| `cli/import_cmd.py` | Pass the callback that prints per-directive lines; print the aggregate summary after `import_business_objects` returns. |
| `tests/integration/test_business_object_import_summary.py` (new) | Cover per-directive and aggregate output for: fresh import, full re-import, mixed (some new + some existing). |
| `README.md` | Show the new output format under the import section. |

## Out of scope

- Per-record output for plain transactions (already has its own
  summary; that subsystem is unrelated).
- Verbosity flags (`--quiet` / `--verbose`). Possible follow-up if
  the per-directive lines turn out to be too noisy in real-world
  imports.
- A machine-readable output mode (JSON) — same follow-up bucket.

---

**Created**: 2026-05-08
