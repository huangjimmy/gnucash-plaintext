"""Applying a foreign credit moves its cost basis onto what is left of it.

Applying a customer's credit to an invoice does not set the credit aside:
GnuCash reduces the split it comes from to the part being applied and carves
the remainder into a new split in the same transaction. A 100.00 USD credit
meeting a 40.00 USD invoice becomes a 40.00 split and a 60.00 one.

The basis has to follow the 60.00 — that is what the customer still holds, and
what the book still owes — while the 40.00 has become a settlement and holds
nothing.
"""

from pathlib import Path

from click.testing import CliRunner

from cli.main import cli

RATES = 'tests/fixtures/fx_rates_usd_dated.yaml'

SECOND_INVOICE = (
    'invoice "INV-USD-SECOND"\n'
    '\tcustomer_id: "C-US"\n'
    '\tcurrency: USD\n'
    '\tdate_opened: 2026-03-01\n'
    '\tauto_apply_credit: true\n'
    '\tentry:\n'
    '\t\tdate: 2026-03-01\n'
    '\t\tdescription: "More consulting"\n'
    '\t\taction: "Hours"\n'
    '\t\taccount: "Income:Sales"\n'
    '\t\tquantity: 1\n'
    '\t\tprice: 40\n'
    '\t\ttaxable: false\n'
    '\t\ttax_included: false\n'
    '\tposted:\n'
    '\t\tdate: 2026-03-01\n'
    '\t\tdue: 2026-04-01\n'
    '\t\tar_account: "Assets:Accounts Receivable USD"\n'
    '\t\tmemo: "Invoice INV-USD-SECOND"\n'
    '\t\taccumulate: true\n')


SECOND_BILL = (
    'bill "BILL-USD-SECOND"\n'
    '\tvendor_id: "V-US"\n'
    '\tcurrency: USD\n'
    '\tdate_opened: 2026-03-01\n'
    '\tauto_apply_credit: true\n'
    '\tentry:\n'
    '\t\tdate: 2026-03-01\n'
    '\t\tdescription: "More parts"\n'
    '\t\taction: "Material"\n'
    '\t\taccount: "Expenses:Supplies"\n'
    '\t\tquantity: 1\n'
    '\t\tprice: 40\n'
    '\t\ttaxable: false\n'
    '\t\ttax_included: false\n'
    '\tposted:\n'
    '\t\tdate: 2026-03-01\n'
    '\t\tdue: 2026-04-01\n'
    '\t\tap_account: "Liabilities:Accounts Payable USD"\n'
    '\t\tmemo: "Bill BILL-USD-SECOND"\n'
    '\t\taccumulate: true\n')


def _overpaid_book(runner, tmp_path):
    """A 100.00 USD invoice paid with 200.00, leaving 100.00 of credit."""
    book = tmp_path / 'book.gnucash'
    result = runner.invoke(cli, [
        'import', '--new', str(book),
        'tests/fixtures/fx_invoice_usd_overpaid_into_usd_bank.txt',
        '--include-business-objects', '--fx-rates', RATES])
    assert result.exit_code == 0, result.output
    return book


def test_the_remaining_credit_keeps_the_cost_it_was_acquired_at(tmp_path):
    """60.00 USD of credit is left, and it is still worth 1.4 CAD/USD.

    Left where they were, the keys stayed on the part that was applied: the
    40.00 settling the new invoice went on claiming 100.00 available — a
    balance for currency it no longer carries, one unapply away from being
    read — while the 60.00 the customer still has became a prepayment with no
    cost at all, listed nowhere and sellable not at all.
    """
    runner = CliRunner()
    book = _overpaid_book(runner, tmp_path)

    second = tmp_path / 'second.txt'
    second.write_text(SECOND_INVOICE)
    result = runner.invoke(cli, ['import', str(book), str(second),
                                 '--include-business-objects', '--fx-rates', RATES])
    assert result.exit_code == 0, result.output

    exported = tmp_path / 'out.txt'
    assert runner.invoke(cli, ['export', str(book), str(exported),
                               '--include-business-objects']).exit_code == 0
    text = exported.read_text()

    # The applied part carries no basis figures at all.
    applied = text.split('Assets:Accounts Receivable USD -40.00 USD')[1]
    applied = applied.split('\n\tAssets')[0]
    assert 'cost_basis_available' not in applied, applied
    assert 'cost_basis_cost' not in applied, applied

    # What is left of the credit carries them, at its own size.
    remainder = text.split('Assets:Accounts Receivable USD -60.00 USD')[1]
    remainder = remainder.split('\n\tAssets')[0]
    assert 'cost_basis_available: "60.00"' in remainder, remainder
    assert 'cost_basis_cost: "1.4 CAD/USD"' in remainder, remainder

    # And the listing follows: the first invoice's 100.00, the second's 40.00,
    # and 60.00 of credit still owed — nothing offering more than it holds.
    listing = runner.invoke(cli, ['fx-balances', str(book)]).output
    assert 'Available USD: 200.00' in listing, listing
    assert '60.00 USD' in listing, listing
    checked = runner.invoke(cli, ['fx-balances', str(book), '--verify-costs'])
    assert checked.exit_code == 0, checked.output


