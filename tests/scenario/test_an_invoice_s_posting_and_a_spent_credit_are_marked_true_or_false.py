"""An invoice's posting and a credit spent on an invoice are marked `#True` or `#False`.

The rules are the author's, set after Q-054 shipped with gnucash-plaintext's
own `bool` keys stored as the text `"true"`: such a key is `#True` or
`#False` when stored and when exported, a file may also write `#True` as
`"true"`, `"yes"` or `1` and `#False` as `"false"`, `"no"` or `0`, `""` and
any other value on one is refused, and only `$None$` removes one.

The case: customer C001 overpays INV-001 by 50.00, and INV-002, for 30.00,
spends that credit with `auto_apply_credit: true`. Posting each invoice marks
its transaction `business_generated`; spending the credit marks the split it
spent `applied_from_credit`. Step 1 is imported into a new book with
`--include-business-objects`; every step after it with `--strategy update`
over the book the step before left, restating the payment or INV-002's
posting as the export writes it. GnuCash gives those transactions guids of
its own, so the fixtures write each as a name in braces — `{payment}`,
`{spent}`, `{posting}` and the rest — and the test fills them in from step
1's export. After each step, `export` writes the payment and the posting as
the fixture named states, and the import prints exactly the warnings and the
refusal stated here. A refused step leaves the book as the step before it.

Step 1, `tests/fixtures/an_invoice_s_marks_1_a_credit_spent_on_the_next_invoice.txt`:
the accounts, C001, and

invoice "INV-001"
	customer_id: "C001"
	currency: CAD
	date_opened: 2026-01-01
	entry: … 1 × 100 on Income:Sales …
	posted: … 2026-01-01 to Assets:Accounts Receivable, memo "INV-001" …
	payment:
		date: 2026-01-10
		amount: 150
		bank_account: "Assets:Bank"
		memo: "Overpaid"
		prepayment: 50

invoice "INV-002"
	customer_id: "C001"
	currency: CAD
	date_opened: 2026-02-01
	auto_apply_credit: true
	entry: … 1 × 30 on Income:Sales …
	posted: … 2026-02-01 to Assets:Accounts Receivable, memo "INV-002" …

Exported, `an_invoice_s_marks_1_a_credit_spent_on_the_next_invoice_exported.txt`;
no warning:

2026-01-10 * "Acme"
	guid: "{payment}"
	txn_type: P
	owner: customer:C001
	Assets:Bank 150.00 CAD
		guid: "{bank}"
		action: "Payment"
		memo:"Overpaid"
	Assets:Accounts Receivable -100.00 CAD
		guid: "{settled}"
		action: "Payment"
		memo:"Overpaid"
	Assets:Accounts Receivable -30.00 CAD
		guid: "{spent}"
		action: "Payment"
		memo:"Overpaid"
		applied_from_credit: #True
	Assets:Accounts Receivable -20.00 CAD
		guid: "{credit}"
		action: "Payment"
		memo:"Overpaid"
		lot_owner: customer:C001:{customer}
		lot_guid: "{lot}"
2026-02-01 * "INV-002" "INV-002"
	guid: "{posting}"
	txn_type: I
	owner: customer:C001
	business_generated: #True
	Assets:Accounts Receivable 30.00 CAD
		guid: "{posting_ar}"
		action: "Invoice"
		memo:"INV-002"
	Income:Sales -30.00 CAD
		guid: "{posting_sales}"
		action: "Invoice"
		memo:"INV-002"

Steps 2 to 5 restate INV-002's posting as that export writes it, with its
`business_generated:` line as the step states:

Step 2, `an_invoice_s_marks_2_the_posting_stated_false.txt`: `#False`.
Exported as `an_invoice_s_marks_2_the_posting_stated_false_exported.txt`,
step 1's export with `business_generated: #False`; no warning.

Step 3, `an_invoice_s_marks_3_the_posting_stated_as_1.txt`: `1`. Exported as
step 1's, `#True`; no warning.

Step 4, `an_invoice_s_marks_4_the_posting_stated_empty.txt`: `""`. Refused:

  '2026-02-01 * "INV-002" "INV-002"': `business_generated` is gnucash-plaintext's own key, so `business_generated: ""` is refused. It states nothing; to remove the key, write `business_generated: $None$`.

Step 5, `an_invoice_s_marks_5_the_posting_stated_as_the_text_maybe.txt`:
`"maybe"`. Refused:

  '2026-02-01 * "INV-002" "INV-002"': `business_generated` is gnucash-plaintext's own key, so `business_generated: "maybe"` is refused. It holds #True or #False, which may also be written "true", "yes" or 1, and "false", "no" or 0.

After each of steps 4 and 5 the book is step 3's.

Steps 6 to 10 restate the payment as step 1's export writes it, with the
spent split's `applied_from_credit:` line as the step states:

Step 6, `an_invoice_s_marks_6_the_spent_credit_stated_false.txt`: `#False`.
Exported as `an_invoice_s_marks_6_the_spent_credit_stated_false_exported.txt`,
step 1's export with `applied_from_credit: #False`; no warning.

Step 7, `an_invoice_s_marks_7_the_spent_credit_stated_as_the_text_yes.txt`:
`"yes"`. Exported as step 1's, `#True`; no warning.

Step 8, `an_invoice_s_marks_8_the_spent_credit_stated_empty.txt`: `""`.
Refused:

  'Assets:Accounts Receivable -30.00 CAD': `applied_from_credit` is gnucash-plaintext's own key, so `applied_from_credit: ""` is refused. It states nothing; to remove the key, write `applied_from_credit: $None$`.

Step 9, `an_invoice_s_marks_9_the_spent_credit_stated_as_the_text_maybe.txt`:
`"maybe"`. Refused:

  'Assets:Accounts Receivable -30.00 CAD': `applied_from_credit` is gnucash-plaintext's own key, so `applied_from_credit: "maybe"` is refused. It holds #True or #False, which may also be written "true", "yes" or 1, and "false", "no" or 0.

After each of steps 8 and 9 the book is step 7's.

Step 10, `an_invoice_s_marks_10_the_spent_credit_s_mark_removed.txt`:
`$None$`. Exported as
`an_invoice_s_marks_10_the_spent_credit_s_mark_removed_exported.txt`, step
1's export with no `applied_from_credit:` line; no warning.
"""

