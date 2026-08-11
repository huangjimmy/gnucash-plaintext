"""What `validate` reports on a transaction with a single split.

GnuCash balances what it is handed: commit a transaction whose splits do not
sum to zero and it adds an `Imbalance` split, so the book comes out with two.
That is not true of a split worth nothing — 0.00 is already balanced, there is
nothing to correct, and the transaction stays exactly as written, with one
split and no counterpart.

Which is a transaction that says nothing happened, in a ledger, and the
`SINGLE_SPLIT` check exists to point at it. Nothing had ever reached that
check (T-009): every validate test in the suite runs over a book this tool
wrote, where every transaction has two sides by construction.

The book is built with the bindings rather than imported, because this tool's
own importer will not write such a transaction — which is the point of a
command that reads books other things wrote.
"""

import os
import tempfile
from pathlib import Path

import pytest
from click.testing import CliRunner

from cli.main import cli


@pytest.fixture
def book_with_a_lone_split():
    import gnucash
    from gnucash import Account, GncNumeric, Session, Split, Transaction

    fd, path = tempfile.mkstemp(suffix='.gnucash')
    os.close(fd)
    os.unlink(path)
    try:
        try:
            from gnucash import SessionOpenMode
            session = Session(f'xml://{path}', SessionOpenMode.SESSION_NEW_STORE)
        except ImportError:
            session = Session(f'xml://{path}', is_new=True)

        book = session.book
        root = book.get_root_account()
        cad = book.get_table().lookup('CURRENCY', 'CAD')

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

        lonely = Transaction(book)
        lonely.BeginEdit()
        lonely.SetCurrency(cad)
        lonely.SetDate(3, 2, 2024)
        lonely.SetDescription('Only one side')
        only_split = Split(book)
        only_split.SetParent(lonely)
        only_split.SetAccount(bank)
        only_split.SetValue(GncNumeric(0, 100))
        lonely.CommitEdit()

        session.save()
        session.end()
        yield path
    finally:
        if os.path.exists(path):
            os.unlink(path)


@pytest.fixture
def book_with_an_imbalance():
    """A book where GnuCash had to park a difference it could not place.

    This is what an entry that does not add up looks like once it is stored:
    not an unbalanced transaction — the engine does not keep those — but a
    balanced one carrying a split in `Imbalance-CAD`.
    """
    import gnucash
    from gnucash import Account, GncNumeric, Session, Split, Transaction

    fd, path = tempfile.mkstemp(suffix='.gnucash')
    os.close(fd)
    os.unlink(path)
    try:
        try:
            from gnucash import SessionOpenMode
            session = Session(f'xml://{path}', SessionOpenMode.SESSION_NEW_STORE)
        except ImportError:
            session = Session(f'xml://{path}', is_new=True)

        book = session.book
        root = book.get_root_account()
        cad = book.get_table().lookup('CURRENCY', 'CAD')

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

        expenses = Account(book)
        expenses.SetName('Expenses')
        expenses.SetType(gnucash.ACCT_TYPE_EXPENSE)
        expenses.SetCommodity(cad)
        root.append_child(expenses)

        lopsided = Transaction(book)
        lopsided.BeginEdit()
        lopsided.SetCurrency(cad)
        lopsided.SetDate(4, 2, 2024)
        lopsided.SetDescription('Does not add up')
        out = Split(book)
        out.SetParent(lopsided)
        out.SetAccount(bank)
        out.SetValue(GncNumeric(-1000, 100))
        back = Split(book)
        back.SetParent(lopsided)
        back.SetAccount(expenses)
        back.SetValue(GncNumeric(700, 100))
        lopsided.CommitEdit()          # GnuCash parks the missing 3.00

        session.save()
        session.end()
        yield path
    finally:
        if os.path.exists(path):
            os.unlink(path)


