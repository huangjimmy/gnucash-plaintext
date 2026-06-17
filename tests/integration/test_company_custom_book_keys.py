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

import time
from pathlib import Path

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
    time.sleep(1)
    return gf


def _import(runner, gf, content, tmp_path, name):
    p = tmp_path / name
    p.write_text(content)
    r = runner.invoke(cli, ['import', str(gf), str(p), '--include-business-objects'])
    assert r.exit_code == 0, r.output
    time.sleep(1)


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
    time.sleep(1)
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
