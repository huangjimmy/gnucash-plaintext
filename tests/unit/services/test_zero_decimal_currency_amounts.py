"""Amounts in a currency with no minor unit.

A yen is not divided into hundredths. GnuCash records that as the commodity's
smallest unit — `get_fraction()` is 1 for JPY, 100 for CAD — so 103 yen is
written 103, and rounding a JPY figure "to the cent" means rounding it to the
whole yen. Anything that hardcodes two decimals, a `.2f` or a denominator of
100, is wrong for these currencies, so every amount takes its smallest unit
from its own commodity.

The figures here are 103 and 1030 rather than round hundreds: 100.00 and 100
are both plausible-looking, so a round number can hide a wrong denominator that
103 exposes.

KRW is the version-dependent case: GnuCash's ISO table carries the won with a
fraction of 100 through 5.14 and normalises it to 1 from 5.15, so its expected
decimals are read off the commodity rather than written into the test.
"""

from fractions import Fraction

from click.testing import CliRunner

from cli.main import cli
from infrastructure.gnucash.utils import (
    find_account,
    money_text,
    numeric_to_fraction,
    to_money,
    to_string_with_decimal_point_placed,
)
from repositories.gnucash_repository import GnuCashRepository, SessionMode

FIXTURE = 'tests/fixtures/zero_decimal_currency_accounts.txt'


def _import(tmp_path):
    gnucash_file = tmp_path / 'book.gnucash'
    result = CliRunner().invoke(cli, [
        'import', '--new', str(gnucash_file), FIXTURE,
        '--include-business-objects'])
    assert result.exit_code == 0, result.output
    return gnucash_file


def _book(tmp_path):
    repo = GnuCashRepository(str(_import(tmp_path)))
    repo.open(mode=SessionMode.READ_ONLY)
    return repo


def _commodity(repo, account_path):
    account = find_account(repo.book.get_root_account(), account_path)
    assert account is not None, f'{account_path} missing'
    return account.GetCommodity()


def test_the_yen_has_no_minor_unit(tmp_path):
    repo = _book(tmp_path)
    try:
        assert _commodity(repo, 'Assets:Bank:JPY').get_fraction() == 1
        assert _commodity(repo, 'Assets:Bank').get_fraction() == 100
    finally:
        repo.close()


def test_a_yen_amount_is_written_without_decimals(tmp_path):
    repo = _book(tmp_path)
    try:
        jpy = _commodity(repo, 'Assets:Bank:JPY')
        assert to_string_with_decimal_point_placed(
            to_money(Fraction(103), jpy.get_fraction())) == '103'

        cad = _commodity(repo, 'Assets:Bank')
        assert to_string_with_decimal_point_placed(
            to_money(Fraction(103), cad.get_fraction())) == '103.00'
    finally:
        repo.close()


def test_tax_on_a_yen_invoice_reaches_a_whole_yen(tmp_path):
    """Where a fractional yen comes from, and where it has to end up.

    No JPY split can hold half a yen, but tax produces one: 2070 JPY at 5% is
    103.5 exactly. It has to reach a whole yen to be booked, half a yen is the
    rounding boundary, and money rounds away from zero — so 104.

    Both figures are checked: what GnuCash books on the posting transaction,
    and what this tool prints. They have to be the same number, or the invoice
    sent to the customer disagrees with the ledger it came from.
    """
    gnucash_file = tmp_path / 'jpy.gnucash'
    result = CliRunner().invoke(cli, [
        'import', '--new', str(gnucash_file),
        'tests/fixtures/jpy_invoice_tax_half_yen.txt',
        '--include-business-objects'])
    assert result.exit_code == 0, result.output

    repo = GnuCashRepository(str(gnucash_file))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        tax_account = find_account(repo.book.get_root_account(),
                                   'Liabilities:Tax:Sales Tax JPY')
        booked = abs(numeric_to_fraction(tax_account.GetBalance()))
        assert booked == Fraction(104), booked
    finally:
        repo.close()

    exported = tmp_path / 'out.txt'
    result = CliRunner().invoke(cli, ['export', str(gnucash_file), str(exported),
                                      '--include-business-objects'])
    assert result.exit_code == 0, result.output
    text = exported.read_text()
    # The tax is credited whole, and the receivable is the 2070 plus that 104.
    assert 'Liabilities:Tax:Sales Tax JPY -104 JPY' in text, text
    assert 'Assets:Accounts Receivable JPY 2174 JPY' in text, text
    assert '103.50' not in text and '103.5' not in text, text

    # The document the customer receives says the same, in yen: the invoice
    # renderer computes its own tax figures rather than reading the splits.
    printed = tmp_path / 'invoice.txt'
    result = CliRunner().invoke(cli, [
        'print-invoice', str(gnucash_file), 'INV-JPY-HALF',
        '--format', 'plaintext', '-o', str(printed)])
    assert result.exit_code == 0, result.output
    document = printed.read_text()
    assert 'entry_tax: 104' in document, document
    assert 'invoice_total: 2174' in document, document
    assert '.00' not in document, document


def test_a_zero_is_written_at_its_currency_s_decimals(tmp_path):
    """Zero is where the engines disagree, so it is pinned on all of them.

    GnuCash 3.8's `gnc_numeric_to_decimal` reduces 0/100 to 0/1 where every
    later version keeps 0/100 — and a formatter that counts the zeros in the
    denominator then writes `0` on Ubuntu 20.04 and `0.00` everywhere else, in
    exports and printed invoices alike. The decimals come from the commodity,
    so a zero is written like any other amount in that currency.
    """
    repo = _book(tmp_path)
    try:
        cad = _commodity(repo, 'Assets:Bank').get_fraction()
        jpy = _commodity(repo, 'Assets:Bank:JPY').get_fraction()
    finally:
        repo.close()

    assert money_text(Fraction(0), cad) == '0.00'
    assert money_text(Fraction(0), jpy) == '0'
    # And a whole amount keeps its decimals for the same reason.
    assert money_text(Fraction(7), cad) == '7.00'
    assert money_text(Fraction(7), jpy) == '7'
    assert money_text(Fraction('-0.5'), cad) == '-0.50'


def test_won_decimals_follow_its_own_commodity(tmp_path):
    """Whatever GnuCash says the won's smallest unit is, the rendering agrees.

    The engine's answer changes between versions, so the test asserts the rule
    — decimals come from the commodity — not one version's value.
    """
    repo = _book(tmp_path)
    try:
        fraction = _commodity(repo, 'Assets:Bank:KRW').get_fraction()
        places = len(str(fraction)) - 1
        expected = '1030' if places == 0 else '1030.' + '0' * places
        assert to_string_with_decimal_point_placed(
            to_money(Fraction(1030), fraction)) == expected
    finally:
        repo.close()


def test_a_yen_balance_survives_a_round_trip_whole(tmp_path):
    """The 103 JPY the fixture buys comes back as 103, not 103.00."""
    gnucash_file = _import(tmp_path)
    exported = tmp_path / 'out.txt'
    result = CliRunner().invoke(cli, ['export', str(gnucash_file), str(exported)])
    assert result.exit_code == 0, result.output

    text = exported.read_text()
    assert 'Assets:Bank:JPY 103 JPY' in text, text
    assert '103.00 JPY' not in text, text
