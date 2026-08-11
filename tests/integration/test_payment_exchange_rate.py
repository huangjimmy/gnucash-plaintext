"""Q-035: a payment that crosses a currency boundary settles at the rate given.

`share_price:` on a payment block carries the meaning it has on any split — one
unit of the record's currency is worth this many units of the account the money
lands in. It is required when the two currencies differ and rejected when they
match. Every case is mirrored on the bill side, where the money moves the other
way.
"""

import re
from pathlib import Path

from click.testing import CliRunner

from cli.main import cli
from services.plaintext_parser import RESIDUAL_AMOUNT as RESIDUAL

RATES = 'tests/fixtures/fx_rates_usd_dated.yaml'


def _import(runner, book, fixture):
    return runner.invoke(cli, ['import', '--new', str(book), fixture,
                               '--include-business-objects', '--fx-rates', RATES])


def _export_text(runner, book, out):
    result = runner.invoke(cli, ['export', str(book), str(out),
                                 '--include-business-objects'])
    assert result.exit_code == 0, result.output
    return out.read_text()


def _variant(tmp_path, fixture, old, new, name='variant.txt'):
    """A fixture with one line changed — for the near-identical error cases."""
    path = tmp_path / name
    path.write_text(Path(fixture).read_text().replace(old, new))
    return str(path)


def test_invoice_paid_into_a_cad_bank_credits_what_the_bank_gave(tmp_path):
    """The fixture states `settled_amount: 137.00` — what the bank statement
    shows — and the rate is derived from it."""
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    result = _import(runner, book,
                     'tests/fixtures/fx_invoice_usd_paid_from_cad_bank.txt')
    assert result.exit_code == 0, result.output

    exported = _export_text(runner, book, tmp_path / 'out.txt')
    assert 'Assets:Bank 137.00 CAD' in exported, exported
    # The invoice reads as paid rather than orphaning the payment.
    assert 'payment: none' not in exported, exported


def test_the_rate_may_be_stated_instead_of_the_settled_amount(tmp_path):
    """`share_price: "1.37"` is the same payment written the other way."""
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    fixture = _variant(tmp_path,
                       'tests/fixtures/fx_invoice_usd_paid_from_cad_bank.txt',
                       'settled_amount: 137.00', 'share_price: "1.37"')
    result = _import(runner, book, fixture)
    assert result.exit_code == 0, result.output

    exported = _export_text(runner, book, tmp_path / 'out.txt')
    assert 'Assets:Bank 137.00 CAD' in exported, exported
    assert 'Income:FX Gain 3.00 CAD' in exported, exported


def test_a_settled_amount_and_a_rate_that_disagree_are_refused(tmp_path):
    runner = CliRunner()
    fixture = _variant(
        tmp_path, 'tests/fixtures/fx_invoice_usd_paid_from_cad_bank.txt',
        'settled_amount: 137.00',
        'settled_amount: 137.00\n\t\tshare_price: "1.39"')
    result = _import(runner, tmp_path / 'book.gnucash', fixture)
    assert result.exit_code != 0, result.output
    message = result.output + str(result.exception)
    assert 'must agree' in message, message


def test_a_settled_amount_on_a_same_currency_payment_is_refused(tmp_path):
    runner = CliRunner()
    fixture = _variant(
        tmp_path, 'tests/fixtures/fx_invoice_usd_paid_from_usd_bank.txt',
        'memo: "Payment for INV-USD-USDBANK"',
        'settled_amount: 100.00\n\t\tmemo: "Payment for INV-USD-USDBANK"')
    result = _import(runner, tmp_path / 'book.gnucash', fixture)
    assert result.exit_code != 0, result.output
    message = result.output + str(result.exception)
    assert 'nothing to convert' in message, message


def test_invoice_payment_across_currencies_requires_a_rate(tmp_path):
    runner = CliRunner()
    result = _import(runner, tmp_path / 'book.gnucash',
                     'tests/fixtures/fx_invoice_usd_paid_from_cad_bank_no_rate.txt')
    assert result.exit_code != 0, result.output
    message = result.output + str(result.exception)
    assert 'share_price' in message, message
    assert 'USD' in message and 'CAD' in message, message


