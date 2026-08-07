"""A transaction's type is restored, and only a type GnuCash knows.

`txn_type: P` marks a payment. Restoring it matters — a re-imported payment
that is not a payment to the engine is invisible to `find-orphan-payments` —
but restoring it means writing into engine state, where a character GnuCash
does not know would export straight back out and become permanent.
"""

import re

from click.testing import CliRunner

from cli.main import cli


def test_a_type_gnucash_does_not_know_is_refused(tmp_path):
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    result = runner.invoke(cli, ['import', '--new', str(book),
                                 'tests/fixtures/txn_type_unknown.txt'])

    assert 'txn_type' in result.output, result.output
    assert "'Z'" in result.output, result.output
    assert 'Errors:       1' in result.output, result.output

    # And it did not reach the book: nothing exports it back out. The book
    # exists — the accounts imported fine — so this is asserted, not skipped.
    exported = tmp_path / 'out.txt'
    assert book.exists(), result.output
    assert runner.invoke(cli, ['export', str(book), str(exported)]).exit_code == 0
    assert 'txn_type: Z' not in exported.read_text(), exported.read_text()


def test_a_stated_payment_type_survives_a_round_trip(tmp_path):
    """`txn_type: P` on a plain transaction comes back out again.

    Not through a `payment:` block — those are typed by the engine when the
    payment is applied — but stated on an ordinary transaction, which is what
    an exported book looks like on re-import.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    result = runner.invoke(cli, ['import', '--new', str(book),
                                 'tests/fixtures/txn_type_payment_plain.txt'])
    assert result.exit_code == 0, result.output

    first = tmp_path / 'one.txt'
    assert runner.invoke(cli, ['export', str(book), str(first)]).exit_code == 0
    assert 'txn_type: P' in first.read_text(), first.read_text()

    second_book = tmp_path / 'second.gnucash'
    assert runner.invoke(cli, ['import', '--new', str(second_book),
                               str(first)]).exit_code == 0
    second = tmp_path / 'two.txt'
    assert runner.invoke(cli, ['export', str(second_book), str(second)]).exit_code == 0

    assert 'txn_type: P' in second.read_text(), second.read_text()
    assert '\x00' not in second.read_text(), second.read_text()


def test_an_update_restores_a_type_and_refuses_one_gnucash_does_not_know(tmp_path):
    """The edit path writes into engine state too, so it checks the same way.

    `--strategy update` re-imports an edited export, and `txn_type:` on that
    file reaches the same engine setter a fresh import does. Both halves are
    the update path's own: a type GnuCash knows is applied, and one it does
    not is refused — and refused before the edit begins, so there is nothing
    to roll back: the character is judged on its own, which takes only the
    character. `test_a_refused_type_on_an_update_leaves_no_lot_behind` is the
    same rule seen from the book's side.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    result = runner.invoke(cli, ['import', '--new', str(book),
                                 'tests/fixtures/txn_type_payment_plain.txt'])
    assert result.exit_code == 0, result.output

    exported = tmp_path / 'out.txt'
    assert runner.invoke(cli, ['export', str(book), str(exported)]).exit_code == 0
    text = exported.read_text()
    assert 'txn_type: P' in text, text

    # An ordinary edit alongside the type: the description changes, the type
    # is re-applied, and both land.
    edited = tmp_path / 'edited.txt'
    edited.write_text(text.replace('"Stated as a payment"',
                                   '"Stated as a payment (wire)"'))
    result = runner.invoke(cli, ['import', str(book), str(edited),
                                 '--strategy', 'update'])
    assert result.exit_code == 0, result.output

    after = tmp_path / 'after.txt'
    assert runner.invoke(cli, ['export', str(book), str(after)]).exit_code == 0
    assert 'Stated as a payment (wire)' in after.read_text(), after.read_text()
    assert 'txn_type: P' in after.read_text(), after.read_text()

    # And a type it does not know, on the same path.
    bad = tmp_path / 'bad.txt'
    bad.write_text(after.read_text().replace('txn_type: P', 'txn_type: Z'))
    result = runner.invoke(cli, ['import', str(book), str(bad),
                                 '--strategy', 'update'])
    assert 'txn_type' in result.output, result.output
    assert "'Z'" in result.output, result.output

    # Rolled back whole: the description the refused file also carried is not
    # in the book, and the type it would have overwritten is still P.
    final = tmp_path / 'final.txt'
    assert runner.invoke(cli, ['export', str(book), str(final)]).exit_code == 0
    assert 'txn_type: Z' not in final.read_text(), final.read_text()
    assert 'txn_type: P' in final.read_text(), final.read_text()


