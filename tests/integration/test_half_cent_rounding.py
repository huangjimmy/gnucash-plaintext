"""Money rounds away from zero, not to even.

Amounts are held as exact fractions precisely so a rate is never a float, but a
figure still has to reach the cent when it is written to a split — and where it
lands on an exact half-cent, the direction is an accounting decision, not a
numeric convenience. Python's `round` is banker's rounding, which sends a half
to the nearest *even* cent; a CRA filer's figures round away from zero.

45.00 USD booked at 1.405 CAD/USD is 63.225 CAD exactly — half a cent — so it
is 63.23, and settling it for 62.00 CAD realizes a 1.23 CAD loss. Banker's
rounding gives 63.22 and 1.22, a cent adrift in the books and in the gain
reported for the year.
"""

from click.testing import CliRunner

from cli.main import cli


def test_a_half_cent_settlement_rounds_away_from_zero(tmp_path):
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    result = runner.invoke(cli, [
        'import', '--new', str(book),
        'tests/fixtures/fx_invoice_partial_settlement_half_cent.txt',
        '--include-business-objects',
        '--fx-rates', 'tests/fixtures/fx_rates_usd_half_cent.yaml'])
    assert result.exit_code == 0, result.output

    exported = tmp_path / 'out.txt'
    result = runner.invoke(cli, ['export', str(book), str(exported)])
    assert result.exit_code == 0, result.output
    text = exported.read_text()

    # The 45.00 USD settled is valued at what it cost: 63.225 -> 63.23.
    assert 'value: "-63.23"' in text, text
    # And the loss is what is left after the 62.00 CAD received.
    assert 'Income:FX Gain 1.23 CAD' in text, text


def test_a_half_cent_residual_on_a_transaction_rounds_the_same_way(tmp_path):
    """The same sale written as an ordinary transaction reaches the same cent.

    `$residual$` is computed, not stated, so it is rounded rather than refused
    — otherwise the same economic event would be accepted as a payment block
    and rejected as a transaction, and the writer would be blamed for `49/40`,
    a figure appearing nowhere in their file.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    result = runner.invoke(cli, [
        'import', '--new', str(book),
        'tests/fixtures/fx_sell_usd_half_cent_residual.txt'])
    assert result.exit_code == 0, result.output

    exported = tmp_path / 'out.txt'
    result = runner.invoke(cli, ['export', str(book), str(exported)])
    assert result.exit_code == 0, result.output
    text = exported.read_text()

    assert 'Income:FX Gain 1.23 CAD' in text, text
    # Both figures reached the cent, so nothing is left over to scrub in.
    assert 'Imbalance' not in text, text
    # The exported rate is 63.23 / 45.00 — 6323/4500, or 1.405 + 1/9000 — not
    # the 1.405 the file stated. The value had to reach the cent, and the rate
    # that comes back is the one those two stored figures describe. A stated
    # rate is an input to the value, not a field that round-trips, so asserting
    # it comes back verbatim would be asserting something this tool cannot
    # deliver.
    #
    # What the rate must not do is arrive truncated: parsed as 1.40 it values
    # the 45.00 USD at 63.00, and the entry loses 23 cents to an imbalance.
    assert 'share_price: "6323/4500"' in text, text
