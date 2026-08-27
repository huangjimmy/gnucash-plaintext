"""Q-035: foreign-currency cost bases, their basis balances, and selling.

Every split that brings foreign currency in establishes a cost basis. Selling
picks one or more of them by guid; each basis's basis balance falls by what
the sale takes from it, and picking more than a basis has is refused.

The basis balance of a cost basis is not an account balance — a paid
invoice's basis keeps its balance after the money has moved to the bank, and
one bank account holds currency from several bases at different costs.
"""

import re
from pathlib import Path

from click.testing import CliRunner

from cli.main import cli

RATES = 'tests/fixtures/fx_rates_usd_dated.yaml'


def _import_new(runner, book, fixture, *extra):
    result = runner.invoke(cli, ['import', '--new', str(book), fixture,
                                 '--include-business-objects', *extra])
    assert result.exit_code == 0, result.output
    # The CLI exits 0 when individual transactions fail, so a fixture that
    # imports nothing would let a test assert against an empty book and pass
    # on nothing. One did.
    assert 'Errors:       0' in result.output, result.output
    return result


def _import(runner, book, path, *extra):
    return runner.invoke(cli, ['import', str(book), str(path), *extra])


def _export_text(runner, book, out):
    result = runner.invoke(cli, ['export', str(book), str(out),
                                 '--include-business-objects'])
    assert result.exit_code == 0, result.output
    return out.read_text()


def _split_guid(exported: str, split_line: str) -> str:
    """The guid of the split whose line reads `split_line` — how a user finds
    the basis to name, straight out of their own export."""
    lines = exported.splitlines()
    for index, line in enumerate(lines):
        if line.strip() == split_line:
            for following in lines[index + 1:index + 4]:
                match = re.search(r'guid:\s*"([0-9a-f]{32})"', following)
                if match:
                    return match.group(1)
    raise AssertionError(f'no guid found for {split_line!r} in:\n{exported}')


def _split_kvp(book, split_guid: str) -> dict:
    """The custom KVP on one split, read from the book itself.

    The export filters `orphaned_by_unpost` out, so asserting on exported text
    says nothing about whether the key is still on the split. This is how a
    test can tell "cleared" from "hidden".
    """
    from gnucash import Query, Transaction

    from infrastructure.gnucash.kvp import get_custom_metadata
    from repositories.gnucash_repository import GnuCashRepository, SessionMode

    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        query = Query()
        query.search_for('Trans')
        query.set_book(repo.book)
        for raw in query.run():
            for split in Transaction(instance=raw).GetSplitList():
                if split.GetGUID().to_string() == split_guid:
                    found = dict(get_custom_metadata(split))
                    query.destroy()
                    return found
        query.destroy()
    finally:
        repo.close()
    raise AssertionError(f'no split with guid {split_guid!r} in {book}')


def _balances(runner, book):
    result = runner.invoke(cli, ['fx-balances', str(book)])
    assert result.exit_code == 0, result.output
    return result.output


def _write_sale(tmp_path, fixture, **guids):
    text = Path(fixture).read_text()
    for name, value in guids.items():
        text = text.replace('{' + name + '}', value)
    path = tmp_path / 'sale.txt'
    path.write_text(text)
    return path


def _buy_and_borrow_book(runner, tmp_path):
    """A book holding 200 USD: 100 bought at 1.35 and 100 borrowed at 1.30."""
    book = tmp_path / 'book.gnucash'
    _import_new(runner, book, 'tests/fixtures/fx_buy_and_borrow_usd.txt')
    exported = _export_text(runner, book, tmp_path / 'out.txt')
    guids = re.findall(
        r'Assets:Bank:USD 100\.00 USD\n\t+guid: "([0-9a-f]{32})"', exported)
    assert len(guids) == 2, exported
    # The bought basis is dated 2026-01-10, the borrowed one 2026-01-20; the
    # export is chronological.
    return book, guids[0], guids[1]


def test_every_way_currency_arrives_is_listed_with_its_cost(tmp_path):
    """An invoice, a bill, a purchase and a borrowing each establish a basis."""
    runner = CliRunner()
    book, bought, borrowed = _buy_and_borrow_book(runner, tmp_path)
    listing = _balances(runner, book)
    assert bought in listing and borrowed in listing, listing
    # The cost carries its own direction — CAD per USD — so no reader has to
    # guess which way round a bare 1.35 goes.
    assert '1.35 CAD/USD' in listing, listing
    assert '1.3 CAD/USD' in listing, listing
    assert 'Total USD basis balance: 200.00 USD' in listing, listing

    invoice_book = tmp_path / 'inv.gnucash'
    _import_new(runner, invoice_book, 'tests/fixtures/fx_usd_invoice_cad_income.txt',
                '--fx-rates', RATES)
    invoice_listing = _balances(runner, invoice_book)
    assert 'Assets:Accounts Receivable USD' in invoice_listing, invoice_listing
    assert '1.4 CAD/USD' in invoice_listing, invoice_listing
    assert 'Total USD basis balance: 100.00' in invoice_listing, invoice_listing

    bill_book = tmp_path / 'bill.gnucash'
    _import_new(runner, bill_book, 'tests/fixtures/fx_usd_bill_cad_expense.txt',
                '--fx-rates', RATES)
    bill_listing = _balances(runner, bill_book)
    assert 'Accounts Payable USD' in bill_listing, bill_listing
    assert 'Total USD basis balance: 100.00' in bill_listing, bill_listing


def test_two_bases_at_the_same_cost_stay_two(tmp_path):
    """Same cost, same currency, same account — still two bases, each with its
    own basis balance, because each is its own split."""
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    fixture = tmp_path / 'same_cost.txt'
    source = Path('tests/fixtures/fx_buy_and_borrow_usd.txt').read_text()
    fixture.write_text(source.replace('"1.30"', '"1.35"')
                             .replace('130.00', '135.00'))
    _import_new(runner, book, str(fixture))

    listing = _balances(runner, book)
    guids = re.findall(r'\b([0-9a-f]{32})\b', listing)
    assert len(set(guids)) == 2, listing
    assert 'Total USD basis balance: 200.00' in listing, listing


def test_selling_against_one_basis_books_the_gain_and_lowers_that_basis(tmp_path):
    """40 of 100 USD sold: the basis keeps 60.00 available, and the residual
    split books the difference between cost and proceeds."""
    runner = CliRunner()
    book, bought, _borrowed = _buy_and_borrow_book(runner, tmp_path)

    sale = _write_sale(tmp_path, 'tests/fixtures/fx_sell_usd_partial.txt',
                       basis_a=bought)
    result = _import(runner, book, sale)
    assert result.exit_code == 0, result.output

    listing = _balances(runner, book)
    assert '60.00 USD' in listing, listing
    assert 'Total USD basis balance: 160.00' in listing, listing

    exported = _export_text(runner, book, tmp_path / 'after.txt')
    # 40 USD at cost 1.35 is 54.00; sold for 55.60; the residual is the 1.60 gain.
    assert 'Income:FX Gain -1.60 CAD' in exported, exported
    assert f'cost_basis_split_guid: "{bought}"' in exported, exported
    assert 'cost_basis_balance: "60.00"' in exported, exported


def test_a_sale_can_spread_across_several_bases(tmp_path):
    """150 USD sold as 100 from one basis and 50 from another: two USD splits,
    one naming each, and both balances fall by what that sale took."""
    runner = CliRunner()
    book, bought, borrowed = _buy_and_borrow_book(runner, tmp_path)

    sale = _write_sale(tmp_path, 'tests/fixtures/fx_sell_usd_two_cost_bases.txt',
                       basis_a=bought, basis_b=borrowed)
    result = _import(runner, book, sale)
    assert result.exit_code == 0, result.output

    listing = _balances(runner, book)
    assert 'Total USD basis balance: 50.00 USD' in listing, listing
    assert '0.00 USD' in listing, listing

    exported = _export_text(runner, book, tmp_path / 'after.txt')
    # Cost consumed 135.00 + 65.00 = 200.00 against 208.50 of proceeds.
    assert 'Income:FX Gain -8.50 CAD' in exported, exported


def test_selling_more_than_a_basis_has_is_refused(tmp_path):
    runner = CliRunner()
    book, bought, _borrowed = _buy_and_borrow_book(runner, tmp_path)

    sale = _write_sale(tmp_path, 'tests/fixtures/fx_sell_usd_over_available.txt',
                       basis_a=bought)
    result = _import(runner, book, sale)
    message = result.output + str(result.exception)
    assert 'exceeds its basis balance' in message, message

    # And nothing was recorded: the basis still has all 100.00 available.
    listing = _balances(runner, book)
    assert 'Total USD basis balance: 200.00' in listing, listing


def test_selling_at_a_cost_the_basis_does_not_carry_is_refused(tmp_path):
    runner = CliRunner()
    book, bought, _borrowed = _buy_and_borrow_book(runner, tmp_path)

    sale = _write_sale(tmp_path, 'tests/fixtures/fx_sell_usd_wrong_stated_cost.txt',
                       basis_a=bought)
    result = _import(runner, book, sale)
    message = result.output + str(result.exception)
    assert 'cost basis' in message and '1.35' in message, message


def test_naming_a_split_that_is_no_cost_basis_is_refused(tmp_path):
    """A guid that matches nothing, and one that matches a CAD split, are both
    errors rather than a silently uncounted sale."""
    runner = CliRunner()
    book, bought, _borrowed = _buy_and_borrow_book(runner, tmp_path)

    unknown = _write_sale(tmp_path, 'tests/fixtures/fx_sell_usd_partial.txt',
                          basis_a='0' * 32)
    result = _import(runner, book, unknown)
    message = result.output + str(result.exception)
    assert 'matches no split' in message, message


