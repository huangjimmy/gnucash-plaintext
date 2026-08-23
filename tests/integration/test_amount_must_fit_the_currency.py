"""A booked amount is a number of the currency's own units, or it is refused.

GnuCash keeps a smallest unit per *account* as well as per commodity, and will
store an amount finer than the currency has. This tool does not follow it
there. The two are separate things, and a plaintext ledger that books a tenth
of a cent is describing money nobody can pay.

`18.190` is fine — it is `18.19` with a trailing zero, and lands as 1819/100.
`18.191` is not, and is refused rather than stored.

Why it has to be refused rather than rounded: stored, the amount kept the
account's finer unit while the *value* was rounded to the currency's, so a
same-currency split came out with an amount of 5/1000 and a value of 1/100 —
double, with an implied exchange rate of 2 between a currency and itself.
Nothing caught it, because both splits were wrong by the same factor in
opposite directions and the values still summed to zero: every check in the
book asks whether the values balance, and none asks whether a same-currency
split's value equals its amount. The import reported `Errors: 0` and saved.
"""

from pathlib import Path

from click.testing import CliRunner

from cli.main import cli

TOO_FINE = str(Path('tests/fixtures/amount_finer_than_the_currency.txt'))
EXACT = str(Path('tests/fixtures/account_with_finer_scu.txt'))


class TestAnAmountTheCurrencyCannotHold:
    def test_it_is_refused_and_the_figure_is_named(self, tmp_path):
        gnc = tmp_path / 'book.gnucash'
        result = CliRunner().invoke(cli, ['import', '--new', str(gnc), TOO_FINE])

        assert 'Errors:       0' not in result.output
        assert '18.191' in result.output
        assert 'CAD' in result.output

    def test_nothing_of_it_reaches_the_book(self, tmp_path):
        gnc = tmp_path / 'book.gnucash'
        CliRunner().invoke(cli, ['import', '--new', str(gnc), TOO_FINE])

        out = tmp_path / 'out.txt'
        exported = CliRunner().invoke(cli, ['export', str(gnc), str(out)])
        assert exported.exit_code == 0, exported.output
        # Asserted outright rather than `if out.exists() else ''`: that
        # spelling passes when the export wrote nothing at all, which is a
        # different failure wearing this one's clothes.
        assert out.exists(), 'the export wrote nothing'
        assert '18.19' not in out.read_text()


class TestAnAccountCoarserThanItsCurrency:
    """The other direction, which judging only the currency lets through.

    An account may be kept to whole dollars. 18.19 is a fine number of
    Canadian dollars and not a number of *those*, and rounding it to 18 on
    the way in changes a figure the file stated — while the counterpart split
    keeps 18.19, so GnuCash parks the 0.19 in Imbalance-CAD and the summary
    reports no errors.
    """

    COARSE = str(Path('tests/fixtures/amount_finer_than_a_coarse_account.txt'))

    def test_it_is_refused_rather_than_rounded(self, tmp_path):
        gnc = tmp_path / 'book.gnucash'
        result = CliRunner().invoke(cli, ['import', '--new', str(gnc), self.COARSE])

        assert 'Errors:       0' not in result.output, result.output
        assert '18.19' in result.output

    def test_no_imbalance_is_left_in_the_book(self, tmp_path):
        """What the rounding would have produced, asserted against directly."""
        gnc = tmp_path / 'book.gnucash'
        CliRunner().invoke(cli, ['import', '--new', str(gnc), self.COARSE])

        out = tmp_path / 'out.txt'
        exported = CliRunner().invoke(cli, ['export', str(gnc), str(out)])
        assert exported.exit_code == 0, exported.output
        assert out.exists()
        assert 'Imbalance' not in out.read_text()


