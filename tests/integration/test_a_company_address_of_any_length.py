"""A company's address is as long as the company's address.

GnuCash keeps the book-level one as a single free multi-line string — the
`Company Address` option, which File → Properties → Business shows as one text
box. Nothing there stops at four lines, and an address with a unit number, a
country and an "attention" line reaches six without being unusual.

The `company` block indexes those lines — `addr[0]` upwards, as many as the
address has. The index is in brackets so that the list stays a syntax rather
than a convention: `addr[7]` is the eighth line and `addr7` is an ordinary
custom key, which is what a book owner naming their own keys expects of a name
they chose.

`addr1`..`addr4` are still read, since ledgers holding them exist, and mean
what they always did: `addr1` is the first line, which is `addr[0]`. A block
spelling one line both ways is refused rather than resolved.

A customer's or a vendor's address is a different object — a `GncAddress`,
which really does have exactly four fields (`SetAddr1`..`SetAddr4`). A fifth
line on one of those blocks is refused: nothing in the book could hold it, and
filing it somewhere that never prints is how it used to be lost.
"""

import time
from pathlib import Path

import pytest
from click.testing import CliRunner

from cli.main import cli
from infrastructure.gnucash.kvp import (
    get_book_custom_metadata,
    get_book_string_option,
    merge_book_custom_metadata,
    set_book_string_option,
)
from repositories.gnucash_repository import GnuCashRepository, SessionMode

FIXTURES = Path('tests/fixtures')
LEDGER = str(FIXTURES / 'a_company_with_a_six_line_address.txt')

SIX = ['42 Example Street', 'Unit 5', 'Springfield ON', 'A1A 1A1', 'CANADA',
       'Attn: Accounts Payable']


def _second_save_apart():
    """GnuCash names its backup file by the second, so two saves inside one
    fail with `ERR_FILEIO_BACKUP_ERROR`."""
    time.sleep(1.1)


def _import(path, ledger, new=False):
    args = ['import'] + (['--new'] if new else []) + [str(path), str(ledger),
                                                      '--include-business-objects']
    return CliRunner().invoke(cli, args)


def _write(tmp_path, name, text):
    target = tmp_path / name
    target.write_text(text, encoding='utf-8')
    return target


def _book_address(path):
    """The lines GnuCash itself holds, which is what its dialogs and its
    reports read."""
    repo = GnuCashRepository(str(path))
    repo.open(SessionMode.READ_ONLY)
    try:
        raw = get_book_string_option(repo.book, 'Business',
                                     'Company Address') or ''
    finally:
        repo.close()
    return raw.split('\n') if raw else []


def _book_custom_keys(path):
    repo = GnuCashRepository(str(path))
    repo.open(SessionMode.READ_ONLY)
    try:
        return get_book_custom_metadata(repo.book) or {}
    finally:
        repo.close()


def _exported_address(path, tmp_path, name='exported.txt'):
    """The `addrN:` lines of the exported `company` block, in file order."""
    out = tmp_path / name
    result = CliRunner().invoke(cli, ['export', str(path), '--output',
                                      str(out), '--include-business-objects'])
    assert result.exit_code == 0, result.output
    lines = []
    for line in out.read_text(encoding='utf-8').splitlines():
        stripped = line.strip()
        if stripped.startswith('addr') and ':' in stripped:
            lines.append(stripped)
    return lines


@pytest.fixture
def book(tmp_path):
    path = tmp_path / 'company.gnucash'
    made = _import(path, LEDGER, new=True)
    assert made.exit_code == 0, made.output
    return path


