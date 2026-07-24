"""
CLI command for importing plaintext transactions to GnuCash.
"""

import os

import click

from repositories.gnucash_repository import GnuCashRepository, SessionMode
from services.conflict_resolver import ResolutionStrategy
from services.gnucash_importer import GnuCashImporter
from services.plaintext_parser import DirectiveType, PlaintextParser
from use_cases.export_transactions import ExportTransactionsUseCase
from use_cases.import_transactions import ImportTransactionsUseCase
from use_cases.unpost_business_objects import format_orphan_warning_block


def _warn_open_prepayment_mismatches(directives, book):
    """Recompute open prepayment credits from the book and warn (never fail)
    when a declared `open_prepayment:` block disagrees with reality.

    The summary is informational and derived, so the book's lots are
    authoritative; a mismatch means the file is stale (e.g. hand-edited), and
    the next export rewrites the correct value. We only check accounts whose
    directive actually declares `open_prepayment:` blocks — a file that omits
    the summary is not nagged.
    """
    declared = {}   # (account, kind, owner_id) -> declared total
    for d in directives:
        if d.type != DirectiveType.OPEN_ACCOUNT:
            continue
        account = d.props.get('account')
        if not account:
            continue
        for child in d.children:
            if child.type != DirectiveType.OPEN_PREPAYMENT:
                continue
            md = child.metadata
            kind = ('customer' if md.get('customer')
                    else 'vendor' if md.get('vendor') else None)
            if not kind:
                continue
            try:
                amount = float(str(md.get('amount', '0')).split()[0])
            except (ValueError, IndexError):
                continue
            key = (account, kind, md.get(kind))
            declared[key] = declared.get(key, 0.0) + amount

    if not declared:
        return

    # Compute the actual open credits with the SAME lot-walk the exporter uses
    # (owner via the lot, so standalone credits are seen consistently), keyed by
    # the same account names declared above.
    from services.gnucash_importer import find_account
    from use_cases.export_transactions import open_prepayments_for_account
    root = book.get_root_account()
    actual = {}
    for account_name in {k[0] for k in declared}:
        acct = find_account(root, account_name)
        if acct is None:
            continue
        for kind, oid, _guid, amount in open_prepayments_for_account(acct):
            actual[(account_name, kind, oid)] = (
                actual.get((account_name, kind, oid), 0.0) + amount)

    for key in sorted(set(declared) | set(actual)):
        d_amt = declared.get(key, 0.0)
        a_amt = actual.get(key, 0.0)
        if abs(d_amt - a_amt) > 0.005:
            account, kind, owner_id = key
            click.echo(
                f"  warning: open_prepayment on {account} for {kind} "
                f"{owner_id!r} declares {d_amt:.2f} but the book holds "
                f"{a_amt:.2f}", err=True)