class TestAPaymentBlocksOwnAmount:
    """Which line of a block states the figure does not change the rule.

    `18.191` on a split line is refused; the same figure as a payment's
    `amount:` reached a parser that works at a fixed millionth and refuses
    nothing. GnuCash then rounded it to 18.19 on the way into the splits and
    the run reported `Errors: 0` — so the invoice was settled by a figure the
    file never stated, and the next export wrote 18.19 back. Measured.
    """

    PAYMENT = str(Path('tests/fixtures/'
                       'payment_amount_finer_than_the_currency.txt'))

    def test_it_is_refused_and_names_the_figure(self, tmp_path):
        gnc = tmp_path / 'pay.gnucash'
        result = CliRunner().invoke(cli, [
            'import', '--new', str(gnc), self.PAYMENT,
            '--include-business-objects'])

        assert 'Errors:       0' not in result.output, result.output
        assert '18.191' in result.output, result.output
        assert '0.01' in result.output, result.output

    def test_no_payment_of_the_rounded_figure_is_made(self, tmp_path):
        """What it did instead: settled the invoice with 18.19.

        A refused business object takes the whole import with it — the error
        escapes past `repo.save()` and the session ends unsaved — so the
        assertion is that no book was written at all. Written as `if not
        gnc.exists(): return`, this passed on that outcome by skipping, which
        is the same thing as not testing it.
        """
        gnc = tmp_path / 'pay.gnucash'
        result = CliRunner().invoke(cli, [
            'import', '--new', str(gnc), self.PAYMENT,
            '--include-business-objects'])

        assert '18.191' in result.output, result.output
        assert not gnc.exists(), 'a refused payment left a book behind'


class TestAPaymentOnACoarseReceivable:
    """The account arm of the same check, which never ran on this path.

    18.19 is a fine number of Canadian dollars and not a whole number of the
    units a receivable kept to whole dollars holds. The settling split lands
    on that account and is stored at its unit, so the amount came out 18
    against a value of 18.19 on a same-currency split, and the export wrote
    `amount: 18` back — a figure the file never stated, on the invoice it
    was meant to settle.
    """

    COARSE = str(Path('tests/fixtures/'
                      'payment_amount_finer_than_a_coarse_receivable.txt'))

    def test_it_is_refused_against_the_accounts_unit(self, tmp_path):
        gnc = tmp_path / 'coarse.gnucash'
        result = CliRunner().invoke(cli, [
            'import', '--new', str(gnc), self.COARSE,
            '--include-business-objects'])

        assert 'Errors:       0' not in result.output, result.output
        assert '18.19' in result.output, result.output
        assert 'that account is kept to' in result.output, result.output

    def test_no_book_is_written_holding_a_payment_of_18(self, tmp_path):
        gnc = tmp_path / 'coarse.gnucash'
        result = CliRunner().invoke(cli, [
            'import', '--new', str(gnc), self.COARSE,
            '--include-business-objects'])

        assert 'that account is kept to' in result.output, result.output
        assert not gnc.exists(), 'a refused payment left a book behind'


class TestASettledAmountFinerThanTheBank:
    """`settled_amount:` is the cash that lands on the bank split.

    Checked only for "parses" and "positive", 780.005 HKD gave a rate of
    780.005/100, the split rounded to 780.00, and the residual was computed
    from that rounded figure — so the entry balanced and the run reported
    `Errors: 0` about a payment the file did not describe.
    """

    FINE = str(Path('tests/fixtures/settled_amount_finer_than_the_bank.txt'))
    RATES = 'tests/fixtures/fx_rates_usd_and_hkd.yaml'

    def test_it_is_refused_and_names_the_figure(self, tmp_path):
        gnc = tmp_path / 'settled.gnucash'
        result = CliRunner().invoke(cli, [
            'import', '--new', str(gnc), self.FINE,
            '--include-business-objects', '--fx-rates', self.RATES])

        assert 'Errors:       0' not in result.output, result.output
        assert '780.005' in result.output, result.output
        assert 'HKD' in result.output, result.output

    def test_a_whole_number_of_the_banks_units_still_settles(self, tmp_path):
        """The sibling fixture, one thousandth away and legal."""
        gnc = tmp_path / 'ok.gnucash'
        result = CliRunner().invoke(cli, [
            'import', '--new', str(gnc),
            'tests/fixtures/fx_usd_invoice_settled_into_an_hkd_bank.txt',
            '--include-business-objects', '--fx-rates', self.RATES])

        assert result.exit_code == 0, result.output
        assert 'Errors:       0' in result.output, result.output