def test_invoice_payment_in_the_same_currency_rejects_a_rate(tmp_path):
    runner = CliRunner()
    result = _import(runner, tmp_path / 'book.gnucash',
                     'tests/fixtures/fx_invoice_usd_paid_from_usd_bank_with_rate.txt')
    assert result.exit_code != 0, result.output
    message = result.output + str(result.exception)
    assert 'share_price' in message, message


def test_bill_paid_out_of_a_cad_bank_takes_what_the_bank_gave(tmp_path):
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    result = _import(runner, book,
                     'tests/fixtures/fx_bill_usd_paid_from_cad_bank.txt')
    assert result.exit_code == 0, result.output

    exported = _export_text(runner, book, tmp_path / 'out.txt')
    assert 'Assets:Bank -137.00 CAD' in exported, exported
    assert 'payment: none' not in exported, exported


def test_bill_payment_across_currencies_requires_a_rate(tmp_path):
    runner = CliRunner()
    result = _import(runner, tmp_path / 'book.gnucash',
                     'tests/fixtures/fx_bill_usd_paid_from_cad_bank_no_rate.txt')
    assert result.exit_code != 0, result.output
    message = result.output + str(result.exception)
    assert 'share_price' in message, message


def test_bill_payment_in_the_same_currency_rejects_a_rate(tmp_path):
    runner = CliRunner()
    result = _import(runner, tmp_path / 'book.gnucash',
                     'tests/fixtures/fx_bill_usd_paid_from_usd_bank_with_rate.txt')
    assert result.exit_code != 0, result.output
    message = result.output + str(result.exception)
    assert 'share_price' in message, message


def _balances(runner, book):
    result = runner.invoke(cli, ['fx-balances', str(book)])
    assert result.exit_code == 0, result.output
    return result.output


def test_paying_a_usd_invoice_at_another_rate_realizes_the_difference(tmp_path):
    """Revenue was recognised at 1.40 and 137.00 CAD arrived: the 3.00 CAD
    shortfall is realized on the settlement date, not left unexplained.

    The A/R side of the payment is valued at the cost basis it settles
    (140.00 CAD), so the entry balances only with the loss booked.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    result = _import(runner, book,
                     'tests/fixtures/fx_invoice_usd_paid_from_cad_bank.txt')
    assert result.exit_code == 0, result.output

    exported = _export_text(runner, book, tmp_path / 'out.txt')
    assert 'Assets:Bank 137.00 CAD' in exported, exported
    assert 'Income:FX Gain 3.00 CAD' in exported, exported          # debit: a loss
    assert 'value: "-140.00"' in exported, exported
    assert 'cost_basis_split_guid:' in exported, exported

    # Settling into CAD consumed the basis: that USD is gone.
    assert 'Total USD basis balance: 0.00 USD' in _balances(runner, book)


def test_paying_a_usd_bill_at_another_rate_realizes_the_difference(tmp_path):
    """The mirror: a payable booked at 140.00 CAD settled for 137.00 CAD of
    cash is a 3.00 CAD gain."""
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    result = _import(runner, book,
                     'tests/fixtures/fx_bill_usd_paid_from_cad_bank.txt')
    assert result.exit_code == 0, result.output

    exported = _export_text(runner, book, tmp_path / 'out.txt')
    assert 'Assets:Bank -137.00 CAD' in exported, exported
    assert 'Income:FX Gain -3.00 CAD' in exported, exported         # credit: a gain
    assert 'value: "140.00"' in exported, exported
    assert 'Total USD basis balance: 0.00 USD' in _balances(runner, book)


def test_a_realizing_payment_must_say_where_the_gain_belongs(tmp_path):
    """No account is configured anywhere: the payment block says it with a
    split, and without one the settlement is refused."""
    runner = CliRunner()
    result = _import(
        runner, tmp_path / 'book.gnucash',
        'tests/fixtures/fx_invoice_usd_paid_from_cad_bank_no_gain_split.txt')
    assert result.exit_code != 0, result.output
    message = str(result.exception) + result.output.split('.txt')[-1]
    assert 'add a split to the payment block' in message, message
    assert '$residual$' in message, message
    assert '3.00' in message, message


def test_a_payment_carrying_anything_but_the_residual_is_refused(tmp_path):
    """The block places one figure: the difference the settlement realized.

    That difference is the only thing in the entry nobody moved — it is what
    the rate did. A bank fee moved money: the bank debited the account on a
    date of its own, and it arrives in a bank import like any other
    transaction. Writing it here instead makes it part of the settlement, and
    a fee taken out of what the conversion produced silently becomes a worse
    rate: 274.00 CAD made and 2.00 kept prices the currency at 272/200, so a
    dollar of bank charge lands in the cost basis of whatever credit the
    payment leaves — where every later sale of that currency is measured
    against it.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    fixture = _variant(
        tmp_path, 'tests/fixtures/fx_invoice_usd_paid_from_cad_bank.txt',
        '\t\tIncome:FX Gain $residual$ CAD',
        '\t\tExpenses:Bank Fees 2.00 CAD\n\t\tIncome:FX Gain $residual$ CAD')
    fixture_text = Path(fixture).read_text().replace(
        '2026-01-01 open Income\n',
        '2026-01-01 open Expenses\n\ttype: Expense\n'
        '\tcommodity.namespace: "CURRENCY"\n\tcommodity.mnemonic: "CAD"\n'
        '2026-01-01 open Expenses:Bank Fees\n\ttype: Expense\n'
        '\tcommodity.namespace: "CURRENCY"\n\tcommodity.mnemonic: "CAD"\n'
        '2026-01-01 open Income\n')
    Path(fixture).write_text(fixture_text)

    result = _import(runner, book, fixture)
    assert result.exit_code != 0, result.output
    # The message names the line it will not place — whatever that line is.
    # Nothing here decides what an account *means*: an account is not a charge
    # because of its name, and the only test applied is whether the line is
    # the residual.
    assert "'Expenses:Bank Fees'" in result.output, result.output
    assert f'is not {RESIDUAL}' in result.output, result.output
    assert 'its own transaction' in result.output, result.output


