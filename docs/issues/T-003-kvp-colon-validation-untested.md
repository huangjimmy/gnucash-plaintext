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

## Resolution

The cases are tested against real GnuCash books rather than in a
`TestColonValidation` class of `tests/unit/services/test_kvp_metadata.py`:

- writing a key containing `:` raises `ValueError`:
  `tests/integration/test_kvp_all_objects.py::TestCustomerKvp::test_colon_key_raises`;
- a key containing `:` that another tool wrote into a book is dropped on export
  rather than written:
  `tests/integration/test_metadata_written_by_another_tool.py::…::test_a_key_with_a_colon_is_dropped_on_the_way_out`;
- a valid key reads back unchanged: the `test_roundtrip` tests of
  `tests/integration/test_kvp_all_objects.py`;
- `set-book-key` refuses a key containing `:`:
  `tests/integration/test_cli_bad_arguments_are_refused.py::TestSetBookKey::test_a_key_with_a_colon_is_refused`.
