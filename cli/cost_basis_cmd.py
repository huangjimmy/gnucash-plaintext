"""
CLI command listing foreign-currency cost bases (Q-035).

Every split that brought foreign currency into the book — an invoice's A/R
split, a bill's A/P split, currency bought or borrowed — establishes a **cost
basis**: so many units, at what they cost in the book's own currency. Selling that
currency picks one or more of these cost bases by guid, so a user writing a sale
needs to see what cost bases exist, what each cost, and how much each has left.

The balance of a cost basis is not the balance of an account: it is how much
of *one split's* currency, at *that split's* cost, has not yet been sold. One
bank account can hold currency from several cost bases at different costs, and a
paid invoice's cost basis stays listed after the money has moved to the bank.
"""

from fractions import Fraction

import click

from infrastructure.gnucash.utils import exact_text, money_text
from repositories.gnucash_repository import GnuCashRepository, SessionMode
from services.foreign_currency import (
    BASE_CURRENCY,
    COST_BASIS_BALANCE_KEY,
    book_keeps_cost_bases,
    cost_bases,
    foreign_currency_account_balances,
    pending_disposals,
    verify_cost_bases,
)


def _grouped(figure: str) -> str:
    """Thousands separators in the integer part, left as exact text.

    A figure that no decimal states exactly arrives as the fraction it is —
    `10/57 CAD/HKD`, a rate of 1/5.7 — and is passed through untouched. There
    is no integer part to group, and treating one as a number is how this
    listing came to crash on a book holding a third currency.
    """
    if '/' in figure:
        return figure
    sign = '-' if figure.startswith('-') else ''
    body = figure.lstrip('-')
    whole, _, decimals = body.partition('.')
    whole = f'{int(whole):,}'
    return sign + whole + ('.' + decimals if decimals else '')


def _format_amount(value, unit: int) -> str:
    """An amount at its own currency's decimals — 1,200.00 USD, 103 JPY.

    The decimals come from the commodity's smallest unit, so a currency without
    a minor unit is not printed with two invented ones.
    """
    return _grouped(money_text(value, unit))


def _format_exactly(value, unit: int) -> str:
    """The same, except that a figure the unit cannot express is written as it
    is rather than rounded into it.

    For figures printed *because* they differ: rounding two of those to the
    cent prints the same number twice and claims they disagree.
    """
    if (value * unit).denominator != 1:
        return _grouped(exact_text(value))
    return _format_amount(value, unit)


def _format_cost_basis_balance(row) -> str:
    """A cost basis this tool never wrote a balance for reads `none recorded`, not
    a number: how much of it is still unsold is not known, and its full amount
    would be a guess that could re-open currency already sold.

    `malformed` is the whole cost basis, not this column: it is what a row says when
    reading the cost basis at all raised — a stored *cost* that will not parse — so
    there is no balance to print and no cost either.

    A balance that will not parse reads `none recorded`, the same as one never
    written. Nothing can be sold against either, which is what this column is
    for; that the two are not the same thing is `--verify-costs`'s to say, and
    it quotes the text the split actually holds
    (`test_verify_costs.py::test_a_balance_that_will_not_parse_is_reported_not_read_as_absent`).
    """
    if row.get('malformed'):
        return 'malformed'
    if row['balance'] is None:
        return 'none recorded'
    return f"{_format_amount(row['balance'], row['unit'])} {row['currency']}"


def _format_cost(value, currency: str) -> str:
    """The cost with its direction spelled out — `1.35 CAD/USD`, CAD per unit of
    the currency held. A bare number leaves the reader to guess which way round
    it goes, and both readings are plausible.

    A rate has no smallest unit of its own, so it is written at however many
    decimals it needs rather than rounded to the currency's.
    """
    if value is None:
        return '—'
    return f'{_grouped(exact_text(value))} {BASE_CURRENCY}/{currency}'


def _finish_verifying(verified, pending: int = 0) -> None:
    """Report what the check found and set the exit code, once.

    Both endings of the listing — the empty one a filter can leave and the
    ordinary one — finish here, so the report and the exit code cannot drift
    apart between them.
    """
    if verified is None:
        return
    click.echo('')
    _report_disagreements(verified['findings'], verified['checked'],
                          pending)
    _report_currency_totals(verified.get('currency_totals') or [])
    if verified['findings']:
        raise SystemExit(1)


