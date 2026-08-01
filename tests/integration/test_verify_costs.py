"""`fx-balances --verify-costs`: does the book agree with itself?

A cost is derived from the ledger, never asserted by this tool, so it is only
as right as the ledger is consistent. Two things are checked: an available
balance against what its basis brought in, and a stored cost against the
transaction it sits in. Both are exact questions about figures the ledger
states.

Two inexact ones are deliberately not asked. A split's `share_price` against
its value: GnuCash stores no rate — `xaccSplitGetSharePrice` divides value by
amount on demand — so the comparison is one number against itself and cannot
fail. And whether a transaction's base-currency splits agree about its rate:
rates run forward, from a figure a file states into an amount the ledger
rounds, and reading the rounded amount back to ask which rate produced it has
no answer. Every criterion tried in that direction reported correct books.

It is a check, not a rule: it reads, reports everything it found, and exits 1
at the end if anything disagreed.
"""

from pathlib import Path

from click.testing import CliRunner

from cli.main import cli
from infrastructure.gnucash.kvp import get_custom_metadata, set_custom_metadata
from infrastructure.gnucash.utils import find_account
from repositories.gnucash_repository import GnuCashRepository, SessionMode


def _verify(runner, book):
    return runner.invoke(cli, ['fx-balances', str(book), '--verify-costs'])


def test_a_book_this_tool_wrote_agrees_with_itself(tmp_path):
    """Every fixture cost checks out against the ledger it came from.

    Bought, borrowed, invoiced, billed, a settlement whose rate does not
    divide into cents, and the three overpayments where two rates meet in one
    entry. Nothing this tool writes disagrees with itself.
    """
    runner = CliRunner()
    for fixture, extra in (
        ('tests/fixtures/fx_buy_and_borrow_usd.txt', []),
        ('tests/fixtures/fx_usd_invoice_cad_income.txt',
         ['--fx-rates', 'tests/fixtures/fx_rates_usd_dated.yaml']),
        ('tests/fixtures/fx_usd_bill_cad_expense.txt',
         ['--fx-rates', 'tests/fixtures/fx_rates_usd_dated.yaml']),
        ('tests/fixtures/fx_invoice_partial_settlement_half_cent.txt',
         ['--fx-rates', 'tests/fixtures/fx_rates_usd_half_cent.yaml']),
        # The overpayments, where two rates meet in one entry: the record's
        # for what it settles, the payment's for what it leaves behind.
        ('tests/fixtures/fx_invoice_usd_overpaid_into_cad_bank.txt',
         ['--fx-rates', 'tests/fixtures/fx_rates_usd_dated.yaml']),
        ('tests/fixtures/fx_bill_usd_overpaid_into_cad_bank.txt',
         ['--fx-rates', 'tests/fixtures/fx_rates_usd_dated.yaml']),
        ('tests/fixtures/fx_invoice_usd_overpaid_into_usd_bank.txt',
         ['--fx-rates', 'tests/fixtures/fx_rates_usd_dated.yaml']),
    ):
        book = tmp_path / (fixture.rsplit('/', 1)[-1] + '.gnucash')
        result = runner.invoke(cli, ['import', '--new', str(book), fixture,
                                     '--include-business-objects', *extra])
        assert result.exit_code == 0, result.output

        checked = _verify(runner, book)
        assert checked.exit_code == 0, f'{fixture}:\n{checked.output}'
        assert 'every cost agrees' in checked.output, f'{fixture}:\n{checked.output}'


