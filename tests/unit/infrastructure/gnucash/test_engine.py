"""
Unit tests for infrastructure/gnucash/engine.py utilities.

These tests run without GnuCash installed — they mock ctypes to
exercise pure-Python logic in iterate_glist, safe_ctypes_string,
verify_ctypes_functions, and load_gnc_engine.

Bug coverage (four bugs found in commit db9e600):

  Bug #1 — iterate_glist: `glist_ptr = glist.next` was outside the try block.
      If GList.from_address() raises on the first iteration, `glist` is never
      assigned, so `glist.next` raises NameError and crashes the caller.

  Bug #2 — load_gnc_engine fallback: the try/except only caught
      (OSError, AttributeError). A RuntimeError raised by
      verify_ctypes_functions propagated immediately, skipping all
      remaining library paths in the fallback chain.

  Bug #3 — safe_ctypes_string: the `lib` parameter was accepted but
      never referenced inside the function body, making it dead weight
      in the API.

  Bug #4 — DEBUGGING_GNUCASH_BINDINGS.md line 41: a code example still
      used the old pre-utility pattern instead of safe_ctypes_string.
      (No test needed — documentation-only fix.)
"""
import ctypes
from unittest.mock import MagicMock, patch

import pytest

from infrastructure.gnucash.engine import (
    GList,
    iterate_glist,
    load_gnc_engine,
    safe_ctypes_string,
    verify_ctypes_functions,
)

# ---------------------------------------------------------------------------
# Bug #1 — iterate_glist: NameError when GList.from_address raises on first
#           iteration because glist_ptr = glist.next was outside the try block
# ---------------------------------------------------------------------------

class TestIterateGlist:
    def test_empty_list_returns_empty(self):
        """None pointer → empty result list, no error."""
        assert iterate_glist(MagicMock(), None, lambda _lib, p: p) == []

    def test_single_element_processed(self):
        """Happy path: single-element list, process_func doubles the data pointer."""
        lib = MagicMock()
        node = MagicMock()
        node.data = 0x1000
        node.next = None

        with patch.object(GList, "from_address", return_value=node):
            result = iterate_glist(lib, 0xDEAD, lambda _lib, ptr: ptr * 2)

        assert result == [0x2000]

    def test_process_func_exception_skips_element_and_continues(self):
        """process_func raising should log a warning and continue iteration.

        glist.data IS accessible (from_address succeeded), so glist.next is
        also accessible and iteration can continue to the next node.
        """
        lib = MagicMock()

        # Two-node list: node1 → node2 → None
        node2 = MagicMock()
        node2.data = 0x2000
        node2.next = None

        node1 = MagicMock()
        node1.data = 0x1000
        node1.next = 0xBEEF  # non-zero so loop continues to node2

        call_count = [0]

        def from_addr(address):
            call_count[0] += 1
            return node1 if call_count[0] == 1 else node2

        def bad_process(lib, ptr):
            if ptr == 0x1000:
                raise ValueError("simulated failure on first element")
            return ptr

        with patch.object(GList, "from_address", side_effect=from_addr):
            result = iterate_glist(lib, 0xDEAD, bad_process)

        # node1 failed → skipped; node2 succeeded → in results
        assert result == [0x2000]

    def test_from_address_exception_on_first_iteration_does_not_raise_nameerror(self):
        """Bug #1: glist_ptr = glist.next was outside the try block.

        When GList.from_address() raises on the very first iteration,
        `glist` is never assigned.  The old code then hit `glist.next`
        outside the try, raising NameError and crashing the caller.

        After the fix the exception must be caught and the function must
        return an empty list (with a logged warning) instead of raising.
        """
        lib = MagicMock()

        with patch.object(GList, "from_address", side_effect=ValueError("corrupt address")):
            # Must NOT raise — should return [] and log a warning
            result = iterate_glist(lib, 0xDEADBEEF, lambda _lib, p: p)

        assert result == []

    def test_from_address_exception_mid_iteration_does_not_raise(self):
        """from_address failure on iteration N>1 must not bleed into next loop cycle."""
        lib = MagicMock()

        good_node = MagicMock()
        good_node.data = 0xABC
        good_node.next = 0x999  # non-zero → try second iteration

        call_count = [0]

        def from_addr(address):
            call_count[0] += 1
            if call_count[0] == 1:
                return good_node
            raise ValueError("second node corrupt")

        with patch.object(GList, "from_address", side_effect=from_addr):
            result = iterate_glist(lib, 0x111, lambda _lib, p: p)

        assert result == [0xABC]


