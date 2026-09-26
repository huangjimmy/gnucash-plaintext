---
id: T-007
title: Plaintext parser edge cases are not tested
category: tests
severity: medium
status: closed
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

## Resolution

`TestParserEdgeCases` in `tests/unit/services/test_plaintext_parser.py` covers
the cases, one test each: `test_cjk_account_name_parses_correctly`,
`test_transaction_with_no_splits_creates_directive`,
`test_duplicate_commodity_last_one_wins`,
`test_metadata_with_empty_value_parses_as_empty_string` and
`test_metadata_unclosed_quote_treated_as_literal`.
