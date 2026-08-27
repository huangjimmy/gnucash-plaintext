"""A line's `guid:` says which line a block edits, and a line keeps its own.

An entry now carries `guid:` through the export, so an invoice can be edited
without its lines losing the identity the book gave them. Two things follow,
and neither was true while an edit destroyed every line and built them again:

- a block naming **no** guid still edits a line rather than replacing it, so
  a hand-written file — which names none — leaves the guids alone instead of
  renumbering every line of every invoice it touches;
- a guid naming a line that is somebody else's, or the same line twice, is
  refused. Forcing a guid GnuCash already gave to another object is how a
  book gets two of them, and the collection is a hash: the loser is gone.
"""

import pytest
from click.testing import CliRunner

from cli.main import cli

LEDGER = """2026-01-01 commodity CAD
\tmnemonic: "CAD"
\tfullname: "Canadian Dollar"
\tnamespace: "CURRENCY"
\tfraction: 100
2026-01-01 open Assets
\ttype: Asset
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Assets:Accounts Receivable
\ttype: Accounts Receivable
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Liabilities
\ttype: Liability
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Liabilities:Accounts Payable
\ttype: Liability
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
2026-01-01 open Expenses
\ttype: Expense
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Expenses:Supplies
\ttype: Expense
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"

customer "C-ENT"
\tname: "Entry Ltd"
\tcurrency: CAD

vendor "V-ENT"
\tname: "Entry Supplies"
\tcurrency: CAD

invoice "INV-ENT-001"
\tcustomer_id: "C-ENT"
\tcurrency: CAD
\tdate_opened: 2026-02-01
\tentry:
\t\tdate: 2026-02-01
\t\tdescription: "Design"
\t\taccount: "Income:Sales"
\t\tquantity: 1
\t\tprice: 100
\t\ttaxable: #False
\t\ttax_included: #False
\tentry:
\t\tdate: 2026-02-01
\t\tdescription: "Support"
\t\taccount: "Income:Sales"
\t\tquantity: 1
\t\tprice: 40
\t\ttaxable: #False
\t\ttax_included: #False
\tposted: none
\tpayment: none

bill "BILL-ENT-001"
\tvendor_id: "V-ENT"
\tcurrency: CAD
\tdate_opened: 2026-02-01
\tentry:
\t\tdate: 2026-02-01
\t\tdescription: "Paper"
\t\taccount: "Expenses:Supplies"
\t\tquantity: 1
\t\tprice: 20
\t\ttaxable: #False
\t\ttax_included: #False
\tposted: none
\tpayment: none
"""


#: The same invoice, posted — where a line the file states differently is
#: refused rather than rebuilt, so the comparison decides whether the file
#: can be imported at all.
POSTED = LEDGER.replace('\tposted: none\n\tpayment: none\n\nbill', """\tposted:
\t\tdate: 2026-02-01
\t\tdue: 2026-03-03
\t\tar_account: "Assets:Accounts Receivable"
\t\tmemo: "INV-ENT-001"
\t\taccumulate: #True
\tpayment: none

bill""")

#: The same book with a tax table, and a line on each invoice using it.
#: What a line keeps when its block stops naming a field is measured on the
#: tax table, the one field set only where a block names it.
WITH_TAX = (LEDGER
            .replace('customer "C-ENT"', 'taxtable "GST"\n'
                     '\tentry:\n'
                     '\t\taccount: "Income:Sales"\n'
                     '\t\trate: 5.0%\n'
                     '\t\ttype: PERCENT\n'
                     '\ncustomer "C-ENT"')
            .replace('\t\tdescription: "Design"\n',
                     '\t\tdescription: "Design"\n\t\tnotes: "as quoted"\n')
            .replace('\t\tdescription: "Paper"\n',
                     '\t\tdescription: "Paper"\n\t\tnotes: "on account"\n')
            .replace('\t\tprice: 100\n\t\ttaxable: #False\n',
                     '\t\tprice: 100\n\t\ttaxable: #True\n'
                     '\t\ttax_table: "GST"\n')
            .replace('\t\tprice: 20\n\t\ttaxable: #False\n',
                     '\t\tprice: 20\n\t\ttaxable: #True\n'
                     '\t\ttax_table: "GST"\n'))


def _book(tmp_path, ledger_text=LEDGER):
    ledger = tmp_path / 'in.txt'
    ledger.write_text(ledger_text, encoding='utf-8')
    book = tmp_path / 'book.gnucash'
    made = CliRunner().invoke(cli, ['import', '--new', str(book), str(ledger),
                                    '--include-business-objects'])
    assert made.exit_code == 0, made.output
    return book


