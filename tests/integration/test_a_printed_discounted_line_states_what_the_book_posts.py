"""A printed invoice's figures are the figures its posting splits carry.

`print-invoice` writes `entry_amount:`, `entry_tax:`, a `breakdown:` block
per tax account and the three `invoice_*` totals. Those were computed here as
quantity × price, which is right for a line with no discount and wrong for
every line with one — and the discount now reaches the book through the
ledger, so the disagreement is reachable from a file.

Measured on GnuCash 5.10, 10 × 100.00 discounted 10 per cent against a 10 per
cent tax table: `pretax` posts 900.00 + 90.00, `sametime` posts 900.00 +
100.00, and `posttax` posts 890.00 + 100.00. Quantity × price said
1000.00 + 100.00 for all three, so an invoice handed to a customer stated
1000.00 while its own A/R split said 990.00 — and `--format pdf`, drawn by
GnuCash's own report, printed the right figure beside the wrong one from the
same command.

Every assertion here reads the book rather than a number written into this
file: the printed total has to equal the A/R posting, and each `breakdown:`
amount the split that reached that tax account.
"""

from fractions import Fraction

import pytest
from click.testing import CliRunner

from cli.main import cli
from infrastructure.gnucash.utils import numeric_to_fraction
from repositories.gnucash_repository import GnuCashRepository, SessionMode

LEDGER = 'tests/fixtures/discounted_lines_with_tax_three_ways.txt'

INVOICES = (
    'INV-DISCOUNT-PRETAX',
    'INV-DISCOUNT-SAMETIME',
    'INV-DISCOUNT-POSTTAX',
    'INV-DISCOUNT-INCLUDED',
    'INV-DISCOUNT-TWO-TAXES',
)


@pytest.fixture(scope='module')
def book(tmp_path_factory):
    path = tmp_path_factory.mktemp('discounts') / 'book.gnucash'
    made = CliRunner().invoke(cli, ['import', '--new', str(path), LEDGER,
                                    '--include-business-objects'])
    assert made.exit_code == 0, made.output
    return path


def _printed(book, tmp_path, invoice):
    out = tmp_path / f'{invoice}.txt'
    result = CliRunner().invoke(cli, [
        'print-invoice', str(book), invoice, '--format', 'plaintext',
        '--output', str(out)])
    assert result.exit_code == 0, result.output
    return out.read_text(encoding='utf-8')


def _printed_bill(book, tmp_path):
    out = tmp_path / 'BILL-TAX-INCLUDED.txt'
    result = CliRunner().invoke(cli, [
        'print-bill', str(book), 'BILL-TAX-INCLUDED', '--format', 'plaintext',
        '--output', str(out)])
    assert result.exit_code == 0, result.output
    return out.read_text(encoding='utf-8')


def _stated(printed, key):
    """The figure a printed invoice states for `key`, as an exact Fraction."""
    for line in printed.splitlines():
        bare = line.strip()
        if bare.startswith(f'{key}:'):
            return Fraction(bare.split(':', 1)[1].strip())
    raise AssertionError(f'{key}: is not in the printed invoice:\n{printed}')


def _posting_splits(book_path, memo):
    """`{account full name: amount}` for the transaction an invoice posted."""
    from gnucash import Query, Split

    from infrastructure.gnucash.utils import get_account_full_name

    repo = GnuCashRepository(str(book_path))
    repo.open(SessionMode.READ_ONLY)
    try:
        q = Query()
        q.search_for('Split')
        q.set_book(repo.book)
        found = {}
        for raw in q.run():
            split = Split(instance=raw)
            if split.GetParent().GetDescription() != memo:
                continue
            name = get_account_full_name(split.GetAccount())
            found[name] = found.get(name, Fraction(0)) + numeric_to_fraction(
                split.GetAmount())
        q.destroy()
        return found
    finally:
        repo.close()


