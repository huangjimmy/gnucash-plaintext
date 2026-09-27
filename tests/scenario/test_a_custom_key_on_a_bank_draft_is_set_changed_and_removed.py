"""A custom key on a bank draft is set, changed, joined by another, and removed.

The case is the author's, reported for Q-054: a draft of 500.00 CAD from
Asset:BankB into Asset:BankA, and a note the user keeps on it. Step 1 is
imported into a new book; every step after it with `--strategy update` over
the book the step before left. After each, `export` writes the draft as its
`_exported.txt` fixture states, and nothing else on it, and the import prints
no warning. What `$None$` and `#None` do to GnuCash's own fields, a
transaction's notes and a split's memo and action, is
`test_a_gnucash_field_stated_none_keeps_what_gnucash_keeps_and_says_so.py`.

Step 1, `tests/fixtures/a_bank_draft_1_with_no_key.txt`: the accounts, and
the draft with no key.

2026-01-01 open Asset
	type: Asset
	commodity.namespace: "CURRENCY"
	commodity.mnemonic: "CAD"
2026-01-01 open Asset:BankA
	type: Bank
	commodity.namespace: "CURRENCY"
	commodity.mnemonic: "CAD"
2026-01-01 open Asset:BankB
	type: Bank
	commodity.namespace: "CURRENCY"
	commodity.mnemonic: "CAD"

2026-01-10 * "A draft from bank account b"
	guid: "5ce0a4100000000000000000000000d1"
	Asset:BankA 500.00 CAD
		guid: "5ce0a4100000000000000000000000a1"
	Asset:BankB -500.00 CAD
		guid: "5ce0a4100000000000000000000000b1"

Exported, `a_bank_draft_1_with_no_key_exported.txt`:

2026-01-10 * "A draft from bank account b"
	guid: "5ce0a4100000000000000000000000d1"
	Asset:BankA 500.00 CAD
		guid: "5ce0a4100000000000000000000000a1"
	Asset:BankB -500.00 CAD
		guid: "5ce0a4100000000000000000000000b1"

Step 2, `a_bank_draft_2_noting_the_rate_at_21_99.txt`: the user keeps a note
on the draft's split, as a key of their own.

2026-01-10 * "A draft from bank account b"
	guid: "5ce0a4100000000000000000000000d1"
	Asset:BankA 500.00 CAD
		guid: "5ce0a4100000000000000000000000a1"
	Asset:BankB -500.00 CAD
		guid: "5ce0a4100000000000000000000000b1"
		bank_draft: "interest APR 21.99%, I should repay early"

Exported, `a_bank_draft_2_noting_the_rate_at_21_99_exported.txt`:

2026-01-10 * "A draft from bank account b"
	guid: "5ce0a4100000000000000000000000d1"
	Asset:BankA 500.00 CAD
		guid: "5ce0a4100000000000000000000000a1"
	Asset:BankB -500.00 CAD
		guid: "5ce0a4100000000000000000000000b1"
		bank_draft: "interest APR 21.99%, I should repay early"

Step 3, `a_bank_draft_3_noting_the_rate_at_24_99.txt`: the rate corrected.

2026-01-10 * "A draft from bank account b"
	guid: "5ce0a4100000000000000000000000d1"
	Asset:BankA 500.00 CAD
		guid: "5ce0a4100000000000000000000000a1"
	Asset:BankB -500.00 CAD
		guid: "5ce0a4100000000000000000000000b1"
		bank_draft: "interest APR 24.99%, I should repay early"

Exported, `a_bank_draft_3_noting_the_rate_at_24_99_exported.txt`:

2026-01-10 * "A draft from bank account b"
	guid: "5ce0a4100000000000000000000000d1"
	Asset:BankA 500.00 CAD
		guid: "5ce0a4100000000000000000000000a1"
	Asset:BankB -500.00 CAD
		guid: "5ce0a4100000000000000000000000b1"
		bank_draft: "interest APR 24.99%, I should repay early"

Step 4, `a_bank_draft_4_noting_it_as_over_draft.txt`: the note moved to
another key, the block no longer stating `bank_draft:`.

2026-01-10 * "A draft from bank account b"
	guid: "5ce0a4100000000000000000000000d1"
	Asset:BankA 500.00 CAD
		guid: "5ce0a4100000000000000000000000a1"
	Asset:BankB -500.00 CAD
		guid: "5ce0a4100000000000000000000000b1"
		over_draft: "interest APR 24.99%, I should repay early"

Exported, `a_bank_draft_4_noting_it_as_over_draft_exported.txt`: both keys,
since a key a block does not state says nothing about it.

2026-01-10 * "A draft from bank account b"
	guid: "5ce0a4100000000000000000000000d1"
	Asset:BankA 500.00 CAD
		guid: "5ce0a4100000000000000000000000a1"
	Asset:BankB -500.00 CAD
		guid: "5ce0a4100000000000000000000000b1"
		bank_draft: "interest APR 24.99%, I should repay early"
		over_draft: "interest APR 24.99%, I should repay early"

Step 5, `a_bank_draft_5_stating_bank_draft_as_the_text_none.txt`: `"#None"`
in quotes, the text `#None`, which removes nothing.

2026-01-10 * "A draft from bank account b"
	guid: "5ce0a4100000000000000000000000d1"
	Asset:BankA 500.00 CAD
		guid: "5ce0a4100000000000000000000000a1"
	Asset:BankB -500.00 CAD
		guid: "5ce0a4100000000000000000000000b1"
		bank_draft: "#None"
		over_draft: "interest APR 24.99%, I should repay early"

Exported, `a_bank_draft_5_stating_bank_draft_as_the_text_none_exported.txt`:

2026-01-10 * "A draft from bank account b"
	guid: "5ce0a4100000000000000000000000d1"
	Asset:BankA 500.00 CAD
		guid: "5ce0a4100000000000000000000000a1"
	Asset:BankB -500.00 CAD
		guid: "5ce0a4100000000000000000000000b1"
		bank_draft: "#None"
		over_draft: "interest APR 24.99%, I should repay early"

Step 6, `a_bank_draft_6_stating_bank_draft_as_null.txt`: `#None` unquoted,
the null value, which the key holds, and which removes nothing either.

2026-01-10 * "A draft from bank account b"
	guid: "5ce0a4100000000000000000000000d1"
	Asset:BankA 500.00 CAD
		guid: "5ce0a4100000000000000000000000a1"
	Asset:BankB -500.00 CAD
		guid: "5ce0a4100000000000000000000000b1"
		bank_draft: #None
		over_draft: "interest APR 24.99%, I should repay early"

Exported, `a_bank_draft_6_stating_bank_draft_as_null_exported.txt`:

2026-01-10 * "A draft from bank account b"
	guid: "5ce0a4100000000000000000000000d1"
	Asset:BankA 500.00 CAD
		guid: "5ce0a4100000000000000000000000a1"
	Asset:BankB -500.00 CAD
		guid: "5ce0a4100000000000000000000000b1"
		bank_draft: #None
		over_draft: "interest APR 24.99%, I should repay early"

Step 7, `a_bank_draft_7_removing_bank_draft.txt`: `$None$`, as README says.

2026-01-10 * "A draft from bank account b"
	guid: "5ce0a4100000000000000000000000d1"
	Asset:BankA 500.00 CAD
		guid: "5ce0a4100000000000000000000000a1"
	Asset:BankB -500.00 CAD
		guid: "5ce0a4100000000000000000000000b1"
		bank_draft: $None$
		over_draft: "interest APR 24.99%, I should repay early"

Exported, `a_bank_draft_7_removing_bank_draft_exported.txt`: `bank_draft:`
removed.

2026-01-10 * "A draft from bank account b"
	guid: "5ce0a4100000000000000000000000d1"
	Asset:BankA 500.00 CAD
		guid: "5ce0a4100000000000000000000000a1"
	Asset:BankB -500.00 CAD
		guid: "5ce0a4100000000000000000000000b1"
		over_draft: "interest APR 24.99%, I should repay early"

Step 8, `a_bank_draft_8_stating_over_draft_as_the_empty_text.txt`: `""`, the
empty text, which the key holds. Only `$None$` removes a key; the author's
rule, stated for Q-054 and restated after it shipped with `""` removing one.

2026-01-10 * "A draft from bank account b"
	guid: "5ce0a4100000000000000000000000d1"
	Asset:BankA 500.00 CAD
		guid: "5ce0a4100000000000000000000000a1"
	Asset:BankB -500.00 CAD
		guid: "5ce0a4100000000000000000000000b1"
		over_draft: ""

Exported, `a_bank_draft_8_stating_over_draft_as_the_empty_text_exported.txt`:

2026-01-10 * "A draft from bank account b"
	guid: "5ce0a4100000000000000000000000d1"
	Asset:BankA 500.00 CAD
		guid: "5ce0a4100000000000000000000000a1"
	Asset:BankB -500.00 CAD
		guid: "5ce0a4100000000000000000000000b1"
		over_draft: ""

Step 9, `a_bank_draft_9_stating_over_draft_as_the_text_none_between_dollar_signs.txt`:
`"$None$"` in quotes, the text `$None$`, which removes nothing.

2026-01-10 * "A draft from bank account b"
	guid: "5ce0a4100000000000000000000000d1"
	Asset:BankA 500.00 CAD
		guid: "5ce0a4100000000000000000000000a1"
	Asset:BankB -500.00 CAD
		guid: "5ce0a4100000000000000000000000b1"
		over_draft: "$None$"

Exported, `a_bank_draft_9_stating_over_draft_as_the_text_none_between_dollar_signs_exported.txt`:

2026-01-10 * "A draft from bank account b"
	guid: "5ce0a4100000000000000000000000d1"
	Asset:BankA 500.00 CAD
		guid: "5ce0a4100000000000000000000000a1"
	Asset:BankB -500.00 CAD
		guid: "5ce0a4100000000000000000000000b1"
		over_draft: "$None$"

Step 10, `a_bank_draft_10_removing_over_draft.txt`: `$None$` unquoted.

2026-01-10 * "A draft from bank account b"
	guid: "5ce0a4100000000000000000000000d1"
	Asset:BankA 500.00 CAD
		guid: "5ce0a4100000000000000000000000a1"
	Asset:BankB -500.00 CAD
		guid: "5ce0a4100000000000000000000000b1"
		over_draft: $None$

Exported, `a_bank_draft_10_removing_over_draft_exported.txt`: no key left.

2026-01-10 * "A draft from bank account b"
	guid: "5ce0a4100000000000000000000000d1"
	Asset:BankA 500.00 CAD
		guid: "5ce0a4100000000000000000000000a1"
	Asset:BankB -500.00 CAD
		guid: "5ce0a4100000000000000000000000b1"

Steps 11 to 20 state `bank_draft:` on the same split, each as the step
says, and the export writes it back exactly as stated: a key of the user's
own holds what the file states, and nothing is converted. Each step's
fixture is step 10's draft with the one line, and its `_exported.txt` the
same draft with the line as written below. The author's rules, stated after
Q-054: `#True` and `#False` are flags; `"#True"`, `"yes"` and `"1"` in
quotes are text; `1` is a number; a word without quotes is refused; a date
is written without quotes, and a date in quotes is text.

Step 11, `a_bank_draft_11_stating_bank_draft_true.txt`: `bank_draft: #True`,
exported `bank_draft: #True`.

Step 12, `a_bank_draft_12_stating_bank_draft_false.txt`: `bank_draft: #False`,
exported `bank_draft: #False`.

Step 13, `a_bank_draft_13_stating_bank_draft_as_the_text_hash_true.txt`:
`bank_draft: "#True"`, exported `bank_draft: "#True"`, text and no flag.

Step 14, `a_bank_draft_14_stating_bank_draft_as_the_text_yes.txt`:
`bank_draft: "yes"`, exported `bank_draft: "yes"`, text and no flag.

Step 15, `a_bank_draft_15_stating_bank_draft_as_the_text_1.txt`:
`bank_draft: "1"`, exported `bank_draft: "1"`, text and no number.

Step 16, `a_bank_draft_16_stating_bank_draft_as_1.txt`: `bank_draft: 1`,
exported `bank_draft: 1`, the number.

Step 17, `a_bank_draft_17_stating_bank_draft_as_a_bare_yes.txt`:
`bank_draft: yes`. Refused, and the book is step 16's:

  'Asset:BankB -500.00 CAD': `bank_draft` is a key of your own, and `bank_draft: yes` states a word without quotes. Write `bank_draft: "yes"` for the text, or #True or #False.

Step 18, `a_bank_draft_18_stating_bank_draft_as_a_date.txt`:
`bank_draft: 2026-01-31`, exported `bank_draft: 2026-01-31`, a date.

Step 19, `a_bank_draft_19_stating_bank_draft_as_the_text_of_a_date.txt`:
`bank_draft: "2026-01-31"`, exported `bank_draft: "2026-01-31"`, text and no
date.

Step 20, `a_bank_draft_20_stating_bank_draft_as_no_date.txt`:
`bank_draft: 2026-13-45`. Refused, and the book is step 19's:

  'Asset:BankB -500.00 CAD': `bank_draft: 2026-13-45` is no date. Write a date as YYYY-MM-DD, such as 2026-01-31, or `bank_draft: "2026-13-45"` for the text.
"""

