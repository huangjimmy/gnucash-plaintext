"""An older book's own keys are exported as the type each holds.

Before Q-055 gnucash-plaintext stored its `bool` keys — `took_the_residual`,
`applied_from_credit`, `business_generated` and Q-018's `cash_basis` — as the
text `"true"`, and Q-018's `due_date` as the text of a date, because a bare
`2026-05-30` was read as text. Q-055 gives each key one type, and
RELEASE_NOTES says a book written before exports `"true"` as `#True`, on a
transaction, a split, an invoice and a bill alike, and its `due_date` as a
date without quotes.

Each test builds the book from a fixture of the scenario or issue that states
the key, writes the slot the way an older version stored it, exports the
book, and imports that export back with nothing changed.
"""
from pathlib import Path

from click.testing import CliRunner
from gnucash import Query

from infrastructure.gnucash.kvp import get_custom_metadata, set_custom_metadata
from infrastructure.gnucash.utils import wrap_invoice_or_bill
from repositories.gnucash_repository import GnuCashRepository
from tests.conftest import _run

FIXTURES = Path('tests/fixtures')
MARKS = ('took_the_residual', 'applied_from_credit', 'business_generated')


def _imported(book, *fixtures):
    for number, fixture in enumerate(fixtures):
        args = ['import', str(book), str(FIXTURES / fixture), '--include-business-objects']
        if number == 0:
            args.insert(1, '--new')
        done = _run(CliRunner(), *args)
        assert done.exit_code == 0, done.output
    return book


def _as_text(obj, keys):
    """Write each of `keys` the object holds as `True` as the text `"true"`, as an older version stored it."""
    slot = dict(get_custom_metadata(obj) or {})
    older = {k: 'true' for k in keys if slot.get(k) is True}
    if older:
        set_custom_metadata(obj, {**slot, **older})
        assert all(get_custom_metadata(obj)[k] == 'true' for k in older)
    return sorted(older)


def _marks_stored_as_an_older_version_stored_them(book):
    """Every transaction's and split's mark the book holds as `True`, written as `"true"`; the keys written."""
    written = []
    repo = GnuCashRepository(str(book))
    repo.open()
    try:
        seen = set()
        for account in repo.book.get_root_account().get_descendants():
            for split in account.GetSplitList():
                txn = split.GetParent()
                txn.BeginEdit()
                if txn.GetGUID().to_string() not in seen:
                    seen.add(txn.GetGUID().to_string())
                    written += _as_text(txn, MARKS)
                written += _as_text(split, MARKS)
                txn.CommitEdit()
        repo.save()
    finally:
        repo.close()
    return sorted(written)


def _record_stored_as_an_older_version_stored_it(book, record_id):
    """Write the record's `cash_basis` and `due_date` as text, as they were stored before Q-055."""
    repo = GnuCashRepository(str(book))
    repo.open()
    try:
        query = Query()
        query.search_for('gncInvoice')
        query.set_book(repo.book)
        record = next(r for r in (wrap_invoice_or_bill(raw) for raw in query.run())
                      if r.GetID() == record_id)
        query.destroy()
        slot = dict(get_custom_metadata(record))
        slot['cash_basis'] = 'true'
        slot['due_date'] = str(slot['due_date'])
        record.BeginEdit()
        set_custom_metadata(record, slot)
        record.CommitEdit()
        assert get_custom_metadata(record)['cash_basis'] == 'true'
        assert type(get_custom_metadata(record)['due_date']) is str
        repo.save()
    finally:
        repo.close()


def _exported(book, tmp_path, name):
    out = tmp_path / name
    done = _run(CliRunner(), 'export', str(book), str(out), '--include-business-objects')
    assert done.exit_code == 0, done.output
    return out


def _lines(out, *keys):
    return [line.strip() for line in out.read_text().splitlines()
            if line.strip().split(':')[0] in keys]


