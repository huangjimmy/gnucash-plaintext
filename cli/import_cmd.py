"""
CLI command for importing plaintext transactions to GnuCash.
"""

import os
import re
from fractions import Fraction

import click

from infrastructure.gnucash.utils import exact_text
from repositories.gnucash_repository import GnuCashRepository, SessionMode
from services.conflict_resolver import ResolutionStrategy
from services.gnucash_importer import GnuCashImporter
from services.plaintext_parser import DirectiveType
from use_cases.export_transactions import ExportTransactionsUseCase
from use_cases.import_transactions import ImportTransactionsUseCase
from use_cases.unpost_business_objects import format_orphan_warning_block


def _named_in(name: str, message: str) -> bool:
    """Whether `message` names exactly this account or commodity.

    Whole name, not substring. `Income:Sales` is a substring of
    `Income:Sales Returns`, so a failure to create the first would be welded
    onto a message about the second — sending the reader to a line that is
    correct, which is the one thing this clause exists to prevent.

    Both ends, because a name has two of them: `ZZ` is the tail of `XZZ`, and
    written on the right alone this offered a refused `ZZ` as the reason an
    account kept in `XZZ` could not be made. That one hides, because it is
    usually accidentally right — a failed `USD` really does explain
    `Assets:Bank:USD`.

    What may sit either side is a character a name could not have continued
    with. Every message these are matched against delimits a name that way —
    quoted (`'Income:Sales' not found`) or in a list (`(FUND, FUNDX)`).

    A name ending a sentence would not match, because a full stop is a
    character a name can contain. No message reads that way, and one reworded
    to would fail the tests that pin this chain rather than quietly stop
    naming causes — so this is written for the shapes that exist, not for a
    period that would have to be told apart from `Sales.Old` on the day one
    appeared.
    """
    if not name:
        return False
    # The quote is not in either set, because quoting is how these messages
    # usually delimit a name — `'Liabilities:GST' not found`. Left in, the
    # whole chain this function serves stopped matching.
    #
    # And a space is on the right only. A name may be *followed* by one and
    # still continue (`Income:Sales Returns`), but it is regularly *preceded*
    # by one as a separator — `Cannot find commodity (CURRENCY, XZZ)` — so
    # forbidding it on the left threw away the correct cause along with the
    # wrong one. What is left on that side are the characters that continue a
    # name with nothing between, which is what `ZZ` inside `XZZ` is.
    before, after = r"[\w.:-]", r"[\w &.:-]"
    return re.search(f'(?<!{before})' + re.escape(name) + f'(?!{after})',
                     message) is not None


def _subject_of(reported: str) -> str:
    """What a `Failed to create X <name>: …` line is about, or ''.

    Cut at the colon-and-space that ends the name, not at the first colon: an
    account's own name is full of colons — `Failed to create account
    Income:Sales: …` is about `Income:Sales`, and splitting on `:` made it
    about `Income`.
    """
    for prefix in ('Failed to create commodity ', 'Failed to create account '):
        if reported.startswith(prefix):
            return re.split(r':\s', reported[len(prefix):])[0].strip()
    return ''


def _report_what_was_already_found(result) -> None:
    """Print the errors this run had collected, before one raises past them.

    A business object that raises leaves by a different door from the summary,
    so everything the commodity, account and transaction passes had gathered
    went unprinted: the reader corrected the one failure they were shown, ran
    again, and met the next. The export half of this release gathers a whole
    book's offenders so it is fixed in one pass; this is the same thing on the
    way in.

    Only what the run found *before* the raise. What comes after is not
    reached, and claiming otherwise would be a summary of a run that stopped.
    """
    for entry in (result.errors or []) if result is not None else ():
        click.echo(f"  error: {entry['error']}", err=True)


