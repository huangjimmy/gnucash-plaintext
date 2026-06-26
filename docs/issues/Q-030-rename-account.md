---
id: Q-030
title: No way to rename an account; the full round-trip can't express it
category: feature
severity: enhancement
status: closed
---

## Problem

GnuCash lets you rename an account — including giving it a new name under a different parent — keeping all its transactions. Our plaintext had no way to do this.

The full export/import round-trip can't express it cleanly. Every transaction split names its account by **full path** (`account: "Assets:Bank:Checking"`), so renaming an account through the text would require rewriting *every* transaction line that references it — miss one and the file is inconsistent (a "breaking" edit). Worse, editing only the `open` directive's path while leaving the `guid:` would make the importer try to create a new account with an in-use GUID, which errors; with no `guid:` it silently creates a duplicate. So account restructuring was effectively impossible via plaintext.

## Fix

A surgical CLI command, `rename-account`, that mutates the live book directly. GnuCash keeps splits attached to accounts **by reference, not by name**, so renaming the account leaves every split intact; the next export simply prints the new path wherever the account appears — no transaction lines to hand-edit.

```
gnucash-plaintext rename-account <book> --guid <account-guid> --to "<new name>"
```

It is one operation — rename. The account is identified by **GUID** (stable since Q-027), never by its old name — the name is precisely what changes. `--to` is the account's new full name, so a single rename can change the leaf, the parent, or both at once. There is no separate "move": placing the account under a different parent is just what happens when the new name names a different parent.

- bare leaf `--to "Chequing"` → `Assets:Bank:Checking` becomes `Assets:Bank:Chequing` (same parent);
- full path `--to "Assets:Checking"` → new parent `Assets`, same leaf;
- full path `--to "Assets:Cash:Petty"` → new parent **and** new leaf, together.

Mechanically: find by GUID → `SetName(leaf)` and, only if the parent differs, `new_parent.append_child(account)`.

### Guards — each refusal gives an explicit, detailed message and leaves the book untouched

- `bad_guid` — `--guid` is not a valid GUID (names the value, points to `export-accounts`).
- `not_found` — no account in the book has that GUID.
- `parent_not_found` — a named parent in `--to` doesn't exist.
- `cycle` — the new parent is the account itself or one of its descendants (would make the account its own ancestor).
- `name_taken` — the target parent already has a child with the new leaf name.
- `unchanged` — `--to` equals the current name; nothing written.

Names in messages and path resolution use the plaintext colon convention; GnuCash's own `get_full_name()` uses the engine separator (`.` in a headless book), so the use case builds colon names itself.

## Files touched

| File | Change |
|---|---|
| `use_cases/rename_account.py` | `execute_rename` — GUID lookup, `--to` parsing, guards, rename/reparent. |
| `cli/rename_account_cmd.py` | `rename-account` command. |
| `cli/main.py` | Register the command. |
| `README.md` | Document `rename-account`. |

## Tests

`tests/integration/test_rename_account.py` (fixture `tests/fixtures/rename_account_book.txt` — accounts + a transaction touching the renamed account):

- all three rename shapes — leaf only, parent only, parent **and** leaf together — each preserve the **GUID**;
- the transaction's split **follows** the account — after a rename the export prints the new path on the split and the old path appears nowhere;
- **full export → import → export roundtrip** after a rename (all three shapes) reproduces the renamed book byte-for-byte in a fresh book, with the account at its new path, same GUID, split intact — proving the rename leaves the book self-consistent;
- guards: malformed GUID, unknown GUID, cycle, name collision, unknown new parent each error with an explicit message and leave the book unchanged; a no-op reports `unchanged`. The failure tests assert the message content.
- Passing on GnuCash 3.8 and 5.10.

## Related issues

- **Q-027** — account GUID preservation, which makes GUID-based identity reliable across roundtrips.

---

**Created**: 2026-06-26