def test_a_stored_cost_that_drifted_from_the_transaction_is_reported(tmp_path):
    """The copy is no longer believed, so something has to say it is there.

    A `cost_basis_cost` beside a transaction that states its own cost is not
    used — the transaction wins — which means it can sit in a book saying
    something false and change nothing. This is what says so, with both
    figures, and it is why the check exists at all: the fix that stopped the
    copy from being believed also stopped it from being visible.

    The KVP is written directly here because the importer refuses a file that
    states one; a book can still carry one from a hand edit or an older tool.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    result = runner.invoke(cli, ['import', '--new', str(book),
                                 'tests/fixtures/fx_buy_and_borrow_usd.txt'])
    assert result.exit_code == 0, result.output
    assert _verify(runner, book).exit_code == 0

    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.NORMAL)
    try:
        account = find_account(repo.book.get_root_account(), 'Assets:Bank:USD')
        split = account.GetSplitList()[0]
        transaction = split.GetParent()
        transaction.BeginEdit()
        metadata = dict(get_custom_metadata(split))
        metadata['cost_basis_cost'] = '9.99 CAD/USD'
        set_custom_metadata(split, metadata)
        transaction.CommitEdit()
        repo.save()
    finally:
        repo.close()

    checked = _verify(runner, book)
    assert checked.exit_code == 1, checked.output
    assert '1 disagree' in checked.output, checked.output
    assert 'the transaction says 1.35' in checked.output, checked.output

    # The whole computation, not just the verdict: both guids, the figures the
    # ledger carries, every factor, and both answers with the one used.
    assert 'split guid' in checked.output and 'tx guid' in checked.output, checked.output
    assert 'value / amount   1.35' in checked.output, checked.output
    assert 'computed cost    1.35 CAD/USD' in checked.output, checked.output
    assert 'stored cost      9.99 CAD/USD' in checked.output, checked.output
    assert 'used             1.35 CAD/USD' in checked.output, checked.output

    # And the listing is still printed — the check reports at the end rather
    # than exiting on the first thing it finds.
    assert 'Available USD: 200.00' in checked.output, checked.output
    assert '1.35 CAD/USD' in checked.output, checked.output


def test_every_disagreement_is_reported_before_the_exit(tmp_path):
    """Two bad bases, both reported, one exit code.

    A check that stopped at the first would answer "is anything wrong" while
    hiding what — and a book is verified precisely to learn everything wrong
    with it in one pass.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    result = runner.invoke(cli, ['import', '--new', str(book),
                                 'tests/fixtures/fx_buy_and_borrow_usd.txt'])
    assert result.exit_code == 0, result.output

    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.NORMAL)
    try:
        account = find_account(repo.book.get_root_account(), 'Assets:Bank:USD')
        for split, wrong in zip(account.GetSplitList(),
                                ('9.99 CAD/USD', '0.01 CAD/USD')):
            transaction = split.GetParent()
            transaction.BeginEdit()
            metadata = dict(get_custom_metadata(split))
            metadata['cost_basis_cost'] = wrong
            set_custom_metadata(split, metadata)
            transaction.CommitEdit()
        repo.save()
    finally:
        repo.close()

    checked = _verify(runner, book)
    assert checked.exit_code == 1, checked.output
    assert '2 disagree' in checked.output, checked.output
    assert '9.99' in checked.output and '0.01' in checked.output, checked.output


