"""Every cost basis is consumable, on its own side, and never below nothing.

The rules are the author's, set out in Q-054 after the reported case, under
"The author then set out what every cost basis is, and what may consume it".

Where a cost basis is kept decides nothing: an invoice's on its receivable,
a bill's on its payable, a deposit's on a bank, a bank's below zero, a card's
in credit. Two rules decide whether a disposal may draw on one:

- dollars held draw on a cost basis of dollars held, and dollars owed on one
  of dollars owed;
- no disposal takes a cost basis below nothing, whether it states the guid
  of the cost basis or `$pending$`.

The books are `usd_collected_off_an_invoice_and_still_held.txt`, whose only US
dollar cost basis is INV-USD-1's, 2,720.00 held, and
`usd_owed_on_a_card_that_paid_a_bill.txt`, whose only one is BILL-USD-1's,
1,000.00 owed; `a_usd_bank_below_zero_and_a_usd_card_above_zero_each_twice.txt`,
whose bank below zero holds two liability cost bases and whose card in credit
holds two asset cost bases; and
`a_usd_bank_at_minus_500_bought_1000_and_a_usd_card_in_credit_500_charged_1000.txt`,
whose bank and card each crossed zero, drawing the cost basis they held to
nothing and opening one on the other side. A split that makes an asset grow
opens an asset cost basis, and one that takes it below zero a liability cost
basis; a liability is the mirror. Each disposal is written in US dollars, as the pending fixtures beside them
are.
"""

import re

from click.testing import CliRunner

from tests.conftest import _run

FIXTURES = 'tests/fixtures/'
RATES = FIXTURES + 'usd_at_the_rates_the_statement_lines_records_were_posted_at.yaml'
COLLECTED = FIXTURES + 'usd_collected_off_an_invoice_and_still_held.txt'
OWED_ON_THE_CARD = FIXTURES + 'usd_owed_on_a_card_that_paid_a_bill.txt'


def _book(tmp_path, *ledgers):
    book = tmp_path / 'book.gnucash'
    for number, ledger in enumerate(ledgers):
        made = _run(CliRunner(), 'import', *(['--new'] if number == 0 else []), str(book),
                    ledger, '--include-business-objects', '--fx-rates', RATES)
        assert made.exit_code == 0 and 'Errors:       0' in made.output, made.output
    return book


def _ledger(tmp_path, name, text):
    path = tmp_path / f'{name}.txt'
    path.write_text(text)
    return str(path)


def _imported(book, ledger):
    done = _run(CliRunner(), 'import', str(book), ledger)
    assert done.exit_code == 0 and 'Errors:       0' in done.output, done.output
    return done


def _refused(book, ledger):
    done = _run(CliRunner(), 'import', str(book), ledger)
    assert 'Errors:       1' in done.output, done.output
    assert 'Transactions: 0' in done.output, done.output
    return done.output


def _listing(book):
    costs = _run(CliRunner(), 'fx-balances', str(book), '--verify-costs')
    assert costs.exit_code == 0 and 'warning' not in costs.output, costs.output
    integrity = _run(CliRunner(), '--verify-integrity', str(book))
    assert integrity.exit_code == 0, integrity.output
    return costs.output


def _guid_on(book, account):
    """The guid of the cost basis on the account whose name ends `account`."""
    for line in _listing(book).splitlines():
        if account in line:
            found = re.search(r'\b([0-9a-f]{32})\b', line)
            if found:
                return found.group(1)
    raise AssertionError(f'no cost basis on {account!r} in:\n{_listing(book)}')


def _invoice_guid(book):
    return _guid_on(book, 'Accounts Receivable USD')


def _bill_guid(book):
    return _guid_on(book, 'Accounts Payable USD')


def _sale(amount, cad, pick, day='2026-09-01'):
    """Dollars held sold out of Assets:Wise USD into the Canadian bank."""
    return (f'{day} * "Sell {amount} USD"\n'
            f'\tcurrency.mnemonic: "USD"\n'
            f'\tAssets:Wise USD -{amount} USD\n'
            f'\t\tcost_basis_split_guid: {pick}\n'
            f'\tAssets:Chequing {cad} CAD\n'
            f'\t\taccount.commodity.mnemonic: "CAD"\n'
            f'\t\tvalue: "{amount}"\n')


