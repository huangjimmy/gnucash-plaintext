"""Fitting a page's lines to the figure the book holds.

A printed page states a tax per line and a tax for the page, and the
book holds only the second: GnuCash rounds a page's tax once, and an
accumulated posting carries no per-line tax split. Rounded on their own the
lines need not add to the whole — three lines of 13.0434… each print 13.04
against a stated 39.13 — so `figures_that_add_up` fits them to it.

The arithmetic is exact rationals throughout, so these are asked of the
function directly: a Fraction in, a Fraction out, and no book needed to say
what 39.13 split three ways is.
"""

from fractions import Fraction

from services.invoice_renderer import figures_that_add_up


def _cents(*values):
    return [Fraction(value, 100) for value in values]


class TestTheColumnAddsUp:
    def test_three_lines_of_a_third_of_a_cent(self):
        """13.0434… × 3, against a page tax of 39.13."""
        parts = [Fraction(1304347826087, 100000000000)] * 3

        fitted = figures_that_add_up(parts, Fraction(3913, 100), 100)

        assert sum(fitted, Fraction(0)) == Fraction(3913, 100)
        assert sorted(fitted) == _cents(1304, 1304, 1305)

    def test_the_odd_unit_goes_to_the_largest_remainder(self):
        parts = [Fraction(101, 100), Fraction(1019, 1000)]

        fitted = figures_that_add_up(parts, Fraction(203, 100), 100)

        # 1.01 exactly, and 1.019 — the second is the one carrying a
        # remainder, so it is the one rounded up.
        assert fitted == _cents(101, 102)

    def test_a_currency_with_no_minor_unit(self):
        """A yen has no hundredths, so a unit is a whole yen."""
        parts = [Fraction(207, 2), Fraction(207, 2)]

        fitted = figures_that_add_up(parts, Fraction(207), 1)

        assert sum(fitted, Fraction(0)) == Fraction(207)
        assert sorted(fitted) == [Fraction(103), Fraction(104)]

    def test_nothing_to_fit_is_nothing(self):
        assert figures_that_add_up([], Fraction(0), 100) == []

    def test_parts_that_already_add_up_are_left_alone(self):
        parts = _cents(4500, 7200)

        assert figures_that_add_up(parts, Fraction(117), 100) == parts


class TestALineWhoseFigureIsNegative:
    """A page mixing signs — a negative quantity beside a positive one.

    Truncating toward zero rather than flooring leaves a negative part with a
    remainder in (-1, 0], which sorts as the *largest* and takes the spare
    unit that belongs to the line with the biggest fraction. Measured on the
    pair below: the negative line printed 0.01 for a figure of -0.001, and
    the import recomputes each line's figure and compares it exactly, so the
    page came back refused by the command that wrote it.
    """

    def test_the_spare_unit_goes_to_the_largest_fraction_not_the_negative(
            self):
        parts = [Fraction(130485, 10000), Fraction(-1, 1000)]

        fitted = figures_that_add_up(parts, Fraction(1305, 100), 100)

        assert sum(fitted, Fraction(0)) == Fraction(1305, 100)
        assert fitted == [Fraction(1305, 100), Fraction(0)]

    def test_a_page_of_negative_lines_still_adds_up(self):
        parts = [Fraction(-1304, 100), Fraction(-13043, 1000)]

        fitted = figures_that_add_up(parts, Fraction(-2608, 100), 100)

        assert sum(fitted, Fraction(0)) == Fraction(-2608, 100)


class TestWhichLinesTakeTheOddUnits:
    """Flooring every line leaves the column under the whole by a unit or
    two, and those units go to the lines with the largest fractions.

    Never more than one for any line, and never below zero, because the whole is
    the lines' own sum rounded: it sits within half a unit of them, and each
    floor sits under its own line. Which is why there is one pass and no
    limit to check — see `figures_that_add_up`.
    """

    def test_a_line_carrying_no_tax_is_never_handed_any(self):
        """A `taxable: false` line has no tax and no `breakdown:` block under
        it, so a unit landing there states tax the line does not carry and
        that nothing on the page adds up to. Two taxable lines of 0.9975
        beside one that is not: both units go to the two that hold tax."""
        parts = [Fraction(9975, 10000), Fraction(9975, 10000), Fraction(0)]

        fitted = figures_that_add_up(parts, Fraction(2), 100)

        assert fitted[2] == 0
        assert sum(fitted, Fraction(0)) == Fraction(2)

    def test_every_line_flooring_to_nothing_still_adds_to_the_page(self):
        """Two ¥10 lines at 5 per cent: half a yen each, and a page tax
        of ¥1. Both floor to nothing, so a rule that would not raise a line
        sitting at zero left the column at nothing while the page said 1
        — and the import recomputes the same fit, so nothing contradicts the
        page."""
        parts = [Fraction(1, 2), Fraction(1, 2)]

        fitted = figures_that_add_up(parts, Fraction(1), 1)

        assert sum(fitted, Fraction(0)) == Fraction(1)
        assert sorted(fitted) == [Fraction(0), Fraction(1)]

    def test_the_same_where_a_currency_has_cents(self):
        parts = [Fraction(5, 1000), Fraction(5, 1000)]

        fitted = figures_that_add_up(parts, Fraction(1, 100), 100)

        assert sum(fitted, Fraction(0)) == Fraction(1, 100)

    def test_a_page_carrying_no_tax_at_all_is_left_alone(self):
        parts = [Fraction(0), Fraction(0)]

        assert figures_that_add_up(parts, Fraction(0), 100) == [0, 0]

    def test_the_three_line_page_that_was_measured(self):
        """The figures from the probe: three lines of one tax account, whose
        own rounded total is 1.43 — two lines take a unit and the exact one
        takes none."""
        parts = [Fraction(6294, 10000), Fraction(6, 10), Fraction(1998, 10000)]

        fitted = figures_that_add_up(parts, Fraction(143, 100), 100)

        assert sum(fitted, Fraction(0)) == Fraction(143, 100)
        assert fitted == _cents(63, 60, 20)
