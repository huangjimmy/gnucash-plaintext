"""`batch` runs read commands against one book opened once, each writing its output to a file (Q-058).

Asked by the author, after another user's page needed five processes, each
opening the book: "gnucash plaintext takes a batch file, every two lines are 1
command first and then the path of output, console output is a summary of
batch result, with each command result in output file." The batch only reads.

Each file holds what the command writes when it runs alone. A rates file one
command reads prices that command's page and no other: on a book holding US
dollars and euros, a balance sheet stating 4,050.20 CAD of assets states
7,000.00 CAD with the rates file and 4,050.20 CAD again on the next line.
"""

from click.testing import CliRunner

from tests.conftest import _run
from tests.integration.text_report_pages import FIXTURES, book_from

OPENS_WITH_USD = 'acmu_1_opens_with_1000_usd_that_cost_1298_80_cad_on_2020_01_01.txt'
INVOICES_IN_USD_AND_EUR = (
    'acmu_2_invoices_abc_1000_usd_at_1_2732_cad_per_usd_and_abc_europe_1000_eur_at_1_5608_cad_per_eur_'
    'and_is_paid_in_full.txt')
OVERSTATED = 'a_cost_basis_stating_more_than_the_accounts_hold.txt'


def _a_book_holding_usd_and_eur(tmp_path):
    book = book_from(tmp_path, OPENS_WITH_USD, '--include-business-objects')
    done = _run(CliRunner(), 'import', str(book), str(FIXTURES / INVOICES_IN_USD_AND_EUR),
                '--include-business-objects')
    assert done.exit_code == 0, done.output
    return book


def _batch(tmp_path, book, *lines):
    listed = tmp_path / 'batch.txt'
    listed.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return _run(CliRunner(), 'batch', str(book), str(listed))


def _total_assets(page):
    return [line.strip() for line in page.splitlines() if 'total_assets:' in line]


