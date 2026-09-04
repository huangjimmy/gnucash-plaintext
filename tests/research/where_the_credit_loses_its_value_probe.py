"""Probe: which step values the credit at par on GnuCash 3.8?

The book is built in three steps after the CAD bank overpayment lands:
attaching the invoice to it (which carves the credit), spending that credit on
a second invoice, and unposting that invoice. This dumps the overpayment
transaction after each, so the step that writes a −100.00 value where −137.00
belongs says so itself.

    ./scripts/test.sh ubuntu20 tests/research/where_the_credit_loses_its_value_probe.py
    ./scripts/test.sh latest   tests/research/where_the_credit_loses_its_value_probe.py
"""

from pathlib import Path

from click.testing import CliRunner

import tests.integration.test_a_credit_handed_back_by_an_unpost_is_checked as t
from repositories.gnucash_repository import GnuCashRepository, SessionMode
from services.foreign_currency import (
    iter_splits,
    split_commodity,
    split_guid,
    transaction_currency,
)

REPORT = []


def _dump(book, when):
    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        seen = set()
        for split in iter_splits(repo.book):
            transaction = split.GetParent()
            if transaction is None:
                continue
            if not (transaction.GetDescription() or '').startswith('FX Customer'):
                continue
            guid = transaction.GetGUID().to_string()
            if guid in seen:
                continue
            seen.add(guid)
            REPORT.append(f'--- {when} (currency '
                          f'{transaction_currency(transaction)}) ---')
            for other in transaction.GetSplitList():
                REPORT.append(
                    f'    {split_guid(other)[:8]} '
                    f'{other.GetAccount().get_full_name()[:34]:34} '
                    f'{split_commodity(other)} '
                    f'amount={other.GetAmount()} value={other.GetValue()}')
    finally:
        repo.close()


def test_probe(tmp_path):
    runner = CliRunner()
    from cli.main import cli
    book = tmp_path / 'book.gnucash'
    started = runner.invoke(cli, [
        'import', '--new', str(book),
        'tests/fixtures/fx_usd_invoice_paid_from_a_cad_bank.txt',
        '--include-business-objects', '--fx-rates', t.RATES])
    assert started.exit_code == 0, started.output

    assert t._run(runner, 'import', str(book),
                  'tests/fixtures/fx_cad_bank_overpaying_a_usd_receivable.txt',
                  '--fx-rates', t.RATES).exit_code == 0
    _dump(book, '1. the bank overpayment as imported')

    attach = tmp_path / 'attach.txt'
    attach.write_text(
        Path('tests/fixtures/fx_usd_invoice_overpaid_from_the_cad_bank.txt')
        .read_text().replace('TXN_GUID', t._the_overpaying_transaction(book)))
    assert t._run(runner, 'import', str(book), str(attach),
                  '--include-business-objects', '--fx-rates', t.RATES
                  ).exit_code == 0
    _dump(book, '2. after the invoice is attached and the credit carved')

    # The engine's own application, which is what this measures.
    assert t._run(runner, 'import', str(book),
                  'tests/fixtures/fx_invoice_auto_applying_a_cad_paid_credit.txt',
                  '--include-business-objects', '--fx-rates', t.RATES
                  ).exit_code == 0
    _dump(book, '3. after the engine applies the credit to a second invoice')

    assert t._run(runner, 'unpost-invoices', str(book),
                  'INV-FX-SPENDS-CREDIT').exit_code == 0
    _dump(book, '4. after that invoice is unposted')

    raise AssertionError('\n'.join(REPORT))
