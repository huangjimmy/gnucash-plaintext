"""The errors a command ends with that are refusals, printed as `Error: <sentence>`.

Each is raised below the CLI, where Click is not known, and says in a sentence
why the command could not go on: a book that cannot be opened, a page GnuCash
could not draw, no Guile, no PDF engine. The group (`cli/main.py`) prints one
as Click prints its own refusals, and `batch` (`cli/batch_cmd.py`) does the
same for each command it runs, so the two read this one list.
"""

from infrastructure.guile import GuileUnavailableError
from infrastructure.pdf.printing import PdfEngineUnavailableError
from repositories.gnucash_repository import BookUnavailableError
from services.gnucash_report import PageNotRenderedError

REFUSED_IN_A_SENTENCE = (BookUnavailableError, PageNotRenderedError,
                         GuileUnavailableError, PdfEngineUnavailableError)
