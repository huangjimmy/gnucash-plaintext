"""What a `from_credit: true` payment block must say, and what it may not.

A credit block spends currency the book already holds, so it names the split
it comes out of rather than an account and an amount to move. Everything it
states is checked against the book, the way a stated cost or a stated balance
is: a block that cannot be honoured is refused rather than half-applied.
"""

from fractions import Fraction
from pathlib import Path

from click.testing import CliRunner

from cli.main import cli
from repositories.gnucash_repository import GnuCashRepository, SessionMode

ACCOUNTS = 'tests/fixtures/payment_roundtrip_accounts.txt'
FIXTURES = Path('tests/fixtures')


def _book_with_a_credit(runner, tmp_path):
    """A customer with 50.00 of credit left over from overpaying INV-001."""
    book = tmp_path / 'book.gnucash'
    assert runner.invoke(cli, ['import', '--new', str(book), ACCOUNTS]).exit_code == 0
    primer = tmp_path / 'primer.txt'
    primer.write_text((FIXTURES / 'q015_aac_primer_invoice.txt').read_text())
    result = runner.invoke(cli, ['import', str(book), str(primer),
                                 '--include-business-objects'])
    assert result.exit_code == 0, result.output
    return book


def _credit_split(book, description=None,
                  account_name='Assets.Accounts Receivable',
                  amount='-5000/100'):
    """(transaction guid, split guid) of a 50.00 credit, by transaction if named."""
    from gnucash import Query, Transaction

    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        query = Query()
        query.search_for('Trans')
        query.set_book(repo.book)
        for raw in query.run():
            transaction = Transaction(instance=raw)
            if description is not None and transaction.GetDescription() != description:
                continue
            for split in transaction.GetSplitList():
                account = split.GetAccount()
                if account is None:
                    continue
                if account.get_full_name() != account_name:
                    continue
                if str(split.GetAmount()) == amount:
                    return (transaction.GetGUID().to_string(),
                            split.GetGUID().to_string())
        query.destroy()
    finally:
        repo.close()
    raise AssertionError('no 50.00 credit split found')


def _credit_amounts(book):
    """{transaction description: amount as an exact Fraction} of every unspent
    credit split.

    A credit is a receivable split still in a lot no invoice owns — read
    from the book itself, so a listing that miscounts cannot make the test
    agree with it.

    The amount is the value, not GnuCash's rendering of it. A GncNumeric prints
    as `num/denom` at the unit its account is kept to, so the same 49.90 reads
    as `-4990/100` on an ordinary receivable and `-499/10` on one kept to the
    tenth — and a test comparing the text is asserting which account it happens
    to be on as much as how much money is there.
    """
    import gnucash.gnucash_core_c as gc
    from gnucash import Query, Transaction

    from infrastructure.gnucash.utils import numeric_to_fraction

    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        query = Query()
        query.search_for('Trans')
        query.set_book(repo.book)
        found = {}
        for raw in query.run():
            transaction = Transaction(instance=raw)
            for split in transaction.GetSplitList():
                account = split.GetAccount()
                if account is None:
                    continue
                if account.get_full_name() != 'Assets.Accounts Receivable':
                    continue
                lot = split.GetLot()
                if lot is None or gc.gncInvoiceGetInvoiceFromLot(lot):
                    continue
                found[transaction.GetDescription()] = numeric_to_fraction(
                    split.GetAmount())
        query.destroy()
        return found
    finally:
        repo.close()


def _credit_transaction_figures(book, description):
    """Every split's amount and value on one transaction, and the value sum.

    Read from the book rather than from an export: a value equal to its
    amount is not written out, so a value gone astray by a tenth of a cent
    would leave no trace in the file to assert on.
    """
    from fractions import Fraction

    from gnucash import Query, Transaction

    from infrastructure.gnucash.utils import numeric_to_fraction

    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        query = Query()
        query.search_for('Trans')
        query.set_book(repo.book)
        for raw in query.run():
            transaction = Transaction(instance=raw)
            if transaction.GetDescription() != description:
                continue
            splits = list(transaction.GetSplitList())
            total = sum((numeric_to_fraction(s.GetValue()) for s in splits),
                        Fraction(0))
            found = {'amounts': [str(s.GetAmount()) for s in splits],
                     'values': [str(s.GetValue()) for s in splits],
                     'value_sum': str(total)}
            query.destroy()
            return found
        query.destroy()
    finally:
        repo.close()
    raise AssertionError(f'no transaction described {description!r}')


def _lots_on(book, account_name):
    """How many lots the account has.

    Read through the importer's own reader, so the test asks the book the same
    way the code does. An empty lot is invisible to `find-prepayments`, which
    lists by balance, and counting is the only way to see one left behind.
    """
    from infrastructure.gnucash.utils import get_account_full_name
    from services.gnucash_importer import _live_lot_pointers

    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        root = repo.book.get_root_account()
        stack = [root]
        while stack:
            account = stack.pop()
            for child in account.get_children():
                stack.append(child)
            if get_account_full_name(account) == account_name:
                return len(_live_lot_pointers(account))
    finally:
        repo.close()
    raise AssertionError(f'no account named {account_name!r}')


def _outstanding(book, invoice_id):
    """What the invoice's lot still says it is owed."""
    from gnucash import Query

    from infrastructure.gnucash.utils import wrap_invoice_or_bill

    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        query = Query()
        query.search_for('gncInvoice')
        query.set_book(repo.book)
        for raw in query.run():
            invoice = wrap_invoice_or_bill(raw)
            if invoice.GetID() != invoice_id:
                continue
            lot = invoice.GetPostedLot()
            query.destroy()
            return None if lot is None else str(lot.get_balance())
        query.destroy()
    finally:
        repo.close()
    raise AssertionError(f'{invoice_id} not found')


def _import_fixture(runner, book, tmp_path, name, txn_guid='', split_guid=''):
    text = (FIXTURES / name).read_text()
    text = text.replace('TXN_GUID', txn_guid).replace('SPLIT_GUID', split_guid)
    path = tmp_path / name
    path.write_text(text)
    return runner.invoke(cli, ['import', str(book), str(path),
                               '--include-business-objects'])


def test_a_block_giving_its_split_walks_each_account_once(tmp_path, monkeypatch):
    """The guards before a move share one reading of the account's lots.

    Asking whether a lot is still the account's means walking the account's
    whole lot list — one lot per invoice ever posted on a receivable, and a
    `GList` node built in Python for each. Three guards run back to back
    before a `txn_split_guid:` block moves anything: whose money the split is,
    whether it already settles another invoice, and whether it sits in an
    owner's credit. Each asked the account again, so re-importing an export of
    a long-lived book cost the product of its invoices and its history — the
    shape the retarget's own candidate search was corrected for, in the same
    change, and left in the guards beside it.

    Nothing between them moves a split, so one reading answers all three.
    """
    from services import gnucash_importer

    runner = CliRunner()
    book = _book_with_a_credit(runner, tmp_path)
    txn_guid, split_guid = _credit_split(book)

    # Counted where the list is actually walked, which is a question the memo
    # cannot answer — not once per reader that asks, since the whole point is
    # that several readers ask and one walk answers them.
    walks = []
    real = gnucash_importer._live_lot_pointers

    def counted(account):
        memo = gnucash_importer._LIVE_LOT_MEMO
        if memo is None or int(account.instance) not in memo:
            walks.append(account.get_full_name())
        return real(account)

    monkeypatch.setattr(gnucash_importer, '_live_lot_pointers', counted)
    result = _import_fixture(runner, book, tmp_path,
                             'credit_payment_smaller_than_the_invoice.txt',
                             txn_guid, split_guid)
    assert result.exit_code == 0, result.output

    receivable = [name for name in walks if 'Receivable' in name]
    assert len(receivable) == 1, walks


def test_a_credit_block_states_no_account(tmp_path):
    """Nothing paid out of a bank, so stating one is refused."""
    runner = CliRunner()
    book = _book_with_a_credit(runner, tmp_path)
    txn_guid, split_guid = _credit_split(book)

    result = _import_fixture(runner, book, tmp_path,
                             'credit_payment_naming_a_bank.txt', txn_guid, split_guid)
    assert result.exit_code != 0, result.output
    assert 'states no account' in result.output, result.output
    assert 'bank_account' in result.output, result.output


def test_a_credit_block_has_no_date_of_its_own(tmp_path):
    """`date:` is refused, because GnuCash records none for an application."""
    runner = CliRunner()
    book = _book_with_a_credit(runner, tmp_path)
    txn_guid, split_guid = _credit_split(book)

    result = _import_fixture(runner, book, tmp_path,
                             'credit_payment_dated_like_a_payment.txt',
                             txn_guid, split_guid)
    assert result.exit_code != 0, result.output
    assert 'credit_dated:' in result.output, result.output


def test_a_credit_block_must_say_which_credit(tmp_path):
    """Without the guids the file says a credit was applied, not which one."""
    runner = CliRunner()
    book = _book_with_a_credit(runner, tmp_path)

    result = _import_fixture(runner, book, tmp_path,
                             'credit_payment_giving_no_split.txt')
    assert result.exit_code != 0, result.output
    assert 'txn_split_guid' in result.output, result.output
    assert 'auto_apply_credit' in result.output, result.output


def test_a_stated_credit_date_that_disagrees_is_refused(tmp_path):
    """The date is checked against the transaction the guid names."""
    runner = CliRunner()
    book = _book_with_a_credit(runner, tmp_path)
    txn_guid, split_guid = _credit_split(book)

    result = _import_fixture(runner, book, tmp_path,
                             'credit_payment_with_the_wrong_date.txt',
                             txn_guid, split_guid)
    assert result.exit_code != 0, result.output
    assert 'credit_dated: 2026-01-11' in result.output, result.output
    assert '2026-01-10' in result.output, result.output


def test_claiming_more_than_the_split_carries_is_refused(tmp_path):
    """A block spends the whole split it names, so 45.00 of a 50.00 is refused."""
    runner = CliRunner()
    book = _book_with_a_credit(runner, tmp_path)
    txn_guid, split_guid = _credit_split(book)

    result = _import_fixture(runner, book, tmp_path,
                             'credit_payment_claiming_more_than_the_split.txt',
                             txn_guid, split_guid)
    assert result.exit_code != 0, result.output
    assert 'amount: 45.00' in result.output, result.output
    assert '50.00' in result.output, result.output
    assert 'what the split holds' in result.output, result.output


def test_one_owners_credit_cannot_settle_anothers_invoice(tmp_path):
    """Beta's invoice cannot be paid out of Acme's credit.

    The block addresses a credit by guid, and a guid copied out of a large
    export says nothing about whose money it is. Spending it left Beta's
    invoice reading as paid though Beta paid nothing, Acme's 50.00 gone from
    `find-prepayments`, and the book still owing Acme 50.00 with no record of
    it anywhere.
    """
    runner = CliRunner()
    book = _book_with_a_credit(runner, tmp_path)
    txn_guid, split_guid = _credit_split(book)

    result = _import_fixture(runner, book, tmp_path,
                             'credit_payment_of_another_owners_credit.txt',
                             txn_guid, split_guid)
    assert result.exit_code != 0, result.output
    assert 'C001' in result.output, result.output
    assert 'C002' in result.output, result.output

    # And Acme still has every cent of it.
    prepayments = runner.invoke(cli, ['find-prepayments', str(book)])
    assert prepayments.exit_code == 0, prepayments.output
    assert '50.00' in prepayments.output, prepayments.output


def test_a_retarget_cannot_take_another_owners_split_either(tmp_path):
    """The same guard on the ordinary `txn_guid:` retarget.

    A payment block naming a bank account attaches the split its guids point
    at to this invoice's lot, which is the same move a credit block makes and
    was open to the same mistake: Gamma's invoice settled out of Acme's money.
    """
    runner = CliRunner()
    book = _book_with_a_credit(runner, tmp_path)
    txn_guid, split_guid = _credit_split(book)

    result = _import_fixture(runner, book, tmp_path,
                             'retarget_payment_of_another_owners_split.txt',
                             txn_guid, split_guid)
    assert result.exit_code != 0, result.output
    assert 'C001' in result.output, result.output
    assert 'C003' in result.output, result.output

    prepayments = runner.invoke(cli, ['find-prepayments', str(book)])
    assert prepayments.exit_code == 0, prepayments.output
    assert '50.00' in prepayments.output, prepayments.output


def test_a_credit_smaller_than_the_invoice_owes_pays_what_it_can(tmp_path):
    """50.00 of credit against a 200.00 invoice settles 50.00 of it.

    Part-paying is what a payment usually does, and a credit is a payment.
    The invoice stays open for the rest and the credit is spent.
    """
    runner = CliRunner()
    book = _book_with_a_credit(runner, tmp_path)
    txn_guid, split_guid = _credit_split(book)

    result = _import_fixture(runner, book, tmp_path,
                             'credit_payment_smaller_than_the_invoice.txt',
                             txn_guid, split_guid)
    assert result.exit_code == 0, result.output

    exported = tmp_path / 'out.txt'
    assert runner.invoke(cli, ['export', str(book), str(exported),
                               '--include-business-objects']).exit_code == 0
    block = exported.read_text().split('invoice "INV-CREDIT-PARTIAL"')[1]
    block = block.split('\n\n')[0]
    assert 'from_credit: #True' in block, block
    assert 'amount: 50.00' in block, block

    # The credit is gone and 150.00 of the invoice is still owed.
    prepayments = runner.invoke(cli, ['find-prepayments', str(book)])
    assert prepayments.exit_code == 0, prepayments.output
    assert 'No pre-payment credits found' in prepayments.output, prepayments.output
    assert _outstanding(book, 'INV-CREDIT-PARTIAL') == '15000/100'


