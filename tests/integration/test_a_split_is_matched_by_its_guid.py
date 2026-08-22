"""A split block names its split with `guid:`, and that is what it updates.

The export writes a `guid:` under every split. Re-importing with
`--strategy update` did not read it: splits were paired with the file's
blocks by account name and then by *position within that account*, so two
splits on one account — the repo's own example is a meal and a tip both on
`Expenses:Dining` — were matched by the order they happened to be written
in.

Measured before the fix, on a file holding exactly what the export wrote,
with the two blocks swapped:

    file says   6552… = 20.00 "tip"    14da… = 10.00 "meal"
    book after  6552… = 10.00 "meal"   14da… = 20.00 "tip"

The amounts changed places. The book then contradicted the file that had
just been imported into it, and said `Updated: 1` while doing it.

**Two splits of the same amount are the sharper case**, and the one a
reader would never catch: 15.00 for coffee and 15.00 for cake swap their
*memos* and nothing else moves. No total changes, no balance changes, and
no amount looks wrong — the only thing that says which split is which is
the guid the file already carries.

Nothing caught either because a round trip cannot: the export writes the
splits in the book's order, so position and identity agree for every file
this tool produces. It takes a file whose blocks were reordered — by hand,
by a merge, by anything that rewrites a ledger — to tell the two apart.
"""

from fractions import Fraction

import pytest
from click.testing import CliRunner

from cli.main import cli
from infrastructure.gnucash.utils import (
    get_account_full_name,
    money_text,
    numeric_to_fraction,
)
from repositories.gnucash_repository import GnuCashRepository, SessionMode

ACCOUNTS = """2026-01-01 commodity CAD
\tmnemonic: "CAD"
\tfullname: "Canadian Dollar"
\tnamespace: "CURRENCY"
\tfraction: 100
2026-01-01 open Assets
\ttype: Asset
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Assets:Bank
\ttype: Bank
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Expenses
\ttype: Expense
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Expenses:Dining
\ttype: Expense
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Expenses:Groceries
\ttype: Expense
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"

"""

#: `(id, first line, second line)` — two splits on one account. The first
#: pair differ in amount, so a wrong pairing shows up in the figures; the
#: second pair do not, so a wrong pairing shows up nowhere but the memo.
PAIRS = [
    ('different amounts', ('10.00', 'meal'), ('20.00', 'tip')),
    ('the same amount', ('15.00', 'coffee'), ('15.00', 'cake')),
]


def _ledger(first, second):
    # Added as rationals: money in this project never goes through binary
    # floating point, tests included.
    total = Fraction(first[0]) + Fraction(second[0])
    return (ACCOUNTS + '2026-02-01 * "Dinner"\n'
            + f'\tExpenses:Dining {first[0]} CAD\n\t\tmemo:"{first[1]}"\n'
            + f'\tExpenses:Dining {second[0]} CAD\n\t\tmemo:"{second[1]}"\n'
            + f'\tAssets:Bank -{money_text(total, 100)} CAD\n')


def _splits_on(book, account_name):
    """`{guid: (amount, memo)}` for every split on one account."""
    repo = GnuCashRepository(str(book))
    repo.open(SessionMode.READ_ONLY)
    try:
        found = {}
        for account in repo.book.get_root_account().get_descendants():
            if get_account_full_name(account) != account_name:
                continue
            for split in account.GetSplitList():
                found[split.GetGUID().to_string()] = (
                    str(numeric_to_fraction(split.GetAmount())),
                    split.GetMemo())
        return found
    finally:
        repo.close()


def _dining(book):
    return _splits_on(book, 'Expenses:Dining')


def _groceries(book):
    return _splits_on(book, 'Expenses:Groceries')


def _a_second_transactions_split(book, tmp_path):
    """Put a second transaction in the book and return one of its guids."""
    other = tmp_path / 'other.txt'
    other.write_text('2026-03-01 * "Another day"\n'
                     '\tExpenses:Groceries 5.00 CAD\n'
                     '\tAssets:Bank -5.00 CAD\n', encoding='utf-8')
    result = CliRunner().invoke(cli, ['import', str(book), str(other)])
    assert result.exit_code == 0, result.output
    return sorted(_groceries(book))[0]


