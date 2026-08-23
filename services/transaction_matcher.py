"""
Transaction Matcher Service

Provides duplicate detection for transactions using two strategies:
1. GUID-based matching: For transactions exported from GnuCash with GUID metadata
2. Signature-based matching: For new transactions (e.g., from QFX) using
   (date + accounts + doc_link + tx_num + owner)

## Why the signature is `(date, accounts, doc_link, tx_num, owner)`

All three secondary discriminators are explicitly set (by the user or by
GnuCash's business module) and faithfully round-tripped by the exporter, so
two transactions sharing date + accounts but differing on any of these are
genuinely distinct:

- **doc_link** — explicitly authored link to a receipt or an external file
  (e.g. two grocery trips on the same day with separate receipts).
- **tx_num** — `Transaction.GetNum()`, free-text. Users may store check
  numbers, statement references, payee tags, workflow codes — GnuCash itself
  doesn't prescribe semantics. Same-day same-account transactions with
  different `tx_num` values are distinct regardless of how the user uses it.
- **owner** — `vendor:V001` / `customer:C001`, set by GnuCash's business
  module on invoice/bill posting transactions and payments created via
  `gncOwnerApplyPayment`. Read here via `gncOwnerGetOwnerFromTxn` with a
  custom-KVP slot fallback for plaintext-roundtripped transactions (which
  carry owner in KVP because `gncOwnerCopyOnTxn` is a no-op from Python in
  GnuCash 5.x — see `infrastructure/gnucash/kvp.py:38-46`).

### Strict equality, with documented empty-equivalence

Strict equality (not wildcard) is correct because:

  a) Export always round-trips these fields: `export_transactions.py`
     faithfully writes `doc_link`, the header Num slot, and the `owner:` line
     to plaintext, so a re-import has the same values as GnuCash.
  b) QFX/TSV imports have none of these set (all None), and the matching
     GnuCash transactions also have none set (None), so None == None →
     correctly identified as duplicates.

Empty-equivalent values are normalised to `None` in the signature:
`Transaction.GetNum()` returns `""` for unset, while the plaintext form
distinguishes (or doesn't, depending on the writer); without normalisation,
a clean re-import would mismatch its own pre-import data and create
duplicates.

Do NOT introduce None-as-wildcard. If a user manually attaches a receipt to
a previously-imported transaction inside the GnuCash UI and then tries to
re-import the original plaintext file (which has no doc_link), the mismatch
is intentional: the plaintext file is stale and should be re-exported
before re-importing.

GnuCash 3.x–5.x API compatibility (GetDocLink / GetAssociation) is covered by
scripts/test-all-versions.sh.

This service operates on GnuCash Transaction objects directly, no duplicate
domain models.
"""

import ctypes
from typing import List, Optional, Set, Tuple

from infrastructure.gnucash.engine import load_gnc_engine
from infrastructure.gnucash.kvp import get_custom_metadata

Signature = Tuple[str, Tuple[str, ...], Optional[str], Optional[str], Optional[str]]


def _normalise(s: Optional[str]) -> Optional[str]:
    """Collapse `""` to `None` so plaintext / GnuCash unset states compare equal."""
    return s if s else None


