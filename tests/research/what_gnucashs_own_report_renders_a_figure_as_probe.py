"""Probe: how GnuCash's own report writes a figure, beside how this one does.

The plaintext page writes its own figures, and the question is what it should
write them as — `1100`, `1100.00`, or something else again. That is not a
matter of taste: `--output-format html` draws GnuCash's **own** Balance Sheet
against the same book, so the two pages can be put side by side and GnuCash
asked directly.

The book is built to hold the cases that differ:

- a hundred million, where Guile's float printer wrote `1.0e8`;
- a holding whose value has cents, and one whose value has none;
- a gain that lands on a whole number;
- a share quantity, which is counted rather than valued;
- a Japanese yen balance, because the yen divides into 1 and a page that pads
  every figure to two places would be wrong about it.

    ./scripts/test.sh latest tests/research/what_gnucashs_own_report_renders_a_figure_as_probe.py
"""

import re

from click.testing import CliRunner

from cli.main import cli

AS_OF = '2026-12-31'

LEDGER = '''2026-01-01 commodity CAD
\tmnemonic: "CAD"
\tfullname: "Canadian Dollar"
\tnamespace: "CURRENCY"
\tfraction: 100
2026-01-01 commodity USD
\tmnemonic: "USD"
\tfullname: "US Dollar"
\tnamespace: "CURRENCY"
\tfraction: 100
2026-01-01 commodity JPY
\tmnemonic: "JPY"
\tfullname: "Japanese Yen"
\tnamespace: "CURRENCY"
\tfraction: 1
2026-01-01 open Assets
\ttype: "Asset"
\tplaceholder: #True
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Assets:CAD Bank
\ttype: "Bank"
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Assets:USD Bank
\ttype: "Bank"
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "USD"
2026-01-01 open Assets:JPY Bank
\ttype: "Bank"
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "JPY"
2026-01-01 open Equity
\ttype: "Equity"
\tplaceholder: #True
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Equity:Opening CAD
\ttype: "Equity"
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"

price
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "USD"
\tcurrency.mnemonic: "CAD"
\ttime: "2026-12-31 12:00:00 +0000"
\tvalue: "29/20"
\tsource: "user:price-editor"
\ttype: "last"

price
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "JPY"
\tcurrency.mnemonic: "CAD"
\ttime: "2026-12-31 12:00:00 +0000"
\tvalue: "1/100"
\tsource: "user:price-editor"
\ttype: "last"

2026-01-15 * "Opening capital of a hundred million"
\tcurrency.mnemonic: "CAD"
\tAssets:CAD Bank 100000000.00 CAD
\tEquity:Opening CAD -100000000.00 CAD

2026-02-01 * "Buy 1,000.00 USD at 1.30"
\tcurrency.mnemonic: "CAD"
\tAssets:USD Bank 1000.00 USD
\t\taccount.commodity.mnemonic: "USD"
\t\tshare_price: "13/10"
\t\tvalue: "1300.00"
\tAssets:CAD Bank -1300.00 CAD

2026-03-01 * "Buy 250,000 JPY at 0.01"
\tcurrency.mnemonic: "CAD"
\tAssets:JPY Bank 250000 JPY
\t\taccount.commodity.mnemonic: "JPY"
\t\tshare_price: "1/100"
\t\tvalue: "2500.00"
\tAssets:CAD Bank -2500.00 CAD
'''


def _stripped(markup):
    """Every cell of GnuCash's own page, as text."""
    cells = re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', markup, re.S)
    out = []
    for cell in cells:
        text = re.sub(r'<[^>]+>', '', cell)
        text = (text.replace('&nbsp;', ' ').replace('&amp;', '&')
                    .replace('&#36;', '$').replace('&gt;', '>').replace('&lt;', '<'))
        text = ' '.join(text.split())
        if text:
            out.append(text)
    return out


def test_what_gnucashs_own_report_renders_a_figure_as(tmp_path, capsys):
    book = tmp_path / 'probe.gnucash'
    ledger = tmp_path / 'ledger.txt'
    ledger.write_text(LEDGER, encoding='utf-8')
    made = CliRunner().invoke(cli, ['import', '--new', str(book), str(ledger)])
    assert made.exit_code == 0, made.output

    page = tmp_path / 'gnucash.html'
    drawn = CliRunner().invoke(
        cli, ['balance-sheet', str(book), '--as-of', AS_OF,
              '--output-format', 'html', '--output', str(page)])
    assert drawn.exit_code == 0, drawn.output

    text = CliRunner().invoke(cli, ['balance-sheet', str(book), '--as-of', AS_OF])
    assert text.exit_code == 0, text.output

    with capsys.disabled():
        print()
        print('==== GnuCash\'s own Balance Sheet, every cell holding a digit ====')
        for cell in _stripped(page.read_text(encoding='utf-8')):
            if any(ch.isdigit() for ch in cell):
                print(f'    {cell}')

        print()
        print('==== this report\'s plaintext page, in full ====')
        for line in text.output.splitlines():
            if not line.strip().startswith('#'):
                print(line)
