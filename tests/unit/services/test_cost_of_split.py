"""What a foreign-currency split cost, in the book's own currency.

`cost_of` is what every cost basis is priced by, so it has to be right for any
transaction that brings foreign currency in — not only the two-currency shapes
the rest of the suite exercises.

The hard case is one transaction touching three currencies: 99.90 CAD sold for
both USD and HKD at 1.35 CAD/USD and 5.7 HKD/CAD. Each split has its own cost,
and neither is the whole CAD divided by one split's amount.
"""

from fractions import Fraction

from click.testing import CliRunner

from cli.main import cli
from infrastructure.gnucash.kvp import set_custom_metadata
from infrastructure.gnucash.utils import find_account
from repositories.gnucash_repository import GnuCashRepository, SessionMode
from services.foreign_currency import cost_of


def _split_on(book, account_path):
    account = find_account(book.get_root_account(), account_path)
    assert account is not None, f'{account_path} missing'
    splits = account.GetSplitList()
    assert len(splits) == 1, f'{account_path} has {len(splits)} splits'
    return splits[0]


def _book_with_three_currency_sale(tmp_path):
    runner = CliRunner()
    gnucash_file = tmp_path / 'book.gnucash'
    result = runner.invoke(cli, [
        'import', '--new', str(gnucash_file),
        'tests/fixtures/fx_sell_cad_for_usd_and_hkd.txt',
        '--include-business-objects'])
    assert result.exit_code == 0, result.output
    repo = GnuCashRepository(str(gnucash_file))
    repo.open(mode=SessionMode.READ_ONLY)
    return repo


def test_cost_of_the_usd_split_is_what_that_split_cost(tmp_path):
    """54.00 of the CAD bought the 40.00 USD, so the cost is 1.35 CAD/USD.

    Taking the whole 99.90 CAD against the USD split charges it for the HKD as
    well and reports 2.4975.
    """
    repo = _book_with_three_currency_sale(tmp_path)
    try:
        cost = cost_of(_split_on(repo.book, 'Assets:Bank:USD'))
    finally:
        repo.close()
    assert cost == Fraction(27, 20), f'expected 1.35 CAD/USD, got {cost}'


def test_a_bank_fee_is_not_part_of_what_the_currency_cost(tmp_path):
    """40.00 USD bought at 1.35 with a 2.70 CAD fee charged alongside cost
    1.35 CAD/USD; the fee is an expense.

    A rule that adds up the base-currency splits sweeps the fee in and reports
    1.4175 — and would keep reporting it in every gain computed against that
    basis.
    """
    runner = CliRunner()
    gnucash_file = tmp_path / 'fee.gnucash'
    result = runner.invoke(cli, [
        'import', '--new', str(gnucash_file),
        'tests/fixtures/fx_buy_usd_with_bank_fee.txt',
        '--include-business-objects'])
    assert result.exit_code == 0, result.output

    repo = GnuCashRepository(str(gnucash_file))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        cost = cost_of(_split_on(repo.book, 'Assets:Bank:USD'))
    finally:
        repo.close()
    assert cost == Fraction(27, 20), f'expected 1.35 CAD/USD, got {cost}'


def test_a_discount_on_the_base_side_is_part_of_what_the_currency_cost(tmp_path):
    """90.00 USD receivable against 140.00 CAD of revenue less a 14.00 CAD
    discount cost 126/90 = 1.40 CAD/USD.

    Unlike a bank fee, a discount is not a separate expense the book paid: it
    reduces the revenue, so the base currency the transaction actually booked
    is the 126.00 that the receivable was raised for.
    """
    runner = CliRunner()
    gnucash_file = tmp_path / 'discount.gnucash'
    result = runner.invoke(cli, [
        'import', '--new', str(gnucash_file),
        'tests/fixtures/fx_usd_posting_with_cad_discount.txt',
        '--include-business-objects'])
    assert result.exit_code == 0, result.output

    repo = GnuCashRepository(str(gnucash_file))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        cost = cost_of(_split_on(repo.book, 'Assets:Accounts Receivable USD'))
    finally:
        repo.close()
    assert cost == Fraction(7, 5), f'expected 1.40 CAD/USD, got {cost}'

    # And that is what the listing shows the user.
    result = runner.invoke(cli, ['fx-balances', str(gnucash_file)])
    assert result.exit_code == 0, result.output
    assert '1.4 CAD/USD' in result.output, result.output
    assert '90.00 USD' in result.output, result.output