class TestARateThatReachesTheSameFigure:
    """`share_price:` is the other spelling, and reaches the same cash.

    100 USD at 7.80005 is 780.005 HKD. Checked only for "parses" and
    "positive", the rate produced exactly what its twin above produces —
    except that nothing then matched it either: the comparison reads what the
    file says against what the book holds, 780.005 against a rounded 780.00,
    so the invoice was judged changed on every import and a posted one is
    rebuilt to be judged again.
    """

    FINE = str(Path('tests/fixtures/share_price_finer_than_the_bank.txt'))
    RATES = 'tests/fixtures/fx_rates_usd_and_hkd.yaml'

    def test_it_is_refused_and_names_the_figure(self, tmp_path):
        gnc = tmp_path / 'rate.gnucash'
        result = CliRunner().invoke(cli, [
            'import', '--new', str(gnc), self.FINE,
            '--include-business-objects', '--fx-rates', self.RATES])

        assert 'Errors:       0' not in result.output, result.output
        assert '780.005' in result.output, result.output
        assert 'HKD' in result.output, result.output

    def test_no_book_is_left_holding_the_rounded_payment(self, tmp_path):
        gnc = tmp_path / 'rate.gnucash'
        CliRunner().invoke(cli, [
            'import', '--new', str(gnc), self.FINE,
            '--include-business-objects', '--fx-rates', self.RATES])

        assert not gnc.exists(), 'a refused payment left a book behind'

    def test_a_rate_with_no_exact_decimal_says_so_readably(self, tmp_path):
        """A rate may be written as a fraction, and 1/7 of nothing lands.

        README writes rates like `10000/14000`, so a rate need not have an
        exact decimal — and what it reaches then has none either. `100/7` is
        the right figure to quote; the sentence around it has to read, and a
        label ending in a verb gave `the share_price on this invoice, which
        reaches states 100/7 HKD`.
        """
        gnc = tmp_path / 'seventh.gnucash'
        ledger = tmp_path / 'seventh.txt'
        ledger.write_text(Path(self.FINE).read_text()
                          .replace('share_price: 7.80005', 'share_price: "1/7"'))
        result = CliRunner().invoke(cli, [
            'import', '--new', str(gnc), str(ledger),
            '--include-business-objects', '--fx-rates', self.RATES])

        assert result.exit_code != 0, result.output
        assert "the cash this invoice's share_price reaches states 100/7 HKD" \
            in result.output, result.output
        assert 'reaches states' not in result.output.replace(
            "share_price reaches states", ''), result.output

    def test_a_rate_reaching_a_whole_cent_still_settles(self, tmp_path):
        """7.80 against 7.80005 — the rule is about what the rate reaches."""
        gnc = tmp_path / 'ok.gnucash'
        ledger = tmp_path / 'ok.txt'
        ledger.write_text(Path(self.FINE).read_text()
                          .replace('share_price: 7.80005', 'share_price: 7.80'))
        result = CliRunner().invoke(cli, [
            'import', '--new', str(gnc), str(ledger),
            '--include-business-objects', '--fx-rates', self.RATES])

        assert result.exit_code == 0, result.output
        assert 'Errors:       0' in result.output, result.output


