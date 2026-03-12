"""
Conflict resolution service for GnuCash transactions.

Handles conflicts when transactions have the same signature (date + accounts)
but different amounts. Provides strategies for resolving such conflicts.
"""

from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from gnucash import Transaction


class ResolutionStrategy(Enum):
    """Strategy for resolving transaction conflicts"""
    KEEP_EXISTING = "keep_existing"
    KEEP_INCOMING = "keep_incoming"
    SKIP = "skip"
    MANUAL = "manual"


class ConflictInfo:
    """Information about a conflicting transaction pair"""

    def __init__(self, existing: Transaction, incoming: Transaction):
        """
        Initialize conflict information.

        Args:
            existing: Transaction already in GnuCash file
            incoming: Conflicting transaction to be imported
        """
        self.existing = existing
        self.incoming = incoming
        self._extract_info()

    def _extract_info(self):
        """Extract relevant information from both transactions"""
        # Existing transaction info
        self.existing_date = self.existing.GetDate().strftime("%Y-%m-%d")
        self.existing_description = self.existing.GetDescription()
        self.existing_splits = self._get_split_info(self.existing)

        # Incoming transaction info
        self.incoming_date = self.incoming.GetDate().strftime("%Y-%m-%d")
        self.incoming_description = self.incoming.GetDescription()
        self.incoming_splits = self._get_split_info(self.incoming)

    def _get_split_info(self, transaction: Transaction) -> List[Dict[str, Any]]:
        """
        Extract split information from a transaction.

        Args:
            transaction: Transaction to extract from

        Returns:
            List of dicts with account name and value
        """
        splits = []
        for split in transaction.GetSplitList():
            account = split.GetAccount()
            account_name = self._get_account_full_name(account)
            value = split.GetValue()
            splits.append({
                'account': account_name,
                'value': value,
                'value_num': value.num(),
                'value_denom': value.denom()
            })
        return splits

    def _get_account_full_name(self, account) -> str:
        """Get full hierarchical account name"""
        parent = account.get_parent()
        name = account.GetName()

        if parent is not None and not parent.is_root():
            name = ":".join([self._get_account_full_name(parent), name])
        return name

    def get_summary(self) -> str:
        """
        Get human-readable summary of the conflict.

        Returns:
            Multi-line string describing the conflict
        """
        lines = []
        lines.append(f"Conflict on {self.existing_date}:")
        lines.append(f"  Existing: {self.existing_description}")
        for split in self.existing_splits:
            value = f"{split['value_num']}/{split['value_denom']}"
            lines.append(f"    {split['account']}: {value}")

        lines.append(f"  Incoming: {self.incoming_description}")
        for split in self.incoming_splits:
            value = f"{split['value_num']}/{split['value_denom']}"
            lines.append(f"    {split['account']}: {value}")

        return "\n".join(lines)

    def amounts_differ(self) -> bool:
        """
        Check if the amounts differ between transactions.

        Returns:
            True if amounts are different
        """
        if len(self.existing_splits) != len(self.incoming_splits):
            return True

        # Sort by account name for comparison
        existing_sorted = sorted(self.existing_splits, key=lambda s: s['account'])
        incoming_sorted = sorted(self.incoming_splits, key=lambda s: s['account'])

        for e, i in zip(existing_sorted, incoming_sorted):
            if e['account'] != i['account']:
                return True
            if e['value_num'] != i['value_num'] or e['value_denom'] != i['value_denom']:
                return True

        return False


class ConflictResolver:
    """Service for resolving transaction conflicts"""

    def __init__(self):
        """Initialize conflict resolver"""
        pass

    def create_conflict_info(self, existing: Transaction, incoming: Transaction) -> ConflictInfo:
        """
        Create conflict information object.

        Args:
            existing: Existing transaction in GnuCash
            incoming: Incoming conflicting transaction

        Returns:
            ConflictInfo object with details
        """
        return ConflictInfo(existing, incoming)

    def resolve(
        self,
        conflicts: List[Tuple[Transaction, Transaction]],
        strategy: ResolutionStrategy = ResolutionStrategy.SKIP
    ) -> Tuple[List[Transaction], List[ConflictInfo]]:
        """
        Resolve a list of conflicts using the given strategy.

        Args:
            conflicts: List of (existing, incoming) transaction pairs
            strategy: Resolution strategy to apply

        Returns:
            Tuple of:
            - List of transactions to import
            - List of ConflictInfo for unresolved conflicts
        """
        to_import = []
        unresolved = []

        for existing, incoming in conflicts:
            conflict_info = ConflictInfo(existing, incoming)

            if strategy == ResolutionStrategy.KEEP_EXISTING:
                # Don't import, keep existing
                continue
            elif strategy == ResolutionStrategy.KEEP_INCOMING:
                # Import the incoming, will need to delete existing first
                to_import.append(incoming)
            elif strategy == ResolutionStrategy.SKIP:
                # Skip both, add to unresolved
                unresolved.append(conflict_info)
            elif strategy == ResolutionStrategy.MANUAL:
                # Requires manual intervention
                unresolved.append(conflict_info)

        return to_import, unresolved

    def resolve_single(
        self,
        existing: Transaction,
        incoming: Transaction,
        strategy: ResolutionStrategy
    ) -> Optional[Transaction]:
        """
        Resolve a single conflict.

        Args:
            existing: Existing transaction
            incoming: Incoming transaction
            strategy: How to resolve

        Returns:
            Transaction to import, or None if conflict unresolved
        """
        if strategy == ResolutionStrategy.KEEP_EXISTING:
            return None
        elif strategy == ResolutionStrategy.KEEP_INCOMING:
            return incoming
        elif strategy in (ResolutionStrategy.SKIP, ResolutionStrategy.MANUAL):
            return None

        return None

    def get_resolution_choices(self, conflict_info: ConflictInfo) -> List[Dict[str, Any]]:
        """
        Get available resolution choices for a conflict.

        Args:
            conflict_info: Information about the conflict

        Returns:
            List of dicts with choice information
        """
        choices = []

        choices.append({
            'strategy': ResolutionStrategy.KEEP_EXISTING,
            'label': 'Keep existing transaction',
            'description': f'Keep: {conflict_info.existing_description}'
        })

        choices.append({
            'strategy': ResolutionStrategy.KEEP_INCOMING,
            'label': 'Use incoming transaction',
            'description': f'Use: {conflict_info.incoming_description}'
        })

        choices.append({
            'strategy': ResolutionStrategy.SKIP,
            'label': 'Skip both',
            'description': 'Do not import, keep existing unchanged'
        })

        return choices

    def format_conflict_report(self, conflicts: List[ConflictInfo]) -> str:
        """
        Format a report of unresolved conflicts.

        Args:
            conflicts: List of ConflictInfo objects

        Returns:
            Formatted report string
        """
        if not conflicts:
            return "No conflicts to report."

        lines = []
        lines.append(f"Found {len(conflicts)} conflict(s):")
        lines.append("")

        for i, conflict in enumerate(conflicts, 1):
            lines.append(f"Conflict {i}:")
            lines.append(conflict.get_summary())
            lines.append("")

        return "\n".join(lines)
