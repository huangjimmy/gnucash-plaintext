"""
Unit tests for services/invoice_renderer.py — read_book_company_info.

Pure Python — no GnuCash session required.  We write minimal XML files that
mirror the GnuCash book slot structure and verify the function extracts fields
correctly.
"""

import gzip
import os
import tempfile
import xml.etree.ElementTree as ET

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NS = {
    'gnc':  'http://www.gnucash.org/XML/gnc',
    'book': 'http://www.gnucash.org/XML/book',
    'slot': 'http://www.gnucash.org/XML/slot',
}

_GNC  = '{http://www.gnucash.org/XML/gnc}'
_BOOK = '{http://www.gnucash.org/XML/book}'
_SLOT = '{http://www.gnucash.org/XML/slot}'


def _slot_el(key: str, value: str, value_type: str = 'string') -> ET.Element:
    s = ET.Element('slot')
    k = ET.SubElement(s, f'{_SLOT}key')
    k.text = key
    v = ET.SubElement(s, f'{_SLOT}value')
    v.set('type', value_type)
    v.text = value
    return s


def _frame_slot(key: str, children) -> ET.Element:
    """Build a slot whose value is a 'frame' containing *children* slots."""
    s = ET.Element('slot')
    k = ET.SubElement(s, f'{_SLOT}key')
    k.text = key
    v = ET.SubElement(s, f'{_SLOT}value')
    v.set('type', 'frame')
    for child in children:
        v.append(child)
    return s


def _build_gnucash_xml(company: dict) -> bytes:
    """
    Build a minimal .gnucash XML document with the given company fields.

    company keys: name, id, phone, email, url, address (multi-line string)
    """
    root = ET.Element('gnc-v2')
    book = ET.SubElement(root, f'{_GNC}book')
    book.set('version', '2.0.0')
    book_slots = ET.SubElement(book, f'{_BOOK}slots')

    biz_children = []
    field_map = {
        'name':    'Company Name',
        'id':      'Company ID',
        'phone':   'Company Phone Number',
        'email':   'Company Email Address',
        'url':     'Company Website URL',
        'address': 'Company Address',
    }
    for attr, gnc_key in field_map.items():
        if attr in company:
            biz_children.append(_slot_el(gnc_key, company[attr]))

    options_slot = _frame_slot('options', [_frame_slot('Business', biz_children)])
    book_slots.append(options_slot)

    return ET.tostring(root, encoding='unicode').encode('utf-8')


def _write_xml_file(xml_bytes: bytes, compress: bool = False) -> str:
    """Write xml_bytes to a temp file, optionally gzip-compressed. Returns path."""
    suffix = '.gnucash'
    fd, path = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    if compress:
        with gzip.open(path, 'wb') as f:
            f.write(xml_bytes)
    else:
        with open(path, 'wb') as f:
            f.write(xml_bytes)
    return path


# ---------------------------------------------------------------------------
# Tests: read_book_company_info with an uncompressed file
# ---------------------------------------------------------------------------

class TestReadBookCompanyInfoUncompressed:

    def test_reads_company_name(self):
        from services.invoice_renderer import read_book_company_info
        xml_bytes = _build_gnucash_xml({'name': 'Acme Corp'})
        path = _write_xml_file(xml_bytes, compress=False)
        try:
            info = read_book_company_info(path)
            assert info['name'] == 'Acme Corp'
        finally:
            os.unlink(path)

    def test_reads_all_company_fields(self):
        from services.invoice_renderer import read_book_company_info
        xml_bytes = _build_gnucash_xml({
            'name':    'Widget Ltd',
            'id':      'BN-12345',
            'phone':   '+1-800-555-0100',
            'email':   'billing@widget.example',
            'url':     'https://widget.example',
            'address': '123 Main St\nSuite 4\nToronto\nON M5V 1A1',
        })
        path = _write_xml_file(xml_bytes, compress=False)
        try:
            info = read_book_company_info(path)
            assert info['name']  == 'Widget Ltd'
            assert info['id']    == 'BN-12345'
            assert info['phone'] == '+1-800-555-0100'
            assert info['email'] == 'billing@widget.example'
            assert info['url']   == 'https://widget.example'
            assert info['address'] == ['123 Main St', 'Suite 4', 'Toronto',
                                       'ON M5V 1A1']
        finally:
            os.unlink(path)

    def test_missing_slots_return_empty_strings(self):
        """When the book has no Business slots the result is all empty strings."""
        from services.invoice_renderer import read_book_company_info
        xml_bytes = _build_gnucash_xml({})
        path = _write_xml_file(xml_bytes, compress=False)
        try:
            info = read_book_company_info(path)
            assert info['name']  == ''
            assert info['phone'] == ''
            assert info['address'] == []
        finally:
            os.unlink(path)

    def test_the_address_is_as_long_as_the_book_wrote_it(self):
        """However many lines that is — two here, six below.

        Four keys padded with '' was the shape before, and it could not say
        anything but four: the slot is one free-text field and File →
        Properties → Business takes as many lines as are typed into it, so a
        fifth was read by nobody and printed nowhere.
        """
        from services.invoice_renderer import read_book_company_info
        xml_bytes = _build_gnucash_xml({'address': 'Line 1\nLine 2'})
        path = _write_xml_file(xml_bytes, compress=False)
        try:
            assert read_book_company_info(path)['address'] == ['Line 1',
                                                               'Line 2']
        finally:
            os.unlink(path)

    def test_and_a_line_past_the_fourth_is_kept(self):
        from services.invoice_renderer import read_book_company_info
        xml_bytes = _build_gnucash_xml({
            'address': '42 Example Street\nUnit 5\nSpringfield ON\n'
                       'A1A 1A1\nCANADA\nAttn: Accounts Payable'})
        path = _write_xml_file(xml_bytes, compress=False)
        try:
            assert read_book_company_info(path)['address'][-2:] == [
                'CANADA', 'Attn: Accounts Payable']
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# Tests: read_book_company_info with a gzip-compressed file
# ---------------------------------------------------------------------------

