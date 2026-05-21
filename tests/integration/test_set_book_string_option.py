"""Integration tests for set_book_string_option.

Background — Q-019 needed to populate Business → Company options on a
test book so the print-invoice / print-bill render path could read them
via `read_book_company_info`. The first attempt used
`qof_instance_set_kvp` (variadic) with a 3-element path; ctypes' x86_64
ABI handling silently no-ops that call for path counts >= 2. The
working implementation switched to `qof_book_set_string_option(book,
"options/<section>/<name>", value)` which is non-variadic and lets the C
side handle GSList construction.

These tests verify the new API is **write-compatible** with what the
GnuCash GUI's File→Properties dialog would have produced — same slot
path, same canonical structure, update-replaces-not-appends, no
duplicates. They use a real GnuCash session (`gnucash.Session`) and a
real .gnucash file on disk; nothing is mocked.
"""
import gzip
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from click.testing import CliRunner

from cli.main import cli

FIXTURES = Path('tests/fixtures')
ACCOUNTS = str(FIXTURES / 'q019_accounts.txt')

_BOOK_NS = 'http://www.gnucash.org/XML/book'
_SLOT_NS = 'http://www.gnucash.org/XML/slot'
_GNC_NS = 'http://www.gnucash.org/XML/gnc'


@pytest.fixture
def fresh_book(tmp_path):
    """A fresh .gnucash file imported from the Q-019 accounts fixture.
    Used as a known starting point with no Business slots."""
    runner = CliRunner()
    gnc = tmp_path / 'book.gnucash'
    r = runner.invoke(cli, ['import', '--new', str(gnc), ACCOUNTS])
    assert r.exit_code == 0, f'accounts: {r.output}'
    time.sleep(1)
    return gnc


def _read_xml(gnc_path):
    """Read the .gnucash file as XML (gzip-aware). Returns the root
    element. Read-only inspection — no writes — so the namespace
    prefix preservation concerns from the renderer test don't apply."""
    with open(gnc_path, 'rb') as f:
        head = f.read(2)
    is_gzip = head == b'\x1f\x8b'
    if is_gzip:
        with gzip.open(gnc_path, 'rb') as f:
            return ET.fromstring(f.read())
    with open(gnc_path, 'rb') as f:
        return ET.fromstring(f.read())


def _walk_slot_value(parent_value_el, key_chain):
    """Walk a chain of slot keys through `<slot:value type="frame">` →
    `<slot>` → `<slot:key>` → `<slot:value>`. Returns the leaf
    `<slot:value>` element, or None if any link is missing.

    This is the exact traversal `read_book_company_info` uses, so a
    slot reachable via this walk is by definition reachable to the
    production reader."""
    cur = parent_value_el
    for want_key in key_chain:
        found = None
        for slot in cur.findall('slot'):
            k = slot.find(f'{{{_SLOT_NS}}}key')
            if k is not None and k.text == want_key:
                found = slot.find(f'{{{_SLOT_NS}}}value')
                break
        if found is None:
            return None
        cur = found
    return cur


def _read_business_slot(gnc_path, key):
    """Return the string value at slots → options → Business → <key>
    or None if absent. Walks the XML directly."""
    root = _read_xml(gnc_path)
    book = root.find(f'{{{_GNC_NS}}}book')
    if book is None:
        return None
    slots = book.find(f'{{{_BOOK_NS}}}slots')
    if slots is None:
        return None
    # `slots` is the book's <book:slots>; its children are <slot>s, not
    # a <slot:value>. Wrap in a synthetic parent to reuse _walk_slot_value.
    fake_parent = ET.Element('value')
    fake_parent.extend(slots.findall('slot'))
    leaf = _walk_slot_value(fake_parent, ['options', 'Business', key])
    if leaf is None:
        return None
    return (leaf.text or '').strip()


def _count_business_slot_occurrences(gnc_path, key):
    """Count how many times the slot appears at the canonical path.
    Verifies update-semantics: a second write with the same key must
    REPLACE the existing slot, not append a duplicate. Returns 0 if
    the slot is absent."""
    root = _read_xml(gnc_path)
    book = root.find(f'{{{_GNC_NS}}}book')
    if book is None:
        return 0
    slots = book.find(f'{{{_BOOK_NS}}}slots')
    if slots is None:
        return 0
    # Find every <slot:key>options</slot:key> at the top level, descend
    # into its frame, find every <slot:key>Business</slot:key>, descend
    # again, count <slot:key>{key}</slot:key>.
    count = 0
    for options_slot in slots.findall('slot'):
        k = options_slot.find(f'{{{_SLOT_NS}}}key')
        if k is None or k.text != 'options':
            continue
        options_value = options_slot.find(f'{{{_SLOT_NS}}}value')
        if options_value is None:
            continue
        for biz_slot in options_value.findall('slot'):
            bk = biz_slot.find(f'{{{_SLOT_NS}}}key')
            if bk is None or bk.text != 'Business':
                continue
            biz_value = biz_slot.find(f'{{{_SLOT_NS}}}value')
            if biz_value is None:
                continue
            for field_slot in biz_value.findall('slot'):
                fk = field_slot.find(f'{{{_SLOT_NS}}}key')
                if fk is not None and fk.text == key:
                    count += 1
    return count


def _write_business_options(gnc_path, *pairs):
    """Open a session, call set_book_string_option once per (key, value)
    pair, save, close. Returns a list of booleans matching the helper's
    success result per pair.

    Batched in a single session because GnuCash's backup-file naming
    uses YYYYMMDDHHMMSS — two opens-save-close cycles in the same
    second collide on the backup filename and the second save fails
    with ERR_FILEIO_BACKUP_ERROR. Real callers (the GnuCash GUI, the
    print-bill setup helper) also batch their writes for the same
    reason."""
    import gnucash

    from infrastructure.gnucash.kvp import set_book_string_option
    sess = gnucash.Session(f'xml://{gnc_path}')
    try:
        results = [
            set_book_string_option(sess.book, 'Business', key, value)
            for key, value in pairs
        ]
        sess.save()
    finally:
        sess.end()
    return results