def _report_currency_totals(totals) -> None:
    """Say which currency does not add up, and by how much.

    A warning, and it does not set the exit code. Every cost basis here passes the
    questions asked of it one at a time — that is what makes this worth
    printing and also what makes it the wrong thing to refuse over: the book is
    readable, its figures are the ones it holds, and what put the two sides out
    of step is not something the book records. The reader is the one who can
    say which of them is right.

    Both figures and the difference, because the difference alone says nothing
    about where to look: 80.00 short of 200.00 is a cost basis that lost its
    balance, and 80.00 over is one that gained currency that never arrived.
    """
    for row in totals:
        currency = row['currency']
        unit = row['unit']
        short = row['difference'] > 0
        click.echo('')
        click.echo(
            f"warning: the {currency} cost bases hold "
            f"{_format_amount(row['held'], unit)} {currency} between them, "
            f"and the ledger says {_format_amount(row['arrived'], unit)} "
            f"{currency} arrived and {_format_amount(row['sold'], unit)} "
            f"{currency} was sold against a cost basis — leaving "
            f"{_format_amount(row['ledger'], unit)} {currency}.")
        click.echo(
            f"  {_format_amount(abs(row['difference']), unit)} {currency} is "
            + ('accounted for by no cost basis. A balance was lowered with no sale '
               'to account for it, or a sale was undone and less was put back than '
               'it had drawn down.'
               if short else
               'held by the cost bases beyond what arrived. A balance was raised '
               'without a sale being deleted, or one was stated too high.'))
        click.echo(
            '  Nothing is refused: every cost basis is within its own bounds, and '
            'which side is right is not something the book records.')


def _report_malformed(malformed: int, verified) -> None:
    """Say that a cost basis could not be read, wherever the listing ends up.

    Over the whole book rather than what a filter left, and printed on the
    empty listing too: `--currency HKD` on a USD book said "no cost bases
    found" and never mentioned that one of them is malformed, which is the
    one thing that listing could not tell the reader itself. Silent when
    `--verify-costs` is on, because the report below says the same thing with
    the reason attached.
    """
    if malformed and verified is None:
        click.echo(
            f'{malformed} cost basis(es) could not be read: their own figures '
            f'do not parse. Run with `--verify-costs` for the reason and the '
            f'split each is on.')


