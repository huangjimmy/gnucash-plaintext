"""gnucash-plaintext's own keys hold what they hold, and only `$None$` removes one.

The rules are the author's, set after Q-054 shipped with `""` removing a key
and with `took_the_residual` stored as the text `"true"`: only `$None$`
unquoted removes a key; `""` states nothing, so it is refused on a key of
gnucash-plaintext's own; a `bool` key is `#True` or `#False` when stored and
when exported, and a file may also write `#True` as `"true"`, `"yes"` or `1`,
and `#False` as `"false"`, `"no"` or `0`.

The case is a CAD book that buys 1,000.00 USD at 1.30 and sells every dollar
at 1.40, the 100.00 between them booked with `$residual$`, which marks the gain
split `took_the_residual`. Step 1 is imported into a new book; every step
after it with `--strategy update` over the book the step before left. After
each, `export` writes the purchase and the sale as the fixture named states,
and the import prints exactly the warnings and the refusal stated here. A
refused step leaves the book as the step before it left it.

Step 1, `tests/fixtures/a_gain_split_s_mark_1_a_thousand_usd_bought_and_sold.txt`:
the accounts, the opening capital, and

2026-02-01 * "Buy 1,000.00 USD at 1.30"
	guid: "0b0b0b0b0b0b0b0b0b0b0b0b0b0b2000"
	currency.mnemonic: "CAD"
	Assets:USD Bank 1000.00 USD
		guid: "0b0b0b0b0b0b0b0b0b0b0b0b0b0b1000"
		account.commodity.mnemonic: "USD"
		share_price: "13/10"
		value: "1300.00"
	Assets:CAD Bank -1300.00 CAD
		guid: "0b0b0b0b0b0b0b0b0b0b0b0b0b0b1001"

2026-06-01 * "Sell every dollar at 1.40"
	guid: "0b0b0b0b0b0b0b0b0b0b0b0b0b0b2001"
	currency.mnemonic: "CAD"
	Assets:USD Bank -1000.00 USD
		guid: "0b0b0b0b0b0b0b0b0b0b0b0b0b0b1002"
		account.commodity.mnemonic: "USD"
		share_price: "13/10"
		value: "-1300.00"
		cost_basis_split_guid: "0b0b0b0b0b0b0b0b0b0b0b0b0b0b1000"
	Assets:CAD Bank 1400.00 CAD
		guid: "0b0b0b0b0b0b0b0b0b0b0b0b0b0b1003"
	Income:FX Gain $residual$ CAD
		guid: "0b0b0b0b0b0b0b0b0b0b0b0b0b0b1004"

Exported, `a_gain_split_s_mark_1_a_thousand_usd_bought_and_sold_exported.txt`;
no warning:

2026-02-01 * "Buy 1,000.00 USD at 1.30"
	guid: "0b0b0b0b0b0b0b0b0b0b0b0b0b0b2000"
	currency.mnemonic: "CAD"
	Assets:USD Bank 1000.00 USD
		guid: "0b0b0b0b0b0b0b0b0b0b0b0b0b0b1000"
		account.commodity.mnemonic: "USD"
		share_price: "1.30000"
		value: "1300.00"
		cost_basis_balance: "0.00"
	Assets:CAD Bank -1300.00 CAD
		guid: "0b0b0b0b0b0b0b0b0b0b0b0b0b0b1001"
2026-06-01 * "Sell every dollar at 1.40"
	guid: "0b0b0b0b0b0b0b0b0b0b0b0b0b0b2001"
	currency.mnemonic: "CAD"
	Assets:CAD Bank 1400.00 CAD
		guid: "0b0b0b0b0b0b0b0b0b0b0b0b0b0b1003"
	Assets:USD Bank -1000.00 USD
		guid: "0b0b0b0b0b0b0b0b0b0b0b0b0b0b1002"
		account.commodity.mnemonic: "USD"
		share_price: "1.30000"
		value: "-1300.00"
		cost_basis_split_guid: "0b0b0b0b0b0b0b0b0b0b0b0b0b0b1000"
	Income:FX Gain -100.00 CAD
		guid: "0b0b0b0b0b0b0b0b0b0b0b0b0b0b1004"
		took_the_residual: #True

Steps 2 to 10 each restate the sale as that export writes it, with the gain
split's last line as the step states:

	Income:FX Gain -100.00 CAD
		guid: "0b0b0b0b0b0b0b0b0b0b0b0b0b0b1004"
		took_the_residual: <as the step states>

Step 2, `a_gain_split_s_mark_2_stated_false.txt`: `#False`. Exported as
`a_gain_split_s_mark_2_stated_false_exported.txt`, which is step 1's export
with `took_the_residual: #False`; no warning.

Step 3, `a_gain_split_s_mark_3_stated_as_the_text_true.txt`: `"true"`.
Exported as step 1's, `#True`; no warning.

Step 4, `a_gain_split_s_mark_4_stated_as_0.txt`: `0`. Exported as step 2's,
`#False`; no warning.

Step 5, `a_gain_split_s_mark_5_stated_as_1.txt`: `1`. Exported as step 1's,
`#True`; no warning.

Step 6, `a_gain_split_s_mark_6_stated_as_the_text_false.txt`: `"false"`.
Exported as step 2's, `#False`; no warning.

Step 7, `a_gain_split_s_mark_7_stated_as_the_text_yes.txt`: `"yes"`.
Exported as step 1's, `#True`; no warning.

Step 8, `a_gain_split_s_mark_8_stated_empty.txt`: `""`. Refused:

  'Income:FX Gain -100.00 CAD': `took_the_residual` is gnucash-plaintext's own key, so `took_the_residual: ""` is refused. It states nothing; to remove the key, write `took_the_residual: $None$`.

The book is step 7's: exported as step 1's, `#True`.

Step 9, `a_gain_split_s_mark_9_stated_as_the_text_maybe.txt`: `"maybe"`.
Refused:

  'Income:FX Gain -100.00 CAD': `took_the_residual` is gnucash-plaintext's own key, so `took_the_residual: "maybe"` is refused. It holds #True or #False, which may also be written "true", "yes" or 1, and "false", "no" or 0.

The book is step 7's: exported as step 1's, `#True`.

Step 10, `a_gain_split_s_mark_10_removed.txt`: `$None$`. Exported as
`a_gain_split_s_mark_10_removed_exported.txt`, which is step 1's export with
no `took_the_residual:` line; no warning.

Step 11, `a_gain_split_s_mark_11_the_purchase_s_balance_stated_empty.txt`:
the purchase restated as step 1's export writes it, with

		cost_basis_balance: ""

Refused:

  'Assets:USD Bank 1000.00 USD': `cost_basis_balance` is gnucash-plaintext's own key, so `cost_basis_balance: ""` is refused. It states nothing; to remove the key, write `cost_basis_balance: $None$`.

Step 12, `a_gain_split_s_mark_12_the_sale_s_cost_basis_stated_empty.txt`:
the sale restated with

		cost_basis_split_guid: ""

on its US dollar split. Refused:

  'Assets:USD Bank -1000.00 USD': `cost_basis_split_guid` is gnucash-plaintext's own key, so `cost_basis_split_guid: ""` is refused. It states nothing; to remove the key, write `cost_basis_split_guid: $None$`.

Step 13, `a_gain_split_s_mark_13_the_sale_s_cost_stated_empty.txt`: the sale
restated with

		cost_basis_cost: ""

on its US dollar split. Refused:

  'Assets:USD Bank -1000.00 USD': `cost_basis_cost` is gnucash-plaintext's own key, so `cost_basis_cost: ""` is refused. It states nothing; to remove the key, write `cost_basis_cost: $None$`.

After each of steps 11 to 13 the book is step 10's.

Step 14, `a_gain_split_s_mark_14_keys_of_the_user_s_own_stating_true_yes_and_0.txt`:
the sale restated with four keys of the user's own on the gain split, which
are text and numbers as stated, and neither #True nor #False:

	Income:FX Gain -100.00 CAD
		guid: "0b0b0b0b0b0b0b0b0b0b0b0b0b0b1004"
		reviewed: "true"
		approved: "yes"
		count: 0
		code: "0"

Exported, `a_gain_split_s_mark_14_keys_of_the_user_s_own_stating_true_yes_and_0_exported.txt`,
each as written, the keys in the order the export sorts them; no warning:

	Income:FX Gain -100.00 CAD
		guid: "0b0b0b0b0b0b0b0b0b0b0b0b0b0b1004"
		approved: "yes"
		code: "0"
		count: 0
		reviewed: "true"

Steps 15 to 18 restate the sale with the gain split's `took_the_residual:`
line as the step states and without the user's keys, which a block not
stating them leaves as they are:

Step 15, `a_gain_split_s_mark_15_stated_as_the_text_no.txt`: `"no"`.
Exported as `a_gain_split_s_mark_15_stated_as_the_text_no_exported.txt`,
step 14's export with `took_the_residual: #False` after the user's keys; no
warning.

Step 16, `a_gain_split_s_mark_16_stated_as_the_text_1.txt`: `"1"`. Exported
as `a_gain_split_s_mark_16_stated_as_the_text_1_exported.txt`, step 14's
export with `took_the_residual: #True`; no warning.

Step 17, `a_gain_split_s_mark_17_stated_as_the_text_0.txt`: `"0"`. Exported
as step 15's, `#False`; no warning.

Step 18, `a_gain_split_s_mark_18_stated_true.txt`: `#True`. Exported as step
16's, `#True`; no warning.
"""

