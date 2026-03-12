"""
BookCloser service for year-end book closing.

Handles multi-currency year-end closing:
- Zeroes out all Income/Expense account balances cumulatively up to closing date
- Creates one closing transaction per currency
- Auto-creates Equity:Retained Earnings:{currency} accounts as needed
"""

from datetime import date
from fractions import Fraction
from typing import Dict, List, Optional, Set, Tuple

from gnucash import Account, GncNumeric, Split, Transaction
from gnucash.gnucash_core_c import ACCT_TYPE_EQUITY, ACCT_TYPE_EXPENSE, ACCT_TYPE_INCOME

from infrastructure.gnucash.utils import find_account

CLOSING_DESCRIPTION_PREFIX = "Closing entry"


class BookCloser:
    """Service for closing books with multi-currency support"""

    def get_balance_as_of_date(
        self,
        account: Account,
        closing_date: date,
        exclude_guids: Optional[Set[str]] = None,
    ) -> Fraction:
        """
        Get account balance as of closing_date by summing splits on or before that date.

        Returns balance as a Python Fraction for exact arithmetic.
        Positive = debit balance, Negative = credit balance.

        Args:
            account: GnuCash account
            closing_date: Include splits on or before this date
            exclude_guids: Set of transaction GUIDs to exclude (used for --force dry-run)
        """
        total = Fraction(0)
        for split in account.GetSplitList():
            tx = split.GetParent()
            tx_date = tx.GetDate()
            if date(tx_date.year, tx_date.month, tx_date.day) <= closing_date:
                if exclude_guids and tx.GetGUID().to_string() in exclude_guids:
                    continue
                value = split.GetValue()
                total += Fraction(value.num(), value.denom())
        return total

    def is_closed(self, root: Account, closing_date: date) -> bool:
        """
        Check if books are closed as of closing_date.

        Definition: All Income/Expense accounts have zero balance as of the closing date.
        This is the ground truth — if balances are zero, the books are closed
        regardless of how it was achieved.
        """
        for account in root.get_descendants():
            account_type = account.GetType()
            if account_type not in (ACCT_TYPE_INCOME, ACCT_TYPE_EXPENSE):
                continue
            balance = self.get_balance_as_of_date(account, closing_date)
            if balance != Fraction(0):
                return False
        return True

    def group_accounts_by_currency(
        self,
        root: Account,
        closing_date: date,
        exclude_guids: Optional[Set[str]] = None,
    ) -> Dict[str, List[Tuple[Account, Fraction]]]:
        """
        Group Income/Expense accounts with non-zero balances by their commodity.

        Returns: {currency_code: [(account, balance), ...]}
        Only includes accounts with non-zero balances as of closing_date.

        Args:
            root: Root account
            closing_date: Date to compute balances as of
            exclude_guids: Transaction GUIDs to exclude from balance computation
        """
        accounts_by_currency: Dict[str, List[Tuple[Account, Fraction]]] = {}

        for account in root.get_descendants():
            account_type = account.GetType()
            if account_type not in (ACCT_TYPE_INCOME, ACCT_TYPE_EXPENSE):
                continue

            commodity = account.GetCommodity()
            if commodity is None:
                continue

            currency_code = commodity.get_mnemonic()
            balance = self.get_balance_as_of_date(account, closing_date, exclude_guids)

            if balance != Fraction(0):
                if currency_code not in accounts_by_currency:
                    accounts_by_currency[currency_code] = []
                accounts_by_currency[currency_code].append((account, balance))

        return accounts_by_currency

    def find_closing_transactions(
        self, root: Account, closing_date: date
    ) -> List[Transaction]:
        """
        Find existing closing transactions on the given date.

        Identifies by: date == closing_date AND description starts with "Closing entry ("
        Returns unique transactions (deduped by GUID).
        """
        closing_txns = []
        seen_guids: Set[str] = set()

        for account in root.get_descendants():
            for split in account.GetSplitList():
                tx = split.GetParent()
                tx_date = tx.GetDate()
                if date(tx_date.year, tx_date.month, tx_date.day) != closing_date:
                    continue
                desc = tx.GetDescription()
                if not desc.startswith(f"{CLOSING_DESCRIPTION_PREFIX} ("):
                    continue
                guid = tx.GetGUID().to_string()
                if guid not in seen_guids:
                    seen_guids.add(guid)
                    closing_txns.append(tx)

        return closing_txns

    def get_or_create_equity_account(
        self,
        book,
        root: Account,
        equity_template: str,
        currency_code: str,
    ) -> Tuple[Account, bool]:
        """
        Get or create the equity account for a currency.

        For template "Equity:Retained Earnings" and currency "CAD",
        finds or creates "Equity:Retained Earnings:CAD".
        Each missing level in the path is created as ACCT_TYPE_EQUITY.

        Returns:
            (account, was_created) tuple
        """
        full_path = f"{equity_template}:{currency_code}"

        existing = find_account(root, full_path)
        if existing is not None:
            return existing, False

        commod_table = book.get_table()
        currency = commod_table.lookup("CURRENCY", currency_code)

        parts = full_path.split(":")
        current = root

        for part in parts:
            found = None
            for child in current.get_children_sorted():
                if child.GetName() == part:
                    found = child
                    break

            if found is not None:
                current = found
            else:
                new_account = Account(book)
                new_account.SetName(part)
                new_account.SetType(ACCT_TYPE_EQUITY)
                new_account.SetCommodity(currency)
                current.append_child(new_account)
                current = new_account

        return current, True

    def create_closing_transaction(
        self,
        book,
        closing_date: date,
        currency_code: str,
        account_balances: List[Tuple[Account, Fraction]],
        equity_account: Account,
    ) -> Transaction:
        """
        Create a closing transaction for one currency.

        For each Income/Expense account:
            split value = -balance  (zeroes out the account)

        Equity split = sum(all account balances)  (balances the transaction)

        Proof of balance:
            sum(-balance for each) + sum(balances) = 0 ✓

        Example (CAD, Income=1000, Expenses=300):
            Income:Salary       +1000  (debit, zeroes -1000 credit balance)
            Expenses:Food        -300  (credit, zeroes +300 debit balance)
            Equity:RE:CAD        -700  (credit, net income flows to equity)
            Sum = 1000 - 300 - 700 = 0 ✓
        """
        commod_table = book.get_table()
        currency = commod_table.lookup("CURRENCY", currency_code)
        currency_fraction = currency.get_fraction()

        tx = Transaction(book)
        tx.BeginEdit()
        tx.SetCurrency(currency)
        tx.SetDate(closing_date.day, closing_date.month, closing_date.year)
        tx.SetDescription(f"{CLOSING_DESCRIPTION_PREFIX} ({currency_code})")

        equity_balance = Fraction(0)

        for account, balance in account_balances:
            closing_value = -balance
            numerator = int(closing_value * currency_fraction)
            split = Split(book)
            split.SetParent(tx)
            split.SetAccount(account)
            split.SetValue(GncNumeric(numerator, currency_fraction))
            equity_balance += balance

        equity_numerator = int(equity_balance * currency_fraction)
        equity_split = Split(book)
        equity_split.SetParent(tx)
        equity_split.SetAccount(equity_account)
        equity_split.SetValue(GncNumeric(equity_numerator, currency_fraction))

        tx.CommitEdit()
        return tx