def test_two_residual_splits_on_one_payment_are_refused(tmp_path):
    runner = CliRunner()
    fixture = _variant(
        tmp_path, 'tests/fixtures/fx_invoice_usd_paid_from_cad_bank.txt',
        '\t\tIncome:FX Gain $residual$ CAD',
        '\t\tIncome:FX Gain $residual$ CAD\n\t\tIncome:Sales $residual$ CAD')
    result = _import(runner, tmp_path / 'book.gnucash', fixture)
    assert result.exit_code != 0, result.output
    message = str(result.exception) + result.output.split('.txt')[-1]
    assert 'only one can take the residual' in message, message


def test_a_gain_split_in_another_currency_is_refused(tmp_path):
    runner = CliRunner()
    fixture = _variant(
        tmp_path, 'tests/fixtures/fx_invoice_usd_paid_from_cad_bank.txt',
        '\t\tIncome:FX Gain $residual$ CAD',
        '\t\tAssets:Bank:USD $residual$ USD')
    result = _import(runner, tmp_path / 'book.gnucash', fixture)
    assert result.exit_code != 0, result.output
    message = str(result.exception) + result.output.split('.txt')[-1]
    assert 'is in USD but the settlement is stated in CAD' in message, message


def test_settling_in_the_records_own_currency_realizes_nothing(tmp_path):
    """A USD invoice paid into a USD bank moves money at the cost it already
    carries. The A/R split stays the basis for that 100 USD, and the bank split
    does not become a second one — the book holds 100 USD, not 200."""
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    result = _import(runner, book,
                     'tests/fixtures/fx_invoice_usd_paid_from_usd_bank.txt')
    assert result.exit_code == 0, result.output

    listing = _balances(runner, book)
    assert listing.count('100.00 USD     100.00 USD') == 1, listing
    assert 'Total USD basis balance: 100.00 USD' in listing, listing
    assert 'Assets:Bank:USD' not in listing, listing

    # No gain split anywhere in the payment entry — the fixture declares an
    # FX account, and it stays unused.
    exported = _export_text(runner, book, tmp_path / 'out.txt')
    payment_entry = exported.split('2026-02-25 * ')[-1]
    assert 'FX Gain' not in payment_entry, payment_entry


