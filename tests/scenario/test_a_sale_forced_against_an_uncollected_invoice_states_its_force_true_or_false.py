"""A sale forced against an uncollected invoice states its force `#True` or `#False`.

The rules are the author's, set after Q-054 shipped with gnucash-plaintext's
own `bool` keys read and written as text: `cost_basis_force` is `#True` or
`#False` when stored and when exported, a file may also write `#True` as
`"true"`, `"yes"` or `1` and `#False` as `"false"`, `"no"` or `0`, and `""`,
a word without quotes such as `true` or `yes`, and any other value on it is
refused.

The case is `test_cost_basis_must_be_collected.py`'s: INV-USD-001, 100.00 USD
posted at 1.40, not yet collected, and 40.00 USD sold against its cost basis.
The invoice's receivable holds no dollars to sell, so the sale is refused
unless it states `cost_basis_force` true, which says the money is in hand
anyway. Step 1 imports `tests/fixtures/fx_usd_invoice_cad_income.txt` into a
new book; step 2 imports the sale; every step after it restates the sale
with `--strategy update`. The invoice's cost basis is a split GnuCash gave a
guid of its own, so the fixtures write it `{basis}` and the test fills it in
from `fx-balances`. After each step, `export` writes the sale as the fixture
named states, and the import prints exactly the warnings and the refusal
stated here. A refused step leaves the book as the step before it.

Step 2, `tests/fixtures/a_forced_sale_2_forty_usd_sold_stating_force_as_the_text_true.txt`:

2026-02-01 * "Sell 40 USD"
	guid: "0c0c0c0c0c0c0c0c0c0c0c0c0c0c2000"
	currency.mnemonic: "CAD"
	Assets:Bank:USD -40.00 USD
		guid: "0c0c0c0c0c0c0c0c0c0c0c0c0c0c1000"
		account.commodity.mnemonic: "USD"
		share_price: "1.40"
		value: "-56.00"
		cost_basis_split_guid: "{basis}"
		cost_basis_force: "true"
	Assets:Bank 54.80 CAD
		guid: "0c0c0c0c0c0c0c0c0c0c0c0c0c0c1001"
		account.commodity.mnemonic: "CAD"
		share_price: "1"
		value: "54.80"
	Income:FX Gain $residual$ CAD
		guid: "0c0c0c0c0c0c0c0c0c0c0c0c0c0c1002"
		account.commodity.mnemonic: "CAD"

Exported, `a_forced_sale_2_forty_usd_sold_stating_force_as_the_text_true_exported.txt`;
no warning:

2026-02-01 * "Sell 40 USD"
	guid: "0c0c0c0c0c0c0c0c0c0c0c0c0c0c2000"
	currency.mnemonic: "CAD"
	Assets:Bank 54.80 CAD
		guid: "0c0c0c0c0c0c0c0c0c0c0c0c0c0c1001"
	Income:FX Gain 1.20 CAD
		guid: "0c0c0c0c0c0c0c0c0c0c0c0c0c0c1002"
		took_the_residual: #True
	Assets:Bank:USD -40.00 USD
		guid: "0c0c0c0c0c0c0c0c0c0c0c0c0c0c1000"
		account.commodity.mnemonic: "USD"
		share_price: "1.4"
		value: "-56.00"
		cost_basis_force: #True
		cost_basis_split_guid: "{basis}"

Steps 3 to 7 restate the sale as that export writes it, with its
`cost_basis_force:` line as the step states:

Step 3, `a_forced_sale_3_stating_force_as_the_text_yes.txt`: `"yes"`.
Exported as step 2's, `#True`; no warning.

Step 4, `a_forced_sale_4_stating_force_as_1.txt`: `1`. Exported as step 2's,
`#True`; no warning.

Step 5, `a_forced_sale_5_stating_force_empty.txt`: `""`. Refused:

  'Assets:Bank:USD -40.00 USD': `cost_basis_force` is gnucash-plaintext's own key, so `cost_basis_force: ""` is refused. It states nothing; to remove the key, write `cost_basis_force: $None$`.

Step 6, `a_forced_sale_6_stating_force_as_the_text_maybe.txt`: `"maybe"`.
Refused:

  'Assets:Bank:USD -40.00 USD': `cost_basis_force` is gnucash-plaintext's own key, so `cost_basis_force: "maybe"` is refused. It holds #True or #False, which may also be written "true", "yes" or 1, and "false", "no" or 0.

After each of steps 5 and 6 the book is step 4's: exported as step 2's.

Step 7, `a_forced_sale_7_stating_force_as_the_text_no.txt`: `"no"`. Exported
as `a_forced_sale_7_stating_force_as_the_text_no_exported.txt`, step 2's
export with `cost_basis_force: #False`; no warning. The sale is not refused
for it: an edit that leaves every cost basis as it was is accepted (Q-048),
and the refusal of a sale against an uncollected invoice is asked of a sale
being imported.

Steps 8 to 15 restate the sale the same way, with its `cost_basis_force:`
line as the step states. Each accepted step exports as step 2's, `#True`,
or step 7's, `#False`; none warns.

Step 8, `a_forced_sale_8_stating_force_as_the_text_1.txt`: `"1"`, `#True`.

Step 9, `a_forced_sale_9_stating_force_as_the_text_0.txt`: `"0"`, `#False`.

Step 10, `a_forced_sale_10_stating_force_true.txt`: `#True`, `#True`.

Step 11, `a_forced_sale_11_stating_force_as_the_text_false.txt`: `"false"`,
`#False`.

Step 12, `a_forced_sale_12_stating_force_as_0.txt`: `0`, `#False`.

Step 13, `a_forced_sale_13_stating_force_false.txt`: `#False`, `#False`.

Step 14, `a_forced_sale_14_stating_force_as_a_bare_true.txt`: `true`, a word
without quotes. Refused, and the book is step 13's:

  'Assets:Bank:USD -40.00 USD': `cost_basis_force` is gnucash-plaintext's own key, so `cost_basis_force: true` is refused. It holds #True or #False, which may also be written "true", "yes" or 1, and "false", "no" or 0.

Step 15, `a_forced_sale_15_stating_force_as_a_bare_yes.txt`: `yes`, a word
without quotes. Refused as step 14 is, stating `cost_basis_force: yes`.
"""