class TestTheTotalAndTheReceivable:
    @pytest.mark.parametrize('invoice', INVOICES)
    def test_the_printed_total_is_the_receivable_the_book_holds(
            self, book, tmp_path, invoice):
        printed = _printed(book, tmp_path, invoice)
        splits = _posting_splits(book, invoice)

        assert _stated(printed, 'invoice_total') == \
            splits['Assets:Accounts Receivable']

    @pytest.mark.parametrize('invoice', INVOICES)
    def test_and_the_subtotal_is_what_reached_the_income_account(
            self, book, tmp_path, invoice):
        printed = _printed(book, tmp_path, invoice)
        splits = _posting_splits(book, invoice)

        assert _stated(printed, 'invoice_subtotal') == \
            -splits['Income:Sales']

    @pytest.mark.parametrize('invoice', INVOICES)
    def test_and_the_tax_total_is_what_reached_the_tax_accounts(
            self, book, tmp_path, invoice):
        printed = _printed(book, tmp_path, invoice)
        splits = _posting_splits(book, invoice)
        taxes = -sum((amount for name, amount in splits.items()
                      if name.startswith('Liabilities:')), Fraction(0))

        assert _stated(printed, 'invoice_tax_total') == taxes


class TestEachRuleSeparately:
    """The three rules, stated as the figures rather than read off the book.

    The tests above would pass on an invoice whose splits were wrong in the
    same way as its printed page. These say which figures are right, and are
    the measurement the module docstring reports.
    """

    def test_a_discount_before_tax(self, book, tmp_path):
        printed = _printed(book, tmp_path, 'INV-DISCOUNT-PRETAX')

        assert _stated(printed, 'invoice_subtotal') == 900
        assert _stated(printed, 'invoice_tax_total') == 90
        assert _stated(printed, 'invoice_total') == 990

    def test_a_discount_at_the_same_time_as_tax(self, book, tmp_path):
        printed = _printed(book, tmp_path, 'INV-DISCOUNT-SAMETIME')

        assert _stated(printed, 'invoice_subtotal') == 900
        assert _stated(printed, 'invoice_tax_total') == 100
        assert _stated(printed, 'invoice_total') == 1000

    def test_a_discount_after_tax(self, book, tmp_path):
        printed = _printed(book, tmp_path, 'INV-DISCOUNT-POSTTAX')

        assert _stated(printed, 'invoice_subtotal') == 890
        assert _stated(printed, 'invoice_tax_total') == 100
        assert _stated(printed, 'invoice_total') == 990

    def test_a_value_discount_off_a_price_that_includes_tax(
            self, book, tmp_path):
        """1100.00 gross is 1000.00 net of a 10 per cent tax, less 100.00."""
        printed = _printed(book, tmp_path, 'INV-DISCOUNT-INCLUDED')

        assert _stated(printed, 'invoice_subtotal') == 900
        assert _stated(printed, 'invoice_tax_total') == 90
        assert _stated(printed, 'invoice_total') == 990


class TestTheBreakdownPerTaxAccount:
    def test_each_account_gets_what_its_posting_split_got(
            self, book, tmp_path):
        """Two tax accounts on one discounted line: 5 per cent and 8 per cent
        of 900.00, not of 1000.00."""
        printed = _printed(book, tmp_path, 'INV-DISCOUNT-TWO-TAXES')
        splits = _posting_splits(book, 'INV-DISCOUNT-TWO-TAXES')

        blocks = _breakdown_blocks(printed)

        assert blocks == {
            'Liabilities:Sales Tax': -splits['Liabilities:Sales Tax'],
            'Liabilities:Local Tax': -splits['Liabilities:Local Tax'],
        }
        assert blocks['Liabilities:Sales Tax'] == 45
        assert blocks['Liabilities:Local Tax'] == 72

    def test_a_table_naming_one_account_twice_is_one_block(
            self, book, tmp_path):
        """5 per cent and 7 per cent to the same account. GnuCash merges them
        when it works out what each account receives, so a row per table
        entry would have both rows claiming the whole 12.00 and a column
        adding to twice the tax."""
        printed = _printed(book, tmp_path, 'INV-ONE-ACCOUNT-TWICE')
        splits = _posting_splits(book, 'INV-ONE-ACCOUNT-TWICE')

        blocks = _breakdown_blocks(printed)

        assert blocks == {'Liabilities:Sales Tax': Fraction(12)}
        assert blocks['Liabilities:Sales Tax'] == \
            -splits['Liabilities:Sales Tax']
        assert _stated(printed, 'invoice_tax_total') == Fraction(12)
        # And the rate on that one row is the two rates together.
        assert 'rate: 12' in printed, printed

    def test_the_blocks_sum_to_the_tax_the_invoice_states(
            self, book, tmp_path):
        printed = _printed(book, tmp_path, 'INV-DISCOUNT-TWO-TAXES')

        assert sum(_breakdown_blocks(printed).values(), Fraction(0)) == \
            _stated(printed, 'invoice_tax_total')


