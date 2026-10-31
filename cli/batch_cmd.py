"""CLI command: run a batch of read commands against one book opened once (Q-058).

`batch <book> <batch-file>`

The batch file lists commands in pairs of lines: a command as it is typed
without the book, then the path its output is written to.

    # the T2 page
    balance-sheet --as-of 2025-12-31
    out/balance-sheet-2025.txt
    export --start-date 2025-01-01
    out/ledger-2025.txt

Every command reads the one session `one_open_book_for_reading` holds, so the
book is opened once, and one process starts. What that saves on each build is
measured in Q-058.

Nothing in a batch writes to the book, and the book is never saved. That is
what tells it from `migrate`, which runs commands that write and saves once.
"""

import contextlib
import io
import os
import shlex
import sys
from pathlib import Path

import click

from cli._refusals import REFUSED_IN_A_SENTENCE
from cli.account_balance_cmd import account_balance
from cli.balance_sheet_cmd import balance_sheet
from cli.bill_print_cmd import print_bill
from cli.cost_basis_cmd import fx_balances
from cli.export_accounts_cmd import export_accounts
from cli.export_beancount_cmd import export_beancount
from cli.export_cmd import export_transactions
from cli.export_prices_cmd import export_prices
from cli.export_transaction_cmd import export_transaction
from cli.find_orphan_payments_cmd import find_orphan_payments
from cli.find_prepayments_cmd import find_prepayments
from cli.find_transactions_cmd import find_transactions
from cli.income_statement_cmd import income_statement
from cli.invoice_print_cmd import print_invoice
from cli.report_cmd import report
from cli.validate_cmd import validate_ledger
from cli.verify_integrity_cmd import verify_integrity
from repositories.gnucash_repository import one_open_book_for_reading

# The commands a batch runs: every command that only reads the book. Each is
# listed with how it is handed the path its output is written to, and the
# parameters through which a line would state a book or an output file of its
# own, which the batch states itself. A command that writes a file of its own
# is handed the path the way it takes one, so a page laid out as HTML or PDF is
# written as it is alone; every other command's printed output is written to
# the path.
_FILE_GIVEN_AFTER_THE_BOOK = 'after the book'
_FILE_GIVEN_AS_OUTPUT = '--output'
_PRINTED = 'printed'
_READERS = {
    'export': (export_transactions, _FILE_GIVEN_AFTER_THE_BOOK,
               ('output_file', 'output_path', 'input_file')),
    'export-accounts': (export_accounts, _FILE_GIVEN_AFTER_THE_BOOK, ('output_file',)),
    'export-prices': (export_prices, _FILE_GIVEN_AFTER_THE_BOOK, ('output_file',)),
    'export-beancount': (export_beancount, _FILE_GIVEN_AFTER_THE_BOOK,
                         ('output_file', 'output_path', 'input_file')),
    'export-transaction': (export_transaction, _FILE_GIVEN_AS_OUTPUT,
                           ('output_path', 'input_file')),
    'balance-sheet': (balance_sheet, _FILE_GIVEN_AS_OUTPUT, ('output_file',)),
    'income-statement': (income_statement, _FILE_GIVEN_AS_OUTPUT, ('output_file',)),
    'report': (report, _FILE_GIVEN_AS_OUTPUT, ('output_file',)),
    'print-invoice': (print_invoice, _FILE_GIVEN_AS_OUTPUT, ('output',)),
    'print-bill': (print_bill, _FILE_GIVEN_AS_OUTPUT, ('output',)),
    'fx-balances': (fx_balances, _PRINTED, ()),
    'account-balance': (account_balance, _PRINTED, ()),
    'verify-integrity': (verify_integrity, _PRINTED, ()),
    'validate': (validate_ledger, _PRINTED, ('input_file', 'report')),
    'find-transactions': (find_transactions, _PRINTED, ()),
    'find-prepayments': (find_prepayments, _PRINTED, ()),
    'find-orphan-payments': (find_orphan_payments, _PRINTED, ()),
}

