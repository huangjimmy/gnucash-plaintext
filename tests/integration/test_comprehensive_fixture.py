"""
Test the comprehensive fixture to ensure it loads properly

This verifies that the plaintext test data fixture works correctly.
"""

import pytest


class TestComprehensiveFixture:
    """Test comprehensive test data fixture"""

    def test_fixture_loads_successfully(self, temp_gnucash_comprehensive):
        """Test that comprehensive fixture loads without errors"""
        from repositories.gnucash_repository import GnuCashRepository

        with GnuCashRepository(temp_gnucash_comprehensive) as repo:
            # Verify currencies exist
            cad = repo.get_commodity('CURRENCY', 'CAD')
            usd = repo.get_commodity('CURRENCY', 'USD')
            jpy = repo.get_commodity('CURRENCY', 'JPY')
            hkd = repo.get_commodity('CURRENCY', 'HKD')
            krw = repo.get_commodity('CURRENCY', 'KRW')

            assert cad is not None
            assert usd is not None
            assert jpy is not None
            assert hkd is not None
            assert krw is not None

            # Verify non-currency commodity
            membership = repo.get_commodity('Membership Rewards', 'イオン')
            assert membership is not None

            # Verify international accounts exist
            assert repo.get_account('費用 香港:食品雜貨') is not None  # Chinese
            assert repo.get_account('経費 日本:食料品 しょくりょうひん') is not None  # Japanese
            assert repo.get_account('경비 한국:식료품') is not None  # Korean

            # Verify transactions
            transactions = repo.get_all_transactions()
            assert len(transactions) == 13

            # Verify accounts
            accounts = repo.get_all_accounts()
            # Should have many accounts (all the ones declared in plaintext)
            assert len(accounts) > 20

    def test_fixture_has_complex_transactions(self, temp_gnucash_comprehensive):
        """Test that fixture includes complex transaction features"""
        from repositories.gnucash_repository import GnuCashRepository

        with GnuCashRepository(temp_gnucash_comprehensive) as repo:
            transactions = repo.get_all_transactions()

            # Find the forex transaction with notes
            # In GnuCash format: "Forex" is the payee, "I need to get..." is the description
            forex_tx = None
            for tx in transactions:
                desc = tx.GetDescription()
                notes = tx.GetNotes()
                if "Japan trip" in desc or (notes and "Vancouver" in notes):
                    forex_tx = tx
                    break

            assert forex_tx is not None
            assert forex_tx.GetNotes() == "This transaction took place at Vancouver, BC"

            # Verify it has 2 splits
            splits = forex_tx.GetSplitList()
            assert len(splits) == 2

            # Check for memo and action on splits
            has_memo = False
            has_action = False
            for split in splits:
                if split.GetMemo():
                    has_memo = True
                if split.GetAction():
                    has_action = True

            assert has_memo, "Forex transaction should have split memo"
            assert has_action, "Forex transaction should have split action"

    def test_fixture_has_membership_rewards(self, temp_gnucash_comprehensive):
        """Test that fixture includes non-currency commodity transaction"""
        from repositories.gnucash_repository import GnuCashRepository

        with GnuCashRepository(temp_gnucash_comprehensive) as repo:
            # Find membership rewards account
            account = repo.get_account('Assets:Membership Rewards:イオン会員')
            assert account is not None

            # Verify account commodity
            commodity = account.GetCommodity()
            assert commodity.get_namespace() == 'Membership Rewards'
            assert commodity.get_mnemonic() == 'イオン'

            # Verify transaction exists
            transactions = repo.get_transactions_by_account(account)
            assert len(transactions) == 1

            tx = transactions[0]
            assert '歓迎オファー' in tx.GetDescription()
