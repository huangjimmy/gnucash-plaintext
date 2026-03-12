"""
Beancount parser service for importing GnuCash-compatible beancount files.

Parses beancount files with GnuCash metadata and validates them for import.
"""

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional


@dataclass
class BeancountCommodity:
    """Beancount commodity with GnuCash metadata"""
    date: datetime
    symbol: str
    gnucash_mnemonic: str
    gnucash_namespace: str
    gnucash_fullname: Optional[str] = None
    gnucash_fraction: int = 100


@dataclass
class BeancountAccount:
    """Beancount account with GnuCash metadata"""
    date: datetime
    account: str
    commodity: str
    gnucash_name: str
    gnucash_guid: str
    gnucash_type: str
    gnucash_placeholder: str
    gnucash_code: Optional[str] = None
    gnucash_description: Optional[str] = None
    gnucash_tax_related: str = "False"


@dataclass
class BeancountPosting:
    """Beancount posting with GnuCash metadata"""
    account: str
    amount: str
    commodity: str
    gnucash_memo: Optional[str] = None
    gnucash_action: Optional[str] = None


@dataclass
class BeancountTransaction:
    """Beancount transaction with GnuCash metadata"""
    date: datetime
    flag: str
    payee: Optional[str]
    narration: Optional[str]
    gnucash_guid: str
    postings: List[BeancountPosting]
    gnucash_notes: Optional[str] = None
    gnucash_doclink: Optional[str] = None


class BeancountValidationError(Exception):
    """Exception raised when beancount file fails validation"""
    pass


