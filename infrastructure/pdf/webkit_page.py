#!/usr/bin/env python
"""Lay a rendered document out with WebKit — the engine GnuCash prints with.

GnuCash's Print Invoice button hands its report's HTML to WebKit and prints
that, so a page laid out any other way is a second answer to a question
GnuCash has already answered. WeasyPrint is such a second answer, and the
difference is not cosmetic: measured on one page carrying a reader's
`Table border width` of 1, WebKit paints **97** rectangles and WeasyPrint
**none**, because the borders come from HTML-4 presentational attributes
(`border`, `cellpadding`, `bgcolor`) that GnuCash's report writes and
WeasyPrint does not implement. The reader sees a printed invoice with no
lines round anything.

**This module is the child process, not a library.** It is run as
`python3 -m infrastructure.pdf.webkit_page <html> <out> <format>` by
`infrastructure/pdf/printing.py` beside it, for two reasons:

* WebKit needs a GTK main loop, and running one inside the process that holds
  an open GnuCash book and an initialised Guile is a second event loop over
  the same ctypes-shared globals — the kind of arrangement this project's
  own findings say to keep apart;
* it needs a display. A machine printing from a script has none, so the
  parent arranges one — an `Xvfb` it starts and shares across a run, the
  reader's own `DISPLAY` where there is one, or `xvfb-run` on a machine that
  has the wrapper and no server of its own. See `a_display`.

PDF and nothing else, though GnuCash's dialog offers PostScript and SVG
beside it: asked for either — same page, same code — the print operation
reports *finished* and writes no file anywhere.

**The printer is named in English on purpose.** `Print to File` is a msgid in
GTK's own `gtk30` catalogue, so a French machine calls it `Imprimer dans un
fichier` and a German one `In Datei drucken`; WebKit looks a printer up by
exact name and does not fall back, so asking for the English name under
`LANG=fr_FR` fails with `Printer not found (500)`. The parent runs this child
with `LC_MESSAGES=C` for that reason, and leaves every other category alone —
`LC_PAPER` most of all, which is what decides the sheet.
"""
import sys

import gi

gi.require_version('Gtk', '3.0')
# 4.1 is what a GnuCash 5 build carries and 4.0 what a 4.x one does. Asked in
# that order, so a machine with both takes the one its GnuCash prints with.
for _api in ('4.1', '4.0'):
    try:
        gi.require_version('WebKit2', _api)
        break
    except ValueError:  # pragma: no cover - the loop's last arm raises below
        continue

from gi.repository import GLib, Gtk, WebKit2  # noqa: E402

#: A page that never finishes loading must not hang a print run for ever, and
#: this guard has to fire before the parent's — a sentence naming WebKit beats
#: one naming a killed subprocess. The parent gives a document 90 seconds; a
#: page takes 0.42–0.60 of one, measured on 5.10 under a ten-version sweep.
GIVE_UP_AFTER = 60


def _print(source: str, target: str, fmt: str) -> int:
    view = WebKit2.WebView()
    # No JavaScript. GnuCash's report interpolates book text into the page —
    # a customer's name, an entry description, a document's notes, the logo
    # filename — and a field the report does not escape is then script that
    # runs while an invoice is being printed, with `fetch` and the rest of a
    # browser to send what is on the page somewhere. GnuCash's own viewer
    # leaves it on, being a browser as well as a printer; nothing about
    # laying out an invoice needs it, and a page that draws the same either
    # way should draw the safe way. WeasyPrint, which this replaced, ran none.
    #
    # What it does not close: a remote `<img src>`, an `@import`ed
    # stylesheet, a `<link>` — WebKit fetches those without any script, from
    # a page built out of book text. That is the exposure WeasyPrint had too,
    # so nothing here is a step back, and closing it means a network policy
    # rather than a settings flag.
    view.get_settings().set_property('enable-javascript', False)
    loop = GLib.MainLoop()
    failed = []

    def when_loaded(webview, event):
        if event != WebKit2.LoadEvent.FINISHED:
            return
        settings = Gtk.PrintSettings()
        # The printer GTK reserves for writing a file rather than sending
        # anything to a queue; with `output-uri` set, nothing is spooled.
        settings.set_printer('Print to File')
        settings.set(Gtk.PRINT_SETTINGS_OUTPUT_URI,
                     GLib.filename_to_uri(target))
        settings.set(Gtk.PRINT_SETTINGS_OUTPUT_FILE_FORMAT, fmt)
        # No paper size named, so the sheet is the one GTK derives from the
        # reader's locale — A4 nearly everywhere, US Letter under `en_US` and
        # `en_CA` — which is the sheet GnuCash starts from on the same
        # machine. Naming one printed every reader's document on the author's
        # paper, and a book that prints Letter here and A4 from GnuCash is
        # the mismatch this path exists to remove.
        operation = WebKit2.PrintOperation.new(webview)
        operation.set_print_settings(settings)
        operation.connect('finished', lambda op: loop.quit())
        operation.connect('failed',
                          lambda op, error: (failed.append(str(error)),
                                             loop.quit()))
        operation.print_()

    def when_it_will_not_load(webview, event, uri, error):
        """A load that failed, said as a failure rather than printed.

        WebKit renders its own error page for a failed main-frame load and
        *then* reports the load finished — so without this the printer prints
        "Unable to load page", writes a perfectly valid PDF, and exits 0. The
        reader's customer gets that page where the invoice should be.

        `True` stops the error page being rendered at all.
        """
        failed.append(f'the page could not be loaded ({uri}): {error}')
        loop.quit()
        return True

    view.connect('load-failed', when_it_will_not_load)
    view.connect('load-changed', when_loaded)
    # From a `file://` URI, which is what GnuCash does — `gnc-html-webkit`
    # writes the report to a temp file and calls `webkit_web_view_load_uri`
    # on it. `load_html` with an `about:blank` base was tried and is subtly
    # different: the page then has an opaque origin, so a `file://` image the
    # report references is dropped without a word. Tax Invoice and Australian
    # Tax Invoice have a *Logo filename* option and emit `<img src="…">` from
    # it, and a printed invoice missing its letterhead is exactly the kind of
    # difference from GnuCash's own page this path exists to close.
    view.load_uri(GLib.filename_to_uri(source))

    def out_of_time():
        failed.append(f'WebKit did not finish printing within '
                      f'{GIVE_UP_AFTER} seconds')
        loop.quit()
        return False

    GLib.timeout_add_seconds(GIVE_UP_AFTER, out_of_time)
    loop.run()
    if failed:
        print(failed[0], file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(_print(sys.argv[1], sys.argv[2], sys.argv[3]))