class TestASecurityIsNotMoney:
    """Fund units answer to the account they sit on, not to a currency.

    A holding is quoted in units, and units are commonly carried to three
    decimals or more whatever `fraction:` the commodity declares. So a
    quantity is judged against the account's own unit alone — and when one
    fails, the refusal has to say so. The message branches, and a security
    can only ever fail the account branch; sending it down the currency one
    told the reader to round 12.3456 to two places when three are legal, and
    called fund units "not money this book can record" when they are not
    money at all.
    """

    FINE = str(Path('tests/fixtures/fund_units_at_the_accounts_unit.txt'))
    TOO_FINE = str(Path('tests/fixtures/fund_units_finer_than_the_account.txt'))

    def test_three_decimals_are_accepted_on_a_thousandths_account(
            self, tmp_path):
        """Even though FUNDX declares `fraction: 100`."""
        gnc = tmp_path / 'fund.gnucash'
        result = CliRunner().invoke(cli, ['import', '--new', str(gnc), self.FINE])

        assert result.exit_code == 0, result.output
        assert 'Errors:       0' in result.output, result.output

    def test_the_quantity_comes_back_out_unchanged(self, tmp_path):
        gnc = tmp_path / 'fund.gnucash'
        assert CliRunner().invoke(
            cli, ['import', '--new', str(gnc), self.FINE]).exit_code == 0

        out = tmp_path / 'out.txt'
        exported = CliRunner().invoke(cli, ['export', str(gnc), str(out)])
        assert exported.exit_code == 0, exported.output
        # The ticker is namespace-qualified on the way out, which is how a
        # security is told apart from a currency of the same mnemonic.
        assert 'Assets:Fund 12.345 FUND.FUNDX' in out.read_text(), out.read_text()

        # And the export is readable, which is the half that matters: the
        # guard on the way out gates on the same namespace, so a quantity
        # this fine must not be refused there either.
        back = tmp_path / 'back.gnucash'
        again = CliRunner().invoke(cli, ['import', '--new', str(back), str(out)])
        assert again.exit_code == 0, again.output
        assert 'Errors:       0' in again.output, again.output

    def test_it_imports_with_business_objects_too(self, tmp_path):
        """The flag anyone with invoices or bills passes.

        That path creates accounts itself, and it created them before any
        commodity — so a ledger declaring a fund and an account holding it
        imported without the flag and failed with it: `account "Assets:Fund":
        Cannot find commodity (FUND, FUNDX)`. This is the file a reader ends
        up with after being told to declare their unit as a fund rather than
        a currency, so the advice has to survive the flag.
        """
        gnc = tmp_path / 'fund.gnucash'
        result = CliRunner().invoke(cli, [
            'import', '--new', str(gnc), self.FINE,
            '--include-business-objects'])

        assert result.exit_code == 0, result.output
        assert 'Errors:       0' in result.output, result.output

        out = tmp_path / 'out.txt'
        assert CliRunner().invoke(
            cli, ['export', str(gnc), str(out)]).exit_code == 0
        assert 'Assets:Fund 12.345 FUND.FUNDX' in out.read_text(), \
            out.read_text()

    def test_a_finer_quantity_is_refused_against_the_account(self, tmp_path):
        gnc = tmp_path / 'fund.gnucash'
        result = CliRunner().invoke(
            cli, ['import', '--new', str(gnc), self.TOO_FINE])

        assert 'Errors:       0' not in result.output, result.output
        assert '12.3456' in result.output, result.output
        assert 'that account is kept to' in result.output, result.output
        assert '0.001' in result.output, result.output

    def test_it_is_not_told_to_round_to_the_currencys_cent(self, tmp_path):
        """The wrong branch's two claims, asserted against by name."""
        gnc = tmp_path / 'fund.gnucash'
        result = CliRunner().invoke(
            cli, ['import', '--new', str(gnc), self.TOO_FINE])

        assert 'that account is kept to' in result.output, result.output
        assert 'finer than that currency' not in result.output, result.output
        assert 'not money this book can record' not in result.output, result.output


class TestAnAmountItCanHold:
    def test_a_trailing_zero_is_still_the_same_money(self, tmp_path):
        """18.190 is 18.19; the third digit says nothing the cent does not."""
        gnc = tmp_path / 'ok.gnucash'
        result = CliRunner().invoke(cli, ['import', '--new', str(gnc), EXACT])

        assert result.exit_code == 0, result.output
        assert 'Errors:       0' in result.output

    def test_its_value_equals_its_amount(self, tmp_path):
        """The invariant the refusal exists to keep true.

        One currency, one figure: a split in the transaction's own currency
        has a value equal to its amount, exactly, or the books say two
        different things about the same money.
        """
        from gnucash import Query, Transaction

        from repositories.gnucash_repository import GnuCashRepository, SessionMode

        gnc = tmp_path / 'ok.gnucash'
        assert CliRunner().invoke(
            cli, ['import', '--new', str(gnc), EXACT]).exit_code == 0

        repo = GnuCashRepository(str(gnc))
        repo.open(mode=SessionMode.READ_ONLY)
        try:
            query = Query()
            query.search_for('Trans')
            query.set_book(repo.book)
            seen = 0
            for raw in query.run():
                transaction = Transaction(instance=raw)
                for split in transaction.GetSplitList():
                    amount, value = split.GetAmount(), split.GetValue()
                    assert (amount.num() * value.denom()
                            == value.num() * amount.denom()), (
                        f'{split.GetAccount().get_full_name()}: '
                        f'amount {amount.num()}/{amount.denom()} '
                        f'value {value.num()}/{value.denom()}')
                    seen += 1
            query.destroy()
            assert seen >= 2
        finally:
            repo.close()