class TestALedgerThatStatesSixLines:
    """The fixture's address, which is six lines long."""

    def test_every_line_reaches_the_address_gnucash_holds(self, book):
        assert _book_address(book) == SIX

    def test_none_of_them_are_filed_as_custom_metadata(self, book):
        """Where the fifth and sixth used to go: the book-level custom blob,
        which round-trips through the ledger and is never rendered. A book
        whose address ends at line four prints an invoice without its
        country on it."""
        held = _book_custom_keys(book)
        assert not [k for k in held if k.startswith('addr')], held

    def test_the_export_states_all_six(self, book, tmp_path):
        assert _exported_address(book, tmp_path) == [
            'addr[0]: "42 Example Street"',
            'addr[1]: "Unit 5"',
            'addr[2]: "Springfield ON"',
            'addr[3]: "A1A 1A1"',
            'addr[4]: "CANADA"',
            'addr[5]: "Attn: Accounts Payable"',
        ]

    def test_and_a_book_rebuilt_from_that_export_has_the_same_address(
            self, book, tmp_path):
        out = tmp_path / 'exported.txt'
        assert CliRunner().invoke(cli, [
            'export', str(book), '--output', str(out),
            '--include-business-objects']).exit_code == 0

        rebuilt = tmp_path / 'rebuilt.gnucash'
        built = _import(rebuilt, out, new=True)
        assert built.exit_code == 0, built.output
        assert _book_address(rebuilt) == SIX


class TestAnAddressTypedIntoGnuCash:
    """A book this tool did not write the address into.

    The GUI's box takes as many lines as you type. Reading only four of them
    back is a silent truncation: the export is the whole ledger, so what it
    leaves out is gone from any book rebuilt from it.
    """

    def test_the_export_states_every_line_the_book_holds(self, tmp_path):
        path = tmp_path / 'typed.gnucash'
        made = _import(path, LEDGER, new=True)
        assert made.exit_code == 0, made.output

        _second_save_apart()
        repo = GnuCashRepository(str(path))
        repo.open(SessionMode.NORMAL)
        try:
            set_book_string_option(repo.book, 'Business', 'Company Address',
                                   '\n'.join(SIX + ['c/o The Front Desk']))
            repo.save()
        finally:
            repo.close()

        assert _exported_address(path, tmp_path)[-1] == \
            'addr[6]: "c/o The Front Desk"'


class TestThePrintedDocument:
    """The reader's copy, which is the point of holding an address at all.

    Three writers state a company address — the ledger export, `print-invoice`
    and `print-bill` — and each one read the slot for itself. Two were fixed
    and the third still cut the address at four lines, which is exactly the
    drift `services/plaintext_blocks` exists to stop.
    """

    @pytest.fixture
    def book_with_a_document(self, tmp_path):
        path = tmp_path / 'printed.gnucash'
        ledger = tmp_path / 'ledger.txt'
        ledger.write_text(
            Path(LEDGER).read_text(encoding='utf-8')
            + Path(FIXTURES / 'q019_accounts.txt').read_text(encoding='utf-8')
            + '\ncustomer "C-PRINT"\n\tname: "A Customer"\n\tcurrency: CAD\n'
            + _AN_INVOICE, encoding='utf-8')
        made = _import(path, ledger, new=True)
        assert made.exit_code == 0, made.output
        return path

    def test_it_carries_every_line_of_the_address(self, book_with_a_document,
                                                  tmp_path):
        out = tmp_path / 'inv.txt'
        result = CliRunner().invoke(cli, [
            'print-invoice', str(book_with_a_document), 'INV-PRINT-001',
            '--format', 'plaintext', '--output', str(out)])

        assert result.exit_code == 0, result.output
        printed = out.read_text(encoding='utf-8')
        for line in SIX:
            assert line in printed, (line, printed[:2000])


_AN_INVOICE = '''
invoice "INV-PRINT-001"
\tcustomer_id: "C-PRINT"
\tcurrency: CAD
\tdate_opened: 2026-03-09
\tentry:
\t\tdate: 2026-03-09
\t\tdescription: "Consulting"
\t\taction: "Hours"
\t\taccount: "Income:Sales"
\t\tquantity: 1
\t\tprice: 100
\t\ttaxable: false
\t\ttax_included: false
'''