def test_a_credit_bigger_than_the_invoice_pays_what_it_owes(tmp_path):
    """50.00 of credit meeting a 30.00 invoice settles it and leaves 20.00.

    Attaching the whole split would take the lot to −20.00, where the invoice
    reads neither settled nor open and the customer's 20.00 disappears from
    `find-prepayments` — it lists lots no invoice owns, and that money would
    be inside one that does. GnuCash divides a credit itself, so it is asked
    to, and the block ends up meaning what a reader would take it to mean.
    """
    runner = CliRunner()
    book = _book_with_a_credit(runner, tmp_path)
    txn_guid, split_guid = _credit_split(book)

    result = _import_fixture(runner, book, tmp_path,
                             'credit_payment_bigger_than_the_invoice.txt',
                             txn_guid, split_guid)
    assert result.exit_code == 0, result.output

    # The invoice is settled, not overshot.
    assert _outstanding(book, 'INV-CREDIT-OVERPAID') == '0/100'

    # And 20.00 of the credit is still the customer's.
    prepayments = runner.invoke(cli, ['find-prepayments', str(book)])
    assert prepayments.exit_code == 0, prepayments.output
    assert 'CAD 20.00' in prepayments.output, prepayments.output

    # What settled it says so, at the size it actually took.
    exported = tmp_path / 'out.txt'
    assert runner.invoke(cli, ['export', str(book), str(exported),
                               '--include-business-objects']).exit_code == 0
    block = exported.read_text().split('invoice "INV-CREDIT-OVERPAID"')[1]
    block = block.split('\n\n')[0]
    assert 'from_credit: #True' in block, block
    assert 'amount: 30.00' in block, block


def test_a_credit_appended_to_an_invoice_already_in_the_book_is_applied(tmp_path):
    """Adding the block to a file already imported settles the invoice.

    A file whose only change is a new payment takes the add-a-payment path
    rather than being rebuilt, and that path ran the block and threw away
    what it said: a credit needing to be divided was never divided, so the
    import reported the invoice updated while it stayed unpaid and the credit
    stayed whole — and running the file again did nothing again.
    """
    runner = CliRunner()
    book = _book_with_a_credit(runner, tmp_path)
    assert _import_fixture(runner, book, tmp_path,
                           'credit_payment_appended_invoice.txt').exit_code == 0
    txn_guid, split_guid = _credit_split(book)

    result = _import_fixture(runner, book, tmp_path,
                             'credit_payment_appended_to_a_posted_invoice.txt',
                             txn_guid, split_guid)
    assert result.exit_code == 0, result.output

    assert _outstanding(book, 'INV-APPEND') == '0/100'
    prepayments = runner.invoke(cli, ['find-prepayments', str(book)])
    assert prepayments.exit_code == 0, prepayments.output
    assert 'CAD 20.00' in prepayments.output, prepayments.output


def test_a_credit_takes_only_what_the_cash_before_it_left(tmp_path):
    """80.00 of cash and a 50.00 credit against a 100.00 invoice.

    Cash blocks are applied before credit ones, so by the time the credit is
    reached the invoice owes 20.00, not the 100.00 it was posted for.
    Measuring the credit against the invoice's total instead let all 50.00 in
    and took the lot to −30.00 — the invoice neither settled nor open, and
    30.00 of the customer's money inside its lot, where `find-prepayments`
    cannot see it.
    """
    runner = CliRunner()
    book = _book_with_a_credit(runner, tmp_path)
    txn_guid, split_guid = _credit_split(book)

    result = _import_fixture(runner, book, tmp_path,
                             'credit_payment_after_a_cash_payment.txt',
                             txn_guid, split_guid)
    assert result.exit_code == 0, result.output

    assert _outstanding(book, 'INV-CASH-THEN-CREDIT') == '0/100'
    prepayments = runner.invoke(cli, ['find-prepayments', str(book)])
    assert prepayments.exit_code == 0, prepayments.output
    assert 'CAD 30.00' in prepayments.output, prepayments.output