def _read_owner_from_transaction(transaction) -> Optional[str]:
    """
    Return the owner reference (e.g. `"vendor:V001"` / `"customer:C001"`) for a
    GnuCash Transaction, or `None` if no owner is set.

    Tries `gncOwnerGetOwnerFromTxn` first (set by the business module on
    posting/payment transactions). Falls back to the custom-KVP `owner` slot,
    which is where plaintext-roundtripped transactions store the value (the C
    setter is a no-op from Python on GnuCash 5.x).
    """
    try:
        lib = load_gnc_engine()
        lib.gncOwnerGetOwnerFromTxn.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        lib.gncOwnerGetOwnerFromTxn.restype = ctypes.c_int
        lib.gncOwnerGetID.argtypes = [ctypes.c_void_p]
        lib.gncOwnerGetID.restype = ctypes.c_char_p
        lib.gncOwnerGetType.argtypes = [ctypes.c_void_p]
        lib.gncOwnerGetType.restype = ctypes.c_int

        tx_ptr = int(transaction.instance)
        owner_buf = ctypes.create_string_buffer(256)
        owner_p = ctypes.cast(owner_buf, ctypes.c_void_p).value
        if lib.gncOwnerGetOwnerFromTxn(tx_ptr, owner_p) == 1:
            otype = lib.gncOwnerGetType(owner_p)
            oid_raw = lib.gncOwnerGetID(owner_p)
            oid = oid_raw.decode('utf-8', errors='replace') if oid_raw else ''
            kind = {2: 'customer', 4: 'vendor'}.get(otype)
            if kind and oid:
                return f'{kind}:{oid}'
    except (AttributeError, OSError):
        pass

    custom = get_custom_metadata(transaction) or {}
    return _normalise(custom.get('owner'))