class TestABlockThatNamesSomeOfTheLines:
    """A block says what it is changing.

    This is the format's own rule — `key: "value"` sets, `key: ""` clears, an
    absent key says nothing — and the customer address path has always
    followed it. The book's address rewrote the whole slot from whatever the
    block named, so a block correcting the street deleted the postcode.
    """

    def test_a_line_it_does_not_name_is_left_alone(self, book, tmp_path):
        ledger = _write(tmp_path, 'street.txt',
                        'company\n\taddr[0]: "9 New Road"\n')
        _second_save_apart()
        result = _import(book, ledger)
        assert result.exit_code == 0, result.output

        assert _book_address(book) == ['9 New Road'] + SIX[1:]

    def test_a_line_named_empty_is_cleared(self, book, tmp_path):
        ledger = _write(tmp_path, 'shorter.txt', 'company\n\taddr[5]: ""\n')
        _second_save_apart()
        result = _import(book, ledger)
        assert result.exit_code == 0, result.output

        assert _book_address(book) == SIX[:5]

    def test_a_line_cleared_in_the_middle_keeps_the_ones_after_it_in_place(
            self, book, tmp_path):
        """The number is the line's position, not its order of appearance —
        so clearing line three leaves the country on line five, where the
        rest of the address expects it."""
        ledger = _write(tmp_path, 'gap.txt', 'company\n\taddr[2]: ""\n')
        _second_save_apart()
        result = _import(book, ledger)
        assert result.exit_code == 0, result.output

        assert _book_address(book) == [SIX[0], SIX[1], '', SIX[3], SIX[4],
                                       SIX[5]]


class TestAnAddressLongerThanNine:
    """`addr[10]` is the eleventh line, not something between the first and
    the second. Sorted as text it lands there, which is what a plain sort of
    the keys would do."""

    def test_the_eleventh_line_follows_the_tenth(self, tmp_path):
        lines = [f'Line {n}' for n in range(1, 13)]
        block = 'company\n\tname: "Long Co"\n' + ''.join(
            f'\taddr[{i}]: "{line}"\n' for i, line in enumerate(lines))
        ledger = _write(tmp_path, 'long.txt', block)
        path = tmp_path / 'long.gnucash'
        made = _import(path, ledger, new=True)
        assert made.exit_code == 0, made.output

        assert _book_address(path) == lines