import re
from pathlib import Path

from click.testing import CliRunner

from tests.conftest import _run

FIXTURES = Path('tests/fixtures')

STEPS = [
    'a_bank_draft_1_with_no_key',
    'a_bank_draft_2_noting_the_rate_at_21_99',
    'a_bank_draft_3_noting_the_rate_at_24_99',
    'a_bank_draft_4_noting_it_as_over_draft',
    'a_bank_draft_5_stating_bank_draft_as_the_text_none',
    'a_bank_draft_6_stating_bank_draft_as_null',
    'a_bank_draft_7_removing_bank_draft',
    'a_bank_draft_8_stating_over_draft_as_the_empty_text',
    'a_bank_draft_9_stating_over_draft_as_the_text_none_between_dollar_signs',
    'a_bank_draft_10_removing_over_draft',
    'a_bank_draft_11_stating_bank_draft_true',
    'a_bank_draft_12_stating_bank_draft_false',
    'a_bank_draft_13_stating_bank_draft_as_the_text_hash_true',
    'a_bank_draft_14_stating_bank_draft_as_the_text_yes',
    'a_bank_draft_15_stating_bank_draft_as_the_text_1',
    'a_bank_draft_16_stating_bank_draft_as_1',
    'a_bank_draft_17_stating_bank_draft_as_a_bare_yes',
    'a_bank_draft_18_stating_bank_draft_as_a_date',
    'a_bank_draft_19_stating_bank_draft_as_the_text_of_a_date',
    'a_bank_draft_20_stating_bank_draft_as_no_date',
]

