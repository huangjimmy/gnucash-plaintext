"""An invoice GnuCash paid from a liability account is exported with that account.

GnuCash's Process Payment dialog applies a customer's payment from whatever
account the reader picks, a liability among them: a deposit the customer left
on `Liabilities:Owed Back`, used later to pay their invoice. The import applies
an invoice's payment only from an asset or an equity account, so a book holds
this payment because GnuCash applied it.

The export still writes the account the money came from on the `payment:`
block, rather than an empty one.
"""

import re
from datetime import datetime

from click.testing import CliRunner
from gnucash import GncNumeric

from cli.main import cli
from infrastructure.gnucash.utils import find_account
from repositories.gnucash_repository import GnuCashRepository, SessionMode
from services.gnucash_importer import _find_invoices_by_id

LEDGER = 'tests/fixtures/invoices_in_each_state_to_unapply.txt'


def test_the_payment_block_states_the_liability_the_money_came_from(tmp_path):
    book = tmp_path / 'book.gnucash'
    made = CliRunner().invoke(cli, ['import', '--new', str(book), LEDGER,
                                    '--include-business-objects'])
    assert made.exit_code == 0, made.output

    repo = GnuCashRepository(str(book))
    repo.open(SessionMode.NORMAL)
    try:
        root = repo.book.get_root_account()
        record, = _find_invoices_by_id(repo.book, 'INV-UNPAID')
        record.ApplyPayment(None, find_account(root, 'Liabilities:Owed Back'),
                            GncNumeric(10000, 100), GncNumeric(1, 1),
                            datetime(2026, 1, 10), 'Deposit applied', '')
        repo.save()
    finally:
        repo.close()

    out = tmp_path / 'out.txt'
    exported = CliRunner().invoke(cli, ['export', str(book), str(out),
                                        '--include-business-objects'])

    assert exported.exit_code == 0, exported.output
    block = re.search(r'^invoice "INV-UNPAID"\n(?:[\t ][^\n]*\n|\n)*',
                      out.read_text(), flags=re.M).group(0)
    assert 'payment:' in block, block
    assert 'account: "Liabilities:Owed Back"' in block, block
