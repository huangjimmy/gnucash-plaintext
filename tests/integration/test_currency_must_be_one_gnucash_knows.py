"""A currency GnuCash cannot store is refused, not written and lost.

GnuCash fills the `CURRENCY` namespace from its own ISO 4217 table, and
serialises a currency without `<cmdty:name>` or `<cmdty:fraction>` because it
expects to look both up when the file is read back. A code that is not in that
table has nothing to look up, so the book it writes will not reload: GnuCash
reports `Syntax error in Xml File` and hands back an empty book.

Before this, the import said `Errors: 0` and the summary counted every
account and transaction it had built. The file on disk was unreadable, and
the next command over it — export, report, anything — saw a book with nothing
in it. A ledger imported that way is gone, and nothing said so.

Found while covering the beancount exporter (T-009): a fixture reached for a
mnemonic GnuCash would not have to supply a name for, and the book it built
came back empty.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner

from cli.main import cli

FIXTURES = Path('tests/fixtures')
UNKNOWN = str(FIXTURES / 'commodity_currency_gnucash_does_not_know.txt')


class TestACurrencyOutsideTheIsoTable:
    @pytest.mark.parametrize('extra', [[], ['--include-business-objects']])
    def test_it_exits_non_zero_either_way(self, extra, tmp_path):
        """One file, one answer, whichever flags are passed.

        The two paths used to make commodities in different places — a
        business-objects pass that raised on a failure, and the transaction
        pass that collected it — so the same refused ledger stopped with the
        flag and returned 0 without it, over a `--new` book that had loaded
        nothing. `import … && next-step` cannot read a summary. Commodities
        are made once now, and this holds the answer the same either way.
        """
        gnc = tmp_path / 'refused.gnucash'
        result = CliRunner().invoke(
            cli, ['import', '--new', str(gnc), UNKNOWN, *extra])

        assert result.exit_code != 0, result.output
        assert 'ISO 4217' in result.output, result.output

    def test_the_import_refuses_it_and_says_why(self, tmp_path):
        gnc = tmp_path / 'book.gnucash'
        result = CliRunner().invoke(cli, ['import', '--new', str(gnc), UNKNOWN])

        assert 'Failed to create commodity QQD' in result.output
        assert 'QQD' in result.output
        assert 'CURRENCY' in result.output
        assert 'Errors:       0' not in result.output
        assert 'Errors:       2' in result.output, (
            'the commodity failure and the account that needed it')

    def test_the_message_names_what_to_do_instead(self, tmp_path):
        """There is no such thing as a non-ISO currency; there is a security.

        A unit GnuCash does not issue is a stock or a fund, and those live in
        a namespace of their own — where the name and the fraction are written
        into the file instead of being looked up by code.
        """
        gnc = tmp_path / 'book.gnucash'
        result = CliRunner().invoke(cli, ['import', '--new', str(gnc), UNKNOWN])

        assert 'ISO 4217' in result.output
        assert 'namespace' in result.output
        assert 'stock or a fund' in result.output

    def test_the_same_unit_imports_as_a_security(self, tmp_path):
        """The route the message sends the reader down has to work.

        Against the book, not the exit code and not the summary: `import`
        reports failures in the summary and exits 0 either way, and the
        summary counts no commodities at all — a file that declares one and
        nothing else reports "Nothing to import" whether it worked or not. So
        `exit_code == 0` and `Errors: 0` are both true of a run that stored
        nothing. This is the test standing behind the refusal's advice, and it
        has to be able to fail.
        """
        from repositories.gnucash_repository import (
            GnuCashRepository,
            SessionMode,
        )

        gnc = tmp_path / 'security.gnucash'
        as_fund = 'tests/fixtures/qqd_declared_as_a_fund.txt'

        result = CliRunner().invoke(cli, ['import', '--new', str(gnc), as_fund])

        assert result.exit_code == 0, result.output
        assert 'Errors:       0' in result.output, result.output
        assert 'Commodities:  1' in result.output, result.output

        repo = GnuCashRepository(str(gnc))
        repo.open(mode=SessionMode.READ_ONLY)
        try:
            stored = repo.book.get_table().lookup('FUND', 'QQD')
            assert stored is not None, 'the fund was not stored'
            assert stored.get_fullname() == 'Q Fund'
            assert stored.get_fraction() == 100
        finally:
            repo.close()

    def test_a_currency_gnucash_knows_still_imports(self, tmp_path):
        """The guard must not refuse the ordinary case it stands next to."""
        gnc = tmp_path / 'ok.gnucash'
        good = tmp_path / 'good.txt'
        good.write_text(
            Path(UNKNOWN).read_text().replace('QQD', 'XCD'))

        result = CliRunner().invoke(cli, ['import', '--new', str(gnc), str(good)])

        assert result.exit_code == 0, result.output
        assert 'Errors:       0' in result.output, result.output
        assert 'ISO 4217' not in result.output, result.output
        # XCD is already in GnuCash's ISO table, so nothing was created —
        # counted on the declaration instead, every re-imported export would
        # report every commodity it holds as new.
        assert 'Commodities:  0' in result.output, result.output

    def test_it_is_saved_with_business_objects_too(self, tmp_path):
        """The flag makes its own accounts, and its own commodities with them.

        The transaction pass then walks the same declarations and finds them
        already in the book, so it answers "created nothing" — and the count
        it returns is what decides whether the book is saved. Discarded, a
        file declaring commodities and nothing else went back to "Nothing to
        import" on this path and wrote a book without them, which is the
        failure the count was added to fix.
        """
        from repositories.gnucash_repository import (
            GnuCashRepository,
            SessionMode,
        )

        gnc = tmp_path / 'flagged.gnucash'
        as_fund = 'tests/fixtures/qqd_declared_as_a_fund.txt'

        result = CliRunner().invoke(cli, [
            'import', '--new', str(gnc), as_fund,
            '--include-business-objects'])

        assert result.exit_code == 0, result.output
        assert 'Errors:       0' in result.output, result.output
        assert 'Commodities:  1' in result.output, result.output
        assert 'Nothing to import' not in result.output, result.output

        repo = GnuCashRepository(str(gnc))
        repo.open(mode=SessionMode.READ_ONLY)
        try:
            assert repo.book.get_table().lookup('FUND', 'QQD') is not None, \
                'the fund was not stored'
        finally:
            repo.close()

    def test_a_fraction_change_is_reported_rather_than_left_blank(self,
                                                                  tmp_path):
        """A run whose only effect is an update said it did nothing.

        The summary printed `commodities_created` alone while `has_changes`
        counted updates too, so the whole thing read `0 / 0 / 0 / 0` and then
        `✓ Changes saved`. That is not hypothetical: GnuCash disagrees with
        itself about ISO fractions across supported versions, so a book moved
        between two distros takes this path on every run, forever.
        """
        gnc = tmp_path / 'fraction.gnucash'
        as_fund = 'tests/fixtures/qqd_declared_as_a_fund.txt'
        assert CliRunner().invoke(
            cli, ['import', '--new', str(gnc), as_fund]).exit_code == 0

        finer = tmp_path / 'finer.txt'
        finer.write_text(
            Path(as_fund).read_text().replace('fraction: 100',
                                              'fraction: 1000'))
        again = CliRunner().invoke(cli, ['import', str(gnc), str(finer)])

        assert again.exit_code == 0, again.output
        assert 'Commodities:  0 created, 1 updated' in again.output, again.output
        assert 'Nothing to import' not in again.output, again.output

    def test_declaring_the_fund_twice_creates_it_once(self, tmp_path):
        """The count is what the book gained, not what the file said."""
        gnc = tmp_path / 'twice.gnucash'
        as_fund = 'tests/fixtures/qqd_declared_as_a_fund.txt'
        assert CliRunner().invoke(
            cli, ['import', '--new', str(gnc), as_fund]).exit_code == 0

        again = CliRunner().invoke(cli, ['import', str(gnc), as_fund])

        assert again.exit_code == 0, again.output
        assert 'Errors:       0' in again.output, again.output
        assert 'Commodities:  0' in again.output, again.output

    def test_the_book_it_refused_is_not_left_holding_half_a_ledger(self, tmp_path):
        """Nothing of it is written, and now not even the empty book.

        The point of refusing the commodity rather than storing it was that
        the book stays readable. It goes further than that now: a `--new` run
        that reported errors takes its book away, so there is no file at all —
        which is the stronger form of the same statement, and the one that
        keeps the retry from being blocked by a file the reader never made.
        """
        gnc = tmp_path / 'book.gnucash'
        result = CliRunner().invoke(cli, ['import', '--new', str(gnc), UNKNOWN])

        assert result.exit_code != 0, result.output
        assert 'QQD' in result.output, result.output
        assert not gnc.exists(), 'a refused import left a book behind'

    def test_a_book_it_imported_into_is_still_readable(self, tmp_path):
        """The same refusal against an existing book, which is not removed.

        `--new` sweeps only what it made. Importing the same ledger into a
        book that was already there has to leave that book alone and
        readable — the commodity is refused, and nothing else is disturbed.
        """
        gnc = tmp_path / 'existing.gnucash'
        assert CliRunner().invoke(cli, [
            'import', '--new', str(gnc),
            'tests/fixtures/account_with_finer_scu.txt']).exit_code == 0

        refused = CliRunner().invoke(cli, ['import', str(gnc), UNKNOWN])
        assert refused.exit_code != 0, refused.output
        assert gnc.exists(), 'an existing book was removed'

        out = tmp_path / 'check.txt'
        exported = CliRunner().invoke(cli, ['export', str(gnc), str(out)])
        assert exported.exit_code == 0, exported.output
        assert out.exists(), 'the export wrote nothing at all'
        text = out.read_text()
        assert 'QQD' not in text, text
        assert 'Expenses:Fuel 18.190 CAD' in text, text