def test_a_retarget_giving_only_a_transaction_is_guarded_too(tmp_path):
    """Dropping `txn_split_guid:` must not drop the check with it.

    A payment block naming just `txn_guid:` retargets the transaction's
    counter split into this invoice's lot — the same move, one line shorter,
    and it went unguarded: another customer's invoice settled out of this
    payment, with the payer's credit gone and the book still owing it.

    The transaction here carries one receivable split, which is what lets a
    block name it and nothing else: with several, which one would move is
    decided by the order they are in, and the file is refused for not saying.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    assert runner.invoke(cli, ['import', '--new', str(book), ACCOUNTS]).exit_code == 0
    assert _import_fixture(runner, book, tmp_path,
                           'invoice_paid_exactly_by_one_split.txt').exit_code == 0
    assert runner.invoke(cli, ['unpost-invoices', str(book),
                               'INV-EXACT']).exit_code == 0

    txn_guid, _split_guid = _credit_split(book, amount='-10000/100')
    result = _import_fixture(runner, book, tmp_path,
                             'retarget_giving_only_another_owners_transaction.txt',
                             txn_guid)
    assert result.exit_code != 0, result.output
    assert 'C-EXACT' in result.output, result.output
    assert 'C-OTHER' in result.output, result.output


def test_a_credit_on_a_invoice_that_owes_nothing_is_refused(tmp_path):
    """Cash settled it in full, so there is nothing for a credit to settle.

    With the invoice already paid the credit has no room: attaching it whole
    takes the lot to −50.00, and dividing it applies nothing. The file is
    saying something about this invoice that is not true of it.
    """
    runner = CliRunner()
    book = _book_with_a_credit(runner, tmp_path)
    txn_guid, split_guid = _credit_split(book)

    result = _import_fixture(runner, book, tmp_path,
                             'credit_payment_on_an_invoice_owing_nothing.txt',
                             txn_guid, split_guid)
    assert result.exit_code != 0, result.output
    assert 'owes nothing' in result.output, result.output

    prepayments = runner.invoke(cli, ['find-prepayments', str(book)])
    assert prepayments.exit_code == 0, prepayments.output
    assert 'CAD 50.00' in prepayments.output, prepayments.output


def test_the_credit_the_block_names_is_the_one_that_is_spent(tmp_path):
    """With two credits open, the file says which, and the book must obey.

    Dividing a credit is the engine's work, and the engine chooses among the
    owner's open credits in its own order — so a block naming the March
    credit could see the January one carved instead, reported as success.
    Two credits of an owner are not interchangeable: they were acquired on
    different days, and in a foreign currency at different costs.
    """
    runner = CliRunner()
    book = _book_with_a_credit(runner, tmp_path)
    second = tmp_path / 'second.txt'
    second.write_text(
        (FIXTURES / 'second_customer_prepayment.txt').read_text())
    assert runner.invoke(cli, ['import', str(book), str(second)]).exit_code == 0

    # Name the March credit against a 30.00 invoice: 50.00 is bigger, so it
    # has to be divided, and it is the March one that must give up 30.00.
    txn_guid, split_guid = _credit_split(book, description='Acme pays ahead again')
    result = _import_fixture(runner, book, tmp_path,
                             'credit_payment_giving_the_later_credit.txt',
                             txn_guid, split_guid)

    assert result.exit_code == 0, result.output

    # The invoice is settled out of the credit the file named, and January's
    # credit — the one the engine would have reached for first — is untouched.
    # Read from the book, split by split, and not through `find-prepayments`:
    # either amount appearing somewhere in that listing is true whichever
    # credit was carved, so the test has to say which credit carries which —
    # and reading the book directly says which credit is which whatever any
    # listing chooses to show.
    assert _outstanding(book, 'INV-PICKS-A-CREDIT') == '0/100'
    assert _credit_amounts(book) == {'Acme': Fraction(-50),
                                     'Acme pays ahead again': Fraction(-20)}


def test_a_credit_in_a_lot_spanning_three_transactions_is_named_by_its_own_split(tmp_path):
    """A lot's splits span transactions, so the reading has to be per-split.

    One invoice settled 40.00 and 30.00 off two deposits and 30.00 out of the
    customer's standing credit, then unposted: all three splits are marked, but
    only the two the bank paid are orphans. What is left to list is the 30.00
    that came from credit — and it has to be named by *its* transaction.

    Reading the mark off one split's parent knows nothing about the others, so
    the filter saw only the first cash split and settled on the second — a bank
    payment — reporting the credit's balance against that payment's date and
    account, and a `from_credit:` block written from that guid is refused for
    naming a settlement a bank paid. Offering a credit whose guid cannot be
    spent is the shape this whole area is being corrected for.
    """
    from gnucash import Query, Transaction

    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    assert runner.invoke(cli, ['import', '--new', str(book), ACCOUNTS]).exit_code == 0
    setup = tmp_path / 'setup.txt'
    setup.write_text((FIXTURES / 'one_bank_tx_two_owners.txt').read_text())
    assert runner.invoke(cli, ['import', str(book), str(setup),
                               '--include-business-objects']).exit_code == 0
    deposits = tmp_path / 'deposits.txt'
    deposits.write_text(
        (FIXTURES / 'three_deposits_and_a_standing_credit.txt').read_text())
    assert runner.invoke(cli, ['import', str(book), str(deposits)]).exit_code == 0

    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        query = Query()
        query.search_for('Trans')
        query.set_book(repo.book)
        guids, credit_split = {}, None
        for raw in query.run():
            transaction = Transaction(instance=raw)
            description = transaction.GetDescription()
            guids[description] = transaction.GetGUID().to_string()
            if description == 'Alpha pays ahead':
                for split in transaction.GetSplitList():
                    if str(split.GetAmount()) == '-3000/100':
                        credit_split = split.GetGUID().to_string()
        query.destroy()
    finally:
        repo.close()
    assert credit_split is not None, guids

    settled = tmp_path / 'three_ways.txt'
    settled.write_text(
        (FIXTURES / 'invoice_settled_by_two_cash_and_one_credit.txt').read_text()
        .replace('TXN_ONE', guids['Alpha first cash'])
        .replace('TXN_TWO', guids['Alpha second cash'])
        .replace('TXN_CREDIT', guids['Alpha pays ahead'])
        .replace('SPLIT_CREDIT', credit_split))
    built = runner.invoke(cli, ['import', str(book), str(settled),
                                '--include-business-objects'])
    assert built.exit_code == 0, built.output
    assert _outstanding(book, 'INV-THREE-WAYS') == '0/100'

    assert runner.invoke(cli, ['unpost-invoices', str(book),
                               'INV-THREE-WAYS']).exit_code == 0

    # The 30.00 that came from credit is still the customer's, and it is
    # reported against the transaction that brought it in.
    listed = runner.invoke(cli, ['find-prepayments', str(book)])
    assert listed.exit_code == 0, listed.output
    assert '30.00' in listed.output, listed.output
    assert 'Alpha pays ahead' in listed.output, listed.output
    assert 'Alpha first cash' not in listed.output, listed.output
    assert 'Alpha second cash' not in listed.output, listed.output
    assert guids['Alpha pays ahead'] in listed.output.replace('-', ''), \
        listed.output


def test_a_rebuild_takes_its_own_orphan_over_a_loose_sibling(tmp_path):
    """Loose means unclaimed, not "belongs to whoever asks next".

    A deposit covering two customers, with only the first invoice imported:
    its portion settles it, the other stays loose until that invoice arrives.
    Editing the first unposts it, and its settlement becomes an orphan on a
    transaction that also carries the second customer's untouched portion.

    Both are things the mover could place, and only the mark says which was
    ever this invoice's. Taking the loose one settles this invoice out of the
    other customer's money and abandons its own settlement — and nothing
    refuses it, because with one loose split there is no ambiguity to see.
    What the reader gets instead is a demand to declare a `prepayment:` for
    the 20.00 difference on a payment they never made.
    """
    from gnucash import Query, Transaction

    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    assert runner.invoke(cli, ['import', '--new', str(book), ACCOUNTS]).exit_code == 0
    deposit = tmp_path / 'deposit.txt'
    deposit.write_text((FIXTURES / 'one_bank_tx_two_owners.txt').read_text())
    assert runner.invoke(cli, ['import', str(book), str(deposit),
                               '--include-business-objects']).exit_code == 0

    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        query = Query()
        query.search_for('Trans')
        query.set_book(repo.book)
        splits, txn_guid = {}, None
        for raw in query.run():
            transaction = Transaction(instance=raw)
            if transaction.GetDescription() != 'Deposit covering Alpha and Beta':
                continue
            txn_guid = transaction.GetGUID().to_string()
            for split in transaction.GetSplitList():
                splits[str(split.GetAmount())] = split.GetGUID().to_string()
        query.destroy()
    finally:
        repo.close()
    assert txn_guid is not None

    first = tmp_path / 'alpha.txt'
    first.write_text((FIXTURES / 'alpha_alone_giving_its_own_portion.txt')
                     .read_text().replace('TXN_GUID', txn_guid)
                     .replace('SPLIT_A', splits['-10000/100']))
    assert runner.invoke(cli, ['import', str(book), str(first),
                               '--include-business-objects']).exit_code == 0
    assert _outstanding(book, 'INV-TWO-A') == '0/100'

    # One takeable split left, so the block gets as far as its own `amount:` —
    # and a figure that is not one is said to be that, rather than failing
    # further in on a number nobody wrote. Nothing parses it earlier on this
    # spelling: the block names its transaction and leaves the split to be
    # found, so the check comparing the two is the first to read it.
    unreadable = tmp_path / 'not_a_number.txt'
    unreadable.write_text(
        (FIXTURES / 'retarget_stating_an_amount_that_is_not_a_number.txt')
        .read_text().replace('TXN_GUID', txn_guid))
    nan = runner.invoke(cli, ['import', str(book), str(unreadable),
                              '--include-business-objects'])
    assert nan.exit_code != 0, nan.output
    assert 'must be a number' in nan.output, nan.output
    assert 'one hundred' in nan.output, nan.output

    edited = tmp_path / 'alpha_edited.txt'
    edited.write_text((FIXTURES / 'alpha_rebuilt_giving_only_the_transaction.txt')
                      .read_text().replace('TXN_GUID', txn_guid))
    # The edit changes a line, and a line under a posting is not changed by an
    # import — the unpost is a step of its own now. It is what orphans this
    # invoice's settlement, which is the state the rest of this test is about.
    assert runner.invoke(cli, ['unpost-invoices', str(book),
                               'INV-TWO-A']).exit_code == 0
    rebuilt = runner.invoke(cli, ['import', str(book), str(edited),
                                  '--include-business-objects'])
    assert rebuilt.exit_code == 0, rebuilt.output
    assert 'prepayment' not in rebuilt.output, rebuilt.output
    assert _outstanding(book, 'INV-TWO-A') == '0/100'

    # Beta's portion is where it was — still loose, still theirs to claim when
    # their invoice arrives. Settled by it, this invoice would read as paid
    # while Beta's money had quietly gone.
    beta = tmp_path / 'beta.txt'
    beta.write_text((FIXTURES / 'second_owner_names_the_shared_deposit.txt')
                    .read_text().replace('TXN_GUID', txn_guid))
    assert runner.invoke(cli, ['import', str(book), str(beta),
                               '--include-business-objects']).exit_code == 0
    assert _outstanding(book, 'INV-TWO-B') == '0/100'

    # With both settled, unposting one leaves its portion orphaned on a
    # transaction whose other portion still settles Beta's invoice. The listing
    # has to be told which split it is about: taking whichever AR split came
    # last found Beta's, whose lot still holds an invoice, and Alpha's money
    # was then reported by nothing — while every refusal about it asks for a
    # guid. The figure is the orphan's own 100.00, not the deposit's 220.00.
    assert runner.invoke(cli, ['unpost-invoices', str(book),
                               'INV-TWO-A']).exit_code == 0
    orphans = runner.invoke(cli, ['find-orphan-payments', str(book)])
    assert orphans.exit_code == 0, orphans.output
    assert '100.00' in orphans.output, orphans.output
    assert '220.00' not in orphans.output, orphans.output
    assert 'Alpha' in orphans.output, orphans.output

    # Even with Beta's invoice not yet imported, deleting that guid would take
    # Beta's unclaimed 120.00 out of the bank and put back only Alpha's 100.00.
    # What the warning guards is "this guid holds money that is not this
    # row's", and a portion nobody has claimed yet is exactly that — so it
    # does not wait for the other portion to become an orphan too.
    alone = runner.invoke(cli, ['find-orphan-payments', str(book)])
    assert alone.exit_code == 0, alone.output
    assert 'would take that with them' in alone.output, alone.output
    assert 'delete with `delete-transactions' not in alone.output, alone.output
    # And there is no second kind of guid here to send the reader to: one
    # transaction, and its only guid is the shared one. Ending on "for a guid
    # not marked" names a category this listing has nothing in, which reads as
    # an option they have merely not spotted yet — and the whole point of the
    # warning is that this listing has no safe guid to delete.
    assert 'For a guid not marked' not in alone.output, alone.output
    assert 'not available for any guid' in alone.output, alone.output
    # And what it says the guid carries is money beyond *the row* — which is
    # what the listing was asked and what the delete would take. Calling it
    # money the listing is not about is false as soon as the other portion is
    # unposted too and becomes a row of its own, which is the next step below.
    assert 'money beyond the row' in alone.output, alone.output
    assert 'this listing is not about' not in alone.output, alone.output

    # Unpost the other one too and the deposit carries two orphans, which is
    # two rows. Reported once it named whichever came last, and the other
    # invoice's money was listed nowhere — while every refusal about it asks
    # the reader for a guid. This is why the mark stores an invoice guid
    # rather than `true`.
    assert runner.invoke(cli, ['unpost-invoices', str(book),
                               'INV-TWO-B']).exit_code == 0
    both = runner.invoke(cli, ['find-orphan-payments', str(book)])
    assert both.exit_code == 0, both.output
    assert '100.00' in both.output, both.output
    assert '120.00' in both.output, both.output
    # Two orphaned payments, but one transaction — and the count says so,
    # because a guid is what the cleanup advice acts on and deleting it twice
    # is not a thing a reader should be invited to try.
    assert 'reported as 2 orphaned payments' in both.output, both.output
    assert '1 orphan bank-side payment transaction' in both.output, both.output
    # Deleting that guid would take the other customer's money with it, so the
    # advice says so rather than offering it — and says it as what it is. Both
    # portions are rows here, so the listing *is* about all of it; what the
    # guid carries beyond any one row is what a whole-transaction delete takes.
    assert 'would take that with them' in both.output, both.output
    assert 'money beyond the row' in both.output, both.output
    assert 'this listing is not about' not in both.output, both.output

    # Each row says whose money it is, asked of that row's own split. The
    # owner recorded on the transaction is one of the two at best, and stamped
    # on both rows it reported Beta's 120.00 as Alpha's.
    assert 'C-TWO-A' in both.output, both.output
    assert 'C-TWO-B' in both.output, both.output

    # So each customer's filter finds their own, and only their own.
    alpha = runner.invoke(cli, ['find-orphan-payments', str(book),
                                '--customer', 'C-TWO-A'])
    assert alpha.exit_code == 0, alpha.output
    assert '100.00' in alpha.output, alpha.output
    assert '120.00' not in alpha.output, alpha.output
    # And the warning survives the narrowing. Filtering to one customer is
    # what a reader cleaning that customer up does, and it is the very case
    # where deleting the guid takes the other's money — so the row carries
    # the fact rather than the listing counting what happened to survive.
    assert 'would take that with them' in alpha.output, alpha.output
    assert 'money beyond the row' in alpha.output, alpha.output
    beta = runner.invoke(cli, ['find-orphan-payments', str(book),
                               '--customer', 'C-TWO-B'])
    assert beta.exit_code == 0, beta.output
    assert '120.00' in beta.output, beta.output
    assert '100.00' not in beta.output, beta.output

    # A third invoice paid the ordinary way, then unposted, puts a guid in the
    # listing that holds nothing but itself. Now both kinds are there, and the
    # advice has somewhere to send the reader for the second: delete that one,
    # not the shared ones.
    third = tmp_path / 'alpha_c.txt'
    third.write_text(
        (FIXTURES / 'alpha_paid_by_a_bank_tx_of_its_own.txt').read_text())
    assert runner.invoke(cli, ['import', str(book), str(third),
                               '--include-business-objects']).exit_code == 0
    assert runner.invoke(cli, ['unpost-invoices', str(book),
                               'INV-TWO-C']).exit_code == 0
    mixed = runner.invoke(cli, ['find-orphan-payments', str(book)])
    assert mixed.exit_code == 0, mixed.output
    assert '30.00' in mixed.output, mixed.output
    assert 'For a guid not marked' in mixed.output, mixed.output
    assert 'not available for any guid' not in mixed.output, mixed.output


def test_one_deposit_can_settle_two_owners_invoices(tmp_path):
    """The guard must not refuse the shape it was written beside.

    One bank deposit settling several invoices is an ordinary thing, and
    when those invoices belong to different owners each block names its own
    split. Asking the *transaction* whose money it is answers for the first
    owned split it finds, so Beta's invoice was refused for being Alpha's —
    while the split Beta's block names is Beta's, and is what decides.
    """
    from gnucash import Query, Transaction

    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    assert runner.invoke(cli, ['import', '--new', str(book), ACCOUNTS]).exit_code == 0
    deposit = tmp_path / 'deposit.txt'
    deposit.write_text((FIXTURES / 'one_bank_tx_two_owners.txt').read_text())
    assert runner.invoke(cli, ['import', str(book), str(deposit),
                               '--include-business-objects']).exit_code == 0

    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        query = Query()
        query.search_for('Trans')
        query.set_book(repo.book)
        splits = {}
        txn_guid = None
        for raw in query.run():
            transaction = Transaction(instance=raw)
            if transaction.GetDescription() != 'Deposit covering Alpha and Beta':
                continue
            txn_guid = transaction.GetGUID().to_string()
            for split in transaction.GetSplitList():
                splits[str(split.GetAmount())] = split.GetGUID().to_string()
        query.destroy()
    finally:
        repo.close()
    assert txn_guid is not None

    text = (FIXTURES / 'one_bank_tx_two_owners_invoices.txt').read_text()
    text = (text.replace('TXN_GUID', txn_guid)
                .replace('SPLIT_A', splits['-10000/100'])
                .replace('SPLIT_B', splits['-12000/100']))
    path = tmp_path / 'invoices.txt'
    path.write_text(text)
    result = runner.invoke(cli, ['import', str(book), str(path),
                                 '--include-business-objects'])
    assert result.exit_code == 0, result.output

    assert _outstanding(book, 'INV-TWO-A') == '0/100'
    assert _outstanding(book, 'INV-TWO-B') == '0/100'

    # And once both portions are spent, a third invoice naming that deposit
    # has nothing left to take. Every split on it settles an invoice that
    # reads as paid, so moving one would settle this invoice by leaving that
    # invoice unpaid — with every figure in the book still balancing, which
    # is what makes it worth refusing rather than reporting afterwards.
    #
    # Same owner as the first invoice, so the owner guard has nothing to say:
    # what is wrong is that the money is spent, not whose it was.
    spent = tmp_path / 'third.txt'
    spent.write_text((FIXTURES / 'third_invoice_names_a_spent_deposit.txt')
                     .read_text().replace('TXN_GUID', txn_guid))
    refused = runner.invoke(cli, ['import', str(book), str(spent),
                                  '--include-business-objects'])
    assert refused.exit_code != 0, refused.output
    # The message has to name what is actually wrong. Both splits are there;
    # what they are not is free, and a reader told "no non-bank split" would go
    # looking for one that is in front of them.
    assert 'already settles an invoice or a bill' in refused.output, refused.output
    assert 'txn_split_guid' in refused.output, refused.output
    assert 'expected a non-' not in refused.output, refused.output
    # And it names only what can be the obstacle. A split holding an owner's
    # credit is one the retarget may place — it is a tier of the search — so
    # a transaction with one never reaches this refusal, and offering a credit
    # as a possible reason sends the reader looking for one they have not got.
    assert 'credit' not in refused.output, refused.output
    assert _outstanding(book, 'INV-TWO-A') == '0/100'
    assert _outstanding(book, 'INV-TWO-B') == '0/100'

    # And that refusal's own advice — name the split outright — is not a way
    # round it. Followed without doing the unpicking it asks for, this invoice
    # would read as paid and Alpha's as unpaid, every figure still balancing:
    # the harm the bare spelling is guarded against, reached through the
    # remedy for the guard.
    outright = tmp_path / 'outright.txt'
    outright.write_text(
        (FIXTURES / 'third_invoice_giving_a_spent_split_outright.txt')
        .read_text().replace('TXN_GUID', txn_guid)
        .replace('SPLIT_A', splits['-10000/100']))
    named = runner.invoke(cli, ['import', str(book), str(outright),
                                '--include-business-objects'])
    assert named.exit_code != 0, named.output
    assert "another invoice's or bill's lot" in named.output, named.output
    assert 'Unpick it there first' in named.output, named.output
    assert _outstanding(book, 'INV-TWO-A') == '0/100'
    assert _outstanding(book, 'INV-TWO-B') == '0/100'

    # The other way a retarget finds nothing is the literal absence: a
    # transaction with no side outside the bank at all. That is a different
    # mistake — nothing is spoken for — and the remedy is not `txn_split_guid:`,
    # which can only name a split that exists.
    inside = tmp_path / 'inside.txt'
    inside.write_text((FIXTURES / 'deposit_wholly_inside_the_bank.txt').read_text())
    assert runner.invoke(cli, ['import', str(book), str(inside)]).exit_code == 0

    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        query = Query()
        query.search_for('Trans')
        query.set_book(repo.book)
        inside_guid = None
        for raw in query.run():
            transaction = Transaction(instance=raw)
            if transaction.GetDescription() == \
                    'Bank correction, both sides in one account':
                inside_guid = transaction.GetGUID().to_string()
        query.destroy()
    finally:
        repo.close()
    assert inside_guid is not None

    nowhere = tmp_path / 'nowhere.txt'
    nowhere.write_text(
        (FIXTURES / 'invoice_giving_a_transaction_with_no_other_side.txt')
        .read_text().replace('TXN_GUID', inside_guid))
    empty = runner.invoke(cli, ['import', str(book), str(nowhere),
                                '--include-business-objects'])
    assert empty.exit_code != 0, empty.output
    assert 'no split outside' in empty.output, empty.output
    assert 'already settles' not in empty.output, empty.output

    # And a file may not write the note an unpost keeps for itself. It says a
    # split is not an owner's credit, and names an invoice — which is how a
    # rebuild picks its own orphan out of a transaction carrying several — so
    # a file stating it could choose which credit an invoice spends, past the
    # guard above. The export never writes it; nor may a file.
    stated = tmp_path / 'stated_note.txt'
    stated.write_text(
        (FIXTURES / 'split_stating_an_unposts_own_note.txt').read_text())
    lots_before = _lots_on(book, 'Assets:Accounts Receivable')
    noted = runner.invoke(cli, ['import', str(book), str(stated)])
    assert 'orphaned_by_unpost' in noted.output, noted.output
    assert 'not a key a file may state' in noted.output, noted.output
    assert 'Assets:Accounts Receivable' in noted.output, noted.output
    # Refused rather than partly believed: that transaction lands nowhere,
    # while the ordinary one beside it does — which is what makes the import
    # save, so anything the refusal left behind is on disk to be found.
    assert 'Transactions: 1' in noted.output, noted.output
    assert 'Errors:       1' in noted.output, noted.output
    # And nothing was opened on the way to the refusal. The bad key is on the
    # *last* split, behind one carrying `lot_owner:` — acting on that opens a
    # lot, and `gnc_lot_new` + `xaccAccountInsertLot` are not undone by the
    # transaction's rollback. Counted rather than looked for in
    # `find-prepayments`, which lists lots by balance and so cannot see an
    # empty one left behind.
    assert _lots_on(book, 'Assets:Accounts Receivable') == lots_before, \
        'the refusal left a lot behind on the receivable'

    # And stated a level up, on the transaction. Refused on the split and kept
    # there, it is stored as ordinary metadata and written straight back out —
    # so exporting that book produces a file this tool says no file may write,
    # and the key is in a book from a file after all, which is the one thing
    # the guard is for.
    at_tx = tmp_path / 'tx_note.txt'
    at_tx.write_text(
        (FIXTURES / 'transaction_stating_an_unposts_own_note.txt').read_text())
    on_tx = runner.invoke(cli, ['import', str(book), str(at_tx)])
    assert 'not a key a file may state' in on_tx.output, on_tx.output
    # Named by its date, since no account is named a level up — the wording
    # the error table documents, so a reader grepping for their own message
    # finds one.
    assert 'the transaction dated 2026-04-03' in on_tx.output, on_tx.output
    assert 'Transactions: 1' in on_tx.output, on_tx.output
    assert 'Errors:       1' in on_tx.output, on_tx.output

    # And a book that already carries one on a transaction — every build
    # before the refusal stored it — still exports and re-imports. Refusing a
    # file that states it while writing that same file is a book with no way
    # back in, and the export is the half that has to give: nothing reads the
    # key off a transaction, so dropping it there loses nothing. Seeded the
    # way such a book got it, since the import that used to do it is now
    # refused, and this is the state that matters rather than the route.
    _put_the_note_on_a_transaction(book, 'A transaction beside the refused one')
    out = tmp_path / 'carrying.txt'
    exported = runner.invoke(cli, ['export', str(book), str(out)])
    assert exported.exit_code == 0, exported.output
    assert 'orphaned_by_unpost' not in out.read_text(), out.read_text()
    back = tmp_path / 'back.gnucash'
    restored = runner.invoke(cli, ['import', '--new', str(back), str(out),
                                   '--include-business-objects'])
    # Counted, not exit-coded: a refused transaction is collected as an error
    # and the command still exits 0, so `exit_code == 0` would hold on the
    # very file this is about — the one the export should not have written.
    assert 'Errors:       0' in restored.output, restored.output
    assert 'Errors:       1' not in restored.output, restored.output

    # And on the update path, which is the half where refusing late costs
    # something: that arm destroys and rewrites splits, and a `lot_owner:`
    # beside the bad key opens an owner lot the rollback does not undo. The
    # transaction it names is the deposit, already in the book.
    updated = tmp_path / 'update_note.txt'
    updated.write_text(
        (FIXTURES / 'update_stating_an_unposts_own_note.txt')
        .read_text().replace('TXN_GUID', txn_guid))
    edited = runner.invoke(cli, ['import', str(book), str(updated),
                                 '--strategy', 'update'])
    assert 'not a key a file may state' in edited.output, edited.output
    assert 'Assets:Accounts Receivable' in edited.output, edited.output
    # The deposit is untouched: both portions still settle their invoices, so
    # nothing was destroyed on the way to the refusal.
    assert _outstanding(book, 'INV-TWO-A') == '0/100'
    assert _outstanding(book, 'INV-TWO-B') == '0/100'

    # And a level up on that same path, where no split states anything: the
    # update arm merges what a file says into what the transaction carries, so
    # the key reaches the book by the shorter route with nothing on a split to
    # refuse. The message names the transaction, which is what the reader has
    # to go on when no account is named.
    up = tmp_path / 'update_tx_note.txt'
    up.write_text(
        (FIXTURES / 'update_stating_an_unposts_own_note_on_the_transaction.txt')
        .read_text().replace('TXN_GUID', txn_guid))
    up_edited = runner.invoke(cli, ['import', str(book), str(up),
                                    '--strategy', 'update'])
    assert 'not a key a file may state' in up_edited.output, up_edited.output
    assert 'the transaction dated 2026-05-15' in up_edited.output, up_edited.output
    assert _outstanding(book, 'INV-TWO-A') == '0/100'
    assert _outstanding(book, 'INV-TWO-B') == '0/100'
    after = runner.invoke(cli, ['export', str(book), str(tmp_path / 'after.txt')])
    assert after.exit_code == 0, after.output
    assert 'orphaned_by_unpost' not in (tmp_path / 'after.txt').read_text()


def test_a_vendor_credit_bigger_than_the_bill_is_divided_too(tmp_path):
    """The payable side, where a credit is a debit and the signs invert.

    A vendor holding 50.00 of the book's money against a 30.00 bill: 30.00
    settles it and 20.00 stays a claim on the vendor. The division writes new
    splits with signs of its own, and this side has always been where a wrong
    sign goes unnoticed — the bill reads settled and the money reappears
    somewhere else.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    assert runner.invoke(cli, ['import', '--new', str(book), ACCOUNTS]).exit_code == 0
    primer = tmp_path / 'primer.txt'
    primer.write_text((FIXTURES / 'q015_aac_primer_bill.txt').read_text())
    assert runner.invoke(cli, ['import', str(book), str(primer),
                               '--include-business-objects']).exit_code == 0

    txn_guid, split_guid = _credit_split(
        book, account_name='Liabilities.Accounts Payable', amount='5000/100')
    result = _import_fixture(runner, book, tmp_path,
                             'credit_payment_bigger_than_the_bill.txt',
                             txn_guid, split_guid)
    assert result.exit_code == 0, result.output

    assert _outstanding(book, 'BILL-CREDIT-OVERPAID') == '0/100'
    prepayments = runner.invoke(cli, ['find-prepayments', str(book)])
    assert prepayments.exit_code == 0, prepayments.output
    assert 'vendor V001' in prepayments.output, prepayments.output
    assert 'CAD 20.00' in prepayments.output, prepayments.output