class TestSeveralLinesAndSeveralTaxAccounts:
    """Where the two roundings can disagree, and the only shape that shows it.

    GnuCash totals an invoice's tax per *account* across every line, rounding
    each account once — so with several lines and several accounts its figure
    need not be what the lines round to on their own. One line or one account
    hides that: they coincide. Measured on 5.10, this invoice's lines hold
    0.6294, 0.6000 and 0.1998 of tax and its accounts receive 0.24, 0.48 and
    0.71 — 1.43 either way here, and the page has to state figures that add
    to it and match the splits account by account.
    """

    INVOICE = 'INV-THREE-ACCOUNTS'

    def test_the_tax_column_adds_to_the_invoice_and_matches_the_splits(
            self, book, tmp_path):
        printed = _printed(book, tmp_path, self.INVOICE)
        splits = _posting_splits(book, self.INVOICE)

        per_line = [Fraction(line.split(':', 1)[1].strip())
                    for line in printed.splitlines()
                    if line.strip().startswith('entry_tax:')]
        taxes = -sum((amount for name, amount in splits.items()
                      if name.startswith('Liabilities:Tax')), Fraction(0))

        assert len(per_line) == 3, printed
        assert sum(per_line, Fraction(0)) == _stated(printed,
                                                     'invoice_tax_total')
        assert _stated(printed, 'invoice_tax_total') == taxes
        assert taxes == Fraction(143, 100)

    def test_and_each_account_is_what_its_split_received(
            self, book, tmp_path):
        printed = _printed(book, tmp_path, self.INVOICE)
        splits = _posting_splits(book, self.INVOICE)

        # Every `breakdown:` block on the page, summed per account.
        found = {}
        for account, amount in _breakdown_rows(printed):
            found[account] = found.get(account, Fraction(0)) + amount

        assert found == {
            'Liabilities:Tax A': -splits['Liabilities:Tax A'],
            'Liabilities:Tax B': -splits['Liabilities:Tax B'],
            'Liabilities:Tax C': -splits['Liabilities:Tax C'],
        }
        assert sorted(found.values()) == [Fraction(24, 100), Fraction(48, 100),
                                          Fraction(71, 100)]

    def test_each_account_holds_what_its_split_holds_across_lines(
            self, book, tmp_path):
        """Two lines of 1.10 taxed at 5% + 5%: each line owes 0.055 to each
        account. Rounding a line's own breakdown gives one account 0.06 and
        the other 0.05 on both lines — 0.12 against 0.10 — while the book
        rounds each account once across the invoice and posts 0.11 each.
        The page has to state the book's figures, so the fit works per
        account first and hands each account's total out over the lines."""
        printed = _printed(book, tmp_path, 'INV-EVEN-SPLIT')
        splits = _posting_splits(book, 'INV-EVEN-SPLIT')

        found = {}
        for account, amount in _breakdown_rows(printed):
            found[account] = found.get(account, Fraction(0)) + amount

        assert found == {
            'Liabilities:Sales Tax': -splits['Liabilities:Sales Tax'],
            'Liabilities:Local Tax': -splits['Liabilities:Local Tax'],
        }
        assert sorted(found.values()) == [Fraction(11, 100), Fraction(11, 100)]
        assert _stated(printed, 'invoice_tax_total') == Fraction(22, 100)

    def test_and_the_page_reads_back_into_its_own_book(self, book, tmp_path):
        page = tmp_path / f'{self.INVOICE}-again.txt'
        page.write_text(_printed(book, tmp_path, self.INVOICE),
                        encoding='utf-8')

        again = CliRunner().invoke(cli, ['import', str(book), str(page),
                                         '--include-business-objects'])

        assert again.exit_code == 0, again.output
        assert f'invoice "{self.INVOICE}": unchanged' in again.output, \
            again.output


