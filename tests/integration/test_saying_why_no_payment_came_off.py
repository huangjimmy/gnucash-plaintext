"""`unapply-payment` and `unlink` name the reason when nothing comes off.

Both commands move money: a payment's receivable split leaves the invoice's lot
and lands on the account `--to` gives. So when neither runs, the reader has to
be able to tell which of several quite different situations they are in — the
invoice was never posted, it was posted and never paid, `--txn` gives the guid
of a transaction that is no payment on the record, or the id matches more than
one record. Each is a different next step, and "unapply failed" is none of them.

**Both commands are run against every one of them.** They are one operation
under two names, reach the same statuses through the same code, and take their
words from `the_reason_nothing_came_off`. Two of those statuses carry no
detail of their own, so a command left to print the status word answered a
duplicate id with `ambiguous_id` — which names the situation and not the way
out of it, and `--by-guid` is a flag nobody guesses.

Every one of these leaves the book alone; `test_unapply_payment.py` and
`test_unlinking_a_linked_transaction.py` hold the cases where a payment does
come off.
"""

from pathlib import Path
from typing import NamedTuple

import pytest
from click.testing import CliRunner

from cli.main import cli
from tests.integration.test_delete_invoice_bill import _create_duplicate_invoice

LEDGER = str(Path('tests/fixtures/invoices_in_each_state_to_unapply.txt'))
TO = 'Liabilities:Owed Back'
A_GUID_NAMING_NOTHING = 'deadbeefdeadbeefdeadbeefdeadbeef'


class Command(NamedTuple):
    """A command, the word it calls the operation by, and the word it reports
    a run with."""
    name: str
    verb: str
    done: str


COMMANDS = [Command('unapply-payment', 'unapply', 'unapplied'),
            Command('unlink', 'unlink', 'unlinked')]


@pytest.fixture(params=COMMANDS, ids=[c.name for c in COMMANDS])
def command(request):
    return request.param


@pytest.fixture
def book(tmp_path):
    path = tmp_path / 'book.gnucash'
    result = CliRunner().invoke(cli, [
        'import', '--new', str(path), LEDGER, '--include-business-objects'])
    assert result.exit_code == 0, result.output
    return path


def _run(command, book, *args, to=TO):
    return CliRunner().invoke(
        cli, [command.name, str(book), *args, '--to', to])


class TestAnInvoiceNeverPosted:
    def test_it_is_refused(self, command, book):
        result = _run(command, book, 'INV-DRAFT')

        assert result.exit_code != 0, result.output

    def test_it_says_the_invoice_is_not_posted(self, command, book):
        """Not "no payments" — the next step is to post it, not to find one."""
        result = _run(command, book, 'INV-DRAFT')

        assert 'not posted' in result.output, result.output
        assert 'INV-DRAFT' in result.output, result.output


class TestAnInvoicePostedAndUnpaid:
    def test_it_is_refused(self, command, book):
        result = _run(command, book, 'INV-UNPAID')

        assert result.exit_code != 0, result.output

    def test_it_says_there_is_no_payment_rather_than_no_invoice(
            self, command, book):
        """The invoice is there and posted; what is missing is a payment."""
        result = _run(command, book, 'INV-UNPAID')

        assert f'no payments to {command.verb}' in result.output, result.output
        assert 'INV-UNPAID' in result.output, result.output

    def test_the_reason_never_names_the_other_command(
            self, command, book):
        """A reader of `unlink` told there is "nothing to unapply" has been
        handed the wrong manual page, and the other way round."""
        result = _run(command, book, 'INV-UNPAID')

        other, = [c for c in COMMANDS if c.verb != command.verb]
        assert other.verb not in result.output, result.output


class TestATxnGuidNamingNoPaymentOnTheRecord:
    def test_it_is_refused(self, command, book):
        result = _run(command, book, 'INV-PAID', '--txn', A_GUID_NAMING_NOTHING)

        assert result.exit_code != 0, result.output

    def test_the_guid_that_did_not_match_is_named(self, command, book):
        result = _run(command, book, 'INV-PAID', '--txn', A_GUID_NAMING_NOTHING)

        assert A_GUID_NAMING_NOTHING in result.output, result.output

    def test_the_payments_the_record_does_have_are_named_too(
            self, command, book):
        """So the reader can pick one instead of going to look for the list."""
        result = _run(command, book, 'INV-PAID', '--txn', A_GUID_NAMING_NOTHING)

        assert 'payments: ' in result.output, result.output

    def test_the_payment_the_record_does_have_is_left_applied(
            self, command, book):
        """A refusal takes nothing off, including the payments it did not name.

        Shown by taking it off afterwards: a second run succeeds only against a
        payment that is still on the lot, so a run that reports one here is the
        refusal having changed nothing.
        """
        _run(command, book, 'INV-PAID', '--txn', A_GUID_NAMING_NOTHING)

        after = _run(command, book, 'INV-PAID')

        assert after.exit_code == 0, after.output
        assert command.done in after.output, after.output


