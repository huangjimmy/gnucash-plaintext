"""A foreign invoice settled into a bank in a third currency.

A Canadian company invoices in USD and is paid into a Hong Kong account. The
settlement entry is denominated in the base currency, because the realized
difference is a figure in it, so two things need valuing in CAD: the cash,
through the bank's own rate, and the receivable, at the cost it was booked at.

This was refused outright — "a gain between two foreign currencies is not
supported" — which was the wrong diagnosis. Nothing about the shape is
unsupportable; the rates simply never reached the settlement, so the code had
nothing to value the cash with. What it is short of is a number, and it now
says which one.
"""

from pathlib import Path

from click.testing import CliRunner
from gnucash import Query, Transaction

from cli.main import cli
from repositories.gnucash_repository import GnuCashRepository, SessionMode

LEDGER = str(Path('tests/fixtures/fx_usd_invoice_settled_into_an_hkd_bank.txt'))
BILL = str(Path('tests/fixtures/fx_usd_bill_settled_from_an_hkd_bank.txt'))
USD_ONLY = 'tests/fixtures/fx_rates_usd_dated.yaml'
BOTH = 'tests/fixtures/fx_rates_usd_and_hkd.yaml'


def _import(tmp_path, rates, ledger=LEDGER):
    gnc = tmp_path / 'book.gnucash'
    args = ['import', '--new', str(gnc), ledger, '--include-business-objects']
    if rates:
        args += ['--fx-rates', rates]
    return gnc, CliRunner().invoke(cli, args)


def _settlement_lines(book):
    """The payment transaction, as (currency, [(account, amount, value)]).

    A list, not a dict: an overpayment puts two splits on the receivable and
    keying by account name would silently keep one of them.
    """
    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        query = Query()
        query.search_for('Trans')
        query.set_book(repo.book)
        for raw in query.run():
            transaction = Transaction(instance=raw)
            currency = transaction.GetCurrency().get_mnemonic()
            names = {s.GetAccount().get_full_name() for s in
                     transaction.GetSplitList()}
            if 'Assets.Bank.HKD' not in names:
                continue
            lines = [
                (s.GetAccount().get_full_name(),
                 f'{s.GetAmount().num()}/{s.GetAmount().denom()}',
                 f'{s.GetValue().num()}/{s.GetValue().denom()}')
                for s in transaction.GetSplitList()]
            query.destroy()
            return currency, lines
        query.destroy()
    finally:
        repo.close()
    raise AssertionError('no settlement touching the HKD bank')


def _settlement(book):
    """The same, keyed by account — for the entries with one split each."""
    currency, lines = _settlement_lines(book)
    rows = {name: (amount, value) for name, amount, value in lines}
    assert len(rows) == len(lines), 'two splits share an account; use the lines'
    return currency, rows


class TestWithoutTheBanksRate:
    def test_it_asks_for_the_rate_it_is_missing(self, tmp_path):
        """Named as a pair and a date, the way the posting step asks."""
        _, result = _import(tmp_path, USD_ONLY)

        assert result.exit_code != 0, result.output
        assert 'HKD/CAD rate on 2026-02-25' in result.output
        assert 'does not carry' in result.output

    def test_it_does_not_call_the_shape_unsupported(self, tmp_path):
        """The old message blamed the shape for a missing number.

        The positive assertion comes first on purpose: `'not supported' not
        in output` is true of empty output too, so on its own it would pass
        against a command that crashed without printing anything.
        """
        _, result = _import(tmp_path, USD_ONLY)

        assert 'HKD/CAD rate' in result.output, result.output
        assert 'not supported' not in result.output

    def test_with_no_rates_at_all_the_posting_asks_first(self, tmp_path):
        """Posting needs USD/CAD before the settlement needs anything."""
        _, result = _import(tmp_path, None)

        assert result.exit_code != 0
        assert 'USD/CAD rate on 2026-01-05' in result.output


