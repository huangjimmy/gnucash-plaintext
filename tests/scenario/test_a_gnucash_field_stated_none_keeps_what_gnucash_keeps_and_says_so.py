"""A GnuCash field stated `$None$` or `#None` keeps what GnuCash keeps, and the import says so.

The case is the author's, reported for Q-054, beside the custom key the
same draft carries: a transaction's `notes:` and a split's `memo:` are
GnuCash's own fields, not custom keys. A field cannot be removed, and GnuCash
cannot set these two to `#None` either: its setters ignore a null for them.
So `$None$` and `#None` on them set them to `""`, and the import warns for
each. Every other field is set as stated and read back, and the import warns
where GnuCash keeps something else: a split's action ignores a null. A
transaction's doc link ignores a null too, and GnuCash stores `#None` for
`""`, so `#None` and `$None$` on it are handed to GnuCash as `""`, and
`doc_link: ""` warns that GnuCash keeps `#None`.

Step 1 is imported into a new book; every step after it with
`--strategy update` over the book the step before left. After each, `export`
writes the draft as its `_exported.txt` fixture states, and the import
prints exactly the warnings stated here, none where none is stated.

Step 1, `tests/fixtures/a_draft_s_fields_1_with_notes_and_a_memo.txt`: the
accounts, and a draft with notes on the transaction and the note as the
split's memo.

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
	guid: "5ce0a4100000000000000000000000d2"
	notes: "DONT DO THIS AGAIN"
	Asset:BankA 500.00 CAD
		guid: "5ce0a4100000000000000000000000a2"
	Asset:BankB -500.00 CAD
		guid: "5ce0a4100000000000000000000000b2"
		memo: "interest APR 24.99%, I should repay early"

Exported, `a_draft_s_fields_1_with_notes_and_a_memo_exported.txt`; no warning:

2026-01-10 * "A draft from bank account b"
	guid: "5ce0a4100000000000000000000000d2"
	notes: "DONT DO THIS AGAIN"
	Asset:BankA 500.00 CAD
		guid: "5ce0a4100000000000000000000000a2"
	Asset:BankB -500.00 CAD
		guid: "5ce0a4100000000000000000000000b2"
		memo:"interest APR 24.99%, I should repay early"

Step 2, `a_draft_s_fields_2_stating_notes_and_memo_none_between_dollar_signs.txt`:
the user removing the notes and the memo, and keeping the note as `alert:`.

2026-01-10 * "A draft from bank account b"
	guid: "5ce0a4100000000000000000000000d2"
	notes: $None$
	Asset:BankA 500.00 CAD
		guid: "5ce0a4100000000000000000000000a2"
	Asset:BankB -500.00 CAD
		guid: "5ce0a4100000000000000000000000b2"
		memo: $None$
		alert: "interest APR 24.99%, I should repay early"

The import warns:

  ⚠ '2026-01-10 * "A draft from bank account b"': `notes` is a GnuCash field, which cannot be removed or set to #None, so `notes: $None$` sets it to "". An empty field is not written in the export, which does not mean it was removed.
  ⚠ 'Asset:BankB -500.00 CAD': `memo` is a GnuCash field, which cannot be removed or set to #None, so `memo: $None$` sets it to "". An empty field is not written in the export, which does not mean it was removed.

Exported, `a_draft_s_fields_2_stating_notes_and_memo_none_between_dollar_signs_exported.txt`:

2026-01-10 * "A draft from bank account b"
	guid: "5ce0a4100000000000000000000000d2"
	Asset:BankA 500.00 CAD
		guid: "5ce0a4100000000000000000000000a2"
	Asset:BankB -500.00 CAD
		guid: "5ce0a4100000000000000000000000b2"
		alert: "interest APR 24.99%, I should repay early"

Step 3, `a_draft_s_fields_3_with_notes_and_a_memo_again.txt`: the notes and
the memo set again.

2026-01-10 * "A draft from bank account b"
	guid: "5ce0a4100000000000000000000000d2"
	notes: "DONT DO THIS AGAIN"
	Asset:BankA 500.00 CAD
		guid: "5ce0a4100000000000000000000000a2"
	Asset:BankB -500.00 CAD
		guid: "5ce0a4100000000000000000000000b2"
		memo: "interest APR 24.99%, I should repay early"

Exported, `a_draft_s_fields_3_with_notes_and_a_memo_again_exported.txt`, with
`alert:` kept, since a key a block does not state says nothing about it; no
warning:

2026-01-10 * "A draft from bank account b"
	guid: "5ce0a4100000000000000000000000d2"
	notes: "DONT DO THIS AGAIN"
	Asset:BankA 500.00 CAD
		guid: "5ce0a4100000000000000000000000a2"
	Asset:BankB -500.00 CAD
		guid: "5ce0a4100000000000000000000000b2"
		memo:"interest APR 24.99%, I should repay early"
		alert: "interest APR 24.99%, I should repay early"

Step 4, `a_draft_s_fields_4_stating_notes_and_memo_as_null.txt`: `#None` on
both.

2026-01-10 * "A draft from bank account b"
	guid: "5ce0a4100000000000000000000000d2"
	notes: #None
	Asset:BankA 500.00 CAD
		guid: "5ce0a4100000000000000000000000a2"
	Asset:BankB -500.00 CAD
		guid: "5ce0a4100000000000000000000000b2"
		memo: #None

The import warns:

  ⚠ '2026-01-10 * "A draft from bank account b"': `notes` is a GnuCash field, which cannot be removed or set to #None, so `notes: #None` sets it to "". An empty field is not written in the export, which does not mean it was removed.
  ⚠ 'Asset:BankB -500.00 CAD': `memo` is a GnuCash field, which cannot be removed or set to #None, so `memo: #None` sets it to "". An empty field is not written in the export, which does not mean it was removed.

Exported, `a_draft_s_fields_4_stating_notes_and_memo_as_null_exported.txt`:

2026-01-10 * "A draft from bank account b"
	guid: "5ce0a4100000000000000000000000d2"
	Asset:BankA 500.00 CAD
		guid: "5ce0a4100000000000000000000000a2"
	Asset:BankB -500.00 CAD
		guid: "5ce0a4100000000000000000000000b2"
		alert: "interest APR 24.99%, I should repay early"

Step 5, `a_draft_s_fields_5_with_an_action.txt`: an action on the split.

2026-01-10 * "A draft from bank account b"
	guid: "5ce0a4100000000000000000000000d2"
	Asset:BankA 500.00 CAD
		guid: "5ce0a4100000000000000000000000a2"
	Asset:BankB -500.00 CAD
		guid: "5ce0a4100000000000000000000000b2"
		action: "Draft"

Exported, `a_draft_s_fields_5_with_an_action_exported.txt`; no warning:

2026-01-10 * "A draft from bank account b"
	guid: "5ce0a4100000000000000000000000d2"
	Asset:BankA 500.00 CAD
		guid: "5ce0a4100000000000000000000000a2"
	Asset:BankB -500.00 CAD
		guid: "5ce0a4100000000000000000000000b2"
		action: "Draft"
		alert: "interest APR 24.99%, I should repay early"

Step 6, `a_draft_s_fields_6_stating_the_action_as_null.txt`: `#None` on the
action, which GnuCash's setter ignores, so the action is kept.

2026-01-10 * "A draft from bank account b"
	guid: "5ce0a4100000000000000000000000d2"
	Asset:BankA 500.00 CAD
		guid: "5ce0a4100000000000000000000000a2"
	Asset:BankB -500.00 CAD
		guid: "5ce0a4100000000000000000000000b2"
		action: #None

The import warns:

  ⚠ 'Asset:BankB -500.00 CAD': `action: #None` was stated, and GnuCash keeps `action: "Draft"`.

Exported, `a_draft_s_fields_6_stating_the_action_as_null_exported.txt`:

2026-01-10 * "A draft from bank account b"
	guid: "5ce0a4100000000000000000000000d2"
	Asset:BankA 500.00 CAD
		guid: "5ce0a4100000000000000000000000a2"
	Asset:BankB -500.00 CAD
		guid: "5ce0a4100000000000000000000000b2"
		action: "Draft"
		alert: "interest APR 24.99%, I should repay early"

Step 7, `a_draft_s_fields_7_with_a_doc_link.txt`: a doc link on the
transaction. Steps 9 and 11 import the same file again.

2026-01-10 * "A draft from bank account b"
	guid: "5ce0a4100000000000000000000000d2"
	doc_link: "https://bank.example/drafts/500.pdf"
	Asset:BankA 500.00 CAD
		guid: "5ce0a4100000000000000000000000a2"
	Asset:BankB -500.00 CAD
		guid: "5ce0a4100000000000000000000000b2"

Exported, `a_draft_s_fields_7_with_a_doc_link_exported.txt`; no warning:

2026-01-10 * "A draft from bank account b"
	guid: "5ce0a4100000000000000000000000d2"
	doc_link: "https://bank.example/drafts/500.pdf"
	Asset:BankA 500.00 CAD
		guid: "5ce0a4100000000000000000000000a2"
	Asset:BankB -500.00 CAD
		guid: "5ce0a4100000000000000000000000b2"
		action: "Draft"
		alert: "interest APR 24.99%, I should repay early"

Step 8, `a_draft_s_fields_8_stating_the_doc_link_as_null.txt`: `#None` on the
doc link, which sets it to `#None`; no warning.

2026-01-10 * "A draft from bank account b"
	guid: "5ce0a4100000000000000000000000d2"
	doc_link: #None
	Asset:BankA 500.00 CAD
		guid: "5ce0a4100000000000000000000000a2"
	Asset:BankB -500.00 CAD
		guid: "5ce0a4100000000000000000000000b2"

Exported, `a_draft_s_fields_8_stating_the_doc_link_as_null_exported.txt`, with
no `doc_link:` line, since the export writes none for `#None`:

2026-01-10 * "A draft from bank account b"
	guid: "5ce0a4100000000000000000000000d2"
	Asset:BankA 500.00 CAD
		guid: "5ce0a4100000000000000000000000a2"
	Asset:BankB -500.00 CAD
		guid: "5ce0a4100000000000000000000000b2"
		action: "Draft"
		alert: "interest APR 24.99%, I should repay early"

Step 9 sets the doc link again, and exports as step 7; no warning.

Step 10, `a_draft_s_fields_10_stating_the_doc_link_none_between_dollar_signs.txt`:

2026-01-10 * "A draft from bank account b"
	guid: "5ce0a4100000000000000000000000d2"
	doc_link: $None$
	Asset:BankA 500.00 CAD
		guid: "5ce0a4100000000000000000000000a2"
	Asset:BankB -500.00 CAD
		guid: "5ce0a4100000000000000000000000b2"

The import warns:

  ⚠ '2026-01-10 * "A draft from bank account b"': `doc_link` is a GnuCash field, which cannot be removed, so `doc_link: $None$` sets it to #None.

Exported, `a_draft_s_fields_10_stating_the_doc_link_none_between_dollar_signs_exported.txt`:

2026-01-10 * "A draft from bank account b"
	guid: "5ce0a4100000000000000000000000d2"
	Asset:BankA 500.00 CAD
		guid: "5ce0a4100000000000000000000000a2"
	Asset:BankB -500.00 CAD
		guid: "5ce0a4100000000000000000000000b2"
		action: "Draft"
		alert: "interest APR 24.99%, I should repay early"

Step 11 sets the doc link again, and exports as step 7; no warning.

Step 12, `a_draft_s_fields_12_stating_the_doc_link_empty.txt`:

2026-01-10 * "A draft from bank account b"
	guid: "5ce0a4100000000000000000000000d2"
	doc_link: ""
	Asset:BankA 500.00 CAD
		guid: "5ce0a4100000000000000000000000a2"
	Asset:BankB -500.00 CAD
		guid: "5ce0a4100000000000000000000000b2"

The import warns:

  ⚠ '2026-01-10 * "A draft from bank account b"': `doc_link: ""` was stated, and GnuCash keeps `doc_link: #None`.

Exported, `a_draft_s_fields_12_stating_the_doc_link_empty_exported.txt`:

2026-01-10 * "A draft from bank account b"
	guid: "5ce0a4100000000000000000000000d2"
	Asset:BankA 500.00 CAD
		guid: "5ce0a4100000000000000000000000a2"
	Asset:BankB -500.00 CAD
		guid: "5ce0a4100000000000000000000000b2"
		action: "Draft"
		alert: "interest APR 24.99%, I should repay early"
"""

