#!/usr/bin/env python
"""Several rendered documents as one printable page.

Each document is rendered as a whole HTML file — GnuCash's report writes a
`<!DOCTYPE>`, an `<html>`, a `<head>` carrying the stylesheet, and a `<body>`.
Concatenating those files gives a document with three DOCTYPEs and three
`<html>` elements, which is invalid as HTML and as XML, so the parts are taken
apart and rebuilt into one shell.

**The shell rebuilt is the report's own, not a bare one.** The `<!DOCTYPE>`,
`<html>` and `<body>` tags are kept from the first fragment whole, attributes
and all, and the head is kept for its contents — every part of that is
something GnuCash decided and a reader can see:

* the `<!DOCTYPE>`, without which a browser lays the page out in quirks mode;
* `<html dir='auto'>`, which is how a right-to-left document reads correctly;
* `<body bgcolor="…">`, whose attributes carry the stylesheet's colours —
  GnuCash's own `html-document.scm` writes that tag with the comment "this
  lovely little number just makes sure that `<body>` attributes like bgcolor
  get included";
* the `<head>`, holding a `<link>` to the report's stylesheet and an inline
  `<style>` of its font options.

Synthesised bare instead, all four were lost — and `-o file.html` takes this
path for a *single* document too, so the same invoice came out one way to a
file and another way into a directory, one in standards mode with the report's
colours and one in quirks mode without them. The first fragment's tags serve
all of them: they come from one report with one set of options, so they are
identical but for the title.
"""
import re

# `re.S` throughout: a head or a body spans lines, and `.` stops at a newline
# without it — which matched nothing and silently fell back to the whole file.
_HEAD = re.compile(r'<head\b[^>]*>(.*?)</head>', re.S | re.I)
_BODY = re.compile(r'<body\b[^>]*>(.*?)</body>', re.S | re.I)

# The opening tags, kept whole — attributes and all.
_DOCTYPE = re.compile(r'<!DOCTYPE[^>]*>', re.I)
_HTML_OPEN = re.compile(r'<html\b[^>]*>', re.I)
_BODY_OPEN = re.compile(r'<body\b[^>]*>', re.I)


class PdfEngineUnavailableError(RuntimeError):
    """No WeasyPrint, so an HTML page cannot be laid out as a PDF."""


def load_weasyprint():
    """WeasyPrint, or a sentence saying how to get it.

    Imported here and not at module scope, because it is needed only by
    `--format pdf` and importing it is not cheap. Its own class rather than
    the bare `ModuleNotFoundError`, so the commands can print what to install:
    a traceback is not an answer to "this machine has no PDF engine", and
    `income-statement` has said so properly for as long as it has had a PDF.
    """
    try:
        import weasyprint
    except ImportError as absent:  # pragma: no cover - every image has it
        raise PdfEngineUnavailableError(
            'WeasyPrint is not installed, so a PDF cannot be laid out. '
            'Install it with `pip install weasyprint`, or on Debian '
            '`apt install python3-weasyprint`. `--format html` and '
            '`--format plaintext` need nothing.') from absent
    return weasyprint


def _body_of(fragment: str) -> str:
    """What to print for one document.

    Every fragment is a whole HTML document, because the only thing that makes
    one is GnuCash's report and `render_document_html` refuses a page that is
    not a rendered document. So the `<body>` is always there to take — and if
    a build ever draws one without it, that is a sentence like every other
    refusal here, rather than an `AttributeError` from a regex that found
    nothing.
    """
    found = _BODY.search(fragment)
    if found is None:  # pragma: no cover - no supported build draws one
        from services.gnucash_report import DocumentNotRenderedError

        raise DocumentNotRenderedError(
            'GnuCash drew a page with no <body> to print, so there is nothing '
            'to put in a combined document. This build lays its page out '
            'differently from the ten this was measured against.')
    return found.group(1)


def combine_pages(fragments) -> str:
    """One HTML document showing each of `fragments`, one per printed page.

    `page-break-after` on each section so a printed or PDF'd run starts every
    document on a fresh sheet, which is what printing them one at a time does.
    """
    fragments = list(fragments)
    # Never empty: both print commands refuse a selection that matched nothing
    # with a `UsageError` long before this. Indexing rather than guarding, so
    # there is no branch here that no run can take.
    first = fragments[0]

    doctype = _first(_DOCTYPE, first, '<!DOCTYPE html>')
    html_open = _first(_HTML_OPEN, first, '<html>')
    body_open = _first(_BODY_OPEN, first, '<body>')
    head = _first(_HEAD, first, '', group=1)

    # `<div>` and not `<section>`: the DOCTYPE carried above is GnuCash's, and
    # its report writes HTML 4.01 Transitional, which has no `section`. The
    # two lay out identically — every engine styles `section` as a block from
    # its HTML5 UA sheet whatever the doctype says — so the choice costs
    # nothing and keeps the page conforming to what it declares itself to be.
    pages = ''.join(
        f'<div style="page-break-after: always;">{_body_of(f)}</div>'
        for f in fragments)
    return (f'{doctype}\n{html_open}<head>{head}</head>'
            f'{body_open}{pages}</body></html>')


def _first(pattern, fragment: str, fallback: str, group: int = 0) -> str:
    """What `fragment` opens with, or `fallback` where it says nothing.

    Reached only by a build whose report writes a shell none of the ten
    supported ones writes, and the fallbacks differ in what they cost. The
    DOCTYPE, `<html>` and `<body>` ones are what a page needs to be a page at
    all — a document with no DOCTYPE is a quirks-mode document. The head's is
    an empty string, which is a page that prints unstyled; it is not a refusal
    like `_body_of`'s, because a document laid out in a browser's default
    fonts is still the document, where a document with no body is not.

    The pragma is on the fallback alone — the branch that finds the tag is
    every run there has ever been.
    """
    found = pattern.search(fragment)
    if found is None:  # pragma: no cover - no supported build omits these
        return fallback
    return found.group(group)