class TestTheBillSideOfTheSameRule:
    """A bill has no discount, and rounds the same way an invoice does.

    GnuCash rounds each line to the currency's smallest unit as it posts it.
    Summing exact fractions and rounding the total once says something else:
    three lines of 100.00 tax-included at 15 per cent post 86.96 of expense
    each — 260.88 — where 300.00 / 1.15 rounded once is 260.87, so a printed
    bill stated a subtotal and a tax its own A/P transaction contradicted.
    """

    def _printed_bill(self, book, tmp_path):
        return _printed_bill(book, tmp_path)

    def test_the_printed_total_is_the_payable_the_book_holds(
            self, book, tmp_path):
        printed = self._printed_bill(book, tmp_path)
        splits = _posting_splits(book, 'BILL-TAX-INCLUDED')

        assert _stated(printed, 'bill_total') == \
            -splits['Liabilities:Accounts Payable']

    def test_and_the_subtotal_is_what_reached_the_expense_account(
            self, book, tmp_path):
        printed = self._printed_bill(book, tmp_path)
        splits = _posting_splits(book, 'BILL-TAX-INCLUDED')

        assert _stated(printed, 'bill_subtotal') == splits['Expenses:Supplies']
        assert _stated(printed, 'bill_subtotal') == Fraction(26088, 100)

    def test_and_the_tax_is_what_reached_the_tax_account(self, book, tmp_path):
        """39.13, not the 39.12 the three rounded lines add to: GnuCash
        rounds an invoice's tax once, and the split follows GnuCash."""
        printed = self._printed_bill(book, tmp_path)
        splits = _posting_splits(book, 'BILL-TAX-INCLUDED')

        assert _stated(printed, 'bill_tax_total') == \
            splits['Liabilities:Sales Tax']
        assert _stated(printed, 'bill_tax_total') == Fraction(3913, 100)
        assert _stated(printed, 'bill_total') == Fraction(30001, 100)

    def test_the_tax_column_adds_to_the_tax_the_bill_states(
            self, book, tmp_path):
        """Three lines whose tax is 13.0434… each. Rounded on their own they
        each print 13.04 and add to 39.12, against a stated 39.13 — a
        column a reader cannot add. The lines are fitted to the invoice's
        figure instead, so one of them carries the odd cent."""
        printed = self._printed_bill(book, tmp_path)

        per_line = [Fraction(line.split(':', 1)[1].strip())
                    for line in printed.splitlines()
                    if line.strip().startswith('entry_tax:')]

        assert len(per_line) == 3, printed
        assert sum(per_line, Fraction(0)) == _stated(printed, 'bill_tax_total')
        assert sorted(per_line) == [Fraction(1304, 100), Fraction(1304, 100),
                                    Fraction(1305, 100)]

    def test_and_the_net_column_adds_to_the_subtotal(self, book, tmp_path):
        printed = self._printed_bill(book, tmp_path)

        per_line = [Fraction(line.split(':', 1)[1].strip())
                    for line in printed.splitlines()
                    if line.strip().startswith('entry_amount:')]

        assert sum(per_line, Fraction(0)) == _stated(printed, 'bill_subtotal')

    def test_and_the_printed_bill_re_imports_unchanged(self, book, tmp_path):
        printed = tmp_path / 'bill-again.txt'
        printed.write_text(self._printed_bill(book, tmp_path),
                           encoding='utf-8')

        again = CliRunner().invoke(cli, ['import', str(book), str(printed),
                                         '--include-business-objects'])

        assert again.exit_code == 0, again.output
        assert 'bill "BILL-TAX-INCLUDED": unchanged' in again.output, \
            again.output


