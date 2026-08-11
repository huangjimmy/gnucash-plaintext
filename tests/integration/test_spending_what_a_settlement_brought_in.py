"""Cash a settlement brought in is spent like any other foreign cash.

Settling a USD invoice into an HKD bank puts 1,560.00 HKD in the book at 0.172
and opens a basis balance for it, so the money is sellable. Paying a USD
bill back out of that same account is a disposal, and this tool measures every
foreign disposal against a named cost basis.

A `payment:` block has nowhere to name one — GnuCash's `ApplyPayment` writes
its bank split, so `cost_basis_split_guid:` cannot go on it the way an ordinary
transaction's selling split carries it. Allowed through, that drifts twice
over: the balance keeps offering currency the account no longer holds, and the
cash leaves valued at the payment day's rate rather than at what it cost, so an
account holding no HKD is left holding a CAD figure whenever the two differ.

So the block is refused where a basis still has a balance to draw down, and the
refusal names the route that works. That route is exercised here too, because a
message telling the reader to do something has to be a message about something
they can do.

Both halves are new with foreign-bank settlement: before it, a payment into a
bank in a third currency was refused outright, so neither settlement in this
file could be written at all.
"""

from pathlib import Path

from click.testing import CliRunner
from gnucash import Query, Transaction

from cli.main import cli
from repositories.gnucash_repository import GnuCashRepository, SessionMode

BOTH = 'tests/fixtures/fx_hkd_settled_in_then_spent_out.txt'
SETUP = 'tests/fixtures/fx_hkd_spent_by_retarget_setup.txt'
RETARGET = 'tests/fixtures/fx_hkd_spent_by_retarget.txt'
RATES = 'tests/fixtures/fx_rates_usd_and_hkd.yaml'


def _import(runner, book, ledger, new=False):
    args = ['import']
    if new:
        args += ['--new']
    args += [str(book), ledger, '--include-business-objects',
             '--fx-rates', RATES]
    return runner.invoke(cli, args)


def _basis_on(listing, account_fragment):
    """The split GUID of the one basis sitting on a named account."""
    found = [line.split()[1] for line in listing.splitlines()
             if account_fragment in line]
    assert len(found) == 1, f'{account_fragment}: {found}\n{listing}'
    return found[0]


def _hkd_bank(book):
    """Every split on the HKD bank, as (amount, value) strings."""
    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        query = Query()
        query.search_for('Trans')
        query.set_book(repo.book)
        rows = []
        for raw in query.run():
            for split in Transaction(instance=raw).GetSplitList():
                if split.GetAccount().get_full_name() != 'Assets.Bank.HKD':
                    continue
                amount, value = split.GetAmount(), split.GetValue()
                rows.append((f'{amount.num()}/{amount.denom()}',
                             f'{value.num()}/{value.denom()}'))
        query.destroy()
        return rows
    finally:
        repo.close()


class TestAPaymentBlockCannotSpendABasisBalance:
    def test_it_is_refused(self, tmp_path):
        result = _import(CliRunner(), tmp_path / 'book.gnucash', BOTH, new=True)

        assert result.exit_code != 0, result.output
        assert 'Errors:       0' not in result.output, result.output

    def test_it_names_the_account_and_the_balance_its_bases_have(self, tmp_path):
        result = _import(CliRunner(), tmp_path / 'book.gnucash', BOTH, new=True)

        assert "'Assets:Bank:HKD'" in result.output, result.output
        assert '1560.00 HKD of balance' in result.output, result.output

    def test_it_names_the_route_that_can_say_which_basis(self, tmp_path):
        """A refusal with no way out is a dead end, not a diagnosis."""
        result = _import(CliRunner(), tmp_path / 'book.gnucash', BOTH, new=True)

        assert 'cost_basis_split_guid:' in result.output, result.output
        assert 'txn_guid:' in result.output, result.output

    def test_the_incoming_settlement_alone_is_untouched(self, tmp_path):
        """Only the spending half is refused; the arriving half still works."""
        runner = CliRunner()
        book = tmp_path / 'setup.gnucash'
        result = _import(runner, book, SETUP, new=True)

        assert result.exit_code == 0, result.output
        assert 'Errors:       0' in result.output, result.output
        listing = runner.invoke(cli, ['fx-balances', str(book)])
        assert 'Total HKD basis balance: 1,560.00 HKD' in listing.output, listing.output