import re
from pathlib import Path

from click.testing import CliRunner

from tests.conftest import _run

FIXTURES = Path('tests/fixtures')
RATES = 'tests/fixtures/fx_rates_usd_dated.yaml'

STEPS = [
    None,
    'a_forced_sale_2_forty_usd_sold_stating_force_as_the_text_true',
    'a_forced_sale_3_stating_force_as_the_text_yes',
    'a_forced_sale_4_stating_force_as_1',
    'a_forced_sale_5_stating_force_empty',
    'a_forced_sale_6_stating_force_as_the_text_maybe',
    'a_forced_sale_7_stating_force_as_the_text_no',
    'a_forced_sale_8_stating_force_as_the_text_1',
    'a_forced_sale_9_stating_force_as_the_text_0',
    'a_forced_sale_10_stating_force_true',
    'a_forced_sale_11_stating_force_as_the_text_false',
    'a_forced_sale_12_stating_force_as_0',
    'a_forced_sale_13_stating_force_false',
    'a_forced_sale_14_stating_force_as_a_bare_true',
    'a_forced_sale_15_stating_force_as_a_bare_yes',
]

REFUSED = {5, 6, 14, 15}

FORCED = 'a_forced_sale_2_forty_usd_sold_stating_force_as_the_text_true_exported'
NOT_FORCED = 'a_forced_sale_7_stating_force_as_the_text_no_exported'
SALE = 'Assets:Bank:USD -40.00 USD'


def _refused(stated):
    return (f"{SALE!r}: `cost_basis_force` is gnucash-plaintext's own key, "
            f'so `cost_basis_force: {stated}` is refused.')


HOLDS = (' It holds #True or #False, which may also be written "true", "yes" or 1, '
         'and "false", "no" or 0.')
EMPTY = _refused('""') + ' It states nothing; to remove the key, write `cost_basis_force: $None$`.'
MAYBE = _refused('"maybe"') + HOLDS
BARE_TRUE = _refused('true') + HOLDS
BARE_YES = _refused('yes') + HOLDS


def _warnings(output):
    return [line.strip() for line in output.splitlines() if line.strip().startswith('⚠')]


def _filled(name, basis):
    return (FIXTURES / f'{name}.txt').read_text().replace('{basis}', basis)


def _sale(book, tmp_path):
    """The sale as `export` writes it, or None where the book holds no sale yet."""
    out = tmp_path / 'out.txt'
    exported = _run(CliRunner(), 'export', str(book), str(out))
    assert exported.exit_code == 0, exported.output
    found = re.search(r'2026-02-01 \* "Sell 40 USD"\n(?:\t[^\n]*\n)*', out.read_text())
    return found.group(0) if found else None


