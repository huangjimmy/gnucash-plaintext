"""Every file inside a package the wheel ships is in the wheel.

`pyproject.toml` ships the Python packages it lists, and of the other files in
them only those `[tool.setuptools.package-data]` matches. The suite installs
the project in editable mode, which reads the source folder, so a file left
out of the wheel is missing only for someone who installed the package, and no
other test can see it. The customized GnuCash report that prints the plaintext
balance sheet and income statement was one: a wheel built from the tree held
`services/gnucash_statements.py` and not the `.scm` it loads, so `balance-sheet`
from an installed package would have had no report to print with.

Read from `pyproject.toml` the way setuptools reads it: a package-data key is a
package (`*` is every package), and each pattern is a glob relative to that
package's directory, matched part by part so that `*.yaml` does not reach into
a subdirectory.
"""

import fnmatch
import pathlib
import sys

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from services.gnucash_statements import TEXT_REPORTS

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


def _setuptools():
    with open(REPO_ROOT / 'pyproject.toml', 'rb') as f:
        return tomllib.load(f)['tool']['setuptools']


def _matches(relative, pattern):
    path_parts = relative.split('/')
    pattern_parts = pattern.split('/')
    return (len(path_parts) == len(pattern_parts)
            and all(fnmatch.fnmatchcase(part, glob)
                    for part, glob in zip(path_parts, pattern_parts)))


def _owner(path, packages):
    """The listed package whose directory holds `path` most closely, and `path` relative to it."""
    relative = path.relative_to(REPO_ROOT).as_posix()
    owners = [package for package in packages
              if relative.startswith(package.replace('.', '/') + '/')]
    if not owners:
        return None, relative
    package = max(owners, key=len)
    return package, relative[len(package.replace('.', '/')) + 1:]


def _shipped(path, setuptools):
    package, relative = _owner(path, setuptools['packages'])
    if package is None:
        return False
    data = setuptools.get('package-data', {})
    patterns = list(data.get('*', [])) + list(data.get(package, []))
    return any(_matches(relative, pattern) for pattern in patterns)


def test_every_file_that_is_not_python_in_a_shipped_package_is_package_data():
    setuptools = _setuptools()
    left_out = []
    for package in setuptools['packages']:
        for path in (REPO_ROOT / package.replace('.', '/')).rglob('*'):
            if (path.is_file() and path.suffix not in ('.py', '.pyc')
                    and '__pycache__' not in path.parts
                    and not _shipped(path, setuptools)):
                left_out.append(path.relative_to(REPO_ROOT).as_posix())
    assert sorted(set(left_out)) == []


def test_the_report_the_statements_are_printed_with_is_shipped():
    assert TEXT_REPORTS.is_file(), TEXT_REPORTS
    assert _shipped(TEXT_REPORTS.resolve(), _setuptools()), TEXT_REPORTS