def test_fx_balances_lists_both_bases_with_their_own_costs(tmp_path):
    """What a reader sees: one row per basis, each at its own cost.

    The HKD cost is 10/57 CAD/HKD, which no decimal states exactly, so it is
    listed as the fraction it is rather than rounded to a number that would not
    reproduce the amounts.
    """
    runner = CliRunner()
    gnucash_file = tmp_path / 'book.gnucash'
    result = runner.invoke(cli, [
        'import', '--new', str(gnucash_file),
        'tests/fixtures/fx_sell_cad_for_usd_and_hkd.txt',
        '--include-business-objects'])
    assert result.exit_code == 0, result.output

    result = runner.invoke(cli, ['fx-balances', str(gnucash_file)])
    assert result.exit_code == 0, result.output
    listing = result.output
    assert '1.35 CAD/USD' in listing, listing
    assert '40.00 USD' in listing, listing
    assert '10/57 CAD/HKD' in listing, listing
    assert '261.63 HKD' in listing, listing


def test_cost_of_the_hkd_split_is_what_that_split_cost(tmp_path):
    """45.90 of the CAD bought the 261.63 HKD, so the cost is 1/5.7 CAD/HKD.

    The transaction is in USD, which is neither the book's currency nor this
    split's, so a rule that only handles those two answers None and the HKD
    gets no balance.
    """
    repo = _book_with_three_currency_sale(tmp_path)
    try:
        cost = cost_of(_split_on(repo.book, 'Assets:Bank:HKD'))
    finally:
        repo.close()
    assert cost is not None, 'HKD brought into the book has a cost'
    assert cost == Fraction(10, 57), f'expected 1/5.7 CAD/HKD, got {cost}'


def test_the_transaction_outranks_a_cost_stored_beside_it(tmp_path):
    """A stored cost is a fallback, not an override.

    `cost_basis_cost` exists for the one shape whose transaction cannot state
    a cost — every split in one foreign currency, no base-currency figure
    anywhere in it. Where the transaction *can* state one, it is the answer:
    the ledger's own figures are what the book is, and a KVP beside them is a
    copy that can be stale, hand-edited, or left behind by a correction.

    Consulted first, that copy won. A split bought for 135.00 CAD reported
    whatever the KVP said — 9.99 CAD/USD here — and `fx-balances`, every gain,
    and the cost every later sale must be valued at all followed the copy
    rather than the money. Correcting the transaction could not dislodge it,
    because the correction changes the figures the copy was hiding.
    """
    runner = CliRunner()
    gnucash_file = tmp_path / 'book.gnucash'
    result = runner.invoke(cli, [
        'import', '--new', str(gnucash_file),
        'tests/fixtures/fx_buy_and_borrow_usd.txt'])
    assert result.exit_code == 0, result.output

    repo = GnuCashRepository(str(gnucash_file))
    repo.open(mode=SessionMode.NORMAL)
    try:
        account = find_account(repo.book.get_root_account(), 'Assets:Bank:USD')
        split = next(s for s in account.GetSplitList()
                     if cost_of(s) == Fraction(27, 20))     # the 1.35 purchase

        transaction = split.GetParent()
        transaction.BeginEdit()
        set_custom_metadata(split, {'cost_basis_cost': '9.99 CAD/USD'})
        transaction.CommitEdit()

        assert cost_of(split) == Fraction(27, 20), (
            f'135.00 CAD bought 100.00 USD, so it cost 1.35 — the split '
            f'reports {cost_of(split)}')
    finally:
        repo.close()