def _repayment(amount, cad, pick, day='2026-09-01'):
    """Dollars owed on Liabilities:Credit Card USD repaid from the Canadian bank."""
    return (f'{day} * "Repay {amount} USD"\n'
            f'\tcurrency.mnemonic: "USD"\n'
            f'\tLiabilities:Credit Card USD {amount} USD\n'
            f'\t\tcost_basis_split_guid: {pick}\n'
            f'\tAssets:Chequing -{cad} CAD\n'
            f'\t\taccount.commodity.mnemonic: "CAD"\n'
            f'\t\tvalue: "-{amount}"\n')


def _disposal(account, amount, other, cad, pick, day='2034-02-01'):
    """`amount` USD on `account` against `cad` CAD on `other`, stated in US dollars.

    `cad` carries its own sign, the opposite of `amount`'s.
    """
    value = amount[1:] if amount.startswith('-') else f'-{amount}'
    return (f'{day} * "{amount} USD on {account}"\n'
            f'\tcurrency.mnemonic: "USD"\n'
            f'\t{account} {amount} USD\n'
            f'\t\tcost_basis_split_guid: {pick}\n'
            f'\t{other} {cad} CAD\n'
            f'\t\taccount.commodity.mnemonic: "CAD"\n'
            f'\t\tvalue: "{value}"\n')


def _left(book, guid):
    """The cost basis balance `fx-balances` lists for the cost basis `guid`."""
    for line in _listing(book).splitlines():
        if guid in line:
            # ... BROUGHT IN, COST BASIS BALANCE, SIDE: the balance is the
            # figure before the side's word and its currency.
            return line.split()[-3]
    raise AssertionError(f'no cost basis {guid} in:\n{_listing(book)}')


PENDING = '$pending$'

# 1,000.00 USD more in the bank, at a cost of its own: 1,400.00 CAD.
DOLLARS_BOUGHT = ('2026-08-20 * "Dollars bought"\n'
                  '\tcurrency.mnemonic: "USD"\n'
                  '\tAssets:Wise USD 1000.00 USD\n'
                  '\tAssets:Chequing -1400.00 CAD\n'
                  '\t\taccount.commodity.mnemonic: "CAD"\n'
                  '\t\tvalue: "-1000.00"\n')

# 1,000.00 USD more in the bank, borrowed in a transaction stating no Canadian
# figure, so no cost basis stands for it.
DOLLARS_BORROWED = ('2026-07-01 open Liabilities\n'
                    '\ttype: "Liability"\n'
                    '\tplaceholder: #True\n'
                    '\tcommodity.namespace: "CURRENCY"\n'
                    '\tcommodity.mnemonic: "CAD"\n'
                    '2026-07-01 open Liabilities:Loan USD\n'
                    '\ttype: "Liability"\n'
                    '\tcommodity.namespace: "CURRENCY"\n'
                    '\tcommodity.mnemonic: "USD"\n'
                    '2026-08-20 * "Dollars borrowed"\n'
                    '\tcurrency.mnemonic: "USD"\n'
                    '\tAssets:Wise USD 1000.00 USD\n'
                    '\tLiabilities:Loan USD -1000.00 USD\n')

# 500.00 USD more owed on the card, at a cost of its own: 690.00 CAD drawn
# as a cash advance.
CARD_ADVANCE = ('2026-08-20 * "Cash advance"\n'
                '\tcurrency.mnemonic: "USD"\n'
                '\tLiabilities:Credit Card USD -500.00 USD\n'
                '\tAssets:Chequing 690.00 CAD\n'
                '\t\taccount.commodity.mnemonic: "CAD"\n'
                '\t\tvalue: "500.00"\n')

# 500.00 USD more owed on the card, charged in a transaction stating no
# Canadian figure, so no cost basis stands for it.
CARD_CHARGED_IN_DOLLARS = ('2026-07-01 open Assets:Wise USD\n'
                           '\ttype: "Bank"\n'
                           '\tcommodity.namespace: "CURRENCY"\n'
                           '\tcommodity.mnemonic: "USD"\n'
                           '2026-08-20 * "Card moved into dollars held"\n'
                           '\tcurrency.mnemonic: "USD"\n'
                           '\tLiabilities:Credit Card USD -500.00 USD\n'
                           '\tAssets:Wise USD 500.00 USD\n')


