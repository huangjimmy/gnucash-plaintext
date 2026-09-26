"""Money is rounded by GnuCash's own rule, and this asks GnuCash what it is.

A page drawn from GnuCash's book states GnuCash's figures, so where it rounds
money it has to round the way GnuCash rounds it. GnuCash exports that rule:
`gnc_numeric_convert(value, denom, how)` with `GNC-RND-ROUND`, which sends a
tie to the nearest even. Its own report code calls it — `report-utilities.scm`
on 3.4, `commodity-utilities.scm` on 5.10 — and so should this one, rather than
re-implementing a rounding rule in Scheme arithmetic and hoping the two agree.

They did not agree. Rounding half-up instead put `worth 1386.47 CAD` in a
working beside `value: "1386.46"` on the same holding's account line, and the
gain built on it left the two sides of a balance sheet a cent apart.

This asks the questions a scenario test cannot, because every book's figures
divide cleanly long before they reach a tie:

- is the rule reachable from where the report runs, on every supported build;
- what it answers for an exact half, which is the only case two rules differ on;
- what it answers for a *negative* exact half, which is where GnuCash 3.4 is
  known to lose the sign under `HALF_UP` (CLAUDE.md finding 22) — a workaround
  this report carries, and which may not be needed under GnuCash's own rule.

No book and no commodity: the rule is a property of the engine, and asking it
that way is what lets this run everywhere and fail for one reason only.
"""

from pathlib import Path

import pytest

from infrastructure.gnucash.engine import load_gnc_engine
from infrastructure.guile import load_guile

# 13.865 and its negative: an exact half at a currency's two places. Half-up
# answers 13.87; a tie to the nearest even answers 13.86.
A_HALF = (13865, 1000)
CENTS = 100

# What one currency's cost bases came to on a real book, measured by
# `tests/research/how_big_a_summed_cost_basis_cost_gets_probe.py`: 14,067.49
# CAD, carried as a 75-bit numerator over a 62-bit denominator because four of
# the five bases behind it had been drawn part of the way. `INT64_MAX` is 63
# bits.
A_MEASURED_OVERSIZED_COST = (33127907093144872216827, 2354926672531400000)


# Where GnuCash keeps the rounding rule, and it is in two places at once.
#
# The `GNC-RND-*` constants are Scheme, exported by the engine module — from
# `engine.scm` itself on 3.4, from `(gnucash engine gnc-numeric)` on 5.x. The
# procedures that use them are C, wrapped by SWIG into a module called
# `(sw_engine)`, which `(gnucash engine)` imports without re-exporting. Asking
# only for `(gnucash engine)` therefore binds the constants and none of the
# procedures — measured on 3.4 as `(#f #f #t)`.
#
# `(sw_engine)` is made by `load-extension "libgncmod-engine"` rather than
# living in a file, so looking for one on disk finds nothing and proves
# nothing. Each name is tried and a failure passed over, as the report modules
# are: a build has one spelling or the other.
#
# `module-use!` rather than `use-modules`, which is a macro that has to appear
# at the top level and will not expand inside the `catch` this needs.
#
# The engine module comes first, and on 3.4 it has to. `(sw_engine)` does not
# exist until something loads it: `engine.scm` runs `(load-extension
# "libgncmod-engine" "scm_init_sw_engine_module")`, and that registration is
# what puts the module on the map. Asked for first, `(sw_engine)` resolves to
# nothing, the failure is swallowed here, and the question that follows finds
# `gnc-numeric-convert` unbound — while the next test in the same process finds
# it fine, the module having been registered by then. Measured that way round:
# whichever test ran first failed, whatever it was asking.
_ENGINE_MODULES = (
    "'(gnucash engine)",
    "'(sw_engine)",
    "'(gnucash engine gnc-numeric)",
)