def _steps(tmp_path, last):
    """The sale as exported before step `last` and after it, that step's import output, and the cost basis guid."""
    book = tmp_path / 'book.gnucash'
    made = _run(CliRunner(), 'import', '--new', str(book),
                'tests/fixtures/fx_usd_invoice_cad_income.txt',
                '--include-business-objects', '--fx-rates', RATES)
    assert made.exit_code == 0, made.output
    listing = _run(CliRunner(), 'fx-balances', str(book))
    basis = re.search(r'\b([0-9a-f]{32})\b', listing.output).group(1)
    for number in range(2, last + 1):
        if number == last:
            before = _sale(book, tmp_path)
        ledger = tmp_path / f'{STEPS[number - 1]}.txt'
        ledger.write_text(_filled(STEPS[number - 1], basis))
        args = (['import', str(book), str(ledger)] if number == 2
                else ['import', '--strategy', 'update', str(book), str(ledger)])
        done = _run(CliRunner(), *args)
        if number < last:
            assert (done.exit_code != 0 if number in REFUSED
                    else done.exit_code == 0 and 'Errors:       0' in done.output), done.output
    return before, _sale(book, tmp_path), done, basis


def _force(sale):
    """What the sale states for `cost_basis_force:`, or None where it states none."""
    found = re.search(r'\n\t\tcost_basis_force: ([^\n]*)\n', sale)
    return found.group(1) if found else None


def _accepted(done):
    assert done.exit_code == 0 and 'Errors:       0' in done.output, done.output
    assert _warnings(done.output) == [], done.output


def _refused_with(done, refusal):
    assert done.exit_code != 0, done.output
    assert refusal in done.output, done.output
    assert _warnings(done.output) == [], done.output


def test_2_cost_basis_force_the_text_true_forces_the_sale_and_is_exported_as_true(tmp_path):
    """The text "true" on `cost_basis_force` forces the sale and is read as #True.

    `import` of the 40.00 USD sale against the uncollected invoice's cost basis,
    stating `cost_basis_force: "true"`. The key holds a bool, so the text true
    is stored as #True. The sale is accepted, and exported with #True.
    """
    before, after, done, basis = _steps(tmp_path, 2)
    _accepted(done)
    assert before is None
    assert _force(after) == '#True'
    assert after == _filled(FORCED, basis)


def test_3_cost_basis_force_the_text_yes_is_stored_and_exported_as_true(tmp_path):
    """The text "yes" on `cost_basis_force` is read as #True.

    `import --strategy update` of the sale, stating `cost_basis_force: "yes"`.
    It is stored as #True and exported as #True. The force stays #True.
    """
    before, after, done, basis = _steps(tmp_path, 3)
    _accepted(done)
    assert _force(before) == '#True'
    assert _force(after) == '#True'
    assert after == _filled(FORCED, basis)


def test_4_cost_basis_force_1_is_stored_and_exported_as_true(tmp_path):
    """The number 1 on `cost_basis_force` is read as #True.

    `import --strategy update` of the sale, stating `cost_basis_force: 1`. It is
    stored as #True and exported as #True. The force stays #True.
    """
    before, after, done, basis = _steps(tmp_path, 4)
    _accepted(done)
    assert _force(before) == '#True'
    assert _force(after) == '#True'
    assert after == _filled(FORCED, basis)


def test_5_cost_basis_force_empty_is_refused(tmp_path):
    """The empty text on `cost_basis_force` is refused, and the force is kept.

    `import --strategy update` of the sale, stating `cost_basis_force: ""`. The
    empty text states nothing, and only `$None$` removes a key, so the file is
    refused whole and the force stays #True.
    """
    before, after, done, basis = _steps(tmp_path, 5)
    _refused_with(done, EMPTY)
    assert _force(before) == '#True'
    assert _force(after) == '#True'
    assert after == before == _filled(FORCED, basis)


def test_6_cost_basis_force_a_text_that_is_neither_true_nor_false_is_refused(tmp_path):
    """A text that is neither true nor false on `cost_basis_force` is refused.

    `import --strategy update` of the sale, stating `cost_basis_force: "maybe"`.
    It is no spelling of #True or #False, so the file is refused whole and the
    force stays #True.
    """
    before, after, done, basis = _steps(tmp_path, 6)
    _refused_with(done, MAYBE)
    assert _force(before) == '#True'
    assert _force(after) == '#True'
    assert after == before == _filled(FORCED, basis)


