"""Linking a payment whose settling split is not on the receivable yet.

Q-039. `INV-USD-001` is 100.00 USD, its receivable is USD and the bank is USD,
so 100 USD arrived against 100 USD owed: the settlement does not convert and no
rate is involved. But the money was booked against `Assets:Due From Director`,
which is CAD, before anyone had worked out what it was — so GnuCash quoted the
entry in CAD and gave that split 139.00 of it at 1.39.

Neither figure is a fact about the settlement. Both are an artefact of
`Assets:Due From Director` being CAD, and both go when it is replaced. Linking
the payment has to move that split to the receivable **and restate it**. The
import does not: it sets the account and nothing else, so the split lands on a
USD account still carrying −139.

The same-currency shape is covered here too, and is the commoner one: a split
sitting in `Assets:Suspense USD` against a USD invoice moves without anything
being restated. What may be moved at all is a question about the account, not
about currency — hence the classes on income, on fund units, and on units held
on an account of an ordinary type.

Measured on the reporter's own numbers in
`tests/research/linking_a_bank_tx_whose_other_side_is_another_currency_probe.py`,
where the same book shows the third failure this cannot: where the parked
figure and the invoice's happen to be equal, nothing refuses and the book is
left saying 139 USD for 139 CAD of money.
"""

from fractions import Fraction
from pathlib import Path

import pytest
from click.testing import CliRunner
from gnucash import Query, Transaction
from gnucash.gnucash_core_c import ACCT_TYPE_ASSET

from cli.main import cli
from infrastructure.gnucash.utils import get_account_full_name
from repositories.gnucash_repository import GnuCashRepository, SessionMode

FIXTURES = Path('tests/fixtures')
BOOK = str(FIXTURES / 'fx_usd_invoice_cad_income.txt')
MONEY_IN = str(FIXTURES / 'money_booked_to_a_cad_account.txt')
LINKED = str(FIXTURES / 'a_payment_naming_the_parked_split.txt')
NAMES_ONLY_THE_TX = str(
    FIXTURES / 'a_payment_naming_only_the_parked_transaction.txt')
NO_SUCH_ACCOUNT = str(FIXTURES / 'a_payment_naming_an_account_the_tx_has_not_got.txt')
TWO_SPLITS = str(FIXTURES / 'money_arriving_as_two_receivable_splits.txt')
NAMES_TWO_SPLITS = str(FIXTURES / 'a_payment_naming_two_settling_splits.txt')
NAMES_ONE_SPLIT = str(FIXTURES / 'a_payment_naming_one_settling_split.txt')
PAYMENTSPLIT_ASTRAY = str(
    FIXTURES / 'a_paymentsplit_that_is_not_under_a_transaction.txt')
NAMES_TWO_TRANSACTIONS = str(
    FIXTURES / 'a_payment_naming_two_transactions.txt')
TRANSACTION_OUTSIDE_A_PAYMENT = str(
    FIXTURES / 'a_transaction_directive_outside_a_payment.txt')
PAYMENTSPLIT_OUTSIDE_A_PAYMENT = str(
    FIXTURES / 'a_paymentsplit_outside_a_payment.txt')
USD_PARKED = str(FIXTURES / 'money_booked_to_a_usd_account.txt')
USD_LINKED = str(
    FIXTURES / 'a_payment_naming_the_usd_split_that_settles_it.txt')
USD_OVERPAID = str(
    FIXTURES / 'more_money_booked_to_a_usd_account.txt')
USD_OVERPAID_LINKED = str(
    FIXTURES / 'a_payment_naming_the_usd_parked_split.txt')
SUSPENSE = 'Assets:Suspense USD'
TWO_SPLITS_TWO_MEMOS = str(
    FIXTURES / 'money_arriving_as_two_splits_with_their_own_memos.txt')
CREDIT_NAMING_A_TRANSACTION = str(
    FIXTURES / 'a_credit_payment_naming_a_transaction_block.txt')
GUID_THAT_WILL_NOT_PARSE = str(
    FIXTURES / 'a_payment_whose_transaction_guid_will_not_parse.txt')
TWO_SPLITS_WORTH_MORE = str(
    FIXTURES / 'money_arriving_as_two_splits_worth_more.txt')
NAMES_TWO_SPLITS_WORTH_MORE = str(
    FIXTURES / 'a_payment_naming_two_splits_worth_more.txt')
BILL_TWO_SPLITS = str(FIXTURES / 'money_paid_out_as_two_payable_splits.txt')
BILL_NAMES_TWO_SPLITS = str(
    FIXTURES / 'a_bill_payment_naming_two_settling_splits.txt')
SIDES_SWAPPED = str(
    FIXTURES / 'a_payment_naming_the_bank_split_and_the_other_account.txt')
SIDES_SWAPPED_NO_SPLIT = str(
    FIXTURES / 'a_payment_naming_only_the_other_account.txt')
A_CREDIT_NOTE = str(FIXTURES / 'a_usd_credit_note.txt')
A_REFUND = str(FIXTURES / 'money_refunded_to_the_customer.txt')
REFUND_NAMING_THE_TX = str(
    FIXTURES / 'a_refund_payment_naming_only_the_transaction.txt')
A_CASH_SALE = str(FIXTURES / 'a_cash_sale_with_its_income_split.txt')
NAMES_THE_INCOME_SPLIT = str(
    FIXTURES / 'a_payment_naming_the_income_split.txt')
NAMES_ONLY_THE_CASH_SALE = str(
    FIXTURES / 'a_payment_naming_only_the_cash_sale.txt')
A_CASH_SALE_WORTH_MORE = str(
    FIXTURES / 'a_cash_sale_worth_more_than_the_invoice.txt')
OVERPAYS_FROM_THE_CASH_SALE = str(
    FIXTURES / 'a_payment_overpaying_from_the_cash_sale.txt')
USD_PARKED_WORTH_MORE = str(
    FIXTURES / 'more_money_parked_in_usd_than_the_invoice_owes.txt')
OVERPAYS_WITH_SIDES_SWAPPED = str(
    FIXTURES / 'a_payment_overpaying_with_the_sides_swapped.txt')
ONE_SPLIT_TWICE_TWO_SPELLINGS = str(
    FIXTURES / 'a_payment_naming_one_split_twice_in_two_spellings.txt')
ONE_SPLIT_MISSTATED = str(
    FIXTURES / 'a_payment_naming_one_split_and_misstating_it.txt')
TWO_INVOICES_SMALL_RESIDUE = str(
    FIXTURES / 'money_for_two_invoices_and_a_smaller_residue.txt')
THE_FIFTY_INVOICE = str(
    FIXTURES / 'a_fifty_dollar_invoice_settled_by_its_share.txt')
GROUPED_BESIDE_AN_ORPHAN = str(
    FIXTURES / 'a_grouped_payment_beside_an_orphan.txt')
PARKED_IN_YEN = str(FIXTURES / 'money_booked_to_a_yen_account.txt')
THE_YEN_PAID_INVOICE = str(
    FIXTURES / 'a_third_usd_invoice_paid_from_yen.txt')
TWO_INVOICES_AND_A_RESIDUE = str(
    FIXTURES / 'money_for_two_invoices_and_a_residue.txt')
THE_SECOND_INVOICE = str(
    FIXTURES / 'a_second_usd_invoice_settled_by_its_share.txt')
GROUPED_BESIDE_ANOTHER_SHARE = str(
    FIXTURES / 'a_grouped_payment_beside_another_invoices_share.txt')
GROUPED_MISSTATING_A_PARKED_SPLIT = str(
    FIXTURES / 'a_grouped_payment_misstating_a_parked_split.txt')
ONE_SPLIT_AS_CREDIT = str(
    FIXTURES / 'money_arriving_with_one_split_as_credit.txt')
NAMES_A_SPLIT_IN_A_CREDIT_LOT = str(
    FIXTURES / 'a_payment_naming_a_split_in_a_credit_lot.txt')
TWO_SPLITS_MISSTATED = str(
    FIXTURES / 'a_payment_naming_two_splits_and_misstating_them.txt')
KEY_SPELLING_MISSTATED = str(
    FIXTURES / 'a_key_spelled_payment_misstating_its_split.txt')
INCOME_USD = 'Income:Sales USD'
A_FUND_SALE = str(FIXTURES / 'money_from_selling_fund_units.txt')
NAMES_THE_FUND_SPLIT = str(FIXTURES / 'a_payment_naming_the_fund_split.txt')
NAMES_ONLY_THE_FUND_SALE = str(
    FIXTURES / 'a_payment_naming_only_the_fund_sale.txt')
FUND = 'Assets:Fund'
UNITS_ON_AN_ASSET = str(
    FIXTURES / 'money_from_selling_units_held_on_an_asset.txt')
NAMES_UNITS_ON_AN_ASSET = str(
    FIXTURES / 'a_payment_naming_units_held_on_an_asset.txt')
UNITS = 'Assets:Units'
BILL_PAID_IN_UNITS = str(
    FIXTURES / 'a_bill_paid_by_handing_over_fund_units.txt')
BILL_NAMES_THE_FUND_SPLIT = str(
    FIXTURES / 'a_bill_payment_naming_the_fund_split.txt')
MONEY_OUT_IN_USD = str(FIXTURES / 'money_paid_out_of_a_usd_account.txt')
BILL_SIDES_SWAPPED = str(
    FIXTURES / 'a_bill_payment_with_the_sides_swapped.txt')
A_CASH_PURCHASE = str(FIXTURES / 'a_cash_purchase_with_its_expense_split.txt')
BILL_NAMES_THE_EXPENSE_SPLIT = str(
    FIXTURES / 'a_bill_payment_naming_the_expense_split.txt')
EXPENSES = 'Expenses:Supplies:USD'
BILL_NAMES_THE_BANK_AS_A_PAYMENTSPLIT = str(
    FIXTURES / 'a_bill_payment_naming_the_bank_split_as_a_paymentsplit.txt')
BILL_MONEY_OUT_FELL_SHORT = str(
    FIXTURES / 'less_money_paid_out_than_the_bill_block_claims.txt')
BILL_CLAIMS_MORE_THAN_THE_BANK_SENT = str(
    FIXTURES / 'a_bill_payment_claiming_more_than_the_bank_sent.txt')
BILL_ON_A_PLAIN_LIABILITY = str(
    FIXTURES / 'a_bill_posted_to_a_plain_liability.txt')
PLAIN_LIABILITY_NAMES_THE_FUND_SPLIT = str(
    FIXTURES / 'a_bill_on_a_plain_liability_naming_the_fund_split.txt')
BILL_MONEY_OUT_TWO_CAD_SPLITS = str(
    FIXTURES / 'money_paid_out_as_two_parked_cad_splits.txt')
BILL_NAMES_TWO_PARKED_CAD_SPLITS = str(
    FIXTURES / 'a_bill_payment_naming_two_parked_cad_splits.txt')
BILL_MONEY_OUT_OF_A_CAD_BANK = str(
    FIXTURES / 'money_paid_out_of_a_cad_bank_for_a_usd_bill.txt')
BILL_LINKED_FROM_A_CAD_BANK = str(
    FIXTURES / 'a_bill_payment_linking_a_cad_bank_to_a_usd_bill.txt')
BILL_MONEY_OUT_OVERPAID = str(
    FIXTURES / 'more_money_paid_out_than_the_bill_owes.txt')
BILL_OVERPAYS_FROM_A_PARKED_SPLIT = str(
    FIXTURES / 'a_bill_payment_overpaying_from_a_parked_split.txt')
CLAIMS_LESS_THAN_ITS_SPLITS = str(
    FIXTURES / 'a_grouped_payment_claiming_less_than_its_splits.txt')
NAMES_ONE_SPLIT_TWICE = str(
    FIXTURES / 'a_payment_naming_one_split_twice.txt')
USD_PARKED_CAD_BANK = str(
    FIXTURES / 'money_parked_in_usd_that_reached_a_cad_bank.txt')
NAMES_USD_SPLIT_CAD_BANK = str(
    FIXTURES / 'a_payment_naming_the_usd_split_behind_a_cad_bank.txt')
CAD_BANK_ACCOUNT = 'Assets:Bank'
TWO_SPLITS_AND_A_RESIDUE = str(
    FIXTURES / 'money_arriving_for_two_splits_and_a_residue.txt')
NAMES_TWO_BESIDE_A_RESIDUE = str(
    FIXTURES / 'a_payment_naming_two_splits_beside_a_residue.txt')
FINER_THAN_THE_CENT = str(FIXTURES / 'money_parked_at_a_tenth_of_a_cent.txt')
A_TRANSACTION_WITH_NO_SPLITS = str(
    FIXTURES / 'a_payment_naming_a_transaction_with_no_splits.txt')
GROUPED_WITH_A_PREPAYMENT = str(
    FIXTURES / 'a_grouped_payment_with_a_prepayment.txt')
THE_OTHER_WIRE = str(FIXTURES / 'a_second_wire_the_directive_names.txt')
KEY_AND_DIRECTIVE_DISAGREE = str(
    FIXTURES / 'a_payment_whose_key_and_directive_disagree.txt')
RESIDUE_ON_THE_RECEIVABLE = str(
    FIXTURES / 'money_arriving_with_its_residue_on_the_receivable.txt')
FOLLOWS_THE_REMEDY = str(
    FIXTURES / 'a_payment_following_the_overpayment_remedy.txt')
USD_FEE_USD_PARKED = str(
    FIXTURES / 'money_parked_in_usd_beside_a_usd_fee.txt')
NAMES_USD_SPLIT_BESIDE_A_USD_FEE = str(
    FIXTURES / 'a_payment_naming_the_usd_split_beside_a_usd_fee.txt')
TWO_PARKED_CAD_SPLITS = str(
    FIXTURES / 'money_booked_to_two_cad_splits.txt')
NAMES_TWO_PARKED_CAD_SPLITS = str(
    FIXTURES / 'a_payment_naming_two_parked_cad_splits.txt')
NAMES_THE_BANK_SPLIT = str(FIXTURES / 'a_payment_naming_the_bank_split.txt')
OVERPAID = str(FIXTURES / 'more_money_parked_than_the_invoice_owes.txt')
LINKED_OVERPAID = str(
    FIXTURES / 'a_payment_overpaying_from_a_parked_split.txt')
FELL_SHORT = str(FIXTURES / 'less_money_parked_than_the_block_claims.txt')
LINKED_FELL_SHORT = str(
    FIXTURES / 'a_payment_claiming_more_than_the_bank_got.txt')
LINKED_OVERPAID_BY_SPLIT = str(
    FIXTURES / 'a_payment_overpaying_and_naming_the_parked_split.txt')
LINKED_FELL_SHORT_BY_SPLIT = str(
    FIXTURES / 'a_payment_claiming_more_and_naming_the_parked_split.txt')
CAD_BANK = str(FIXTURES / 'money_parked_with_a_cad_bank.txt')
LINKED_FROM_A_CAD_BANK = str(
    FIXTURES / 'a_payment_linking_a_cad_bank_to_a_usd_invoice.txt')
USD_FEE = str(FIXTURES / 'money_parked_beside_a_usd_fee.txt')
LINKED_WITH_A_USD_FEE = str(
    FIXTURES / 'a_payment_naming_the_split_parked_beside_a_usd_fee.txt')
WITH_A_FEE = str(FIXTURES / 'money_parked_beside_a_cad_fee.txt')
LINKED_WITH_A_FEE = str(
    FIXTURES / 'a_payment_naming_the_split_parked_beside_a_fee.txt')
RATES = str(FIXTURES / 'fx_rates_usd_dated.yaml')

BILL_BOOK = str(FIXTURES / 'fx_usd_bill_cad_expense.txt')
MONEY_OUT = str(FIXTURES / 'money_paid_out_of_a_cad_account.txt')
BILL_LINKED = str(FIXTURES / 'a_bill_payment_naming_the_parked_split.txt')
BILL_NAMES_ONLY_THE_TX = str(
    FIXTURES / 'a_bill_payment_naming_only_the_transaction.txt')

BANK = 'Assets:Bank:USD'
AR = 'Assets:Accounts Receivable USD'
AP = 'Liabilities:Accounts Payable USD'
DIRECTOR = 'Assets:Due From Director'


