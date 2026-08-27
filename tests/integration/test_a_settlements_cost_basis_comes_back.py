"""Taking a converting settlement off a record gives its cost basis back.

Settling a foreign-currency invoice into a bank kept in another currency
converts money, so it draws the converted units out of the receivable's cost
basis — that USD is gone, spent at the rate the bank gave. `unapply-payment`
and `unlink` put the settlement back to being owed, and the basis has to come
back with it: the currency was never sold, it went back to being a receivable.

What it cost while the balance stayed spent, on the book this uses — a 100.00
USD invoice booked at 1.40 and settled into a CAD bank at 1.37:

- the invoice is Outstanding for 100.00 USD again, and `fx-balances` offers
  0.00 USD against it;
- re-applying the money to the right invoice — the whole reason to take a
  payment off — is refused: "that USD has already been sold against it". The
  invoice cannot be settled by any converting payment again.

Both commands are run against it, because they take a payment off through the
same code and either can be pointed at a payment that converted.
"""

from fractions import Fraction
from pathlib import Path
from typing import NamedTuple

import pytest
from click.testing import CliRunner

from cli.main import cli
from infrastructure.gnucash.kvp import get_custom_metadata, set_custom_metadata
from infrastructure.gnucash.utils import (
    get_account_full_name,
    numeric_to_fraction,
)
from repositories.gnucash_repository import GnuCashRepository, SessionMode
from services.foreign_currency import cost_basis_guid_of, iter_splits

FIXTURES = Path('tests/fixtures')
RATES = str(FIXTURES / 'fx_rates_usd_dated.yaml')
TO = 'Assets:Bank:USD'


class Record(NamedTuple):
    """A record, its ledger, and the flag that reaches it.

    Both sides, because a payable's signs run the other way and this path both
    draws a cost basis down and gives it back — CLAUDE.md finding 7, and the
    place Q-035 records the suite having been caught customer-side already.
    """
    ledger: str
    ident: str
    flag: list


RECORDS = [
    Record(str(FIXTURES / 'fx_invoice_usd_paid_from_cad_bank.txt'),
           'INV-USD-PAY', []),
    Record(str(FIXTURES / 'fx_bill_usd_paid_from_cad_bank.txt'),
           'BILL-USD-PAY', ['--bill']),
]
OWED_BACK_ACCOUNT = str(FIXTURES / 'an_account_to_owe_a_customer_back_in.txt')
OWED_BACK = 'Liabilities:Due to customer'


@pytest.fixture(params=['unapply-payment', 'unlink'])
def command(request):
    return request.param


@pytest.fixture(params=RECORDS, ids=[r.ident for r in RECORDS])
def record(request):
    return request.param


@pytest.fixture
def book(tmp_path, record):
    """100.00 USD booked at 1.40, settled into a CAD bank at 1.37.

    An invoice on one pass and a bill on the other, the same figures either
    way — the signs are what differ, and they are what a give-back gets wrong
    silently.
    """
    path = tmp_path / 'book.gnucash'
    result = CliRunner().invoke(cli, [
        'import', '--new', str(path), record.ledger,
        '--include-business-objects', '--fx-rates', RATES])
    assert result.exit_code == 0, result.output
    return path


def _take_it_off(command, book, record, to=TO):
    return CliRunner().invoke(
        cli, [command, str(book), record.ident, *record.flag, '--to', to])


def _balances(book):
    result = CliRunner().invoke(cli, ['fx-balances', str(book)])
    assert result.exit_code == 0, result.output
    return result.output


def _exported(book, out_dir):
    """The book as a ledger, read back as text.

    Through `export`, because what a key costs is what the export writes: a
    slot read straight out of the book would say nothing about the line a
    reader ends up with.
    """
    path = out_dir / 'exported.txt'
    result = CliRunner().invoke(cli, ['export', str(book), str(path)])
    assert result.exit_code == 0, result.output
    return path.read_text()


def _splits_on(book, account_name):
    """Every split amount on this account, exactly."""
    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        return [numeric_to_fraction(split.GetAmount())
                for split in iter_splits(repo.book)
                if get_account_full_name(split.GetAccount()) == account_name]
    finally:
        repo.close()


