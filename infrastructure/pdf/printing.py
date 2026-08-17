#!/usr/bin/env python
"""Laying a rendered document out as a PDF, the way GnuCash lays one out.

GnuCash's Print Invoice button hands its report's HTML to WebKit and prints
that, so a page laid out any other way answers a question GnuCash has already
answered. Measured on one page carrying a reader's `Table border width` of 1:
WebKit paints 97 rectangles and WeasyPrint none, the borders coming from the
HTML-4 presentational attributes GnuCash's report writes (`border`,
`cellpadding`, `bgcolor`) which WeasyPrint does not implement. The reader's
printed invoice had no lines round anything.

Here rather than in `services/`, because everything in it is an adapter to
something outside this process: an X server, a child interpreter, the
reader's locale. `services/document_pages.py` keeps the part that is about
documents — taking several rendered pages and making one printable HTML of
them — and `webkit_page.py` beside this is the child that does the printing.
"""
import contextlib
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


class PdfEngineUnavailableError(RuntimeError):
    """Nothing on this machine can lay a rendered page out as a PDF."""


#: The child that does the printing, and where to run it from so `-m` finds
#: the package however this was invoked — an installed console script has any
#: working directory at all.
_CHILD = 'infrastructure.pdf.webkit_page'
_PROJECT = Path(__file__).resolve().parent.parent.parent

#: How long a single document may take to lay out, start to finish — the
#: child, and everything inside the command it is run by: a stale `DISPLAY`,
#: `xvfb-run` waiting on a server. Without it a print run hung with no output
#: and nothing to interrupt but Ctrl-C.
#:
#: Measured on 5.10, under the load of a ten-version sweep: one page takes
#: **0.42–0.60 seconds**, and two hundred documents in one combined print
#: take 2.1. So this is a ceiling for something being wrong rather than a
#: limit any document meets.
GIVE_UP_AFTER = 90

#: And how long *arranging a display* may take, across every attempt rather
#: than each: the server is started before the command above exists, so that
#: timeout does not cover it.
#:
#: Measured on the same run: an `Xvfb` is up and listening in **0.052–0.058
#: seconds**. This is three hundred times that, and what it is really bounding
#: is an `Xvfb` that starts and never opens its socket — a read-only or
#: oddly-mounted `/tmp/.X11-unix` — which otherwise cost the poll and the kill
#: below on each of thirty-one display numbers in turn, minutes of a print run
#: sitting silent.
STOP_LOOKING_FOR_A_DISPLAY_AFTER = 20

#: How long to wait for a server's socket, and for a server that will not
#: serve to die. Five seconds is ~90× the measured startup; the second is a
#: `SIGTERM`ed `Xvfb`, which goes at once.
WAIT_FOR_THE_SOCKET = 5
WAIT_FOR_A_SERVER_TO_DIE = 5

#: What can be printed to a file, mapped to the `output-file-format` GTK
#: takes. PDF and nothing else, on measurement rather than on principle:
#: GnuCash's own print dialog offers PostScript and SVG beside it, and asking
#: GTK's "Print to File" printer for either — same page, same code, `ps` and
#: `svg` in place of `pdf` — ends with the operation reporting *finished* and
#: no file written anywhere. An option that exits 0 and produces nothing is
#: worse than an option that is not offered, so neither is.
PRINTABLE = {'pdf': 'pdf'}

#: Every category `LC_ALL` decides, so that taking `LC_ALL` away leaves each
#: of them saying what it said. `LC_PAPER` is the one that matters here — it
#: decides the sheet — and the rest are listed because `LC_ALL` decided them
#: too and dropping any is the same kind of mistake. `LC_MESSAGES` is absent
#: on purpose: forcing it is the whole reason any of this happens.
_WHAT_LC_ALL_DECIDES = ('LC_PAPER', 'LC_CTYPE', 'LC_TIME', 'LC_NUMERIC',
                        'LC_MONETARY', 'LC_COLLATE', 'LC_MEASUREMENT',
                        'LC_ADDRESS', 'LC_NAME', 'LC_TELEPHONE',
                        'LC_IDENTIFICATION')