def _a_settled_invoice(tmp_path):
    """A book holding a paid invoice; returns it and its settling split."""
    ledger = tmp_path / 'settled.txt'
    ledger.write_text(ACCOUNTS + """2026-01-01 open Assets:Accounts Receivable
\ttype: Accounts Receivable
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Income
\ttype: Income
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Income:Sales
\ttype: Income
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"

customer "C-PAID"
\tname: "Paid Ltd"
\tcurrency: CAD

invoice "INV-PAID-001"
\tcustomer_id: "C-PAID"
\tcurrency: CAD
\tdate_opened: 2026-02-01
\tentry:
\t\tdate: 2026-02-01
\t\tdescription: "A line"
\t\taccount: "Income:Sales"
\t\tquantity: 1
\t\tprice: 30
\t\ttaxable: #False
\t\ttax_included: #False
\tposted:
\t\tdate: 2026-02-01
\t\tdue: 2026-03-03
\t\tar_account: "Assets:Accounts Receivable"
\t\tmemo: "INV-PAID-001"
\t\taccumulate: #True
\tpayment:
\t\tdate: 2026-02-10
\t\tamount: 30.00
\t\tbank_account: "Assets:Bank"
\t\tmemo: "Paid"
""", encoding='utf-8')
    book = tmp_path / 'settled.gnucash'
    made = CliRunner().invoke(cli, ['import', '--new', str(book), str(ledger),
                                    '--include-business-objects'])
    assert made.exit_code == 0, made.output

    # The receivable split that settles it: the one in a lot that is not
    # the posting's own.
    repo = GnuCashRepository(str(book))
    repo.open(SessionMode.READ_ONLY)
    try:
        for account in repo.book.get_root_account().get_descendants():
            if get_account_full_name(account) != 'Assets:Accounts Receivable':
                continue
            for split in account.GetSplitList():
                if split.GetMemo() == 'Paid':
                    return book, split.GetGUID().to_string()
        raise AssertionError('no settling split')
    finally:
        repo.close()


def _without_the_receivable_split(text, guid):
    """The same ledger with the split block naming `guid` deleted.

    Its account is named by nothing else on that transaction, so the file
    stops naming the account at all.
    """
    lines = text.split('\n')
    for start, line in enumerate(lines):
        if not line.startswith('\tAssets:Accounts Receivable '):
            continue
        end = start + 1
        while end < len(lines) and lines[end].startswith('\t\t'):
            end += 1
        if any(guid in held for held in lines[start:end]):
            return '\n'.join(lines[:start] + lines[end:])
    raise AssertionError(f'no split block naming {guid}')


def _swap_the_two_dining_blocks(text):
    """The same file with its two `Expenses:Dining` blocks exchanged."""
    lines = text.split('\n')
    starts = [i for i, line in enumerate(lines)
              if line.startswith('\tExpenses:Dining ')]
    assert len(starts) == 2, (starts, text)

    def block(start):
        end = start + 1
        while end < len(lines) and lines[end].startswith('\t\t'):
            end += 1
        return lines[start:end], end

    one, end_one = block(starts[0])
    two, end_two = block(starts[1])
    return '\n'.join(lines[:starts[0]] + two + lines[end_one:starts[1]]
                     + one + lines[end_two:])


def _book(tmp_path, first, second):
    ledger = tmp_path / 'in.txt'
    ledger.write_text(_ledger(first, second), encoding='utf-8')
    book = tmp_path / 'book.gnucash'
    made = CliRunner().invoke(cli, ['import', '--new', str(book), str(ledger)])
    assert made.exit_code == 0, made.output
    return book


def _exported(book, tmp_path, name='out.txt'):
    out = tmp_path / name
    assert CliRunner().invoke(
        cli, ['export', str(book), '--output', str(out)]).exit_code == 0
    return out.read_text(encoding='utf-8')