def _put_a_key_on_the_settlement(book, key, value):
    """Give the settlement split a custom key of its own.

    Arranged through the same KVP writer the import path uses, rather than a
    ledger file: the split's guid is GnuCash's own, made when the payment was
    applied, so no fixture can name it.
    """
    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.NORMAL)
    try:
        for split in iter_splits(repo.book):
            if not cost_basis_guid_of(split):
                continue
            metadata = dict(get_custom_metadata(split))
            metadata[key] = value
            parent = split.GetParent()
            parent.BeginEdit()
            set_custom_metadata(split, metadata)
            parent.CommitEdit()
            repo.save()
            return
        raise AssertionError('no settlement split carries a cost basis key')
    finally:
        repo.close()


def test_the_settlement_spends_the_basis_while_it_is_applied(book):
    """The state this is the undo of: settled, so the USD is gone."""
    assert '0.00' in _balances(book), _balances(book)


def test_the_basis_is_offered_again_once_the_payment_comes_off(command, book, record):
    """100.00 USD owed again is 100.00 USD of basis to settle it with."""
    result = _take_it_off(command, book, record)

    assert result.exit_code == 0, result.output
    assert '100.00' in _balances(book), _balances(book)


def test_the_record_can_be_settled_again_afterwards(command, book, record):
    """The point of taking a payment off is applying it somewhere.

    Left spent, the basis refused this with "that USD has already been sold
    against it" — about money the book had just gone back to being owed.
    """
    off = _take_it_off(command, book, record)
    assert off.exit_code == 0, off.output

    again = CliRunner().invoke(cli, [
        'import', str(book), record.ledger,
        '--include-business-objects', '--fx-rates', RATES])

    assert again.exit_code == 0, again.output
    assert 'already been sold' not in again.output, again.output


def test_the_key_is_dropped_rather_than_emptied(command, book, record):
    """An emptied key is a line in every export from then on.

    The export writes every custom key it finds, and the import drops a key
    whose value is empty — so a book carrying `cost_basis_split_guid: ""`
    exports a line nobody typed, and a book rebuilt from that export does not
    hold it. The ledger and its own export would build two different books.
    """
    off = _take_it_off(command, book, record)
    assert off.exit_code == 0, off.output

    assert 'cost_basis_split_guid' not in _exported(book, book.parent)


def test_the_split_s_other_keys_survive(command, book, record):
    """The slot is rewritten, so it has to be read first.

    `set_custom_metadata` replaces what is there, so writing the one key back
    took every other key on that split with it and said nothing. A
    `department:` on a settlement split is an ordinary thing to carry — the
    update path merges custom keys onto a split from its block.
    """
    _put_a_key_on_the_settlement(book, 'department', 'east')

    off = _take_it_off(command, book, record)
    assert off.exit_code == 0, off.output

    assert 'department' in _exported(book, book.parent)


def _income_statement(book):
    result = CliRunner().invoke(cli, [
        'income-statement', str(book), '--start', '2026-01-01',
        '--end', '2026-12-31', '--fx-rates', RATES])
    assert result.exit_code == 0, result.output
    return result.output


def test_the_realized_difference_stays_where_the_file_put_it(command, book, record):
    """And the book then says two things at once. Measured, not assumed.

    The −3.00 CAD is not this tool's split. Settling 100.00 USD booked at 1.40
    into a CAD bank at 1.37 realizes a difference, and the payment block has
    to say where it belongs — `_book_payment_fx_difference` refuses the block
    outright otherwise, naming `Income:FX Gain $residual$ CAD`. So it is the
    file's own line, in the transaction the file wrote, and neither command
    rewrites that: the whole promise here is that the entry survives whole.

    What that leaves, measured on this book: the basis reads 100.00 USD owed
    and undisposed while the income statement carries −3.00 CAD of realized
    difference on disposing of it. Both are true of what happened — the money
    did convert, and it is no longer settling this invoice — and no rule in
    this tool can decide whose line to rewrite.

    So it is stated rather than silently left: README and Q-039 both say that
    applying the money to another record with another `$residual$` line
    records the difference twice, and that the first line is the reader's to
    remove.
    """
    before = _income_statement(book)
    assert '3.00' in before, before

    off = _take_it_off(command, book, record)
    assert off.exit_code == 0, off.output

    assert '3.00' in _income_statement(book), _income_statement(book)
    assert '100.00' in _balances(book), _balances(book)


