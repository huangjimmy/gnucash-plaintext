---
id: Q-031
title: No batch operations or migrations — every surgical command is one-op-per-save
category: feature
severity: enhancement
status: closed
---

## Problem

Every surgical CLI command (`rename-account`, `unapply-payment`, `delete-*`) opens the book, does **one** mutation, saves, and closes. Each save writes a GnuCash backup whose filename carries a **second-resolution** timestamp, so two saves in the same second collide (`ERR_FILEIO_BACKUP_ERROR`) — back-to-back operations must be ≥1s apart. Renaming 200 accounts therefore costs **200+ seconds**.

There was also no migration concept: no way to express an ordered set of operations, apply them as a unit, and **track which have been applied** — the database-migration model. Users want to version their chart-of-accounts evolution and replay it reproducibly, and to know "what version is this book on?" cheaply.

Plaintext `import` doesn't cover this: it is **declarative** state-sync, and can't express an imperative "rename X → Y" (renaming an account in a declarative file would mean rewriting every transaction that references it by path — the reason `rename-account` is a command, not a directive). Migrations are imperative and ordered — a different paradigm.

## Fix

A `migrate` command that applies versioned migrations to a book in a **single save**.

```
gnucash-plaintext migrate <book> <migrations-dir> [--dry-run] [--status] [--verify]
```

### Migration files are operation lines (CLI syntax)

A migration file (`migrations/0002_rename_chequing.txt`) is an ordered list of operation lines — each uses CLI syntax (an operation command + args, minus the book), parsed by Click itself via `shlex.split` + `command.main(args=…, standalone_mode=False)`. One vocabulary for interactive use and migrations; the file doubles as runnable documentation.

A migration line is **not** "any CLI command", though. Operations come from a strict allowlist (`_OPERATIONS`) of mutating, batch-aware commands. Read/meta commands — `export`, `import`, `print-invoice`, and `migrate` itself — are intentionally excluded, so a migration only changes the target book and **migrations cannot nest**. Each refusal is explicit: a `migrate` line says migrations don't nest; any other non-operation says it is not a migration operation and lists the ones that are.

```
# 0002_rename_chequing
rename-account --guid 51359958977a4ca88ec927c2958b3d8b --to "Assets:Current:Chequing"
set-book-key --key schema_version --value 2
```

### Session ownership moves up → one save

Each operation command now checks the Click context for a `BatchSession` (`cli/_batch.py`): present (under `migrate`) → it mutates that shared, already-open book and records the change, leaving the single save to the owner; absent → it runs standalone exactly as before (open, mutate, save, close). The book argument became optional on these commands. The use cases were already book-in / no-save, so this is a CLI-layer change only. 200 renames ⇒ **1 save**.

### Two-layer history → cheap no-op

- **In-book, source of truth:** `options/Plaintext/Migrations` — a JSON list of `{id, applied_at, checksum}`, the "schema_migrations table" that travels with the `.gnucash` file. Written during the apply (the book is already open + saving).
- **Sidecar cache:** `<book>.migrate-state.json` — readable JSON stamped with the book's size+mtime. A no-op `migrate` reads the sidecar + `stat`s the book (cheap) and, if the stamp still matches and nothing is pending, prints `up to date … book not opened` and **never opens the GnuCash file**. The sidecar is a regenerable cache; the in-book history wins whenever the stamp is stale (book moved/reverted), and `--verify` bypasses the cache.

### Semantics

- **Atomic:** all pending migrations apply to one book; if any operation fails, `migrate` aborts **before** saving — nothing persists, nothing is recorded (`… no changes were saved`).
- **Immutable history:** editing an already-applied migration changes its checksum and is rejected (Flyway-style), pointing the user to write a new migration.
- **Two version layers:** the tool tracks *which files ran*; a migration can also `set-book-key --key schema_version --value N` to stamp the user's **own** semantic version (Q-029 custom-key store, round-trips via the `company` directive). The user-facing "what version am I on?" is answerable from the sidecar with zero book reads.
- **Extensible vocabulary:** any batch-aware command registered in `_OPERATIONS` is a valid migration operation. v1 ships `rename-account` and `set-book-key`.

## Files touched

| File | Change |
|---|---|
| `cli/_batch.py` | `BatchSession` + `current_batch(ctx)` — shared open book + change log for batched ops. |
| `cli/rename_account_cmd.py` | Batch-aware: optional book, operates on `ctx.obj.book` under a batch, else standalone. |
| `cli/set_book_key_cmd.py`, `use_cases/set_book_key.py` | New `set-book-key` op (custom book key / version key). |
| `use_cases/migrate.py` | Discovery, checksums, in-book history, sidecar read/write + freshness. |
| `cli/migrate_cmd.py` | The `migrate` command — fast path, authoritative apply with one save, atomicity, immutability, dry-run/status. |
| `infrastructure/gnucash/kvp.py` | `MIGRATIONS_SECTION` / `MIGRATIONS_SLOT` for the in-book history. |
| `cli/main.py`, `README.md` | Register + document `migrate` and `set-book-key`. |

## Tests

`tests/integration/test_migrate.py`: a batch of renames + a version stamp applied in one run (`1 save`); a re-run is a no-op that doesn't open the book (sidecar fast path); an operation failure aborts atomically with the book unchanged and nothing recorded; an edited applied migration is rejected as immutable; `--dry-run` changes nothing; an unknown operation is rejected; the `schema_version` key round-trips through export. Passing on GnuCash 3.8 and 5.10; the Q-030 `rename-account` standalone tests still pass (the refactor is backward-compatible).

## Related issues

- **Q-030** — `rename-account`, the first batch-aware operation.
- **Q-029** — the custom book-key store reused for `set-book-key` and the migration history slot.

---

**Created**: 2026-06-26
