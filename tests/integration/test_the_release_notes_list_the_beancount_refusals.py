"""Every new `import-beancount` refusal is written down where readers look.

A refusal turns a file that imported — silently wrong, but imported — into a
run that stops. Hand-editing an export is the reason this format exists, so
these are shapes people arrive at, and a reader upgrading meets them without
warning unless the release notes say so. The plaintext refusals are listed
exhaustively; the beancount ones were two lines of fourteen.

Both halves of each row are checked against the thing itself: the refusal is
run, and the sentence naming it is read out of `RELEASE_NOTES.md`. A note
without the behaviour and a behaviour without the note both fail here, which is
what keeps the list from drifting as the next refusal is added.
"""

import re
from pathlib import Path

import pytest
from click.testing import CliRunner

from cli.main import cli

FIXTURES = Path('tests/fixtures')
NOTES = Path('RELEASE_NOTES.md')

# (fixture, what the run says, the sentence in RELEASE_NOTES that names it)
REFUSALS = [
    ('beancount_posting_it_cannot_read',
     'cannot read the posting line',
     'a posting line it cannot read'),
    ('beancount_posting_that_lost_its_indent',
     'is not indented, so it reads as a new directive',
     'a posting that lost its indentation'),
    ('beancount_cost_left_to_be_inferred',
     'holds its cost at `{}`',
     'asks for the cost to be inferred'),
    ('beancount_total_against_no_units',
     'states a total against no units',
     'a total stated against no units'),
    ('beancount_amount_that_is_not_a_number',
     'states an amount that is not a number',
     'an amount, cost or rate that is not a number'),
    ('beancount_cost_that_is_not_a_number',
     'states a cost that is not a number',
     'an amount, cost or rate that is not a number'),
    ('beancount_price_that_is_not_a_number',
     'states a price that is not a number',
     'an amount, cost or rate that is not a number'),
    ('beancount_a_day_that_does_not_exist',
     'is not a date',
     'a date that does not exist'),
    ('beancount_an_open_with_a_trailing_comment',
     'needs the currency the account is kept in',
     '`open` with no currency constraint'),
    ('beancount_account_with_no_name',
     'has a gnucash-name that names nothing',
     'a `gnucash-name` that names nothing'),
    ('beancount_account_name_ending_in_a_separator',
     'has a gnucash-name that names nothing',
     'a `gnucash-name` that names nothing'),
    ('beancount_a_posting_in_the_wrong_commodity',
     'is in a commodity the account does not hold',
     'a posting in a commodity its account does not hold'),
    ('beancount_conversion_with_no_rate',
     'says nothing about what it is worth in it',
     'says nothing about what it is worth in it'),
    ('beancount_a_rate_in_a_third_currency',
     'states its rate in USD while the transaction is denominated in CAD',
     'a rate stated in a third commodity, or in shares'),
    ('beancount_a_rate_in_shares',
     'states its rate in NASDAQ.NEWCO',
     'a rate stated in a third commodity, or in shares'),
    ('beancount_shares_moved_between_brokers',
     'has no posting in a currency',
     'a transfer in kind with no posting in a currency'),
    ('beancount_units_finer_than_the_account',
     'which is finer than that account is kept to',
     'an amount finer than the unit its account is kept to'),
    ('beancount_an_invented_currency_code',
     'is not an ISO 4217 code',
     'a `commodity` in the `CURRENCY` namespace that is not ISO 4217'),
]


def _unreleased() -> str:
    """The section a reader upgrading to the next version reads.

    Bounded at the next `## ` heading so a sentence surviving in an older
    release's notes does not stand in for one removed from this one.
    """
    text = NOTES.read_text()
    start = text.index('## Unreleased')
    after = text[start + len('## Unreleased'):]
    end = re.search(r'^## ', after, re.MULTILINE)
    return after[:end.start()] if end else after


@pytest.mark.parametrize('fixture,said,noted', REFUSALS,
                         ids=[row[0] for row in REFUSALS])
class TestARefusalAndItsNote:
    def test_the_file_is_refused(self, fixture, said, noted, tmp_path):
        book = tmp_path / f'{fixture}.gnucash'
        result = CliRunner().invoke(cli, [
            'import-beancount', str(book),
            str(FIXTURES / f'{fixture}.beancount')])

        assert result.exit_code != 0, result.output
        assert said in result.output, result.output

    def test_the_release_notes_name_it(self, fixture, said, noted):
        assert noted in _unreleased(), (
            f'{fixture} is refused and RELEASE_NOTES does not say so')