class TestABlockGivingItsSplitAnotherAccount:
    def test_moves_the_split_and_keeps_its_guid(self, tmp_path):
        """Recategorising is the commonest edit anyone makes to a ledger.

        The blocks are paired within one account, so a block whose account
        line changed found an empty group: it built a new split with a guid
        GnuCash minted, and the split it named was destroyed as an orphan
        of the group it had been in. The identity was lost on exactly the
        edit this format is for.
        """
        book = _book(tmp_path, *PAIRS[0][1:])
        exported = _exported(book, tmp_path)
        before = _dining(book)
        moved = sorted(before, key=lambda guid: before[guid][1])[1]  # 'tip'

        edited = tmp_path / 'edited.txt'
        edited.write_text(
            exported.replace('\tExpenses:Dining 20.00 CAD',
                             '\tExpenses:Groceries 20.00 CAD'),
            encoding='utf-8')
        result = CliRunner().invoke(cli, ['import', str(book), str(edited),
                                          '--strategy', 'update'])
        assert result.exit_code == 0, result.output

        assert moved in _groceries(book), (moved, _groceries(book))
        assert _groceries(book)[moved] == ('20', 'tip'), _groceries(book)
        assert list(_dining(book)) == [g for g in before if g != moved], \
            _dining(book)

    def test_and_moves_nothing_where_a_later_block_is_refused(self, tmp_path):
        """A file that refuses moves nothing, which is what the update path
        says about itself: every refusal before `BeginEdit`.

        Both live in the same pass — the block that recategorises a split
        and the block that names a guid this transaction has not got — so
        one could move a split and the next refuse the file. The run does
        not stop there: the error is collected and the import goes on to
        save whatever else it did, by design, and the moved split would
        have gone to disk under an account no file asked for.
        """
        book = _book(tmp_path, *PAIRS[0][1:])
        elsewhere = _a_second_transactions_split(book, tmp_path)
        exported = _exported(book, tmp_path, 'after.txt')
        before = _dining(book)
        refusing = next(guid for guid, (_, memo) in before.items()
                        if memo == 'tip')

        text = exported.replace('\tExpenses:Dining 10.00 CAD',
                                '\tExpenses:Groceries 10.00 CAD')
        edited = tmp_path / 'edited.txt'
        edited.write_text(text.replace(refusing, elsewhere), encoding='utf-8')
        # The recategorised block is read first, so a pass that moved as it
        # went would have moved it before reaching the refusal.
        written = edited.read_text(encoding='utf-8')
        assert (written.index('Expenses:Groceries 10.00')
                < written.index(elsewhere)), written

        result = CliRunner().invoke(cli, ['import', str(book), str(edited),
                                          '--strategy', 'update'])

        assert result.exit_code != 0, result.output
        assert _dining(book) == before, _dining(book)


class TestAFileThatRecategorisesOneSplitAndLosesAnother:
    def test_moves_nothing_at_all(self, tmp_path):
        """The refusal comes first, so the recategorisation never happens.

        Both live in the same rebuild: one block gives its split another
        account, and the file stops naming the account of a split that is
        in an invoice's lot. Carried out in the order they were read, the
        move landed and the refusal followed it — and the run does not stop
        at an error, it collects it and saves whatever else it did. What
        kept the moved split off the disk was `xaccTransRollbackEdit`
        restoring `split->acc`, which nothing here measures across GnuCash
        3.8 to 5.16. The plan is settled before `BeginEdit` now, so the
        guarantee does not rest on the rollback at all.
        """
        book, settling = _a_settled_invoice(tmp_path)
        exported = _exported(book, tmp_path)
        before = _splits_on(book, 'Assets:Bank')
        assert before, 'the payment should have a bank split'

        recategorised = exported.replace('\tAssets:Bank 30.00 CAD',
                                         '\tExpenses:Dining 30.00 CAD')
        assert recategorised != exported, exported
        edited = tmp_path / 'edited.txt'
        edited.write_text(
            _without_the_receivable_split(recategorised, settling),
            encoding='utf-8')

        result = CliRunner().invoke(cli, ['import', str(book), str(edited),
                                          '--include-business-objects',
                                          '--strategy', 'update'])

        assert result.exit_code != 0, result.output
        assert 'is in lot' in str(result.output) + str(result.exception)
        assert _splits_on(book, 'Assets:Bank') == before, \
            _splits_on(book, 'Assets:Bank')


