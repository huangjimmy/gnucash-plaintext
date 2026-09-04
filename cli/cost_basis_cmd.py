"""
CLI command listing foreign-currency cost bases (Q-035).

Every split that brought foreign currency into the book — an invoice's A/R
split, a bill's A/P split, currency bought or borrowed — establishes a cost
basis: so many units at a stated cost in the book's own currency. Selling that
currency picks one or more of these bases by guid, so a user writing a sale
needs to see what bases exist, what each cost, and how much each has left.

The balance of a cost basis is not the balance of an account: it is how much
of *one split's* currency, at *that split's* cost, has not yet been sold. One
bank account can hold currency from several bases at different costs, and a
paid invoice's basis stays listed after the money has moved to the bank.
"""

from fractions import Fraction

import click

from infrastructure.gnucash.utils import exact_text, money_text
from repositories.gnucash_repository import GnuCashRepository, SessionMode
from services.foreign_currency import (
    BASE_CURRENCY,
    COST_BASIS_BALANCE_KEY,
    cost_bases,
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
    a minor unit is not given two invented ones.
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
    """A basis this tool never wrote a balance for reads `none recorded`, not
    a number: how much of it is still unsold is not known, and its full amount
    would be a guess that could re-open currency already sold.

    `malformed` is the whole basis, not this column: it is what a row says when
    reading the basis at all raised — a stored *cost* that will not parse — so
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


def _finish_verifying(verified) -> None:
    """Report what the check found and set the exit code, once.

    Both endings of the listing — the empty one a filter can leave and the
    ordinary one — finish here, so the report and the exit code cannot drift
    apart between them.
    """
    if verified is None:
        return
    click.echo('')
    _report_disagreements(verified['findings'], verified['checked'])
    _report_currency_totals(verified.get('currency_totals') or [])
    if verified['findings']:
        raise SystemExit(1)


def _report_currency_totals(totals) -> None:
    """Say which currency does not add up, and by how much.

    A warning, and it does not set the exit code. Every basis here passes the
    questions asked of it one at a time — that is what makes this worth
    printing and also what makes it the wrong thing to refuse over: the book is
    readable, its figures are the ones it holds, and what put the two sides out
    of step is not something the book records. The reader is the one who can
    say which of them is right.

    Both figures and the difference, because the difference alone says nothing
    about where to look: 80.00 short of 200.00 is a basis that lost its
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
            f"{currency} was sold against a basis — leaving "
            f"{_format_amount(row['ledger'], unit)} {currency}.")
        click.echo(
            f"  {_format_amount(abs(row['difference']), unit)} {currency} is "
            + ('accounted for by no basis. A balance was lowered without a '
               'sale to lower it, or a sale gave back less than it took.'
               if short else
               'held by the bases beyond what arrived. A balance was raised '
               'without a sale being deleted, or one was stated too high.'))
        click.echo(
            '  Nothing is refused: every basis is within its own bounds, and '
            'which side is right is not something the book records.')