def _report_disagreements(disagreements, checked: int, pending: int = 0) -> None:
    """What `--verify-costs` found, said in full.

    Every disagreement is reported, not the first — the run gathers them all
    and the exit code comes at the end, so one bad cost basis never hides the rest.

    Each is printed with the whole computation behind it: both guids to open
    the book at, the amount and value the ledger carries, its balance, the
    rate the transaction converted at with each base-currency
    split measured against it, every factor of the derivation, and both
    answers with which one is used. Which figure is wrong is the reader's
    judgement; showing only that two differ leaves them to re-derive it by
    hand. A cost basis that could not be read at all carries its traceback for the
    same reason.
    """
    # A disposal pending its cost basis is not a disagreement: the file said
    # its cost basis is not decided, and it is counted, not reported as wrong.
    still = f' {pending} disposal(s) are pending their cost basis.' if pending else ''
    if not disagreements:
        click.echo(f'Checked {checked} cost basis(es): every cost agrees with '
                   f'the figures it is derived from.{still}')
        return

    # "and found" rather than "of which", because the two numbers do not count
    # the same things. `checked` is the cost bases in the book; a finding can
    # be about a split that is not one at all — a balance stored where nothing
    # reads it, a sale drawing on a split that is no cost basis — so a book with
    # one stranded balance and no cost bases read "Checked 0 cost basis(es); 1
    # disagree".
    click.echo(f'Checked {checked} cost basis(es), and found '
               f'{len(disagreements)} thing(s) that do not hold:{still}')
    for row in disagreements:
        click.echo('')
        click.echo(f"{row['date']}  {row['account']}")
        if row['description']:
            click.echo(f"    {row['description']}")
        click.echo(f"    split guid         {row['guid']}")
        click.echo(f"    tx guid            {row['tx_guid']}")
        if 'amount' in row:
            # Exactly, every one of them: these figures are printed because
            # something about this cost basis is wrong, and a rounded one can hide
            # the very difference being reported — the balance line read
            # "100.00" two lines above a finding about 100001/1000.
            click.echo(f"    amount             "
                       f"{_format_exactly(row['amount'], row['unit'])} {row['currency']}")
            click.echo(f"    value              "
                       f"{_format_exactly(row['value'], row['tx_unit'])} "
                       f"{row['tx_currency']}   (the transaction's currency)")
            if row['balance'] is not None:
                click.echo(f"    cost basis balance "
                           f"{_format_exactly(row['balance'], row['unit'])} "
                           f"{row['currency']}")
            if row['malformed_balance']:
                click.echo(f"    cost basis balance "
                           f"{row['malformed_balance']!r}   (does not parse)")
            if row['tx_rate'] is not None:
                click.echo(f"    transaction rate   {exact_text(row['tx_rate'])} "
                           f"{BASE_CURRENCY}/{row['tx_currency']}")
            # The figures the rate was added up from, so a reader can see what
            # the cost came from. Where an account is kept finer than its
            # currency, say so: three decimals on a CAD figure otherwise read
            # as a mistake rather than as the unit that account is held to.
            for account, amount, value, unit, currency_unit in row['base_figures']:
                held = ('' if unit == currency_unit else
                        f'  (account held to '
                        f'{_format_exactly(Fraction(1, unit), unit)})')
                click.echo(f"    {account}: "
                           f"{_format_exactly(amount, unit)} {BASE_CURRENCY} "
                           f"for {_format_exactly(value, row['tx_unit'])} "
                           f"{row['tx_currency']}{held}")
            # The factors the derivation multiplied, as it multiplied them.
            # Nothing is added for a step the computation did not take: a
            # transaction in the book's own currency has one factor, and
            # printing a second one at 1 would report arithmetic that never
            # happened.
            for label, factor in row['factors']:
                if factor is None:
                    shown = f'— (no {BASE_CURRENCY} figure in the transaction)'
                else:
                    shown = exact_text(factor)
                click.echo(f'    {label:<18} {shown}')
            click.echo(f"    computed cost      "
                       f"{_format_cost(row['derived'], row['currency'])}")
            click.echo(f"    stored cost        "
                       f"{_format_cost(row['stored'], row['currency'])}")
            click.echo(f"    used               "
                       f"{_format_cost(row['used'], row['currency'])}")
        for problem in row['problems']:
            click.echo(f'    - {problem}')
        if row.get('traceback'):
            for line in row['traceback'].rstrip().splitlines():
                click.echo(f'    | {line}')
    click.echo('')


def _report_pending(pending) -> None:
    """The disposals with `cost_basis_split_guid: $pending$`, per currency.

    Each drew on no cost basis, so the cost bases above offer what they add up
    to beyond what the accounts hold, until an edit states the cost basis each
    draws on.
    """
    for code in sorted({row['currency'] for row in pending}):
        mine = [row for row in pending if row['currency'] == code]
        total = sum((row['amount'] for row in mine), Fraction(0))
        click.echo(f'{len(mine)} disposal(s) pending their cost basis: '
                   f"{_format_amount(total, mine[0]['unit'])} {code}. No cost basis "
                   f'is drawn down for them until an edit states the one each draws on.')
        for row in mine:
            click.echo(f"{row['date']}   {row['account']}   "
                       f"{_format_amount(row['amount'], row['unit'])} {code}   "
                       f"{row['description']}")