@pytest.fixture
def book_named_like_an_imbalance():
    """A user account called `Imbalance Reserve`, holding an ordinary entry."""
    import gnucash
    from gnucash import Account, GncNumeric, Session, Split, Transaction

    fd, path = tempfile.mkstemp(suffix='.gnucash')
    os.close(fd)
    os.unlink(path)
    try:
        try:
            from gnucash import SessionOpenMode
            session = Session(f'xml://{path}', SessionOpenMode.SESSION_NEW_STORE)
        except ImportError:
            session = Session(f'xml://{path}', is_new=True)

        book = session.book
        root = book.get_root_account()
        cad = book.get_table().lookup('CURRENCY', 'CAD')

        assets = Account(book)
        assets.SetName('Assets')
        assets.SetType(gnucash.ACCT_TYPE_ASSET)
        assets.SetCommodity(cad)
        root.append_child(assets)

        reserve = Account(book)
        reserve.SetName('Imbalance Reserve')
        reserve.SetType(gnucash.ACCT_TYPE_BANK)
        reserve.SetCommodity(cad)
        assets.append_child(reserve)

        bank = Account(book)
        bank.SetName('Bank')
        bank.SetType(gnucash.ACCT_TYPE_BANK)
        bank.SetCommodity(cad)
        assets.append_child(bank)

        ordinary = Transaction(book)
        ordinary.BeginEdit()
        ordinary.SetCurrency(cad)
        ordinary.SetDate(5, 2, 2024)
        ordinary.SetDescription('Set aside')
        a = Split(book)
        a.SetParent(ordinary)
        a.SetAccount(reserve)
        a.SetValue(GncNumeric(1000, 100))
        b = Split(book)
        b.SetParent(ordinary)
        b.SetAccount(bank)
        b.SetValue(GncNumeric(-1000, 100))
        ordinary.CommitEdit()

        session.save()
        session.end()
        yield path
    finally:
        if os.path.exists(path):
            os.unlink(path)


class TestTwoAccountUnitsInOneTransaction:
    """One entry across two account units, and why the balance check is safe.

    The balance check sums split *values*. It summed bare numerators, which is
    right only while every value in a transaction shares a denominator — so
    the question is whether a book this tool writes can produce a transaction
    where they do not.

    It cannot: GnuCash normalises every value to the *transaction currency's*
    fraction, whatever unit each account is kept to. This ledger puts a
    `commodity_scu: 1000` account opposite an ordinary one in a single CAD
    transaction — the shape most likely to break it — and both values come
    back at /100. The per-account unit lives on the *amount*, which this check
    never reads.

    So the numerator sum was sound for GnuCash-written books, and the guard
    it needed was for the other input class: a file something else wrote,
    where 1/2 and -1/4 would have summed to zero. That is what the fraction
    sum is for, and this test is what says the everyday case was never the
    reason.
    """

    LEDGER = str(Path('tests/fixtures/one_transaction_two_account_units.txt'))

    def _book(self, tmp_path):
        gnc = tmp_path / 'mixed.gnucash'
        result = CliRunner().invoke(cli, ['import', '--new', str(gnc), self.LEDGER])
        assert result.exit_code == 0, result.output
        assert 'Errors:       0' in result.output, result.output
        return str(gnc)

    def test_values_are_normalised_to_the_transaction_currency(self, tmp_path):
        """Measured, not assumed — it is what makes the check safe."""
        from gnucash import Query, Session, Transaction

        session = Session(f'xml://{self._book(tmp_path)}')
        try:
            query = Query()
            query.search_for('Trans')
            query.set_book(session.book)
            values, amounts = set(), set()
            for raw in query.run():
                for split in Transaction(instance=raw).GetSplitList():
                    values.add(split.GetValue().denom())
                    amounts.add(split.GetAmount().denom())
            query.destroy()
        finally:
            session.end()

        assert values == {100}, values
        assert amounts == {100, 1000}, amounts

    def test_validate_does_not_call_it_unbalanced(self, tmp_path):
        result = CliRunner().invoke(cli, ['validate', self._book(tmp_path)])

        assert result.exit_code == 0, result.output
        assert 'VALIDATION REPORT' in result.output, result.output
        assert 'UNBALANCED' not in result.output, result.output