def test_a_converting_settlement_can_be_written_out_as_a_transaction(tmp_path):
    """The alternative to letting the engine build the entry: write the whole
    entry — both amounts, the A/R side at the invoice's cost, `$residual$` for
    the gain — and claim it with `txn_guid:` / `txn_split_guid:`.

    Nothing is derived here, so the payment block needs no rate at all, and the
    invoice still ends up paid with its basis consumed.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    result = runner.invoke(cli, ['import', '--new', str(book),
                                 'tests/fixtures/fx_usd_invoice_cad_income.txt',
                                 '--include-business-objects', '--fx-rates', RATES])
    assert result.exit_code == 0, result.output

    listing = _balances(runner, book)
    basis = re.search(r'\b([0-9a-f]{32})\b', listing).group(1)

    settlement = tmp_path / 'settlement.txt'
    settlement.write_text(
        Path('tests/fixtures/fx_settlement_txn_for_invoice.txt').read_text()
        .replace('{basis_guid}', basis))
    result = runner.invoke(cli, ['import', str(book), str(settlement)])
    assert result.exit_code == 0, result.output
    assert 'error:' not in result.output, result.output

    result = runner.invoke(cli, ['import', str(book),
                                 'tests/fixtures/fx_invoice_usd_retarget_payment.txt',
                                 '--include-business-objects'])
    assert result.exit_code == 0, result.output

    exported = _export_text(runner, book, tmp_path / 'out.txt')
    assert 'Assets:Bank 137.00 CAD' in exported, exported
    assert 'Income:FX Gain 3.00 CAD' in exported, exported
    assert 'payment: none' not in exported, exported
    assert 'Total USD basis balance: 0.00 USD' in _balances(runner, book)


def test_a_converting_payment_survives_export_and_re_import(tmp_path):
    """A book with a realized settlement exports and re-imports intact.

    The export states the payment as a retarget of the transaction it already
    wrote out, so the fresh book inherits the FX split and the values verbatim
    and needs no rate to rebuild them.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    assert _import(runner, book,
                   'tests/fixtures/fx_invoice_usd_paid_from_cad_bank.txt'
                   ).exit_code == 0

    exported = tmp_path / 'out.txt'
    text = _export_text(runner, book, exported)
    assert 'txn_split_guid:' in text, text

    fresh = tmp_path / 'fresh.gnucash'
    result = runner.invoke(cli, ['import', '--new', str(fresh), str(exported),
                                 '--include-business-objects'])
    assert result.exit_code == 0, result.output
    # Per-transaction failures print as `error: …`; the summary's `Errors:`
    # count line is not one.
    assert 'error:' not in result.output, result.output
    assert 'Errors:       0' in result.output, result.output

    round_tripped = _export_text(runner, fresh, tmp_path / 'again.txt')
    assert 'Income:FX Gain 3.00 CAD' in round_tripped, round_tripped
    assert 'Assets:Bank 137.00 CAD' in round_tripped, round_tripped
    assert 'value: "-140.00"' in round_tripped, round_tripped
    assert 'Total USD basis balance: 0.00 USD' in _balances(runner, fresh)


def test_same_currency_payment_still_settles_without_a_rate(tmp_path):
    """The single-currency path keeps working: no rate asked for, none needed."""
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    result = runner.invoke(cli, ['import', '--new', str(book),
                                 'tests/fixtures/business_objects.txt',
                                 '--include-business-objects'])
    assert result.exit_code == 0, result.output
    exported = _export_text(runner, book, tmp_path / 'out.txt')
    assert 'payment:' in exported, exported


