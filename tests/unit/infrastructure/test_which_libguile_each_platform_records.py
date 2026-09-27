"""Which libguile GnuCash records, and where the one in this process is read.

A render runs GnuCash's own Scheme, so the interpreter has to be the one
GnuCash is linked to, and `infrastructure/guile.py` asks GnuCash's libraries
rather than searching by name. Each platform records that differently, and both
readings are exercised here:

- an ELF records a **soname**, `libguile-2.2.so.1`, which the loader resolves as
  it would for GnuCash. `tests/integration/test_the_interpreter_is_gnucashs_own.py`
  checks that against the real images.
- a Mach-O records the **whole install path**, `/opt/local/lib/libguile-3.0.1.dylib`,
  because macOS searches neither MacPorts' prefix nor Homebrew's and the
  trailing name alone is on no search path (CLAUDE.md finding 31).

And where the libguile already open is read: `/proc/self/maps` where there is
one, and dyld's list of loaded images where there is not.

These are bytes on disk and a supplied image list, so a container runs both —
the alternative was marking the macOS reading as uncovered, which states that
it cannot be checked when only the *call* cannot: `_dyld_image_count` is not a
symbol on Linux. That it answers correctly against a real dyld is measured on a
mac and written down in CLAUDE.md finding 31; that this code reads the answer
correctly is measured here.
"""

import ctypes
from unittest.mock import MagicMock, patch

from infrastructure.guile import _the_libguile_dyld_lists, gnucash_libguile_soname, mapped_libguile

#: A Mach-O holds each linked library's install path as a plain string among
#: NUL padding, which is how these fixtures write it.
A_MACH_O_LOAD_COMMAND = b'\x0c\x00\x00\x00\x38\x00\x00\x00'


def _a_library_recording(tmp_path, name, recorded: bytes):
    """A file in a directory the engine is looked for in, holding `recorded`."""
    library = tmp_path / 'gnucash' / name
    library.parent.mkdir(exist_ok=True)
    library.write_bytes(b'\x00' * 32 + A_MACH_O_LOAD_COMMAND + recorded + b'\x00' * 16)
    return library


def _looked_for_in(tmp_path):
    """`ENGINE_LIB_PATHS` pointing at that directory, as the engine's own path."""
    return patch('infrastructure.gnucash.engine.ENGINE_LIB_PATHS',
                 [str(tmp_path / 'gnucash' / 'libgnc-engine.dylib')])


class TestWhatAMachORecords:
    def test_the_whole_install_path_is_read_from_the_library(self, tmp_path):
        """Not the trailing name: dlopen would look in `/usr/lib` for that and
        find nothing, MacPorts' prefix being on no search path."""
        _a_library_recording(tmp_path, 'libgnc-expressions-guile.dylib',
                             b'/opt/local/lib/libguile-3.0.1.dylib')

        with _looked_for_in(tmp_path):
            assert gnucash_libguile_soname() == '/opt/local/lib/libguile-3.0.1.dylib'

    def test_padding_before_the_path_is_not_taken_into_it(self, tmp_path):
        """A NUL ends the path as surely as whitespace does.

        `\\S` does not cover NUL, so a pattern written with it is free to start
        at a `/` in unrelated data and hand back a path with NULs through it,
        which dlopen refuses. Here the bytes before the install path are
        another path, NUL-separated, as a real Mach-O's are.
        """
        _a_library_recording(
            tmp_path, 'libgnc-expressions-guile.dylib',
            b'/opt/local/lib/libgnc-core-utils.dylib\x00\x00'
            b'/opt/local/lib/libguile-3.0.1.dylib')

        with _looked_for_in(tmp_path):
            assert gnucash_libguile_soname() == '/opt/local/lib/libguile-3.0.1.dylib'

    def test_an_elf_soname_is_still_read_as_a_soname(self, tmp_path):
        """The ELF reading is unchanged by the Mach-O one, and comes first."""
        _a_library_recording(tmp_path, 'libgnc-app-utils.so',
                             b'\x00libguile-2.2.so.1\x00')

        with _looked_for_in(tmp_path):
            assert gnucash_libguile_soname() == 'libguile-2.2.so.1'


class TestWhereTheLibraryAlreadyOpenIsRead:
    """`/proc/self/maps` where there is one, dyld's image list where there is not."""

    def test_dyld_is_asked_where_there_is_no_proc(self):
        images = [b'/usr/lib/libSystem.B.dylib',
                  b'/opt/local/lib/libguile-3.0.1.dylib',
                  b'/opt/local/lib/libgnc-engine.dylib']
        dyld = MagicMock()
        dyld._dyld_image_count.return_value = len(images)
        dyld._dyld_get_image_name.side_effect = images

        with patch('infrastructure.guile.Path') as no_proc, \
                patch.object(ctypes, 'CDLL', return_value=dyld):
            no_proc.return_value.exists.return_value = False
            found = mapped_libguile()

        assert found == '/opt/local/lib/libguile-3.0.1.dylib'

    def test_none_where_dyld_lists_no_libguile(self):
        """What it answers before the first render, where nothing has loaded one."""
        dyld = MagicMock()
        dyld._dyld_image_count.return_value = 1
        dyld._dyld_get_image_name.side_effect = [b'/usr/lib/libSystem.B.dylib']

        with patch('infrastructure.guile.Path') as no_proc, \
                patch.object(ctypes, 'CDLL', return_value=dyld):
            no_proc.return_value.exists.return_value = False
            assert mapped_libguile() is None

    def test_an_image_dyld_has_no_path_for_is_passed_over(self):
        """`_dyld_get_image_name` answers NULL for an index that has gone, and
        ctypes reads that as None — which `in` would raise on."""
        dyld = MagicMock()
        dyld._dyld_image_count.return_value = 2
        dyld._dyld_get_image_name.side_effect = [None, b'/opt/local/lib/libguile-3.0.1.dylib']

        with patch.object(ctypes, 'CDLL', return_value=dyld):
            assert _the_libguile_dyld_lists() == '/opt/local/lib/libguile-3.0.1.dylib'

    def test_the_index_and_the_string_are_declared(self):
        """A pointer read as a `c_int` loses its top half (CLAUDE.md finding 1),
        and an undeclared return is read as one."""
        dyld = MagicMock()
        dyld._dyld_image_count.return_value = 0
        dyld._dyld_get_image_name.side_effect = []

        with patch.object(ctypes, 'CDLL', return_value=dyld):
            _the_libguile_dyld_lists()

        assert dyld._dyld_image_count.restype is ctypes.c_uint32
        assert dyld._dyld_get_image_name.restype is ctypes.c_char_p
        assert dyld._dyld_get_image_name.argtypes == [ctypes.c_uint32]
