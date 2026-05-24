"""
Q-020 regression: Num set, Description empty must round-trip without
silently relabeling Num as Description.

This bug is *not* detectable by a plaintext-only roundtrip diff — the buggy
exporter writes the Num value into the slot the parser interprets as
Description, and both sides agree about what the plaintext says. Detection
requires introspecting the re-imported GnuCash transaction directly:
`GetNum()` must return the original Num value and `GetDescription()` must
return the original (empty) description.
"""

import os
import tempfile

from repositories.gnucash_repository import GnuCashRepository
from use_cases.export_transactions import ExportTransactionsUseCase
from use_cases.import_transactions import ImportTransactionsUseCase


def _new_temp_gnucash_path() -> str:
    fd, path = tempfile.mkstemp(suffix='.gnucash')
    os.close(fd)
    os.unlink(path)
    return path


def _new_temp_plaintext_path() -> str:
    fd, path = tempfile.mkstemp(suffix='.txt')
    os.close(fd)
    return path


def _make_book_with_num_only_tx(path: str, num_value: str) -> None:
    """Create a fresh book with a single transaction whose Num is set and
    Description is empty.

    The transaction debits Expenses:Groceries 50 CAD and credits
    Assets:Bank:Checking -50 CAD on 2024-02-15.
    """
    import gnucash
    from gnucash import Account, GncNumeric, Session, Split, Transaction

    try:
        from gnucash import SessionOpenMode
        session = Session(f'xml://{path}', SessionOpenMode.SESSION_NEW_STORE)
    except ImportError:
        session = Session(f'xml://{path}', is_new=True)

    try:
        book = session.book
        root = book.get_root_account()
        cad = book.get_table().lookup('CURRENCY', 'CAD')

        def _add(parent, name, acct_type):
            acct = Account(book)
            acct.SetName(name)
            acct.SetType(acct_type)
            acct.SetCommodity(cad)
            parent.append_child(acct)
            return acct

        assets = _add(root, 'Assets', gnucash.ACCT_TYPE_ASSET)
        bank = _add(assets, 'Bank', gnucash.ACCT_TYPE_BANK)
        checking = _add(bank, 'Checking', gnucash.ACCT_TYPE_BANK)
        expenses = _add(root, 'Expenses', gnucash.ACCT_TYPE_EXPENSE)
        groceries = _add(expenses, 'Groceries', gnucash.ACCT_TYPE_EXPENSE)

        tx = Transaction(book)
        tx.BeginEdit()
        tx.SetCurrency(cad)
        tx.SetDate(15, 2, 2024)
        tx.SetNum(num_value)
        tx.SetDescription('')  # explicit empty — the bug's trigger

        s1 = Split(book)
        s1.SetParent(tx)
        s1.SetAccount(groceries)
        s1.SetValue(GncNumeric(5000, 100))
        s1.SetAmount(GncNumeric(5000, 100))

        s2 = Split(book)
        s2.SetParent(tx)
        s2.SetAccount(checking)
        s2.SetValue(GncNumeric(-5000, 100))
        s2.SetAmount(GncNumeric(-5000, 100))

        tx.CommitEdit()
        session.save()
    finally:
        session.end()
        session.destroy()


def test_num_only_roundtrips_through_plaintext():
    """
    GnuCash book with Num="CHK-001", Description="" → export plaintext →
    import into a fresh GnuCash book → re-imported transaction must still
    have Num="CHK-001" and Description="".

    Without the Q-020 exporter fix this test fails: the plaintext exporter
    writes `2024-02-15 * "CHK-001"`, the parser reads the single quoted
    string as Description, and the re-imported transaction ends up with
    Num="" and Description="CHK-001".
    """
    source_path = _new_temp_gnucash_path()
    target_path = _new_temp_gnucash_path()
    plaintext_path = _new_temp_plaintext_path()

    try:
        _make_book_with_num_only_tx(source_path, num_value='CHK-001')

        with GnuCashRepository(source_path) as repo:
            export_uc = ExportTransactionsUseCase(repo)
            export_result = export_uc.execute()
            plaintext = export_uc.format_as_plaintext(export_result)

        with open(plaintext_path, 'w') as fh:
            fh.write(plaintext)

        # The exported header must carry both the Num and an empty Desc slot.
        assert '2024-02-15 * "CHK-001" ""' in plaintext, (
            "Exporter did not emit explicit empty Description slot when Num was set. "
            f"Header line missing from:\n{plaintext}"
        )

        GnuCashRepository.create_new_file(target_path)
        with GnuCashRepository(target_path) as repo:
            import_uc = ImportTransactionsUseCase(repo)
            import_result = import_uc.import_from_file(plaintext_path)
            repo.save()
            assert import_result.error_count == 0, import_result.errors
            assert import_result.imported_count == 1, (
                f"Expected 1 import, got {import_result.imported_count}"
            )

        # Introspect GnuCash directly — this is the assertion that the bug
        # bypassed in a plaintext-only roundtrip check.
        with GnuCashRepository(target_path) as repo:
            transactions = repo.get_all_transactions()
            assert len(transactions) == 1
            tx = transactions[0]
            assert tx.GetNum() == 'CHK-001', (
                f"Num was silently relabeled. GetNum() returned {tx.GetNum()!r}, "
                f"expected 'CHK-001'."
            )
            assert tx.GetDescription() == '', (
                f"Description should be empty after round-trip but got "
                f"{tx.GetDescription()!r} — Num leaked into the Description slot."
            )
    finally:
        for p in (source_path, target_path, plaintext_path):
            if p and os.path.exists(p):
                os.unlink(p)
