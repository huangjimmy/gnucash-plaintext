"""A book made from a fixture, and the lines of a statement written as plaintext.

`balance-sheet`, `income-statement` and `report` are written by the customized
GnuCash reports in
`infrastructure/gnucash/reports/balance-sheet-and-income-statement-as-text.scm`
in this project's own plaintext format: a dated directive, then keys and
account lines indented under it with tabs.

    2026-12-31 balance-sheet
        # comment lines the report writes, saying what the keys mean
        currency.mnemonic: "CAD"
        Assets:HKD Bank 5500.00 HKD
            account.commodity.mnemonic: "HKD"
            share_price: "0.2"
            value: "1100.00"
        total_assets: 38532.80 CAD
        unrealized_gains: 2303.20 CAD

So a test asks for an account's line by its path, or for a key by its name,
rather than splitting a padded column page. An account holding something other
than the report's currency carries what a split carries: the commodity, the
price GnuCash used where the book holds one in the report's currency, and the
value GnuCash made of it.
"""

import re
from fractions import Fraction
from pathlib import Path

from click.testing import CliRunner

from tests.conftest import _run

FIXTURES = Path('tests/fixtures')


def book_from(tmp_path, fixture, *flags):
    """A new book imported from `tests/fixtures/<fixture>`."""
    book = tmp_path / 'book.gnucash'
    result = _run(CliRunner(), 'import', '--new', str(book), str(FIXTURES / fixture), *flags)
    assert result.exit_code == 0, result.output
    return book


def a_book_using_trading_accounts(tmp_path, fixture=None):
    """A new book with "Use Trading Accounts" on, and `fixture` imported into it.

    A GnuCash user turns the option on in File → Properties → Accounts, and
    GnuCash then records each multi-currency transaction with trading splits of
    its own making. Nothing in gnucash-plaintext sets it, so the book is made
    the way GnuCash keeps one: the option set on a new book, and the ledger
    imported after.

    A new book holding nothing but a book option writes no file when saved, so
    it is given a top-level CAD account, which is also what keeps the book in
    CAD.
    """
    from gnucash import ACCT_TYPE_BANK, Account

    from infrastructure.gnucash.kvp import write_book_string_option
    from repositories.gnucash_repository import GnuCashRepository, SessionMode

    book = tmp_path / 'trading.gnucash'
    repo = GnuCashRepository(str(book))
    repo.open(SessionMode.NEW)
    try:
        write_book_string_option(repo.book, 'Accounts', 'Use Trading Accounts', 't')
        petty_cash = Account(repo.book)
        petty_cash.BeginEdit()
        petty_cash.SetName('Petty Cash')
        petty_cash.SetType(ACCT_TYPE_BANK)
        petty_cash.SetCommodity(repo.book.get_table().lookup('CURRENCY', 'CAD'))
        repo.book.get_root_account().append_child(petty_cash)
        petty_cash.CommitEdit()
        repo.save()
    finally:
        repo.close()
    if fixture is not None:
        imported = _run(CliRunner(), 'import', str(book), str(FIXTURES / fixture))
        assert imported.exit_code == 0, imported.output
    return book


def shares_as_a_block_writes(quantity, mnemonic, places=4):
    """A share count as the block writes one: padded to the commodity's own places.

    `10.0000 AMZN` for a security whose fraction is 10000. The block's figures
    are written exactly — padded to what the commodity is kept to, never
    rounded — so a whole number of shares has one spelling on every build.
    GnuCash's own column page writes the same holding as `10 AMZN` up to 5.10
    and `10. AMZN` from 5.13, which is its formatter rather than this one, and
    is why the block writes its own.
    """
    return f'{quantity}.{"0" * places} {mnemonic}' if places else f'{quantity} {mnemonic}'


def _own_lines(output):
    """The block's own lines: one tab in, so an account's nested keys are left.

    The report's own comment lines are one tab in too, so they are here as
    well. Nothing below minds — each looks for a line starting with an account
    path or a key name, and a comment starts with `#` — but a caller counting
    these lines would be counting those too.
    """
    return [line for line in output.splitlines()
            if line.startswith('\t') and not line.startswith('\t\t')]


def directive_of(output):
    """The line that opens the block: `2026-01-25 balance-sheet`.

    `report` writes a block per statement, so this answers for a page holding
    one and the test for `report` asks by statement instead.
    """
    opening = [line for line in output.splitlines()
               if line.strip() and not line.startswith('\t')]
    assert len(opening) == 1, output
    return opening[0]