def test_the_cost_pools_every_base_split_rather_than_judging_them(tmp_path):
    """Whether the CAD lines "agree" is not a question the ledger can answer.

    A transaction whose CAD revenue implies 1.4 and whose CAD fee implies 1.25
    looks inconsistent, and it may well be — but the same shape arises from
    rounding alone, and nothing in the rounded figures separates the two. So
    the cost is the aggregate of every base-currency split, which is one
    number whatever order they are read in, and no verdict is passed on them.

    Three criteria for such a verdict were tried and each reported correct
    books: the ratios against each other (every taxed foreign invoice), each
    against the pooled rate (a bill of 1.819 CAD for 1.30 USD beside 5.00 for
    3.57, which 1.3992 produces exactly), and the windows the rounding leaves.
    A rate in this tool is an exact figure a file states; inferring one back
    out of rounded amounts and then testing it is a guess with a tax figure
    resting on it.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    result = runner.invoke(
        cli, ['import', '--new', str(book),
              'tests/fixtures/fx_two_base_splits_at_different_rates.txt'])
    assert result.exit_code == 0, result.output

    # No verdict, and one cost: 150.00 CAD over 108.00 USD, whichever of the
    # two CAD lines is read first.
    checked = _verify(runner, book)
    assert checked.exit_code == 0, checked.output
    assert 'every cost agrees' in checked.output, checked.output
    assert '25/18 CAD/USD' in checked.output, checked.output


def test_a_taxed_foreign_invoice_is_not_read_as_two_rates(tmp_path):
    """Rounding is not disagreement.

    A taxed USD invoice converts its CAD income and its CAD tax at one rate
    and rounds each to the cent on its own, so their amount-over-value ratios
    differ in the last digits — 1.40006 against 1.39940 on 33.33 USD at 10%.
    Comparing those ratios to each other calls every taxed foreign invoice
    inconsistent, which is the ordinary shape of the thing this feature is
    for. The rate is applied back to each split and rounded the way its value
    was instead.

    The cost is the whole transaction's rate as well, not one split's: reading
    the first CAD split it found priced this basis at 1.3994 from the tax
    line, and a book that listed its tax split second would have said 1.40006.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    result = runner.invoke(
        cli, ['import', '--new', str(book),
              'tests/fixtures/fx_usd_invoice_with_tax.txt',
              '--include-business-objects',
              '--fx-rates', 'tests/fixtures/fx_rates_usd_dated.yaml'])
    assert result.exit_code == 0, result.output

    checked = _verify(runner, book)
    assert checked.exit_code == 0, checked.output
    assert 'every cost agrees' in checked.output, checked.output

    # 46.66 + 4.66 CAD against 33.33 + 3.33 USD, which is 51.32 / 36.66.
    listing = runner.invoke(cli, ['fx-balances', str(book)]).output
    assert '2566/1833 CAD/USD' in listing, listing
    assert '36.66 USD' in listing, listing


def test_a_balance_above_what_arrived_or_below_zero_is_reported(tmp_path):
    """Two exact comparisons, against two figures the book already holds.

    A balance falls only by what a sale takes and rises only by what one gives
    back, so a balance above the amount its split brought in is currency
    offered that never arrived, and one below zero is a sale no ledger
    records. Nothing is inferred and nothing is tolerated: the bounds are the
    split's own amount and zero.

    A file stating either is refused now
    (`tests/integration/test_stated_balance_is_checked.py`), so these are
    written straight onto the split — which is how a book comes by one
    anyway: a GUI edit, or a version of this tool that did not check.
    """
    runner = CliRunner()
    # The third is past its bound by a fraction of a cent and by nothing else,
    # so a message that rounded it would read "100.00 against the 100.00" and
    # report nothing at all. It is written as the fraction it is, the way every
    # figure this tool cannot express in its currency's smallest unit is.
    for stated, expected in (('150.00', '150.00'), ('-10.00', '-10.00'),
                             ('100.001', '100001/1000')):
        book = tmp_path / f'book{stated}.gnucash'
        result = runner.invoke(cli, ['import', '--new', str(book),
                                     'tests/fixtures/fx_buy_and_borrow_usd.txt'])
        assert result.exit_code == 0, result.output

        repo = GnuCashRepository(str(book))
        repo.open(mode=SessionMode.NORMAL)
        try:
            account = find_account(repo.book.get_root_account(), 'Assets:Bank:USD')
            split = account.GetSplitList()[0]
            transaction = split.GetParent()
            transaction.BeginEdit()
            metadata = dict(get_custom_metadata(split))
            metadata['cost_basis_available'] = stated
            set_custom_metadata(split, metadata)
            transaction.CommitEdit()
            repo.save()
        finally:
            repo.close()

        checked = _verify(runner, book)
        assert checked.exit_code == 1, checked.output
        assert 'available balance is' in checked.output, checked.output
        assert expected in checked.output, checked.output


