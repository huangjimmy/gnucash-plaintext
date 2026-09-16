"""An account with no commodity is left out of the export, and the rest is written.

Nothing this tool writes makes such an account, but a book from another tool
can hold one, and GnuCash keeps it through a save and a reload
(tests/research/whether_a_reload_keeps_a_security_currency_or_an_account_with_no_commodity_probe.py).
Its `open` line would have no commodity to state, so every export leaves it
out: as the parent of an account that is written, and on its own.
"""

import re

import gnucash
import pytest
from click.testing import CliRunner
from gnucash import Account

from infrastructure.gnucash.utils import find_account
from repositories.gnucash_repository import GnuCashRepository, SessionMode
from tests.conftest import _run

FIXTURE = 'tests/fixtures/cash_opened_from_equity.txt'


def _a_book_from_another_tool(tmp_path):
    """The cash account moved under `Holder`, an account with no commodity."""
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    made = _run(runner, 'import', '--new', str(book), FIXTURE)
    assert made.exit_code == 0, made.output

    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.NORMAL)
    try:
        root = repo.book.get_root_account()
        holder = Account(repo.book)
        holder.BeginEdit()
        holder.SetName('Holder')
        holder.SetType(gnucash.ACCT_TYPE_ASSET)
        root.append_child(holder)
        holder.CommitEdit()
        holder.append_child(find_account(root, 'Assets:Cash'))
        repo.save()
    finally:
        repo.close()
    return runner, book


@pytest.mark.parametrize('command, options', [
    ('export', []),
    ('export', ['--all-accounts']),
    ('export-accounts', []),
], ids=['export', 'export-all-accounts', 'export-accounts'])
def test_it_is_left_out_and_the_rest_is_written(tmp_path, command, options):
    runner, book = _a_book_from_another_tool(tmp_path)
    out = tmp_path / 'out.txt'

    result = _run(runner, command, str(book), str(out), *options)

    assert result.exit_code == 0, result.output
    opened = re.findall(r'^\d{4}-\d{2}-\d{2} open (.+)$', out.read_text(), flags=re.M)
    assert 'Holder' not in opened, opened
    assert {'Holder:Cash', 'Equity'} <= set(opened), opened


def test_the_beancount_export_leaves_it_out_too(tmp_path):
    """Beancount opens an account without its parent, so the child is declared
    and the parent with nothing to state is not."""
    runner, book = _a_book_from_another_tool(tmp_path)
    out = tmp_path / 'out.beancount'

    result = _run(runner, 'export-beancount', str(book), str(out))

    assert result.exit_code == 0, result.output
    declared = re.findall(r'gnucash-name: "([^"]*)"', out.read_text())
    assert 'Holder' not in declared, declared
    assert 'Holder:Cash' in declared, declared