def test_available_balance_survives_export_and_re_import(tmp_path):
    """The balance is book state, so it round-trips — and re-importing the same
    sale does not take it twice."""
    runner = CliRunner()
    book, bought, _borrowed = _buy_and_borrow_book(runner, tmp_path)
    sale = _write_sale(tmp_path, 'tests/fixtures/fx_sell_usd_partial.txt',
                       basis_a=bought)
    assert _import(runner, book, sale).exit_code == 0

    _export_text(runner, book, tmp_path / 'roundtrip.txt')
    fresh = tmp_path / 'fresh.gnucash'
    result = runner.invoke(cli, ['import', '--new', str(fresh),
                                 str(tmp_path / 'roundtrip.txt'),
                                 '--include-business-objects'])
    assert result.exit_code == 0, result.output
    assert '60.00 USD' in _balances(runner, fresh), _balances(runner, fresh)

    # Re-importing the same sale into the original book is a duplicate and
    # changes nothing — the balance is derived from the book, not decremented.
    assert _import(runner, book, sale).exit_code == 0
    assert 'Total USD basis balance: 160.00' in _balances(runner, book)


def test_an_overpayment_opens_a_basis_like_a_borrowing(tmp_path):
    """200.00 USD paid on a 100.00 USD invoice: the bank holds 200, so the
    bases hold 200 of balance between them.

    The overpayment is a credit balance on the receivable — the customer's
    money, held and owed back — which is a borrowing in the shape of the A/P
    side. Counting only the settling split opened a basis for half of what the
    bank held, and a sale of the rest was refused as exceeding its basis.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    _import_new(runner, book,
                'tests/fixtures/fx_invoice_usd_overpaid_into_usd_bank.txt',
                '--fx-rates', RATES)

    listing = _balances(runner, book)
    assert 'Total USD basis balance: 200.00' in listing, listing
    rows = [line for line in listing.splitlines() if 'Accounts Receivable USD' in line]
    assert len(rows) == 2, listing
    for row in rows:
        assert '100.00 USD' in row, row

    # Paid in the invoice's own currency, the payment has no CAD figure in it
    # to derive a cost from — every split is USD and `share_price` describes a
    # rate of 1 — so this is the one basis whose cost is written down, and it
    # is written with its direction. The bank's own 200.00 USD split carries
    # no basis at all for the same reason, which is what keeps the currency
    # from being counted twice.
    exported = _export_text(runner, book, tmp_path / 'out.txt')
    assert 'cost_basis_cost: "1.4 CAD/USD"' in exported, exported
    assert 'cost_basis' not in exported.split('Assets:Bank:USD 200.00 USD')[1] \
        .split('\n\tAssets')[0], exported


def test_the_overpaid_currency_can_then_be_sold(tmp_path):
    """A basis that lists is a basis that sells.

    The book holds 200.00 USD after the overpayment, so all 200.00 can be sold
    — 100 against the invoice's basis and 100 against the credit's, both
    carried at 1.40. The 290.00 CAD it fetches against 280.00 of cost leaves a
    10.00 CAD gain, and nothing is left available.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    _import_new(runner, book,
                'tests/fixtures/fx_invoice_usd_overpaid_into_usd_bank.txt',
                '--fx-rates', RATES)

    guids = re.findall(r'\b([0-9a-f]{32})\b', _balances(runner, book))
    assert len(guids) == 2, _balances(runner, book)

    sale = _write_sale(tmp_path, 'tests/fixtures/fx_sell_overpaid_usd.txt',
                       basis_a=guids[0], basis_b=guids[1])
    result = _import(runner, book, sale)
    assert result.exit_code == 0, result.output

    exported = _export_text(runner, book, tmp_path / 'out.txt')
    assert 'Income:FX Gain -10.00 CAD' in exported, exported
    assert 'Total USD basis balance: 0.00' in _balances(runner, book), _balances(runner, book)


def test_a_second_record_does_not_open_bases_on_the_first(tmp_path):
    """Two foreign records sharing one receivable stay independent.

    Opening a basis for an overpayment means finding the split the payment
    left behind. Looking for it across the whole account finds every *other*
    record's settlement split too — none of them in this record's lot — and
    stamps them with this record's cost. Two ordinary invoices on one A/R
    account were enough: the book claimed 400.00 USD sellable while the bank
    held 300.00.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    _import_new(runner, book,
                'tests/fixtures/fx_invoice_usd_overpaid_into_usd_bank.txt',
                '--fx-rates', RATES)
    result = runner.invoke(cli, [
        'import', str(book), 'tests/fixtures/fx_invoice_usd_paid_from_usd_bank.txt',
        '--include-business-objects', '--fx-rates', RATES])
    assert result.exit_code == 0, result.output

    listing = _balances(runner, book)
    # 100.00 from the first invoice, 100.00 it was overpaid by, 100.00 from the
    # second — which is exactly what the USD bank holds.
    assert 'Total USD basis balance: 300.00' in listing, listing
    rows = [line for line in listing.splitlines() if 'USD' in line and 'CAD/USD' in line]
    assert len(rows) == 3, listing

    # And the second payment wrote nothing onto the first invoice's splits.
    exported = _export_text(runner, book, tmp_path / 'out.txt')
    settling = exported.split('Payment for INV-USD-OVER')
    assert len(settling) > 1, exported
    assert 'cost_basis_cost' not in settling[1].split('2026-')[0], exported


def test_paying_down_a_payable_opens_no_basis(tmp_path):
    """A debit on a payable is money sent, not currency held.

    A vendor prepayment is a debit on that same account and *is* a basis, so
    the direction alone cannot separate them — the lot does: a settlement
    belongs to the bill it settles, a prepayment to nothing yet. Counting
    either direction offered 100.00 USD that had already left the book.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    _import_new(runner, book, 'tests/fixtures/fx_pay_down_usd_payable.txt')

    listing = _balances(runner, book)
    assert 'No foreign-currency cost bases found' in listing, listing

    exported = _export_text(runner, book, tmp_path / 'out.txt')
    assert 'cost_basis' not in exported, exported


def test_a_hand_written_overpayment_opens_one_basis_only(tmp_path):
    """A prepayment written as an ordinary transaction, and no lot anywhere.

    The 100.00 USD arrives in the bank and the receivable carries the credit
    that says it is owed back. Only the bank side is currency the book can
    sell, and its basis is there; counting the credit as well would offer
    200.00 USD against 100.00 held.

    This is the shape that has no lot at all, which the prepayment test
    (`_is_prepayment`) answers False for. That was raised as a defect — a
    hand-written credit no longer establishing a basis, its currency
    unsellable — and this test is why it is not one: the currency arrived in
    the bank, the bank split is a basis for it, and it is sellable from there.
    Answering True for the lot-less credit as well would list the same 100.00
    USD twice. What the credit records is the obligation, not a second holding.

    The lotted prepayment gets the same answer for the same reason
    (`test_refunding_a_prepayment_opens_no_basis`), so `lot_owner:` changes
    which side of a receivable a split is, not how many holdings there are.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    _import_new(runner, book,
                'tests/fixtures/hand_written_customer_overpayment.txt')

    listing = _balances(runner, book)
    assert 'Total USD basis balance: 100.00' in listing, listing
    assert listing.count('1.4 CAD/USD') == 1, listing


def test_refunding_a_prepayment_opens_no_basis(tmp_path):
    """A receivable debit is not always currency arriving.

    An invoice posting and a refund are both debits on the receivable. The
    posting brings in currency the customer owes; the refund sends the
    customer's own money back. The lot is what separates them — a posting sits
    in the lot its invoice owns, a refund settles an owner lot no invoice
    owns — and counting every debit offered 100.00 USD that had already left.

    The prepayment itself is one lump written twice, and is listed once: the
    bank took the money, so the bank split is the basis and the credit facing
    it is the obligation. `lot_owner:` says which side of a receivable this
    is, not how many holdings there are — counting the credit as well listed
    the same 100.00 USD twice, disagreeing with the hand-written overpayment
    above over the same economics.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    _import_new(runner, book, 'tests/fixtures/fx_refund_usd_prepayment.txt')

    listing = _balances(runner, book)
    # One lump of currency, one basis: the bank's 100.00 USD. The credit
    # facing it records the obligation, not a second holding — the same
    # answer the hand-written overpayment above gets, and `lot_owner:` does
    # not change what the money is. The refund adds nothing either: it sends
    # that money away.
    assert 'Total USD basis balance: 100.00' in listing, listing
    assert listing.count('1.37 CAD/USD') == 1, listing
    assert 'Assets:Bank:USD' in listing, listing
    assert 'Receivable' not in listing, listing


def test_a_prepayment_arriving_as_base_currency_opens_it_on_the_receivable(tmp_path):
    """The obligation is the only record of the currency, so it carries it.

    A customer prepays 100 USD and the bank takes CAD: there is no
    foreign-currency split beside the credit, and the book holds no USD
    anywhere. The credit is the basis — 100.00 USD at 1.37 — and a basis's
    total is not an account's balance.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    _import_new(runner, book, 'tests/fixtures/fx_prepayment_arriving_as_cad.txt')

    listing = _balances(runner, book)
    assert 'Accounts Receivable USD' in listing, listing
    assert 'Total USD basis balance: 100.00' in listing, listing
    assert '1.37 CAD/USD' in listing, listing


def test_a_settlement_arriving_as_base_currency_opens_no_second_basis(tmp_path):
    """Why the lot-less credit is not read as a prepayment.

    Written by hand with the money arriving as CAD, a settlement and a
    prepayment are the same three lines; only the lot differs, and neither
    hand-written split has one. This is the settlement half: the receivable
    already opened its 100.00 USD basis when it was written, and the credit
    that closes it brings nothing in.

    Reading every lot-less credit as a prepayment — which is what recognising
    the prepayment half by shape alone would mean — lists this settlement as a
    second basis and offers 200.00 USD from a book holding none. The
    prepayment says which it is with `lot_owner:`, and opens its basis in full
    (see the test above).
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    _import_new(runner, book, 'tests/fixtures/fx_settlement_arriving_as_cad.txt')

    listing = _balances(runner, book)
    assert 'Total USD basis balance: 100.00' in listing, listing
    assert listing.count('1.4 CAD/USD') == 1, listing
    assert '1.37 CAD/USD' not in listing, listing