def test_a_basis_that_cannot_be_read_is_reported_not_crashed_on(tmp_path):
    """The listing survives a basis whose own figures do not parse.

    A `cost_basis_cost` that is not a cost takes the whole listing down if it
    is read while building it — so the command dies with a traceback at
    exactly the moment there is something in the book worth looking at. It is
    listed as unreadable instead, and `--verify-costs` says why.

    The split poisoned here is the overpaid credit, which is the one basis
    whose cost genuinely comes from that KVP: its transaction is USD
    throughout and prices nothing. On a split the transaction *can* price, a
    malformed KVP is never read at all — the transaction is consulted first —
    so it could not reach this path.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    result = runner.invoke(
        cli, ['import', '--new', str(book),
              'tests/fixtures/fx_invoice_usd_overpaid_into_usd_bank.txt',
              '--include-business-objects',
              '--fx-rates', 'tests/fixtures/fx_rates_usd_dated.yaml'])
    assert result.exit_code == 0, result.output

    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.NORMAL)
    try:
        account = find_account(repo.book.get_root_account(),
                               'Assets:Accounts Receivable USD')
        split = next(s for s in account.GetSplitList()
                     if 'cost_basis_cost' in get_custom_metadata(s))
        transaction = split.GetParent()
        transaction.BeginEdit()
        metadata = dict(get_custom_metadata(split))
        metadata['cost_basis_cost'] = 'oops'
        set_custom_metadata(split, metadata)
        transaction.CommitEdit()
        repo.save()
    finally:
        repo.close()

    # Without the flag: the listing still comes out, and says where to look.
    listing = runner.invoke(cli, ['fx-balances', str(book)])
    assert listing.exit_code == 0, listing.output
    assert 'unreadable' in listing.output, listing.output
    assert '--verify-costs' in listing.output, listing.output
    assert '1.4 CAD/USD' in listing.output, listing.output      # the invoice's

    # With it: the reason, on the split it is on, with the traceback.
    checked = _verify(runner, book)
    assert checked.exit_code == 1, checked.output
    assert 'could not be read at all' in checked.output, checked.output
    assert "reads 'oops'" in checked.output, checked.output
    assert 'Traceback' in checked.output, checked.output

    # And the book exports, with the bad figure in the file where it can be
    # corrected. This is the route the report above tells its reader to take,
    # so asking whether the split is a cost basis on the way out — which reads
    # the very cost that will not parse — took the export down with it.
    exported = tmp_path / 'out.txt'
    export = runner.invoke(cli, ['export', str(book), str(exported)])
    assert export.exit_code == 0, export.output
    assert "cost_basis_cost: \"oops\"" in exported.read_text(), exported.read_text()


def test_the_count_is_what_was_checked_not_what_the_listing_shows(tmp_path):
    """Filtering a listing narrows what is shown, not what is verified.

    `--currency HKD` on a book of USD bases lists nothing, and the check still
    walks every basis in the book. Reporting the filtered count said "checked
    0" above a report of what those 0 bases got wrong.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    assert runner.invoke(cli, ['import', '--new', str(book),
                               'tests/fixtures/fx_buy_and_borrow_usd.txt']).exit_code == 0

    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.NORMAL)
    try:
        account = find_account(repo.book.get_root_account(), 'Assets:Bank:USD')
        split = account.GetSplitList()[0]
        transaction = split.GetParent()
        transaction.BeginEdit()
        metadata = dict(get_custom_metadata(split))
        metadata['cost_basis_available'] = '150.00'
        set_custom_metadata(split, metadata)
        transaction.CommitEdit()
        repo.save()
    finally:
        repo.close()

    checked = runner.invoke(cli, ['fx-balances', str(book), '--verify-costs',
                                  '--currency', 'HKD'])
    assert checked.exit_code == 1, checked.output
    assert 'No foreign-currency cost bases found' in checked.output, checked.output
    assert 'Checked 2 cost basis(es)' in checked.output, checked.output


