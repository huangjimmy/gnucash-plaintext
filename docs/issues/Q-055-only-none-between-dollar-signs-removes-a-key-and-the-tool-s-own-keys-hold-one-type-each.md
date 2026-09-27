---
id: Q-055
title: "Only `$None$` removes a key, a custom key holds what the file states, and gnucash-plaintext's own keys hold one type each"
category: quality
severity: medium
status: closed
---

## What was reported

Q-054 added `$None$` so that a file could say "remove this key" in a way no
value could be mistaken for, after `#None` became a null a custom key keeps.
The author's rule was that `$None$` removes a key. Q-054 shipped with `""`
still removing one as well: `removes_the_key` in `infrastructure/gnucash/kvp.py`
answered yes for an empty value, and README's table said `key: ""` would
"clear the field — and for a custom key, remove it". A user read README at
that commit and found the rule the author had stated nowhere in it.

Reading the same code turned up how the rest of gnucash-plaintext's own keys
were held. `took_the_residual`, `applied_from_credit` and `business_generated`
were written as the text `"true"`, and read back by comparing text:
`str(value).strip().lower() == 'true'`. `states_the_residual_mark` read any
text that was not `""`, `"false"`, `"0"` or `"no"` as a mark, `"maybe"`
included. Q-018's `cash_basis` was documented as the bare `cash_basis: true`,
and its `due_date` was a bare date the decoder returned as text, stored as
text, and exported in quotes.

## The rules

The author's, stated while the fix was being written:

- Only `$None$`, unquoted, removes a key. `""` is the empty text.
- A key of the user's own holds what the file states, as it states it:
  `#True` and `#False` are `bool`, `1` is a number, `2026-01-31` without
  quotes is a date, and anything in quotes is text, so `"#True"`, `"yes"`,
  `"1"` and `"2026-01-31"` are text. Each is exported as it was stated. A
  word without quotes, such as `yes`, is refused, and so is a date without
  quotes the calendar does not have, such as `2026-13-45`.
- gnucash-plaintext's own keys hold one type each. A `bool` key is stored
  and exported as `#True` or `#False`, and a file may also write `#True` as
  `"true"`, `"yes"` or `1`, and `#False` as `"false"`, `"no"` or `0`; a word
  without quotes, `true` and `yes` included, is refused. A date key takes a
  date in quotes as the date, and exports it without them. `""` on any of
  them states nothing and is refused.

## What changed

- `removes_the_key` answers yes for `$None$` alone.
- The decoder returns a date written `YYYY-MM-DD` without quotes as a
  `DateAsWritten`, a `str` holding its digits, so every reader of a date
  field that parses text parses it as before. A word without quotes that is
  no keyword, number or date comes back a `BareWord`, a `str` too, told apart
  only where it matters.
- `set_custom_metadata` stores a date in the JSON slot as
  `{"$date": "2026-01-31"}`, since JSON has no date, and `get_custom_metadata`
  reads it back as a date. `encode_value_as_string` writes a date without
  quotes. A book written before this holds only strings, and reads as it did.
  The `company` block's keys and `set-book-key` share one book-level slot,
  and `merge_book_custom_metadata` and `get_book_custom_metadata` store and
  read a date in it the same way, so `incorporated: 2026-01-31` on a company
  block exports without quotes (`test_company_custom_book_keys.py`).
- `THE_TOOL_S_OWN_KEYS` in `services/foreign_currency.py` lists each of
  gnucash-plaintext's own keys and the Python type it holds: `bool` for
  `took_the_residual`, `applied_from_credit`, `cost_basis_force`,
  `business_generated` and `cash_basis`; `DateAsWritten` for `due_date`;
  `str` for `cost_basis_balance`, `cost_basis_cost` and
  `cost_basis_split_guid`. `the_tool_s_own_keys_as_they_hold` reads a file's
  values for them as that type, before anything else reads the file, and
  refuses what cannot be.
- `the_custom_keys_stated_as_bare_words` refuses a word without quotes on a
  key of the user's own.
- Every writer of a `bool` key writes `True`; every reader asks `as_a_bool`,
  which reads `True` and the old text `"true"` alike. `as_written` gives
  the export each key as the type it holds: a `bool` key of an older book,
  stored as `"true"`, is written `#True`, and its `due_date`, stored as the
  text of a date, is written as a date without quotes. The transaction,
  split, invoice and bill exports all use it, and
  `test_an_older_book_s_own_keys_are_exported_as_the_type_each_holds.py`
  exports a gain split's `took_the_residual`, a posting's
  `business_generated`, a spent credit's `applied_from_credit`, and an
  invoice's and a bill's `cash_basis` and `due_date`, each holding the old
  text, and imports each export back with nothing changed.
- `same_value`, which decides whether an owner's or a record's key changed,
  tells `#True` from `1` and a date from the text of its digits, which
  Python's `==` calls equal.
- `cost_basis_balance: $None$` and `cost_basis_cost: $None$` pass the checks
  of a stated balance and cost; those checks let `""` through as a removal
  and never learned `$None$`, so removing a balance was refused as "not a
  number".

## Tests

- `tests/scenario/test_a_custom_key_on_a_bank_draft_is_set_changed_and_removed.py`:
  steps 8 to 20, a key of the user's own stated `""`, `"$None$"`, `$None$`,
  `#True`, `#False`, `"#True"`, `"yes"`, `"1"`, `1`, a bare `yes`, a date, the
  text of a date, and a date the calendar has not.
- `tests/scenario/test_the_tool_s_own_keys_hold_what_they_hold_and_only_none_between_dollar_signs_removes_one.py`:
  `took_the_residual` in every spelling, `""` on the cost basis keys, and
  keys of the user's own stating `"true"`, `"yes"`, `0` and `"0"` kept as
  written.
- `tests/scenario/test_an_invoice_s_posting_and_a_spent_credit_are_marked_true_or_false.py`:
  `business_generated` and `applied_from_credit`.
- `tests/scenario/test_a_sale_forced_against_an_uncollected_invoice_states_its_force_true_or_false.py`:
  `cost_basis_force` in every spelling, a bare `true` and a bare `yes`
  refused.
- `tests/scenario/test_a_cash_basis_invoice_states_its_due_date_as_a_date.py`:
  `cash_basis` and `due_date`.
- `tests/integration/test_a_key_stated_empty_holds_the_empty_text.py`,
  `test_an_empty_key_on_an_account.py` and
  `test_removing_a_custom_key_removes_it_from_the_book.py` state the rule for
  transactions, splits, accounts, owners and invoices.