def test_a_refused_transaction_leaves_every_basis_where_it_was(tmp_path):
    """A file that names a basis and is then refused moves nothing.

    The transaction here picks a basis for 40.00 USD and states, on the split
    below, a cost that cannot be read. The whole thing is refused before it is
    created — a stated cost is checked first, ahead of the transaction and
    ahead of the pick — so no balance is ever lowered, the rest of the file
    still imports, and the book keeps its 200.00 USD.

    This is the reachable half. That the drawdown can be *undone* once it has
    happened is a separate guarantee with a separate test
    (`tests/unit/services/test_cost_basis_drawdown_is_reversible.py`): no file
    can provoke a refusal between the drawdown and the end of the import, so a
    fixture claiming to would assert nothing.
    """
    runner = CliRunner()
    book, bought, _borrowed = _buy_and_borrow_book(runner, tmp_path)

    rejected = _write_sale(tmp_path,
                           'tests/fixtures/fx_sale_refused_before_drawing_down.txt',
                           basis_a=bought)
    result = _import(runner, book, rejected)
    assert 'cost_basis_cost' in result.output, result.output
    assert 'Transactions: 1' in result.output, result.output    # the other one

    listing = _balances(runner, book)
    assert 'Total USD basis balance: 200.00' in listing, listing
    assert '60.00 USD' not in listing, listing

    exported = _export_text(runner, book, tmp_path / 'after.txt')
    assert 'Sell 40 USD beside' not in exported, exported


def test_prepaying_a_vendor_from_a_usd_bank_moves_the_basis_across(tmp_path):
    """The vendor mirror of a customer's overpayment, both ways round.

    Sending a vendor 100 USD out of the USD the book holds leaves a claim on
    that vendor for the same 100 USD, and the claim is where the currency now
    is: the payable debit establishes a basis. The bank side is a spend like
    any other, so it names the basis it spends and that basis goes to zero —
    the 100 USD stays counted once, on the account that now holds it.

    Written without naming it, the outgoing side draws down nothing and the
    listing keeps offering the bank's basis: 200.00 USD against 100.00 held.
    That is the same rule as any sale that names no basis, and it is asserted
    here so the vendor case is not read as an exception to it.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    _import_new(runner, book, 'tests/fixtures/fx_vendor_prepayment_setup.txt')
    basis = re.search(r'\b([0-9a-f]{32})\b', _balances(runner, book)).group(1)

    prepayment = _write_sale(
        tmp_path, 'tests/fixtures/fx_vendor_prepayment_from_usd_bank.txt',
        basis_a=basis)
    result = _import(runner, book, prepayment)
    assert result.exit_code == 0, result.output

    listing = _balances(runner, book)
    assert 'Accounts Payable USD' in listing, listing
    assert 'Total USD basis balance: 100.00' in listing, listing
    assert '0.00 USD' in listing, listing            # the bank's basis, spent

    # The same prepayment naming nothing on its way out.
    bare_book = tmp_path / 'bare.gnucash'
    _import_new(runner, bare_book, 'tests/fixtures/fx_vendor_prepayment_setup.txt')
    bare = tmp_path / 'bare.txt'
    bare.write_text(
        Path('tests/fixtures/fx_vendor_prepayment_from_usd_bank.txt').read_text()
        .replace('\t\tcost_basis_split_guid: "{basis_a}"\n', ''))
    result = _import(runner, bare_book, bare)
    assert result.exit_code == 0, result.output
    assert 'Total USD basis balance: 200.00' in _balances(runner, bare_book)


def test_a_refund_naming_no_lot_reads_as_the_receivable_it_resembles(tmp_path):
    """`lot_owner:` decides on the debit side too, not only the credit side.

    A refund and a receivable written by hand are the same three lines. What
    separates them is the lot — a refund settles the owner lot no invoice
    owns — so a debit naming none is read as a receivable and establishes a
    basis, exactly as a credit naming none is read as a settlement and does
    not. Neither side guesses, and neither side is stricter than the other.

    Written as this fixture does, the listing reports 100.00 USD on the
    receivable while the bank's USD has gone. That is right for the reading
    the file gave it and wrong for the one it meant, which is why the refund
    fixture beside it names its owner.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    _import_new(runner, book, 'tests/fixtures/fx_refund_without_a_lot_owner.txt')

    listing = _balances(runner, book)
    assert 'Accounts Receivable USD' in listing, listing
    assert '1.37 CAD/USD' in listing, listing

    # And with `lot_owner:` on that same debit, nothing is established: the
    # one line is the whole difference.
    lotted = tmp_path / 'lotted.gnucash'
    _import_new(runner, lotted, 'tests/fixtures/fx_refund_usd_prepayment.txt')
    lotted_listing = _balances(runner, lotted)
    assert 'Receivable' not in lotted_listing, lotted_listing


def test_currency_arriving_in_a_liability_counts_as_having_arrived(tmp_path):
    """One lump, one basis — including when the lump arrives as a credit.

    A vendor prepaid from a USD credit line writes the draw and the claim in
    one transaction. The draw is where the currency entered the book, and a
    liability rises as its amount goes *negative*, so a test for "did this
    currency arrive elsewhere" that looks for a positive amount is blind to
    it: the payable debit then opened a second basis and the listing offered
    200.00 USD for one 100.00 USD draw.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    _import_new(runner, book,
                'tests/fixtures/fx_vendor_prepayment_from_a_usd_credit_line.txt')

    listing = _balances(runner, book)
    assert 'Total USD basis balance: 100.00' in listing, listing
    assert 'USD Credit Line' in listing, listing
    assert 'Accounts Payable' not in listing, listing


def test_an_overpayment_retargeted_into_the_lot_opens_the_credits_basis(tmp_path):
    """A bank transaction already in the book, divided by `txn_guid:`.

    The overpayment mechanic is reached two ways, and only one of them moves
    money. A `payment:` block with `account:` has GnuCash write the payment;
    a block with `txn_guid:` attaches a transaction the book already holds —
    off a bank feed, say — and divides it in place. Both leave the same two
    splits on the receivable: the part that settled the invoice, in its lot,
    and the credit, in a lot of its own.

    The credit is currency the book holds and owes back, so it is a basis like
    any other, and its cost is the one the invoice was carried at: paid in the
    invoice's own currency, the transaction states no CAD figure to derive it
    from. Without it the book claimed 100.00 USD sellable while its bank held
    200.00, and selling what it actually had was refused for exceeding a basis
    nothing had opened.
    """
    from repositories.gnucash_repository import GnuCashRepository, SessionMode

    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    _import_new(runner, book, 'tests/fixtures/fx_usd_overpayment_retargeted_setup.txt',
                '--fx-rates', RATES)

    bank = tmp_path / 'bank.txt'
    bank.write_text(
        Path('tests/fixtures/fx_usd_overpayment_retargeted_bank.txt').read_text())
    assert runner.invoke(cli, ['import', str(book), str(bank),
                               '--fx-rates', RATES]).exit_code == 0

    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        from gnucash import Query, Transaction
        query = Query()
        query.search_for('Trans')
        query.set_book(repo.book)
        txn_guid = None
        for raw in query.run():
            transaction = Transaction(instance=raw)
            for split in transaction.GetSplitList():
                if str(split.GetAmount()) == '20000/100':
                    txn_guid = transaction.GetGUID().to_string()
        query.destroy()
    finally:
        repo.close()
    assert txn_guid is not None

    attach = tmp_path / 'attach.txt'
    attach.write_text(
        Path('tests/fixtures/fx_usd_overpayment_retargeted_invoice.txt')
        .read_text().replace('TXN_GUID', txn_guid))
    result = runner.invoke(cli, ['import', str(book), str(attach),
                                 '--include-business-objects', '--fx-rates', RATES])
    assert result.exit_code == 0, result.output

    # Both halves are bases, at the rate the invoice was booked at, and the
    # book offers exactly the 200.00 USD its bank holds.
    listing = _balances(runner, book)
    assert listing.count('1.4 CAD/USD') == 2, listing
    assert 'Total USD basis balance: 200.00 USD' in listing, listing

    checked = runner.invoke(cli, ['fx-balances', str(book), '--verify-costs'])
    assert checked.exit_code == 0, checked.output

    # An overpaid invoice stays editable. Unposting to rebuild it leaves the
    # transaction carrying two splits a retarget could place — the settlement
    # just orphaned, and the residue this same invoice parked — so counted
    # together they read as ambiguous, and an ordinary edit becomes
    # unimportable with the remedy reachable only by re-exporting. The mark is
    # what says which of the two was ever this invoice's.
    edited = tmp_path / 'edited.txt'
    edited.write_text(
        Path('tests/fixtures/fx_usd_overpaid_invoice_edited.txt')
        .read_text().replace('TXN_GUID', txn_guid))
    # The edit revises a line, and a line under a posting is changed by
    # unposting first — which is also what orphans the settlement this test
    # then watches the rebuild take back.
    assert runner.invoke(cli, ['unpost-invoices', str(book),
                               'INV-USD-RETARGET']).exit_code == 0
    again = runner.invoke(cli, ['import', str(book), str(edited),
                                '--include-business-objects', '--fx-rates', RATES])
    assert again.exit_code == 0, again.output
    assert 'names only the transaction' not in again.output, again.output

    reread = _export_text(runner, book, tmp_path / 'edited_out.txt')
    edited_block = reread.split('invoice "INV-USD-RETARGET"')[1]
    assert 'Consulting, revised' in edited_block, edited_block
    assert 'payment: none' not in edited_block, edited_block
    assert runner.invoke(cli, ['fx-balances', str(book),
                               '--verify-costs']).exit_code == 0

    # And a second invoice may then spend that credit the short way — naming
    # the transaction and nothing else. The money is the customer's, sitting in
    # a lot of the customer's, so this settles out of credit whether or not the
    # file uses the word: the split's basis is spent with it, and the book goes
    # back to offering the 100.00 USD its bank actually holds free.
    second = tmp_path / 'second.txt'
    second.write_text(
        Path('tests/fixtures/second_usd_invoice_takes_the_parked_credit.txt')
        .read_text().replace('TXN_GUID', txn_guid))
    spent = runner.invoke(cli, ['import', str(book), str(second),
                                '--include-business-objects', '--fx-rates', RATES])
    assert spent.exit_code == 0, spent.output

    # The credit was spent, so it is no longer currency the book holds: the
    # deposit of 2026-02-25 drops off the listing, and what is left is the two
    # invoices' own receivables — 200.00 USD, which is what the bank holds.
    # Left with its basis it would offer 300.00 against a bank holding 200.00,
    # money the book cannot produce and no other figure disagrees with.
    listing = _balances(runner, book)
    assert '2026-02-25' not in listing, listing
    assert 'Total USD basis balance: 200.00 USD' in listing, listing
    assert listing.count('CAD/USD') == 2, listing

    checked = runner.invoke(cli, ['fx-balances', str(book), '--verify-costs'])
    assert checked.exit_code == 0, checked.output

    # And it is written down on the split, so the export says what happened:
    # this invoice was settled out of credit, and reads back as the
    # `from_credit:` block it would have been written as the long way. Nothing
    # else about the split afterwards says the money came out of credit rather
    # than out of a bank.
    exported = _export_text(runner, book, tmp_path / 'out.txt')
    second_block = exported.split('invoice "INV-USD-SECOND"')[1]
    assert 'from_credit: #True' in second_block, second_block
    assert 'bank_account:' not in second_block.split('payment:')[1], second_block


def test_a_bare_retarget_dividing_a_credit_carries_its_cost(tmp_path):
    """A credit bigger than the invoice it settles, named the short way.

    The whole-split move and the division are different code, and only the
    first was covered for this spelling. Dividing, what is left over keeps the
    cost the credit was acquired at — the figure already on the split it was
    carved from — because a `from_credit:` block reaching the identical
    division does exactly that.

    Priced instead at the settling record's own posting cost, which is what
    happens when the division is not recognised as spending a credit, the
    remainder would be valued at the later invoice's rate. Here that is 1.37
    against the 1.4 the money actually arrived at: a gain the customer's
    money never made, on currency the book merely still owes them.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    _import_new(runner, book, 'tests/fixtures/fx_usd_overpayment_retargeted_setup.txt',
                '--fx-rates', RATES)

    bank = tmp_path / 'bank.txt'
    bank.write_text(
        Path('tests/fixtures/fx_usd_overpayment_retargeted_bank.txt').read_text())
    assert runner.invoke(cli, ['import', str(book), str(bank),
                               '--fx-rates', RATES]).exit_code == 0

    from repositories.gnucash_repository import GnuCashRepository, SessionMode
    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        from gnucash import Query, Transaction
        query = Query()
        query.search_for('Trans')
        query.set_book(repo.book)
        txn_guid = None
        for raw in query.run():
            transaction = Transaction(instance=raw)
            for split in transaction.GetSplitList():
                if str(split.GetAmount()) == '20000/100':
                    txn_guid = transaction.GetGUID().to_string()
        query.destroy()
    finally:
        repo.close()
    assert txn_guid is not None

    attach = tmp_path / 'attach.txt'
    attach.write_text(
        Path('tests/fixtures/fx_usd_overpayment_retargeted_invoice.txt')
        .read_text().replace('TXN_GUID', txn_guid))
    assert runner.invoke(cli, ['import', str(book), str(attach),
                               '--include-business-objects', '--fx-rates',
                               RATES]).exit_code == 0

    third = tmp_path / 'third.txt'
    third.write_text(
        Path('tests/fixtures/third_usd_invoice_dividing_the_parked_credit.txt')
        .read_text().replace('TXN_GUID', txn_guid))
    divided = runner.invoke(cli, ['import', str(book), str(third),
                                  '--include-business-objects', '--fx-rates', RATES])
    assert divided.exit_code == 0, divided.output

    # Recorded as a credit spent, and the 60.00 left of it still costs what it
    # cost — 1.4, not the 1.37 this invoice was posted at.
    exported = _export_text(runner, book, tmp_path / 'out.txt')
    block = exported.split('invoice "INV-USD-THIRD"')[1]
    assert 'from_credit: #True' in block, block

    # The row for the deposit is what the division left: 60.00 still owed
    # back, at the 1.4 it arrived at. INV-USD-THIRD's own 1.37 row beneath it
    # is its receivable, which is a separate basis and rightly at its own rate.
    listing = _balances(runner, book)
    remainder = next((line for line in listing.splitlines()
                      if line.startswith('2026-02-25')), '')
    assert '1.4 CAD/USD' in remainder, listing
    assert '60.00 USD' in remainder, listing
    assert '1.37' not in remainder, listing
    assert 'Total USD basis balance: 200.00 USD' in listing, listing
    assert runner.invoke(cli, ['fx-balances', str(book),
                               '--verify-costs']).exit_code == 0


