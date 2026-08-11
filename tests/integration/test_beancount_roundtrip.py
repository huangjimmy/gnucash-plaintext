"""
Test bidirectional GnuCash ↔ Beancount conversion.

Tests that we can export GnuCash to beancount and import it back without data loss.
"""

import tempfile

import pytest

from repositories.gnucash_repository import GnuCashRepository
from use_cases.export_beancount import ExportBeancountUseCase
from use_cases.import_beancount import ImportBeancountUseCase


class TestBeancountRoundtrip:
    """Test round-trip conversion: GnuCash → Beancount → GnuCash"""

    def test_roundtrip_preserves_all_data(self, temp_gnucash_with_transactions):
        """Test that exporting to beancount and importing back preserves all data"""
        # Export to beancount
        repo1 = GnuCashRepository(temp_gnucash_with_transactions)
        repo1.open()

        try:
            use_case = ExportBeancountUseCase(repo1)
            beancount_content = use_case.execute()

            # Get original data for comparison
            len({
                acc.GetCommodity().get_mnemonic()
                for acc in repo1.get_all_accounts()
                if acc.GetCommodity()
            })
            original_accounts = len(repo1.get_all_accounts())
            original_transactions = len(repo1.get_all_transactions())
            # What each account is denominated in, to compare against — a
            # round trip that quietly substituted a default commodity would
            # otherwise still satisfy every count above it.
            original_commodities = {
                account.get_full_name(): (
                    account.GetCommodity().get_namespace(),
                    account.GetCommodity().get_mnemonic(),
                    account.GetCommodity().get_fraction())
                for account in repo1.get_all_accounts()
                if account.GetCommodity() is not None}

        finally:
            repo1.close()

        # Write beancount to temp file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.beancount', delete=False) as f:
            f.write(beancount_content)
            beancount_file = f.name

        # Import beancount to new GnuCash file
        import os
        fd, new_gnucash_file = tempfile.mkstemp(suffix='.gnucash')
        os.close(fd)
        os.unlink(new_gnucash_file)  # Delete so create_new_file can create it

        GnuCashRepository.create_new_file(new_gnucash_file)
        repo2 = GnuCashRepository(new_gnucash_file)
        repo2.open()

        try:
            import_use_case = ImportBeancountUseCase(repo2)
            result = import_use_case.import_from_file(beancount_file)

            # Verify no errors
            assert not result.has_errors(), f"Import had errors: {result.errors}"

            # Verify counts match. Not `commodities_created > 0`: that counts
            # what the book *gained*, and this book's currencies are in
            # GnuCash's ISO table already, so a faithful round trip creates
            # none of them. What the round trip owes is that each account came
            # back in the commodity it went out in — asking the rebuilt book
            # whether it *has* that commodity cannot fail, because the account
            # resolved it from the table to be created at all.
            assert result.accounts_created == original_accounts
            assert result.transactions_created == original_transactions

            rebuilt = {
                account.get_full_name(): (
                    account.GetCommodity().get_namespace(),
                    account.GetCommodity().get_mnemonic(),
                    account.GetCommodity().get_fraction())
                for account in repo2.get_all_accounts()
                if account.GetCommodity() is not None}
            assert rebuilt == original_commodities, rebuilt

            repo2.save()

        finally:
            repo2.close()

    def test_roundtrip_preserves_account_names_with_spaces(self, temp_gnucash_comprehensive):
        """Test that account names with spaces are preserved through round-trip"""
        # This fixture has accounts like "Assets:Cash in Wallet"
        repo1 = GnuCashRepository(temp_gnucash_comprehensive)
        repo1.open()

        try:
            # Find an account with spaces
            accounts = repo1.get_all_accounts()
            account_with_spaces = None
            for acc in accounts:
                from infrastructure.gnucash.utils import get_account_full_name
                name = get_account_full_name(acc)
                if ' ' in name:
                    account_with_spaces = name
                    break

            assert account_with_spaces is not None, "Test fixture should have accounts with spaces"

            # Export to beancount
            use_case = ExportBeancountUseCase(repo1)
            beancount_content = use_case.execute()

        finally:
            repo1.close()

        # Verify beancount has gnucash-name metadata
        assert 'gnucash-name:' in beancount_content
        assert account_with_spaces in beancount_content

        # Write beancount to temp file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.beancount', delete=False) as f:
            f.write(beancount_content)
            beancount_file = f.name

        # Import back to new GnuCash file
        import os
        fd, new_gnucash_file = tempfile.mkstemp(suffix='.gnucash')
        os.close(fd)
        os.unlink(new_gnucash_file)  # Delete so create_new_file can create it

        GnuCashRepository.create_new_file(new_gnucash_file)
        repo2 = GnuCashRepository(new_gnucash_file)
        repo2.open()

        try:
            import_use_case = ImportBeancountUseCase(repo2)
            result = import_use_case.import_from_file(beancount_file)

            assert not result.has_errors(), f"Import had errors: {result.errors}"

            # Verify the account with spaces was recreated
            recreated_account = repo2.get_account(account_with_spaces)
            assert recreated_account is not None, \
                f"Account '{account_with_spaces}' should be recreated with original name"

        finally:
            repo2.close()

    def test_beancount_export_includes_all_metadata(self, temp_gnucash_with_transactions):
        """Test that beancount export includes all required gnucash-* metadata"""
        repo = GnuCashRepository(temp_gnucash_with_transactions)
        repo.open()

        try:
            use_case = ExportBeancountUseCase(repo)
            beancount_content = use_case.execute()

        finally:
            repo.close()

        # Verify all required metadata is present
        assert 'gnucash-name:' in beancount_content, "Should have account name metadata"
        assert 'gnucash-guid:' in beancount_content, "Should have GUID metadata"
        assert 'gnucash-type:' in beancount_content, "Should have account type metadata"
        assert 'gnucash-mnemonic:' in beancount_content, "Should have commodity mnemonic"
        assert 'gnucash-namespace:' in beancount_content, "Should have commodity namespace"

    def test_import_rejects_beancount_without_metadata(self):
        """Test that import rejects standard beancount files without gnucash-* metadata"""
        # Create a standard beancount file without gnucash-* metadata
        standard_beancount = """
2024-01-01 commodity USD

2024-01-01 open Assets:Bank:Checking USD

2024-01-01 * "Paycheck"
    Assets:Bank:Checking   1000.00 USD
    Income:Salary         -1000.00 USD
"""

        with tempfile.NamedTemporaryFile(mode='w', suffix='.beancount', delete=False) as f:
            f.write(standard_beancount)
            beancount_file = f.name

        # Try to import - should fail validation
        from services.beancount_parser import BeancountParser, BeancountValidationError

        parser = BeancountParser()
        with pytest.raises(BeancountValidationError, match="missing required"):
            parser.parse_file(beancount_file)