def test_what_is_left_of_the_credit_comes_back_with_its_cost(tmp_path):
    """The carved basis survives a rebuild, not just an export.

    Which split is the applied part and which the remainder is worked out
    from what the credit lost, and the figures are then rewritten across
    splits GnuCash minted seconds earlier. Reading the export back proves the
    book was written correctly; only importing it into an empty book proves
    the file says enough to reconstruct it.
    """
    runner = CliRunner()
    book = _overpaid_book(runner, tmp_path)
    second = tmp_path / 'second.txt'
    second.write_text(SECOND_INVOICE)
    assert runner.invoke(cli, ['import', str(book), str(second),
                               '--include-business-objects',
                               '--fx-rates', RATES]).exit_code == 0

    exported = tmp_path / 'out.txt'
    assert runner.invoke(cli, ['export', str(book), str(exported),
                               '--include-business-objects']).exit_code == 0

    rebuilt = tmp_path / 'rebuilt.gnucash'
    result = runner.invoke(cli, ['import', '--new', str(rebuilt), str(exported),
                                 '--include-business-objects'])
    assert result.exit_code == 0, result.output

    # The same 200.00 across the same three bases, the remaining credit still
    # carrying the cost it was acquired at.
    listing = runner.invoke(cli, ['fx-balances', str(rebuilt)])
    assert listing.exit_code == 0, listing.output
    assert 'Available USD: 200.00' in listing.output, listing.output
    assert '1.4 CAD/USD' in listing.output, listing.output
    assert '60.00 USD' in listing.output, listing.output
    checked = runner.invoke(cli, ['fx-balances', str(rebuilt), '--verify-costs'])
    assert checked.exit_code == 0, checked.output

    # And the rebuilt book says what it was built from, down to the byte.
    again = tmp_path / 'out2.txt'
    assert runner.invoke(cli, ['export', str(rebuilt), str(again),
                               '--include-business-objects']).exit_code == 0
    assert again.read_text() == exported.read_text()


def test_a_credit_spent_to_the_last_cent_keeps_no_basis(tmp_path):
    """Nothing is carved, and the whole of it is spent, so nothing is left.

    A credit consumed in full moves into the document's lot as one split,
    never shrinking. Watching only for a split that got smaller left that one
    still carrying the balance and cost of currency it had just spent — inert
    while it sits in a document's lot, and a stated balance on a settlement
    the moment anything reads the file.
    """
    runner = CliRunner()
    book = _overpaid_book(runner, tmp_path)

    bigger = tmp_path / 'bigger.txt'
    bigger.write_text(SECOND_INVOICE.replace('price: 40', 'price: 250')
                      .replace('INV-USD-SECOND', 'INV-USD-BIGGER'))
    result = runner.invoke(cli, ['import', str(book), str(bigger),
                                 '--include-business-objects', '--fx-rates', RATES])
    assert result.exit_code == 0, result.output

    exported = tmp_path / 'out.txt'
    assert runner.invoke(cli, ['export', str(book), str(exported),
                               '--include-business-objects']).exit_code == 0
    text = exported.read_text()

    # The whole 100.00 credit went into the invoice, and carries nothing.
    spent = text.split('Assets:Accounts Receivable USD -100.00 USD')[1]
    spent = spent.split('\n\tAssets')[0].split('\n\tIncome')[0]
    assert 'cost_basis_available' not in spent, spent
    assert 'cost_basis_cost' not in spent, spent

    # The book now holds the first invoice's 100.00 and the new one's 250.00.
    listing = runner.invoke(cli, ['fx-balances', str(book)])
    assert listing.exit_code == 0, listing.output
    assert 'Available USD: 350.00' in listing.output, listing.output
    checked = runner.invoke(cli, ['fx-balances', str(book), '--verify-costs'])
    assert checked.exit_code == 0, checked.output