class TestWithBothRates:
    def test_the_settlement_lands(self, tmp_path):
        book, result = _import(tmp_path, BOTH)

        assert result.exit_code == 0, result.output
        assert 'Errors:       0' in result.output
        assert book.exists()

    def test_the_entry_is_denominated_in_the_base_currency(self, tmp_path):
        book, _ = _import(tmp_path, BOTH)
        currency, _rows = _settlement(book)

        assert currency == 'CAD'

    def test_the_cash_is_valued_at_the_banks_rate(self, tmp_path):
        """780.00 HKD at 0.172 is 134.16 CAD — the amount stays HKD."""
        book, _ = _import(tmp_path, BOTH)
        _currency, rows = _settlement(book)

        assert rows['Assets.Bank.HKD'] == ('78000/100', '13416/100')

    def test_the_receivable_is_valued_at_what_it_cost(self, tmp_path):
        """Booked at 1.40, so 100.00 USD stands at 140.00 CAD."""
        book, _ = _import(tmp_path, BOTH)
        _currency, rows = _settlement(book)

        assert rows['Assets.Accounts Receivable USD'] == ('-10000/100',
                                                          '-14000/100')

    def test_the_difference_is_realized_on_the_residual_split(self, tmp_path):
        """134.16 received against 140.00 booked: 5.84 CAD realized."""
        book, _ = _import(tmp_path, BOTH)
        _currency, rows = _settlement(book)

        assert rows['Income.FX Gain'] == ('584/100', '584/100')

    def test_nothing_is_scrubbed_into_an_imbalance(self, tmp_path):
        """The bank's value written as its amount left 645.84 unexplained.

        GnuCash balances a transaction it is handed regardless, by inventing
        an Imbalance split — so the entry looked fine and the books were
        wrong by the whole difference between 780 and 134.16.
        """
        book, _ = _import(tmp_path, BOTH)
        _currency, rows = _settlement(book)

        assert not [name for name in rows if 'Imbalance' in name], rows
        values = [int(v.split('/')[0]) for _a, v in rows.values()]
        assert sum(values) == 0, rows


class TestAnInvoiceAlreadyInTheBaseCurrency:
    """A CAD invoice paid into an HKD account realizes nothing.

    The old code refused the whole shape at the top — badly worded for this
    case ("neither is CAD" when the invoice *was* CAD), but it refused.
    Removing that guard let this run on: the posting split is base-currency,
    so `derived_cost_of` answers 1 rather than None and the cost basis bail-out
    does not catch it, and the run reached the drawdown and demanded
    `cost_basis_balance:` on a CAD split — a key the importer refuses on a
    CAD split, on a split no directive writes. It had committed a
    `cost_basis_split:` pointing at a base-currency split on the way.

    This is the everyday configuration for a Canadian book with foreign
    accounts, and every other test here uses a USD invoice, so nothing
    covered it.
    """

    CAD = str(Path('tests/fixtures/fx_cad_invoice_settled_into_an_hkd_bank.txt'))

    def test_it_is_refused_for_the_reason_it_is_refused(self, tmp_path):
        _book, result = _import(tmp_path, BOTH, ledger=self.CAD)

        assert result.exit_code != 0, result.output
        assert 'Nothing is realized' in result.output
        assert 'HKD' in result.output

    def test_it_does_not_ask_for_something_impossible(self, tmp_path):
        """The old failure told the reader to state a key that is refused."""
        _book, result = _import(tmp_path, BOTH, ledger=self.CAD)

        assert 'cost_basis_balance' not in result.output, result.output
        assert 'no balance recorded' not in result.output, result.output

    def test_it_is_refused_without_a_residual_line_too(self, tmp_path):
        """The form a reader actually writes when nothing is realized.

        The refusal ran through `_require_no_unplaced_payment_splits`, which
        speaks only when the block carries split lines — so dropping the
        `$residual$` made the same shape succeed silently, with the incoming
        currency left unsellable and the entry denominated differently on 3.8
        than on 4.x.
        """
        bare = str(Path(
            'tests/fixtures/fx_cad_invoice_into_hkd_without_a_residual.txt'))
        _book, result = _import(tmp_path, BOTH, ledger=bare)

        assert result.exit_code != 0, result.output
        assert 'Nothing is realized' in result.output, result.output
        assert 'Errors:       0' not in result.output, result.output


