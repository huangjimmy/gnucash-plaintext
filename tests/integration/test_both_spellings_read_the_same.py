"""`account:` and `bank_account:` are one key, so they must read the same.

`account:` is the canonical spelling of a payment's account and
`bank_account:` the accepted alias — every reader of a payment block goes
through one resolver that takes either. One did not: the rule that lets a
self-describing payment be created when its `txn_guid:` resolves to nothing
asked for `bank_account:` alone.

So the same block, differing in one word, got two answers: the alias minted a
payment for money that never moved, silently; the canonical key refused the
run. And the tool's own writers emit the alias, so everything it produces took
the lenient path while a person retyping the documented key got the refusal.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner

from cli.main import cli

FIXTURES = Path('tests/fixtures')
SPELLINGS = {
    'bank_account': str(FIXTURES / 'a_payment_named_with_bank_account.txt'),
    'account': str(FIXTURES / 'a_payment_named_with_account.txt'),
}


@pytest.mark.parametrize('spelling', list(SPELLINGS))
class TestAGuidNamingNothing:
    def _run(self, tmp_path, spelling):
        book = tmp_path / f'{spelling}.gnucash'
        return CliRunner().invoke(cli, [
            'import', '--new', str(book), SPELLINGS[spelling],
            '--include-business-objects'])

    def test_the_block_is_read(self, tmp_path, spelling):
        """It says everything needed to make the payment."""
        result = self._run(tmp_path, spelling)

        assert result.exit_code == 0, result.output

    def test_the_reader_is_told_the_guid_was_not_used(self, tmp_path,
                                                      spelling):
        """Otherwise a stale reference and a reconstruction look alike."""
        result = self._run(tmp_path, spelling)

        assert 'deadbeef' in result.output, result.output