class TestAPrintedPageReadIntoAFreshBook:
    """A page carries its figures to a book that has never seen the invoice.

    Every other re-import test reads a page back into the book it was printed
    from, where the writer and the importer walk the same list in the same
    order. A fresh book orders an invoice by GnuCash's own comparison — date,
    then date entered, then description — and stamps its own date entered, so
    the fit has to reach the same answer from the invoice's own content
    rather than from a line's position in a list.
    """

    def _figures(self, page: str) -> list:
        """Every figure the page states, in order."""
        return [line.strip() for line in page.splitlines()
                if line.strip().startswith(('entry_amount:', 'entry_tax:',
                                            'amount:', 'invoice_', 'bill_'))]

    @pytest.mark.parametrize('invoice', ['INV-THREE-ACCOUNTS',
                                          'INV-DISCOUNT-TWO-TAXES',
                                          'INV-DISCOUNT-PRETAX'])
    def test_the_page_states_the_same_figures_from_either_book(
            self, book, tmp_path, invoice):
        printed = _printed(book, tmp_path, invoice)
        page = tmp_path / f'{invoice}-page.txt'
        page.write_text(printed, encoding='utf-8')

        fresh = tmp_path / f'{invoice}-fresh.gnucash'
        assert CliRunner().invoke(cli, [
            'import', '--new', str(fresh), LEDGER,
            '--include-business-objects']).exit_code == 0
        # `updated` rather than `unchanged`: the page names the posting
        # transaction of the book it was printed from, which this one has
        # not got, so the invoice is rebuilt. What has to survive that is
        # the figures.
        again = CliRunner().invoke(cli, ['import', str(fresh), str(page),
                                         '--include-business-objects'])
        assert again.exit_code == 0, again.output

        second = tmp_path / 'second'
        second.mkdir(exist_ok=True)
        assert self._figures(_printed(fresh, second, invoice)) == \
            self._figures(printed)

    def test_a_three_line_bill_likewise(self, book, tmp_path):
        printed = _printed_bill(book, tmp_path)
        page = tmp_path / 'bill-page.txt'
        page.write_text(printed, encoding='utf-8')

        fresh = tmp_path / 'bill-fresh.gnucash'
        assert CliRunner().invoke(cli, [
            'import', '--new', str(fresh), LEDGER,
            '--include-business-objects']).exit_code == 0

        again = CliRunner().invoke(cli, ['import', str(fresh), str(page),
                                         '--include-business-objects'])
        assert again.exit_code == 0, again.output

        second = tmp_path / 'second'
        second.mkdir(exist_ok=True)
        assert self._figures(_printed_bill(fresh, second)) == \
            self._figures(printed)


class TestAPageThatDisagreesWithTheBook:
    """A figure edited on a printed page is refused, on a bill as on an
    invoice.

    The import recomputes every informational figure through the same engine
    functions the writer asked, and refuses a page whose numbers are not the
    book's. The bill half of that check was never wired: a page printed by
    an earlier release — per-line rounded tax, a total that was the sum of
    the lines — re-imported reporting `unchanged`, with `bill_total: 300.00`
    against an A/P split of 300.01 and nothing said.
    """

    def _refused(self, book, tmp_path, invoice, command, source, wanted):
        out = tmp_path / f'{invoice}-edited.txt'
        printed = _printed(book, tmp_path, invoice) if command == \
            'print-invoice' else _printed_bill(book, tmp_path)
        assert source in printed, (source, printed)
        out.write_text(printed.replace(source, wanted, 1), encoding='utf-8')

        result = CliRunner().invoke(cli, ['import', str(book), str(out),
                                          '--include-business-objects'])
        assert result.exit_code != 0, result.output
        return result.output

    def test_a_bills_total_that_is_not_what_the_book_posts(
            self, book, tmp_path):
        output = self._refused(book, tmp_path, 'BILL-TAX-INCLUDED',
                               'print-bill',
                               'bill_total: 300.01', 'bill_total: 300.00')

        assert 'bill_total' in output, output
        assert '300.01' in output, output

    def test_a_bill_lines_tax_that_is_not_what_the_book_posts(
            self, book, tmp_path):
        output = self._refused(book, tmp_path, 'BILL-TAX-INCLUDED',
                               'print-bill',
                               'entry_tax: 13.04', 'entry_tax: 26.08')

        assert 'entry_tax' in output, output

    def test_an_invoices_total_likewise(self, book, tmp_path):
        output = self._refused(book, tmp_path, 'INV-DISCOUNT-PRETAX',
                               'print-invoice',
                               'invoice_total: 990.00',
                               'invoice_total: 1090.00')

        assert 'invoice_total' in output, output


