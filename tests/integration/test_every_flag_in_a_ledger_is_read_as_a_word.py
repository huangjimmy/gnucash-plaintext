"""Every flag in a ledger takes the same six words, and refuses the rest.

A line is decoded before it is read, so `True` arrives as a boolean and `1`
as an integer, and one typo used to get three different answers depending on
which key it landed in:

- compared against the string `true` — `accumulate:` on a `posted:` block,
  and `taxable:` beside it — every one of `True`, `1` and `yes` read as
  **false**, and so did a typo;
- read as "not one of the falsy words" — `auto_apply_credit:`, `from_credit:`,
  `active:`, `closing:`, `billable:` — a typo read as **true**, which is the
  costly direction on each of them: `auto_apply_credit: treu` spends the
  owner's credit against an invoice the file never asked to settle that way;
- and `payment_type:` was refused by name, which is what the rest do now.

`accumulate:` is the one whose effect is visible in the book, so it is what
the first two classes here measure: two lines against one account, merged
into one split when the flag is read and posted a split each when it is not.
An invoice of one line posts the same transaction either way. The rest are
one refusal apiece — the key named, and both sets of spellings offered.
"""

import re
from pathlib import Path

import pytest
from click.testing import CliRunner
from gnucash import Query

from cli.main import cli
from infrastructure.gnucash.utils import wrap_invoice_or_bill
from repositories.gnucash_repository import GnuCashRepository, SessionMode

LEDGER = str(Path('tests/fixtures') /
             'an_invoice_whose_lines_share_an_account.txt')


def _splits_of_the_posting(book_path, invoice):
    """How many splits the invoice's posting transaction carries."""
    repo = GnuCashRepository(str(book_path))
    repo.open(SessionMode.READ_ONLY)
    try:
        q = Query()
        q.search_for('gncInvoice')
        q.set_book(repo.book)
        for raw in q.run():
            record = wrap_invoice_or_bill(raw)
            if record.GetID() == invoice:
                posted = record.GetPostedTxn()
                assert posted is not None, f'{invoice} is not posted'
                answer = len(posted.GetSplitList())
                q.destroy()
                return answer
        q.destroy()
        raise AssertionError(f'no invoice named {invoice!r}')
    finally:
        repo.close()


def _imported(tmp_path, source=None, wanted=None):
    """The ledger, with one spelling of the flag swapped for another.

    A book named after the spelling, because `import --new` will not write
    over one already there and a test below walks several spellings in a row.
    """
    slug = re.sub(r'[^a-z0-9]+', '-', (wanted or 'as written').lower())
    ledger = tmp_path / f'{slug}.txt'
    text = Path(LEDGER).read_text(encoding='utf-8')
    if source is not None:
        assert source in text, source
        text = text.replace(source, wanted)
    ledger.write_text(text, encoding='utf-8')

    book = tmp_path / f'{slug}.gnucash'
    return CliRunner().invoke(cli, ['import', '--new', str(book), str(ledger),
                                    '--include-business-objects']), book


class TestTheFlagDecidesWhatIsPosted:
    """Which is what makes the rest of this file worth asserting: read
    wrongly, the flag is not inert — the posting transaction differs."""

    def test_asked_for_the_two_lines_become_one_split(self, tmp_path):
        result, book = _imported(tmp_path)

        assert result.exit_code == 0, result.output
        assert _splits_of_the_posting(book, 'INV-ACC-001') == 2

    def test_refused_each_line_posts_its_own(self, tmp_path):
        result, book = _imported(tmp_path, 'accumulate: true',
                                 'accumulate: false')

        assert result.exit_code == 0, result.output
        assert _splits_of_the_posting(book, 'INV-ACC-001') == 3


class TestASpellingThatUsedToMeanFalse:
    """Each of these was compared against the string `true` and lost."""

    @pytest.mark.parametrize('spelling', ['accumulate: True',
                                          'accumulate: 1',
                                          'accumulate: yes'])
    def test_the_invoice_accumulates(self, tmp_path, spelling):
        result, book = _imported(tmp_path, 'accumulate: true', spelling)

        assert result.exit_code == 0, result.output
        assert _splits_of_the_posting(book, 'INV-ACC-001') == 2

    @pytest.mark.parametrize('spelling', ['accumulate: True',
                                          'accumulate: 1',
                                          'accumulate: yes'])
    def test_and_so_does_the_bill(self, tmp_path, spelling):
        """The bill path posts through its own copy of this code, so it
        answers the spelling on its own or not at all."""
        result, book = _imported(tmp_path, 'accumulate: true', spelling)

        assert result.exit_code == 0, result.output
        assert _splits_of_the_posting(book, 'BILL-ACC-001') == 2


