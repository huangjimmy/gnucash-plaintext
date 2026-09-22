"""`fx-balances` states what the accounts hold, beside what the cost bases say.

A cost basis balance and an account balance answer different questions. A cost
basis balance is how much of *one split's* currency has not been sold; an
account balance is what an account holds. They are one figure where every
disposal gave the cost basis it drew on, and they part company where currency
left without saying which basis it came out of.

Reading the listing alone, a reader could not see that. The cost basis rows say
10,000.00 USD is still against the book's one US dollar cost basis, and nothing
on the page said the accounts hold 4,980.00 — that had to be worked out from a
balance sheet, or from the split values behind another key entirely.

It is a block of its own rather than a column on each row, because the two do
not line up: a cost basis sits on one split's account, and the currency it
brought in can since have moved across several. Here the US dollars sit in a
bank and a loan, and neither belongs in the other's row.
"""

from click.testing import CliRunner

from cli.main import cli

FIXTURE = ('tests/fixtures/'
           'a_cad_book_with_usd_hkd_and_shares_priced_in_its_price_database.txt')


def _listing(tmp_path, *extra):
    book = tmp_path / 'book.gnucash'
    runner = CliRunner()
    made = runner.invoke(cli, ['import', '--new', str(book), FIXTURE])
    assert made.exit_code == 0, made.output

    result = runner.invoke(cli, ['fx-balances', str(book), *extra])
    assert result.exit_code == 0, result.output
    return result.output


def test_each_account_is_listed_with_what_it_holds(tmp_path):
    """Two US dollar accounts, each on its own row with its own sign."""
    listing = _listing(tmp_path)
    lines = [line.rstrip() for line in listing.splitlines()]

    assert any(line.startswith('Assets:USD Bank') and line.endswith('7,480.00 USD')
               for line in lines), listing
    assert any(line.startswith('Liabilities:USD Loan')
               and line.endswith('-2,500.00 USD') for line in lines), listing
    assert any(line.startswith('Assets:HKD Bank') and line.endswith('5,500.00 HKD')
               for line in lines), listing


def test_each_currency_is_totalled_with_what_is_held_apart_from_what_is_owed(tmp_path):
    """Not netted: 7,480.00 held and 2,500.00 owed are two facts, not 4,980.00.

    A cost basis balance is a magnitude whichever side it sits on, so a netted
    account total cannot be read against one. Kept apart, each side can be.
    """
    lines = [line.rstrip() for line in _listing(tmp_path).splitlines()]

    assert 'Total USD held in accounts: 7,480.00 USD' in lines, lines
    assert 'Total USD owed on accounts: 2,500.00 USD' in lines, lines
    assert 'Total HKD held in accounts: 5,500.00 HKD' in lines, lines
    # Nothing is owed in Hong Kong dollars, so no line claims otherwise.
    assert not any(line.startswith('Total HKD owed') for line in lines), lines


def test_it_is_stated_beside_the_cost_basis_totals_and_they_differ(tmp_path):
    """The whole point: on this book the two do not agree, and the page says so.

    10,000.00 USD was bought and a cost basis opened for it. The dollars have
    since gone out to buy shares, repay a loan and pay interest — all in
    transactions stated wholly in US dollars, and not one of them gives that
    cost basis's guid — so the basis was never drawn down. A reader now sees
    both figures without leaving the listing.
    """
    lines = [line.rstrip() for line in _listing(tmp_path).splitlines()]

    assert 'Total USD cost basis balance: 10,000.00 USD' in lines, lines
    assert 'Total USD held in accounts: 7,480.00 USD' in lines, lines
    # The cost bases come first: the listing is about them, and what the
    # accounts hold is stated against it.
    assert (lines.index('Total USD cost basis balance: 10,000.00 USD')
            < lines.index('Total USD held in accounts: 7,480.00 USD')), lines


def test_a_currency_filter_narrows_the_block_too(tmp_path):
    """`--currency` narrows what is shown, so both halves narrow together.

    A filtered listing that still stated every currency's holdings would be
    answering a question the reader did not ask, and the two halves would
    describe different books.
    """
    lines = [line.rstrip() for line in _listing(tmp_path, '--currency', 'USD').splitlines()]

    assert 'Total USD held in accounts: 7,480.00 USD' in lines, lines
    assert not any(line.startswith('Total HKD held') for line in lines), lines
    assert not any(line.startswith('Assets:HKD Bank') for line in lines), lines


def test_a_book_with_no_cost_basis_still_says_what_its_accounts_hold(tmp_path):
    """The book that needs this block most is the one it was not printed for.

    `No foreign-currency cost bases found.` returned before the holdings were
    reached, so a book whose bases are all spent, one filtered to a currency
    with none, and one that never opened any — imported before cost bases
    existed, or holding a stock bought with foreign currency — were told
    nothing about the money they still hold, which is the whole of what this
    command can tell them.
    """
    lines = [line.rstrip()
             for line in _listing(tmp_path, '--currency', 'GBP').splitlines()]

    assert 'No foreign-currency cost bases found.' in lines, lines
    # GBP narrows both halves, and the book holds none, so the block says
    # nothing rather than printing an empty table.
    assert not any('in accounts' in line or 'on accounts' in line
                   for line in lines), lines


def test_a_filter_leaving_no_basis_still_states_the_holdings_it_covers(tmp_path):
    """And where the filtered currency *is* held, the holdings are stated.

    `--with-balance-only` on a book whose bases are all drawn to nothing leaves
    no row, and the accounts still hold what they hold.
    """
    lines = [line.rstrip() for line
             in _listing(tmp_path, '--with-balance-only', '--currency', 'HKD').splitlines()]

    assert 'Total HKD held in accounts: 5,500.00 HKD' in lines, lines
