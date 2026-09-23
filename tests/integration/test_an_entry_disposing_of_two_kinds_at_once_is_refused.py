"""One entry cannot give up currency and shares at once and state one difference.

A disposal realizes the difference between what the units cost and what they
fetched, and the file says which split that difference is with `$residual$`. An
entry that draws down a currency cost basis *and* a security cost basis realizes
two differences, one of each kind, and the balance sheet keeps them apart —
`realized_gains_fx` and `realized_gains_other`, which a filer's return asks for
separately.

One split cannot be both. Counting it as either states the other as nothing, and
dividing it would be `import` writing a figure the file never gave, which is the
same rule that refuses a disposal giving no cost basis guid. So the entry is
refused as it lands, and the reader is told to write it as the two entries it is.

The book is otherwise whole: the transactions before the refused one are
imported, so the refusal is about that entry rather than about the file.
"""

from click.testing import CliRunner

from cli.main import cli

LEDGER = 'tests/fixtures/one_entry_disposing_of_currency_and_shares_at_once.txt'
REFUSAL = ('this transaction draws down a currency cost basis and a security '
           'cost basis at once')


def _imported(tmp_path):
    return CliRunner().invoke(
        cli, ['import', '--new', str(tmp_path / 'book.gnucash'), LEDGER])


def test_the_entry_is_refused(tmp_path):
    done = _imported(tmp_path)

    assert 'Errors:       1' in done.output, done.output
    assert REFUSAL in done.output, done.output


def test_it_says_why_one_split_cannot_state_both(tmp_path):
    done = _imported(tmp_path)

    assert ('because a balance sheet keeps a gain on currency apart from a '
            'gain on shares') in done.output, done.output


def test_it_says_what_to_write_instead(tmp_path):
    """Two entries, which is what the book would have had to say anyway."""
    done = _imported(tmp_path)

    assert ('Write it as two transactions: the shares sold for what they '
            'fetched, and the currency spent.') in done.output, done.output


def test_the_transactions_before_it_are_still_imported(tmp_path):
    """The refusal is about that entry, not about the file.

    Four of them, and the fourth gives up both kinds as well — it is imported,
    because every figure in it is stated outright and no split of it stands as
    the difference. What is refused is one split being asked to be two
    differences, not the two disposals sharing an entry.
    """
    done = _imported(tmp_path)

    assert 'Transactions: 4' in done.output, done.output
