---
id: T-003
title: KVP metadata colon validation is untested
category: tests
severity: medium
status: closed
---

## Problem

`infrastructure/gnucash/kvp.py` enforces that metadata keys must not contain
colons on write, but silently strips them on read. This asymmetric behaviour
(write = reject, read = sanitize) is intentional but neither path is tested,
so a future refactor could silently break either invariant.

## Missing test cases

- Writing a KVP key containing `:` → should raise / return False
- Reading a KVP key that somehow contains `:` → should be sanitized, not crash
- Round-trip: write valid key, read back, verify key is unchanged
- Boundary: key is exactly the colon character

## Affected files

- `infrastructure/gnucash/kvp.py`
- `tests/unit/services/test_kvp_metadata.py`

## Suggested fix

Extend `tests/unit/services/test_kvp_metadata.py` with a `TestColonValidation`
class covering the four cases above. The existing mock-based test infrastructure
in that file should be sufficient without a real GnuCash session.
