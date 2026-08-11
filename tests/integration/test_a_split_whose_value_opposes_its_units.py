"""A split whose value has the opposite sign to its units.

`@@ total` is beancount's way of stating what a posting is worth, and it takes
the sign from the units: `10 HOOL @@ 50.00 USD` weighs +50.00 and
`-10 HOOL @@ 50.00 USD` weighs −50.00, the total itself being a cost rather
than a signed figure. So a split holding +10 units worth −50.00 has nothing to
write there — stating 50.00 says the opposite of what the book holds, and
stating −50.00 is read as a cost of −50.00 against +10 units, which is the same
answer again.

The importer rebuilds the value as `amount × (total / |amount|)`, so such a
posting comes back with the sign of its units and no complaint. That is the
same class of loss as the return of capital next door in
`test_a_split_with_no_units.py` — a figure the form cannot carry — and it gets
the same answer: refuse the book and point at the plaintext export, which
states the units and the value separately and signs both.
"""

import os
import tempfile

import pytest
from click.testing import CliRunner

from cli.main import cli


def _book_with_an_opposed_split():
    """+10 HOOL worth −50.00 USD, balanced by cash of +50.00."""
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
    transaction.SetDescription('Units one way, value the other')
    held = Split(book)
    held.SetParent(transaction)
    held.SetAccount(stock)
    held.SetAmount(GncNumeric(10, 1))
    held.SetValue(GncNumeric(-5000, 100))
    other = Split(book)
    other.SetParent(transaction)
    other.SetAccount(cash)
    other.SetAmount(GncNumeric(5000, 100))
    other.SetValue(GncNumeric(5000, 100))
    transaction.CommitEdit()

    session.save()
    session.end()
    return path


@pytest.fixture
def opposed():
    path = _book_with_an_opposed_split()
    yield path
    if os.path.exists(path):
        os.unlink(path)


class TestThePremise:
    def test_gnucash_keeps_the_two_signs_apart(self, opposed):
        """Or the shape below is about a book that cannot exist."""
        from gnucash import Query, Transaction

        from repositories.gnucash_repository import (
            GnuCashRepository,
            SessionMode,
        )

        repo = GnuCashRepository(opposed)
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

        assert rows['Assets.HOOL'] == ('100000/10000', '-5000/100'), rows


class TestTheBeancountExport:
    def test_it_refuses_the_book(self, opposed, tmp_path):
        out = tmp_path / 'opposed.beancount'
        result = CliRunner().invoke(cli, ['export-beancount', opposed,
                                          str(out)])

        assert result.exit_code != 0, result.output
        assert 'Assets:HOOL' in result.output, result.output
        assert not out.exists(), 'a refused export left a file behind'

    def test_it_says_which_way_each_figure_goes(self, opposed, tmp_path):
        result = CliRunner().invoke(cli, [
            'export-beancount', opposed, str(tmp_path / 'opposed.beancount')])

        assert '10' in result.output, result.output
        assert '-50.00' in result.output, result.output

    def test_the_release_notes_say_a_whole_book_is_refused(self):
        """A book that is right and a format that cannot hold it — there is
        no remedy inside GnuCash, so a reader has to be told."""
        from pathlib import Path

        text = Path('RELEASE_NOTES.md').read_text()
        unreleased = text[text.index('## Unreleased'):]
        unreleased = unreleased[:unreleased.index('\n## ', 1)]

        assert '**A value opposing its units**' in unreleased, unreleased


class TestThePlaintextExport:
    def test_it_states_both_figures_with_their_signs(self, opposed, tmp_path):
        """Which is what the refusal tells the reader to use."""
        out = tmp_path / 'opposed.txt'
        result = CliRunner().invoke(cli, ['export', opposed, str(out)])

        assert result.exit_code == 0, result.output
        text = out.read_text()
        assert 'Assets:HOOL 10.0000 NASDAQ.HOOL' in text, text
        assert 'value: "-50.00"' in text, text
