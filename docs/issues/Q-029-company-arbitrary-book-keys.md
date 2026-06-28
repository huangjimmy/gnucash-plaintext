---
id: Q-029
title: company directive only round-trips known seller-identity keys; no way to store arbitrary book-level data
category: quality
severity: medium
status: closed
---

## Problem

The `company` directive (Q-028) round-trips a fixed set of GnuCash Business options — name, contact, Company ID, GST/PST, address, phone, fax, email, url. It is the only book-level directive, and it only understands those known keys. There is no way to record other book-level information through plaintext import — a fiscal year end, a province, an entity type (e.g. "T2 Corporation"), a ledger locale.

The CLI can already set arbitrary book string options internally (`set_book_string_option` / `get_book_string_option`), but that capability is not exposed to `import`. Every other directive — `customer`, `vendor`, `account` — already accepts arbitrary keys beyond its known ones and round-trips them as custom metadata; `company` did not.

Note on accounting period specifically: GnuCash's Start Date / End Date of the accounting period are an **application preference** (GSettings), not stored in the `.gnucash` file. So there is no native book slot to map a fiscal year to — it can only be kept as our own book-level data.

## Fix

The `company` directive now accepts **any** key. Known keys map to GnuCash Business option slots and render in the seller block as before. **Any other key** is kept as book-level custom metadata that round-trips but is never rendered — private book data (a customer has no business seeing the seller's fiscal year).

```
company
  name: "Acme Inc."
  id: "123456789RT0001"
  gst: "123456789RT0001"
  fiscal_year_end: "12-31"
  province: "British Columbia"
  entity_type: "T2 Corporation"
  ledger_locale: "en_CA"
```

### Storage

All custom (non-Business) keys are serialised together as one JSON blob in a single dedicated book option slot, `options/Plaintext/Custom Metadata`, via the existing `set_book_string_option`. One fixed slot (rather than one slot per key) means the exporter reads it back by a known path — avoiding cross-version KVP key-enumeration, which the bindings make unreliable. The section is private to this tool, so it never collides with GnuCash's own Business options. The object-level `set_custom_metadata` path was tried first and does **not** persist on the book object (verified empirically — it read back empty), which is why the book-option path is used.

The directive is a partial **upsert** of custom keys (see the reopened section below): keys it names are set, keys it omits are preserved, and a key given the null value (`#None`) is removed.

## Reopened (2026-06-28): partial import must not delete custom keys

The original implementation **replaced** the whole custom-metadata blob whenever the directive carried any custom key — a deliberate "mirror `set_custom_metadata`" choice that was wrong and was not flagged. It broke the directive's own documented contract ("an absent field is left as-is", honoured by the known-Business-field tier) and was inconsistent with `set-book-key` (Q-031), which merges. The result: a partial, hand-written `company` directive that set one custom key **silently deleted every other custom key** the book held (a user's `schema_version`, `entity_type`, etc.). Known Business fields were unaffected — so the deletion hit exactly the keys users hand-edit.

**Fix:** the custom-key tier now follows **JSON Merge Patch** semantics (RFC 7386) — `key: value` upserts, `key: #None` removes, an omitted key is preserved. It is implemented in one shared helper, `merge_book_custom_metadata` in `infrastructure/gnucash/kvp.py`, used by **both** `import_company` and `set-book-key`, so the `company` directive and `set-book-key` provably behave the same. A full export → import round-trip is unaffected (the export emits every key, so the upsert restores all of them).

## Files touched

| File | Change |
|---|---|
| `infrastructure/gnucash/kvp.py` | `COMPANY_CUSTOM_SECTION` / `COMPANY_CUSTOM_SLOT` constants for the dedicated custom-metadata slot. |
| `services/gnucash_importer.py` | `import_company` collects every non-Business, non-address key into a JSON blob and writes it via `set_book_string_option`. |
| `use_cases/export_business_objects.py` | `_export_company` reads the blob back and emits each custom key as its own `key: value` line (sorted, stable round-trip). |
| `README.md` | Document arbitrary custom keys on the `company` directive. |

## Tests

`tests/integration/test_company_custom_book_keys.py` (fixture `tests/fixtures/company_custom_keys.txt`):

- Custom keys export with their exact values alongside the known fields.
- Double-roundtrip (import → export → fresh import → export) keeps the whole `company` block byte-identical, custom keys included.
- Custom keys and their distinctive values do **not** appear in rendered `print-invoice` / `print-bill` output (plaintext and HTML), while a known field (GST) still renders — proving the seller block runs but private book data stays out of it.
- Passing on GnuCash 3.8 and 5.10.

## Related issues

- **Q-028** — the `company` directive and the Business string-option round-trip this extends.

---

**Created**: 2026-06-17