# ---------------------------------------------------------------------------
# Helpers shared by data-fidelity tests below
# ---------------------------------------------------------------------------

def _do_roundtrip(source_path: str) -> tuple:
    """
    Export *source_path* to beancount then import into a fresh GnuCash file.

    Returns (repo2, new_path) — caller must repo2.close() and os.unlink(new_path).
    """
    import os

    repo1 = GnuCashRepository(source_path)
    repo1.open()
    try:
        beancount_content = ExportBeancountUseCase(repo1).execute()
    finally:
        repo1.close()

    fd, beancount_path = tempfile.mkstemp(suffix='.beancount')
    with os.fdopen(fd, 'w') as f:
        f.write(beancount_content)

    fd2, new_path = tempfile.mkstemp(suffix='.gnucash')
    os.close(fd2)
    os.unlink(new_path)

    repo2 = None
    try:
        GnuCashRepository.create_new_file(new_path)
        repo2 = GnuCashRepository(new_path)
        repo2.open()
        result = ImportBeancountUseCase(repo2).import_from_file(beancount_path)
        assert not result.has_errors(), f"Import had errors: {result.errors}"
        repo2.save()
    except Exception:
        # Clean up on failure so caller never receives an open repo or stale file
        import contextlib
        if repo2 is not None:
            with contextlib.suppress(Exception):
                repo2.close()
        with contextlib.suppress(OSError):
            os.unlink(new_path)
        raise
    finally:
        os.unlink(beancount_path)

    return repo2, new_path