def _exported(book, tmp_path, name='out.txt'):
    out = tmp_path / name
    assert CliRunner().invoke(cli, [
        'export', str(book), '--output', str(out),
        '--include-business-objects']).exit_code == 0
    return out.read_text(encoding='utf-8')


def _entry_guids(text):
    """`{description: guid}` for every entry block in an exported ledger.

    Read from the entry blocks alone — an account writes `guid:` and
    `description:` too, and reading whichever pair came past last collected
    the accounts as a line described `""`.
    """
    found, in_entry, guid = {}, False, None
    for line in text.splitlines():
        stripped = line.strip()
        if not line.startswith('\t\t'):
            in_entry, guid = stripped == 'entry:', None
        elif not in_entry:
            continue
        elif stripped.startswith('guid: "'):
            guid = stripped[len('guid: "'):-1]
        elif stripped.startswith('description: "'):
            found[stripped[len('description: "'):-1]] = guid
    return found


def _entry_prices(text):
    """`{description: price}` for every entry block, read as it is written."""
    found, in_entry, described = {}, False, None
    for line in text.splitlines():
        stripped = line.strip()
        if not line.startswith('\t\t'):
            in_entry, described = stripped == 'entry:', None
        elif not in_entry:
            continue
        elif stripped.startswith('description: "'):
            described = stripped[len('description: "'):-1]
        elif stripped.startswith('price: ') and described is not None:
            found[described] = stripped[len('price: '):]
    return found


def _reimported(book, tmp_path, text, name='edited.txt'):
    edited = tmp_path / name
    edited.write_text(text, encoding='utf-8')
    return CliRunner().invoke(cli, ['import', str(book), str(edited),
                                    '--include-business-objects'])


def _without_entry_guids(text):
    """The same ledger with no `guid:` under any entry — a hand-written one.

    Only the entry blocks lose theirs: an invoice's own `guid:` sits at one
    tab, an entry's at two, and dropping the invoice's would make this a
    test about finding the invoice instead.
    """
    kept, in_entry = [], False
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        if stripped == 'entry:':
            in_entry = True
        elif not line.startswith('\t\t'):
            in_entry = False
        if in_entry and stripped.startswith('guid: "'):
            continue
        kept.append(line)
    return ''.join(kept)


class TestALineNamingNoGuid:
    def test_keeps_the_guid_it_had(self, tmp_path):
        """The line is edited, not replaced.

        Destroyed and built again, every line of the invoice came back with
        a guid GnuCash had just minted — so a file correcting one word of one
        description renumbered both lines, and anything that had recorded
        what they were pointed at nothing.
        """
        book = _book(tmp_path)
        before = _entry_guids(_exported(book, tmp_path))
        assert len(before) == 3, before

        result = _reimported(book, tmp_path, _without_entry_guids(
            _exported(book, tmp_path).replace('"Support"', '"Support plan"')))
        assert result.exit_code == 0, result.output
        assert 'invoice "INV-ENT-001": updated' in result.output, result.output

        after = _entry_guids(_exported(book, tmp_path, 'again.txt'))
        assert after['Design'] == before['Design'], (before, after)
        assert after['Support plan'] == before['Support'], (before, after)
        assert after['Paper'] == before['Paper'], (before, after)


class TestALineNamingAGuid:
    def test_is_the_line_that_block_edits(self, tmp_path):
        """Not the line sitting in that position.

        The blocks are written the other way round, so pairing by position
        would move `Design` onto `Support`'s line and vice versa — the same
        two amounts and the same two descriptions in the book, on the wrong
        lines, which no total and no balance shows.

        One price changes as well, so the invoice differs from the file and
        the lines are rebuilt: a swap on its own can be answered `unchanged`,
        and a test of what a rebuild does must make one happen.
        """
        book = _book(tmp_path)
        before = _entry_guids(_exported(book, tmp_path))

        exported = _exported(book, tmp_path)
        design = _entry_block(exported, 'Design')
        support = _entry_block(exported, 'Support')
        swapped = exported.replace(
            design + support,
            support.replace('price: 40', 'price: 45') + design)
        assert swapped != exported

        result = _reimported(book, tmp_path, swapped)
        assert result.exit_code == 0, result.output
        assert 'invoice "INV-ENT-001": updated' in result.output, result.output

        again = _exported(book, tmp_path, 'again.txt')
        assert _entry_guids(again) == before, (before, _entry_guids(again))
        assert _entry_prices(again)['Design'] == '100', _entry_prices(again)
        assert _entry_prices(again)['Support'] == '45', _entry_prices(again)

    def test_the_book_has_not_got_is_the_new_line_s_own(self, tmp_path):
        book = _book(tmp_path)
        wanted = 'ab12ab12ab12ab12ab12ab12ab12ab12'

        exported = _exported(book, tmp_path)
        added = exported.replace('\tposted: none\n\tpayment: none\n\nbill', (
            '\tentry:\n'
            f'\t\tguid: "{wanted}"\n'
            '\t\tdate: 2026-02-01\n'
            '\t\tdescription: "Hosting"\n'
            '\t\taccount: "Income:Sales"\n'
            '\t\tquantity: 1\n'
            '\t\tprice: 10\n'
            '\t\ttaxable: #False\n'
            '\t\ttax_included: #False\n'
            '\tposted: none\n\tpayment: none\n\nbill'), 1)
        assert added != exported

        result = _reimported(book, tmp_path, added)
        assert result.exit_code == 0, result.output

        after = _entry_guids(_exported(book, tmp_path, 'again.txt'))
        assert after['Hosting'] == wanted, after