def _each_split_of(book, description):
    """Every split as its own row.

    `_money_in` keys by account, which is enough while each account appears
    once — and is exactly wrong where two splits of one transaction sit on the
    receivable, since the second would overwrite the first and two splits
    would read as one.

    Each row carries its commodity, because a figure alone does not say what
    was moved: 1.000 of a fund's units and 1.000 dollars read the same.
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
                commodity = split.GetAccount().GetCommodity()
                rows.append({
                    'account': get_account_full_name(split.GetAccount()),
                    'amount': Fraction(split.GetAmount().num(),
                                       split.GetAmount().denom()),
                    'commodity': (commodity.get_mnemonic()
                                  if commodity is not None else None),
                    'in_a_lot': split.GetLot() is not None,
                })
        query.destroy()
        return rows
    finally:
        repo.close()


def _posting_guid(book):
    """The invoice's posting transaction, by guid.

    What an unpost destroys. Balances are the same either way, so nothing but
    the guid says whether a rebuild put the invoice back on the transaction the
    book was booked through or minted another.
    """
    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        query = Query()
        query.search_for('gncInvoice')
        query.set_book(repo.book)
        from infrastructure.gnucash.utils import wrap_invoice_or_bill
        for raw in query.run():
            record = wrap_invoice_or_bill(raw)
            if record.GetID() != 'INV-USD-001':
                continue
            posted = record.GetPostedTxn()
            found = posted.GetGUID().to_string() if posted else None
            query.destroy()
            return found
        query.destroy()
        return None
    finally:
        repo.close()


def _money_in(book, description='Money in'):
    """The named transaction: its currency, and a row per split."""
    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        query = Query()
        query.search_for('Trans')
        query.set_book(repo.book)
        found = None
        for raw in query.run():
            transaction = Transaction(instance=raw)
            if transaction.GetDescription() != description:
                continue
            splits = {}
            for split in transaction.GetSplitList():
                account = split.GetAccount()
                splits[get_account_full_name(account)] = {
                    'commodity': account.GetCommodity().get_mnemonic(),
                    'amount': Fraction(split.GetAmount().num(),
                                       split.GetAmount().denom()),
                    'value': Fraction(split.GetValue().num(),
                                      split.GetValue().denom()),
                    'in_a_lot': split.GetLot() is not None,
                }
            found = (transaction.GetCurrency().get_mnemonic(), splits)
            break
        query.destroy()
        return found
    finally:
        repo.close()


@pytest.fixture
def book(tmp_path):
    """The posted USD invoice, and the money parked against the CAD account.

    The rate is the *posting's* — a USD invoice booking to a CAD income account
    converts, and that is the invoice being raised. Nothing below states a
    rate, because nothing below converts.
    """
    path = tmp_path / 'book.gnucash'
    runner = CliRunner()
    first = runner.invoke(cli, [
        'import', '--new', str(path), BOOK,
        '--include-business-objects', '--fx-rates', RATES])
    assert first.exit_code == 0, first.output
    second = runner.invoke(cli, ['import', str(path), MONEY_IN])
    assert second.exit_code == 0, second.output
    return path


class TestTheBookBeforeTheLink:
    def test_the_money_is_parked_against_the_cad_account(self, book):
        """Stated rather than assumed: everything below turns on this shape."""
        currency, splits = _money_in(book)

        assert currency == 'CAD', currency
        assert splits[BANK]['amount'] == 100
        assert splits[DIRECTOR]['amount'] == -139
        assert splits[DIRECTOR]['commodity'] == 'CAD'
        assert not splits[DIRECTOR]['in_a_lot']


class TestLinkingIt:
    def test_the_run_is_accepted(self, book):
        result = CliRunner().invoke(cli, [
            'import', str(book), LINKED, '--include-business-objects'])

        assert result.exit_code == 0, result.output

    def test_the_receivable_carries_what_the_bank_received(self, book):
        """−100 USD, not −139.

        What the parked split carried is not the settlement: it is what
        balanced the entry against a CAD account. Kept, it books 139 USD for
        100 USD of money, and the receivable is the side that says so.
        """
        CliRunner().invoke(cli, ['import', str(book), LINKED,
                                 '--include-business-objects'])
        _, splits = _money_in(book)

        assert AR in splits, sorted(splits)
        assert splits[AR]['amount'] == -100, splits[AR]
        assert splits[AR]['in_a_lot'], 'the settlement belongs to the lot'

    def test_no_cad_is_left_in_the_entry(self, book):
        """Both sides are USD, so the entry is quoted in USD.

        Left in CAD it carries a rate for a settlement that converted nothing,
        and every value on it is a figure nobody stated.
        """
        CliRunner().invoke(cli, ['import', str(book), LINKED,
                                 '--include-business-objects'])
        currency, splits = _money_in(book)

        assert currency == 'USD', currency
        assert DIRECTOR not in splits, f'{DIRECTOR} keeps no split'
        assert splits[BANK]['value'] == 100, splits[BANK]
        assert splits[AR]['value'] == -100, splits[AR]

    def test_the_entry_still_balances(self, book):
        CliRunner().invoke(cli, ['import', str(book), LINKED,
                                 '--include-business-objects'])
        _, splits = _money_in(book)

        assert sum(row['value'] for row in splits.values()) == 0, splits


class TestTheSameForABill:
    """The payable side, which the path would otherwise ship unexercised.

    A bill posts the other way round — CLAUDE.md finding 7 — so its settlement
    is the opposite sign from an invoice's. `relink_a_parked_split` writes the
    negation of what the bank did, which is right on both without knowing which
    it is looking at, and that is worth measuring rather than arguing.
    """

    @pytest.fixture
    def book_with_a_bill(self, tmp_path):
        path = tmp_path / 'bills.gnucash'
        runner = CliRunner()
        first = runner.invoke(cli, [
            'import', '--new', str(path), BILL_BOOK,
            '--include-business-objects', '--fx-rates', RATES])
        assert first.exit_code == 0, first.output
        second = runner.invoke(cli, ['import', str(path), MONEY_OUT])
        assert second.exit_code == 0, second.output
        return path

    def test_the_run_is_accepted(self, book_with_a_bill):
        result = CliRunner().invoke(cli, [
            'import', str(book_with_a_bill), BILL_LINKED,
            '--include-business-objects'])

        assert result.exit_code == 0, result.output

    def test_the_payable_carries_what_the_bank_sent(self, book_with_a_bill):
        """+100, where an invoice's receivable would be −100."""
        CliRunner().invoke(cli, ['import', str(book_with_a_bill), BILL_LINKED,
                                 '--include-business-objects'])
        currency, splits = _money_in(book_with_a_bill, 'Money out')

        assert currency == 'USD', currency
        assert DIRECTOR not in splits, sorted(splits)
        assert splits[AP]['amount'] == 100, splits[AP]
        assert splits[AP]['in_a_lot'], 'the settlement belongs to the lot'

    def test_naming_only_the_transaction_works_on_a_bill_too(
            self, book_with_a_bill):
        """The branch that carries the sign guard, on the side whose sign runs
        the other way.

        A payable posts negative and its settlement is positive, the reverse of
        an invoice's — the subtlety that made a credit note's refund read as a
        swapped `account:`. Every other bill fixture here names its split or
        groups several, so this branch had run on the invoice side only.
        """
        result = CliRunner().invoke(cli, [
            'import', str(book_with_a_bill), BILL_NAMES_ONLY_THE_TX,
            '--include-business-objects'])

        assert result.exit_code == 0, result.output

    def test_that_lands_where_naming_the_split_lands(self, book_with_a_bill):
        CliRunner().invoke(cli, ['import', str(book_with_a_bill),
                                 BILL_NAMES_ONLY_THE_TX,
                                 '--include-business-objects'])
        currency, splits = _money_in(book_with_a_bill, 'Money out')

        assert currency == 'USD', currency
        assert splits[AP]['amount'] == 100
        assert splits[AP]['in_a_lot']
        assert DIRECTOR not in splits, splits

    def test_the_entry_still_balances(self, book_with_a_bill):
        CliRunner().invoke(cli, ['import', str(book_with_a_bill), BILL_LINKED,
                                 '--include-business-objects'])
        _, splits = _money_in(book_with_a_bill, 'Money out')

        assert sum(row['value'] for row in splits.values()) == 0, splits


class TestAPaymentNamingOnlyTheTransaction:
    """`txn_guid:` with no `txn_split_guid:` beside it.

    The transaction has one side that is not the bank, so there is nothing to
    choose between and naming the split adds nothing. This is what a person
    writes by hand, and it is the way that failed worst: it measured the parked
    139.00 CAD against the invoice's 100.00 USD, called the difference an
    overpayment, and offered `prepayment: 39.00` for money that does not exist
    in either currency.
    """

    def test_the_run_is_accepted(self, book):
        result = CliRunner().invoke(cli, [
            'import', str(book), NAMES_ONLY_THE_TX,
            '--include-business-objects'])

        assert result.exit_code == 0, result.output
        assert 'prepayment' not in result.output, result.output

    def test_it_lands_where_naming_the_split_lands(self, book):
        """Both say the same thing, so both leave the same book."""
        CliRunner().invoke(cli, ['import', str(book), NAMES_ONLY_THE_TX,
                                 '--include-business-objects'])
        currency, splits = _money_in(book)

        assert currency == 'USD', currency
        assert DIRECTOR not in splits, sorted(splits)
        assert splits[AR]['amount'] == -100, splits[AR]
        assert splits[AR]['value'] == -100, splits[AR]
        assert splits[AR]['in_a_lot']


class TestOnePaymentMadeOfSeveralSplits:
    """One transaction clearing the receivable with two splits.

    Two tranches of one wire, or two lines a bookkeeper entered separately.
    The money arrived once, so it is one payment and one `payment:` block —
    written as two blocks it would say the invoice was paid twice, which is a
    different fact about the customer.

    Each split carries its own figure, 60 and 40 of the 100, so nothing is
    divided or inferred. All the block says is which splits are this one's.
    """

    @pytest.fixture
    def paid_in_two(self, book):
        assert CliRunner().invoke(
            cli, ['import', str(book), TWO_SPLITS]).exit_code == 0
        return book

    def test_the_run_is_accepted(self, paid_in_two):
        result = CliRunner().invoke(cli, [
            'import', str(paid_in_two), NAMES_TWO_SPLITS,
            '--include-business-objects'])

        assert result.exit_code == 0, result.output

    def test_both_splits_end_up_in_the_lot(self, paid_in_two):
        """Both, not the first of them — which is what taking one would do,
        leaving the invoice showing 40 still owed against a bank that has the
        whole 100."""
        CliRunner().invoke(cli, ['import', str(paid_in_two), NAMES_TWO_SPLITS,
                                 '--include-business-objects'])
        rows = _each_split_of(paid_in_two, 'Money in, two lines')

        receivables = [row for row in rows if row['account'] == AR]
        assert len(receivables) == 2, rows
        assert sorted(row['amount'] for row in receivables) == [-60, -40]
        assert all(row['in_a_lot'] for row in receivables), receivables

    def test_it_reads_as_one_payment_not_two(self, paid_in_two):
        """The count is the point. Two blocks would say paid twice."""
        CliRunner().invoke(cli, ['import', str(paid_in_two), NAMES_TWO_SPLITS,
                                 '--include-business-objects'])
        exported = paid_in_two.parent / 'out.txt'
        assert CliRunner().invoke(cli, [
            'export', str(paid_in_two), '--output', str(exported),
            '--include-business-objects']).exit_code == 0

        text = exported.read_text(encoding='utf-8')
        block = text[text.index('invoice "INV-USD-001"'):]
        block = block[:block.find('\ninvoice ') if '\ninvoice ' in block[1:]
                      else len(block)]
        assert block.count('payment:') == 1, block


class TestAFeeBesideTheSettlement:
    """A third split means the settlement cannot be worked out, so it is asked
    for.

    What the parked split is worth is read from what the bank received, and
    that is the settlement only while the two of them are the whole entry. Put
    a 5.00 wire fee beside a 100.00 receipt and the same numbers have two
    honest readings — the customer paid 105 and the fee is borne here, or they
    paid 100 and the fee is theirs. Nothing in the book records which, and it
    is not this tool's to choose.

    Same currency throughout, so this is not the conversion refusal. It is
    about which figure settles the invoice, not about a rate.
    """

    @pytest.fixture
    def with_a_usd_fee(self, book):
        assert CliRunner().invoke(
            cli, ['import', str(book), USD_FEE]).exit_code == 0
        return book

    def test_it_is_refused(self, with_a_usd_fee):
        result = CliRunner().invoke(cli, [
            'import', str(with_a_usd_fee), LINKED_WITH_A_USD_FEE,
            '--include-business-objects'])

        assert result.exit_code != 0, result.output
        assert 'cannot tell how much' in result.output, result.output

    def test_it_says_both_readings_and_what_to_do(self, with_a_usd_fee):
        """A refusal a reader cannot act on is a dead end. This one names the
        figure the bank got, the split that makes it ambiguous, and the two
        answers it is between."""
        result = CliRunner().invoke(cli, [
            'import', str(with_a_usd_fee), LINKED_WITH_A_USD_FEE,
            '--include-business-objects'])

        assert '100.00' in result.output, result.output
        assert 'Expenses:Supplies:USD 5.00' in result.output, result.output
        assert 'an amount on every split' in result.output, result.output

    def test_the_entry_is_left_alone(self, with_a_usd_fee):
        CliRunner().invoke(cli, ['import', str(with_a_usd_fee),
                                 LINKED_WITH_A_USD_FEE,
                                 '--include-business-objects'])
        currency, splits = _money_in(with_a_usd_fee,
                                     'Money in, net of a wire fee')

        assert currency == 'CAD', currency
        assert splits[DIRECTOR]['amount'] == Fraction('-145.95'), splits


class TestTheGroupedBlockReadsBack:
    """A book exported and read straight back is unchanged.

    The export writes one block per transaction; the comparison counted one
    settlement per *split*. Two splits against one block read as a changed
    invoice, so the run unposted it, destroyed its posting, and the rebuild
    then met the splits its own unpost had abandoned. Nothing about the file
    had changed.
    """

    @pytest.fixture
    def settled(self, book):
        runner = CliRunner()
        assert runner.invoke(
            cli, ['import', str(book), TWO_SPLITS]).exit_code == 0
        assert runner.invoke(cli, [
            'import', str(book), NAMES_TWO_SPLITS,
            '--include-business-objects']).exit_code == 0
        return book

    def _exported(self, book):
        out = book.parent / 'roundtrip.txt'
        result = CliRunner().invoke(cli, [
            'export', str(book), '--output', str(out),
            '--include-business-objects'])
        assert result.exit_code == 0, result.output
        return out

    def test_the_export_states_the_whole_payment(self, settled):
        """`amount:` is what arrived, not one split's share of it.

        Read into a book that never held the transaction the guids resolve to
        nothing and the payment is entered from the block, so a block saying
        60 books 60 for money that moved 100.
        """
        text = self._exported(settled).read_text(encoding='utf-8')

        assert 'amount: 100.00' in text, text
        assert 'amount: 60.00' not in text, text

    def test_reading_it_back_changes_nothing(self, settled):
        exported = self._exported(settled)

        again = CliRunner().invoke(cli, [
            'import', str(settled), str(exported),
            '--include-business-objects'])

        assert again.exit_code == 0, again.output
        assert 'invoice "INV-USD-001": unchanged' in again.output, again.output

    def test_the_posting_survives_reading_it_back(self, settled):
        """The cost of getting this wrong: an unpost destroys the posting
        transaction, so a book judged changed by its own export comes back on
        a transaction nothing else in the world points at."""
        before = _posting_guid(settled)
        exported = self._exported(settled)

        CliRunner().invoke(cli, ['import', str(settled), str(exported),
                                 '--include-business-objects'])

        assert _posting_guid(settled) == before


class TestWhatItWillNotDo:
    """The refusals, each with the reason that is true of it.

    Both are asked before anything moves, so a refused run leaves the entry as
    it found it — asserted, because a half-relinked transaction is the state
    nothing else here would notice.
    """

    def test_an_account_no_split_is_on_is_named_not_worked_around(self, book):
        """What the settlement is worth is read off the split that received
        the money. With no such split the figure would come from somewhere
        else and nothing would say which, so the account is named instead."""
        result = CliRunner().invoke(cli, [
            'import', str(book), NO_SUCH_ACCOUNT, '--include-business-objects'])

        assert result.exit_code != 0, result.output
        assert 'Assets:Bank' in result.output, result.output
        assert 'no split on that account' in result.output, result.output

    def test_the_entry_is_left_alone_when_that_is_refused(self, book):
        CliRunner().invoke(cli, ['import', str(book), NO_SUCH_ACCOUNT,
                                 '--include-business-objects'])
        currency, splits = _money_in(book)

        assert currency == 'CAD', currency
        assert splits[DIRECTOR]['amount'] == -139, splits[DIRECTOR]

    def test_a_fee_in_another_currency_is_refused_the_same_way(self, book):
        """One rule covers it, and it is not about the rate.

        A CAD fee raises a rate question too, but the question before it is how
        much of the transaction settles the invoice — and that is unanswerable
        for the same reason a same-currency fee makes it unanswerable. Refusing
        on the rate would answer the second question while the first is still
        open.
        """
        CliRunner().invoke(cli, ['import', str(book), WITH_A_FEE])

        result = CliRunner().invoke(cli, [
            'import', str(book), LINKED_WITH_A_FEE,
            '--include-business-objects'])

        assert result.exit_code != 0, result.output
        assert 'cannot tell how much' in result.output, result.output
        assert 'Expenses:Supplies 21.00' in result.output, result.output

    def test_a_bank_in_another_currency_is_refused_as_a_conversion(self, book):
        """The settlement really converts here, and nothing states the rate.

        The opposite of the case this issue is about: there the invoice, the
        receivable and the bank were all USD and only the discarded split was
        CAD. Here the money arrived in CAD against a USD receivable, so the
        parked split's figure is not a conversion of anything — it stood in for
        the receivable — and there is no rate in the transaction to read.

        Nothing reached this while it was being written, and it fails worst of
        all: restating from what the bank received wrote 139.00 CAD onto the
        receivable as 139.00 USD and requoted the entry USD, an implicit 1:1.
        """
        assert CliRunner().invoke(
            cli, ['import', str(book), CAD_BANK]).exit_code == 0

        result = CliRunner().invoke(cli, [
            'import', str(book), LINKED_FROM_A_CAD_BANK,
            '--include-business-objects'])

        assert result.exit_code != 0, result.output
        assert 'USD' in result.output and 'CAD' in result.output, result.output
        assert 'only the payer knows' in result.output, result.output

    def test_that_entry_is_left_alone(self, book):
        CliRunner().invoke(cli, ['import', str(book), CAD_BANK])
        CliRunner().invoke(cli, ['import', str(book), LINKED_FROM_A_CAD_BANK,
                                 '--include-business-objects'])
        currency, splits = _money_in(book, 'Money in, to the CAD bank')

        assert currency == 'CAD', currency
        assert AR not in splits, sorted(splits)
        assert splits[DIRECTOR]['amount'] == -139, splits

    def test_an_overpayment_out_of_a_parked_split_is_refused(self, book):
        """The refusal a reader reaches by doing what the run asked.

        An overpayment has to be divided, and naming a split divides nothing —
        a residue beside it has to be its own split already. Where the parked
        split is in another currency there is a second reason, and it is the
        one that was measured: the carve reads the parked split's own figure,
        which stood in for the receivable, so the run asked for
        `prepayment: 20.00`, took it, then settled 100 and parked 66.80 — with
        the values still summing to zero in CAD.
        """
        assert CliRunner().invoke(
            cli, ['import', str(book), OVERPAID]).exit_code == 0

        result = CliRunner().invoke(cli, [
            'import', str(book), LINKED_OVERPAID,
            '--include-business-objects'])

        assert result.exit_code != 0, result.output
        assert 'stood in for the receivable' in result.output, result.output
        assert 'Assets:Due From Director' in result.output, result.output

    def test_that_overpaid_entry_is_left_alone(self, book):
        CliRunner().invoke(cli, ['import', str(book), OVERPAID])
        CliRunner().invoke(cli, ['import', str(book), LINKED_OVERPAID,
                                 '--include-business-objects'])
        rows = _each_split_of(book, 'Money in, more than owed')

        assert sorted(row['account'] for row in rows) == [
            'Assets:Bank:USD', DIRECTOR], rows
        assert not any(row['in_a_lot'] for row in rows), rows

    def test_a_part_payment_that_falls_short_of_what_it_states(self, book):
        """`amount:` asserts what arrived, and the bank says otherwise.

        The guard skips itself when the account it weighs is not the record's
        currency, so handing it `Assets:Due From Director` turned it off for the
        very case this branch made reachable — a block claiming 100 against a
        bank that received 60 settled the invoice by 60 and said nothing.
        """
        assert CliRunner().invoke(
            cli, ['import', str(book), FELL_SHORT]).exit_code == 0

        result = CliRunner().invoke(cli, [
            'import', str(book), LINKED_FELL_SHORT,
            '--include-business-objects'])

        assert result.exit_code != 0, result.output
        assert 'part-paid' in result.output, result.output

    @pytest.mark.parametrize('setup,linked,says', [
        (OVERPAID, LINKED_OVERPAID_BY_SPLIT, 'stood in for the receivable'),
        (FELL_SHORT, LINKED_FELL_SHORT_BY_SPLIT, 'part-paid'),
    ])
    def test_naming_the_split_earns_the_same_refusal(self, book, setup,
                                                     linked, says):
        """Naming a split says *which* split settles the record. It says
        nothing about how much arrived, and this branch now writes the bank's
        figure onto the receivable exactly as the other one does — so the two
        size questions belong to it too.

        Asked on neither, a 120.00 receipt settled a 100.00 invoice and left
        the lot at −20 with no credit anywhere, and a block claiming 100.00
        settled it with the 60.00 the bank got. The overpayment refusal on the
        sibling branch ends "name the settling one with `txn_split_guid:`", so
        this is the edit a reader is sent to make.
        """
        assert CliRunner().invoke(
            cli, ['import', str(book), setup]).exit_code == 0

        result = CliRunner().invoke(cli, [
            'import', str(book), linked, '--include-business-objects'])

        assert result.exit_code != 0, result.output
        assert says in result.output, result.output

    def test_a_paymentsplit_naming_the_bank_side_is_refused(self, book):
        """The likeliest mistake once splits can be named, and the one nothing
        else catches: the bank split is in no lot, is nobody's, and settles
        nothing, so every other guard passes it into the invoice's lot."""
        assert CliRunner().invoke(
            cli, ['import', str(book), TWO_SPLITS]).exit_code == 0

        result = CliRunner().invoke(cli, [
            'import', str(book), NAMES_THE_BANK_SPLIT,
            '--include-business-objects'])

        assert result.exit_code != 0, result.output
        assert 'Assets:Bank:USD' in result.output, result.output
        assert 'Assets:Accounts Receivable USD' in result.output, result.output

    def test_the_fee_entry_is_left_alone(self, book):
        CliRunner().invoke(cli, ['import', str(book), WITH_A_FEE])
        CliRunner().invoke(cli, ['import', str(book), LINKED_WITH_A_FEE,
                                 '--include-business-objects'])
        currency, splits = _money_in(book, 'Money in, net of a fee')

        assert currency == 'CAD', currency
        assert splits[DIRECTOR]['amount'] == -160, splits[DIRECTOR]
        assert splits['Expenses:Supplies']['amount'] == 21