class TestEachFileHoldsWhatTheCommandWritesAlone:

    def test_every_command_writes_its_file_and_the_run_exits_0(self, tmp_path):
        book = _a_book_holding_usd_and_eur(tmp_path)
        rates = tmp_path / 'rates.yaml'
        rates.write_text('USD/CAD:\n  2021-12-31: 2.00\nEUR/CAD:\n  2021-12-31: 3.00\n')
        out = tmp_path / 'out'
        out.mkdir()

        done = _batch(
            tmp_path, book,
            '# the year end, priced by the book and then by the rates file',
            'balance-sheet --as-of 2021-12-31', f'{out}/sheet.txt',
            '',
            f'balance-sheet --as-of 2021-12-31 --fx-rates {rates}', f'{out}/sheet-at-the-rates.txt',
            'balance-sheet --as-of 2021-12-31', f'{out}/sheet-again.txt',
            'income-statement --start 2021-01-01 --end 2021-12-31', f'{out}/income.txt',
            'export --include-business-objects', f'{out}/ledger.txt',
            'fx-balances', f'{out}/fx-balances.txt',
            'find-prepayments', f'{out}/prepayments.txt')

        assert done.exit_code == 0, done.output
        assert done.output.splitlines() == [
            f'ok      balance-sheet --as-of 2021-12-31 -> {out}/sheet.txt',
            f'ok      balance-sheet --as-of 2021-12-31 --fx-rates {rates} -> '
            f'{out}/sheet-at-the-rates.txt',
            f'ok      balance-sheet --as-of 2021-12-31 -> {out}/sheet-again.txt',
            f'ok      income-statement --start 2021-01-01 --end 2021-12-31 -> {out}/income.txt',
            f'ok      export --include-business-objects -> {out}/ledger.txt',
            f'ok      fx-balances -> {out}/fx-balances.txt',
            f'ok      find-prepayments -> {out}/prepayments.txt',
            '7 commands: 7 succeeded, 0 failed',
        ]

        alone = tmp_path / 'alone'
        alone.mkdir()
        runner = CliRunner()
        for args, written in (
                (['balance-sheet', book, '--as-of', '2021-12-31', '--output',
                  alone / 'sheet.txt'], 'sheet.txt'),
                (['balance-sheet', book, '--as-of', '2021-12-31', '--fx-rates', rates, '--output',
                  alone / 'sheet-at-the-rates.txt'], 'sheet-at-the-rates.txt'),
                (['income-statement', book, '--start', '2021-01-01', '--end', '2021-12-31',
                  '--output', alone / 'income.txt'], 'income.txt'),
                (['export', book, alone / 'ledger.txt', '--include-business-objects'],
                 'ledger.txt')):
            ran = _run(runner, *[str(arg) for arg in args])
            assert ran.exit_code == 0, ran.output
            assert (out / written).read_text() == (alone / written).read_text(), written
        for command, written in (('fx-balances', 'fx-balances.txt'),
                                 ('find-prepayments', 'prepayments.txt')):
            ran = _run(runner, command, str(book))
            assert ran.exit_code == 0, ran.output
            assert (out / written).read_text() == ran.output, written

    def test_every_other_read_command_writes_what_it_writes_alone(self, tmp_path):
        book = _a_book_holding_usd_and_eur(tmp_path)
        out = tmp_path / 'out'
        out.mkdir()
        invoice_posted = '0d590000000000000000000000000021'

        done = _batch(
            tmp_path, book,
            'export-accounts', f'{out}/accounts.txt',
            'export-prices', f'{out}/prices.txt',
            'export-beancount', f'{out}/ledger.beancount',
            f'export-transaction --guid {invoice_posted}', f'{out}/posted.txt',
            'print-invoice INV-ABC --format plaintext', f'{out}/INV-ABC.txt',
            'validate', f'{out}/validate.txt',
            'report income-statement balance-sheet --fiscal-year-end 2021-12-31',
            f'{out}/report.txt',
            'account-balance Assets --as-of 2021-12-31', f'{out}/assets.txt',
            "find-transactions --account 'Assets:Chase Chequing'", f'{out}/chequing.txt',
            'find-orphan-payments', f'{out}/orphans.txt',
            'verify-integrity', f'{out}/integrity.txt')

        assert done.exit_code == 0, done.output
        assert done.output.splitlines()[-1] == '11 commands: 11 succeeded, 0 failed', done.output

        alone = tmp_path / 'alone'
        alone.mkdir()
        runner = CliRunner()
        for args, written in (
                (['export-accounts', book, alone / 'accounts.txt'], 'accounts.txt'),
                (['export-prices', book, alone / 'prices.txt'], 'prices.txt'),
                (['export-beancount', book, alone / 'ledger.beancount'], 'ledger.beancount'),
                (['export-transaction', book, '--guid', invoice_posted, '--output',
                  alone / 'posted.txt'], 'posted.txt'),
                (['print-invoice', book, 'INV-ABC', '--format', 'plaintext', '--output',
                  alone / 'INV-ABC.txt'], 'INV-ABC.txt'),
                (['report', book, 'income-statement', 'balance-sheet', '--fiscal-year-end',
                  '2021-12-31', '--output', alone / 'report.txt'], 'report.txt')):
            ran = _run(runner, *[str(arg) for arg in args])
            assert ran.exit_code == 0, ran.output
            assert (out / written).read_text() == (alone / written).read_text(), written
        assert 'INV-ABC' in (out / 'INV-ABC.txt').read_text()
        assert invoice_posted in (out / 'posted.txt').read_text()
        for args, written in (
                (['validate'], 'validate.txt'),
                (['account-balance', 'Assets', '--as-of', '2021-12-31'], 'assets.txt'),
                (['find-transactions', '--account', 'Assets:Chase Chequing'], 'chequing.txt'),
                (['find-orphan-payments'], 'orphans.txt'),
                (['verify-integrity'], 'integrity.txt')):
            ran = _run(runner, args[0], str(book), *args[1:])
            assert ran.exit_code == 0, ran.output
            assert (out / written).read_text() == ran.output, written

    def test_a_bill_prints_as_it_prints_alone(self, tmp_path):
        book = book_from(tmp_path, 'a_book_with_a_date_format.txt', '--include-business-objects')

        done = _batch(tmp_path, book,
                      'print-bill BILL-DATE-001 --format plaintext', f'{tmp_path}/bill.txt')

        assert done.exit_code == 0, done.output
        ran = _run(CliRunner(), 'print-bill', str(book), 'BILL-DATE-001', '--format',
                   'plaintext', '--output', str(tmp_path / 'alone.txt'))
        assert ran.exit_code == 0, ran.output
        assert (tmp_path / 'bill.txt').read_text() == (tmp_path / 'alone.txt').read_text()
        assert 'BILL-DATE-001' in (tmp_path / 'bill.txt').read_text()

    def test_a_rates_file_prices_its_own_line_and_no_other(self, tmp_path):
        book = _a_book_holding_usd_and_eur(tmp_path)
        rates = tmp_path / 'rates.yaml'
        rates.write_text('USD/CAD:\n  2021-12-31: 2.00\nEUR/CAD:\n  2021-12-31: 3.00\n')

        done = _batch(
            tmp_path, book,
            'balance-sheet --as-of 2021-12-31', f'{tmp_path}/before.txt',
            f'balance-sheet --as-of 2021-12-31 --fx-rates {rates}', f'{tmp_path}/at-the-rates.txt',
            'balance-sheet --as-of 2021-12-31', f'{tmp_path}/after.txt')

        assert done.exit_code == 0, done.output
        assert _total_assets((tmp_path / 'before.txt').read_text()) == ['total_assets: 4050.20 CAD']
        assert _total_assets((tmp_path / 'at-the-rates.txt').read_text()) == [
            'total_assets: 7000.00 CAD']
        assert _total_assets((tmp_path / 'after.txt').read_text()) == ['total_assets: 4050.20 CAD']


