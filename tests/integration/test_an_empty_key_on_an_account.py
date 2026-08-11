"""`key: ""` clears a custom key on an account being created.

README states the rule once: `key: "value"` sets, `key: ""` clears, and an
absent line says nothing. Transactions, splits, customers, vendors, invoices
and bills all keep it.

Accounts did not. An empty value was stored as an empty custom key, written
back out by the exporter, and carried through every round trip after that — so
one spelling meant "remove this" on six kinds of block and "store an empty
string" on the seventh, and there was no spelling at all that took a custom
key off an account.

**Only on creation.** An `open` for an account the book already holds is
skipped whole — found by name, and the block never read — so nothing in it
sets, clears or compares anything. That is what the last class here pins, and
what README says beside the rule, because a reader who takes the rule at its
word would otherwise write `key: ""` into an `open` and watch nothing happen.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner

from cli.main import cli

LEDGER = """\
2026-01-01 commodity CAD
\tmnemonic: "CAD"
\tfullname: "Canadian Dollar"
\tnamespace: "CURRENCY"
\tfraction: 100
2026-01-01 open Assets
\ttype: Asset
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Assets:Bank
\ttype: Bank
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
\tregion: "west"
\tdepartment: ""
2026-01-01 open Expenses
\ttype: Expense
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Expenses:Sundry
\ttype: Expense
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"

2026-02-01 * "Something, so the export has an account block to write"
\tAssets:Bank -20.00 CAD
\tExpenses:Sundry 20.00 CAD
"""


@pytest.fixture
def exported(tmp_path):
    book = tmp_path / 'book.gnucash'
    ledger = tmp_path / 'ledger.txt'
    ledger.write_text(LEDGER)
    result = CliRunner().invoke(cli, ['import', '--new', str(book), str(ledger)])
    assert result.exit_code == 0, result.output

    out = tmp_path / 'out.txt'
    exported = CliRunner().invoke(cli, ['export', str(book), str(out)])
    assert exported.exit_code == 0, exported.output
    assert out.exists(), exported.output
    text = out.read_text()
    assert text.strip(), f'the export wrote nothing: {exported.output}'
    return text


class TestAnAccountsClearedKey:
    def test_it_is_not_written_back(self, exported):
        assert 'department:' not in exported, exported

    def test_the_key_with_a_value_is_kept(self, exported):
        """Clearing one says nothing about the others."""
        assert 'region: "west"' in exported, exported


class TestAnOpenForAnAccountTheBookAlreadyHas:
    """A no-op, whatever it says — which is why README says so beside the rule.

    The account is found by name and the block skipped whole, so an `open` is
    "create this account" and nothing else. Neither setting a key nor clearing
    one reaches the book, and there is no comparison to notice the difference.
    """

    def _twice(self, tmp_path, second: str) -> str:
        runner = CliRunner()
        book = tmp_path / 'book.gnucash'
        first = tmp_path / 'first.txt'
        first.write_text(LEDGER)
        assert runner.invoke(cli, ['import', '--new', str(book),
                                   str(first)]).exit_code == 0

        again = tmp_path / 'again.txt'
        again.write_text(second)
        result = runner.invoke(cli, ['import', str(book), str(again)])
        assert result.exit_code == 0, result.output

        out = tmp_path / 'out.txt'
        assert runner.invoke(cli, ['export', str(book),
                                   str(out)]).exit_code == 0
        return out.read_text()

    def test_a_new_value_does_not_reach_the_account(self, tmp_path):
        text = self._twice(tmp_path, LEDGER.replace('region: "west"',
                                                    'region: "east"'))

        assert 'region: "west"' in text, text
        assert 'east' not in text, text

    def test_clearing_a_key_does_not_reach_it_either(self, tmp_path):
        text = self._twice(tmp_path, LEDGER.replace('region: "west"',
                                                    'region: ""'))

        assert 'region: "west"' in text, text
