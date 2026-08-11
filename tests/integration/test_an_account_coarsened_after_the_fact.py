"""An account whose Smallest Fraction is tightened under figures it already holds.

The everyday route: a CAD expense account kept to cents holds 18.19, and
someone later sets its Smallest Fraction to whole dollars in GnuCash. The
question is what `export` then writes, because the amount is written at the
*account's* unit and 18.19 is not a whole number of dollars.

Measured on a real book rather than reasoned about: GnuCash rounds the split's
**amount** to the account's unit itself, at save, and leaves the **value** at
18.19 — so the book holds `amount 18, value 18.19`, and the two differ on a
same-currency split. The exporter writes exactly that, with the ratio on the
`share_price:` line, and the re-import reproduces both figures. Nothing is
rounded away and no `Imbalance-CAD 0.19` appears.

That is why the export's refusal is judged against the *currency* alone and
not also against the account. Judging the account too would refuse a book that
round-trips exactly, and refusing an export is refusing the only way out of
the book. This test is what keeps that reasoning honest: it runs on every
supported build, so an engine that does not round the amount will say so here
rather than in someone's ledger.
"""

import os
import tempfile

import pytest
from click.testing import CliRunner

from cli.main import cli


def _new_session(path=None, new=True):
    from gnucash import Session

    if path is None:
        fd, path = tempfile.mkstemp(suffix='.gnucash')
        os.close(fd)
        os.unlink(path)
    try:
        from gnucash import SessionOpenMode
        mode = (SessionOpenMode.SESSION_NEW_STORE if new
                else SessionOpenMode.SESSION_NORMAL_OPEN)
        return Session(f'xml://{path}', mode), path
    except ImportError:
        return Session(f'xml://{path}', is_new=new), path


@pytest.fixture
def coarsened_book():
    """18.19 booked while the account held cents, then coarsened to dollars."""
    import gnucash
    from gnucash import Account, GncNumeric, Split, Transaction

    session, path = _new_session()
    book = session.book
    root = book.get_root_account()
    cad = book.get_table().lookup('CURRENCY', 'CAD')

    def child(parent, name, kind, scu):
        account = Account(book)
        account.SetName(name)
        account.SetType(kind)
        account.SetCommodity(cad)
        account.SetCommoditySCU(scu)
        parent.append_child(account)
        return account

    assets = child(root, 'Assets', gnucash.ACCT_TYPE_ASSET, 100)
    bank = child(assets, 'Bank', gnucash.ACCT_TYPE_BANK, 100)
    expenses = child(root, 'Expenses', gnucash.ACCT_TYPE_EXPENSE, 100)
    later = child(expenses, 'Coarsened', gnucash.ACCT_TYPE_EXPENSE, 100)

    transaction = Transaction(book)
    transaction.BeginEdit()
    transaction.SetCurrency(cad)
    transaction.SetDate(1, 2, 2026)
    transaction.SetDescription('Booked while the account still held cents')
    out = Split(book)
    out.SetParent(transaction)
    out.SetAccount(later)
    out.SetValue(GncNumeric(1819, 100))
    out.SetAmount(GncNumeric(1819, 100))
    back = Split(book)
    back.SetParent(transaction)
    back.SetAccount(bank)
    back.SetValue(GncNumeric(-1819, 100))
    back.SetAmount(GncNumeric(-1819, 100))
    transaction.CommitEdit()
    session.save()
    session.end()

    # Reopened and tightened, the way the GnuCash UI does it.
    session, _ = _new_session(path, new=False)
    target = (session.book.get_root_account()
              .lookup_by_name('Expenses').lookup_by_name('Coarsened'))
    target.BeginEdit()
    target.SetCommoditySCU(1)
    target.CommitEdit()
    session.save()
    session.end()

    yield path
    if os.path.exists(path):
        os.unlink(path)