class TestACommandThatDoesNotExit0:

    def test_the_commands_after_it_still_run_and_the_batch_exits_1(self, tmp_path):
        book = book_from(tmp_path, OVERSTATED)

        done = _batch(
            tmp_path, book,
            'verify-integrity', f'{tmp_path}/integrity.txt',
            'balance-sheet --as-of 2021-12-31 --currency XYZ', f'{tmp_path}/in-xyz.txt',
            'fx-balances', f'{tmp_path}/fx-balances.txt')

        assert done.exit_code == 1, done.output
        lines = done.output.splitlines()
        assert lines[0] == f'failed  verify-integrity, it exited 1 -> {tmp_path}/integrity.txt'
        assert lines[1] == (f'failed  balance-sheet --as-of 2021-12-31 --currency XYZ, '
                            f'it exited 1 -> {tmp_path}/in-xyz.txt'), lines[1]
        assert lines[2] == f'ok      fx-balances -> {tmp_path}/fx-balances.txt'
        assert lines[3] == '3 commands: 1 succeeded, 2 failed'

    def test_each_writes_what_it_prints_alone(self, tmp_path):
        book = book_from(tmp_path, OVERSTATED)
        checked = _run(CliRunner(), 'verify-integrity', str(book))
        refused = _run(CliRunner(), 'balance-sheet', str(book), '--as-of', '2021-12-31',
                       '--currency', 'XYZ')

        _batch(tmp_path, book,
               'verify-integrity', f'{tmp_path}/integrity.txt',
               'balance-sheet --as-of 2021-12-31 --currency XYZ', f'{tmp_path}/in-xyz.txt')

        assert checked.exit_code == 1, checked.output
        assert (tmp_path / 'integrity.txt').read_text() == checked.output
        assert refused.exit_code == 1, refused.output
        assert (tmp_path / 'in-xyz.txt').read_text() == refused.output

    def test_a_refusal_with_its_usage_writes_what_it_prints_alone(self, tmp_path):
        book = book_from(tmp_path, OVERSTATED)
        refused = _run(CliRunner(), 'find-transactions', str(book))

        done = _batch(tmp_path, book, 'find-transactions', f'{tmp_path}/found.txt')

        assert done.exit_code == 1, done.output
        assert refused.exit_code == 2, refused.output
        assert refused.output.startswith('Usage: '), refused.output
        assert (tmp_path / 'found.txt').read_text() == refused.output

    def test_a_page_gnucash_cannot_draw_writes_the_refusal_and_the_batch_goes_on(self, tmp_path):
        book = book_from(tmp_path, 'a_book_with_a_date_format.txt', '--include-business-objects')
        broken = str(FIXTURES / 'a_report_that_will_not_parse.scm')
        drawn = ['print-bill', 'BILL-DATE-001', '--format', 'html', '--report-file', broken,
                 '--report', 'A Report That Will Not Parse']
        refused = _run(CliRunner(), drawn[0], str(book), *drawn[1:],
                       '--output', str(tmp_path / 'alone.html'))

        done = _batch(tmp_path, book,
                      ' '.join(f"'{word}'" for word in drawn), f'{tmp_path}/bill.html',
                      'fx-balances', f'{tmp_path}/fx-balances.txt')

        assert refused.exit_code == 1, refused.output
        assert 'could not be loaded' in refused.output, refused.output
        assert done.exit_code == 1, done.output
        lines = done.output.splitlines()
        assert lines[0].startswith('failed  print-bill ') and lines[0].endswith(
            f', it exited 1 -> {tmp_path}/bill.html'), lines[0]
        assert lines[1] == f'ok      fx-balances -> {tmp_path}/fx-balances.txt'
        assert lines[2] == '2 commands: 1 succeeded, 1 failed'
        assert (tmp_path / 'bill.html').read_text() == refused.output

    def test_what_a_command_prints_to_stderr_is_in_its_file(self, tmp_path):
        book = book_from(tmp_path, OVERSTATED)
        found = _run(CliRunner(), 'find-transactions', str(book), '--amount', '123456.78')

        done = _batch(tmp_path, book,
                      'find-transactions --amount 123456.78', f'{tmp_path}/found.txt')

        assert found.exit_code == 0, found.output
        assert 'No matching transactions found.' in found.output, found.output
        assert done.exit_code == 0, done.output
        assert 'No matching' not in done.output, done.output
        assert (tmp_path / 'found.txt').read_text() == found.output

    def test_a_printed_page_refused_for_a_directory_says_why_on_the_console(self, tmp_path):
        book = book_from(tmp_path, OVERSTATED)

        done = _batch(tmp_path, book,
                      'print-invoice NO-SUCH-INVOICE --format plaintext', f'{tmp_path}/pages/',
                      'fx-balances', f'{tmp_path}/fx-balances.txt')

        assert done.exit_code == 1, done.output
        lines = done.output.splitlines()
        assert lines[0].startswith(
            f'failed  print-invoice NO-SUCH-INVOICE --format plaintext, it exited 2 -> '
            f'{tmp_path}/pages/: no invoices matched the selection'), lines[0]
        assert lines[1] == f'ok      fx-balances -> {tmp_path}/fx-balances.txt'
        assert not (tmp_path / 'pages').exists()