def test_the_remainder_is_told_apart_from_a_settlement_of_its_own_size(tmp_path):
    """Size alone does not say which split is what is left of a credit.

    A 250.00 payment against a 100.00 invoice leaves 150.00 of credit beside
    the 100.00 that settled the invoice — in the same transaction. A later
    50.00 invoice carves the credit into 50.00 applied and 100.00 remaining,
    and that remainder is exactly the size of the settlement sitting next to
    it. Picking by size, the settlement can be reached first and handed the
    credit's balance and cost, which nothing then reads: its lot belongs to a
    document, so it is no basis. The customer's real 100.00 is left untracked,
    the book reports 150.00 available against 250.00 held, and selling that
    credit is refused for having no tracked balance.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    result = runner.invoke(cli, [
        'import', '--new', str(book),
        'tests/fixtures/fx_credit_whose_remainder_matches_a_settlement.txt',
        '--include-business-objects', '--fx-rates', RATES])
    assert result.exit_code == 0, result.output

    second = tmp_path / 'second.txt'
    second.write_text(SECOND_INVOICE.replace('price: 40', 'price: 50'))
    result = runner.invoke(cli, ['import', str(book), str(second),
                                 '--include-business-objects', '--fx-rates', RATES])
    assert result.exit_code == 0, result.output

    exported = tmp_path / 'out.txt'
    assert runner.invoke(cli, ['export', str(book), str(exported),
                               '--include-business-objects']).exit_code == 0
    text = exported.read_text()

    # The split that settled the first invoice holds nothing: it is money that
    # has gone, and its lot belongs to a document.
    settlement = text.split('Assets:Accounts Receivable USD -100.00 USD')[1]
    settlement = settlement.split('\n\tAssets')[0].split('\n\tIncome')[0]
    assert 'cost_basis_available' not in settlement, settlement
    assert 'cost_basis_cost' not in settlement, settlement

    # What is left of the credit is 100.00, and it is what carries the basis.
    remainder = text.split('Assets:Accounts Receivable USD -100.00 USD')[2]
    remainder = remainder.split('\n\tAssets')[0].split('\n\tIncome')[0]
    assert 'cost_basis_available: "100.00"' in remainder, remainder
    assert 'cost_basis_cost: "1.4 CAD/USD"' in remainder, remainder

    # 100.00 on the first invoice, 50.00 on the second, 100.00 still owed
    # back — against 250.00 in the bank.
    listing = runner.invoke(cli, ['fx-balances', str(book)])
    assert listing.exit_code == 0, listing.output
    assert 'Available USD: 250.00' in listing.output, listing.output
    checked = runner.invoke(cli, ['fx-balances', str(book), '--verify-costs'])
    assert checked.exit_code == 0, checked.output


def _the_credit_split(book):
    """(transaction guid, split guid) of the customer's −100.00 USD credit."""
    import gnucash.gnucash_core_c as gc
    from gnucash import Query, Transaction

    from repositories.gnucash_repository import GnuCashRepository, SessionMode

    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        query = Query()
        query.search_for('Trans')
        query.set_book(repo.book)
        for raw in query.run():
            transaction = Transaction(instance=raw)
            for split in transaction.GetSplitList():
                account = split.GetAccount()
                if account is None:
                    continue
                if account.get_full_name() != 'Assets.Accounts Receivable USD':
                    continue
                if str(split.GetAmount()) != '-10000/100':
                    continue
                # The credit, not the split that settled the invoice: both
                # are −100.00 on the same day, and what separates them is
                # that a settlement's lot belongs to a document.
                lot = split.GetLot()
                if lot is not None and gc.gncInvoiceGetInvoiceFromLot(lot):
                    continue
                return (transaction.GetGUID().to_string(),
                        split.GetGUID().to_string())
        query.destroy()
    finally:
        repo.close()
    raise AssertionError('no 100.00 USD credit split found')