def test_naming_a_credits_split_by_guid_spends_it_like_any_other(tmp_path):
    """The third spelling, which must answer as the other two do.

    `txn_split_guid:` says *which* split settles the invoice, not where the
    money came from — so a guid landing on an owner's parked credit spends
    that credit, and the accounting follows the split rather than the wording.

    This is the route the ambiguity refusal names: once a transaction carries
    two of an owner's credits, the bare `txn_guid:` spelling is refused and
    the reader is told to name the split. Following that advice must not
    quietly drop what the refused spelling would have done.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    _import_new(runner, book, 'tests/fixtures/fx_usd_overpayment_retargeted_setup.txt',
                '--fx-rates', RATES)

    bank = tmp_path / 'bank.txt'
    bank.write_text(
        Path('tests/fixtures/fx_usd_overpayment_retargeted_bank.txt').read_text())
    assert runner.invoke(cli, ['import', str(book), str(bank),
                               '--fx-rates', RATES]).exit_code == 0

    from repositories.gnucash_repository import GnuCashRepository, SessionMode
    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        from gnucash import Query, Transaction
        query = Query()
        query.search_for('Trans')
        query.set_book(repo.book)
        txn_guid = None
        for raw in query.run():
            transaction = Transaction(instance=raw)
            for split in transaction.GetSplitList():
                if str(split.GetAmount()) == '20000/100':
                    txn_guid = transaction.GetGUID().to_string()
        query.destroy()
    finally:
        repo.close()
    assert txn_guid is not None

    attach = tmp_path / 'attach.txt'
    attach.write_text(
        Path('tests/fixtures/fx_usd_overpayment_retargeted_invoice.txt')
        .read_text().replace('TXN_GUID', txn_guid))
    assert runner.invoke(cli, ['import', str(book), str(attach),
                               '--include-business-objects', '--fx-rates',
                               RATES]).exit_code == 0

    # The residue the division parked, found the way a user would: it is the
    # remaining receivable split on that transaction.
    exported = _export_text(runner, book, tmp_path / 'before.txt')
    # Two receivable splits of -100.00 sit on that transaction now: the part
    # that settled INV-USD-RETARGET, and the residue parked as the customer's
    # credit. The credit is the one carrying `lot_owner:`, which is how the
    # export says whose money a split is and how a reader would pick it out.
    split_guid = None
    lines = exported.splitlines()
    for index, line in enumerate(lines):
        if line.strip() != 'Assets:Accounts Receivable USD -100.00 USD':
            continue
        # This split's own lines only: everything indented deeper than the
        # split line, stopping at the next split. Reading a fixed window ran
        # into the sibling below and returned the settlement's guid for the
        # credit's `lot_owner:`.
        depth = len(line) - len(line.lstrip('\t'))
        own, found = [], None
        for following in lines[index + 1:]:
            if len(following) - len(following.lstrip('\t')) <= depth:
                break
            own.append(following)
        if not any('lot_owner:' in entry for entry in own):
            continue
        for entry in own:
            match = re.search(r'guid:\s*"([0-9a-f]{32})"', entry)
            if match:
                found = match.group(1)
                break
        if found:
            split_guid = found
            break
    assert split_guid is not None, exported

    second = tmp_path / 'second.txt'
    second.write_text(
        Path('tests/fixtures/second_usd_invoice_names_the_credit_split.txt')
        .read_text().replace('TXN_GUID', txn_guid).replace('SPLIT_GUID', split_guid))
    spent = runner.invoke(cli, ['import', str(book), str(second),
                                '--include-business-objects', '--fx-rates', RATES])
    assert spent.exit_code == 0, spent.output

    # Recorded as what it was: a credit spent, not a bank payment.
    after = _export_text(runner, book, tmp_path / 'out.txt')
    block = after.split('invoice "INV-USD-NAMED"')[1]
    assert 'from_credit: #True' in block, block

    # And spent, so the credit is no longer currency the book holds — the same
    # answer the bare spelling gives on the same move.
    listing = _balances(runner, book)
    assert '2026-02-25' not in listing, listing
    assert 'Total USD basis balance: 200.00 USD' in listing, listing
    assert runner.invoke(cli, ['fx-balances', str(book),
                               '--verify-costs']).exit_code == 0


def test_a_settlement_an_unpost_orphaned_is_not_read_as_credit_later(tmp_path):
    """The mirror of the case above, and the one that outlives the process.

    Unposting leaves the lot on the account holding whatever settled the
    invoice, and a lot holding no invoice is exactly what an owner's credit
    looks like — live, naming nothing, owner attached, nothing in the book
    telling them apart. That state is saved to the file, so the import that
    finds it may be days later and knows nothing of the unpost that made it.

    Read as a credit, the rebuild would strip `cost_basis_balance` from a
    settlement the bank really paid — the book then offering *less* USD than
    it holds — and the export would write that bank payment as
    `from_credit: true`, losing the account and the date the money came from.

    So the unpost writes down what it orphaned, and names the invoice it
    orphaned it from. Driven here through the `unpost-invoices` command, which
    is the one-step route into the state and shares no memory at all with the
    import that comes after it.

    The deposit settles the invoice *exactly*, which is the case the mark alone
    has to carry: no residue is parked beside the orphan, so the transaction
    offers one candidate, and the ambiguity guard — which does catch the
    overpaid shape — has nothing to say about it.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    _import_new(runner, book, 'tests/fixtures/fx_usd_overpayment_retargeted_setup.txt',
                '--fx-rates', RATES)

    bank = tmp_path / 'bank.txt'
    bank.write_text(
        Path('tests/fixtures/fx_usd_exact_settlement_bank.txt').read_text())
    assert runner.invoke(cli, ['import', str(book), str(bank),
                               '--fx-rates', RATES]).exit_code == 0

    from repositories.gnucash_repository import GnuCashRepository, SessionMode
    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        from gnucash import Query, Transaction
        query = Query()
        query.search_for('Trans')
        query.set_book(repo.book)
        txn_guid = None
        for raw in query.run():
            transaction = Transaction(instance=raw)
            for split in transaction.GetSplitList():
                if str(split.GetAmount()) == '10000/100':
                    txn_guid = transaction.GetGUID().to_string()
        query.destroy()
    finally:
        repo.close()
    assert txn_guid is not None

    attach = tmp_path / 'attach.txt'
    attach.write_text(
        Path('tests/fixtures/fx_usd_invoice_settled_exactly_by_retarget.txt')
        .read_text().replace('TXN_GUID', txn_guid))
    assert runner.invoke(cli, ['import', str(book), str(attach),
                               '--include-business-objects', '--fx-rates',
                               RATES]).exit_code == 0

    # Unposted on its own, as a person would from the command line. The 100.00
    # that settled the invoice is now sitting in a lot naming no invoice.
    unposted = runner.invoke(cli, ['unpost-invoices', str(book),
                                   'INV-USD-RETARGET'])
    assert unposted.exit_code == 0, unposted.output

    # Exported from that state — which is where a person stops, looks at the
    # orphan warning, and dumps the book — the note stays behind. It is true of
    # this book and only until the invoice is rebuilt, and a file carrying it
    # would land it on whatever split it was imported onto, where it would say
    # "not an owner's credit" about a split that is one.
    mid = _export_text(runner, book, tmp_path / 'mid.txt')
    assert 'orphaned_by_unpost' not in mid, mid

    # In the book, though, it is on the split — which is the whole point of it
    # being durable. Read from the book rather than the export, or the filter
    # above would answer for it and "cleared" would look like "hidden".
    settling_guid = _split_guid(
        mid, 'Assets:Accounts Receivable USD -100.00 USD')
    assert 'orphaned_by_unpost' in _split_kvp(book, settling_guid), \
        _split_kvp(book, settling_guid)

    # And nothing offers it as money to spend. The lot it sits in passes every
    # test a credit passes — live, no invoice, owner attached — so both
    # listings have to ask the same question the settling paths ask, or the
    # tool advertises a credit and then refuses every attempt to use it.
    #
    assert 'open_prepayment:' not in mid, mid
    prepayments = runner.invoke(cli, ['find-prepayments', str(book)])
    assert prepayments.exit_code == 0, prepayments.output
    assert '100.00' not in prepayments.output, prepayments.output

    # Nor does that file rebuild it as one somewhere else. The mark cannot
    # travel — a file may not assert it — so what must not travel either is
    # `lot_owner:`, which is a file saying "this split is an owner's credit,
    # put it in a lot of theirs". Written, restoring the export into a fresh
    # book turned a bank's payment into spendable credit under this very
    # version, which is the whole harm, reached through the ordinary
    # export-and-restore workflow rather than a legacy book.
    restored = tmp_path / 'restored.gnucash'
    assert runner.invoke(cli, ['import', '--new', str(restored), str(
        tmp_path / 'mid.txt'), '--include-business-objects',
        '--fx-rates', RATES]).exit_code == 0
    listed = runner.invoke(cli, ['find-prepayments', str(restored)])
    assert listed.exit_code == 0, listed.output
    assert '100.00' not in listed.output, listed.output
    assert 'lot_owner' not in mid, mid

    # But it is still money, and the restored book has to say so. Taking the
    # credit away leaves a loose split on the receivable, which nothing lists
    # by itself: not `find-prepayments`, which lists lots, and not this, whose
    # two other readings are the engine's type slot and the owner the engine
    # recorded. On GnuCash 4.4 and 3.8 the engine answers neither for a
    # settlement attached by retarget, so the export wrote neither line and
    # the restored book carried a receivable of −100.00 that no command
    # explained — the "listed by no command" hole again, one workflow further
    # on, and reachable through export-and-restore under this version.
    restored_orphans = runner.invoke(cli, ['find-orphan-payments',
                                           str(restored)])
    assert restored_orphans.exit_code == 0, restored_orphans.output
    assert '100.00' in restored_orphans.output, restored_orphans.output
    assert 'C-US' in restored_orphans.output, restored_orphans.output

    # And it survives the next round-trip too. Exporting the restored book has
    # to re-emit what it was given: the owner slot is `gncOwnerApplyPayment`'s
    # and cannot be set from Python, so on that book the `owner:` line the
    # file carried is the only copy of it, and dropping it as already-written
    # lost the orphan one workflow later rather than one.
    again = _export_text(runner, restored, tmp_path / 'again.txt')
    twice = tmp_path / 'twice.gnucash'
    assert runner.invoke(cli, ['import', '--new', str(twice), str(
        tmp_path / 'again.txt'), '--include-business-objects',
        '--fx-rates', RATES]).exit_code == 0
    still = runner.invoke(cli, ['find-orphan-payments', str(twice)])
    assert still.exit_code == 0, still.output
    assert '100.00' in still.output, still.output
    assert 'C-US' in still.output, still.output
    assert 'orphaned_by_unpost' not in again, again

    # It is an orphaned payment, and that is the command that says so — on
    # every supported engine. Both of the readings `find-orphan-payments` used
    # miss a settlement attached by retarget: the 5.x heuristic wants a
    # lot-and-owner backref it never had, and the `txn_type:` KVP only exists
    # once a book has been exported. So it reads the mark, which the unpost
    # wrote on the split. Without it, GnuCash 4.4 and 3.8 listed this money
    # nowhere at all while every refusal about it asked for a guid.
    orphans = runner.invoke(cli, ['find-orphan-payments', str(book)])
    assert orphans.exit_code == 0, orphans.output
    assert '100.00' in orphans.output, orphans.output
    assert txn_guid in orphans.output.replace('-', ''), orphans.output

    # And the reasons given are the ones that applied — which differ by
    # engine, so what is asserted is the invariant rather than either answer.
    # The mark is always there: it is why this row exists. The transaction's
    # type and owner slots are read where they answer (GnuCash 5.10 derives
    # them from the lot the retarget left) and left out where they do not
    # (4.4 and 3.8 want a backref this settlement never had), and the owner is
    # named exactly once either way — by the transaction or by the lot.
    assert 'orphaned_by_unpost' in orphans.output, orphans.output
    named_by_txn = 'gncOwnerGetOwnerFromTxn(tx) returned' in orphans.output
    named_by_lot = 'the lot it sits in names' in orphans.output
    assert named_by_txn != named_by_lot, orphans.output

    # The third spelling is the one a reader is led into: unposting puts the
    # money in a lot of the customer's, so `find-prepayments` and the exported
    # `open_prepayment:` both offer it as a credit to spend. Writing it as one
    # is refused, because a bank paid this and the split never said otherwise.
    miscalled = tmp_path / 'as_credit.txt'
    miscalled.write_text(
        Path('tests/fixtures/fx_usd_invoice_calling_its_own_orphan_a_credit.txt')
        .read_text().replace('TXN_GUID', txn_guid)
        .replace('SPLIT_GUID', settling_guid))
    refused = runner.invoke(cli, ['import', str(book), str(miscalled),
                                  '--include-business-objects', '--fx-rates', RATES])
    assert refused.exit_code != 0, refused.output
    assert 'a settlement a bank paid' in refused.output, refused.output
    assert 'txn_guid:' in refused.output, refused.output

    # A separate import, which knows nothing of that unpost beyond what the
    # book carries. It re-posts the invoice and takes its settlement back.
    again = runner.invoke(cli, ['import', str(book), str(attach),
                                '--include-business-objects', '--fx-rates', RATES])
    assert again.exit_code == 0, again.output

    # Still a bank payment, with the account and date that paid it — not a
    # credit spent, which is what the same move out of an owner's lot means.
    exported = _export_text(runner, book, tmp_path / 'out.txt')
    block = exported.split('invoice "INV-USD-RETARGET"')[1]
    assert 'from_credit' not in block, block
    assert 'Assets:Bank:USD' in block, block
    assert 'orphaned_by_unpost' not in exported, exported

    # And the note is gone from the split, not merely filtered out of the
    # file: the rebuild put it back in an invoice's lot, so it is a settlement
    # again and nothing it carries should still call it an orphan.
    assert 'orphaned_by_unpost' not in _split_kvp(book, settling_guid), \
        _split_kvp(book, settling_guid)

    # And the basis is where it was: the 100.00 the bank holds, at the rate the
    # invoice was booked at. Read as a credit spent, this split would have been
    # stripped and the book would offer nothing against a bank holding 100.00.
    listing = _balances(runner, book)
    assert 'Total USD basis balance: 100.00 USD' in listing, listing
    assert runner.invoke(cli, ['fx-balances', str(book),
                               '--verify-costs']).exit_code == 0

    # And the same holds when the engine does the choosing rather than the
    # file. Edited again and asking for whatever credit the customer has, with
    # no payment block of its own: the unpost orphans the settlement, and
    # `auto_apply_credit: true` has GnuCash search for open, naming nothing,
    # owner-attached lots — which is exactly what it has just been left. The
    # engine may well hand the invoice its own settlement back; what it must
    # not do is have that recorded as a credit spent, because no credit was.
    edited = tmp_path / 'edited.txt'
    edited.write_text(
        Path('tests/fixtures/fx_usd_invoice_rebuilt_asking_for_any_credit.txt')
        .read_text())
    # As above: the revision changes a line, so the unpost is its own step —
    # and it is the unpost that leaves the orphan this test is about.
    assert runner.invoke(cli, ['unpost-invoices', str(book),
                               'INV-USD-RETARGET']).exit_code == 0
    revised = runner.invoke(cli, ['import', str(book), str(edited),
                                  '--include-business-objects', '--fx-rates', RATES])
    assert revised.exit_code == 0, revised.output

    exported = _export_text(runner, book, tmp_path / 'after.txt')
    block = exported.split('invoice "INV-USD-RETARGET"')[1]
    assert 'Consulting, revised' in block, block
    assert 'from_credit' not in block, block

    # Read off the split, not out of the file. The engine's own
    # `gnc_lot_add_split` put it back in the invoice's lot, which is the one
    # route in that does not pass `_attach_split_to_lot`, so the note has to
    # come off here too — and the export filter would hide a stale one.
    assert 'orphaned_by_unpost' not in _split_kvp(book, settling_guid), \
        _split_kvp(book, settling_guid)