def _reraise_with_the_cause(exc, also=()):
    """Re-raise a business-object failure with what actually went wrong.

    An account this run could not make is very often what a business object is
    failing over, and the account's own error says what was wrong with the
    declaration — the line the reader edits. Read only as "account not found",
    the run names something written correctly and sends them to look at it.

    `also` is what the run has already reported: the commodity and account
    steps run before this, and their failures are in `result.errors`.

    Followed as far as it reaches, because the cause can be two steps down. A
    commodity fails, the account kept in it fails naming the mnemonic, and the
    tax table posting to that account fails naming the account — so the tax
    table's own message reaches the account, and the account's reaches the
    commodity. Attached in rounds until nothing new matches.

    And only what a failure actually names. Taken whole, every per-object error
    in the run was welded on, so an invoice failing over a missing tax table
    was told "That account could not be created: the amount on split
    'Expenses:Fuel' states 18.191 CAD".

    Both the owners pass and the invoice pass go through here, because they
    meet the same missing account by different routes and only one of them had
    the handling.
    """
    message = str(exc)
    reaching = message
    remaining = [text for text in also if text and text not in message]
    attached = []
    while True:
        found = [text for text in remaining if _named_in(_subject_of(text),
                                                         reaching)]
        if not found:
            break
        for text in found:
            remaining.remove(text)
            attached.append(text)
            reaching = f'{reaching} {text}'
    if attached:
        # Each kind under its own clause. Carried under one worded for an
        # account, a commodity's failure read `That account could not be
        # created: Failed to create commodity XYZ` — the cause correct, and
        # the sentence around it pointing at the account declaration, in the
        # one message written to stop a reader looking in the wrong place.
        for kind, prefix in (('account', 'Failed to create account '),
                             ('commodity', 'Failed to create commodity ')):
            of_this_kind = [t for t in attached if t.startswith(prefix)]
            if of_this_kind:
                message = (f'{message}. That {kind} could not be created: '
                           + '; '.join(of_this_kind))
        raise ValueError(message) from exc
    raise exc


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
                amount = Fraction(str(md.get('amount', '0')).split()[0])
            except (ValueError, IndexError, ZeroDivisionError):
                continue
            key = (account, kind, md.get(kind))
            declared[key] = declared.get(key, Fraction(0)) + amount

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
                actual.get((account_name, kind, oid), Fraction(0)) + amount)

    # Both sides are exact, so a declared credit either matches what the book
    # holds or it does not — no half-cent slack to absorb a float's drift.
    for key in sorted(set(declared) | set(actual)):
        d_amt = declared.get(key, Fraction(0))
        a_amt = actual.get(key, Fraction(0))
        if d_amt != a_amt:
            account, kind, owner_id = key
            click.echo(
                f"  warning: open_prepayment on {account} for {kind} "
                f"{owner_id!r} declares {exact_text(d_amt)} but the book holds "
                f"{exact_text(a_amt)}", err=True)


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
@click.option(
    '--fx-rates',
    'fx_rates_file',
    type=click.Path(exists=True),
    default=None,
    help='YAML exchange rates, flat (USD: 1.36) or dated. Required to post a '
         'foreign-currency invoice or bill whose income/expense account is in '
         'another currency — that is the rate its revenue is booked at.'
)
def import_transactions(gnucash_file, input_file, gnucash_path, plaintext_file, strategy, dry_run, create_new, include_business_objects, output_new, fx_rates_file):
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

    fx_rates = None
    if fx_rates_file:
        from services.fx_rates import FxRates
        try:
            fx_rates = FxRates.load(fx_rates_file)
        except (OSError, ValueError) as exc:
            raise click.UsageError(f"Could not read --fx-rates file: {exc}") from exc

    # Map CLI strategy to ResolutionStrategy enum
    strategy_map = {
        'skip': ResolutionStrategy.SKIP,
        'keep-existing': ResolutionStrategy.KEEP_EXISTING,
        'keep-incoming': ResolutionStrategy.KEEP_INCOMING,
        'update': ResolutionStrategy.UPDATE,
    }
    resolution_strategy = strategy_map[strategy]

    # Whether anything has reached the book yet, which decides whether a
    # failure below may take a `--new` file away with it.
    saved = False
    # Whether the run reported anything it could not do. Read after the
    # session is closed, so the exit and any cleanup happen in that order.
    failed = False

    try:
        if create_new:
            GnuCashRepository.create_new_file(gnucash_file)

        # Open repository
        mode = SessionMode.READ_ONLY if dry_run else SessionMode.NORMAL
        repo = GnuCashRepository(gnucash_file)
        repo.open(mode=mode)

        try:
            biz_objects_seen = 0
            biz_directives = None
            early_biz_result = None
            all_directives = []
            importer = GnuCashImporter()

            def _owners_and_tax_tables(parser, result):
                """Customers, vendors, tax tables — after the accounts, before
                the transactions.

                A standalone transaction may name an owner or a tax table, so
                they have to be in the book before the transaction pass; they
                name accounts, so the accounts come before them. Invoices and
                bills stay behind until afterwards, because their `txn_guid:`
                resolves against a bank transaction the transaction pass is
                about to create.

                Called by `import_from_file` between those two steps, so the
                declarations in the file are carried out once each and in that
                order. Doing it here instead — a second parse and a second run
                of the commodity and account loops — is what made every count,
                every refusal and every remembered fact something that had to
                be reconciled between two passes afterwards.
                """
                nonlocal biz_directives, biz_objects_seen, early_biz_result
                nonlocal all_directives
                click.echo("Importing business objects...")
                # The file, read once. What the deferred invoice pass and the
                # `open_prepayment:` check need is here, and reading it again
                # to get it is what this hook exists to stop.
                all_directives = list(parser.root_directive.children)
                early_directives = [
                    d for d in parser.root_directive.children
                    if d.type in {DirectiveType.COMPANY, DirectiveType.CUSTOMER,
                                  DirectiveType.VENDOR, DirectiveType.TAXTABLE}
                ]
                biz_directives = [
                    d for d in parser.root_directive.children
                    if d.type in (DirectiveType.INVOICE, DirectiveType.BILL)
                ]
                biz_objects_seen = len(early_directives) + len(biz_directives)
                try:
                    early_biz_result = importer.import_business_objects(
                        early_directives, repo.book,
                        on_directive_status=lambda kind, ident, status: click.echo(
                            f'{kind} "{ident}": {status}'
                        ),
                        fx_rates=fx_rates,
                    )
                except Exception as exc:
                    # What the steps above already reported. A tax table
                    # posting to an account whose own line was refused fails
                    # with "account not found" — true, and not the reason,
                    # which is a line above it in the reader's own file.
                    #
                    # Printed as well as attached: the cause is welded onto
                    # this failure, and everything else the run found is still
                    # the reader's to fix on this pass rather than the next.
                    _report_what_was_already_found(result)
                    _reraise_with_the_cause(
                        exc, [e['error'] for e in (result.errors or [])])

            # Create use case
            use_case = ImportTransactionsUseCase(repo)

            # Import standalone transactions (Q-016: BEFORE invoices/bills).
            click.echo(f"Importing transactions from {input_file}...")
            if dry_run:
                click.echo("(Dry run - no changes will be made)")

            result = use_case.import_from_file(
                input_file, resolution_strategy,
                on_accounts_ready=(_owners_and_tax_tables
                                   if include_business_objects else None))
            # A file that could not be read is refused, not summarised. The
            # hook above never runs for one — the parse is checked before any
            # declaration is carried out — so both paths agree on the exit code
            # and on whether a book is left behind.
            if result.parse_failed:
                raise click.ClickException(
                    f'{input_file} could not be read, so nothing was '
                    f'imported:\n  - '
                    + '\n  - '.join(e['error'] for e in result.errors))

            # Now process the deferred invoice/bill directives — by now
            # any bank tx referenced via `txn_guid:` is in the book.
            biz_result = early_biz_result if include_business_objects else None
            if biz_directives:
                try:
                    late_result = importer.import_business_objects(
                        biz_directives, repo.book,
                        on_directive_status=lambda kind, ident, status: click.echo(
                            f'{kind} "{ident}": {status}'
                        ),
                        on_orphan_warning=lambda kind, ident, orphans: click.echo(
                            format_orphan_warning_block(kind, orphans, ident=ident),
                            err=True,
                        ),
                        fx_rates=fx_rates,
                    )
                except Exception as exc:
                    # The same carrying as the early pass, and needed more
                    # here: an entry posting to an income account is the
                    # ordinary way to meet an account that could not be made,
                    # where a tax table is not. This one raises past the
                    # summary, so `result.errors` — which by now holds the
                    # account's own failure from the transaction pass — is
                    # never printed, and the reader was left with `invoice
                    # "INV-1": Account 'Income:Sales' not found`, true and not
                    # the reason.
                    _report_what_was_already_found(result)
                    _reraise_with_the_cause(
                        exc, [e['error'] for e in (result.errors or [])])
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
                _warn_open_prepayment_mismatches(all_directives, repo.book)

            # Display results
            click.echo("")
            click.echo("Import Summary:")
            click.echo("=" * 50)
            click.echo(f"  Transactions: {result.imported_count}")
            click.echo(f"  Updated:      {result.updated_count}")
            click.echo(f"  Commodities:  {result.commodities_created} created, "
                       f"{result.commodities_updated} updated")
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
            #
            # `seen`, not `changed` — the section's whole content is what the
            # book did about them, `unchanged` included, so a run that changed
            # none of them still has something to report. The two were one
            # counter, and `has_changes` reading it meant an unchanged ledger
            # rewrote the book on every run.
            if include_business_objects and biz_objects_seen > 0:
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
            # Business objects must be counted here: they are written to
            # GnuCash memory before import_from_file() runs, so they are never
            # reflected in result.imported_count / accounts_created. Without
            # them, importing into an existing file that already has all
            # accounts produces has_changes=False → repo.save() is skipped →
            # customers/invoices/bills are silently lost on session.end().
            #
            # What the book *did* about them, not how many the file carried.
            # Counting directives, a ledger of one customer and one invoice
            # re-imported unchanged reported every object `unchanged` and then
            # saved the book anyway — every run, with a fresh timestamped
            # backup each time, and two runs in one second meet
            # `ERR_FILEIO_BACKUP_ERROR`. That is the same defect the commodity
            # and account counters were split apart to fix, on the third
            # counter.
            biz_objects_changed = sum(
                counts.get('created', 0) + counts.get('updated', 0)
                for counts in (biz_result.counts.values() if biz_result else ()))
            # Commodities count too: a file that declares one and nothing else
            # changes the book, and leaving it out meant `import --new
            # book.gnucash <commodities>.txt` reported "Nothing to import" and
            # wrote a book without them. That is the file a reader ends up
            # with after being told to declare their unit as a fund rather
            # than a currency.
            has_changes = (
                result.imported_count > 0
                or result.updated_count > 0
                or result.commodities_created > 0
                or result.commodities_updated_on_disk > 0
                or result.accounts_created > 0
                or biz_objects_changed > 0
            )
            if not dry_run and has_changes:
                click.echo("")
                click.echo("Saving changes...")
                repo.save()
                saved = True
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

            elif dry_run and not result.error_count:
                click.echo("")
                click.echo("✓ Dry run complete (no changes made)")
            elif dry_run:
                # A dry run reports what would happen, and what would happen
                # here is a refusal. Ticked regardless, it printed its errors,
                # signed off clean, and exited 1 — the same contradiction the
                # branch below was written against, one arm over.
                #
                # And what would happen is rarely all-or-nothing: a file of
                # nine good transactions and one bad one imports the nine and
                # refuses the one. Said as "nothing would be imported", that
                # read four lines under `Transactions: 9` — and it is the
                # sentence a reader consults *before* committing to the real
                # run, which saves those nine. "Nothing to import" and
                # "nothing could be imported" are different answers here too.
                click.echo("")
                if has_changes:
                    click.echo(
                        f"✗ Dry run complete — {result.error_count} "
                        f"object(s) would be refused; the rest would import",
                        err=True)
                else:
                    click.echo(
                        "✗ Dry run complete — nothing would be imported",
                        err=True)
            elif result.error_count:
                # "Nothing to import" and "nothing could be imported" are
                # different answers, and the tick belongs to the first. Said
                # with a tick, a run whose every object was refused printed
                # its errors and then signed off as though the file had
                # simply held nothing new.
                click.echo("")
                click.echo("✗ Nothing was imported", err=True)
            else:
                click.echo("")
                click.echo("✓ Nothing to import")

            # A run that reported errors exits non-zero, whichever path
            # produced them. `Errors: N` printed and the command returned 0,
            # so `import … && next-step` carried on over a book that had
            # loaded nothing — while the same file with
            # `--include-business-objects` stopped, because that path raises
            # on the failures this one collects. One file, two answers, and a
            # script is the caller that cannot see the difference.
            #
            # After the save, not instead of it: what did import is imported,
            # and the exit code is how the run says the rest did not.
            # Noted rather than raised here: the `finally` below closes the
            # session, and a `--new` book that never got anything is swept
            # after that — the same order every other cleanup path uses.
            # Unlinking the data file with the session still open leaves the
            # engine holding a path that is gone, which is the state the
            # sweep exists to avoid rather than create.
            failed = result.error_count > 0

        finally:
            repo.close()

        if failed:
            if create_new and not saved and os.path.exists(gnucash_file):
                os.remove(gnucash_file)
            raise SystemExit(1)

    except Exception as e:
        # A book `--new` made and never finished writing is swept up, so a
        # failed run does not leave an empty file where the next attempt
        # cannot write. Only while nothing has been saved, though: the
        # `--output-new` listing is written after `repo.save()` has already
        # reported `✓ Changes saved`, and an unwritable path for that side
        # file used to delete the book the run had just imported into.
        if create_new and not saved and os.path.exists(gnucash_file):
            os.remove(gnucash_file)
        raise click.ClickException(str(e)) from e