def _edit_the_credits_basis(book, change):
    """Rewrite the credit split's cost-basis KVP, and save.

    A book can hold a basis this tool would refuse to import — hand-edited in
    the GnuCash GUI, or written by a version that checked less — and how such
    a book is *read* is the thing under test. Both callers below make one the
    only way one can be made: by writing the KVP the importer will not accept.
    """
    from gnucash import Query, Transaction

    from infrastructure.gnucash.kvp import get_custom_metadata, set_custom_metadata
    from repositories.gnucash_repository import GnuCashRepository, SessionMode

    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.NORMAL)
    try:
        query = Query()
        query.search_for('Trans')
        query.set_book(repo.book)
        touched = 0
        for raw in query.run():
            transaction = Transaction(instance=raw)
            for split in transaction.GetSplitList():
                metadata = dict(get_custom_metadata(split))
                if 'cost_basis_available' not in metadata:
                    continue
                if str(split.GetAmount()) != '-10000/100':
                    continue
                transaction.BeginEdit()
                set_custom_metadata(split, change(metadata))
                transaction.CommitEdit()
                touched += 1
        query.destroy()
        assert touched == 1, f'expected one credit basis, touched {touched}'
        repo.save()
    finally:
        repo.close()


def test_a_balance_that_will_not_parse_survives_a_division_as_it_reads(tmp_path):
    """Unreadable is not absent, and a division must not write over it.

    `available_of` answers None for a balance that is missing and for one that
    will not parse alike, so inside a branch that has already found the key,
    None can only mean unparseable. Treated as absent, the largest figure the
    division could produce is written onto a basis nobody can vouch for — and
    the text `--verify-costs` exists to report is destroyed on the way: `20,00`
    for `20.00` comes back as a clean 70.00 available.
    """
    runner = CliRunner()
    book = _overpaid_book(runner, tmp_path)
    _edit_the_credits_basis(
        book, lambda md: {**md, 'cost_basis_available': '20,00'})

    credit_txn, credit_split = _the_credit_split(book)
    second = tmp_path / 'second.txt'
    second.write_text(
        Path('tests/fixtures/fx_invoice_naming_a_part_sold_credit.txt').read_text()
        .replace('TXN_GUID', credit_txn).replace('SPLIT_GUID', credit_split))
    result = runner.invoke(cli, ['import', str(book), str(second),
                                 '--include-business-objects', '--fx-rates', RATES])
    assert result.exit_code == 0, result.output

    exported = tmp_path / 'out.txt'
    assert runner.invoke(cli, ['export', str(book), str(exported),
                               '--include-business-objects']).exit_code == 0
    text = exported.read_text()
    remainder = text.split('Assets:Accounts Receivable USD -70.00 USD')[1]
    remainder = remainder.split('\n\tAssets')[0].split('\n\tIncome')[0]
    assert 'cost_basis_available: "20,00"' in remainder, remainder

    # And the report still names it, which is the whole point of keeping it:
    # the text itself, quoted back, is what tells the reader what to correct.
    checked = runner.invoke(cli, ['fx-balances', str(book), '--verify-costs'])
    assert checked.exit_code == 1, checked.output
    assert "'20,00'   (does not parse)" in checked.output, checked.output
    assert "reads '20,00', which is not a number" in checked.output, checked.output


