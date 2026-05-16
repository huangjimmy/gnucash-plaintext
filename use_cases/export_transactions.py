"""
Use case for exporting GnuCash transactions to plaintext format.

Exports complete GnuCash data including commodities, accounts, and transactions
with all metadata required for round-trip import.
"""

import datetime
import os
from fractions import Fraction
from typing import Optional, Sequence

from gnucash import Transaction
from gnucash.gnucash_core_c import (
    GncGUID,
    string_to_guid,
    xaccAccountGetTypeStr,
    xaccTransLookup,
)

from infrastructure.gnucash.kvp import get_custom_metadata
from infrastructure.gnucash.utils import (
    encode_value_as_string,
    get_account_full_name,
    get_commodity_ticker,
    get_parent_accounts_and_self,
    number_in_string_format_is_1,
    to_string_with_decimal_point_placed,
)
from repositories.gnucash_repository import GnuCashRepository


def _format_fraction_as_decimal(f: Fraction, decimal_places: int) -> str:
    """
    Format a Fraction as a fixed-point decimal string.

    GnuCash amounts always use power-of-10 denominators (100 for CAD, 1 for
    JPY, etc.), so multiplying by 10**decimal_places always yields an exact
    integer — no rounding is needed.

    Args:
        f: Fraction value to format
        decimal_places: Number of digits after the decimal point (0 for JPY, 2
            for CAD/USD, etc.)

    Returns:
        Formatted string, e.g. "1234.56", "-0.50", "12345"
    """
    if decimal_places == 0:
        return str(int(f))
    scale = 10 ** decimal_places
    scaled_int = int(f * scale)
    sign = '-' if scaled_int < 0 else ''
    abs_str = str(abs(scaled_int))
    if len(abs_str) > decimal_places:
        return sign + abs_str[:-decimal_places] + '.' + abs_str[-decimal_places:]
    else:
        return sign + '0.' + '0' * (decimal_places - len(abs_str)) + abs_str


class ExportResult:
    """Container for export data"""
    def __init__(self):
        self.commodities = []  # List of (commodity, first_transaction)
        self.accounts = []     # List of (account, first_transaction)
        self.transactions = [] # List of transactions
        self.commodity_seen = set()
        self.account_seen = set()
        # Running balance data: tx_guid -> {account_guid -> Fraction}
        # Populated by execute(with_balance=True); empty dict means no balances.
        self.account_balances_after_tx: dict = {}


