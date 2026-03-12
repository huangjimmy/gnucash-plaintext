"""
CLI command for validating GnuCash ledger.
"""

import os

import click

from repositories.gnucash_repository import GnuCashRepository, SessionMode
from use_cases.validate_ledger import ValidateLedgerUseCase


@click.command()
@click.argument('gnucash_file', required=False, type=click.Path())
@click.option('-i', '--input', 'input_file', type=click.Path(), help='Input GnuCash XML file')
@click.option('--report', '-r', type=click.Path(), help='Save report to file')
@click.option('--quick', '-q', is_flag=True, help='Quick check (errors only)')
@click.option('--stats', '-s', is_flag=True, help='Show statistics')
def validate_ledger(gnucash_file, input_file, report, quick, stats):
    """
    Validate GnuCash ledger integrity.

    Supports both positional and flag-based arguments:

    \b
    Positional style:
        gnucash-plaintext validate mybook.gnucash

    \b
    Flag style:
        gnucash-plaintext validate -i mybook.gnucash

    Examples:

        gnucash-plaintext validate mybook.gnucash

        gnucash-plaintext validate -i mybook.gnucash --quick

        gnucash-plaintext validate mybook.gnucash --report validation.txt

        gnucash-plaintext validate -i mybook.gnucash --stats
    """
    # Support both positional and flag-based arguments
    gnucash_file = input_file or gnucash_file

    if not gnucash_file:
        raise click.UsageError("Missing GnuCash file. Use positional argument or -i/--input flag.")

    # Validate file existence
    if not os.path.exists(gnucash_file):
        raise click.UsageError(f"GnuCash file does not exist: {gnucash_file}")
    try:
        # Open repository
        repo = GnuCashRepository(gnucash_file)
        repo.open(mode=SessionMode.READ_ONLY)

        try:
            # Create use case
            use_case = ValidateLedgerUseCase(repo)

            if quick:
                # Quick validation
                click.echo(f"Running quick validation on {gnucash_file}...")
                is_valid = use_case.quick_check()

                if is_valid:
                    click.echo("✓ Ledger is valid (no errors)")
                else:
                    click.echo("✗ Ledger has errors", err=True)
                    raise click.Abort()

            elif stats:
                # Show statistics
                click.echo(f"Analyzing {gnucash_file}...")
                ledger_stats = use_case.get_statistics()

                click.echo("")
                click.echo("Ledger Statistics:")
                click.echo("=" * 50)
                click.echo(f"  File:         {ledger_stats['file_path']}")
                click.echo(f"  Accounts:     {ledger_stats['total_accounts']}")
                click.echo(f"  Transactions: {ledger_stats['total_transactions']}")

                click.echo("")
                click.echo("Accounts by Category:")
                for category, count in ledger_stats['accounts_by_category'].items():
                    if count > 0:
                        click.echo(f"  {category:<12} {count}")

                validation = ledger_stats['validation']
                click.echo("")
                click.echo("Validation Status:")
                if validation['is_valid']:
                    click.echo("  ✓ Valid (no errors)")
                else:
                    click.echo(f"  ✗ {validation['error_count']} error(s)")

                if validation['warning_count'] > 0:
                    click.echo(f"  ⚠ {validation['warning_count']} warning(s)")

            else:
                # Full validation with report
                click.echo(f"Validating {gnucash_file}...")
                result = use_case.validate_and_report(output_path=report)

                click.echo("")
                click.echo(result.get_summary())

                if result.is_valid():
                    if result.has_warnings():
                        click.echo("⚠ Ledger is valid but has warnings")
                    else:
                        click.echo("✓ Ledger is valid")
                else:
                    click.echo("✗ Ledger has errors", err=True)

                if report:
                    click.echo(f"✓ Report saved to {report}")

                if not result.is_valid():
                    raise click.Abort()

        finally:
            repo.close()

    except Exception as e:
        click.echo(f"✗ Error: {str(e)}", err=True)
        raise click.Abort() from e
