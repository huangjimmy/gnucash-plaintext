"""Session ownership for batched operations (Q-031: `migrate`).

Each surgical CLI command (`rename-account`, …) used to open the book, do one
mutation, and save — so applying N of them meant N saves, and because a GnuCash
save writes a backup whose filename has a *second*-resolution timestamp, two
saves in the same second collide; back-to-back ops must be ≥1s apart. 200
renames ⇒ 200+ seconds.

To batch many operations into a single save, session ownership moves out of the
individual commands and up to a parent (the `migrate` runner). A command checks
the Click context: if a `BatchSession` is present it mutates that shared book and
records the change, leaving the single save to the owner; otherwise it runs
standalone — opens the book, mutates, saves once, closes — exactly as before.
"""


class BatchSession:
    """A book held open across a batch of operation commands, plus the running
    record of what they did. Operation commands mutate `book` and call
    `mark_dirty()` / `note()`; the owner performs the one save at the end."""

    def __init__(self, book):
        self.book = book
        self.dirty = False
        self.log = []  # one human-readable line per applied operation

    def mark_dirty(self):
        self.dirty = True

    def note(self, message):
        self.log.append(message)


def current_batch(ctx):
    """Return the active `BatchSession` from the Click context, or None when the
    command is being run standalone (no parent owns the session)."""
    obj = getattr(ctx, 'obj', None)
    return obj if isinstance(obj, BatchSession) else None
