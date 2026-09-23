"""A borrowed dollar, from drawing the loan to owing nothing, in step throughout.

`docs/issues/Q-045-a-borrowed-dollar-worked-through.txt` reasons this book out
on paper; this runs it. A Canadian book borrows 1,000.00 USD at 1% for a year,
is paid 1,010.00 USD by a customer, repays 1,010.00 USD, and sells what is
left. Five transactions, and after every one of them the same question is
asked.

**The invariant, checked before and after each transaction**: per currency and
per side, what the cost bases hold is what the accounts hold. The asset-side
bases against the bank, the liability-side bases against the loan, never added
together — a book can hold a currency and owe it at once, and one figure for
both answers for neither.

**And at the end, every US dollar figure is nought**: no basis, no balance, on
either side. A book that has repaid its loan and sold its remaining dollars
holds none and owes none, and if a cost basis is left standing there is
currency the book thinks it has.

The rates are the whole of the arithmetic — 1.30 when the loan is drawn, 1.35
when the customer pays, 1.40 at the end — and what they make is checked at the
close:

    + 50.50 CAD  on the 1,010.00 the customer paid, held 1.35 -> 1.40
    -100.00 CAD  on the 1,000.00 principal, owed 1.30 -> 1.40
    +100.00 CAD  on the 1,000.00 borrowed and held, 1.30 -> 1.40
       0.00 CAD  on the interest, owed and paid at 1.40
    ----------
    + 50.50 CAD

The loan's loss and the gain on holding its money cancel exactly, which is what
a borrowing nobody spends should do, and only a book measuring both sides finds
it. What is left is the gain on the dollars the company actually earned.
"""

from fractions import Fraction

from click.testing import CliRunner

from repositories.gnucash_repository import GnuCashRepository, SessionMode
from services.foreign_currency import (
    cost_basis_items_by_currency_and_side,
    foreign_currency_account_balances,
)
from tests.conftest import _run

AS_OF = '2027-12-31'

THE_ACCOUNTS = '''\
2026-01-01 commodity CAD
\tmnemonic: "CAD"
\tfullname: "Canadian Dollar"
\tnamespace: "CURRENCY"
\tfraction: 100
2026-01-01 commodity USD
\tmnemonic: "USD"
\tfullname: "US Dollar"
\tnamespace: "CURRENCY"
\tfraction: 100

2026-01-01 open Assets
\ttype: "Asset"
\tplaceholder: #True
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Assets:Bank
\ttype: "Bank"
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Assets:USD Bank
\ttype: "Bank"
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "USD"
2026-01-01 open Liabilities
\ttype: "Liability"
\tplaceholder: #True
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Liabilities:USD Loan
\ttype: "Liability"
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "USD"
2026-01-01 open Income
\ttype: "Income"
\tplaceholder: #True
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Income:Consulting
\ttype: "Income"
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Income:FX Gain
\ttype: "Income"
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Expenses
\ttype: "Expense"
\tplaceholder: #True
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Expenses:Interest
\ttype: "Expense"
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Expenses:Foreign exchange loss
\ttype: "Expense"
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
'''

DRAW_THE_LOAN = '''\
2026-01-02 * "Borrow 1,000.00 USD for a year at 1%"
\tcurrency.mnemonic: "CAD"
\tAssets:USD Bank 1000.00 USD
\t\taccount.commodity.mnemonic: "USD"
\t\tshare_price: "1.30000"
\t\tvalue: "1300.00"
\t\tcost_basis_balance: "1000.00"
\tLiabilities:USD Loan -1000.00 USD
\t\taccount.commodity.mnemonic: "USD"
\t\tshare_price: "1.30000"
\t\tvalue: "-1300.00"
\t\tcost_basis_balance: "1000.00"
'''

THE_CUSTOMER_PAYS = '''\
2026-06-30 * "Customer pays 1,010.00 USD"
\tcurrency.mnemonic: "CAD"
\tAssets:USD Bank 1010.00 USD
\t\taccount.commodity.mnemonic: "USD"
\t\tshare_price: "1.35000"
\t\tvalue: "1363.50"
\t\tcost_basis_balance: "1010.00"
\tIncome:Consulting -1363.50 CAD
'''

