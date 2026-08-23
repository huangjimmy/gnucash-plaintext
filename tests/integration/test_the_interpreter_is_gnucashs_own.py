"""The Scheme interpreter a render runs in is the one GnuCash is linked to.

GnuCash's report is Scheme, and the modules it loads to draw a page
resolve their `scm_*` symbols against whatever libguile is globally visible. If
that is a *different* libguile from the one GnuCash is built on, they find a
second, unrelated Scheme heap — a crash, or a page that never arrives, with
nothing on it saying why.

Picking one by name cannot tell the difference: `find_library('guile-3.0')`
answers "is a guile-3.0 installed here", and a machine can have both. This is
not hypothetical across the supported builds — GnuCash 3.8 on Ubuntu 20.04 is
linked to guile-2.2 while every other build is on guile-3.0, so a newest-first
search by name is one `apt install guile-3.0` away from being wrong there.

What does answer the right question is GnuCash's own libraries: a linked
library records the soname it needs, and reading it gives what the loader
would give GnuCash. Each supported image carries a single guile, so no run of
this suite can reach the two-guile machine; what it checks is that the choice
comes from GnuCash rather than from a version-ordered guess, which is the part
that would go wrong there.
"""

import ctypes.util

from infrastructure.guile import (
    _candidates,
    gnucash_libguile_soname,
    load_guile,
    mapped_libguile,
)


class TestWhichLibraryIsChosen:
    def test_gnucash_says_which_libguile_it_needs(self):
        soname = gnucash_libguile_soname()

        assert soname, 'no GnuCash library on this build names a libguile'
        assert soname.startswith('libguile-'), soname

    def test_gnucashs_answer_is_tried_first_and_is_not_the_only_one(self):
        """What GnuCash names is a claim about *which* library, never a claim
        that it is installed — the soname is read out of an ELF file, and that
        file says what it was linked against on a machine that has no libguile
        at all. Which is why the candidates are a list that gets tried, rather
        than one name that gets loaded: on Fedora and openSUSE, `gnucash`
        alone does not install guile.
        """
        candidates = list(_candidates())

        assert candidates, 'nothing at all to try'
        assert candidates[0] == gnucash_libguile_soname(), candidates

    def test_the_interpreter_loaded_is_the_one_gnucash_names(self):
        wanted = gnucash_libguile_soname()
        loaded = load_guile()

        # `CDLL._name` is what it was opened with — the soname read off
        # GnuCash's own library, so the Scheme heap the report runs in is the
        # heap GnuCash's modules were built against.
        assert loaded._name == wanted, (loaded._name, wanted)

    def test_the_file_it_resolved_to_is_that_library(self):
        """The loader turns the soname into a file, and it is a matching one —
        `libguile-2.2.so.1` resolving to `libguile-2.2.so.1.4.2` on GnuCash
        3.8, which is the same library under its full version."""
        load_guile()

        mapped = mapped_libguile()
        assert mapped and gnucash_libguile_soname() in mapped, (
            mapped, gnucash_libguile_soname())

    def test_a_search_by_name_is_not_what_decided_it(self):
        """Recorded, not asserted equal: on an image carrying one guile the
        two agree, and the point of reading GnuCash's own library is the image
        that carries two. A failure here would mean the name search found
        something GnuCash does not use — which is exactly what must not decide
        the answer."""
        by_name = next((found for found in
                        (ctypes.util.find_library(name) for name in
                         ('guile-3.0', 'guile-2.2', 'guile-2.0', 'guile'))
                        if found), None)

        assert gnucash_libguile_soname(), by_name
