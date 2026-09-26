"""Whether an import skips a transaction as a copy of another when its guid is not in the book.

The book holds a 10.00 USD deposit on 2026-08-13, between Wise USD and Due
from director. A second import then brings the transaction that has its 1.00
USD fee, on the same date and the same two accounts, in a run of its own. The
fee's transaction comes in three forms:

- without a guid;
- with a guid no transaction in the book has;
- without a guid of its own, and with a guid on each split that no split in
  the book has.

Printed for each: the import's summary, and whether the fee's transaction is
in the book afterwards.

Run: ./scripts/test.sh latest tests/research/whether_a_transaction_with_a_guid_not_in_the_book_is_skipped_as_a_duplicate_probe.py -s
"""

import re
from pathlib import Path

from click.testing import CliRunner

from tests.conftest import _run

FIXTURES = 'tests/fixtures/'
BASE = FIXTURES + 'a_usd_invoice_and_bill_for_statement_lines_on_a_holding_account.txt'
RATES = FIXTURES + 'usd_at_the_rates_the_statement_lines_records_were_posted_at.yaml'
LEDGER = FIXTURES + 'a_usd_deposit_and_its_fee_pending_its_cost_basis_the_same_day.txt'
DEPOSIT = '2026-08-13 * "Received money from a customer"'
FEE = '2026-08-13 * "Charges for the deposit"'


def _block(text, head):
    return re.search(rf'{re.escape(head)}\n(?:\t[^\n]*\n)*', text).group(0)


def _case(tmp_path, name, fee):
    where = tmp_path / name
    where.mkdir()
    book = where / 'book.gnucash'
    _run(CliRunner(), 'import', '--new', str(book), BASE, '--include-business-objects',
         '--fx-rates', RATES)
    deposit = where / 'deposit.txt'
    deposit.write_text(_block(Path(LEDGER).read_text(), DEPOSIT))
    _run(CliRunner(), 'import', str(book), str(deposit), '--fx-rates', RATES)
    ledger = where / 'fee.txt'
    ledger.write_text(fee)
    done = CliRunner().invoke(__import__('cli.main').main.cli, [
        'import', str(book), str(ledger), '--fx-rates', RATES])
    exported = where / 'exported.txt'
    _run(CliRunner(), 'export', str(book), str(exported))
    summary = re.search(r'Import Summary:.*?Errors:\s+\d+', done.output, re.S)
    print(f'\n=== {name}: exit {done.exit_code}\n--- the transaction imported\n{fee}'
          f'--- summary\n{summary.group(0) if summary else done.output[-800:]}\n'
          f'--- the transaction that has the fee is in the book: {FEE in exported.read_text()}')


def test_probe(tmp_path):
    fee = _block(Path(LEDGER).read_text(), FEE)
    _case(tmp_path, 'without a guid', fee)
    _case(tmp_path, 'with a guid no transaction in the book has',
          fee.replace(FEE + '\n', FEE + '\n\tguid: "0e530000000000000000000000000fee"\n'))
    _case(tmp_path, 'without a guid of its own, and a guid on each split no split in the book has',
          fee.replace('\tAssets:Wise USD -1.00 USD\n',
                      '\tAssets:Wise USD -1.00 USD\n\t\tguid: "0e530000000000000000000000000f01"\n')
          .replace('\tAssets:Due from director 1.40 CAD\n',
                   '\tAssets:Due from director 1.40 CAD\n\t\tguid: "0e530000000000000000000000000f02"\n'))
