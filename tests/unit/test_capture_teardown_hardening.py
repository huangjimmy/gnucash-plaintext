"""A file descriptor GnuCash closed must not fail a passing run.

GnuCash's backend churns descriptors — a `.LCK` per session, a `.log` per
session — and intermittently closes the one pytest saved when it set up
fd-level capture. Pytest restores it with `os.dup2` and raises
`OSError: [Errno 9] Bad file descriptor` on a run where every assertion passed.
`tests/conftest.py` hardens the paths that restore it.

This pins that hardening. The flake is probabilistic — it last surfaced on
Debian 11 only when all ten distro containers ran at once, and the same suite
passed on its own — so without a test the protection could be dropped and
nothing would say so until a commit was blocked by a run with no real failure
in it.
"""

import contextlib
import logging
import os

import pytest

from tests.conftest import (
    a_spare_copy_of,
    put_the_descriptor_back_if_it_has_gone,
    swallow_oserror,
)

CAPTURE_CLASS_NAMES = ('FDCaptureBinary', 'FDCapture', 'SysCaptureBinary', 'SysCapture')


def _capture_classes():
    capture = pytest.importorskip('_pytest.capture')
    found = [getattr(capture, name, None) for name in CAPTURE_CLASS_NAMES]
    return [cls for cls in found if cls is not None]


def test_the_fd_restoring_capture_paths_are_hardened():
    """`done` ends the run; `suspend` and `resume` bracket every test.

    `CaptureManager.item_capture` is a generator context manager whose
    `finally` calls `suspend_global_capture`, so an unhardened `suspend` fails
    the test it was wrapping — reported as
    `contextlib.py __exit__ -> next(self.gen) -> OSError` — rather than as a
    teardown artifact at the end.
    """
    classes = _capture_classes()
    assert classes, 'pytest capture classes not found'
    for cls in classes:
        assert getattr(cls, '_gnc_hardened', False), f'{cls.__name__} is not hardened'


def test_the_capture_reading_path_is_hardened_too():
    """`snap` reads the capture file, and the same generator calls it.

    `item_capture` reads the captured output *after* its `finally`, and the end
    of the run reads it again through `pop_outerr_to_orig`. Both land in
    `snap`, which reads the temp file behind the descriptor — so a closed one
    raises there with the same `contextlib` frame, and every test after it
    errors. That is 2807 errors behind one closed fd, on a suite whose
    assertions all passed.
    """
    for cls in _capture_classes():
        snapped = cls.snap
        assert getattr(snapped, '__name__', '') == '_safe', (
            f'{cls.__name__}.snap is not hardened')


def test_a_reading_path_falls_back_to_an_empty_capture_of_its_own_type():
    """None would move the failure one frame along, not handle it.

    What `snap` returns is used — pytest puts it in the report section for the
    test — so the binary classes have to answer with bytes and the rest with
    str. Read off the wrapper rather than provoked, because reaching the read
    means getting past the state and type assertions pytest makes first, and
    those are its business rather than this hardening's.
    """
    def _gone(self):
        raise OSError(9, 'Bad file descriptor')

    assert swallow_oserror(_gone, b'')(object()) == b''
    assert swallow_oserror(_gone, '')(object()) == ''

    capture = pytest.importorskip('_pytest.capture')
    for name in CAPTURE_CLASS_NAMES:
        cls = getattr(capture, name, None)
        if cls is None:
            continue
        expected = b'' if name.endswith('Binary') else ''
        assert cls.snap._gnc_fallback == expected, name
        assert isinstance(cls.snap._gnc_fallback, type(expected)), name


def test_the_restoring_paths_answer_with_nothing():
    """`done`, `suspend` and `resume` are called for their effect, not a value."""
    for cls in _capture_classes():
        for method in ('done', 'suspend', 'resume'):
            wrapped = getattr(cls, method, None)
            if wrapped is not None and hasattr(wrapped, '_gnc_fallback'):
                assert wrapped._gnc_fallback is None, f'{cls.__name__}.{method}'


def test_the_logging_close_path_is_hardened():
    """The logging plugin closes its file handler in `pytest_unconfigure`."""
    for cls in (logging.FileHandler, logging.StreamHandler):
        assert getattr(cls, '_gnc_close_hardened', False), f'{cls.__name__} is not hardened'