def test_dividing_a_credit_that_belongs_to_no_lot_is_refused(tmp_path):
    """A credit with no owner lot cannot be divided without losing the rest.

    Attaching such a split whole is fine — that is how a rebuilt book settles
    its invoices. Dividing one is not: what is left stays in no lot, and
    `find-prepayments` walks lots, so the owner's remaining money would be
    visible nowhere at all.
    """
    from gnucash import Query, Transaction

    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    assert runner.invoke(cli, ['import', '--new', str(book), ACCOUNTS]).exit_code == 0
    deposit = tmp_path / 'deposit.txt'
    deposit.write_text((FIXTURES / 'one_bank_tx_two_owners.txt').read_text())
    assert runner.invoke(cli, ['import', str(book), str(deposit),
                               '--include-business-objects']).exit_code == 0

    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        query = Query()
        query.search_for('Trans')
        query.set_book(repo.book)
        txn_guid = split_guid = None
        for raw in query.run():
            transaction = Transaction(instance=raw)
            for split in transaction.GetSplitList():
                if str(split.GetAmount()) != '-10000/100':
                    continue
                assert split.GetLot() is None      # loose, as imported
                txn_guid = transaction.GetGUID().to_string()
                split_guid = split.GetGUID().to_string()
        query.destroy()
    finally:
        repo.close()
    assert split_guid is not None

    result = _import_fixture(runner, book, tmp_path,
                             'credit_payment_giving_a_lotless_credit.txt',
                             txn_guid, split_guid)
    assert result.exit_code != 0, result.output
    assert 'no lot' in result.output, result.output
    assert 'lot_owner' in result.output, result.output


def test_a_dividing_file_imported_twice_changes_nothing(tmp_path):
    """The file that divided a credit reads as done when it comes back.

    Dividing mints a split for the part spent, and the file names the credit
    it was carved from — so a second import found a split in the lot whose
    guid the file never mentions, called the invoice changed, and unposted it
    to rebuild: the orphan warning, the credit re-read at its new size, and a
    30.00 invoice left settled by 20.00.
    """
    runner = CliRunner()
    book = _book_with_a_credit(runner, tmp_path)
    txn_guid, split_guid = _credit_split(book)

    first = _import_fixture(runner, book, tmp_path,
                            'credit_payment_bigger_than_the_invoice.txt',
                            txn_guid, split_guid)
    assert first.exit_code == 0, first.output
    assert _outstanding(book, 'INV-CREDIT-OVERPAID') == '0/100'

    again = _import_fixture(runner, book, tmp_path,
                            'credit_payment_bigger_than_the_invoice.txt',
                            txn_guid, split_guid)
    assert again.exit_code == 0, again.output
    assert 'orphaned' not in again.output, again.output
    assert '1 unchanged' in again.output, again.output
    assert _outstanding(book, 'INV-CREDIT-OVERPAID') == '0/100'

    prepayments = runner.invoke(cli, ['find-prepayments', str(book)])
    assert 'CAD 20.00' in prepayments.output, prepayments.output


def test_every_open_credit_is_listed_whatever_gave_it_its_owner(tmp_path):
    """Two credits in the book, two credits in the listing, on every engine.

    A credit gets its owner from its lot when `lot_owner:` names one, and the
    listing asked only the transaction — which GnuCash answers for on 5.10
    (`latest`) and declines to on 4.4 (`debian11`) and 3.8 (`ubuntu20`), where
    the type it wants is read from a slot rather than derived. Those are the
    versions it was measured on; the tag names and the version numbers are not
    interchangeable. So a customer's second credit was reported by the
    book and by `fx-balances` and by nothing the user would run to find money
    owed back: one credit listed where two were held.
    """
    runner = CliRunner()
    book = _book_with_a_credit(runner, tmp_path)
    second = tmp_path / 'second.txt'
    second.write_text((FIXTURES / 'second_customer_prepayment.txt').read_text())
    assert runner.invoke(cli, ['import', str(book), str(second)]).exit_code == 0

    assert _credit_amounts(book) == {'Acme': Fraction(-50),
                                     'Acme pays ahead again': Fraction(-50)}

    prepayments = runner.invoke(cli, ['find-prepayments', str(book)])
    assert prepayments.exit_code == 0, prepayments.output
    assert 'Found 2 open pre-payment credits' in prepayments.output, prepayments.output
    assert prepayments.output.count('customer C001 (Acme)  CAD 50.00') == 2, (
        prepayments.output)