THE_INTEREST = '''\
2027-01-02 * "Interest for the year, 10.00 USD"
\tcurrency.mnemonic: "CAD"
\tExpenses:Interest 14.00 CAD
\tLiabilities:USD Loan -10.00 USD
\t\taccount.commodity.mnemonic: "USD"
\t\tshare_price: "1.40000"
\t\tvalue: "-14.00"
\t\tcost_basis_balance: "10.00"
'''


def _repay(loan_basis, interest_basis, bank_basis):
    """1,010.00 USD repaid: two liability bases consumed, one asset basis.

    Three guids for one transaction, because three cost bases are drawn down
    and each was taken on at its own rate. The loan split is written twice, one
    per basis it draws on, which is how a disposal spread across two bases is
    stated.

    **Each split leaves at what its units cost, not at today's rate**, which is
    the convention every disposal in this format follows: 1.30 on the
    principal, 1.40 on the interest, 1.35 on the dollars the customer paid.
    Written at 1.40 throughout the transaction balances by itself and
    `$residual$` is refused for having nothing to take — which is right, because
    a disposal whose splits already balance realized nothing, and this one
    realized 49.50.

        1,300.00 + 14.00 - 1,363.50 = -49.50, so the residual is 49.50 CAD
        of loss — the -100.00 on the principal against the +50.50 on the
        dollars held, which is what the book actually made.
    """
    return f'''\
2027-01-02 * "Repay the loan, 1,010.00 USD"
\tcurrency.mnemonic: "CAD"
\tLiabilities:USD Loan 1000.00 USD
\t\taccount.commodity.mnemonic: "USD"
\t\tshare_price: "1.30000"
\t\tvalue: "1300.00"
\t\tcost_basis_split_guid: "{loan_basis}"
\tLiabilities:USD Loan 10.00 USD
\t\taccount.commodity.mnemonic: "USD"
\t\tshare_price: "1.40000"
\t\tvalue: "14.00"
\t\tcost_basis_split_guid: "{interest_basis}"
\tAssets:USD Bank -1010.00 USD
\t\taccount.commodity.mnemonic: "USD"
\t\tshare_price: "1.35000"
\t\tvalue: "-1363.50"
\t\tcost_basis_split_guid: "{bank_basis}"
\tExpenses:Foreign exchange loss $residual$ CAD
'''


def _sell_what_is_left(bank_basis):
    """The 1,000.00 USD the loan brought in, sold for Canadian dollars.

    They cost 1.30 and fetch 1.40, so they leave at 1,300.00 and the bank takes
    1,400.00: the residual is a gain of 100.00 CAD, which is exactly what the
    owed side lost on the same dollars. A borrowing nobody spends ends level,
    and it takes both sides to show it.

    **The residual goes to an exchange gain account, not to revenue.** What a
    currency disposal realizes is a gain on holding the currency, and booking
    it to `Income:Consulting` would report it as money earned from customers —
    on the income statement, in the wrong line, and inside `total_revenue`.
    """
    return f'''\
2027-01-03 * "Sell the remaining 1,000.00 USD at 1.40"
\tcurrency.mnemonic: "CAD"
\tAssets:Bank 1400.00 CAD
\tAssets:USD Bank -1000.00 USD
\t\taccount.commodity.mnemonic: "USD"
\t\tshare_price: "1.30000"
\t\tvalue: "-1300.00"
\t\tcost_basis_split_guid: "{bank_basis}"
\tIncome:FX Gain $residual$ CAD
'''


def _read(book):
    """Every cost basis and every foreign balance, as the sheet reads them."""
    from datetime import date
    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        rows = list(cost_basis_items_by_currency_and_side(
            repo.book, date(2027, 12, 31)))
        holdings = list(foreign_currency_account_balances(repo.book))
    finally:
        repo.close()
    return rows, holdings