class TestReadBookCompanyInfoCompressed:

    def test_reads_company_name_from_gzip(self):
        from services.invoice_renderer import read_book_company_info
        xml_bytes = _build_gnucash_xml({'name': 'Compressed Corp'})
        path = _write_xml_file(xml_bytes, compress=True)
        try:
            info = read_book_company_info(path)
            assert info['name'] == 'Compressed Corp'
        finally:
            os.unlink(path)

    def test_reads_all_fields_from_gzip(self):
        from services.invoice_renderer import read_book_company_info
        xml_bytes = _build_gnucash_xml({
            'name':  'Zipped Inc',
            'email': 'info@zipped.example',
        })
        path = _write_xml_file(xml_bytes, compress=True)
        try:
            info = read_book_company_info(path)
            assert info['name']  == 'Zipped Inc'
            assert info['email'] == 'info@zipped.example'
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# Tests: _render_seller_header (Q-019)
# ---------------------------------------------------------------------------
#
# `_render_seller_header` builds the `# Issued by: ...` comment that
# the plaintext invoice renderer puts at the top of each rendered
# document. Unit-tested here because it's pure-Python (no GnuCash
# session) and the format is what recipients see byte-for-byte.

class TestRenderSellerHeader:
    def test_full_company_info_emits_all_fields(self):
        from services.invoice_renderer import _render_seller_header
        out = _render_seller_header({
            'name':  'Acme Inc.',
            'id':    '12345RT0001',
            'address': ['100 Main St'],
            'phone': '+1-555-0000',
            'email': 'hi@acme.test',
            'url':   'https://acme.test',
        })
        assert out.startswith('# Issued by: Acme Inc.')
        # Label uses "Company ID:" (jurisdiction-neutral) — matches the
        # GnuCash slot name. The slot value itself remains the supplier's
        # tax-registration number (e.g. CRA GST/HST, US EIN, etc.), so
        # ITC validity isn't affected by the neutral label.
        assert 'Company ID: 12345RT0001' in out
        assert '100 Main St' in out
        assert '+1-555-0000' in out
        assert 'hi@acme.test' in out
        assert 'https://acme.test' in out
        # Pre-fix iteration was `for key, label in (('phone', None), ...)`
        # and the dead branch `f'{label}: {val}'` would have produced
        # `None: +1-555-0000` if the label were ever set. Pin the
        # invariant so the next refactor doesn't reintroduce the
        # broken structure.
        assert 'None:' not in out

    def test_missing_company_returns_empty_string(self):
        from services.invoice_renderer import _render_seller_header
        assert _render_seller_header(None) == ''
        assert _render_seller_header({}) == ''
        # Whitespace-only name counts as missing — plaintext output then
        # skips the file-scoped seller block entirely.
        assert _render_seller_header({'name': '   '}) == ''

    def test_partial_company_skips_empty_fields(self):
        """Address lines and optional contact fields are omitted from
        the header when blank — no `| |` or trailing `| ` artifacts."""
        from services.invoice_renderer import _render_seller_header
        out = _render_seller_header({
            'name':  'Sole Proprietor',
            'id':    '',
            'address': ['', '', '', ''],
            'phone': '',
            'email': 'me@example.test',
            'url':   '',
        })
        assert out == '# Issued by: Sole Proprietor | me@example.test'

    def test_every_line_of_a_long_address_is_in_the_header(self):
        """The header is the seller block a recipient reads, so an address
        cut off at four lines reaches them missing its country."""
        from services.invoice_renderer import _render_seller_header
        out = _render_seller_header({
            'name': 'Acme Inc.',
            'address': ['42 Example Street', 'Unit 5', 'Springfield ON',
                        'A1A 1A1', 'CANADA'],
        })

        assert '42 Example Street, Unit 5, Springfield ON, A1A 1A1, CANADA' \
            in out
