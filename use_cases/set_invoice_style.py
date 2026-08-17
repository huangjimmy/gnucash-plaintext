"""Write the footer and the CSS a printed document carries onto the book.

GnuCash's report options give the pair as **Layout → CSS** and **Display →
Extra Notes**, and until now setting either meant opening GnuCash, which is no
use on a machine printing from a script. `set-invoice-style` writes both from
the command line.

`services/invoice_style.py` holds the slots, the storage rule and the read —
asked on every render by `print-invoice`. What lives here is the write:
comparing each setting against the book, writing only a setting that differs,
and reporting what changed and what refused.
"""

from infrastructure.gnucash.kvp import (
    get_book_string_option,
    write_book_string_option,
)
from services.invoice_style import CSS_SLOT, NOTE_SLOT, OFF_THE_BOOK, STORED


def execute_set_invoice_style(book, css=None, note=None) -> list:
    """Set the CSS, the footer, or both. Returns what changed.

    Three values, three answers:

    * `None` leaves a setting as the book has it — an unstated option is not
      an instruction, as everywhere else in this format;
    * `OFF_THE_BOOK` takes the setting off, so the report's own footer and
      styling print again — `--clear-note` and `--clear-css`;
    * any string is stored, `''` included, which for the footer means a
      document printed with no footer at all.
    """
    changed = []
    for value, slot, what in ((css, CSS_SLOT, 'css'),
                              (note, NOTE_SLOT, 'note')):
        if value is None:
            continue
        # Taking the slot away is what leaves the report's own value in play,
        # and an empty *stored* string cannot be told from an absent slot —
        # see the note on `STORED` in `services/invoice_style.py`, which is
        # why a footer set to nothing is stored behind a prefix instead.
        wanted = '' if value is OFF_THE_BOOK else STORED + value
        if (get_book_string_option(book, 'Business', slot) or '') == wanted:
            continue
        # The raising form, so a refused write reaches the reader carrying
        # what refused it. The bool form logs the reason and answers `False`,
        # which a command whose whole job is the write would report as
        # `✓ Set note` over a book holding nothing new — or, checking the
        # bool, as a sentence about a reason it no longer has.
        write_book_string_option(book, 'Business', slot, wanted)
        changed.append(what)
    return changed