# What a command adds to the book for its own run, by the parameter that asks
# for it. `--fx-rates` and `--prices` add prices to the open book (finding 28),
# and GnuCash keeps one price a day for a pair, so an added price can displace
# one the book holds. Taking ours off would not bring that one back, so the
# book is read from disk again for the commands after.
_ADDS_PRICES = ('fx_rates_file', 'prices_file')

# The commands handed a path ending in `/` write a file for each invoice or
# bill into that directory, as they do alone, and make it.
_TAKE_A_DIRECTORY = ('print-invoice', 'print-bill')


class _Line:
    """One command of the batch, parsed before the book is opened."""

    def __init__(self, number, words, output):
        self.number = number
        self.text = ' '.join(shlex.quote(word) for word in words)
        self.name = words[0]
        self.rest = words[1:]
        self.output = output
        # The command's own parameters, as Click parsed them before the book
        # was opened.
        self.params = {}


def _read_the_batch(batch_file):
    """The commands the file lists, each with the line it starts on, or a UsageError."""
    lines = []
    for number, text in enumerate(Path(batch_file).read_text(encoding='utf-8').splitlines(), 1):
        stripped = text.strip()
        if stripped and not stripped.startswith('#'):
            lines.append((number, stripped))
    if len(lines) % 2:
        number, text = lines[-1]
        raise click.UsageError(
            f'{batch_file}: line {number}, "{text}", has no line after it for the path its '
            f'output is written to. A batch file lists a command, then the path its output '
            f'is written to, for each command.')
    parsed = []
    for (number, command), (_, output) in zip(lines[::2], lines[1::2]):
        try:
            words = shlex.split(command)
        except ValueError as reason:
            raise click.UsageError(f'{batch_file}: line {number}: {reason}') from None
        parsed.append(_Line(number, words, output))
    return parsed


def _the_arguments(line, book):
    """What the command is invoked with: the book, the line's own words, and where to write."""
    _, given, _ = _READERS[line.name]
    if given == _FILE_GIVEN_AFTER_THE_BOOK:
        return [book, line.output] + line.rest
    if given == _FILE_GIVEN_AS_OUTPUT:
        return [book] + line.rest + ['--output', line.output]
    return [book] + line.rest


def _why_the_line_is_refused(line, book, outputs):
    """The sentence refusing one line before the book is opened, or None."""
    if line.name not in _READERS:
        return (f'"{line.name}" is not a command a batch runs. A batch only reads the book, '
                f'and runs {", ".join(sorted(_READERS))}.')
    command, _, its_own_files = _READERS[line.name]
    # Read first as the line is written, with nothing the batch adds, because
    # a path the batch hands as `--output` would hide one the line states, and
    # the command's own file is refused here rather than by Click's sentence
    # about an extra argument. Parsed resiliently, Click refuses nothing here:
    # an option the command does not take is refused by the parse below.
    stated = command.make_context(line.name, [book] + line.rest, resilient_parsing=True).params
    if any(stated.get(name) is not None for name in its_own_files):
        return ('it states a book or an output file of its own. A batch reads the book it is '
                'given, and writes each command\'s output to the path on the line after it. '
                'Leave the file out of the command.')
    try:
        parsed = command.make_context(line.name, _the_arguments(line, book),
                                      resilient_parsing=False)
    except click.ClickException as refusal:
        return refusal.format_message()
    line.params = parsed.params
    if line.name == 'account-balance' and parsed.params.get('fx_rates_file') is not None:
        return ('account-balance --fx-rates saves the rates to the book, and a batch only '
                'reads the book. Run it on its own.')
    if line.output.endswith('/') or os.path.isdir(line.output):
        if not (line.output.endswith('/') and line.name in _TAKE_A_DIRECTORY):
            return f'{line.output} is a directory, and {line.name} writes one file.'
    elif not os.path.isdir(os.path.dirname(line.output) or '.'):
        return f'{line.output} is in {os.path.dirname(line.output)}, which does not exist.'
    where = os.path.realpath(line.output)
    if where in outputs:
        return f'{line.output} is the output of line {outputs[where]} as well.'
    outputs[where] = line.number
    return None