class TestTheInvoiceSCostBasisIsConsumedByItsGuid:
    def test_a_dollar_sold_stating_it_is_imported(self, tmp_path):
        book = _book(tmp_path, COLLECTED)
        guid = _invoice_guid(book)

        _imported(book, _ledger(tmp_path, 'sale', _sale('1.00', '1.40', f'"{guid}"')))

        listed = _listing(book)
        assert 'Total USD held in accounts: 2,719.00 USD' in listed, listed
        assert '1 disposal(s) pending' not in listed, listed

    def test_every_dollar_sold_stating_it_leaves_it_at_nothing(self, tmp_path):
        book = _book(tmp_path, COLLECTED)
        guid = _invoice_guid(book)

        _imported(book, _ledger(tmp_path, 'sale', _sale('2720.00', '3808.00', f'"{guid}"')))

        listed = _listing(book)
        assert 'Total USD held in accounts: 0.00 USD' in listed, listed


class TestTheBillSCostBasisIsConsumedByItsGuid:
    def test_part_of_the_card_repaid_stating_it_is_imported(self, tmp_path):
        book = _book(tmp_path, OWED_ON_THE_CARD)
        guid = _bill_guid(book)

        _imported(book, _ledger(tmp_path, 'repay', _repayment('100.00', '138.00', f'"{guid}"')))

        listed = _listing(book)
        assert 'Total USD owed on accounts: 900.00 USD' in listed, listed

    def test_the_whole_card_repaid_stating_it_leaves_it_at_nothing(self, tmp_path):
        book = _book(tmp_path, OWED_ON_THE_CARD)
        guid = _bill_guid(book)

        _imported(book, _ledger(tmp_path, 'repay', _repayment('1000.00', '1380.00', f'"{guid}"')))

        assert _left(book, guid) == '0.00'


class TestACostBasisIsNotConsumedFromTheOtherSide:
    def test_dollars_held_stating_the_bill_s_cost_basis_are_refused(self, tmp_path):
        book = _book(tmp_path, COLLECTED, OWED_ON_THE_CARD)
        guid = _bill_guid(book)

        refused = _refused(book, _ledger(tmp_path, 'sale', _sale('1.00', '1.40', f'"{guid}"')))

        assert (f"cost_basis_split_guid '{guid}' is a cost basis of USD the book "
                f"owed, but this split spends USD the book held") in refused, refused

    def test_dollars_owed_stating_the_invoice_s_cost_basis_are_refused(self, tmp_path):
        book = _book(tmp_path, COLLECTED, OWED_ON_THE_CARD)
        guid = _invoice_guid(book)

        refused = _refused(book, _ledger(tmp_path, 'repay',
                                         _repayment('100.00', '138.00', f'"{guid}"')))

        assert (f"cost_basis_split_guid '{guid}' is a cost basis of USD the book "
                f"held, but this split spends USD the book owed") in refused, refused


class TestACostBasisIsNotConsumedBelowNothingByItsGuid:
    def test_more_dollars_than_the_invoice_s_cost_basis_holds_are_refused(self, tmp_path):
        book = _book(tmp_path, COLLECTED, _ledger(tmp_path, 'bought', DOLLARS_BOUGHT))
        guid = _invoice_guid(book)

        refused = _refused(book, _ledger(tmp_path, 'sale',
                                         _sale('3000.00', '4200.00', f'"{guid}"')))

        assert (f'3000.00 USD against cost basis {guid} exceeds its cost basis '
                f'balance by 280.00 USD') in refused, refused

    def test_more_dollars_than_the_bill_s_cost_basis_owes_are_refused(self, tmp_path):
        book = _book(tmp_path, OWED_ON_THE_CARD, _ledger(tmp_path, 'advance', CARD_ADVANCE))
        guid = _bill_guid(book)

        refused = _refused(book, _ledger(tmp_path, 'repay',
                                         _repayment('1200.00', '1656.00', f'"{guid}"')))

        assert (f'1200.00 USD against cost basis {guid} exceeds its cost basis '
                f'balance by 200.00 USD') in refused, refused


