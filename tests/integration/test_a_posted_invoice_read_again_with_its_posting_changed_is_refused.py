"""A posted invoice read again with its `posted:` block changed is refused.

A posted invoice takes a `payment:` block and nothing else. Changing what its
`posted:` block says, the day it was posted or the receivable it posts to,
means rebuilding a record the book has already booked, so the import refuses
and says to unpost it first.
"""

import pytest
from click.testing import CliRunner

from cli.main import cli
from tests.integration.test_find_orphan_payments import (
    _fixture,
    _import,
    _setup_book,
    _write,
)

SECOND_RECEIVABLE = (
    '2026-01-01 open Assets:Accounts Receivable Two\n'
    '\ttype: Accounts Receivable\n'
    '\tcommodity.namespace: "CURRENCY"\n'
    '\tcommodity.mnemonic: "CAD"\n\n')


@pytest.mark.parametrize('old, new, opened', [
    ('\tposted:\n\t\tdate: 2026-01-01\n', '\tposted:\n\t\tdate: 2026-01-02\n', ''),
    ('\t\tar_account: "Assets:Accounts Receivable"\n',
     '\t\tar_account: "Assets:Accounts Receivable Two"\n', SECOND_RECEIVABLE),
], ids=['posted-another-day', 'posted-to-another-receivable'])
def test_it_is_refused(tmp_path, old, new, opened):
    runner = CliRunner()
    text = _fixture('q014_invoice_posted_paid')
    book = _setup_book(runner, tmp_path, text)
    assert old in text, text
    again = _write(tmp_path / 'again.txt', opened + text.replace(old, new))

    result = _import(runner, book, again)

    assert result.exit_code != 0, result.output
    assert 'this invoice is posted, and this file changes it' in result.output, \
        result.output