def _report_account_balances(holdings, currency):
    """What the accounts hold of each foreign currency, under the cost basis totals.

    A block of its own rather than a column on each row, because the two do not
    line up: a cost basis sits on one split's account, and the currency it
    brought in can since have moved across several. A receivable's cost basis
    whose money is now in two banks has no one account to put in its row.

    **Held and owed are totalled apart**, because they are different facts and
    adding them answers for neither. A cost basis balance is stored as a
    magnitude on both sides — `open_cost_basis_balance` writes
    `abs(split.GetAmount())` — while an account's balance carries its sign, so
    a liability's −1,000.00 against a basis of 1,000.00 read as a 2,000.00
    disagreement on a book where every figure is right.
    `us_dollars_borrowed_into_a_canadian_bank.txt` is that book. The balance
    sheet keeps the two sides apart for the same reason.

    **What compares with what**: the cost basis total above covers both sides,
    being a sum of magnitudes, so it is read against the side those bases are
    on. Where they agree, every disposal stated the basis it drew on. Where the
    held total falls short of a basis on the asset side, currency left without
    saying which basis it came out of. A currency owed with no basis against it
    is a third thing again — a borrowing stated wholly in that currency opens
    none — and it shows here as an owed total with nothing above it to match.
    """
    if currency:
        holdings = [row for row in holdings if row['currency'] == currency.upper()]

    # Nothing to say where the book holds no foreign currency at all, which a
    # book with no cost bases can be: this block is printed for such a book
    # precisely because "what the accounts hold" is the whole of what can be
    # said about it, and on a book holding nothing that is nothing.
    if not holdings:
        return

    click.echo('')
    width = max(len('ACCOUNT'),
                max((len(row['account']) for row in holdings), default=0))
    header = f"{'ACCOUNT':<{width}} {'BALANCE':>18}"
    click.echo(header)
    click.echo('-' * len(header))

    held = {}
    owed = {}
    units = {}
    for row in sorted(holdings, key=lambda row: (row['currency'], row['account'])):
        shown = _format_amount(row['balance'], row['unit']) + ' ' + row['currency']
        click.echo(f"{row['account']:<{width}} {shown:>18}")
        # By sign, which is which side the money is on — the same division the
        # cost bases are kept in, and for the same reason: a book can hold a
        # currency and owe it at once, and one total for both matches neither.
        side = owed if row['balance'] < 0 else held
        side[row['currency']] = side.get(row['currency'], 0) + abs(row['balance'])
        units[row['currency']] = row['unit']

    click.echo('')
    for code in sorted(set(held) | set(owed)):
        if code in held:
            click.echo(f'Total {code} held in accounts: '
                       f'{_format_amount(held[code], units[code])} {code}')
        if code in owed:
            click.echo(f'Total {code} owed on accounts: '
                       f'{_format_amount(owed[code], units[code])} {code}')


@click.command('fx-balances')
@click.argument('gnucash_file', type=click.Path(exists=True))
@click.option('--currency', 'currency', default=None,
              help='Only list cost bases in this currency (e.g. USD).')
@click.option('--with-balance-only', is_flag=True,
              help='Show only cost bases with a balance above zero — hiding both '
                   'the exhausted ones and any reading `none recorded`.')
@click.option('--verify-costs', is_flag=True,
              help='Check each cost against the ledger figures it is derived '
                   'from, and report any that disagree (exits 1 if any do).')