class TestTheCurrencyItBroughtIn:
    """Cash a settlement brings in is sellable, like cash from anywhere else.

    Settling a USD receivable into an HKD bank puts 780.00 HKD in the book at
    0.172 CAD/HKD. That split establishes a cost basis by every measure the
    tool uses — a non-base currency, acquired, with a derivable cost — but the
    settlement path never opened its cost basis balance, so `fx-balances`
    listed it as `none recorded` and a later sale naming it was refused for having
    no balance recorded. The same 780 HKD arriving as an ordinary transaction
    was sellable: how the money came in decided whether the book would let go
    of it.
    """

    def test_the_cash_is_listed_with_a_balance_to_sell(self, tmp_path):
        book, result = _import(tmp_path, BOTH)
        assert result.exit_code == 0, result.output

        listed = CliRunner().invoke(cli, ['fx-balances', str(book)])
        assert listed.exit_code == 0, listed.output
        assert 'Assets:Bank:HKD' in listed.output
        assert '780.00 HKD' in listed.output
        assert 'Total HKD cost basis balance: 780.00 HKD' in listed.output

    def test_its_balance_is_recorded(self, tmp_path):
        book, result = _import(tmp_path, BOTH)
        assert result.exit_code == 0, result.output

        listed = CliRunner().invoke(cli, ['fx-balances', str(book)])
        # The positive assertions come first: `'none recorded' not in output` is
        # true of empty output, and a command that raised leaves it empty, so
        # on its own this would pass against an `fx-balances` that never read
        # the book.
        assert listed.exit_code == 0, listed.output
        assert 'Assets:Bank:HKD' in listed.output, listed.output
        assert 'none recorded' not in listed.output, listed.output


class TestWhenTheRateDidNotMove:
    """A settlement that realizes nothing still brings the cash in.

    100.00 USD booked at 1.40 is 140.00 CAD, and the 1000.00 HKD paid for it
    is 140.00 CAD at 0.14 — so there is no difference to place and the block
    needs no `$residual$` line. That takes an early return, and the call that
    opens the incoming currency's balance sat below it: the one case where a
    reader would least expect their money to arrive unsellable was the case
    that left it that way.
    """

    EXACT = str(Path(
        'tests/fixtures/fx_usd_invoice_settled_into_hkd_at_the_booked_rate.txt'))
    RATES = 'tests/fixtures/fx_rates_hkd_at_the_booked_rate.yaml'

    def test_it_imports_without_asking_for_a_residual(self, tmp_path):
        gnc = tmp_path / 'exact.gnucash'
        result = CliRunner().invoke(cli, [
            'import', '--new', str(gnc), self.EXACT,
            '--include-business-objects', '--fx-rates', self.RATES])

        assert result.exit_code == 0, result.output
        assert 'Errors:       0' in result.output, result.output

    def test_the_cash_it_brought_in_is_still_sellable(self, tmp_path):
        gnc = tmp_path / 'exact.gnucash'
        assert CliRunner().invoke(cli, [
            'import', '--new', str(gnc), self.EXACT,
            '--include-business-objects',
            '--fx-rates', self.RATES]).exit_code == 0

        listed = CliRunner().invoke(cli, ['fx-balances', str(gnc)])
        assert listed.exit_code == 0, listed.output
        assert 'Total HKD cost basis balance: 1,000.00 HKD' in listed.output, listed.output
        assert 'none recorded' not in listed.output, listed.output