def test_a_converting_payment_that_overpays_values_both_parts(tmp_path):
    """An overpayment converts at the payment's rate, not the record's.

    The 100.00 USD that clears the invoice is released at what the invoice
    carried, 1.40; the 100.00 USD overpaid was received at 1.37 and is worth
    137.00 CAD. Both belong in the entry, and what is left over is the 3.00
    CAD the invoice lost.

    Before: `GncLot` has no guid accessor, so identifying the settling split
    raised on every converting overpayment; patched past that, the credit's
    value was left out of the arithmetic entirely and GnuCash scrubbed in
    Imbalance-CAD 137.00 while the loss reported as 134.00.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    result = runner.invoke(cli, [
        'import', '--new', str(book),
        'tests/fixtures/fx_invoice_usd_overpaid_into_cad_bank.txt',
        '--include-business-objects', '--fx-rates', RATES])
    assert result.exit_code == 0, result.output

    exported = tmp_path / 'out.txt'
    result = runner.invoke(cli, ['export', str(book), str(exported)])
    assert result.exit_code == 0, result.output
    text = exported.read_text()

    assert 'Imbalance' not in text, text
    assert 'value: "-140.00"' in text, text     # settled at the invoice's rate
    assert 'value: "-137.00"' in text, text     # the credit, at the payment's
    assert 'Income:FX Gain 3.00 CAD' in text, text


def test_a_converting_bill_payment_that_overpays_values_both_parts(tmp_path):
    """The bill mirror: the prepayment it leaves is a basis like any other.

    Less cash extinguishing more liability is a gain, so the 3.00 CAD is
    credited here. And the 100.00 USD sent beyond the bill is currency the
    book has a claim on, listed and sellable — a payable judged by its credit
    side alone had that prepayment's KVPs written and then ignored, reporting
    0.00 USD available against 100.00 USD held.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    result = runner.invoke(cli, [
        'import', '--new', str(book),
        'tests/fixtures/fx_bill_usd_overpaid_into_cad_bank.txt',
        '--include-business-objects', '--fx-rates', RATES])
    assert result.exit_code == 0, result.output

    exported = tmp_path / 'out.txt'
    result = runner.invoke(cli, ['export', str(book), str(exported)])
    assert result.exit_code == 0, result.output
    text = exported.read_text()

    assert 'Imbalance' not in text, text
    assert 'value: "140.00"' in text, text     # cleared at the bill's rate
    assert 'value: "137.00"' in text, text     # the prepayment, at the payment's
    assert 'Income:FX Gain -3.00 CAD' in text, text

    listing = runner.invoke(cli, ['fx-balances', str(book)]).output
    assert 'Total USD basis balance: 100.00' in listing, listing
    # And at the rate it was actually sent at, 274/200, not the 1.40 the bill
    # was carried at — the whole point of taking the cost from the payment's
    # own figures rather than writing the record's onto it.
    assert '1.37 CAD/USD' in listing, listing


