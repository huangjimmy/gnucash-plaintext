"""The currency a book is kept in, which is the currency its reports are in.

GnuCash stores no currency for a book. Measured on all eleven builds on a book
kept only in HKD: the root account holds no commodity, the book-currency call
answers nothing on 3.4 and 3.8 and does not exist from 4.4, and GnuCash's own
Balance Sheet defaults its report currency to USD (Q-042). So the currency is
found here, from the first of these that gives one:

1. a currency given on the command (`--currency`);
2. the `company` block's `base_currency:`, one of the book-level custom keys
   `import` keeps in the book;
3. the currency every top-level account held in a currency shares. An account
   holding shares or a fund is held in no currency and is passed over, and so
   are the top-level accounts GnuCash makes for itself — `Imbalance-<CUR>`,
   `Orphan-<CUR>` and `Trading`.

Where none of them gives one, the book's currency is refused, and nothing is
taken to be CAD.
"""

from typing import Optional

from infrastructure.gnucash.kvp import get_book_custom_metadata

BASE_CURRENCY_KEY = 'base_currency'

_HOW_TO_STATE_IT = ('State it with --currency on the command, or with '
                    '`base_currency: "HKD"` in the company block, which import keeps '
                    'in the book.')


class BookCurrencyUnknownError(Exception):
    """Nothing says which currency the book is kept in, or what does is not a currency."""


def _gnucash_made_it(name: str) -> bool:
    """Whether GnuCash made this top-level account rather than a ledger.

    `Imbalance-CAD`, `Orphan-USD` and `Trading` are GnuCash's own, made as it
    scrubs a book or as a book with trading accounts records a transaction.
    """
    return name.startswith(('Imbalance-', 'Orphan-')) or name == 'Trading'


def book_currency(book, stated: Optional[str] = None) -> str:
    """The mnemonic of the currency the book is kept in, such as "HKD"."""
    table = book.get_table()

    def known(code: str) -> bool:
        return table.lookup('CURRENCY', code) is not None

    if stated is not None and str(stated).strip():
        code = str(stated).strip()
        if not known(code):
            raise BookCurrencyUnknownError(
                f'--currency {code}: GnuCash knows no currency {code}.')
        return code

    given = get_book_custom_metadata(book).get(BASE_CURRENCY_KEY)
    if given is not None and str(given).strip():
        code = str(given).strip()
        if not known(code):
            raise BookCurrencyUnknownError(
                f'The company block gives base_currency {code}, and GnuCash knows no '
                f'currency {code}. {_HOW_TO_STATE_IT}')
        return code

    # The accounts GnuCash makes for itself are passed over. Its scrub completes
    # a transaction whose splits do not add up by parking the difference in
    # `Imbalance-<CUR>`, and puts a split whose account has gone in
    # `Orphan-<CUR>` — one of each per currency it met, as children of the root,
    # which is why `test_full_conversion_chain.py` can filter them by name.
    # `Trading` is the same: GnuCash makes it, and the accounts under it, for a
    # book whose "Use Trading Accounts" option is on.
    #
    # None of them says which currency the book is kept in. A book kept in CAD
    # that once met a USD transaction GnuCash had to complete holds
    # `Imbalance-CAD` and `Imbalance-USD`, and counting those made its
    # top-level currencies two and its answer none.
    held = sorted({account.GetCommodity().get_mnemonic()
                   for account in book.get_root_account().get_children()
                   if account.GetCommodity() is not None
                   and account.GetCommodity().get_namespace() == 'CURRENCY'
                   and not _gnucash_made_it(account.GetName() or '')})
    if len(held) == 1:
        return held[0]
    if not held:
        raise BookCurrencyUnknownError(
            f'The book has no top-level account held in a currency, so nothing says '
            f'which currency it is kept in. {_HOW_TO_STATE_IT}')
    raise BookCurrencyUnknownError(
        f'The book\'s top-level accounts are held in {", ".join(held)}, so nothing says '
        f'which of them the book is kept in. {_HOW_TO_STATE_IT}')


def the_books_own_currency_or(book, given: str) -> str:
    """The currency the book is kept in, or `given` where nothing says which.

    What an income or expense account is asked to be kept in. A statement drawn
    in another currency does not change the currency the book is kept in, and
    an account kept in the book's own currency is not warned about because a
    page was asked for in US dollars. Where the book does not say, the currency
    the reader gave is the only answer there is.
    """
    try:
        return book_currency(book)
    except BookCurrencyUnknownError:
        return given
