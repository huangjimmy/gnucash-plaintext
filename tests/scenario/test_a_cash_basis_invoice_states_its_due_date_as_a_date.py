"""A cash-basis invoice states `cash_basis` as `#True` or `#False` and its due date as a date.

Q-018's two keys on an invoice awaiting cash: `cash_basis`, a `bool`, and
`due_date`, a date. The rules are the author's, set after Q-054 shipped with
`cash_basis` stored as the text `"true"`: a `bool` key of gnucash-plaintext's
own is `#True` or `#False` when stored and when exported, a file may also
write `#True` as `"true"`, `"yes"` or `1` and `#False` as `"false"`, `"no"` or
`0`, and a word without quotes such as `true` is refused; a date is written
`2026-05-30`, without quotes, and on a date key of gnucash-plaintext's own a
date in quotes is read as the date and exported without them.

Step 1 is imported into a new book with `--include-business-objects`; every
step after it restates the invoice. The book gives the invoice, its customer
and its line guids of its own, so the exported fixtures write each as a name
in braces, `{invoice}`, `{customer}` and `{entry}`, and the test fills them
in from step 1's export. After each step, `export` writes the invoice as the
fixture named states, and the import prints exactly the refusal stated here.
A refused step leaves the book as the step before it.

Step 1, `tests/fixtures/a_cash_basis_invoice_1_awaiting_cash_due_on_a_date.txt`:
the accounts, customer C-Q18-U1, and

invoice "INV-Q18-UNPOSTED-WITH-DUE"
	customer_id: "C-Q18-U1"
	currency: CAD
	date_opened: 2026-05-01
	cash_basis: #True
	due_date: 2026-05-30
	entry: … 1 × 80 on Income:Sales …
	posted: none
	payment: none

Exported, `a_cash_basis_invoice_1_awaiting_cash_due_on_a_date_exported.txt`:
`cash_basis: #True` and `due_date: 2026-05-30`.

Steps 2 to 8 restate the invoice with its `cash_basis:` and `due_date:`
lines as the step states:

Step 2, `a_cash_basis_invoice_2_due_on_the_text_of_a_date.txt`:
`due_date: "2026-06-15"`, in quotes. Exported as
`a_cash_basis_invoice_2_due_on_the_text_of_a_date_exported.txt`,
`due_date: 2026-06-15`, a date.

Step 3, `a_cash_basis_invoice_3_stating_cash_basis_false.txt`:
`cash_basis: #False`. Exported as
`a_cash_basis_invoice_3_stating_cash_basis_false_exported.txt`,
`cash_basis: #False`.

Step 4, `a_cash_basis_invoice_4_stating_cash_basis_as_the_text_true.txt`:
`cash_basis: "true"`. Exported as step 2's, `cash_basis: #True`.

Step 5, `a_cash_basis_invoice_5_due_on_a_text_that_is_no_date.txt`:
`due_date: "soon"`. Refused, and the book is step 4's:

  'invoice "INV-Q18-UNPOSTED-WITH-DUE"': `due_date` is gnucash-plaintext's own key, so `due_date: "soon"` is refused. It holds a date, written YYYY-MM-DD, such as 2026-01-31.

Step 6, `a_cash_basis_invoice_6_due_on_a_day_the_calendar_has_not.txt`:
`due_date: 2026-02-30`. Refused the same way, stating `due_date: 2026-02-30`.

Step 7, `a_cash_basis_invoice_7_stating_cash_basis_as_a_bare_true.txt`:
`cash_basis: true`, a word without quotes. Refused:

  'invoice "INV-Q18-UNPOSTED-WITH-DUE"': `cash_basis` is gnucash-plaintext's own key, so `cash_basis: true` is refused. It holds #True or #False, which may also be written "true", "yes" or 1, and "false", "no" or 0.

Step 8, `a_cash_basis_invoice_8_removing_the_due_date.txt`:
`due_date: $None$`. Exported as
`a_cash_basis_invoice_8_removing_the_due_date_exported.txt`, with no
`due_date:` line.
"""

import re
from pathlib import Path

from click.testing import CliRunner

from tests.conftest import _run

FIXTURES = Path('tests/fixtures')