def test_dividing_a_credit_on_an_account_kept_finer_than_the_cent(tmp_path):
    """50.00 divided against 30.00 leaves 20.00, held at the account's unit.

    An account may be kept finer than its currency — a tenth of a cent, which
    this tool round-trips as `commodity_scu:` — and a same-currency split
    carries its value at that unit too, so the division reports thousandths
    where the account has them.

    The figures a file *states* are whole cents, because that is all a file
    may state: a booked amount is judged against the currency however fine the
    account is. This began as a 50.005 credit, and what that bought was a
    split whose amount sat at the account's unit while its value was rounded
    to the currency's — two figures for one sum, balancing only because both
    halves were wrong the same way.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    source = tmp_path / 'setup.txt'
    source.write_text(
        (FIXTURES / 'credit_on_an_account_kept_finer_than_the_cent.txt').read_text())
    assert runner.invoke(cli, ['import', '--new', str(book), str(source),
                               '--include-business-objects']).exit_code == 0

    txn_guid, split_guid = _credit_split(book, amount='-50000/1000')
    result = _import_fixture(runner, book, tmp_path,
                             'credit_payment_dividing_a_finer_credit.txt',
                             txn_guid, split_guid)
    assert result.exit_code == 0, result.output

    assert _outstanding(book, 'INV-FINE') == '0/1000'
    assert _credit_amounts(book) == {'Fine Grained pays ahead': Fraction(-20)}

    # The amounts divide at the account's own unit — 50.000 into 30.000 and
    # 20.000 — and the values still sum to zero, so GnuCash has no imbalance
    # to record. The denominators are the point: on this account the figures
    # are thousandths, and a division that answered in hundredths would be
    # rounding on the way past.
    figures = _credit_transaction_figures(book, 'Fine Grained pays ahead')
    assert sorted(figures['amounts']) == sorted(
        ['50000/1000', '-30000/1000', '-20000/1000']), figures
    assert figures['value_sum'] == '0', figures


def test_the_order_the_blocks_are_written_in_does_not_decide_the_book(tmp_path):
    """Credit written above the cash reads the same as cash written above it.

    A credit takes what the invoice still owes, and what it owes depends on
    the cash beside it — so a credit divided at the moment its own line is
    read takes the whole 30.00 invoice, and the 20.00 of cash below it lands
    as a prepayment nobody asked for. The file says the same thing either way
    round, and the book has to as well.
    """
    runner = CliRunner()
    book = _book_with_a_credit(runner, tmp_path)
    txn_guid, split_guid = _credit_split(book)

    result = _import_fixture(runner, book, tmp_path,
                             'credit_payment_written_before_the_cash.txt',
                             txn_guid, split_guid)
    assert result.exit_code == 0, result.output

    # 20.00 of cash and 10.00 of credit settle it; 40.00 of credit is left.
    assert _outstanding(book, 'INV-CREDIT-FIRST') == '0/100'
    assert _credit_amounts(book) == {'Acme': Fraction(-40)}


def test_cash_and_credit_on_one_invoice_read_the_same_every_time(tmp_path):
    """Appended together, and read again, in either order.

    Two paths reach the same invoice: a file that builds it, and a file that
    appends payments to one the book already has. Credit waits for cash on the
    first; it has to on the second too, or the same two blocks settle the
    invoice differently depending on whether it existed yet.

    And an invoice carrying both kinds has to read as unchanged when its own
    file comes back — the lot holds cash before credit whatever order the file
    is written in, so a comparison made position by position calls the file a
    change and rebuilds it: the cash payment orphaned, a new one minted, and
    the credit divided again, smaller each time.
    """
    runner = CliRunner()
    book = _book_with_a_credit(runner, tmp_path)
    txn_guid, split_guid = _credit_split(book)

    # The invoice exists first, unpaid, so the pair arrives by the append path.
    assert _import_fixture(
        runner, book, tmp_path,
        'credit_payment_written_before_the_cash_unpaid.txt').exit_code == 0
    appended = _import_fixture(runner, book, tmp_path,
                               'credit_payment_written_before_the_cash.txt',
                               txn_guid, split_guid)
    assert appended.exit_code == 0, appended.output
    assert _outstanding(book, 'INV-CREDIT-FIRST') == '0/100'
    assert _credit_amounts(book) == {'Acme': Fraction(-40)}

    # And the same file again is nothing to do.
    again = _import_fixture(runner, book, tmp_path,
                            'credit_payment_written_before_the_cash.txt',
                            txn_guid, split_guid)
    assert again.exit_code == 0, again.output
    assert 'orphaned' not in again.output, again.output
    assert '1 unchanged' in again.output, again.output
    assert _outstanding(book, 'INV-CREDIT-FIRST') == '0/100'
    assert _credit_amounts(book) == {'Acme': Fraction(-40)}


def test_cash_appended_below_a_credit_already_applied_is_added_not_rebuilt(tmp_path):
    """The rest of the money arrives later, and the credit stays where it is.

    An export writes the credit block first, so a user appends the cash at the
    tail — and the invoice already holds the credit. Reading the file's
    blocks cash-first while the lot holds only the credit paired the two
    wrongly, so an ordinary append became an unpost and rebuild: the orphan
    warning, fresh entry guids, and on a foreign-currency invoice whose cost basis
    something measures against, a hard refusal instead of a payment.
    """
    runner = CliRunner()
    book = _book_with_a_credit(runner, tmp_path)
    txn_guid, split_guid = _credit_split(book)

    assert _import_fixture(runner, book, tmp_path,
                           'credit_first_then_cash_appended_a.txt',
                           txn_guid, split_guid).exit_code == 0
    assert _outstanding(book, 'INV-MIX') == '5000/100'

    appended = _import_fixture(runner, book, tmp_path,
                               'credit_first_then_cash_appended_b.txt',
                               txn_guid, split_guid)
    assert appended.exit_code == 0, appended.output
    assert 'orphaned' not in appended.output, appended.output
    assert _outstanding(book, 'INV-MIX') == '0/100'


def test_a_invoice_a_credit_was_divided_into_is_not_rebuilt(tmp_path):
    """A file naming the credit at its pre-division size is refused.

    Dividing settles the invoice with the split the file named and parks
    what is left as a new one, so afterwards that split carries what it took
    — 30.00, not the 50.00 the file was written with. A file still claiming
    50.00 is describing a book that no longer exists, and is refused for
    saying so rather than rebuilt against figures nothing holds. Nothing
    reaches the file on disk: the invoice is still settled and the customer
    still has what the division left them.
    """
    runner = CliRunner()
    book = _book_with_a_credit(runner, tmp_path)
    txn_guid, split_guid = _credit_split(book)
    assert _import_fixture(runner, book, tmp_path,
                           'credit_payment_bigger_than_the_invoice.txt',
                           txn_guid, split_guid).exit_code == 0
    assert _outstanding(book, 'INV-CREDIT-OVERPAID') == '0/100'

    # Unposted first, so the credit block is reached at all: a posted
    # invoice takes a `payment:` block and nothing else, so the edited
    # invoice field this file also carries would be refused before the
    # block this test wants refused is read.
    assert runner.invoke(cli, ['unpost-invoices', str(book),
                               'INV-CREDIT-OVERPAID']).exit_code == 0
    edited = _import_fixture(runner, book, tmp_path,
                             'credit_payment_bigger_than_the_invoice_edited.txt',
                             txn_guid, split_guid)
    assert edited.exit_code != 0, edited.output
    assert 'does not match the credit split' in edited.output, edited.output
    assert 'what the export writes back' in edited.output, edited.output

    # The invoice is unposted — the step above did that, out loud — and
    # the refused import changed nothing else: the credit still holds what
    # the division left the customer, rather than having been divided
    # again against a figure the book has not held since.
    assert _credit_amounts(book) == {'Acme': Fraction(-20)}


def test_a_total_the_account_cannot_hold_is_not_posted(tmp_path):
    """An amount is a figure its account can express, or it is refused.

    A price carries as many decimals as it needs — 1.819 a litre is ordinary —
    and it is the *quantity* that makes the amount land on a figure the book
    can record: ten litres is 18.19, and the two reconcile. A total that falls
    between two of an account's units reconciles with nothing.

    GnuCash rounds it. A 30.05 total posted to a receivable kept to the tenth
    becomes 30.10, so the invoice is owed a figure it was never issued for,
    every payment afterwards is measured against the rounded one, and nothing
    in the book disagrees. Which unit an account is kept to is the user's to
    set and this tool round-trips it; what it will not do is write an amount
    that unit cannot hold.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    source = tmp_path / 'setup.txt'
    source.write_text(
        (FIXTURES / 'credit_on_a_coarsely_kept_account.txt').read_text())
    assert runner.invoke(cli, ['import', '--new', str(book), str(source),
                               '--include-business-objects']).exit_code == 0

    txn_guid, split_guid = _credit_split(book, amount='-500/10')
    result = _import_fixture(runner, book, tmp_path,
                             'credit_payment_on_a_coarsely_kept_account.txt',
                             txn_guid, split_guid)
    assert result.exit_code != 0, result.output
    assert 'cannot hold' in result.output, result.output
    assert '30.05' in result.output, result.output
    assert 'commodity_scu' in result.output, result.output

    # Nothing posted, nothing spent: the customer's credit is untouched.
    assert _credit_amounts(book) == {'Coarse Co pays ahead': Fraction(-50)}, \
        _credit_amounts(book)


def test_a_coarse_account_takes_a_total_it_can_hold(tmp_path):
    """The unit is not the objection — landing between two of them is.

    The same receivable kept to the tenth, and an invoice totalling 30.10:
    that is a figure the account holds exactly, so it posts, and a credit
    settles it to the last unit with no rounding anywhere.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    source = tmp_path / 'setup.txt'
    source.write_text(
        (FIXTURES / 'credit_on_a_coarsely_kept_account.txt').read_text())
    assert runner.invoke(cli, ['import', '--new', str(book), str(source),
                               '--include-business-objects']).exit_code == 0

    txn_guid, split_guid = _credit_split(book, amount='-500/10')
    result = _import_fixture(runner, book, tmp_path,
                             'credit_takes_the_last_unit_of_a_coarse_account.txt',
                             txn_guid, split_guid)
    assert result.exit_code == 0, result.output

    # 30.00 of cash and the last 0.10 from the credit, which keeps 49.90.
    assert _outstanding(book, 'INV-LAST-UNIT') == '0/10', \
        _outstanding(book, 'INV-LAST-UNIT')
    assert _credit_amounts(book) == {'Coarse Co pays ahead': Fraction(-499, 10)}, \
        _credit_amounts(book)


def test_the_export_of_a_divided_credit_can_be_edited_and_re_imported(tmp_path):
    """The remedy the refusal names has to work.

    A file naming the credit at its pre-division size cannot rebuild the
    invoice — that is what the refusal is for. The export names the other
    thing, the split the division minted at what it took, and editing *that*
    file has to go through: refusing it too would leave the invoice
    permanently uneditable, with the refusal pointing at a way out that is
    itself refused.
    """
    runner = CliRunner()
    book = _book_with_a_credit(runner, tmp_path)
    txn_guid, split_guid = _credit_split(book)
    assert _import_fixture(runner, book, tmp_path,
                           'credit_payment_bigger_than_the_invoice.txt',
                           txn_guid, split_guid).exit_code == 0

    exported = tmp_path / 'out.txt'
    assert runner.invoke(cli, ['export', str(book), str(exported),
                               '--include-business-objects']).exit_code == 0
    # Through the unpost the refusal names: a posted invoice takes a
    # `payment:` block and nothing else, an invoice field included. The
    # subject here is that the export of a divided credit survives the
    # round trip, which is what the import after the unpost measures.
    edited = tmp_path / 'edited.txt'
    edited.write_text(exported.read_text().replace(
        'invoice "INV-CREDIT-OVERPAID"\n',
        'invoice "INV-CREDIT-OVERPAID"\n\tnotes: "corrected"\n'))
    assert runner.invoke(cli, ['unpost-invoices', str(book),
                               'INV-CREDIT-OVERPAID']).exit_code == 0
    result = runner.invoke(cli, ['import', str(book), str(edited),
                                 '--include-business-objects'])
    assert result.exit_code == 0, result.output

    # Still settled, and the customer still has what the division left them.
    assert _outstanding(book, 'INV-CREDIT-OVERPAID') == '0/100'
    assert _credit_amounts(book) == {'Acme': Fraction(-20)}


def test_a_credit_on_a_finer_account_exports_at_that_account_s_unit(tmp_path):
    """50.000 goes out as 50.000, not 50.00 — or the file cannot come back.

    An amount is held to its account's own unit, and a payment block states an
    amount. Written at the currency's two places instead, the block says a
    figure with a different denominator from the split's, and re-importing it
    is refused for the mismatch — a book that cannot read its own export.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    source = tmp_path / 'setup.txt'
    source.write_text(
        (FIXTURES / 'credit_on_an_account_kept_finer_than_the_cent.txt').read_text())
    assert runner.invoke(cli, ['import', '--new', str(book), str(source),
                               '--include-business-objects']).exit_code == 0

    txn_guid, split_guid = _credit_split(book, amount='-50000/1000')
    assert _import_fixture(runner, book, tmp_path,
                           'credit_payment_whole_on_a_finer_account.txt',
                           txn_guid, split_guid).exit_code == 0

    exported = tmp_path / 'out.txt'
    assert runner.invoke(cli, ['export', str(book), str(exported),
                               '--include-business-objects']).exit_code == 0
    assert 'amount: 50.000' in exported.read_text(), exported.read_text()

    # And the book reads its own export back.
    rebuilt = tmp_path / 'rebuilt.gnucash'
    result = runner.invoke(cli, ['import', '--new', str(rebuilt), str(exported),
                                 '--include-business-objects'])
    assert result.exit_code == 0, result.output