class ExportTransactionsUseCase:
    """Use case for exporting transactions to plaintext with full metadata"""

    def __init__(self, repository: GnuCashRepository):
        """
        Initialize use case.

        Args:
            repository: GnuCash repository instance
        """
        self.repository = repository

    def execute(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        account_filter: Optional[str] = None,
        all_accounts: bool = False,
        with_balance: bool = False,
    ) -> ExportResult:
        """
        Export transactions with ALL commodities and accounts.

        IMPORTANT: When filtering transactions, we still export ALL commodities
        and ALL accounts. This is required for successful import - commodities
        and accounts are declarations that must exist before transactions can
        reference them.

        Args:
            start_date: Optional start date for filtering TRANSACTIONS only
            end_date: Optional end date for filtering TRANSACTIONS only
            account_filter: Optional account path for filtering TRANSACTIONS only
            all_accounts: If True, export ALL accounts regardless of transactions
            with_balance: If True, compute running per-account balances so that
                format_as_plaintext() can emit a ``balance:`` line on every
                split.  Balances are calculated over ALL transactions (not just
                the filtered subset) so the values are always correct even when
                a date or account filter is in effect.

        Returns:
            ExportResult with:
            - ALL commodities (not filtered, or all from accounts if all_accounts=True)
            - ALL accounts (not filtered, or all from repository if all_accounts=True)
            - Filtered transactions (by date/account if specified)
            - account_balances_after_tx populated when with_balance=True
        """
        # Get ALL transactions first (we'll filter them later)
        all_transactions = self.repository.get_all_transactions()

        # Sort by date
        all_transactions.sort(key=lambda tx: tx.GetDate())

        # Filter transactions by date range if specified
        if start_date and end_date:
            filtered_transactions = []
            for tx in all_transactions:
                tx_date = tx.GetDate().strftime("%Y-%m-%d")
                if start_date <= tx_date <= end_date:
                    filtered_transactions.append(tx)
            transactions = filtered_transactions
        else:
            transactions = all_transactions

        # Filter transactions by account if specified
        if account_filter:
            filtered = []
            for tx in transactions:
                for split in tx.GetSplitList():
                    account = split.GetAccount()
                    account_name = get_account_full_name(account)
                    if account_name.startswith(account_filter):
                        filtered.append(tx)
                        break
            transactions = filtered

        result = ExportResult()

        if all_accounts:
            # Collect ALL accounts and their commodities directly from repository
            for account in self.repository.get_all_accounts():
                commodity = account.GetCommodity()
                if commodity is None:
                    continue
                ticker = get_commodity_ticker(commodity)
                if ticker not in result.commodity_seen:
                    result.commodity_seen.add(ticker)
                    result.commodities.append((commodity, None))
                account_guid = account.GetGUID().to_string()
                if account_guid not in result.account_seen:
                    result.account_seen.add(account_guid)
                    result.accounts.append((account, None))
        else:
            # Collect ALL commodities and ALL accounts (not just from filtered transactions)
            # This is critical - without all declarations, import will fail
            for transaction in all_transactions:
                self._collect_transaction_data(transaction, result)

        # Only include the filtered transactions in the result
        result.transactions = transactions

        # Pre-compute running balances across ALL transactions when requested so
        # that filtered exports still show correct cumulative account balances.
        if with_balance:
            result.account_balances_after_tx = self._compute_running_balances(
                all_transactions
            )

        return result

    def _compute_running_balances(self, all_transactions_sorted: list) -> dict:
        """
        Compute the per-account running balance after each transaction.

        Iterates every transaction in chronological order (caller must pre-sort)
        and accumulates split amounts using exact Fraction arithmetic.  The
        result is a mapping from tx_guid to a nested dict of
        {account_guid -> Fraction} holding the account balance *after* that
        transaction has been applied.

        Only accounts that appear in a given transaction are stored for that
        transaction; the caller looks up the balance for (tx_guid, account_guid)
        at format time.

        Args:
            all_transactions_sorted: All transactions, already sorted by date.

        Returns:
            dict mapping tx_guid (str) -> dict[account_guid (str) -> Fraction]
        """
        running: dict = {}   # account_guid -> Fraction (cumulative)
        result: dict = {}    # tx_guid -> {account_guid -> Fraction}

        for tx in all_transactions_sorted:
            tx_guid = tx.GetGUID().to_string()
            tx_accounts: set = set()

            for split in tx.GetSplitList():
                account = split.GetAccount()
                account_guid = account.GetGUID().to_string()
                amount = split.GetAmount()
                delta = Fraction(int(amount.num()), int(amount.denom()))
                running[account_guid] = running.get(account_guid, Fraction(0)) + delta
                tx_accounts.add(account_guid)

            result[tx_guid] = {guid: running[guid] for guid in tx_accounts}

        return result

    def _collect_transaction_data(self, transaction, result: ExportResult):
        """
        Collect commodity, account, and transaction data.

        Args:
            transaction: GnuCash Transaction object
            result: ExportResult to populate
        """
        splits = transaction.GetSplitList()

        # Collect commodities and accounts from splits
        for split in splits:
            split_account = split.GetAccount()
            commodity = split_account.GetCommodity()
            ticker = get_commodity_ticker(commodity)

            # Collect commodity if not seen
            if ticker not in result.commodity_seen:
                result.commodity_seen.add(ticker)
                result.commodities.append((commodity, transaction))

            # Collect account hierarchy if not seen
            accounts = get_parent_accounts_and_self(split_account)
            for account in accounts:
                account_guid = account.GetGUID().to_string()
                if account_guid not in result.account_seen:
                    result.account_seen.add(account_guid)
                    result.accounts.append((account, transaction))

        # Add transaction
        result.transactions.append(transaction)

    def format_as_plaintext(self, result: ExportResult) -> str:
        """
        Format export result as plaintext string with full legacy format.

        When result.account_balances_after_tx is non-empty (i.e. execute() was
        called with with_balance=True), each split line will be followed by a
        ``balance:`` metadata line showing the cumulative account balance after
        that transaction, expressed in the account's own commodity.

        Args:
            result: ExportResult with commodities, accounts, and transactions

        Returns:
            Formatted plaintext string with all metadata
        """
        lines = []

        # Output commodities
        for commodity, transaction in result.commodities:
            self._format_commodity(commodity, transaction, lines)

        # Output accounts
        for account, transaction in result.accounts:
            self._format_account(account, transaction, lines)

        # Output transactions
        for transaction in result.transactions:
            tx_guid = transaction.GetGUID().to_string()
            balance_map = result.account_balances_after_tx.get(tx_guid)
            self._format_transaction(transaction, lines, balance_map=balance_map)

        # Join lines and add trailing newline to match legacy format
        return '\n'.join(lines) + '\n' if lines else ''

    def execute_accounts_only(self) -> ExportResult:
        """
        Export all accounts and their commodities without loading any transactions.

        Much faster than execute() for account-structure-only exports since it
        never touches the transaction log.

        The open date for each declaration is determined at format time by
        format_accounts_only(as_of_date=...).  This method only populates the
        account and commodity lists — it carries no date information.

        Returns:
            ExportResult with all accounts and commodities; no transactions.
        """
        result = ExportResult()
        for account in self.repository.get_all_accounts():
            commodity = account.GetCommodity()
            if commodity is None:
                continue
            ticker = get_commodity_ticker(commodity)
            if ticker not in result.commodity_seen:
                result.commodity_seen.add(ticker)
                result.commodities.append((commodity, None))
            account_guid = account.GetGUID().to_string()
            if account_guid not in result.account_seen:
                result.account_seen.add(account_guid)
                result.accounts.append((account, None))
        return result

    def format_accounts_only(self, result: ExportResult, as_of_date: Optional[str] = None) -> str:
        """Format commodities and accounts using as_of_date (or file mtime) for open dates."""
        lines = []
        for commodity, transaction in result.commodities:
            self._format_commodity(commodity, transaction, lines, date_override=as_of_date)
        for account, transaction in result.accounts:
            self._format_account(account, transaction, lines, date_override=as_of_date)
        return '\n'.join(lines) + '\n' if lines else ''

    def format_accounts_section(self, result: ExportResult) -> str:
        """Format only commodities and accounts (no transactions)."""
        lines = []
        for commodity, transaction in result.commodities:
            self._format_commodity(commodity, transaction, lines)
        for account, transaction in result.accounts:
            self._format_account(account, transaction, lines)
        return '\n'.join(lines) + '\n' if lines else ''

    def format_transactions_section(self, result: ExportResult) -> str:
        """Format only transactions (no commodities or accounts)."""
        lines = []
        for transaction in result.transactions:
            tx_guid = transaction.GetGUID().to_string()
            balance_map = result.account_balances_after_tx.get(tx_guid)
            self._format_transaction(transaction, lines, balance_map=balance_map)
        return '\n'.join(lines) + '\n' if lines else ''

    def format_transaction_list(self, transactions: list) -> str:
        """
        Format a list of Transaction objects as plaintext (transaction blocks only).

        Collects all required data from the transactions and returns their
        plaintext representation without commodity or account preamble.
        Useful for outputting newly imported transactions with their GUIDs.
        """
        result = ExportResult()
        for tx in transactions:
            self._collect_transaction_data(tx, result)
        return self.format_transactions_section(result)

    def _file_date_str(self) -> str:
        """Return GnuCash file modification date as YYYY-MM-DD string."""
        mtime = os.path.getmtime(self.repository.file_path)
        return datetime.date.fromtimestamp(mtime).strftime("%Y-%m-%d")

    def _format_commodity(self, commodity, transaction, lines: list, date_override: Optional[str] = None):
        """Format commodity declaration"""
        mnemonic = commodity.get_mnemonic()
        namespace = commodity.get_namespace()
        fraction = commodity.get_fraction()
        fullname = commodity.get_fullname()

        if date_override is not None:
            date_str = date_override
        elif transaction is not None:
            date_str = transaction.GetDate().strftime("%Y-%m-%d")
        else:
            date_str = self._file_date_str()
        ticker = get_commodity_ticker(commodity)

        lines.append(f'{date_str} commodity {ticker}')
        lines.append(f'\tmnemonic: {encode_value_as_string(mnemonic)}')
        lines.append(f'\tfullname: {encode_value_as_string(fullname)}')
        lines.append(f'\tnamespace: {encode_value_as_string(namespace)}')
        lines.append(f'\tfraction: {fraction}')

    def _format_account(self, account, transaction, lines: list, date_override: Optional[str] = None):
        """Format account declaration"""
        commodity = account.GetCommodity()
        if commodity is None:
            return

        mnemonic = commodity.get_mnemonic()
        namespace = commodity.get_namespace()
        fraction = commodity.get_fraction()
        commodity_scu = account.GetCommoditySCU()

        if date_override is not None:
            date_str = date_override
        elif transaction is not None:
            date_str = transaction.GetDate().strftime("%Y-%m-%d")
        else:
            date_str = self._file_date_str()
        account_full_name = get_account_full_name(account)
        account_guid = account.GetGUID()
        account_type = account.GetType()
        account_type_str = xaccAccountGetTypeStr(account_type)
        is_placeholder = account.GetPlaceholder()
        code = account.GetCode()
        description = account.GetDescription()
        color = account.GetColor()
        notes = account.GetNotes()
        tax_related = account.GetTaxRelated()

        lines.append(f'{date_str} open {account_full_name}')
        lines.append(f'\tguid: "{account_guid.to_string()}"')
        lines.append(f'\ttype: "{account_type_str}"')

        for (key, value) in [
            ('placeholder', is_placeholder),
            ('code', code),
            ('description', description),
            ('color', color),
            ('notes', notes),
            ('tax_related', tax_related),
        ]:
            if value is not None:
                lines.append(f'\t{key}: {encode_value_as_string(value)}')

        lines.append(f'\tcommodity.namespace: {encode_value_as_string(namespace)}')
        lines.append(f'\tcommodity.mnemonic: {encode_value_as_string(mnemonic)}')
        if commodity_scu != fraction:
            lines.append(f'\tcommodity_scu: {encode_value_as_string(commodity_scu)}')

        custom_meta = get_custom_metadata(account)
        for k, v in sorted(custom_meta.items()):
            lines.append(f'\t{k}: {encode_value_as_string(v)}')

    def _format_transaction(
        self,
        transaction,
        lines: list,
        balance_map: Optional[dict] = None,
    ):
        """
        Format transaction with all metadata.

        Args:
            transaction: GnuCash Transaction object
            lines: Output lines list to append to
            balance_map: Optional {account_guid -> Fraction} of running balances
                after this transaction.  When provided, each split gets a
                ``balance:`` metadata line.
        """
        tx_guid = transaction.GetGUID()
        tx_splits = transaction.GetSplitList()
        date_str = transaction.GetDate().strftime("%Y-%m-%d")
        tx_num = transaction.GetNum()
        tx_desc = transaction.GetDescription()
        tx_notes = transaction.GetNotes()
        tx_currency = transaction.GetCurrency()
        tx_currency_namespace = tx_currency.get_namespace()
        tx_currency_symbol = tx_currency.get_mnemonic()

        # GetAssociation was renamed to GetDocLink in GnuCash 4.x
        try:
            tx_doc_link = transaction.GetDocLink()
        except AttributeError:
            # Fall back to older GnuCash API (< 4.0)
            tx_doc_link = transaction.GetAssociation()

        # Transaction header
        line = f'{date_str} *'
        if tx_num and tx_num.strip() != "":
            line += f' {encode_value_as_string(tx_num)}'
        if tx_desc and tx_desc.strip() != "":
            line += f' {encode_value_as_string(tx_desc)}'
        lines.append(line)

        # Transaction metadata
        lines.append(f'\tguid: {encode_value_as_string(tx_guid.to_string())}')
        if tx_currency_namespace != 'CURRENCY':
            lines.append(f'\tcurrency.namespace: {encode_value_as_string(tx_currency_namespace)}')

        # Check if multi-currency transaction
        split_currencies = [
            (split.GetAccount().GetCommodity().get_namespace(),
             split.GetAccount().GetCommodity().get_mnemonic())
            for split in tx_splits
        ]
        split_currencies = list(set(split_currencies))
        if len(split_currencies) > 1:
            lines.append(f'\tcurrency.mnemonic: {encode_value_as_string(tx_currency_symbol)}')

        if tx_doc_link is not None:
            lines.append(f'\tdoc_link: {encode_value_as_string(tx_doc_link)}')
        if tx_notes and tx_notes.strip() != "":
            lines.append(f'\tnotes: {encode_value_as_string(tx_notes)}')

        # txn_type + owner: GnuCash internal classifier + customer/vendor
        # KVP backref set by the business-object machinery (txn_type='I'
        # on invoice/bill posting transactions and 'P' on payments
        # created by `gncOwnerApplyPayment`; the gncOwner KVP slot names
        # the customer/vendor that the payment paid). Default txn_type
        # is 'N' (normal); only emit non-N values so old plaintext files
        # round-trip unchanged. Both fields are needed so that orphan
        # bank-side payment transactions (whose AR/AP lot was detached
        # by unpost) can still be detected by `find-orphan-payments`
        # after a plaintext roundtrip — without these fields the
        # restored tx defaults to txn_type='N' and no owner ref, so
        # criteria 1 and 2 of the classifier fail.
        import ctypes as _ctypes

        from infrastructure.gnucash.engine import load_gnc_engine as _load
        _lib = _load()
        _tx_ptr = int(transaction.instance)
        try:
            _lib.xaccTransGetTxnType.restype = _ctypes.c_char
            _lib.xaccTransGetTxnType.argtypes = [_ctypes.c_void_p]
            _t = _lib.xaccTransGetTxnType(_tx_ptr)
            if isinstance(_t, bytes):
                _t = _t.decode('ascii', errors='replace')
            if _t and _t != 'N':
                lines.append(f'\ttxn_type: {_t}')
        except AttributeError:
            pass

        try:
            _lib.gncOwnerGetOwnerFromTxn.argtypes = [_ctypes.c_void_p, _ctypes.c_void_p]
            _lib.gncOwnerGetOwnerFromTxn.restype = _ctypes.c_int
            _lib.gncOwnerGetID.argtypes = [_ctypes.c_void_p]
            _lib.gncOwnerGetID.restype = _ctypes.c_char_p
            _lib.gncOwnerGetType.argtypes = [_ctypes.c_void_p]
            _lib.gncOwnerGetType.restype = _ctypes.c_int
            _owner_buf = _ctypes.create_string_buffer(256)
            _owner_p = _ctypes.cast(_owner_buf, _ctypes.c_void_p).value
            if _lib.gncOwnerGetOwnerFromTxn(_tx_ptr, _owner_p) == 1:
                _otype = _lib.gncOwnerGetType(_owner_p)
                _oid_raw = _lib.gncOwnerGetID(_owner_p)
                _oid = (_oid_raw.decode('utf-8', errors='replace')
                        if _oid_raw else '')
                _kind = {2: 'customer', 4: 'vendor'}.get(_otype)
                if _kind and _oid:
                    lines.append(f'\towner: {_kind}:{_oid}')
        except AttributeError:
            pass

        # Emit custom KVP metadata. Skip Q-014's `txn_type` and `owner`
        # slots — they're already emitted above as dedicated lines based
        # on the live C state, and re-emitting from the KVP slot would
        # produce duplicate lines on the second pass of an export → import
        # → export roundtrip (the importer stores `txn_type:` and `owner:`
        # from the plaintext as custom KVPs since the matching C setters
        # are no-ops on GnuCash 4.8+).
        _q014_reserved_tx = {'txn_type', 'owner'}
        custom_meta = get_custom_metadata(transaction)
        for key, value in sorted(custom_meta.items()):
            if key in _q014_reserved_tx:
                continue
            lines.append(f'\t{key}: {encode_value_as_string(value)}')

        # Splits
        for split in tx_splits:
            balance: Optional[Fraction] = None
            if balance_map is not None:
                account_guid = split.GetAccount().GetGUID().to_string()
                balance = balance_map.get(account_guid)
            self._format_split(
                split, tx_currency_namespace, tx_currency_symbol, lines,
                balance=balance,
            )

    def _format_split(
        self,
        split,
        tx_currency_namespace,
        tx_currency_symbol,
        lines: list,
        balance: Optional[Fraction] = None,
    ):
        """
        Format split with all metadata.

        Args:
            split: GnuCash Split object
            tx_currency_namespace: Transaction currency namespace
            tx_currency_symbol: Transaction currency mnemonic
            lines: Output lines list to append to
            balance: Optional running balance (Fraction) of this account after
                the parent transaction.  When provided, a ``balance:`` metadata
                line is emitted as the last item of the split's metadata block.
        """
        split_account = split.GetAccount()
        split_currency = split_account.GetCommodity()
        split_currency_namespace = split_currency.get_namespace()
        split_currency_symbol = split_currency.get_mnemonic()

        split_account_full_name = get_account_full_name(split_account)
        action = split.GetAction()
        memo = split.GetMemo()

        formatted_amount = to_string_with_decimal_point_placed(split.GetAmount())
        share_price = to_string_with_decimal_point_placed(split.GetSharePrice())
        split_value = to_string_with_decimal_point_placed(split.GetValue())

        # Split line
        currency_ticker = get_commodity_ticker(split_currency)
        if ' ' in currency_ticker or '\t' in currency_ticker:
            currency_ticker = encode_value_as_string(currency_ticker)
        lines.append(f'\t{split_account_full_name} {formatted_amount} {currency_ticker}')

        # Split metadata
        split_currency_not_match_tx = (
            split_currency_symbol != tx_currency_symbol or
            split_currency_namespace != tx_currency_namespace
        )

        if split_currency_not_match_tx:
            lines.append(f'\t\taccount.commodity.mnemonic: {encode_value_as_string(split_currency_symbol)}')
            if split_currency_namespace != 'CURRENCY':
                lines.append(f'\t\taccount.commodity.namespace: {encode_value_as_string(split_currency_namespace)}')

        if not number_in_string_format_is_1(share_price) or split_currency_not_match_tx:
            lines.append(f'\t\tshare_price: {encode_value_as_string(share_price)}')

        if split_value != formatted_amount:
            lines.append(f'\t\tvalue: {encode_value_as_string(split_value)}')

        if action is not None and action != "":
            lines.append(f'\t\taction: {encode_value_as_string(action)}')

        if memo and memo != "":
            lines.append(f'\t\tmemo:{encode_value_as_string(memo)}')

        # Q-014: orphan-lot reconstruction marker. When this split is on
        # the AR/AP side of an unposted/orphan payment lot (lot exists,
        # is owner-attached, but has no invoice), emit the owner so the
        # importer can re-create the orphan lot — that's what makes the
        # GnuCash 5.x txn-type heuristic return 'P' on the restored book
        # (the heuristic is "AR/AP split's lot has an invoice OR an
        # owner"; the second arm covers our case).
        import ctypes as _ctypes

        from infrastructure.gnucash.engine import load_gnc_engine as _load
        _lib = _load()
        try:
            _lib.xaccSplitGetLot.argtypes = [_ctypes.c_void_p]
            _lib.xaccSplitGetLot.restype = _ctypes.c_void_p
            _lib.gncInvoiceGetInvoiceFromLot.argtypes = [_ctypes.c_void_p]
            _lib.gncInvoiceGetInvoiceFromLot.restype = _ctypes.c_void_p
            _lib.gncOwnerGetOwnerFromLot.argtypes = [_ctypes.c_void_p, _ctypes.c_void_p]
            _lib.gncOwnerGetOwnerFromLot.restype = _ctypes.c_int
            _lib.gncOwnerGetID.argtypes = [_ctypes.c_void_p]
            _lib.gncOwnerGetID.restype = _ctypes.c_char_p
            _lib.gncOwnerGetType.argtypes = [_ctypes.c_void_p]
            _lib.gncOwnerGetType.restype = _ctypes.c_int
            _lot_ptr = _lib.xaccSplitGetLot(int(split.instance))
            if _lot_ptr:
                _inv = _lib.gncInvoiceGetInvoiceFromLot(_lot_ptr)
                if not _inv:                       # orphan lot — emit marker
                    _owner_buf = _ctypes.create_string_buffer(256)
                    _owner_p = _ctypes.cast(_owner_buf, _ctypes.c_void_p).value
                    if _lib.gncOwnerGetOwnerFromLot(_lot_ptr, _owner_p) == 1:
                        _otype = _lib.gncOwnerGetType(_owner_p)
                        _oid_raw = _lib.gncOwnerGetID(_owner_p)
                        _oid = (_oid_raw.decode('utf-8', errors='replace')
                                if _oid_raw else '')
                        _kind = {2: 'customer', 4: 'vendor'}.get(_otype)
                        if _kind and _oid:
                            lines.append(f'\t\tlot_owner: {_kind}:{_oid}')
        except AttributeError:
            pass

        # Emit custom split KVP metadata. Skip Q-014's `lot_owner` slot
        # for the same reason as the tx-level reserved keys above:
        # the importer stores `lot_owner:` as a custom KVP AND uses it
        # to reconstruct an orphan lot; on re-export we already emit it
        # from the live lot state via the block above.
        _q014_reserved_split = {'lot_owner'}
        custom_split_meta = get_custom_metadata(split)
        for key, value in sorted(custom_split_meta.items()):
            if key in _q014_reserved_split:
                continue
            lines.append(f'\t\t{key}: {encode_value_as_string(value)}')

        # Running balance — emitted last so it reads as a post-transaction annotation
        if balance is not None:
            fraction = split_currency.get_fraction()
            decimal_places = len(str(fraction)) - 1
            balance_str = _format_fraction_as_decimal(balance, decimal_places)
            balance_ticker = get_commodity_ticker(split_currency)
            lines.append(f'\t\tbalance: "{balance_str} {balance_ticker}"')

    def execute_by_guids(self, guids: Sequence[str]) -> ExportResult:
        """
        Export one or more transactions identified by their GUIDs in one pass.

        Looks up each GUID with xaccTransLookup (O(1) per lookup), then feeds
        every transaction into a single ExportResult via _collect_transaction_data.
        Commodities and accounts are deduplicated naturally by the seen-sets in
        ExportResult — no post-hoc merging needed.

        Duplicate GUIDs in the input are silently ignored (each transaction
        appears exactly once in the result).

        Args:
            guids: sequence of 32-character hex GUID strings

        Returns:
            ExportResult containing all matched transactions plus the union of
            their commodity and account declarations

        Raises:
            ValueError: if any GUID is malformed or not found in the book
        """
        result = ExportResult()
        seen_guids = set()
        for guid in guids:
            if guid in seen_guids:
                continue
            seen_guids.add(guid)
            gnc_guid = GncGUID()
            if not string_to_guid(guid, gnc_guid):
                raise ValueError(f"Invalid GUID format: {guid}")
            raw = xaccTransLookup(gnc_guid, self.repository.book.instance)
            if raw is None:
                raise ValueError(f"No transaction found with GUID: {guid}")
            self._collect_transaction_data(Transaction(instance=raw), result)
        return result

    def execute_by_guid(self, guid: str) -> ExportResult:
        """
        Export a single transaction identified by its GUID.

        Convenience wrapper around execute_by_guids for the single-item case.

        Args:
            guid: 32-character hex GUID string of the transaction to export

        Returns:
            ExportResult containing the single transaction plus its
            commodities and accounts

        Raises:
            ValueError: if the GUID string is malformed or no transaction
                        with that GUID exists
        """
        return self.execute_by_guids([guid])

    def export_to_file(
        self,
        output_path: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        account_filter: Optional[str] = None,
        all_accounts: bool = False,
        with_balance: bool = False,
    ) -> int:
        """
        Export transactions to file.

        Args:
            output_path: Path for output file
            start_date: Optional start date
            end_date: Optional end date
            account_filter: Optional account filter
            all_accounts: If True, export all accounts even without transactions
            with_balance: If True, include running account balance per split

        Returns:
            Number of transactions exported
        """
        result = self.execute(
            start_date, end_date, account_filter, all_accounts,
            with_balance=with_balance,
        )
        plaintext = self.format_as_plaintext(result)

        with open(output_path, 'w') as f:
            f.write(plaintext)

        return len(result.transactions)
