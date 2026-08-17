#!/usr/bin/env python
"""Set the two free-text boxes carried by a printed document.

GnuCash's report options give the pair as **Printable Invoice → Display →
Extra Notes** and **Printable Invoice → Layout → CSS**. `set-invoice-style`
writes both from the command line and keeps both in the book, so a document
printed from a script carries the footer and the styling with no GnuCash
window open anywhere.
"""

from pathlib import Path

import click

from cli._saving import save_or_report
from repositories.gnucash_repository import GnuCashRepository, SessionMode
from services.invoice_style import OFF_THE_BOOK, the_books_invoice_style
from use_cases.set_invoice_style import execute_set_invoice_style


@click.command()
@click.argument('gnucash_file', type=click.Path(exists=True))
@click.option('--note', default=None,
              help='The footer under a printed document — GnuCash\'s '
                   'Display → Extra Notes. Pass "" for no footer.')
@click.option('--css', 'css_file', default=None,
              type=click.Path(exists=True, dir_okay=False),
              help='A CSS file for the page — GnuCash\'s Layout → CSS. The '
                   'file is the whole stylesheet and replaces the one the '
                   'report ships with, which draws the line-item borders and '
                   'table widths; print with --clear-css and copy the page\'s '
                   '<style> block to start from it. Stored in the book, so '
                   'the file is read once and not needed again.')
@click.option('--clear-note', is_flag=True, default=False,
              help='Take the footer off the book, so the footer the report '
                   'itself carries prints again.')
@click.option('--clear-css', is_flag=True, default=False,
              help='Take the CSS back to the report\'s own.')
@click.option('--show', is_flag=True, default=False,
              help='Print what the book holds and change nothing.')
def set_invoice_style(gnucash_file, note, css_file, clear_note, clear_css,
                      show):
    """Set the notes and CSS a printed invoice or bill carries.

    Examples:

        # a footer, in place of GnuCash's "Thank you for your patronage!"
        set-invoice-style book.gnucash --note "Payment due in 30 days"

        # no footer at all
        set-invoice-style book.gnucash --note ""

        # GnuCash's own footer back
        set-invoice-style book.gnucash --clear-note

        # styling for the page, from a CSS file
        set-invoice-style book.gnucash --css invoice.css

        # what the book holds now
        set-invoice-style book.gnucash --show
    """
    # Two ways to say what the CSS should be, and two things to do with the
    # book. Neither pair has an order that is more right than the other, so
    # neither is given one: obeying half of what was typed and saying nothing
    # about the rest is how `--note "x" --show` printed the *old* footer and
    # set nothing, reading exactly like a write that had happened.
    if clear_css and css_file:
        raise click.UsageError(
            '--css and --clear-css say different things about the same '
            'setting: one sets the styling from a file, the other takes it '
            'back to the report\'s own')
    if clear_note and note is not None:
        raise click.UsageError(
            '--note and --clear-note say different things about the same '
            'setting: one sets the footer — `--note ""` for no footer at all '
            '— and the other takes the footer off the book, leaving the one '
            'the report itself carries')
    if show and (note is not None or css_file or clear_css or clear_note):
        raise click.UsageError(
            '--show reads the book and changes nothing, so it cannot be '
            'combined with a setting — run it again on its own to see what '
            'was set')

    css = None
    if clear_css:
        css = OFF_THE_BOOK
    elif css_file:
        try:
            css = Path(css_file).read_text(encoding='utf-8')
        except UnicodeDecodeError as unreadable:
            # A stylesheet saved as Latin-1 — a `©` or a curly quote in a
            # comment is all it takes. The text is stored in the book and
            # crosses into GnuCash as UTF-8, so the file has to be UTF-8, and
            # a named refusal beats the traceback every other path here
            # avoids.
            raise click.UsageError(
                f'{css_file} is not UTF-8 text and could not be read: '
                f'{unreadable}') from unreadable
        # A file holding nothing is refused rather than read as `--clear-css`.
        # Both take the styling back to the report's own, and one of the two
        # is a file a build step truncated — reported as `✓ Set css` over a
        # page carrying none of the styling the file was supposed to hold.
        #
        # `strip()`, because a file written by `echo >` or by a generator that
        # emitted only its trailing newline holds `"\n"`, which is not empty
        # and is not styling either: stored, it *replaces* the report's own
        # CSS, so the page loses the styling `--clear-css` would have given
        # back.
        if not css.strip():
            raise click.UsageError(
                f'{css_file} holds no styling — pass --clear-css to take the '
                f'page back to the styling the report itself carries')

    if show:
        repo = GnuCashRepository(gnucash_file)
        repo.open(SessionMode.READ_ONLY)
        try:
            held_css, held_note = the_books_invoice_style(repo.book)
        finally:
            repo.close()
        # A footer set to nothing is the one state a bare value cannot show:
        # `note: ` reads as truncated output, and README points at `--show` as
        # the way to tell a footer set empty from a book that names none.
        if held_note is None:
            click.echo('note: (none — the report\'s own footer prints)')
        elif held_note == '':
            click.echo('note: (empty — no footer prints)')
        else:
            click.echo(f'note: {held_note}')
        if held_css is None:
            click.echo('css:  (the report\'s own)')
        else:
            # Unindented, so what follows the header is the stylesheet as the
            # book holds it rather than a copy two spaces deeper. Reading is
            # what this is for: the `note:` line above may itself run to
            # several lines, so no fixed number of lines to skip recovers the
            # block. The stylesheet a book carries is also in every page it
            # draws, inside `<style>`, which is where README sends a reader
            # who has lost the file.
            click.echo('css:')
            click.echo(held_css.rstrip('\n'))
        return

    if clear_note:
        note = OFF_THE_BOOK

    if css is None and note is None:
        raise click.UsageError(
            'nothing to set: pass --note, --clear-note, --css, --clear-css '
            'or --show')

    repo = GnuCashRepository(gnucash_file)
    repo.open(SessionMode.NORMAL)
    try:
        try:
            changed = execute_set_invoice_style(repo.book, css=css, note=note)
        except Exception as refused:
            # Non-zero and carrying the reason, rather than `✓ Set note` over
            # a book holding nothing new: writing the setting is the whole of
            # what the command does. The sentence quotes what the book raised
            # — `write_book_string_option` lets the exception out for exactly
            # this — and `from refused` keeps the traceback.
            raise click.ClickException(
                f'the book would not take the setting: '
                f'{type(refused).__name__}: {refused}') from refused
        if not changed:
            click.echo('✓ Already set that way')
            return
        save_or_report(repo)
    finally:
        repo.close()
    click.echo(f'✓ Set {" and ".join(changed)}')
