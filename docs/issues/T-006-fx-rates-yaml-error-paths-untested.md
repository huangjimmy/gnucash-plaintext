---
id: T-006
title: FX rates YAML error paths are untested
category: tests
severity: low
status: open
---

## Problem

`services/fx_rates.py` loads a user-supplied YAML file but none of the failure
modes are tested:

- File does not exist
- File is not valid YAML (syntax error)
- File is valid YAML but missing the expected currency pair
- Value is non-numeric (e.g. `"n/a"` instead of `1.25`)

Because these are silent or uncaught, a misconfigured FX file produces a
confusing `KeyError` or `TypeError` deep in the conversion stack rather than
a user-facing message pointing at the YAML file.

## Affected files

- `services/fx_rates.py`
- `tests/unit/services/test_fx_rates.py`

## Suggested fix

Extend `test_fx_rates.py` with parametrised error cases using `tmp_path` to
write bad YAML files. Each case should assert a specific, user-readable
exception message is raised (not a bare `KeyError`/`TypeError`).