def _answers(tmp_path: Path, scheme: str) -> str:
    """Evaluate `scheme`, which writes its answer to the file it is passed.

    Asked with GnuCash's engine module imported, which is how its own reports
    reach these names. A bare interpreter has none of them, and asking one
    says nothing about the environment a report is evaluated in.

    **The importing is its own evaluation, and on GnuCash 3.4 it has to be.**
    There, the first `scm_eval_string` of a process cannot see the SWIG-wrapped
    procedures and the second can: measured, whichever test ran first failed
    with `gnc-numeric-convert` unbound while the next one called it and got the
    right answer, whatever either was asking. `(defined? 'gnc-numeric-convert)`
    answering `#f` on that build is the same effect — asked too early rather
    than answered wrongly.

    It costs the report nothing, which is why the whole suite draws its pages
    on 3.4: by the time this tool's `.scm` is evaluated the report modules have
    been loaded and several evaluations have gone before it. It costs a harness
    that loads the engine and evaluates once, which is what this is.
    """
    load_gnc_engine()
    lib = load_guile()
    out = tmp_path / 'answer.txt'
    errors = tmp_path / 'errors.txt'

    def evaluate(expression: str) -> None:
        lib.scm_eval_string(lib.scm_from_utf8_string(expression.encode('utf-8')))

    importing = ' '.join(
        f'(catch #t'
        f'  (lambda () (module-use! (current-module) (resolve-interface {module})))'
        f'  (lambda (key . args) #f))'
        for module in _ENGINE_MODULES)
    evaluate(f'(begin {importing} #t)')
    evaluate(
        f'(catch #t'
        f'  (lambda () (call-with-output-file "{out}"'
        f'               (lambda (port) (display {scheme} port))) #t)'
        f'  (lambda (key . args)'
        f'    (call-with-output-file "{errors}"'
        f'      (lambda (port) (display (list key args) port)))))')
    if errors.exists() and errors.read_text(encoding='utf-8').strip():
        pytest.fail(errors.read_text(encoding='utf-8').strip()[:600])
    assert out.exists(), 'the expression wrote no answer'
    return out.read_text(encoding='utf-8').strip()


def _rounded_to_cents(tmp_path: Path, numerator: int) -> str:
    """`numerator`/1000 rounded to cents by GnuCash, as an exact value.

    The answer is the value, not the pair it arrives in: `gnc-numeric-convert`
    returns a fraction in lowest terms rather than one over the denominator it
    was asked for, so 13.86 comes back as 693/50. Comparing the pair compares
    spellings and fails on an answer that is right.
    """
    return _answers(
        tmp_path,
        f'(let ((rounded (gnc-numeric-convert'
        f'                 (gnc-numeric-create {numerator} {A_HALF[1]})'
        f'                 {CENTS} GNC-RND-ROUND)))'
        f'  (/ (gnc-numeric-num rounded) (gnc-numeric-denom rounded)))')


def test_an_exact_half_goes_to_the_nearest_even(tmp_path):
    """13.865 at two places is 13.86, not 13.87 — the tie every book avoids."""
    assert _rounded_to_cents(tmp_path, A_HALF[0]) == '693/50'


def test_a_figure_too_big_for_the_engines_arguments(tmp_path):
    """A cost summed across several part-drawn bases outgrows a 64-bit argument.

    `plaintext:basis-cost` is one exact fraction added up over every cost basis
    of a currency and side, and a cost is a value over an amount.

    An *untouched* basis costs nothing to add: its balance is still its own
    amount, so the division cancels and the term is exactly the money the
    currency came in for. It is a basis drawn **part** of the way that grows —
    the balance is no longer the amount, nothing cancels, and the term keeps a
    denominator about the size of the original amount in cents. Several of
    those add by lowest common multiple.

    The figure below is measured, not chosen to be large. It is the US dollar
    cost the report reaches by adding up the rows
    `cost_basis_items_by_currency_and_side` returns, for a book
    of five consulting payments in US dollars, at the four-decimal rates a bank
    publishes, with part of each later spent:
    `tests/research/how_big_a_summed_cost_basis_cost_gets_probe.py` builds it
    and reports the total after every basis — 30 bits, 42, 57, then 69 at the
    fourth, which is already past `INT64_MAX`, and 75 at the fifth. Fourteen
    thousand dollars carried in seventy-five bits.

    `gnc-numeric-create` takes two `gint64` and refuses it: measured on 3.4 and
    5.10 alike, it answers `Value out of range -9223372036854775808 to
    9223372036854775807`, and a page that rounds a figure that size through the
    engine does not render at all — on a book whose cost bases match its
    holdings, which is the book this feature is for.

    **GnuCash never meets this, and the 64-bit argument is not its defect.** A
    `gnc_numeric` is an int64 pair, and every figure GnuCash stores is already
    at its commodity's smallest unit, so its denominators stay at 100 and a
    number this shape is one it would never construct. This one is built here,
    by adding exact rationals rather than rounding as GnuCash does.

    So the report applies GnuCash's rule instead of calling it, with Scheme's
    `round` on the exact rational: the same tie to the nearest even, no ceiling.
    This is that rounding, asked of the figure the engine will not take.
    """
    numerator, denominator = A_MEASURED_OVERSIZED_COST
    answer = _answers(
        tmp_path,
        f'(let* ((figure (/ {numerator} {denominator}))'
        f'       (rounded (/ (round (* figure {CENTS})) {CENTS})))'
        f'  rounded)')

    assert answer == '1406749/100', answer


def test_a_negative_exact_half_keeps_its_sign(tmp_path):
    """Where `HALF_UP` loses it on 3.4, which is why the report rounds a magnitude.

    If GnuCash's own rule keeps the sign on every build, the report has no
    reason to take a figure apart and put it back together.
    """
    assert _rounded_to_cents(tmp_path, -A_HALF[0]) == '-693/50'