# The steps whose file is refused whole, leaving the book as the step before it left it.
REFUSED = {17, 20}
SPLIT = 'Asset:BankB -500.00 CAD'


def _warnings(output):
    return [line.strip() for line in output.splitlines() if line.strip().startswith('⚠')]


def _after_with_output(tmp_path, last):
    """The draft as `export` writes it after steps 1 to `last`, the warnings the last import printed, and its output.

    The whole draft, every line of it, so a key the fixture does not state
    fails the comparison as surely as a key it states and the book lacks. And
    every warning, so one no step expects fails as surely as one missing.
    """
    book = tmp_path / 'book.gnucash'
    for number, step in enumerate(STEPS[:last], start=1):
        ledger = str(FIXTURES / f'{step}.txt')
        args = (['import', '--new', str(book), ledger] if number == 1
                else ['import', '--strategy', 'update', str(book), ledger])
        done = _run(CliRunner(), *args)
        if number in REFUSED:
            assert done.exit_code == 1, done.output
            assert 'could not be read, so nothing was imported' in done.output, done.output
        else:
            assert done.exit_code == 0 and 'Errors:       0' in done.output, done.output
    out = tmp_path / 'out.txt'
    exported = _run(CliRunner(), 'export', str(book), str(out))
    assert exported.exit_code == 0, exported.output
    draft = re.search(r'2026-01-10 \* "A draft from bank account b"\n(?:\t[^\n]*\n)*',
                      out.read_text())
    assert draft, out.read_text()
    return draft.group(0), _warnings(done.output), done.output