def test_7_cost_basis_force_the_text_no_is_stored_and_exported_as_false(tmp_path):
    """The text "no" on `cost_basis_force` is read as #False.

    `import --strategy update` of the sale, stating `cost_basis_force: "no"`. It
    is stored as #False and exported as #False. The force goes from #True to
    #False.
    """
    before, after, done, basis = _steps(tmp_path, 7)
    _accepted(done)
    assert _force(before) == '#True'
    assert _force(after) == '#False'
    assert after == _filled(NOT_FORCED, basis)


def test_8_cost_basis_force_the_text_1_is_stored_and_exported_as_true(tmp_path):
    """The text "1" on `cost_basis_force` is read as #True.

    `import --strategy update` of the sale, stating `cost_basis_force: "1"`. It
    is stored as #True and exported as #True. The force goes from #False to
    #True.
    """
    before, after, done, basis = _steps(tmp_path, 8)
    _accepted(done)
    assert _force(before) == '#False'
    assert _force(after) == '#True'
    assert after == _filled(FORCED, basis)


def test_9_cost_basis_force_the_text_0_is_stored_and_exported_as_false(tmp_path):
    """The text "0" on `cost_basis_force` is read as #False.

    `import --strategy update` of the sale, stating `cost_basis_force: "0"`. It
    is stored as #False and exported as #False. The force goes from #True to
    #False.
    """
    before, after, done, basis = _steps(tmp_path, 9)
    _accepted(done)
    assert _force(before) == '#True'
    assert _force(after) == '#False'
    assert after == _filled(NOT_FORCED, basis)


def test_10_cost_basis_force_true_is_stored_and_exported_as_true(tmp_path):
    """#True on `cost_basis_force` is stored and exported as #True.

    `import --strategy update` of the sale, stating `cost_basis_force: #True`,
    a bool. The force goes from #False to #True.
    """
    before, after, done, basis = _steps(tmp_path, 10)
    _accepted(done)
    assert _force(before) == '#False'
    assert _force(after) == '#True'
    assert after == _filled(FORCED, basis)


def test_11_cost_basis_force_the_text_false_is_stored_and_exported_as_false(tmp_path):
    """The text "false" on `cost_basis_force` is read as #False.

    `import --strategy update` of the sale, stating `cost_basis_force: "false"`.
    It is stored as #False and exported as #False. The force goes from #True to
    #False.
    """
    before, after, done, basis = _steps(tmp_path, 11)
    _accepted(done)
    assert _force(before) == '#True'
    assert _force(after) == '#False'
    assert after == _filled(NOT_FORCED, basis)


def test_12_cost_basis_force_0_is_stored_and_exported_as_false(tmp_path):
    """The number 0 on `cost_basis_force` is read as #False.

    `import --strategy update` of the sale, stating `cost_basis_force: 0`. It is
    stored as #False and exported as #False. The force stays #False.
    """
    before, after, done, basis = _steps(tmp_path, 12)
    _accepted(done)
    assert _force(before) == '#False'
    assert _force(after) == '#False'
    assert after == _filled(NOT_FORCED, basis)


def test_13_cost_basis_force_false_is_stored_and_exported_as_false(tmp_path):
    """#False on `cost_basis_force` is stored and exported as #False.

    `import --strategy update` of the sale, stating `cost_basis_force: #False`,
    a bool. The force stays #False.
    """
    before, after, done, basis = _steps(tmp_path, 13)
    _accepted(done)
    assert _force(before) == '#False'
    assert _force(after) == '#False'
    assert after == _filled(NOT_FORCED, basis)


def test_14_cost_basis_force_a_bare_true_is_refused(tmp_path):
    """A bare `true` on `cost_basis_force` is refused, and the force is kept.

    `import --strategy update` of the sale, stating `cost_basis_force: true`, a
    word without quotes. The file is refused whole, and the force stays #False.
    """
    before, after, done, basis = _steps(tmp_path, 14)
    _refused_with(done, BARE_TRUE)
    assert _force(before) == '#False'
    assert _force(after) == '#False'
    assert after == before == _filled(NOT_FORCED, basis)


def test_15_cost_basis_force_a_bare_yes_is_refused(tmp_path):
    """A bare `yes` on `cost_basis_force` is refused, and the force is kept.

    `import --strategy update` of the sale, stating `cost_basis_force: yes`, a
    word without quotes. The file is refused whole, and the force stays #False.
    """
    before, after, done, basis = _steps(tmp_path, 15)
    _refused_with(done, BARE_YES)
    assert _force(before) == '#False'
    assert _force(after) == '#False'
    assert after == before == _filled(NOT_FORCED, basis)
