"""A commodity that cannot be created is reported the same way either way.

The `--include-business-objects` pre-pass creates commodities before the
business objects that reference them, and a declaration it cannot carry out is
left to the transaction pass, which attempts the same declarations and reports
what fails. That works while the transaction pass is reached — and a tax table
posting to an account in the failed commodity is imported before it.

So the same file gave two answers. Without the flag: exit 1, the commodity's
own error in the summary, the book on disk. With it: the business-object
import raised, the outer handler removed the `--new` book, and the reason the
reader was given was an account's "cannot find commodity" — the symptom, one
step removed from the cause in their own file.

The account arm of this was already carried through. The commodity arm is the
same shape and the same fix: remember what the pre-pass could not make, and
say it when something downstream trips over it.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner

from cli.main import cli

LEDGER = """\
2026-01-01 commodity XYZ
\tmnemonic: "XYZ"
\tfullname: "Not An ISO Currency"
\tnamespace: "CURRENCY"
\tfraction: 100
2026-01-01 open Liabilities
\ttype: Liability
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "XYZ"
2026-01-01 open Liabilities:GST
\ttype: Liability
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "XYZ"

taxtable "GST"
\tentry:
\t\taccount: "Liabilities:GST"
\t\tamount: 5.0
\t\ttype: percentage
"""


def _run(tmp_path, *extra):
    book = tmp_path / 'book.gnucash'
    ledger = tmp_path / 'ledger.txt'
    ledger.write_text(LEDGER)
    return CliRunner().invoke(cli, ['import', '--new', str(book), str(ledger),
                                    *extra])


class TestWithoutTheFlag:
    def test_it_is_refused(self, tmp_path):
        result = _run(tmp_path)

        assert result.exit_code != 0, result.output

    def test_the_commodity_is_named(self, tmp_path):
        result = _run(tmp_path)

        assert 'XYZ' in result.output, result.output


class TestWithBusinessObjects:
    def test_it_is_refused_too(self, tmp_path):
        result = _run(tmp_path, '--include-business-objects')

        assert result.exit_code != 0, result.output

    def test_the_commodity_is_named_here_as_well(self, tmp_path):
        """Not only the account or the tax table that tripped over it."""
        result = _run(tmp_path, '--include-business-objects')

        assert 'XYZ' in result.output, result.output

    def test_it_says_a_currency_must_be_iso(self, tmp_path):
        """The cause, in the words the unflagged run uses."""
        result = _run(tmp_path, '--include-business-objects')

        assert 'ISO' in result.output, result.output

    def test_it_calls_the_cause_a_commodity(self, tmp_path):
        """The one message written to stop a reader looking in the wrong
        place has to name the right kind of thing.

        The clause was worded for an account, and a commodity's failure was
        carried under it: `That account could not be created: Failed to create
        commodity XYZ`. The cause is there and correct, and the sentence
        around it sends the reader to the account declaration instead.
        """
        result = _run(tmp_path, '--include-business-objects')

        assert 'That commodity could not be created: Failed to create ' \
            'commodity XYZ' in result.output, result.output
        assert 'That account could not be created: Failed to create ' \
            'commodity' not in result.output, result.output