class TestABlockNamingAGuidTheBookHasNotGot:
    def test_creates_the_split_under_it(self, tmp_path):
        """A guid the book has nowhere is the guid a new split asks for.

        Handed a spare split instead — the positional fallback, which the
        line blocks guard against and these did not — the block updated a
        split the file never named, and the guid it asked for was nowhere
        in the book. The next export then contradicted the file that had
        just been imported.
        """
        book = _book(tmp_path, *PAIRS[0][1:])
        exported = _exported(book, tmp_path)
        wanted = 'ab12ab12ab12ab12ab12ab12ab12ab12'
        before = _dining(book)

        edited = tmp_path / 'edited.txt'
        edited.write_text(exported.replace(sorted(before)[1], wanted),
                          encoding='utf-8')
        result = CliRunner().invoke(cli, ['import', str(book), str(edited),
                                          '--strategy', 'update'])
        assert result.exit_code == 0, result.output

        after = _dining(book)
        assert wanted in after, after
        assert len(after) == len(before), (before, after)


class TestASplitNoBlockNames:
    def test_is_not_destroyed_while_it_is_in_a_lot(self, tmp_path):
        """One mistyped hex digit is enough to get here.

        A guid the book has nowhere is a split being created, so the split
        the block meant is named by nobody and falls in with the surplus —
        and destroying it takes a settlement out of its invoice's lot. The
        account's balance does not move, so nothing looks wrong while the
        invoice reads unpaid.
        """
        book, settling = _a_settled_invoice(tmp_path)
        exported = _exported(book, tmp_path)

        edited = tmp_path / 'edited.txt'
        edited.write_text(
            exported.replace(settling, 'ab12ab12ab12ab12ab12ab12ab12ab12'),
            encoding='utf-8')
        result = CliRunner().invoke(cli, ['import', str(book), str(edited),
                                          '--include-business-objects',
                                          '--strategy', 'update'])

        assert result.exit_code != 0, result.output
        message = str(result.output) + str(result.exception)
        assert settling in message, message
        assert 'is in lot' in message, message

    def test_nor_when_the_file_stops_naming_its_account(self, tmp_path):
        """The other way a split goes unnamed: the block is deleted.

        Its account is then absent from the file altogether, which is a
        different loop from the one that pairs within an account — and the
        same settlement taken out of the same lot.
        """
        book, settling = _a_settled_invoice(tmp_path)
        exported = _exported(book, tmp_path)

        edited = tmp_path / 'edited.txt'
        edited.write_text(_without_the_receivable_split(exported, settling),
                          encoding='utf-8')
        result = CliRunner().invoke(cli, ['import', str(book), str(edited),
                                          '--include-business-objects',
                                          '--strategy', 'update'])

        assert result.exit_code != 0, result.output
        message = str(result.output) + str(result.exception)
        assert settling in message, message
        assert 'is in lot' in message, message