STEPS = [
    'a_cash_basis_invoice_1_awaiting_cash_due_on_a_date',
    'a_cash_basis_invoice_2_due_on_the_text_of_a_date',
    'a_cash_basis_invoice_3_stating_cash_basis_false',
    'a_cash_basis_invoice_4_stating_cash_basis_as_the_text_true',
    'a_cash_basis_invoice_5_due_on_a_text_that_is_no_date',
    'a_cash_basis_invoice_6_due_on_a_day_the_calendar_has_not',
    'a_cash_basis_invoice_7_stating_cash_basis_as_a_bare_true',
    'a_cash_basis_invoice_8_removing_the_due_date',
]

REFUSED = {5, 6, 7}

DUE_ON_A_DATE = 'a_cash_basis_invoice_1_awaiting_cash_due_on_a_date_exported'
DUE_LATER = 'a_cash_basis_invoice_2_due_on_the_text_of_a_date_exported'
NOT_CASH_BASIS = 'a_cash_basis_invoice_3_stating_cash_basis_false_exported'
NO_DUE_DATE = 'a_cash_basis_invoice_8_removing_the_due_date_exported'

INVOICE = 'invoice "INV-Q18-UNPOSTED-WITH-DUE"'
HOLDS_A_DATE = ' It holds a date, written YYYY-MM-DD, such as 2026-01-31.'
HOLDS_TRUE_OR_FALSE = (' It holds #True or #False, which may also be written "true", "yes" '
                       'or 1, and "false", "no" or 0.')


def _refused(key, stated):
    return f"{INVOICE!r}: `{key}` is gnucash-plaintext's own key, so `{key}: {stated}` is refused."


def _warnings(output):
    return [line.strip() for line in output.splitlines() if line.strip().startswith('⚠')]


def _invoice(book, tmp_path):
    out = tmp_path / 'out.txt'
    exported = _run(CliRunner(), 'export', str(book), str(out), '--include-business-objects')
    assert exported.exit_code == 0, exported.output
    return re.search(re.escape(INVOICE) + r'\n(?:\t[^\n]*\n)*', out.read_text()).group(0)


def _filled(name, guids):
    text = (FIXTURES / f'{name}.txt').read_text()
    for key, guid in guids.items():
        text = text.replace('{' + key + '}', guid)
    return text


def _steps(tmp_path, last):
    """The invoice as exported before step `last` and after it, that step's import output, and the guids.

    Before step 1 there is no book, so `before` is None.
    """
    book = tmp_path / 'book.gnucash'
    before = None
    for number, step in enumerate(STEPS[:last], start=1):
        if number == last and number > 1:
            before = _invoice(book, tmp_path)
        args = ['import', str(book), str(FIXTURES / f'{step}.txt'), '--include-business-objects']
        if number == 1:
            args.insert(1, '--new')
        done = _run(CliRunner(), *args)
        if number < last:
            assert (done.exit_code == 1 if number in REFUSED
                    else done.exit_code == 0 and 'Errors:       0' in done.output), done.output
        if number == 1:
            first = _invoice(book, tmp_path)
            guids = dict(zip(('invoice', 'customer', 'entry'),
                             re.findall(r'"([0-9a-f]{32})"', first)))
    return before, _invoice(book, tmp_path), done, guids


def _line(invoice, key):
    """What the invoice states for `key:`, or None where it states none."""
    found = re.search(rf'\n\t{key}: ([^\n]*)\n', invoice)
    return found.group(1) if found else None


def _accepted(done):
    assert done.exit_code == 0 and 'Errors:       0' in done.output, done.output
    assert _warnings(done.output) == [], done.output


def _refused_with(done, refusal):
    assert done.exit_code == 1, done.output
    assert 'could not be read, so nothing was imported' in done.output, done.output
    assert refusal in done.output, done.output
    assert _warnings(done.output) == [], done.output


def test_1_cash_basis_holds_true_and_due_date_holds_a_date(tmp_path):
    """The invoice holds `cash_basis: #True` and `due_date: 2026-05-30`.

    `import --new --include-business-objects` of the unposted invoice, stating
    `cash_basis: #True`, a bool, and `due_date: 2026-05-30`, a date without
    quotes. Both are exported as stated.
    """
    _, after, done, guids = _steps(tmp_path, 1)
    _accepted(done)
    assert _line(after, 'cash_basis') == '#True'
    assert _line(after, 'due_date') == '2026-05-30'
    assert after == _filled(DUE_ON_A_DATE, guids)