def _run(line, book):
    """Run one command on the open book: its exit code, and what the console says of it.

    Every command's result is written to its path, whatever it is, because
    nothing a batch runs changes the book: what it printed, as
    `verify-integrity` prints the list of what is wrong and exits 1, and
    for a command refused, the refusal it prints alone. A directory holds no
    one file to write a refusal to, so a printed page refused for a directory
    says why on the console.
    """
    command, given, _ = _READERS[line.name]
    # A stream with bytes beneath it, written straight through, because
    # `validate` writes its report to `sys.stdout.buffer` and `click.echo` to
    # the text stream, and the file must hold both in the order they came.
    printed = io.TextIOWrapper(io.BytesIO(), encoding='utf-8', write_through=True)
    code = 0
    refusal = None
    # Under the name it has alone, which a usage error prints.
    alone = f'{click.get_current_context().find_root().command_path} {line.name}'
    try:
        # What it prints to stderr as well, as a command alone prints both
        # to the console: a search that finds nothing says so there.
        with contextlib.redirect_stdout(printed), contextlib.redirect_stderr(printed):
            command.main(args=_the_arguments(line, book), prog_name=alone,
                         standalone_mode=False)
    except SystemExit as leaving:
        code = leaving.code or 0
    except click.ClickException as raised:
        refusal = raised
    except REFUSED_IN_A_SENTENCE as raised:
        # What the group makes of it for a command alone (`cli/main.py`).
        refusal = click.ClickException(str(raised))
    why = ''
    if refusal is not None:
        # What Click prints for it alone: a usage error's usage lines too.
        refusal.show(file=printed)
        code = refusal.exit_code
        if line.output.endswith('/'):
            why = f': {refusal.format_message()}'
        else:
            given = _PRINTED
    if given == _PRINTED:
        Path(line.output).write_bytes(printed.buffer.getvalue())
    if code:
        return code, f'failed  {line.text}, it exited {code} -> {line.output}{why}'
    return 0, f'ok      {line.text} -> {line.output}'


@click.command('batch')
@click.argument('gnucash_file', type=click.Path(exists=True, dir_okay=False))
@click.argument('batch_file', type=click.Path(exists=True, dir_okay=False))
def batch(gnucash_file, batch_file):
    """Run read commands against one book opened once, each writing its output to a file.

    The batch file lists, for each command, the command as typed without the
    book, then on the next line the path its output is written to. Blank lines
    and lines starting with # are skipped. Every command reads; none writes to
    the book, and the book is never saved.

    \b
        balance-sheet --as-of 2025-12-31
        out/balance-sheet-2025.txt
        export
        out/ledger.txt
    """
    lines = _read_the_batch(batch_file)
    if not lines:
        raise click.UsageError(f'{batch_file} lists no command.')
    outputs = {}
    refused = [(line, _why_the_line_is_refused(line, gnucash_file, outputs)) for line in lines]
    refused = [(line, why) for line, why in refused if why is not None]
    if refused:
        raise click.UsageError('\n'.join(
            [f'{batch_file}: the book was not opened, because:']
            + [f'  line {line.number}, {line.text}: {why}' for line, why in refused]))

    failed = 0
    with one_open_book_for_reading(gnucash_file) as book:
        for line in lines:
            code, said = _run(line, gnucash_file)
            if any(line.params.get(name) is not None for name in _ADDS_PRICES):
                book.reopen()
            if code:
                failed += 1
            click.echo(said)
    click.echo(f'{len(lines)} commands: {len(lines) - failed} succeeded, {failed} failed')
    if failed:
        sys.exit(1)