class TransactionMatcher:
    """
    Match transactions to detect duplicates and conflicts.

    A transaction is considered:
    - DUPLICATE: Same signature (date + accounts + doc_link + tx_num + owner), amounts match
    - CONFLICT: Same signature, amounts differ
    - NEW: No matching signature found
    """

    def __init__(self):
        """Initialize transaction matcher."""
        self._account_name_cache = {}
        pass

    def find_duplicates(
        self,
        existing_transactions: List,  # List[gnucash.Transaction]
        incoming_transactions: List,  # List[gnucash.Transaction]
    ) -> Tuple[List, List, List]:
        """
        Find duplicates, conflicts, and new transactions.

        Args:
            existing_transactions: Transactions already in GnuCash file
            incoming_transactions: New transactions to check

        Returns:
            Tuple of (new_transactions, duplicates, conflicts)
            - new_transactions: Transactions not in existing (safe to add)
            - duplicates: Transactions already exist (skip)
            - conflicts: Same signature but different amounts (needs resolution)
        """
        new = []
        duplicates = []
        conflicts = []

        existing_by_signature = {}
        for tx in existing_transactions:
            sig = self.get_signature(tx)
            existing_by_signature.setdefault(sig, []).append(tx)

        for incoming_tx in incoming_transactions:
            incoming_sig = self.get_signature(incoming_tx)

            if incoming_sig not in existing_by_signature:
                new.append(incoming_tx)
                continue

            matching_txs = existing_by_signature[incoming_sig]
            is_duplicate = False
            for existing_tx in matching_txs:
                if self._amounts_match(incoming_tx, existing_tx):
                    is_duplicate = True
                    duplicates.append(incoming_tx)
                    break

            if not is_duplicate:
                conflicts.append(incoming_tx)

        return new, duplicates, conflicts

    def get_signature(self, transaction) -> Signature:
        """
        Extract transaction signature: `(date, sorted_account_names, doc_link, tx_num, owner)`.

        Empty-equivalent values (`""`) are normalised to `None` so signatures
        from re-imported plaintext compare equal to those from the originating
        GnuCash book.

        Args:
            transaction: GnuCash Transaction object

        Returns:
            5-tuple `(date_string, tuple_of_sorted_account_names, doc_link, tx_num, owner)`
        """
        if hasattr(transaction, '_cached_signature'):
            return transaction._cached_signature

        date_str = transaction.GetDate().strftime("%Y-%m-%d")

        splits = transaction.GetSplitList()
        account_names = [self._get_account_full_name(s.GetAccount()) for s in splits]

        # GetAssociation was renamed to GetDocLink in GnuCash 4.x
        try:
            doc_link = transaction.GetDocLink()
        except AttributeError:
            doc_link = transaction.GetAssociation()

        tx_num = transaction.GetNum()
        owner = _read_owner_from_transaction(transaction)

        sig = (
            date_str,
            tuple(sorted(account_names)),
            _normalise(doc_link),
            _normalise(tx_num),
            _normalise(owner),
        )

        transaction._cached_signature = sig
        return sig

    def get_signature_for_plaintext(
        self,
        date_str: str,
        account_names: List[str],
        doc_link: Optional[str] = None,
        tx_num: Optional[str] = None,
        owner: Optional[str] = None,
    ) -> Signature:
        """
        Create signature from plaintext transaction data (before creating
        GnuCash object). Useful for checking duplicates before importing.

        Args:
            date_str: Date in YYYY-MM-DD format
            account_names: List of account names from splits
            doc_link: doc_link value from plaintext metadata, or None
            tx_num: tx_num value from the transaction header Num slot, or None
            owner: owner value from `owner:` metadata (e.g. `"vendor:V001"`), or None

        Returns:
            5-tuple `(date_string, tuple_of_sorted_account_names, doc_link, tx_num, owner)`
        """
        return (
            date_str,
            tuple(sorted(account_names)),
            _normalise(doc_link),
            _normalise(tx_num),
            _normalise(owner),
        )

    def find_by_guid(
        self,
        transactions: List,  # List[gnucash.Transaction]
        guid: str
    ) -> Optional[object]:  # Optional[gnucash.Transaction]
        """
        Find transaction by GnuCash GUID.

        Args:
            transactions: List of GnuCash Transaction objects
            guid: GnuCash GUID string (32-character hex)

        Returns:
            Transaction object if found, None otherwise
        """
        for tx in transactions:
            if tx.GetGUID().to_string() == guid:
                return tx
        return None

    def _get_account_full_name(self, account) -> str:
        """Get full hierarchical name of account (e.g. `"Assets:Bank:Checking"`)."""
        if account in self._account_name_cache:
            return self._account_name_cache[account]

        names = []
        current = account
        while current is not None:
            account_name = current.GetName()
            if account_name and account_name != "Root Account":
                names.insert(0, account_name)
            current = current.get_parent()
        full_name = ":".join(names)

        self._account_name_cache[account] = full_name
        return full_name

    def _amounts_match(self, tx1, tx2) -> bool:
        """
        Check if two transactions have matching split amounts.

        Two transactions are duplicates if they have the same signature AND
        the same amounts for each split.
        """
        splits1 = tx1.GetSplitList()
        splits2 = tx2.GetSplitList()

        if len(splits1) != len(splits2):
            return False

        amounts1 = {}
        for split in splits1:
            account_name = self._get_account_full_name(split.GetAccount())
            amounts1[account_name] = split.GetValue()

        for split in splits2:
            account_name = self._get_account_full_name(split.GetAccount())
            amount = split.GetValue()
            if account_name not in amounts1:
                return False
            # GncNumeric.equal — `!=` is broken on GnuCash 3.8/4.4.
            if not amounts1[account_name].equal(amount):
                return False

        return True

    def has_duplicate_signature(
        self,
        transactions: List,  # List[gnucash.Transaction]
        date_str: str,
        account_names: List[str],
        doc_link: Optional[str] = None,
        tx_num: Optional[str] = None,
        owner: Optional[str] = None,
    ) -> bool:
        """
        Check if any transaction in the list has the given signature.

        Convenience method for quick duplicate checks without creating GnuCash
        objects.
        """
        target_sig = self.get_signature_for_plaintext(
            date_str, account_names, doc_link, tx_num, owner
        )
        return any(self.get_signature(tx) == target_sig for tx in transactions)

    def get_duplicate_count(
        self,
        transactions: List  # List[gnucash.Transaction]
    ) -> int:
        """Count duplicate transactions in a list."""
        seen_signatures: Set[Signature] = set()
        duplicate_count = 0
        for tx in transactions:
            sig = self.get_signature(tx)
            if sig in seen_signatures:
                duplicate_count += 1
            else:
                seen_signatures.add(sig)
        return duplicate_count