import re
from pathlib import Path

from click.testing import CliRunner

from tests.conftest import _run

FIXTURES = Path('tests/fixtures')

STEPS = [
    'an_invoice_s_marks_1_a_credit_spent_on_the_next_invoice',
    'an_invoice_s_marks_2_the_posting_stated_false',
    'an_invoice_s_marks_3_the_posting_stated_as_1',
    'an_invoice_s_marks_4_the_posting_stated_empty',
    'an_invoice_s_marks_5_the_posting_stated_as_the_text_maybe',
    'an_invoice_s_marks_6_the_spent_credit_stated_false',
    'an_invoice_s_marks_7_the_spent_credit_stated_as_the_text_yes',
    'an_invoice_s_marks_8_the_spent_credit_stated_empty',
    'an_invoice_s_marks_9_the_spent_credit_stated_as_the_text_maybe',
    'an_invoice_s_marks_10_the_spent_credit_s_mark_removed',
]

# The steps whose file is refused whole, leaving the book as the step before it left it.
REFUSED = {4, 5, 8, 9}

BOTH_TRUE = 'an_invoice_s_marks_1_a_credit_spent_on_the_next_invoice_exported'
POSTING_FALSE = 'an_invoice_s_marks_2_the_posting_stated_false_exported'
SPENT_FALSE = 'an_invoice_s_marks_6_the_spent_credit_stated_false_exported'
SPENT_REMOVED = 'an_invoice_s_marks_10_the_spent_credit_s_mark_removed_exported'

POSTING = '2026-02-01 * "INV-002" "INV-002"'
SPENT = 'Assets:Accounts Receivable -30.00 CAD'
GUID = r'([0-9a-f]{32})'

# Each guid in step 1's export, in the order its two blocks write them.
NAMES = ('payment', 'bank', 'settled', 'spent', 'credit', 'customer', 'lot',
         'posting', 'posting_ar', 'posting_sales')


def _refused(key, stated, line):
    return f"{line!r}: `{key}` is gnucash-plaintext's own key, so `{key}: {stated}` is refused."


def _refused_empty(key, line):
    return (_refused(key, '""', line)
            + f' It states nothing; to remove the key, write `{key}: $None$`.')


def _refused_maybe(key, line):
    return (_refused(key, '"maybe"', line)
            + ' It holds #True or #False, which may also be written "true", "yes" or 1, '
              'and "false", "no" or 0.')


def _warnings(output):
    return [line.strip() for line in output.splitlines() if line.strip().startswith('⚠')]


