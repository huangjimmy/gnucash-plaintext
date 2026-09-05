"""The CLI package.

The one thing here is an import order. Every command below reaches GnuCash's
bindings, and on Debian 10 loading WeasyPrint after them kills the process —
`infrastructure/pdf/cairo_before_gnucash.py` has the measurement. This runs
before any `cli.*` module does, because importing one imports this first, and
that is the only place the ordering can be stated once: written in `main.py`
it would sit among the imports, where the formatter sorts `infrastructure`
after `cli` and puts it back too late.
"""

from infrastructure.pdf.cairo_before_gnucash import load_the_page_engine_first

load_the_page_engine_first()
