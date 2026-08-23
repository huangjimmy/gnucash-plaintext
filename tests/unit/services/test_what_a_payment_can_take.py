"""How much of what an invoice owes a payment can actually take.

Floored to the unit the account is kept to, never rounded up: rounding up
settles more than is owed and takes the lot past zero, where the invoice reads
neither settled nor open and the owner's money is inside a lot they cannot
spend from.

Driven directly because the input cannot be written in a file. What a payment
cancels is the posting split, and both it and every payment on the account are
held at the account's unit — so a residue between them is a whole number of
those units and the flooring changes nothing. A book whose splits are finer
than the account they sit on is what the guard is for, and this tool will not
write one: an amount finer than the account's unit is refused at the door.
"""

from fractions import Fraction

import pytest

from services.gnucash_importer import (
    _refuse_a_payment_that_would_fall_short,
    _refuse_if_below_the_accounts_unit,
    _takeable_from,
)


class FakeAccount:
    """An account kept to `unit` — a tenth of a dollar at 10, a cent at 100."""

    def __init__(self, unit):
        self.unit = unit

    def GetCommoditySCU(self):      # noqa: N802  (GnuCash's own spelling)
        return self.unit


@pytest.mark.parametrize('owed, unit, expected', [
    (Fraction(3010, 100), 10, Fraction(301, 10)),    # already a whole unit
    (Fraction(3005, 100), 10, Fraction(300, 10)),    # finer: down, never up
    (Fraction(5, 100), 10, Fraction(0)),             # finer than one unit
    (Fraction(1, 10), 10, Fraction(1, 10)),          # exactly one unit
    (Fraction(20005, 1000), 1000, Fraction(20005, 1000)),
])
def test_what_can_be_taken_is_floored_to_the_accounts_unit(owed, unit, expected):
    assert _takeable_from(owed, FakeAccount(unit)) == expected


def test_a_residue_finer_than_one_unit_leaves_nothing_to_take():
    """Which is what the refusal beside it is for.

    Taken as zero and applied anyway, the division writes a 0.00 split into the
    invoice's lot, tagged as though a credit had been spent on it, while the
    credit itself is untouched — and the export writes that split back out as
    `amount: 0.00`, a file this importer then refuses.
    """
    assert _takeable_from(Fraction(5, 100), FakeAccount(10)) == 0


class FakeCommodity:
    def get_mnemonic(self):     # noqa: N802  (GnuCash's own spelling)
        return 'CAD'

    def get_fraction(self):
        return 100


class FakeAccountWithCommodity(FakeAccount):
    def GetCommodity(self):     # noqa: N802
        return FakeCommodity()


def test_nothing_takeable_is_refused_rather_than_returned():
    """Both paths that divide a payment ask this, so they cannot disagree.

    The bank path used to work its residual out from a figure that had floored
    to nothing, tell the reader to declare the whole payment as `prepayment:`,
    accept that, and then refuse for the sub-unit residue when it came to apply
    it — a remedy the same import rejected.
    """
    account = FakeAccountWithCommodity(10)

    assert _refuse_if_below_the_accounts_unit(
        Fraction(1, 10), account, 'Invoice', 'INV-1') == Fraction(1, 10)

    with pytest.raises(Exception, match='less than the unit this account'):
        _refuse_if_below_the_accounts_unit(
            Fraction(5, 100), account, 'Invoice', 'INV-1')


class FakeCommodityNamed(FakeCommodity):
    def __init__(self, mnemonic):
        self._mnemonic = mnemonic

    def get_mnemonic(self):     # noqa: N802
        return self._mnemonic


class FakeAccountIn(FakeAccount):
    def __init__(self, unit, mnemonic):
        super().__init__(unit)
        self._commodity = FakeCommodityNamed(mnemonic)

    def GetCommodity(self):     # noqa: N802
        return self._commodity


def test_a_payment_is_not_judged_against_a_figure_in_another_currency():
    """Two numbers in different money are not comparable, so nothing is said.

    A block naming only its transaction is what a bank feed's transactions are
    attached with, and the side that is not the bank can be an Imbalance split
    in the bank's currency rather than the invoice's. `amount:` is written in
    the invoice's money. Compared anyway, a 74.00 of one currency reads as
    falling short of a 100.00 of another and the file is refused for a
    shortfall that exists only in the arithmetic.

    Driven directly because no file reaches it: it needs a transaction whose
    other side is in neither the invoice's currency nor the bank's, which is
    a book this tool does not write.
    """
    receivable = FakeAccountIn(100, 'USD')
    elsewhere = FakeAccountIn(100, 'GBP')

    # Same money, and genuinely short: refused, naming both figures.
    with pytest.raises(Exception, match='part-paid'):
        _refuse_a_payment_that_would_fall_short(
            {'amount': '100'}, Fraction(74), Fraction(100), receivable,
            'Invoice', 'INV-1', 'abc', receivable)

    # Different money: the same numbers say nothing about each other.
    _refuse_a_payment_that_would_fall_short(
        {'amount': '100'}, Fraction(74), Fraction(100), receivable,
        'Invoice', 'INV-1', 'abc', elsewhere)