def test_the_one_stored_cost_survives_a_round_trip(tmp_path):
    """Export, import into a fresh book, and the borrowed cost is still there.

    `cost_basis_cost` is written for exactly one shape — a USD invoice
    overpaid from a USD bank, where no split carries a CAD figure — and it is
    the only cost that would be lost if the KVP did not survive. The refusal
    that now guards a stated cost sits close enough to this path that a change
    could stop it round-tripping without any other test noticing.
    """
    runner = CliRunner()
    first = tmp_path / 'first.gnucash'
    result = runner.invoke(
        cli, ['import', '--new', str(first),
              'tests/fixtures/fx_invoice_usd_overpaid_into_usd_bank.txt',
              '--include-business-objects',
              '--fx-rates', 'tests/fixtures/fx_rates_usd_dated.yaml'])
    assert result.exit_code == 0, result.output

    exported = tmp_path / 'out.txt'
    assert runner.invoke(cli, ['export', str(first), str(exported),
                               '--include-business-objects']).exit_code == 0
    assert 'cost_basis_cost: "1.4 CAD/USD"' in exported.read_text(), exported.read_text()

    second = tmp_path / 'second.gnucash'
    result = runner.invoke(cli, ['import', '--new', str(second), str(exported),
                                 '--include-business-objects'])
    assert result.exit_code == 0, result.output

    listing = runner.invoke(cli, ['fx-balances', str(second)]).output
    assert 'Available USD: 200.00' in listing, listing
    assert '1.4 CAD/USD' in listing, listing
    assert _verify(runner, second).exit_code == 0, _verify(runner, second).output


def test_a_currency_worth_less_than_a_dollar_is_not_read_as_two_rates(tmp_path):
    """The direction the check measures in decides whether it is usable.

    A taxed HKD invoice at 0.1754 CAD/HKD carries CAD figures made from the
    HKD ones and rounded to the cent — 58.47 and 5.85. Half a CAD cent is a
    fifth of a HKD cent the other way round, so reading the rate backwards,
    from CAD into HKD, says the income split should be 333.35 HKD where the
    ledger holds 333.33, and every book in a currency worth less than a
    Canadian dollar reports as converted at two rates.

    Measured the way the figures were made — HKD into CAD, rounded to the cent
    — it agrees. The USD case passes either way round, which is why this
    sibling exists: the tool supports currencies on both sides of parity.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    result = runner.invoke(
        cli, ['import', '--new', str(book),
              'tests/fixtures/fx_hkd_invoice_with_tax.txt',
              '--include-business-objects',
              '--fx-rates', 'tests/fixtures/fx_rates_hkd_dated.yaml'])
    assert result.exit_code == 0, result.output

    checked = _verify(runner, book)
    assert checked.exit_code == 0, checked.output
    assert 'every cost agrees' in checked.output, checked.output
    assert 'Available HKD: 366.66' in checked.output, checked.output


def test_a_spending_split_is_not_a_basis_however_its_cost_reads(tmp_path):
    """What a split cannot be, it cannot be an unreadable one of either.

    A split that moves foreign currency out establishes nothing, so a
    `cost_basis_cost` on it is inert whatever it says. Reading that cost
    before asking which direction the split moves raised inside the guard,
    which the listing then caught and reported as an unreadable cost basis —
    exit 1, for a spend that is no basis at all.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    result = runner.invoke(
        cli, ['import', '--new', str(book),
              'tests/fixtures/usd_moved_between_two_usd_accounts.txt'])
    assert result.exit_code == 0, result.output

    # Written by hand, because the importer refuses such a line: a book can
    # still carry one from a GUI edit or an older tool.
    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.NORMAL)
    try:
        account = find_account(repo.book.get_root_account(), 'Assets:Bank:USD')
        split = next(s for s in account.GetSplitList()
                     if s.GetAmount().num() < 0)
        transaction = split.GetParent()
        transaction.BeginEdit()
        set_custom_metadata(split, {'cost_basis_cost': 'oops'})
        transaction.CommitEdit()
        repo.save()
    finally:
        repo.close()

    listing = runner.invoke(cli, ['fx-balances', str(book)])
    assert listing.exit_code == 0, listing.output
    assert 'unreadable' not in listing.output, listing.output

    checked = _verify(runner, book)
    assert checked.exit_code == 0, checked.output
    assert 'could not be read' not in checked.output, checked.output

    # And the book can still be exported and read back. Nothing reads that
    # cost, `--verify-costs` says nothing about it, and the transaction is in
    # one currency throughout so there is no derived cost to notice it by —
    # written out, it made a file this tool refuses, which is the one route a
    # user has out of a stored cost that should not be there.
    exported = tmp_path / 'out.txt'
    assert runner.invoke(cli, ['export', str(book), str(exported)]).exit_code == 0
    assert 'cost_basis_cost' not in exported.read_text(), exported.read_text()
    rebuilt = tmp_path / 'rebuilt.gnucash'
    back = runner.invoke(cli, ['import', '--new', str(rebuilt), str(exported)])
    assert back.exit_code == 0, back.output


