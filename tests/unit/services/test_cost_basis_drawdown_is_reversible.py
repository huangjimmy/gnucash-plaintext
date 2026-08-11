"""Whatever a transaction draws from a cost basis can be handed back.

The importer applies a transaction's picks — checking each one and lowering
the balances — and then keeps reading the transaction. If anything after that
refuses it, the transaction is destroyed, and the drawdown has to go with it:
a basis left lowered by a sale the book does not hold is currency that can no
longer be sold and that nothing accounts for.

Every refusal the *file* can cause is checked before the drawdown today — a
stated cost is parsed before the transaction is created, and a pick is
validated before any balance moves — so what remains between the two is the
engine: the lot query behind `_is_prepayment`, and the KVP writes that open a
basis. Those cannot be provoked from a fixture, so the mechanism is exercised
directly here rather than through a file that would prove nothing.
"""

from fractions import Fraction

from click.testing import CliRunner
from gnucash import Split, Transaction

from cli.main import cli
from infrastructure.gnucash.kvp import set_custom_metadata
from infrastructure.gnucash.utils import find_account, to_money
from repositories.gnucash_repository import GnuCashRepository, SessionMode
from services.foreign_currency import (
    COST_BASIS_SPLIT_KEY,
    apply_cost_basis_picks,
    cost_basis_balance_of,
    cost_of,
    find_split_by_guid,
    give_back_to_cost_bases,
    split_guid,
)

CENTS = 100


def _basis_balances(book):
    """Every basis on the USD account, by guid, with the balance each has."""
    account = find_account(book.get_root_account(), 'Assets:Bank:USD')
    found = {}
    for split in account.GetSplitList():
        balance = cost_basis_balance_of(split)
        if balance is not None:
            found[split_guid(split)] = balance
    return found


def _sale_picking(book, picks):
    """A transaction selling `units` from each basis in `picks`: {guid: units}.

    Written the way the importer writes one — splits parented, valued at the
    cost of the basis each picks, and carrying `cost_basis_split_guid` —
    because that is what `apply_cost_basis_picks` reads.
    """
    root = book.get_root_account()
    usd_account = find_account(root, 'Assets:Bank:USD')
    cad_account = find_account(root, 'Assets:Bank')

    transaction = Transaction(book)
    transaction.BeginEdit()
    transaction.SetCurrency(cad_account.GetCommodity())
    transaction.SetDescription('Sell USD against two bases')

    proceeds = Fraction(0)
    for guid, units in picks.items():
        value = units * cost_of(find_split_by_guid(book, guid))
        split = Split(book)
        split.SetParent(transaction)
        split.SetAccount(usd_account)
        split.SetAmount(to_money(-units, CENTS))
        split.SetValue(to_money(-value, CENTS))
        set_custom_metadata(split, {COST_BASIS_SPLIT_KEY: guid})
        proceeds += value

    balancing = Split(book)
    balancing.SetParent(transaction)
    balancing.SetAccount(cad_account)
    balancing.SetAmount(to_money(proceeds, CENTS))
    balancing.SetValue(to_money(proceeds, CENTS))
    transaction.CommitEdit()
    return transaction


def test_giving_back_restores_exactly_what_the_picks_took(tmp_path):
    """Two bases drawn down by one transaction, both restored in full."""
    runner = CliRunner()
    gnucash_file = tmp_path / 'book.gnucash'
    result = runner.invoke(cli, [
        'import', '--new', str(gnucash_file),
        'tests/fixtures/fx_buy_and_borrow_usd.txt'])
    assert result.exit_code == 0, result.output

    repo = GnuCashRepository(str(gnucash_file))
    repo.open(mode=SessionMode.NORMAL)
    try:
        before = _basis_balances(repo.book)
        assert sorted(before.values()) == [Fraction(100), Fraction(100)], before

        # 40 from the basis that cost 1.35, 25 from the one that cost 1.30.
        picks = {}
        for guid in before:
            cost = cost_of(find_split_by_guid(repo.book, guid))
            picks[guid] = Fraction(40) if cost == Fraction(27, 20) else Fraction(25)
        transaction = _sale_picking(repo.book, picks)

        taken = apply_cost_basis_picks(repo.book, transaction)
        assert sorted(taken.values()) == [Fraction(25), Fraction(40)], taken
        during = _basis_balances(repo.book)
        assert sorted(during.values()) == [Fraction(60), Fraction(75)], during

        give_back_to_cost_bases(repo.book, taken)
        assert _basis_balances(repo.book) == before, (
            f'{before} became {_basis_balances(repo.book)}')
    finally:
        repo.close()
