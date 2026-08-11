"""Correcting a printed document that was settled by two payments at once.

The single-payment case is covered: a printed document read into a foreign
book, edited and read again, reattaches the settlement its own rebuild
loosened rather than paying twice.

With two payments out of one account the rebuild marks *both* settlements with
the same document guid, so "the settlement this record orphaned" has two
answers and each block has to be given its own. Handed the wrong one, the
retarget checks the block's figure against the split it would move and refuses
a correct file:

    this block says 60.00 arrived, but the split it would move … carries 40.00

Taking the first marked orphan paired them correctly only while the account
listed its splits in the order the document lists its payments. Measured by
walking that list the other way, the correction was refused.

The pairing is not visible in the book — both settlements are this document's
and both go back into its lot — so a test on the book is evidence for nothing
here, and the run has to say which movement it reattached.

The shape was uncovered: every printed fixture carried one payment, and the
two-payment one uses two different bank accounts, so a block's `bank_account:`
told them apart.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner

from cli.main import cli

SOURCE = str(Path('tests/fixtures/an_invoice_paid_twice_from_one_bank.txt'))


def _bank_amounts(book):
    """Every amount that moved through the bank, sorted."""
    from gnucash import Query, Transaction

    from repositories.gnucash_repository import GnuCashRepository, SessionMode

    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        query = Query()
        query.search_for('Trans')
        query.set_book(repo.book)
        found = []
        for raw in query.run():
            for split in Transaction(instance=raw).GetSplitList():
                account = split.GetAccount()
                if account is not None and account.get_full_name() == 'Assets.Bank':
                    found.append(str(split.GetAmount()))
        query.destroy()
        return sorted(found)
    finally:
        repo.close()


def _payments_by_amount(book):
    """{bank amount: transaction guid} for the payments in the book."""
    from gnucash import Query, Transaction

    from repositories.gnucash_repository import GnuCashRepository, SessionMode

    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        query = Query()
        query.search_for('Trans')
        query.set_book(repo.book)
        found = {}
        for raw in query.run():
            transaction = Transaction(instance=raw)
            for split in transaction.GetSplitList():
                account = split.GetAccount()
                if account is not None and account.get_full_name() == 'Assets.Bank':
                    found[str(split.GetAmount())] = \
                        transaction.GetGUID().to_string()
        query.destroy()
        return found
    finally:
        repo.close()


def _what_the_document_says(book, tmp_path, name='out.txt'):
    out = tmp_path / name
    result = CliRunner().invoke(cli, [
        'export', str(book), str(out), '--include-business-objects'])
    assert result.exit_code == 0, result.output
    return out.read_text()


@pytest.fixture
def elsewhere(tmp_path):
    """A second book built from the printed document, not from the ledger."""
    runner = CliRunner()
    source = tmp_path / 'source.gnucash'
    assert runner.invoke(cli, ['import', '--new', str(source), SOURCE,
                               '--include-business-objects']).exit_code == 0

    printed = tmp_path / 'printed.txt'
    assert runner.invoke(cli, [
        'print-invoice', str(source), 'INV-TWICE',
        '--format', 'plaintext', '-o', str(printed)]).exit_code == 0

    book = tmp_path / 'elsewhere.gnucash'
    assert runner.invoke(cli, ['import', '--new', str(book), SOURCE,
                               '--include-business-objects']).exit_code == 0
    return book, printed


class TestCorrectingIt:
    def test_the_edited_document_re_imports(self, elsewhere, tmp_path):
        book, printed = elsewhere
        edited = tmp_path / 'edited.txt'
        edited.write_text(printed.read_text().replace(
            '\tcurrency: CAD', '\tnotes: "Corrected"\n\tcurrency: CAD', 1))

        result = CliRunner().invoke(cli, [
            'import', str(book), str(edited), '--include-business-objects'])

        assert result.exit_code == 0, result.output

    def test_the_money_still_moved_once_each(self, elsewhere, tmp_path):
        """Two payments in, two payments out — neither doubled, neither lost."""
        book, printed = elsewhere
        before = _bank_amounts(book)
        assert before == ['4000/100', '6000/100'], before

        edited = tmp_path / 'edited.txt'
        edited.write_text(printed.read_text().replace(
            '\tcurrency: CAD', '\tnotes: "Corrected"\n\tcurrency: CAD', 1))
        CliRunner().invoke(cli, ['import', str(book), str(edited),
                                 '--include-business-objects'])

        assert _bank_amounts(book) == before

    def test_each_payment_keeps_its_own_date_and_figure(self, elsewhere,
                                                        tmp_path):
        """Both movements come back out of the book as they went in."""
        book, printed = elsewhere
        edited = tmp_path / 'edited.txt'
        edited.write_text(printed.read_text().replace(
            '\tcurrency: CAD', '\tnotes: "Corrected"\n\tcurrency: CAD', 1))
        CliRunner().invoke(cli, ['import', str(book), str(edited),
                                 '--include-business-objects'])

        text = _what_the_document_says(book, tmp_path)
        block = text.split('invoice "INV-TWICE"')[1]
        assert 'date: 2026-01-15' in block, block
        assert 'amount: 60.00' in block, block
        assert 'date: 2026-02-15' in block, block
        assert 'amount: 40.00' in block, block

    def test_a_block_naming_no_orphan_of_its_own_is_not_given_one(
            self, elsewhere, tmp_path):
        """An edited figure describes a movement neither orphan is.

        The search takes a marked orphan matching the block's own figure and
        date. Where none matches it fell back to the first marked orphan
        anyway — handing the block a settlement of a different size, which the
        retarget then rejects with a complaint about mismatched figures
        instead of the block being read for what it says.

        Reached by editing one payment's amount in a document whose blocks
        still carry the guids of the book they were printed from.
        """
        book, printed = elsewhere
        edited = tmp_path / 'edited.txt'
        edited.write_text(printed.read_text().replace('amount: 60.00',
                                                      'amount: 55.00'))

        result = CliRunner().invoke(cli, [
            'import', str(book), str(edited), '--include-business-objects'])

        # Read for what it says, which is where an unresolvable guid
        # describing a payment the book has not got already goes.
        assert 'recording the payment from the block' in result.output, \
            result.output
        # And the other block, which does name an orphan of its own, still
        # gets it — one mismatch does not cost the document the rest.
        assert 'reattaching the settlement this rebuild loosened' in \
            result.output, result.output

    def test_the_figure_the_file_states_is_the_one_booked(self, elsewhere,
                                                          tmp_path):
        """55.00 stated, 55.00 in the book.

        Handed the first marked orphan instead, the 60.00 settlement was
        attached to a block stating 55.00 and the run reported `updated` —
        the figure the file states, ignored in silence.
        """
        book, printed = elsewhere
        edited = tmp_path / 'edited.txt'
        edited.write_text(printed.read_text().replace('amount: 60.00',
                                                      'amount: 55.00'))
        CliRunner().invoke(cli, ['import', str(book), str(edited),
                                 '--include-business-objects'])

        assert '5500/100' in _bank_amounts(book), _bank_amounts(book)

    def test_each_block_reattaches_its_own_movement(self, elsewhere, tmp_path):
        """The pairing itself, which the book cannot be asked about.

        Both settlements are this document's and both go back into its lot, so
        the book reads the same whichever block claimed which — a test on the
        book is evidence for nothing here. What the run says it did is the
        only place the pairing is visible, and it names the transaction.
        """
        book, printed = elsewhere
        before = _payments_by_amount(book)
        edited = tmp_path / 'edited.txt'
        edited.write_text(printed.read_text().replace(
            '\tcurrency: CAD', '\tnotes: "Corrected"\n\tcurrency: CAD', 1))

        result = CliRunner().invoke(cli, [
            'import', str(book), str(edited), '--include-business-objects'])
        assert result.exit_code == 0, result.output

        reattached = [line.rsplit(' ', 1)[1].strip()
                      for line in result.output.splitlines()
                      if 'reattaching the settlement' in line]
        assert len(reattached) == 2, result.output
        # The blocks are read in the order the document writes them — 60.00
        # first, then 40.00 — so each guid has to be the movement of that size.
        assert reattached == [before['6000/100'], before['4000/100']], (
            reattached, before)