class TestSomeBlocksNamingAGuidAndSomeNot:
    """One file, both kinds of block. Neither may take the other's line."""

    def test_each_block_still_edits_its_own_line(self, tmp_path):
        """The blocks are the other way round and only one names its guid:
        the named one goes by its guid, and the other takes what is left —
        which is its own line, and would be the wrong one if the guid pass
        did not run first."""
        book = _book(tmp_path)
        before = _entry_guids(_exported(book, tmp_path))

        exported = _exported(book, tmp_path)
        design = _entry_block(exported, 'Design')
        support = _entry_block(exported, 'Support')
        swapped = exported.replace(
            design + support,
            support.replace('price: 40', 'price: 45')
            + _without_entry_guids(design))
        assert swapped != exported

        result = _reimported(book, tmp_path, swapped)
        assert result.exit_code == 0, result.output
        assert 'invoice "INV-ENT-001": updated' in result.output, result.output

        again = _exported(book, tmp_path, 'again.txt')
        assert _entry_guids(again) == before, (before, _entry_guids(again))
        assert _entry_prices(again)['Design'] == '100', _entry_prices(again)
        assert _entry_prices(again)['Support'] == '45', _entry_prices(again)

    def test_a_new_line_beside_them_is_the_only_one_created(self, tmp_path):
        """A line the file adds names no guid — there is nothing to name.
        The lines already there keep theirs."""
        book = _book(tmp_path)
        before = _entry_guids(_exported(book, tmp_path))

        exported = _exported(book, tmp_path)
        added = exported.replace(
            _entry_block(exported, 'Design'),
            '\tentry:\n'
            '\t\tdate: 2026-02-01\n'
            '\t\tdescription: "Hosting"\n'
            '\t\taccount: "Income:Sales"\n'
            '\t\tquantity: 1\n'
            '\t\tprice: 10\n'
            '\t\ttaxable: #False\n'
            '\t\ttax_included: #False\n'
            + _entry_block(exported, 'Design'), 1)
        assert added != exported

        result = _reimported(book, tmp_path, added)
        assert result.exit_code == 0, result.output
        assert 'invoice "INV-ENT-001": updated' in result.output, result.output

        after = _entry_guids(_exported(book, tmp_path, 'again.txt'))
        assert after['Design'] == before['Design'], (before, after)
        assert after['Support'] == before['Support'], (before, after)
        assert after['Hosting'] not in before.values(), (before, after)


class TestTheComparisonThatDecidesUnchanged:
    """It has to pair the lines the way the rebuild pairs them."""

    def test_reads_a_reordered_file_as_unchanged(self, tmp_path):
        """Because it is: the same lines, written in another order.

        Compared by position, the two lines look changed — and on a
        **posted** invoice that is refused outright, with a remedy that
        does not work: after `unpost-invoices` the rebuild pairs by guid,
        so the invoice's own line order never changes, it is reposted, and
        the same file is refused again. A file a merge reordered could
        never be imported at all.
        """
        book = _book(tmp_path, POSTED)
        exported = _exported(book, tmp_path)
        design = _entry_block(exported, 'Design')
        support = _entry_block(exported, 'Support')

        result = _reimported(book, tmp_path,
                             exported.replace(design + support,
                                              support + design))

        assert result.exit_code == 0, result.output
        assert 'invoice "INV-ENT-001": unchanged' in result.output, \
            result.output

    def test_reads_two_lines_that_swapped_guids_as_changed(self, tmp_path):
        """The mirror case, and the silent one.

        Every field stays where it is and only the two `guid:` values trade
        places, so a positional comparison sees nothing at all and reports
        `unchanged` — the book then asserting the opposite of what the file
        says about which line is which.
        """
        book = _book(tmp_path)
        exported = _exported(book, tmp_path)
        before = _entry_guids(exported)

        swapped = (exported
                   .replace(before['Design'], 'PLACEHOLDER')
                   .replace(before['Support'], before['Design'])
                   .replace('PLACEHOLDER', before['Support']))
        result = _reimported(book, tmp_path, swapped)
        assert result.exit_code == 0, result.output
        assert 'invoice "INV-ENT-001": updated' in result.output, result.output

        after = _entry_guids(_exported(book, tmp_path, 'again.txt'))
        assert after['Design'] == before['Support'], (before, after)
        assert after['Support'] == before['Design'], (before, after)


