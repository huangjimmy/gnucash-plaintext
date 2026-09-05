#!/usr/bin/env python
"""Several rendered invoices and bills as one printable page.

Each is rendered as a whole HTML file — GnuCash's report writes a
`<!DOCTYPE>`, an `<html>`, a `<head>` carrying the stylesheet, and a `<body>`.
Concatenating those files gives a page with three DOCTYPEs and three
`<html>` elements, which is invalid as HTML and as XML, so the parts are taken
apart and rebuilt into one shell.

**The shell rebuilt is the report's own, not a bare one.** The `<!DOCTYPE>`,
`<html>` and `<body>` tags are kept from the first fragment whole, attributes
and all, and the head is kept for its contents — every part of that is
something GnuCash decided and a reader can see:

* the `<!DOCTYPE>`, without which a browser lays the page out in quirks mode;
* `<html dir='auto'>`, which is how a right-to-left page reads correctly;
* `<body bgcolor="…">`, whose attributes carry the stylesheet's colours —
  GnuCash's own `html-document.scm` writes that tag with the comment "this
  lovely little number just makes sure that `<body>` attributes like bgcolor
  get included";
* the `<head>`, holding a `<link>` to the report's stylesheet, an inline
  `<style>` of its font options, and the `<meta>` naming the page's encoding
  — which is what keeps an accented name accented once the page reaches
  WebKit as a file.

Synthesised bare instead, all four were lost — and `-o file.html` takes this
path for a *single* invoice too, so the same one came out one way to a
file and another way into a directory, one in standards mode with the report's
colours and one in quirks mode without them. The first fragment's tags serve
all of them: they come from one report with one set of options, so they are
identical but for the title.

What lays the page out once it is built is `infrastructure/pdf/printing.py`,
that being an adapter to an X server and a child interpreter rather than
anything about invoices.
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


def _body_of(fragment: str) -> str:
    """What to print for one invoice or bill.

    Every fragment is a whole HTML file, because the only thing that makes
    one is GnuCash's report and `render_page_html` refuses anything that is
    not a rendered page. So the `<body>` is always there to take — and if
    a build ever draws one without it, that is a sentence like every other
    refusal here, rather than an `AttributeError` from a regex that found
    nothing.
    """
    found = _BODY.search(fragment)
    if found is None:  # pragma: no cover - no supported build draws one
        from services.gnucash_report import PageNotRenderedError

        raise PageNotRenderedError(
            'GnuCash drew a page with no <body> to print, so there is nothing '
            'to put in a combined file. This build lays its page out '
            'differently from the ten this was measured against.')
    return found.group(1)


def combine_pages(fragments) -> str:
    """One HTML file showing each of `fragments`, one per printed page.

    `page-break-after` on each section so a printed or PDF'd run starts every
    one on a fresh sheet, which is what printing them one at a time does.
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

    # `<div>` and not `<section>`: where the DOCTYPE above is GnuCash's, its
    # report writes HTML 4.01 Transitional, which has no `section`. On
    # GnuCash 3.4 the report writes no DOCTYPE at all and the page takes the
    # HTML5 fallback instead, so the declaration is not always 4.01 — but
    # `div` conforms to both, and the two lay out identically anyway: every
    # engine styles `section` as a block from its HTML5 UA sheet whatever the
    # doctype says. So the choice costs nothing under either declaration.
    pages = ''.join(
        f'<div style="page-break-after: always;">{_body_of(f)}</div>'
        for f in fragments)
    return (f'{doctype}\n{html_open}<head>{head}</head>'
            f'{body_open}{pages}</body></html>')


def _first(pattern, fragment: str, fallback: str, group: int = 0) -> str:
    """What `fragment` opens with, or `fallback` where it says nothing.

    The fallbacks differ in what they cost. The DOCTYPE, `<html>` and
    `<body>` ones are what a page needs to be a page at all — one with no
    DOCTYPE renders in quirks mode. The head's is an empty string, which is a
    page that prints unstyled; it is not a refusal like `_body_of`'s, because
    a page laid out in a browser's default fonts is still the page, where one
    with no body is not.

    **The DOCTYPE fallback is not a dead branch.** GnuCash 3.4 writes no
    DOCTYPE, so every combined page on Debian 10 takes it and gains standards
    mode from it — measured in
    `tests/research/what_shell_a_printed_page_has_probe.py`, and the reason
    `test_one_page_is_the_same_page_whichever_way_it_is_written` compares only
    the tags the verbatim page actually has. Every other build writes all
    four, so it is the one supported build that reaches this at all.
    """
    found = pattern.search(fragment)
    if found is None:
        return fallback
    return found.group(group)
