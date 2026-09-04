"""An invoice's id is theirs to choose, and it is used as a file name.

`print-invoice`/`print-bill` with `-o out/` write one file per invoice, named
after the invoice. That is the right thing for a reader opening the
directory, and it means an id — free text, chosen by whoever wrote the ledger
— is joined to a path. Two things follow, and both were measured on real
books before they were fixed:

* an id holding a separator (`2026/001`, an ordinary way to number an invoice)
  addressed a directory nobody made: `FileNotFoundError`, as a traceback,
  after every invoice had been rendered and none written;
* two invoices may share an id — GnuCash does not stop it, and both survive a
  save and reload — so one file was written, the last render kept, and the run
  reported `✓ Wrote 2 invoice(s)`.

What must stay true alongside the fixes: an ordinary id still names its file
the way it always did, because that name is what a script globs for.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner

from cli.main import cli

FIXTURES = Path('tests/fixtures')
ACCOUNTS = str(FIXTURES / 'q019_accounts.txt')


def _a_book(tmp_path):
    path = tmp_path / 'book.gnucash'
    made = CliRunner().invoke(cli, ['import', '--new', str(path), ACCOUNTS])
    assert made.exit_code == 0, made.output
    return path


def _an_invoice(record_id, customer_id='C-NAME'):
    return f'''
invoice "{record_id}"
\tcustomer_id: "{customer_id}"
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
\tposted:
\t\tdate: 2026-03-09
\t\tdue: 2026-04-09
\t\tar_account: "Assets:Accounts Receivable"
\t\tmemo: "{record_id}"
\t\taccumulate: true
'''


def _ledger(tmp_path, *record_ids):
    text = ('customer "C-NAME"\n\tname: "Naming Co."\n\tcurrency: CAD\n'
            + ''.join(_an_invoice(i) for i in record_ids))
    path = tmp_path / 'ledger.txt'
    path.write_text(text, encoding='utf-8')
    return str(path)


class TestAnOrdinaryId:
    def test_names_its_file_the_way_it_always_did(self, tmp_path):
        """The common case must not move: scripts glob for these."""
        book = _a_book(tmp_path)
        assert CliRunner().invoke(cli, [
            'import', str(book), _ledger(tmp_path, 'INV-2026-001'),
            '--include-business-objects']).exit_code == 0

        outdir = tmp_path / 'out'
        result = CliRunner().invoke(cli, [
            'print-invoice', str(book), '*', '--format', 'html',
            '--output', f'{outdir}/'])

        assert result.exit_code == 0, result.output
        assert [p.name for p in sorted(outdir.iterdir())] == \
            ['INV-2026-001.html']


class TestAnIdThatLooksLikeAPath:
    """`2026/001` is a way people number invoices, not a hostile input."""

    def test_it_writes_one_file_inside_the_directory(self, tmp_path):
        book = _a_book(tmp_path)
        assert CliRunner().invoke(cli, [
            'import', str(book), _ledger(tmp_path, '2026/001'),
            '--include-business-objects']).exit_code == 0

        outdir = tmp_path / 'out'
        result = CliRunner().invoke(cli, [
            'print-invoice', str(book), '*', '--format', 'html',
            '--output', f'{outdir}/'])

        assert result.exit_code == 0, result.output
        written = [p for p in outdir.rglob('*') if p.is_file()]
        assert [p.name for p in written] == ['2026-001.html'], written
        # and in the directory the reader named, not a subdirectory of it
        assert written[0].parent == outdir, written[0]

    def test_and_does_not_write_outside_what_was_asked_for(self, tmp_path):
        """The same mechanism pointed the other way."""
        book = _a_book(tmp_path)
        assert CliRunner().invoke(cli, [
            'import', str(book), _ledger(tmp_path, '../escaped'),
            '--include-business-objects']).exit_code == 0

        outdir = tmp_path / 'out'
        result = CliRunner().invoke(cli, [
            'print-invoice', str(book), '*', '--format', 'html',
            '--output', f'{outdir}/'])

        assert result.exit_code == 0, result.output
        assert not (tmp_path / 'escaped.html').exists(), 'wrote outside outdir'
        written = [p for p in outdir.iterdir() if p.is_file()]
        assert len(written) == 1, written


class TestTwoInvoicesWithOneId:
    """GnuCash permits it, so a printed run has to survive it.

    Built through the bindings rather than this tool's importer, which treats
    the id as identity and would update the first rather than add a second —
    the state exists in books, it just cannot be reached by importing.
    """

    @pytest.fixture
    def book_with_two(self, tmp_path):
        book = _a_book(tmp_path)
        assert CliRunner().invoke(cli, [
            'import', str(book), _ledger(tmp_path, 'SAME-ID'),
            '--include-business-objects']).exit_code == 0

        # Through this project's own session layer rather than `Session(...,
        # mode=...)`: GnuCash 3.8's binding has no `mode` keyword, and the
        # repository is where that difference is already handled.
        from gnucash.gnucash_business import Customer, Invoice

        from repositories.gnucash_repository import (
            GnuCashRepository,
            SessionMode,
        )

        repo = GnuCashRepository(str(book))
        repo.open(SessionMode.NORMAL)
        try:
            inner = repo.book
            cad = inner.get_table().lookup('CURRENCY', 'CAD')
            customer = Customer(inner, 'C-SECOND', cad, 'Second Co.')
            Invoice(inner, 'SAME-ID', cad, customer)
            repo.save()
        finally:
            repo.close()
        return book

    def test_both_are_written(self, book_with_two, tmp_path):
        outdir = tmp_path / 'out'
        result = CliRunner().invoke(cli, [
            'print-invoice', str(book_with_two), '*', '--format', 'html',
            '--output', f'{outdir}/'])

        assert result.exit_code == 0, result.output
        written = sorted(p.name for p in outdir.iterdir() if p.is_file())
        assert len(written) == 2, written
        assert 'Wrote 2 invoice(s)' in result.output, result.output

    def test_each_is_named_so_the_other_is_findable(self, book_with_two,
                                                    tmp_path):
        """Both take the guid, not just the second.

        Leaving one on the plain name would mean a reader who found
        `SAME-ID.html` had no reason to suspect a second invoice at all.
        """
        outdir = tmp_path / 'out'
        assert CliRunner().invoke(cli, [
            'print-invoice', str(book_with_two), '*', '--format', 'html',
            '--output', f'{outdir}/']).exit_code == 0

        written = sorted(p.name for p in outdir.iterdir() if p.is_file())
        assert all(name.startswith('SAME-ID_') for name in written), written
        assert written[0] != written[1]

    def test_a_third_id_spelled_like_one_of_those_names_still_gets_its_own(
            self, book_with_two, tmp_path):
        """The disambiguated name is a name too, and an id is free text.

        An invoice whose id happens to read like another's `<id>_<guid>` would
        land on that file — the same overwrite this class exists to stop, one
        step further along — so distinctness is settled on the names rather
        than on the ids they came from.
        """
        outdir = tmp_path / 'first'
        assert CliRunner().invoke(cli, [
            'print-invoice', str(book_with_two), '*', '--format', 'html',
            '--output', f'{outdir}/']).exit_code == 0
        taken = sorted(p.stem for p in outdir.iterdir() if p.is_file())

        assert CliRunner().invoke(cli, [
            'import', str(book_with_two), _ledger(tmp_path, taken[0]),
            '--include-business-objects']).exit_code == 0

        again = tmp_path / 'again'
        result = CliRunner().invoke(cli, [
            'print-invoice', str(book_with_two), '*', '--format', 'html',
            '--output', f'{again}/'])

        assert result.exit_code == 0, result.output
        written = [p.name for p in again.iterdir() if p.is_file()]
        assert len(written) == len(set(written)) == 3, written


class TestABillIsNamedTheSameWay:
    """`print-bill` took the same change, through its own call site.

    Two near-identical call sites is how a fix comes to be applied to one of
    them, so the bill side states its own answer rather than inheriting the
    invoice's.
    """

    def _a_book_with_a_bill(self, tmp_path, record_id):
        book = _a_book(tmp_path)
        ledger = tmp_path / 'bills.txt'
        ledger.write_text(
            'vendor "V-NAME"\n\tname: "Naming Supply"\n\tcurrency: CAD\n'
            f'''
bill "{record_id}"
\tvendor_id: "V-NAME"
\tcurrency: CAD
\tdate_opened: 2026-03-09
\tentry:
\t\tdate: 2026-03-09
\t\tdescription: "Paper"
\t\taction: "Material"
\t\taccount: "Expenses:Office Supplies"
\t\tquantity: 1
\t\tprice: 40
\t\ttaxable: false
\t\ttax_included: false
\tposted:
\t\tdate: 2026-03-09
\t\tdue: 2026-04-09
\t\tap_account: "Liabilities:Accounts Payable"
\t\tmemo: "{record_id}"
\t\taccumulate: true
''', encoding='utf-8')
        made = CliRunner().invoke(cli, ['import', str(book), str(ledger),
                                        '--include-business-objects'])
        assert made.exit_code == 0, made.output
        return book

    def test_an_ordinary_id_names_its_file_the_way_it_always_did(self,
                                                                 tmp_path):
        book = self._a_book_with_a_bill(tmp_path, 'BILL-2026-001')
        outdir = tmp_path / 'out'
        result = CliRunner().invoke(cli, [
            'print-bill', str(book), '*', '--format', 'html',
            '--output', f'{outdir}/'])

        assert result.exit_code == 0, result.output
        assert [p.name for p in sorted(outdir.iterdir())] == \
            ['BILL-2026-001.html']

    def test_and_an_id_holding_a_separator_stays_in_the_directory(self,
                                                                  tmp_path):
        book = self._a_book_with_a_bill(tmp_path, '2026/001')
        outdir = tmp_path / 'out'
        result = CliRunner().invoke(cli, [
            'print-bill', str(book), '*', '--format', 'html',
            '--output', f'{outdir}/'])

        assert result.exit_code == 0, result.output
        written = [p for p in outdir.rglob('*') if p.is_file()]
        assert [p.name for p in written] == ['2026-001.html'], written
        assert written[0].parent == outdir, written[0]


class TestAnIdTooLongToBeAFilename:
    """Length is the third question a free-text id has to answer.

    A filesystem takes 255 bytes for a name. An id past that raised `OSError`
    from the write — after every invoice in the run had been rendered, which
    leaves the ones before the offender on disk and the rest missing: the
    partial directory the render-everything-first ordering exists to prevent.
    """

    def test_it_is_cut_to_something_writable(self, tmp_path):
        book = _a_book(tmp_path)
        assert CliRunner().invoke(cli, [
            'import', str(book), _ledger(tmp_path, 'A' * 400),
            '--include-business-objects']).exit_code == 0

        outdir = tmp_path / 'out'
        result = CliRunner().invoke(cli, [
            'print-invoice', str(book), '*', '--format', 'html',
            '--output', f'{outdir}/'])

        assert result.exit_code == 0, result.output
        written = [p.name for p in outdir.iterdir() if p.is_file()]
        assert len(written) == 1, written
        assert len(written[0].encode('utf-8')) <= 255, len(written[0])
        assert written[0].startswith('AAAA')


class TestAnIdThatIsNoNameAtAll:
    """`..` is an id a ledger can state, and it addresses a directory
    rather than a file. It becomes `untitled`, because a file has to be called
    something."""

    def test_it_is_written_as_a_file(self, tmp_path):
        book = _a_book(tmp_path)
        assert CliRunner().invoke(cli, [
            'import', str(book), _ledger(tmp_path, '..'),
            '--include-business-objects']).exit_code == 0

        outdir = tmp_path / 'out'
        result = CliRunner().invoke(cli, [
            'print-invoice', str(book), '*', '--format', 'html',
            '--output', f'{outdir}/'])

        assert result.exit_code == 0, result.output
        assert [p.name for p in outdir.iterdir() if p.is_file()] == \
            ['untitled.html']