class TestACostBasisIsNotConsumedBelowNothingByPending:
    def test_every_dollar_the_invoice_s_cost_basis_holds_is_pending(self, tmp_path):
        book = _book(tmp_path, COLLECTED)

        _imported(book, _ledger(tmp_path, 'sale', _sale('2720.00', '3808.00', PENDING)))

        listed = _listing(book)
        assert '1 disposal(s) pending their cost basis: 2,720.00 USD.' in listed, listed

    def test_more_than_the_held_cost_bases_hold_is_refused(self, tmp_path):
        book = _book(tmp_path, COLLECTED, _ledger(tmp_path, 'borrowed', DOLLARS_BORROWED))

        refused = _refused(book, _ledger(tmp_path, 'sale', _sale('3000.00', '4200.00', PENDING)))

        assert ('but the cost bases of USD the book held have 2720.00 USD left, '
                'and this split disposes of 3000.00 USD') in refused, refused

    def test_a_second_pending_sale_past_what_is_left_is_refused(self, tmp_path):
        book = _book(tmp_path, COLLECTED, _ledger(tmp_path, 'borrowed', DOLLARS_BORROWED))
        _imported(book, _ledger(tmp_path, 'first', _sale('2000.00', '2800.00', PENDING)))

        refused = _refused(book, _ledger(tmp_path, 'second',
                                         _sale('720.01', '1008.01', PENDING, day='2026-09-02')))

        assert ('but the cost bases of USD the book held have 720.00 USD left, '
                'and this split disposes of 720.01 USD') in refused, refused

    def test_every_dollar_the_bill_s_cost_basis_owes_is_pending(self, tmp_path):
        book = _book(tmp_path, OWED_ON_THE_CARD)

        _imported(book, _ledger(tmp_path, 'repay', _repayment('1000.00', '1380.00', PENDING)))

        listed = _listing(book)
        assert '1 disposal(s) pending their cost basis: 1,000.00 USD.' in listed, listed

    def test_more_than_the_owed_cost_bases_owe_is_refused(self, tmp_path):
        book = _book(tmp_path, OWED_ON_THE_CARD,
                     _ledger(tmp_path, 'charged', CARD_CHARGED_IN_DOLLARS))

        refused = _refused(book, _ledger(tmp_path, 'repay',
                                         _repayment('1200.00', '1656.00', PENDING)))

        assert ('but the cost bases of USD the book owed have 1000.00 USD left, '
                'and this split disposes of 1200.00 USD') in refused, refused


# Assets:USD Bank at -300.00 USD holding two liability cost bases, 100.00 at
# 1.30 and 200.00 at 1.35; Liabilities:USD Card at 300.00 USD in credit holding
# two asset cost bases, 200.00 at 1.35 and 100.00 at 1.40.
EACH_TWICE = FIXTURES + 'a_usd_bank_below_zero_and_a_usd_card_above_zero_each_twice.txt'
BANK_OWES_100 = '0d0d0000000000000000000000000001'
CARD_HOLDS_200 = '0d0d0000000000000000000000000004'
CARD_HOLDS_100 = '0d0d0000000000000000000000000005'

# Assets:USD Bank at -500.00 USD, then 1,000.00 USD bought and deposited into
# it: at 500.00 USD, holding an asset cost basis of 500.00 at 1.35, beside the
# liability cost basis of 500.00 at 1.30 the deposit drew to nothing.
# Liabilities:USD Card at 500.00 USD in credit, then 1,000.00 USD spent on it:
# owing 500.00 USD, holding a liability cost basis of 500.00 at 1.35, beside
# the asset cost basis of 500.00 at 1.30 the charge drew to nothing.
ACROSS_ZERO = (FIXTURES
               + 'a_usd_bank_at_minus_500_bought_1000_and_a_usd_card_in_credit_500_charged_1000.txt')
BANK_OWED_SPENT = '0e0e0000000000000000000000000001'
BANK_HOLDS_500 = '0e0e0000000000000000000000000002'
CARD_HELD_SPENT = '0e0e0000000000000000000000000003'
CARD_OWES_500 = '0e0e0000000000000000000000000004'


def _into_the_bank(amount, cad, pick):
    return _disposal('Assets:USD Bank', amount, 'Assets:CAD Bank', f'-{cad}', pick)


def _out_of_the_bank(amount, cad, pick):
    return _disposal('Assets:USD Bank', f'-{amount}', 'Assets:CAD Bank', cad, pick)


def _paid_onto_the_card(amount, cad, pick):
    return _disposal('Liabilities:USD Card', amount, 'Assets:CAD Bank', f'-{cad}', pick)


def _charged_to_the_card(amount, cad, pick):
    return _disposal('Liabilities:USD Card', f'-{amount}', 'Expenses:Travel', cad, pick)


