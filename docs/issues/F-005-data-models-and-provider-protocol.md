---
id: F-005
title: "Statement import: data models and StatementProvider protocol"
category: feature
severity: high
status: open
branch: feature/statement-import-pipeline
---

## What to build

`infrastructure/pdf/__init__.py` — package init (empty)

`infrastructure/pdf/standard_tx.py`:
- `Split` dataclass: `account: str`, `amount: Decimal`
- `StandardTransaction` dataclass: `post_date: date`, `description: str`,
  `currency: str`, `splits: list[Split]` (at least 2),
  `source_pdfs: list[str]`, `guid: str | None = None`

`infrastructure/pdf/provider.py`:
- `StatementProvider` as `typing.Protocol` marked `@runtime_checkable`
- Fields: `autopay_source: dict[str, str]`
- Methods: `can_handle(filename: str) -> bool`, `parse(path: str) -> list[StandardTransaction]`

No PDF parsing logic. No GnuCash types. Pure data model and interface contract.

## Unit tests

`tests/unit/infrastructure/test_standard_tx.py`:
- `Split` constructed with `Decimal` — correct value stored
- `Split` with `float` passed — dataclass does NOT coerce; test asserts
  `not isinstance(split.amount, Decimal)` to document non-coercion behaviour
  (implementor must add `__post_init__` or a validator if coercion is wanted)
- `StandardTransaction` defaults: `guid is None`, `source_pdfs == []`
  (use `field(default_factory=list)` for `source_pdfs` — bare `[]` is
  rejected by Python dataclasses as a mutable default)
- `StandardTransaction` with 3 splits constructs correctly (multi-category expense)
- A concrete class satisfying `StatementProvider` fields and methods passes
  `isinstance(provider, StatementProvider)`
- A class missing `can_handle` fails the protocol check

## Integration tests

`tests/integration/infrastructure/test_standard_tx.py`:
- `from infrastructure.pdf.standard_tx import StandardTransaction, Split` succeeds
  inside Docker environment (catches import errors in GnuCash container)
- `StandardTransaction` with CJK description (`"自動轉賬"`) — no encoding error
  on construction or `repr()`

## Acceptance

All unit and integration tests pass. `Split.amount` is `Decimal` and
`StatementProvider` is `runtime_checkable`.

## Files

- `infrastructure/pdf/__init__.py` (new)
- `infrastructure/pdf/standard_tx.py` (new)
- `infrastructure/pdf/provider.py` (new)
- `tests/unit/infrastructure/test_standard_tx.py` (new)
- `tests/integration/infrastructure/test_standard_tx.py` (new)