def test_a_cost_stated_on_a_security_is_refused(tmp_path):
    """Shares are counted and priced, not converted, so they have no cost.

    A stated balance on a security split has always been refused; a stated
    cost went in and was stored, on a split `establishes_cost_basis` then
    ignores by namespace. In a transaction with no base-currency figure in it
    there is nothing to notice the stored figure by either, so `50 CAD/USTECH`
    sat in the book saying what a share cost, read by nothing.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    assert runner.invoke(cli, ['import', '--new', str(book),
                               'tests/fixtures/foreign_security_book.txt']).exit_code == 0

    result = runner.invoke(cli, ['import', str(book),
                                 'tests/fixtures/stated_cost_on_a_security_split.txt'])
    assert 'security rather than a currency' in result.output, result.output
    assert 'Transactions: 0' in result.output, result.output
    assert 'Errors:       1' in result.output, result.output


def test_two_bases_in_one_transaction_share_its_cost(tmp_path):
    """One transaction, one rate, however many bases it establishes.

    Both USD splits are priced through the same CAD lines, so both cost the
    same — the aggregate of those lines — and neither depends on which of them
    is read first or on which basis is looked at.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    result = runner.invoke(cli, ['import', '--new', str(book),
                                 'tests/fixtures/fx_two_bases_and_two_rates.txt'])
    assert result.exit_code == 0, result.output

    # Both bases are priced through the same CAD lines, so both carry the same
    # cost — the aggregate — and neither is judged against the other.
    listing = runner.invoke(cli, ['fx-balances', str(book)]).output
    assert listing.count('25/18 CAD/USD') == 2, listing
    checked = _verify(runner, book)
    assert checked.exit_code == 0, checked.output
    assert 'Checked 2 cost basis(es)' in checked.output, checked.output


def test_a_stored_cost_that_does_not_parse_is_reported_as_what_it_is(tmp_path):
    """A line nothing reads cannot make a whole basis unreadable.

    `cost_of` never reaches a stored cost on a split its transaction prices,
    so a malformed one there changes no figure in the book. The check reads it
    deliberately, and reading it must not turn a basis whose amount, value,
    rate and derived cost are all perfectly legible into "could not be read at
    all" — nor count it twice, once for being examined and once for failing.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    result = runner.invoke(cli, ['import', '--new', str(book),
                                 'tests/fixtures/fx_buy_and_borrow_usd.txt'])
    assert result.exit_code == 0, result.output

    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.NORMAL)
    try:
        account = find_account(repo.book.get_root_account(), 'Assets:Bank:USD')
        split = account.GetSplitList()[0]
        transaction = split.GetParent()
        transaction.BeginEdit()
        metadata = dict(get_custom_metadata(split))
        metadata['cost_basis_cost'] = 'oops'
        set_custom_metadata(split, metadata)
        transaction.CommitEdit()
        repo.save()
    finally:
        repo.close()

    checked = _verify(runner, book)
    assert checked.exit_code == 1, checked.output
    assert 'Checked 2 cost basis(es); 1 disagree' in checked.output, checked.output
    assert 'could not be read at all' not in checked.output, checked.output
    assert "reads 'oops'" in checked.output, checked.output
    assert 'which is what is used' in checked.output, checked.output
    # The rest of the row is there, because the rest of the row is readable.
    assert 'computed cost    1.35 CAD/USD' in checked.output, checked.output

    # And the listing agrees with it rather than contradicting it.
    listing = runner.invoke(cli, ['fx-balances', str(book)])
    assert listing.exit_code == 0, listing.output
    assert 'unreadable' not in listing.output, listing.output
    assert '1.35 CAD/USD' in listing.output, listing.output


def test_a_split_held_finer_than_the_cent_is_measured_at_its_own_unit(tmp_path):
    """An account can be kept finer than its currency, and its splits with it.

    Fuel is priced to a tenth of a cent, so its expense account is denominated
    at 1/1000 and one litre lands on 1.819 CAD — an amount the currency cannot
    hold and the account can, which is the whole reason `commodity_scu:`
    exists. On an ordinary CAD account the same figure is refused.

    Applying the transaction's rate back to such a split has to round the way
    the split is held. Rounded to the cent instead, 1.819 was measured against
    an implied 1.82, a correct book reported as converted at two rates — and
    the message, rounding both for display, printed "1.82 and it carries 1.82".
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    result = runner.invoke(
        cli, ['import', '--new', str(book),
              'tests/fixtures/fx_usd_bill_with_a_finer_cad_account.txt'])
    assert result.exit_code == 0, result.output

    checked = _verify(runner, book)
    assert checked.exit_code == 0, checked.output
    assert 'every cost agrees' in checked.output, checked.output