class TestABankBelowZeroHasItsLiabilityCostBasesConsumed:
    def test_a_deposit_stating_one_draws_it_down(self, tmp_path):
        book = _book(tmp_path, EACH_TWICE)

        _imported(book, _ledger(tmp_path, 'in', _into_the_bank('50.00', '70.00',
                                                               f'"{BANK_OWES_100}"')))

        assert _left(book, BANK_OWES_100) == '50.00'
        assert 'Total USD owed on accounts: 250.00 USD' in _listing(book)

    def test_a_deposit_pending_its_cost_basis_is_counted_pending(self, tmp_path):
        book = _book(tmp_path, EACH_TWICE)

        _imported(book, _ledger(tmp_path, 'in', _into_the_bank('50.00', '70.00', PENDING)))

        listed = _listing(book)
        assert '1 disposal(s) pending their cost basis: 50.00 USD.' in listed, listed

    def test_a_deposit_stating_the_card_s_asset_cost_basis_is_refused(self, tmp_path):
        book = _book(tmp_path, EACH_TWICE)

        refused = _refused(book, _ledger(tmp_path, 'in', _into_the_bank(
            '50.00', '70.00', f'"{CARD_HOLDS_200}"')))

        assert (f"cost_basis_split_guid '{CARD_HOLDS_200}' is a cost basis of USD the "
                f"book held, but this split spends USD the book owed") in refused, refused

    def test_a_deposit_past_what_one_has_left_is_refused(self, tmp_path):
        book = _book(tmp_path, EACH_TWICE)

        refused = _refused(book, _ledger(tmp_path, 'in', _into_the_bank(
            '150.00', '210.00', f'"{BANK_OWES_100}"')))

        assert (f'150.00 USD against cost basis {BANK_OWES_100} exceeds its cost basis '
                f'balance by 50.00 USD') in refused, refused


class TestACardAboveZeroHasItsAssetCostBasesConsumed:
    def test_a_charge_stating_one_draws_it_down(self, tmp_path):
        book = _book(tmp_path, EACH_TWICE)

        _imported(book, _ledger(tmp_path, 'charge', _charged_to_the_card(
            '50.00', '70.00', f'"{CARD_HOLDS_200}"')))

        assert _left(book, CARD_HOLDS_200) == '150.00'
        assert 'Total USD held in accounts: 250.00 USD' in _listing(book)

    def test_a_charge_pending_its_cost_basis_is_counted_pending(self, tmp_path):
        book = _book(tmp_path, EACH_TWICE)

        _imported(book, _ledger(tmp_path, 'charge', _charged_to_the_card(
            '50.00', '70.00', PENDING)))

        listed = _listing(book)
        assert '1 disposal(s) pending their cost basis: 50.00 USD.' in listed, listed

    def test_a_charge_stating_the_bank_s_liability_cost_basis_is_refused(self, tmp_path):
        book = _book(tmp_path, EACH_TWICE)

        refused = _refused(book, _ledger(tmp_path, 'charge', _charged_to_the_card(
            '50.00', '70.00', f'"{BANK_OWES_100}"')))

        assert (f"cost_basis_split_guid '{BANK_OWES_100}' is a cost basis of USD the "
                f"book owed, but this split spends USD the book held") in refused, refused

    def test_a_charge_past_what_one_has_left_is_refused(self, tmp_path):
        book = _book(tmp_path, EACH_TWICE)

        refused = _refused(book, _ledger(tmp_path, 'charge', _charged_to_the_card(
            '150.00', '210.00', f'"{CARD_HOLDS_100}"')))

        assert (f'150.00 USD against cost basis {CARD_HOLDS_100} exceeds its cost basis '
                f'balance by 50.00 USD') in refused, refused


class TestCrossingZeroConsumesOneCostBasisAndOpensAnother:
    def test_the_deposit_draws_the_liability_to_nothing_and_opens_500_held(self, tmp_path):
        book = _book(tmp_path, ACROSS_ZERO)

        listed = _listing(book)
        assert _left(book, BANK_OWED_SPENT) == '0.00'
        assert re.search(rf'{BANK_HOLDS_500}\s+Assets:USD Bank\s+1\.35 CAD/USD\s+'
                         r'500\.00 USD\s+500\.00 USD', listed), listed
        assert 'Assets:USD Bank              500.00 USD' in listed, listed

    def test_the_charge_draws_the_asset_to_nothing_and_opens_500_owed(self, tmp_path):
        book = _book(tmp_path, ACROSS_ZERO)

        listed = _listing(book)
        assert _left(book, CARD_HELD_SPENT) == '0.00'
        assert re.search(rf'{CARD_OWES_500}\s+Liabilities:USD Card\s+1\.35 CAD/USD\s+'
                         r'500\.00 USD\s+500\.00 USD', listed), listed
        assert 'Liabilities:USD Card        -500.00 USD' in listed, listed