class TestARecordWithSeveralPaymentsAndNoSelector:
    """The status whose whole job is to say what to type next.

    README: "omitting all selectors is an error — never an implicit 'all'".
    No book in the suite could reach it before, so the sentence it prints was
    read by nobody.
    """

    def test_it_is_refused(self, command, book):
        result = _run(command, book, 'INV-TWICE')

        assert result.exit_code != 0, result.output

    def test_it_says_how_many_payments_there_are(self, command, book):
        result = _run(command, book, 'INV-TWICE')

        assert 'INV-TWICE has 2 payments' in result.output, result.output

    def test_it_names_both_selectors(self, command, book):
        """Either one is a way out, and neither is guessable."""
        result = _run(command, book, 'INV-TWICE')

        assert '--txn <guid>' in result.output, result.output
        assert '--all' in result.output, result.output

    def test_the_guids_to_choose_between_are_printed(self, command, book):
        """`--txn` takes a guid, so a refusal that withholds them is a dead
        end: the reader would have to go and run `find-orphan-payments`."""
        result = _run(command, book, 'INV-TWICE')

        guids = [line.split('payments: ')[1] for line in result.output.splitlines()
                 if 'payments: ' in line]
        assert guids, result.output
        assert len(guids[0].split(', ')) == 2, result.output

    def test_the_remedy_is_told_in_the_command_s_own_word(self, command, book):
        """This is the one status that tells the reader what to type, and it
        was built where the command's verb is not known — so `unlink` answered
        "or --all to unapply all", which is the other command's manual."""
        result = _run(command, book, 'INV-TWICE')

        other, = [c for c in COMMANDS if c.verb != command.verb]
        assert f'--all to {command.verb} every payment' in result.output, result.output
        assert other.verb not in result.output, result.output

    def test_both_payments_are_left_applied(self, command, book):
        """A refusal takes nothing off, so the record is still ambiguous."""
        _run(command, book, 'INV-TWICE')

        again = _run(command, book, 'INV-TWICE')

        assert again.exit_code != 0, again.output
        assert 'has 2 payments' in again.output, again.output


class TestTheArgumentsBothCommandsRefuse:
    """The guards each command carried a copy of, tested against both.

    They are one implementation now — `cli/taking_a_payment_off.py` — and this
    is what says so for `unlink`, which had copies of both and no test of
    either.
    """

    def test_txn_and_all_together_are_refused(self, command, book):
        """One says which payments, the other says every payment."""
        result = CliRunner().invoke(cli, [
            command.name, str(book), 'INV-PAID', '--to', TO,
            '--txn', A_GUID_NAMING_NOTHING, '--all'])

        assert result.exit_code != 0, result.output
        assert 'mutually exclusive' in result.output, result.output

    def test_a_guid_that_will_not_parse_is_refused(self, command, book):
        """Asserted on the message, because the alternatives cannot fail.

        `CliRunner` stores an uncaught exception in `result.exception` and
        writes nothing to `result.output`, with `exit_code` 1. So a crash and
        a refusal are both "exit_code != 0 and no 'Traceback' in output", and
        a test asserting only those two would pass whether the guard existed
        or not.
        """
        result = CliRunner().invoke(cli, [
            command.name, str(book), 'INV-PAID', '--to', TO,
            '--txn', 'not-a-guid'])

        assert result.exit_code != 0, result.output
        assert 'Invalid GUID format' in result.output, result.output
        assert 'not-a-guid' in result.output, result.output

    def test_a_to_account_the_book_has_not_got_is_refused(self, command, book):
        """One wording, for two commands README calls one operation.

        The copies had already drifted: `--to account 'X' not found in the
        book` from one and `account not found: 'X'` from the other.
        """
        result = _run(command, book, 'INV-PAID', to='Assets:No Such Account')

        assert result.exit_code != 0, result.output
        assert '--to account' in result.output, result.output
        assert 'not found in the book' in result.output, result.output


class TestAnIdTwoRecordsShare:
    @pytest.fixture
    def shared(self, book):
        _create_duplicate_invoice(book, dup_id='INV-PAID',
                                  customer_id='C-UNAPPLY', currency_code='CAD')
        return book

    def test_it_is_refused(self, command, shared):
        result = _run(command, shared, 'INV-PAID')

        assert result.exit_code != 0, result.output

    def test_it_says_to_name_the_guid_instead(self, command, shared):
        """The remedy, not the status word.

        `ambiguous_id` carries no detail of its own, so this is the message a
        command has to be given rather than one it can fall back into.
        """
        result = _run(command, shared, 'INV-PAID')

        assert 'matches multiple records' in result.output, result.output
        assert '--by-guid' in result.output, result.output
        assert 'ambiguous_id' not in result.output, result.output