def _blocks(book, tmp_path):
    out = tmp_path / 'out.txt'
    exported = _run(CliRunner(), 'export', str(book), str(out))
    assert exported.exit_code == 0, exported.output
    text = out.read_text()
    return ''.join(re.search(re.escape(head) + r'\n(?:\t[^\n]*\n)*', text).group(0)
                   for head in ('2026-01-10 * "Acme"', POSTING))


def _filled(name, guids):
    text = (FIXTURES / f'{name}.txt').read_text()
    for key, guid in guids.items():
        text = text.replace('{' + key + '}', guid)
    return text


def _steps(tmp_path, last):
    """The payment and the posting as exported before step `last` and after it, that step's import output, and the guids.

    Before step 1 there is no book, so `before` is None.
    """
    book = tmp_path / 'book.gnucash'
    done = _run(CliRunner(), 'import', '--new', str(book), str(FIXTURES / f'{STEPS[0]}.txt'),
                '--include-business-objects')
    assert done.exit_code == 0 and 'Errors:       0' in done.output, done.output
    guids = dict(zip(NAMES, re.findall(GUID, _blocks(book, tmp_path))))
    before = None
    for number, step in enumerate(STEPS[1:last], start=2):
        if number == last:
            before = _blocks(book, tmp_path)
        ledger = tmp_path / f'{step}.txt'
        ledger.write_text(_filled(step, guids))
        done = _run(CliRunner(), 'import', '--strategy', 'update', str(book), str(ledger))
        if number < last:
            assert (done.exit_code == 1 if number in REFUSED
                    else done.exit_code == 0 and 'Errors:       0' in done.output), done.output
    return before, _blocks(book, tmp_path), done, guids


def _business_generated(blocks):
    """What INV-002's posting states for `business_generated:`, or None where it states none."""
    found = re.search(r'\n\tbusiness_generated: ([^\n]*)\n', blocks[blocks.index(POSTING):])
    return found.group(1) if found else None


def _applied_from_credit(blocks):
    """What the spent split states for `applied_from_credit:`, or None where it states none."""
    spent = blocks[blocks.index(SPENT):blocks.index('Assets:Accounts Receivable -20.00 CAD')]
    found = re.search(r'\n\t\tapplied_from_credit: ([^\n]*)\n', spent)
    return found.group(1) if found else None


def _accepted(done):
    assert done.exit_code == 0 and 'Errors:       0' in done.output, done.output
    assert _warnings(done.output) == [], done.output


def _refused_with(done, refusal):
    assert done.exit_code == 1, done.output
    assert 'could not be read, so nothing was imported' in done.output, done.output
    assert refusal in done.output, done.output
    assert _warnings(done.output) == [], done.output


def test_1_posting_marks_business_generated_and_spending_marks_applied_from_credit_true(tmp_path):
    """Posting an invoice and spending a credit mark both #True.

    `import --new --include-business-objects` of INV-001, overpaid by 50.00,
    and INV-002, spending that credit. Posting INV-002 marks its transaction
    `business_generated`, and spending the credit marks the spent split
    `applied_from_credit`, both stored as #True, not the text "true".
    """
    _, after, done, guids = _steps(tmp_path, 1)
    _accepted(done)
    assert _business_generated(after) == '#True'
    assert _applied_from_credit(after) == '#True'
    assert after == _filled(BOTH_TRUE, guids)


def test_2_business_generated_false_is_stored_and_exported_as_false(tmp_path):
    """#False on the posting is stored and exported as #False.

    `import --strategy update` of INV-002's posting transaction, stating
    `business_generated: #False`, a bool. The mark goes from #True to #False,
    and the spent split's mark is untouched.
    """
    before, after, done, guids = _steps(tmp_path, 2)
    _accepted(done)
    assert _business_generated(before) == '#True'
    assert _business_generated(after) == '#False'
    assert _applied_from_credit(after) == '#True'
    assert after == _filled(POSTING_FALSE, guids)


def test_3_business_generated_1_is_stored_and_exported_as_true(tmp_path):
    """The number 1 on the posting is read as #True.

    `import --strategy update` of INV-002's posting transaction, stating
    `business_generated: 1`. The key is gnucash-plaintext's own and holds a
    bool, so the number 1 is stored as #True and exported as #True. The mark
    goes from #False to #True.
    """
    before, after, done, guids = _steps(tmp_path, 3)
    _accepted(done)
    assert _business_generated(before) == '#False'
    assert _business_generated(after) == '#True'
    assert after == _filled(BOTH_TRUE, guids)