class TestAnIndexThatIsNotALine:
    """A file may not ask for a line absurdly far out — which is a different
    question from how long an address may be.

    Nothing caps the address a *book* holds; the class above pins that it is
    exported in full. But the index is a *position*, so a file naming
    `addr[10000000]` asks for a ten-million-line address built out of ten
    million empty ones: taken at its word it wrote ten megabytes of newlines
    into the book and had every later export state them back, and a wider one
    raised `MemoryError` from the allocation, reaching the reader as a
    sentence about index-sized integers.
    """

    def test_a_line_far_past_any_address_is_refused(self, tmp_path):
        ledger = _write(tmp_path, 'huge.txt',
                        'company\n\taddr[10000000]: "CANADA"\n')
        path = tmp_path / 'huge.gnucash'
        result = _import(path, ledger, new=True)

        assert result.exit_code != 0, result.output
        assert 'addr[10000000]' in result.output
        assert 'typo' in result.output

    def test_and_so_is_one_no_integer_could_hold(self, tmp_path):
        """The shape that used to raise from the allocation itself."""
        ledger = _write(tmp_path, 'wider.txt',
                        'company\n\taddr[99999999999999999999]: "CANADA"\n')
        path = tmp_path / 'wider.gnucash'
        result = _import(path, ledger, new=True)

        assert result.exit_code != 0, result.output
        assert 'index-sized' not in result.output, result.output

    def test_a_book_holding_a_long_address_is_exported_in_full(self,
                                                               tmp_path):
        """Whatever GnuCash holds, whether or not a *file* could ask for it.

        Nothing caps a book's address: GnuCash's box takes as many lines as
        are typed into it, and refusing the export would leave such a book
        with no way out of GnuCash and into this format at all. An address is
        not a sub-cent amount — it can always be stated, it is only more keys.
        """
        path = tmp_path / 'long.gnucash'
        made = CliRunner().invoke(cli, [
            'import', '--new', str(path),
            str(FIXTURES / 'q019_accounts.txt')])
        assert made.exit_code == 0, made.output

        lines = [f'Line {n}' for n in range(1, 121)]
        _second_save_apart()
        repo = GnuCashRepository(str(path))
        repo.open(SessionMode.NORMAL)
        try:
            set_book_string_option(repo.book, 'Business', 'Company Address',
                                   '\n'.join(lines))
            repo.save()
        finally:
            repo.close()

        assert _exported_address(path, tmp_path)[-1] == 'addr[119]: "Line 120"'

    def test_and_a_book_rebuilt_from_that_export_still_has_it(self, tmp_path):
        """So the round trip has no length at which it stops working."""
        path = tmp_path / 'long.gnucash'
        assert CliRunner().invoke(cli, [
            'import', '--new', str(path),
            str(FIXTURES / 'q019_accounts.txt')]).exit_code == 0

        lines = [f'Line {n}' for n in range(1, 121)]
        _second_save_apart()
        repo = GnuCashRepository(str(path))
        repo.open(SessionMode.NORMAL)
        try:
            set_book_string_option(repo.book, 'Business', 'Company Address',
                                   '\n'.join(lines))
            repo.save()
        finally:
            repo.close()

        out = tmp_path / 'exported.txt'
        assert CliRunner().invoke(cli, [
            'export', str(path), '--output', str(out),
            '--include-business-objects']).exit_code == 0
        rebuilt = tmp_path / 'rebuilt.gnucash'
        built = _import(rebuilt, out, new=True)
        assert built.exit_code == 0, built.output

        assert _book_address(rebuilt) == lines

    def test_but_a_long_address_is_still_an_address(self, tmp_path):
        """The ceiling is past any real one, so it refuses typos only."""
        lines = [f'Line {n}' for n in range(1, 41)]
        block = 'company\n\tname: "Long Co"\n' + ''.join(
            f'\taddr[{i}]: "{line}"\n' for i, line in enumerate(lines))
        path = tmp_path / 'forty.gnucash'
        made = _import(path, _write(tmp_path, 'forty.txt', block), new=True)
        assert made.exit_code == 0, made.output

        assert _book_address(path) == lines


