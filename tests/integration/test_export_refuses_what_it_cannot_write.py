"""A book holding a figure plaintext cannot express is reported, not written.

A booked amount is a whole number of the currency's units. `18.190` is
`18.19` and writes fine; `1.819` CAD is not a number of cents. GnuCash will
store one — a unit price may carry three decimals, and an account can be kept
to thousandths — but the plaintext format has no way to say it, and the
importer refuses it.

Exported anyway, `export` reported success and wrote a file that `import`
then dropped the transaction from. Worse, the file was opened before the text
was rendered, so a failure part-way truncated the target: exporting over
yesterday's ledger destroyed it and left nothing.

The book is built through the bindings because this tool's own importer will
not write such a split — which is the point, since `export` exists to read
books other things wrote.
"""

import os
import tempfile

import pytest
from click.testing import CliRunner

from cli.main import cli


def _book_holding(numerator, denominator=1000, extra=()):
    """A CAD book whose fuel account is kept to thousandths.

    `extra` adds further transactions at the same denominator, for checking
    that every offender is reported rather than only the first.
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
    bank.SetCommoditySCU(1000)
    assets.append_child(bank)

    expenses = Account(book)
    expenses.SetName('Expenses')
    expenses.SetType(gnucash.ACCT_TYPE_EXPENSE)
    expenses.SetCommodity(cad)
    root.append_child(expenses)

    fuel = Account(book)
    fuel.SetName('Fuel')
    fuel.SetType(gnucash.ACCT_TYPE_EXPENSE)
    fuel.SetCommodity(cad)
    fuel.SetCommoditySCU(1000)
    expenses.append_child(fuel)

    for index, num in enumerate((numerator, *extra)):
        transaction = Transaction(book)
        transaction.BeginEdit()
        transaction.SetCurrency(cad)
        transaction.SetDate(1 + index, 2, 2026)
        transaction.SetDescription(f'Litre {index + 1}')
        out = Split(book)
        out.SetParent(transaction)
        out.SetAccount(fuel)
        out.SetValue(GncNumeric(num, denominator))
        out.SetAmount(GncNumeric(num, denominator))
        back = Split(book)
        back.SetParent(transaction)
        back.SetAccount(bank)
        back.SetValue(GncNumeric(-num, denominator))
        back.SetAmount(GncNumeric(-num, denominator))
        transaction.CommitEdit()

    session.save()
    session.end()
    return path


def _overpaid_invoice_book():
    """A 30.00 invoice paid 50.00, on a receivable kept to thousandths.

    Both halves of the business-objects export write a figure out of it: the
    settling `amount:` and the `prepayment:` left over. Imported cent-clean,
    because the importer will not write either of them finer than that.
    """
    import tempfile as _tempfile

    from click.testing import CliRunner as _CliRunner

    fd, path = _tempfile.mkstemp(suffix='.gnucash')
    os.close(fd)
    os.unlink(path)
    runner = _CliRunner()
    first = runner.invoke(cli, [
        'import', '--new', path,
        'tests/fixtures/credit_on_an_account_kept_finer_than_the_cent.txt',
        '--include-business-objects'])
    assert first.exit_code == 0, first.output
    second = runner.invoke(cli, [
        'import', path,
        'tests/fixtures/overpaid_invoice_on_a_finer_account.txt',
        '--include-business-objects'])
    assert second.exit_code == 0, second.output
    return path


def _book_with_an_offender_on_each_side():
    """A sub-cent payment amount *and* an unrelated sub-cent bank split.

    One offender for each half of `--include-business-objects`: the payment
    figure the invoices section writes, and an ordinary split the
    transactions section writes. Nothing links them, so a run that names only
    one is a run that stopped at the first list.
    """
    from pathlib import Path as _Path

    from click.testing import CliRunner as _CliRunner

    path = _book_with_a_sub_cent_payment()
    ordinary = _Path('tests/fixtures/a_bank_transfer_to_make_sub_cent.txt')
    with tempfile.NamedTemporaryFile('w', suffix='.txt', delete=False) as handle:
        handle.write(ordinary.read_text())
        ledger = handle.name
    try:
        result = _CliRunner().invoke(cli, ['import', path, ledger])
        assert result.exit_code == 0, result.output
    finally:
        os.unlink(ledger)
    return _move_a_bank_split(path, 4000, 40005)


def _move_a_bank_split(path, cents, thousandths):
    """The same move on the bank side, for a transaction-section offender."""
    from gnucash import GncNumeric, Query, Session, Transaction

    session = Session(f'xml://{path}')
    try:
        query = Query()
        query.search_for('Trans')
        query.set_book(session.book)
        moved = 0
        for raw in query.run():
            transaction = Transaction(instance=raw)
            for split in transaction.GetSplitList():
                amount = split.GetAmount()
                if split.GetAccount().get_full_name() != 'Assets.Bank':
                    continue
                if amount.num() * 100 != cents * amount.denom():
                    continue
                transaction.BeginEdit()
                split.SetAmount(GncNumeric(thousandths, 1000))
                split.SetValue(GncNumeric(thousandths, 1000))
                transaction.CommitEdit()
                moved += 1
        query.destroy()
        assert moved == 1, f'expected one bank split at {cents / 100}, moved {moved}'
        session.save()
    finally:
        session.end()
    return path


def _move_a_receivable_split(path, cents, thousandths):
    """Move the A/R split holding `cents` to `thousandths`, through GnuCash.

    Which is how a book comes to hold such a figure: the account's unit takes
    it and the GUI writes it, while this tool's importer refuses to.
    """
    from gnucash import GncNumeric, Query, Session, Transaction

    session = Session(f'xml://{path}')
    try:
        query = Query()
        query.search_for('Trans')
        query.set_book(session.book)
        moved = 0
        for raw in query.run():
            transaction = Transaction(instance=raw)
            for split in transaction.GetSplitList():
                amount = split.GetAmount()
                if 'Receivable' not in split.GetAccount().get_full_name():
                    continue
                if amount.num() * 100 != cents * amount.denom():
                    continue
                transaction.BeginEdit()
                split.SetAmount(GncNumeric(thousandths, 1000))
                split.SetValue(GncNumeric(thousandths, 1000))
                transaction.CommitEdit()
                moved += 1
        query.destroy()
        assert moved == 1, f'expected one split at {cents / 100}, moved {moved}'
        session.save()
    finally:
        session.end()
    return path


def _book_with_a_sub_cent_payment():
    """The settling split moved to 30.005, which `amount:` has to say."""
    return _move_a_receivable_split(_overpaid_invoice_book(), -3000, -30005)


def _book_with_a_sub_cent_prepayment():
    """The residue moved to 20.005, leaving the settlement whole cents.

    `amount:` is checked eighty lines earlier, so a book where both are
    sub-cent refuses there and never reaches the prepayment line.
    """
    return _move_a_receivable_split(_overpaid_invoice_book(), -2000, -20005)


def _book_with_two_sub_cent_payments():
    """Two invoices, each settled by a figure the format cannot write.

    A second overpaid invoice for the same customer, at amounts that differ
    from the first so each settling split can be moved on its own.
    """
    from pathlib import Path as _Path

    from click.testing import CliRunner as _CliRunner

    path = _overpaid_invoice_book()
    second = (_Path('tests/fixtures/overpaid_invoice_on_a_finer_account.txt')
              .read_text()
              .replace('INV-FINE-OVER', 'INV-FINE-TWO')
              .replace('price: 30', 'price: 40')
              .replace('amount: 50.00', 'amount: 55.00')
              .replace('prepayment: 20.00', 'prepayment: 15.00'))
    with tempfile.NamedTemporaryFile('w', suffix='.txt', delete=False) as handle:
        handle.write(second)
        ledger = handle.name
    try:
        result = _CliRunner().invoke(cli, [
            'import', path, ledger, '--include-business-objects'])
        assert result.exit_code == 0, result.output
    finally:
        os.unlink(ledger)
    _move_a_receivable_split(path, -3000, -30005)
    _move_a_receivable_split(path, -4000, -40005)
    return path


@pytest.fixture
def book_with_a_sub_cent_amount():
    """1.819 CAD — a figure the currency cannot hold."""
    path = _book_holding(1819)
    yield path
    if os.path.exists(path):
        os.unlink(path)


@pytest.fixture
def book_with_a_trailing_zero():
    """18.190 CAD — which is 18.19, and writes fine."""
    path = _book_holding(18190)
    yield path
    if os.path.exists(path):
        os.unlink(path)


class TestAFigureItCannotWrite:
    def test_the_export_is_refused_and_names_the_split(
            self, book_with_a_sub_cent_amount, tmp_path):
        out = tmp_path / 'out.txt'
        result = CliRunner().invoke(
            cli, ['export', book_with_a_sub_cent_amount, str(out)])

        assert result.exit_code != 0, result.output
        assert 'Expenses:Fuel' in result.output, result.output
        assert '1.819' in result.output, result.output
        assert 'smallest unit is 0.01' in result.output, result.output

    def test_it_says_a_unit_price_may_carry_more_decimals(
            self, book_with_a_sub_cent_amount, tmp_path):
        """The distinction that makes the refusal actionable."""
        result = CliRunner().invoke(
            cli, ['export', book_with_a_sub_cent_amount,
                  str(tmp_path / 'out.txt')])

        assert 'unit price may carry more decimals' in result.output

    def test_no_file_is_written(self, book_with_a_sub_cent_amount, tmp_path):
        out = tmp_path / 'out.txt'
        CliRunner().invoke(cli, ['export', book_with_a_sub_cent_amount, str(out)])

        assert not out.exists(), 'a failed export left a file behind'

    def test_an_existing_export_is_not_destroyed(
            self, book_with_a_sub_cent_amount, tmp_path):
        """The target was opened before the text was rendered.

        So a refusal part-way through truncated whatever was already there —
        exporting over yesterday's ledger destroyed it and wrote nothing.
        """
        previous = tmp_path / 'yesterday.txt'
        previous.write_text('# a previous export the user still needs\n')
        before = previous.read_text()

        result = CliRunner().invoke(
            cli, ['export', book_with_a_sub_cent_amount, str(previous)])

        assert result.exit_code != 0, result.output
        assert previous.read_text() == before, 'the previous export was clobbered'


class TestTheOtherExport:
    """`export-beancount` refuses the same figure, for the same reason.

    Beancount could state `1.819 CAD` faithfully — but the importer will not
    read a sub-cent currency amount back, so writing it produced a file this
    tool could not import: `export-beancount` exited 0 and `import-beancount`
    on its own output reported `Transactions: 0` and named the amount. One
    export refusing what the other writes is wrong either way round; this is
    the direction that matches the rule the importer enforces.
    """

    def test_it_is_refused_and_names_the_split(
            self, book_with_a_sub_cent_amount, tmp_path):
        out = tmp_path / 'out.beancount'
        result = CliRunner().invoke(
            cli, ['export-beancount', book_with_a_sub_cent_amount, str(out)])

        assert result.exit_code != 0, result.output
        assert 'Expenses:Fuel' in result.output, result.output
        assert '1.819' in result.output, result.output

    def test_no_file_is_written(self, book_with_a_sub_cent_amount, tmp_path):
        out = tmp_path / 'out.beancount'
        CliRunner().invoke(
            cli, ['export-beancount', book_with_a_sub_cent_amount, str(out)])

        assert not out.exists(), 'a failed export left a file behind'

    def test_every_offender_is_named_in_a_single_run(self, tmp_path):
        """The same as the plaintext export: a book of thousands should not
        be fixed one run at a time, whichever format is being written."""
        path = _book_holding(1819, extra=(2725,))
        try:
            result = CliRunner().invoke(
                cli, ['export-beancount', path, str(tmp_path / 'o.beancount')])

            assert result.exit_code != 0, result.output
            assert '2 transaction(s)' in result.output, result.output
            assert '1.819' in result.output, result.output
            assert '2.725' in result.output, result.output
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_a_figure_it_can_write_still_round_trips(
            self, book_with_a_trailing_zero, tmp_path):
        """18.190 is 18.19, so nothing here is refused."""
        out = tmp_path / 'out.beancount'
        assert CliRunner().invoke(cli, [
            'export-beancount', book_with_a_trailing_zero,
            str(out)]).exit_code == 0

        back = tmp_path / 'back.gnucash'
        result = CliRunner().invoke(
            cli, ['import-beancount', str(back), str(out)])
        assert result.exit_code == 0, result.output


class TestTheBusinessObjectsHalf:
    """`--include-business-objects` writes payment figures too.

    A payment's `amount:` and an overpayment's `prepayment:` are booked
    amounts written out of the same books, and that half of the export had no
    such rule — so a receivable kept to a tenth of a cent holding a 50.005
    payment exported cleanly and re-imported as a refusal. Both importers
    judge those two keys against the currency now, and this is the export
    saying the same thing.
    """

    def test_a_payment_finer_than_the_cent_is_refused(self, tmp_path):
        """Named by the payment line, not by the transaction that holds it.

        The same split is in the transaction section too, and that refusal
        would satisfy an assertion on `50.005` alone — so this asserts the one
        string only the business-objects guard writes, and the invoice it
        now names.
        """
        path = _book_with_a_sub_cent_payment()
        try:
            result = CliRunner().invoke(cli, [
                'export', path, str(tmp_path / 'out.txt'),
                '--include-business-objects'])

            assert result.exit_code != 0, result.output
            assert 'the payment amount' in result.output, result.output
            assert 'invoice "INV-FINE-OVER"' in result.output, result.output
            assert '30.005' in result.output, result.output
            assert 'smallest unit is 0.01' in result.output, result.output
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_a_prepayment_finer_than_the_cent_is_refused(self, tmp_path):
        """The residual line, which the payment line cannot stand in for.

        `amount:` is checked eighty lines earlier, so a book where both are
        sub-cent refuses there and never reaches this. Reaching it needs a
        settlement in whole cents whose *residue* is not — an overpayment
        moved so that only the credit left over carries the third decimal.
        """
        path = _book_with_a_sub_cent_prepayment()
        try:
            result = CliRunner().invoke(cli, [
                'export', path, str(tmp_path / 'out.txt'),
                '--include-business-objects'])

            assert result.exit_code != 0, result.output
            assert 'the prepayment' in result.output, result.output
            assert 'the payment amount' not in result.output, result.output
            assert '20.005' in result.output, result.output
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_nothing_is_written(self, tmp_path):
        path = _book_with_a_sub_cent_payment()
        out = tmp_path / 'out.txt'
        try:
            CliRunner().invoke(cli, [
                'export', path, str(out), '--include-business-objects'])

            assert not out.exists(), 'a failed export left a file behind'
        finally:
            if os.path.exists(path):
                os.unlink(path)


class TestSeveralOffenders:
    def test_every_one_is_named_in_a_single_run(self, tmp_path):
        """A book of thousands should not be fixed one export at a time."""
        path = _book_holding(1819, extra=(2725,))
        try:
            result = CliRunner().invoke(
                cli, ['export', path, str(tmp_path / 'out.txt')])

            assert result.exit_code != 0, result.output
            assert '2 transaction(s)' in result.output, result.output
            assert '1.819' in result.output, result.output
            assert '2.725' in result.output, result.output
        finally:
            if os.path.exists(path):
                os.unlink(path)


class TestAnOffenderOnEachSide:
    """Both lists are gathered, so the book is still fixed in one pass.

    Each half gathers its own offenders, but the invoices are written first
    and refused before the transactions section was ever formatted — so a book
    with one of each named only the invoice, and the reader who corrected it
    met the split on the next run. Two runs to learn two figures, out of a
    guard whose whole purpose is that a book of thousands is not fixed one run
    at a time.
    """

    def test_both_are_named_in_a_single_run(self, tmp_path):
        path = _book_with_an_offender_on_each_side()
        try:
            result = CliRunner().invoke(cli, [
                'export', path, str(tmp_path / 'out.txt'),
                '--include-business-objects'])

            assert result.exit_code != 0, result.output
            # The payment, from the invoices half...
            assert 'invoice "INV-FINE-OVER"' in result.output, result.output
            assert '30.005' in result.output, result.output
            # ...and the ordinary split, from the transactions half.
            assert '40.005' in result.output, result.output
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_nothing_is_written(self, tmp_path):
        path = _book_with_an_offender_on_each_side()
        out = tmp_path / 'out.txt'
        try:
            CliRunner().invoke(cli, [
                'export', path, str(out), '--include-business-objects'])

            assert not out.exists(), 'a failed export left a file behind'
        finally:
            if os.path.exists(path):
                os.unlink(path)


class TestSeveralOffendingInvoices:
    """The business-objects half gathers them too.

    It refused on the first invoice, so a book with several unwritable
    payment amounts took one run per payment — and since the business objects
    are written before the transactions section, that book's transaction-level
    offenders were never reported at all. The same principle as the
    transaction export above, which had the opposite behaviour.
    """

    def test_both_invoices_are_named_in_a_single_run(self, tmp_path):
        path = _book_with_two_sub_cent_payments()
        try:
            result = CliRunner().invoke(cli, [
                'export', path, str(tmp_path / 'out.txt'),
                '--include-business-objects'])

            assert result.exit_code != 0, result.output
            assert '2 business object(s)' in result.output, result.output
            assert 'invoice "INV-FINE-OVER"' in result.output, result.output
            assert 'invoice "INV-FINE-TWO"' in result.output, result.output
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_both_figures_are_shown(self, tmp_path):
        """Naming the invoices is not enough to go and fix them by."""
        path = _book_with_two_sub_cent_payments()
        try:
            result = CliRunner().invoke(cli, [
                'export', path, str(tmp_path / 'out.txt'),
                '--include-business-objects'])

            assert '30.005' in result.output, result.output
            assert '40.005' in result.output, result.output
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_nothing_is_written(self, tmp_path):
        """Collecting them does not mean writing the invoices that were fine."""
        path = _book_with_two_sub_cent_payments()
        out = tmp_path / 'out.txt'
        try:
            CliRunner().invoke(cli, [
                'export', path, str(out), '--include-business-objects'])

            assert not out.exists(), 'a failed export left a file behind'
        finally:
            if os.path.exists(path):
                os.unlink(path)


class TestAFigureItCanWrite:
    def test_a_trailing_zero_exports_and_re_imports(
            self, book_with_a_trailing_zero, tmp_path):
        """18.190 is 18.19: written at the account's unit, and legal."""
        out = tmp_path / 'out.txt'
        exported = CliRunner().invoke(
            cli, ['export', book_with_a_trailing_zero, str(out)])

        assert exported.exit_code == 0, exported.output
        assert 'Expenses:Fuel 18.190 CAD' in out.read_text()

        back = tmp_path / 'back.gnucash'
        result = CliRunner().invoke(cli, ['import', '--new', str(back), str(out)])
        assert result.exit_code == 0, result.output
        assert 'Errors:       0' in result.output, result.output