class TestABatchFileRefusedBeforeTheBookIsOpened:

    def test_every_line_that_cannot_run_is_listed(self, tmp_path):
        book = book_from(tmp_path, OVERSTATED)
        rates = tmp_path / 'rates.yaml'
        rates.write_text('USD/CAD:\n  2021-12-31: 2.00\n')

        done = _batch(
            tmp_path, book,
            'import ledger.txt', f'{tmp_path}/a.txt',
            'balance-sheet --as-of 2021-12-31 --no-such-option', f'{tmp_path}/b.txt',
            f'export {tmp_path}/elsewhere.txt', f'{tmp_path}/c.txt',
            f'account-balance --fx-rates {rates}', f'{tmp_path}/d.txt',
            'fx-balances', f'{tmp_path}/e.txt',
            'find-prepayments', f'{tmp_path}/e.txt',
            f'export-accounts {tmp_path}/elsewhere.txt', f'{tmp_path}/f.txt',
            f'print-invoice INV-1 --format plaintext -o {tmp_path}/elsewhere.txt',
            f'{tmp_path}/g.txt',
            f'validate --report {tmp_path}/elsewhere.txt', f'{tmp_path}/h.txt',
            'fx-balances', f'{tmp_path}/missing/i.txt',
            'verify-integrity', f'{tmp_path}/pages/',
            'find-orphan-payments', str(tmp_path))

        assert done.exit_code == 2, done.output
        assert f'{tmp_path}/batch.txt: the book was not opened, because:' in done.output
        assert ('line 1, import ledger.txt: "import" is not a command a batch runs. A batch only '
                'reads the book, and runs account-balance, balance-sheet, export, '
                'export-accounts, export-beancount, export-prices, export-transaction, '
                'find-orphan-payments, find-prepayments, find-transactions, fx-balances, '
                'income-statement, print-bill, print-invoice, report, validate, '
                'verify-integrity.') in done.output
        for number, text in ((13, f'export-accounts {tmp_path}/elsewhere.txt'),
                             (15, f'print-invoice INV-1 --format plaintext -o '
                                  f'{tmp_path}/elsewhere.txt'),
                             (17, f'validate --report {tmp_path}/elsewhere.txt')):
            assert (f'line {number}, {text}: it states a book or an output file of its '
                    f'own.') in done.output
        # Click's own sentence, which is worded differently from one version to the next.
        refused = [line for line in done.output.splitlines()
                   if line.startswith('  line 3, balance-sheet --as-of 2021-12-31 --no-such-option: ')]
        assert len(refused) == 1 and refused[0].count('--no-such-option') == 2, done.output
        assert (f'line 5, export {tmp_path}/elsewhere.txt: it states a book or an output file '
                f'of its own.') in done.output
        assert (f'line 7, account-balance --fx-rates {rates}: account-balance --fx-rates saves '
                f'the rates to the book, and a batch only reads the book.') in done.output
        assert (f'line 11, find-prepayments: {tmp_path}/e.txt is the output of line 9 '
                f'as well.') in done.output
        assert 'line 9,' not in done.output
        assert (f'line 19, fx-balances: {tmp_path}/missing/i.txt is in {tmp_path}/missing, which '
                f'does not exist.') in done.output
        assert (f'line 21, verify-integrity: {tmp_path}/pages/ is a directory, and '
                f'verify-integrity writes one file.') in done.output
        assert (f'line 23, find-orphan-payments: {tmp_path} is a directory, and '
                f'find-orphan-payments writes one file.') in done.output
        assert not (tmp_path / 'missing').exists() and not (tmp_path / 'pages').exists()
        assert not [path.name for path in tmp_path.iterdir() if path.name[0] in 'abcdefgh'
                    and path.suffix == '.txt' and path.name != 'batch.txt']

    def test_a_command_with_no_line_after_it(self, tmp_path):
        book = book_from(tmp_path, OVERSTATED)

        done = _batch(tmp_path, book, 'fx-balances', f'{tmp_path}/a.txt', '# the last one',
                      'find-prepayments')

        assert done.exit_code == 2, done.output
        assert (f'{tmp_path}/batch.txt: line 4, "find-prepayments", has no line after it for the '
                f'path its output is written to.') in done.output

    def test_a_quote_left_open(self, tmp_path):
        book = book_from(tmp_path, OVERSTATED)

        done = _batch(tmp_path, book, 'find-transactions --account "Assets', f'{tmp_path}/a.txt')

        assert done.exit_code == 2, done.output
        assert f'{tmp_path}/batch.txt: line 1: No closing quotation' in done.output

    def test_a_file_listing_no_command(self, tmp_path):
        book = book_from(tmp_path, OVERSTATED)

        done = _batch(tmp_path, book, '# nothing yet')

        assert done.exit_code == 2, done.output
        assert f'{tmp_path}/batch.txt lists no command.' in done.output