def test_a_record_with_no_cost_cannot_reach_the_overpayment_arithmetic(tmp_path):
    """Why that arithmetic never divides by zero.

    An overpayment is valued at what the bank received over everything it paid
    for, and that divisor is the payment's own receivable splits. For it to be
    zero every one of them would have to be zero — the excess included, and
    the excess is why there is an overpayment at all.

    Driving the settled side to zero is as close as a book gets, and it never
    arrives: a 0.00 posting has no value over amount, so the record carries no
    cost to measure against and the payment returns there. The other way in is
    closed as well — a payment of nothing joins no lot, and a payment with no
    lot returns a step earlier still.

    Both of those returns are silent unless the block carries split lines that
    nothing would then place, which is what this fixture gives it: with
    `Income:FX Gain $residual$` on the payment, the return becomes a refusal
    that names the line and says where to write it instead.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    result = runner.invoke(cli, [
        'import', '--new', str(book),
        'tests/fixtures/fx_invoice_usd_zero_amount_overpaid.txt',
        '--include-business-objects', '--fx-rates', RATES])

    assert result.exit_code != 0, result.output
    assert 'carries no cost in CAD' in result.output, result.output
    assert 'Income:FX Gain' in result.output, result.output


def test_an_overpaid_converting_payment_round_trips(tmp_path):
    """Export it, import that into a fresh book, export again — and compare.

    The overpaid split carries an engine-set value and a `cost_basis_balance`
    KVP, and both have to survive the trip. No expectation is written down
    here: the diff is the answer.
    """
    import difflib

    runner = CliRunner()
    first = tmp_path / 'first.gnucash'
    result = runner.invoke(cli, [
        'import', '--new', str(first),
        'tests/fixtures/fx_invoice_usd_overpaid_into_cad_bank.txt',
        '--include-business-objects', '--fx-rates', RATES])
    assert result.exit_code == 0, result.output

    one = tmp_path / 'one.txt'
    result = runner.invoke(cli, ['export', str(first), str(one),
                                 '--include-business-objects'])
    assert result.exit_code == 0, result.output

    second = tmp_path / 'second.gnucash'
    result = runner.invoke(cli, ['import', '--new', str(second), str(one),
                                 '--include-business-objects'])
    assert result.exit_code == 0, result.output

    two = tmp_path / 'two.txt'
    result = runner.invoke(cli, ['export', str(second), str(two),
                                 '--include-business-objects'])
    assert result.exit_code == 0, result.output

    diff = list(difflib.unified_diff(
        one.read_text().splitlines(), two.read_text().splitlines(),
        fromfile='first export', tofile='second export', lineterm=''))
    assert not diff, '\n'.join(diff)


def test_an_overpaid_converting_bill_payment_round_trips(tmp_path):
    """The bill twin of the round-trip: the vendor prepayment survives too."""
    import difflib

    runner = CliRunner()
    first = tmp_path / 'first.gnucash'
    result = runner.invoke(cli, [
        'import', '--new', str(first),
        'tests/fixtures/fx_bill_usd_overpaid_into_cad_bank.txt',
        '--include-business-objects', '--fx-rates', RATES])
    assert result.exit_code == 0, result.output

    one = tmp_path / 'one.txt'
    result = runner.invoke(cli, ['export', str(first), str(one),
                                 '--include-business-objects'])
    assert result.exit_code == 0, result.output

    second = tmp_path / 'second.gnucash'
    result = runner.invoke(cli, ['import', '--new', str(second), str(one),
                                 '--include-business-objects'])
    assert result.exit_code == 0, result.output

    two = tmp_path / 'two.txt'
    result = runner.invoke(cli, ['export', str(second), str(two),
                                 '--include-business-objects'])
    assert result.exit_code == 0, result.output

    diff = list(difflib.unified_diff(
        one.read_text().splitlines(), two.read_text().splitlines(),
        fromfile='first export', tofile='second export', lineterm=''))
    assert not diff, '\n'.join(diff)


def test_the_residual_must_land_in_income_or_expense(tmp_path):
    """A realized difference is a gain or a loss, so it belongs in the P&L.

    `$residual$` says "whatever the settlement leaves over", and what it
    leaves over is the difference between the rate a record was booked at and
    the rate it settled at. That is income when the book gained and an expense
    when it lost. Posted to a bank or an asset instead, the difference is
    still absorbed — the entry balances either way — but it never reaches the
    income statement: it sits in the balance sheet as though the money had
    merely moved, and the year's FX result is understated by exactly that
    much.

    Only the account's *type* is read. Nothing here decides what an account
    means from its name.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    fixture = _variant(
        tmp_path, 'tests/fixtures/fx_invoice_usd_paid_from_cad_bank.txt',
        '\t\tIncome:FX Gain $residual$ CAD',
        '\t\tAssets:Bank $residual$ CAD')

    result = _import(runner, book, fixture)
    assert result.exit_code != 0, result.output
    assert f'{RESIDUAL} on' in result.output, result.output
    assert "'Assets:Bank'" in result.output, result.output
    assert 'income or expense' in result.output, result.output


def test_a_loss_may_be_booked_to_an_expense_account(tmp_path):
    """Income or expense — both, because a realized difference is either.

    Settling a 100.00 USD invoice booked at 1.40 for 137.00 CAD loses 3.00,
    and a loss is what an expense account is for. The rule reads "income or
    expense" and the fixtures all say income, so this is the other arm: a
    payment posting its residual to `Expenses:FX Loss` is as ordinary as one
    posting a gain to income, and refusing it would make the commonest way of
    writing a loss unimportable.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    source = Path('tests/fixtures/fx_invoice_usd_paid_from_cad_bank.txt').read_text()
    fixture = tmp_path / 'loss_to_expense.txt'
    fixture.write_text(
        source.replace(
            '2026-01-01 open Income:FX Gain\n\ttype: Income\n',
            '2026-01-01 open Expenses\n\ttype: Expense\n'
            '\tcommodity.namespace: "CURRENCY"\n\tcommodity.mnemonic: "CAD"\n'
            '2026-01-01 open Expenses:FX Loss\n\ttype: Expense\n')
        .replace('Income:FX Gain $residual$ CAD',
                 'Expenses:FX Loss $residual$ CAD'))

    result = _import(runner, book, str(fixture))
    assert result.exit_code == 0, result.output

    exported = _export_text(runner, book, tmp_path / 'out.txt')
    assert 'Expenses:FX Loss 3.00 CAD' in exported, exported
    assert 'Imbalance' not in exported, exported
