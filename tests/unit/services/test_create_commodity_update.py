"""
Tests for `GnuCashImporter.create_commodity` honoring the user's declared
fraction even when the commodity already exists in the book.

Two angles:

1. CURRENCY commodity (KRW) — proves the new "update existing" branch fires
   and the in-memory fraction matches what the user declared. We don't assert
   on save+reopen because GnuCash 5.15+ normalises ISO 4217 currencies on
   save (Bug 666536 fix); that is upstream behaviour.

2. Non-CURRENCY commodity (custom unit, e.g. a stock-like or points
   commodity) — proves the same update branch fires AND the value persists
   through save+reopen on every supported GnuCash version, since GnuCash
   does not touch user-defined commodity namespaces.
"""

import os
import tempfile


def _fresh_book_path():
    fd, path = tempfile.mkstemp(suffix='.gnucash')
    os.close(fd)
    os.unlink(path)
    return path


def _make_create_commodity_directive(mnemonic: str, fullname: str, namespace: str, fraction: int):
    from services.gnucash_importer import DirectiveType, PlaintextDirective
    d = PlaintextDirective(
        directive_type=DirectiveType.CREATE_COMMODITY,
        level=0,
        line=f"commodity {namespace}.{mnemonic}",
    )
    d.metadata = {
        'mnemonic': mnemonic,
        'fullname': fullname,
        'namespace': namespace,
        'fraction': fraction,
    }
    return d


def test_user_fraction_overrides_pre_registered_currency_in_memory():
    """Pre-registered KRW gets the user's fraction in memory after import."""
    from repositories.gnucash_repository import GnuCashRepository
    from services.gnucash_importer import GnuCashImporter

    path = _fresh_book_path()
    GnuCashRepository.create_new_file(path)
    repo = GnuCashRepository(path)
    repo.open()
    try:
        book = repo.book
        krw = book.get_table().lookup('CURRENCY', 'KRW')
        assert krw is not None, "KRW should be pre-registered"
        pre_fraction = krw.get_fraction()
        # User-chosen fraction guaranteed to differ from any GnuCash default
        # (5.10 ships KRW with 100, 5.15 ships 1; neither equals 1000).
        user_fraction = 1000

        directive = _make_create_commodity_directive(
            mnemonic='KRW', fullname='Won', namespace='CURRENCY', fraction=user_fraction
        )
        GnuCashImporter.create_commodity(directive, book)

        krw_after = book.get_table().lookup('CURRENCY', 'KRW')
        assert krw_after.get_fraction() == user_fraction, (
            f"Importer must honor user's fraction={user_fraction}; "
            f"saw {krw_after.get_fraction()} (pre-import was {pre_fraction})"
        )
    finally:
        repo.close()
        if os.path.exists(path):
            os.unlink(path)


def test_user_fraction_overrides_existing_custom_commodity_through_save():
    """Non-CURRENCY commodity update survives save+reopen on every distro.

    First import creates the commodity with fraction A; second import
    declares the same commodity with fraction B; after save+reopen the
    persisted fraction is B.
    """
    from repositories.gnucash_repository import GnuCashRepository
    from services.gnucash_importer import GnuCashImporter

    path = _fresh_book_path()
    namespace = 'CUSTOM'
    mnemonic = 'PTS'
    fullname = 'Loyalty Points'

    GnuCashRepository.create_new_file(path)
    repo = GnuCashRepository(path)
    repo.open()
    try:
        d1 = _make_create_commodity_directive(mnemonic, fullname, namespace, 10)
        GnuCashImporter.create_commodity(d1, repo.book)
        assert repo.book.get_table().lookup(namespace, mnemonic).get_fraction() == 10
        # Re-declare at fraction=1000 → update branch fires.
        d2 = _make_create_commodity_directive(mnemonic, fullname, namespace, 1000)
        GnuCashImporter.create_commodity(d2, repo.book)
        assert repo.book.get_table().lookup(namespace, mnemonic).get_fraction() == 1000
        repo.save()
    finally:
        repo.close()

    repo2 = GnuCashRepository(path)
    repo2.open()
    try:
        commodity = repo2.book.get_table().lookup(namespace, mnemonic)
        assert commodity is not None, f"Custom commodity {namespace}.{mnemonic} should persist"
        assert commodity.get_fraction() == 1000, (
            f"User-declared fraction must survive save+reopen for non-CURRENCY "
            f"commodities; saw {commodity.get_fraction()}"
        )
    finally:
        repo2.close()
        if os.path.exists(path):
            os.unlink(path)
