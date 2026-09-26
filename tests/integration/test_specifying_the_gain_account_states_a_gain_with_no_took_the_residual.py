"""A book with no `took_the_residual` states its realized gain once its FX gain/loss account is specified.

`took_the_residual` records which split of a disposal is the exchange
difference. Nothing else in a book can answer that: in a balanced transaction
the same arithmetic holds for every split, and the account type does not
separate them either — a bank charge is an expense and so is a loss.

The key is new, and every book written before it has none. Those books were
imported from plaintext files that used `$residual$` correctly; `import`
calculated the amount, the amount is what was stored, and the release that
stored it had no key to write. Read now they state `realized_gains_fx: 0.00`
while their income statement states the difference their income account holds,
which is a figure that is simply wrong about them.

`--fx-gain-account` supplies the fact the book does not carry: the account a
book's exchange differences are booked to. A split still counts only where the
transaction is stated in the book's own currency and holds a disposal stating
the guid of the cost basis it drew on, so a rent line cannot claim a gain and a
foreign-stated transaction cannot add another currency's units into the total.

**With an FX gain/loss account specified, `took_the_residual` is not consulted
at all.** The two are not added together: a reader who states where their
differences are booked has answered the question for the whole book, and a page
that also counted whatever keys happened to be in it would answer differently
depending on which release imported which transaction. So a split carrying the
key on an account not specified is passed over, which is what
`test_the_option_replaces_the_key` holds.

The option is repeatable, because a book may keep its gains and its losses in
two accounts.
"""

import re
from pathlib import Path

from click.testing import CliRunner

from tests.conftest import _run
from tests.integration.text_report_pages import block_of, key_of

BOUGHT = 'tests/fixtures/a_cad_book_that_bought_a_thousand_usd.txt'
WITH_THE_KEY = 'tests/fixtures/the_thousand_usd_sold_with_the_gain_written_out.txt'
WITHOUT_THE_KEY = 'tests/fixtures/the_thousand_usd_sold_with_no_took_the_residual.txt'
WITH_A_CHARGE = ('tests/fixtures/'
                 'the_thousand_usd_sold_less_a_charge_with_no_took_the_residual.txt')
GAIN_ACCOUNT = 'Income:FX Gain'
CHARGE_ACCOUNT = 'Expenses:Bank charges'
AS_OF = '2026-12-31'

# What `realized_gains_fx` states in each case, in full. The figure alone
# cannot show which split was counted, and that is the whole subject here: the
# sale made 100.00 and paid a 10.00 charge, both on accounts a difference can
# land on, so what separates the cases is the account each split is on.
THE_GAIN = '\n'.join((
    '\t\trealized_gains_fx: 100.00',
    '\t\tsplits:',
    '\t\t\tsplit:',
    '\t\t\t\tdate: 2026-06-01',
    f'\t\t\t\taccount: "{GAIN_ACCOUNT}"',
    '\t\t\t\tamount: 100.00'))
THE_CHARGE = '\n'.join((
    '\t\trealized_gains_fx: -10.00',
    '\t\tsplits:',
    '\t\t\tsplit:',
    '\t\t\t\tdate: 2026-06-01',
    f'\t\t\t\taccount: "{CHARGE_ACCOUNT}"',
    '\t\t\t\tamount: -10.00'))
BOTH_OF_THEM = '\n'.join((
    '\t\trealized_gains_fx: 90.00',
    '\t\tsplits:',
    '\t\t\tsplit:',
    '\t\t\t\tdate: 2026-06-01',
    f'\t\t\t\taccount: "{CHARGE_ACCOUNT}"',
    '\t\t\t\tamount: -10.00',
    '\t\t\tsplit:',
    '\t\t\t\tdate: 2026-06-01',
    f'\t\t\t\taccount: "{GAIN_ACCOUNT}"',
    '\t\t\t\tamount: 100.00'))
NOTHING_COUNTED = '\n'.join((
    '\t\trealized_gains_fx: 0.00',
    '\t\tsplits: # there is no split'))


def _sold(runner, tmp_path, sale, name):
    """The purchase, then `sale` on top of it, in a book of its own."""
    book = tmp_path / f'{name}.gnucash'
    bought = _run(runner, 'import', '--new', str(book), BOUGHT)
    assert bought.exit_code == 0, bought.output

    listing = _run(runner, 'fx-balances', str(book))
    assert listing.exit_code == 0, listing.output
    found = re.search(r'\b([0-9a-f]{32})\b', listing.output)
    assert found, listing.output

    ledger = tmp_path / f'{name}.txt'
    ledger.write_text(
        Path(sale).read_text(encoding='utf-8').replace('{usd_basis}', found.group(1)),
        encoding='utf-8')
    landed = _run(runner, 'import', str(book), str(ledger))
    assert landed.exit_code == 0, landed.output
    return book


