"""Book shapes the beancount export has a line for, and nothing had produced.

The round-trip tests all run over one small book of three plain transactions,
so the optional metadata the exporter emits — an account's code and
description, a transaction's document link, a number without a description —
was written by code no test executed (T-009). Each is ordinary: a cheque
entered before anyone said what it was for, a receipt scanned and linked, an
account carrying the number it has in the chart of accounts.
"""

from pathlib import Path

from click.testing import CliRunner

from cli.main import cli

FIXTURES = Path('tests/fixtures')
LEDGER = str(FIXTURES / 'beancount_export_edge_shapes.txt')


def _exported(tmp_path):
    gnc = tmp_path / 'book.gnucash'
    created = CliRunner().invoke(cli, ['import', '--new', str(gnc), LEDGER])
    assert created.exit_code == 0, created.output
    out = tmp_path / 'ledger.beancount'
    exported = CliRunner().invoke(cli, ['export-beancount', str(gnc), str(out)])
    assert exported.exit_code == 0, exported.output
    return out.read_text()


class TestOptionalAccountMetadata:
    def test_a_code_and_a_description_are_carried(self, tmp_path):
        text = _exported(tmp_path)

        assert 'gnucash-code: "1001"' in text
        assert 'gnucash-description: "Operating account"' in text

    def test_an_account_without_them_carries_neither(self, tmp_path):
        """Empty is left out, not written as `""` for the import to strip."""
        text = _exported(tmp_path)
        sundry = text.split('open Expenses:Sundry')[1].split('open ')[0]

        assert 'gnucash-code' not in sundry
        assert 'gnucash-description' not in sundry


class TestCommodityMetadata:
    def test_the_currencys_own_name_is_carried(self, tmp_path):
        text = _exported(tmp_path)
        xcd = text.split('commodity XCD')[1].split('\n2024')[0]

        assert 'gnucash-mnemonic: "XCD"' in xcd
        assert 'gnucash-fullname: "East Caribbean Dollar"' in xcd
        assert 'gnucash-fraction: "100"' in xcd


class TestTransactionMetadata:
    def test_a_document_link_is_carried(self, tmp_path):
        text = _exported(tmp_path)

        assert 'gnucash-doclink: "file:///receipts/2024-02-02.pdf"' in text

    def test_a_number_without_a_description_still_writes_both(self, tmp_path):
        """Beancount's payee/narration pair, with only one of them to say.

        One string is beancount's *narration*, so writing the number alone
        filed it as what the entry was for and lost the number — measured, on
        a round trip through this tool's own importer. Both slots are written
        and the reader keys on how many strings there are, which is the answer
        the plaintext export arrived at under Q-020.
        """
        text = _exported(tmp_path)

        assert '2024-02-01 * "CHK-1001" ""' in text

    def test_a_transaction_with_both_writes_both(self, tmp_path):
        """The other side of that branch, so the pair is pinned as a pair."""
        gnc = tmp_path / 'both.gnucash'
        assert CliRunner().invoke(
            cli, ['import', '--new', str(gnc), LEDGER]).exit_code == 0
        numbered = ('tests/fixtures/'
                    'a_transaction_with_a_number_and_a_description.txt')
        assert CliRunner().invoke(
            cli, ['import', str(gnc), numbered]).exit_code == 0

        out = tmp_path / 'o.beancount'
        assert CliRunner().invoke(
            cli, ['export-beancount', str(gnc), str(out)]).exit_code == 0
        assert '* "CHK-1002" "Paid the printer"' in out.read_text()
