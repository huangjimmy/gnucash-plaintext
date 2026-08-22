"""What the child that lays a page out is told about the reader's locale.

Exactly one thing is forced on it: GTK's *message* catalogue. The child asks
GTK for a printer by name, and `Print to File` is a `gtk30` msgid — a French
machine calls it `Imprimer dans un fichier` — while WebKit looks a printer up
by exact name and answers `Printer not found (500)` for one it does not hold.

Everything else is the reader's, `LC_PAPER` above all, because it decides the
sheet and the sheet is meant to be the machine's. That makes `LC_ALL` the
delicate part: glibc resolves every category through it first, so it can
neither be kept (it would carry the translated messages back in) nor simply
dropped (it would take the paper size with it).

Testable here and nowhere else in this suite: a pure `dict → dict`, needing
no locale installed, which matters because the images carry `C`, `C.utf8` and
`POSIX` and nothing else — so no end-to-end test can see any of this.
"""

from infrastructure.pdf.printing import _speaking_english


class TestTheMessagesAreForced:
    def test_the_catalogue_is_c_whatever_the_reader_has(self):
        said = _speaking_english({'LC_MESSAGES': 'fr_FR.UTF-8'})

        assert said['LC_MESSAGES'] == 'C'

    def test_and_a_translation_preference_is_cleared(self):
        """`LANGUAGE` outranks `LC_MESSAGES` in gettext, so leaving it set
        translates the printer's name after all."""
        said = _speaking_english({'LANGUAGE': 'fr:en'})

        assert said['LANGUAGE'] == ''


class TestEverythingElseIsTheReaders:
    def test_the_paper_is_left_alone(self):
        said = _speaking_english({'LC_PAPER': 'en_CA.UTF-8'})

        assert said['LC_PAPER'] == 'en_CA.UTF-8'

    def test_and_so_is_the_rest_of_the_environment(self):
        said = _speaking_english({'PATH': '/usr/bin', 'HOME': '/home/reader'})

        assert said['PATH'] == '/usr/bin'
        assert said['HOME'] == '/home/reader'


class TestWhatLcAllDecided:
    """The category that overrides every other, and is removed here.

    Removing it is unavoidable: `LC_ALL=fr_FR.UTF-8` would translate the
    printer's name whatever `LC_MESSAGES` says. What it was deciding has to
    survive the removal, or the sheet goes with it.
    """

    def test_it_is_gone(self):
        said = _speaking_english({'LC_ALL': 'en_US.UTF-8'})

        assert 'LC_ALL' not in said

    def test_but_the_paper_it_chose_stays(self):
        """A reader whose only locale variable is `LC_ALL` — `docker run -e
        LC_ALL=…`, or a profile exporting it with `LANG` unset — prints US
        Letter from GnuCash. Dropping the variable alone left the child at
        the `C` fallback: `na_letter 612 792` became `iso_a4 595 842`."""
        said = _speaking_english({'LC_ALL': 'en_US.UTF-8'})

        assert said['LC_PAPER'] == 'en_US.UTF-8'

    def test_and_it_wins_over_a_weaker_category(self):
        """`LC_ALL` *overrides* the per-category variables; it is not a
        fallback behind them. GnuCash on this machine prints Letter, so the
        child has to, and keeping the older `LC_PAPER` printed A4."""
        said = _speaking_english({'LC_ALL': 'en_US.UTF-8',
                                  'LC_PAPER': 'en_GB.UTF-8'})

        assert said['LC_PAPER'] == 'en_US.UTF-8'

    def test_except_the_messages_it_chose(self):
        """The one category not carried over, that being the point."""
        said = _speaking_english({'LC_ALL': 'fr_FR.UTF-8'})

        assert said['LC_MESSAGES'] == 'C'
        assert said['LC_PAPER'] == 'fr_FR.UTF-8'