class TestADifferenceGnuCashHadToPark:
    def test_the_book_holds_an_imbalance_split(self, book_with_an_imbalance):
        """The premise: the transaction balances, and an Imbalance split is why."""
        from gnucash import Query, Session, Transaction

        session = Session(f'xml://{book_with_an_imbalance}')
        try:
            query = Query()
            query.search_for('Trans')
            query.set_book(session.book)
            names = [s.GetAccount().GetName()
                     for raw in query.run()
                     for s in Transaction(instance=raw).GetSplitList()]
            query.destroy()
        finally:
            session.end()

        assert any(n.startswith('Imbalance') for n in names), names

    def test_validate_reports_it(self, book_with_an_imbalance):
        """The check that can actually fire on a GnuCash book.

        "Do the splits sum to zero" never can — the engine guarantees they
        do — so the money that failed to balance sat in `Imbalance-CAD` with
        nothing looking for it.
        """
        result = CliRunner().invoke(cli, ['validate', book_with_an_imbalance])

        assert 'IMBALANCE_SPLIT' in result.output, result.output
        assert 'Does not add up' in result.output
        assert 'Imbalance' in result.output

    def test_it_is_a_warning_rather_than_an_error(self, book_with_an_imbalance):
        """A book mid-reconciliation is not a broken book.

        A bank feed lands the money and leaves the other side in Imbalance
        until someone classifies it — this repo's own fixtures call that "the
        shape a bank feed leaves". Reported as an error, `validate` would
        fail every book with an unclassified deposit in it.
        """
        result = CliRunner().invoke(cli, ['validate', book_with_an_imbalance])

        assert result.exit_code == 0, result.output
        warnings = result.output.split('WARNINGS')[-1]
        assert 'IMBALANCE_SPLIT' in warnings, result.output

    def test_an_account_merely_named_like_one_is_not_flagged(
            self, book_named_like_an_imbalance):
        """`Imbalance Reserve` is somebody's own account, not GnuCash's.

        The names GnuCash generates are `Imbalance-<CUR>`; a prefix match
        swept up anything a user happened to name similarly and reported
        their ordinary transactions.
        """
        result = CliRunner().invoke(cli, ['validate', book_named_like_an_imbalance])

        # The positive assertions come first: `'X' not in result.output` is
        # true of empty output, and a crash leaves it empty — so on its own it
        # would pass against a `validate` that never examined the book. This
        # is the only test standing behind matching `Imbalance-<CUR>` exactly
        # rather than by prefix, so it has to be able to fail.
        assert result.exit_code == 0, result.output
        # `validate` names only what it flags, and it flags nothing here, so
        # the positive assertion is that it said so. Written as `'Set aside'
        # in output or 'no issues' in output` it read like two ways of
        # passing, but the left side can never be true of a transaction the
        # check ignores — a disjunction with one live arm, which is a
        # single-sided assertion wearing a second.
        assert 'no issues' in result.output, result.output
        assert 'IMBALANCE_SPLIT' not in result.output, result.output



class TestAnImbalanceNamedAfterASecurity:
    """GnuCash names the account after whatever failed to balance.

    So a fund leaves `Imbalance-FUNDX` and a stock `Imbalance-USTECH`, not
    three letters. Matched as `Imbalance-[A-Z]{3}` the check saw only the
    currency case and called such a book clean — and those are exactly the
    ones the beancount round-trip work kept producing, from a security
    posting valued in its own units.
    """

    def _book_with_a_fund_imbalance(self, tmp_path):
        """12.345 FUNDX in, nothing out: GnuCash invents the counterpart."""
        import gnucash
        from gnucash import (
            Account,
            GncCommodity,
            GncNumeric,
            Session,
            Split,
            Transaction,
        )

        path = str(tmp_path / 'fund.gnucash')
        try:
            from gnucash import SessionOpenMode
            session = Session(f'xml://{path}', SessionOpenMode.SESSION_NEW_STORE)
        except ImportError:
            session = Session(f'xml://{path}', is_new=True)

        book = session.book
        root = book.get_root_account()
        table = book.get_table()
        cad = table.lookup('CURRENCY', 'CAD')
        table.insert(GncCommodity(book, 'Example Fund', 'FUND', 'FUNDX', '', 100))
        fundx = table.lookup('FUND', 'FUNDX')

        assets = Account(book)
        assets.SetName('Assets')
        assets.SetType(gnucash.ACCT_TYPE_ASSET)
        assets.SetCommodity(cad)
        root.append_child(assets)

        fund = Account(book)
        fund.SetName('Fund')
        fund.SetType(gnucash.ACCT_TYPE_MUTUAL)
        fund.SetCommodity(fundx)
        assets.append_child(fund)

        lopsided = Transaction(book)
        lopsided.BeginEdit()
        lopsided.SetCurrency(fundx)
        lopsided.SetDate(4, 2, 2024)
        lopsided.SetDescription('Units with nothing on the other side')
        only = Split(book)
        only.SetParent(lopsided)
        only.SetAccount(fund)
        only.SetValue(GncNumeric(12345, 1000))
        only.SetAmount(GncNumeric(12345, 1000))
        lopsided.CommitEdit()

        session.save()
        session.end()
        return path

    def test_the_premise_gnucash_named_it_after_the_fund(self, tmp_path):
        """Or this is a test about a book that does not exist."""
        from gnucash import Query, Session, Transaction

        path = self._book_with_a_fund_imbalance(tmp_path)
        session = Session(f'xml://{path}')
        try:
            query = Query()
            query.search_for('Trans')
            query.set_book(session.book)
            names = {split.GetAccount().GetName()
                     for raw in query.run()
                     for split in Transaction(instance=raw).GetSplitList()}
            query.destroy()
        finally:
            session.end()

        assert 'Imbalance-FUNDX' in names, names

    def test_validate_flags_it(self, tmp_path):
        path = self._book_with_a_fund_imbalance(tmp_path)

        result = CliRunner().invoke(cli, ['validate', path])

        assert 'IMBALANCE_SPLIT' in result.output, result.output
        assert 'Imbalance-FUNDX' in result.output, result.output


