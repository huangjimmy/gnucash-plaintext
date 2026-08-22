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

So the soname is read off GnuCash's own libraries, which name what they are
linked to, and the loader resolves it exactly as it would for GnuCash itself.
That is the rule `engine.py` follows when it promotes GnuCash's `.so` by path
rather than trusting the loader to pick a library called "the engine".

**`argtypes` matters here as much as anywhere.** `scm_c_eval_string` takes a
pointer; called without a declaration, ctypes passes a Python `int` as a C
`int` and a 64-bit pointer loses its top half — the same truncation
`engine.py` documents, with the same segfault.
"""
import ctypes
import ctypes.util
import re
from pathlib import Path

# Last resort, when GnuCash's libraries name none and none is mapped: newest
# first, and the names differ by distribution — Fedora ships `guile3.0` with
# no unversioned symlink at all.
_CANDIDATES = ('guile-3.0', 'guile-2.2', 'guile-2.0', 'guile')

# A libguile already open in this process, from `/proc/self/maps`.
_MAPPED = re.compile(r'\s(/\S*/libguile[^\s/]*\.so[^\s/]*)$')

# The soname as a library records what it is linked to, e.g.
# `libguile-2.2.so.1`. Read from the file's bytes rather than through an ELF
# parser: it is a plain string in `.dynstr`, and nothing here needs to know
# the format to find it.
_NEEDED = re.compile(rb'libguile-[0-9.]+\.so\.[0-9]+')

_loaded = None


class GuileUnavailableError(RuntimeError):
    """No libguile in this process or on this machine, so GnuCash's report
    cannot be run."""


def mapped_libguile():
    """The libguile this process already has open, or None.

    Read from `/proc/self/maps`. A fallback, and second in line: it answers
    None before the first render — importing the GnuCash bindings maps no
    libguile, measured — and afterwards it names whatever was loaded, which is
    this module's own choice. So it is the answer only where GnuCash's
    libraries name none, and otherwise it is how a test can see that the
    soname resolved to a real file.
    """
    try:
        maps = Path('/proc/self/maps').read_text()
    except OSError:
        return None
    for line in maps.splitlines():
        found = _MAPPED.search(line)
        if found:
            return found.group(1)
    return None


def gnucash_libguile_soname():
    """What GnuCash's own libraries say they are linked to, or None.

    Every build has some `libgnc*` that names its libguile — on GnuCash 3.8
    it is `libgncmod-app-utils.so` and on 5.x `libgnc-app-utils.so`, among
    others — so the directories the engine is found in are read until one
    does. Returning a soname rather than a path lets the dynamic loader
    resolve it the way it resolves it for GnuCash.
    """
    from infrastructure.gnucash.engine import ENGINE_LIB_PATHS

    seen = set()
    for engine in ENGINE_LIB_PATHS:
        for directory in (Path(engine).parent, Path(engine).parent.parent):
            if directory in seen or not directory.is_dir():
                continue
            seen.add(directory)
            for path in sorted(directory.glob('libgnc*.so*')):
                try:
                    found = _NEEDED.search(path.read_bytes())
                except OSError:
                    continue
                if found:
                    return found.group().decode()
    return None


def _candidates():
    """Every libguile worth trying, best answer first.

    GnuCash's own soname first, then anything already mapped, then a search by
    name. Each is a *claim* about which library to use and none of them is a
    claim that it is installed: the soname is read out of GnuCash's ELF, which
    names what it was linked against whether or not that library is on the
    machine — the exact state Fedora and openSUSE ship, and the reason both
    Dockerfiles install `guile` explicitly. So they are tried in turn, and only
    a name that actually loads is the answer.
    """
    for candidate in (gnucash_libguile_soname(), mapped_libguile()):
        if candidate:
            yield candidate
    for name in _CANDIDATES:
        found = ctypes.util.find_library(name)
        if found:
            yield found


def load_guile():
    """The interpreter, initialised, with its signatures declared.

    Cached: `scm_init_guile` is idempotent per thread, but the handle is
    process-wide and a second `CDLL` would give a second set of signatures.
    """
    global _loaded
    if _loaded is not None:
        return _loaded

    lib = None
    tried = []
    for candidate in _candidates():
        tried.append(candidate)
        try:
            # RTLD_GLOBAL for the reason engine.py promotes GnuCash's engine:
            # the Scheme modules GnuCash dlopens resolve their `scm_*` against
            # whatever is globally visible, and a locally-loaded copy leaves
            # them to find another.
            lib = ctypes.CDLL(candidate, mode=ctypes.RTLD_GLOBAL)
            break
        except OSError:
            continue

    if lib is None:  # pragma: no cover - every supported image ships guile
        raise GuileUnavailableError(
            'libguile could not be loaded, so GnuCash\'s own invoice report '
            'cannot be run and a page cannot be rendered. '
            + (f'GnuCash is linked against {tried[0]} and it is not installed'
               if tried else 'Nothing on this machine names one')
            + '. Install guile — `dnf install guile` on Fedora, '
              '`zypper install guile` on openSUSE; most other distributions '
              'install it with GnuCash itself.')

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
