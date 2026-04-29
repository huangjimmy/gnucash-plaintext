---
id: Q-001
title: Inconsistent exception types across CLI commands
category: quality
severity: low
status: open
---

## Problem

CLI commands use three different ways to signal errors to the user:

| Pattern | Example location | User sees |
|---|---|---|
| `raise click.UsageError(msg)` | `invoice_print_cmd.py:41` | `Error: msg` (exit 2) |
| `raise click.ClickException(msg)` | various | `Error: msg` (exit 1) |
| `raise ValueError(msg)` | some services | Python traceback (exit 1) |
| `click.echo(...)` + `sys.exit(1)` | some commands | Custom text (exit 1) |

The inconsistency means:
- Error exit codes differ between commands (1 vs 2), breaking scripted callers
- Some errors show a Python traceback that leaks internal implementation details
- The user experience differs depending on which command was used

## Suggested fix

Establish and enforce a convention:

- **User input errors** (wrong file, missing ID, invalid date format):
  `raise click.UsageError(msg)` → exit 2
- **Runtime errors** (GnuCash file corrupt, write failed):
  `raise click.ClickException(msg)` → exit 1
- **Internal errors** (unexpected exception): let them propagate naturally
  (or wrap with `click.ClickException` and include the original message)

Exceptions raised by services should not reach the CLI as bare Python
exceptions. Each CLI command's main body should have a top-level
`except (SpecificError, AnotherError) as e: raise click.ClickException(str(e))`.

## Affected files

All files in `cli/`.
