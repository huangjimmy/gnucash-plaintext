"""
CLI command for exporting GnuCash transactions to plaintext.
"""

import os

import click

from repositories.gnucash_repository import GnuCashRepository, SessionMode
from use_cases.export_business_objects import ExportBusinessObjectsUseCase
from use_cases.export_transactions import (
    ExportTransactionsUseCase,
    UnwritableFigureError,
)


@click.command()
@click.argument('gnucash_file', required=False, type=click.Path())
@click.argument('output_file', required=False, type=click.Path())
@click.option('-i', '--input', 'input_file', type=click.Path(), help='Input GnuCash XML file')
@click.option('-o', '--output', 'output_path', type=click.Path(), help='Output plaintext file')
@click.option('--start-date', '-s', help='Start date (YYYY-MM-DD)')
@click.option('--end-date', '-e', help='End date (YYYY-MM-DD)')
@click.option('--account', '-a', help='Filter by account path')
@click.option('--all-accounts', 'all_accounts', is_flag=True, help='Export all accounts even if they have no transactions (implied by --include-business-objects)')
@click.option('--include-business-objects', is_flag=True, help='Include business objects (customers, invoices, etc.)')
@click.option('--with-balance', 'with_balance', is_flag=True,
              help='Append running account balance after each split (useful for bank reconciliation)')
def export_transactions(gnucash_file, output_file, input_file, output_path, start_date, end_date, account, all_accounts, include_business_objects, with_balance):
    """
    Export transactions from GnuCash file to plaintext format.

    Supports both positional and flag-based arguments:

    \b
    Positional style:
        gnucash-plaintext export mybook.gnucash transactions.txt

    \b
    Flag style:
        gnucash-plaintext export -i mybook.gnucash -o transactions.txt

    Examples:

        gnucash-plaintext export mybook.gnucash transactions.txt

        gnucash-plaintext export -i mybook.gnucash -o transactions.txt

        gnucash-plaintext export mybook.gnucash transactions.txt --start-date 2024-01-01

        gnucash-plaintext export -i mybook.gnucash -o transactions.txt --account "Expenses:Groceries"

        gnucash-plaintext export mybook.gnucash transactions.txt --with-balance
    """
    # Support both positional and flag-based arguments
    gnucash_file = input_file or gnucash_file
    output_file = output_path or output_file

    if not gnucash_file:
        raise click.UsageError("Missing input file. Use positional argument or -i/--input flag.")
    if not output_file:
        raise click.UsageError("Missing output file. Use positional argument or -o/--output flag.")

    # Validate file existence
    if not os.path.exists(gnucash_file):
        raise click.UsageError(f"Input file does not exist: {gnucash_file}")
    try:
        # Open repository
        repo = GnuCashRepository(gnucash_file)
        repo.open(mode=SessionMode.READ_ONLY)

        try:
            business_objects_output = ""
            # Held rather than raised, so the transactions section is still
            # formatted and its own offenders gathered. Each half names every
            # one of its own, but the documents were written first and refused
            # before the other list existed — so a book with an unwritable
            # payment amount and an unwritable split named only the payment,
            # and the reader who corrected it met the split on the next run.
            # Two runs to learn two figures, out of a guard whose purpose is
            # that a book is not fixed one run at a time.
            documents_refusal = None
            if include_business_objects:
                click.echo("Exporting business objects...")
                business_use_case = ExportBusinessObjectsUseCase(repo.book)
                try:
                    business_objects_output = business_use_case.execute()
                except UnwritableFigureError as exc:
                    documents_refusal = exc

            # Create use case
            use_case = ExportTransactionsUseCase(repo)

            # Export. Business objects reach accounts no split touches — an
            # entry's income/expense account, a posted: block's A/R account, a
            # tax-table entry's tax account — so an export that carries them
            # emits the full chart of accounts. Collecting accounts from
            # transaction splits alone left a book of unposted invoices with
            # zero `open` directives and no way to re-import it.
            click.echo(f"Exporting transactions from {gnucash_file}...")
            result = use_case.execute(
                start_date=start_date,
                end_date=end_date,
                account_filter=account,
                all_accounts=all_accounts or include_business_objects,
                with_balance=with_balance,
            )
            count = len(result.transactions)

            # Rendered in full before the file is opened. Formatting can
            # refuse — a split holding a figure finer than its currency cannot
            # be written as plaintext — and opening first meant the target was
            # already truncated when it did: exporting over yesterday's ledger
            # destroyed it and wrote nothing in its place. Measured: a 0-byte
            # file where a good export had been.
            transactions_refusal = None
            try:
                if include_business_objects:
                    # Import-ready order: accounts, then business objects, then
                    # transactions.
                    text = (use_case.format_accounts_section(result)
                            + "\n"
                            + business_objects_output
                            + "\n\n"
                            + use_case.format_transactions_section(result))
                else:
                    text = use_case.format_as_plaintext(result)
            except UnwritableFigureError as exc:
                transactions_refusal = exc

            if documents_refusal is not None or transactions_refusal is not None:
                # Both, where both found something: one pass over the book
                # tells the reader everything there is to correct in it.
                raise UnwritableFigureError('\n'.join(
                    str(refusal) for refusal
                    in (documents_refusal, transactions_refusal)
                    if refusal is not None))

            # UTF-8 stated rather than taken from the locale. Without it,
            # `open(..., "w")` truncates and then `write` raises on the first
            # character the locale cannot hold — the half-written destination
            # the whole build-then-write block above exists to prevent, and a
            # customer named `Éditions Cliché` is enough to reach it.
            with open(output_file, "w", encoding="utf-8") as f:
                f.write(text)

            click.echo(f"✓ Exported {count} transaction(s) to {output_file}")

        finally:
            repo.close()

    except Exception as e:
        raise click.ClickException(str(e)) from e
