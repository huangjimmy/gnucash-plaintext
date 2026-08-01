"""Q-035: `--include-business-objects` emits the book's whole chart of accounts.

Business objects reach accounts no split touches — an entry's income or expense
account, a `posted:` block's A/R account, a tax-table entry's tax account. A
posted invoice happens to drag its accounts in through the posting transaction,
but an unposted one contributes nothing, so a book holding only drafts exported
with zero `open` directives and could not be re-imported.

Independent of currency: a plain CAD book with one draft invoice failed the
same way.
"""

from pathlib import Path

from click.testing import CliRunner

from cli.main import cli


def _open_directives(text: str) -> list:
    return [line for line in text.splitlines() if ' open ' in line]


def test_a_book_of_unposted_business_objects_re_imports(tmp_path):
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    result = runner.invoke(cli, ['import', '--new', str(book),
                                 'tests/fixtures/business_objects_with_guids.txt',
                                 '--include-business-objects'])
    assert result.exit_code == 0, result.output

    exported = tmp_path / 'out.txt'
    result = runner.invoke(cli, ['export', str(book), str(exported),
                                 '--include-business-objects'])
    assert result.exit_code == 0, result.output
    text = exported.read_text()
    assert _open_directives(text), text

    fresh = tmp_path / 'fresh.gnucash'
    result = runner.invoke(cli, ['import', '--new', str(fresh), str(exported),
                                 '--include-business-objects'])
    assert result.exit_code == 0, result.output
    assert 'not found' not in result.output, result.output


def test_accounts_reached_only_by_a_draft_invoice_are_exported(tmp_path):
    """The entry's income account has no split at all until the invoice posts,
    yet the file that re-creates the invoice needs it declared."""
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    fixture = tmp_path / 'draft.txt'
    fixture.write_text(
        Path('tests/fixtures/fx_usd_invoice_cad_income.txt').read_text()
        .split('  posted:')[0])
    result = runner.invoke(cli, ['import', '--new', str(book), str(fixture),
                                 '--include-business-objects'])
    assert result.exit_code == 0, result.output

    exported = tmp_path / 'out.txt'
    result = runner.invoke(cli, ['export', str(book), str(exported),
                                 '--include-business-objects'])
    assert result.exit_code == 0, result.output
    text = exported.read_text()
    assert 'open Income:Sales' in text, text
    assert 'open Assets:Accounts Receivable USD' in text, text

    fresh = tmp_path / 'fresh.gnucash'
    result = runner.invoke(cli, ['import', '--new', str(fresh), str(exported),
                                 '--include-business-objects'])
    assert result.exit_code == 0, result.output


def test_a_plain_export_still_carries_only_the_accounts_it_needs(tmp_path):
    """Without business objects the export is unchanged: accounts come from the
    transactions being exported."""
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    result = runner.invoke(cli, ['import', '--new', str(book),
                                 'tests/fixtures/fx_buy_and_borrow_usd.txt',
                                 '--include-business-objects'])
    assert result.exit_code == 0, result.output

    exported = tmp_path / 'plain.txt'
    result = runner.invoke(cli, ['export', str(book), str(exported)])
    assert result.exit_code == 0, result.output
    text = exported.read_text()
    assert 'open Assets:Bank:USD' in text, text
    # Income:FX Gain has no splits in this book and no business object refers
    # to it, so a plain export leaves it out.
    assert 'open Income:FX Gain' not in text, text
