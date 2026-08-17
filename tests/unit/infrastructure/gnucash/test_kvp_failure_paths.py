"""What the KVP layer does when the C side is not there to answer.

Every slot this tool writes goes through `qof_instance_set_kvp` in ctypes, and
every read through `qof_instance_get_kvp` — on all ten supported builds, not
as a fallback for one of them. The handlers around those calls decide what
happens when the library is missing, and none of them had ever run (T-009).

These are the paths with **no scenario in the product**: no file, no command
and no book state reaches them, because they describe an installation that is
broken — `libgobject-2.0` absent, or the engine library not loadable — and the
suite necessarily runs on installations that work. That is why the failure is
injected here, at the loader boundary, and only here. Everything else this
module does when it meets something it cannot read is reached the ordinary
way, through a real command over a real book, in
`tests/integration/test_metadata_written_by_another_tool.py`.

Kept rather than deleted, unlike the SWIG paths this file's subject used to
carry: those could not run on a *working* install either, which made them
dead. These run on a broken one, and what they do there — report and carry on,
rather than abort an import half-way through a book — is a decision worth
holding to.
"""

import pytest

from infrastructure.gnucash import kvp


class _NoInstance:
    """An object whose `.instance` cannot be turned into a pointer.

    The shape a caller reaches this with is a wrapper the bindings did not
    build — the accessors take "a Transaction or a Split" and nothing checks.
    """

    @property
    def instance(self):
        raise RuntimeError('no instance behind this object')


class TestWithoutLibgobject:
    """`libgobject-2.0` is what builds the GValue both calls hand to GnuCash."""

    def test_setting_reports_failure_rather_than_raising(self, monkeypatch):
        monkeypatch.setattr(kvp, '_load_gobject', lambda: None)

        assert kvp._set_via_qof_instance(1, 'slot', 'value') is False

    def test_reading_answers_nothing_rather_than_raising(self, monkeypatch):
        monkeypatch.setattr(kvp, '_load_gobject', lambda: None)

        assert kvp._get_via_qof_instance(1, 'slot') is None


class TestWhenTheEngineCallFails:
    """Anything the C side raises is a slot that was not written, not a crash."""

    def _engine_that_will_not_load(self):
        def _raise():
            raise OSError('libgncmod-engine is not loadable here')
        return _raise

    def test_setting_reports_failure(self, monkeypatch):
        monkeypatch.setattr(kvp, '_load_gnc_engine', self._engine_that_will_not_load())

        assert kvp._set_via_qof_instance(1, 'slot', 'value') is False

    def test_reading_answers_nothing(self, monkeypatch):
        monkeypatch.setattr(kvp, '_load_gnc_engine', self._engine_that_will_not_load())

        assert kvp._get_via_qof_instance(1, 'slot') is None


class _PointerWithoutABook:
    """A pointer no C call may be handed — 1 is not an address.

    Every test using this relies on the guard under test returning *before*
    the pointer reaches ctypes: measured, `_set_via_qof_instance(1, …)` with
    nothing patched does not return False, it segfaults the interpreter. That
    is what makes these tests prove something — they pass only while the
    check short-circuits — and it is also the trap in them. Move a C call
    above the guard and this suite stops failing and starts crashing.
    """

    instance = 1


class TestWritingASlotWithoutLibgobject:
    """The write reports failure rather than claiming a slot it did not set."""

    def test_the_slot_setter_answers_false(self, monkeypatch):
        monkeypatch.setattr(kvp, '_load_gobject', lambda: None)

        assert kvp._set_string_slot(_PointerWithoutABook(), 'slot', 'v') is False


class TestBookOptionsWithoutAPointer:
    def test_setting_reports_failure(self):
        assert kvp.set_book_string_option(_NoInstance(), 'sec', 'name', 'v') is False

    def test_and_the_raising_form_says_what_went_wrong(self):
        """Two contracts over one body: a bulk write takes the bool and
        carries on, while `set-invoice-style` — one command, one write —
        needs the reason, which the bool has already thrown away."""
        with pytest.raises(Exception) as refused:
            kvp.write_book_string_option(_NoInstance(), 'sec', 'name', 'v')

        assert 'instance' in str(refused.value)

    def test_reading_answers_nothing(self):
        assert kvp.get_book_string_option(_NoInstance(), 'sec', 'name') is None


class TestAnObjectWithNoPointer:
    def test_setting_a_slot_reports_failure(self):
        assert kvp._set_string_slot(_NoInstance(), 'slot', 'value') is False

    def test_reading_a_slot_answers_nothing(self):
        assert kvp._get_string_slot(_NoInstance(), 'slot') is None

    def test_storing_metadata_is_logged_rather_than_raised(self, caplog):
        """`set_custom_metadata` returns nothing, so the log is the report.

        An import part-way through a book would otherwise abort on a slot it
        could not write, and the transaction it was writing is already in the
        book by then.
        """
        with caplog.at_level('ERROR'):
            assert kvp.set_custom_metadata(_NoInstance(), {'a': 'b'}) is None

    def test_a_value_that_will_not_serialise_is_logged_rather_than_raised(self,
                                                                          caplog):
        with caplog.at_level('ERROR'):
            kvp.set_custom_metadata(_NoInstance(), {'a': object()})

        assert 'Failed to store custom metadata' in caplog.text


class TestKeyValidation:
    def test_a_colon_in_a_key_is_refused_before_anything_is_written(self):
        """Colons separate key from value in the plaintext format."""
        with pytest.raises(ValueError, match=':'):
            kvp.set_custom_metadata(_NoInstance(), {'tax:category': 'x'})
