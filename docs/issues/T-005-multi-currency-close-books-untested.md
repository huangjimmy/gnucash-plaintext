---
id: T-005
title: Multi-currency close-books path has no test
category: tests
severity: medium
status: open
---

## Problem

`services/book_closer.py` and `use_cases/close_books.py` almost certainly
contain a separate code path for accounts whose balance is in a foreign
currency (non-home-currency closing requires FX conversion to determine the
equity adjustment). This path is never exercised in
`tests/integration/test_cli_close_books.py`, which only uses a single-currency
fixture.

A silent failure here would corrupt the retained earnings figure in a
multi-currency book.

## Missing test cases

- Close-books on a book with a USD income account in a CAD home-currency book
- Verify the equity closing entry includes a currency conversion split
- Verify the resulting book balances (assets = liabilities + equity) after closing

## Affected files

- `services/book_closer.py`
- `use_cases/close_books.py`
- `tests/integration/test_cli_close_books.py`

## Suggested fix

Add a `multi_currency_close_books_fixture` that creates income/expense accounts
in a foreign currency, runs `close-books`, and asserts the resulting equity
split has the correct value and commodity.