import re
from pathlib import Path

from click.testing import CliRunner

from tests.conftest import _run

FIXTURES = Path('tests/fixtures')

STEPS = [
    'a_gain_split_s_mark_1_a_thousand_usd_bought_and_sold',
    'a_gain_split_s_mark_2_stated_false',
    'a_gain_split_s_mark_3_stated_as_the_text_true',
    'a_gain_split_s_mark_4_stated_as_0',
    'a_gain_split_s_mark_5_stated_as_1',
    'a_gain_split_s_mark_6_stated_as_the_text_false',
    'a_gain_split_s_mark_7_stated_as_the_text_yes',
    'a_gain_split_s_mark_8_stated_empty',
    'a_gain_split_s_mark_9_stated_as_the_text_maybe',
    'a_gain_split_s_mark_10_removed',
    'a_gain_split_s_mark_11_the_purchase_s_balance_stated_empty',
    'a_gain_split_s_mark_12_the_sale_s_cost_basis_stated_empty',
    'a_gain_split_s_mark_13_the_sale_s_cost_stated_empty',
    'a_gain_split_s_mark_14_keys_of_the_user_s_own_stating_true_yes_and_0',
    'a_gain_split_s_mark_15_stated_as_the_text_no',
    'a_gain_split_s_mark_16_stated_as_the_text_1',
    'a_gain_split_s_mark_17_stated_as_the_text_0',
    'a_gain_split_s_mark_18_stated_true',
]