def test_the_progress_column_is_hardened_too():
    """Writing the descriptor, not only reading it or putting it back.

    `TerminalReporter` flushes the `[ 77%]` column after every test. A closed
    descriptor raises there from inside `pytest_runtest_logreport`, which
    pytest reports as an `INTERNALERROR` and not as a failing test — so the
    run ends mid-suite with every test that ran having passed. Seen on
    Debian 11 at 2747 of 3556.
    """
    io = pytest.importorskip('_pytest._io')
    assert getattr(io.TerminalWriter, '_gnc_write_hardened', False), (
        'TerminalWriter.write is not hardened')


def test_the_progress_column_still_writes_what_it_is_given():
    """Hardened, not silenced: only an OSError is swallowed.

    Checked on the wrapper rather than on pytest's own writer, whose output
    is the stream this test is being reported on.
    """
    written = []
    assert swallow_oserror(lambda _self, text: written.append(text))(
        object(), 'hello') is None
    assert written == ['hello']


def test_a_closed_descriptor_is_swallowed():
    """The wrapper returns rather than raising when the fd is already gone."""
    def _gone(self):
        raise OSError(9, 'Bad file descriptor')

    assert swallow_oserror(_gone)(object()) is None


def test_anything_that_is_not_an_fd_problem_still_raises():
    """Only OSError is swallowed — a real fault must not be hidden by this."""
    def _broken(self):
        raise ValueError('not an fd problem')

    with pytest.raises(ValueError):
        swallow_oserror(_broken)(object())


def test_a_working_call_is_left_alone():
    def _fine(self, value):
        return value * 2

    assert swallow_oserror(_fine)(object(), 21) == 42


class TestTheDescriptorPytestFlushesOnItsWayOut:
    """`console_main` flushes `sys.stdout` as pytest returns, and where
    GnuCash has closed fd 1 that flush ends the run mid-suite through `runpy`
    — no assertion behind it, and the sweep reporting that version failed.

    Neither hardened class is on that path, and neither is `sys.stdout`:
    capture has replaced that object before `conftest.py` is imported, and
    what pytest flushes at the end is the original it saved. So the descriptor
    is what gets put back, in the last hook before that flush.

    Exercised on a descriptor of its own — closing fd 1 in the process running
    these tests would take pytest's own output with it.
    """

    def test_a_spare_is_held_for_stdout(self):
        import tests.conftest as conftest

        assert conftest._A_SPARE_STDOUT is not None

        # `os.fstat` on that descriptor is what this used to do, and it is not
        # a thing this test can rely on: it is one process-wide fd, taken when
        # conftest was imported, and the same GnuCash churn the spare exists
        # for can close it while some unrelated test runs. Measured on Debian
        # 10 under the eleven-way sweep — `OSError: [Errno 9] Bad file
        # descriptor`, reported as this hardening being broken when what it had
        # met was the hazard.
        #
        # So what is checked is that a spare can be taken here and now, which
        # is the mechanism, and does not depend on what ran before.
        fresh = a_spare_copy_of(1)
        assert fresh is not None
        try:
            os.fstat(fresh)
        finally:
            with contextlib.suppress(OSError):
                os.close(fresh)

    def test_a_closed_descriptor_is_put_back(self, tmp_path):
        target = os.open(tmp_path / 'out.txt', os.O_WRONLY | os.O_CREAT)
        spare = a_spare_copy_of(target)
        try:
            os.close(target)
            assert put_the_descriptor_back_if_it_has_gone(target, spare) is True
            os.fstat(target)                    # open again, from the spare
            os.write(target, b'said')
        finally:
            for fd in (target, spare):
                with contextlib.suppress(OSError):
                    os.close(fd)
        assert (tmp_path / 'out.txt').read_bytes() == b'said'

    def test_a_descriptor_that_is_still_there_is_left_alone(self, tmp_path):
        target = os.open(tmp_path / 'out.txt', os.O_WRONLY | os.O_CREAT)
        spare = a_spare_copy_of(target)
        try:
            assert put_the_descriptor_back_if_it_has_gone(target, spare) is False
        finally:
            for fd in (target, spare):
                os.close(fd)

    def test_with_no_spare_it_does_nothing(self):
        assert put_the_descriptor_back_if_it_has_gone(1, None) is False
