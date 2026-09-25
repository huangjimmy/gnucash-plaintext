"""A book holding a disposal that gives no cost basis, exported and imported again.

A book written in GnuCash's own register, or by gnucash-plaintext before a
disposal had to say which cost basis it came out of, can hold dollars spent
with no `cost_basis_split_guid:`. The book itself is read as it stands. Its
export is a ledger, and imported into a new book that ledger meets the rule
every ledger meets: the purchase opens a cost basis, and the spend that gives
none is refused.

The import says which transaction and how much, imports everything else, and
`fx-balances` on the result lists the cost bases the spend could have come out
of. Bringing it forward is writing that transaction the way every disposal is
written — the guid, the dollars at what they cost, and a `$residual$` split for
what they realized — and taking off the `cost_basis_balance:` the export states
on the dollars bought, which is the old book's figure and drew nothing down for
the spend. The book it then imports is one whose cost bases hold what its
accounts hold, which `--verify-integrity` confirms.

The spend is written through GnuCash's own bindings, the way the register
writes one, because `import` would refuse to write it.
"""

from click.testing import CliRunner

from cli.main import cli
from infrastructure.gnucash.utils import find_account
from repositories.gnucash_repository import GnuCashRepository

LEDGER = 'tests/fixtures/a_cad_book_that_bought_a_thousand_usd.txt'
THE_DOLLARS_BOUGHT = '0b0b0b0b0b0b0b0b0b0b0b0b0b0b1000'


def _a_book_with_a_spend_written_in_the_register(tmp_path):
    """1,000.00 USD bought at 1.30, then 400.00 of them sold for 560.00 CAD."""
    from gnucash import GncNumeric, Split, Transaction

    book_path = tmp_path / 'old.gnucash'
    made = CliRunner().invoke(cli, ['import', '--new', str(book_path), LEDGER])
    assert made.exit_code == 0, made.output

    repo = GnuCashRepository(str(book_path))
    repo.open()
    book = repo.book
    root = book.get_root_account()
    transaction = Transaction(book)
    transaction.BeginEdit()
    transaction.SetCurrency(book.get_table().lookup('CURRENCY', 'CAD'))
    transaction.SetDate(1, 3, 2026)
    transaction.SetDescription('Sell 400.00 USD at 1.40')
    dollars = Split(book)
    dollars.SetParent(transaction)
    dollars.SetAccount(find_account(root, 'Assets:USD Bank'))
    dollars.SetAmount(GncNumeric(-40000, 100))
    dollars.SetValue(GncNumeric(-56000, 100))
    proceeds = Split(book)
    proceeds.SetParent(transaction)
    proceeds.SetAccount(find_account(root, 'Assets:CAD Bank'))
    proceeds.SetAmount(GncNumeric(56000, 100))
    proceeds.SetValue(GncNumeric(56000, 100))
    transaction.CommitEdit()
    repo.save()
    repo.close()
    return book_path


def _exported(tmp_path):
    ledger = tmp_path / 'exported.txt'
    done = CliRunner().invoke(
        cli, ['export', str(_a_book_with_a_spend_written_in_the_register(tmp_path)),
              str(ledger)])
    assert done.exit_code == 0, done.output
    return ledger


def test_the_export_imported_again_refuses_the_spend_and_says_which(tmp_path):
    ledger = _exported(tmp_path)

    done = CliRunner().invoke(
        cli, ['import', '--new', str(tmp_path / 'new.gnucash'), str(ledger)])

    assert 'Errors:       1' in done.output, done.output
    assert ('error: Sell 400.00 USD at 1.40: this transaction is a sale of 400.00 USD '
            'the book held for 560.00 CAD: Assets:USD Bank, a Bank account in USD, is '
            'credited 400.00 USD; Assets:CAD Bank, a Bank account in CAD, is debited '
            '560.00 CAD. A sale requires a consumption of one or more cost bases, but no split says '
            'which.') in done.output, done.output


def test_the_rest_is_imported_and_lists_the_cost_basis_to_give(tmp_path):
    ledger = _exported(tmp_path)
    book = tmp_path / 'new.gnucash'
    CliRunner().invoke(cli, ['import', '--new', str(book), str(ledger)])

    listing = CliRunner().invoke(cli, ['fx-balances', str(book)]).output

    assert THE_DOLLARS_BOUGHT in listing, listing
    assert 'Total USD cost basis balance: 1,000.00 USD' in listing, listing


def test_written_as_a_disposal_the_spend_brings_the_book_forward(tmp_path):
    """The block every disposal is written as: the guid, the dollars at what they cost, and `$residual$`.

    The dollars cost 1.30 and fetched 1.40, so 520.00 of cost leaves and
    40.00 is realized. The spend draws 400.00 off the dollars bought, and
    600.00 are left on both counts.
    """
    ledger = _exported(tmp_path)
    text = ledger.read_text()
    # The balance the export states on the dollars bought is the old book's,
    # which drew nothing down for the spend, so it is taken off and the
    # import works it out from the disposals instead.
    stated = '\t\tcost_basis_balance: "1000.00"\n'
    assert text.count(stated) == 1, text
    text = text.replace(stated, '')
    start = text.index('2026-03-01 * "Sell 400.00 USD at 1.40"')
    # The next dated block, or the end of the file where the sale is the last.
    end = text.find('\n2', start)
    end = len(text.rstrip('\n')) if end < 0 else end
    # The export writes only the accounts a transaction uses, so the account
    # the difference is booked to is opened here as well.
    opened = ''.join(
        f'2026-01-01 open {name}\n\ttype: "Income"\n'
        f'\tcommodity.namespace: "CURRENCY"\n\tcommodity.mnemonic: "CAD"\n'
        for name in ('Income', 'Income:FX Gain')
        if f'open {name}\n' not in text)
    ledger.write_text(
        text[:start]
        + opened
        + '2026-03-01 * "Sell 400.00 USD at 1.40"\n'
          '\tcurrency.mnemonic: "CAD"\n'
          '\tAssets:USD Bank -400.00 USD\n'
          '\t\taccount.commodity.mnemonic: "USD"\n'
          '\t\tshare_price: "13/10"\n'
          '\t\tvalue: "-520.00"\n'
          f'\t\tcost_basis_split_guid: "{THE_DOLLARS_BOUGHT}"\n'
          '\tAssets:CAD Bank 560.00 CAD\n'
          '\tIncome:FX Gain $residual$ CAD'
        + text[end:])
    book = tmp_path / 'new.gnucash'

    done = CliRunner().invoke(cli, ['--verify-integrity', 'import', '--new',
                                    str(book), str(ledger)])
    listing = CliRunner().invoke(cli, ['fx-balances', str(book)]).output
    sheet = CliRunner().invoke(cli, ['balance-sheet', str(book), '--as-of',
                                     '2026-12-31', '--no-itemize']).output

    assert 'Errors:       0' in done.output, done.output
    assert 'The book is consistent and balanced.' in done.output, done.output
    assert 'Total USD cost basis balance: 600.00 USD' in listing, listing
    assert 'Total USD held in accounts: 600.00 USD' in listing, listing
    assert '\trealized_gains_fx: 40.00 CAD' in sheet.splitlines(), sheet
