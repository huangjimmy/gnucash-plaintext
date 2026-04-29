---
id: T-007
title: Plaintext parser edge cases are not tested
category: tests
severity: medium
status: open
---

## Problem

`services/plaintext_parser.py` has unit tests for the happy path but the
following edge cases are absent:

- **Malformed metadata**: unclosed string quotes (`description: "foo`),
  metadata line with no value (`code:`), value containing a literal `"` character
- **Duplicate commodity declarations**: two `commodity` blocks with the same
  mnemonic — should it merge, error, or take last?
- **Unicode in account names**: CJK characters, RTL text, emoji, and combining
  diacritics (e.g. `Expenses:食費` or `Assets:Café`) — these are real use cases
  for this project
- **Extremely long account names**: names over 255 characters (GnuCash's internal
  limit, if any)
- **Empty transaction body**: a transaction header with no splits
- **Split with missing amount**: a split line where the amount is omitted

## Affected files

- `services/plaintext_parser.py`
- `tests/unit/services/test_plaintext_parser.py`

## Suggested fix

Add a parametrised `test_parser_edge_cases` class in `test_plaintext_parser.py`.
Each case passes a crafted input string and asserts either the correct parsed
output or a specific `ParseError` with a helpful message.