def test_a_nul_type_from_an_older_export_does_not_come_back_out(tmp_path):
    """The books already written have to be cleanable.

    Every version before this one emitted the unset C field as a literal NUL,
    so files exist that read `txn_type: \\x00`. Importing one stores that NUL
    as a KVP — the engine setter refuses it, but the slot is written like any
    other custom value — and the export's KVP fallback then wrote it straight
    back out. The C-field branch above it was guarded and this one was not, so
    the byte survived a round trip that was supposed to remove it.

    The file is built here rather than committed as a fixture: a NUL byte in a
    `.txt` under `tests/fixtures/` is a hazard for every tool that reads the
    repo, and what matters is the byte, not the surrounding text.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    assert runner.invoke(cli, ['import', '--new', str(book),
                               'tests/fixtures/txn_type_payment_plain.txt']).exit_code == 0
    exported = tmp_path / 'out.txt'
    assert runner.invoke(cli, ['export', str(book), str(exported)]).exit_code == 0

    older = tmp_path / 'older.txt'
    older.write_text(exported.read_text().replace('txn_type: P', 'txn_type: \x00'))

    second = tmp_path / 'second.gnucash'
    assert runner.invoke(cli, ['import', '--new', str(second), str(older)]).exit_code == 0
    again = tmp_path / 'again.txt'
    assert runner.invoke(cli, ['export', str(second), str(again)]).exit_code == 0

    text = again.read_text()
    assert '\x00' not in text, repr(text)
    assert 'txn_type' not in text, text


def test_a_refused_type_on_an_update_leaves_no_lot_behind(tmp_path):
    """The check has to come before the edit, not at the end of it.

    An update that writes a prepayment attaches its split to the owner's lot,
    and a lot is engine state a transaction rollback does not clearly undo. An
    unknown `txn_type:` in the same file is a pure string mistake, knowable
    before a single split is touched — so it is refused there, and the lot is
    never created.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    result = runner.invoke(
        cli, ['import', '--new', str(book),
              'tests/fixtures/cad_transaction_before_becoming_a_prepayment.txt',
              '--include-business-objects'])
    assert result.exit_code == 0, result.output

    exported = tmp_path / 'out.txt'
    assert runner.invoke(cli, ['export', str(book), str(exported)]).exit_code == 0
    guid = re.search(r'corrected into a customer prepayment"\n\tguid: "([0-9a-f]{32})"',
                     exported.read_text()).group(1)

    edited = tmp_path / 'edited.txt'
    edited.write_text(
        '2026-02-01 * "Customer prepaid 100 USD, arriving as CAD"\n'
        f'\tguid: "{guid}"\n'
        '\ttxn_type: Z\n'
        '\tcurrency.mnemonic: "CAD"\n'
        '\tAssets:Bank 137.00 CAD\n'
        '\t\taccount.commodity.mnemonic: "CAD"\n'
        '\tAssets:Accounts Receivable USD -100.00 USD\n'
        '\t\taccount.commodity.mnemonic: "USD"\n'
        '\t\tshare_price: "1.37"\n'
        '\t\tvalue: "-137.00"\n'
        '\t\tlot_owner: "customer:C-US"\n')

    result = runner.invoke(cli, ['import', str(book), str(edited),
                                 '--strategy', 'update'])
    assert "'Z'" in result.output, result.output

    after = tmp_path / 'after.txt'
    assert runner.invoke(cli, ['export', str(book), str(after)]).exit_code == 0
    text = after.read_text()
    assert 'lot_owner' not in text, text
    assert 'open_prepayment' not in text, text
    assert 'No foreign-currency cost bases found' in runner.invoke(
        cli, ['fx-balances', str(book)]).output