class TestAGuidWrittenWithoutQuotes:
    """All-digit hex names its split like any other guid.

    The format has always taken an unquoted guid — `guid: b2b3…b4` is the
    friction-free hand-written form. All-digit hex is exactly as
    unambiguous, and what stood in its way was the parser: an unquoted
    number goes through `int`, and `int('0000…0022')` is 22, so the digits
    that made it a guid were gone before any reader saw them. The value
    carries them now (`NumberAsWritten`), and the guid is the one in the
    file.

    Read as "this block names no split" — which is what a value nothing
    could parse used to mean — such a block fell through to position, the
    very pairing a guid is written to end: two `Expenses:Dining` blocks,
    one unquoted guid, and the 15.00 coffee and the 15.00 cake swap memos
    with `Updated: 1` and nothing looking wrong. A block naming a *new*
    split lost the guid as quietly, the split coming back under one
    GnuCash minted while the next export contradicted the file that made
    it.
    """

    #: Leading zeros are what a number loses most of: this arrives as 22.
    WROTE = '00000000000000000000000000000022'

    def _a_book_whose_split_was_named_unquoted(self, tmp_path):
        ledger = tmp_path / 'in.txt'
        ledger.write_text(
            ACCOUNTS + '2026-02-01 * "Dinner"\n'
            + '\tExpenses:Dining 10.00 CAD\n'
            + f'\t\tguid: {self.WROTE}\n'
            + '\t\tmemo: "meal"\n'
            + '\tAssets:Bank -10.00 CAD\n', encoding='utf-8')
        book = tmp_path / 'book.gnucash'
        made = CliRunner().invoke(cli, ['import', '--new', str(book),
                                        str(ledger)])
        assert made.exit_code == 0, made.output
        return book

    def test_names_the_split_it_creates(self, tmp_path):
        book = self._a_book_whose_split_was_named_unquoted(tmp_path)

        assert list(_dining(book)) == [self.WROTE], _dining(book)

    def test_and_the_same_line_matches_that_split_next_time(self, tmp_path):
        """The half that position would have got wrong: a second import of
        the same line edits the split it names rather than adding one."""
        book = self._a_book_whose_split_was_named_unquoted(tmp_path)

        # From the export, whose transaction `guid:` `--strategy update`
        # requires — with the split's own guid unquoted again, which is the
        # line under test, and its memo corrected.
        edited = _exported(book, tmp_path).replace(
            f'guid: "{self.WROTE}"', f'guid: {self.WROTE}').replace(
            'memo:"meal"', 'memo:"meal, corrected"')
        assert f'guid: {self.WROTE}\n' in edited, edited
        assert 'meal, corrected' in edited, edited

        again = tmp_path / 'again.txt'
        again.write_text(edited, encoding='utf-8')
        result = CliRunner().invoke(cli, ['import', str(book), str(again),
                                          '--strategy', 'update'])
        assert result.exit_code == 0, result.output

        assert _dining(book) == {self.WROTE: ('10', 'meal, corrected')}, \
            _dining(book)

    @pytest.mark.parametrize('wrote', ['0', '000'])
    def test_and_one_written_as_zeros_is_refused_like_any_other(self, wrote,
                                                                tmp_path):
        """The value that reads as *nothing* rather than as a bad guid.

        An unquoted number is a number, and a number of zero is falsy, so
        every reader asking `if declared` took `guid: 0` for a block
        naming none: it fell through to positional pairing, and the split
        it created carried a guid GnuCash minted. Quoted, `guid: "0"` was
        refused — one value answered two ways by its quotes. Thirty-two
        zeros is a guid and is accepted; these are not.
        """
        ledger = tmp_path / 'in.txt'
        ledger.write_text(
            ACCOUNTS + '2026-02-01 * "Dinner"\n'
            + '\tExpenses:Dining 10.00 CAD\n'
            + f'\t\tguid: {wrote}\n'
            + '\tAssets:Bank -10.00 CAD\n', encoding='utf-8')
        book = tmp_path / 'book.gnucash'
        result = CliRunner().invoke(cli, ['import', '--new', str(book),
                                          str(ledger)])

        assert result.exit_code != 0, result.output
        message = str(result.output) + str(result.exception)
        assert f"'{wrote}'" in message, message

    def test_but_one_too_short_to_be_a_guid_is_refused_as_written(self,
                                                                 tmp_path):
        """And refused for what it is, naming the characters in the file.

        `guid: 22` is two characters, not a guid. Read as the number 22
        there was nothing left to name it by: every remedy the message
        could offer was a guid nobody wrote — 32 characters guessed by the
        padding, in whichever base the padding chose.
        """
        ledger = tmp_path / 'in.txt'
        ledger.write_text(
            ACCOUNTS + '2026-02-01 * "Dinner"\n'
            + '\tExpenses:Dining 10.00 CAD\n'
            + '\t\tguid: 22\n'
            + '\tAssets:Bank -10.00 CAD\n', encoding='utf-8')
        book = tmp_path / 'book.gnucash'
        result = CliRunner().invoke(cli, ['import', '--new', str(book),
                                          str(ledger)])

        assert result.exit_code != 0, result.output
        message = str(result.output) + str(result.exception)
        assert "'22'" in message, message