def _page(runner, book, *flags):
    drawn = _run(runner, 'balance-sheet', str(book), '--as-of', AS_OF, *flags)
    assert drawn.exit_code == 0, drawn.output
    return drawn.output


def test_a_book_with_no_took_the_residual_states_nothing_realized(tmp_path):
    """What the book says on its own, and why the option exists.

    Not an assertion that this is right for the book — it is the wrong answer
    for a book that realized 100.00 — but the answer the page must state while
    nothing in the book says which split holds the exchange difference.
    """
    runner = CliRunner()
    book = _sold(runner, tmp_path, WITHOUT_THE_KEY, 'without_the_key')

    assert block_of(_page(runner, book), 'realized_gains_fx') == NOTHING_COUNTED


def test_specifying_the_account_states_the_gain(tmp_path):
    """The same sale a book carrying `took_the_residual` states as 100.00."""
    runner = CliRunner()
    book_without_the_key = _sold(runner, tmp_path, WITHOUT_THE_KEY, 'without_the_key')
    book_with_the_key = _sold(runner, tmp_path, WITH_THE_KEY, 'with_the_key')

    page = _page(runner, book_without_the_key, '--fx-gain-account', GAIN_ACCOUNT)

    assert block_of(page, 'realized_gains_fx') == THE_GAIN
    assert key_of(page, 'total_realized_gains') == '100.00 CAD'
    assert block_of(page, 'realized_gains_fx') == block_of(
        _page(runner, book_with_the_key), 'realized_gains_fx')


def test_a_charge_beside_the_difference_is_left_out(tmp_path):
    """The whole reason the account is specified rather than inferred.

    The disposal pays a 10.00 bank charge and leaves a 100.00 difference, both
    on accounts a difference can land on. Stating the income account takes the
    difference and not the charge; counting every income and expense split of
    the transaction would state 110.00.
    """
    runner = CliRunner()
    book = _sold(runner, tmp_path, WITH_A_CHARGE, 'with_a_charge')

    page = _page(runner, book, '--fx-gain-account', GAIN_ACCOUNT)

    assert block_of(page, 'realized_gains_fx') == THE_GAIN


def test_a_page_in_another_currency_says_the_option_is_not_applied(tmp_path):
    """Silence here would read as "your account was counted and came to 0.00".

    A realized gain is measured from the cost bases, and those are recorded in
    the book's own currency, so a page asked for in a second currency states no
    realized gain at all — there is nothing for the account to apply to. The
    option is accepted and does nothing, which is exactly the shape that needs
    saying out loud: the reader gets a page with no realized gain on it and no
    indication that the option they passed was set aside.
    """
    runner = CliRunner()
    book = _sold(runner, tmp_path, WITHOUT_THE_KEY, 'in_another_currency')

    drawn = _run(runner, 'balance-sheet', str(book), '--as-of', AS_OF,
                 '--currency', 'HKD', '--fx-gain-account', GAIN_ACCOUNT)

    assert drawn.exit_code == 0, drawn.output
    assert '--fx-gain-account is not applied to a page in HKD' in drawn.output, \
        drawn.output
    assert 'recorded in CAD' in drawn.output, drawn.output


def test_an_account_that_cannot_hold_a_difference_is_warned_about(tmp_path):
    """A bank account resolves, counts nothing, and would say nothing.

    An exchange difference is booked to income or expense — a split on a bank
    or a receivable moved money rather than measuring anything — so a
    balance-sheet account here can never count. And because the option
    replaces `took_the_residual` rather than adding to it, passing one turns a
    book that states 100.00 on its own into a book that states 0.00, at exit 0.
    That is the same silent wrong answer the unknown-account warning exists to
    prevent, reached by a different mistake, so it gets its own sentence.
    """
    runner = CliRunner()
    book = _sold(runner, tmp_path, WITH_THE_KEY, 'wrong_type')

    drawn = _run(runner, 'balance-sheet', str(book), '--as-of', AS_OF,
                 '--fx-gain-account', 'Assets:USD Bank')

    assert drawn.exit_code == 0, drawn.output
    assert 'is not an income or expense account' in drawn.output, drawn.output
    # And the figure it leaves: the book's own key is not consulted once an
    # account is passed, so the page states nothing realized.
    assert block_of(drawn.output, 'realized_gains_fx') == '\n'.join((
        '\t\trealized_gains_fx: 0.00',
        '\t\tsplits: # there is no split')), drawn.output


def test_an_empty_account_is_warned_about_like_any_other_the_book_lacks(tmp_path):
    """`""` is a path of no segments, which resolves to the root account.

    So the unknown-account check found something and said nothing, and the
    option then counted nothing — `realized_gains_fx: 0.00` at exit 0 on a book
    that realized 100.00, which is the silent wrong answer the check exists to
    prevent.
    """
    runner = CliRunner()
    book = _sold(runner, tmp_path, WITHOUT_THE_KEY, 'empty_account')

    drawn = _run(runner, 'balance-sheet', str(book), '--as-of', AS_OF,
                 '--fx-gain-account', '')

    assert drawn.exit_code == 0, drawn.output
    assert 'matches no account in this book' in drawn.output, drawn.output