class TestTheWholeBookOfThem:
    """Every invoice in this fixture, exported and read back.

    The classes above take one page at a time; this is the run they all
    assume works. A credit note's figures have a file of their own —
    `tests/integration/test_a_credit_note_is_carried_like_any_invoice.py`.
    """

    def test_a_book_of_ordinary_invoices_exports_and_re_imports(
            self, tmp_path):
        book = tmp_path / 'ordinary.gnucash'
        assert CliRunner().invoke(cli, ['import', '--new', str(book), LEDGER,
                                        '--include-business-objects']
                                  ).exit_code == 0
        ledger = tmp_path / 'exported.txt'
        assert CliRunner().invoke(cli, [
            'export', str(book), '--output', str(ledger),
            '--include-business-objects']).exit_code == 0

        again = CliRunner().invoke(cli, ['import', str(book), str(ledger),
                                         '--include-business-objects'])

        assert again.exit_code == 0, again.output
        assert 'invoice "INV-DISCOUNT-PRETAX": unchanged' in again.output, \
            again.output


class TestReadingThePrintedPageBack:
    @pytest.mark.parametrize('invoice', INVOICES)
    def test_a_printed_invoice_re_imports_unchanged(
            self, book, tmp_path, invoice):
        """The import recomputes every informational figure and refuses
        an invoice whose figures disagree, so this is the same check from the
        other side — and it would fail on a page printed from the old
        arithmetic against a book posted by GnuCash."""
        printed = tmp_path / f'{invoice}-again.txt'
        printed.write_text(_printed(book, tmp_path, invoice),
                           encoding='utf-8')

        again = CliRunner().invoke(cli, ['import', str(book), str(printed),
                                         '--include-business-objects'])

        assert again.exit_code == 0, again.output
        assert f'invoice "{invoice}": unchanged' in again.output, again.output


class TestWhichRoundingAnInvoicesTaxIs:
    """An invoice's tax is the sum of its accounts', each rounded once.

    The alternative reading — one rounding of the whole invoice's tax —
    gives the same answer for almost every invoice, which is why it has to
    be asked of a case that parts them. One line of 1.10 taxed at 5% + 5% owes
    0.055 to each account:

        per account, each rounded once : 0.06 + 0.06 = 0.12
        the whole rounded once         : round(0.11)  = 0.11

    Measured on 5.10: `gncInvoiceGetTotalTax` answers **0.12** and the posting
    splits carry 0.06 to each account. That is the model
    `entries_fitted_to_the_page` computes, and the `stated !=
    invoice_tax` refusal it ends with is what would fire if some version
    ever answered the other way — so this is the invoice that would fire it.
    """

    @pytest.fixture
    def book(self, tmp_path):
        path = tmp_path / 'halves.gnucash'
        assert CliRunner().invoke(cli, ['import', '--new', str(path), LEDGER,
                                        '--include-business-objects']
                                  ).exit_code == 0
        return path

    def test_the_book_posts_a_unit_to_each_account(self, book):
        splits = _posting_splits(book, 'INV-ONE-LINE-TWO-HALVES')

        assert splits['Liabilities:Sales Tax'] == Fraction(-6, 100), splits
        assert splits['Liabilities:Local Tax'] == Fraction(-6, 100), splits

    def test_and_the_page_states_the_same(self, book, tmp_path):
        """Rounded the other way the page would say 0.11, and the run would
        refuse rather than print a column that does not add up."""
        printed = _printed(book, tmp_path, 'INV-ONE-LINE-TWO-HALVES')

        assert _stated(printed, 'invoice_tax_total') == Fraction(12, 100)
        assert _stated(printed, 'entry_tax') == Fraction(12, 100)
        assert _breakdown_blocks(printed) == {
            'Liabilities:Sales Tax': Fraction(6, 100),
            'Liabilities:Local Tax': Fraction(6, 100),
        }

    def test_and_it_re_imports_unchanged(self, book, tmp_path):
        page = tmp_path / 'page.txt'
        page.write_text(_printed(book, tmp_path, 'INV-ONE-LINE-TWO-HALVES'),
                        encoding='utf-8')

        result = CliRunner().invoke(cli, ['import', str(book), str(page),
                                          '--include-business-objects'])

        assert result.exit_code == 0, result.output
        assert 'invoice "INV-ONE-LINE-TWO-HALVES": unchanged' in result.output