class TestCrossingZeroPendingItsCostBasis:
    """The bank at −100.00 and the card 200.00 in credit, each crossing zero with `$pending$`.

    What the split consumes is pending against the cost basis on the other
    side of zero, and what it brings past zero opens a cost basis of its own.
    """

    def test_a_deposit_crossing_the_bank_below_zero_is_imported(self, tmp_path):
        book = _book(tmp_path, EACH_TWICE)

        _imported(book, _ledger(tmp_path, 'in', _into_the_bank('400.00', '560.00', PENDING)))

        listed = _listing(book)
        assert '1 disposal(s) pending their cost basis: 300.00 USD.' in listed, listed
        assert 'Assets:USD Bank              100.00 USD' in listed, listed

    def test_a_charge_crossing_the_card_in_credit_is_imported(self, tmp_path):
        book = _book(tmp_path, EACH_TWICE)

        _imported(book, _ledger(tmp_path, 'charge', _charged_to_the_card(
            '400.00', '560.00', PENDING)))

        listed = _listing(book)
        assert '1 disposal(s) pending their cost basis: 300.00 USD.' in listed, listed
        assert 'Liabilities:USD Card        -100.00 USD' in listed, listed


class TestWhatCrossingZeroOpenedIsConsumed:
    def test_the_bank_s_asset_cost_basis_is_drawn_down_by_a_sale(self, tmp_path):
        book = _book(tmp_path, ACROSS_ZERO)

        _imported(book, _ledger(tmp_path, 'out', _out_of_the_bank(
            '100.00', '140.00', f'"{BANK_HOLDS_500}"')))

        assert _left(book, BANK_HOLDS_500) == '400.00'
        assert 'Total USD held in accounts: 400.00 USD' in _listing(book)

    def test_the_card_s_liability_cost_basis_is_drawn_down_by_a_payment(self, tmp_path):
        book = _book(tmp_path, ACROSS_ZERO)

        _imported(book, _ledger(tmp_path, 'pay', _paid_onto_the_card(
            '100.00', '140.00', f'"{CARD_OWES_500}"')))

        assert _left(book, CARD_OWES_500) == '400.00'
        assert 'Total USD owed on accounts: 400.00 USD' in _listing(book)

    def test_a_sale_pending_its_cost_basis_is_counted_pending(self, tmp_path):
        book = _book(tmp_path, ACROSS_ZERO)

        _imported(book, _ledger(tmp_path, 'out', _out_of_the_bank('100.00', '140.00', PENDING)))

        listed = _listing(book)
        assert '1 disposal(s) pending their cost basis: 100.00 USD.' in listed, listed

    def test_a_payment_pending_its_cost_basis_is_counted_pending(self, tmp_path):
        book = _book(tmp_path, ACROSS_ZERO)

        _imported(book, _ledger(tmp_path, 'pay', _paid_onto_the_card(
            '100.00', '140.00', PENDING)))

        listed = _listing(book)
        assert '1 disposal(s) pending their cost basis: 100.00 USD.' in listed, listed

    def test_a_sale_stating_the_card_s_spent_asset_cost_basis_is_refused(self, tmp_path):
        book = _book(tmp_path, ACROSS_ZERO)

        refused = _refused(book, _ledger(tmp_path, 'out', _out_of_the_bank(
            '100.00', '140.00', f'"{CARD_HELD_SPENT}"')))

        assert (f'100.00 USD against cost basis {CARD_HELD_SPENT} exceeds its cost basis '
                f'balance by 100.00 USD') in refused, refused

    def test_a_payment_stating_the_bank_s_spent_liability_cost_basis_is_refused(self, tmp_path):
        book = _book(tmp_path, ACROSS_ZERO)

        refused = _refused(book, _ledger(tmp_path, 'pay', _paid_onto_the_card(
            '100.00', '140.00', f'"{BANK_OWED_SPENT}"')))

        assert (f'100.00 USD against cost basis {BANK_OWED_SPENT} exceeds its cost basis '
                f'balance by 100.00 USD') in refused, refused
