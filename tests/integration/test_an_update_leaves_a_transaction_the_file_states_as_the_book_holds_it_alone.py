"""`--strategy update` leaves a transaction the file states as the book holds it alone, and says it is up to date.

A book is corrected by exporting it, changing a few transactions and
importing the file with `--strategy update`. Every other block in that file
states its transaction as the book already holds it: no new changes. Those
transactions are up to date, so they are not edited, not committed and not
counted as updated, and a file with no new changes saves nothing.

Up to date is decided against the book's own export: a block reading line
for line as the export writes that transaction. A block saying the same
thing written another way is edited, as every block was before.

Measured on 5,000 transactions, where editing every block cost a commit each
(`tests/research/how_long_an_edit_read_as_new_takes_on_a_large_book_probe.py`).
"""

from click.testing import CliRunner

from tests.conftest import _run

FIXTURES = 'tests/fixtures/'
BASE = FIXTURES + 'a_usd_invoice_and_bill_for_statement_lines_on_a_holding_account.txt'
RATES = FIXTURES + 'usd_at_the_rates_the_statement_lines_records_were_posted_at.yaml'
DEPOSIT = FIXTURES + 'a_usd_deposit_and_its_fee_on_a_holding_account.txt'
CHARGE = FIXTURES + 'a_cad_bank_charge_on_the_holding_account.txt'


def _book(tmp_path):
    book = tmp_path / 'book.gnucash'
    for args in (('--new', str(book), BASE, '--include-business-objects'),
                 (str(book), DEPOSIT), (str(book), CHARGE)):
        done = _run(CliRunner(), 'import', *args, '--fx-rates', RATES)
        assert done.exit_code == 0 and 'Errors:       0' in done.output, done.output
    return book


def _exported(book, tmp_path):
    ledger = tmp_path / 'exported.txt'
    done = _run(CliRunner(), 'export', str(book), str(ledger))
    assert done.exit_code == 0, done.output
    return ledger.read_text()


def _updated(book, tmp_path, text):
    edit = tmp_path / 'edit.txt'
    edit.write_text(text)
    done = _run(CliRunner(), 'import', str(book), str(edit), '--strategy', 'update',
                '--fx-rates', RATES)
    assert done.exit_code == 0 and 'Errors:       0' in done.output, done.output
    return done.output


def test_the_books_own_export_is_up_to_date_and_saves_nothing(tmp_path):
    book = _book(tmp_path)
    text = _exported(book, tmp_path)
    written = book.stat().st_mtime_ns

    output = _updated(book, tmp_path, text)

    # Two invoices' postings, two bills', the deposit and the bank charge.
    assert 'Updated:      0' in output, output
    assert 'Up to date:   6 (no new changes, not edited)' in output, output
    assert 'Saving changes' not in output, output
    assert book.stat().st_mtime_ns == written
    assert _exported(book, tmp_path) == text


def test_one_transaction_changed_is_the_one_updated(tmp_path):
    book = _book(tmp_path)
    text = _exported(book, tmp_path)

    output = _updated(book, tmp_path,
                      text.replace('* "Bank charge"', '* "Bank charge for September"'))

    assert 'Updated:      1' in output, output
    assert 'Up to date:   5 (no new changes, not edited)' in output, output
    assert '* "Bank charge for September"' in _exported(book, tmp_path)


def test_a_transaction_the_export_cannot_write_is_edited(tmp_path):
    """1.819 CAD, finer than the currency, is corrected to 1.82 by a block stating its guid.

    The export refuses such a transaction, so there is no export to compare
    the block with, and the block is read as the edit it is. Built through
    the bindings, because the import will not write such a split.
    """
    import gnucash
    from gnucash import Account, GncNumeric, Split, Transaction

    from repositories.gnucash_repository import GnuCashRepository, SessionMode

    path = tmp_path / 'book.gnucash'
    repo = GnuCashRepository(str(path))
    repo.open(SessionMode.NEW)
    book = repo.book
    cad = book.get_table().lookup('CURRENCY', 'CAD')

    def child(parent, name, kind):
        account = Account(book)
        account.SetName(name)
        account.SetType(kind)
        account.SetCommodity(cad)
        account.SetCommoditySCU(1000)
        parent.append_child(account)
        return account

    bank = child(child(book.get_root_account(), 'Assets', gnucash.ACCT_TYPE_ASSET),
                 'Bank', gnucash.ACCT_TYPE_BANK)
    fuel = child(child(book.get_root_account(), 'Expenses', gnucash.ACCT_TYPE_EXPENSE),
                 'Fuel', gnucash.ACCT_TYPE_EXPENSE)
    transaction = Transaction(book)
    transaction.BeginEdit()
    transaction.SetCurrency(cad)
    transaction.SetDate(1, 2, 2026)
    transaction.SetDescription('One litre')
    for account, sign in ((fuel, 1), (bank, -1)):
        split = Split(book)
        split.SetParent(transaction)
        split.SetAccount(account)
        split.SetValue(GncNumeric(sign * 1819, 1000))
        split.SetAmount(GncNumeric(sign * 1819, 1000))
    transaction.CommitEdit()
    guid = transaction.GetGUID().to_string()
    repo.save()
    repo.close()

    output = _updated(path, tmp_path,
                      f'2026-02-01 * "One litre"\n'
                      f'\tguid: "{guid}"\n'
                      f'\tcurrency.mnemonic: "CAD"\n'
                      f'\tExpenses:Fuel 1.82 CAD\n'
                      f'\tAssets:Bank -1.82 CAD\n')

    assert 'Updated:      1' in output, output
    # Written to the account's thousandths, 1.820.
    exported = _exported(path, tmp_path)
    assert 'Expenses:Fuel 1.820 CAD' in exported, exported


def test_the_same_figures_written_another_way_are_edited(tmp_path):
    """5.00 written as 5.0 states the same amount, and is edited, as every block was before.

    Up to date is the export's own text: a block written any other way is
    read as an edit, which changes nothing here and is reported as an update.
    """
    book = _book(tmp_path)
    text = _exported(book, tmp_path)

    output = _updated(book, tmp_path,
                      text.replace('Expenses:Bank charges 5.00 CAD', 'Expenses:Bank charges 5.0 CAD'))

    assert 'Updated:      1' in output, output
    assert _exported(book, tmp_path) == text