class TestTheOtherAccountTheScrubInvents:
    """`Orphan-<mnemonic>`, for a split whose account has gone missing.

    GnuCash's scrub makes two accounts, not one: `Imbalance-` takes money an
    entry did not account for, `Orphan-` takes a split left without an
    account — a partial merge, a damaged file, or a run of Actions → Check &
    Repair. Same construction and the same reason to look at it, and
    `SPLIT_NO_ACCOUNT` cannot cover it, because after the scrub the split does
    have an account.
    """

    def _book_with_an_orphan_account(self, tmp_path):
        """An account named the way the scrub names one, with a split on it."""
        import gnucash
        from gnucash import Account, GncNumeric, Session, Split, Transaction

        path = str(tmp_path / 'orphan.gnucash')
        try:
            from gnucash import SessionOpenMode
            session = Session(f'xml://{path}', SessionOpenMode.SESSION_NEW_STORE)
        except ImportError:
            session = Session(f'xml://{path}', is_new=True)

        book = session.book
        root = book.get_root_account()
        cad = book.get_table().lookup('CURRENCY', 'CAD')

        def child(parent, name, kind):
            account = Account(book)
            account.SetName(name)
            account.SetType(kind)
            account.SetCommodity(cad)
            parent.append_child(account)
            return account

        assets = child(root, 'Assets', gnucash.ACCT_TYPE_ASSET)
        bank = child(assets, 'Bank', gnucash.ACCT_TYPE_BANK)
        orphan = child(root, 'Orphan-CAD', gnucash.ACCT_TYPE_BANK)

        transaction = Transaction(book)
        transaction.BeginEdit()
        transaction.SetCurrency(cad)
        transaction.SetDate(4, 2, 2024)
        transaction.SetDescription('Scrubbed into an orphan account')
        out = Split(book)
        out.SetParent(transaction)
        out.SetAccount(bank)
        out.SetValue(GncNumeric(-1000, 100))
        back = Split(book)
        back.SetParent(transaction)
        back.SetAccount(orphan)
        back.SetValue(GncNumeric(1000, 100))
        transaction.CommitEdit()

        session.save()
        session.end()
        return path

    def test_validate_flags_it(self, tmp_path):
        path = self._book_with_an_orphan_account(tmp_path)

        result = CliRunner().invoke(cli, ['validate', path])

        assert 'IMBALANCE_SPLIT' in result.output, result.output
        assert 'Orphan-CAD' in result.output, result.output

    def test_the_message_says_what_an_orphan_account_means(self, tmp_path):
        path = self._book_with_an_orphan_account(tmp_path)

        result = CliRunner().invoke(cli, ['validate', path])

        assert 'account has gone missing' in result.output, result.output


class TestASplitWithNoCounterpart:
    def test_the_book_really_holds_one_split(self, book_with_a_lone_split):
        """The premise, asserted — or the rest proves nothing.

        If GnuCash had added a counterpart the transaction would be ordinary
        and the check below would be reporting something else.
        """
        from gnucash import Query, Session, Transaction

        session = Session(f'xml://{book_with_a_lone_split}')
        try:
            query = Query()
            query.search_for('Trans')
            query.set_book(session.book)
            counts = [len(Transaction(instance=raw).GetSplitList())
                      for raw in query.run()]
            query.destroy()
        finally:
            session.end()

        assert 1 in counts, counts

    def test_validate_reports_it(self, book_with_a_lone_split):
        result = CliRunner().invoke(cli, ['validate', book_with_a_lone_split])

        assert 'SINGLE_SPLIT' in result.output, result.output
        assert 'Only one side' in result.output

    def test_the_book_does_not_validate_clean(self, book_with_a_lone_split):
        result = CliRunner().invoke(cli, ['validate', book_with_a_lone_split])

        assert 'Validation passed with no issues' not in result.output