class TestAGuidNothingCanParse:
    """Refused, rather than read as a block naming no split at all.

    Quoted and malformed is the case left: 32 characters that are not hex.
    Read as "this block names no split" it fell through to position, so a
    file naming one split by a mistyped guid updated another one entirely
    and reported the transaction updated.
    """

    def test_is_refused_on_a_split_the_book_already_has(self, tmp_path):
        book = _book(tmp_path, *PAIRS[1][1:])
        exported = _exported(book, tmp_path)
        before = _dining(book)
        named = sorted(before)[0]

        edited = tmp_path / 'edited.txt'
        edited.write_text(
            exported.replace(f'"{named}"', '"zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz"'),
            encoding='utf-8')
        result = CliRunner().invoke(cli, ['import', str(book), str(edited),
                                          '--strategy', 'update'])

        assert result.exit_code != 0, result.output
        message = str(result.output) + str(result.exception)
        assert 'Invalid GUID format' in message, message
        assert _dining(book) == before, _dining(book)

    def test_is_refused_on_a_split_being_created(self, tmp_path):
        """The create path reads the same key and dropped it as quietly:
        the split came back under a guid GnuCash minted, and the next
        export contradicted the file that made it."""
        ledger = tmp_path / 'in.txt'
        ledger.write_text(
            ACCOUNTS + '2026-02-01 * "Dinner"\n'
            + '\tExpenses:Dining 10.00 CAD\n'
            + '\t\tguid: "zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz"\n'
            + '\tAssets:Bank -10.00 CAD\n', encoding='utf-8')
        book = tmp_path / 'book.gnucash'
        result = CliRunner().invoke(cli, ['import', '--new', str(book),
                                          str(ledger)])

        assert result.exit_code != 0, result.output
        message = str(result.output) + str(result.exception)
        assert 'Invalid GUID format' in message, message


class TestTheSameRuleOnEveryBlockThatCarriesAGuid:
    """A guid nothing can parse is refused wherever it is written.

    The rule was applied to a split block and to an invoice's lines while
    the transaction one line above kept a `try`/`except` that dropped a
    guid it could not read — so the same value was refused on the split
    and taken as "no guid" on the transaction containing it, which is the
    worse of the two: a transaction's guid is what an invoice's
    `txn_guid:` and `posted_txn_guid:` resolve against, and one GnuCash
    minted instead is a guid no file names. An `open` block had the same
    hole for the zero case.
    """

    @pytest.mark.parametrize('wrote', ['"zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz"',
                                       '0', '"0"',
                                       '"00000000000000000000000000000000"'])
    def test_on_a_transaction(self, wrote, tmp_path):
        ledger = tmp_path / 'in.txt'
        ledger.write_text(
            ACCOUNTS + '2026-02-01 * "Dinner"\n'
            + f'\tguid: {wrote}\n'
            + '\tExpenses:Dining 10.00 CAD\n'
            + '\tAssets:Bank -10.00 CAD\n', encoding='utf-8')
        book = tmp_path / 'book.gnucash'

        result = CliRunner().invoke(cli, ['import', '--new', str(book),
                                          str(ledger)])

        assert result.exit_code != 0, result.output
        assert 'GUID' in str(result.output) + str(result.exception), \
            result.output

    @pytest.mark.parametrize('wrote', [
        '00000000000000000000000000000022',
        '"00000000000000000000000000000022"',
        '"00000000-0000-0000-0000-0000000000AB"',
    ])
    def test_and_the_transaction_it_names_is_found_again(self, wrote,
                                                         tmp_path):
        """A guid the book holds is the same guid however it was written.

        The map of what the book holds is keyed by the canonical string,
        and the lookups used the value the file carried: an unquoted
        all-digit guid is a *number* by then, and a number is in no
        dictionary of strings — so `--strategy update` refused a
        transaction the book was holding, quoting `22` at someone who
        wrote thirty-two characters, and the default strategy fell past
        the guid branch to create one and died on the guid already being
        taken. A hyphenated or upper-case guid missed the same way.
        """
        ledger = tmp_path / 'in.txt'
        ledger.write_text(
            ACCOUNTS + '2026-02-01 * "Dinner"\n'
            + f'\tguid: {wrote}\n'
            + '\tExpenses:Dining 10.00 CAD\n'
            + '\t\tmemo: "meal"\n'
            + '\tAssets:Bank -10.00 CAD\n', encoding='utf-8')
        book = tmp_path / 'book.gnucash'
        made = CliRunner().invoke(cli, ['import', '--new', str(book),
                                        str(ledger)])
        assert made.exit_code == 0, made.output

        again = CliRunner().invoke(cli, ['import', str(book), str(ledger),
                                         '--strategy', 'update'])

        assert again.exit_code == 0, again.output
        assert len(_dining(book)) == 1, _dining(book)

    def test_and_on_an_account(self, tmp_path):
        ledger = tmp_path / 'in.txt'
        ledger.write_text(
            ACCOUNTS + '2026-01-01 open Expenses:Travel\n'
            + '\tguid: 0\n'
            + '\ttype: Expense\n'
            + '\tcommodity.namespace: "CURRENCY"\n'
            + '\tcommodity.mnemonic: "CAD"\n', encoding='utf-8')
        book = tmp_path / 'book.gnucash'

        result = CliRunner().invoke(cli, ['import', '--new', str(book),
                                          str(ledger)])

        assert result.exit_code != 0, result.output
        assert 'GUID' in str(result.output) + str(result.exception), \
            result.output