def test_the_account_specified_is_the_one_believed(tmp_path):
    """The option states what the book does not know, so it is believed.

    Stating an account that holds something other than an exchange difference
    is a reader saying their differences are booked there. Nothing in the book
    contradicts it, which is why the account has to come from someone who knows
    the book.
    """
    runner = CliRunner()
    book = _sold(runner, tmp_path, WITH_A_CHARGE, 'with_a_charge')

    page = _page(runner, book, '--fx-gain-account', CHARGE_ACCOUNT)

    assert block_of(page, 'realized_gains_fx') == THE_CHARGE


def test_two_accounts_may_be_specified(tmp_path):
    """A book that keeps its gains and its losses apart states both accounts."""
    runner = CliRunner()
    book = _sold(runner, tmp_path, WITH_A_CHARGE, 'with_a_charge')

    page = _page(runner, book,
                 '--fx-gain-account', GAIN_ACCOUNT,
                 '--fx-gain-account', CHARGE_ACCOUNT)

    assert block_of(page, 'realized_gains_fx') == BOTH_OF_THEM


def test_the_working_states_the_gain_it_counted(tmp_path):
    """A figure counted without its working would be taken on trust."""
    runner = CliRunner()
    book = _sold(runner, tmp_path, WITHOUT_THE_KEY, 'without_the_key')

    page = _page(runner, book, '--fx-gain-account', GAIN_ACCOUNT)

    assert block_of(page, 'realized_gains_fx') == THE_GAIN, page


def test_report_draws_the_same_sheet_as_balance_sheet(tmp_path):
    """`report` draws this page too, so it takes the option or the two disagree."""
    runner = CliRunner()
    book = _sold(runner, tmp_path, WITHOUT_THE_KEY, 'without_the_key')

    drawn = _run(runner, 'report', str(book), 'balance-sheet',
                 '--fiscal-year-end', AS_OF, '--as-of', AS_OF,
                 '--fx-gain-account', GAIN_ACCOUNT)
    assert drawn.exit_code == 0, drawn.output

    assert block_of(drawn.output, 'realized_gains_fx') == THE_GAIN


def test_a_book_carrying_the_key_needs_no_option(tmp_path):
    """A book carrying `took_the_residual` states its gain with nothing added."""
    runner = CliRunner()
    book = _sold(runner, tmp_path, WITH_THE_KEY, 'with_the_key')

    assert block_of(_page(runner, book), 'realized_gains_fx') == THE_GAIN


def test_the_option_states_the_same_account_the_key_is_on(tmp_path):
    """Specifying the very account `took_the_residual` is already on changes nothing."""
    runner = CliRunner()
    book = _sold(runner, tmp_path, WITH_THE_KEY, 'with_the_key')

    assert block_of(_page(runner, book, '--fx-gain-account', GAIN_ACCOUNT),
                    'realized_gains_fx') == THE_GAIN


def test_the_option_replaces_the_key(tmp_path):
    """`took_the_residual` is not consulted at all once an account is specified.

    The book's own gain split carries `took_the_residual` and is on
    `Income:FX Gain`. Specifying a different account leaves that split
    uncounted. Had the two been added together instead of one replacing the
    other, the page would still state 100.00, and what it showed would depend
    on which release imported the transaction rather than on what was asked
    for.
    """
    runner = CliRunner()
    book = _sold(runner, tmp_path, WITH_THE_KEY, 'with_the_key')

    assert block_of(_page(runner, book, '--fx-gain-account', CHARGE_ACCOUNT),
                    'realized_gains_fx') == NOTHING_COUNTED


def test_an_account_the_book_does_not_have_is_warned_about(tmp_path):
    """A misspelt name would otherwise turn a correct figure into 0.00 in silence.

    The option replaces `took_the_residual` rather than adding to it, so a name
    the book has no account for counts nothing and the page states 0.00 — on a
    book that carries the key and realized 100.00, at exit 0. The run says so on
    stderr instead, and still prints the page: an account absent from the book
    is not the same as one that exists and has no qualifying split yet, which is
    what a sheet dated before that account was opened looks like.
    """
    runner = CliRunner()
    book = _sold(runner, tmp_path, WITH_THE_KEY, 'with_the_key')

    drawn = _run(runner, 'balance-sheet', str(book), '--as-of', AS_OF,
                 '--fx-gain-account', 'Income:FX gain')
    assert drawn.exit_code == 0, drawn.output

    assert block_of(drawn.output, 'realized_gains_fx') == NOTHING_COUNTED
    assert 'Income:FX gain' in drawn.output
    assert 'matches no account in this book' in drawn.output