def test_a_divided_credit_on_a_finer_account_reports_itself_honestly(tmp_path):
    """20.000 left over is 20.000 in the listing and in the export.

    A lot on a receivable kept to a tenth of a cent holds its figures at that
    unit, and both the `open_prepayment:` summary and `find-prepayments` wrote
    them at the currency's two places instead. The summary is read back and
    compared exactly on import, so a denominator that disagreed had the book
    warning about itself on every import.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    source = tmp_path / 'setup.txt'
    source.write_text(
        (FIXTURES / 'credit_on_an_account_kept_finer_than_the_cent.txt').read_text())
    assert runner.invoke(cli, ['import', '--new', str(book), str(source),
                               '--include-business-objects']).exit_code == 0

    txn_guid, split_guid = _credit_split(book, amount='-50000/1000')
    assert _import_fixture(runner, book, tmp_path,
                           'credit_payment_dividing_a_finer_credit.txt',
                           txn_guid, split_guid).exit_code == 0

    listing = runner.invoke(cli, ['find-prepayments', str(book)])
    assert listing.exit_code == 0, listing.output
    assert 'CAD 20.000' in listing.output, listing.output

    exported = tmp_path / 'out.txt'
    assert runner.invoke(cli, ['export', str(book), str(exported),
                               '--include-business-objects']).exit_code == 0
    assert 'amount: 20.000' in exported.read_text(), exported.read_text()

    # Read back with nothing to complain about.
    rebuilt = tmp_path / 'rebuilt.gnucash'
    result = runner.invoke(cli, ['import', '--new', str(rebuilt), str(exported),
                                 '--include-business-objects'])
    assert result.exit_code == 0, result.output
    assert 'open_prepayment' not in result.output, result.output
    assert 'declares' not in result.output, result.output


def test_the_payable_side_orders_and_refuses_the_same_way(tmp_path):
    """Cash before credit, and no rebuild after a division — on a bill.

    The ordering, the deferral and the refusals are written once and used from
    both sides, but this is the side where a wrong sign or a missed call fails
    quietly: the bill reads settled and the money turns up somewhere else.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    assert runner.invoke(cli, ['import', '--new', str(book), ACCOUNTS]).exit_code == 0
    primer = tmp_path / 'primer.txt'
    primer.write_text((FIXTURES / 'q015_aac_primer_bill.txt').read_text())
    assert runner.invoke(cli, ['import', str(book), str(primer),
                               '--include-business-objects']).exit_code == 0

    txn_guid, split_guid = _credit_split(
        book, account_name='Liabilities.Accounts Payable', amount='5000/100')

    # Credit written above the cash: 20.00 of cash and 10.00 of credit settle
    # the 30.00 bill, and 40.00 stays a claim on the vendor.
    result = _import_fixture(runner, book, tmp_path,
                             'bill_credit_written_before_the_cash.txt',
                             txn_guid, split_guid)
    assert result.exit_code == 0, result.output
    assert _outstanding(book, 'BILL-CREDIT-FIRST') == '0/100'
    prepayments = runner.invoke(cli, ['find-prepayments', str(book)])
    assert 'CAD 40.00' in prepayments.output, prepayments.output

    # And the file that divided that credit cannot rebuild the bill.
    edited = tmp_path / 'edited.txt'
    edited.write_text(
        (FIXTURES / 'bill_credit_written_before_the_cash.txt').read_text()
        .replace('TXN_GUID', txn_guid).replace('SPLIT_GUID', split_guid)
        .replace('\tcurrency: CAD\n', '\tcurrency: CAD\n\tnotes: "corrected"\n'))
    # Unposted first, so the run reaches the credit block at all: a posted
    # invoice takes a `payment:` block and nothing else, so an edited
    # invoice field is refused before the block this test wants refused
    # is ever read.
    assert runner.invoke(cli, ['unpost-bills', str(book),
                               'BILL-CREDIT-FIRST']).exit_code == 0
    after_the_unpost = _credit_amounts(book)
    refused = runner.invoke(cli, ['import', str(book), str(edited),
                                  '--include-business-objects'])
    assert refused.exit_code != 0, refused.output
    assert 'does not match the credit split' in refused.output, refused.output
    # Unposted by the step above, and nothing further by the refusal.
    assert _credit_amounts(book) == after_the_unpost


def test_a_credit_owned_by_its_lot_is_guarded_by_the_shorter_block_too(tmp_path):
    """`lot_owner:` puts the owner on the lot, and the guard has to look there.

    A block naming only `txn_guid:` moves whichever counter split the
    transaction carries. Asking only the transaction found nothing for a
    credit a file had written — its owner is on the lot, which is why
    `find-prepayments` asks the lot first — so the shorter spelling of the
    block was looser than the one naming a split, and Epsilon's invoice could
    settle out of Acme's credit.
    """
    runner = CliRunner()
    book = _book_with_a_credit(runner, tmp_path)
    second = tmp_path / 'second.txt'
    second.write_text((FIXTURES / 'second_customer_prepayment.txt').read_text())
    assert runner.invoke(cli, ['import', str(book), str(second)]).exit_code == 0
    txn_guid, _split = _credit_split(book, description='Acme pays ahead again')

    result = _import_fixture(runner, book, tmp_path,
                             'retarget_giving_only_a_lot_owned_credit.txt',
                             txn_guid)
    assert result.exit_code != 0, result.output
    assert 'C001' in result.output, result.output
    assert 'C005' in result.output, result.output

    # Acme keeps both credits.
    assert _credit_amounts(book) == {'Acme': Fraction(-50),
                                     'Acme pays ahead again': Fraction(-50)}


def test_a_sub_cent_prepayment_residual_survives_its_own_export(tmp_path):
    """`prepayment:` states 20.005, like the `amount:` above it.

    Written at the currency's two places, the residual said 20.00 for a lot
    holding 20.005 — and both readers compare it exactly, so the invoice read
    as changed on the way back: the orphan warning, an unpost, and then the
    rebuild's own check refusing over the same five thousandths.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    source = tmp_path / 'setup.txt'
    source.write_text(
        (FIXTURES / 'credit_on_an_account_kept_finer_than_the_cent.txt').read_text())
    assert runner.invoke(cli, ['import', '--new', str(book), str(source),
                               '--include-business-objects']).exit_code == 0
    assert _import_fixture(runner, book, tmp_path,
                           'overpaid_invoice_on_a_finer_account.txt').exit_code == 0

    exported = tmp_path / 'out.txt'
    assert runner.invoke(cli, ['export', str(book), str(exported),
                               '--include-business-objects']).exit_code == 0

    # Whatever the residual is — GnuCash carves it at the cent on 4.4
    # (`debian11`) and at the account's thousandth on 5.10 (`latest`) — the
    # file states it to the place the account is kept to, not truncated to the
    # currency's two.
    import re
    residuals = re.findall(r'prepayment: ([0-9.]+)', exported.read_text())
    assert residuals, exported.read_text()
    assert all(len(figure.partition('.')[2]) == 3 for figure in residuals), residuals

    again = runner.invoke(cli, ['import', str(book), str(exported),
                                '--include-business-objects'])
    assert again.exit_code == 0, again.output
    assert 'orphaned' not in again.output, again.output


def test_an_unlotted_split_of_a_single_owner_payment_is_still_guarded(tmp_path):
    """Unposting leaves a payment's split in no lot, and it stays theirs.

    A split in no lot has no owner of its own, and the guard falls back to
    the transaction where that transaction carries a single receivable split
    — one payment, one owner, nothing ambiguous about it. This is the shape
    that reaches it: an invoice paid in full and then unposted, which is
    ordinary correction work and leaves the payment split loose.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    assert runner.invoke(cli, ['import', '--new', str(book), ACCOUNTS]).exit_code == 0
    assert _import_fixture(runner, book, tmp_path,
                           'invoice_paid_exactly_by_one_split.txt').exit_code == 0
    assert runner.invoke(cli, ['unpost-invoices', str(book),
                               'INV-EXACT']).exit_code == 0

    txn_guid, split_guid = _credit_split(book, amount='-10000/100')
    result = _import_fixture(
        runner, book, tmp_path,
        'retarget_giving_an_unlotted_split_of_another_owner.txt',
        txn_guid, split_guid)
    assert result.exit_code != 0, result.output
    assert 'C-EXACT' in result.output, result.output
    assert 'C-OTHER' in result.output, result.output


def test_a_credit_already_spent_cannot_be_spent_again(tmp_path):
    """A split in an invoice's lot settled that one and is not the owner's."""
    runner = CliRunner()
    book = _book_with_a_credit(runner, tmp_path)
    # The split that settled INV-001 lives in INV-001's lot.
    from gnucash import Query, Transaction

    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        query = Query()
        query.search_for('Trans')
        query.set_book(repo.book)
        settled = None
        for raw in query.run():
            transaction = Transaction(instance=raw)
            for split in transaction.GetSplitList():
                account = split.GetAccount()
                if account is None or account.get_full_name() != 'Assets.Accounts Receivable':
                    continue
                if str(split.GetAmount()) == '-10000/100':
                    settled = (transaction.GetGUID().to_string(),
                               split.GetGUID().to_string())
        query.destroy()
    finally:
        repo.close()
    assert settled is not None

    # The block claims exactly what that split carries and belongs to the same
    # customer, so being spent already is the only thing wrong with it.
    result = _import_fixture(runner, book, tmp_path,
                             'credit_payment_of_an_already_spent_split.txt',
                             settled[0], settled[1])
    assert result.exit_code != 0, result.output
    assert 'already in another invoice' in result.output, result.output


def test_a_credit_block_states_the_memo_the_split_keeps(tmp_path):
    """`memo:` in a credit block reaches the split, and survives the save.

    The memo is written last, after the division has committed, so that the
    credit left behind keeps the memo it arrived with rather than one about
    settling this invoice. That puts the call outside any edit this code
    opened — `xaccSplitSetMemo` opens and commits its own, which is what makes
    it safe, and this is the test that says so rather than leaving it to be
    read off the C source.

    Nothing covered it before: every path this tool takes on its own is a
    re-import of an export, which states the memo the split already carries,
    so a write and a no-op are indistinguishable there. Here they are not —
    the credit arrived carrying "Overpaid", so a memo that never reached the
    file would come back as that.
    """
    runner = CliRunner()
    book = _book_with_a_credit(runner, tmp_path)
    txn_guid, split_guid = _credit_split(book)

    result = _import_fixture(runner, book, tmp_path,
                             'credit_payment_stating_its_own_memo.txt',
                             txn_guid, split_guid)
    assert result.exit_code == 0, result.output

    # Read from the saved file, not from the session that wrote it.
    exported = tmp_path / 'out.txt'
    assert runner.invoke(cli, ['export', str(book), str(exported),
                               '--include-business-objects']).exit_code == 0
    text = exported.read_text()
    block = text.split('invoice "INV-CREDIT-MEMO"')[1].split('\ninvoice ')[0]
    assert 'memo: "Settled out of credit"' in block, block
    assert 'memo: "Overpaid"' not in block, block


def test_a_credit_sees_cash_that_arrived_by_retarget(tmp_path):
    """What the invoice owes counts a retargeted payment too.

    Cash blocks are applied before credit ones, so a credit takes what is left
    after them — and how the cash got there cannot change that figure. A block
    naming an existing transaction with `txn_guid:` attaches its split with
    `xaccSplitSetLot`, which sets the split's lot but does not add it to that
    lot's split list until the book has been written and read back, so reading
    the lot to find what has been paid sees nothing of it.

    Measured against a 100.00 invoice with 80.00 retargeted onto it and a
    50.00 credit named below: the credit is measured against 100.00 rather
    than the 20.00 still owed, so it is attached whole instead of divided, the
    lot lands at −30.00 with `IsPaid` false, and the customer's 50.00 is
    inside a lot they cannot spend from. The same file written with an
    ordinary cash block settles correctly, because `ApplyPayment` adds its
    split to the lot the way the lot expects.
    """
    runner = CliRunner()
    book = _book_with_a_credit(runner, tmp_path)
    txn_guid, split_guid = _credit_split(book)

    bank = tmp_path / 'bank.txt'
    bank.write_text((FIXTURES / 'cash_by_retarget_then_credit_bank.txt').read_text())
    assert runner.invoke(cli, ['import', str(book), str(bank)]).exit_code == 0

    cash_txn_guid = _cash_txn_guid(book, '8000/100')
    text = ((FIXTURES / 'cash_by_retarget_then_credit.txt').read_text()
            .replace('CASH_TXN_GUID', cash_txn_guid)
            .replace('TXN_GUID', txn_guid).replace('SPLIT_GUID', split_guid))
    path = tmp_path / 'invoice.txt'
    path.write_text(text)
    result = runner.invoke(cli, ['import', str(book), str(path),
                                 '--include-business-objects'])
    assert result.exit_code == 0, result.output

    # 80.00 of cash and 20.00 of the credit settle it exactly, and the
    # customer keeps the 30.00 the division leaves them.
    assert _outstanding(book, 'INV-RETARGET-THEN-CREDIT') == '0/100'
    prepayments = runner.invoke(cli, ['find-prepayments', str(book)])
    assert 'CAD 30.00' in prepayments.output, prepayments.output


