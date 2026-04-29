---
id: S-002
title: Broad except-Exception in gzip fallback masks real errors
category: security
severity: low
status: open
---

## Problem

`services/invoice_renderer.py:22-26` catches `Exception` broadly when
attempting to open the `.gnucash` file as gzip:

```python
try:
    with _gz.open(file_path, 'rb') as f:
        xml_root = xml.etree.ElementTree.parse(f).getroot()
except Exception:
    xml_root = xml.etree.ElementTree.parse(file_path).getroot()
```

This silently swallows:
- `PermissionError` — user cannot read the file; retried as uncompressed,
  which also fails with a different (confusing) error
- `MemoryError` — very large file exhausts memory; silently retried
- `FileNotFoundError` — path does not exist; same issue
- Any XML parse error from within the gzip stream

The user receives no indication of what actually went wrong.

## Suggested fix

Replace the broad catch with specific exceptions:

```python
import gzip

try:
    with gzip.open(file_path, 'rb') as f:
        xml_root = xml.etree.ElementTree.parse(f).getroot()
except (gzip.BadGzipFile, EOFError):
    xml_root = xml.etree.ElementTree.parse(file_path).getroot()
```

`gzip.BadGzipFile` is raised when the file is not gzip-compressed (Python 3.8+).
`EOFError` covers truncated gzip streams. All other exceptions (permissions,
memory, missing file) should propagate to the caller unchanged.

Note: `gzip.BadGzipFile` was added in Python 3.8. Since the project targets
Python ≥ 3.7 (per `pyproject.toml`), add a `try/except ImportError` fallback
to `OSError` for 3.7 compatibility, or raise the minimum to 3.8.