def test_2_due_date_in_quotes_is_held_as_a_date(tmp_path):
    """A date in quotes on `due_date` is stored as a date and exported without quotes.

    `import --include-business-objects` of the invoice again, stating
    `due_date: "2026-06-15"`, the date as text. `due_date` is
    gnucash-plaintext's own key and holds a date, so the text is converted to
    the date. The due date goes from 2026-05-30 to 2026-06-15.
    """
    before, after, done, guids = _steps(tmp_path, 2)
    _accepted(done)
    assert _line(before, 'due_date') == '2026-05-30'
    assert _line(after, 'due_date') == '2026-06-15'
    assert after == _filled(DUE_LATER, guids)


def test_3_cash_basis_false_is_held_as_false(tmp_path):
    """#False on `cash_basis` is stored and exported as #False.

    `import --include-business-objects` of the invoice again, stating
    `cash_basis: #False`, a bool. It goes from #True to #False, and the due
    date stays 2026-06-15.
    """
    before, after, done, guids = _steps(tmp_path, 3)
    _accepted(done)
    assert _line(before, 'cash_basis') == '#True'
    assert _line(after, 'cash_basis') == '#False'
    assert _line(after, 'due_date') == '2026-06-15'
    assert after == _filled(NOT_CASH_BASIS, guids)


def test_4_cash_basis_the_text_true_is_held_as_true(tmp_path):
    """The text "true" on `cash_basis` is read as #True.

    `import --include-business-objects` of the invoice again, stating
    `cash_basis: "true"`. The key holds a bool, so the text true is stored as
    #True and exported as #True. It goes from #False to #True.
    """
    before, after, done, guids = _steps(tmp_path, 4)
    _accepted(done)
    assert _line(before, 'cash_basis') == '#False'
    assert _line(after, 'cash_basis') == '#True'
    assert after == _filled(DUE_LATER, guids)


def test_5_due_date_a_text_that_is_no_date_is_refused(tmp_path):
    """A text that is no date on `due_date` is refused, and the due date is kept.

    `import --include-business-objects` of the invoice again, stating
    `due_date: "soon"`. The file is refused whole, and the due date stays
    2026-06-15.
    """
    before, after, done, guids = _steps(tmp_path, 5)
    _refused_with(done, _refused('due_date', '"soon"') + HOLDS_A_DATE)
    assert _line(before, 'due_date') == '2026-06-15'
    assert _line(after, 'due_date') == '2026-06-15'
    assert after == before == _filled(DUE_LATER, guids)


def test_6_due_date_a_day_the_calendar_has_not_is_refused(tmp_path):
    """A day the calendar has not on `due_date` is refused, and the due date is kept.

    `import --include-business-objects` of the invoice again, stating
    `due_date: 2026-02-30`, without quotes. February has no 30th, so the file is
    refused whole, and the due date stays 2026-06-15.
    """
    before, after, done, guids = _steps(tmp_path, 6)
    _refused_with(done, _refused('due_date', '2026-02-30') + HOLDS_A_DATE)
    assert _line(before, 'due_date') == '2026-06-15'
    assert _line(after, 'due_date') == '2026-06-15'
    assert after == before == _filled(DUE_LATER, guids)


def test_7_cash_basis_a_bare_true_is_refused(tmp_path):
    """A bare `true` on `cash_basis` is refused, and the key is kept.

    `import --include-business-objects` of the invoice again, stating
    `cash_basis: true`, a word without quotes. The file is refused whole, and
    `cash_basis` stays #True.
    """
    before, after, done, guids = _steps(tmp_path, 7)
    _refused_with(done, _refused('cash_basis', 'true') + HOLDS_TRUE_OR_FALSE)
    assert _line(before, 'cash_basis') == '#True'
    assert _line(after, 'cash_basis') == '#True'
    assert after == before == _filled(DUE_LATER, guids)


def test_8_due_date_none_between_dollar_signs_removes_it(tmp_path):
    """`$None$` on `due_date` removes the due date.

    `import --include-business-objects` of the invoice again, stating
    `due_date: $None$`, without quotes. The due date goes from 2026-06-15 to
    none, and `cash_basis` stays #True.
    """
    before, after, done, guids = _steps(tmp_path, 8)
    _accepted(done)
    assert _line(before, 'due_date') == '2026-06-15'
    assert _line(after, 'due_date') is None
    assert _line(after, 'cash_basis') == '#True'
    assert after == _filled(NO_DUE_DATE, guids)