def _make_roundtrip_book():
    """
    Build a minimal GnuCash file with a rich variety of accounts and one
    transaction that exercises every field the roundtrip must preserve:

    Accounts (all referenced by at least one transaction so they get exported):
        Assets:Bank:Checking   BANK    CAD
        Expenses:Groceries     EXPENSE CAD
        Income:Salary          INCOME  CAD
        PersonalLoan           LIABILITY CAD  ← ROOT-LEVEL, no 'Liabilities:' prefix
                                               → exercises the 'Liability' bug fix

    The PersonalLoan account is created at the root to ensure
    need_append_top_level_prefix=True so determine_prefix() is actually called.
    Accounts already under 'Liabilities:...' skip that code path entirely.

    Transactions:
      2024-03-15  "Work expense reimbursement"  num="42"  notes="Expense report #99"
          Expenses:Groceries   +75.00  (memo="team lunch", action="expense")
          Assets:Bank:Checking -75.00

      2024-03-01  "March salary"
          Assets:Bank:Checking +3000.00
          Income:Salary        -3000.00

      2024-03-05  "Loan repayment"
          PersonalLoan         +200.00
          Assets:Bank:Checking -200.00

    Returns path.  Caller must unlink(path).
    """
    import os

    import gnucash
    from gnucash import Account, GncNumeric, Session, Split, Transaction

    fd, path = tempfile.mkstemp(suffix='.gnucash')
    os.close(fd)
    os.unlink(path)

    try:
        from gnucash import SessionOpenMode
        session = Session(f'xml://{path}', SessionOpenMode.SESSION_NEW_STORE)
    except ImportError:
        session = Session(f'xml://{path}', is_new=True)

    book = session.book
    root = book.get_root_account()
    cad = book.get_table().lookup('CURRENCY', 'CAD')

    def _acct(name, atype, parent):
        a = Account(book)
        a.SetName(name)
        a.SetType(atype)
        a.SetCommodity(cad)
        parent.append_child(a)
        return a

    assets = _acct('Assets', gnucash.ACCT_TYPE_ASSET, root)
    bank = _acct('Bank', gnucash.ACCT_TYPE_BANK, assets)
    checking = _acct('Checking', gnucash.ACCT_TYPE_BANK, bank)

    expenses = _acct('Expenses', gnucash.ACCT_TYPE_EXPENSE, root)
    groceries = _acct('Groceries', gnucash.ACCT_TYPE_EXPENSE, expenses)

    income = _acct('Income', gnucash.ACCT_TYPE_INCOME, root)
    salary = _acct('Salary', gnucash.ACCT_TYPE_INCOME, income)

    # Root-level LIABILITY account (full name = "PersonalLoan", no "Liabilities:" prefix).
    # This is the account type that triggered the None-prefix bug before the fix.
    personal_loan = _acct('PersonalLoan', gnucash.ACCT_TYPE_LIABILITY, root)

    def _tx(date_d, date_m, date_y, desc, num=None, notes=None, splits=None):
        t = Transaction(book)
        t.BeginEdit()
        t.SetCurrency(cad)
        t.SetDate(date_d, date_m, date_y)
        t.SetDescription(desc)
        if num:
            t.SetNum(num)
        if notes:
            t.SetNotes(notes)
        for acct, num_val, memo, action in (splits or []):
            s = Split(book)
            s.SetParent(t)
            s.SetAccount(acct)
            s.SetValue(GncNumeric(num_val, 100))
            s.SetAmount(GncNumeric(num_val, 100))
            if memo:
                s.SetMemo(memo)
            if action:
                s.SetAction(action)
        t.CommitEdit()

    _tx(15, 3, 2024, "Work expense reimbursement", num="42",
        notes="Expense report #99",
        splits=[
            (groceries,  7500, "team lunch", "expense"),
            (checking,  -7500, None, None),
        ])

    _tx(1, 3, 2024, "March salary", splits=[
        (checking,   300000, None, None),
        (salary,    -300000, None, None),
    ])

    _tx(5, 3, 2024, "Loan repayment", splits=[
        (personal_loan,  20000, None, None),
        (checking,      -20000, None, None),
    ])

    session.save()
    session.end()

    return path


