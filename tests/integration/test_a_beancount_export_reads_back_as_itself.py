"""What this tool exports, this tool has to be able to read back.

A beancount header carries two strings and GnuCash two fields: the number and
the description. They are not interchangeable — a cheque number filed as the
description is a wrong entry, not a cosmetic one — and neither is a quote
inside either of them, which beancount escapes and this export did not.

Both failures are of the same kind: the export writes something its own
importer reads as something else, or cannot read at all. The plaintext side
found the first one already (Q-020) and answers it by always writing both
slots and keying on how many strings there are rather than on whether they say
anything.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner
from gnucash import Query, Transaction

from cli.main import cli
from repositories.gnucash_repository import GnuCashRepository, SessionMode

FIXTURES = Path('tests/fixtures')


def _entries(book):
    """Each transaction as (description, number), by description."""
    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        query = Query()
        query.search_for('Trans')
        query.set_book(repo.book)
        found = {}
        for raw in query.run():
            transaction = Transaction(instance=raw)
            found[transaction.GetDescription()] = transaction.GetNum()
        query.destroy()
        return found
    finally:
        repo.close()


def _text_of(book):
    """Every free-text field the export writes, by where it came from."""
    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        bank = repo.get_account('Assets:Bank')
        found = {'code': bank.GetCode(), 'description': bank.GetDescription()}
        query = Query()
        query.search_for('Trans')
        query.set_book(repo.book)
        for raw in query.run():
            transaction = Transaction(instance=raw)
            if transaction.GetDescription() != 'Filed under C:\\name':
                continue
            try:
                found['doclink'] = transaction.GetDocLink()
            except AttributeError:
                found['doclink'] = transaction.GetAssociation()
            found['memos'] = sorted(
                split.GetMemo() for split in transaction.GetSplitList())
        query.destroy()
        return found
    finally:
        repo.close()


def _round_trip(tmp_path, ledger, name):
    """plaintext → book → beancount → book, and hand back the second book."""
    first = tmp_path / f'{name}-1.gnucash'
    made = CliRunner().invoke(cli, ['import', '--new', str(first), str(ledger)])
    assert made.exit_code == 0, made.output

    exported = tmp_path / f'{name}.beancount'
    out = CliRunner().invoke(
        cli, ['export-beancount', str(first), str(exported)])
    assert out.exit_code == 0, out.output

    second = tmp_path / f'{name}-2.gnucash'
    back = CliRunner().invoke(
        cli, ['import-beancount', str(second), str(exported)])
    assert back.exit_code == 0, f'{back.output}\n---\n{exported.read_text()}'
    return second, exported


class TestANumberWithNoDescription:
    """A cheque written into the ledger before anyone said what it was for.

    One string in the header is beancount's narration, so a lone number came
    back as the description and the number was gone. Writing both slots is
    only half the fix: `"CHK-1001" ""` still swaps, because an empty narration
    is falsy and the swap asked whether it said anything rather than whether
    it was there.
    """

    LEDGER = FIXTURES / 'beancount_export_edge_shapes.txt'

    def test_the_number_comes_back_as_the_number(self, tmp_path):
        book, _ = _round_trip(tmp_path, self.LEDGER, 'num')

        entries = _entries(book)
        assert entries.get('') == 'CHK-1001', entries

    def test_it_is_not_filed_as_the_description(self, tmp_path):
        book, _ = _round_trip(tmp_path, self.LEDGER, 'num')

        assert 'CHK-1001' not in _entries(book), _entries(book)

    def test_a_number_and_a_description_still_keep_their_places(self, tmp_path):
        """The branch that already worked, so the fix does not trade them."""
        ledger = FIXTURES / 'a_transaction_with_a_number_and_a_description.txt'
        first = tmp_path / 'both-1.gnucash'
        assert CliRunner().invoke(cli, [
            'import', '--new', str(first), str(self.LEDGER)]).exit_code == 0
        assert CliRunner().invoke(cli, [
            'import', str(first), str(ledger)]).exit_code == 0

        exported = tmp_path / 'both.beancount'
        assert CliRunner().invoke(cli, [
            'export-beancount', str(first), str(exported)]).exit_code == 0
        second = tmp_path / 'both-2.gnucash'
        back = CliRunner().invoke(
            cli, ['import-beancount', str(second), str(exported)])
        assert back.exit_code == 0, back.output

        assert _entries(second).get('Paid the printer') == 'CHK-1002', \
            _entries(second)


class TestAQuoteInADescription:
    """`Paid "Acme" Ltd` — ordinary in a book, and a string terminator here.

    Written raw into the header, the file this tool produced could not be read
    by this tool: the description ran to the first inner quote and the rest of
    the line was not a header, so the parse refused — and a refused parse
    takes the whole ledger, not one entry.
    """

    QUOTED = FIXTURES / 'a_description_carrying_quotes.txt'

    def test_the_export_reads_back(self, tmp_path):
        book, _ = _round_trip(tmp_path, self.QUOTED, 'quoted')

        assert _entries(book), 'nothing came back'

    def test_the_description_is_the_one_the_book_held(self, tmp_path):
        book, _ = _round_trip(tmp_path, self.QUOTED, 'quoted')

        assert 'Paid "Acme" Ltd' in _entries(book), _entries(book)

    def test_a_semicolon_beside_it_is_not_a_comment(self, tmp_path):
        """The quote-counting that finds a comment is thrown by a raw quote."""
        book, _ = _round_trip(tmp_path, self.QUOTED, 'quoted')

        assert 'Lunch; and coffee' in _entries(book), _entries(book)

    def test_both_in_one_description(self, tmp_path):
        """Where escaping goes wrong rather than missing.

        The comment stripper counts quotes and the string reader honours
        `\\"`; disagreeing, they cut the line inside its own string, and the
        header that was left did not parse — so the whole ledger was refused
        over a description this tool had just written.
        """
        book, _ = _round_trip(tmp_path, self.QUOTED, 'quoted')

        assert 'Paid "Acme; Ltd"' in _entries(book), _entries(book)


class TestABackslashInText:
    """`C:\\name` — a Windows path, and an escape character before an `n`.

    Escaped, it is written `C:\\\\name`. Read back one replacement at a time,
    `\\n` fired on the second backslash and the `n`, and the description came
    back as `C:\\` + a newline + `ame`: silent, and permanent after one round
    trip.
    """

    QUOTED = FIXTURES / 'a_description_carrying_quotes.txt'

    def test_the_description_survives(self, tmp_path):
        book, _ = _round_trip(tmp_path, self.QUOTED, 'backslash')

        assert 'Filed under C:\\name' in _entries(book), _entries(book)

    def test_the_memo_survives(self, tmp_path):
        book, _ = _round_trip(tmp_path, self.QUOTED, 'backslash')

        assert 'Kept in C:\\name; see the folder' in _text_of(book)['memos'], \
            _text_of(book)

    def test_a_link_ending_in_one_survives(self, tmp_path):
        """Which is what a Windows directory looks like."""
        book, _ = _round_trip(tmp_path, self.QUOTED, 'backslash')

        assert _text_of(book)['doclink'] == 'file:///C:\\receipts\\', \
            _text_of(book)


class TestTheAccountsOwnText:
    """The header was fixed and the fields beside it were not.

    An account's code and description are free text a person typed, read back
    through the same rule as everything else — and a name that *starts* with a
    quote read back as empty, which the "names nothing" check then refused,
    taking the whole ledger down over text the file plainly carries.
    """

    QUOTED = FIXTURES / 'a_description_carrying_quotes.txt'

    def test_the_code_survives(self, tmp_path):
        book, _ = _round_trip(tmp_path, self.QUOTED, 'accounttext')

        assert _text_of(book)['code'] == 'A"B', _text_of(book)

    def test_the_description_survives(self, tmp_path):
        book, _ = _round_trip(tmp_path, self.QUOTED, 'accounttext')

        assert _text_of(book)['description'] == (
            'Called "Old" until 2023; renamed since'), _text_of(book)
