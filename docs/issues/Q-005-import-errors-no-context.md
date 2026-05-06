---
id: Q-005
title: Import errors show raw exception message with no context
category: quality
severity: high
status: open
---

## Problem

When the importer encounters an error, the user sees a raw Python exception
message with no context about what failed or how to fix it:

```
Error: 'currency'          ← KeyError — which directive? which field? which file?
Error: 'A/Receivable'      ← KeyError — which account? what's the valid value?
Error: Account 'X' not found when trying to determine currency for transaction ...
```

This affects **all three import paths** in `import_cmd.py`:

### 1. Business objects (`import_business_objects`)

`import_business_objects` calls each per-type importer with no try/except.
Any exception (KeyError on missing field, ValueError, GnuCash error) propagates
unmodified to the CLI, which catches it as `click.ClickException(str(e))`:

```python
# import_cmd.py
importer.import_business_objects(...)   # bare call — no context on failure
```

The user is told `Error: 'currency'` with no indication of which customer,
vendor, invoice, or bill caused the problem.

### 2. Account creation (`create_account`)

Called in a loop but errors are either swallowed or raised without the
account name in scope:

```python
for directive in parser.root_directive.children:
    if directive.type == DirectiveType.OPEN_ACCOUNT:
        importer.create_account(directive, repo.book)   # bare call
```

### 3. Transaction import

Slightly better — the transaction import loop does have per-transaction
try/except, but the error dict only contains the raw exception string
without the directive's source location (line number, file name).

## What the user should see

| Scenario | Current | Should be |
|---|---|---|
| Missing `currency` on customer | `Error: 'currency'` | `customer "C1": missing required field 'currency'` |
| Unknown account type on re-import | `Error: 'A/Receivable'` | `account "Assets:AR": unknown type 'A/Receivable' — valid types: Asset, Bank, ...` |
| Invoice references unknown customer | `Error: CustomerLookupByID returned None` | `invoice "INV-001": customer_id "C1" not found — import customers before invoices` |
| Account not found for split | `Error: Account 'X' not found` | `transaction 2026-01-15 "Dinner": split account "Expenses:Food" not found` |

## Fix

Wrap each per-type importer call in `import_business_objects` with a
try/except that catches generic exceptions and re-raises with directive
context:

```python
def import_business_objects(self, directives, book):
    for directive in directives:
        if directive.type == DirectiveType.CUSTOMER:
            try:
                self.import_customer(directive, book)
            except Exception as e:
                cid = directive.props.get('id', '?')
                raise ValueError(f'customer "{cid}": {e}') from e
        ...
```

Apply the same pattern to:
- `import_vendor` calls
- `import_taxtable` calls  
- `import_invoice` calls
- `import_bill` calls
- `create_account` call in `import_cmd.py`

For transactions, add file name and line number to the existing error dict.

## Files to change

| File | Change |
|---|---|
| `services/gnucash_importer.py` | Wrap each call in `import_business_objects` with try/except adding directive context |
| `cli/import_cmd.py` | Wrap `create_account` loop with per-directive try/except |

---

**Created**: 2026-05-06