def _amounts_and_values_of(book, description):
    """Each split's amount *and* value, which is where a rounding shows.

    `_each_split_of` reads the amount alone, and a value rounded to the wrong
    currency's unit sits beside an amount that is still right — the entry
    balancing all the while, because both sides were rounded the same way.
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
                })
        query.destroy()
        return rows
    finally:
        repo.close()


def _reword_two_settling_splits(book):
    """Give the two lotted receivable splits different memos, in the book.

    The format states a split's memo, but this shape has to be built by
    settling first and rewording after — the point is what the *export* does
    with a grouped payment whose splits word themselves differently.
    """
    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.NORMAL)
    try:
        query = Query()
        query.search_for('Trans')
        query.set_book(repo.book)
        for raw in query.run():
            transaction = Transaction(instance=raw)
            if transaction.GetDescription() != 'Money in, two lines and a residue':
                continue
            lotted = [split for split in transaction.GetSplitList()
                      if get_account_full_name(split.GetAccount()) == AR
                      and split.GetLot() is not None]
            transaction.BeginEdit()
            for index, split in enumerate(lotted):
                split.SetMemo(f'Tranche {index + 1}')
            transaction.CommitEdit()
        query.destroy()
        repo.save()
    finally:
        repo.close()


def _split_memos(book, description):
    """The memo on each receivable split of a transaction, by guid."""
    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        query = Query()
        query.search_for('Trans')
        query.set_book(repo.book)
        found = {}
        for raw in query.run():
            transaction = Transaction(instance=raw)
            if transaction.GetDescription() != description:
                continue
            for split in transaction.GetSplitList():
                if get_account_full_name(split.GetAccount()) != AR:
                    continue
                found[split.GetGUID().to_string()] = split.GetMemo() or ''
        query.destroy()
        return found
    finally:
        repo.close()


class TestOnePaymentOfSeveralSplitsOnABill:
    """The payable side of the grouping, which shipped on argument before.

    `print-bill` had no grouping of its own, so a bill settled by one two-split
    transaction printed two `payment:` blocks — the bill paid twice, which is a
    different fact about the vendor — while the same book's `export` wrote one.
    Both read `settlements_by_transaction` now, and a bill's settling splits are
    positive where an invoice's are negative, which is what the summed
    `amount:` has to carry.
    """

    @pytest.fixture
    def settled_bill(self, tmp_path):
        path = tmp_path / 'bills.gnucash'
        runner = CliRunner()
        assert runner.invoke(cli, [
            'import', '--new', str(path), BILL_BOOK,
            '--include-business-objects',
            '--fx-rates', RATES]).exit_code == 0
        assert runner.invoke(
            cli, ['import', str(path), BILL_TWO_SPLITS]).exit_code == 0
        paid = runner.invoke(cli, [
            'import', str(path), BILL_NAMES_TWO_SPLITS,
            '--include-business-objects'])
        assert paid.exit_code == 0, paid.output
        return path

    def test_both_payable_splits_end_up_in_the_lot(self, settled_bill):
        rows = _each_split_of(settled_bill, 'Money out, two lines')

        payables = [row for row in rows if row['account'] == AP]
        assert len(payables) == 2, rows
        assert sorted(row['amount'] for row in payables) == [40, 60]
        assert all(row['in_a_lot'] for row in payables), payables

    def test_the_export_writes_one_block_of_the_whole_amount(self,
                                                             settled_bill):
        out = settled_bill.parent / 'bill_out.txt'
        assert CliRunner().invoke(cli, [
            'export', str(settled_bill), '--output', str(out),
            '--include-business-objects']).exit_code == 0

        text = out.read_text(encoding='utf-8')
        block = text[text.index('bill "BILL-USD-001"'):]
        assert block.count('payment:') == 1, block
        assert 'amount: 100.00' in block, block
        assert 'amount: 60.00' not in block, block

    def test_the_printed_bill_says_the_same(self, settled_bill):
        """The defect the renderer comment names: two blocks printed where the
        export wrote one."""
        out = settled_bill.parent / 'bill_printed.txt'
        assert CliRunner().invoke(cli, [
            'print-bill', str(settled_bill), 'BILL-USD-001',
            '--format', 'plaintext', '-o', str(out)]).exit_code == 0

        text = out.read_text(encoding='utf-8')
        assert text.count('payment:') == 1, text
        assert text.count('PaymentSplit') == 2, text
        assert 'amount: 100.00' in text, text

    def test_reading_the_bill_export_back_changes_nothing(self, settled_bill):
        out = settled_bill.parent / 'bill_roundtrip.txt'
        assert CliRunner().invoke(cli, [
            'export', str(settled_bill), '--output', str(out),
            '--include-business-objects']).exit_code == 0

        again = CliRunner().invoke(cli, [
            'import', str(settled_bill), str(out),
            '--include-business-objects'])

        assert again.exit_code == 0, again.output
        assert 'bill "BILL-USD-001": unchanged' in again.output, again.output


class TestAParkedSplitThatStatesItsOwnSettlement:
    """The bank is foreign, the parked split is not.

    The mirror of the shape Q-039 reports, and the one where the parked figure
    is authoritative: a USD parked split against a USD invoice on a USD
    receivable states the settlement outright, with its CAD value beside it
    because the entry is quoted in the bank's currency.

    `the_settlement_amount` already answers this — where the split being placed
    is in the record's currency it returns that split's own figure and never
    asks the bank. The refusal beside it weighed the *bank's* currency
    unconditionally and turned the file away as a conversion nobody wrote a
    rate for, saying something untrue of the split in the process: that what it
    carries "stood in for the receivable, not a conversion of it", when it is a
    stated conversion.

    So the spelling the docs call deterministic was strictly weaker than the
    one they call optional — `txn_guid:` alone settles this same file.
    """

    @pytest.fixture
    def parked_behind_a_cad_bank(self, book):
        assert CliRunner().invoke(
            cli, ['import', str(book), USD_PARKED_CAD_BANK]).exit_code == 0
        return book

    def test_naming_the_split_is_accepted(self, parked_behind_a_cad_bank):
        result = CliRunner().invoke(cli, [
            'import', str(parked_behind_a_cad_bank), NAMES_USD_SPLIT_CAD_BANK,
            '--include-business-objects'])

        assert result.exit_code == 0, result.output

    def test_the_receivable_carries_what_the_split_stated(
            self, parked_behind_a_cad_bank):
        CliRunner().invoke(cli, ['import', str(parked_behind_a_cad_bank),
                                 NAMES_USD_SPLIT_CAD_BANK,
                                 '--include-business-objects'])
        rows = _each_split_of(parked_behind_a_cad_bank,
                              'Money in, USD parked, CAD bank')

        receivable = [row for row in rows if row['account'] == AR]
        assert len(receivable) == 1, rows
        assert receivable[0]['amount'] == -100
        assert receivable[0]['in_a_lot']

    def test_the_cad_bank_split_is_untouched(self, parked_behind_a_cad_bank):
        """Nothing converted here, so nothing about the bank side changes."""
        CliRunner().invoke(cli, ['import', str(parked_behind_a_cad_bank),
                                 NAMES_USD_SPLIT_CAD_BANK,
                                 '--include-business-objects'])
        rows = _each_split_of(parked_behind_a_cad_bank,
                              'Money in, USD parked, CAD bank')

        bank = [row for row in rows if row['account'] == CAD_BANK_ACCOUNT]
        assert len(bank) == 1, rows
        assert bank[0]['amount'] == 139


class TestAGroupedSettlementBesideAResidue:
    """A payment of two splits on a transaction that also left 50.00 loose.

    `settlements_by_transaction` ungroups on a residue, so that a `prepayment:`
    can sit beside each block — the grouped spelling cannot carry one. But the
    residue belongs to the payment **once**, and `payment_residue` is computed
    per block against the splits outside it: each of the two blocks skips the
    other (it is in this record's lot) and counts the loose 50.00, so both
    declare the whole of it.

    Read into a fresh book that has to build the payment from the blocks, the
    two together claim 100.00 of residue for 50.00 of money.
    """

    @pytest.fixture
    def settled_with_a_residue(self, book):
        runner = CliRunner()
        assert runner.invoke(
            cli, ['import', str(book), TWO_SPLITS_AND_A_RESIDUE]
        ).exit_code == 0
        done = runner.invoke(cli, [
            'import', str(book), NAMES_TWO_BESIDE_A_RESIDUE,
            '--include-business-objects'])
        assert done.exit_code == 0, done.output
        return book

    def _exported(self, book):
        out = book.parent / 'residue_out.txt'
        assert CliRunner().invoke(cli, [
            'export', str(book), '--output', str(out),
            '--include-business-objects']).exit_code == 0
        text = out.read_text(encoding='utf-8')
        block = text[text.index('invoice "INV-USD-001"'):]
        return out, block

    def test_the_residue_is_stated_once_not_once_per_block(
            self, settled_with_a_residue):
        _out, block = self._exported(settled_with_a_residue)

        declared = [line for line in block.splitlines()
                    if line.strip().startswith('prepayment:')]
        assert len(declared) == 1, block
        assert '50.00' in declared[0], declared

    def test_that_page_reads_into_a_fresh_book_twice(self,
                                                     settled_with_a_residue,
                                                     tmp_path):
        """The page carries no `txn_guid:`, so in a book that never held the
        wire the payment is entered from the block — `amount:` plus the
        `prepayment:` beside it, 150.00 in all.

        Read again, the block is compared against that payment, and the figure
        it is compared *by* dropped the residue for want of a `txn_guid:` key:
        100.00 against a 150.00 bank split. So the invoice read as changed on
        every read after the first — unposted, its posting destroyed, rebuilt
        — on a page nobody had edited. That is the failure
        `_bank_side_figure_of` was written to end for the key spelling,
        arriving through the one that carries its transaction as a directive.
        """
        printed = settled_with_a_residue.parent / 'residue_page.txt'
        assert CliRunner().invoke(cli, [
            'print-invoice', str(settled_with_a_residue), 'INV-USD-001',
            '--format', 'plaintext', '-o', str(printed)]).exit_code == 0

        elsewhere = tmp_path / 'elsewhere.gnucash'
        runner = CliRunner()
        assert runner.invoke(cli, [
            'import', '--new', str(elsewhere), BOOK,
            '--include-business-objects', '--fx-rates', RATES]).exit_code == 0
        first = runner.invoke(cli, [
            'import', str(elsewhere), str(printed),
            '--include-business-objects'])
        assert first.exit_code == 0, first.output

        again = runner.invoke(cli, [
            'import', str(elsewhere), str(printed),
            '--include-business-objects'])

        assert again.exit_code == 0, again.output
        assert 'invoice "INV-USD-001": unchanged' in again.output, again.output

    def test_the_printed_page_states_it_too(self, settled_with_a_residue):
        """The page is the whole of what a reader gets — no transaction
        section, so this line is the only place the residue can be said.

        Dropped from it, a page of a two-split payment beside a 50.00 residue
        entered 100.00 for money that moved 150.00 and never created the
        owner's 50.00.
        """
        out = settled_with_a_residue.parent / 'residue_printed.txt'
        assert CliRunner().invoke(cli, [
            'print-invoice', str(settled_with_a_residue), 'INV-USD-001',
            '--format', 'plaintext', '-o', str(out)]).exit_code == 0

        text = out.read_text(encoding='utf-8')
        # `\tpayment:` rather than `payment:`, which `prepayment:` contains.
        assert text.count('\tpayment:') == 1, text
        assert 'prepayment: 50.00' in text, text
        assert text.count('prepayment:') == 1, text

    def test_it_builds_a_fresh_book_from_nothing(self, settled_with_a_residue,
                                                 tmp_path):
        """The book the export describes has to be buildable from it alone.

        Built into a book that already holds the customer, the guids clash on
        the customer before any payment is read — so the export is read into an
        empty one, which is the case a printed page lands in anyway.
        """
        out, _block = self._exported(settled_with_a_residue)

        elsewhere = tmp_path / 'elsewhere.gnucash'
        again = CliRunner().invoke(cli, [
            'import', '--new', str(elsewhere), str(out),
            '--include-business-objects'])

        assert again.exit_code == 0, again.output

    def test_every_receivable_split_is_placed_in_that_book(
            self, settled_with_a_residue, tmp_path):
        """The two settlements in the invoice's lot and the 50.00 in a lot of
        the customer's — the residue stated once and parked once."""
        out, _block = self._exported(settled_with_a_residue)
        elsewhere = tmp_path / 'elsewhere.gnucash'
        assert CliRunner().invoke(cli, [
            'import', '--new', str(elsewhere), str(out),
            '--include-business-objects']).exit_code == 0

        rows = _each_split_of(elsewhere, 'Money in, two lines and a residue')
        receivables = [row for row in rows if row['account'] == AR]
        assert sorted(row['amount'] for row in receivables) == [-60, -50, -40]
        assert all(row['in_a_lot'] for row in receivables), receivables

    def test_differing_memos_do_not_ungroup_it(self, book):
        """A memo is a label and the ledger writes each split's own anyway; a
        residue written once per block is money invented. So the residue
        decides, and the block stays grouped."""
        runner = CliRunner()
        assert runner.invoke(
            cli, ['import', str(book), TWO_SPLITS_AND_A_RESIDUE]
        ).exit_code == 0
        assert runner.invoke(cli, [
            'import', str(book), NAMES_TWO_BESIDE_A_RESIDUE,
            '--include-business-objects']).exit_code == 0
        _reword_two_settling_splits(book)

        _out, block = self._exported(book)

        assert block.count('\tpayment:') == 1, block
        assert block.count('prepayment:') == 1, block

    def test_neither_wording_is_lost_reading_that_export_back(self, book):
        """The block carries one `memo:` and the splits word themselves two
        ways, so it cannot be a correction to both.

        Written to every split it names, the block's single wording flattened
        them — "Tranche 1" onto the −40 as well, and "Tranche 2" gone from the
        book, with the next export converging on the lossy shape. The block
        wins over the transaction section where the two disagree, so the
        section's copy does not save it.
        """
        runner = CliRunner()
        assert runner.invoke(
            cli, ['import', str(book), TWO_SPLITS_AND_A_RESIDUE]
        ).exit_code == 0
        assert runner.invoke(cli, [
            'import', str(book), NAMES_TWO_BESIDE_A_RESIDUE,
            '--include-business-objects']).exit_code == 0
        _reword_two_settling_splits(book)
        out, _block = self._exported(book)

        again = runner.invoke(cli, [
            'import', str(book), str(out), '--include-business-objects'])

        assert again.exit_code == 0, again.output
        memos = _split_memos(book, 'Money in, two lines and a residue')
        assert sorted(m for m in memos.values() if m) == [
            'Tranche 1', 'Tranche 2'], memos


class TestAFigureFinerThanTheCurrency:
    """Whether the restatement can be handed a figure the receivable cannot
    hold.

    `relink_a_parked_split` copies the bank split's amount onto the receivable.
    A bank kept to a tenth of a cent, holding 100.005, would put a figure there
    the export then refuses — a book this tool wrote and cannot read back.

    It cannot arrive that way. A booked amount is judged against the
    **currency**, whatever unit the account is kept to, so a file may not state
    100.005 USD at all: the transaction is refused before any invoice sees it.
    That is the same rule `credit_on_an_account_kept_finer_than_the_cent.txt`
    records. So the shape is unreachable through this tool — which is the
    finding, and why the guard inside the restatement is for books GnuCash
    itself wrote rather than for anything a file can ask for.
    """

    def test_the_transaction_itself_is_refused(self, book):
        result = CliRunner().invoke(
            cli, ['import', str(book), FINER_THAN_THE_CENT])

        assert result.exit_code != 0, result.output
        assert '100.005' in result.output, result.output

    def test_nothing_of_it_reaches_the_book(self, book):
        CliRunner().invoke(cli, ['import', str(book), FINER_THAN_THE_CENT])

        assert not _each_split_of(book, 'Money in, finer than the cent')


class TestAPrepaymentBesideAGroupedBlock:
    """A grouped block carries `prepayment:` like any other.

    A residue is the payment's rather than any one split's, so naming several
    settlements says nothing against stating what was left over — and on a
    printed page that line is the only place a residue can be said at all, the
    page carrying no transaction section to hang a `lot_owner:` on.

    What it is weighed against is the receivable splits of the transaction the
    block does **not** name. Asked against the single named split alone, a
    payment of two counted its own other half as residue.

    So the only refusal here is the declared figure matching no residue, and it
    is reached where the book holds the transaction to weigh against. Where the
    guid names nothing there is nothing to weigh: the names are dropped and the
    block is entered from its own fields, `prepayment:` included, as any block
    naming money this book has not got is.
    """

    def test_a_figure_no_residue_matches_is_refused(self, book):
        assert CliRunner().invoke(
            cli, ['import', str(book), TWO_SPLITS]).exit_code == 0

        result = CliRunner().invoke(cli, [
            'import', str(book), GROUPED_WITH_A_PREPAYMENT,
            '--include-business-objects'])

        assert result.exit_code != 0, result.output
        # Caught before the comparison now, and by the figure rather than by
        # the lot: the splits this block does not name come to nothing.
        assert 'the splits it does not name come to 0.00' in result.output, \
            result.output

    def test_a_residue_the_block_does_not_name_is_parked(self, book):
        """A grouped block carries `prepayment:` like any other.

        A residue is the payment's, not any one split's, so naming several
        splits does not stop a block saying what was left over — and on a
        printed page this line is the only place it can be said at all, that
        page having no transaction section to hang a `lot_owner:` on.

        What it is weighed against is the splits the block does **not** name:
        asked against the single named split alone, a payment of two counted
        its own other half as residue.
        """
        runner = CliRunner()
        assert runner.invoke(
            cli, ['import', str(book), TWO_SPLITS_AND_A_RESIDUE]
        ).exit_code == 0
        stated = book.parent / 'grouped_prepay.txt'
        stated.write_text(
            (FIXTURES / 'a_payment_naming_two_splits_beside_a_residue.txt')
            .read_text(encoding='utf-8')
            .replace('    account: "Assets:Bank:USD"',
                     '    account: "Assets:Bank:USD"\n    prepayment: 50'),
            encoding='utf-8')

        done = runner.invoke(cli, [
            'import', str(book), str(stated), '--include-business-objects'])

        assert done.exit_code == 0, done.output
        rows = _each_split_of(book, 'Money in, two lines and a residue')
        assert all(row['in_a_lot'] for row in rows
                   if row['account'] == AR), rows


class TestTheDirectiveBeatsTheKeys:
    """A block carrying both spellings, naming two different transactions.

    The directive decides and the two keys go unread — a strict override rather
    than a refusal, because someone correcting an exported block adds the
    advanced form to it and having to delete two keys first earns nothing.

    **And the run says so**, which is the part that needed a test. The keys
    being read by nothing is exactly the state a reader cannot see in the book
    afterwards: nothing there distinguishes "the key was ignored" from "the
    file only ever named one", so the note is the only thing that can. Neither
    the override nor either note had a fixture, which made this the one
    behaviour here whose regression would be invisible.
    """

    @pytest.fixture
    def both_wires(self, book):
        runner = CliRunner()
        assert runner.invoke(
            cli, ['import', str(book), TWO_SPLITS]).exit_code == 0
        assert runner.invoke(
            cli, ['import', str(book), THE_OTHER_WIRE]).exit_code == 0
        return book

    def test_the_run_is_accepted(self, both_wires):
        result = CliRunner().invoke(cli, [
            'import', str(both_wires), KEY_AND_DIRECTIVE_DISAGREE,
            '--include-business-objects'])

        assert result.exit_code == 0, result.output

    def test_the_directives_transaction_is_the_one_linked(self, both_wires):
        CliRunner().invoke(cli, ['import', str(both_wires),
                                 KEY_AND_DIRECTIVE_DISAGREE,
                                 '--include-business-objects'])
        named = _each_split_of(both_wires, 'Money in, the other wire')

        settled = [row for row in named
                   if row['account'] == AR and row['in_a_lot']]
        assert [row['amount'] for row in settled] == [-100], named

    def test_the_transaction_the_key_names_is_untouched(self, both_wires):
        CliRunner().invoke(cli, ['import', str(both_wires),
                                 KEY_AND_DIRECTIVE_DISAGREE,
                                 '--include-business-objects'])
        keyed = _each_split_of(both_wires, 'Money in, two lines')

        receivables = [row for row in keyed if row['account'] == AR]
        assert len(receivables) == 2, keyed
        assert not any(row['in_a_lot'] for row in receivables), receivables

    def test_the_run_says_the_keys_went_unread(self, both_wires):
        """The only thing that distinguishes the override from a file that
        named one transaction all along."""
        result = CliRunner().invoke(cli, [
            'import', str(both_wires), KEY_AND_DIRECTIVE_DISAGREE,
            '--include-business-objects'])

        assert 'txn_guid' in result.output, result.output
        assert 'Transaction' in result.output, result.output


class TestFollowingTheOverpaymentRemedy:
    """Doing what the refusal tells you to do, and having it work.

    The refusal asks for the transaction to be written with the settlement and
    the residue as two splits, the settling one named and the rest declared as
    `prepayment:`. Nothing followed it, and as first worded it was not
    followable: the natural place to put those two splits in this feature's
    context is the account the money was parked on, and the reconciliation only
    counts loose splits on the record's own posted account — so a residue left
    there sums to 0.00 and earns a second refusal that says nothing about
    where it should have gone. The message names the account now.
    """

    @pytest.fixture
    def written_out(self, book):
        assert CliRunner().invoke(
            cli, ['import', str(book), RESIDUE_ON_THE_RECEIVABLE]
        ).exit_code == 0
        return book

    def test_the_remedy_is_accepted(self, written_out):
        result = CliRunner().invoke(cli, [
            'import', str(written_out), FOLLOWS_THE_REMEDY,
            '--include-business-objects'])

        assert result.exit_code == 0, result.output

    def test_the_settlement_and_the_residue_are_both_lotted(self, written_out):
        """The settling split in the invoice's lot, the residue in one of the
        customer's — not left loose, which is what `prepayment:` is for."""
        CliRunner().invoke(cli, ['import', str(written_out),
                                 FOLLOWS_THE_REMEDY,
                                 '--include-business-objects'])
        rows = _each_split_of(written_out, 'Money in, settlement and residue')

        receivables = [row for row in rows if row['account'] == AR]
        assert sorted(row['amount'] for row in receivables) == [-100, -20]
        assert all(row['in_a_lot'] for row in receivables), receivables


class TestAFeeBesideASplitThatStatesItsOwnFigure:
    """A third split does not make the size ambiguous where the split says it.

    The fee refusal exists because the settlement is otherwise *inferred* from
    what the bank received: 95.00 credited beside a 5.00 fee is a customer who
    paid 100 and bore the fee, or one who paid 95 with the fee ours, and
    nothing in the book says which.

    A suspense split stating −100.00 USD against a USD invoice has said which.
    So this is accepted — and the accepting path had no test at all, every
    other fee fixture here parking in CAD, where the figure means nothing and
    the ambiguity is real. README and Q-039 stated the refusal without that
    bound, promising one for their own worked example.
    """

    @pytest.fixture
    def a_fee_in_usd(self, book):
        assert CliRunner().invoke(
            cli, ['import', str(book), USD_FEE_USD_PARKED]).exit_code == 0
        return book

    def test_it_is_accepted(self, a_fee_in_usd):
        result = CliRunner().invoke(cli, [
            'import', str(a_fee_in_usd), NAMES_USD_SPLIT_BESIDE_A_USD_FEE,
            '--include-business-objects'])

        assert result.exit_code == 0, result.output

    def test_the_split_settles_the_invoice_at_its_own_figure(self,
                                                             a_fee_in_usd):
        CliRunner().invoke(cli, ['import', str(a_fee_in_usd),
                                 NAMES_USD_SPLIT_BESIDE_A_USD_FEE,
                                 '--include-business-objects'])
        rows = _each_split_of(a_fee_in_usd, 'Money in, USD suspense, net of a fee')

        receivable = [row for row in rows if row['account'] == AR]
        assert len(receivable) == 1, rows
        assert receivable[0]['amount'] == -100
        assert receivable[0]['in_a_lot']

    def test_the_fee_and_the_bank_are_untouched(self, a_fee_in_usd):
        CliRunner().invoke(cli, ['import', str(a_fee_in_usd),
                                 NAMES_USD_SPLIT_BESIDE_A_USD_FEE,
                                 '--include-business-objects'])
        rows = _each_split_of(a_fee_in_usd, 'Money in, USD suspense, net of a fee')

        by_account = {row['account']: row for row in rows}
        assert by_account['Expenses:Supplies:USD']['amount'] == 5
        assert by_account[BANK]['amount'] == 95


class TestACreditBlockNamingATransactionOnASettledRecord:
    """The credit refusal has to be asked before the comparison, not inside it.

    `_apply_credit_payment_directive` is where the refusal lived, and an
    unchanged record never reaches it. `payment_slots` counts a settlement per
    `PaymentSplit` whatever kind of block it sits in, and a slot carrying a
    guid is matched by guid alone — so an exported credit block, which already
    carries `txn_guid:` and `txn_split_guid:`, with a `Transaction` naming the
    same transaction and split added to it, matched its own settlement, printed
    `unchanged`, and had its directive read by nobody.

    That is the silent unread line the refusal exists to prevent, on the one
    path that never reached it. The unpaid record was the only case covered.
    """

    ACCOUNTS = 'tests/fixtures/payment_roundtrip_accounts.txt'

    @pytest.fixture
    def credit_settled(self, tmp_path):
        runner = CliRunner()
        book = tmp_path / 'credit.gnucash'
        assert runner.invoke(
            cli, ['import', '--new', str(book), self.ACCOUNTS]).exit_code == 0
        for name in ('q015_aac_primer_invoice.txt',
                     'q015_aac_inv002_partial_credit.txt'):
            done = runner.invoke(cli, [
                'import', str(book), str(FIXTURES / name),
                '--include-business-objects'])
            assert done.exit_code == 0, done.output
        out = tmp_path / 'credit_out.txt'
        assert runner.invoke(cli, [
            'export', str(book), str(out),
            '--include-business-objects']).exit_code == 0
        text = out.read_text(encoding='utf-8')
        assert 'from_credit: #True' in text, text
        return book, out, text

    @staticmethod
    def _with_a_transaction_directive(text):
        """The credit block, plus a `Transaction` naming what it already names."""
        lines = text.splitlines()
        for index, line in enumerate(lines):
            if line.strip() != 'from_credit: #True':
                continue
            txn = split = ''
            for after in lines[index:index + 8]:
                if after.strip().startswith('txn_guid:'):
                    txn = after.split('"')[1]
                elif after.strip().startswith('txn_split_guid:'):
                    split = after.split('"')[1]
            assert txn and split, lines[index:index + 8]
            lines.insert(index + 1, f'\t\t\tPaymentSplit "{split}"')
            lines.insert(index + 1, f'\t\tTransaction "{txn}"')
            return '\n'.join(lines) + '\n'
        raise AssertionError('no credit block in the export')

    def test_the_unedited_export_reads_back_unchanged(self, credit_settled):
        """Stated rather than assumed: the directive is the only difference."""
        book, out, text = credit_settled

        again = CliRunner().invoke(cli, [
            'import', str(book), str(out), '--include-business-objects'])

        assert again.exit_code == 0, again.output
        assert 'unchanged' in again.output, again.output

    def test_adding_a_transaction_directive_is_refused(self, credit_settled,
                                                       tmp_path):
        book, _out, text = credit_settled
        edited = tmp_path / 'credit_with_directive.txt'
        edited.write_text(self._with_a_transaction_directive(text),
                          encoding='utf-8')

        result = CliRunner().invoke(cli, [
            'import', str(book), str(edited), '--include-business-objects'])

        assert result.exit_code != 0, result.output
        assert 'no grouped spelling' in result.output, result.output


class TestSeveralSplitsThisCannotDivide:
    """Two named splits, both parked in another currency.

    One parked split can be restated from what the bank received. Two cannot:
    dividing the 100.00 USD between them needs a ratio, and the only numbers on
    offer are the CAD figures being discarded — splitting it 70/69 because the
    CAD happened to fall that way is a rate invented out of scaffolding.

    Asked where the block's names are read, ahead of the per-split account
    check in the grouped branch, so the reader is told the settlement cannot be
    divided rather than that each split is on the wrong account — true, but not
    the obstacle. That ordering is why this needs a test of its own: without
    one, nothing distinguishes the two refusals.
    """

    @pytest.fixture
    def parked_in_two(self, book):
        assert CliRunner().invoke(
            cli, ['import', str(book), TWO_PARKED_CAD_SPLITS]).exit_code == 0
        return book

    def test_it_is_refused(self, parked_in_two):
        result = CliRunner().invoke(cli, [
            'import', str(parked_in_two), NAMES_TWO_PARKED_CAD_SPLITS,
            '--include-business-objects'])

        assert result.exit_code != 0, result.output

    def test_it_says_the_settlement_cannot_be_divided(self, parked_in_two):
        """Its own message, not the per-split account check's."""
        result = CliRunner().invoke(cli, [
            'import', str(parked_in_two), NAMES_TWO_PARKED_CAD_SPLITS,
            '--include-business-objects'])

        assert 'another currency' in result.output, result.output
        # And names them, so a reader can go and look rather than counting
        # their own splits to work out which two were meant.
        assert 'ccdd11223344556677889900eeffaabb' in result.output, \
            result.output
        assert 'dd11223344556677889900eeffaabbcc' in result.output, \
            result.output
        assert DIRECTOR in result.output, result.output

    def test_the_entry_is_left_alone(self, parked_in_two):
        CliRunner().invoke(cli, ['import', str(parked_in_two),
                                 NAMES_TWO_PARKED_CAD_SPLITS,
                                 '--include-business-objects'])
        rows = _each_split_of(parked_in_two, 'Money in, parked in two lines')

        parked = [row for row in rows if row['account'] == DIRECTOR]
        assert len(parked) == 2, rows
        assert sorted(row['amount'] for row in parked) == [-70, -69]
        assert not any(row['in_a_lot'] for row in parked), parked


class TestAPaymentNamingOneSplitTwice:
    """A copy-pasted `PaymentSplit` line.

    Nothing deduplicated it: the guids come back verbatim, `payment_slots`
    emits one slot per entry, and the grouped branch claims one split per
    entry. So one 40.00 split counted as two settlements — `amount:` was
    *required* to state 80.00 for money that moved 40.00, the owed check
    passed, and the attach ran twice (idempotent), leaving the book with one
    settlement of 40.00 against a file asserting 80.00.

    Then it never settles: two slots against the one split the lot holds, so
    the invoice is judged changed on every import of an unedited file. That is
    what slots exist to prevent, and two `Transaction` blocks under one payment
    were already refused for the same reason.
    """

    @pytest.fixture
    def two_splits(self, book):
        assert CliRunner().invoke(
            cli, ['import', str(book), TWO_SPLITS]).exit_code == 0
        return book

    def test_it_is_refused(self, two_splits):
        result = CliRunner().invoke(cli, [
            'import', str(two_splits), NAMES_ONE_SPLIT_TWICE,
            '--include-business-objects'])

        assert result.exit_code != 0, result.output

    def test_the_refusal_names_the_repeated_guid(self, two_splits):
        result = CliRunner().invoke(cli, [
            'import', str(two_splits), NAMES_ONE_SPLIT_TWICE,
            '--include-business-objects'])

        assert '8192a3b4c5d6e7f80912233445566778' in result.output, \
            result.output

    def test_nothing_is_attached(self, two_splits):
        CliRunner().invoke(cli, ['import', str(two_splits),
                                 NAMES_ONE_SPLIT_TWICE,
                                 '--include-business-objects'])
        rows = _each_split_of(two_splits, 'Money in, two lines')

        receivables = [row for row in rows if row['account'] == AR]
        assert not any(row['in_a_lot'] for row in receivables), receivables

    def test_the_two_spellings_of_one_guid_are_one_name(self, two_splits):
        """A guid is written hyphenated or not and means the same split —
        GnuCash's own windows show the hyphenated form. Everything else here
        normalises before comparing; the guard compared raw strings."""
        result = CliRunner().invoke(cli, [
            'import', str(two_splits), ONE_SPLIT_TWICE_TWO_SPELLINGS,
            '--include-business-objects'])

        assert result.exit_code != 0, result.output
        assert 'named twice' in result.output, result.output


class TestAResidueBesideAnOrphanedSettlement:
    """An orphan is a settlement waiting to be put back, not a residue.

    `payment_residue` — which writes every `prepayment:` line — skips two kinds
    of split: one in a lot naming a record, and one this tool's own unpost
    orphaned. The first was carried into the readers last round and the second
    was not, so a wire whose other settlement had since been unposted counted
    that loose 50.00 toward a declared 30.00 and made it 80.00.

    An orphan is not `_settles_another_record`: unposting leaves the lot
    naming nothing (CLAUDE.md §10), which is exactly why the mark exists. So
    the export wrote 30.00 and its own importer refused the file — before the
    comparison that would have said `unchanged`.
    """

    @pytest.fixture
    def with_an_orphan(self, book):
        runner = CliRunner()
        assert runner.invoke(
            cli, ['import', str(book), TWO_INVOICES_SMALL_RESIDUE]
        ).exit_code == 0
        assert runner.invoke(cli, [
            'import', str(book), THE_FIFTY_INVOICE,
            '--include-business-objects']).exit_code == 0
        assert runner.invoke(cli, [
            'import', str(book), GROUPED_BESIDE_AN_ORPHAN,
            '--include-business-objects']).exit_code == 0
        unposted = runner.invoke(cli, [
            'unpost-invoices', str(book), 'INV-USD-004'])
        assert unposted.exit_code == 0, unposted.output
        return book

    def test_the_export_reads_back_unchanged(self, with_an_orphan):
        out = with_an_orphan.parent / 'with_orphan.txt'
        assert CliRunner().invoke(cli, [
            'export', str(with_an_orphan), '--output', str(out),
            '--include-business-objects']).exit_code == 0

        again = CliRunner().invoke(cli, [
            'import', str(with_an_orphan), str(out),
            '--include-business-objects'])

        assert again.exit_code == 0, again.output
        assert 'invoice "INV-USD-001": unchanged' in again.output, again.output


class TestAParkedCurrencyCoarserThanTheRecords:
    """Requote first, then restate — or the values are rounded to the wrong
    unit.

    GnuCash rounds a split's *value* to the transaction's current currency as
    it is set. Restating before requoting therefore rounds through the parked
    split's own unit: a yen is its own smallest unit, so −100.50 became −101.00
    and the bank's +100.50 became +101.00, and converting back to hundredths
    afterwards cannot recover the cent.

    What that leaves is an amount of −100.50 USD beside a value of −101.00 USD
    on the same commodity — an implied 1.00498 between USD and USD that nobody
    wrote — and the entry balances, both sides having been rounded the same
    way, so nothing disagrees. The export then writes a `share_price` for a
    USD→USD split.

    CAD and USD are both hundredths, which is why nothing else here shows it.
    The importer's own update path already sets the currency first.
    """

    @pytest.fixture
    def parked_in_yen(self, book):
        runner = CliRunner()
        assert runner.invoke(
            cli, ['import', str(book), PARKED_IN_YEN]).exit_code == 0
        done = runner.invoke(cli, [
            'import', str(book), THE_YEN_PAID_INVOICE,
            '--include-business-objects'])
        assert done.exit_code == 0, done.output
        return book

    def test_the_receivable_keeps_its_cent(self, parked_in_yen):
        rows = _amounts_and_values_of(parked_in_yen, 'Money in, parked in yen')

        receivable = [row for row in rows if row['account'] == AR]
        assert len(receivable) == 1, rows
        assert receivable[0]['amount'] == Fraction(-201, 2), receivable
        assert receivable[0]['value'] == Fraction(-201, 2), receivable

    def test_the_bank_side_keeps_its_cent(self, parked_in_yen):
        """Its value is set in the same edit, off the same currency."""
        rows = _amounts_and_values_of(parked_in_yen, 'Money in, parked in yen')

        bank = [row for row in rows if row['account'] == BANK]
        assert len(bank) == 1, rows
        assert bank[0]['amount'] == Fraction(201, 2), bank
        assert bank[0]['value'] == Fraction(201, 2), bank


class TestAResidueBesideAnotherInvoicesShare:
    """The reader and the writer have to mean the same thing by "residue".

    One wire settles this invoice with two splits, settles another with a
    third, and leaves a fourth over. `payment_residue` — the writer — skips a
    split sitting in a lot that names an invoice or a bill, because that is
    that record's portion and was never left over. The reader totalled every
    receivable split the block did not name, so the other invoice's 180.00
    counted toward a declared 50.00 and made it 230.00.

    So the block the export writes for this state was refused by the importer
    that received it. The arithmetic is old — it came out of the rebuild path
    verbatim — but reachable only when a record was being rebuilt, and the key
    spelling short-circuits on a matching `txn_guid:` before it. Asking it
    before the comparison, for the spelling that pairs by guid, is what
    unmasked it.
    """

    @pytest.fixture
    def one_share_settled(self, book):
        runner = CliRunner()
        assert runner.invoke(
            cli, ['import', str(book), TWO_INVOICES_AND_A_RESIDUE]
        ).exit_code == 0
        done = runner.invoke(cli, [
            'import', str(book), THE_SECOND_INVOICE,
            '--include-business-objects'])
        assert done.exit_code == 0, done.output
        return book

    def test_the_grouped_block_beside_it_is_accepted(self, one_share_settled):
        result = CliRunner().invoke(cli, [
            'import', str(one_share_settled), GROUPED_BESIDE_ANOTHER_SHARE,
            '--include-business-objects'])

        assert result.exit_code == 0, result.output

    def test_the_export_of_it_builds_a_fresh_book(self, one_share_settled,
                                                  tmp_path):
        """The state the export exists for, rebuilt from the export.

        A residue on a wire that settles two records belongs to neither
        block. Written on both — each skipping the other's portion, so each
        seeing the same 50.00 — the ledger declared 100.00 of residue for
        50.00 of money and no import order survived: reading this invoice
        first found 230.00 loose against a declared 50.00, and reading the
        other first found 150.00. Same-book re-import said `unchanged`
        throughout, so only the rebuild the export exists for was broken.

        `lot_owner:` on the split is what carries such a residue, which the
        transaction section writes and which the refusal itself names as the
        way to park one.
        """
        CliRunner().invoke(cli, ['import', str(one_share_settled),
                                 GROUPED_BESIDE_ANOTHER_SHARE,
                                 '--include-business-objects'])
        out = one_share_settled.parent / 'shared_wire.txt'
        assert CliRunner().invoke(cli, [
            'export', str(one_share_settled), '--output', str(out),
            '--include-business-objects']).exit_code == 0

        elsewhere = tmp_path / 'elsewhere.gnucash'
        again = CliRunner().invoke(cli, [
            'import', '--new', str(elsewhere), str(out),
            '--include-business-objects'])

        assert again.exit_code == 0, again.output

    def test_the_rebuilt_book_holds_every_split(self, one_share_settled,
                                                tmp_path):
        CliRunner().invoke(cli, ['import', str(one_share_settled),
                                 GROUPED_BESIDE_ANOTHER_SHARE,
                                 '--include-business-objects'])
        out = one_share_settled.parent / 'shared_wire.txt'
        assert CliRunner().invoke(cli, [
            'export', str(one_share_settled), '--output', str(out),
            '--include-business-objects']).exit_code == 0
        elsewhere = tmp_path / 'elsewhere.gnucash'
        assert CliRunner().invoke(cli, [
            'import', '--new', str(elsewhere), str(out),
            '--include-business-objects']).exit_code == 0

        rows = _each_split_of(elsewhere, 'Money in, two invoices and a residue')
        receivables = [row for row in rows if row['account'] == AR]
        assert sorted(row['amount'] for row in receivables) == [
            -180, -60, -50, -40]
        assert all(row['in_a_lot'] for row in receivables), receivables

    def test_every_split_lands_where_it_belongs(self, one_share_settled):
        CliRunner().invoke(cli, ['import', str(one_share_settled),
                                 GROUPED_BESIDE_ANOTHER_SHARE,
                                 '--include-business-objects'])
        rows = _each_split_of(one_share_settled,
                              'Money in, two invoices and a residue')

        receivables = [row for row in rows if row['account'] == AR]
        assert sorted(row['amount'] for row in receivables) == [
            -180, -60, -50, -40]
        assert all(row['in_a_lot'] for row in receivables), receivables


class TestAGroupedBlockNamingSomebodysCredit:
    """The lot refusal firing, which nothing exercised.

    Its only coverage asserted it does *not* fire — on a split already in this
    record's own lot. It is reachable: a `PaymentSplit` naming a split parked
    in the owner's credit takes money the customer is owed, leaving the credit
    short with every figure in the book still balancing.

    The grouped spelling is stricter than the single one here, on purpose.
    `txn_split_guid:` naming that same split spends the credit deliberately —
    the route the ambiguity refusal sends readers down by name — while a block
    naming several splits is saying which of them settle this record, not
    choosing which credit to spend. README lists it now, since a reader
    grouping two splits where one is a credit meets a refusal the format did
    not mention.
    """

    @pytest.fixture
    def one_is_credit(self, book):
        assert CliRunner().invoke(
            cli, ['import', str(book), ONE_SPLIT_AS_CREDIT]).exit_code == 0
        return book

    def test_it_is_refused(self, one_is_credit):
        result = CliRunner().invoke(cli, [
            'import', str(one_is_credit), NAMES_A_SPLIT_IN_A_CREDIT_LOT,
            '--include-business-objects'])

        assert result.exit_code != 0, result.output
        assert 'in lot' in result.output, result.output

    def test_neither_split_is_taken(self, one_is_credit):
        """Judged before any is attached, so a refused file changes nothing."""
        CliRunner().invoke(cli, ['import', str(one_is_credit),
                                 NAMES_A_SPLIT_IN_A_CREDIT_LOT,
                                 '--include-business-objects'])
        rows = _each_split_of(one_is_credit, 'Money in, two lines')

        settling = [row for row in rows
                    if row['account'] == AR and row['amount'] == -60]
        assert len(settling) == 1, rows
        assert not settling[0]['in_a_lot'], settling


class TestAnAmountEditedAfterTheSettlementLanded:
    """`amount:` weighed on a record that already matches, and in both
    spellings.

    The sum check lived on the apply side, and an unchanged record is never
    applied — a naming block's slots pair by guid, and nothing on the
    comparison side reads `amount:` at all. So editing a settled block's
    figure to 60.00 reported `unchanged` at exit 0, leaving the ledger stating
    60.00 for money that moved 100.00.

    The key spelling is deliberately not asked the same question. `amount:`
    means a different figure there — `_bank_side_figure_of` reads it as what
    moved through the bank, residue included — which is why the remedy this
    tool prints for an overpayment states 120.00 beside a 100.00 split and a
    `prepayment: 20`. Weighing that against the named split would refuse the
    tool's own advice.
    """

    @pytest.fixture
    def settled(self, book):
        runner = CliRunner()
        assert runner.invoke(
            cli, ['import', str(book), TWO_SPLITS]).exit_code == 0
        assert runner.invoke(cli, [
            'import', str(book), NAMES_TWO_SPLITS,
            '--include-business-objects']).exit_code == 0
        return book

    def test_editing_the_amount_of_a_settled_block_is_refused(self, settled):
        result = CliRunner().invoke(cli, [
            'import', str(settled), TWO_SPLITS_MISSTATED,
            '--include-business-objects'])

        assert result.exit_code != 0, result.output
        assert 'unchanged' not in result.output, result.output

    def test_that_refusal_quotes_both_figures(self, settled):
        result = CliRunner().invoke(cli, [
            'import', str(settled), TWO_SPLITS_MISSTATED,
            '--include-business-objects'])

        assert '60.00' in result.output, result.output
        assert '100.00' in result.output, result.output

    def test_an_edited_prepayment_is_weighed_too(self, book):
        """`prepayment:` is in the same position `amount:` was.

        A naming block's slots pair by guid, so `_single_payment_matches` —
        which is what compares the declared residue on the key spelling —
        never runs for one. Editing a settled block's `prepayment: 50` to
        `999` therefore read back `unchanged`, leaving the ledger asserting a
        999.00 credit the book has not got.
        """
        runner = CliRunner()
        assert runner.invoke(
            cli, ['import', str(book), TWO_SPLITS_AND_A_RESIDUE]
        ).exit_code == 0
        source = (FIXTURES / 'a_payment_naming_two_splits_beside_a_residue.txt'
                  ).read_text(encoding='utf-8')
        stated = book.parent / 'with_residue.txt'
        stated.write_text(
            source.replace('    account: "Assets:Bank:USD"',
                           '    account: "Assets:Bank:USD"\n    prepayment: 50'),
            encoding='utf-8')
        assert runner.invoke(cli, [
            'import', str(book), str(stated),
            '--include-business-objects']).exit_code == 0
        edited = book.parent / 'residue_edited.txt'
        edited.write_text(
            stated.read_text(encoding='utf-8').replace('prepayment: 50',
                                                       'prepayment: 999'),
            encoding='utf-8')

        again = runner.invoke(cli, [
            'import', str(book), str(edited), '--include-business-objects'])

        assert again.exit_code != 0, again.output
        assert 'unchanged' not in again.output, again.output

    def test_the_key_spelling_states_the_bank_side_instead(self, book):
        """Not the same question, and deliberately so.

        `amount:` on `txn_guid:` + `txn_split_guid:` is what moved through the
        bank, residue and all — which is why the overpayment remedy states
        120.00 beside a 100.00 split and a `prepayment: 20`. Weighing it
        against the named split would refuse this tool's own advice, so the
        block below is accepted where the directive form of it is refused.
        """
        assert CliRunner().invoke(
            cli, ['import', str(book), TWO_SPLITS]).exit_code == 0

        result = CliRunner().invoke(cli, [
            'import', str(book), KEY_SPELLING_MISSTATED,
            '--include-business-objects'])

        assert result.exit_code == 0, result.output


class TestABlockNamingOneSplitAndMisstatingIt:
    """`amount:` has to be read on a one-`PaymentSplit` block too.

    The sum check was written for a block naming several, so a block naming one
    fell past it — and its slot carries the guid, so the pairing matches by
    that and `_single_payment_matches`, the only other reader of `amount:`,
    never runs for it either. The equivalent `txn_guid:` + `txn_split_guid:`
    block gets a bare slot and *is* amount-matched, so two spellings the docs
    call equivalent disagreed.

    The cost is the same "one file, two meanings" the sum check exists for: in
    the book holding the transaction the split settles its own 60.00, and in
    one that does not the guids resolve to nothing and the stated figure is
    entered from the block.
    """

    @pytest.fixture
    def two_splits(self, book):
        assert CliRunner().invoke(
            cli, ['import', str(book), TWO_SPLITS]).exit_code == 0
        return book

    def test_it_is_refused(self, two_splits):
        result = CliRunner().invoke(cli, [
            'import', str(two_splits), ONE_SPLIT_MISSTATED,
            '--include-business-objects'])

        assert result.exit_code != 0, result.output

    def test_the_refusal_quotes_both_figures(self, two_splits):
        result = CliRunner().invoke(cli, [
            'import', str(two_splits), ONE_SPLIT_MISSTATED,
            '--include-business-objects'])

        assert '999.00' in result.output, result.output
        assert '60.00' in result.output, result.output

    def test_a_parked_split_in_the_same_currency_is_weighed_too(self, book):
        """The exemption belongs to a split foreign to the receivable.

        It was scoped to "parked", which is decided by account type, so a USD
        suspense split against a USD invoice took it — though its own figure
        states the settlement there, which is what `the_settlement_amount`
        already returns for it. Nothing else caught the overstatement: 100.00
        against 100.00 owed passes both the fall-short and the overpayment
        refusals, so `amount: 999` imported at exit 0.
        """
        assert CliRunner().invoke(
            cli, ['import', str(book), USD_PARKED]).exit_code == 0

        result = CliRunner().invoke(cli, [
            'import', str(book), GROUPED_MISSTATING_A_PARKED_SPLIT,
            '--include-business-objects'])

        assert result.exit_code != 0, result.output
        assert '999.00' in result.output, result.output
        assert '100.00' in result.output, result.output


class TestAnOverpaymentWalkingPastTheGuards:
    """The overpayment arm returns before the guards installed after it.

    Both checks on the `txn_guid:`-alone branch sat below the carve, which
    `return`s — so they guarded only the file that settles exactly, and the
    same file overpaying went straight through. `prepayment:` is what chooses
    that arm, so adding one is the whole difference between the refused
    versions of these two and the accepted ones.

    What it cost: a cash sale's revenue split re-accounted onto the receivable
    and divided 100/20; and, with the sides swapped, the bank's own deposit
    moved there at +100.00 with +20.00 parked in a lot called a credit while
    holding a debit. Both balanced and both exited 0.
    """

    def test_the_cash_sale_is_refused_when_it_overpays(self, book):
        runner = CliRunner()
        assert runner.invoke(
            cli, ['import', str(book), A_CASH_SALE_WORTH_MORE]).exit_code == 0

        result = runner.invoke(cli, [
            'import', str(book), OVERPAYS_FROM_THE_CASH_SALE,
            '--include-business-objects'])

        assert result.exit_code != 0, result.output
        assert INCOME_USD in result.output, result.output

    def test_the_revenue_is_not_carved(self, book):
        runner = CliRunner()
        assert runner.invoke(
            cli, ['import', str(book), A_CASH_SALE_WORTH_MORE]).exit_code == 0
        runner.invoke(cli, ['import', str(book), OVERPAYS_FROM_THE_CASH_SALE,
                            '--include-business-objects'])
        rows = _each_split_of(book, 'Cash sale, too much, income baked in')

        income = [row for row in rows if row['account'] == INCOME_USD]
        assert len(income) == 1, rows
        assert income[0]['amount'] == -120
        assert not [row for row in rows if row['account'] == AR], rows

    def test_the_swapped_sides_are_refused_when_they_overpay(self, book):
        runner = CliRunner()
        assert runner.invoke(
            cli, ['import', str(book), USD_PARKED_WORTH_MORE]).exit_code == 0

        result = runner.invoke(cli, [
            'import', str(book), OVERPAYS_WITH_SIDES_SWAPPED,
            '--include-business-objects'])

        assert result.exit_code != 0, result.output

    def test_the_deposit_is_not_carved_off_the_bank(self, book):
        runner = CliRunner()
        assert runner.invoke(
            cli, ['import', str(book), USD_PARKED_WORTH_MORE]).exit_code == 0
        runner.invoke(cli, ['import', str(book), OVERPAYS_WITH_SIDES_SWAPPED,
                            '--include-business-objects'])
        rows = _each_split_of(book,
                              'Money in, USD suspense, swapped and too much')

        bank = [row for row in rows if row['account'] == BANK]
        assert len(bank) == 1, rows
        assert bank[0]['amount'] == 120
        assert not bank[0]['in_a_lot'], bank


class TestACreditNotesRefund:
    """A credit note posts the other way round, so its settlement does too.

    `−100.00` on the receivable where an invoice puts `+100.00`, and the refund
    that cancels it is therefore `+100.00`. The sign a settlement must have is
    the opposite of the posting's, which is what `_still_owed` has always
    computed — not a property of the account's type.

    Read from the type alone, "a settlement of a receivable is negative on it"
    is true of an invoice and the reverse of this, so the swapped-sides guard
    refused a link that had always worked, telling the reader to give
    `account:` the account the money moved through when `account:` was right.

    Only the `txn_guid:`-alone spelling reaches it: an exported refund carries
    `txn_split_guid:`, whose branch does not run the guard for a split already
    on the receivable. So a round-trip was unaffected and a hand-written or
    bank-feed-first ledger was not.
    """

    @pytest.fixture
    def a_note_and_its_refund(self, book):
        runner = CliRunner()
        posted = runner.invoke(cli, [
            'import', str(book), A_CREDIT_NOTE, '--include-business-objects'])
        assert posted.exit_code == 0, posted.output
        assert runner.invoke(
            cli, ['import', str(book), A_REFUND]).exit_code == 0
        return book

    def test_the_note_posts_the_other_way_round(self, a_note_and_its_refund):
        """Stated rather than assumed: everything below turns on this sign."""
        rows = _each_split_of(a_note_and_its_refund,
                              'Credit note CN-USD-001')

        receivable = [row for row in rows if row['account'] == AR]
        assert len(receivable) == 1, rows
        assert receivable[0]['amount'] == -100, receivable

    def test_the_refund_links(self, a_note_and_its_refund):
        result = CliRunner().invoke(cli, [
            'import', str(a_note_and_its_refund), REFUND_NAMING_THE_TX,
            '--include-business-objects'])

        assert result.exit_code == 0, result.output

    def test_the_receivable_split_joins_the_notes_lot(self,
                                                      a_note_and_its_refund):
        CliRunner().invoke(cli, ['import', str(a_note_and_its_refund),
                                 REFUND_NAMING_THE_TX,
                                 '--include-business-objects'])
        rows = _each_split_of(a_note_and_its_refund, 'Refund to the customer')

        receivable = [row for row in rows if row['account'] == AR]
        assert len(receivable) == 1, rows
        assert receivable[0]['amount'] == 100
        assert receivable[0]['in_a_lot']


class TestASplitOnIncomeExpenseOrEquity:
    """Money is not parked in income, expense or equity.

    A split was read as parked by *negation* — any account that is not the
    receivable or the payable — so the revenue split of a complete cash-sale
    entry qualified. All three accounts being USD, the guard that would look at
    the rest of the entry returns early; and an income credit is negative,
    which is the sign a receivable settlement wants.

    So naming it moved the revenue onto the receivable: the sale gone from the
    P&L, the invoice reading paid, the entry balancing exactly as it did
    before, at exit 0. The reconciliation guide calls this shape unsupported —
    a bank entry with the income baked in has nothing on a receivable to link —
    and before this it was a hard refusal for not living on an AR/AP account.
    """

    @pytest.fixture
    def a_cash_sale(self, book):
        assert CliRunner().invoke(
            cli, ['import', str(book), A_CASH_SALE]).exit_code == 0
        return book

    def test_it_is_refused(self, a_cash_sale):
        """For the account, not the commodity — the revenue is in dollars."""
        result = CliRunner().invoke(cli, [
            'import', str(a_cash_sale), NAMES_THE_INCOME_SPLIT,
            '--include-business-objects'])

        assert result.exit_code != 0, result.output
        assert INCOME_USD in result.output, result.output
        assert 'nor an account money passes through' in result.output, \
            result.output
        assert 'not a currency' not in result.output, result.output

    def test_naming_only_the_transaction_is_refused_too(self, a_cash_sale):
        """The check belongs on the split about to move, not on the words that
        chose it — Q-039 says the two spellings reach the same place.

        This arm also regressed: the settlement used to be the split's own
        figure, so a CAD income split against a USD invoice hit "exceeds
        invoice remaining" and was turned away by accident. Reading it off the
        bank removed that barrier without putting the deliberate one there.
        """
        result = CliRunner().invoke(cli, [
            'import', str(a_cash_sale), NAMES_ONLY_THE_CASH_SALE,
            '--include-business-objects'])

        assert result.exit_code != 0, result.output
        assert INCOME_USD in result.output, result.output

    def test_the_revenue_survives_that_spelling_too(self, a_cash_sale):
        CliRunner().invoke(cli, ['import', str(a_cash_sale),
                                 NAMES_ONLY_THE_CASH_SALE,
                                 '--include-business-objects'])
        rows = _each_split_of(a_cash_sale, 'Cash sale, income baked in')

        income = [row for row in rows if row['account'] == INCOME_USD]
        assert len(income) == 1, rows
        assert income[0]['amount'] == -100

    def test_the_revenue_stays_on_the_income_account(self, a_cash_sale):
        CliRunner().invoke(cli, ['import', str(a_cash_sale),
                                 NAMES_THE_INCOME_SPLIT,
                                 '--include-business-objects'])
        rows = _each_split_of(a_cash_sale, 'Cash sale, income baked in')

        income = [row for row in rows if row['account'] == INCOME_USD]
        assert len(income) == 1, rows
        assert income[0]['amount'] == -100
        assert not income[0]['in_a_lot'], income
        assert not [row for row in rows if row['account'] == AR], rows


class TestASplitOfUnitsRatherThanMoney:
    """A payment moves money, and fund units are not money.

    `Assets:Fund` is a Mutual Fund account holding FUNDX, and a sale of units
    puts 1.000 of them against the 100.00 USD the bank received. Every guard
    on this path is about currency or sign, and this shape satisfies all of
    them: the sign is a receivable settlement's, the bank is in the invoice's
    own currency, no third split is in the entry, and the figure read off the
    bank is exactly what is owed.

    So what refuses it is the account it sits on, not any figure on the entry.
    Moving the split would set its account to the receivable and restate it in
    dollars — 1.000 FUNDX gone from the fund, the invoice reading paid, the
    entry balancing in USD, at exit 0, and the units simply overwritten.

    Refused on the **commodity**: FUNDX is not a currency, and that is what
    the message says. A Mutual Fund account fails the type list too, so either
    would turn this particular file away — but only the commodity is true of
    every account that holds units, which is what the next class measures.
    """

    @pytest.fixture
    def a_fund_sale(self, book):
        assert CliRunner().invoke(
            cli, ['import', str(book), A_FUND_SALE]).exit_code == 0
        return book

    def test_the_units_are_on_the_fund_before_the_link(self, a_fund_sale):
        """Stated rather than assumed: the refusals below turn on this shape."""
        rows = _each_split_of(a_fund_sale, 'Fund units sold')

        units = [row for row in rows if row['account'] == FUND]
        assert len(units) == 1, rows
        assert units[0]['amount'] == Fraction(-1), units
        assert units[0]['commodity'] == 'FUNDX', units

    def test_naming_the_fund_split_is_refused(self, a_fund_sale):
        """Naming the commodity, which is what is wrong with it.

        A Mutual Fund account fails the type list as well, so the message has
        two true things it could say; the one that helps names FUNDX.
        """
        result = CliRunner().invoke(cli, [
            'import', str(a_fund_sale), NAMES_THE_FUND_SPLIT,
            '--include-business-objects'])

        assert result.exit_code != 0, result.output
        assert FUND in result.output, result.output
        assert 'FUNDX, which is not a currency' in result.output, result.output

    def test_naming_only_the_transaction_is_refused_too(self, a_fund_sale):
        """`txn_guid:` alone finds the one side that is not the bank.

        Pinning the reason, not just the refusal: this branch reaches the
        restatement by a different route, and asserting only that the account
        is named would go on passing if some earlier guard began turning the
        file away for something else — leaving the branch this class exists
        for uncovered while the suite stayed green.
        """
        result = CliRunner().invoke(cli, [
            'import', str(a_fund_sale), NAMES_ONLY_THE_FUND_SALE,
            '--include-business-objects'])

        assert result.exit_code != 0, result.output
        assert FUND in result.output, result.output
        assert 'FUNDX, which is not a currency' in result.output, result.output

    def test_the_units_survive_naming_the_split(self, a_fund_sale):
        CliRunner().invoke(cli, ['import', str(a_fund_sale),
                                 NAMES_THE_FUND_SPLIT,
                                 '--include-business-objects'])
        rows = _each_split_of(a_fund_sale, 'Fund units sold')

        units = [row for row in rows if row['account'] == FUND]
        assert len(units) == 1, rows
        assert units[0]['amount'] == Fraction(-1), units
        assert units[0]['commodity'] == 'FUNDX', units
        assert not units[0]['in_a_lot'], units
        assert not [row for row in rows if row['account'] == AR], rows

    def test_the_units_survive_naming_only_the_transaction(self, a_fund_sale):
        CliRunner().invoke(cli, ['import', str(a_fund_sale),
                                 NAMES_ONLY_THE_FUND_SALE,
                                 '--include-business-objects'])
        rows = _each_split_of(a_fund_sale, 'Fund units sold')

        units = [row for row in rows if row['account'] == FUND]
        assert len(units) == 1, rows
        assert units[0]['amount'] == Fraction(-1), units
        assert units[0]['commodity'] == 'FUNDX', units
        assert not [row for row in rows if row['account'] == AR], rows


class TestUnitsHeldOnAnAccountOfAnOrdinaryType:
    """What decides it is the commodity, not the account's type.

    A GnuCash account's type and its commodity are set independently, and this
    tool will build the combination: `type: Asset` beside
    `commodity.namespace: "FUND"` is accepted by `import_account`, which calls
    `SetType` and `SetCommodity` without cross-checking them. Asset is one of
    the types a payment may move a split off.

    So a type check alone cannot deliver what it promises. `Assets:Units`
    holds FUNDY on an Asset account, and the restatement would write −100.00
    over the 1.000 units exactly as it would on a Mutual Fund account — the
    same corruption, one type across.

    Refusing by commodity closes both, and closes the ones nobody enumerated:
    a security on a Bank account, a book whose types were set by hand.
    """

    @pytest.fixture
    def units_on_an_asset(self, book):
        assert CliRunner().invoke(
            cli, ['import', str(book), UNITS_ON_AN_ASSET]).exit_code == 0
        return book

    def test_the_account_is_an_ordinary_asset_holding_units(
            self, units_on_an_asset):
        """Stated rather than assumed: the refusal below turns on this shape.

        If the type were Mutual Fund the previous class would already cover
        it, and this one would be measuring nothing.
        """
        repo = GnuCashRepository(str(units_on_an_asset))
        repo.open(mode=SessionMode.READ_ONLY)
        try:
            account = repo.book.get_root_account().lookup_by_name(
                'Assets').lookup_by_name('Units')
            assert account.GetType() == ACCT_TYPE_ASSET, account.GetType()
            assert account.GetCommodity().get_namespace() == 'FUND'
        finally:
            repo.close()

    def test_naming_those_units_is_refused(self, units_on_an_asset):
        """And refused for the commodity, which is the only true reason.

        The account-type wording would name `Assets:Units` too, so asserting
        the account alone cannot tell the two refusals apart — and the one
        that does not apply here sends a reader to change the account's type,
        which is not what is wrong with the file.
        """
        result = CliRunner().invoke(cli, [
            'import', str(units_on_an_asset), NAMES_UNITS_ON_AN_ASSET,
            '--include-business-objects'])

        assert result.exit_code != 0, result.output
        assert UNITS in result.output, result.output
        assert 'FUNDY, which is not a currency' in result.output, result.output
        assert 'nor an account money passes through' not in result.output, \
            result.output

    def test_the_units_survive_it(self, units_on_an_asset):
        CliRunner().invoke(cli, ['import', str(units_on_an_asset),
                                 NAMES_UNITS_ON_AN_ASSET,
                                 '--include-business-objects'])
        rows = _each_split_of(units_on_an_asset,
                              'Units sold from an asset account')

        units = [row for row in rows if row['account'] == UNITS]
        assert len(units) == 1, rows
        assert units[0]['amount'] == Fraction(-1), units
        assert units[0]['commodity'] == 'FUNDY', units
        assert not [row for row in rows if row['account'] == AR], rows


class TestUnitsOnTheBillSide:
    """A bill has a payable, and the refusal has to say so.

    The units refusal is not sign-dependent — a bill posts the other way
    round, so its settlement is positive on the payable, and +1.000 FUNDX
    satisfies that as readily as −1.000 satisfies an invoice's. The commodity
    is what refuses it on both sides.

    What differs is the wording. A bill's own account is the payable, and a
    message telling its reader the split cannot be moved "onto the
    receivable", or that it is not "this bill's own receivable", names an
    account their book has not got and sends them looking for it.
    """

    @pytest.fixture
    def a_bill_paid_in_units(self, tmp_path):
        path = tmp_path / 'bills.gnucash'
        runner = CliRunner()
        first = runner.invoke(cli, [
            'import', '--new', str(path), BILL_BOOK,
            '--include-business-objects', '--fx-rates', RATES])
        assert first.exit_code == 0, first.output
        second = runner.invoke(cli, ['import', str(path), BILL_PAID_IN_UNITS])
        assert second.exit_code == 0, second.output
        return path

    def test_it_is_refused_for_the_commodity(self, a_bill_paid_in_units):
        result = CliRunner().invoke(cli, [
            'import', str(a_bill_paid_in_units), BILL_NAMES_THE_FUND_SPLIT,
            '--include-business-objects'])

        assert result.exit_code != 0, result.output
        assert FUND in result.output, result.output
        assert 'FUNDX, which is not a currency' in result.output, result.output

    def test_the_refusal_names_the_payable_not_a_receivable(
            self, a_bill_paid_in_units):
        result = CliRunner().invoke(cli, [
            'import', str(a_bill_paid_in_units), BILL_NAMES_THE_FUND_SPLIT,
            '--include-business-objects'])

        assert result.exit_code != 0, result.output
        assert 'payable' in result.output, result.output
        assert 'receivable' not in result.output, result.output
        assert 'would place is on' in result.output, result.output

    def test_the_units_survive_it(self, a_bill_paid_in_units):
        CliRunner().invoke(cli, ['import', str(a_bill_paid_in_units),
                                 BILL_NAMES_THE_FUND_SPLIT,
                                 '--include-business-objects'])
        rows = _each_split_of(a_bill_paid_in_units,
                              'Bill settled in fund units')

        units = [row for row in rows if row['account'] == FUND]
        assert len(units) == 1, rows
        assert units[0]['amount'] == Fraction(1), units
        assert units[0]['commodity'] == 'FUNDX', units
        assert not [row for row in rows if row['account'] == AP], rows


class TestEveryRefusalABillReachesSaysPayable:
    """A bill has no receivable, and no refusal it reaches may say it has.

    The word is one a reader acts on: told their split cannot be moved "onto
    the receivable", someone with a bill goes looking through their chart of
    accounts for an account that is not there. Three refusals on this path
    say it, reached by three different files, and fixing the one a reviewer
    happens to name leaves the other two.

    So each arm gets its own scenario rather than one standing for the rest:

    - the account arm of the placeability refusal, reached by naming the
      expense split of a cash purchase — dollars, so the commodity arm has
      nothing to say and only the account's type refuses it;
    - the commodity arm, in `TestUnitsOnTheBillSide` above;
    - the swapped-sides refusal, reached by giving `account:` and
      `txn_split_guid:` each other's split. That one is caught by the sign,
      and the sign is precisely what a bill reverses, so it is a refusal
      bills reach *more* readily than invoices do.
    """

    @pytest.fixture
    def a_bill_and_a_cash_purchase(self, tmp_path):
        path = tmp_path / 'bills.gnucash'
        runner = CliRunner()
        first = runner.invoke(cli, [
            'import', '--new', str(path), BILL_BOOK,
            '--include-business-objects', '--fx-rates', RATES])
        assert first.exit_code == 0, first.output
        second = runner.invoke(cli, ['import', str(path), A_CASH_PURCHASE])
        assert second.exit_code == 0, second.output
        return path

    @pytest.fixture
    def a_bill_and_money_in_suspense(self, tmp_path):
        path = tmp_path / 'bills.gnucash'
        runner = CliRunner()
        first = runner.invoke(cli, [
            'import', '--new', str(path), BILL_BOOK,
            '--include-business-objects', '--fx-rates', RATES])
        assert first.exit_code == 0, first.output
        second = runner.invoke(cli, ['import', str(path), MONEY_OUT_IN_USD])
        assert second.exit_code == 0, second.output
        return path

    def test_the_account_arm_says_payable(self, a_bill_and_a_cash_purchase):
        result = CliRunner().invoke(cli, [
            'import', str(a_bill_and_a_cash_purchase),
            BILL_NAMES_THE_EXPENSE_SPLIT, '--include-business-objects'])

        assert result.exit_code != 0, result.output
        assert EXPENSES in result.output, result.output
        assert 'payable' in result.output, result.output
        assert 'receivable' not in result.output, result.output

    def test_the_expense_stays_where_it_is(self, a_bill_and_a_cash_purchase):
        CliRunner().invoke(cli, ['import', str(a_bill_and_a_cash_purchase),
                                 BILL_NAMES_THE_EXPENSE_SPLIT,
                                 '--include-business-objects'])
        rows = _each_split_of(a_bill_and_a_cash_purchase,
                              'Cash purchase, expense baked in')

        cost = [row for row in rows if row['account'] == EXPENSES]
        assert len(cost) == 1, rows
        assert cost[0]['amount'] == 100, cost
        assert not [row for row in rows if row['account'] == AP], rows

    def test_the_swapped_sides_refusal_says_payable(
            self, a_bill_and_money_in_suspense):
        result = CliRunner().invoke(cli, [
            'import', str(a_bill_and_money_in_suspense), BILL_SIDES_SWAPPED,
            '--include-business-objects'])

        assert result.exit_code != 0, result.output
        assert 'payable' in result.output, result.output
        assert 'receivable' not in result.output, result.output
        assert "the posting's sign reversed" in result.output, result.output

    def test_the_swapped_sides_entry_is_untouched(
            self, a_bill_and_money_in_suspense):
        CliRunner().invoke(cli, ['import', str(a_bill_and_money_in_suspense),
                                 BILL_SIDES_SWAPPED,
                                 '--include-business-objects'])
        rows = _each_split_of(a_bill_and_money_in_suspense,
                              'Money out, USD suspense')

        parked = [row for row in rows if row['account'] == SUSPENSE]
        assert len(parked) == 1, rows
        assert parked[0]['amount'] == 100, parked
        assert not parked[0]['in_a_lot'], parked
        assert not [row for row in rows if row['account'] == AP], rows

    def test_a_paymentsplit_on_the_bank_says_payable(
            self, a_bill_and_money_in_suspense):
        """The grouped spelling's own account check.

        Reached with a `Transaction` block rather than the keys, and it names
        the account the record posts to — so it is a fifth place the word can
        be wrong, on a path none of the others go down.
        """
        result = CliRunner().invoke(cli, [
            'import', str(a_bill_and_money_in_suspense),
            BILL_NAMES_THE_BANK_AS_A_PAYMENTSPLIT,
            '--include-business-objects'])

        assert result.exit_code != 0, result.output
        assert 'payable' in result.output, result.output
        assert 'receivable' not in result.output, result.output
        assert 'Every split a payment names' in result.output, result.output

    def test_a_block_claiming_more_than_the_bank_sent_says_payable(
            self, tmp_path):
        """The fall-short refusal, on the arm that read the bank.

        A bill owing 100.00 USD whose other side is CAD, paid 60.00: the
        named split's own figure stood in for the payable, so the settlement
        comes off the bank — and the explanation of *why* names the record's
        own account.
        """
        path = tmp_path / 'bills.gnucash'
        runner = CliRunner()
        first = runner.invoke(cli, [
            'import', '--new', str(path), BILL_BOOK,
            '--include-business-objects', '--fx-rates', RATES])
        assert first.exit_code == 0, first.output
        second = runner.invoke(cli, ['import', str(path),
                                     BILL_MONEY_OUT_FELL_SHORT])
        assert second.exit_code == 0, second.output

        result = runner.invoke(cli, [
            'import', str(path), BILL_CLAIMS_MORE_THAN_THE_BANK_SENT,
            '--include-business-objects'])

        assert result.exit_code != 0, result.output
        assert 'payable' in result.output, result.output
        assert 'receivable' not in result.output, result.output
        assert 'stood in for the payable' in result.output, result.output

    def test_a_bill_posted_to_a_plain_liability_still_says_payable(
            self, tmp_path):
        """The word comes from the owner, not from the account's type.

        Those usually agree, and where they do nothing distinguishes the two
        sources. GnuCash does not make them agree: `gncInvoicePostToAccount`
        validates nothing about the account it is given and this tool's own
        posting check compares currencies only, so `ap_account:` naming a
        plain `type: Liability` is a book that gets built.

        Read from the account's type, the refusal then says "this **bill**'s
        own **receivable**" — the two halves of one sentence disagreeing,
        because they were answered from two different places.
        """
        path = tmp_path / 'bills.gnucash'
        runner = CliRunner()
        first = runner.invoke(cli, [
            'import', '--new', str(path), BILL_BOOK,
            '--include-business-objects', '--fx-rates', RATES])
        assert first.exit_code == 0, first.output
        second = runner.invoke(cli, ['import', str(path),
                                     BILL_ON_A_PLAIN_LIABILITY])
        assert second.exit_code == 0, second.output

        # `--fx-rates` because BILL-USD-002 is posted by this run, and its
        # entry account is CAD: the posting converts, unlike the settlement.
        result = runner.invoke(cli, [
            'import', str(path), PLAIN_LIABILITY_NAMES_THE_FUND_SPLIT,
            '--include-business-objects', '--fx-rates', RATES])

        assert result.exit_code != 0, result.output
        assert 'bill' in result.output.lower(), result.output
        assert 'payable' in result.output, result.output
        assert 'receivable' not in result.output, result.output
        assert 'would place is on' in result.output, result.output

    def _bill_book_with(self, tmp_path, money):
        path = tmp_path / 'bills.gnucash'
        runner = CliRunner()
        first = runner.invoke(cli, [
            'import', '--new', str(path), BILL_BOOK,
            '--include-business-objects', '--fx-rates', RATES])
        assert first.exit_code == 0, first.output
        second = runner.invoke(cli, ['import', str(path), money])
        assert second.exit_code == 0, second.output
        return path, runner

    def test_two_parked_splits_this_cannot_divide_says_payable(self, tmp_path):
        """The grouped spelling naming two splits parked in another currency."""
        path, runner = self._bill_book_with(tmp_path,
                                            BILL_MONEY_OUT_TWO_CAD_SPLITS)

        result = runner.invoke(cli, [
            'import', str(path), BILL_NAMES_TWO_PARKED_CAD_SPLITS,
            '--include-business-objects'])

        assert result.exit_code != 0, result.output
        assert 'payable' in result.output, result.output
        assert 'receivable' not in result.output, result.output
        # The arm this is for, not another refusal that says "payable" too.
        assert 'places each at the figure it carries' in result.output, \
            result.output

    def test_a_converting_settlement_says_payable(self, tmp_path):
        """The bank in a currency the payable is not."""
        path, runner = self._bill_book_with(tmp_path,
                                            BILL_MONEY_OUT_OF_A_CAD_BANK)

        result = runner.invoke(cli, [
            'import', str(path), BILL_LINKED_FROM_A_CAD_BANK,
            '--include-business-objects'])

        assert result.exit_code != 0, result.output
        assert 'payable' in result.output, result.output
        assert 'receivable' not in result.output, result.output
        assert 'only the payer knows what at' in result.output, result.output

    def test_an_overpayment_this_cannot_carve_says_payable(self, tmp_path):
        """More paid out than the bill owes, from a parked split."""
        path, runner = self._bill_book_with(tmp_path,
                                            BILL_MONEY_OUT_OVERPAID)

        result = runner.invoke(cli, [
            'import', str(path), BILL_OVERPAYS_FROM_A_PARKED_SPLIT,
            '--include-business-objects'])

        assert result.exit_code != 0, result.output
        assert 'payable' in result.output, result.output
        assert 'receivable' not in result.output, result.output
        assert 'out of a number that means nothing' in result.output, \
            result.output


class TestTheTwoSidesOfTheLinkSwapped:
    """`account:` naming `Assets:Suspense USD` and `txn_split_guid:` the bank.

    One mistake, and every guard was symmetric in the two splits:
    `Assets:Suspense USD` is an asset, the bank split is not on a receivable so it reads as
    parked, it is in no lot, both sides are USD, and 100.00 arrived against
    100.00 owed. `refuse_when_the_amount_cannot_be_read` excludes *both* named
    splits when it looks for a third, so it is structurally incapable of
    catching this.

    What it produced at exit 0: the settlement read as the negation of what the
    *parked* split did, so the bank split was moved onto the receivable at
    +100.00. The deposit left `Assets:Bank:USD` entirely, the lot held the
    posting's +100 and this +100 so the invoice read as owing 200, and the
    entry still balanced.

    The sign is what is not symmetric. A settlement of a receivable is negative
    on it and of a payable positive, so read off the wrong split it comes out
    the wrong way round — which is the one thing that tells the arrival from
    the split being placed.
    """

    @pytest.fixture
    def parked_in_usd(self, book):
        assert CliRunner().invoke(
            cli, ['import', str(book), USD_PARKED]).exit_code == 0
        return book

    def test_it_is_refused(self, parked_in_usd):
        result = CliRunner().invoke(cli, [
            'import', str(parked_in_usd), SIDES_SWAPPED,
            '--include-business-objects'])

        assert result.exit_code != 0, result.output

    def test_the_deposit_stays_on_the_bank(self, parked_in_usd):
        """The damage it did: the bank's own split left the transaction."""
        CliRunner().invoke(cli, ['import', str(parked_in_usd), SIDES_SWAPPED,
                                 '--include-business-objects'])
        rows = _each_split_of(parked_in_usd, 'Money in, USD suspense')

        bank = [row for row in rows if row['account'] == BANK]
        assert len(bank) == 1, rows
        assert bank[0]['amount'] == 100
        assert not bank[0]['in_a_lot'], bank

    def test_the_parked_split_is_left_alone(self, parked_in_usd):
        CliRunner().invoke(cli, ['import', str(parked_in_usd), SIDES_SWAPPED,
                                 '--include-business-objects'])
        rows = _each_split_of(parked_in_usd, 'Money in, USD suspense')

        suspense = [row for row in rows if row['account'] == SUSPENSE]
        assert len(suspense) == 1, rows
        assert suspense[0]['amount'] == -100

    def test_the_same_swap_without_naming_the_split_is_refused(self,
                                                              parked_in_usd):
        """One line shorter, and it took a different road.

        The sign guard sits inside the restatement so no caller can reach that
        without it — but where the currencies agree this spelling never reaches
        the restatement at all. It takes the plain attach instead, which moved
        the bank's own deposit onto the receivable with no sign asked.
        """
        result = CliRunner().invoke(cli, [
            'import', str(parked_in_usd), SIDES_SWAPPED_NO_SPLIT,
            '--include-business-objects'])

        assert result.exit_code != 0, result.output

    def test_the_deposit_stays_on_the_bank_then_too(self, parked_in_usd):
        CliRunner().invoke(cli, ['import', str(parked_in_usd),
                                 SIDES_SWAPPED_NO_SPLIT,
                                 '--include-business-objects'])
        rows = _each_split_of(parked_in_usd, 'Money in, USD suspense')

        bank = [row for row in rows if row['account'] == BANK]
        assert len(bank) == 1, rows
        assert bank[0]['amount'] == 100
        assert not bank[0]['in_a_lot'], bank


class TestAGroupedBlockThatMisstatesItsAmount:
    """`amount:` on a grouped block is the sum of the splits it names.

    README says so, and the reason is that one file has to mean one thing in
    two books: where the transaction is held the named splits settle by their
    own figures, and where it is not the payment is entered from the block. A
    block naming 60 and 40 while stating `amount: 60` settles 100 in one book
    and enters 60 in the other.

    Nothing weighed it. A naming block is matched by guid, so
    `_single_payment_matches` — the only thing that reads `amount:` — never
    runs for it, and the grouped branch never looked at the stated figure.
    """

    @pytest.fixture
    def two_splits(self, book):
        assert CliRunner().invoke(
            cli, ['import', str(book), TWO_SPLITS]).exit_code == 0
        return book

    def test_it_is_refused(self, two_splits):
        result = CliRunner().invoke(cli, [
            'import', str(two_splits), CLAIMS_LESS_THAN_ITS_SPLITS,
            '--include-business-objects'])

        assert result.exit_code != 0, result.output

    def test_the_refusal_quotes_both_figures(self, two_splits):
        result = CliRunner().invoke(cli, [
            'import', str(two_splits), CLAIMS_LESS_THAN_ITS_SPLITS,
            '--include-business-objects'])

        assert '60.00' in result.output, result.output
        assert '100.00' in result.output, result.output

    def test_neither_split_is_attached(self, two_splits):
        CliRunner().invoke(cli, ['import', str(two_splits),
                                 CLAIMS_LESS_THAN_ITS_SPLITS,
                                 '--include-business-objects'])
        rows = _each_split_of(two_splits, 'Money in, two lines')

        receivables = [row for row in rows if row['account'] == AR]
        assert not any(row['in_a_lot'] for row in receivables), receivables


class TestAGroupedBlockClaimingMoreThanIsOwed:
    """Naming several splits claims them all in one step, and weighed nothing.

    The branch checked each named split for existence, account, lot and owner,
    then attached them all — without once comparing what they come to against
    what the record still owes. Two splits of 60.00 against a 100.00 invoice
    left the lot at −20: the invoice reading paid, 20.00 of the customer's
    money in no credit lot, exit 0. That is the state every other spelling
    refuses, and a residue cannot even be placed beside this one, `prepayment:`
    being refused there.
    """

    @pytest.fixture
    def too_much(self, book):
        assert CliRunner().invoke(
            cli, ['import', str(book), TWO_SPLITS_WORTH_MORE]).exit_code == 0
        return book

    def test_it_is_refused(self, too_much):
        result = CliRunner().invoke(cli, [
            'import', str(too_much), NAMES_TWO_SPLITS_WORTH_MORE,
            '--include-business-objects'])

        assert result.exit_code != 0, result.output

    def test_the_refusal_quotes_both_figures(self, too_much):
        result = CliRunner().invoke(cli, [
            'import', str(too_much), NAMES_TWO_SPLITS_WORTH_MORE,
            '--include-business-objects'])

        assert '120.00' in result.output, result.output
        assert '100.00' in result.output, result.output

    def test_neither_split_is_attached(self, too_much):
        CliRunner().invoke(cli, ['import', str(too_much),
                                 NAMES_TWO_SPLITS_WORTH_MORE,
                                 '--include-business-objects'])
        rows = _each_split_of(too_much, 'Money in, two lines, too much')

        receivables = [row for row in rows if row['account'] == AR]
        assert len(receivables) == 2, rows
        assert not any(row['in_a_lot'] for row in receivables), receivables


class TestAMemoOnAGroupedBlock:
    """A grouped block's `memo:`, both ways round.

    README's rule is one block, one settlement, one memo, and a grouped block
    is the shape that rule never met: it is one *payment* made of several
    settlements. Its memo is the payment's, so it belongs on every split the
    block names.

    Reading it was skipped entirely. `_correct_payment_memos` selects blocks by
    `child.metadata.get('txn_guid')`, and a grouped block writes
    `Transaction`/`PaymentSplit` *instead of* those two keys, so it `continue`d
    past. A grouped block's slots are then paired by split guid alone, so the
    comparison that would otherwise call the record changed never ran either:
    correct the wording in an exported ledger, re-import, and the answer was
    `unchanged` with the book keeping the old words. That is verbatim the
    failure `_correct_payment_memos` exists to prevent, back again for the one
    shape it does not select.

    Writing it has the mirror problem. One `memo:` cannot state two splits that
    word themselves differently — the first's wording would be reported as the
    payment's and the second's would be in the ledger nowhere — so where they
    differ the export writes a block per split, which is the escape a residue
    already takes.
    """

    @pytest.fixture
    def settled(self, book):
        runner = CliRunner()
        assert runner.invoke(
            cli, ['import', str(book), TWO_SPLITS]).exit_code == 0
        assert runner.invoke(cli, [
            'import', str(book), NAMES_TWO_SPLITS,
            '--include-business-objects']).exit_code == 0
        return book

    def test_an_edited_memo_reaches_every_split_the_block_names(self, settled):
        out = settled.parent / 'memo.txt'
        assert CliRunner().invoke(cli, [
            'export', str(settled), '--output', str(out),
            '--include-business-objects']).exit_code == 0
        text = out.read_text(encoding='utf-8')
        assert 'memo: ""' in text, text
        out.write_text(text.replace('memo: ""', 'memo: "Wire, corrected"', 1),
                       encoding='utf-8')

        again = CliRunner().invoke(cli, [
            'import', str(settled), str(out), '--include-business-objects'])

        assert again.exit_code == 0, again.output
        memos = _split_memos(settled, 'Money in, two lines')
        assert set(memos.values()) == {'Wire, corrected'}, memos

    def test_splits_wording_themselves_differently_are_written_apart(
            self, book):
        runner = CliRunner()
        assert runner.invoke(
            cli, ['import', str(book), TWO_SPLITS_TWO_MEMOS]).exit_code == 0
        assert runner.invoke(cli, [
            'import', str(book), NAMES_TWO_SPLITS,
            '--include-business-objects']).exit_code == 0

        out = book.parent / 'two_memos.txt'
        assert CliRunner().invoke(cli, [
            'export', str(book), '--output', str(out),
            '--include-business-objects']).exit_code == 0

        text = out.read_text(encoding='utf-8')
        block = text[text.index('invoice "INV-USD-001"'):]
        assert block.count('payment:') == 2, block
        assert 'First tranche' in block, block
        assert 'Second tranche' in block, block


class TestAParkedSplitInTheRecordsOwnCurrency:
    """The single-currency shape, which is the common one.

    Every other fixture here parks CAD against a USD invoice, because that is
    what the issue reported. But whether a split still has to be moved is
    decided by account *type*, not by currency, so a USD `Assets:Suspense USD`
    against a USD invoice takes the same branch — and on that branch the only overpayment guard skips itself
    wherever the parked split's currency matches the receivable's.

    That exemption is right about what it was written for: the guard protects a
    carve that reads the parked split's own figure, and where the currencies
    agree that figure is sound. It is wrong about everything else on the
    branch, because nothing else there weighs what arrived against what is
    owed. So 120.00 into `Assets:Suspense USD` settled a 100.00 invoice with
    the lot at −20 and the customer's 20.00 in no credit lot, at exit 0 — the
    state the cross-currency fixture beside it documents as the defect.

    The `txn_guid:`-alone spelling refuses it whatever the currencies, so the
    two spellings disagreed, and the overpayment refusal's own remedy is what
    sends a reader to this one.
    """

    @pytest.fixture
    def parked_in_usd(self, book):
        assert CliRunner().invoke(
            cli, ['import', str(book), USD_PARKED]).exit_code == 0
        return book

    @pytest.fixture
    def overpaid_in_usd(self, book):
        assert CliRunner().invoke(
            cli, ['import', str(book), USD_OVERPAID]).exit_code == 0
        return book

    def test_it_settles_the_invoice_when_the_figures_agree(self,
                                                           parked_in_usd):
        result = CliRunner().invoke(cli, [
            'import', str(parked_in_usd), USD_LINKED,
            '--include-business-objects'])

        assert result.exit_code == 0, result.output

    def test_the_split_moves_to_the_receivable(self, parked_in_usd):
        CliRunner().invoke(cli, ['import', str(parked_in_usd), USD_LINKED,
                                 '--include-business-objects'])
        rows = _each_split_of(parked_in_usd, 'Money in, USD suspense')

        assert not [row for row in rows if row['account'] == SUSPENSE], rows
        receivable = [row for row in rows if row['account'] == AR]
        assert len(receivable) == 1, rows
        assert receivable[0]['amount'] == -100
        assert receivable[0]['in_a_lot']

    def test_an_overpayment_is_refused_here_too(self, overpaid_in_usd):
        """The currencies agreeing says the parked figure can be trusted. It
        does not say the invoice is owed that much."""
        result = CliRunner().invoke(cli, [
            'import', str(overpaid_in_usd), USD_OVERPAID_LINKED,
            '--include-business-objects'])

        assert result.exit_code != 0, result.output

    def test_that_refusal_says_what_the_residue_is(self, overpaid_in_usd):
        result = CliRunner().invoke(cli, [
            'import', str(overpaid_in_usd), USD_OVERPAID_LINKED,
            '--include-business-objects'])

        assert 'prepayment' in result.output, result.output
        assert '20.00' in result.output, result.output

    def test_the_overpaid_entry_is_left_alone(self, overpaid_in_usd):
        """Refused before anything moves — the split is still in suspense."""
        CliRunner().invoke(cli, ['import', str(overpaid_in_usd),
                                 USD_OVERPAID_LINKED,
                                 '--include-business-objects'])
        rows = _each_split_of(overpaid_in_usd, 'Money in, USD suspense, too much')

        suspense = [row for row in rows if row['account'] == SUSPENSE]
        assert len(suspense) == 1, rows
        assert suspense[0]['amount'] == -120
        assert not suspense[0]['in_a_lot']


class TestABlockNamingOneSplit:
    """A `Transaction` naming exactly one `PaymentSplit`.

    `payment_slots` gives it a slot carrying that guid, as it does every slot
    of a block naming several, so it is paired by the split it names. Given a
    bare slot instead it was paired on date, amount and memo — and its
    `amount:` is the settlement's share while the figure it was weighed against
    is the bank side of the transaction, so it never matched its own payment.

    It is the path a reader reaches by writing the directive for a single
    settlement, which the format allows and no export emits, so it has to
    round-trip like any other block.
    """

    @pytest.fixture
    def part_paid(self, book):
        runner = CliRunner()
        assert runner.invoke(
            cli, ['import', str(book), TWO_SPLITS]).exit_code == 0
        first = runner.invoke(cli, [
            'import', str(book), NAMES_ONE_SPLIT,
            '--include-business-objects'])
        assert first.exit_code == 0, first.output
        return book

    def test_only_the_split_it_names_settles_the_invoice(self, part_paid):
        rows = _each_split_of(part_paid, 'Money in, two lines')

        lotted = [row for row in rows
                  if row['account'] == AR and row['in_a_lot']]
        assert [row['amount'] for row in lotted] == [-60], rows

    def test_reading_the_same_block_again_changes_nothing(self, part_paid):
        """The hand-written spelling, read twice — no export in between.

        A one-split naming block was given a `None` slot, so it was paired by
        date/amount/memo instead of by the guid it names. Its `amount:` is the
        settlement's share, 60.00 of a wire that moved 100.00, and the figure
        it was weighed against is the bank side of the transaction — so the
        block never matched its own payment, and every re-import of an unedited
        file unposted the invoice, destroyed the posting and rebuilt it. The
        export cannot produce this shape (it writes `txn_guid:` +
        `txn_split_guid:` for a single settlement), so nothing that
        round-trips an export was ever going to catch it.
        """
        again = CliRunner().invoke(cli, [
            'import', str(part_paid), NAMES_ONE_SPLIT,
            '--include-business-objects'])

        assert again.exit_code == 0, again.output
        assert 'invoice "INV-USD-001": unchanged' in again.output, again.output

    def test_reading_it_again_keeps_the_posting(self, part_paid):
        before = _posting_guid(part_paid)

        CliRunner().invoke(cli, ['import', str(part_paid), NAMES_ONE_SPLIT,
                                 '--include-business-objects'])

        assert _posting_guid(part_paid) == before

    def test_it_reads_back_unchanged(self, part_paid):
        """The `None` slot has to pair with the settlement the lot holds.

        Failing to, the invoice reads as changed by its own export — unposted,
        its posting destroyed, and rebuilt from splits its own unpost
        abandoned.
        """
        exported = part_paid.parent / 'one_split.txt'
        assert CliRunner().invoke(cli, [
            'export', str(part_paid), '--output', str(exported),
            '--include-business-objects']).exit_code == 0

        again = CliRunner().invoke(cli, [
            'import', str(part_paid), str(exported),
            '--include-business-objects'])

        assert again.exit_code == 0, again.output
        assert 'invoice "INV-USD-001": unchanged' in again.output, again.output


class TestASecondSettlingSplitOnATransactionAlreadySettlingIt:
    """Adding a split to a transaction that already settles this invoice.

    The bookkeeper finds the wire cleared 60 of the 100, adds the second
    receivable line, and rewrites the block to name both. That block classifies
    as an *addition* — one lot split against two slots, the first claimed and
    the second free — so no unpost runs and nothing marks the split already in
    the lot.

    It was refused outright. `refuse_to_move_a_split_out_of_its_lot` was scoped
    to "any lot" and is asked before the sibling refusal that has always
    exempted this record's own, so it spoke first and described the invoice's
    own settlement as somebody else's money — offering an `unapply-payment`
    that would be wrong to follow. The legitimate edit was unreachable.
    """

    @pytest.fixture
    def part_paid(self, book):
        runner = CliRunner()
        assert runner.invoke(
            cli, ['import', str(book), TWO_SPLITS]).exit_code == 0
        assert runner.invoke(cli, [
            'import', str(book), NAMES_ONE_SPLIT,
            '--include-business-objects']).exit_code == 0
        return book

    def test_naming_both_splits_is_accepted(self, part_paid):
        result = CliRunner().invoke(cli, [
            'import', str(part_paid), NAMES_TWO_SPLITS,
            '--include-business-objects'])

        assert result.exit_code == 0, result.output

    def test_the_invoice_own_settlement_is_not_called_another_record_s(
            self, part_paid):
        """The message is the defect, not just the exit code: it named this
        record's own money as settling something else."""
        result = CliRunner().invoke(cli, [
            'import', str(part_paid), NAMES_TWO_SPLITS,
            '--include-business-objects'])

        assert 'is in lot' not in result.output, result.output
        assert 'unapply-payment' not in result.output, result.output

    def test_both_splits_end_up_in_the_lot(self, part_paid):
        CliRunner().invoke(cli, ['import', str(part_paid), NAMES_TWO_SPLITS,
                                 '--include-business-objects'])
        rows = _each_split_of(part_paid, 'Money in, two lines')

        receivables = [row for row in rows if row['account'] == AR]
        assert len(receivables) == 2, rows
        assert sorted(row['amount'] for row in receivables) == [-60, -40]
        assert all(row['in_a_lot'] for row in receivables), receivables


class TestADirectiveWhereNothingWouldReadIt:
    """A `Transaction` or `PaymentSplit` written where nothing reads it.

    Both are matched on the stripped line, so before these refusals one written
    anywhere at all parsed into a directive no reader ever asks for — a line
    the file states and the run ignores, which is what every other unread line
    in this format is refused for.

    Each is asked before anything moves, so a refused file changes nothing.
    """

    def test_a_paymentsplit_not_under_a_transaction_is_refused(self, book):
        result = CliRunner().invoke(cli, [
            'import', str(book), PAYMENTSPLIT_ASTRAY,
            '--include-business-objects'])

        assert result.exit_code != 0, result.output
        assert 'PaymentSplit' in result.output, result.output
        assert 'Transaction' in result.output, result.output

    def test_two_transactions_under_one_payment_are_refused(self, book):
        """One payment is one transaction. Money that arrived twice is two
        payments, and the format has a spelling for that — a block each."""
        result = CliRunner().invoke(cli, [
            'import', str(book), NAMES_TWO_TRANSACTIONS,
            '--include-business-objects'])

        assert result.exit_code != 0, result.output
        assert 'Transaction' in result.output, result.output

    def test_a_transaction_outside_a_payment_block_is_refused(self, book):
        """`Transaction` names the transaction a *payment* refers to, so under
        `posted:` it means nothing."""
        result = CliRunner().invoke(cli, [
            'import', str(book), TRANSACTION_OUTSIDE_A_PAYMENT,
            '--include-business-objects'])

        assert result.exit_code != 0, result.output
        assert 'payment' in result.output.lower(), result.output

    def test_a_paymentsplit_outside_a_payment_block_is_refused(self, book):
        result = CliRunner().invoke(cli, [
            'import', str(book), PAYMENTSPLIT_OUTSIDE_A_PAYMENT,
            '--include-business-objects'])

        assert result.exit_code != 0, result.output
        assert 'PaymentSplit' in result.output, result.output

    def test_the_entry_is_left_alone_when_a_directive_is_refused(self, book):
        CliRunner().invoke(cli, ['import', str(book), TWO_SPLITS])

        CliRunner().invoke(cli, ['import', str(book), PAYMENTSPLIT_ASTRAY,
                                 '--include-business-objects'])
        rows = _each_split_of(book, 'Money in, two lines')

        receivables = [row for row in rows if row['account'] == AR]
        assert not any(row['in_a_lot'] for row in receivables), receivables

    def test_a_transaction_naming_no_splits_is_refused(self, book):
        """The directive's children are its splits — that is what it is for.

        Childless it says only what `txn_guid:` says, and is read by nobody:
        the block scores a bare slot, so the comparison pairs it on
        date/amount/memo and an otherwise-matching record reports `unchanged`
        before the override, or the note saying the keys went unread, ever
        runs.
        """
        assert CliRunner().invoke(
            cli, ['import', str(book), TWO_SPLITS]).exit_code == 0

        result = CliRunner().invoke(cli, [
            'import', str(book), A_TRANSACTION_WITH_NO_SPLITS,
            '--include-business-objects'])

        assert result.exit_code != 0, result.output
        assert 'PaymentSplit' in result.output, result.output

    def test_a_transaction_guid_that_will_not_parse_is_refused(self, book):
        """The early guard reads `txn_guid:` and `txn_split_guid:` out of the
        block's keys, and the directives carry theirs somewhere else — so the
        new spelling had no equivalent of it.

        Where the record otherwise matched, the parse error was swallowed, the
        block scored one bare slot, and the run said `unchanged` with the
        mistyped line read by nobody.
        """
        result = CliRunner().invoke(cli, [
            'import', str(self._already_settled(book)),
            GUID_THAT_WILL_NOT_PARSE, '--include-business-objects'])

        assert result.exit_code != 0, result.output
        assert 'not-a-guid' in result.output, result.output

    def test_the_posting_survives_a_guid_that_will_not_parse(self, book):
        """Asked before anything is unposted.

        The record has to be settled already for this to bite: the block then
        accounts for fewer settlements than the lot holds, so the run falls to
        the rebuild — `Unpost(False)` destroys the posting, and only after that
        does the guid fail to parse.
        """
        settled = self._already_settled(book)
        before = _posting_guid(settled)

        CliRunner().invoke(cli, ['import', str(settled),
                                 GUID_THAT_WILL_NOT_PARSE,
                                 '--include-business-objects'])

        assert _posting_guid(settled) == before

    @staticmethod
    def _already_settled(book):
        runner = CliRunner()
        assert runner.invoke(
            cli, ['import', str(book), TWO_SPLITS]).exit_code == 0
        assert runner.invoke(cli, [
            'import', str(book), NAMES_TWO_SPLITS,
            '--include-business-objects']).exit_code == 0
        return book

    def test_a_transaction_block_on_a_credit_payment_is_refused(self, book):
        """There is no grouped spelling of a credit block.

        `Transaction` / `PaymentSplit` is read by the branch that links a bank
        transaction; a `from_credit:` block goes to the one that spends an
        owner's credit, which knows only `txn_guid:` and `txn_split_guid:`. So
        the directive is read by nobody — while `payment_slots` counts a
        settlement per `PaymentSplit` whatever block it sits in, so the two
        halves of the run disagree about how many settlements the file
        accounts for.
        """
        result = CliRunner().invoke(cli, [
            'import', str(book), CREDIT_NAMING_A_TRANSACTION,
            '--include-business-objects'])

        assert result.exit_code != 0, result.output
        assert 'from_credit' in result.output, result.output
        # The directive's own refusal, not whatever the credit lookup would
        # have said about a split it could not find: this block is refused for
        # naming a `Transaction` at all, before any credit is looked for.
        assert 'no grouped spelling' in result.output, result.output


class TestThePrintedPageOfAGroupedPayment:
    """`print-invoice` writes the grouped block too, and its own way.

    The renderers format independently of the ledger export — they share
    `settlements_by_transaction` but not the block writer — and they are
    exactly where the duplicate-block defect lived: `print-bill` had no
    grouping at all, so a bill settled by one two-split transaction printed two
    blocks while the same book's export wrote one.

    A printed page is documented as re-importable, so the summed `amount:` and
    the indented children have to come out of the renderer as they come out of
    the export.
    """

    @pytest.fixture
    def settled(self, book):
        runner = CliRunner()
        assert runner.invoke(
            cli, ['import', str(book), TWO_SPLITS]).exit_code == 0
        assert runner.invoke(cli, [
            'import', str(book), NAMES_TWO_SPLITS,
            '--include-business-objects']).exit_code == 0
        return book

    def _printed(self, book):
        out = book.parent / 'printed.txt'
        result = CliRunner().invoke(cli, [
            'print-invoice', str(book), 'INV-USD-001',
            '--format', 'plaintext', '-o', str(out)])
        assert result.exit_code == 0, result.output
        return out.read_text(encoding='utf-8')

    def test_the_page_states_one_payment_of_the_whole_amount(self, settled):
        text = self._printed(settled)

        assert text.count('payment:') == 1, text
        assert 'amount: 100.00' in text, text
        assert 'amount: 60.00' not in text, text

    def test_the_page_names_both_splits_under_the_transaction(self, settled):
        text = self._printed(settled)

        assert text.count('PaymentSplit') == 2, text
        assert '708192a3b4c5d6e7f809122334455667' in text, text
        assert '8192a3b4c5d6e7f80912233445566778' in text, text

    def _in_a_fresh_book(self, settled, tmp_path):
        printed = settled.parent / 'printed.txt'
        self._printed(settled)
        elsewhere = tmp_path / 'elsewhere.gnucash'
        assert CliRunner().invoke(cli, [
            'import', '--new', str(elsewhere), BOOK,
            '--include-business-objects', '--fx-rates', RATES]).exit_code == 0
        first = CliRunner().invoke(cli, [
            'import', str(elsewhere), str(printed),
            '--include-business-objects'])
        assert first.exit_code == 0, first.output
        return elsewhere, printed

    def test_the_printed_page_reads_back_into_a_fresh_book(self, settled,
                                                           tmp_path):
        """The whole point of printing plaintext. A page carrying one split's
        share would enter that figure as the payment in a book that never held
        the transaction."""
        self._in_a_fresh_book(settled, tmp_path)

    def test_reading_it_into_that_book_twice_changes_nothing(self, settled,
                                                             tmp_path):
        """The guids on the page name the book it was printed from.

        In a fresh book they name nothing, so the payment is entered from the
        block — as **one** settlement, by `ApplyPayment`, and the import drops
        the named splits for exactly that reason. The comparison counted them
        anyway, being purely syntactic: two `PaymentSplit` children are two
        slots whatever the book holds. One settling split against two slots is
        a record judged changed by a file it already matches, so every run
        unposted it, destroyed the posting and rebuilt — for ever, on a file
        nobody had edited.
        """
        elsewhere, printed = self._in_a_fresh_book(settled, tmp_path)

        again = CliRunner().invoke(cli, [
            'import', str(elsewhere), str(printed),
            '--include-business-objects'])

        assert again.exit_code == 0, again.output
        assert 'invoice "INV-USD-001": unchanged' in again.output, again.output

    def test_the_posting_in_that_book_survives_the_second_read(self, settled,
                                                               tmp_path):
        elsewhere, printed = self._in_a_fresh_book(settled, tmp_path)
        before = _posting_guid(elsewhere)

        CliRunner().invoke(cli, ['import', str(elsewhere), str(printed),
                                 '--include-business-objects'])

        assert _posting_guid(elsewhere) == before
