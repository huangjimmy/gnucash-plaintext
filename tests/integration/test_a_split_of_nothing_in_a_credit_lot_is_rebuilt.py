"""A split of nothing in an owner's credit lot is rebuilt into that lot.

GnuCash's View → Lots puts any loose split on the receivable into a lot,
0.00 CAD included. The export then writes the credit's `lot_owner:` and
`lot_guid:` on that split too. Measured on 5.10: a fresh book built from that
export refused the transaction — "failed to attach the settlement split to
customer 'C001''s lot (GnuCash refused the lot membership)". The split had
joined; the join was judged by whether the lot's balance moved, and a split of
nothing never moves it.
"""

from click.testing import CliRunner

from cli.main import cli

ACCOUNTS = 'tests/fixtures/payment_roundtrip_accounts.txt'
OVERPAID = 'tests/fixtures/q015_oh_inv_export_emits.txt'
NOTHING = 'tests/fixtures/a_line_of_nothing_on_the_receivable.txt'
AR = 'Assets:Accounts Receivable'


def _run(*args):
    return CliRunner().invoke(cli, [str(arg) for arg in args])


def _imported(*args):
    result = _run('import', *args)
    assert result.exit_code == 0, result.output
    return result


def _the_split_of_nothing_put_in_the_credit_lot(book):
    """As View → Lots does it: the loose 0.00 split added to C001's 50.00 credit lot."""
    from infrastructure.gnucash.engine import load_gnc_engine
    from infrastructure.gnucash.utils import get_account_full_name, numeric_to_fraction, qof_pointer
    from repositories.gnucash_repository import GnuCashRepository
    from services.foreign_currency import iter_splits

    lib = load_gnc_engine()
    repo = GnuCashRepository(str(book))
    repo.open()
    try:
        receivable = [split for split in iter_splits(repo.book)
                      if get_account_full_name(split.GetAccount()) == AR]
        credit = next(split for split in receivable if split.GetLot() is not None
                      and numeric_to_fraction(split.GetAmount()) == -50)
        nothing = next(split for split in receivable
                       if numeric_to_fraction(split.GetAmount()) == 0)
        account = nothing.GetAccount()
        account.BeginEdit()
        lib.gnc_lot_add_split(qof_pointer(credit.GetLot()), qof_pointer(nothing))
        account.CommitEdit()
        repo.save()
    finally:
        repo.close()


def test_the_export_rebuilds_a_book_with_it_in_the_credit_lot(tmp_path):
    book = tmp_path / 'book.gnucash'
    _imported('--new', book, ACCOUNTS)
    _imported(book, OVERPAID, '--include-business-objects')
    _imported(book, NOTHING)
    _the_split_of_nothing_put_in_the_credit_lot(book)
    out = tmp_path / 'out.txt'
    assert _run('export', book, out, '--include-business-objects').exit_code == 0

    fresh = tmp_path / 'fresh.gnucash'
    rebuilt = _run('import', '--new', fresh, out, '--include-business-objects')

    assert rebuilt.exit_code == 0, rebuilt.output
    again = tmp_path / 'again.txt'
    assert _run('export', fresh, again, '--include-business-objects').exit_code == 0
    lot_guids = [line.strip() for line in again.read_text().splitlines() if 'lot_guid:' in line]
    assert len(lot_guids) == 2 and lot_guids[0] == lot_guids[1], again.read_text()
    listed = _run('find-prepayments', fresh)
    assert 'customer C001 (Acme)  CAD 50.00' in listed.output, listed.output
