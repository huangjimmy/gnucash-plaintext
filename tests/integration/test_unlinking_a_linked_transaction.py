"""Unlinking the transaction that paid an invoice: it stays, the invoice owes.

An invoice can be paid without entering any money. The bank feed came in
first, or a director paid out of pocket, so the transaction is already in the
book; a `payment:` block giving its guid puts the receivable's account on one
of its splits, and that split becomes the settlement. Q-039 is that path.

Undoing it leaves a payment with nothing to do with the invoice: the split
comes off the receivable, leaves the lot, and takes the account `--to` gives.

There was no way back. `unapply-payment` detaches a payment and puts `--to` on
the payment split, which is the right shape, but it set the account and nothing
else: a 100.00 USD split given a CAD account kept the figure 100.00 and now
means 100.00 CAD. That is the defect Q-039 was reported for, in reverse.

A split never moves — it belongs to one transaction, and what changes is the
account on the split. The two figures a split carries make the new one readable
without a rate: an amount, in the commodity of the account the split is on, and
a value, in the currency the transaction is quoted in. So where the new account
is kept in the currency the transaction is quoted in, the value **is** the
figure to write. Nothing converts, and nothing has to be stated.
"""

from fractions import Fraction
from pathlib import Path

import pytest
from click.testing import CliRunner
from gnucash import Query, Transaction

from cli.main import cli
from infrastructure.gnucash.utils import get_account_full_name
from repositories.gnucash_repository import GnuCashRepository, SessionMode

FIXTURES = Path('tests/fixtures')
BOOK = str(FIXTURES / 'fx_usd_invoice_cad_income.txt')
RATES = str(FIXTURES / 'fx_rates_usd_dated.yaml')
AR_USD = 'Assets:Accounts Receivable USD'
DIRECTOR = 'Assets:Due From Director'


def _splits_of(book, description):
    """Every split of the transaction with this description: account, amount
    and value.

    The value matters here as much as the amount: what a split is worth in its
    transaction's currency is the figure an account kept in that currency has
    to take, and it is the one setting the account alone leaves untouched.

    `get_account_full_name` rather than GnuCash's own `get_full_name`, which
    separates with whatever the book's separator is — a dot in these images.
    """
    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        query = Query()
        query.search_for('Trans')
        query.set_book(repo.book)
        rows = []
        for raw in query.run():
            transaction = Transaction(instance=raw)
            if transaction.GetDescription() != description:
                continue
            for split in transaction.GetSplitList():
                rows.append({
                    'account': get_account_full_name(split.GetAccount()),
                    'amount': Fraction(split.GetAmount().num(),
                                       split.GetAmount().denom()),
                    'value': Fraction(split.GetValue().num(),
                                      split.GetValue().denom()),
                    'in_a_lot': split.GetLot() is not None,
                })
        query.destroy()
        return sorted(rows, key=lambda row: row['account'])
    finally:
        repo.close()


def _splits_on_account(book, account_name):
    """Every split amount on this account, whatever transaction it belongs to.

    By account rather than by description, for the checks that ask whether a
    run wrote anything at all: a payment transaction takes the owner's name,
    not the memo the block states, so a description no transaction has matches
    nothing and asserts nothing.
    """
    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        query = Query()
        query.search_for('Trans')
        query.set_book(repo.book)
        found = []
        for raw in query.run():
            for split in Transaction(instance=raw).GetSplitList():
                if get_account_full_name(split.GetAccount()) == account_name:
                    found.append(Fraction(split.GetAmount().num(),
                                          split.GetAmount().denom()))
        query.destroy()
        return found
    finally:
        repo.close()


MONEY = str(FIXTURES / 'money_parked_in_usd_that_reached_a_cad_bank.txt')
LINKED = str(FIXTURES / 'a_payment_giving_the_usd_split_behind_a_cad_bank.txt')
DESCRIPTION = 'Money in, USD parked, CAD bank'


