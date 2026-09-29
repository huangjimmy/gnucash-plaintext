"""A customer's credit spent on an invoice realizes what the credit's cost and the invoice's cost differ by (Q-054).

The author's case, stated on 2026-09-29. INV-USD-OVER bills C-US 100.00 USD,
posted on 2026-01-05 at 1.40 CAD/USD. On 2026-02-25 C-US pays 200.00 USD into
the US dollar bank at 1.37 CAD/USD: 100.00 USD settles INV-USD-OVER, and the
other 100.00 USD is C-US's credit, owed at 1.37 CAD/USD, 137.00 CAD.

On 2026-03-01 INV-USD-WHOLE bills C-US 100.00 USD, and its `payment:` block
spends the whole credit with `from_credit: true`. A receivable carried at
what the invoice was posted at is paid off by a credit carried at 137.00 CAD,
and the difference is realized that day:

1. posted at 1.32 CAD/USD, 132.00 CAD: a gain of 5.00 CAD, on the block's
   `Income:FX Gain $residual$ CAD` line;
2. posted at 1.37 CAD/USD, the credit's own cost: nothing is realized, and no
   gain or loss split is written;
3. posted at 1.42 CAD/USD, 142.00 CAD: a loss of 5.00 CAD, and the block
   states no split for it, so the import refuses the block and says why.
"""

import re
from pathlib import Path

from click.testing import CliRunner

from tests.conftest import _run

FIXTURES = Path('tests/fixtures')
OVERPAID = FIXTURES / 'fx_invoice_usd_overpaid_into_usd_bank.txt'
WITH_THE_LINE = (
    FIXTURES / 'inv_usd_whole_spending_the_customers_credit_with_an_income_fx_gain_residual_line.txt')
STATING_NO_SPLIT = (
    FIXTURES / 'inv_usd_whole_spending_the_customers_credit_stating_no_gain_or_loss_split.txt')
AT_1_32 = FIXTURES / 'fx_rates_usd_1_32_cad_per_usd_on_2026_03_01.yaml'
AT_1_37 = FIXTURES / 'fx_rates_usd_dated.yaml'
AT_1_42 = FIXTURES / 'fx_rates_usd_1_42_cad_per_usd_on_2026_03_01.yaml'
# The overpayment, which holds the credit's split, and so the settlement.
PAYMENT = '2026-02-25 * "US Customer"'


def _overpaid(tmp_path, rates):
    book = tmp_path / 'book.gnucash'
    made = _run(CliRunner(), 'import', '--new', str(book), str(OVERPAID),
                '--include-business-objects', '--fx-rates', str(rates))
    assert made.exit_code == 0, made.output
    return book


def _exported(book, tmp_path):
    ledger = tmp_path / 'exported.txt'
    done = _run(CliRunner(), 'export', str(book), str(ledger), '--include-business-objects')
    assert done.exit_code == 0, done.output
    return ledger.read_text()


def _spend_the_credit(book, tmp_path, fixture, rates, *more):
    """Import `fixture`, stating the credit's transaction and split as the export writes them."""
    listing = _run(CliRunner(), 'fx-balances', str(book)).output
    credit = next(line.split()[1] for line in listing.splitlines()
                  if 'Receivable' in line and 'liability' in line)
    text = _exported(book, tmp_path)
    transaction = re.findall(r'\n\d{4}-\d\d-\d\d \*[^\n]*\n\tguid: "([0-9a-f]{32})"',
                             text[:text.index(f'guid: "{credit}"')])[-1]
    ledger = tmp_path / 'spend.txt'
    ledger.write_text(fixture.read_text().replace('TXN_GUID', transaction)
                      .replace('SPLIT_GUID', credit))
    return _run(CliRunner(), 'import', *more, str(book), str(ledger),
                '--include-business-objects', '--fx-rates', str(rates))


