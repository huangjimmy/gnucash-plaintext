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
            assert info['addr1'] == '123 Main St'
            assert info['addr2'] == 'Suite 4'
            assert info['addr3'] == 'Toronto'
            assert info['addr4'] == 'ON M5V 1A1'
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
            assert info['addr1'] == ''
        finally:
            os.unlink(path)

    def test_address_fewer_than_four_lines_pads_with_empty(self):
        """A two-line address still produces four addr keys; extras are ''."""
        from services.invoice_renderer import read_book_company_info
        xml_bytes = _build_gnucash_xml({'address': 'Line 1\nLine 2'})
        path = _write_xml_file(xml_bytes, compress=False)
        try:
            info = read_book_company_info(path)
            assert info['addr1'] == 'Line 1'
            assert info['addr2'] == 'Line 2'
            assert info['addr3'] == ''
            assert info['addr4'] == ''
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
