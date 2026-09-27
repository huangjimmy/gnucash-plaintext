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
]


def _warnings(output):
    return [line.strip() for line in output.splitlines() if line.strip().startswith('⚠')]


def _after(tmp_path, last):
    """The draft as `export` writes it after steps 1 to `last`, and the warnings the last import printed.

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
        assert done.exit_code == 0 and 'Errors:       0' in done.output, done.output
    out = tmp_path / 'out.txt'
    exported = _run(CliRunner(), 'export', str(book), str(out))
    assert exported.exit_code == 0, exported.output
    draft = re.search(r'2026-01-10 \* "A draft from bank account b"\n(?:\t[^\n]*\n)*',
                      out.read_text())
    assert draft, out.read_text()
    return draft.group(0), _warnings(done.output)


def _expected(last):
    return (FIXTURES / f'{STEPS[last - 1]}_exported.txt').read_text()


def test_1_the_draft_carries_no_key(tmp_path):
    assert _after(tmp_path, 1) == (_expected(1), [])


def test_2_the_user_keeps_a_note_on_it(tmp_path):
    assert _after(tmp_path, 2) == (_expected(2), [])


def test_3_the_note_is_corrected(tmp_path):
    assert _after(tmp_path, 3) == (_expected(3), [])


def test_4_a_second_key_leaves_the_first_where_it_is(tmp_path):
    assert _after(tmp_path, 4) == (_expected(4), [])


def test_5_none_in_quotes_is_text_and_removes_nothing(tmp_path):
    assert _after(tmp_path, 5) == (_expected(5), [])


def test_6_none_unquoted_is_the_null_value_and_removes_nothing(tmp_path):
    assert _after(tmp_path, 6) == (_expected(6), [])


def test_7_none_between_dollar_signs_removes_the_key(tmp_path):
    assert _after(tmp_path, 7) == (_expected(7), [])