def _linked_book(tmp_path):
    """The book Q-039 makes: a USD invoice settled by a split of a CAD entry.

    `Assets:Bank` +139.00 CAD against `Assets:Suspense USD` −100.00 USD, whose
    own value is −139.00 CAD. Linking puts the USD receivable's account on that
    USD split, where it states the settlement outright and nothing but the
    account changes.
    """
    path = tmp_path / 'linked.gnucash'
    runner = CliRunner()
    first = runner.invoke(cli, [
        'import', '--new', str(path), BOOK,
        '--include-business-objects', '--fx-rates', RATES])
    assert first.exit_code == 0, first.output
    assert runner.invoke(cli, ['import', str(path), MONEY]).exit_code == 0
    linked = runner.invoke(cli, [
        'import', str(path), LINKED,
        '--include-business-objects', '--fx-rates', RATES])
    assert linked.exit_code == 0, linked.output

    on_ar = [row for row in _splits_of(path, DESCRIPTION)
             if row['account'] == AR_USD]
    assert len(on_ar) == 1, _splits_of(path, DESCRIPTION)
    assert on_ar[0]['amount'] == -100, on_ar
    assert on_ar[0]['value'] == -139, on_ar
    assert on_ar[0]['in_a_lot'], 'the link put it in the invoice lot'
    return path


CENTS_MONEY = str(FIXTURES / 'money_reaching_a_cad_bank_at_a_rate_with_cents.txt')
CENTS_LINK = str(FIXTURES / 'a_payment_giving_the_split_valued_at_a_rate_with_cents.txt')
CENTS_DESCRIPTION = 'Money in at a rate with cents'
DIRECTOR_WHOLE = 'Assets:Due From Director Whole'
COARSE_ACCOUNT = str(FIXTURES / 'an_account_kept_to_whole_dollars.txt')


def _book_valued_with_cents(tmp_path):
    """The same link, at a rate that does not come out even.

    The split is worth −139.37 CAD rather than −139.00, so the figure a CAD
    account takes has cents in it — which is what an account kept to whole
    dollars cannot state. `Assets:Due From Director Whole` is that account,
    opened by the same fixture.
    """
    path = tmp_path / 'cents.gnucash'
    runner = CliRunner()
    first = runner.invoke(cli, [
        'import', '--new', str(path), BOOK,
        '--include-business-objects', '--fx-rates', RATES])
    assert first.exit_code == 0, first.output
    money = runner.invoke(cli, ['import', str(path), CENTS_MONEY])
    assert money.exit_code == 0, money.output
    coarse = runner.invoke(cli, ['import', str(path), COARSE_ACCOUNT])
    assert coarse.exit_code == 0, coarse.output
    linked = runner.invoke(cli, [
        'import', str(path), CENTS_LINK,
        '--include-business-objects', '--fx-rates', RATES])
    assert linked.exit_code == 0, linked.output

    on_ar = [row for row in _splits_of(path, CENTS_DESCRIPTION)
             if row['account'] == AR_USD]
    assert len(on_ar) == 1, _splits_of(path, CENTS_DESCRIPTION)
    assert on_ar[0]['value'] == Fraction(-13937, 100), on_ar
    assert on_ar[0]['in_a_lot'], 'the link put it in the invoice lot'
    return path


HKD_MONEY = str(FIXTURES / 'money_parked_in_usd_that_reached_an_hkd_bank.txt')
HKD_LINK = str(FIXTURES / 'a_payment_giving_the_usd_split_behind_an_hkd_bank.txt')
HKD_DESCRIPTION = 'Money in, USD parked, HKD bank'
RATES_HKD = str(FIXTURES / 'fx_rates_usd_and_hkd.yaml')


def _book_behind_an_hkd_bank(tmp_path):
    """A USD invoice settled by a split of an entry quoted in a third currency.

    The book is CAD, the invoice USD, the entry HKD — so neither side of the
    transaction is the book's own currency, and the split's value is in a
    currency an account may not be kept in.
    """
    path = tmp_path / 'hkd.gnucash'
    runner = CliRunner()
    first = runner.invoke(cli, [
        'import', '--new', str(path), BOOK,
        '--include-business-objects', '--fx-rates', RATES_HKD])
    assert first.exit_code == 0, first.output
    money = runner.invoke(cli, ['import', str(path), HKD_MONEY])
    assert money.exit_code == 0, money.output
    linked = runner.invoke(cli, [
        'import', str(path), HKD_LINK,
        '--include-business-objects', '--fx-rates', RATES_HKD])
    assert linked.exit_code == 0, linked.output

    on_ar = [row for row in _splits_of(path, HKD_DESCRIPTION)
             if row['account'] == AR_USD]
    assert len(on_ar) == 1, _splits_of(path, HKD_DESCRIPTION)
    assert on_ar[0]['amount'] == -100, on_ar
    assert on_ar[0]['value'] == -780, on_ar
    assert on_ar[0]['in_a_lot'], 'the link put it in the invoice lot'
    return path


