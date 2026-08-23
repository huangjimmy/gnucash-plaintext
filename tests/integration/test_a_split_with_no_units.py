"""A split holding zero units, in a commodity that is not its transaction's.

Two shapes, and they part company at the value. Zero units worth zero is an
ordinary placeholder — nothing to state, and it must round-trip. Zero units
worth real money is a return of capital, which is how GnuCash's own investment
documentation says to enter one, and which GnuCash stores as `amount 0` with a
value (measured).

Beancount weighs a posting by its units times its cost, so nothing times
anything is nothing: `@@ 50.00` on `0 HOOL` states a total the form has no way
to attach. The first shape is therefore written bare and read back bare; the
second cannot be written at all, and is refused rather than exported without
the only figure it carries.

Getting this wrong cost the round trip both ways. The export dropped the total
on any zero-amount split, and the import — once it began refusing a
cross-currency posting that states no rate — then refused the very file the
export had just written.
"""

import os
import tempfile

import pytest
from click.testing import CliRunner

from cli.main import cli


def _book_with_a_zero_split(value_cents):
    """A USD book whose stock split holds no units and `value_cents` of value."""
    import gnucash
    from gnucash import (
        Account,
        GncCommodity,
        GncNumeric,
        Session,
        Split,
        Transaction,
    )

    fd, path = tempfile.mkstemp(suffix='.gnucash')
    os.close(fd)
    os.unlink(path)
    try:
        from gnucash import SessionOpenMode
        session = Session(f'xml://{path}', SessionOpenMode.SESSION_NEW_STORE)
    except ImportError:
        session = Session(f'xml://{path}', is_new=True)

    book = session.book
    root = book.get_root_account()
    table = book.get_table()
    usd = table.lookup('CURRENCY', 'USD')
    table.insert(GncCommodity(book, 'Hooli', 'NASDAQ', 'HOOL', '', 10000))
    hool = table.lookup('NASDAQ', 'HOOL')

    def child(parent, name, kind, commodity):
        account = Account(book)
        account.SetName(name)
        account.SetType(kind)
        account.SetCommodity(commodity)
        parent.append_child(account)
        return account

    assets = child(root, 'Assets', gnucash.ACCT_TYPE_ASSET, usd)
    stock = child(assets, 'HOOL', gnucash.ACCT_TYPE_STOCK, hool)
    cash = child(assets, 'Cash', gnucash.ACCT_TYPE_BANK, usd)

    transaction = Transaction(book)
    transaction.BeginEdit()
    transaction.SetCurrency(usd)
    transaction.SetDate(1, 3, 2024)
    transaction.SetDescription('No units')
    held = Split(book)
    held.SetParent(transaction)
    held.SetAccount(stock)
    held.SetAmount(GncNumeric(0, 1))
    held.SetValue(GncNumeric(-value_cents, 100))
    other = Split(book)
    other.SetParent(transaction)
    other.SetAccount(cash)
    other.SetAmount(GncNumeric(value_cents, 100))
    other.SetValue(GncNumeric(value_cents, 100))
    transaction.CommitEdit()

    session.save()
    session.end()
    return path


@pytest.fixture
def worth_nothing():
    """0 HOOL worth 0 USD — a placeholder, and it must survive."""
    path = _book_with_a_zero_split(0)
    yield path
    if os.path.exists(path):
        os.unlink(path)


@pytest.fixture
def worth_fifty():
    """0 HOOL worth 50.00 USD — a return of capital."""
    path = _book_with_a_zero_split(5000)
    yield path
    if os.path.exists(path):
        os.unlink(path)


class TestThePremise:
    def test_gnucash_keeps_the_value_against_no_units(self, worth_fifty):
        """Or the shape below is about a book that cannot exist."""
        from gnucash import Query, Transaction

        from repositories.gnucash_repository import (
            GnuCashRepository,
            SessionMode,
        )

        repo = GnuCashRepository(worth_fifty)
        repo.open(mode=SessionMode.READ_ONLY)
        try:
            query = Query()
            query.search_for('Trans')
            query.set_book(repo.book)
            rows = {
                split.GetAccount().get_full_name(): (
                    f'{split.GetAmount().num()}/{split.GetAmount().denom()}',
                    f'{split.GetValue().num()}/{split.GetValue().denom()}')
                for raw in query.run()
                for split in Transaction(instance=raw).GetSplitList()}
            query.destroy()
        finally:
            repo.close()

        assert rows['Assets.HOOL'] == ('0/10000', '-5000/100'), rows


class TestWorthNothing:
    def test_it_round_trips_through_beancount(self, worth_nothing, tmp_path):
        """Nothing to state, so nothing is asked for on the way back in.

        Refusing it — as the no-rate rule first did — meant the importer
        rejected a posting this tool's own export had just written.
        """
        beans = tmp_path / 'zero.beancount'
        assert CliRunner().invoke(
            cli, ['export-beancount', worth_nothing, str(beans)]).exit_code == 0
        assert '0 NASDAQ.HOOL' in beans.read_text(), beans.read_text()

        back = tmp_path / 'back.gnucash'
        result = CliRunner().invoke(
            cli, ['import-beancount', str(back), str(beans)])
        assert result.exit_code == 0, result.output
        assert 'Transactions: 1' in result.output, result.output


class TestWorthRealMoney:
    def test_the_beancount_export_refuses_it(self, worth_fifty, tmp_path):
        out = tmp_path / 'roc.beancount'
        result = CliRunner().invoke(
            cli, ['export-beancount', worth_fifty, str(out)])

        assert result.exit_code != 0, result.output
        assert 'holds no units' in result.output, result.output
        assert '50.00' in result.output, result.output
        assert not out.exists(), 'a refused export left a file behind'

    def test_the_release_notes_say_a_whole_book_is_refused(self):
        """No remedy exists inside GnuCash, so a reader has to be told.

        The book is right and the format cannot hold it — unlike the sub-cent
        amount beside it in the notes, which is a figure to correct. Someone
        with a brokerage account meets this on the first export after
        upgrading, and the way out is the plaintext export.
        """
        # The release this refusal was written up in, named: the whole file
        # lets a note outlive the behaviour it describes, and "the newest
        # section" would need the sentence copied into every release after
        # this one.
        from tests.integration.release_notes_sections import notes_for
        unreleased = notes_for('v0.4.0')

        assert ('refuses a whole book over a split whose value the format '
                'cannot state') in unreleased, unreleased
        assert '**A return of capital**' in unreleased, unreleased

    def test_the_plaintext_export_states_both_figures(self, worth_fifty,
                                                      tmp_path):
        """Which is what the refusal tells the reader to use."""
        out = tmp_path / 'roc.txt'
        result = CliRunner().invoke(cli, ['export', worth_fifty, str(out)])

        assert result.exit_code == 0, result.output
        text = out.read_text()
        # At the account's own unit, and with the value on its own line —
        # which is the whole reason the refusal points here.
        assert 'Assets:HOOL 0.0000 NASDAQ.HOOL' in text, text
        assert 'value: "-50.00"' in text, text