import re
from pathlib import Path

from click.testing import CliRunner

from tests.conftest import _run

FIXTURES = Path('tests/fixtures')

STEPS = [
    'a_draft_s_fields_1_with_notes_and_a_memo',
    'a_draft_s_fields_2_stating_notes_and_memo_none_between_dollar_signs',
    'a_draft_s_fields_3_with_notes_and_a_memo_again',
    'a_draft_s_fields_4_stating_notes_and_memo_as_null',
    'a_draft_s_fields_5_with_an_action',
    'a_draft_s_fields_6_stating_the_action_as_null',
    'a_draft_s_fields_7_with_a_doc_link',
    'a_draft_s_fields_8_stating_the_doc_link_as_null',
    'a_draft_s_fields_7_with_a_doc_link',
    'a_draft_s_fields_10_stating_the_doc_link_none_between_dollar_signs',
    'a_draft_s_fields_7_with_a_doc_link',
    'a_draft_s_fields_12_stating_the_doc_link_empty',
]

TRANSACTION = '2026-01-10 * "A draft from bank account b"'
SPLIT = 'Asset:BankB -500.00 CAD'


def _emptied(stated):
    return [
        f'⚠ {line!r}: `{key}` is a GnuCash field, which cannot be removed or set to '
        f'#None, so `{key}: {stated}` sets it to "". An empty field is not written in '
        f'the export, which does not mean it was removed.'
        for key, line in (('notes', TRANSACTION), ('memo', SPLIT))]