def _after(tmp_path, last):
    """The draft as `export` writes it after steps 1 to `last`, and the warnings the last import printed."""
    draft, warnings, _ = _after_with_output(tmp_path, last)
    return draft, warnings


def _expected(last):
    return (FIXTURES / f'{STEPS[last - 1]}_exported.txt').read_text()


def test_1_the_draft_carries_no_key(tmp_path):
    assert _after(tmp_path, 1) == (_expected(1), [])


def test_2_bank_draft_keeps_the_user_s_note(tmp_path):
    assert _after(tmp_path, 2) == (_expected(2), [])


def test_3_bank_draft_is_corrected(tmp_path):
    assert _after(tmp_path, 3) == (_expected(3), [])


def test_4_over_draft_leaves_bank_draft_where_it_is(tmp_path):
    assert _after(tmp_path, 4) == (_expected(4), [])


def test_5_bank_draft_none_in_quotes_is_text_and_removes_nothing(tmp_path):
    assert _after(tmp_path, 5) == (_expected(5), [])


def test_6_bank_draft_none_unquoted_is_the_null_value_and_removes_nothing(tmp_path):
    assert _after(tmp_path, 6) == (_expected(6), [])


def _keys(draft):
    """The custom keys the draft's Asset:BankB split holds, each with the value the export writes."""
    split = draft[draft.index('\tAsset:BankB -500.00 CAD\n'):]
    return dict(line.strip().split(': ', 1) for line in split.splitlines()[1:]
                if not line.strip().startswith('guid:'))