class TestTheSpellingThatCameBefore:
    """`addr1`..`addr4` are still read. Ledgers holding them exist — every
    export this tool wrote until now used them — and an address is not a thing
    to drop over a spelling. Nothing writes them any more."""

    def test_the_old_spelling_still_reaches_the_address(self, tmp_path):
        ledger = _write(tmp_path, 'old.txt',
                        'company\n\tname: "Old Co"\n'
                        '\taddr1: "42 Example Street"\n\taddr2: "Unit 5"\n')
        path = tmp_path / 'old.gnucash'
        made = _import(path, ledger, new=True)
        assert made.exit_code == 0, made.output

        assert _book_address(path) == ['42 Example Street', 'Unit 5']

    @pytest.mark.parametrize('old,new,line', [('addr1', 'addr[0]', 1),
                                              ('addr3', 'addr[2]', 3)])
    def test_and_it_is_the_same_line_as_the_new_one(self, tmp_path, old, new,
                                                    line):
        """`addr1` is `addr[0]`, counting as it does from one rather than
        from zero — so a block naming both is naming one line twice, and is
        refused rather than resolved to whichever the reader wrote last.

        The message names the two keys the block actually used and the line
        they share. It used to describe every collision as `addr1`-vs-`addr[0]`
        whatever the line, so a block colliding on line three was told about
        keys it had not written.
        """
        ledger = _write(tmp_path, 'both.txt',
                        f'company\n\t{old}: "42 Example Street"\n'
                        f'\t{new}: "9 New Road"\n')
        path = tmp_path / 'both.gnucash'
        result = _import(path, ledger, new=True)

        assert result.exit_code != 0, result.output
        assert old in result.output and new in result.output
        assert f'line {line}' in result.output

    @pytest.mark.parametrize('padded,meant', [('addr[00]', 'addr[0]'),
                                              ('addr[07]', 'addr[7]')])
    def test_an_index_with_a_leading_zero_is_refused(self, tmp_path, padded,
                                                     meant):
        """One spelling per line, so `addr[07]` cannot quietly be line eight.

        Taken as `addr[7]` it would let one block name a line twice while
        looking like it named two, and the refusal for that reads as though
        the reader had mixed the old spelling with the new — which they had
        not.
        """
        ledger = _write(tmp_path, 'padded.txt',
                        f'company\n\t{padded}: "42 Example Street"\n')
        path = tmp_path / 'padded.gnucash'
        result = _import(path, ledger, new=True)

        assert result.exit_code != 0, result.output
        assert padded in result.output and meant in result.output

    def test_a_bracketed_key_that_is_not_an_address_is_refused(self,
                                                               tmp_path):
        """The brackets mark the format's own numbering, so a block does not
        mint one of its own.

        `note[0]` accepted today is the name the next list-valued key would
        need already taken, in books written before it meant anything — which
        is the position `addr5` left this format in, and the reason the
        brackets exist. Nothing loses a key to this: the parser accepted no
        bracket at all until now, so no ledger holds one.
        """
        ledger = _write(tmp_path, 'minted.txt',
                        'company\n\tname: "Own Co"\n\tnote[0]: "mine"\n')
        path = tmp_path / 'minted.gnucash'
        result = _import(path, ledger, new=True)

        assert result.exit_code != 0, result.output
        assert 'note[0]' in result.output and 'note0' in result.output

    def test_a_key_that_merely_ends_in_a_digit_is_an_ordinary_key(self,
                                                                  tmp_path):
        """The reason the index is in brackets. `addr7` is a name a book
        owner chose, and it round-trips as what it is — not as the eighth
        line of the address."""
        ledger = _write(tmp_path, 'own.txt',
                        'company\n\tname: "Own Co"\n'
                        '\taddr[0]: "42 Example Street"\n'
                        '\taddr7: "a key of my own"\n')
        path = tmp_path / 'own.gnucash'
        made = _import(path, ledger, new=True)
        assert made.exit_code == 0, made.output

        assert _book_address(path) == ['42 Example Street']
        assert _book_custom_keys(path).get('addr7') == 'a key of my own'


class TestABookWhoseAddressIsStillInTheOldSlot:
    """Written before the `company` block had address lines, so they sit in
    the book's custom metadata and the GnuCash option is empty. That slot is
    the only copy such a book has.

    The lines a block names are written *on top of* it. Written instead of it,
    editing one line of a four-line address left the option holding that line
    alone: the other three were dropped from the slot as superseded, the
    option never learnt them, and the export — which reads the slot only when
    the book has no address at all — wrote a one-line address. A block that
    said nothing about the address kept all four, so it was asking to change
    one of them that lost the rest.
    """

    @pytest.fixture
    def legacy(self, tmp_path):
        path = tmp_path / 'legacy.gnucash'
        made = CliRunner().invoke(cli, [
            'import', '--new', str(path),
            str(FIXTURES / 'q019_accounts.txt')])
        assert made.exit_code == 0, made.output

        _second_save_apart()
        repo = GnuCashRepository(str(path))
        repo.open(SessionMode.NORMAL)
        try:
            merge_book_custom_metadata(repo.book, {
                'addr1': '42 Example Street', 'addr2': 'Unit 5',
                'addr3': 'Springfield ON', 'addr4': 'A1A 1A1'})
            repo.save()
        finally:
            repo.close()
        return path

    def test_a_block_that_edits_one_line_keeps_the_others(self, legacy,
                                                          tmp_path):
        ledger = _write(tmp_path, 'street.txt',
                        'company\n\taddr[0]: "9 New Road"\n')
        _second_save_apart()
        result = _import(legacy, ledger)
        assert result.exit_code == 0, result.output

        assert _book_address(legacy) == ['9 New Road', 'Unit 5',
                                         'Springfield ON', 'A1A 1A1']

    def test_and_the_export_states_them(self, legacy, tmp_path):
        """Which is what a rebuild gets."""
        ledger = _write(tmp_path, 'street.txt',
                        'company\n\taddr[0]: "9 New Road"\n')
        _second_save_apart()
        assert _import(legacy, ledger).exit_code == 0

        _second_save_apart()
        assert _exported_address(legacy, tmp_path) == [
            'addr[0]: "9 New Road"',
            'addr[1]: "Unit 5"',
            'addr[2]: "Springfield ON"',
            'addr[3]: "A1A 1A1"',
        ]

    def test_and_the_old_copies_are_gone_from_the_slot(self, legacy,
                                                        tmp_path):
        """All of them, since the option now holds the whole address —
        otherwise the line is stated twice and the stale copy wins."""
        ledger = _write(tmp_path, 'street.txt',
                        'company\n\taddr[0]: "9 New Road"\n')
        _second_save_apart()
        assert _import(legacy, ledger).exit_code == 0

        held = _book_custom_keys(legacy)
        assert not [k for k in held if k.startswith('addr')], held

    def test_a_block_that_says_nothing_about_it_migrates_it_whole(
            self, legacy, tmp_path):
        ledger = _write(tmp_path, 'name.txt', 'company\n\tname: "Renamed"\n')
        _second_save_apart()
        assert _import(legacy, ledger).exit_code == 0

        assert _book_address(legacy) == ['42 Example Street', 'Unit 5',
                                         'Springfield ON', 'A1A 1A1']


