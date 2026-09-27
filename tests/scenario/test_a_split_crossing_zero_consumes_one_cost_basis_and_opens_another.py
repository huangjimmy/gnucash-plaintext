"""A split crossing zero consumes the cost basis on one side and opens one on the other.

The case is the author's, recorded in Q-054's rules: an asset account at
−500 holds a liability cost basis of 500, and 1,000 arriving into it takes
it to 500, consuming the liability cost basis and opening an asset cost basis
of 500. The rates, 1.30 and 1.20, and the card's case, its mirror, are this
test's.

Assets:USD Bank owes 500.00 USD at 1.30, and Liabilities:USD Card holds
500.00 USD in credit at 1.30
(`a_usd_bank_owing_500_at_1_30_and_a_usd_card_in_credit_500_at_1_30.txt`).
Each is then taken across zero by 1,000.00 USD at 1.20: 1,000.00 USD bought
for 1,200.00 CAD and deposited into the bank, and 1,000.00 USD of travel,
1,200.00 CAD, charged to the card.

By definition, each crossing split does two things:

- the 500.00 up to zero consumes the cost basis the account held. The bank's
  debt cost 650.00 CAD and is repaid with 600.00, a gain of 50.00; the card's
  credit cost 650.00 and pays for 600.00 of travel, a loss of 50.00;
- the 500.00 past zero opens a cost basis of its own at the rate the dollars
  were acquired at, 1.20: 500.00 USD held in the bank, and 500.00 USD owed on
  the card.

Stated with the guid of the cost basis consumed
(`..._each_crossing_zero_at_1_20_stating_the_cost_basis.txt`), the gain and
the loss are realized. Pending it (`..._pending_the_cost_basis.txt`), the
consumed 500.00 is pending at the 600.00 CAD it was acquired at, the new cost
basis opens all the same, and an edit stating the guid later makes the book
the one stated with the guid from the start.
"""

import re

from click.testing import CliRunner

from tests.conftest import _run

F = 'tests/fixtures/'
BEFORE = F + 'a_usd_bank_owing_500_at_1_30_and_a_usd_card_in_credit_500_at_1_30.txt'
CROSSING = F + 'a_usd_bank_owing_500_at_1_30_and_a_usd_card_in_credit_500_at_1_30_each_crossing_zero_at_1_20'
STATING = CROSSING + '_stating_the_cost_basis.txt'
PENDING = CROSSING + '_pending_the_cost_basis.txt'

BANK_OWED = '0f0f0000000000000000000000000001'
BANK_HELD = '0f0f0000000000000000000000000002'
CARD_HELD = '0f0f0000000000000000000000000003'
CARD_OWED = '0f0f0000000000000000000000000004'


def _imported(book, ledger, *options):
    done = _run(CliRunner(), 'import', *options, str(book), ledger)
    assert done.exit_code == 0 and 'Errors:       0' in done.output, done.output
    return done


def _book(tmp_path, crossing, name='book'):
    book = tmp_path / f'{name}.gnucash'
    _imported(book, BEFORE, '--new')
    _imported(book, crossing)
    return book


def _listing(book):
    costs = _run(CliRunner(), 'fx-balances', str(book), '--verify-costs')
    assert costs.exit_code == 0 and 'warning' not in costs.output, costs.output
    integrity = _run(CliRunner(), '--verify-integrity', str(book))
    assert integrity.exit_code == 0, integrity.output
    return costs.output


def _row(listing, guid):
    """A cost basis's cost, what it brought in, and its balance, as `fx-balances` lists them."""
    found = re.search(rf'{guid}\s+\S.*?\s+(\S+) CAD/USD\s+(\S+) USD\s+(\S+) USD', listing)
    assert found, f'no cost basis {guid} in:\n{listing}'
    return found.groups()


def _export(book, tmp_path, name):
    out = tmp_path / f'{name}.txt'
    done = _run(CliRunner(), 'export', str(book), str(out))
    assert done.exit_code == 0, done.output
    return out


class TestStatingTheCostBasis:
    def test_the_bank_s_debt_is_consumed_and_500_held_opens_at_1_20(self, tmp_path):
        listing = _listing(_book(tmp_path, STATING))

        assert _row(listing, BANK_OWED) == ('1.3', '500.00', '0.00'), listing
        assert _row(listing, BANK_HELD) == ('1.2', '500.00', '500.00'), listing
        assert 'Assets:USD Bank              500.00 USD' in listing, listing

    def test_the_card_s_credit_is_consumed_and_500_owed_opens_at_1_20(self, tmp_path):
        listing = _listing(_book(tmp_path, STATING))

        assert _row(listing, CARD_HELD) == ('1.3', '500.00', '0.00'), listing
        assert _row(listing, CARD_OWED) == ('1.2', '500.00', '500.00'), listing
        assert 'Liabilities:USD Card        -500.00 USD' in listing, listing

    def test_the_bank_realizes_a_gain_of_50_and_the_card_a_loss_of_50(self, tmp_path):
        exported = _export(_book(tmp_path, STATING), tmp_path, 'out').read_text()

        deposit, charge = (exported.split(f'"{title}"')[1].split('\n\n')[0] for title in (
            '1,000.00 USD bought at 1.20 and deposited into the USD bank',
            '1,000.00 USD of travel charged to the card at 1.20'))
        assert re.search(r'Income:FX Gain -50\.00 CAD', deposit), deposit
        assert re.search(r'Income:FX Gain 50\.00 CAD', charge), charge

    def test_its_export_rebuilds_the_same_cost_bases(self, tmp_path):
        book = _book(tmp_path, STATING)
        rebuilt = tmp_path / 'rebuilt.gnucash'

        _imported(rebuilt, str(_export(book, tmp_path, 'out')), '--new')

        assert _listing(rebuilt) == _listing(book)


class TestPendingTheCostBasis:
    def test_the_consumed_parts_are_pending_and_the_cost_bases_they_consume_are_whole(
            self, tmp_path):
        listing = _listing(_book(tmp_path, PENDING))

        assert '2 disposal(s) pending their cost basis: 1,000.00 USD.' in listing, listing
        assert re.search(r'Assets:USD Bank\s+500\.00 USD\s+1,000\.00 USD bought', listing), listing
        assert re.search(r'Liabilities:USD Card\s+500\.00 USD\s+1,000\.00 USD of travel',
                         listing), listing
        assert _row(listing, BANK_OWED) == ('1.3', '500.00', '500.00'), listing
        assert _row(listing, CARD_HELD) == ('1.3', '500.00', '500.00'), listing

    def test_500_held_and_500_owed_open_at_1_20(self, tmp_path):
        listing = _listing(_book(tmp_path, PENDING))

        assert _row(listing, BANK_HELD) == ('1.2', '500.00', '500.00'), listing
        assert _row(listing, CARD_OWED) == ('1.2', '500.00', '500.00'), listing
        assert 'Assets:USD Bank              500.00 USD' in listing, listing
        assert 'Liabilities:USD Card        -500.00 USD' in listing, listing

    def test_its_export_rebuilds_the_same_cost_bases(self, tmp_path):
        book = _book(tmp_path, PENDING)
        rebuilt = tmp_path / 'rebuilt.gnucash'

        _imported(rebuilt, str(_export(book, tmp_path, 'out')), '--new')

        assert _listing(rebuilt) == _listing(book)

    def test_an_edit_stating_the_guid_makes_it_the_book_stated_with_it(self, tmp_path):
        pending = _book(tmp_path, PENDING)
        stated = _book(tmp_path, STATING, name='stated')

        _imported(pending, STATING, '--strategy', 'update')

        assert _listing(pending) == _listing(stated)