class TestABlockNamingASplitTheBookHasElsewhere:
    def test_is_refused(self, tmp_path):
        """Not paired by position instead, which updates a third split.

        A guid belonging to another transaction's split — or to an account,
        a line, a lot — names no split of this transaction. Fallen through
        to position, that block's amount and memo landed on whichever split
        of its group was spare, the run reported `Updated: 1`, and the book
        contradicted the file. A file assembled out of two exports is how a
        guid arrives on the wrong block.
        """
        book = _book(tmp_path, *PAIRS[0][1:])
        elsewhere = _a_second_transactions_split(book, tmp_path)
        exported = _exported(book, tmp_path, 'after.txt')
        dining = sorted(_dining(book))

        edited = tmp_path / 'edited.txt'
        edited.write_text(exported.replace(dining[1], elsewhere),
                          encoding='utf-8')
        result = CliRunner().invoke(cli, ['import', str(book), str(edited),
                                          '--strategy', 'update'])

        assert result.exit_code != 0, result.output
        message = str(result.output) + str(result.exception)
        assert elsewhere in message, message
        assert 'not a split of this transaction' in message, message


class TestTwoBlocksNamingOneSplit:
    def test_are_refused(self, tmp_path):
        """A guid is one split, so the second block cannot have it.

        Left to fall through to position, that block would update whichever
        split was spare — so a file naming `G` twice would put the second
        block's amount and memo on a third split it never mentioned, and
        report the transaction updated. The line blocks are refused for the
        same reason, in the same words.
        """
        book = _book(tmp_path, *PAIRS[0][1:])
        exported = _exported(book, tmp_path)
        guids = sorted(_dining(book))

        edited = tmp_path / 'edited.txt'
        edited.write_text(exported.replace(guids[1], guids[0]),
                          encoding='utf-8')
        result = CliRunner().invoke(cli, ['import', str(book), str(edited),
                                          '--strategy', 'update'])

        assert result.exit_code != 0, result.output
        message = str(result.output) + str(result.exception)
        assert guids[0] in message, message
        assert 'two splits name guid' in message, message


@pytest.mark.parametrize('label,first,second', PAIRS,
                         ids=[pair[0] for pair in PAIRS])
class TestAFileWhoseBlocksWereReordered:
    def _reordered(self, tmp_path, first, second):
        book = _book(tmp_path, first, second)
        before = _dining(book)
        swapped = tmp_path / 'swapped.txt'
        swapped.write_text(
            _swap_the_two_dining_blocks(_exported(book, tmp_path)),
            encoding='utf-8')
        result = CliRunner().invoke(cli, ['import', str(book), str(swapped),
                                          '--strategy', 'update'])
        assert result.exit_code == 0, result.output
        # Reached the update path — skipped as a duplicate, these tests
        # would pass while proving nothing.
        assert 'Updated:      1' in result.output, result.output
        return book, before

    def test_each_split_keeps_what_its_guid_was_given(
            self, tmp_path, label, first, second):
        """The whole point of writing a guid under a split: the block names
        which split it is, so where it sits in the file cannot decide."""
        book, before = self._reordered(tmp_path, first, second)

        assert _dining(book) == before

    def test_and_the_memo_stays_on_its_own_split(
            self, tmp_path, label, first, second):
        """Stated on its own because it is the half that moves silently
        where the two amounts are equal: nothing in the book's totals
        changes, and the coffee is filed as the cake."""
        book, before = self._reordered(tmp_path, first, second)

        assert {guid: memo for guid, (_, memo) in _dining(book).items()} == \
            {guid: memo for guid, (_, memo) in before.items()}