def test_7_bank_draft_none_between_dollar_signs_removes_it(tmp_path):
    draft, warnings = _after(tmp_path, 7)
    assert 'bank_draft' not in _keys(draft), draft
    assert _keys(draft) == {'over_draft': '"interest APR 24.99%, I should repay early"'}, draft
    assert (draft, warnings) == (_expected(7), [])


def _steps(tmp_path, last):
    """The draft's split keys before step `last` and after it, the draft after it, and that step's output."""
    (tmp_path / 'before').mkdir()
    (tmp_path / 'after').mkdir()
    before, _ = _after(tmp_path / 'before', last - 1)
    draft, warnings, output = _after_with_output(tmp_path / 'after', last)
    assert warnings == [], output
    return _keys(before), _keys(draft), draft, output


def test_8_over_draft_the_empty_text_is_held_and_removes_nothing(tmp_path):
    """The empty text on `over_draft` is held as the empty text, not a removal.

    `import --strategy update` of the draft, its BankB split stating
    `over_draft: ""`. Only `$None$` removes a key, so the key is kept, holding "".
    """
    before, after, draft, _ = _steps(tmp_path, 8)
    assert before == {'over_draft': '"interest APR 24.99%, I should repay early"'}
    assert after == {'over_draft': '""'}
    assert draft == _expected(8)


def test_9_over_draft_none_between_dollar_signs_in_quotes_is_text_and_removes_nothing(tmp_path):
    """`"$None$"` in quotes on `over_draft` is text, and removes nothing.

    `import --strategy update` of the draft, its BankB split stating
    `over_draft: "$None$"`. The key holds the text $None$.
    """
    before, after, draft, _ = _steps(tmp_path, 9)
    assert before == {'over_draft': '""'}
    assert after == {'over_draft': '"$None$"'}
    assert draft == _expected(9)


def test_10_over_draft_none_between_dollar_signs_removes_it(tmp_path):
    """`$None$` without quotes on `over_draft` removes the key.

    `import --strategy update` of the draft, its BankB split stating
    `over_draft: $None$`. The split then holds no key.
    """
    before, after, draft, _ = _steps(tmp_path, 10)
    assert before == {'over_draft': '"$None$"'}
    assert after == {}
    assert draft == _expected(10)


def test_11_bank_draft_true_is_held_as_true(tmp_path):
    """#True on `bank_draft` is stored and exported as #True.

    `import --strategy update` of the draft, its BankB split stating
    `bank_draft: #True`, a bool. The key is added.
    """
    before, after, draft, _ = _steps(tmp_path, 11)
    assert before == {}
    assert after == {'bank_draft': '#True'}
    assert draft == _expected(11)


def test_12_bank_draft_false_is_held_as_false(tmp_path):
    """#False on `bank_draft` is stored and exported as #False.

    `import --strategy update` of the draft, its BankB split stating
    `bank_draft: #False`, a bool. The key goes from #True to #False.
    """
    before, after, draft, _ = _steps(tmp_path, 12)
    assert before == {'bank_draft': '#True'}
    assert after == {'bank_draft': '#False'}
    assert draft == _expected(12)


def test_13_bank_draft_the_text_hash_true_is_text_and_not_true(tmp_path):
    """The text "#True" on `bank_draft` stays text.

    `import --strategy update` of the draft, its BankB split stating
    `bank_draft: "#True"`, in quotes. A key of the user's own is not converted,
    so it is stored as text and exported in quotes.
    """
    before, after, draft, _ = _steps(tmp_path, 13)
    assert before == {'bank_draft': '#False'}
    assert after == {'bank_draft': '"#True"'}
    assert draft == _expected(13)


