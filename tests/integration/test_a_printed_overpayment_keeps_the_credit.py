"""A printed document states the whole payment, not only its own share.

A payment can be larger than the document it settles: 250.00 against a 100.00
invoice settles it and leaves 150.00 as the customer's credit. `amount:` is
this document's own slice — it has to be, because one deposit can settle
several documents and the bank figure would over-report every one of them — so
the residue is stated separately, as `prepayment:`.

The ledger export has always written it. A printed document did not, and a
printed document is re-importable: the guids in it are what let its own book
relink rather than pay twice, and in any other book they name nothing and the
payment is made from the block. Made from a block saying only `amount: 100`,
the run entered a 100.00 bank movement for money that moved 250.00, left the
customer's 150.00 credit uncreated, marked the invoice settled and exited 0.

Nothing about it was loud. `_check_declared_prepayment` returns at once when
the key is absent, on the reasoning that `amount:` says how much was paid and
GnuCash carves the residue out of it — true of the export's block, where
`amount:` is the bank figure's whole share of this document, and not of a
block whose payment was bigger than the document.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner

from cli.main import cli

FIXTURES = Path('tests/fixtures')
ACCOUNTS = str(FIXTURES / 'payment_roundtrip_accounts.txt')
OVERPAID = str(FIXTURES / 'an_overpaid_invoice_to_print.txt')


def _bank_and_receivable(book):
    """Every Assets:Bank and Assets:Accounts Receivable amount in the book."""
    from gnucash import Query, Transaction

    from repositories.gnucash_repository import GnuCashRepository, SessionMode

    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        query = Query()
        query.search_for('Trans')
        query.set_book(repo.book)
        rows = []
        for raw in query.run():
            for split in Transaction(instance=raw).GetSplitList():
                account = split.GetAccount()
                if account is None:
                    continue
                name = account.get_full_name()
                if name not in ('Assets.Bank', 'Assets.Accounts Receivable'):
                    continue
                rows.append((name, str(split.GetAmount())))
        query.destroy()
        return sorted(rows)
    finally:
        repo.close()


@pytest.fixture
def printed(tmp_path):
    """The invoice, printed out of the book that holds it."""
    runner = CliRunner()
    book = tmp_path / 'source.gnucash'
    assert runner.invoke(cli, ['import', '--new', str(book), ACCOUNTS
                               ]).exit_code == 0
    result = runner.invoke(cli, ['import', str(book), OVERPAID,
                                 '--include-business-objects'])
    assert result.exit_code == 0, result.output

    out = tmp_path / 'INV-OVER.txt'
    printed = runner.invoke(cli, ['print-invoice', str(book), 'INV-OVER',
                                  '--format', 'plaintext', '-o', str(out)])
    assert printed.exit_code == 0, printed.output
    return out


class TestWhatIsPrinted:
    def test_it_states_the_residue(self, printed):
        """`prepayment: 150.00` — the figure the export has always written."""
        assert 'prepayment: 150.00' in printed.read_text(), printed.read_text()


class TestReadIntoABookThatNeverHeldTheDeposit:
    @pytest.fixture
    def rebuilt(self, printed, tmp_path):
        runner = CliRunner()
        book = tmp_path / 'fresh.gnucash'
        assert runner.invoke(cli, ['import', '--new', str(book), ACCOUNTS
                                   ]).exit_code == 0
        result = runner.invoke(cli, ['import', str(book), str(printed),
                                     '--include-business-objects'])
        assert result.exit_code == 0, result.output
        return book

    def test_the_bank_moved_what_it_moved(self, rebuilt):
        """250.00, not the 100.00 that settled the invoice."""
        bank = [amount for name, amount in _bank_and_receivable(rebuilt)
                if name == 'Assets.Bank']

        assert bank == ['25000/100'], _bank_and_receivable(rebuilt)

    def test_the_customers_credit_exists(self, rebuilt):
        """The 150.00 is on the receivable, as the customer's own money."""
        listed = CliRunner().invoke(cli, ['find-prepayments', str(rebuilt)])

        assert listed.exit_code == 0, listed.output
        assert '150.00' in listed.output, listed.output
        assert 'C-OVER' in listed.output, listed.output

    def test_reading_it_again_changes_nothing(self, rebuilt, printed):
        """The second read has to find the money the first one entered.

        Everything that asks "is this movement already here?" compares the
        block's figure against a *bank* split, and the bank holds the whole
        250.00 while `amount:` states the 100.00 that settled the invoice. Read
        as 100.00 the second run matched nothing: the payment looked different
        from the file that wrote it, the document was unposted and rebuilt, the
        rebuild could not find its own orphan, the duplicate guard could not
        see the deposit — and a second 250.00 landed in the bank. Exit 0, and
        again on every read after that.
        """
        before = _bank_and_receivable(rebuilt)

        result = CliRunner().invoke(cli, ['import', str(rebuilt), str(printed),
                                          '--include-business-objects'])

        assert result.exit_code == 0, result.output
        assert _bank_and_receivable(rebuilt) == before, (
            _bank_and_receivable(rebuilt), before)

    def test_the_credit_is_still_one_credit(self, rebuilt, printed):
        CliRunner().invoke(cli, ['import', str(rebuilt), str(printed),
                                 '--include-business-objects'])

        listed = CliRunner().invoke(cli, ['find-prepayments', str(rebuilt)])

        assert listed.exit_code == 0, listed.output
        assert 'Found 1 open pre-payment credit' in listed.output, listed.output

    def test_the_invoice_reads_as_settled(self, rebuilt, tmp_path):
        """Settled by its own 100.00, with the rest still the customer's."""
        out = tmp_path / 'again.txt'
        exported = CliRunner().invoke(cli, ['export', str(rebuilt), str(out),
                                            '--include-business-objects'])
        assert exported.exit_code == 0, exported.output

        block = out.read_text().split('invoice "INV-OVER"')[1]
        assert 'amount: 100.00' in block, block
        assert 'prepayment: 150.00' in block, block
