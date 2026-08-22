"""Reading a page GnuCash drew, on every version that draws one.

The page is GnuCash's own Printable Invoice, so its wording is GnuCash's and it
is not identical across the ten supported builds. A test that pins one build's
spelling is a test that says the other nine print the page wrong.

What differs is small and known: 3.8 writes `cellspacing="0"` where 5.x writes
`"0.0"`, and spells its ellipsis `...` where 5.x uses `…`. The wording, the
column headings, the totals and the block structure are the same on both.

And one difference is the font, not GnuCash: text read back out of a PDF comes
through whatever ligatures the build's fonts have, so `Office` arrives as
`Oﬃce` on some of them. It is the same word to the person who selected it.
"""

import unicodedata


def readable(text: str) -> str:
    """The page as a person reads it, not as a byte-comparison sees it.

    NFKC folds the ligatures a PDF's text layer carries back to their letters
    and any non-breaking spaces back to spaces; `&nbsp;` is spelled out first
    because in HTML it is an entity, not yet a character.
    """
    return unicodedata.normalize('NFKC', text.replace('&nbsp;', ' '))


def is_in_progress(text: str) -> bool:
    """Whether the page says the invoice is not posted yet.

    `Invoice in progress…` on 5.x, `Invoice in progress...` on 3.8 — the same
    sentence with the ellipsis spelled differently.
    """
    return 'in progress' in readable(text)