def test_an_orphan_partly_spent_elsewhere_stops_being_that_invoices_own(tmp_path):
    """What a credit carve does to the mark, and what it must not do.

    An orphaned settlement is a credit like any other to every invoice but
    the one it was orphaned from — so another invoice may spend part of it.
    GnuCash applies what it needs and carves the rest into a new split, and in
    doing so copies the source split's whole slot frame onto the splits it
    makes: the remainder arrives carrying a mark that describes a split it
    merely came from.

    Measured on GnuCash 5.10, 4.13, 4.4, 3.8 and 5.15, the two halves come out
    differently. The carved remainder gets an empty slot frame — no mark, and
    no basis either. The *applied* part keeps the source split's guid and its
    slots, so it arrives still marked as the first invoice's orphan, though
    it is now the second invoice's settlement.

    Left there, the mark describes a split that no longer matches it — the
    thing every stored key in this area is corrected for — and the first
    invoice's rebuild would be reading state about a settlement that has
    since been spent on somebody else's invoice.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    _import_new(runner, book, 'tests/fixtures/fx_usd_overpayment_retargeted_setup.txt',
                '--fx-rates', RATES)

    bank = tmp_path / 'bank.txt'
    bank.write_text(
        Path('tests/fixtures/fx_usd_exact_settlement_bank.txt').read_text())
    assert runner.invoke(cli, ['import', str(book), str(bank),
                               '--fx-rates', RATES]).exit_code == 0

    from repositories.gnucash_repository import GnuCashRepository, SessionMode
    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        from gnucash import Query, Transaction
        query = Query()
        query.search_for('Trans')
        query.set_book(repo.book)
        txn_guid = None
        for raw in query.run():
            transaction = Transaction(instance=raw)
            for split in transaction.GetSplitList():
                if str(split.GetAmount()) == '10000/100':
                    txn_guid = transaction.GetGUID().to_string()
        query.destroy()
    finally:
        repo.close()
    assert txn_guid is not None

    attach = tmp_path / 'attach.txt'
    attach.write_text(
        Path('tests/fixtures/fx_usd_invoice_settled_exactly_by_retarget.txt')
        .read_text().replace('TXN_GUID', txn_guid))
    assert runner.invoke(cli, ['import', str(book), str(attach),
                               '--include-business-objects', '--fx-rates',
                               RATES]).exit_code == 0
    assert runner.invoke(cli, ['unpost-invoices', str(book),
                               'INV-USD-RETARGET']).exit_code == 0

    # A second, smaller invoice spends part of what is now loose credit.
    small = tmp_path / 'small.txt'
    small.write_text(
        Path('tests/fixtures/fx_usd_small_invoice_taking_any_credit.txt').read_text())
    spent = runner.invoke(cli, ['import', str(book), str(small),
                                '--include-business-objects', '--fx-rates', RATES])
    assert spent.exit_code == 0, spent.output

    exported = _export_text(runner, book, tmp_path / 'carved.txt')

    # The 40.00 that was applied is INV-USD-SMALL's settlement now, and no
    # longer anything of the invoice it was orphaned from. It keeps the
    # source split's guid and its slots across the engine's rebuild, so the
    # mark arrives on it and has to be taken off — measured on GnuCash 5.10,
    # 4.13, 4.4, 3.8 and 5.15, it is there without that.
    applied_guid = _split_guid(
        exported, 'Assets:Accounts Receivable USD -40.00 USD')
    assert 'orphaned_by_unpost' not in _split_kvp(book, applied_guid), \
        _split_kvp(book, applied_guid)

    # And it is not a credit applied. A bank paid that 40.00; the engine only
    # moved it. Stamped otherwise, the invoice it settled exports as
    # `from_credit:` with no account and no date — the money's origin gone,
    # which is what the mark is for. The reading that decides this happens
    # after the basis rewrite above, so the rewrite has to leave the mark in
    # place for it to read.
    assert 'applied_from_credit' not in _split_kvp(book, applied_guid), \
        _split_kvp(book, applied_guid)
    small_block = exported.split('invoice "INV-USD-SMALL"')[1]
    assert 'from_credit' not in small_block, small_block
    assert 'Assets:Bank:USD' in small_block, small_block

    # The 60.00 left over is what the 100.00 was: money a bank paid, still
    # waiting to be put back. Spending part of it elsewhere does not turn the
    # rest into the customer's credit, so the mark goes forward onto it — the
    # engine gives a carved remainder an empty slot frame on every supported
    # version, so nothing arrives on it by itself.
    #
    # Unmarked, that 60.00 passed every test a credit passes: listed by
    # `find-prepayments`, spendable by a `from_credit:` block, and exported as
    # a credit applied with no account and no date.
    remainder_guid = _split_guid(
        exported, 'Assets:Accounts Receivable USD -60.00 USD')
    assert 'orphaned_by_unpost' in _split_kvp(book, remainder_guid), \
        _split_kvp(book, remainder_guid)
    # And no basis was invented for it on the way: a bank-paid orphan carries
    # none, the invoice's posting split holds it.
    assert 'cost_basis_balance' not in _split_kvp(book, remainder_guid), \
        _split_kvp(book, remainder_guid)

    listed = runner.invoke(cli, ['find-prepayments', str(book)])
    assert listed.exit_code == 0, listed.output
    assert '60.00' not in listed.output, listed.output

    # So the first invoice, rebuilt from its own file, has nothing of its own
    # left to take — and says so. What is on that transaction now is the
    # customer's remaining 60.00, which is not the 100.00 the file states a
    # bank paid; taking it would settle this invoice 40.00 short and export as
    # a credit spent, out of a file that plainly describes a bank payment.
    again = runner.invoke(cli, ['import', str(book), str(attach),
                                '--include-business-objects', '--fx-rates', RATES])
    assert again.exit_code != 0, again.output
    assert 'would leave the invoice part-paid' in again.output, again.output
    assert '60.00' in again.output, again.output

    # Refused, so the book is as it was: the invoice unposted, and what is
    # left of its settlement still marked as the bank's money rather than
    # anybody's credit.
    after = _export_text(runner, book, tmp_path / 'after.txt')
    block = after.split('invoice "INV-USD-RETARGET"')[1]
    assert 'posted: none' in block, block
    assert 'orphaned_by_unpost' in _split_kvp(book, remainder_guid), \
        _split_kvp(book, remainder_guid)
    assert runner.invoke(cli, ['fx-balances', str(book),
                               '--verify-costs']).exit_code == 0


def test_dividing_a_bank_paid_orphan_leaves_the_rest_a_bank_payment(tmp_path):
    """The tool's own division has to answer as the engine's carve does.

    An invoice takes 40.00 of a 100.00 settlement an unpost left loose and
    declares the 60.00 it leaves. That 60.00 is what the 100.00 was — money a
    bank paid, waiting to be put back — so the mark goes forward onto it, and
    no basis opens: the basis of the invoice that deposit settled is on that
    invoice's posting split, and pricing the residue at this invoice's rate
    reports a gain the customer's money never made.

    The predicate has to be read *before* the division, which is what makes
    this worth a test of its own: dividing puts the source split into the
    invoice's lot, and being in a lot is exactly what stops it being an
    orphan, so asking afterwards always answers no.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    _import_new(runner, book, 'tests/fixtures/fx_usd_overpayment_retargeted_setup.txt',
                '--fx-rates', RATES)

    bank = tmp_path / 'bank.txt'
    bank.write_text(
        Path('tests/fixtures/fx_usd_exact_settlement_bank.txt').read_text())
    assert runner.invoke(cli, ['import', str(book), str(bank),
                               '--fx-rates', RATES]).exit_code == 0

    from repositories.gnucash_repository import GnuCashRepository, SessionMode
    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        from gnucash import Query, Transaction
        query = Query()
        query.search_for('Trans')
        query.set_book(repo.book)
        txn_guid = None
        for raw in query.run():
            transaction = Transaction(instance=raw)
            for split in transaction.GetSplitList():
                if str(split.GetAmount()) == '10000/100':
                    txn_guid = transaction.GetGUID().to_string()
        query.destroy()
    finally:
        repo.close()
    assert txn_guid is not None

    attach = tmp_path / 'attach.txt'
    attach.write_text(
        Path('tests/fixtures/fx_usd_invoice_settled_exactly_by_retarget.txt')
        .read_text().replace('TXN_GUID', txn_guid))
    assert runner.invoke(cli, ['import', str(book), str(attach),
                               '--include-business-objects', '--fx-rates',
                               RATES]).exit_code == 0
    assert runner.invoke(cli, ['unpost-invoices', str(book),
                               'INV-USD-RETARGET']).exit_code == 0

    smaller = tmp_path / 'smaller.txt'
    smaller.write_text(
        Path('tests/fixtures/fx_smaller_invoice_dividing_an_orphan.txt')
        .read_text().replace('TXN_GUID', txn_guid))
    divided = runner.invoke(cli, ['import', str(book), str(smaller),
                                  '--include-business-objects', '--fx-rates', RATES])
    assert divided.exit_code == 0, divided.output

    exported = _export_text(runner, book, tmp_path / 'out.txt')
    residue_guid = _split_guid(
        exported, 'Assets:Accounts Receivable USD -60.00 USD')
    assert 'orphaned_by_unpost' in _split_kvp(book, residue_guid), \
        _split_kvp(book, residue_guid)
    assert 'cost_basis_balance' not in _split_kvp(book, residue_guid), \
        _split_kvp(book, residue_guid)

    # So nothing offers it as the customer's money to spend.
    assert 'open_prepayment:' not in exported, exported
    listed = runner.invoke(cli, ['find-prepayments', str(book)])
    assert listed.exit_code == 0, listed.output
    assert '60.00' not in listed.output, listed.output
    assert runner.invoke(cli, ['fx-balances', str(book),
                               '--verify-costs']).exit_code == 0

    # And restoring that export into a fresh book does not offer it either.
    # The undivided orphan is kept loose by omitting `lot_owner:`; a divided
    # one leaves a residue the settling invoice's own `prepayment:` figure
    # would have parked in a fresh owner lot on the way back in — an ordinary,
    # unmarked credit, spendable, which is the harm the omission is for.
    restored = tmp_path / 'restored.gnucash'
    assert runner.invoke(cli, ['import', '--new', str(restored), str(
        tmp_path / 'out.txt'), '--include-business-objects',
        '--fx-rates', RATES]).exit_code == 0
    back = runner.invoke(cli, ['find-prepayments', str(restored)])
    assert back.exit_code == 0, back.output
    assert '60.00' not in back.output, back.output