class TestTheSameCurrencyCaseIsAskedToo:
    """A USD bill paid from a USD bank spends a basis balance just as much.

    And realizes nothing doing it, which is what made it easy to miss: the
    cross-currency arithmetic returns as soon as it sees that the record and
    the bank share a currency, more than two hundred lines before the
    disposal used to be looked at. The question has to be asked before that
    return, and this is the commoner of the two shapes.
    """

    BILL = 'tests/fixtures/fx_usd_bill_cad_expense.txt'
    PAY = 'tests/fixtures/fx_bill_paid_from_a_usd_bank_with_a_basis.txt'
    BUY = 'tests/fixtures/buy_100_usd_at_1_35.txt'
    USD_RATES = 'tests/fixtures/fx_rates_usd_dated.yaml'

    def _book_with_usd_at_a_basis(self, runner, tmp_path):
        book = tmp_path / 'book.gnucash'
        result = runner.invoke(cli, [
            'import', '--new', str(book), self.BILL,
            '--include-business-objects', '--fx-rates', self.USD_RATES])
        assert result.exit_code == 0, result.output

        assert runner.invoke(cli, [
            'import', str(book), self.BUY, '--include-business-objects',
            '--fx-rates', self.USD_RATES]).exit_code == 0

        # The bank's own row, not the `Total USD basis balance:` line — the
        # bill's payable is a USD basis too, so the total reads 200.00 and
        # would have matched whatever the bank held.
        assert self._bank_row(runner, book).endswith('100.00 USD')
        return book

    @staticmethod
    def _bank_row(runner, book):
        listing = runner.invoke(cli, ['fx-balances', str(book)])
        assert listing.exit_code == 0, listing.output
        rows = [line for line in listing.output.splitlines()
                if 'Assets:Bank:USD' in line]
        assert len(rows) == 1, listing.output
        return rows[0].rstrip()

    def test_it_is_refused_although_nothing_is_realized(self, tmp_path):
        runner = CliRunner()
        book = self._book_with_usd_at_a_basis(runner, tmp_path)

        result = runner.invoke(cli, [
            'import', str(book), self.PAY, '--include-business-objects',
            '--fx-rates', self.USD_RATES])

        assert result.exit_code != 0, result.output
        assert "'Assets:Bank:USD'" in result.output, result.output
        assert '100.00 USD of balance' in result.output, result.output
        assert 'cost_basis_split_guid:' in result.output, result.output

    def test_the_balance_it_would_have_spent_is_still_whole(self, tmp_path):
        """Refused before anything was drawn down or written."""
        runner = CliRunner()
        book = self._book_with_usd_at_a_basis(runner, tmp_path)
        runner.invoke(cli, [
            'import', str(book), self.PAY, '--include-business-objects',
            '--fx-rates', self.USD_RATES])

        assert self._bank_row(runner, book).endswith('100.00 USD')


class TestAnAccountWithNothingLeftIsStillSpendable:
    """Nothing to draw down means nothing to name, so nothing is refused.

    This is the case every foreign settlement into a fresh account starts
    from — and the one the bill fixtures added with foreign-bank settlement
    use, so a refusal that did not ask about the balance would have taken
    them with it.
    """

    def test_a_bill_paid_from_an_hkd_bank_with_no_balance_still_lands(self, tmp_path):
        result = _import(
            CliRunner(), tmp_path / 'book.gnucash',
            'tests/fixtures/fx_usd_bill_settled_from_an_hkd_bank.txt', new=True)

        assert result.exit_code == 0, result.output
        assert 'Errors:       0' in result.output, result.output


class TestTheOtherOrder:
    """Bill first, invoice second — and nothing refuses, by design.

    The refusal asks what balance the account's bases have at the moment cash
    leaves. Paid first, out of an account with no basis on it yet, the outgoing
    settlement is waved through; the invoice that follows brings the money in
    and opens a basis for the whole of it, and the account nets to zero while
    `fx-balances` still reports the whole of it as basis balance.

    No check at the departure point can see this: the outflow came first, and
    the basis that arrives afterwards has no way to know the money was already
    gone. Nor is "an account may not offer more than it holds" an invariant
    this model keeps — an account that receives 60.00 USD and pays an 8.00 USD
    fee out of the same transaction holds 52.00 and offers 60.00, and that
    book is correct by every rule in `services/foreign_currency.py`. Making
    the two agree means deciding what an outflow that names no basis does to
    the bases on its account, which is a change to the model.

    So this is pinned as what happens, not as what should: a test that fails
    the day somebody changes it, with the reasoning above to read.
    """

    BILL = 'tests/fixtures/fx_usd_bill_settled_from_an_hkd_bank.txt'
    INVOICE = 'tests/fixtures/fx_usd_invoice_settled_into_an_hkd_bank.txt'

    def _both(self, tmp_path):
        runner = CliRunner()
        book = tmp_path / 'order.gnucash'
        first = _import(runner, book, self.BILL, new=True)
        assert first.exit_code == 0, first.output
        second = _import(runner, book, self.INVOICE)
        assert second.exit_code == 0, second.output
        return runner, book

    def test_neither_settlement_is_refused(self, tmp_path):
        runner, book = self._both(tmp_path)

        listed = runner.invoke(cli, ['fx-balances', str(book)])
        assert listed.exit_code == 0, listed.output

    def test_the_account_nets_to_nothing(self, tmp_path):
        _runner, book = self._both(tmp_path)

        rows = _hkd_bank(book)
        assert len(rows) == 2, rows
        assert sum(int(a.split('/')[0]) for a, _v in rows) == 0, rows

    def test_and_the_balance_still_offers_the_whole_of_it(self, tmp_path):
        """What the module docstring describes, asserted so it cannot drift."""
        runner, book = self._both(tmp_path)

        listed = runner.invoke(cli, ['fx-balances', str(book)])
        assert 'Total HKD basis balance: 780.00 HKD' in listed.output, listed.output