def _in_step(book, moment):
    """Per currency and side, the bases hold what the accounts hold."""
    rows, holdings = _read(book)
    for code in sorted({r['currency'] for r in rows}
                       | {h['currency'] for h in holdings}):
        for side, sign in (('asset', 1), ('liability', -1)):
            bases = sum((r['balance'] for r in rows
                         if r['currency'] == code and r['side'] == side),
                        Fraction(0))
            accounts = sign * sum((h['balance'] for h in holdings
                                   if h['currency'] == code
                                   and sign * h['balance'] > 0), Fraction(0))
            assert bases == accounts, (
                f'{moment}: {code} {side} cost bases hold {bases} against '
                f'{accounts} in the accounts')


def _basis(book, side, account_ends_with, balance):
    """The guid of the one basis on that side, account and balance."""
    rows, _ = _read(book)
    found = [r for r in rows if r['side'] == side and r['balance'] == balance
             and r['account'].endswith(account_ends_with)]
    assert len(found) == 1, (side, account_ends_with, balance, rows)
    return found[0]['guid']


def _apply(runner, tmp_path, book, name, ledger):
    """One transaction, with the invariant asked before it and after it."""
    _in_step(book, f'before {name}')
    written = tmp_path / f'{name}.txt'
    written.write_text(ledger, encoding='utf-8')
    result = _run(runner, 'import', str(book), str(written))
    assert result.exit_code == 0, result.output
    _in_step(book, f'after {name}')


def test_the_bases_stay_in_step_and_end_at_nothing(tmp_path):
    runner = CliRunner()
    book = tmp_path / 'borrowed.gnucash'
    opened = tmp_path / 'accounts.txt'
    opened.write_text(THE_ACCOUNTS, encoding='utf-8')
    made = _run(runner, 'import', '--new', str(book), str(opened))
    assert made.exit_code == 0, made.output

    _apply(runner, tmp_path, book, 'the_loan', DRAW_THE_LOAN)
    # Two bases, one a side, and the book is flat in US dollars: it holds as
    # many as it owes.
    rows, _ = _read(book)
    assert sorted((r['side'], r['balance']) for r in rows) == [
        ('asset', Fraction(1000)), ('liability', Fraction(1000))], rows

    _apply(runner, tmp_path, book, 'the_customer', THE_CUSTOMER_PAYS)
    _apply(runner, tmp_path, book, 'the_interest', THE_INTEREST)

    # Interest raised the owed side, so it opened a basis of its own: the book
    # owes 10.00 USD it did not owe before, at what that obligation cost.
    rows, _ = _read(book)
    assert sorted(r['balance'] for r in rows if r['side'] == 'liability') == [
        Fraction(10), Fraction(1000)], rows

    _apply(runner, tmp_path, book, 'the_repayment', _repay(
        loan_basis=_basis(book, 'liability', 'USD Loan', Fraction(1000)),
        interest_basis=_basis(book, 'liability', 'USD Loan', Fraction(10)),
        bank_basis=_basis(book, 'asset', 'USD Bank', Fraction(1010))))

    # Nothing is owed and nothing is left against it; the bank still holds the
    # dollars the loan brought in. A basis spent to nothing stays as a row
    # reading 0.00 rather than disappearing — `fx-balances` lists it, and
    # `--with-balance-only` is the flag for hiding it — so what is asked here
    # is the balance, not the row.
    rows, _ = _read(book)
    assert sum((r['balance'] for r in rows if r['side'] == 'liability'),
               Fraction(0)) == 0, rows
    assert sum((r['balance'] for r in rows if r['side'] == 'asset'),
               Fraction(0)) == Fraction(1000), rows

    _apply(runner, tmp_path, book, 'the_last_dollars', _sell_what_is_left(
        _basis(book, 'asset', 'USD Bank', Fraction(1000))))

    # **Every US dollar figure is nought.** No basis and no balance, either
    # side: a book that has repaid its loan and sold what it held has none and
    # owes none, and a basis left standing here is currency the book thinks it
    # has.
    rows, holdings = _read(book)
    for side in ('asset', 'liability'):
        assert sum((r['balance'] for r in rows
                    if r['currency'] == 'USD' and r['side'] == side),
                   Fraction(0)) == 0, (side, rows)
    assert sum((h['balance'] for h in holdings if h['currency'] == 'USD'),
               Fraction(0)) == 0, holdings
    # And said once more the way a reader would ask it, so a future change that
    # leaves a stray basis behind fails here rather than on a balance sheet.
    _in_step(book, 'at the close')