def _after(tmp_path, last):
    """The draft as `export` writes it after steps 1 to `last`, and the warnings the last import printed.

    The whole draft, every line of it, and every warning, so a line or a
    warning no step states fails as surely as one missing.
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
    warnings = [line.strip() for line in done.output.splitlines()
                if line.strip().startswith('⚠')]
    return draft.group(0), warnings


def _expected(last):
    return (FIXTURES / f'{STEPS[last - 1]}_exported.txt').read_text()


def test_1_the_notes_and_the_memo_are_set(tmp_path):
    assert _after(tmp_path, 1) == (_expected(1), [])


def test_2_none_between_dollar_signs_sets_the_notes_and_the_memo_to_empty_and_warns(tmp_path):
    assert _after(tmp_path, 2) == (_expected(2), _emptied('$None$'))


def test_3_the_notes_and_the_memo_are_set_again(tmp_path):
    assert _after(tmp_path, 3) == (_expected(3), [])


def test_4_none_sets_the_notes_and_the_memo_to_empty_and_warns(tmp_path):
    assert _after(tmp_path, 4) == (_expected(4), _emptied('#None'))


def test_5_an_action_is_set(tmp_path):
    assert _after(tmp_path, 5) == (_expected(5), [])


def test_6_none_on_the_action_keeps_what_gnucash_keeps_and_says_so(tmp_path):
    assert _after(tmp_path, 6) == (_expected(6), [
        f'⚠ {SPLIT!r}: `action: #None` was stated, and GnuCash keeps `action: "Draft"`.'])


def test_7_a_doc_link_is_set(tmp_path):
    assert _after(tmp_path, 7) == (_expected(7), [])


def test_8_none_sets_the_doc_link_to_none(tmp_path):
    assert _after(tmp_path, 8) == (_expected(8), [])


def test_9_the_doc_link_is_set_again(tmp_path):
    assert _after(tmp_path, 9) == (_expected(7), [])


def test_10_none_between_dollar_signs_sets_the_doc_link_to_none_and_warns(tmp_path):
    assert _after(tmp_path, 10) == (_expected(10), [
        f'⚠ {TRANSACTION!r}: `doc_link` is a GnuCash field, which cannot be removed, '
        f'so `doc_link: $None$` sets it to #None.'])


def test_11_the_doc_link_is_set_again(tmp_path):
    assert _after(tmp_path, 11) == (_expected(7), [])


def test_12_empty_on_the_doc_link_keeps_what_gnucash_keeps_and_says_so(tmp_path):
    assert _after(tmp_path, 12) == (_expected(12), [
        f'⚠ {TRANSACTION!r}: `doc_link: ""` was stated, and GnuCash keeps `doc_link: #None`.'])
