"""`--verify-integrity`: check whether a book is consistent and balanced.

Two spellings, and the same check behind both.

**After a command that writes**, as an option on `gnucash-plaintext` itself:

    gnucash-plaintext --verify-integrity import ledger.gnucash today.txt

The command does its work and saves, and the book is then reopened and asked.
Reopened rather than asked in place, because what is worth checking is the book
on disk — the one the next command will read — and a check run against the open
session would pass on state a failed save never wrote.

**On its own**, with no command, which is a check of a book nobody is changing:

    gnucash-plaintext --verify-integrity ledger.gnucash

It exits 1 where something does not hold, so a daily run says so without anyone
reading the page.
"""

import sys
from datetime import datetime

import click

from repositories.gnucash_repository import GnuCashRepository, SessionMode
from services.book_integrity import check_a_book, say_what_it_found

VERIFY_HELP = (
    'After the command has saved, reopen the book and check that the balance '
    'sheet balances, that the income statement accounts for the retained '
    'earnings, that every income and expense account is kept in the book\'s '
    'own currency, and that no cost basis holds more of a currency than the '
    'accounts do. On its own, with no command, it checks the book and prints '
    'the result. Expensive: it draws both statements through GnuCash and walks '
    'every split, so it is a check to run when it matters rather than on every '
    'command.')


def verify_the_book(path: str, as_of=None, currency=None):
    """Check the book at `path`, print the report, and hand it back."""
    repo = GnuCashRepository(str(path))
    repo.open(SessionMode.READ_ONLY)
    try:
        report = check_a_book(repo.session, repo.book, as_of=as_of, currency=currency)
    finally:
        repo.close()
    click.echo(say_what_it_found(report))
    return report


@click.command()
@click.argument('gnucash_file', type=click.Path(exists=True))
@click.option('--as-of', 'as_of', type=click.DateTime(formats=['%Y-%m-%d']),
              help='The date the statements are drawn to. Without it, the date '
                   'of the last transaction in the book, so every transaction '
                   'is on the page.')
@click.option('--currency', 'currency',
              help='The currency the statements are in. Without it, the '
                   'currency the book is kept in.')
def verify_integrity(gnucash_file, as_of, currency):
    """Check whether a book is consistent and balanced, and say what is not."""
    report = verify_the_book(
        gnucash_file,
        as_of=as_of.date() if isinstance(as_of, datetime) else as_of,
        currency=currency)
    if not report.passed:
        sys.exit(1)