class TestOverpaidAcrossThreeCurrencies:
    """The credit left over is worth what the payment converted at.

    A USD invoice overpaid out of an HKD bank settles two things at once and
    not at the same rate. The 100.00 USD that clears the invoice is valued
    at the 1.40 it was booked at; the 100.00 USD overpaid was never bought at
    1.40 — nothing about that rate was paid — it arrived with the rest of the
    cash, at what the whole conversion came to: 1,560.00 HKD worth 268.32 CAD
    for 200.00 USD, so 1.3416.

    That divisor is the bank's figure *restated in the base currency*, and
    every other case that reaches it had a base-currency bank already, where
    restating is a no-op. Left in HKD here it prices USD at 7.80 and values a
    100.00 USD credit at 780.00 CAD — six times over, with the excess landing
    on the residual as realized income.
    """

    LEDGER = str(Path(
        'tests/fixtures/fx_usd_invoice_overpaid_into_an_hkd_bank.txt'))
    BILL = str(Path(
        'tests/fixtures/fx_usd_bill_overpaid_from_an_hkd_bank.txt'))

    def test_it_lands_and_balances(self, tmp_path):
        book, result = _import(tmp_path, BOTH, ledger=self.LEDGER)

        assert result.exit_code == 0, result.output
        assert 'Errors:       0' in result.output, result.output
        _currency, lines = _settlement_lines(book)
        assert not [n for n, _a, _v in lines if 'Imbalance' in n], lines
        assert sum(int(v.split('/')[0]) for _n, _a, v in lines) == 0, lines

    def test_the_credit_is_valued_at_what_the_payment_converted_at(
            self, tmp_path):
        """100.00 USD at 1.3416 is 134.16 CAD — not the invoice's 140.00."""
        book, _ = _import(tmp_path, BOTH, ledger=self.LEDGER)
        _currency, lines = _settlement_lines(book)

        receivable = sorted(v for _n, a, v in lines if a == '-10000/100')
        assert receivable == ['-13416/100', '-14000/100'], lines

    def test_the_cash_is_the_whole_conversion(self, tmp_path):
        """1,560.00 HKD at 0.172 — the figure the rate is derived from."""
        book, _ = _import(tmp_path, BOTH, ledger=self.LEDGER)
        _currency, lines = _settlement_lines(book)

        assert ('Assets.Bank.HKD', '156000/100', '26832/100') in lines, lines

    def test_only_the_settled_part_realizes_anything(self, tmp_path):
        """5.84 CAD, the same as settling 100.00 USD alone into HKD.

        The credit is carried at cost, so it contributes nothing. Valuing it
        at the invoice's 1.40 would report 11.68.
        """
        book, _ = _import(tmp_path, BOTH, ledger=self.LEDGER)
        _currency, lines = _settlement_lines(book)

        assert ('Income.FX Gain', '584/100', '584/100') in lines, lines

    def test_a_prepayment_that_says_the_wrong_figure_is_refused(self, tmp_path):
        """What the block says is left over has to be what is left over.

        On the `txn_guid:` routes this tool carves the residue itself and
        compares the figure exactly; here GnuCash carves it, and nothing read
        the declaration — so `prepayment: 50` on a payment that leaves 100.00
        imported with `Errors: 0` and the next export wrote `prepayment:
        100.00` back. The same misstatement written the other way is refused.
        """
        wrong = str(Path(
            'tests/fixtures/overpayment_declaring_the_wrong_prepayment.txt'))
        book, result = _import(tmp_path, BOTH, ledger=wrong)

        assert result.exit_code != 0, result.output
        assert 'prepayment: 50' in result.output, result.output
        assert '100.00' in result.output, result.output
        assert not book.exists(), 'a refused payment left a book behind'

    def test_the_credit_carries_that_rate_as_its_cost(self, tmp_path):
        """And is sellable at it, like any other USD the book holds."""
        book, _ = _import(tmp_path, BOTH, ledger=self.LEDGER)

        listed = CliRunner().invoke(cli, ['fx-balances', str(book)])
        assert listed.exit_code == 0, listed.output
        assert '1.3416 CAD/USD' in listed.output, listed.output
        assert 'Total USD cost basis balance: 100.00 USD' in listed.output, listed.output

    def test_that_rate_is_in_the_file_the_book_exports(self, tmp_path):
        """Because nothing stores it: the transaction is what carries it.

        Opening the credit's balance and storing its cost are two acts, and
        the second only happens for a cost basis with no balance yet. On this shape
        the settlement's own pass opens the balance first, so the cost is
        never written down — the rate is read off the transaction, whose
        splits are valued in CAD, every time it is asked for.

        That is sound and it is also load-bearing, which nothing said. Export
        this book and rebuild it: if the file stopped carrying values in the
        base currency, or the derivation stopped being reached, the credit
        would come back at no cost at all — sellable nowhere, and against a
        gain nothing could compute.
        """
        runner = CliRunner()
        book, _ = _import(tmp_path, BOTH, ledger=self.LEDGER)

        exported = tmp_path / 'out.txt'
        assert runner.invoke(cli, ['export', str(book), str(exported),
                                   '--include-business-objects']).exit_code == 0
        rebuilt = tmp_path / 'rebuilt.gnucash'
        result = runner.invoke(cli, ['import', '--new', str(rebuilt),
                                     str(exported), '--include-business-objects'])
        assert result.exit_code == 0, result.output

        listed = runner.invoke(cli, ['fx-balances', str(rebuilt)])
        assert listed.exit_code == 0, listed.output
        assert '1.3416 CAD/USD' in listed.output, listed.output
        assert 'Total USD cost basis balance: 100.00 USD' in listed.output, listed.output
        checked = runner.invoke(cli, ['fx-balances', str(rebuilt),
                                      '--verify-costs'])
        assert checked.exit_code == 0, checked.output

    def test_the_payable_side_inverts_every_sign(self, tmp_path):
        """CLAUDE.md finding 7: this is the side a wrong sign hides on."""
        book, result = _import(tmp_path, BOTH, ledger=self.BILL)

        assert result.exit_code == 0, result.output
        _currency, lines = _settlement_lines(book)
        assert ('Assets.Bank.HKD', '-156000/100', '-26832/100') in lines, lines
        assert ('Income.FX Gain', '-584/100', '-584/100') in lines, lines
        assert sorted(v for _n, a, v in lines if a == '10000/100') == [
            '13416/100', '14000/100'], lines
        assert sum(int(v.split('/')[0]) for _n, _a, v in lines) == 0, lines

    def test_the_vendor_prepayment_is_open_at_that_rate(self, tmp_path):
        book, _ = _import(tmp_path, BOTH, ledger=self.BILL)

        listed = CliRunner().invoke(cli, ['fx-balances', str(book)])
        assert '1.3416 CAD/USD' in listed.output, listed.output

        found = CliRunner().invoke(cli, ['find-prepayments', str(book)])
        assert found.exit_code == 0, found.output
        assert 'vendor V-US' in found.output, found.output
        assert 'USD 100.00' in found.output, found.output