def test_a_cad_account_takes_the_cost_and_not_the_cash(command, book, record):
    """−140.00, though the bank received 137.00. The only figure that balances.

    Where a settlement realized a difference the entry is quoted in the book's
    currency and the settlement split's value is written at the *basis cost* —
    100.00 USD at the posting split's `share_price:` of 1.40 — while the bank
    carries the
    137.00 that actually arrived and the file's `$residual$` line carries the
    3.00 between them.

    So a CAD `--to` takes the value, −140.00, and the entry goes on balancing
    because the `Income:FX Gain` split is not deleted. Writing the cash instead
    would leave the transaction 3.00 out, and the only way to write it would
    be to rewrite the reader's own line.

    Worth pinning because it is the figure a reader is handed: `Assets:Due
    From Director` on a converting payment is 3.00 away from the cash, and
    nothing on the page would say why. README says it now.
    """
    opened = CliRunner().invoke(cli, ['import', str(book), OWED_BACK_ACCOUNT])
    assert opened.exit_code == 0, opened.output

    off = _take_it_off(command, book, record, to=OWED_BACK)

    assert off.exit_code == 0, off.output
    rows = _splits_on(book, OWED_BACK)
    assert len(rows) == 1, rows
    # A payable's settlement is positive on it where a receivable's is
    # negative, so the sign follows the record — the figure is the same 140.
    assert abs(rows[0]) == Fraction(140), rows


def test_a_basis_this_command_creates_is_opened_by_it(command, book, record):
    """`--to` a USD account can make the restated split a basis of its own.

    `establishes_cost_basis` answers False for a settlement *because* it
    carries `cost_basis_split_guid`. Dropping that key on the way out clears
    the last gate, so a split given an account kept in its own foreign
    currency becomes a cost basis — and one this command created, which it
    therefore has to open.

    Measured on the bill before it did: `fx-balances` grew a 100.00 USD basis
    on `Assets:Bank:USD` reading `none recorded`, left out of the total,
    under the sentence "this tool never wrote one for them". It had. A later
    sale naming that basis was refused for the same untrue reason, offering a
    hand-written `cost_basis_balance:` as the remedy.

    The invoice side never reached it — a credit on a debit-type account
    raises no foreign balance — which is why both records are run here.
    """
    off = _take_it_off(command, book, record)
    assert off.exit_code == 0, off.output

    assert 'none recorded' not in _balances(book), _balances(book)
    assert 'no balance recorded' not in _balances(book), _balances(book)


def test_the_balance_comes_back_to_what_the_basis_brought_in(command, book, record):
    """The basis is whole again and no more, which `--verify-costs` is for.

    Two things hold it there and only one is this code's: the units given back
    are the ones the settlement drew, and `raise_cost_basis_balance` caps at
    what the basis brought in whatever it is handed.

    Asked of `--verify-costs` rather than of the printed total. On the bill
    the total is legitimately 200.00 USD once the payment comes off — the
    payable owes 100.00 again, and the USD bank now holds the 100.00 the
    settlement was restated onto — so a total is no test of one basis being
    over-filled. What is, is the check that no balance stands above what its
    own basis brought in.
    """
    off = _take_it_off(command, book, record)
    assert off.exit_code == 0, off.output

    assert '100.00' in _balances(book), _balances(book)
    checked = CliRunner().invoke(
        cli, ['fx-balances', str(book), '--verify-costs'])
    assert checked.exit_code == 0, checked.output
    assert 'every cost agrees' in checked.output, checked.output


def test_a_second_run_finds_no_payment_to_take_off(command, book, record):
    """And so cannot give anything back a second time.

    The first run took the split out of the lot, which is what a payment is
    read off. This is why the dropped key is about what the export writes and
    not about a double give-back.
    """
    first = _take_it_off(command, book, record)
    assert first.exit_code == 0, first.output

    again = _take_it_off(command, book, record)

    assert again.exit_code != 0, again.output
    assert 'no payments' in again.output, again.output