class BeancountParser:
    """
    Parse GnuCash-compatible beancount files.

    This parser is specialized for beancount files exported from GnuCash
    with all gnucash-* metadata present. It validates that all required
    metadata exists and no implicit accounts are used.
    """

    def __init__(self):
        self.commodities: List[BeancountCommodity] = []
        self.accounts: List[BeancountAccount] = []
        self.transactions: List[BeancountTransaction] = []
        self.opened_accounts: set = set()
        self.used_accounts: set = set()

    def parse_file(self, file_path: str):
        """
        Parse beancount file and extract all directives.

        Args:
            file_path: Path to beancount file

        Raises:
            BeancountValidationError: If file has validation errors
        """
        with open(file_path) as f:
            content = f.read()

        self.parse(content)

    def parse(self, content: str):
        """
        Parse beancount content string.

        Args:
            content: Beancount file content

        Raises:
            BeancountValidationError: If content has validation errors
        """
        lines = content.split('\n')
        i = 0

        while i < len(lines):
            line = lines[i].strip()

            # Skip empty lines and comments
            if not line or line.startswith(';'):
                i += 1
                continue

            # Parse commodity
            if ' commodity ' in line:
                commodity, lines_consumed = self._parse_commodity(lines, i)
                self.commodities.append(commodity)
                i += lines_consumed
                continue

            # Parse open account
            if ' open ' in line:
                account, lines_consumed = self._parse_account(lines, i)
                self.accounts.append(account)
                self.opened_accounts.add(account.account)
                i += lines_consumed
                continue

            # Parse transaction
            if re.match(r'^\d{4}-\d{2}-\d{2}\s+[*!]', line):
                transaction, lines_consumed = self._parse_transaction(lines, i)
                self.transactions.append(transaction)
                for posting in transaction.postings:
                    self.used_accounts.add(posting.account)
                i += lines_consumed
                continue

            i += 1

        # Validate after parsing
        self._validate()

    def _parse_commodity(self, lines: List[str], start_idx: int) -> tuple:
        """Parse commodity directive and its metadata"""
        line = lines[start_idx].strip()
        match = re.match(r'(\d{4}-\d{2}-\d{2})\s+commodity\s+(\S+)', line)
        if not match:
            raise BeancountValidationError(f"Invalid commodity directive: {line}")

        date_str, symbol = match.groups()
        date = datetime.strptime(date_str, '%Y-%m-%d')

        # Parse metadata
        metadata = {}
        i = start_idx + 1
        while i < len(lines):
            meta_line = lines[i].strip()
            if not meta_line or not meta_line.startswith('gnucash-'):
                break

            match = re.match(r'([\w-]+):\s+"([^"]*)"', meta_line)
            if match:
                key, value = match.groups()
                metadata[key] = value
            i += 1

        # Validate required metadata
        if 'gnucash-mnemonic' not in metadata:
            raise BeancountValidationError(
                f"Commodity {symbol} missing required gnucash-mnemonic metadata"
            )
        if 'gnucash-namespace' not in metadata:
            raise BeancountValidationError(
                f"Commodity {symbol} missing required gnucash-namespace metadata"
            )

        commodity = BeancountCommodity(
            date=date,
            symbol=symbol,
            gnucash_mnemonic=metadata['gnucash-mnemonic'],
            gnucash_namespace=metadata['gnucash-namespace'],
            gnucash_fullname=metadata.get('gnucash-fullname'),
            gnucash_fraction=int(metadata.get('gnucash-fraction', '100'))
        )

        return commodity, i - start_idx

    def _parse_account(self, lines: List[str], start_idx: int) -> tuple:
        """Parse account open directive and its metadata"""
        line = lines[start_idx].strip()
        match = re.match(r'(\d{4}-\d{2}-\d{2})\s+open\s+(\S+)(?:\s+(\S+))?', line)
        if not match:
            raise BeancountValidationError(f"Invalid open directive: {line}")

        date_str, account, commodity = match.groups()
        date = datetime.strptime(date_str, '%Y-%m-%d')

        # Parse metadata
        metadata = {}
        i = start_idx + 1
        while i < len(lines):
            meta_line = lines[i].strip()
            if not meta_line or not meta_line.startswith('gnucash-'):
                break

            match = re.match(r'([\w-]+):\s+"([^"]*)"', meta_line)
            if match:
                key, value = match.groups()
                metadata[key] = value
            i += 1

        # Validate required metadata
        required = ['gnucash-name', 'gnucash-guid', 'gnucash-type', 'gnucash-placeholder']
        for key in required:
            if key not in metadata:
                raise BeancountValidationError(
                    f"Account {account} missing required {key} metadata"
                )

        account_obj = BeancountAccount(
            date=date,
            account=account,
            commodity=commodity or "",
            gnucash_name=metadata['gnucash-name'],
            gnucash_guid=metadata['gnucash-guid'],
            gnucash_type=metadata['gnucash-type'],
            gnucash_placeholder=metadata['gnucash-placeholder'],
            gnucash_code=metadata.get('gnucash-code'),
            gnucash_description=metadata.get('gnucash-description'),
            gnucash_tax_related=metadata.get('gnucash-tax-related', 'False')
        )

        return account_obj, i - start_idx

    def _parse_transaction(self, lines: List[str], start_idx: int) -> tuple:
        """Parse transaction and its postings"""
        line = lines[start_idx].strip()

        # Parse transaction header
        match = re.match(r'(\d{4}-\d{2}-\d{2})\s+([*!])\s*(?:"([^"]*)"\s*)?(?:"([^"]*)")?', line)
        if not match:
            raise BeancountValidationError(f"Invalid transaction: {line}")

        date_str, flag, payee, narration = match.groups()
        date = datetime.strptime(date_str, '%Y-%m-%d')

        # If only one string, it's narration, not payee
        if payee and not narration:
            narration = payee
            payee = None

        # Parse transaction metadata
        tx_metadata = {}
        i = start_idx + 1
        while i < len(lines):
            meta_line = lines[i].strip()
            if not meta_line or not meta_line.startswith('gnucash-'):
                break

            match = re.match(r'([\w-]+):\s+"([^"]*)"', meta_line)
            if match:
                key, value = match.groups()
                # Unescape
                value = value.replace('\\n', '\n').replace('\\"', '"')
                tx_metadata[key] = value
            i += 1

        # Validate required transaction metadata
        if 'gnucash-guid' not in tx_metadata:
            raise BeancountValidationError(
                f"Transaction at {date_str} missing required gnucash-guid metadata"
            )

        # Parse postings
        postings = []
        while i < len(lines):
            posting_line = lines[i].strip()

            # Stop at empty line (end of transaction)
            if not posting_line:
                break

            # Parse posting
            if posting_line.startswith('gnucash-'):
                # This is posting metadata, skip (will be parsed with posting)
                i += 1
                continue

            match = re.match(r'(\S+(?::\S+)*)\s+([-\d.]+)\s+(\S+)', posting_line)
            if not match:
                # Not a posting line, end of transaction
                break

            account, amount, commodity = match.groups()

            # Parse posting metadata
            posting_metadata = {}
            j = i + 1
            while j < len(lines):
                meta_line = lines[j].strip()
                if not meta_line or not meta_line.startswith('gnucash-'):
                    break

                match = re.match(r'([\w-]+):\s+"([^"]*)"', meta_line)
                if match:
                    key, value = match.groups()
                    # Unescape
                    value = value.replace('\\n', '\n').replace('\\"', '"')
                    posting_metadata[key] = value
                j += 1

            posting = BeancountPosting(
                account=account,
                amount=amount,
                commodity=commodity,
                gnucash_memo=posting_metadata.get('gnucash-memo'),
                gnucash_action=posting_metadata.get('gnucash-action')
            )
            postings.append(posting)

            i = j

        transaction = BeancountTransaction(
            date=date,
            flag=flag,
            payee=payee,
            narration=narration,
            gnucash_guid=tx_metadata['gnucash-guid'],
            postings=postings,
            gnucash_notes=tx_metadata.get('gnucash-notes'),
            gnucash_doclink=tx_metadata.get('gnucash-doclink')
        )

        return transaction, i - start_idx

    def _validate(self):
        """Validate parsed beancount file for GnuCash import"""
        errors = []

        # Check for implicit accounts
        implicit_accounts = self.used_accounts - self.opened_accounts
        if implicit_accounts:
            errors.append(
                f"Implicit accounts not allowed: {', '.join(sorted(implicit_accounts))}. "
                f"All accounts must have 'open' directives with gnucash-* metadata."
            )

        if errors:
            raise BeancountValidationError("\n".join(errors))

    def get_account_mapping(self) -> Dict[str, str]:
        """
        Get mapping from beancount account names to GnuCash account names.

        Returns:
            Dict mapping beancount name -> gnucash name
        """
        return {acc.account: acc.gnucash_name for acc in self.accounts}
