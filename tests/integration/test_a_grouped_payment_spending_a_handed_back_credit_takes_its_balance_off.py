"""A grouped payment spending a credit an unpost handed back takes its cost basis balance off.

INV-USD-OVER is overpaid by 100.00 USD into the USD bank, and INV-USD-AUTO
spends that credit whole. `unpost-invoices INV-USD-AUTO` hands it back: the
split carries `applied_from_credit` and the unpost's orphan KVP, and is the
customer's credit again, a cost basis at 1.40 with no balance recorded.
`--strategy update` records `cost_basis_balance: "100.00"` on it, as
`fx-balances` says to.

INV-USD-GROUPED then applies that split with a `Transaction` block. Applying
it spends the credit, so the balance comes off: left on, it would stay on a
split that now settles an invoice, which is no cost basis. Measured on 5.10:
the split keeps `applied_from_credit` and its cost, the balance is gone, and
`--verify-costs` agrees with every figure.

A block stating two splits takes another path, and spends the credit the same
way. `unpost-invoices INV-USD-OVER` loosens that invoice's own settlement,
which a bank paid, beside the credit in the same transaction, and INV-USD-G
applies both. Measured on 5.10: the credit loses its balance and keeps
`applied_from_credit`, the settlement is not recorded as credit, and
`--verify-costs` agrees.
"""

import re
from pathlib import Path

from click.testing import CliRunner

from cli.main import cli

FIXTURES = Path('tests/fixtures')
RATES = FIXTURES / 'fx_rates_usd_dated.yaml'
OVERPAID = FIXTURES / 'fx_invoice_usd_overpaid_into_usd_bank.txt'
AUTO = FIXTURES / 'fx_invoice_auto_applying_the_whole_credit.txt'
GROUPED = FIXTURES / 'a_grouped_payment_applying_a_credit_an_unpost_handed_back.txt'
BESIDE_AN_ORPHAN = FIXTURES / 'a_grouped_payment_applying_a_handed_back_credit_beside_a_bank_paid_orphan.txt'


def _run(*args):
    return CliRunner().invoke(cli, [str(arg) for arg in args])


def _done(*args):
    result = _run(*args)
    assert result.exit_code == 0, result.output
    return result


def _the_credit_handed_back(book):
    """The guid of the split `fx-balances` lists with no balance recorded."""
    listing = _done('fx-balances', book).output
    rows = [line.split()[1] for line in listing.splitlines()
            if 'Accounts Receivable USD' in line and 'none recorded' in line]
    assert len(rows) == 1, listing
    return rows[0]


def _the_transaction_holding(text, split):
    """The guid of the transaction an export writes the split under."""
    transaction = None
    for line in text.splitlines():
        found = re.match(r'\tguid: "([0-9a-f]{32})"$', line)
        if found:
            transaction = found.group(1)
        if line == f'\t\tguid: "{split}"':
            return transaction
    raise AssertionError(f'{split} is not in the export:\n{text}')


def _the_keys_on(text, split):
    """The lines an export writes under the split, from its guid down."""
    lines = text.splitlines()
    start = lines.index(f'\t\tguid: "{split}"')
    keys = []
    for line in lines[start:]:
        if not line.startswith('\t\t'):
            break
        keys.append(line)
    return '\n'.join(keys)


def test_the_grouped_payment_leaves_no_balance_on_the_credit_it_spent(tmp_path):
    book = tmp_path / 'book.gnucash'
    _done('import', '--new', book, OVERPAID, '--include-business-objects', '--fx-rates', RATES)
    _done('import', book, AUTO, '--include-business-objects', '--fx-rates', RATES)
    _done('unpost-invoices', book, 'INV-USD-AUTO')
    credit = _the_credit_handed_back(book)

    exported = tmp_path / 'export.txt'
    _done('export', book, exported)
    text = exported.read_text()
    line = f'\t\tguid: "{credit}"\n'
    transaction = _the_transaction_holding(text, credit)
    stated = tmp_path / 'stated.txt'
    stated.write_text(text.replace(line, line + '\t\tcost_basis_balance: "100.00"\n'))
    _done('import', book, stated, '--strategy', 'update', '--fx-rates', RATES)
    assert 'Total USD cost basis balance: 200.00 USD' in _done('fx-balances', book).output

    grouped = tmp_path / 'grouped.txt'
    grouped.write_text(GROUPED.read_text()
                       .replace('TXN_GUID', transaction).replace('SPLIT_GUID', credit))
    _done('import', book, grouped, '--include-business-objects', '--fx-rates', RATES)

    balances = _run('fx-balances', book, '--verify-costs')
    assert balances.exit_code == 0, balances.output
    assert 'every cost agrees' in balances.output, balances.output
    assert credit not in balances.output, balances.output
    after = tmp_path / 'after.txt'
    _done('export', book, after)
    keys = _the_keys_on(after.read_text(), credit)
    assert 'applied_from_credit: "true"' in keys, keys
    assert 'cost_basis_balance' not in keys, keys


def _the_other_receivable_split(text, transaction, credit):
    """The receivable split beside the credit in the transaction an export writes."""
    lines = text.splitlines()
    start = lines.index(f'\tguid: "{transaction}"')
    others = []
    for at in range(start + 1, len(lines)):
        if not lines[at].startswith('\t'):
            break
        if lines[at].startswith('\tAssets:Accounts Receivable USD '):
            guid = re.match(r'\t\tguid: "([0-9a-f]{32})"$', lines[at + 1]).group(1)
            if guid != credit:
                others.append(guid)
    assert len(others) == 1, others
    return others[0]


def test_a_block_stating_the_credit_beside_a_bank_paid_orphan_takes_its_balance_off(tmp_path):
    book = tmp_path / 'book.gnucash'
    _done('import', '--new', book, OVERPAID, '--include-business-objects', '--fx-rates', RATES)
    _done('import', book, AUTO, '--include-business-objects', '--fx-rates', RATES)
    _done('unpost-invoices', book, 'INV-USD-AUTO')
    credit = _the_credit_handed_back(book)
    _done('unpost-invoices', book, 'INV-USD-OVER')

    exported = tmp_path / 'export.txt'
    _done('export', book, exported)
    text = exported.read_text()
    transaction = _the_transaction_holding(text, credit)
    settlement = _the_other_receivable_split(text, transaction, credit)
    line = f'\t\tguid: "{credit}"\n'
    stated = tmp_path / 'stated.txt'
    stated.write_text(text.replace(line, line + '\t\tcost_basis_balance: "100.00"\n'))
    _done('import', book, stated, '--strategy', 'update', '--fx-rates', RATES)

    grouped = tmp_path / 'grouped.txt'
    grouped.write_text(BESIDE_AN_ORPHAN.read_text()
                       .replace('TXN_GUID', transaction)
                       .replace('SETTLEMENT_GUID', settlement)
                       .replace('CREDIT_GUID', credit))
    _done('import', book, grouped, '--include-business-objects', '--fx-rates', RATES)

    balances = _run('fx-balances', book, '--verify-costs')
    assert balances.exit_code == 0, balances.output
    assert 'every cost agrees' in balances.output, balances.output
    after = tmp_path / 'after.txt'
    _done('export', book, after)
    spent = _the_keys_on(after.read_text(), credit)
    assert 'applied_from_credit: "true"' in spent, spent
    assert 'cost_basis_balance' not in spent, spent
    paid = _the_keys_on(after.read_text(), settlement)
    assert 'applied_from_credit' not in paid, paid