# The steps whose file is refused whole, leaving the book as the step before it left it.
REFUSED = {8, 9, 11, 12, 13}

HOLDING_TRUE ='a_gain_split_s_mark_1_a_thousand_usd_bought_and_sold_exported'
HOLDING_FALSE = 'a_gain_split_s_mark_2_stated_false_exported'
REMOVED = 'a_gain_split_s_mark_10_removed_exported'

def _refused(key, stated, line):
    return f"{line!r}: `{key}` is gnucash-plaintext's own key, so `{key}: {stated}` is refused."


def _refused_empty(key, line):
    return (_refused(key, '""', line)
            + f' It states nothing; to remove the key, write `{key}: $None$`.')


GAIN = 'Income:FX Gain -100.00 CAD'
PURCHASE = 'Assets:USD Bank 1000.00 USD'
SALE = 'Assets:USD Bank -1000.00 USD'
NOT_A_BOOL = (_refused('took_the_residual', '"maybe"', GAIN)
              + ' It holds #True or #False, which may also be written "true", "yes" or 1, '
                'and "false", "no" or 0.')


def _warnings(output):
    return [line.strip() for line in output.splitlines() if line.strip().startswith('⚠')]


def _export(book, tmp_path):
    """The purchase and the sale as `export` writes them."""
    out = tmp_path / 'out.txt'
    exported = _run(CliRunner(), 'export', str(book), str(out))
    assert exported.exit_code == 0, exported.output
    return ''.join(re.search(when + r' \*[^\n]*\n(?:\t[^\n]*\n)*', out.read_text()).group(0)
                   for when in ('2026-02-01', '2026-06-01'))


def _steps(tmp_path, last):
    """The purchase and the sale as exported before step `last` and after it, and that step's import output.

    Before step 1 there is no book, so `before` is None.
    """
    book = tmp_path / 'book.gnucash'
    before = None
    for number, step in enumerate(STEPS[:last], start=1):
        if number == last and number > 1:
            before = _export(book, tmp_path)
        ledger = str(FIXTURES / f'{step}.txt')
        args = (['import', '--new', str(book), ledger] if number == 1
                else ['import', '--strategy', 'update', str(book), ledger])
        done = _run(CliRunner(), *args)
        if number < last:
            assert (done.exit_code == 1 if number in REFUSED
                    else done.exit_code == 0 and 'Errors:       0' in done.output), done.output
    return before, _export(book, tmp_path), done


