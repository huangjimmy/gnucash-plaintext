"""Q-030: `rename-account` renames / reparents an account by GUID, in place.

Covers both cases the operation must handle:
  1. different parent  → reparent (full-path `--to`)
  2. same parent, leaf → rename (bare-leaf `--to`)

In both, the account keeps its GUID and every split stays attached (GnuCash
holds splits by reference, not by name), so the transaction that touched the
account simply follows it — the next export prints the new path everywhere.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner

from cli.main import cli

BOOK = str(Path('tests/fixtures/rename_account_book.txt'))


def _new_book(runner, tmp_path):
    gf = tmp_path / 'book.gnucash'
    r = runner.invoke(cli, ['import', '--new', str(gf), BOOK])
    assert r.exit_code == 0, r.output
    return gf


def _colon_name(acc):
    # Colon-separated full name (GnuCash get_full_name() uses '.' in a headless
    # book; the plaintext format and this command are colon-based).
    parts = []
    node = acc
    while node is not None and node.get_parent() is not None:
        parts.append(node.GetName())
        node = node.get_parent()
    return ':'.join(reversed(parts))


def _accounts(gf):
    """Return {colon_full_name: guid} for every account in the book."""
    from repositories.gnucash_repository import GnuCashRepository
    repo = GnuCashRepository(str(gf))
    repo.open()
    try:
        return {_colon_name(a): a.GetGUID().to_string()
                for a in repo.book.get_root_account().get_descendants()}
    finally:
        repo.close()


def _export(runner, gf, tmp_path):
    out = tmp_path / 'exp.txt'
    r = runner.invoke(cli, ['export', str(gf), str(out)])
    assert r.exit_code == 0, r.output
    return out.read_text()


def _rename(runner, gf, guid, to):
    return runner.invoke(cli, ['rename-account', str(gf), '--guid', guid, '--to', to])


def test_leaf_rename_same_parent(tmp_path):
    runner = CliRunner()
    gf = _new_book(runner, tmp_path)
    guid = _accounts(gf)['Assets:Bank:Checking']

    r = _rename(runner, gf, guid, 'Chequing')
    assert r.exit_code == 0, r.output

    accts = _accounts(gf)
    assert 'Assets:Bank:Chequing' in accts
    assert 'Assets:Bank:Checking' not in accts
    # GUID preserved across the rename.
    assert accts['Assets:Bank:Chequing'] == guid


def test_rename_to_different_parent(tmp_path):
    runner = CliRunner()
    gf = _new_book(runner, tmp_path)
    guid = _accounts(gf)['Assets:Bank:Checking']

    r = _rename(runner, gf, guid, 'Assets:Checking')
    assert r.exit_code == 0, r.output

    accts = _accounts(gf)
    assert 'Assets:Checking' in accts
    assert 'Assets:Bank:Checking' not in accts
    assert accts['Assets:Checking'] == guid          # same account, new parent
    assert 'Assets:Bank' in accts                     # old parent still exists


def test_rename_changes_parent_and_leaf_together(tmp_path):
    """A single rename can change the parent AND the leaf at once."""
    runner = CliRunner()
    gf = _new_book(runner, tmp_path)
    guid = _accounts(gf)['Assets:Bank:Checking']

    r = _rename(runner, gf, guid, 'Assets:Cash:Petty')
    assert r.exit_code == 0, r.output

    accts = _accounts(gf)
    assert 'Assets:Cash:Petty' in accts               # new parent + new leaf
    assert 'Assets:Bank:Checking' not in accts
    assert accts['Assets:Cash:Petty'] == guid


def test_splits_follow_the_renamed_account(tmp_path):
    runner = CliRunner()
    gf = _new_book(runner, tmp_path)
    guid = _accounts(gf)['Assets:Bank:Checking']
    assert _rename(runner, gf, guid, 'Assets:Checking').exit_code == 0

    exported = _export(runner, gf, tmp_path)
    # The transaction split now names the new path; the old path is gone
    # entirely (open directive and split alike) — nothing in the ledger text
    # had to be hand-edited.
    assert 'Assets:Checking' in exported
    assert 'Assets:Bank:Checking' not in exported
    # The split (and its -50.00) still belongs to the moved account.
    assert 'Assets:Checking -50.00 CAD' in exported


# ── Failure cases: each must give an explicit, detailed message and leave the
#    book untouched. ─────────────────────────────────────────────────────────

def test_malformed_guid_is_rejected(tmp_path):
    runner = CliRunner()
    gf = _new_book(runner, tmp_path)
    r = _rename(runner, gf, 'not-a-real-guid', 'Whatever')
    assert r.exit_code != 0
    out = r.output
    assert 'not a valid account GUID' in out and 'not-a-real-guid' in out
    assert 'export-accounts' in out                  # tells the user how to find it


def test_unknown_guid_is_rejected(tmp_path):
    runner = CliRunner()
    gf = _new_book(runner, tmp_path)
    before = _accounts(gf)
    r = _rename(runner, gf, '00000000000000000000000000000000', 'Whatever')
    assert r.exit_code != 0
    out = r.output
    assert 'no account in this book has guid' in out
    assert '00000000000000000000000000000000' in out
    assert _accounts(gf) == before                   # book untouched


def test_rename_cycle_is_rejected(tmp_path):
    runner = CliRunner()
    gf = _new_book(runner, tmp_path)
    # Rename Assets to a name under its own descendant Assets:Bank:Checking.
    guid = _accounts(gf)['Assets']
    r = _rename(runner, gf, guid, 'Assets:Bank:Checking:Assets')
    assert r.exit_code != 0
    out = r.output
    assert "rename account 'Assets'" in out
    assert 'own ancestor' in out                      # explains why
    assert 'Assets:Bank:Checking' in out              # names the offending parent
    assert 'Assets:Bank:Checking' in _accounts(gf)    # unchanged


def test_name_collision_is_rejected(tmp_path):
    runner = CliRunner()
    gf = _new_book(runner, tmp_path)
    before = _accounts(gf)
    guid = before['Assets:Bank:Checking']
    # Expenses:Groceries already exists → renaming Checking there clashes.
    r = _rename(runner, gf, guid, 'Expenses:Groceries')
    assert r.exit_code != 0
    out = r.output
    assert "already exists under that parent" in out
    assert 'Expenses:Groceries' in out and "'Assets:Bank:Checking'" in out
    assert _accounts(gf) == before                    # book untouched


def test_unknown_new_parent_is_rejected(tmp_path):
    runner = CliRunner()
    gf = _new_book(runner, tmp_path)
    guid = _accounts(gf)['Assets:Bank:Checking']
    r = _rename(runner, gf, guid, 'Nope:Checking')
    assert r.exit_code != 0
    out = r.output
    assert "parent 'Nope' does not exist" in out
    assert "rename account 'Assets:Bank:Checking'" in out


def test_no_op_rename_reports_unchanged(tmp_path):
    runner = CliRunner()
    gf = _new_book(runner, tmp_path)
    guid = _accounts(gf)['Assets:Bank:Checking']
    r = _rename(runner, gf, guid, 'Checking')
    assert r.exit_code == 0, r.output
    assert 'nothing to change' in r.output


# ── Full export → import roundtrip after a rename ────────────────────────────

@pytest.mark.parametrize('new_to,new_path', [
    ('Chequing',            'Assets:Bank:Chequing'),   # leaf only
    ('Assets:Chequing',     'Assets:Chequing'),        # parent only
    ('Assets:Cash:Petty',   'Assets:Cash:Petty'),      # parent and leaf
])
def test_full_roundtrip_after_rename(tmp_path, new_to, new_path):
    """After a rename, the whole book must export to self-consistent plaintext
    that re-imports cleanly: a fresh import → export reproduces the renamed
    book byte-for-byte, with the account at its new path, same GUID, and the
    transaction's split still attached."""
    runner = CliRunner()
    gf = _new_book(runner, tmp_path)
    guid = _accounts(gf)['Assets:Bank:Checking']
    assert _rename(runner, gf, guid, new_to).exit_code == 0

    e1 = tmp_path / 'e1.txt'
    assert runner.invoke(cli, ['export', str(gf), str(e1)]).exit_code == 0
    gf2 = tmp_path / 'B.gnucash'
    assert runner.invoke(cli, ['import', '--new', str(gf2), str(e1)]).exit_code == 0
    e2 = tmp_path / 'e2.txt'
    assert runner.invoke(cli, ['export', str(gf2), str(e2)]).exit_code == 0

    # The renamed structure survives a full export→import→export unchanged.
    assert e1.read_text() == e2.read_text()
    accts = _accounts(gf2)
    assert new_path in accts and 'Assets:Bank:Checking' not in accts
    assert accts[new_path] == guid                    # GUID preserved through roundtrip
    assert f'{new_path} -50.00 CAD' in e2.read_text()  # split followed the account