def test_dividing_an_untracked_credit_leaves_it_untracked(tmp_path):
    """No balance was ever written for it, so a division writes none either.

    A credit carrying a cost but no balance is untracked: nothing recorded
    what has already been sold from it. Reading the residue's own size as its
    balance would open a basis for currency that may be long gone, and every
    later sale would be measured against it.
    """
    runner = CliRunner()
    book = _overpaid_book(runner, tmp_path)
    _edit_the_credits_basis(
        book, lambda md: {key: val for key, val in md.items()
                          if key != 'cost_basis_available'})

    credit_txn, credit_split = _the_credit_split(book)
    second = tmp_path / 'second.txt'
    second.write_text(
        Path('tests/fixtures/fx_invoice_naming_a_part_sold_credit.txt').read_text()
        .replace('TXN_GUID', credit_txn).replace('SPLIT_GUID', credit_split))
    result = runner.invoke(cli, ['import', str(book), str(second),
                                 '--include-business-objects', '--fx-rates', RATES])
    assert result.exit_code == 0, result.output

    exported = tmp_path / 'out.txt'
    assert runner.invoke(cli, ['export', str(book), str(exported),
                               '--include-business-objects']).exit_code == 0
    text = exported.read_text()
    remainder = text.split('Assets:Accounts Receivable USD -70.00 USD')[1]
    remainder = remainder.split('\n\tAssets')[0].split('\n\tIncome')[0]
    assert 'cost_basis_available' not in remainder, remainder
    assert 'cost_basis_cost' in remainder, remainder


def test_dividing_a_credit_gives_back_only_what_was_left(tmp_path):
    """A credit already part-sold does not get its balance back on division.

    100.00 USD of credit with 80.00 of it sold has 20.00 left to sell. A
    30.00 invoice naming that credit divides it, and the 70.00 that remains
    the customer's is still only 20.00 of sellable basis — writing the split's
    new size as its balance would re-open 50.00 USD the book no longer holds,
    and every later sale would be measured against currency that is gone.
    """
    runner = CliRunner()
    book = _overpaid_book(runner, tmp_path)

    # Sell 80.00 of the credit's 100.00.
    listing = runner.invoke(cli, ['fx-balances', str(book)]).output
    credit_guid = next(
        line.split()[1] for line in listing.splitlines()
        if 'Accounts Receivable USD' in line and '2026-02-25' in line)
    sale = tmp_path / 'sale.txt'
    sale.write_text(
        Path('tests/fixtures/fx_sell_part_of_a_credit.txt').read_text()
        .replace('{basis}', credit_guid))
    result = runner.invoke(cli, ['import', str(book), str(sale),
                                 '--fx-rates', RATES])
    assert result.exit_code == 0, result.output

    # Name that credit in a block on a 30.00 USD invoice: the credit is
    # bigger, so the block divides it rather than attaching it whole.
    credit_txn, credit_split = _the_credit_split(book)
    second = tmp_path / 'second.txt'
    second.write_text(
        Path('tests/fixtures/fx_invoice_naming_a_part_sold_credit.txt').read_text()
        .replace('TXN_GUID', credit_txn).replace('SPLIT_GUID', credit_split))
    result = runner.invoke(cli, ['import', str(book), str(second),
                                 '--include-business-objects', '--fx-rates', RATES])
    assert result.exit_code == 0, result.output

    exported = tmp_path / 'out.txt'
    assert runner.invoke(cli, ['export', str(book), str(exported),
                               '--include-business-objects']).exit_code == 0
    text = exported.read_text()
    remainder = text.split('Assets:Accounts Receivable USD -70.00 USD')[1]
    remainder = remainder.split('\n\tAssets')[0].split('\n\tIncome')[0]
    assert 'cost_basis_available: "20.00"' in remainder, remainder

    checked = runner.invoke(cli, ['fx-balances', str(book), '--verify-costs'])
    assert checked.exit_code == 0, checked.output