# ── Slot path is what read_book_company_info reads ────────────────

def test_writes_land_at_options_business_key(fresh_book):
    """The slot written by set_book_string_option must appear at
    options → Business → <key> in the saved XML — the exact path the
    `read_book_company_info` reader walks. If the slot landed
    anywhere else (e.g. a flat key like `options/Business/Company
    Name`, or under a different parent frame), the renderer's "From"
    block would silently show empty values, which is exactly the
    silent-compatibility-break this test prevents."""
    assert all(_write_business_options(fresh_book, ('Company Name', 'Acme')))
    val = _read_business_slot(fresh_book, 'Company Name')
    assert val == 'Acme', (
        f'expected slot at options/Business/Company Name with value '
        f'"Acme"; got {val!r}'
    )


def test_renderer_reader_sees_the_written_slot(fresh_book):
    """End-to-end via the production reader. If
    read_book_company_info returns the value, every downstream
    consumer (HTML, plaintext, future API) gets it too."""
    from services.invoice_renderer import read_book_company_info
    assert all(_write_business_options(
        fresh_book,
        ('Company Name',          'Acme Plaintext Co.'),
        ('Company Email Address', 'hi@acme.test'),
        ('Company ID',            '12345RT0001'),
    ))
    info = read_book_company_info(str(fresh_book))
    assert info['name']  == 'Acme Plaintext Co.'
    assert info['email'] == 'hi@acme.test'
    assert info['id']    == '12345RT0001'


# ── Update semantics: second write replaces first ──────────────────

def test_second_write_replaces_first_value(fresh_book):
    """Setting the same key twice with different values: the second
    value wins, and the slot appears exactly once. A duplicate would
    mean GnuCash's own writes (from File→Properties) would silently
    create dual slots on the same book — confusing, and the reader's
    "first match wins" semantics would pick the wrong one.

    Sleeps between session writes because GnuCash's backup-file naming
    uses a 1-second-granularity timestamp; consecutive saves within
    the same second collide. Real callers (GUI users, batched test
    helpers) don't hit this because they batch writes in one session."""
    assert _write_business_options(fresh_book, ('Company Name', 'First Name'))[0]
    first_value = _read_business_slot(fresh_book, 'Company Name')
    assert first_value == 'First Name'

    time.sleep(1.1)
    assert _write_business_options(fresh_book, ('Company Name', 'Second Name'))[0]
    second_value = _read_business_slot(fresh_book, 'Company Name')
    assert second_value == 'Second Name', (
        f'expected second write to replace; got {second_value!r}'
    )

    # The critical compatibility check: exactly ONE Company Name slot.
    n = _count_business_slot_occurrences(fresh_book, 'Company Name')
    assert n == 1, (
        f'expected exactly 1 Company Name slot after two writes; '
        f'found {n}. Duplicates indicate set_book_string_option is '
        f'appending instead of replacing.'
    )


def test_multiple_distinct_keys_coexist(fresh_book):
    """Setting different keys (Company Name + Company Email Address +
    Company ID) puts each at its own slot under the same Business
    frame — verifying the function doesn't accidentally overwrite
    sibling fields."""
    assert all(_write_business_options(
        fresh_book,
        ('Company Name',          'Acme'),
        ('Company Email Address', 'hi@acme.test'),
        ('Company ID',            '12345RT0001'),
    ))
    assert _read_business_slot(fresh_book, 'Company Name')          == 'Acme'
    assert _read_business_slot(fresh_book, 'Company Email Address') == 'hi@acme.test'
    assert _read_business_slot(fresh_book, 'Company ID')            == '12345RT0001'

    for key in ('Company Name', 'Company Email Address', 'Company ID'):
        n = _count_business_slot_occurrences(fresh_book, key)
        assert n == 1, f'expected exactly 1 slot for {key!r}; found {n}'


# ── Non-ASCII value encoding ─────────────────────────────────────

def test_non_ascii_value_round_trips_utf8(fresh_book):
    """Values containing CJK / accented characters must encode as
    UTF-8 in the XML and read back unchanged. The user's books span
    HKD / CNY / JPY locales, so vendor / company names in those
    scripts must survive the write."""
    assert _write_business_options(
        fresh_book,
        ('Company Name', '香港有限公司 — Société Générale'),
    )[0]
    val = _read_business_slot(fresh_book, 'Company Name')
    assert val == '香港有限公司 — Société Générale', (
        f'non-ASCII value must round-trip via UTF-8; got {val!r}'
    )


# ── Pre-existing slots are preserved ─────────────────────────────

def test_setting_new_key_preserves_unrelated_slots(fresh_book):
    """Setting Company Name on a book that already has Company Email
    Address must not wipe the email slot. Real-world flow: the user
    fills in their Business options field-by-field over multiple
    sessions; each set call must be additive. The session-boundary
    sleep handles the backup-naming collision documented above."""
    assert _write_business_options(
        fresh_book, ('Company Email Address', 'hi@acme.test'),
    )[0]
    time.sleep(1.1)
    assert _write_business_options(
        fresh_book, ('Company Name', 'Acme'),
    )[0]
    # Both still present.
    assert _read_business_slot(fresh_book, 'Company Email Address') == 'hi@acme.test'
    assert _read_business_slot(fresh_book, 'Company Name')          == 'Acme'
