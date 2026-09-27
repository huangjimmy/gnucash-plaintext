#!/usr/bin/env python
"""The Scheme interpreter, loaded once and declared once.

Rendering a page asks GnuCash's own report to draw it, and that report is
Scheme — so a Guile interpreter has to exist in this process. This module owns
loading libguile and declaring its signatures, for the same reason
`infrastructure/gnucash/engine.py` owns GnuCash's: a second `CDLL` elsewhere is
a second instance and a second set of signatures, and which one a caller gets
is then decided by import order.

**It must be this process.** GnuCash's report reads the book through the same
C library the Python bindings opened it with, and reaches it through globals —
`gnc_get_current_session`. A Guile in another process shares neither, and no
version exposes `qof-session-begin` to Scheme, so a separate interpreter
cannot open a book of its own either.

**And it must be GnuCash's libguile, not merely a libguile.** The one this
process needs is whichever runtime GnuCash is linked against: initialising a
different one leaves the modules `(use-modules (gnucash engine))` loads
resolving their `scm_*` against a second, unrelated Scheme heap, which is a
crash or an unreadable failure rather than a rendered page.

Asking `find_library('guile-3.0')` answers "is a guile-3.0 installed here",
which is a different question, and the two answers differ on a machine holding
both. Measured across the supported images: GnuCash 3.8 on Ubuntu 20.04 is
built on **guile-2.2**, every other build on guile-3.0 — and guile-3.0
co-installs beside 2.2 happily, so on that build a newest-first search by name
is one `apt install guile-3.0` away from initialising the wrong runtime.

So the soname is read off GnuCash's own libraries, which record what they are
linked to, and the loader resolves it exactly as it would for GnuCash itself.
That is the only library tried. A soname that does not load means guile is not
installed — the state Fedora and openSUSE ship `gnucash` in, and the reason both
Dockerfiles install `guile` — and the answer then is to say so, not to
initialise whichever libguile a search by name happens to find.

That is the rule `engine.py` follows when it promotes GnuCash's `.so` by path
rather than trusting the loader to pick a library called "the engine".

**`argtypes` matters here as much as anywhere.** `scm_c_eval_string` takes a
pointer; called without a declaration, ctypes passes a Python `int` as a C
`int` and a 64-bit pointer loses its top half — the same truncation
`engine.py` documents, with the same segfault.
"""
import ctypes
import re
from pathlib import Path

# A libguile already open in this process, from `/proc/self/maps`.
_MAPPED = re.compile(r'\s(/\S*/libguile[^\s/]*\.so[^\s/]*)$')

# The soname as a library records what it is linked to, e.g.
# `libguile-2.2.so.1`. Read from the file's bytes rather than through an ELF
# parser: it is a plain string in `.dynstr`, and nothing here needs to know
# the format to find it.
_NEEDED = re.compile(rb'libguile-[0-9.]+\.so\.[0-9]+')

# The same fact in a Mach-O, where what a library records is the full install
# path of what it is linked to — `/opt/local/lib/libguile-3.0.1.dylib` — and
# that path is what the loader resolves for GnuCash itself, macOS having no
# search prefix for MacPorts or Homebrew. The path is therefore kept whole:
# handed the trailing `libguile-3.0.1.dylib` alone, dlopen looks in `/usr/lib`
# and the dyld cache and finds nothing. Measured on MacPorts GnuCash 5.14,
# where the library in the engine's own directory that records a libguile is
# `libgnc-expressions-guile.dylib`.
#
# A NUL ends the path as surely as whitespace does, and is spelled out because
# `\S` does not cover it: in a binary the match would otherwise be free to
# start at a `/` in unrelated data and come back as a path with NULs through
# it, which dlopen refuses. That it does not happen today rests on the
# `0x0c` in front of each load command counting as whitespace, which is no
# rule at all.
_NEEDED_MACHO = re.compile(rb'/[^\x00\s]*/libguile-[0-9.]+\.dylib')

_loaded = None


class GuileUnavailableError(RuntimeError):
    """No libguile in this process or on this machine, so GnuCash's report
    cannot be run."""


def mapped_libguile():
    """The libguile this process has open, or None.

    Read from `/proc/self/maps`. It answers None before the first render —
    importing the GnuCash bindings maps no libguile, measured — and afterwards
    reports the file the soname below resolved to, which is how a test sees that
    the library loaded is the one GnuCash is linked against.

    macOS has no `/proc`, and dyld answers the same question directly:
    `_dyld_get_image_name` is the path each image in the process was loaded
    from. Measured on MacPorts GnuCash 5.14 — before `load_guile` the list
    holds no libguile, afterwards `/opt/local/lib/libguile-3.0.1.dylib`.
    """
    maps = Path('/proc/self/maps')
    if not maps.exists():
        return _the_libguile_dyld_lists()
    lines = maps.read_text().splitlines()
    return next((found.group(1) for found in map(_MAPPED.search, lines) if found), None)


