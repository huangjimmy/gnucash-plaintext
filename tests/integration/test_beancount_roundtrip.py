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

            # Verify counts match
            assert result.commodities_created > 0
            assert result.accounts_created == original_accounts
            assert result.transactions_created == original_transactions

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
