"""Q-029: the `company` directive accepts arbitrary keys beyond the known
Business identity fields. Any unknown key (e.g. `fiscal_year_end`, `province`,
`entity_type`, `ledger_locale`) is stored as book-level custom metadata and
round-trips through export/import — but is NEVER rendered on an invoice or bill,
because it is private book data (a customer has no business seeing the seller's
fiscal year).

GnuCash has no native slot for these (accounting period is an app preference,
not stored in the file), so they live in a dedicated book option slot as one
JSON blob.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner

from cli.main import cli

FIXTURES = Path('tests/fixtures')
ACCOUNTS = str(FIXTURES / 'q019_accounts.txt')
COMPANY = str(FIXTURES / 'company_custom_keys.txt')

KNOWN = {
    'name': 'Acme Plaintext Co.',
    'id':   '123456789RT0001',
    'gst':  '123456789RT0001',
    'pst':  'BC PST-1234-5678; SK 9012-3456',
}
CUSTOM = {
    'fiscal_year_end': '12-31',
    'province':        'British Columbia',
    'entity_type':     'T2 Corporation',
    'ledger_locale':   'en_CA',
}


def _new_book(runner, tmp_path, name='book.gnucash'):
    gf = tmp_path / name
    assert runner.invoke(cli, ['import', '--new', str(gf), ACCOUNTS]).exit_code == 0
    return gf


def _import(runner, gf, content, tmp_path, name):
    p = tmp_path / name
    p.write_text(content)
    r = runner.invoke(cli, ['import', str(gf), str(p), '--include-business-objects'])
    assert r.exit_code == 0, r.output


def _export(runner, gf, tmp_path, name='exp.txt'):
    out = tmp_path / name
    r = runner.invoke(cli, ['export', str(gf), str(out), '--include-business-objects'])
    assert r.exit_code == 0, r.output
    return out.read_text()


def _company_block(text):
    out, capturing = [], False
    for line in text.splitlines():
        if not capturing:
            if line.strip() == 'company' and not line[:1].isspace():
                capturing = True
                out.append(line)
            continue
        if line[:1].isspace():
            out.append(line)
        else:
            break
    return '\n'.join(out)


def _company_fields(text):
    fields = {}
    for line in _company_block(text).splitlines()[1:]:
        key, _, val = line.strip().partition(':')
        val = val.strip()
        if val.startswith('"') and val.endswith('"'):
            val = val[1:-1]
        fields[key.strip()] = val
    return fields


def test_custom_keys_round_trip_with_values(tmp_path):
    runner = CliRunner()
    gf = _new_book(runner, tmp_path)
    _import(runner, gf, Path(COMPANY).read_text(), tmp_path, 'company.txt')
    fields = _company_fields(_export(runner, gf, tmp_path))
    for key, want in {**KNOWN, **CUSTOM}.items():
        assert fields.get(key) == want, (key, fields)


def test_custom_keys_survive_double_roundtrip(tmp_path):
    runner = CliRunner()
    gf_a = _new_book(runner, tmp_path, 'A.gnucash')
    _import(runner, gf_a, Path(COMPANY).read_text(), tmp_path, 'company.txt')
    e1 = _export(runner, gf_a, tmp_path, 'e1.txt')
    block1 = _company_block(e1)
    assert block1, e1

    gf_b = tmp_path / 'B.gnucash'
    (tmp_path / 'e1_in.txt').write_text(e1)
    assert runner.invoke(cli, ['import', '--new', str(gf_b),
                               str(tmp_path / 'e1_in.txt'),
                               '--include-business-objects']).exit_code == 0
    block2 = _company_block(_export(runner, gf_b, tmp_path, 'e2.txt'))
    assert block1 == block2, f'--- e1 ---\n{block1}\n--- e2 ---\n{block2}'


def _book_with_company_and(runner, tmp_path, doc_fixture):
    gf = _new_book(runner, tmp_path)
    combined = Path(COMPANY).read_text() + '\n\n' + (FIXTURES / doc_fixture).read_text()
    _import(runner, gf, combined, tmp_path, 'doc.txt')
    return gf


def _assert_custom_not_rendered(doc):
    # Sanity: a known identity field IS rendered, proving the seller block ran.
    assert 'GST: 123456789RT0001' in doc, doc
    # The private custom keys and their distinctive values must NOT appear.
    for token in ('fiscal_year_end', '12-31', 'entity_type', 'T2 Corporation',
                  'ledger_locale', 'en_CA', 'province', 'British Columbia'):
        assert token not in doc, f'custom data {token!r} leaked into render:\n{doc}'


def test_custom_keys_not_rendered_on_invoice(tmp_path):
    runner = CliRunner()
    gf = _book_with_company_and(runner, tmp_path, 'q019_unposted_cash_with_tax.txt')
    for fmt, ext in (('plaintext', 'txt'), ('html', 'html')):
        out = tmp_path / f'inv.{ext}'
        r = runner.invoke(cli, ['print-invoice', str(gf), 'INV-Q19-CASH-TAX-200',
                                '--format', fmt, '-o', str(out)])
        assert r.exit_code == 0, r.output
        _assert_custom_not_rendered(out.read_text())


def test_custom_keys_not_rendered_on_bill(tmp_path):
    runner = CliRunner()
    gf = _book_with_company_and(runner, tmp_path, 'q019_unposted_cash_bill.txt')
    bill_id = None
    for line in (FIXTURES / 'q019_unposted_cash_bill.txt').read_text().splitlines():
        if line.startswith('bill "'):
            bill_id = line.split('"')[1]
            break
    out = tmp_path / 'bill.txt'
    r = runner.invoke(cli, ['print-bill', str(gf), bill_id, '--format', 'plaintext',
                            '-o', str(out)])
    assert r.exit_code == 0, r.output
    _assert_custom_not_rendered(out.read_text())


# ── Reopened Q-029: a partial company import is an UPSERT, not a full replace ──

def test_partial_import_preserves_unmentioned_custom_keys(tmp_path):
    """A later company directive that names only some keys must NOT delete the
    custom keys it omits — the bug that reopened Q-029. (It used to replace the
    whole custom blob, silently dropping absent custom keys.)"""
    runner = CliRunner()
    gf = _new_book(runner, tmp_path)
    _import(runner, gf,
            'company\n\tgst: "GST-111"\n\tprovince: "BC"\n\tentity_type: "T2 Corporation"\n',
            tmp_path, 'c1.txt')
    # Second import touches only province.
    _import(runner, gf, 'company\n\tprovince: "Ontario"\n', tmp_path, 'c2.txt')

    fields = _company_fields(_export(runner, gf, tmp_path))
    assert fields.get('entity_type') == 'T2 Corporation'   # custom key preserved
    assert fields.get('gst') == 'GST-111'                  # known field preserved
    assert fields.get('province') == 'Ontario'             # the named key updated


def test_null_value_removes_a_custom_key(tmp_path):
    """`key: #None` (the format's null) removes that custom key — JSON Merge
    Patch semantics — while leaving the others intact."""
    runner = CliRunner()
    gf = _new_book(runner, tmp_path)
    _import(runner, gf,
            'company\n\tprovince: "BC"\n\tentity_type: "T2 Corporation"\n',
            tmp_path, 'c1.txt')
    _import(runner, gf, 'company\n\tentity_type: #None\n', tmp_path, 'c2.txt')

    fields = _company_fields(_export(runner, gf, tmp_path))
    assert 'entity_type' not in fields                     # removed via null
    assert fields.get('province') == 'BC'                  # the other key survives


class TestAKeyTheCompanyBlockOwns:
    """`set-book-key` writes the blob, and a `company` field is not kept there.

    Every reader of one of those names looks at GnuCash's own Business option:
    the export prefers it, the printed page reads it, and the migration that
    moves an older book's blob copy onto the option fires only while the
    option is empty. So a write here would report `created` and then be
    invisible in every direction — until the next import carrying a `company`
    block deleted it. Refused by name, with the block to use instead.
    """

    def _refused(self, tmp_path, key, value):
        runner = CliRunner()
        gf = _new_book(runner, tmp_path)
        _import(runner, gf, 'company\n\tname: "Acme"\n', tmp_path, 'c1.txt')
        return runner.invoke(cli, ['set-book-key', str(gf),
                                   '--key', key, '--value', value])

    def test_a_business_field_is_refused(self, tmp_path):
        r = self._refused(tmp_path, 'date_format', '%Y-%m-%d')

        assert r.exit_code != 0, r.output
        assert 'date_format' in r.output and 'company' in r.output

    def test_a_field_that_was_always_one_is_refused_too(self, tmp_path):
        """The rule is the set's, not the newest member's."""
        r = self._refused(tmp_path, 'phone', '+1-555-0100')

        assert r.exit_code != 0, r.output
        assert 'phone' in r.output

    @pytest.mark.parametrize('key', ['addr1', 'addr[0]'])
    def test_an_address_line_is_refused_in_either_spelling(self, tmp_path,
                                                           key):
        """And refused *for the right reason*, which is the harder half.

        `addr[0]` is a well-formed key in this format — the grammar takes a
        trailing index — so turning it away as malformed would tell the reader
        their spelling is wrong when it is the format's own, and would never
        reach the sentence naming the block to state it in.
        """
        r = self._refused(tmp_path, key, '42 Example Street')

        assert r.exit_code != 0, r.output
        assert key in r.output
        assert 'company' in r.output
        assert 'invalid book key' not in r.output

    def test_a_key_of_the_readers_own_is_still_accepted(self, tmp_path):
        """Including one that merely looks like an address line."""
        r = self._refused(tmp_path, 'addr7', 'a key of my own')

        assert r.exit_code == 0, r.output


def test_set_book_key_does_not_disturb_other_custom_keys(tmp_path):
    """`set-book-key` shares the merge helper, so it upserts one key without
    dropping the others — same behaviour as the company directive."""
    runner = CliRunner()
    gf = _new_book(runner, tmp_path)
    _import(runner, gf, 'company\n\tprovince: "BC"\n', tmp_path, 'c1.txt')
    r = runner.invoke(cli, ['set-book-key', str(gf), '--key', 'schema_version',
                            '--value', '5'])
    assert r.exit_code == 0, r.output
    fields = _company_fields(_export(runner, gf, tmp_path))
    assert fields.get('schema_version') == '5'
    assert fields.get('province') == 'BC'                  # not disturbed
