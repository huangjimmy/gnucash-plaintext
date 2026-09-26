"""A note the importer cannot write does not stop the import.

The importer writes a note to stderr where it does something a reader should
know about and nothing is wrong: a printed page read into another book states a
`posted_txn_guid:` that matches no transaction there, so the posting is made
with a guid GnuCash assigns it. Where stderr is a pipe nobody reads any more —
`gnucash-plaintext import … 2>&1 | head -1` after `head` has exited — writing
the note raises `BrokenPipeError`. Nothing else on a successful import goes to
stderr, so the note is the only write that can fail, and losing it must not
lose the import.

Run in this process rather than through `CliRunner`, whose streams are in
memory and never break: stderr is a real pipe with its reading end closed.
"""

import contextlib
import os
import sys
from pathlib import Path

from click.testing import CliRunner

from cli.main import cli

SOURCE = str(Path('tests/fixtures/a_payment_named_with_account.txt'))


def _invoked(*args):
    result = CliRunner().invoke(cli, [str(arg) for arg in args])
    assert result.exit_code == 0, result.output
    return result


def _a_printed_page_and_another_book(tmp_path):
    source = tmp_path / 'source.gnucash'
    _invoked('import', '--new', source, SOURCE, '--include-business-objects')
    page = tmp_path / 'printed.txt'
    _invoked('print-invoice', source, 'INV-SPELL', '--format', 'plaintext', '-o', page)
    elsewhere = tmp_path / 'elsewhere.gnucash'
    _invoked('import', '--new', elsewhere, SOURCE)
    return page, elsewhere


def _with_stderr_nobody_reads(*args):
    reading, writing = os.pipe()
    os.close(reading)
    broken = os.fdopen(writing, 'w')
    kept = sys.stderr
    sys.stderr = broken
    try:
        cli.main([str(arg) for arg in args], standalone_mode=False)
    finally:
        sys.stderr = kept
        # Closing flushes what is left, into the same closed pipe.
        with contextlib.suppress(BrokenPipeError):
            broken.close()


def test_the_page_is_imported_all_the_same(tmp_path):
    page, elsewhere = _a_printed_page_and_another_book(tmp_path)

    _with_stderr_nobody_reads('import', elsewhere, page, '--include-business-objects')

    out = tmp_path / 'back.txt'
    _invoked('export', elsewhere, out, '--include-business-objects')
    text = out.read_text()
    assert 'invoice "INV-SPELL"' in text, text
    assert 'posted: none' not in text, text
