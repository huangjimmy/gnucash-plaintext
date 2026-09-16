"""A book cut short, or a file that is no book, is refused rather than read as a book holding nothing.

From GnuCash 4.4 on, a book whose file stops partway through — a copy or a save
that did not finish — opens with no error as a book with no accounts, and so do
a file of no bytes and an XML file in GnuCash's old `<gnc>` format. GnuCash 3.4
and 3.8 refuse all of them
(`tests/research/what_gnucash_says_to_an_empty_file_or_a_book_cut_short_probe.py`).
Read as empty, `export` wrote a ledger holding nothing and said it had exported
it, and every other command answered about a book the file is not.

So each is refused on every build before GnuCash is asked, and a whole book,
compressed as GnuCash writes it or uncompressed, still reads.
"""

import gzip

import pytest
from click.testing import CliRunner

from cli.main import cli

LEDGER = 'tests/fixtures/fx_buy_and_borrow_usd.txt'
CUT_SHORT = 'The book ends partway through'
NOT_A_BOOK = 'That is not a GnuCash book this tool can read'


@pytest.fixture
def written(tmp_path):
    """The bytes of a book GnuCash wrote."""
    book = tmp_path / 'whole.gnucash'
    made = CliRunner().invoke(cli, ['import', '--new', str(book), LEDGER])
    assert made.exit_code == 0, made.output
    return book.read_bytes()


def _uncompressed(written):
    return gzip.decompress(written) if written[:2] == b'\x1f\x8b' else written


def _export(tmp_path, content):
    book = tmp_path / 'book.gnucash'
    book.write_bytes(content)
    out = tmp_path / 'out.txt'
    return CliRunner().invoke(cli, ['export', str(book), str(out)]), out


class TestRefused:
    def test_a_compressed_book_cut_short(self, tmp_path, written):
        result, out = _export(tmp_path, written[:len(written) // 2])

        assert result.exit_code != 0, result.output
        assert CUT_SHORT in result.output, result.output
        assert not out.exists()

    def test_an_uncompressed_book_cut_short(self, tmp_path, written):
        xml = _uncompressed(written)
        result, out = _export(tmp_path, xml[:len(xml) // 2])

        assert result.exit_code != 0, result.output
        assert CUT_SHORT in result.output, result.output
        assert not out.exists()

    def test_an_empty_file(self, tmp_path):
        result, out = _export(tmp_path, b'')

        assert result.exit_code != 0, result.output
        assert NOT_A_BOOK in result.output, result.output
        assert not out.exists()

    def test_a_file_that_only_starts_like_a_compressed_book(self, tmp_path):
        """The two bytes gzip starts with, and then nothing gzip can read."""
        result, out = _export(tmp_path, b'\x1f\x8b\x08\x00' + b'\x00' * 6
                              + b'this is not compressed data')

        assert result.exit_code != 0, result.output
        assert NOT_A_BOOK in result.output, result.output
        assert not out.exists()

    def test_an_xml_file_in_gnucashs_old_format(self, tmp_path):
        result, out = _export(tmp_path, b'<?xml version="1.0"?>\n<gnc>\n</gnc>\n')

        assert result.exit_code != 0, result.output
        assert NOT_A_BOOK in result.output, result.output
        assert not out.exists()

    def test_an_import_into_a_book_cut_short_leaves_it_as_it_was(self, tmp_path, written):
        cut = written[:len(written) // 2]
        book = tmp_path / 'book.gnucash'
        book.write_bytes(cut)

        result = CliRunner().invoke(cli, ['import', str(book), LEDGER])

        assert result.exit_code != 0, result.output
        assert CUT_SHORT in result.output, result.output
        assert book.read_bytes() == cut
        assert sorted(path.name for path in tmp_path.iterdir()
                      if path.name.startswith('book.gnucash')) == ['book.gnucash']


class TestStillRead:
    def test_a_whole_uncompressed_book(self, tmp_path, written):
        result, out = _export(tmp_path, _uncompressed(written))

        assert result.exit_code == 0, result.output
        assert 'Buy 100 USD at 1.35' in out.read_text(encoding='utf-8')