def test_an_orphans_figure_is_reported_in_its_own_currency(tmp_path):
    """A split's amount is in its account's commodity, not its transaction's.

    They agree on an ordinary payment and part company on a foreign invoice
    settled from a base-currency bank: 137.00 CAD out of the bank closing
    100.00 USD of receivable, on a transaction whose currency is CAD. Reporting
    the receivable's figure under the transaction's currency called 100.00 USD
    "100.00 CAD" — the wrong money, at the wrong number of decimals.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    _import_new(runner, book, 'tests/fixtures/fx_usd_invoice_paid_from_a_cad_bank.txt',
                '--fx-rates', RATES)

    bank = tmp_path / 'bank.txt'
    bank.write_text(
        Path('tests/fixtures/fx_cad_bank_settling_a_usd_receivable.txt').read_text())
    assert runner.invoke(cli, ['import', str(book), str(bank),
                               '--fx-rates', RATES]).exit_code == 0

    from repositories.gnucash_repository import GnuCashRepository, SessionMode
    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        from gnucash import Query, Transaction
        query = Query()
        query.search_for('Trans')
        query.set_book(repo.book)
        txn_guid = None
        for raw in query.run():
            transaction = Transaction(instance=raw)
            if transaction.GetDescription().startswith('FX Customer'):
                txn_guid = transaction.GetGUID().to_string()
        query.destroy()
    finally:
        repo.close()
    assert txn_guid is not None

    attach = tmp_path / 'attach.txt'
    attach.write_text(
        Path('tests/fixtures/fx_usd_invoice_settled_from_the_cad_bank.txt')
        .read_text().replace('TXN_GUID', txn_guid))
    assert runner.invoke(cli, ['import', str(book), str(attach),
                               '--include-business-objects', '--fx-rates',
                               RATES]).exit_code == 0
    assert runner.invoke(cli, ['unpost-invoices', str(book),
                               'INV-FX-CAD-BANK']).exit_code == 0

    orphans = runner.invoke(cli, ['find-orphan-payments', str(book)])
    assert orphans.exit_code == 0, orphans.output
    assert 'USD 100.00' in orphans.output, orphans.output
    assert 'CAD 100.00' not in orphans.output, orphans.output
    # And named against the account that money is in. `Assets:Bank` is CAD and
    # never held a dollar of it, so it is where the payment came *through*.
    assert 'Assets:Bank  USD' not in orphans.output, orphans.output
    assert 'paid through: Assets:Bank' in orphans.output, orphans.output
    assert 'Total: USD 100.00 in Assets:Accounts Receivable USD' in \
        orphans.output, orphans.output


def test_a_foreign_credit_is_listed_in_its_own_currency(tmp_path):
    """The credit listing labels by account too, and the check goes quiet.

    Overpaying a 100.00 USD invoice out of a CAD bank parks a 100.00 USD
    residue on the USD receivable, under a CAD transaction. Labelled with the
    transaction's currency it read "CAD 100.00", and the per-owner totals then
    added that customer's USD credit to their real CAD ones.

    The retargeted split here is the −200.00 *USD* receivable side — 274.00 is
    its value, not its amount — so both figures the fall-short check compares
    are USD and it runs normally. The mixed-currency silence it can also take
    is pinned directly in `test_what_a_payment_can_take.py`, there being no
    file that reaches it: the shape needs a bank-feed transaction whose other
    side is in neither the invoice's currency nor the bank's.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    _import_new(runner, book, 'tests/fixtures/fx_usd_invoice_paid_from_a_cad_bank.txt',
                '--fx-rates', RATES)

    bank = tmp_path / 'bank.txt'
    bank.write_text(
        Path('tests/fixtures/fx_cad_bank_overpaying_a_usd_receivable.txt').read_text())
    assert runner.invoke(cli, ['import', str(book), str(bank),
                               '--fx-rates', RATES]).exit_code == 0

    from repositories.gnucash_repository import GnuCashRepository, SessionMode
    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        from gnucash import Query, Transaction
        query = Query()
        query.search_for('Trans')
        query.set_book(repo.book)
        txn_guid = None
        for raw in query.run():
            transaction = Transaction(instance=raw)
            if transaction.GetDescription().startswith('FX Customer'):
                txn_guid = transaction.GetGUID().to_string()
        query.destroy()
    finally:
        repo.close()
    assert txn_guid is not None

    attach = tmp_path / 'attach.txt'
    attach.write_text(
        Path('tests/fixtures/fx_usd_invoice_overpaid_from_the_cad_bank.txt')
        .read_text().replace('TXN_GUID', txn_guid))
    overpaid = runner.invoke(cli, ['import', str(book), str(attach),
                                   '--include-business-objects', '--fx-rates', RATES])
    assert overpaid.exit_code == 0, overpaid.output

    listed = runner.invoke(cli, ['find-prepayments', str(book)])
    assert listed.exit_code == 0, listed.output
    assert 'USD 100.00' in listed.output, listed.output
    assert 'CAD 100.00' not in listed.output, listed.output