class TestABookHoldingItInBothPlaces:
    """The option *and* the old slot, which is a state a book reaches.

    Type an address into File → Properties → Business on a book whose address
    was still in the slot and it holds both. Read as all-or-nothing — the slot
    consulted only when the book has no address at all — a four-line slot
    behind a two-line option had lines three and four in no export and in no
    book rebuilt from one, and no import merged them either, so it was
    permanent.

    The option is the address as far as it goes; the slot supplies what lies
    past the end of it. Never inside it: a line the option lacks within its
    own length was cleared, and putting one back is the export contradicting
    the book.
    """

    @pytest.fixture
    def split(self, tmp_path):
        path = tmp_path / 'split.gnucash'
        made = CliRunner().invoke(cli, [
            'import', '--new', str(path),
            str(FIXTURES / 'q019_accounts.txt')])
        assert made.exit_code == 0, made.output

        _second_save_apart()
        repo = GnuCashRepository(str(path))
        repo.open(SessionMode.NORMAL)
        try:
            merge_book_custom_metadata(repo.book, {
                'addr1': 'was line one', 'addr2': 'was line two',
                'addr3': 'Springfield ON', 'addr4': 'A1A 1A1'})
            set_book_string_option(repo.book, 'Business', 'Company Address',
                                   '9 New Road\nUnit 5')
            repo.save()
        finally:
            repo.close()
        return path

    def test_the_export_states_the_option_then_what_lies_past_it(
            self, split, tmp_path):
        assert _exported_address(split, tmp_path) == [
            'addr[0]: "9 New Road"',
            'addr[1]: "Unit 5"',
            'addr[2]: "Springfield ON"',
            'addr[3]: "A1A 1A1"',
        ]

    def test_an_import_settles_it_onto_the_option(self, split, tmp_path):
        ledger = _write(tmp_path, 'name.txt', 'company\n\tname: "Renamed"\n')
        _second_save_apart()
        assert _import(split, ledger).exit_code == 0

        assert _book_address(split) == ['9 New Road', 'Unit 5',
                                        'Springfield ON', 'A1A 1A1']
        held = _book_custom_keys(split)
        assert not [k for k in held if k.startswith('addr')], held

    def test_and_it_stays_settled(self, split, tmp_path):
        """The second import has nothing left to move, so an unchanged
        ledger stops rewriting the book."""
        ledger = _write(tmp_path, 'name.txt', 'company\n\tname: "Renamed"\n')
        _second_save_apart()
        assert _import(split, ledger).exit_code == 0
        _second_save_apart()
        again = _import(split, ledger)

        assert again.exit_code == 0, again.output
        assert _book_address(split) == ['9 New Road', 'Unit 5',
                                        'Springfield ON', 'A1A 1A1']