def test_dividing_a_credit_valued_in_another_currency_balances(tmp_path):
    """A credit of 100.00 USD worth 137.00 CAD, divided 40/60.

    Where the transaction is in the book's currency and the split in another,
    a split's value is not its amount: the value has to follow the same
    proportion as the amount, and what is left has to be exactly what the
    subtraction leaves. A cent adrift and the transaction no longer balances,
    which GnuCash answers by growing an Imbalance split — silently, since
    nothing about a cost basis looks at values.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    result = runner.invoke(cli, [
        'import', '--new', str(book),
        'tests/fixtures/fx_invoice_usd_overpaid_into_cad_bank.txt',
        '--include-business-objects', '--fx-rates', RATES])
    assert result.exit_code == 0, result.output

    credit_txn, credit_split = _the_credit_split(book)
    second = tmp_path / 'second.txt'
    second.write_text(
        Path('tests/fixtures/fx_invoice_naming_a_credit_valued_in_cad.txt').read_text()
        .replace('TXN_GUID', credit_txn).replace('SPLIT_GUID', credit_split))
    result = runner.invoke(cli, ['import', str(book), str(second),
                                 '--include-business-objects', '--fx-rates', RATES])
    assert result.exit_code == 0, result.output

    exported = tmp_path / 'out.txt'
    assert runner.invoke(cli, ['export', str(book), str(exported)]).exit_code == 0
    text = exported.read_text()

    # 100.00 USD was worth 137.00 CAD, so 40.00 of it is worth 54.80 and the
    # 60.00 left is worth the 82.20 that remains — not 60.00.
    spent = text.split('Assets:Accounts Receivable USD -40.00 USD')[1]
    spent = spent.split('\n\tAssets')[0].split('\n\tIncome')[0]
    assert 'value: "-54.80"' in spent, spent
    remainder = text.split('Assets:Accounts Receivable USD -60.00 USD')[1]
    remainder = remainder.split('\n\tAssets')[0].split('\n\tIncome')[0]
    assert 'value: "-82.20"' in remainder, remainder

    # And the transaction still balances: nothing was created or lost in the
    # division, so GnuCash has no imbalance to record.
    assert 'Imbalance' not in text, text
    checked = runner.invoke(cli, ['fx-balances', str(book), '--verify-costs'])
    assert checked.exit_code == 0, checked.output


def test_a_vendor_credit_keeps_its_cost_the_same_way(tmp_path):
    """The payable side is the mirror: 60.00 USD of claim left, still at 1.4.

    What the book overpaid a vendor is its own currency sitting with them, and
    spending 40.00 of it on a later bill leaves 60.00 that is still the book's
    — at what it cost to send, not at a rate for the day the bill arrived.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    result = runner.invoke(cli, [
        'import', '--new', str(book),
        'tests/fixtures/fx_bill_usd_overpaid_from_usd_bank.txt',
        '--include-business-objects', '--fx-rates', RATES])
    assert result.exit_code == 0, result.output

    second = tmp_path / 'second.txt'
    second.write_text(SECOND_BILL)
    result = runner.invoke(cli, ['import', str(book), str(second),
                                 '--include-business-objects', '--fx-rates', RATES])
    assert result.exit_code == 0, result.output

    exported = tmp_path / 'out.txt'
    assert runner.invoke(cli, ['export', str(book), str(exported),
                               '--include-business-objects']).exit_code == 0
    text = exported.read_text()

    applied = text.split('Liabilities:Accounts Payable USD 40.00 USD')[1]
    applied = applied.split('\n\tLiabilities')[0].split('\n\tAssets')[0]
    assert 'cost_basis_available' not in applied, applied
    assert 'cost_basis_cost' not in applied, applied

    remainder = text.split('Liabilities:Accounts Payable USD 60.00 USD')[1]
    remainder = remainder.split('\n\tLiabilities')[0].split('\n\tAssets')[0]
    assert 'cost_basis_available: "60.00"' in remainder, remainder
    assert 'cost_basis_cost: "1.4 CAD/USD"' in remainder, remainder

    listing = runner.invoke(cli, ['fx-balances', str(book)]).output
    assert '60.00 USD' in listing, listing
    checked = runner.invoke(cli, ['fx-balances', str(book), '--verify-costs'])
    assert checked.exit_code == 0, checked.output

    # And it rebuilds from that file with the claim and its cost intact.
    rebuilt = tmp_path / 'rebuilt.gnucash'
    result = runner.invoke(cli, ['import', '--new', str(rebuilt), str(exported),
                                 '--include-business-objects'])
    assert result.exit_code == 0, result.output
    rebuilt_listing = runner.invoke(cli, ['fx-balances', str(rebuilt)])
    assert rebuilt_listing.exit_code == 0, rebuilt_listing.output
    assert '60.00 USD' in rebuilt_listing.output, rebuilt_listing.output
    assert '1.4 CAD/USD' in rebuilt_listing.output, rebuilt_listing.output
    again = tmp_path / 'out2.txt'
    assert runner.invoke(cli, ['export', str(rebuilt), str(again),
                               '--include-business-objects']).exit_code == 0
    assert again.read_text() == exported.read_text()
