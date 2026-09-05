"""WeasyPrint has to be loaded before GnuCash, or Debian 10 segfaults.

WeasyPrint draws through `cairocffi`, which opens its own copy of libcairo and
makes a surface while it is being imported. GnuCash's bindings pull in GTK,
which has already opened libcairo by then. On Debian 10 the two do not agree
and the process dies — not an exception, a SIGSEGV inside
`cairocffi/surfaces.py`, with no Python frame able to catch it.

Measured on Debian 10 (GnuCash 3.4, Python 3.7, WeasyPrint 52.5), one process
each way:

    import gnucash; import weasyprint     -> Segmentation fault
    import weasyprint; import gnucash     -> fine

What it cost before this existed: `income-statement --pdf` killed the
interpreter, and under pytest a segfault is not a failing test — it ends the
run, so the whole suite reported nothing rather than one red test.

Only Python 3.7 is pre-loaded, because Debian 10 is the only supported build
with that pair and the import is not free — WeasyPrint takes a noticeable
moment, which every command would otherwise pay for a hazard it does not have.
A missing WeasyPrint is not an error here: it is an optional extra, and a
command that needs it says so itself when it is asked for.
"""

import sys


def load_the_page_engine_first() -> bool:
    """Import WeasyPrint now, where importing it later would be too late.

    Returns True when it was loaded, False when there was nothing to load or
    this build does not need the ordering.
    """
    if sys.version_info >= (3, 8):
        return False
    try:
        import weasyprint  # noqa: F401
    except Exception:
        return False
    return True