def test_a_reported_basis_shows_its_figures_at_the_unit_they_are_held_to(tmp_path):
    """What the cost came from, written as the ledger holds it.

    A basis reported for anything at all prints the base-currency splits its
    cost was pooled from. One of these is on an account kept to thousandths,
    where the ledger holds 1.819 CAD: printed at the cent it reads 1.82, a
    figure the book does not contain, and nothing tells a reader that account
    apart from an ordinary CAD one — so the unit is named.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    result = runner.invoke(
        cli, ['import', '--new', str(book),
              'tests/fixtures/fx_usd_bill_two_cad_lines_one_finer.txt'])
    assert result.exit_code == 0, result.output

    # Something to report: a stored cost that drifted from the transaction.
    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.NORMAL)
    try:
        account = find_account(repo.book.get_root_account(),
                               'Liabilities:Accounts Payable USD')
        split = account.GetSplitList()[0]
        transaction = split.GetParent()
        transaction.BeginEdit()
        metadata = dict(get_custom_metadata(split))
        metadata['cost_basis_cost'] = '9.99 CAD/USD'
        set_custom_metadata(split, metadata)
        transaction.CommitEdit()
        repo.save()
    finally:
        repo.close()

    checked = _verify(runner, book)
    assert checked.exit_code == 1, checked.output
    assert 'Expenses:Fuel: 1.819 CAD for 1.30 USD' in checked.output, checked.output
    assert 'account held to 0.001' in checked.output, checked.output
    assert 'Expenses:Parts: 5.00 CAD for 3.57 USD' in checked.output, checked.output


def test_an_unreadable_basis_is_mentioned_even_when_a_filter_hides_it(tmp_path):
    """A filter narrows the listing, not what the book contains.

    `--currency HKD` on a USD book prints "no cost bases found", and that is
    the listing this reader most needs told a basis could not be read at all —
    they cannot see it to notice. The notice covers the whole book, like the
    check does.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    result = runner.invoke(
        cli, ['import', '--new', str(book),
              'tests/fixtures/fx_invoice_usd_overpaid_into_usd_bank.txt',
              '--include-business-objects',
              '--fx-rates', 'tests/fixtures/fx_rates_usd_dated.yaml'])
    assert result.exit_code == 0, result.output

    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.NORMAL)
    try:
        account = find_account(repo.book.get_root_account(),
                               'Assets:Accounts Receivable USD')
        split = next(s for s in account.GetSplitList()
                     if 'cost_basis_cost' in get_custom_metadata(s))
        transaction = split.GetParent()
        transaction.BeginEdit()
        metadata = dict(get_custom_metadata(split))
        metadata['cost_basis_cost'] = 'oops'
        set_custom_metadata(split, metadata)
        transaction.CommitEdit()
        repo.save()
    finally:
        repo.close()

    filtered = runner.invoke(cli, ['fx-balances', str(book), '--currency', 'HKD'])
    assert filtered.exit_code == 0, filtered.output
    assert 'No foreign-currency cost bases found' in filtered.output, filtered.output
    assert 'could not be read' in filtered.output, filtered.output
    assert '--verify-costs' in filtered.output, filtered.output


