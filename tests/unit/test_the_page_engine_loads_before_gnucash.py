"""The ordering that keeps Debian 10 from dying, and the wiring that applies it.

WeasyPrint draws through `cairocffi`, which opens its own libcairo and makes a
surface while being imported; GnuCash's bindings have already opened libcairo
through GTK. On Debian 10 that order is a SIGSEGV — measured, one process each
way, in `infrastructure/pdf/cairo_before_gnucash.py`.

Pinned rather than left to the two call sites, for two reasons this repo has
already met:

- ruff's unsafe fixes rewrote the `sys.version_info` guard into an
  unconditional `return False` once, at `target-version = "py38"`. The setting
  is `py37` now, which closes that door; an import-sorter moving the call in
  `cli/__init__.py`, or an edit dropping it, opens another.
- the failure is a segfault, so under pytest it ends the run instead of
  failing a test. A regression here reads as "the suite produced nothing",
  which is the same signal as a broken container.

The same shape as `test_capture_teardown_hardening.py`, which asserts the
conftest hardening is applied, and `test_the_kill_guard_allows_one_id.py`,
which reads `.claude/settings.json` to check a hook is still wired.
"""

import ast
import pathlib
import sys

from infrastructure.pdf.cairo_before_gnucash import load_the_page_engine_first

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


def test_the_cli_package_calls_it_before_any_command_module():
    """`cli/__init__.py` runs before any `cli.*` module, so it is where the
    ordering can be stated once. Read from the syntax tree rather than by
    matching text, so a call spelled across two lines still counts."""
    tree = ast.parse((REPO_ROOT / 'cli' / '__init__.py').read_text())
    called = {node.func.id
              for node in ast.walk(tree)
              if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    assert 'load_the_page_engine_first' in called, ast.dump(tree)


def test_the_suite_calls_it_before_any_test_reaches_gnucash():
    """A test can `import gnucash` without going through the CLI at all."""
    tree = ast.parse((REPO_ROOT / 'tests' / 'conftest.py').read_text())
    called = {node.func.id
              for node in ast.walk(tree)
              if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    assert 'load_the_page_engine_first' in called


def test_it_does_nothing_above_python_3_7():
    """The import is not free, and Debian 10 is the only build with the pair.

    Whichever side of the boundary this build is on, the answer is checked —
    so a guard rewritten to an unconditional `return False`, which is what
    ruff once did to it, fails here on the one build that needs it.
    """
    if sys.version_info >= (3, 8):
        assert load_the_page_engine_first() is False
    else:
        assert load_the_page_engine_first() is True


def test_and_on_3_7_weasyprint_is_loaded_before_gnucash():
    """The point of all of it: by the time anything imports GnuCash, the page
    engine is already in `sys.modules`."""
    if sys.version_info >= (3, 8):
        import pytest
        pytest.skip('the ordering only matters where cairo disagrees')
    load_the_page_engine_first()
    assert 'weasyprint' in sys.modules