def test_a_deposit_the_account_cannot_express_is_not_divided(tmp_path):
    """A division that would round is refused, not rounded.

    A retarget moves the side that is not the bank, and that side need not be
    on the receivable already — off a bank feed it is an Imbalance split, and
    re-accounting it is the whole point. So the amount being divided is the
    deposit's own, which need not be a whole number of the units the receivable
    is kept to: 50.05 onto an account kept to the tenth.

    Both halves land on that account. 30.10 settles the invoice and 19.95 is
    left, which `SetAmount` rounds to 20.00 on its way in — so the halves sum
    to 50.10 against the 50.05 that was there, GnuCash answers the difference
    with an Imbalance split, and the credit parked is not the figure the file
    asserted. No division of that split is one this account can express, so
    the file is refused and told which spellings do work.

    Moving the split whole is untouched: that changes no amount, and a split
    finer than its account is a state a book can already be in.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    source = tmp_path / 'setup.txt'
    source.write_text(
        (FIXTURES / 'credit_on_a_coarsely_kept_account.txt').read_text())
    assert runner.invoke(cli, ['import', '--new', str(book), str(source),
                               '--include-business-objects']).exit_code == 0

    bank = tmp_path / 'bank.txt'
    bank.write_text(
        (FIXTURES / 'coarse_account_imbalance_deposit_bank.txt').read_text())
    assert runner.invoke(cli, ['import', str(book), str(bank)]).exit_code == 0

    text = ((FIXTURES / 'coarse_account_imbalance_deposit_invoice.txt').read_text()
            .replace('TXN_GUID', _cash_txn_guid(book, '5005/100')))
    path = tmp_path / 'invoice.txt'
    path.write_text(text)
    result = runner.invoke(cli, ['import', str(book), str(path),
                                 '--include-business-objects'])
    assert result.exit_code != 0, result.output
    assert 'cannot hold' in result.output, result.output
    assert 'txn_split_guid' in result.output, result.output

    # Nothing divided, nothing parked: the customer's own credit is all there
    # is, and the deposit is still whole.
    assert _credit_amounts(book) == {'Coarse Co pays ahead': Fraction(-50)}, \
        _credit_amounts(book)


def test_a_retarget_names_its_residual_at_the_accounts_own_unit(tmp_path):
    """The figure a message asks for has to be one the file may state.

    A receivable kept to a tenth of a cent holds 20.000, and that is the
    residual a 50.00 transaction leaves on a 30.00 invoice — the account's unit
    is a thousandth, so its figures carry three places. Written at the
    currency's two instead, the message and the check disagree about the same
    number, and the refusal quotes the expected figure through the same
    formatter, so it reads "declared … does not match the computed residual"
    with both sides printed identically. There is no figure the reader can
    write that the message names.

    Every other figure this tool writes about such an account was already at
    the account's unit — the payment block's `amount:`, the exported
    `prepayment:`, the `open_prepayment:` summary, what `find-prepayments`
    prints. These messages are read the same way and corrected from.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    source = tmp_path / 'setup.txt'
    source.write_text(
        (FIXTURES / 'credit_on_an_account_kept_finer_than_the_cent.txt').read_text())
    assert runner.invoke(cli, ['import', '--new', str(book), str(source),
                               '--include-business-objects']).exit_code == 0

    bank = tmp_path / 'bank.txt'
    bank.write_text((FIXTURES / 'finer_account_retarget_bank.txt').read_text())
    assert runner.invoke(cli, ['import', str(book), str(bank)]).exit_code == 0

    fixture = (FIXTURES / 'finer_account_retarget_invoice.txt').read_text().replace(
        'TXN_GUID', _cash_txn_guid(book, '50000/1000'))

    # No `prepayment:` at all: the message has to name the figure to add.
    asked = tmp_path / 'asked.txt'
    asked.write_text(fixture.replace('PREPAY_LINE', ''))
    result = runner.invoke(cli, ['import', str(book), str(asked),
                                 '--include-business-objects'])
    assert result.exit_code != 0, result.output
    assert 'prepayment: 20.000' in result.output, result.output
    assert '50.000' in result.output, result.output

    # And the figure it named is the one the import accepts.
    stated = tmp_path / 'stated.txt'
    stated.write_text(fixture.replace('PREPAY_LINE', '\t\tprepayment: 20.000'))
    accepted = runner.invoke(cli, ['import', str(book), str(stated),
                                   '--include-business-objects'])
    assert accepted.exit_code == 0, accepted.output
    assert _outstanding(book, 'INV-FINE-RETARGET') == '0/1000', \
        _outstanding(book, 'INV-FINE-RETARGET')

    # `find-prepayments` says the same figure the messages above do, which is
    # what makes the two readable together: the residue reads 20.000, at the
    # account's own unit, not the 20.00 the currency's two places would give.
    listed = runner.invoke(cli, ['find-prepayments', str(book)])
    assert listed.exit_code == 0, listed.output
    assert '20.000' in listed.output, listed.output


def test_a_bare_txn_guid_on_a_deposit_carrying_a_fee_is_refused(tmp_path):
    """Two splits that are not the bank's side, and only one is the payment.

    A retarget moves the side that is not the bank, so what it can pick is not
    limited to receivables: a bank feed leaves an Imbalance split there, and
    re-accounting that one is the whole point of the mechanic. But a deposit
    booked net of a fee has two such sides — the fee and the receivable — and
    nothing in a block naming only the transaction says which.

    Left to pick the first, it takes the 5.00 fee: the 100.00 invoice reads as
    settled by 5.00, the receivable split stays loose, and the money is in the
    wrong place twice over. Counting only receivable-typed splits missed it,
    because by that measure there is exactly one.
    """
    runner = CliRunner()
    book = _book_with_a_credit(runner, tmp_path)

    bank = tmp_path / 'bank.txt'
    bank.write_text((FIXTURES / 'deposit_with_a_bank_fee_bank.txt').read_text())
    assert runner.invoke(cli, ['import', str(book), str(bank)]).exit_code == 0

    text = ((FIXTURES / 'retarget_a_deposit_that_carries_a_fee.txt').read_text()
            .replace('TXN_GUID', _cash_txn_guid(book, '9500/100')))
    path = tmp_path / 'invoice.txt'
    path.write_text(text)
    result = runner.invoke(cli, ['import', str(book), str(path),
                                 '--include-business-objects'])

    assert result.exit_code != 0, result.output
    assert 'txn_split_guid' in result.output, result.output


def test_a_bare_txn_guid_on_a_shared_deposit_is_refused(tmp_path):
    """Which portion of a deposit covering two owners would move? Say so.

    A deposit paying several owners carries a receivable split for each, and
    a block naming only `txn_guid:` moves whichever the transaction happens to
    return first. Allowed through, Beta's invoice is part-paid by Alpha's
    portion — the file names a transaction and the tool picks a split out of
    it by position, which is not a decision a file can be read as having made.

    So it is refused, and the remedy is the spelling that says which:
    `txn_split_guid:`, as `one_bank_tx_two_owners_invoices.txt` writes it.

    The refusal is about the file being ambiguous, not about whose money it
    is. Judging it by owner instead is order-dependent — once Alpha's invoice
    has settled Alpha's portion, that split names an owner while Beta's is
    still loose, so the same file imports or does not depending on what ran
    before it, and the refusal names an owner whose portion is already spent.
    """
    from gnucash import Query, Transaction

    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    assert runner.invoke(cli, ['import', '--new', str(book), ACCOUNTS]).exit_code == 0
    deposit = tmp_path / 'deposit.txt'
    deposit.write_text((FIXTURES / 'two_owner_deposit_named_for_one.txt').read_text())
    assert runner.invoke(cli, ['import', str(book), str(deposit),
                               '--include-business-objects']).exit_code == 0

    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        query = Query()
        query.search_for('Trans')
        query.set_book(repo.book)
        txn_guid = None
        for raw in query.run():
            transaction = Transaction(instance=raw)
            if transaction.GetDescription() == 'Deposit covering Alpha and Beta':
                txn_guid = transaction.GetGUID().to_string()
        query.destroy()
    finally:
        repo.close()
    assert txn_guid is not None

    text = ((FIXTURES / 'second_owner_names_the_shared_deposit.txt').read_text()
            .replace('TXN_GUID', txn_guid))
    path = tmp_path / 'invoice.txt'
    path.write_text(text)
    result = runner.invoke(cli, ['import', str(book), str(path),
                                 '--include-business-objects'])
    assert result.exit_code != 0, result.output
    assert 'txn_split_guid' in result.output, result.output
    # Refused for what the file leaves unsaid, not for whose money it is.
    assert 'C-TWO-A' not in result.output, result.output


def test_a_divided_credit_keeps_the_memo_it_arrived_with(tmp_path):
    """The memo the file states belongs to the part that was spent.

    A block's `memo:` describes settling *this* invoice, so it goes on the
    split that settled it — and the credit left behind keeps the memo it
    arrived with, because it is still the same money sitting on the same
    account waiting to be spent. Which means the memo has to be written after
    the division, not before: written first, the residue is minted from a
    split already carrying "Settled out of credit" and inherits it, and the
    owner's remaining credit reads as though it had paid something.

    A 30.00 invoice against the 50.00 credit, so there is a residue at all —
    the test beside this one names a 200.00 invoice, where the credit is
    attached whole and no residue is ever made.
    """
    runner = CliRunner()
    book = _book_with_a_credit(runner, tmp_path)
    txn_guid, split_guid = _credit_split(book)

    result = _import_fixture(runner, book, tmp_path,
                             'credit_payment_stating_its_own_memo_divided.txt',
                             txn_guid, split_guid)
    assert result.exit_code == 0, result.output
    assert _outstanding(book, 'INV-CREDIT-MEMO-DIVIDED') == '0/100'

    exported = tmp_path / 'out.txt'
    assert runner.invoke(cli, ['export', str(book), str(exported),
                               '--include-business-objects']).exit_code == 0
    text = exported.read_text()

    # The two halves of the divided credit, read from the transaction section:
    # 30.00 settled the invoice and 20.00 is what the customer still has.
    spent = text.split('Assets:Accounts Receivable -30.00 CAD')[1]
    spent = spent.split('\n\tAssets')[0].split('\n2026')[0]
    assert 'Settled out of credit' in spent, spent

    residue = text.split('Assets:Accounts Receivable -20.00 CAD')[1]
    residue = residue.split('\n\tAssets')[0].split('\n2026')[0]
    assert 'Settled out of credit' not in residue, residue
    assert 'Overpaid' in residue, residue


def test_a_second_retargeted_payment_is_measured_against_what_is_left(tmp_path):
    """Two `txn_guid:` blocks on one invoice, and the second sees the first.

    A retargeted split is in its invoice's lot for every purpose except the
    lot's own split list, which does not show it until the book has been
    written and read back. Measured against `lot.get_balance()`, the second
    block on a 100.00 invoice reads it as still owing the whole 100.00 though
    80.00 has just been retargeted onto it: a 50.00 transaction is not an
    overpayment of 100.00, so no `prepayment:` is demanded and the whole split
    moves into the lot, taking it to −30.00 with the customer's 30.00 inside
    it.

    Nothing else covers this: the only other file with two `txn_guid:` blocks
    pairs one with a credit block, and a block that has GnuCash write the
    payment puts its split in the lot the way the lot expects, so a stale read
    and a fresh one agree.
    """
    runner = CliRunner()
    book = _book_with_a_credit(runner, tmp_path)

    bank = tmp_path / 'bank.txt'
    bank.write_text((FIXTURES / 'two_retargeted_cash_blocks_bank.txt').read_text())
    assert runner.invoke(cli, ['import', str(book), str(bank)]).exit_code == 0

    text = ((FIXTURES / 'two_retargeted_cash_blocks.txt').read_text()
            .replace('FIRST_TXN_GUID', _cash_txn_guid(book, '8000/100'))
            .replace('SECOND_TXN_GUID', _cash_txn_guid(book, '5000/100')))
    path = tmp_path / 'invoice.txt'
    path.write_text(text)
    result = runner.invoke(cli, ['import', str(book), str(path),
                                 '--include-business-objects'])
    assert result.exit_code == 0, result.output

    # 80.00 + 20.00 settles it, and the 30.00 over is the customer's.
    assert _outstanding(book, 'INV-TWO-RETARGETS') == '0/100'
    prepayments = runner.invoke(cli, ['find-prepayments', str(book)])
    assert 'CAD 30.00' in prepayments.output, prepayments.output


def test_a_file_stating_what_a_division_leaves_is_not_warned_about(tmp_path):
    """The `open_prepayment:` check reads what the book holds, not what a lot says.

    A file carries an account's open credits alongside the invoices that spend
    them, and the import compares the two. That comparison runs before the book
    is saved, over lots whose split lists have not caught up: moving a split
    with `xaccSplitSetLot` does not take it out of the lot it came from as far
    as `gnc_lot_get_balance` is concerned, so a credit that was just divided
    still reads at its old size.

    So a file stating the truth — 20.00 left of a 50.00 credit after a 30.00
    invoice took its share — was warned about for stating it, and told the book
    held 50.00. Everything downstream is right, which is what makes the warning
    worth fixing rather than deleting: it is the only thing that speaks, and it
    speaks wrongly.
    """
    runner = CliRunner()
    book = _book_with_a_credit(runner, tmp_path)
    txn_guid, split_guid = _credit_split(book)

    result = _import_fixture(runner, book, tmp_path,
                             'dividing_credit_and_declaring_what_is_left.txt',
                             txn_guid, split_guid)
    assert result.exit_code == 0, result.output
    assert 'warning' not in result.output, result.output
    assert _outstanding(book, 'INV-DECLARES-WHAT-IS-LEFT') == '0/100'

    # And the file it exports states the same figure it was given.
    exported = tmp_path / 'out.txt'
    assert runner.invoke(cli, ['export', str(book), str(exported),
                               '--include-business-objects']).exit_code == 0
    assert 'amount: 20.00 CAD' in exported.read_text(), exported.read_text()