def _figures(path):
    """Every split as (account, amount, value), as the book holds them."""
    from gnucash import Query, Transaction

    from repositories.gnucash_repository import GnuCashRepository, SessionMode

    repo = GnuCashRepository(path)
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        query = Query()
        query.search_for('Trans')
        query.set_book(repo.book)
        rows = {}
        for raw in query.run():
            for split in Transaction(instance=raw).GetSplitList():
                amount, value = split.GetAmount(), split.GetValue()
                rows[split.GetAccount().get_full_name()] = (
                    f'{amount.num()}/{amount.denom()}',
                    f'{value.num()}/{value.denom()}')
        query.destroy()
        return rows
    finally:
        repo.close()


class TestWhatTheBookEndsUpHolding:
    def test_gnucash_rounds_the_amount_and_keeps_the_value(self, coarsened_book):
        """The premise everything below rests on, asserted rather than assumed."""
        rows = _figures(coarsened_book)

        assert rows['Expenses.Coarsened'] == ('18/1', '1819/100')
        assert rows['Assets.Bank'] == ('-1819/100', '-1819/100')


class TestTheExport:
    def test_it_is_not_refused(self, coarsened_book, tmp_path):
        out = tmp_path / 'out.txt'
        result = CliRunner().invoke(cli, ['export', coarsened_book, str(out)])

        assert result.exit_code == 0, result.output
        assert out.exists()

    def test_it_writes_the_amount_at_the_accounts_unit_with_the_ratio(
            self, coarsened_book, tmp_path):
        """`18 CAD` alone would lose the 0.19; the share price carries it."""
        out = tmp_path / 'out.txt'
        CliRunner().invoke(cli, ['export', coarsened_book, str(out)])
        text = out.read_text()

        assert 'Expenses:Coarsened 18 CAD' in text, text
        assert 'share_price: "1819/1800"' in text, text
        assert 'Assets:Bank -18.19 CAD' in text, text


class TestTheRoundTrip:
    def test_both_figures_come_back_unchanged(self, coarsened_book, tmp_path):
        out = tmp_path / 'out.txt'
        assert CliRunner().invoke(
            cli, ['export', coarsened_book, str(out)]).exit_code == 0

        back = tmp_path / 'back.gnucash'
        result = CliRunner().invoke(cli, ['import', '--new', str(back), str(out)])
        assert result.exit_code == 0, result.output
        assert 'Errors:       0' in result.output, result.output

        assert _figures(str(back)) == _figures(coarsened_book)

    def test_beancount_carries_both_figures_too(self, coarsened_book, tmp_path):
        """The other export has the same split to write, and the same problem.

        A same-currency split whose value is not its amount is exactly what
        this book holds, and the beancount exporter stated the second figure
        only when the commodities differed — so `18 CAD` went out against
        `-18.19 CAD`, which does not balance as beancount, and re-importing it
        left GnuCash to park the 0.19 in `Imbalance-CAD`.
        """
        beans = tmp_path / 'out.beancount'
        assert CliRunner().invoke(
            cli, ['export-beancount', coarsened_book, str(beans)]).exit_code == 0
        text = beans.read_text()
        assert '@@ 18.19 CAD' in text, text

        back = tmp_path / 'back.gnucash'
        result = CliRunner().invoke(
            cli, ['import-beancount', str(back), str(beans)])
        assert result.exit_code == 0, result.output

        rebuilt = _figures(str(back))
        assert not [name for name in rebuilt if 'Imbalance' in name], rebuilt
        assert rebuilt['Expenses.Coarsened'] == ('18/1', '1819/100'), rebuilt
        assert rebuilt['Assets.Bank'] == ('-1819/100', '-1819/100'), rebuilt

    def test_no_imbalance_is_created(self, coarsened_book, tmp_path):
        """What writing `18` against `-18.19` would have produced."""
        out = tmp_path / 'out.txt'
        CliRunner().invoke(cli, ['export', coarsened_book, str(out)])
        back = tmp_path / 'back.gnucash'
        CliRunner().invoke(cli, ['import', '--new', str(back), str(out)])

        assert not [name for name in _figures(str(back)) if 'Imbalance' in name]

        checked = CliRunner().invoke(cli, ['validate', str(back)])
        assert checked.exit_code == 0, checked.output
        assert 'Imbalance' not in checked.output, checked.output