# ---------------------------------------------------------------------------
# Data-fidelity roundtrip tests
# ---------------------------------------------------------------------------

class TestBeancountRoundtripFidelity:
    """
    Verify that specific field VALUES (not just counts) survive the
    GnuCash → Beancount → GnuCash cycle.
    """

    def test_transaction_amounts_preserved(self):
        """Split amounts survive export→import with exact numeric fidelity."""
        import os

        from infrastructure.gnucash.utils import find_account, get_account_full_name

        path = _make_roundtrip_book()
        try:
            repo2, new_path = _do_roundtrip(path)
            try:
                root = repo2.get_root_account()
                groceries = find_account(root, 'Expenses:Groceries')
                assert groceries is not None

                txs = repo2.get_all_transactions()
                # Find the split for Groceries
                grocery_splits = [
                    s for tx in txs
                    for s in tx.GetSplitList()
                    if get_account_full_name(s.GetAccount()) == 'Expenses:Groceries'
                ]
                assert len(grocery_splits) == 1
                val = grocery_splits[0].GetValue()
                # 75.00 CAD stored as 7500/100
                assert val.num() == 7500
                assert val.denom() == 100
            finally:
                repo2.close()
                os.unlink(new_path)
        finally:
            os.unlink(path)

    def test_transaction_description_and_num_preserved(self):
        """Transaction description (narration) and num (payee) survive the round-trip."""
        import os

        path = _make_roundtrip_book()
        try:
            repo2, new_path = _do_roundtrip(path)
            try:
                txs = repo2.get_all_transactions()
                expense_tx = next(
                    t for t in txs
                    if t.GetDescription() == "Work expense reimbursement"
                )
                assert expense_tx.GetNum() == "42"
            finally:
                repo2.close()
                os.unlink(new_path)
        finally:
            os.unlink(path)

    def test_transaction_notes_preserved(self):
        """Transaction notes survive the round-trip."""
        import os

        path = _make_roundtrip_book()
        try:
            repo2, new_path = _do_roundtrip(path)
            try:
                txs = repo2.get_all_transactions()
                expense_tx = next(
                    t for t in txs
                    if t.GetDescription() == "Work expense reimbursement"
                )
                assert expense_tx.GetNotes() == "Expense report #99"
            finally:
                repo2.close()
                os.unlink(new_path)
        finally:
            os.unlink(path)

    def test_transaction_date_preserved(self):
        """Transaction date survives the round-trip."""
        import os

        path = _make_roundtrip_book()
        try:
            repo2, new_path = _do_roundtrip(path)
            try:
                txs = repo2.get_all_transactions()
                expense_tx = next(
                    t for t in txs
                    if t.GetDescription() == "Work expense reimbursement"
                )
                d = expense_tx.GetDate()
                # GetDate() returns datetime on newer GnuCash bindings;
                # older bindings (GnuCash 3.8-4.4) return time.struct_time.
                year  = d.year  if hasattr(d, 'year')  else d.tm_year
                month = d.month if hasattr(d, 'month') else d.tm_mon
                day   = d.day   if hasattr(d, 'day')   else d.tm_mday
                assert year == 2024
                assert month == 3
                assert day == 15
            finally:
                repo2.close()
                os.unlink(new_path)
        finally:
            os.unlink(path)

    def test_split_memo_and_action_preserved(self):
        """Split-level memo and action survive the round-trip."""
        import os

        from infrastructure.gnucash.utils import get_account_full_name

        path = _make_roundtrip_book()
        try:
            repo2, new_path = _do_roundtrip(path)
            try:
                txs = repo2.get_all_transactions()
                grocery_split = next(
                    s for tx in txs
                    for s in tx.GetSplitList()
                    if get_account_full_name(s.GetAccount()) == 'Expenses:Groceries'
                )
                assert grocery_split.GetMemo() == "team lunch"
                assert grocery_split.GetAction() == "expense"
            finally:
                repo2.close()
                os.unlink(new_path)
        finally:
            os.unlink(path)

    def test_account_types_preserved(self):
        """Account types (BANK, EXPENSE, INCOME) survive the round-trip."""
        import os

        import gnucash

        from infrastructure.gnucash.utils import find_account

        path = _make_roundtrip_book()
        try:
            repo2, new_path = _do_roundtrip(path)
            try:
                root = repo2.get_root_account()
                checking = find_account(root, 'Assets:Bank:Checking')
                groceries = find_account(root, 'Expenses:Groceries')
                salary = find_account(root, 'Income:Salary')

                assert checking is not None
                assert groceries is not None
                assert salary is not None
                assert checking.GetType() == gnucash.ACCT_TYPE_BANK
                assert groceries.GetType() == gnucash.ACCT_TYPE_EXPENSE
                assert salary.GetType() == gnucash.ACCT_TYPE_INCOME
            finally:
                repo2.close()
                os.unlink(new_path)
        finally:
            os.unlink(path)

    def test_liability_account_type_preserved(self):
        """
        Liability-type account survives export→import with correct type.

        This is the regression test for the beancount_converter bug where
        'Liability' account type fell through determine_prefix() and produced
        a 'None:...' beancount name, causing silent data corruption on export.

        After the fix, 'Liability' type correctly maps to the 'Liabilities:'
        beancount prefix.
        """
        import os

        import gnucash

        from infrastructure.gnucash.utils import find_account

        path = _make_roundtrip_book()
        try:
            # Verify the beancount output uses correct prefix (not None:)
            repo1 = GnuCashRepository(path)
            repo1.open()
            try:
                beancount_content = ExportBeancountUseCase(repo1).execute()
            finally:
                repo1.close()

            # The root-level 'PersonalLoan' account (type LIABILITY) has no 'Liabilities:'
            # prefix, so determine_prefix() must be called.  Before the fix it returned
            # None → "None:PersonalLoan". After the fix it returns "Liabilities".
            assert 'Liabilities:PersonalLoan' in beancount_content, (
                "Root-level Liability account should export with 'Liabilities:' prefix"
            )
            assert 'None:' not in beancount_content, (
                "No beancount output should contain 'None:' — that indicates a broken "
                "account-type prefix mapping in beancount_converter"
            )

            # Verify the account reimports at its original GnuCash path with correct type.
            # On export: "PersonalLoan" → "Liabilities:PersonalLoan" beancount name,
            # but gnucash-name metadata stores "PersonalLoan" (the original root-level path).
            # On import: gnucash-name "PersonalLoan" is used for account creation,
            # so the account is restored at root level as "PersonalLoan", not nested
            # under a "Liabilities" parent.
            repo2, new_path = _do_roundtrip(path)
            try:
                root = repo2.get_root_account()
                loan = find_account(root, 'PersonalLoan')
                assert loan is not None, \
                    "'PersonalLoan' should be recreated at root level after roundtrip"
                assert loan.GetType() == gnucash.ACCT_TYPE_LIABILITY
            finally:
                repo2.close()
                os.unlink(new_path)
        finally:
            os.unlink(path)

    def test_commodity_fraction_preserved(self):
        """Commodity fraction (decimal places) survives the round-trip."""
        import os

        path = _make_roundtrip_book()
        try:
            repo2, new_path = _do_roundtrip(path)
            try:
                cad = repo2.get_commodity('CURRENCY', 'CAD')
                assert cad is not None
                assert cad.get_fraction() == 100
            finally:
                repo2.close()
                os.unlink(new_path)
        finally:
            os.unlink(path)

    def test_no_none_prefix_in_beancount_output(self, temp_gnucash_with_transactions):
        """
        Exporting the standard fixture must never produce 'None:' account names.

        Regression for: beancount_converter.determine_prefix() returning None
        for unrecognised account types, silently producing 'None:<name>'.
        """
        repo = GnuCashRepository(temp_gnucash_with_transactions)
        repo.open()
        try:
            beancount_content = ExportBeancountUseCase(repo).execute()
        finally:
            repo.close()

        assert 'None:' not in beancount_content, (
            "Beancount output contains 'None:' — a beancount_converter bug "
            "is producing invalid account names"
        )

    def test_multi_currency_export_contains_all_commodity_declarations(self, temp_gnucash_comprehensive):
        """
        Exporting a multi-currency book declares all commodities.

        The comprehensive fixture uses CAD, USD, HKD, JPY, KRW and a
        non-currency commodity.  The beancount output must have a 'commodity'
        directive for each one so the file is self-contained.
        """
        repo = GnuCashRepository(temp_gnucash_comprehensive)
        repo.open()
        try:
            beancount_content = ExportBeancountUseCase(repo).execute()
        finally:
            repo.close()

        for currency in ('CAD', 'USD', 'HKD', 'JPY', 'KRW'):
            assert f'commodity {currency}' in beancount_content, (
                f"Multi-currency export should declare commodity {currency}"
            )

    def test_multi_currency_export_emits_total_cost_annotations(
            self, temp_gnucash_comprehensive):
        """
        Cross-currency splits carry beancount's `@@ total commodity`.

        The comprehensive fixture has FX transactions (buying USD with CAD,
        buying HKD with CAD). A split whose account commodity differs from its
        transaction's currency has two figures, and the second has to be
        stated or the entry cannot be read back.

        The *total* form, not the per-unit `@ rate`. A rate is a quotient and
        has to be written to some number of places — the exporter used eight —
        and the importer, having no value to read, rebuilt one as
        `amount × round₈(value / amount)`. That error passes half a cent once
        the amount reaches about a million: ¥2,000,000 worth 18,200.01 CAD
        came back a cent out, its counterpart split came back exact, and
        GnuCash parked the difference in an Imbalance split. `@@` states the
        figure the book holds and nothing is reconstructed.
        """
        repo = GnuCashRepository(temp_gnucash_comprehensive)
        repo.open()
        try:
            beancount_content = ExportBeancountUseCase(repo).execute()
        finally:
            repo.close()

        lines = beancount_content.splitlines()
        # Cross-currency posting lines have the form:
        #   <account> <amount> <commodity> @@ <total> <tx_commodity>
        totals = [ln for ln in lines if ln.startswith('  ') and ' @@ ' in ln]
        assert len(totals) > 0, (
            'Expected at least one posting stating its total in the '
            f'transaction currency:\n{beancount_content}'
        )

        # And none in the rounded per-unit form.
        assert not [ln for ln in lines
                    if ln.startswith('  ') and ' @ ' in ln], lines

        # Spot-check: a CAD-funded transaction with a non-CAD account states
        # its total in CAD.
        assert [ln for ln in totals if ln.endswith(' CAD')], totals

    def test_multi_currency_roundtrip_preserves_transaction_count(self, temp_gnucash_comprehensive):
        """
        A multi-currency book round-trips through beancount without losing transactions.

        Verifies that the full GnuCash → beancount → GnuCash pipeline handles
        cross-currency splits (CAD/USD/HKD/JPY) without errors or data loss.
        """
        import os

        repo1 = GnuCashRepository(temp_gnucash_comprehensive)
        repo1.open()
        try:
            original_tx_count = len(repo1.get_all_transactions())
            original_account_count = len(repo1.get_all_accounts())
            use_case = ExportBeancountUseCase(repo1)
            beancount_content = use_case.execute()
        finally:
            repo1.close()

        assert original_tx_count > 0, "Comprehensive fixture should have transactions"

        with tempfile.NamedTemporaryFile(mode='w', suffix='.beancount', delete=False) as f:
            f.write(beancount_content)
            beancount_file = f.name

        fd, new_gnucash = tempfile.mkstemp(suffix='.gnucash')
        os.close(fd)
        os.unlink(new_gnucash)

        try:
            GnuCashRepository.create_new_file(new_gnucash)
            repo2 = GnuCashRepository(new_gnucash)
            repo2.open()
            try:
                result = ImportBeancountUseCase(repo2).import_from_file(beancount_file)
                assert not result.has_errors(), f"Round-trip import had errors: {result.errors}"
                assert result.accounts_created == original_account_count
                assert result.transactions_created == original_tx_count
            finally:
                repo2.close()
        finally:
            os.unlink(beancount_file)
            if os.path.exists(new_gnucash):
                os.unlink(new_gnucash)