BILL_BOOK = str(FIXTURES / 'fx_usd_bill_cad_expense.txt')
DIRECTOR_PAID = str(FIXTURES / 'a_director_paying_a_supplier_out_of_pocket.txt')
BILL_LINKED = str(FIXTURES / 'a_bill_settled_by_what_the_director_paid.txt')
DIRECTOR_CAD = 'Assets:Due From Director'
RATES_JPY = str(FIXTURES / 'fx_rates_usd_and_jpy.yaml')
RATES_WITH_CENTS = str(FIXTURES / 'fx_rates_usd_at_a_rate_with_cents.yaml')


SEVERAL = str(FIXTURES / 'invoices_in_each_state_to_unapply.txt')
OWED_BACK = 'Liabilities:Owed Back'
CAD_IN_A_USD_ENTRY = str(FIXTURES / 'a_cad_split_of_a_usd_quoted_entry.txt')
CAD_SPLIT_LINK = str(FIXTURES / 'a_payment_giving_the_cad_split_of_a_usd_entry.txt')


class TestChoosingAmongSeveralPayments:
    """`--txn` and `--all` on a record paid in two instalments.

    Covered through `unapply-payment` elsewhere, and both commands run the
    same code — but `unlink`'s own selectors were exercised only by the
    refusals, which reads as more complete than it was.
    """

    @pytest.fixture
    def book(self, tmp_path):
        path = tmp_path / 'several.gnucash'
        result = CliRunner().invoke(cli, [
            'import', '--new', str(path), SEVERAL,
            '--include-business-objects'])
        assert result.exit_code == 0, result.output
        return path

    def _guids(self, book):
        refused = CliRunner().invoke(cli, [
            'unlink', str(book), 'INV-TWICE', '--to', OWED_BACK])
        line, = [ln for ln in refused.output.splitlines() if 'payments: ' in ln]
        return line.split('payments: ')[1].strip().split(', ')

    def test_naming_one_takes_that_one_off(self, book):
        first, _second = self._guids(book)

        result = CliRunner().invoke(cli, [
            'unlink', str(book), 'INV-TWICE', '--txn', first,
            '--to', OWED_BACK])

        assert result.exit_code == 0, result.output
        assert first in result.output, result.output

    def test_and_leaves_the_other_applied(self, book):
        """So the record is unambiguous now, not empty: a bare run works."""
        first, _second = self._guids(book)
        CliRunner().invoke(cli, ['unlink', str(book), 'INV-TWICE',
                                 '--txn', first, '--to', OWED_BACK])

        after = CliRunner().invoke(cli, [
            'unlink', str(book), 'INV-TWICE', '--to', OWED_BACK])

        assert after.exit_code == 0, after.output
        assert 'unlinked' in after.output, after.output

    def test_the_splits_own_currency_wins_over_the_entrys(self, book):
        """A CAD split of a USD-quoted entry needs no rate.

        Two rows of the table match a CAD `--to` here — the split's own
        commodity, and "kept in CAD where the entry is quoted elsewhere" — and
        the first is tested first, so the split takes its own amount. Read the
        other way round the run would ask for `--fx-rates` it has no use for,
        and a reader with no rates file would think the unlink impossible.

        The other books here are all held=USD; this is the only one where the
        ordering decides the answer.
        """
        assert CliRunner().invoke(cli, [
            'import', str(book), CAD_IN_A_USD_ENTRY]).exit_code == 0
        linked = CliRunner().invoke(cli, [
            'import', str(book), CAD_SPLIT_LINK, '--include-business-objects'])
        assert linked.exit_code == 0, linked.output

        result = CliRunner().invoke(cli, [
            'unlink', str(book), 'INV-UNPAID', '--to', OWED_BACK])

        assert result.exit_code == 0, result.output
        assert 'fx-rates' not in result.output, result.output
        rows = _splits_of(book, 'Money in, CAD parked, USD bank')
        on_owed = [row for row in rows if row['account'] == OWED_BACK]
        assert len(on_owed) == 1, rows
        assert on_owed[0]['amount'] == -100, on_owed

    def test_a_refusal_on_one_of_them_takes_neither_off(self, book):
        """What the two loops in `unapply_payments` are for.

        Every figure is worked out before the first account changes, so a
        refusal on the second payment leaves the first one applied too. Worked
        payment by payment, the 60.00 would have landed on the whole-dollar
        account and the 40.50 would then have been refused, leaving the record
        half undone and the book saved that way.

        Both refusal tests above use records with one payment, where a
        one-loop implementation passes identically — this is the case that
        tells them apart.
        """
        opened = CliRunner().invoke(cli, ['import', str(book), COARSE_ACCOUNT])
        assert opened.exit_code == 0, opened.output

        result = CliRunner().invoke(cli, [
            'unlink', str(book), 'INV-PART-WHOLE', '--all',
            '--to', DIRECTOR_WHOLE])

        assert result.exit_code != 0, result.output
        assert '40.50' in result.output, result.output
        # On the account, not on a description: `_splits_of` matches the
        # transaction's, and 'Whole instalment' is the payment block's memo,
        # which `ApplyPayment` writes onto the splits while the transaction
        # takes the owner's name. Asserted that way the check passed whatever
        # the command had done.
        assert _splits_on_account(book, DIRECTOR_WHOLE) == [], \
            'the whole instalment was written before the other was refused'
        after = CliRunner().invoke(cli, [
            'unlink', str(book), 'INV-PART-WHOLE', '--to', DIRECTOR_WHOLE])
        assert 'has 2 payments' in after.output, after.output

    def test_all_takes_both_off_at_once(self, book):
        result = CliRunner().invoke(cli, [
            'unlink', str(book), 'INV-TWICE', '--all', '--to', OWED_BACK])

        assert result.exit_code == 0, result.output
        assert result.output.count('unlinked') == 2, result.output
        assert 'now owes 100.00 CAD' in result.output, result.output