def _the_libguile_dyld_lists():
    """The libguile among the images dyld says this process has loaded, or None.

    libSystem's calls, not libguile's, so declared here rather than in
    `load_guile`: the handle is the process's own image list and carries no
    Scheme symbols. `argtypes` for the same reason as everywhere else — the
    index is a C `uint32_t` and the return is a pointer to be read as a string,
    neither of which ctypes guesses.

    On a mac this answers what `/proc/self/maps` answers on Linux, and it was
    measured there: before `load_guile` the list holds no libguile, afterwards
    `/opt/local/lib/libguile-3.0.1.dylib`. `_dyld_image_count` is not a symbol
    on Linux, so what a container can check is this function's own reading of
    the list, which
    `tests/unit/infrastructure/test_which_libguile_each_platform_records.py`
    does with the list supplied.
    """
    dyld = ctypes.CDLL(None)
    dyld._dyld_image_count.restype = ctypes.c_uint32
    dyld._dyld_image_count.argtypes = []
    dyld._dyld_get_image_name.restype = ctypes.c_char_p
    dyld._dyld_get_image_name.argtypes = [ctypes.c_uint32]
    images = (dyld._dyld_get_image_name(index) for index in range(dyld._dyld_image_count()))
    return next((image.decode() for image in images if image and b'libguile' in image), None)


def gnucash_libguile_soname():
    """The libguile soname GnuCash's own libraries record they are linked to.

    Every build has some `libgnc*` that records its libguile — on GnuCash 3.8
    it is `libgncmod-app-utils.so` and on 5.x `libgnc-app-utils.so`, among
    others — so the directories the engine is found in are read until one
    does. Returning a soname rather than a path lets the dynamic loader
    resolve it the way it resolves it for GnuCash. On macOS, where a Mach-O
    records the full install path instead, that path is what comes back, and
    it is what the loader resolves for GnuCash there.

    Raises `StopIteration` where no library records one, which no supported
    image is.
    """
    from infrastructure.gnucash.engine import ENGINE_LIB_PATHS

    directories = []
    for engine in ENGINE_LIB_PATHS:
        for directory in (Path(engine).parent, Path(engine).parent.parent):
            if directory not in directories and directory.is_dir():
                directories.append(directory)
    return next(found.group().decode()
                for directory in directories
                for path in sorted(directory.glob('libgnc*.so*')) + sorted(directory.glob('libgnc*.dylib'))
                for recorded in [path.read_bytes()]
                for pattern in (_NEEDED, _NEEDED_MACHO)
                for found in [pattern.search(recorded)]
                if found)


def load_guile():
    """The interpreter, initialised, with its signatures declared.

    Cached: `scm_init_guile` is idempotent per thread, but the handle is
    process-wide and a second `CDLL` would create a second set of signatures.
    """
    global _loaded
    if _loaded is not None:
        return _loaded

    try:
        # RTLD_GLOBAL for the reason engine.py promotes GnuCash's engine: the
        # Scheme modules GnuCash dlopens resolve their `scm_*` against
        # whatever is globally visible, and a locally-loaded copy leaves them
        # to find another.
        lib = ctypes.CDLL(gnucash_libguile_soname(), mode=ctypes.RTLD_GLOBAL)
    except (OSError, StopIteration) as missing:  # pragma: no cover - every supported image ships guile
        raise GuileUnavailableError(
            'libguile could not be loaded, so GnuCash\'s own invoice report '
            'cannot be run and a page cannot be rendered '
            # `str()` and not the exception itself: an exception instance is
            # always truthy, so `missing or …` never reached the fallback —
            # and the arm the fallback was written for is the one that raises
            # `StopIteration`, whose `str()` is empty. That printed `(). `.
            f'({str(missing) or "no GnuCash library records a libguile"}). '
            'Install guile — `dnf install guile` on Fedora, '
            '`zypper install guile` on openSUSE; most other distributions '
            'install it with GnuCash itself.') from missing

    # `scm_init_guile` returns void and takes nothing, and both are declared
    # rather than left to ctypes' default of `c_int`: an undeclared return type
    # reads whatever the return register happened to hold, which is a number
    # that means nothing and would be believed by anything that looked at it.
    lib.scm_init_guile.restype = None
    lib.scm_init_guile.argtypes = []
    lib.scm_init_guile()
    lib.scm_c_eval_string.restype = ctypes.c_void_p
    lib.scm_c_eval_string.argtypes = [ctypes.c_char_p]
    # The expression is built as UTF-8 and handed over as UTF-8, in two calls
    # rather than one. `scm_c_eval_string` decodes its argument with the
    # *locale's* charset, so the bytes of a `--report` name or a `--report-file`
    # path arrive as whatever the locale makes of them: measured under
    # `LC_ALL=C PYTHONCOERCECLOCALE=0` on 5.10 and 3.8, `Facture améliorée`
    # went in as 17 characters and came out as 19 — each UTF-8 byte read as
    # its own character. Nothing raises; the expression evaluates, against a
    # string nobody typed. `scm_from_utf8_string` says what the bytes are, and
    # `scm_eval_string` takes the string rather than the bytes.
    lib.scm_from_utf8_string.restype = ctypes.c_void_p
    lib.scm_from_utf8_string.argtypes = [ctypes.c_char_p]
    lib.scm_eval_string.restype = ctypes.c_void_p
    lib.scm_eval_string.argtypes = [ctypes.c_void_p]
    _loaded = lib
    return lib
