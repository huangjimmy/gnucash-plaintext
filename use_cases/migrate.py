"""Q-031: migration discovery, history, and the cheap sidecar cache.

Pure logic only — no Click, no session lifecycle (the CLI layer owns those).

A migration is a versioned file of imperative operation lines (each line is a
CLI invocation minus the book), applied in filename order. History is tracked in
two layers:

  - **in-book** (`options/Plaintext/Migrations`): the source of truth, a JSON
    list of `{id, applied_at, checksum}` that travels with the .gnucash file;
  - **sidecar** (`<book>.migrate-state.json`): a cheap, readable cache stamped
    with the book's size+mtime, so a no-op `migrate` can decide there is nothing
    to do WITHOUT opening the (expensive to read) GnuCash file.
"""
import hashlib
import json
import os
from dataclasses import dataclass

from infrastructure.gnucash.kvp import (
    MIGRATIONS_SECTION,
    MIGRATIONS_SLOT,
    get_book_string_option,
    set_book_string_option,
)


@dataclass
class MigrationFile:
    id: str        # filename stem, e.g. '0002_rename_chequing'
    path: str
    ops: list      # operation lines (comments / blank lines stripped)
    checksum: str  # 'sha256:…' over the raw file bytes


def _checksum(raw: bytes) -> str:
    return 'sha256:' + hashlib.sha256(raw).hexdigest()


def _parse_ops(text: str) -> list:
    ops = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith('#'):
            ops.append(stripped)
    return ops


def discover_migrations(migrations_dir: str) -> list:
    """All `*.txt` migration files in `migrations_dir`, sorted by filename
    (the zero-padded numeric prefix is the version order)."""
    out = []
    for name in sorted(os.listdir(migrations_dir)):
        path = os.path.join(migrations_dir, name)
        if not name.endswith('.txt') or not os.path.isfile(path):
            continue
        with open(path, 'rb') as f:
            raw = f.read()
        out.append(MigrationFile(id=name[:-4], path=path,
                                 ops=_parse_ops(raw.decode('utf-8')),
                                 checksum=_checksum(raw)))
    return out


def compute_pending(files, applied):
    """Split discovered `files` against the `applied` records (list of dicts with
    `id` + `checksum`). Returns (pending_files, checksum_errors) where a checksum
    error means an already-applied migration's file was edited (immutable)."""
    by_id = {a['id']: a for a in applied}
    pending, errors = [], []
    for f in files:
        prev = by_id.get(f.id)
        if prev is None:
            pending.append(f)
        elif prev.get('checksum') != f.checksum:
            errors.append((f.id, prev.get('checksum'), f.checksum))
    return pending, errors


# ── in-book history (source of truth) ──────────────────────────────────────

def read_applied_from_book(book) -> list:
    blob = get_book_string_option(book, MIGRATIONS_SECTION, MIGRATIONS_SLOT)
    if not blob:
        return []
    try:
        data = json.loads(blob)
        return data if isinstance(data, list) else []
    except (ValueError, TypeError):
        return []


def write_applied_to_book(book, applied: list):
    set_book_string_option(book, MIGRATIONS_SECTION, MIGRATIONS_SLOT,
                           json.dumps(applied, ensure_ascii=False, sort_keys=True))


# ── sidecar cache (cheap fast-path) ────────────────────────────────────────

def sidecar_path(book_path: str) -> str:
    return book_path + '.migrate-state.json'


def book_stamp(book_path: str) -> dict:
    st = os.stat(book_path)
    return {'book_size': st.st_size, 'book_mtime': st.st_mtime}


def read_sidecar(book_path: str):
    path = sidecar_path(book_path)
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            return json.loads(f.read())
    except (ValueError, OSError):
        return None


def write_sidecar(book_path: str, applied: list):
    data = book_stamp(book_path)
    data['applied'] = applied
    data['head'] = applied[-1]['id'] if applied else None
    with open(sidecar_path(book_path), 'w') as f:
        f.write(json.dumps(data, indent=2, sort_keys=True))


def sidecar_is_fresh(book_path: str, sidecar: dict) -> bool:
    """True if the sidecar's stamp still matches the book file — i.e. the book
    has not changed since the sidecar was written, so its cached `applied` list
    can be trusted without opening the book.

    The book is not stat'd defensively. `migrate` takes it as a
    `click.Path(exists=True)`, so a book that is not there has already been
    refused by the time this is asked; catching the stat and answering "not
    fresh" would only send an absent book on to be opened, which says the same
    thing several frames later and less clearly.
    """
    if not sidecar:
        return False
    current = book_stamp(book_path)
    return (sidecar.get('book_size') == current['book_size']
            and sidecar.get('book_mtime') == current['book_mtime'])