def test_a_invoice_overpaid_by_a_bare_retarget_can_still_be_edited(tmp_path):
    """The splits a division made are not the file being ambiguous.

    A block naming only `txn_guid:` with a `prepayment:` divides the
    transaction: the part that settles the invoice, and the residue parked as
    the owner's credit. So the transaction that carried one receivable split
    now carries two — and asked again on a later edit, "which of these would
    this block move?" reads as unanswerable and the invoice is refused.

    It is answerable. The residue is in a lot already; the only split a
    retarget could place is one that is in none. Counting the placed ones made
    an invoice overpaid this way uneditable for good, with the remedy — name
    the split — reachable only by re-exporting.
    """
    runner = CliRunner()
    book = _book_with_a_credit(runner, tmp_path)

    bank = tmp_path / 'bank.txt'
    bank.write_text((FIXTURES / 'two_retargeted_cash_blocks_bank.txt').read_text())
    assert runner.invoke(cli, ['import', str(book), str(bank)]).exit_code == 0

    base = ((FIXTURES / 'two_retargeted_cash_blocks.txt').read_text()
            .replace('FIRST_TXN_GUID', _cash_txn_guid(book, '8000/100'))
            .replace('SECOND_TXN_GUID', _cash_txn_guid(book, '5000/100')))
    path = tmp_path / 'invoice.txt'
    path.write_text(base)
    assert runner.invoke(cli, ['import', str(book), str(path),
                               '--include-business-objects']).exit_code == 0
    assert _outstanding(book, 'INV-TWO-RETARGETS') == '0/100'

    # Now edit the invoice and import it again, through the unpost the
    # refusal names: the subject is whether an overpaid invoice can be
    # edited at all, and what a posted one takes is a `payment:` block.
    edited = tmp_path / 'edited.txt'
    edited.write_text(base.replace(
        'invoice "INV-TWO-RETARGETS"\n',
        'invoice "INV-TWO-RETARGETS"\n\tnotes: "corrected"\n'))
    assert runner.invoke(cli, ['unpost-invoices', str(book),
                               'INV-TWO-RETARGETS']).exit_code == 0
    again = runner.invoke(cli, ['import', str(book), str(edited),
                                '--include-business-objects'])
    assert again.exit_code == 0, again.output
    assert _outstanding(book, 'INV-TWO-RETARGETS') == '0/100'


def test_a_credit_on_a_shared_deposit_says_nothing_about_its_neighbour(tmp_path):
    """One owner paying ahead does not make the split beside it theirs.

    A deposit can be partly a prepayment and partly a payment: Alpha pays
    ahead, so their portion sits in a credit lot of their own, while Beta's
    portion is loose and waiting for Beta's invoice to name it. Beta names it
    the documented way, by `txn_split_guid:`.

    Read as evidence, Alpha's credit lot answers for the whole transaction and
    Beta is refused for settling out of somebody else's money — told to check
    guids that are correct. Only the other half of a *divided* credit is
    evidence about its neighbour, and that half says so on itself: the import
    writes `applied_from_credit` on the split it moves, so a split that came
    out of a credit can be told from one that never did.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    assert runner.invoke(cli, ['import', '--new', str(book), ACCOUNTS]).exit_code == 0
    deposit = tmp_path / 'deposit.txt'
    deposit.write_text(
        (FIXTURES / 'deposit_part_prepayment_part_payment.txt').read_text())
    assert runner.invoke(cli, ['import', str(book), str(deposit),
                               '--include-business-objects']).exit_code == 0

    txn_guid, split_guid = _credit_split(book, description='Deposit from Alpha and Beta',
                                         amount='-12000/100')
    result = _import_fixture(runner, book, tmp_path,
                             'beta_names_its_own_portion_of_the_deposit.txt',
                             txn_guid, split_guid)
    assert result.exit_code == 0, result.output
    assert _outstanding(book, 'INV-BETA-OWN-PORTION') == '0/100'

    # And Alpha still has the 100.00 they paid ahead.
    prepayments = runner.invoke(cli, ['find-prepayments', str(book)])
    assert 'CAD 100.00' in prepayments.output, prepayments.output


def test_the_loose_half_of_a_divided_credit_is_still_its_owners(tmp_path):
    """A split with no lot, beside one that names an owner, is that owner's.

    Dividing a credit makes two halves of one transaction: the part that
    settled an invoice, which belongs to that invoice's lot, and the credit
    left over, which sits in a lot of its owner's. Exported and read into a
    fresh book, the first arrives with no lot and no `lot_owner:` — the export
    derives that line from live lot state and an invoice's lot is not an
    owner's — while the second brings its owner with it.

    Asked about the loose half alone, the book says nothing: it is in no lot,
    and its transaction carries more than one receivable split, so the
    transaction cannot answer for it either. But the book is not silent here
    the way a shared deposit is. The credit beside it names the owner, and both
    halves came out of one credit, so another owner's invoice naming the loose
    half by guid is naming money the book can show is not theirs.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    assert runner.invoke(cli, ['import', '--new', str(book), ACCOUNTS]).exit_code == 0
    deposit = tmp_path / 'deposit.txt'
    deposit.write_text(
        (FIXTURES / 'divided_credit_shape_two_owners.txt').read_text())
    assert runner.invoke(cli, ['import', str(book), str(deposit),
                               '--include-business-objects']).exit_code == 0

    txn_guid, split_guid = _credit_split(book, description='Alpha pays ahead',
                                         amount='-4000/100')
    result = _import_fixture(runner, book, tmp_path,
                             'beta_claims_alphas_loose_credit_half.txt',
                             txn_guid, split_guid)
    assert result.exit_code != 0, result.output
    assert 'C-TWO-A' in result.output, result.output

    # And Alpha keeps both halves: the credit still reads as theirs, and the
    # loose one is still in no lot rather than in Beta's invoice.
    prepayments = runner.invoke(cli, ['find-prepayments', str(book)])
    assert 'CAD 60.00' in prepayments.output, prepayments.output
    assert 'Alpha' in prepayments.output, prepayments.output
    assert _split_lot_is_none(book, split_guid), 'the loose half was moved'


def test_two_credits_on_two_accounts_answer_for_the_loose_half_together(tmp_path):
    """Credits on different accounts are read together, not just the first one's.

    The credit beside a loose half answers for it only where it is the one
    credit there. Two of them naming two owners answer nothing — neither can
    be shown to be the credit that half came out of — and an invoice naming
    that half proceeds, the way it does beside a shared deposit.

    Which accounts they are on does not enter into it. One bank entry can
    carry a customer's advance and a vendor's prepayment, and the receivable
    and the payable are different accounts; so is the CAD receivable beside
    the USD one, which is the shape this issue is about. Reading the lots of
    whichever account came first and measuring every credit against that list
    drops the others as lots the book has let go of, leaving one owner named
    out of two — and the half is then refused to the owner whose money it may
    actually be, and handed to the other.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    assert runner.invoke(cli, ['import', '--new', str(book), ACCOUNTS]).exit_code == 0
    deposit = tmp_path / 'deposit.txt'
    deposit.write_text(
        (FIXTURES / 'divided_credit_beside_two_disagreeing_credits.txt').read_text())
    assert runner.invoke(cli, ['import', str(book), str(deposit),
                               '--include-business-objects']).exit_code == 0

    txn_guid, split_guid = _credit_split(
        book, description='Alpha pays ahead, the vendor is prepaid',
        amount='-4000/100')
    result = _import_fixture(runner, book, tmp_path,
                             'beta_names_the_half_two_credits_disagree_over.txt',
                             txn_guid, split_guid)
    assert result.exit_code == 0, result.output
    assert _outstanding(book, 'INV-BETA-DISAGREED') == '0/100'

    # And both credits are still where they were — nothing was spent to do it.
    prepayments = runner.invoke(cli, ['find-prepayments', str(book)])
    assert 'CAD 60.00' in prepayments.output, prepayments.output
    assert 'CAD 50.00' in prepayments.output, prepayments.output


def test_retargeting_onto_a_lot_already_past_zero_says_what_is_wrong(tmp_path):
    """An invoice owing less than nothing is refused for owing nothing.

    `txn_split_guid:` names a split outright and attaches it without comparing
    it to what the invoice owes, so a lot can already be past zero by the time
    a later block is read. What is still owed is then negative, and the residual
    a retarget computes from it — the transaction's amount less what the payment
    can take — comes out *larger* than the transaction: 50.00 against −20.00
    outstanding reports a residual of 70.00 and quotes "−20.00 this payment can
    take", which is arithmetic about a state nobody can act on.

    Flooring a negative figure is where it goes wrong — `int()` truncates
    toward zero, so it moves upward — but the fix is not to floor differently.
    Nothing owed and less than nothing owed are the same answer to the same
    question, and it is asked before any residual is worked out.
    """
    runner = CliRunner()
    book = _book_with_a_credit(runner, tmp_path)

    bank = tmp_path / 'bank.txt'
    bank.write_text(
        (FIXTURES / 'retarget_onto_a_lot_already_past_zero_bank.txt').read_text())
    assert runner.invoke(cli, ['import', str(book), str(bank)]).exit_code == 0

    first_txn = _cash_txn_guid(book, '5000/100', 'First')
    second_txn = _cash_txn_guid(book, '5000/100', 'Second')
    text = ((FIXTURES / 'retarget_onto_a_lot_already_past_zero.txt').read_text()
            .replace('FIRST_TXN_GUID', first_txn)
            .replace('FIRST_SPLIT_GUID', _ar_split_guid(book, first_txn))
            .replace('SECOND_TXN_GUID', second_txn))
    path = tmp_path / 'invoice.txt'
    path.write_text(text)
    result = runner.invoke(cli, ['import', str(book), str(path),
                                 '--include-business-objects'])

    assert result.exit_code != 0, result.output
    assert 'owes nothing' in result.output, result.output
    assert 'residual' not in result.output, result.output
    assert '-20.00' not in result.output, result.output


def _put_the_note_on_a_transaction(book, description):
    """Store `orphaned_by_unpost` on a transaction, as an older build would.

    The key never belonged there — everything that reads it reads it off a
    split — but nothing stopped a file putting it there, and what a file put
    there was kept. Written directly because the import that used to do it is
    refused now, and what the export has to cope with is the book, not the
    route it took.

    Read back from the saved book before returning, because everything the
    caller then asserts is about a key being *absent*: a seed that quietly did
    not take leaves the export assertion passing on a book that never carried
    one, which is exactly how the first attempt at this test proved nothing.
    """
    _write_the_note(book, description)
    stored = _transaction_metadata(book, description)
    assert stored.get('orphaned_by_unpost'), \
        f'the note was not stored on {description!r}: {stored!r}'


def _write_the_note(book, description):
    from gnucash import Query, Transaction

    from infrastructure.gnucash.kvp import get_custom_metadata, set_custom_metadata

    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.NORMAL)
    try:
        query = Query()
        query.search_for('Trans')
        query.set_book(repo.book)
        for raw in query.run():
            transaction = Transaction(instance=raw)
            if transaction.GetDescription() != description:
                continue
            metadata = dict(get_custom_metadata(transaction))
            metadata['orphaned_by_unpost'] = '0123456789abcdef0123456789abcdef'
            transaction.BeginEdit()
            set_custom_metadata(transaction, metadata)
            transaction.CommitEdit()
            query.destroy()
            repo.save()
            return
        query.destroy()
    finally:
        repo.close()
    raise AssertionError(f'no transaction described {description!r}')


def _transaction_metadata(book, description):
    """What the named transaction stores, read from the saved book."""
    from gnucash import Query, Transaction

    from infrastructure.gnucash.kvp import get_custom_metadata

    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        query = Query()
        query.search_for('Trans')
        query.set_book(repo.book)
        for raw in query.run():
            transaction = Transaction(instance=raw)
            if transaction.GetDescription() != description:
                continue
            found = dict(get_custom_metadata(transaction))
            query.destroy()
            return found
        query.destroy()
    finally:
        repo.close()
    raise AssertionError(f'no transaction described {description!r}')


def _split_lot_is_none(book, split_guid):
    """True when the split given in the block is still in no lot."""
    from gnucash import Query, Transaction

    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        query = Query()
        query.search_for('Trans')
        query.set_book(repo.book)
        for raw in query.run():
            for split in Transaction(instance=raw).GetSplitList():
                if split.GetGUID().to_string() != split_guid:
                    continue
                answer = split.GetLot() is None
                query.destroy()
                return answer
        query.destroy()
    finally:
        repo.close()
    raise AssertionError(f'split {split_guid} not found')


def _ar_split_guid(book, txn_guid):
    """The receivable-side split of the named transaction."""
    from gnucash import Query, Transaction

    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        query = Query()
        query.search_for('Trans')
        query.set_book(repo.book)
        for raw in query.run():
            transaction = Transaction(instance=raw)
            if transaction.GetGUID().to_string() != txn_guid:
                continue
            for split in transaction.GetSplitList():
                account = split.GetAccount()
                if account is not None and \
                        account.get_full_name() == 'Assets.Accounts Receivable':
                    found = split.GetGUID().to_string()
                    query.destroy()
                    return found
        query.destroy()
    finally:
        repo.close()
    raise AssertionError(f'no receivable split on {txn_guid}')


def _cash_txn_guid(book, amount, memo=None):
    """The guid of the transaction holding a bank split of `amount`.

    `memo` tells two of the same size apart, which is what a book carrying an
    instalment plan looks like.
    """
    from gnucash import Query, Transaction

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
                if account is None or account.get_full_name() != 'Assets.Bank':
                    continue
                if memo is not None and (split.GetMemo() or '') != memo:
                    continue
                if str(split.GetAmount()) == amount:
                    found = transaction.GetGUID().to_string()
                    query.destroy()
                    return found
        query.destroy()
    finally:
        repo.close()
    raise AssertionError(f'no bank split of {amount} found')
