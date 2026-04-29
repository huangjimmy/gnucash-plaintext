---
id: F-001
title: QFX/OFX dependency declared but feature not implemented
category: feature
severity: medium
status: open
---

## Problem

`pyproject.toml` lists `ofxparse>=0.21` as a runtime dependency and
`beautifulsoup4>=4.9` is noted with the comment "Future QFX parsing
alternative". However:

- `infrastructure/qfx/__init__.py` is completely empty
- There is no CLI command for QFX/OFX import in `cli/main.py`
- The README makes no mention of QFX support

Every user who installs the package pays the cost of these dependencies
(download size, import time, potential version conflicts) for zero delivered
functionality.

## Options

### Option A — Remove the stubs (recommended short term)

Remove `ofxparse` and `beautifulsoup4` from `[project.dependencies]` and
delete `infrastructure/qfx/__init__.py`. Add a note in `ROADMAP.md` or a
GitHub issue that QFX support is planned.

### Option B — Implement QFX import

Implement a `qfx-import` CLI command that:
1. Parses a `.qfx`/`.ofx` file via `ofxparse`
2. Produces a plaintext ledger file (or imports directly into `.gnucash`)
3. Maps OFX transaction types to GnuCash account types

This would restore a feature that existed conceptually in the v0.1 design
(per `migration_log.md`).

## Affected files

- `pyproject.toml`
- `infrastructure/qfx/__init__.py`