def test_4_business_generated_empty_is_refused(tmp_path):
    """The empty text on the posting is refused, and the mark is kept.

    `import --strategy update` of INV-002's posting transaction, stating
    `business_generated: ""`. The empty text states nothing, and only `$None$`
    removes a key, so the file is refused whole and the mark stays #True.
    """
    before, after, done, guids = _steps(tmp_path, 4)
    _refused_with(done, _refused_empty('business_generated', POSTING))
    assert _business_generated(before) == '#True'
    assert _business_generated(after) == '#True'
    assert after == before == _filled(BOTH_TRUE, guids)


def test_5_business_generated_a_text_that_is_neither_true_nor_false_is_refused(tmp_path):
    """A text that is neither true nor false on the posting is refused, and the mark is kept.

    `import --strategy update` of INV-002's posting transaction, stating
    `business_generated: "maybe"`. It is no spelling of #True or #False, so the
    file is refused whole and the mark stays #True.
    """
    before, after, done, guids = _steps(tmp_path, 5)
    _refused_with(done, _refused_maybe('business_generated', POSTING))
    assert _business_generated(before) == '#True'
    assert _business_generated(after) == '#True'
    assert after == before == _filled(BOTH_TRUE, guids)


def test_6_applied_from_credit_false_is_stored_and_exported_as_false(tmp_path):
    """#False on the spent split is stored and exported as #False.

    `import --strategy update` of the payment transaction, its spent split
    stating `applied_from_credit: #False`, a bool. The mark goes from #True to
    #False, and the posting's mark is untouched.
    """
    before, after, done, guids = _steps(tmp_path, 6)
    _accepted(done)
    assert _applied_from_credit(before) == '#True'
    assert _applied_from_credit(after) == '#False'
    assert _business_generated(after) == '#True'
    assert after == _filled(SPENT_FALSE, guids)


def test_7_applied_from_credit_the_text_yes_is_stored_and_exported_as_true(tmp_path):
    """The text "yes" on the spent split is read as #True.

    `import --strategy update` of the payment transaction, its spent split
    stating `applied_from_credit: "yes"`. The key holds a bool, so the text yes
    is stored as #True and exported as #True. The mark goes from #False to #True.
    """
    before, after, done, guids = _steps(tmp_path, 7)
    _accepted(done)
    assert _applied_from_credit(before) == '#False'
    assert _applied_from_credit(after) == '#True'
    assert after == _filled(BOTH_TRUE, guids)


def test_8_applied_from_credit_empty_is_refused(tmp_path):
    """The empty text on the spent split is refused, and the mark is kept.

    `import --strategy update` of the payment transaction, its spent split
    stating `applied_from_credit: ""`. The empty text states nothing, so the
    file is refused whole and the mark stays #True.
    """
    before, after, done, guids = _steps(tmp_path, 8)
    _refused_with(done, _refused_empty('applied_from_credit', SPENT))
    assert _applied_from_credit(before) == '#True'
    assert _applied_from_credit(after) == '#True'
    assert after == before == _filled(BOTH_TRUE, guids)


def test_9_applied_from_credit_a_text_that_is_neither_true_nor_false_is_refused(tmp_path):
    """A text that is neither true nor false on the spent split is refused, and the mark is kept.

    `import --strategy update` of the payment transaction, its spent split
    stating `applied_from_credit: "maybe"`. It is no spelling of #True or
    #False, so the file is refused whole and the mark stays #True.
    """
    before, after, done, guids = _steps(tmp_path, 9)
    _refused_with(done, _refused_maybe('applied_from_credit', SPENT))
    assert _applied_from_credit(before) == '#True'
    assert _applied_from_credit(after) == '#True'
    assert after == before == _filled(BOTH_TRUE, guids)


def test_10_applied_from_credit_none_between_dollar_signs_removes_it(tmp_path):
    """`$None$` on the spent split removes its mark.

    `import --strategy update` of the payment transaction, its spent split
    stating `applied_from_credit: $None$`, without quotes. The mark goes from
    #True to none, and the posting's mark is untouched.
    """
    before, after, done, guids = _steps(tmp_path, 10)
    _accepted(done)
    assert _applied_from_credit(before) == '#True'
    assert _applied_from_credit(after) is None
    assert _business_generated(after) == '#True'
    assert after == _filled(SPENT_REMOVED, guids)