def _speaking_english(reader: dict) -> dict:
    """The reader's environment with GTK's *messages* forced to English.

    The child asks GTK for a printer **by name**, and that name is
    translated: `Print to File` is a `gtk30` msgid, so a French machine calls
    it `Imprimer dans un fichier` and WebKit — which looks a printer up by
    exact name and does not fall back — answers `Printer not found (500)`.

    Nothing else is neutralised, `LC_PAPER` least of all: the sheet is the
    machine's, which is the whole point of naming no paper size. That takes
    care with `LC_ALL`, because glibc resolves every category through it
    first — so a reader whose only locale variable is `LC_ALL=en_US.UTF-8`
    (`docker run -e LC_ALL=…`, or a profile that exports it with `LANG`
    unset) loses US Letter to the `C` fallback if it is simply removed.
    Measured: `na_letter 612 792` becomes `iso_a4 595 842`, which is the
    mismatch this whole path exists to remove, reintroduced by the fix for a
    different one. So what `LC_ALL` was deciding is written into each
    category before it goes.
    """
    speaking = dict(reader)
    whole = speaking.pop('LC_ALL', None)
    if whole:
        # Written over each category rather than filled in behind it:
        # `LC_ALL` *overrides* the lot in glibc, it is not a fallback for
        # them. A reader with `LC_ALL=en_US.UTF-8` beside an older
        # `LC_PAPER=en_GB.UTF-8` prints Letter from GnuCash, and keeping the
        # weaker value here would have printed A4 — the same mismatch, in the
        # one case where the two disagree.
        for category in _WHAT_LC_ALL_DECIDES:
            speaking[category] = whole
    speaking['LC_MESSAGES'] = 'C'
    speaking['LANGUAGE'] = ''
    return speaking


def _ran(command: list, env: dict):
    """The child, bounded by `GIVE_UP_AFTER` and answered for in a sentence.

    In a session of its own, so a timeout can take down what the child
    started as well as the child: killing `xvfb-run` alone leaves the `Xvfb`
    and the Python it spawned running after the command has gone.
    """
    import signal

    started = subprocess.Popen(command, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True,
                               cwd=str(_PROJECT), env=env,
                               start_new_session=True)
    try:
        out, err = started.communicate(timeout=GIVE_UP_AFTER)
    except subprocess.TimeoutExpired:  # pragma: no cover - see below
        # Ninety seconds against a measured 0.42–0.60 per page, so nothing a
        # test can wait for. Reached by a display that answers and never
        # draws, which is a machine's state rather than a book's.
        with contextlib.suppress(ProcessLookupError):
            os.killpg(os.getpgid(started.pid), signal.SIGKILL)
        # Suppressed: a child that will not die even on SIGKILL must not
        # replace the sentence about the timeout with a second timeout.
        with contextlib.suppress(subprocess.TimeoutExpired):
            started.wait(timeout=WAIT_FOR_A_SERVER_TO_DIE)
        raise PdfEngineUnavailableError(
            f'laying the document out did not finish within '
            f'{GIVE_UP_AFTER} seconds, so the print was given up on. WebKit '
            f'needs a display, and a display that never comes up — a stale '
            f'DISPLAY naming a server that is gone, an X server that will '
            f'not start — is what takes this long') from None
    return subprocess.CompletedProcess(command, started.returncode, out, err)


