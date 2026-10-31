"""A batch reads the books the other scenarios build, and says what each of those scenarios says (Q-058).

A user of this tool builds one page from several read commands on their book:
two balance sheets, the income statement, an export and a check of the book,
each a process of its own that opens the book. They asked for one run that
opens the book once and writes each command's output to a file. The author
stated the batch file: "every two lines are 1 command first and then the path
of output, console output is a summary of batch result, with each command
result in output file". And the author asked that the batch's scenario be the
cases the other scenarios already hold, not a new one.

So each case here is a book another scenario builds, with that scenario's own
builder and fixtures, read by one `gnucash-plaintext batch` running the read
commands that scenario runs on it:

- ACMU LLC after five years of cost bases and the migration
  (`test_acmu_migrates_from_cost_bases_after_five_years.py`): the balance
  sheet in CAD at each year end and the income statement in CAD of each fiscal
  year, which state the figures that scenario states, then `fx-balances` and
  `verify-integrity`;
- ACME after it sells its EUR
  (`test_acme_keeps_a_balance_in_usd_cad_cny_hkd_eur_and_gbp_on_every_account.py`):
  the balance sheet in USD on each date that scenario reads it, the income
  statement of the fiscal year, `fx-balances` and `verify-integrity`;
- the Hong Kong company after its six steps
  (`test_a_hong_kong_company_measures_its_usd_cny_and_eur_in_hkd.py`) and the
  US company after its four (`test_a_us_company_measures_its_cad_in_usd.py`):
  `fx-balances`, `fx-balances --verify-costs`, `verify-integrity`, the export
  and the year-end balance sheet.

Every file holds what the command prints, or writes, when it runs alone.
"""

import re

from click.testing import CliRunner

from tests.conftest import _run
from tests.scenario import test_a_hong_kong_company_measures_its_usd_cny_and_eur_in_hkd as hong_kong
from tests.scenario import test_a_us_company_measures_its_cad_in_usd as us_company
from tests.scenario import (
    test_acme_keeps_a_balance_in_usd_cad_cny_hkd_eur_and_gbp_on_every_account as acme,
)
from tests.scenario import test_acmu_migrates_from_cost_bases_after_five_years as acmu

# The commands that write a file of their own, handed the path after the book
# when they run alone.
_WRITES_A_FILE = ('export',)


def _batch(tmp_path, book, commands):
    """`gnucash-plaintext batch` over `commands`: its result, and each command's file."""
    out = tmp_path / 'batch-out'
    out.mkdir()
    files = [out / f'{number}.txt' for number in range(len(commands))]
    listing = tmp_path / 'batch.txt'
    listing.write_text(''.join(f'{command}\n{file}\n' for command, file in zip(commands, files)))
    return _run(CliRunner(), 'batch', str(book), str(listing)), files


def _alone(tmp_path, book, command):
    """What `command` prints, or writes, when it runs alone on `book`."""
    name, *rest = command.split()
    if name in _WRITES_A_FILE:
        written = tmp_path / 'alone.txt'
        done = _run(CliRunner(), name, str(book), str(written), *rest)
        assert done.exit_code == 0, done.output
        return written.read_text()
    done = _run(CliRunner(), name, str(book), *rest)
    assert done.exit_code == 0, done.output
    return done.output


def _every_file_is_what_the_command_writes_alone(tmp_path, book, commands):
    done, files = _batch(tmp_path, book, commands)
    assert done.exit_code == 0, done.output
    assert done.output.splitlines()[-1] == (
        f'{len(commands)} commands: {len(commands)} succeeded, 0 failed'), done.output
    for command, file in zip(commands, files):
        assert file.read_text() == _alone(tmp_path, book, command), command
    return [file.read_text() for file in files]


def test_acmu_s_statements_state_the_figures_its_scenario_states(tmp_path):
    book, _ = acmu._book(tmp_path, acmu.MIGRATED)
    sheets = [f'balance-sheet --as-of {as_of} --currency CAD' for as_of, *_ in acmu.THE_SHEET_IN_CAD]
    statements = [f'income-statement --currency CAD --fiscal-year-end {fiscal_year_end}'
                  for fiscal_year_end, _ in acmu.THE_INCOME_STATEMENT_IN_CAD]
    checks = ['fx-balances', 'verify-integrity']

    pages = _every_file_is_what_the_command_writes_alone(tmp_path, book, sheets + statements + checks)

    for page, (_, assets, retained, realized, unrealized) in zip(pages, acmu.THE_SHEET_IN_CAD):
        keys = dict(re.findall(r'^\t([a-z_]+): (-?[\d.]+) CAD', page, re.M))
        assert (keys['total_assets'], keys['total_liabilities_and_equity'], keys['retained_earnings'],
                keys['total_realized_gains'], keys['total_unrealized_gains']) == (
            assets, assets, retained, realized, unrealized)
    for page, (_, lines) in zip(pages[len(sheets):], acmu.THE_INCOME_STATEMENT_IN_CAD):
        stated = dict(re.findall(r'^\t((?:Income|Expenses):\S+(?: \S+)*?) (-?[\d.]+) CAD$', page, re.M))
        stated['net_income'] = re.search(r'^\tnet_income: (-?[\d.]+) CAD', page, re.M).group(1)
        assert stated == lines


def test_acme_s_statements_and_balances_are_what_each_command_writes_alone(tmp_path):
    book = acme._book(tmp_path, acme.OPENS, acme.INVOICES, acme.SELLS_EUR)
    commands = [f'balance-sheet --as-of {as_of} --currency USD'
                for as_of in ('2020-12-31', '2021-01-01', '2021-03-02', '2021-03-03', '2021-05-31',
                              '2021-06-01')]
    commands += ['income-statement --currency USD --fiscal-year-end 2021-06-30',
                 'fx-balances', 'verify-integrity']

    _every_file_is_what_the_command_writes_alone(tmp_path, book, commands)


def test_the_hong_kong_company_s_book_is_what_each_command_writes_alone(tmp_path):
    book = hong_kong._book(tmp_path, len(hong_kong.STEPS))
    commands = ['fx-balances', 'fx-balances --verify-costs', 'verify-integrity', 'export',
                'balance-sheet --as-of 2026-12-31']

    _every_file_is_what_the_command_writes_alone(tmp_path, book, commands)


def test_the_us_company_s_book_is_what_each_command_writes_alone(tmp_path):
    book = us_company._book(tmp_path, len(us_company.STEPS))
    commands = ['fx-balances', 'fx-balances --verify-costs', 'verify-integrity', 'export',
                'balance-sheet --as-of 2026-12-31']

    _every_file_is_what_the_command_writes_alone(tmp_path, book, commands)