class TestAnObjectThatHasNoAddress:
    """An invoice has no address, so `addr1` on one is a key like any other.

    The rules above belong to the blocks that own an address — `company`,
    `customer`, `vendor`. Applied everywhere, a document's own `addr1` was
    read as a line of an address it does not have: a later block naming
    `addr[0]` deleted it as a superseded copy, and a key spelled with a wild
    index was refused for asking too much of an address the document does not
    have.
    """

    def _a_book_with_an_invoice(self, tmp_path, keys):
        path = tmp_path / 'doc.gnucash'
        ledger = _write(tmp_path, 'doc.txt',
                        Path(FIXTURES / 'q019_accounts.txt').read_text(
                            encoding='utf-8')
                        + '\ncustomer "C-DOC"\n\tname: "A Customer"\n'
                          '\tcurrency: CAD\n'
                        + _AN_INVOICE.replace('INV-PRINT-001', 'INV-DOC-001')
                        .replace('C-PRINT', 'C-DOC')
                        + ''.join(f'\t{k}: "{v}"\n' for k, v in keys.items()))
        made = _import(path, ledger, new=True)
        assert made.exit_code == 0, made.output
        return path

    def _invoice_keys(self, path):
        out = path.parent / 'exported.txt'
        assert CliRunner().invoke(cli, [
            'export', str(path), '--output', str(out),
            '--include-business-objects']).exit_code == 0
        block = out.read_text(encoding='utf-8').split('invoice "INV-DOC-001"')
        return block[1].split('\n\n')[0]

    def test_its_own_addr1_survives_a_block_naming_the_other_spelling(
            self, tmp_path):
        path = self._a_book_with_an_invoice(tmp_path, {'addr1': 'mine'})
        # A whole block: a document is rebuilt from its own, so one without
        # `entry:` lines is refused rather than read as an edit.
        later = _write(tmp_path, 'later.txt',
                       _AN_INVOICE.replace('INV-PRINT-001', 'INV-DOC-001')
                       .replace('C-PRINT', 'C-DOC')
                       + '\taddr[0]: "also mine"\n')
        _second_save_apart()
        result = _import(path, later)
        assert result.exit_code == 0, result.output

        block = self._invoice_keys(path)
        assert 'addr1: "mine"' in block, block
        assert 'addr[0]: "also mine"' in block, block

    def test_and_an_index_it_would_refuse_on_an_address_is_just_a_key(
            self, tmp_path):
        path = self._a_book_with_an_invoice(tmp_path,
                                            {'addr[10000000]': 'mine'})

        assert 'addr[10000000]: "mine"' in self._invoice_keys(path)


class TestAnAddressGnuCashCannotHold:
    """A customer's address is a `GncAddress` — four fields, and there is no
    fifth to set. Accepting a fifth line put it in the object's custom
    metadata, where it round-tripped through the ledger and never appeared on
    an invoice: the file said one thing and the printed document showed
    another."""

    @pytest.mark.parametrize('block', ['customer', 'vendor'])
    def test_a_fifth_line_is_refused(self, tmp_path, block):
        ledger = _write(tmp_path, 'five.txt',
                        f'{block} "B-1"\n\tname: "Someone"\n'
                        '\tcurrency: "CAD"\n'
                        '\taddr[0]: "1 Some Way"\n\taddr[4]: "CANADA"\n')
        path = tmp_path / f'{block}.gnucash'
        result = _import(path, ledger, new=True)

        assert result.exit_code != 0, result.output
        assert 'addr[4]' in result.output
        assert 'four' in result.output

    def test_but_the_book_itself_takes_the_line(self, tmp_path):
        """The same index on the `company` block, which is one string rather
        than four fields."""
        ledger = _write(tmp_path, 'book.txt',
                        'company\n\taddr[0]: "1 Some Way"\n'
                        '\taddr[4]: "CANADA"\n')
        path = tmp_path / 'book.gnucash'
        made = _import(path, ledger, new=True)
        assert made.exit_code == 0, made.output

        assert _book_address(path) == ['1 Some Way', '', '', '', 'CANADA']