@click.command()
@click.argument('gnucash_file', required=False, type=click.Path())
@click.argument('input_file', required=False, type=click.Path())
@click.option('-i', '--input', 'gnucash_path', type=click.Path(), help='GnuCash XML file')
@click.option('-f', '--file', 'plaintext_file', type=click.Path(), help='Plaintext transactions file')
@click.option(
    '--strategy',
    type=click.Choice(['skip', 'keep-existing', 'keep-incoming', 'update'], case_sensitive=False),
    default='skip',
    help='Conflict resolution strategy (default: skip). '
         'update: modify existing transactions in-place when a GUID match is found, preserving their GUID.'
)
@click.option(
    '--dry-run',
    is_flag=True,
    help='Preview import without making changes'
)
@click.option(
    '--new',
    'create_new',
    is_flag=True,
    help='Create a new GnuCash file (file must not already exist)'
)
@click.option('--include-business-objects', is_flag=True, help='Include business objects (customers, invoices, etc.)')
@click.option(
    '--output-new',
    'output_new',
    type=click.Path(),
    default=None,
    help='Write newly imported transactions (with GUIDs) to this file. Use "-" for stdout.'
)
def import_transactions(gnucash_file, input_file, gnucash_path, plaintext_file, strategy, dry_run, create_new, include_business_objects, output_new):
    """
    Import plaintext transactions to GnuCash file.

    Supports both positional and flag-based arguments:

    \b
    Positional style:
        gnucash-plaintext import mybook.gnucash transactions.txt

    \b
    Flag style:
        gnucash-plaintext import -i mybook.gnucash -f transactions.txt

    Examples:

        gnucash-plaintext import mybook.gnucash transactions.txt

        gnucash-plaintext import -i mybook.gnucash -f transactions.txt

        gnucash-plaintext import mybook.gnucash transactions.txt --dry-run

        gnucash-plaintext import -i mybook.gnucash -f transactions.txt --strategy keep-incoming

        gnucash-plaintext import --new mybook.gnucash chart-of-accounts.txt

        gnucash-plaintext import mybook.gnucash transactions.txt --output-new new.txt

        gnucash-plaintext import mybook.gnucash transactions.txt --output-new -
    """
    # Support both positional and flag-based arguments
    gnucash_file = gnucash_path or gnucash_file
    input_file = plaintext_file or input_file

    if not gnucash_file:
        raise click.UsageError("Missing GnuCash file. Use positional argument or -i/--input flag.")
    if not input_file:
        raise click.UsageError("Missing plaintext file. Use positional argument or -f/--file flag.")

    if create_new and dry_run:
        raise click.UsageError("--new and --dry-run are mutually exclusive: --new always creates a file.")
    if output_new and dry_run:
        click.echo("Warning: --output-new is ignored in dry-run mode (no changes are saved)", err=True)

    # Validate all paths before touching the filesystem
    if create_new:
        if os.path.exists(gnucash_file):
            raise click.UsageError(
                f"File already exists: {gnucash_file}. "
                "Remove it first or omit --new to import into existing file."
            )
    else:
        if not os.path.exists(gnucash_file):
            raise click.UsageError(
                f"GnuCash file does not exist: {gnucash_file}. "
                "Use --new to create it."
            )
    if not os.path.exists(input_file):
        raise click.UsageError(f"Plaintext file does not exist: {input_file}")
    if output_new and output_new != '-':
        out_dir = os.path.dirname(os.path.abspath(output_new))
        if not os.path.isdir(out_dir):
            raise click.UsageError(f"--output-new directory does not exist: {out_dir}")

    # Map CLI strategy to ResolutionStrategy enum
    strategy_map = {
        'skip': ResolutionStrategy.SKIP,
        'keep-existing': ResolutionStrategy.KEEP_EXISTING,
        'keep-incoming': ResolutionStrategy.KEEP_INCOMING,
        'update': ResolutionStrategy.UPDATE,
    }
    resolution_strategy = strategy_map[strategy]

    try:
        if create_new:
            GnuCashRepository.create_new_file(gnucash_file)

        # Open repository
        mode = SessionMode.READ_ONLY if dry_run else SessionMode.NORMAL
        repo = GnuCashRepository(gnucash_file)
        repo.open(mode=mode)

        try:
            biz_objects_imported = 0
            biz_directives = None
            if include_business_objects:
                # Q-016: parse + create accounts now so business-object
                # directives are ready, but defer their import until AFTER
                # the standalone transaction pass. An invoice's `payment:`
                # block with `txn_guid:` resolves against a bank tx that
                # must already exist in the book — the standalone tx
                # import is what creates it.
                click.echo("Importing business objects...")
                parser = PlaintextParser()
                parser.parse_file(input_file)
                importer = GnuCashImporter()

                # Create accounts first (referenced by both standalone txs
                # and business-object directives).
                for directive in parser.root_directive.children:
                    if directive.type == DirectiveType.OPEN_ACCOUNT:
                        acct_name = directive.props.get('account', '?')
                        try:
                            importer.create_account(directive, repo.book)
                        except Exception as e:
                            raise click.ClickException(
                                f'account "{acct_name}": {e}'
                            ) from e

                # Customers, vendors, and tax tables don't depend on
                # standalone txs and may be referenced from txs (rare but
                # possible). Run them now so the standalone tx pass has
                # full account + owner context.
                biz_types_early = {
                    DirectiveType.COMPANY,
                    DirectiveType.CUSTOMER, DirectiveType.VENDOR,
                    DirectiveType.TAXTABLE,
                }
                early_directives = [
                    d for d in parser.root_directive.children
                    if d.type in biz_types_early
                ]
                early_biz_result = importer.import_business_objects(
                    early_directives, repo.book,
                    on_directive_status=lambda kind, ident, status: click.echo(
                        f'{kind} "{ident}": {status}'
                    ),
                )

                # Defer invoice + bill processing until after the
                # standalone transaction pass so `txn_guid:` lookups
                # resolve.
                biz_directives = [
                    d for d in parser.root_directive.children
                    if d.type in (DirectiveType.INVOICE, DirectiveType.BILL)
                ]
                biz_objects_imported = (
                    len(early_directives) + len(biz_directives)
                )

            # Create use case
            use_case = ImportTransactionsUseCase(repo)

            # Import standalone transactions (Q-016: BEFORE invoices/bills).
            click.echo(f"Importing transactions from {input_file}...")
            if dry_run:
                click.echo("(Dry run - no changes will be made)")

            result = use_case.import_from_file(input_file, resolution_strategy)

            # Now process the deferred invoice/bill directives — by now
            # any bank tx referenced via `txn_guid:` is in the book.
            biz_result = early_biz_result if include_business_objects else None
            if biz_directives:
                late_result = importer.import_business_objects(
                    biz_directives, repo.book,
                    on_directive_status=lambda kind, ident, status: click.echo(
                        f'{kind} "{ident}": {status}'
                    ),
                    on_orphan_warning=lambda kind, ident, orphans: click.echo(
                        format_orphan_warning_block(kind, orphans, ident=ident),
                        err=True,
                    ),
                )
                # Merge invoice/bill counts into the early (customer/vendor/
                # taxtable) result for the summary output.
                for kind in ('invoice', 'bill'):
                    for k, v in late_result.counts[kind].items():
                        biz_result.counts[kind][k] += v

            # open_prepayment: the per-account summary is informational and
            # derived, so the book is authoritative — recompute from the live
            # lots and WARN (never fail) when a declared block disagrees. The
            # next export self-heals the file.
            if include_business_objects and not dry_run:
                _warn_open_prepayment_mismatches(
                    parser.root_directive.children, repo.book)

            # Display results
            click.echo("")
            click.echo("Import Summary:")
            click.echo("=" * 50)
            click.echo(f"  Transactions: {result.imported_count}")
            click.echo(f"  Updated:      {result.updated_count}")
            click.echo(f"  Accounts:     {result.accounts_created}")
            click.echo(f"  Skipped:      {result.skipped_count} (duplicates)")
            click.echo(f"  Conflicts:    {len(result.conflicts)}")
            click.echo(f"  Errors:       {result.error_count}")

            # Hint: some skipped "duplicates" actually had edited content — the
            # default strategy matches them by GUID and skips, so the edit was
            # dropped. Point the user at --strategy update (no behaviour change).
            changed = getattr(result, 'guid_changed_skips', 0)
            if changed:
                noun = 'transaction' if changed == 1 else 'transactions'
                click.echo(
                    f"\n  Note: {changed} skipped {noun} matched an existing GUID "
                    f"but had different content — looks like an edit. To apply "
                    f"such edits in place (preserving the GUID), re-run with "
                    f"--strategy update.", err=True)

            # Surface the actual error text, not just the count, so the user
            # knows what failed and why — e.g. a prepayment-settlement split
            # that found no open credit, or an owner/account mismatch. Goes to
            # stderr so it stands out and survives piping stdout elsewhere.
            for err in (result.errors or []):
                props = err.get('transaction') or {}
                label = (props.get('tx_desc') or props.get('date')
                         or '<transaction>')
                click.echo(f"    error: {label}: {err['error']}", err=True)

            # Business-objects summary (Q-009): only emit when business
            # objects were actually processed; otherwise this section is
            # noise on transaction-only imports.
            if include_business_objects and biz_objects_imported > 0:
                click.echo("")
                click.echo("Business Objects:")
                labels = [
                    ('company',  'Company'),
                    ('customer', 'Customers'),
                    ('vendor',   'Vendors'),
                    ('taxtable', 'Tax tables'),
                    ('invoice',  'Invoices'),
                    ('bill',     'Bills'),
                ]
                for kind, label in labels:
                    counts = biz_result.counts[kind]
                    if biz_result.total(kind) == 0:
                        continue
                    parts = [
                        f"{counts['created']} created",
                        f"{counts['updated']} updated",
                        f"{counts['unchanged']} unchanged",
                        f"{counts['skipped']} skipped",
                    ]
                    click.echo(f"  {(label + ':'):<12} {', '.join(parts)}")

            if result.conflicts:
                click.echo("")
                click.echo("Conflicts detected:")
                for conflict in result.conflicts:
                    click.echo(f"  - {conflict.existing_description} vs {conflict.incoming_description}")

            if result.errors:
                click.echo("")
                click.echo("Errors:")
                for error in result.errors:
                    click.echo(f"  - {error['error']}")

            # Save if not dry run and something was imported.
            # biz_objects_imported must be included here: business objects are
            # written to GnuCash memory before import_from_file() runs, so they
            # are never reflected in result.imported_count / accounts_created.
            # Without this, importing into an existing file that already has all
            # accounts produces has_changes=False → repo.save() is skipped →
            # customers/invoices/bills are silently lost on session.end().
            has_changes = (
                result.imported_count > 0
                or result.updated_count > 0
                or result.accounts_created > 0
                or biz_objects_imported > 0
            )
            if not dry_run and has_changes:
                click.echo("")
                click.echo("Saving changes...")
                repo.save()
                click.echo("✓ Changes saved")

                # Write newly created transactions (transaction blocks only, with GUIDs)
                if output_new and result.new_transactions:
                    exporter = ExportTransactionsUseCase(repo)
                    plaintext = exporter.format_transaction_list(result.new_transactions)
                    if output_new == '-':
                        # Write raw plaintext to stdout — no header so output
                        # remains parseable when piped or redirected
                        click.echo(plaintext, nl=False)
                    else:
                        try:
                            with open(output_new, 'w', encoding='utf-8') as f:
                                f.write(plaintext)
                            click.echo(f"✓ New transactions written to {output_new}")
                        except OSError as exc:
                            raise click.ClickException(f"Could not write --output-new file: {exc}") from exc
            elif dry_run:
                click.echo("")
                click.echo("✓ Dry run complete (no changes made)")
            else:
                click.echo("")
                click.echo("✓ Nothing to import")

        finally:
            repo.close()

    except Exception as e:
        if create_new and os.path.exists(gnucash_file):
            os.remove(gnucash_file)
        raise click.ClickException(str(e)) from e