def fx_balances(gnucash_file, currency, with_balance_only, verify_costs):
    """
    List every foreign-currency cost basis with its cost and its balance.

    Each row is one split: its guid (what a sale names to pick that cost basis), the
    transaction it came from, what one unit cost in the book's currency, how
    much currency it brought in, and how much of it is left to sell.

    To sell foreign currency, write the sale's foreign-currency split naming
    the cost basis it is measured against:

    \b
        2026-03-01 * "Sell 200 USD"
            currency.mnemonic: "CAD"
            Assets:Bank:USD -200.00 USD
                cost_basis_split_guid: "<guid from this listing>"
            Assets:Bank:CAD 278.00 CAD
            Income:FX Gain $residual$ CAD

    A sale measured against two cost bases carries two USD splits, each stating one,
    and each split's amount is how much of that cost basis it uses.

    `--verify-costs` checks each cost against the ledger it is derived from and
    reports what disagrees: that no balance is above what its cost basis brought in
    or below zero, and that a stored `cost_basis_cost` parses and
    agrees with the transaction. Both are exact comparisons against figures the
    book already holds; rates are not checked, because a rate runs forward into
    a rounded figure and the figure does not run back into the rate. The whole
    book is checked and the exit code comes at the end, so one bad cost basis hides
    nothing.

    \b
    Examples:
      gnucash-plaintext fx-balances ledger.gnucash
      gnucash-plaintext fx-balances ledger.gnucash --currency USD
      gnucash-plaintext fx-balances ledger.gnucash --with-balance-only
      gnucash-plaintext fx-balances ledger.gnucash --verify-costs
    """
    repo = GnuCashRepository(gnucash_file)
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        keeps = book_keeps_cost_bases(repo.book)
        rows = cost_bases(repo.book)
        # Gathered here rather than at render time: the book is closed below,
        # and nothing read from it may be used afterwards (CLAUDE.md §26).
        holdings = foreign_currency_account_balances(repo.book)
        pending = [row for row in pending_disposals(repo.book)
                   if not currency or row['currency'] == currency.upper()]
        verified = verify_cost_bases(repo.book) if verify_costs and keeps else None
    finally:
        repo.close()

    # A book that keeps no cost bases has none to list or check (Q-049). What
    # its accounts hold is still what a reader came for.
    if not keeps:
        click.echo('This book keeps no cost bases (`cost_bases: "off"` in its '
                   'company block): its foreign currency is kept as GnuCash '
                   'keeps it.')
        _report_account_balances(holdings, currency)
        return

    malformed = sum(1 for row in rows if row.get('malformed'))

    if currency:
        wanted = currency.upper()
        rows = [row for row in rows if row['currency'] == wanted]
    if with_balance_only:
        # A cost basis with nothing left cannot be sold against, so it is left out.
        rows = [row for row in rows
                if row['balance'] is not None and row['balance'] > 0]

    if not rows:
        click.echo('No foreign-currency cost bases found.')
        # And then what the accounts hold, which is the whole of what this
        # command can tell a reader about such a book — so it is printed here
        # above all, not only where a cost basis survived the filters. A book
        # whose bases are all spent to nothing, one filtered to a currency that
        # has none, and one that never opened any (imported before cost bases
        # existed, or holding a stock bought with foreign currency) all reach
        # this line still holding money, and the block that says how much was
        # the one thing they were not shown.
        _report_pending(pending)
        _report_account_balances(holdings, currency)
        _report_malformed(malformed, verified)
        _finish_verifying(verified, len(pending))
        return

    # Size the account column to the longest name rather than truncating it:
    # a clipped account path ("Liabilities:Accounts Payable U") does not say
    # which account the cost basis is on, which is half of what the row is for.
    width = max(len('ACCOUNT'), max(len(row['account']) for row in rows))
    header = (f"{'DATE':<12} {'SPLIT GUID':<34} {'ACCOUNT':<{width}} "
              f"{'COST':>18} {'BROUGHT IN':>14} {'COST BASIS BALANCE':>18}")
    click.echo(header)
    click.echo('-' * len(header))
    for row in rows:
        click.echo(
            f"{row['date']:<12} {row['guid']:<34} {row['account']:<{width}} "
            f"{_format_cost(row['cost'], row['currency']):>18} "
            f"{_format_amount(row['brought_in'], row['unit']) + ' ' + row['currency']:>14} "
            f"{_format_cost_basis_balance(row):>18}"
        )
        if row['description']:
            click.echo(f"{'':<12} {row['description']}")

    click.echo('')
    totals = {}
    units = {}
    no_balance_recorded = 0
    for row in rows:
        if row.get('malformed'):
            continue
        if row['balance'] is None:
            no_balance_recorded += 1
            continue
        totals[row['currency']] = totals.get(row['currency'], 0) + row['balance']
        units[row['currency']] = row['unit']
    for code in sorted(totals):
        click.echo(f'Total {code} cost basis balance: '
                   f'{_format_amount(totals[code], units[code])} {code}')
    if no_balance_recorded:
        click.echo(
            f'{no_balance_recorded} cost basis(es) have no balance recorded '
            f'and are excluded from the total: this tool never wrote one for '
            f'them, so how much of their currency is still unsold is not '
            f'known. To record one, state `{COST_BASIS_BALANCE_KEY}:` on that '
            f'split in an import file.')
    _report_pending(pending)

    _report_account_balances(holdings, currency)

    _report_malformed(malformed, verified)

    # Last, and only after everything has been listed and every cost basis checked:
    # a verification that stopped the command at the first disagreement would
    # answer "is anything wrong" while hiding what, and hide the listing the
    # reader needs to make sense of it. The count is every cost basis in the book —
    # `rows` is what the filters left, and filtering a listing narrows what is
    # shown, not what was checked. The pending count is of the currency asked
    # for, as the listing of them above is.
    _finish_verifying(verified, len(pending))