class TestAFileThatSaysPostedNone:
    def test_may_change_the_lines_in_the_same_step(self, tmp_path):
        """The refusal is about doing it *quietly*.

        A file saying `posted: none` has asked for the unpost out loud —
        which is what the refusal would send its writer away to do with
        `unpost-invoices`. Refusing it too made the file say a thing the
        tool then told it to say, and the payments such a file orphans are
        warned about as any unpost's are.
        """
        book = _book(tmp_path, POSTED)

        result = _reimported(book, tmp_path, POSTED.replace(
            '\tposted:\n'
            '\t\tdate: 2026-02-01\n'
            '\t\tdue: 2026-03-03\n'
            '\t\tar_account: "Assets:Accounts Receivable"\n'
            '\t\tmemo: "INV-ENT-001"\n'
            '\t\taccumulate: #True\n', '\tposted: none\n'
        ).replace('"Support"', '"Support plan"'))

        assert result.exit_code == 0, result.output
        assert 'invoice "INV-ENT-001": updated' in result.output, result.output

        again = _exported(book, tmp_path, 'again.txt')
        assert 'Support plan' in again, again
        assert 'posted: none' in again, again


class TestALineEditedInPlace:
    @pytest.mark.parametrize('invoice, described, priced', [
        ('invoice "INV-ENT-001"', 'Design', ('price: 100', 'price: 110')),
        ('bill "BILL-ENT-001"', 'Paper', ('price: 20', 'price: 22')),
    ])
    def test_holds_nothing_its_block_did_not_name(self, tmp_path, invoice,
                                                  described, priced):
        """An entry block is the whole line, and that has to stay true of a
        line edited rather than built again.

        A line's tax table is the field that shows it: it is set only where
        the block names one, so a line that had `GST` and is edited by a
        block naming no `tax_table:` would keep charging tax the file does
        not mention — and the invoice's total would come out above what the
        file adds up to, with the page in the book disagreeing with the page
        it was imported from.
        """
        book = _book(tmp_path, WITH_TAX)
        exported = _exported(book, tmp_path)
        assert exported.count('tax_table: "GST"') == 2, exported

        block = _entry_block(exported, described)
        plain = ''.join(line + '\n' for line in block.splitlines()
                        if 'tax_table:' not in line and 'notes:' not in line)
        result = _reimported(book, tmp_path, exported.replace(
            block, plain.replace(*priced)))
        assert result.exit_code == 0, result.output
        assert f'{invoice}: updated' in result.output, result.output

        again = _exported(book, tmp_path, 'again.txt')
        line = _entry_block(again, described)
        assert 'tax_table:' not in line, line
        assert 'notes: ""' in line, line
        assert _entry_guids(again)[described] == _entry_guids(exported)[described]


class TestAGuidTheBookGaveSomethingElse:
    def test_naming_the_same_line_twice_is_refused(self, tmp_path):
        """One guid, two lines. GnuCash's collection is a hash of them, so
        the second line to be given it takes the first's place in the book
        and the first is unreachable — an invoice quietly one line short."""
        book = _book(tmp_path)
        exported = _exported(book, tmp_path)
        guids = _entry_guids(exported)

        result = _reimported(book, tmp_path,
                             exported.replace(guids['Support'],
                                              guids['Design']))

        assert result.exit_code != 0, result.output
        assert guids['Design'] in str(result.output) + str(result.exception)

    def test_naming_another_invoice_s_line_is_refused(self, tmp_path):
        """The bill's line, given to an invoice's. The bill keeps its line
        and the invoice must not be handed it."""
        book = _book(tmp_path)
        exported = _exported(book, tmp_path)
        guids = _entry_guids(exported)

        result = _reimported(book, tmp_path,
                             exported.replace(guids['Support'],
                                              guids['Paper']))

        assert result.exit_code != 0, result.output
        assert guids['Paper'] in str(result.output) + str(result.exception)


def _entry_block(text, description):
    """The whole `entry:` block whose description is `description`."""
    lines = text.splitlines(keepends=True)
    for start, line in enumerate(lines):
        if line.strip() != 'entry:':
            continue
        end = start + 1
        while end < len(lines) and lines[end].startswith('\t\t'):
            end += 1
        block = ''.join(lines[start:end])
        if f'description: "{description}"' in block:
            return block
    raise AssertionError(f'no entry described {description!r}')
