"""Optional business-object fields survive an export and come back.

A customer's address lines and email, an invoice's billing id and notes, and a
payment's cheque number are each written only when the object carries one. No
fixture in the suite carried any of them, so the lines that write them were
never executed (T-009) — and a field that is never written is a field that
quietly disappears from a book on its way through plaintext.
"""

from pathlib import Path

from click.testing import CliRunner

from cli.main import cli

FIXTURES = Path('tests/fixtures')
ACCOUNTS = str(FIXTURES / 'q019_accounts.txt')
LEDGER = str(FIXTURES / 'business_objects_with_optional_fields.txt')


def _exported(tmp_path):
    gnc = tmp_path / 'book.gnucash'
    created = CliRunner().invoke(cli, ['import', '--new', str(gnc), ACCOUNTS])
    assert created.exit_code == 0, created.output
    imported = CliRunner().invoke(cli, ['import', str(gnc), LEDGER,
                                        '--include-business-objects'])
    assert imported.exit_code == 0, imported.output
    assert 'Errors:       0' in imported.output, imported.output

    out = tmp_path / 'out.txt'
    exported = CliRunner().invoke(cli, ['export', str(gnc), str(out),
                                        '--include-business-objects'])
    assert exported.exit_code == 0, exported.output
    return out.read_text()


class TestACustomersAddress:
    def test_every_line_it_carries_is_written(self, tmp_path):
        text = _exported(tmp_path)

        assert 'addr1: "Suite 400"' in text
        assert 'addr2: "1 Example Street"' in text
        assert 'addr3: "Toronto ON"' in text
        assert 'addr4: "M5V 1A1"' in text
        assert 'email: "ap@example.test"' in text

    def test_a_customer_without_them_carries_none(self, tmp_path):
        """Empty is left out, not written as `""` for the import to strip.

        Read off a second *customer*. This looked at the vendor block before,
        where address fields are never written at all — so their absence was
        true by construction and said nothing about the customer writer's
        false side, which is the branch this is here for.
        """
        text = _exported(tmp_path)
        assert 'customer "C-BARE"' in text, text
        bare = text.split('customer "C-BARE"')[1].split('\ncustomer ')[0]
        bare = bare.split('\nvendor ')[0]

        assert 'name: "Bare Co"' in bare, bare
        for field in ('addr1', 'addr2', 'addr3', 'addr4', 'email'):
            assert field not in bare, (field, bare)


class TestAnInvoicesOwnReferences:
    def test_the_billing_id_and_notes_are_written(self, tmp_path):
        text = _exported(tmp_path)

        assert 'billing_id: "PO-99871"' in text
        assert 'notes: "Quoted 2026-02-20, net 30"' in text


class TestAPaymentsChequeNumber:
    def test_it_is_written(self, tmp_path):
        text = _exported(tmp_path)

        assert 'num: "1042"' in text


class TestItAllComesBack:
    def test_the_export_re_imports_into_a_fresh_book(self, tmp_path):
        """The point of writing the fields at all."""
        text = _exported(tmp_path)
        again = tmp_path / 'again.txt'
        again.write_text(text)
        rebuilt = tmp_path / 'rebuilt.gnucash'

        result = CliRunner().invoke(cli, [
            'import', '--new', str(rebuilt), str(again),
            '--include-business-objects'])

        assert result.exit_code == 0, result.output
        assert 'Errors:       0' in result.output, result.output

        out = tmp_path / 'twice.txt'
        assert CliRunner().invoke(
            cli, ['export', str(rebuilt), str(out),
                  '--include-business-objects']).exit_code == 0
        second = out.read_text()
        assert 'billing_id: "PO-99871"' in second
        assert 'email: "ap@example.test"' in second
        assert 'num: "1042"' in second