def _expected(name):
    return (FIXTURES / f'{name}.txt').read_text()


def _keys(blocks, split):
    """Each key the split whose line is `split` states, but its guid, with the value as the export writes it."""
    lines = blocks[blocks.index(f'\t{split}\n') + len(split) + 2:].splitlines()
    held = {}
    for line in lines:
        if not line.startswith('\t\t'):
            break
        key, _, value = line.strip().partition(': ')
        if key != 'guid':
            held[key] = value
    return held


def _mark(blocks):
    """What the gain split's `took_the_residual:` line states, or None where it states none."""
    return _keys(blocks, GAIN).get('took_the_residual')


def _accepted(done):
    assert done.exit_code == 0 and 'Errors:       0' in done.output, done.output
    assert _warnings(done.output) == [], done.output


def _refused_with(done, refusal):
    assert done.exit_code == 1, done.output
    assert 'could not be read, so nothing was imported' in done.output, done.output
    assert refusal in done.output, done.output
    assert _warnings(done.output) == [], done.output


def test_1_the_residual_marks_took_the_residual_true(tmp_path):
    """`$residual$` marks the gain split `took_the_residual: #True`.

    `import --new` of the purchase and the sale, whose gain split states
    `$residual$`. The import marks the split it resolved to, and stores the
    mark as #True, not the text "true".
    """
    _, after, done = _steps(tmp_path, 1)
    _accepted(done)
    assert _mark(after) == '#True'
    assert after == _expected(HOLDING_TRUE)


def test_2_took_the_residual_false_is_stored_and_exported_as_false(tmp_path):
    """#False on the gain split is stored and exported as #False.

    `import --strategy update` of the sale, its gain split stating
    `took_the_residual: #False`, a bool. The mark goes from #True to #False.
    """
    before, after, done = _steps(tmp_path, 2)
    _accepted(done)
    assert _mark(before) == '#True'
    assert _mark(after) == '#False'
    assert after == _expected(HOLDING_FALSE)


def test_3_took_the_residual_the_text_true_is_stored_and_exported_as_true(tmp_path):
    """The text "true" on the gain split is read as #True.

    `import --strategy update` of the sale, its gain split stating
    `took_the_residual: "true"`. The key is gnucash-plaintext's own and holds a
    bool, so the text true is stored as #True and exported as #True. The mark
    goes from #False to #True.
    """
    before, after, done = _steps(tmp_path, 3)
    _accepted(done)
    assert _mark(before) == '#False'
    assert _mark(after) == '#True'
    assert after == _expected(HOLDING_TRUE)


def test_4_took_the_residual_0_is_stored_and_exported_as_false(tmp_path):
    """The number 0 on the gain split is read as #False.

    `import --strategy update` of the sale, its gain split stating
    `took_the_residual: 0`. The key holds a bool, so the number 0 is stored as
    #False and exported as #False. The mark goes from #True to #False.
    """
    before, after, done = _steps(tmp_path, 4)
    _accepted(done)
    assert _mark(before) == '#True'
    assert _mark(after) == '#False'
    assert after == _expected(HOLDING_FALSE)


def test_5_took_the_residual_1_is_stored_and_exported_as_true(tmp_path):
    """The number 1 on the gain split is read as #True.

    `import --strategy update` of the sale, its gain split stating
    `took_the_residual: 1`. The key holds a bool, so the number 1 is stored as
    #True and exported as #True. The mark goes from #False to #True.
    """
    before, after, done = _steps(tmp_path, 5)
    _accepted(done)
    assert _mark(before) == '#False'
    assert _mark(after) == '#True'
    assert after == _expected(HOLDING_TRUE)


def test_6_took_the_residual_the_text_false_is_stored_and_exported_as_false(tmp_path):
    """The text "false" on the gain split is read as #False.

    `import --strategy update` of the sale, its gain split stating
    `took_the_residual: "false"`. The key holds a bool, so the text false is
    stored as #False and exported as #False. The mark goes from #True to #False.
    """
    before, after, done = _steps(tmp_path, 6)
    _accepted(done)
    assert _mark(before) == '#True'
    assert _mark(after) == '#False'
    assert after == _expected(HOLDING_FALSE)


