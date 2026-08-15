#!/usr/bin/env python
"""What each document is called when a run writes one file per document.

`print-invoice`/`print-bill` with `-o out/` name each file after the document
— which is what a reader wants to see in a directory — and a document's id is
theirs to choose, so it cannot be used as a path without asking two questions
first.

**Is it a path?** An id may hold a separator. `2026/001` is an ordinary way to
number an invoice, and this format accepts it, GnuCash stores it, and joining
it to the output directory addressed `out/2026/001.html` — a directory nobody
made. Measured on 5.10: `FileNotFoundError`, as a traceback, with the run
having rendered every document and written none of them. `..` in an id is the
same mechanism pointed the other way, at a file outside the directory the
reader named.

**Is it unique?** GnuCash does not make it so. Measured on 5.10: two invoices
created with one id both persist through a save and reload, so `-o out/` wrote
one file, kept whichever rendered last, and reported `✓ Wrote 2 invoice(s)`.
A document went missing and the summary said otherwise.

So a name is made safe first, and disambiguated with the document's guid only
where it has to be — an id that is unique and path-free keeps the file name it
has always had, because that name is what scripts glob for.
"""

import re
from collections import Counter

# Anything that would make the name reach outside its file: the two
# separators, and the empties (`.`, `..`) that address a directory. Kept to a
# character class rather than `Path` handling, because the answer must be the
# same on every platform — a book written on Windows prints on Linux.
_NOT_A_FILENAME = re.compile(r'[/\\]+')

#: What is left of a filename's 255 bytes once this module has had its way
#: with the rest: `_` plus a 32-character guid plus `.` plus an extension is
#: 38, and the round number below it leaves room for both and to spare.
_LONGEST_STEM = 200


def safe_stem(document_id: str) -> str:
    """`document_id` as one path element, never as a path.

    Separators become `-`, so `2026/001` is `2026-001` and stays in the
    directory the reader named. A stem that would address a directory rather
    than a file — empty, `.`, `..` — becomes `document`, since a file has to
    be called something and a document with no id is a document all the same.

    And it is cut to a length a filesystem will take. That is the third
    question a free-text id has to answer, beside "is it a path?" and "is it
    unique?": an id long enough to push the name past 255 bytes raised
    `OSError` from the write, *after* every document in the run had been
    rendered — the partial directory this module's ordering exists to
    prevent. Cut on bytes rather than characters, since that is what the
    limit counts, and back to a character boundary so the name stays text.
    """
    stem = _NOT_A_FILENAME.sub('-', str(document_id or '')).strip()
    if stem in ('', '.', '..'):
        return 'document'
    encoded = stem.encode('utf-8')
    if len(encoded) > _LONGEST_STEM:
        stem = encoded[:_LONGEST_STEM].decode('utf-8', 'ignore')
    return stem


def file_names(documents, ext: str, guid_of) -> list:
    """`[(name, document)]`, one per document, all distinct.

    `guid_of` reads a document's guid, and is only called for the ones that
    need it: a name shared by two documents takes `_<guid>` on **both**, so
    neither is the one that silently kept the plain name — a reader looking
    for what they printed last time finds two files and can tell them apart,
    rather than finding one and not knowing a second existed.

    Distinctness is settled on the names themselves rather than on the stems
    they came from, because the disambiguated name is a name too. Two ways it
    could still collide, both closed here rather than argued about: a guid
    that reads back empty leaves `<id>_.ext` on every document sharing that
    id, and an id spelled exactly like another's disambiguated name lands on
    it. Neither is likely; both are the same defect as the one this exists to
    fix, and the run must not report writing a file it overwrote.
    """
    # Held as a list before anything is counted, because it is walked twice —
    # once for the stems and once to pair them back up. Handed a generator the
    # second walk saw nothing, so the run wrote no files and still reported
    # having written them, which is the failure this module exists to prevent.
    documents = list(documents)
    stems = [safe_stem(document.GetID()) for document in documents]
    # Counted once rather than per document: `print-invoice book '*' -o out/`
    # is a documented way to print a whole book, and `stems.count` inside the
    # comprehension walks the list again for each of them.
    shared = {stem for stem, times in Counter(stems).items() if times > 1}

    named = []
    taken = set()
    for stem, document in zip(stems, documents):
        name = f'{stem}_{guid_of(document)}.{ext}' if stem in shared \
            else f'{stem}.{ext}'
        # Whatever the guid gave was not enough to tell these apart, so the
        # position in the run is used instead — and then checked, because a
        # position is only unique among positions: an id spelled exactly like
        # `<stem>_<n>` is a name too, and a fallback that is not re-checked
        # lands on it, which is the overwrite this whole module exists to
        # stop.
        #
        # What makes the loop safe is the re-check, not the counter: an
        # earlier document may well be called `SAME-ID_1` already. It ends
        # because each pass tries a name it has not tried and there are
        # finitely many documents to have claimed them.
        attempt = len(named) + 1
        while name in taken:
            name = f'{stem}_{attempt}.{ext}'
            attempt += 1
        taken.add(name)
        named.append((name, document))
    return named