def test_14_bank_draft_the_text_yes_is_text_and_not_true(tmp_path):
    """The text "yes" on `bank_draft` stays text.

    `import --strategy update` of the draft, its BankB split stating
    `bank_draft: "yes"`, in quotes. A key of the user's own is not converted, so
    it is stored as text and exported in quotes.
    """
    before, after, draft, _ = _steps(tmp_path, 14)
    assert before == {'bank_draft': '"#True"'}
    assert after == {'bank_draft': '"yes"'}
    assert draft == _expected(14)


def test_15_bank_draft_the_text_1_is_text_and_no_number(tmp_path):
    """The text "1" on `bank_draft` stays text.

    `import --strategy update` of the draft, its BankB split stating
    `bank_draft: "1"`, in quotes. It is stored as text and exported in quotes.
    """
    before, after, draft, _ = _steps(tmp_path, 15)
    assert before == {'bank_draft': '"yes"'}
    assert after == {'bank_draft': '"1"'}
    assert draft == _expected(15)


def test_16_bank_draft_1_is_the_number_1(tmp_path):
    """The number 1 on `bank_draft` is stored and exported as 1.

    `import --strategy update` of the draft, its BankB split stating
    `bank_draft: 1`, without quotes. A key of the user's own does not read 1 as
    #True.
    """
    before, after, draft, _ = _steps(tmp_path, 16)
    assert before == {'bank_draft': '"1"'}
    assert after == {'bank_draft': '1'}
    assert draft == _expected(16)


def test_17_bank_draft_a_bare_yes_is_refused_and_the_number_kept(tmp_path):
    """A bare `yes` on `bank_draft` is refused, and the key keeps the number 1.

    `import --strategy update` of the draft, its BankB split stating
    `bank_draft: yes`, a word without quotes. The file is refused whole.
    """
    before, after, draft, output = _steps(tmp_path, 17)
    assert (f"{SPLIT!r}: `bank_draft` is a key of your own, and `bank_draft: yes` states "
            'a word without quotes. Write `bank_draft: "yes"` for the text, or #True or '
            '#False.') in output, output
    assert before == {'bank_draft': '1'}
    assert after == {'bank_draft': '1'}
    assert draft == _expected(16)


def test_18_bank_draft_a_bare_date_is_held_as_a_date(tmp_path):
    """A bare date on `bank_draft` is stored as a date and exported without quotes.

    `import --strategy update` of the draft, its BankB split stating
    `bank_draft: 2026-01-31`, without quotes. The key goes from 1 to the date.
    """
    before, after, draft, _ = _steps(tmp_path, 18)
    assert before == {'bank_draft': '1'}
    assert after == {'bank_draft': '2026-01-31'}
    assert draft == _expected(18)


def test_19_bank_draft_the_text_of_a_date_is_text_and_no_date(tmp_path):
    """A date in quotes on `bank_draft` is text, not a date.

    `import --strategy update` of the draft, its BankB split stating
    `bank_draft: "2026-01-31"`, in quotes: the date as text. A key of the user's
    own is not converted, so it is stored as text and exported in quotes, and
    the date the step before stored is replaced by that text.
    """
    before, after, draft, _ = _steps(tmp_path, 19)
    assert before == {'bank_draft': '2026-01-31'}
    assert after == {'bank_draft': '"2026-01-31"'}
    assert draft == _expected(19)


def test_20_bank_draft_a_bare_date_that_is_no_date_is_refused_and_the_text_kept(tmp_path):
    """A bare date the calendar has not on `bank_draft` is refused.

    `import --strategy update` of the draft, its BankB split stating
    `bank_draft: 2026-13-45`, without quotes. The file is refused whole, and the
    key keeps the text "2026-01-31".
    """
    before, after, draft, output = _steps(tmp_path, 20)
    assert (f'{SPLIT!r}: `bank_draft: 2026-13-45` is no date. Write a date as YYYY-MM-DD, '
            'such as 2026-01-31, or `bank_draft: "2026-13-45"` for the text.') in output, output
    assert before == {'bank_draft': '"2026-01-31"'}
    assert after == {'bank_draft': '"2026-01-31"'}
    assert draft == _expected(19)
