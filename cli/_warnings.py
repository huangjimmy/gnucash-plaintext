#!/usr/bin/env python
"""Warning sinks shared by the commands, beside `_dates`, `_saving`, `_batch`.

A warning here is for something a command did that the reader would want to
know about but that is not a reason to refuse: a printed page with nowhere to
put the seller's registration numbers is the case this exists for. It prints
and says so, rather than either refusing a report that is doing what it was
written to do or letting a document leave silently short of something the
reader's tax authority requires.
"""

import click


def said_once():
    """A warning sink that prints each distinct message once, to stderr.

    Printing a whole book is one process rendering many documents, and what a
    page can hold is a property of the report rather than of the document — so
    a page with nowhere for the seller's block has nowhere for it on every
    document in the run, and the same sentence would arrive once per document:
    two lines for a two-invoice book, a hundred for a book of fifty.

    To stderr, because stdout may be the document itself (`-o -`).

    Deduped on `key` and not on the message, and `key` is required, because a
    message worth reading names what was dropped and *that* varies per
    document: the seller's block is one value for the whole book, but the
    customer's is that customer's, so keying on the text collapsed the first
    sentence and repeated the second once per customer — 51 lines for a book
    of 50, from the sink written to stop exactly that. Whoever is warning
    knows what the repetition is about; defaulting it to the message would
    put the trap back for the next caller.
    """
    seen = set()

    def warn(message, key):
        if key in seen:
            return
        seen.add(key)
        click.echo(f'⚠ {message}', err=True)
    return warn