@contextlib.contextmanager
def a_display():
    """An environment WebKit can draw into, for as long as the block runs.

    Three states, in the order they are taken:

    * `DISPLAY` already set — a desktop, or a caller who arranged one. Used
      as it stands and nothing is started;
    * `Xvfb` present — one server is started here, on a display number
      nothing else holds, and killed on the way out. **This is the ordinary
      path**, ahead of the wrapper, because it is the one that can be shared:
      a server started here lasts as long as the block, so `-o out/` over
      fifty documents starts one. `xvfb-run` cannot be shared that way — it
      wraps a *command*, so fifty documents are fifty servers;
    * `xvfb-run` without `Xvfb` — kept as a fallback for a machine that has
      the wrapper and hides the server behind it, which none of the ten
      supported images is.

    None of the three, and the sentence names the package to install rather
    than letting a `FileNotFoundError` out.
    """
    import tempfile

    if os.environ.get('DISPLAY'):
        yield [], None                      # the caller's own display
        return

    # Both arms below are unreachable on every supported image, each of which
    # installs `Xvfb` by name — kept because a reader's machine is not an
    # image, and a missing X server is the likeliest thing to be missing.
    if not shutil.which('Xvfb'):  # pragma: no cover - every image has it
        if shutil.which('xvfb-run'):
            # `-a` is the wrapper picking a free display number itself, and
            # the wrapper owns the server's lifetime — which is why this is a
            # command prefix rather than an environment, and why it cannot be
            # shared across documents.
            yield ['xvfb-run', '-a'], None
            return

        raise PdfEngineUnavailableError(
            'a printed document is laid out by WebKit, the engine GnuCash '
            'itself prints with, and WebKit needs a display: install Xvfb '
            'and xauth (`apt install xvfb xauth`, `dnf install '
            'xorg-x11-server-Xvfb xorg-x11-xauth`, `zypper install '
            'xorg-x11-server-Xvfb xauth`, `pacman -S xorg-server-xvfb '
            'xorg-xauth`) or run where DISPLAY is set. The second of each '
            'pair is what keeps that display to this process rather than any '
            'local one, an invoice being what is drawn on it. `--format '
            'html` needs neither.')

    # With an authority file where there is an `xauth` to make one. A display
    # started without it takes a connection from any local user, and what is
    # on the screen is somebody's invoice — a customer's name, address and
    # what they owe. `xvfb-run` mints a cookie for exactly this reason, and
    # this branch exists because openSUSE ships the server without the
    # wrapper.
    #
    # `xvfb-run` has no unauthenticated mode to copy — read on 5.10, it
    # refuses outright with "xauth command not found" — so a machine without
    # `xauth` could not print at all if this did the same. It prints, on a
    # display that is at least local-only (`-nolisten tcp`), because refusing
    # an invoice over a missing helper is the worse answer. Every supported
    # image carries `xauth`, named in each Dockerfile, so the cookie is what
    # the suite exercises.
    cookies = tempfile.mkdtemp(prefix='gnucash-xauth-')
    authority = Path(cookies) / 'Xauthority'

    def started_on(number: int):
        """An `Xvfb` holding `number`, or `None` if something else has it.

        Tried rather than asked about: the lock file says which numbers were
        taken a moment ago, and two `print-invoice` runs starting together
        both read the same answer and both pick it. `xvfb-run -a` retries the
        next number for the same reason, and so does the caller below.
        """
        guarded = []
        # The `else` — a display with no cookie — is unreachable on every
        # supported image since openSUSE gained `xauth`; see the note above
        # for why it still prints rather than refusing.
        if shutil.which('xauth'):  # pragma: no branch - every image has it
            authority.touch(mode=0o600)
            # Through `source -` on stdin, never `add <cookie>` on the
            # command line: an argument is in `/proc/<pid>/cmdline`, which is
            # world-readable, so a local user polling it takes the cookie and
            # opens the display — for as long as a run holds it, which over
            # `-o out/` and fifty invoices is tens of seconds. That is the
            # exposure this whole block exists to close, handed back through
            # the mechanism meant to close it. `xvfb-run` feeds `xauth` on
            # stdin for the same reason.
            cookie = os.urandom(16).hex()
            made = subprocess.run(
                ['xauth', '-f', str(authority), 'source', '-'],
                input=f'add :{number} MIT-MAGIC-COOKIE-1 {cookie}\n',
                capture_output=True, text=True)
            if made.returncode == 0:
                guarded = ['-auth', str(authority)]
        candidate = subprocess.Popen(
            ['Xvfb', f':{number}', '-screen', '0', '1024x768x24',
             '-nolisten', 'tcp', *guarded],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # The socket appearing is the server being ready; polled rather than
        # slept on, so a fast machine waits milliseconds and a loaded one
        # still gets its server.
        socket = Path(f'/tmp/.X11-unix/X{number}')
        for _ in range(int(WAIT_FOR_THE_SOCKET / 0.05)):
            if socket.exists() or candidate.poll() is not None:
                break
            time.sleep(0.05)
        # An `Xvfb` that will not start, on an image where it always does.
        # The process is asked about before the socket, so a candidate that
        # lost the race for a number is rejected rather than adopting the
        # winner's socket.
        if (candidate.poll() is not None      # pragma: no cover - see above
                or not socket.exists()):
            # A server whose socket never appeared is not a server, whatever
            # its process is doing. Returned as good, it cost every run the
            # poll above and then drew against a display nothing was
            # listening on — surfacing as WebKit's own error rather than the
            # sentence written for having no display at all.
            candidate.terminate()
            with contextlib.suppress(subprocess.TimeoutExpired):
                candidate.wait(timeout=WAIT_FOR_A_SERVER_TO_DIE)
            return None, []
        return candidate, guarded

    server = guarded = None
    try:
        tried = 0
        give_up_at = time.monotonic() + STOP_LOOKING_FOR_A_DISPLAY_AFTER
        for number in range(99, 130):
            if Path(f'/tmp/.X{number}-lock').exists():
                continue
            if time.monotonic() > give_up_at:
                break
            tried += 1
            server, guarded = started_on(number)
            if server is not None:
                break
        # Reached only where no server starts at all, which no image does.
        if server is None:  # pragma: no cover - see the arm above
            # Which of the two it was, because they send a reader to
            # different places: a server that will not start is Xvfb's
            # business, and every number being held is thirty-one lock files,
            # usually stale ones nothing is listening behind.
            raise PdfEngineUnavailableError(
                f'no X server would start on any of the {tried} display '
                f'numbers tried between :99 and :129 within '
                f'{STOP_LOOKING_FOR_A_DISPLAY_AFTER} seconds, so WebKit has '
                f'nowhere to draw the document' if tried else
                'every display number from :99 to :129 is held by a lock '
                'file in /tmp, so there is none left to start an X server '
                'on for WebKit to draw into')
    except BaseException:
        # The cookies go with the attempt. Left behind, a machine where Xvfb
        # cannot start at all — no `/tmp/.X11-unix`, no shm, a locked-down
        # container — grew a `/tmp/gnucash-xauth-*` per print, each holding
        # up to thirty-one magic cookies, while the reader was told nothing
        # had been made.
        shutil.rmtree(cookies, ignore_errors=True)
        raise
    try:
        env = {**os.environ, 'DISPLAY': f':{number}'}
        if guarded:
            env['XAUTHORITY'] = str(authority)
        yield [], env
    finally:
        server.terminate()
        # Suppressed, and last: whatever the body raised is the answer to
        # give the reader, and a server that will not die must not replace it
        # — nor leave the cookie behind.
        with contextlib.suppress(subprocess.TimeoutExpired):
            server.wait(timeout=WAIT_FOR_A_SERVER_TO_DIE)
        shutil.rmtree(cookies, ignore_errors=True)


def laid_out_by_webkit(html: str, fmt: str = 'pdf', on=None) -> bytes:
    """`html` as `fmt`, printed the way GnuCash prints, as bytes.

    Bytes rather than a file, because both print commands lay every document
    out before they touch the destination — a run that cannot lay one out
    must leave no half-written directory behind, which is the rule
    `_write_per_invoice` and `_write_combined` already follow for rendering.

    In a child process, because WebKit wants a GTK main loop and the caller
    holds an open book and an initialised Guile — and because it wants a
    display, which a machine printing from a script has not got. See
    `a_display` for the three ways one is arranged.

    `on` is a display already arranged by the caller, so a run printing fifty
    documents starts one X server rather than fifty. Left out, one is
    arranged for this document alone.
    """
    import tempfile

    with tempfile.TemporaryDirectory(prefix='gnucash-print-') as work:
        page = Path(work) / 'page.html'
        page.write_text(html, encoding='utf-8')
        printed = Path(work) / f'page.{PRINTABLE[fmt]}'
        run = [sys.executable, '-m', _CHILD, str(page), str(printed),
               PRINTABLE[fmt]]
        with (contextlib.nullcontext(on) if on else a_display()) \
                as (prefix, env):
            done = _ran([*prefix, *run],
                        env=_speaking_english(env or os.environ))
        # Asked what is *in* the file, not whether there is one. GTK's file
        # backend opens the output before it spools into it, and a print
        # operation reporting `finished` while writing nothing is measured
        # behaviour, not a hypothetical — it is why PostScript and SVG are
        # not offered. Taking the file's existence for an answer wrote a
        # zero-byte PDF over the reader's destination and said
        # `✓ Wrote 1 invoice(s)`.
        #
        # `%PDF-` and not a magic per format, because `PRINTABLE` has one
        # entry and the measurement above is why: a second format would need
        # its own bytes here, and would be rejected as "wrote no document"
        # until it got them.
        laid_out = printed.read_bytes() if printed.exists() else b''
        if done.returncode == 0 and laid_out.startswith(b'%PDF-'):
            return laid_out

    if done.returncode != 0:
        # Named as what it is. The likeliest cause by far is the bindings
        # being absent — `import gi` fails on a machine that has WebKit's
        # library (GnuCash pulls it in) and none of its typelib.
        #
        # Every line of what the child said, not the last: a GTK teardown
        # warning printed after the real message would otherwise be the whole
        # of what a reader is told.
        raise PdfEngineUnavailableError(
            'WebKit could not lay the document out: '
            + (done.stderr.strip() or 'no reason given')
            + '. A printed document is laid out by WebKit, the engine GnuCash '
              'itself prints with. A DISPLAY naming a server that is gone '
              'fails here too, the bindings checking it as they are imported '
              '— otherwise what is missing is the bindings themselves: '
              '`apt install python3-gi '
              'gir1.2-webkit2-4.1`, `dnf install python3-gobject '
              'webkit2gtk4.1`, `zypper install python3-gobject '
              'typelib-1_0-WebKit2-4_1`, `pacman -S python-gobject '
              'webkit2gtk-4.1`. `--format html` needs none of it.')
    # Exit 0 and nothing that reads as a PDF. No supported build does this
    # for a PDF — it is what asking GTK for PostScript or SVG does, which is
    # why neither is offered — but a printed run that returned an empty
    # document rather than a sentence would be the worst answer available.
    raise PdfEngineUnavailableError(  # pragma: no cover - see above
        f'WebKit reported success and wrote no document — '
        f'{len(laid_out)} bytes, and not a PDF — so there is nothing to '
        f'print')