class TestUnlinkingOnTheBillSide:
    """A payable's signs run the other way, which is where they go unnoticed.

    CLAUDE.md finding 7 is that a bill's payment is the invoice's negated, and
    Q-035 records this project's own lesson: every test of an inference was
    customer-side while the payable ran the other way. The restatement copies
    the split's own value and so carries its sign by construction — this is
    what proves it rather than assuming it.
    """

    def _linked_bill(self, tmp_path):
        path = tmp_path / 'bills.gnucash'
        runner = CliRunner()
        first = runner.invoke(cli, [
            'import', '--new', str(path), BILL_BOOK,
            '--include-business-objects', '--fx-rates', RATES])
        assert first.exit_code == 0, first.output
        assert runner.invoke(cli, ['import', str(path), DIRECTOR_PAID
                                   ]).exit_code == 0
        linked = runner.invoke(cli, [
            'import', str(path), BILL_LINKED,
            '--include-business-objects', '--fx-rates', RATES])
        assert linked.exit_code == 0, linked.output
        return path

    def test_a_converted_figure_is_rounded_to_the_account_and_lands(
            self, tmp_path):
        """The coarse-account refusal guards two branches on purpose.

        A rate may carry any number of decimals, so a conversion produces a
        figure no account could state — 1.39375 against 100.00 is 139.375 —
        and it has to be brought to some unit, the destination account's being
        the only one it could be brought to. Refusing instead would refuse
        ordinary conversions at ordinary rates, on ordinary cent-kept
        accounts.

        A figure *read off the split* is the opposite case: it is already exact
        at a unit the book holds it in, and rounding it loses what the split
        says. So one branch rounds and two refuse, and this is what says the
        difference is meant. Without it the guard could as easily have been put
        on the wrong two branches.

        Measured: 100.00 USD at 1.3937 is 139.37 CAD, and the account counts
        whole dollars, so it takes 139.
        """
        path = self._linked_bill(tmp_path)
        assert CliRunner().invoke(cli, [
            'import', str(path), COARSE_ACCOUNT]).exit_code == 0

        result = CliRunner().invoke(cli, [
            'unlink', str(path), 'BILL-DIRECTOR-001', '--bill',
            '--to', DIRECTOR_WHOLE, '--fx-rates', RATES_WITH_CENTS])

        assert result.exit_code == 0, result.output
        rows = _splits_of(path, 'Director paid the supplier')
        on_whole = [row for row in rows if row['account'] == DIRECTOR_WHOLE]
        assert len(on_whole) == 1, rows
        assert on_whole[0]['amount'] == 139, on_whole

    def test_the_payable_split_keeps_its_sign_through_the_conversion(
            self, tmp_path):
        """+100.00 USD on the payable becomes +140.00 CAD, not −140.00.

        The bill's settlement is positive on the payable, where an invoice's
        is negative on the receivable. The entry is quoted in USD and
        `Assets:Due From Director` is CAD, so nothing on the split is in CAD
        and the rate comes from the file — 1.40, the quote covering
        2026-02-10, since a later one is not extrapolated backwards.
        """
        path = self._linked_bill(tmp_path)

        result = CliRunner().invoke(cli, [
            'unlink', str(path), 'BILL-DIRECTOR-001', '--bill',
            '--to', DIRECTOR_CAD, '--fx-rates', RATES])

        assert result.exit_code == 0, result.output
        rows = _splits_of(path, 'Director paid the supplier')
        on_director = [row for row in rows if row['account'] == DIRECTOR_CAD]
        assert len(on_director) == 1, rows
        assert on_director[0]['amount'] == 140, on_director
        assert on_director[0]['value'] == 100, 'the USD side is the transaction\'s'
        assert not on_director[0]['in_a_lot'], 'it settles nothing now'

    def test_without_rates_it_says_which_file_would_answer_it(self, tmp_path):
        """The book's own currency converts, but only with a rate stated.

        Nothing on this split is in CAD — it holds USD in a USD-quoted entry —
        so there is no figure to read and none to infer. That is the one case
        `--fx-rates` exists for here, and the refusal says so rather than
        raising: click's standalone mode does not catch a plain `Exception`,
        so this reached the reader as a stack trace before the wrapper.
        """
        path = self._linked_bill(tmp_path)

        result = CliRunner().invoke(cli, [
            'unlink', str(path), 'BILL-DIRECTOR-001', '--bill',
            '--to', DIRECTOR_CAD])

        assert result.exit_code != 0, result.output
        assert 'Traceback' not in result.output, result.output
        assert '--fx-rates' in result.output, result.output
        rows = _splits_of(path, 'Director paid the supplier')
        assert not [row for row in rows if row['account'] == DIRECTOR_CAD], rows

    def test_the_rate_it_asks_for_is_the_one_the_file_is_missing(
            self, tmp_path):
        """A USD rate. Asking for a CAD one sent the reader round a loop.

        `rate_fraction` answers CAD with 1 without opening the file, so the
        rate this conversion actually consults is the quoted currency's. The
        refusal asked for the *destination's* — always CAD, since every other
        destination is refused before this point — so a reader who followed it
        added `CAD: 1.0`, changed nothing, and met `No FX rate for USD` on the
        next run.
        """
        path = self._linked_bill(tmp_path)

        result = CliRunner().invoke(cli, [
            'unlink', str(path), 'BILL-DIRECTOR-001', '--bill',
            '--to', DIRECTOR_CAD])

        assert 'a USD rate' in result.output, result.output
        assert 'a CAD rate' not in result.output, result.output

    def test_it_offers_each_currency_that_needs_no_rate_once(self, tmp_path):
        """This bill holds USD in a USD-quoted entry, so there is one.

        The two accounts needing no rate are the one kept in what the split
        holds and the one kept in what the transaction is quoted in. Here they
        are the same currency, and offering both read as "an account kept in
        USD or in USD".
        """
        path = self._linked_bill(tmp_path)

        result = CliRunner().invoke(cli, [
            'unlink', str(path), 'BILL-DIRECTOR-001', '--bill',
            '--to', DIRECTOR_CAD])

        assert 'USD or in USD' not in result.output, result.output
        assert 'kept in USD, which needs no rate' in result.output, result.output