def test_a_book_with_a_drifted_cost_can_still_be_exported_and_reimported(tmp_path):
    """The correction route has to survive the thing it corrects.

    `--verify-costs` tells a user a stored cost has drifted from its
    transaction, and export → import is how this tool says to fix a book. The
    exporter wrote that copy back out verbatim and the importer then refused
    its own file — "drop the line, or correct the split's own figures", to
    someone who never typed it.

    The copy is dropped on the way out, since nothing reads it: what the
    transaction prices, the transaction says. A cost on a split the
    transaction cannot price is the one that matters, and it round-trips
    (see test_the_one_stored_cost_survives_a_round_trip).
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    result = runner.invoke(cli, ['import', '--new', str(book),
                                 'tests/fixtures/fx_buy_and_borrow_usd.txt'])
    assert result.exit_code == 0, result.output

    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.NORMAL)
    try:
        account = find_account(repo.book.get_root_account(), 'Assets:Bank:USD')
        split = account.GetSplitList()[0]
        transaction = split.GetParent()
        transaction.BeginEdit()
        metadata = dict(get_custom_metadata(split))
        metadata['cost_basis_cost'] = '9.99 CAD/USD'
        set_custom_metadata(split, metadata)
        transaction.CommitEdit()
        repo.save()
    finally:
        repo.close()

    assert _verify(runner, book).exit_code == 1        # the drift is reported

    exported = tmp_path / 'out.txt'
    assert runner.invoke(cli, ['export', str(book), str(exported)]).exit_code == 0
    assert 'cost_basis_cost' not in exported.read_text(), exported.read_text()

    fresh = tmp_path / 'fresh.gnucash'
    result = runner.invoke(cli, ['import', '--new', str(fresh), str(exported)])
    assert result.exit_code == 0, result.output
    assert 'Errors:       0' in result.output, result.output

    # And the corrected book keeps the cost the transaction always stated.
    listing = runner.invoke(cli, ['fx-balances', str(fresh)]).output
    assert '1.35 CAD/USD' in listing, listing
    assert '9.99' not in listing, listing
    assert _verify(runner, fresh).exit_code == 0


def test_a_balance_that_will_not_parse_is_reported_not_read_as_untracked(tmp_path):
    """The one balance-side corruption the check could not see.

    A `cost_basis_available` that is not a number reads as no balance at all,
    so the basis lists as `untracked` — over a message saying this tool never
    wrote a balance for it, about a split whose balance it wrote and something
    has since broken. Nothing could be sold against it and nothing said why.

    A stored *cost* that will not parse has always been reported. This is the
    same fault on the other key, and it now gets the same treatment.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    result = runner.invoke(cli, ['import', '--new', str(book),
                                 'tests/fixtures/fx_buy_and_borrow_usd.txt'])
    assert result.exit_code == 0, result.output

    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.NORMAL)
    try:
        account = find_account(repo.book.get_root_account(), 'Assets:Bank:USD')
        split = account.GetSplitList()[0]
        transaction = split.GetParent()
        transaction.BeginEdit()
        metadata = dict(get_custom_metadata(split))
        metadata['cost_basis_available'] = '60.00.00'
        set_custom_metadata(split, metadata)
        transaction.CommitEdit()
        repo.save()
    finally:
        repo.close()

    # It still reads as untracked, because it is: nothing can be sold against
    # a balance that cannot be read.
    listing = runner.invoke(cli, ['fx-balances', str(book)]).output
    assert 'untracked' in listing, listing

    checked = _verify(runner, book)
    assert checked.exit_code == 1, checked.output
    assert 'cost_basis_available' in checked.output, checked.output
    assert "'60.00.00'" in checked.output, checked.output
    assert 'not a number' in checked.output, checked.output