# ---------------------------------------------------------------------------
# Bug #2 — load_gnc_engine fallback: RuntimeError from verify_ctypes_functions
#           was not caught, breaking the library-path fallback chain
# ---------------------------------------------------------------------------

class TestLoadGncEngineFallback:
    def test_runtime_error_from_verify_does_not_break_fallback_chain(self):
        """Bug #2: RuntimeError was not in the except clause.

        With the old code the loop catches only (OSError, AttributeError),
        so a RuntimeError from verify_ctypes_functions propagates immediately —
        the second library path is never tried.

        After the fix RuntimeError must also be caught and the loop must
        continue to the next path.
        """
        verify_calls = [0]

        def mock_verify(lib, required_functions=None):
            verify_calls[0] += 1
            if verify_calls[0] == 1:
                raise RuntimeError("verify failed on first path")
            # Second call succeeds (returns None implicitly)

        mock_lib = MagicMock()

        with patch("infrastructure.gnucash.engine.verify_ctypes_functions", mock_verify), \
                patch("infrastructure.gnucash.engine._setup_lib_restypes"), \
                patch("ctypes.CDLL", return_value=mock_lib):
            result = load_gnc_engine()

        # Before fix: verify_calls[0] == 1 (RuntimeError broke the loop)
        # After fix:  verify_calls[0] >= 2 (first path caught, second path tried)
        assert verify_calls[0] >= 2
        assert result is mock_lib

    def test_all_paths_exhausted_raises_runtime_error(self):
        """When every path fails, load_gnc_engine must raise RuntimeError."""
        with patch("infrastructure.gnucash.engine._setup_lib_restypes", side_effect=OSError("not found")), \
                patch("ctypes.CDLL", side_effect=OSError("not found")), \
                pytest.raises(RuntimeError, match="Could not load"):
            load_gnc_engine()


# ---------------------------------------------------------------------------
# Bug #3 — safe_ctypes_string: `lib` parameter was accepted but never used
# ---------------------------------------------------------------------------

class TestSafeCtypesString:
    def test_decodes_bytes_to_string(self):
        func = MagicMock(return_value=b"hello world")
        assert safe_ctypes_string(func, 0x1234) == "hello world"

    def test_returns_empty_default_when_func_returns_none(self):
        func = MagicMock(return_value=None)
        assert safe_ctypes_string(func, 0x1234) == ""

    def test_returns_custom_default_when_func_returns_none(self):
        func = MagicMock(return_value=None)
        assert safe_ctypes_string(func, 0x1234, default="?") == "?"

    def test_returns_custom_default_when_func_returns_empty_bytes(self):
        func = MagicMock(return_value=b"")
        assert safe_ctypes_string(func, 0x1234, default="fallback") == "fallback"

    def test_lib_parameter_removed_from_signature(self):
        """Bug #3: lib was a dead parameter — callers no longer pass it.

        With the old signature safe_ctypes_string(lib, func, ptr, default="")
        this call raises TypeError: too many positional arguments.
        After the fix (signature: safe_ctypes_string(func, ptr, default=""))
        it must succeed.
        """
        func = MagicMock(return_value=b"test")
        # New signature: no lib argument
        result = safe_ctypes_string(func, 0x1234)
        assert result == "test"

    def test_ptr_is_forwarded_to_func(self):
        """Ensure the ptr argument is actually passed through to the function."""
        func = MagicMock(return_value=b"ok")
        safe_ctypes_string(func, 0xABCD)
        func.assert_called_once_with(0xABCD)


# ---------------------------------------------------------------------------
# verify_ctypes_functions — basic sanity (not a bug fix, just coverage)
# ---------------------------------------------------------------------------

class TestVerifyCtypesFunctions:
    def test_passes_when_all_functions_present(self):
        """If all requested functions exist on the lib object, no exception."""
        lib = MagicMock()
        # MagicMock has every attribute → hasattr returns True for all names
        verify_ctypes_functions(lib, ["gncTaxTableGetTables", "xaccAccountGetName"])

    def test_raises_when_function_missing(self):
        """Functions not on the object must trigger RuntimeError."""
        lib = MagicMock(spec=[])  # spec=[] means no attributes at all
        with pytest.raises(RuntimeError, match="missing required functions"):
            verify_ctypes_functions(lib, ["gncTaxTableGetTables"])