def test_another_invoices_orphan_is_still_a_bank_payment(tmp_path):
    """Whose orphan it is does not make it credit; how it was paid does.

    `unpost-invoices` leaves an invoice unposted and present, with its bank
    settlement loose in a lot of the customer's — and a *different* invoice for
    that customer can name the same deposit with an ordinary bank block. The
    mark on that split names the other invoice, so nothing about it is this
    invoice's own orphan.

    What settles it is the fact the split carries: a bank paid that money and
    it never came out of credit. Read as a credit because it sits in an
    owner's lot, the basis comes off currency the bank still holds and a block
    that named an account and a date exports back as `from_credit:` carrying
    neither.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    _import_new(runner, book, 'tests/fixtures/fx_usd_overpayment_retargeted_setup.txt',
                '--fx-rates', RATES)

    bank = tmp_path / 'bank.txt'
    bank.write_text(
        Path('tests/fixtures/fx_usd_exact_settlement_bank.txt').read_text())
    assert runner.invoke(cli, ['import', str(book), str(bank),
                               '--fx-rates', RATES]).exit_code == 0

    from repositories.gnucash_repository import GnuCashRepository, SessionMode
    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        from gnucash import Query, Transaction
        query = Query()
        query.search_for('Trans')
        query.set_book(repo.book)
        txn_guid = None
        for raw in query.run():
            transaction = Transaction(instance=raw)
            for split in transaction.GetSplitList():
                if str(split.GetAmount()) == '10000/100':
                    txn_guid = transaction.GetGUID().to_string()
        query.destroy()
    finally:
        repo.close()
    assert txn_guid is not None

    attach = tmp_path / 'attach.txt'
    attach.write_text(
        Path('tests/fixtures/fx_usd_invoice_settled_exactly_by_retarget.txt')
        .read_text().replace('TXN_GUID', txn_guid))
    assert runner.invoke(cli, ['import', str(book), str(attach),
                               '--include-business-objects', '--fx-rates',
                               RATES]).exit_code == 0
    assert runner.invoke(cli, ['unpost-invoices', str(book),
                               'INV-USD-RETARGET']).exit_code == 0

    other = tmp_path / 'other.txt'
    other.write_text(
        Path('tests/fixtures/fx_usd_second_invoice_taking_another_orphan.txt')
        .read_text().replace('TXN_GUID', txn_guid))
    taken = runner.invoke(cli, ['import', str(book), str(other),
                                '--include-business-objects', '--fx-rates', RATES])
    assert taken.exit_code == 0, taken.output

    # Still the bank payment the file described, with the account and date it
    # named — and the currency it brought in still costed.
    exported = _export_text(runner, book, tmp_path / 'out.txt')
    block = exported.split('invoice "INV-USD-OTHER"')[1]
    assert 'from_credit' not in block, block
    assert 'Assets:Bank:USD' in block, block
    assert '2026-02-25' in block, block
    assert 'Total USD basis balance: 100.00 USD' in _balances(runner, book), \
        _balances(runner, book)
    assert runner.invoke(cli, ['fx-balances', str(book),
                               '--verify-costs']).exit_code == 0


def test_another_invoices_orphan_is_not_credit_to_the_other_spellings(tmp_path):
    """The same answer whichever of the three ways reaches the split.

    A bank-paid orphan is a settlement waiting to be put back, and that does
    not change because a *different* invoice is the one asking. The bank
    spelling is covered above; these are the two that ask for credit by name —
    a `from_credit:` block, and `auto_apply_credit:` where the engine chooses.
    Both search out exactly what an unpost leaves: a live, naming nothing lot
    with the owner still on it.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    _import_new(runner, book, 'tests/fixtures/fx_usd_overpayment_retargeted_setup.txt',
                '--fx-rates', RATES)

    bank = tmp_path / 'bank.txt'
    bank.write_text(
        Path('tests/fixtures/fx_usd_exact_settlement_bank.txt').read_text())
    assert runner.invoke(cli, ['import', str(book), str(bank),
                               '--fx-rates', RATES]).exit_code == 0

    from repositories.gnucash_repository import GnuCashRepository, SessionMode
    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        from gnucash import Query, Transaction
        query = Query()
        query.search_for('Trans')
        query.set_book(repo.book)
        txn_guid = None
        for raw in query.run():
            transaction = Transaction(instance=raw)
            for split in transaction.GetSplitList():
                if str(split.GetAmount()) == '10000/100':
                    txn_guid = transaction.GetGUID().to_string()
        query.destroy()
    finally:
        repo.close()
    assert txn_guid is not None

    attach = tmp_path / 'attach.txt'
    attach.write_text(
        Path('tests/fixtures/fx_usd_invoice_settled_exactly_by_retarget.txt')
        .read_text().replace('TXN_GUID', txn_guid))
    assert runner.invoke(cli, ['import', str(book), str(attach),
                               '--include-business-objects', '--fx-rates',
                               RATES]).exit_code == 0
    assert runner.invoke(cli, ['unpost-invoices', str(book),
                               'INV-USD-RETARGET']).exit_code == 0

    orphan_guid = _split_guid(
        _export_text(runner, book, tmp_path / 'mid.txt'),
        'Assets:Accounts Receivable USD -100.00 USD')

    # Named outright as a credit by an invoice that never owned it.
    as_credit = tmp_path / 'as_credit.txt'
    as_credit.write_text(
        Path('tests/fixtures/fx_usd_other_invoice_calling_an_orphan_a_credit.txt')
        .read_text().replace('TXN_GUID', txn_guid)
        .replace('SPLIT_GUID', orphan_guid))
    refused = runner.invoke(cli, ['import', str(book), str(as_credit),
                                  '--include-business-objects', '--fx-rates', RATES])
    assert refused.exit_code != 0, refused.output
    assert 'a settlement a bank paid' in refused.output, refused.output

    # And reached by the engine rather than by name. It may well take the
    # split; what it must not do is call it a credit spent.
    grabber = tmp_path / 'grabber.txt'
    grabber.write_text(
        Path('tests/fixtures/fx_usd_other_invoice_asking_for_any_credit.txt')
        .read_text())
    grabbed = runner.invoke(cli, ['import', str(book), str(grabber),
                                  '--include-business-objects', '--fx-rates', RATES])
    assert grabbed.exit_code == 0, grabbed.output

    exported = _export_text(runner, book, tmp_path / 'out.txt')
    grabber_block = exported.split('invoice "INV-USD-GRABBER"')[1]
    assert 'from_credit' not in grabber_block, grabber_block
    assert 'orphaned_by_unpost' not in _split_kvp(book, orphan_guid), \
        _split_kvp(book, orphan_guid)
    assert runner.invoke(cli, ['fx-balances', str(book),
                               '--verify-costs']).exit_code == 0