def test_7_took_the_residual_the_text_yes_is_stored_and_exported_as_true(tmp_path):
    """The text "yes" on the gain split is read as #True.

    `import --strategy update` of the sale, its gain split stating
    `took_the_residual: "yes"`. The key holds a bool, so the text yes is stored
    as #True and exported as #True. The mark goes from #False to #True.
    """
    before, after, done = _steps(tmp_path, 7)
    _accepted(done)
    assert _mark(before) == '#False'
    assert _mark(after) == '#True'
    assert after == _expected(HOLDING_TRUE)


def test_8_took_the_residual_empty_is_refused_and_the_mark_is_kept(tmp_path):
    """The empty text on the gain split is refused, and the mark is kept.

    `import --strategy update` of the sale, its gain split stating
    `took_the_residual: ""`. The empty text states nothing, and only `$None$`
    removes a key, so the file is refused whole and the mark stays #True.
    """
    before, after, done = _steps(tmp_path, 8)
    _refused_with(done, _refused_empty('took_the_residual', GAIN))
    assert _mark(before) == '#True'
    assert _mark(after) == '#True'
    assert after == before == _expected(HOLDING_TRUE)


def test_9_took_the_residual_a_text_that_is_neither_true_nor_false_is_refused(tmp_path):
    """A text that is neither true nor false on the gain split is refused, and the mark is kept.

    `import --strategy update` of the sale, its gain split stating
    `took_the_residual: "maybe"`. It is no spelling of #True or #False, so the
    file is refused whole and the mark stays #True.
    """
    before, after, done = _steps(tmp_path, 9)
    _refused_with(done, NOT_A_BOOL)
    assert _mark(before) == '#True'
    assert _mark(after) == '#True'
    assert after == before == _expected(HOLDING_TRUE)


def test_10_took_the_residual_none_between_dollar_signs_removes_it(tmp_path):
    """`$None$` on the gain split removes the mark.

    `import --strategy update` of the sale, its gain split stating
    `took_the_residual: $None$`, without quotes. The mark goes from #True to
    none, and the export writes no `took_the_residual:` line.
    """
    before, after, done = _steps(tmp_path, 10)
    _accepted(done)
    assert _mark(before) == '#True'
    assert _mark(after) is None
    assert after == _expected(REMOVED)


def test_11_cost_basis_balance_empty_is_refused(tmp_path):
    """The empty text as the purchase's `cost_basis_balance` is refused, and the balance is kept.

    `import --strategy update` of the purchase, its US dollar split stating
    `cost_basis_balance: ""`. The key holds a figure, and the empty text states
    none, so the file is refused whole and the balance stays "0.00".
    """
    before, after, done = _steps(tmp_path, 11)
    _refused_with(done, _refused_empty('cost_basis_balance', PURCHASE))
    assert _keys(before, PURCHASE)['cost_basis_balance'] == '"0.00"'
    assert _keys(after, PURCHASE)['cost_basis_balance'] == '"0.00"'
    assert after == before == _expected(REMOVED)


def test_12_cost_basis_split_guid_empty_is_refused(tmp_path):
    """The empty text as the sale's `cost_basis_split_guid` is refused, and its cost basis is kept.

    `import --strategy update` of the sale, its US dollar split stating
    `cost_basis_split_guid: ""`. The key holds a guid or `$pending$`, and the
    empty text states neither, so the file is refused whole and the sale still
    states the purchase's split.
    """
    before, after, done = _steps(tmp_path, 12)
    _refused_with(done, _refused_empty('cost_basis_split_guid', SALE))
    assert _keys(before, SALE)['cost_basis_split_guid'] == '"0b0b0b0b0b0b0b0b0b0b0b0b0b0b1000"'
    assert _keys(after, SALE)['cost_basis_split_guid'] == '"0b0b0b0b0b0b0b0b0b0b0b0b0b0b1000"'
    assert after == before == _expected(REMOVED)


def test_13_cost_basis_cost_empty_is_refused(tmp_path):
    """The empty text as the sale's `cost_basis_cost` is refused.

    `import --strategy update` of the sale, its US dollar split stating
    `cost_basis_cost: ""`. The key holds a figure, and the empty text states
    none, so the file is refused whole and the split still holds no
    `cost_basis_cost`.
    """
    before, after, done = _steps(tmp_path, 13)
    _refused_with(done, _refused_empty('cost_basis_cost', SALE))
    assert 'cost_basis_cost' not in _keys(before, SALE)
    assert 'cost_basis_cost' not in _keys(after, SALE)
    assert after == before == _expected(REMOVED)


