"""
Integration tests for roundtrip: GnuCash → Plaintext → GnuCash → Plaintext

These tests verify that exporting to plaintext, importing to a new GnuCash file,
and exporting again produces semantically equivalent plaintext output.
"""

import os
import re
import tempfile

import pytest

from repositories.gnucash_repository import GnuCashRepository
from use_cases.export_transactions import ExportTransactionsUseCase
from use_cases.import_transactions import ImportTransactionsUseCase


class TestRoundtrip:
    """Test export-import-export roundtrip"""

    def test_roundtrip_produces_semantic_equivalent(self, temp_gnucash_with_transactions):
        """
        Test that GnuCash → Plaintext → GnuCash → Plaintext produces
        semantically equivalent output.

        GUIDs will differ, but all other data should be identical.
        """
        # Create temp files
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            export1_path = f.name

        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            export2_path = f.name

        # Get temp path for new GnuCash file, then delete it so create_new_file can create it
        with tempfile.NamedTemporaryFile(mode='w', suffix='.gnucash', delete=False) as f:
            new_gnucash_path = f.name
        os.unlink(new_gnucash_path)  # Delete the temp file so create_new_file can create it

        try:
            # STEP 1: Export original to plaintext
            with GnuCashRepository(temp_gnucash_with_transactions) as repo:
                use_case = ExportTransactionsUseCase(repo)
                result = use_case.execute()
                plaintext = use_case.format_as_plaintext(result)

            with open(export1_path, 'w') as f:
                f.write(plaintext)

            # Validate export worked
            assert len(plaintext) > 0, "Export 1 produced empty plaintext"
            assert result.transactions, "Export 1 has no transactions"
            assert result.accounts, "Export 1 has no accounts"
            assert result.commodities, "Export 1 has no commodities"

            # STEP 2: Import plaintext to new GnuCash file
            # Currency will be created from plaintext commodity declarations
            GnuCashRepository.create_new_file(new_gnucash_path)
            with GnuCashRepository(new_gnucash_path) as repo:
                import_use_case = ImportTransactionsUseCase(repo)
                import_result = import_use_case.import_from_file(export1_path)
                repo.save()  # Must save changes!

            # Validate import worked
            assert import_result.imported_count > 0, \
                f"Import failed: imported={import_result.imported_count}, errors={import_result.error_count}"
            assert import_result.error_count == 0, \
                f"Import had errors: {import_result.errors}"

            # STEP 3: Verify imported data by checking transactions
            with GnuCashRepository(new_gnucash_path) as repo:
                transactions = repo.get_all_transactions()
                assert len(transactions) > 0, "New GnuCash file has no transactions after import"
                assert len(transactions) == len(result.transactions), \
                    f"Transaction count mismatch: {len(transactions)} vs {len(result.transactions)}"

            # STEP 4: Export new GnuCash to plaintext
            with GnuCashRepository(new_gnucash_path) as repo:
                use_case = ExportTransactionsUseCase(repo)
                result2 = use_case.execute()
                plaintext2 = use_case.format_as_plaintext(result2)

            with open(export2_path, 'w') as f:
                f.write(plaintext2)

            # Validate second export worked
            assert len(plaintext2) > 0, "Export 2 produced empty plaintext"
            assert result2.transactions, "Export 2 has no transactions"

            # STEP 5: Compare the two exports (normalize GUIDs)
            export1_normalized = self._normalize_guids(plaintext)
            export2_normalized = self._normalize_guids(plaintext2)

            # Compare line by line for better error messages
            export1_lines = export1_normalized.split('\n')
            export2_lines = export2_normalized.split('\n')

            assert len(export1_lines) == len(export2_lines), \
                f"Line count mismatch: {len(export1_lines)} vs {len(export2_lines)}"

            for i, (line1, line2) in enumerate(zip(export1_lines, export2_lines)):
                assert line1 == line2, \
                    f"Line {i+1} differs:\n  Export1: {line1}\n  Export2: {line2}"

        finally:
            for path in [export1_path, export2_path, new_gnucash_path]:
                if os.path.exists(path):
                    os.unlink(path)

    def test_roundtrip_with_date_filter_preserves_all_declarations(self, temp_gnucash_with_transactions):
        """
        Test that filtered export → import → export still preserves
        all commodity and account declarations.
        """
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            export1_path = f.name

        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            export2_path = f.name

        # Get temp path for new GnuCash file, then delete it so create_new_file can create it
        with tempfile.NamedTemporaryFile(mode='w', suffix='.gnucash', delete=False) as f:
            new_gnucash_path = f.name
        os.unlink(new_gnucash_path)  # Delete the temp file so create_new_file can create it

        try:
            # Export with date filter (only 2 transactions)
            with GnuCashRepository(temp_gnucash_with_transactions) as repo:
                use_case = ExportTransactionsUseCase(repo)
                result = use_case.execute(
                    start_date="2024-01-15",
                    end_date="2024-01-20"
                )
                plaintext = use_case.format_as_plaintext(result)

            with open(export1_path, 'w') as f:
                f.write(plaintext)

            # Create and import to new GnuCash
            # Currency will be created from plaintext commodity declarations
            GnuCashRepository.create_new_file(new_gnucash_path)
            with GnuCashRepository(new_gnucash_path) as repo:
                import_use_case = ImportTransactionsUseCase(repo)
                import_use_case.import_from_file(export1_path)
                repo.save()  # Must save changes!

            # Export all transactions from new GnuCash
            with GnuCashRepository(new_gnucash_path) as repo:
                use_case = ExportTransactionsUseCase(repo)
                result = use_case.execute()
                plaintext2 = use_case.format_as_plaintext(result)

            with open(export2_path, 'w') as f:
                f.write(plaintext2)

            # Verify that all accounts were preserved
            with open(export2_path) as f:
                content = f.read()
                # All accounts should be present
                assert "open Assets:Bank:Checking" in content
                assert "open Expenses:Groceries" in content
                assert "open Expenses:Dining" in content

                # But only 2 transactions
                tx_count = len(re.findall(r'^\d{4}-\d{2}-\d{2} \*', content, re.MULTILINE))
                assert tx_count == 2, f"Expected 2 transactions, got {tx_count}"

        finally:
            for path in [export1_path, export2_path, new_gnucash_path]:
                if os.path.exists(path):
                    os.unlink(path)

    def _normalize_guids(self, content: str) -> str:
        """
        Replace all GUIDs with normalized placeholders.

        GUIDs appear as 32-character hex strings without dashes:
        - guid: "52c0652feeee4ef6b283ac29d62b7d71"

        We replace each unique GUID with GUID_001, GUID_002, etc.
        """
        # Pattern to match GUIDs (32-character hex strings without dashes)
        guid_pattern = r'\b[0-9a-f]{32}\b'

        # Find all GUIDs
        guids = re.findall(guid_pattern, content)

        # Create mapping of GUID → placeholder
        guid_map = {}
        for guid in guids:
            if guid not in guid_map:
                guid_map[guid] = f'GUID_{len(guid_map)+1:03d}'

        # Replace GUIDs with placeholders
        normalized = content
        for guid, placeholder in guid_map.items():
            normalized = normalized.replace(guid, placeholder)

        return normalized