def test_an_unposted_bills_orphan_is_not_read_as_a_vendor_credit(tmp_path):
    """The payable side of the same inference, where the signs invert.

    A bill credits its payable and the payment debits it — the mirror of the
    receivable, and the side where a wrong sign is invisible in the figures:
    the invoice reads settled and the money reappears somewhere else
    (CLAUDE.md finding 7). This path both writes and strips a cost basis, so
    an error here is the quiet kind.

    Read as the vendor's credit, the rebuild would take the basis off currency
    the book actually paid out, and the export would call a bank payment a
    credit applied.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    _import_new(runner, book,
                'tests/fixtures/fx_usd_bill_settled_exactly_by_retarget_setup.txt',
                '--fx-rates', RATES)

    bank = tmp_path / 'bank.txt'
    bank.write_text(
        Path('tests/fixtures/fx_usd_bill_exact_settlement_bank.txt').read_text())
    assert runner.invoke(cli, ['import', str(book), str(bank),
                               '--fx-rates', RATES]).exit_code == 0

    from repositories.gnucash_repository import GnuCashRepository, SessionMode
    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        from gnucash import Query, Transaction
        query = Query()
        query.search_for('Trans')
        query.set_book(repo.book)
        txn_guid = None
        for raw in query.run():
            transaction = Transaction(instance=raw)
            for split in transaction.GetSplitList():
                if str(split.GetAmount()) == '-10000/100':
                    txn_guid = transaction.GetGUID().to_string()
        query.destroy()
    finally:
        repo.close()
    assert txn_guid is not None

    attach = tmp_path / 'attach.txt'
    attach.write_text(
        Path('tests/fixtures/fx_usd_bill_settled_exactly_by_retarget.txt')
        .read_text().replace('TXN_GUID', txn_guid))
    assert runner.invoke(cli, ['import', str(book), str(attach),
                               '--include-business-objects', '--fx-rates',
                               RATES]).exit_code == 0
    settled = _export_text(runner, book, tmp_path / 'settled.txt')
    assert 'payment: none' not in settled.split('bill "BILL-USD-RETARGET"')[1], \
        settled

    unposted = runner.invoke(cli, ['unpost-bills', str(book),
                                   'BILL-USD-RETARGET'])
    assert unposted.exit_code == 0, unposted.output
    assert 'orphaned_by_unpost' not in _export_text(
        runner, book, tmp_path / 'mid.txt')

    # The payable side is listed too, by the vendor its lot names — the row
    # selection and the lot-owner reading are the same code both ways round,
    # and this is the side where a sign or an owner going astray is silent.
    orphans = runner.invoke(cli, ['find-orphan-payments', str(book)])
    assert orphans.exit_code == 0, orphans.output
    assert '100.00' in orphans.output, orphans.output
    assert 'V-US' in orphans.output, orphans.output
    assert 'vendor' in orphans.output, orphans.output
    filtered = runner.invoke(cli, ['find-orphan-payments', str(book),
                                   '--vendor', 'V-US'])
    assert filtered.exit_code == 0, filtered.output
    assert '100.00' in filtered.output, filtered.output

    again = runner.invoke(cli, ['import', str(book), str(attach),
                                '--include-business-objects', '--fx-rates', RATES])
    assert again.exit_code == 0, again.output

    # Settled again, by the bank — and the payable split still debits it, which
    # is what says the money went out rather than a vendor credit going down.
    exported = _export_text(runner, book, tmp_path / 'out.txt')
    block = exported.split('bill "BILL-USD-RETARGET"')[1]
    assert 'payment: none' not in block, block
    assert 'from_credit' not in block, block
    assert 'Assets:Bank:USD' in block, block
    assert 'orphaned_by_unpost' not in exported, exported
    assert 'Liabilities:Accounts Payable USD 100.00 USD' in exported, exported


def test_a_bill_spending_a_parked_vendor_claim_records_it_as_credit(tmp_path):
    """The payable mirror of a bare `txn_guid:` reaching an owner's credit.

    Overpaying a vendor leaves money the vendor holds and the book is owed
    back, parked in a lot of the vendor's. A later bill naming that
    transaction and nothing else spends it, and that is a credit being spent
    however the file spells it: the basis comes off the currency, and the
    export says where the money came from.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    _import_new(runner, book,
                'tests/fixtures/fx_usd_bill_settled_exactly_by_retarget_setup.txt',
                '--fx-rates', RATES)

    bank = tmp_path / 'bank.txt'
    bank.write_text(
        Path('tests/fixtures/fx_usd_bill_overpaid_bank.txt').read_text())
    assert runner.invoke(cli, ['import', str(book), str(bank),
                               '--fx-rates', RATES]).exit_code == 0

    from repositories.gnucash_repository import GnuCashRepository, SessionMode
    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        from gnucash import Query, Transaction
        query = Query()
        query.search_for('Trans')
        query.set_book(repo.book)
        txn_guid = None
        for raw in query.run():
            transaction = Transaction(instance=raw)
            for split in transaction.GetSplitList():
                if str(split.GetAmount()) == '-20000/100':
                    txn_guid = transaction.GetGUID().to_string()
        query.destroy()
    finally:
        repo.close()
    assert txn_guid is not None

    attach = tmp_path / 'attach.txt'
    attach.write_text(
        Path('tests/fixtures/fx_usd_bill_overpaid_by_retarget.txt')
        .read_text().replace('TXN_GUID', txn_guid))
    assert runner.invoke(cli, ['import', str(book), str(attach),
                               '--include-business-objects', '--fx-rates',
                               RATES]).exit_code == 0

    second = tmp_path / 'second.txt'
    second.write_text(
        Path('tests/fixtures/second_usd_bill_takes_the_parked_credit.txt')
        .read_text().replace('TXN_GUID', txn_guid))
    spent = runner.invoke(cli, ['import', str(book), str(second),
                                '--include-business-objects', '--fx-rates', RATES])
    assert spent.exit_code == 0, spent.output

    exported = _export_text(runner, book, tmp_path / 'out.txt')
    block = exported.split('bill "BILL-USD-SECOND"')[1]
    assert 'from_credit: #True' in block, block
    assert 'bank_account:' not in block.split('payment:')[1], block

    # The claim was spent, so it is no longer currency the book is owed, and
    # `--verify-costs` agrees the bases left match what the book holds.
    assert '2026-02-25' not in _balances(runner, book), _balances(runner, book)
    assert runner.invoke(cli, ['fx-balances', str(book),
                               '--verify-costs']).exit_code == 0
