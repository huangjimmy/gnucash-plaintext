"""The import summary lists every collected error. `result.errors` is a
uniform list of ``{'error': ...}`` dicts (transaction/account failures also
carry a ``'transaction'`` key). Parser (syntax) failures such as bad
indentation are normalised into that same dict shape in
``ImportTransactionsUseCase.import_from_file``.

Regression guard: parser errors were once appended as raw ``PlaintextParser``
strings, so the summary loop crashed with ``AttributeError: 'str' object has no
attribute 'get'`` when it called ``err.get('transaction')`` on a string entry.
These tests drive the CLI end to end to prove such a file now reports its parse
error instead of crashing.
"""

from click.testing import CliRunner

from cli.main import cli

# A taxtable entry line that mixes a tab and a space. The parser rejects it as
# "Invalid indentation" — the reported case, where a taxtable block's parse
# error reached the summary loop.
MIXED_INDENT_TAXTABLE = (
    'taxtable "GST"\n'
    '\tentry:\n'
    '\t account: "Liabilities:GST"\n'   # tab + space -> "Mixed tabs and spaces"
    '\t\trate: 5.0%\n'
    '\t\ttype: PERCENT\n'
)

# The same malformed indentation inside a transaction block — proves the fix is
# not taxtable-specific: any parser error flows through the same path.
MIXED_INDENT_TRANSACTION = (
    '2026-01-01 * "Deposit"\n'
    '\tAssets:Bank 200.00 CAD\n'
    '\t Income -200.00 CAD\n'           # tab + space -> "Mixed tabs and spaces"
)

# Valid syntax, but the first split references an account that was never opened.
# create_transaction raises -> a *dict* error ({'transaction': ..., 'error': ...})
# reaches the same summary loop. Guards that the fix keeps rendering dict errors.
UNKNOWN_ACCOUNT_TX = (
    '2026-01-01 * "Mystery"\n'
    '\tAssets:Nonexistent 100.00 CAD\n'
    '\tIncome:Nonexistent -100.00 CAD\n'
)


def _run_import(tmp_path, text, name='in.txt'):
    runner = CliRunner()
    gf = tmp_path / 'book.gnucash'
    src = tmp_path / name
    src.write_text(text)
    return runner.invoke(cli, ['import', '--new', str(gf), str(src)])


def test_taxtable_parse_error_is_reported_not_crashed(tmp_path):
    r = _run_import(tmp_path, MIXED_INDENT_TAXTABLE)
    # The crash signature ("'str' object has no attribute 'get'") is gone...
    assert "has no attribute 'get'" not in r.output, r.output
    # ...and the parser's plain-string error is surfaced, not swallowed.
    assert 'Invalid indentation' in r.output, r.output


def test_transaction_parse_error_is_reported_not_crashed(tmp_path):
    r = _run_import(tmp_path, MIXED_INDENT_TRANSACTION)
    assert "has no attribute 'get'" not in r.output, r.output
    assert 'Invalid indentation' in r.output, r.output


def test_dict_shaped_transaction_error_still_renders(tmp_path):
    # A dict error must still render with its transaction label and message,
    # so fixing the string case does not regress the original dict path.
    r = _run_import(tmp_path, UNKNOWN_ACCOUNT_TX)
    assert r.exception is None, r.exception
    assert 'error: Mystery:' in r.output, r.output
    assert 'not found' in r.output, r.output
