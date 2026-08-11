"""A split's value cannot be finer than its transaction's currency.

Every split on a converting transaction carries two figures: the amount, in
the account's own commodity, and the value, in the transaction's. The export
refuses an amount the currency cannot hold, and rounds the value through
`money_text` — which would be the same defect on the other figure, if a book
could hold such a value.

It cannot. **Measured**: `SetValue(GncNumeric(135005, 1000))` on a CAD
transaction reads back as `13501/100`. GnuCash normalises a value to the
transaction currency's denominator as it is written, so the rounding happens
in the engine, before anything this tool does. There is no figure for the
export to be faithful to and nothing for a guard to catch.

Which is why this is a measurement and not a guard. The amount is different —
an account may legitimately be kept finer than its currency (`commodity_scu:`,
a fund to thousandths), so GnuCash stores what it is given and the check has
something to do.
"""

import os
import tempfile

import pytest
from click.testing import CliRunner

from cli.main import cli


def _book_with_a_sub_cent_value():
    """100.00 USD worth 135.005 CAD, written through GnuCash itself.

    The amount is a whole number of cents of its own currency, so the guard on
    amounts has nothing to say about it; only the value is finer than the
    transaction's CAD.
    """
    import gnucash
    from gnucash import Account, GncNumeric, Session, Split, Transaction

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
    cad = table.lookup('CURRENCY', 'CAD')
    usd = table.lookup('CURRENCY', 'USD')

    assets = Account(book)
    assets.SetName('Assets')
    assets.SetType(gnucash.ACCT_TYPE_ASSET)
    assets.SetCommodity(cad)
    root.append_child(assets)

    bank = Account(book)
    bank.SetName('Bank')
    bank.SetType(gnucash.ACCT_TYPE_BANK)
    bank.SetCommodity(cad)
    assets.append_child(bank)

    usd_bank = Account(book)
    usd_bank.SetName('USD')
    usd_bank.SetType(gnucash.ACCT_TYPE_BANK)
    usd_bank.SetCommodity(usd)
    assets.append_child(usd_bank)

    transaction = Transaction(book)
    transaction.BeginEdit()
    transaction.SetCurrency(cad)
    transaction.SetDescription('Buy USD at an unroundable rate')

    incoming = Split(book)
    incoming.SetParent(transaction)
    incoming.SetAccount(usd_bank)
    incoming.SetAmount(GncNumeric(10000, 100))          # 100.00 USD
    incoming.SetValue(GncNumeric(135005, 1000))         # 135.005 CAD

    outgoing = Split(book)
    outgoing.SetParent(transaction)
    outgoing.SetAccount(bank)
    outgoing.SetAmount(GncNumeric(-135005, 1000))
    outgoing.SetValue(GncNumeric(-135005, 1000))
    transaction.CommitEdit()

    session.save()
    session.end()
    return path


@pytest.fixture
def book():
    path = _book_with_a_sub_cent_value()
    yield path
    if os.path.exists(path):
        os.unlink(path)


class TestWhatTheBookHolds:
    def test_gnucash_rounds_it_to_the_transaction_currency(self, book):
        """The measurement everything else here rests on.

        Written as 135.005 CAD and read back as 135.01 — so no book holds a
        value its transaction's currency cannot express, and the export has
        nothing to be unfaithful about.
        """
        from gnucash import Query, Transaction

        from repositories.gnucash_repository import GnuCashRepository, SessionMode

        repo = GnuCashRepository(str(book))
        repo.open(mode=SessionMode.READ_ONLY)
        try:
            query = Query()
            query.search_for('Trans')
            query.set_book(repo.book)
            values = []
            for raw in query.run():
                for split in Transaction(instance=raw).GetSplitList():
                    if split.GetAccount().GetName() == 'USD':
                        values.append(str(split.GetValue()))
            query.destroy()
        finally:
            repo.close()
        assert values == ['13501/100'], values


class TestWhatTheExportDoes:
    def test_it_writes_what_the_book_holds(self, book, tmp_path):
        """So `money_text` on the value is rounding a figure already round."""
        out = tmp_path / 'out.txt'
        result = CliRunner().invoke(cli, ['export', str(book), str(out)])

        assert result.exit_code == 0, result.output
        assert 'value: "135.01"' in out.read_text(), out.read_text()

    def test_and_that_file_reads_back(self, book, tmp_path):
        """Which is the thing the amount guard exists to keep true: what the
        export writes, the importer accepts."""
        out = tmp_path / 'out.txt'
        assert CliRunner().invoke(cli, ['export', str(book),
                                        str(out)]).exit_code == 0

        rebuilt = tmp_path / 'rebuilt.gnucash'
        result = CliRunner().invoke(cli, ['import', '--new', str(rebuilt),
                                          str(out)])
        assert result.exit_code == 0, result.output
