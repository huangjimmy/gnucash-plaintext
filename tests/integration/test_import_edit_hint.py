"""Default-strategy import skips a GUID-matched transaction as a "duplicate".
When the incoming content actually DIFFERS (the user edited the tx), the edit is
silently dropped — so the import now hints at `--strategy update`. This is a
hint only: behaviour is unchanged (still skipped by default).
"""

import time

from click.testing import CliRunner

from cli.main import cli

ACCOUNTS = 'tests/fixtures/payment_roundtrip_accounts.txt'
TX = '2026-01-01 * "Deposit"\n\tAssets:Bank 200.00 CAD\n\tIncome -200.00 CAD\n'


def _new_book(runner, tmp_path):
    gf = tmp_path / 'book.gnucash'
    r = runner.invoke(cli, ['import', '--new', str(gf), ACCOUNTS])
    assert r.exit_code == 0, r.output
    time.sleep(1)
    return gf


def _import(runner, gf, text, name, tmp_path, *extra):
    p = tmp_path / name
    p.write_text(text)
    return runner.invoke(cli, ['import', str(gf), str(p), *extra])


def _bal(gf, name):
    from repositories.gnucash_repository import GnuCashRepository
    repo = GnuCashRepository(str(gf))
    repo.open()
    try:
        out = {}

        def walk(a):
            out[a.get_full_name()] = round(a.GetBalance().to_double(), 2)
            for c in a.get_children():
                walk(c)
        walk(repo.book.get_root_account())
        return out.get(name, 0.0)
    finally:
        repo.close()


def _guid200(gf):
    from repositories.gnucash_repository import GnuCashRepository
    repo = GnuCashRepository(str(gf))
    repo.open()
    try:
        def find(a, n):
            if a.get_full_name() == n:
                return a
            for c in a.get_children():
                g = find(c, n)
                if g:
                    return g
            return None
        bank = find(repo.book.get_root_account(), 'Assets.Bank')
        s = next(s for s in bank.GetSplitList()
                 if abs(s.GetAmount().to_double() - 200.0) < 0.01)
        return s.GetParent().GetGUID().to_string().replace('-', '')
    finally:
        repo.close()


def _edited(guid):
    return (f'2026-01-01 * "Deposit"\n\tguid: "{guid}"\n'
            f'\tAssets:Bank 200.00 CAD\n'
            f'\tAssets:Accounts Receivable -200.00 CAD\n')


def _unchanged(guid):
    return (f'2026-01-01 * "Deposit"\n\tguid: "{guid}"\n'
            f'\tAssets:Bank 200.00 CAD\n\tIncome -200.00 CAD\n')


def test_edited_guid_match_skipped_with_hint_and_unchanged(tmp_path):
    runner = CliRunner()
    gf = _new_book(runner, tmp_path)
    assert _import(runner, gf, TX, 'tx.txt', tmp_path).exit_code == 0
    time.sleep(1)
    guid = _guid200(gf)

    r = _import(runner, gf, _edited(guid), 'edit.txt', tmp_path)
    assert r.exit_code == 0, r.output
    # hint fired (content differs) and the edit was NOT applied by default
    assert 'strategy update' in r.output.lower(), r.output
    assert 'different content' in r.output.lower(), r.output
    time.sleep(1)
    assert _bal(gf, 'Income') == -200.0                       # unchanged
    assert _bal(gf, 'Assets.Accounts Receivable') == 0.0


def test_unchanged_guid_match_skipped_without_hint(tmp_path):
    runner = CliRunner()
    gf = _new_book(runner, tmp_path)
    assert _import(runner, gf, TX, 'tx.txt', tmp_path).exit_code == 0
    time.sleep(1)
    guid = _guid200(gf)

    r = _import(runner, gf, _unchanged(guid), 'same.txt', tmp_path)
    assert r.exit_code == 0, r.output
    assert 'Skipped:      1' in r.output, r.output
    # identical content → it really is a duplicate → NO edit hint
    assert 'strategy update' not in r.output.lower(), r.output


def test_strategy_update_applies_the_edit(tmp_path):
    runner = CliRunner()
    gf = _new_book(runner, tmp_path)
    assert _import(runner, gf, TX, 'tx.txt', tmp_path).exit_code == 0
    time.sleep(1)
    guid = _guid200(gf)

    r = _import(runner, gf, _edited(guid), 'edit.txt', tmp_path,
                '--strategy', 'update')
    assert r.exit_code == 0, r.output
    time.sleep(1)
    # edit applied in place: the Income split is now on AR
    assert _bal(gf, 'Income') == 0.0
    assert _bal(gf, 'Assets.Accounts Receivable') == -200.0