def _sheet(book, rates):
    page = _run(CliRunner(), 'balance-sheet', str(book), '--as-of', '2026-03-31',
                '--fx-rates', str(rates))
    assert page.exit_code == 0, page.output
    return dict(re.findall(r'^\t([a-z_]+): (-?[\d.]+ CAD)', page.output, re.M))


def _consistent(book):
    checked = _run(CliRunner(), '--verify-integrity', str(book))
    assert checked.exit_code == 0, checked.output


def test_1_posted_at_1_32_the_credit_realizes_a_gain_of_5_00_cad(tmp_path):
    """137.00 CAD of credit pays off 132.00 CAD of receivable: 5.00 CAD to Income:FX Gain."""
    book = _overpaid(tmp_path, AT_1_32)

    done = _spend_the_credit(book, tmp_path, WITH_THE_LINE, AT_1_32)

    assert done.exit_code == 0 and 'Errors:       0' in done.output, done.output
    payment = re.search(re.escape(PAYMENT) + r'\n(?:\t[^\n]*\n)*',
                        _exported(book, tmp_path)).group(0)
    assert re.search(r'\tIncome:FX Gain -5\.00 CAD\n(?:\t\t[^\n]*\n)*?'
                     r'\t\ttook_the_residual: #True\n', payment), payment
    assert _sheet(book, AT_1_32)['total_realized_gains'] == '5.00 CAD'
    _consistent(book)


def test_2_posted_at_1_37_the_credit_realizes_nothing_and_no_split_is_written(tmp_path):
    """137.00 CAD of credit pays off 137.00 CAD of receivable: no gain or loss split."""
    book = _overpaid(tmp_path, AT_1_37)

    done = _spend_the_credit(book, tmp_path, WITH_THE_LINE, AT_1_37)

    assert done.exit_code == 0 and 'Errors:       0' in done.output, done.output
    text = _exported(book, tmp_path)
    assert 'took_the_residual' not in text, text
    assert 'Income:FX Gain' not in text.split('\ninvoice ')[0].split('open Income:FX Gain')[-1], text
    assert _sheet(book, AT_1_37)['total_realized_gains'] == '0.00 CAD'
    _consistent(book)


def test_3_posted_at_1_42_a_loss_of_5_00_cad_is_refused_until_the_file_states_where_it_goes(tmp_path):
    """137.00 CAD of credit pays off 142.00 CAD of receivable.

    The block states no split for the 5.00 CAD, so the import refuses it, says
    why, and leaves the book as it was. The user adds the `Income:FX Gain
    $residual$ CAD` line the refusal suggests and imports again, and the loss
    is realized.
    """
    book = _overpaid(tmp_path, AT_1_42)
    on_disk = book.read_bytes()

    refused = _spend_the_credit(book, tmp_path, STATING_NO_SPLIT, AT_1_42, '--atomic')

    assert refused.exit_code != 0, refused.output
    assert ('invoice "INV-USD-WHOLE": the credit this payment spends, 100.00 USD, was '
            'carried at 1.37 CAD/USD, and the invoice was posted at 1.42 CAD/USD, so '
            'spending it realizes -5.00 CAD — add a split to the payment block saying '
            'where that belongs, e.g. `Income:FX Gain $residual$ CAD`') in refused.output, \
        refused.output
    assert book.read_bytes() == on_disk

    done = _spend_the_credit(book, tmp_path, WITH_THE_LINE, AT_1_42, '--atomic')

    assert done.exit_code == 0 and 'Errors:       0' in done.output, done.output
    payment = re.search(re.escape(PAYMENT) + r'\n(?:\t[^\n]*\n)*',
                        _exported(book, tmp_path)).group(0)
    assert re.search(r'\tIncome:FX Gain 5\.00 CAD\n(?:\t\t[^\n]*\n)*?'
                     r'\t\ttook_the_residual: #True\n', payment), payment
    assert _sheet(book, AT_1_42)['total_realized_gains'] == '-5.00 CAD'
    _consistent(book)