def test_14_reviewed_approved_count_and_code_keep_true_yes_and_0_as_written(tmp_path):
    """Keys of the user's own keep "true", "yes", 0 and "0" as the file states them.

    `import --strategy update` of the sale, its gain split stating four keys of
    the user's own: `reviewed: "true"` and `approved: "yes"`, text; `count: 0`,
    a number; `code: "0"`, text. Only gnucash-plaintext's own keys are read as
    a bool, so each of these is stored and exported as stated.
    """
    before, after, done = _steps(tmp_path, 14)
    _accepted(done)
    assert _keys(before, GAIN) == {}
    assert _keys(after, GAIN) == {
        'approved': '"yes"', 'code': '"0"', 'count': '0', 'reviewed': '"true"'}
    assert after == _expected(
        'a_gain_split_s_mark_14_keys_of_the_user_s_own_stating_true_yes_and_0_exported')


BESIDE_THE_USER_S_KEYS_FALSE = 'a_gain_split_s_mark_15_stated_as_the_text_no_exported'
BESIDE_THE_USER_S_KEYS_TRUE = 'a_gain_split_s_mark_16_stated_as_the_text_1_exported'
THE_USER_S_KEYS = {'approved': '"yes"', 'code': '"0"', 'count': '0', 'reviewed': '"true"'}


def test_15_took_the_residual_the_text_no_is_stored_and_exported_as_false(tmp_path):
    """The text "no" on the gain split is read as #False, beside the user's keys.

    `import --strategy update` of the sale, its gain split stating
    `took_the_residual: "no"`. The key holds a bool, so the text no is stored as
    #False. The mark goes from none to #False, and the user's keys, which the
    block does not state, stay as they were.
    """
    before, after, done = _steps(tmp_path, 15)
    _accepted(done)
    assert _keys(before, GAIN) == THE_USER_S_KEYS
    assert _keys(after, GAIN) == {**THE_USER_S_KEYS, 'took_the_residual': '#False'}
    assert after == _expected(BESIDE_THE_USER_S_KEYS_FALSE)


def test_16_took_the_residual_the_text_1_is_stored_and_exported_as_true(tmp_path):
    """The text "1" on the gain split is read as #True.

    `import --strategy update` of the sale, its gain split stating
    `took_the_residual: "1"`. The key holds a bool, so the text 1 is stored as
    #True. The mark goes from #False to #True.
    """
    before, after, done = _steps(tmp_path, 16)
    _accepted(done)
    assert _keys(before, GAIN) == {**THE_USER_S_KEYS, 'took_the_residual': '#False'}
    assert _keys(after, GAIN) == {**THE_USER_S_KEYS, 'took_the_residual': '#True'}
    assert after == _expected(BESIDE_THE_USER_S_KEYS_TRUE)


def test_17_took_the_residual_the_text_0_is_stored_and_exported_as_false(tmp_path):
    """The text "0" on the gain split is read as #False.

    `import --strategy update` of the sale, its gain split stating
    `took_the_residual: "0"`. The key holds a bool, so the text 0 is stored as
    #False. The mark goes from #True to #False.
    """
    before, after, done = _steps(tmp_path, 17)
    _accepted(done)
    assert _keys(before, GAIN) == {**THE_USER_S_KEYS, 'took_the_residual': '#True'}
    assert _keys(after, GAIN) == {**THE_USER_S_KEYS, 'took_the_residual': '#False'}
    assert after == _expected(BESIDE_THE_USER_S_KEYS_FALSE)


def test_18_took_the_residual_true_is_stored_and_exported_as_true(tmp_path):
    """#True on the gain split is stored and exported as #True.

    `import --strategy update` of the sale, its gain split stating
    `took_the_residual: #True`, a bool. The mark goes from #False to #True.
    """
    before, after, done = _steps(tmp_path, 18)
    _accepted(done)
    assert _keys(before, GAIN) == {**THE_USER_S_KEYS, 'took_the_residual': '#False'}
    assert _keys(after, GAIN) == {**THE_USER_S_KEYS, 'took_the_residual': '#True'}
    assert after == _expected(BESIDE_THE_USER_S_KEYS_TRUE)
