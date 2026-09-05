"""`to_money` rounds half away from zero, on both sides of zero.

The engine does the arithmetic — Python's `round` is banker's rounding and
answers a cent adrift on an exact half — and on GnuCash 3.4 the engine drops
the sign while keeping the magnitude:

    GnuCash    (-5/1000).convert(100, HALF_UP)   (+5/1000)
    3.4        +1/100                            +1/100
    5.10       -1/100                            +1/100

`to_money` therefore rounds `abs` and re-signs, which is the same answer on
every build because half-up is symmetric about zero. The closing-entry tests
catch this too — a book of two half-cents came out with every sign inverted on
Debian 10, and *balanced*, so nothing else reported it — but they catch it
through a whole `close-books` run. These say it of the function, which is what
every money figure this tool writes goes through.
"""

from fractions import Fraction

from infrastructure.gnucash.utils import money_text, numeric_to_fraction, to_money


def _as_fraction(value, scu=100):
    return numeric_to_fraction(to_money(Fraction(value), scu))


class TestAnExactHalf:
    """Away from zero on both sides, which is what "half up" means for money."""

    def test_a_positive_half_cent_rounds_up(self):
        assert _as_fraction(Fraction(5, 1000)) == Fraction(1, 100)

    def test_a_negative_half_cent_rounds_down(self):
        assert _as_fraction(Fraction(-5, 1000)) == Fraction(-1, 100)

    def test_and_the_two_are_mirror_images(self):
        assert _as_fraction(Fraction(-5, 1000)) == -_as_fraction(Fraction(5, 1000))

    def test_the_text_carries_the_sign(self):
        assert money_text(Fraction(-5, 1000), 100) == '-0.01'
        assert money_text(Fraction(5, 1000), 100) == '0.01'


class TestTheOrdinaryFigures:
    """Nothing about the re-signing changes what was already right."""

    def test_a_negative_amount_that_needs_no_rounding(self):
        assert _as_fraction(Fraction(-123, 100)) == Fraction(-123, 100)

    def test_a_negative_amount_rounding_down_to_the_nearer_cent(self):
        assert _as_fraction(Fraction(-1234, 1000)) == Fraction(-123, 100)

    def test_a_negative_amount_rounding_up_to_the_nearer_cent(self):
        assert _as_fraction(Fraction(-1236, 1000)) == Fraction(-124, 100)

    def test_zero_has_no_sign_to_lose(self):
        assert _as_fraction(Fraction(0)) == 0

    def test_a_currency_kept_to_whole_units(self):
        assert _as_fraction(Fraction(-5, 10), scu=1) == Fraction(-1)