def directives_of(output):
    """Every block's opening line, in the order the page writes them."""
    return [line for line in output.splitlines()
            if line.strip() and not line.startswith('\t')]


def amount_of(output, path):
    """What the account at `path` holds: `38532.80 CAD`.

    Found by its whole path, which every line carries — `Assets` and
    `Assets:CAD Bank` are two lines and neither is the other.
    """
    wanted = path + ' '
    found = [line.strip()[len(wanted):]
             for line in _own_lines(output)
             if line.strip().startswith(wanted)]
    assert len(found) == 1, (path, output)
    return found[0]


def key_of(output, name):
    """The value of one of the block's keys.

    Two kinds of key sit in a block and they are written differently. A figure
    GnuCash computed states its currency and carries no quotes —
    `unrealized_gains: 2303.20 CAD` — because a money figure in quotes reads as
    a string that happens to look like money. Text keeps its quotes:
    `currency.mnemonic: "CAD"`, `end: "2026-12-31"`. This answers either, with
    the quotes taken off the ones that have them.
    """
    wanted = f'{name}: '
    found = [line.strip()[len(wanted):]
             for line in _own_lines(output)
             if line.strip().startswith(wanted)]
    assert len(found) == 1, (name, output)
    value = found[0]
    if value.startswith('"') and value.endswith('"'):
        return value[1:-1]
    # A figure may state how it was reached — `600.00 CAD # unrealized_gains_fx
    # + unrealized_gains_liabilities_fx` — and the value is the figure. Only an
    # unquoted one is trimmed: a quoted string may hold a `#` of its own.
    return value.split(' #')[0].strip()


def block_of(output, name):
    """The nested lines a gain figure carries, as one string with guids masked.

    Four keys state their items rather than a figure — `realized_gains_fx`,
    `unrealized_gains_assets_fx`, `unrealized_gains_other` and
    `gnucash_balancing_amount` (Q-044). The key's own line is one tab in and
    bare; everything under it is deeper, and the block ends at the next line one
    tab in. A split's guid is made fresh on every import, so it is replaced by
    `<guid>` and the rest compared as written.
    """
    lines = output.splitlines()
    opening = f'\t{name}:'
    start = [index for index, line in enumerate(lines)
             if line == opening or line.startswith(opening + ' #')]
    assert len(start) == 1, (name, output)
    body = []
    for line in lines[start[0] + 1:]:
        if line.startswith('\t\t'):
            body.append(re.sub(r'\b[0-9a-f]{32}\b', '<guid>', line))
            continue
        break
    assert body, (name, output)
    return '\n'.join(body)


def totals_of(output, name):
    """A block's own totals, as `{field: Fraction}`.

    The four itemized keys end in their own summary lines — the key's figure and
    the columns it was reached from — written one tab inside the block, with the
    items themselves deeper than that. So this takes the lines at that one depth
    and leaves the items alone.

    A figure, never a string: a block line writes `250.00` where a key line
    writes `250.00 CAD`, so the same number is spelt two ways on one page. A
    test comparing text would be asserting which of the two it happened to
    read; read as a Fraction, it asks what the number is.
    """
    totals = {}
    for line in block_of(output, name).splitlines():
        if line.startswith('\t\t\t'):
            continue
        field, _, rest = line.strip().partition(': ')
        try:
            totals[field] = Fraction(rest.split(' #')[0].strip())
        except (ValueError, ZeroDivisionError):
            continue
    return totals


def block_total_of(output, name):
    """The figure an itemized key states for itself, from inside its own block.

    An itemized key opens with a bare line and ends with a line of its own name
    carrying the total its items come to:

        realized_gains_fx:
            realized_gains_fx: 250.00     <- this
            splits:
                ...

    So `key_of` cannot read it — the key line has no figure on it — and this
    answers what the key says it is, as a Fraction.
    """
    totals = totals_of(output, name)
    assert name in totals, (name, output)
    return totals[name]


def under(output, path):
    """The keys written under an account's line, as `{name: value}`."""
    lines = output.splitlines()
    wanted = path + ' '
    start = [index for index, line in enumerate(lines)
             if line.startswith('\t') and not line.startswith('\t\t')
             and line.strip().startswith(wanted)]
    assert len(start) == 1, (path, output)
    keys = {}
    for line in lines[start[0] + 1:]:
        if not line.startswith('\t\t'):
            break
        name, _, value = line.strip().partition(': ')
        keys[name] = value.strip('"')
    return keys