class TestUnlinkingALinkedTransaction:
    def test_the_split_takes_the_value_it_already_carried(self, tmp_path):
        """No rate is asked for, because the split states the figure.

        The entry is quoted in CAD and `--to` is a CAD account, so what the
        split is worth there is its own value — −139.00. Setting the account
        and nothing else would leave −100.00 on a CAD account and turn 100 US
        dollars into 100 Canadian ones.
        """
        path = _linked_book(tmp_path)

        result = CliRunner().invoke(cli, [
            'unlink', str(path), 'INV-USD-001', '--to', DIRECTOR])

        assert result.exit_code == 0, result.output
        rows = _splits_of(path, DESCRIPTION)
        on_director = [row for row in rows if row['account'] == DIRECTOR]
        assert len(on_director) == 1, rows
        assert on_director[0]['amount'] == -139, on_director
        assert on_director[0]['value'] == -139, on_director
        assert not on_director[0]['in_a_lot'], 'it settles nothing now'

    def test_it_reports_the_figure_in_the_currency_it_is_in(self, tmp_path):
        """The line says what came off the record, in the record's currency.

        The figure is the receivable split's, so it is denominated in what the
        invoice is — USD. It was reported beside the *transaction's* currency,
        which on this book is CAD, so the line read `100.00 CAD` for 100 US
        dollars: a figure and a currency that never belonged together.
        """
        path = _linked_book(tmp_path)

        result = CliRunner().invoke(cli, [
            'unlink', str(path), 'INV-USD-001', '--to', DIRECTOR])

        assert result.exit_code == 0, result.output
        assert '100.00 USD' in result.output, result.output
        assert '100.00 CAD' not in result.output, result.output
        assert DIRECTOR in result.output, result.output

    def test_the_transaction_it_came_from_is_left_whole(self, tmp_path):
        """The money is the book's own record and unlinking does not touch it.

        This is the whole reason a link is undone rather than the payment
        being unapplied and rebuilt: the bank feed wrote this entry, and its
        other side has to come through unchanged.
        """
        path = _linked_book(tmp_path)

        result = CliRunner().invoke(cli, [
            'unlink', str(path), 'INV-USD-001', '--to', DIRECTOR])

        assert result.exit_code == 0, result.output
        rows = _splits_of(path, DESCRIPTION)
        assert [row['account'] for row in rows] == [
            'Assets:Bank', DIRECTOR], rows
        bank = [row for row in rows if row['account'] == 'Assets:Bank']
        assert bank[0]['amount'] == 139, bank
        assert bank[0]['value'] == 139, bank

    def test_an_account_in_the_same_currency_leaves_the_amount_alone(
            self, tmp_path):
        """The ordinary undo: a USD split takes a USD account again.

        `Assets:Suspense USD` is the account this split carried before the
        link, and it is kept in USD, so the split's amount is already the
        figure that account takes. Nothing is restated and nothing has to be —
        which is the answer the link gave on the way in, where a split already
        in the record's currency had nothing but its account changed.
        """
        path = _linked_book(tmp_path)

        result = CliRunner().invoke(cli, [
            'unlink', str(path), 'INV-USD-001', '--to', 'Assets:Suspense USD'])

        assert result.exit_code == 0, result.output
        rows = _splits_of(path, DESCRIPTION)
        on_suspense = [row for row in rows
                       if row['account'] == 'Assets:Suspense USD']
        assert len(on_suspense) == 1, rows
        assert on_suspense[0]['amount'] == -100, on_suspense
        assert on_suspense[0]['value'] == -139, on_suspense

    def test_unapply_payment_restates_the_same_way(self, tmp_path):
        """The two commands are one operation and cannot disagree.

        `unapply-payment` is where this restatement was missing, so it is the
        command the defect was in: it set the account and left the figure, and
        100 US dollars became 100 Canadian ones. It goes through the same
        function now, and takes the same `--fx-rates`.
        """
        path = _linked_book(tmp_path)

        result = CliRunner().invoke(cli, [
            'unapply-payment', str(path), 'INV-USD-001', '--to', DIRECTOR])

        assert result.exit_code == 0, result.output
        rows = _splits_of(path, DESCRIPTION)
        on_director = [row for row in rows if row['account'] == DIRECTOR]
        assert len(on_director) == 1, rows
        assert on_director[0]['amount'] == -139, on_director

    def test_unapply_payment_says_what_it_needs_instead_of_raising(
            self, tmp_path):
        """A `--to` it cannot convert into is a message, not a traceback.

        Giving `unapply-payment` the restatement gave it this refusal too, and
        the refusal asks for `--fx-rates`. Click's standalone mode does not catch
        a plain `Exception`, so without the wrapper the reader met a stack
        trace quoting a flag the command did not have.
        """
        path = _linked_book(tmp_path)

        result = CliRunner().invoke(cli, [
            'unapply-payment', str(path), 'INV-USD-001',
            '--to', 'Assets:Suspense JPY'])

        assert result.exit_code != 0, result.output
        assert 'Traceback' not in result.output, result.output
        assert 'cost basis' in result.output, result.output

    def test_a_third_foreign_currency_is_refused_even_with_rates(
            self, tmp_path):
        """Converting into one would leave currency no cost basis accounts for.

        The arithmetic is fine — it is what the figure leaves behind that is
        not. A split bringing foreign currency into the book carries a
        `share_price:` and a `value:` in the currency the transaction is quoted
        in, and a cost basis is opened from the two. An unlink states neither
        figure: it puts a settlement back, it does not buy yen.

        Measured before this was refused: `--to Assets:Suspense JPY` with
        rates wrote −14946 JPY and `fx-balances` then listed the USD
        receivable and no JPY at all — foreign currency held with nothing
        behind it.

        `CAD` is not foreign, so converting into the book's own currency
        raises no such question and is what the reporter's case needs.
        """
        path = _linked_book(tmp_path)

        result = CliRunner().invoke(cli, [
            'unlink', str(path), 'INV-USD-001', '--to', 'Assets:Suspense JPY',
            '--fx-rates', RATES_JPY])

        assert result.exit_code != 0, result.output
        assert 'cost basis' in result.output, result.output
        assert 'CAD' in result.output, result.output

        listed = CliRunner().invoke(cli, ['fx-balances', str(path)])
        assert 'JPY' not in listed.output, listed.output
        rows = _splits_of(path, DESCRIPTION)
        on_ar = [row for row in rows if row['account'] == AR_USD]
        assert on_ar and on_ar[0]['in_a_lot'], 'the link is left alone'

    def test_an_account_too_coarse_for_the_figure_is_refused(self, tmp_path):
        """Rounding it would lose what the split says, so it is refused.

        The two branches that read a figure off the split hand it back
        untouched — nothing rounds it here, and `xaccSplitSetAmount` then
        rounds it half up in silence. `Assets:Due From Director Whole` counts
        whole dollars (`commodity_scu: 1`) and the split is worth −139.37 CAD,
        so writing it there wrote −139 and lost the 37 cents. Worse on this
        branch than on the other: the split's value is left alone, so the
        amount and the value would disagree on a split whose account is kept
        in the very currency the transaction is quoted in.

        The import side refuses a figure finer than the account it is destined
        for rather than rounding it — `amount_finer_than_a_coarse_account.txt`
        — and this is the same refusal on the way back.
        """
        path = _book_valued_with_cents(tmp_path)

        result = CliRunner().invoke(cli, [
            'unlink', str(path), 'INV-USD-001', '--to', DIRECTOR_WHOLE])

        assert result.exit_code != 0, result.output
        assert 'Traceback' not in result.output, result.output
        assert '139.37' in result.output, result.output
        assert DIRECTOR_WHOLE in result.output, result.output

    def test_the_refused_coarse_account_leaves_the_link_alone(self, tmp_path):
        """A refusal takes nothing off, the same as every other one here."""
        path = _book_valued_with_cents(tmp_path)

        CliRunner().invoke(cli, [
            'unlink', str(path), 'INV-USD-001', '--to', DIRECTOR_WHOLE])

        rows = _splits_of(path, CENTS_DESCRIPTION)
        on_ar = [row for row in rows if row['account'] == AR_USD]
        assert on_ar and on_ar[0]['in_a_lot'], rows
        assert on_ar[0]['value'] == Fraction(-13937, 100), on_ar

    def test_an_account_kept_to_cents_takes_the_same_figure(self, tmp_path):
        """The refusal is about the account's unit, not about the figure.

        The same −139.37 lands without complaint on a CAD account kept the
        ordinary way, so what is refused above is the rounding and not the
        rate.
        """
        path = _book_valued_with_cents(tmp_path)

        result = CliRunner().invoke(cli, [
            'unlink', str(path), 'INV-USD-001', '--to', DIRECTOR])

        assert result.exit_code == 0, result.output
        rows = _splits_of(path, CENTS_DESCRIPTION)
        on_director = [row for row in rows if row['account'] == DIRECTOR]
        assert len(on_director) == 1, rows
        assert on_director[0]['amount'] == Fraction(-13937, 100), on_director

    def test_the_currency_the_entry_is_quoted_in_is_not_a_third_option(
            self, tmp_path):
        """An HKD-quoted entry cannot send its split to an HKD account.

        The value branch reads a figure the split already carries, which made
        it look like a case needing no rate and therefore no cost basis. It is not:
        the value is denominated in the *transaction's* currency, so where
        that is a third foreign currency the branch wrote HKD into a CAD book
        with nothing accounting for it — the very thing the third-currency
        refusal exists to prevent, reached by going round it.

        The order of the tests is what settles it: the refusal is asked
        before the value is read. Only the commodity the split holds and the
        book's own currency are ever allowed.
        """
        path = _book_behind_an_hkd_bank(tmp_path)

        result = CliRunner().invoke(cli, [
            'unlink', str(path), 'INV-USD-001', '--to', 'Assets:Bank HKD',
            '--fx-rates', RATES_HKD])

        assert result.exit_code != 0, result.output
        assert 'Traceback' not in result.output, result.output
        assert 'cost basis' in result.output, result.output

    def test_that_refusal_offers_only_the_two_that_are_allowed(self, tmp_path):
        """USD or CAD — never HKD, which is the currency being refused.

        The list offered the *quoted* currency too, which here is HKD: the
        refusal would have sent a reader to the account it had just turned
        away.
        """
        path = _book_behind_an_hkd_bank(tmp_path)

        result = CliRunner().invoke(cli, [
            'unlink', str(path), 'INV-USD-001', '--to', 'Assets:Bank HKD',
            '--fx-rates', RATES_HKD])

        assert 'kept in USD or CAD' in result.output, result.output

    def test_the_split_behind_an_hkd_bank_still_takes_its_own_currency(
            self, tmp_path):
        """The refusal is about HKD, not about the entry being foreign.

        `Assets:Suspense USD` is the commodity the split holds, so it brings
        nothing new into the book and is allowed — which is what says the
        guard turns away a currency rather than a shape.
        """
        path = _book_behind_an_hkd_bank(tmp_path)

        result = CliRunner().invoke(cli, [
            'unlink', str(path), 'INV-USD-001', '--to', 'Assets:Suspense USD'])

        assert result.exit_code == 0, result.output
        rows = _splits_of(path, HKD_DESCRIPTION)
        on_suspense = [row for row in rows
                       if row['account'] == 'Assets:Suspense USD']
        assert len(on_suspense) == 1, rows
        assert on_suspense[0]['amount'] == -100, on_suspense

    def test_the_invoice_stays_posted_and_owes_again(self, tmp_path):
        path = _linked_book(tmp_path)

        result = CliRunner().invoke(cli, [
            'unlink', str(path), 'INV-USD-001', '--to', DIRECTOR])
        assert result.exit_code == 0, result.output

        written = tmp_path / 'after.txt'
        out = CliRunner().invoke(cli, [
            'export', str(path), '--output', str(written),
            '--include-business-objects'])
        assert out.exit_code == 0, out.output
        text = written.read_text()
        block = text[text.index('invoice "INV-USD-001"'):]
        block = block[:block.index('\n\n')]
        assert 'posted:' in block, block
        assert 'payment: none' in block, block