class TestAnOpenBlocksTwoFlags:
    """Exit 0 is not the whole answer for these — the flag has to land.

    `placeholder:` and `tax_related:` are written `#True`/`#False` by the
    export and as words by a person, and only the first spelling reached
    `SetPlaceholder`. A bare `false` came back as the string `'false'` and
    SWIG refused the account with "Python object passed to a gboolean
    argument was not True or False" — so the account was missing from the
    book and everything naming it failed after it.
    """

    def _placeholder(self, book_path, name='Assets:Bank'):
        from infrastructure.gnucash.utils import find_account

        repo = GnuCashRepository(str(book_path))
        repo.open(SessionMode.READ_ONLY)
        try:
            account = find_account(repo.book.get_root_account(), name)
            assert account is not None, f'{name} is not in the book'
            return bool(account.GetPlaceholder())
        finally:
            repo.close()

    @pytest.mark.parametrize('spelling', ['true', 'True', '1', 'yes',
                                          '#True'])
    def test_a_word_for_true_makes_a_placeholder(self, tmp_path, spelling):
        result, book = _imported(tmp_path, 'placeholder: false',
                                 f'placeholder: {spelling}')

        assert result.exit_code == 0, result.output
        assert self._placeholder(book) is True

    @pytest.mark.parametrize('spelling', ['false', 'False', '0', 'no',
                                          '#False'])
    def test_and_a_word_for_false_does_not(self, tmp_path, spelling):
        result, book = _imported(tmp_path, 'placeholder: false',
                                 f'placeholder: {spelling}')

        assert result.exit_code == 0, result.output
        assert self._placeholder(book) is False


class TestAWordThatIsNeither:
    """One answer per key, and the same one: named, with both sets of words.

    Each of these is a key a different part of the importer reads, and each
    read the word its own way. `auto_apply_credit:` is the one that costs
    most — read as "not false", the typo below applied the owner's credit to
    the invoice, and the export afterwards wrote `from_credit:` payment
    blocks for money the file never asked to move.
    """

    @pytest.mark.parametrize('key,source', [
        ('accumulate', 'accumulate: true'),
        ('auto_apply_credit', 'auto_apply_credit: false'),
        ('from_credit', 'from_credit: false'),
        ('active', 'active: true'),
        ('closing', 'closing: true'),
        ('taxable', 'taxable: false'),
        ('placeholder', 'placeholder: false'),
        ('tax_related', 'tax_related: false'),
    ])
    def test_a_mistyped_flag_is_refused_by_name(self, tmp_path, key, source):
        result, _ = _imported(tmp_path, source, f'{key}: treu')

        assert result.exit_code != 0, result.output
        assert key in result.output, result.output
        assert 'neither true nor false' in result.output, result.output

    #: `from_credit:` is spelled only the two falsy ways here: the truthy
    #: ones do not say the same thing differently, they say the payment came
    #: out of the owner's credit — a block naming a `bank_account:` is then
    #: refused for contradicting itself, which is a different answer to a
    #: different question.
    @pytest.mark.parametrize('key,source,spelling', [
        (key, source, f'{key}: {word}')
        for key, source, words in [
            ('auto_apply_credit', 'auto_apply_credit: false',
             ('True', '1', 'yes', 'no', '0', 'False')),
            ('from_credit', 'from_credit: false', ('no', '0', 'False')),
            ('active', 'active: true',
             ('True', '1', 'yes', 'no', '0', 'False')),
            ('closing', 'closing: true',
             ('True', '1', 'yes', 'no', '0', 'False')),
            # An `open` block's two, whose spellings the exporter writes as
            # `#True`/`#False` and a person writes as words. Read straight
            # off `decode_value_from_string`, which knows `True` and `#True`
            # and nothing else, a bare `false` came back as the *string*
            # `'false'` — truthy — and reached `SetPlaceholder` as one.
            ('placeholder', 'placeholder: false',
             ('True', '1', 'yes', 'no', '0', 'False', '#True', '#False')),
            ('tax_related', 'tax_related: false',
             ('True', '1', 'yes', 'no', '0', 'False', '#True', '#False')),
        ]
        for word in words
    ])
    def test_and_the_words_it_does_take_are_taken(self, tmp_path, key, source,
                                                  spelling):
        """The other half of the same change. A key made strict that stopped
        accepting what it always accepted would be a worse fault than the one
        being fixed, and three of these keys were read leniently enough that
        every spelling here already worked."""
        result, _ = _imported(tmp_path, source, spelling)

        assert result.exit_code == 0, f'{spelling}: {result.output}'