class TestThePayableSide:
    """The same shape with the signs inverted, which is where they go wrong.

    A payable is settled by a debit and the cash goes out, so every figure
    changes sign. CLAUDE.md finding 7 records this side as the one where a
    wrong sign passes unnoticed — the invoice reads settled and the money
    turns up somewhere else.
    """

    def test_it_lands_and_balances(self, tmp_path):
        book, result = _import(tmp_path, BOTH, ledger=BILL)

        assert result.exit_code == 0, result.output
        _currency, rows = _settlement(book)
        assert not [name for name in rows if 'Imbalance' in name], rows
        assert sum(int(v.split('/')[0]) for _a, v in rows.values()) == 0, rows

    def test_the_payable_is_debited_at_what_it_was_booked_at(self, tmp_path):
        book, _ = _import(tmp_path, BOTH, ledger=BILL)
        _currency, rows = _settlement(book)

        assert rows['Liabilities.Accounts Payable USD'] == ('10000/100',
                                                            '14000/100')

    def test_the_cash_leaves_at_the_banks_rate(self, tmp_path):
        book, _ = _import(tmp_path, BOTH, ledger=BILL)
        _currency, rows = _settlement(book)

        assert rows['Assets.Bank.HKD'] == ('-78000/100', '-13416/100')

    def test_the_difference_is_a_gain_on_this_side(self, tmp_path):
        """Booked at 140.00, settled for 134.16: the bill cost less."""
        book, _ = _import(tmp_path, BOTH, ledger=BILL)
        _currency, rows = _settlement(book)

        assert rows['Income.FX Gain'] == ('-584/100', '-584/100')

    def test_without_the_banks_rate_it_asks_for_it(self, tmp_path):
        _book, result = _import(tmp_path, USD_ONLY, ledger=BILL)

        assert result.exit_code != 0, result.output
        assert 'HKD/CAD rate on 2026-02-25' in result.output
        assert 'not supported' not in result.output