class TestTwoLinesAlikeInEveryField:
    """A block is paired with the line it describes, and takes it out of the
    running whether or not it states any figures.

    Two lines a comparison cannot tell apart still hold different figures —
    each owes 0.055 to each account, each account rounds to 0.11 across the
    two, and the odd unit goes to one of them. So the page states 0.12 for
    one and 0.10 for the other.

    A block stating no figures used to be skipped before the pairing, which
    left its own line free for a later block to be matched against. Strip the
    figures from the first block and the second one — stating 0.10, and
    describing the second line — was judged against the first line's 0.12 and
    refused, naming "entry #2" for a page that was right.
    """

    def _page_with_the_first_line_saying_nothing(self, tmp_path):
        book = tmp_path / 'twins.gnucash'
        assert CliRunner().invoke(cli, ['import', '--new', str(book), LEDGER,
                                        '--include-business-objects']
                                  ).exit_code == 0
        printed = _printed(book, tmp_path, 'INV-TWIN-LINES')

        # The lines the first `entry:` block states its figures on, and the
        # `breakdown:` blocks under it: everything that makes it a block that
        # declares something.
        #
        # Counted from the `invoice` line, because a page starts with its
        # `taxtable` blocks and those have `entry:` sub-blocks of their own —
        # counted from the top of the file, the first two entries here are
        # the tax table's and nothing is stripped at all.
        kept, entries_seen, dropping, in_invoice = [], 0, False, False
        for line in printed.splitlines():
            bare = line.strip()
            if bare.startswith('invoice "'):
                in_invoice = True
            if in_invoice and bare == 'entry:':
                entries_seen += 1
            if entries_seen == 1 and bare.startswith(
                    ('entry_amount:', 'entry_tax:', 'breakdown:')):
                dropping = bare.startswith('breakdown:')
                continue
            if dropping:
                if bare.startswith(('account:', 'rate:', 'amount:')):
                    continue
                dropping = False
            kept.append(line)
        return book, '\n'.join(kept) + '\n'

    def test_the_second_block_is_judged_against_its_own_line(self, tmp_path):
        book, page = self._page_with_the_first_line_saying_nothing(tmp_path)
        edited = tmp_path / 'edited.txt'
        edited.write_text(page, encoding='utf-8')
        assert 'entry_tax:' in page, page          # the second block's, kept

        result = CliRunner().invoke(cli, ['import', str(book), str(edited),
                                          '--include-business-objects'])

        assert result.exit_code == 0, result.output
        assert 'invoice "INV-TWIN-LINES": unchanged' in result.output, \
            result.output

    def test_and_the_page_as_printed_states_both_figures(self, tmp_path):
        """What makes the case above worth holding: the two lines a
        comparison cannot tell apart do not carry the same tax."""
        book = tmp_path / 'twins-whole.gnucash'
        assert CliRunner().invoke(cli, ['import', '--new', str(book), LEDGER,
                                        '--include-business-objects']
                                  ).exit_code == 0
        printed = _printed(book, tmp_path, 'INV-TWIN-LINES')

        taxes = [Fraction(line.split(':', 1)[1].strip())
                 for line in printed.splitlines()
                 if line.strip().startswith('entry_tax:')]
        assert sorted(taxes) == [Fraction(10, 100), Fraction(12, 100)], printed


def _breakdown_rows(printed: str):
    """Every `breakdown:` block on a page as `(account, amount)`, in order —
    the same account appears once per line that is taxed by it."""
    account = None
    for line in printed.splitlines():
        bare = line.strip()
        if bare.startswith('account:'):
            account = bare.split(':', 1)[1].strip().strip('"')
        elif bare.startswith('amount:') and account is not None:
            yield account, Fraction(bare.split(':', 1)[1].strip())
            account = None


def _breakdown_blocks(printed: str) -> dict:
    """`{account: amount}` from every `breakdown:` block on a printed page."""
    blocks = {}
    account = None
    for line in printed.splitlines():
        bare = line.strip()
        if bare.startswith('account:'):
            account = bare.split(':', 1)[1].strip().strip('"')
        elif bare.startswith('amount:') and account is not None:
            blocks[account] = Fraction(bare.split(':', 1)[1].strip())
            account = None
    return blocks
