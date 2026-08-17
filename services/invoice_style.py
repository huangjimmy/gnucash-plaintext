"""The footer and the CSS a printed document carries, as the book holds them.

GnuCash's report options give the pair as **Layout → CSS**, the styling of a
printed page, and **Display → Extra Notes**, the sentence printed under a
document. Both are report options in GnuCash and neither has a book-level home
there, so the two slots below are opened beside `Company GST Number` in the
`Business` frame.

The book, because a printed document belongs to a book: a laptop, a server and
a build printing one book produce one page, and a setting kept in the book
travels with the file rather than with the machine `set-invoice-style` was run
on.

Reading lives here rather than in `use_cases/` because `print-invoice` asks on
every render — a service reading two book options, with no orchestration in it
— and a service may not import a use case. `use_cases/set_invoice_style.py`
does the writing, deciding what changed and what to report.
"""

from infrastructure.gnucash.kvp import get_book_string_option

#: Slots in the Business frame. GnuCash has no book-level home for either
#: setting, both being report options there.
CSS_SLOT = 'Invoice CSS'
NOTE_SLOT = 'Invoice Extra Notes'

#: What is stored is the reader's text behind this prefix, because a book
#: option written empty is *removed*: `qof_book_set_string_option` with `""`
#: takes the slot away, so "set to nothing" and "never set" come back
#: identical.
#:
#: The two are not the same thing here. "Never set" prints the footer the
#: report itself carries — GnuCash's "Thank you for your patronage!" — and
#: "set to nothing" prints no footer at all, which is what emptying the box in
#: GnuCash's dialog asks for. The prefix keeps the slot non-empty so the
#: difference survives a save, and nothing outside this module and its use
#: case sees the prefix.
STORED = 'text:'


class _OffTheBook:
    """The value that takes a setting off the book altogether.

    Three states, and a setting needs a way back to the first: a book saying
    nothing about the footer prints the sentence the report carries, a book
    holding an empty footer prints none, and a book holding text prints the
    text. `''` reaches the second state, so reaching the first needs a value
    of its own — `--clear-note` passes this one.

    Named rather than spelled `None`, which already means "leave the setting
    as the book has it", and rather than a string, which is a footer somebody
    could type.
    """

    def __repr__(self):
        return 'OFF_THE_BOOK'


OFF_THE_BOOK = _OffTheBook()


def the_books_invoice_style(book) -> tuple:
    """`(css, note)` as the book holds them, `None` for a setting absent.

    `''` for a footer set to nothing, which prints no footer — distinct from
    `None`, which leaves the sentence the report itself carries.
    """
    def held(slot):
        # `execute_set_invoice_style` is the only writer of either slot —
        # nothing else in this project touches them, the importer's company
        # block iterating a fixed map of its own and `set-book-key` writing
        # custom metadata elsewhere — so a value without the prefix takes a
        # book edited by hand or by something written later. Asked rather
        # than assumed, because stripping five characters off a value that
        # never carried the prefix is a silent truncation, and asking costs
        # nothing.
        value = get_book_string_option(book, 'Business', slot)
        if not value:
            return None
        return value[len(STORED):] if value.startswith(STORED) else value

    return held(CSS_SLOT), held(NOTE_SLOT)
