---
id: Q-034
title: Uncached ctypes library loads and account-name walks degrade import performance linearly with transaction count
category: bug
severity: medium
status: open
---

## Problem

`load_gnc_engine()` has no caching. Every call sets `restype`/`argtypes` on ~70 ctypes function pointers and verifies ~20 more — pure-Python work that only needs to happen once. The function is called from the hot path `_read_owner_from_transaction()` which runs for **every transaction** during signature computation in `TransactionMatcher.get_signature()`.

A typical import with duplicate detection calls `load_gnc_engine()` O(n) times where n is the number of transactions. Each call repeats ~90 ctypes attribute assignments. For a book with 1000 transactions, that's ~90,000 fully redundant Python operations.

Secondary: `TransactionMatcher._get_account_full_name()` walks the account parent chain for every split every time it's called, and `get_signature()` recomputes from GnuCash API calls even when the same transaction object is checked across multiple matcher calls.

## Cause

1. `infrastructure/gnucash/engine.py:load_gnc_engine()` — no caching. Every call runs `_setup_lib_restypes()` + `verify_ctypes_functions()` which together configure and validate ~90 function pointers. The dlopen promotion is a fast no-op for already-loaded libs; the real cost is those ~90 Python attribute assignments repeated per call.

2. `services/transaction_matcher.py:_get_account_full_name()` — no caching. Walks `get_parent()` chain for every account every time it appears in a split.

3. `services/transaction_matcher.py:get_signature()` — no caching. The same transaction's signature is recomputed from scratch each time it passes through `find_duplicates`, `has_duplicate_signature`, or `get_duplicate_count`.

Note: `kvp.py:_load_gnc_engine()` is uncached too, but its per-call cost is negligible — it only does two dlopen calls (cheap refcount bumps) without any type-setup or verification overhead.

## Fix

1. **`engine.py`**: `@functools.lru_cache(maxsize=1)` on `load_gnc_engine()`. The function is pure — always returns the same CDLL handle.

2. **`kvp.py`**: `@functools.lru_cache(maxsize=1)` on `_load_gobject()`. The existing module-level `_gobj` guard already caches, but `lru_cache` is a belt-and-suspenders hardening in case the global is reset.

3. **`transaction_matcher.py`**:
   - `self._account_name_cache` dict checked in `_get_account_full_name()` before walking the parent chain.
   - `transaction._cached_signature` attribute to avoid recomputing the same transaction's signature across multiple matcher calls.

## Related

- **Q-016** — full GUID emission (the GUID used as alternative cache key was added there)
- **Q-020** — num-only roundtrip and import dedup signature (the signature format this optimizes)

---

**Created**: 2026-07-01
