"""When an account cannot be made, the run says why — not what missed it.

Accounts are created before the business objects that reference them — the
commodity step, then the accounts, then the owners and tax tables the
`on_accounts_ready` hook imports, then the transactions. A declaration that
cannot be carried out is recorded as an error and the run goes on.

A tax table is imported before the transactions. So an account whose own line
is refused —
`commodity_scu:` quoted, which the C setter rejects outright — is not there
when the tax table posts to it, and the run stops on "account not found",
which is true and is not the reason. The reason is a line above it in the
reader's own file, and it was swallowed.

The message has to name the account's own failure. Anything else sends the
reader to look at a tax table that is written correctly.

Invoices and bills reach the same missing account by the other route: they are
imported in the deferred pass, after the transactions, so the account's failure
is recorded by then rather than swallowed — and the refusal has to carry it out
just the same. That one is the commoner way in, an entry posting to an income
account being ordinary where a tax table is not.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner

from cli.main import cli

EARLY = str(Path('tests/fixtures/a_taxtable_on_an_account_that_will_not_open.txt'))
DEFERRED = str(Path('tests/fixtures/an_invoice_on_an_account_that_will_not_open.txt'))


def _run(tmp_path, ledger):
    book = tmp_path / 'book.gnucash'
    return CliRunner().invoke(cli, [
        'import', '--new', str(book), ledger, '--include-business-objects'])


@pytest.fixture
def result(tmp_path):
    return _run(tmp_path, EARLY)


class TestTheRunIsRefused:
    def test_it_does_not_report_success(self, result):
        assert result.exit_code != 0, result.output


class TestWhatItSays:
    def test_the_account_that_could_not_be_made_is_named(self, result):
        assert 'Liabilities:GST' in result.output, result.output

    def test_the_reason_the_account_failed_is_given(self, result):
        """Not just that something later could not find it.

        The account's own declaration is what is wrong, and its failure names
        the unit the setter refused — that is the line the reader edits.
        """
        assert 'commodity_scu' in result.output or 'scu' in result.output.lower(), \
            result.output


class TestTwoFailuresThatExplainNothingAboutEachOther:
    """Gathering up what else went wrong must not invent a connection.

    The deferred pass carries what the run already reported, so the reader is
    told the cause and not only the symptom. Carried unfiltered, that attached
    *every* per-object error to the invoice's failure — so an invoice failing
    over a missing tax table was told "That account could not be created: the
    amount on split 'Expenses:Fuel' states 18.191 CAD", welding two unrelated
    failures into one sentence and blaming an account neither of them names.
    """

    LEDGER = str(Path('tests/fixtures/two_unrelated_failures_in_one_file.txt'))

    @pytest.fixture
    def result(self, tmp_path):
        return _run(tmp_path, self.LEDGER)

    def test_both_failures_are_reported(self, result):
        """Both, which is what the name says and what only one of them did.

        The invoice's failure raises past the summary, so everything the
        commodity, account and transaction passes had already collected went
        with it — and the reader fixes the tax table, runs again, and only
        then meets the split. The export half of this release refuses a whole
        book at once so it is not corrected one run at a time; the import half
        was doing the opposite.
        """
        assert result.exit_code != 0, result.output
        assert 'No Such Table' in result.output, result.output
        assert '18.191' in result.output, result.output

    def test_neither_is_blamed_on_an_account_that_could_not_be_made(
            self, result):
        assert 'That account could not be created' not in result.output, \
            result.output
        assert 'That commodity could not be created' not in result.output, \
            result.output

    def test_the_split_is_not_offered_as_the_invoices_reason(self, result):
        """They share a file and nothing else."""
        for line in result.output.splitlines():
            if 'No Such Table' in line:
                assert '18.191' not in line, line


class TestAnAccountWhoseNameIsAPrefixOfAnother:
    """`Income:Sales` is a substring of `Income:Sales Returns`.

    A chart of accounts is full of names like that, and the cause is attached
    by finding the failure's account named in the message. Found by substring,
    a refused `Income:Sales` was offered as the reason an invoice posting to
    `Income:Sales Returns` failed — a correct line, named as the thing to go
    and fix, which is the one thing this clause exists to prevent.
    """

    LEDGER = str(Path(
        'tests/fixtures/two_accounts_one_name_a_prefix_of_the_other.txt'))

    @pytest.fixture
    def result(self, tmp_path):
        return _run(tmp_path, self.LEDGER)

    def test_the_invoices_own_failure_is_reported(self, result):
        assert result.exit_code != 0, result.output
        assert 'No Such Table' in result.output, result.output

    def test_the_other_account_is_not_offered_as_the_cause(self, result):
        for line in result.output.splitlines():
            if 'No Such Table' in line:
                assert 'could not be created' not in line, line


class TestACommodityWhoseCodeIsASuffixOfAnother:
    """`ZZ` is the tail of `XZZ`, and a name has two ends.

    The boundary that tells `Income:Sales` from `Income:Sales Returns` was
    written on the right only, so a failed object whose name *ends* another's
    was welded on the same way — a refused `ZZ` offered as the reason an
    account kept in `XZZ` could not be made. Often accidentally right, which
    is why nothing caught it: a failed `USD` really does explain
    `Assets:Bank:USD`.
    """

    LEDGER = str(Path(
        'tests/fixtures/two_commodities_one_name_a_suffix_of_the_other.txt'))

    @pytest.fixture
    def result(self, tmp_path):
        return _run(tmp_path, self.LEDGER)

    def test_the_commodity_the_account_names_is_the_cause(self, result):
        assert result.exit_code != 0, result.output
        assert 'Failed to create commodity XZZ' in result.output, result.output

    def test_the_other_one_is_not_offered_as_the_cause(self, result):
        """`ZZ` failed too and is reported as its own error — the run says
        everything it found. What it must not do is offer `ZZ` as the reason
        the account kept in `XZZ` could not be made."""
        clause = result.output.split('That commodity could not be created:')
        assert len(clause) == 2, result.output
        assert 'commodity ZZ:' not in clause[1].split('\n')[0], clause[1]


class TestTheSameAccountReachedByAnInvoice:
    """The deferred pass, which is where most readers will meet this."""

    @pytest.fixture
    def result(self, tmp_path):
        return _run(tmp_path, DEFERRED)

    def test_it_does_not_report_success(self, result):
        assert result.exit_code != 0, result.output

    def test_the_account_that_could_not_be_made_is_named(self, result):
        assert 'Income:Sales' in result.output, result.output

    def test_the_reason_the_account_failed_is_given(self, result):
        assert 'commodity_scu' in result.output or 'scu' in result.output.lower(), \
            result.output