class TestTheRouteTheRefusalNamesWorks:
    @staticmethod
    def _payment_and_its_payable_split(book):
        """The spending transaction, and the split on it that settles a bill.

        Both are needed: the transaction carries a payable split and a gain
        split besides the bank, so naming only the transaction leaves which
        of them settles the bill to the order they happen to be in.
        """
        repo = GnuCashRepository(str(book))
        repo.open(mode=SessionMode.READ_ONLY)
        try:
            query = Query()
            query.search_for('Trans')
            query.set_book(repo.book)
            found = None
            for raw in query.run():
                transaction = Transaction(instance=raw)
                if (transaction.GetDescription()
                        != 'Pay US vendor out of the HKD account'):
                    continue
                payable = next(
                    split for split in transaction.GetSplitList()
                    if 'Accounts Payable' in split.GetAccount().get_full_name())
                found = (transaction.GetGUID().to_string(),
                         payable.GetGUID().to_string())
            query.destroy()
        finally:
            repo.close()
        assert found is not None, 'the spending transaction was not written'
        return found

    def _settled(self, tmp_path):
        runner = CliRunner()
        book = tmp_path / 'book.gnucash'
        assert _import(runner, book, SETUP, new=True).exit_code == 0

        listing = runner.invoke(cli, ['fx-balances', str(book)])
        assert listing.exit_code == 0, listing.output
        bill_basis = _basis_on(listing.output, 'Accounts Payable')
        hkd_basis = _basis_on(listing.output, 'Assets:Bank:HKD')

        # The transaction is written first and the bill then claims it, so the
        # file has to be imported in two passes: the `txn_guid:` cannot be
        # known before the transaction it names exists. Both halves are cut
        # from the substituted text — splitting the raw fixture and slicing
        # the substituted one by that offset silently moved the cut, because
        # a GUID is longer than the placeholder it replaced.
        filled = (Path(RETARGET).read_text()
                  .replace('{bill_basis}', bill_basis)
                  .replace('{hkd_basis}', hkd_basis))
        transaction_half, _, bill_half = filled.partition('bill "BILL-HKD-OUT"')

        spend = tmp_path / 'spend.txt'
        spend.write_text(transaction_half)
        assert _import(runner, book, str(spend)).exit_code == 0

        txn_guid, split_guid = self._payment_and_its_payable_split(book)

        attach = tmp_path / 'attach.txt'
        attach.write_text(('bill "BILL-HKD-OUT"' + bill_half)
                          .replace('TXN_GUID', txn_guid)
                          .replace('SPLIT_GUID', split_guid))
        result = _import(runner, book, str(attach))
        assert result.exit_code == 0, result.output
        assert 'Errors:       0' in result.output, result.output
        return runner, book, result

    def test_the_bill_is_settled(self, tmp_path):
        _runner, _book, result = self._settled(tmp_path)

        assert 'Errors:       0' in result.output, result.output

    def test_the_hkd_balance_is_drawn_down_to_nothing(self, tmp_path):
        """What the payment block would have left at 1,560.00."""
        runner, book, _ = self._settled(tmp_path)

        listing = runner.invoke(cli, ['fx-balances', str(book)])
        assert listing.exit_code == 0, listing.output
        assert 'Total HKD basis balance: 0.00 HKD' in listing.output, listing.output

    def test_the_account_holds_neither_currency_nor_value(self, tmp_path):
        """The drift, asserted against directly: 0 HKD and 0 CAD, both."""
        _runner, book, _ = self._settled(tmp_path)

        rows = _hkd_bank(book)
        assert len(rows) == 2, rows
        assert sum(int(a.split('/')[0]) for a, _v in rows) == 0, rows
        assert sum(int(v.split('/')[0]) for _a, v in rows) == 0, rows

    def test_the_gain_is_measured_against_what_the_cash_cost(self, tmp_path):
        """280.00 of payable relieved by 268.32 of cash: 11.68 CAD."""
        runner, book, _ = self._settled(tmp_path)

        out = tmp_path / 'out.txt'
        assert runner.invoke(cli, ['export', str(book), str(out)]).exit_code == 0
        assert 'Income:FX Gain -11.68 CAD' in out.read_text(), out.read_text()

    def test_the_costs_still_agree(self, tmp_path):
        """And there are costs to agree about.

        `--verify-costs` exits 0 over a book with no bases at all, so the
        count is what makes this a statement rather than a tautology.
        """
        runner, book, _ = self._settled(tmp_path)

        checked = runner.invoke(cli, ['fx-balances', str(book), '--verify-costs'])
        assert checked.exit_code == 0, checked.output
        assert 'cost bas' in checked.output.lower(), checked.output
        assert 'Checked 0' not in checked.output, checked.output