def _report_malformed(malformed: int, verified) -> None:
    """Say that a basis could not be read, wherever the listing ends up.

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


def _report_disagreements(disagreements, checked: int) -> None:
    """What `--verify-costs` found, said in full.

    Every disagreement is reported, not the first — the run gathers them all
    and the exit code comes at the end, so one bad basis never hides the rest.

    Each is printed with the whole computation behind it: both guids to open
    the book at, the amount and value the ledger carries, its balance, the
    rate the transaction converted at with each base-currency
    split measured against it, every factor of the derivation, and both
    answers with which one is used. Which figure is wrong is the reader's
    judgement; showing only that two differ leaves them to re-derive it by
    hand. A basis that could not be read at all carries its traceback for the
    same reason.
    """
    if not disagreements:
        click.echo(f'Checked {checked} cost basis(es): every cost agrees with '
                   f'the figures it is derived from.')
        return

    # "and found" rather than "of which", because the two numbers do not count
    # the same things. `checked` is the cost bases in the book; a finding can
    # be about a split that is not one at all — a balance stored where nothing
    # reads it, a sale drawing on a split that is no basis — so a book with
    # one stranded balance and no bases read "Checked 0 cost basis(es); 1
    # disagree".
    click.echo(f'Checked {checked} cost basis(es), and found '
               f'{len(disagreements)} thing(s) that do not hold:')
    for row in disagreements:
        click.echo('')
        click.echo(f"{row['date']}  {row['account']}")
        if row['description']:
            click.echo(f"    {row['description']}")
        click.echo(f"    split guid       {row['guid']}")
        click.echo(f"    tx guid          {row['tx_guid']}")
        if 'amount' in row:
            # Exactly, every one of them: these figures are printed because
            # something about this basis is wrong, and a rounded one can hide
            # the very difference being reported — the balance line read
            # "100.00" two lines above a finding about 100001/1000.
            click.echo(f"    amount           "
                       f"{_format_exactly(row['amount'], row['unit'])} {row['currency']}")
            click.echo(f"    value            "
                       f"{_format_exactly(row['value'], row['tx_unit'])} "
                       f"{row['tx_currency']}   (the transaction's currency)")
            if row['balance'] is not None:
                click.echo(f"    basis balance    "
                           f"{_format_exactly(row['balance'], row['unit'])} "
                           f"{row['currency']}")
            if row['malformed_balance']:
                click.echo(f"    basis balance    "
                           f"{row['malformed_balance']!r}   (does not parse)")
            if row['tx_rate'] is not None:
                click.echo(f"    transaction rate {exact_text(row['tx_rate'])} "
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
                click.echo(f'    {label:<16} {shown}')
            click.echo(f"    computed cost    "
                       f"{_format_cost(row['derived'], row['currency'])}")
            click.echo(f"    stored cost      "
                       f"{_format_cost(row['stored'], row['currency'])}")
            click.echo(f"    used             "
                       f"{_format_cost(row['used'], row['currency'])}")
        for problem in row['problems']:
            click.echo(f'    - {problem}')
        if row.get('traceback'):
            for line in row['traceback'].rstrip().splitlines():
                click.echo(f'    | {line}')
    click.echo('')


@click.command('fx-balances')
@click.argument('gnucash_file', type=click.Path(exists=True))
@click.option('--currency', 'currency', default=None,
              help='Only list cost bases in this currency (e.g. USD).')
@click.option('--with-balance-only', is_flag=True,
              help='Show only bases with a balance above zero — hiding both '
                   'the exhausted ones and any reading `none recorded`.')
@click.option('--verify-costs', is_flag=True,
              help='Check each cost against the ledger figures it is derived '
                   'from, and report any that disagree (exits 1 if any do).')
def fx_balances(gnucash_file, currency, with_balance_only, verify_costs):
    """
    List every foreign-currency cost basis with its cost and its balance.

    Each row is one split: its guid (what a sale names to pick that basis), the
    transaction it came from, what one unit cost in the book's currency, how
    much currency it brought in, and how much of it is left to sell.

    To sell foreign currency, write the sale's foreign-currency split naming
    the basis it is measured against:

    \b
        2026-03-01 * "Sell 200 USD"
            currency.mnemonic: "CAD"
            Assets:Bank:USD -200.00 USD
                cost_basis_split_guid: "<guid from this listing>"
            Assets:Bank:CAD 278.00 CAD
            Income:FX Gain $residual$ CAD

    A sale measured against two bases carries two USD splits, one naming each,
    and each split's amount is how much of that basis it uses.

    `--verify-costs` checks each cost against the ledger it is derived from and
    reports what disagrees: that no balance is above what its basis brought in
    or below zero, and that a stored `cost_basis_cost` parses and
    agrees with the transaction. Both are exact comparisons against figures the
    book already holds; rates are not checked, because a rate runs forward into
    a rounded figure and the figure does not run back into the rate. The whole
    book is checked and the exit code comes at the end, so one bad basis hides
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
        rows = cost_bases(repo.book)
        verified = verify_cost_bases(repo.book) if verify_costs else None
    finally:
        repo.close()

    malformed = sum(1 for row in rows if row.get('malformed'))

    if currency:
        wanted = currency.upper()
        rows = [row for row in rows if row['currency'] == wanted]
    if with_balance_only:
        # A basis with nothing left cannot be sold against, so it is left out.
        rows = [row for row in rows
                if row['balance'] is not None and row['balance'] > 0]

    if not rows:
        click.echo('No foreign-currency cost bases found.')
        # A filter hiding every row does not make a malformed basis go away,
        # and it is the one thing a reader most needs told: the notice is over
        # the whole book, like the check below it.
        _report_malformed(malformed, verified)
        _finish_verifying(verified)
        return

    # Size the account column to the longest name rather than truncating it:
    # a clipped account path ("Liabilities:Accounts Payable U") does not say
    # which account the basis is on, which is half of what the row is for.
    width = max(len('ACCOUNT'), max(len(row['account']) for row in rows))
    header = (f"{'DATE':<12} {'SPLIT GUID':<34} {'ACCOUNT':<{width}} "
              f"{'COST':>18} {'ACQUIRED':>14} {'BASIS BALANCE':>14}")
    click.echo(header)
    click.echo('-' * len(header))
    for row in rows:
        click.echo(
            f"{row['date']:<12} {row['guid']:<34} {row['account']:<{width}} "
            f"{_format_cost(row['cost'], row['currency']):>18} "
            f"{_format_amount(row['acquired'], row['unit']) + ' ' + row['currency']:>14} "
            f"{_format_cost_basis_balance(row):>14}"
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
        click.echo(f'Total {code} basis balance: '
                   f'{_format_amount(totals[code], units[code])} {code}')
    if no_balance_recorded:
        click.echo(
            f'{no_balance_recorded} cost basis(es) have no balance recorded '
            f'and are excluded from the total: this tool never wrote one for '
            f'them, so how much of their currency is still unsold is not '
            f'known. State `{COST_BASIS_BALANCE_KEY}:` on the split in an '
            f'import file to give it a balance.')

    _report_malformed(malformed, verified)

    # Last, and only after everything has been listed and every basis checked:
    # a verification that stopped the command at the first disagreement would
    # answer "is anything wrong" while hiding what, and hide the listing the
    # reader needs to make sense of it. The count is every basis in the book —
    # `rows` is what the filters left, and filtering a listing narrows what is
    # shown, not what was checked.
    _finish_verifying(verified)