def _imports_back_unchanged(book, tmp_path, first):
    again = _run(CliRunner(), 'import', str(book), str(first), '--include-business-objects')
    assert again.exit_code == 0, again.output
    assert _exported(book, tmp_path, 'second.txt').read_text() == first.read_text()


def test_a_gain_split_s_text_true_is_exported_as_true(tmp_path):
    """An older book's gain split exports `took_the_residual: #True`.

    The sale of a thousand US dollars, from the scenario of the tool's own
    keys, its gain split's `took_the_residual` held as the text `"true"`. The
    export writes it as `#True`, and importing that export changes nothing.
    """
    book = _imported(tmp_path / 'book.gnucash', 'a_gain_split_s_mark_1_a_thousand_usd_bought_and_sold.txt')
    assert _marks_stored_as_an_older_version_stored_them(book) == ['took_the_residual']
    first = _exported(book, tmp_path, 'first.txt')
    assert _lines(first, *MARKS) == ['took_the_residual: #True']
    _imports_back_unchanged(book, tmp_path, first)


def test_a_posting_s_and_a_spent_credit_s_text_true_are_exported_as_true(tmp_path):
    """An older book's posting and spent credit export `business_generated: #True` and `applied_from_credit: #True`.

    INV-001 overpaid and INV-002 spending the credit, from the scenario of an
    invoice's marks. The posting transactions' `business_generated` and the
    spent split's `applied_from_credit` are held as the text `"true"`. The
    export writes each as `#True`, and importing that export changes nothing.
    """
    book = _imported(tmp_path / 'book.gnucash', 'an_invoice_s_marks_1_a_credit_spent_on_the_next_invoice.txt')
    written = _marks_stored_as_an_older_version_stored_them(book)
    assert set(written) == {'applied_from_credit', 'business_generated'}
    first = _exported(book, tmp_path, 'first.txt')
    assert sorted(_lines(first, *MARKS)) == sorted(f'{key}: #True' for key in written)
    _imports_back_unchanged(book, tmp_path, first)


def test_an_invoice_s_text_true_and_text_date_are_exported_as_true_and_a_date(tmp_path):
    """An older book's invoice exports `cash_basis: #True` and `due_date: 2026-05-30`.

    Q-018's unposted invoice, its slot holding `cash_basis` as the text
    `"true"` and `due_date` as the text `"2026-05-30"`. The export writes the
    key gnucash-plaintext keeps as a `bool` as `#True` and the date key without
    quotes, and importing that export changes nothing.
    """
    book = _imported(tmp_path / 'book.gnucash', 'q018_accounts.txt', 'q018_unposted_cash_with_due.txt')
    _record_stored_as_an_older_version_stored_it(book, 'INV-Q18-UNPOSTED-WITH-DUE')
    first = _exported(book, tmp_path, 'first.txt')
    assert _lines(first, 'cash_basis', 'due_date') == ['cash_basis: #True', 'due_date: 2026-05-30']
    _imports_back_unchanged(book, tmp_path, first)


def test_a_bill_s_text_true_and_text_date_are_exported_as_true_and_a_date(tmp_path):
    """An older book's bill exports `cash_basis: #True` and `due_date: 2026-06-11`.

    Q-019's unposted bill, its slot holding `cash_basis` as the text `"true"`
    and `due_date` as the text `"2026-06-11"`. The export writes them as
    `#True` and a date without quotes, and importing that export changes
    nothing.
    """
    book = _imported(tmp_path / 'book.gnucash', 'q019_accounts.txt', 'q019_unposted_cash_bill.txt')
    _record_stored_as_an_older_version_stored_it(book, 'BILL-Q19-CASH-TAX-400')
    first = _exported(book, tmp_path, 'first.txt')
    assert _lines(first, 'cash_basis', 'due_date') == ['cash_basis: #True', 'due_date: 2026-06-11']
    _imports_back_unchanged(book, tmp_path, first)
