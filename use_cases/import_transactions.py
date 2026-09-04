"""
Use case for importing plaintext transactions to GnuCash.

Orchestrates services and repository to parse, validate, and import transactions.
Supports full GnuCash plaintext format with commodity declarations, account declarations,
and transactions.
"""

import logging
from typing import Dict, List

from repositories.gnucash_repository import GnuCashRepository
from services.conflict_resolver import ConflictResolver, ResolutionStrategy
from services.foreign_currency import begin_import_run
from services.gnucash_importer import (
    GnuCashImporter,
    begin_lot_attachments,
    note_what_the_file_states,
    the_guid_a_block_names,
)
from services.ledger_validator import LedgerValidator
from services.plaintext_parser import DirectiveType, PlaintextParser
from services.transaction_matcher import TransactionMatcher


class ImportResult:
    """Result of import operation"""

    def __init__(self):
        self.imported_count = 0
        self.updated_count = 0
        # The transactions `--strategy update` reported under that figure.
        # A `payment:` block correcting one of their memos adds to the same
        # figure, and one transaction changed is one transaction changed.
        self.updated_transaction_guids: set = set()
        # And the ones this run created, which are counted as transactions
        # imported: a memo written onto one of them by a `payment:` block
        # is part of creating it, not a later change to it. `import --new`
        # reported `Transactions: 1` beside `Updated: 1` for a book where
        # one transaction was made and none was touched afterwards.
        self.new_transaction_guids: set = set()
        # Counted, and not only for the summary: what the run changed is what
        # decides whether the book is saved, and a file that declares a
        # commodity and nothing else changed the book without any of the other
        # counters moving. `import --new book.gnucash <commodities>.txt`
        # reported "Nothing to import" and wrote a book without them —
        # measured, and the route the "declare it as a stock or fund instead"
        # refusal sends a reader down.
        # The file could not be read at all, as opposed to some object in it
        # failing. Nothing was attempted, so the caller refuses rather than
        # reporting a summary of a run that never happened.
        self.parse_failed = False
        self.commodities_created = 0
        # A commodity already in the book whose declared fraction differs.
        # Kept apart from a creation because it is not one — and it happens
        # on every run of a book moved between two supported GnuCash versions
        # that disagree about an ISO fraction, so counting it as a creation
        # reported a book gaining a commodity it already had, forever.
        self.commodities_updated = 0
        # Of those, the ones a save can keep. An ISO currency's fraction is
        # not written to the file, so restating it changes the session and
        # nothing else — reported, but not a reason to write the book.
        self.commodities_updated_on_disk = 0
        self.accounts_created = 0
        self.skipped_count = 0
        self.error_count = 0
        self.duplicates = []
        self.conflicts = []
        self.errors = []
        self.new_transactions = []  # Transaction objects created during this import
        # GUID-match skips (default strategy) whose incoming content actually
        # DIFFERS from the existing transaction — i.e. the user edited the tx
        # but the edit was skipped as a "duplicate". Drives a hint at
        # --strategy update. A plain re-import of unchanged txs does not count.
        self.guid_changed_skips = 0

    def get_summary(self) -> str:
        """Get summary string"""
        lines = []
        lines.append(f"Imported: {self.imported_count}")
        lines.append(f"Updated: {self.updated_count}")
        lines.append(f"Commodities created: {self.commodities_created}")
        lines.append(f"Commodities updated: {self.commodities_updated}")
        lines.append(f"Accounts created: {self.accounts_created}")
        lines.append(f"Skipped: {self.skipped_count} (duplicates)")
        lines.append(f"Conflicts: {len(self.conflicts)}")
        lines.append(f"Errors: {self.error_count}")
        return "\n".join(lines)


def _guid_match_content_differs(child, existing_tx) -> bool:
    """True when an incoming transaction directive's content differs from the
    existing transaction it matched by GUID — i.e. the user edited it.

    Compares each split's (account path, exact amount) as a sorted multiset.
    Amounts are compared exactly via `Fraction(num, denom)`, never float, so an
    unchanged re-import never reports a difference and an edited amount always
    does. Used only to decide whether to hint at `--strategy update`; it never
    changes import behaviour."""
    from decimal import Decimal, InvalidOperation
    from fractions import Fraction

    from infrastructure.gnucash.utils import get_account_full_name

    def _incoming():
        out = []
        for s in child.children:
            acct = s.props.get('account')
            if not acct:
                continue
            raw = str(s.props.get('amount', '0')).replace('+', '').strip()
            try:
                val = str(Fraction(Decimal(raw)))
            except (InvalidOperation, ValueError, ZeroDivisionError):
                val = raw
            out.append((acct, val))
        return sorted(out)

    def _existing():
        out = []
        # Every split has an account: a book holding one without is dropped by
        # GnuCash 5.x while loading and segfaults 4.x (CLAUDE.md §12), so a
        # null check here could only ever be skipped.
        for sp in existing_tx.GetSplitList():
            a = sp.GetAccount()
            amt = sp.GetAmount()
            out.append((get_account_full_name(a),
                        str(Fraction(amt.num(), amt.denom()))))
        return sorted(out)

    return _incoming() != _existing()


class ImportTransactionsUseCase:
    """Use case for importing transactions from plaintext"""

    def __init__(self, repository: GnuCashRepository):
        """
        Initialize use case.

        Args:
            repository: GnuCash repository instance
        """
        self.repository = repository
        self.matcher = TransactionMatcher()
        self.resolver = ConflictResolver()
        self.validator = LedgerValidator()

    def execute(
        self,
        plaintext_transactions: List[Dict],
        resolution_strategy: ResolutionStrategy = ResolutionStrategy.SKIP,
        validate: bool = True
    ) -> ImportResult:
        """
        Import transactions from plaintext format.

        Args:
            plaintext_transactions: List of transaction dicts
            resolution_strategy: How to handle conflicts
            validate: Whether to validate transactions before import

        Returns:
            ImportResult with summary
        """
        result = ImportResult()

        # Get existing transactions
        existing_transactions = self.repository.get_all_transactions()

        # Convert plaintext to GnuCash transactions (not yet committed)
        incoming_transactions = []
        for pt_tx in plaintext_transactions:
            try:
                tx = self._create_transaction_from_plaintext(pt_tx)
                incoming_transactions.append(tx)
            except Exception as e:
                result.errors.append({
                    'transaction': pt_tx,
                    'error': str(e)
                })
                result.error_count += 1

        # Find duplicates and conflicts
        new, duplicates, conflicts = self.matcher.find_duplicates(
            existing_transactions,
            incoming_transactions
        )

        # Store for result
        result.duplicates = duplicates
        result.skipped_count = len(duplicates)

        # Validate new transactions
        if validate and new:
            validation_result = self.validator.validate_transactions(new, check_duplicates=False)
            if not validation_result.is_valid():
                result.errors.append({
                    'error': 'Validation failed',
                    'details': validation_result.get_summary()
                })
                # Counted, like every other error path here. The exit code is
                # `error_count > 0` now, so "the run reported an error" and
                # "`error_count` is non-zero" have to mean the same thing —
                # this was the one place in the file where they did not.
                result.error_count += 1
                # Don't import if validation fails
                return result

        # Resolve conflicts
        if conflicts:
            # Need to find corresponding existing transactions for conflicts
            conflict_pairs = []
            for conflict_tx in conflicts:
                conflict_sig = self.matcher.get_signature(conflict_tx)
                # Find existing transaction with same signature
                for existing_tx in existing_transactions:
                    existing_sig = self.matcher.get_signature(existing_tx)
                    if existing_sig == conflict_sig:
                        conflict_pairs.append((existing_tx, conflict_tx))
                        break

            to_import_from_conflicts, unresolved = self.resolver.resolve(
                conflict_pairs,
                resolution_strategy
            )
            new.extend(to_import_from_conflicts)
            # unresolved is a list of ConflictInfo objects
            result.conflicts = unresolved

        # Counted, not committed: each was built against the book by
        # `_create_transaction_from_plaintext`, which is where a failure
        # happens and where it is already caught and counted. Nothing is left
        # to do here that can fail, so there is no failure to report — the
        # `try` that wrapped this counted an exception the body cannot raise.
        result.imported_count += len(new)

        return result

    def _create_transaction_from_plaintext(self, plaintext_tx: Dict):
        """
        Create GnuCash transaction from plaintext format.

        Args:
            plaintext_tx: Transaction dictionary

        Returns:
            GnuCash Transaction object (created but not yet committed)
        """
        from datetime import datetime

        from gnucash import Split

        from infrastructure.gnucash.utils import transaction_under_construction

        # Parse date
        date_str = plaintext_tx['date']
        date = datetime.strptime(date_str, "%Y-%m-%d")
        date_tuple = (date.day, date.month, date.year)

        # Get currency
        currency_code = plaintext_tx.get('currency', 'USD')
        currency = self.repository.get_commodity('CURRENCY', currency_code)

        # Everything from the moment the transaction exists is inside the
        # guard — the description is subscripted, not `.get`, so a dict
        # without one raises before a single split is attached and would
        # otherwise leave an allocated transaction with an open edit.
        with transaction_under_construction(self.repository.book) as tx:
            tx.SetCurrency(currency)
            tx.SetDate(*date_tuple)
            tx.SetDescription(plaintext_tx['description'])

            for split_data in plaintext_tx['splits']:
                account_path = split_data['account']
                account = self.repository.get_account(account_path)

                if account is None:
                    raise ValueError(f"Account not found: {account_path}")

                # Convert amount to GncNumeric. A number reaches the currency's
                # smallest unit through GnuCash's own rounding: multiplying a
                # float by 100 and truncating turns 0.07 into 6.999... and books
                # 0.06, and truncation loses the half-cent rounding would keep.
                amount = split_data['amount']
                if isinstance(amount, str):
                    from infrastructure.gnucash.utils import string_to_gnc_numeric
                    gnc_amount = string_to_gnc_numeric(amount, currency)
                else:
                    from fractions import Fraction

                    from infrastructure.gnucash.utils import to_money
                    gnc_amount = to_money(Fraction(str(amount)),
                                          currency.get_fraction())

                split = Split(self.repository.book)
                split.SetParent(tx)
                split.SetAccount(account)
                split.SetValue(gnc_amount)

        return tx

    def import_from_file(
        self,
        input_path: str,
        resolution_strategy: ResolutionStrategy = ResolutionStrategy.SKIP,
        on_accounts_ready=None,
        atomic: bool = False,
    ) -> ImportResult:
        """
        Import from full GnuCash plaintext format file.

        This properly handles the complete format with:
        - Commodity declarations (commodity CAD, etc.)
        - Account declarations (open Assets:Bank:Checking, etc.)
        - Transactions with full metadata

        Commodities and accounts are created first, then transactions are imported
        with duplicate detection and conflict resolution.

        `on_accounts_ready(parser, result)` is called once, after the accounts
        exist and before any transaction is read. It is where owners and tax
        tables go: a standalone transaction may name either, so they have to be
        in the book before the transaction pass, and they need the accounts
        that come before them.

        A hook rather than a second pass by the caller. `--include-business-
        objects` used to parse the file itself and create the commodities and
        the accounts over again, so every declaration in the file was carried
        out twice and the two copies had to be made to agree afterwards: the
        counts (the second pass finds everything already there and reports
        creating nothing), what `has_changes` reads from them, which failures
        were reported and by which pass, and what a commodity's fraction was
        before the file restated it. Each of those was a defect found
        separately, and the last of them — a currency widened past the amount
        rule — was a book that imported cleanly and could never be exported.
        One parse, one pass, one answer.

        Args:
            input_path: Path to plaintext file in GnuCash format
            resolution_strategy: How to handle conflicts
            on_accounts_ready: Called with (parser, result) once the accounts
                exist, before transactions are read

        Returns:
            ImportResult with summary
        """
        result = ImportResult()

        # Q-035: a cost basis whose cost basis balance this file states is
        # stating it net of the file's own sales; forget what the last file
        # stated before reading this one.
        begin_import_run(atomic)
        # And which lots the last file attached splits to, which is what tells
        # this one when a lot's own split list can be trusted.
        begin_lot_attachments()

        # Parse the plaintext file using the new parser
        parser = PlaintextParser()
        parser.parse_file(input_path)

        # What only the whole file can say about a payment: the memo its
        # transaction section gives each split, and how many invoices
        # settle from each transaction. Read here because the book cannot
        # answer either while the run is still building it.
        note_what_the_file_states(parser.root_directive.children)

        if parser.errors:
            # Normalise parser (syntax) errors into the same {'error': ...} shape
            # the transaction/account failure paths use, so result.errors is
            # always a list of dicts and every consumer can treat it uniformly.
            result.errors.extend({'error': msg} for msg in parser.errors)
            result.error_count = len(parser.errors)
            # And said apart from the rest, because it is a different kind of
            # failure: the file could not be read at all, so nothing in it was
            # attempted. The caller exits non-zero on this — `import --new
            # book.gnucash broken.txt && next-step` proceeded on an empty book
            # otherwise, while the same command with
            # `--include-business-objects` failed and removed the file. One
            # file, two answers, and a script is the caller that cannot see
            # the difference.
            result.parse_failed = True
            return result

        # Process directives in order: commodities -> accounts -> transactions
        book = self.repository.book
        importer = GnuCashImporter()

        # Step 1: Create all commodities
        for child in parser.root_directive.children:
            if child.type == DirectiveType.CREATE_COMMODITY:
                try:
                    outcome = importer.create_commodity(child, book)
                    if outcome == 'created':
                        result.commodities_created += 1
                    elif outcome in ('updated', 'updated-in-session'):
                        # Both are reported. Only one is a reason to save:
                        # an ISO currency's fraction is not written to the
                        # file, so saving cannot keep it and the next run
                        # finds the same difference. See `create_commodity`.
                        result.commodities_updated += 1
                        if outcome == 'updated':
                            result.commodities_updated_on_disk += 1
                except Exception as e:
                    # Reported like an account's or a transaction's, not logged
                    # and dropped. "Continue — commodity might already exist"
                    # described a case `create_commodity` handles itself: an
                    # existing commodity is looked up and its fraction updated,
                    # no exception raised. What actually reaches here is a
                    # commodity that could not be made, and swallowing it left
                    # the summary saying `Errors: 0` while every account and
                    # transaction in that commodity failed for a reason stated
                    # nowhere — or, worse, landed in a book that would not
                    # reload.
                    # `props['symbol']`, which is where the parser puts a
                    # commodity directive's name. There is no `'commodity'`
                    # key, and the fallback is reached precisely when
                    # `metadata['mnemonic']` is missing — the same case
                    # `create_commodity` raises `KeyError` on — so the message
                    # would have read "Failed to create commodity ?".
                    mnemonic = (child.metadata.get('mnemonic')
                                or child.props.get('symbol', '?'))
                    error_msg = f"Failed to create commodity {mnemonic}: {e}"
                    logging.warning(error_msg)
                    result.errors.append({'error': error_msg})
                    result.error_count += 1

        # Step 2: Create all accounts
        for child in parser.root_directive.children:
            if child.type == DirectiveType.OPEN_ACCOUNT:
                try:
                    if importer.create_account(child, book):
                        result.accounts_created += 1
                except Exception as e:
                    account_name = child.props.get('account', '?')
                    error_msg = f"Failed to create account {account_name}: {e}"
                    logging.warning(error_msg)
                    result.errors.append({'error': error_msg})
                    result.error_count += 1

        # Between the accounts and the transactions: owners and tax tables, so
        # a transaction naming one finds it. Invoices and bills are not here —
        # their `txn_guid:` resolves against a bank transaction this pass is
        # about to create — and the caller applies those after this returns.
        if on_accounts_ready is not None:
            on_accounts_ready(parser, result)

        # Step 3: Import transactions with duplicate detection
        existing_transactions = self.repository.get_all_transactions()
        existing_guid_map = {tx.GetGUID().to_string(): tx for tx in existing_transactions}

        # UPDATE strategy: validate ALL transactions before applying ANY update.
        # This ensures atomicity: either the whole file is valid and all updates
        # are applied, or we fail before touching the book.
        if resolution_strategy == ResolutionStrategy.UPDATE:
            tx_directives = [
                child for child in parser.root_directive.children
                if child.type == DirectiveType.TRANSACTION
            ]
            for child in tx_directives:
                if 'guid' not in child.metadata:
                    date_str = child.props.get('date', '?')
                    desc = child.props.get('description', '?')
                    raise ValueError(
                        f"--strategy update requires a guid: field on every transaction "
                        f"(transaction on {date_str} \"{desc}\" has none)"
                    )
                # As the book spells it: the map is keyed by the canonical
                # form, and a hyphenated, upper-case or unquoted all-digit
                # guid is the same guid written another way.
                guid = the_guid_a_block_names(child.metadata)
                if guid not in existing_guid_map:
                    raise ValueError(f"Transaction GUID {guid!r} not found in book")

            for child in tx_directives:
                guid = the_guid_a_block_names(child.metadata)
                existing_tx = existing_guid_map[guid]
                try:
                    importer.update_transaction(existing_tx, child, book)
                    result.updated_count += 1
                    # Which transactions this pass has already reported, so
                    # a `payment:` block correcting one of their memos is
                    # not counted a second time under the same figure.
                    result.updated_transaction_guids.add(
                        existing_tx.GetGUID().to_string())
                except Exception as e:
                    logging.error(f"Failed to update transaction {guid}: {e}")
                    result.errors.append({'transaction': child.props, 'error': str(e)})
                    result.error_count += 1
            return result

        for child in parser.root_directive.children:
            if child.type == DirectiveType.TRANSACTION:
                try:
                    # Check for match by GUID if present (non-UPDATE strategies)
                    if 'guid' in child.metadata:
                        # As the book spells it, for the reason the update
                        # strategy gives above.
                        guid = the_guid_a_block_names(child.metadata)
                        if guid in existing_guid_map:
                            _date = child.props.get('date', '?')
                            _desc = child.props.get('tx_desc') or '(no description)'
                            _splits = ', '.join(
                                f"{s.props.get('account', '?')} {s.props.get('amount', '?')}"
                                for s in child.children
                                if s.props.get('account')
                            )
                            # If the incoming content actually differs from the
                            # existing tx, the user is editing — but the default
                            # strategy skips it. Count that so the CLI can hint
                            # at --strategy update (it is not a true duplicate).
                            changed = _guid_match_content_differs(
                                child, existing_guid_map[guid])
                            if changed:
                                result.guid_changed_skips += 1
                            logging.warning(
                                "Skipping %s (GUID match): %s \"%s\" [%s]\n"
                                "  matched existing transaction by GUID: %s",
                                'EDITED transaction' if changed else 'duplicate',
                                _date, _desc, _splits, guid,
                            )
                            result.skipped_count += 1
                            continue

                    # Q-020: route through the matcher so the full signature
                    # contract (date, accounts, doc_link, tx_num, owner) is
                    # honoured. The prior inline scan compared only date and
                    # the set of accounts, silently dropping legitimate
                    # second same-day transactions distinguished by any of
                    # the other three fields.
                    date_str = child.props['date']
                    split_accounts = [split.props['account'] for split in child.children]
                    incoming_doc_link = child.metadata.get('doc_link')
                    incoming_tx_num = child.props.get('tx_num')
                    incoming_owner = child.metadata.get('owner')
                    incoming_sig = self.matcher.get_signature_for_plaintext(
                        date_str, split_accounts,
                        doc_link=incoming_doc_link,
                        tx_num=incoming_tx_num,
                        owner=incoming_owner,
                    )

                    matched_existing = [
                        tx for tx in existing_transactions
                        if self.matcher.get_signature(tx) == incoming_sig
                    ]

                    if matched_existing:
                        _desc = child.props.get('tx_desc') or '(no description)'
                        _splits = ', '.join(
                            f"{s.props.get('account', '?')} {s.props.get('amount', '?')}"
                            for s in child.children
                            if s.props.get('account')
                        )
                        matched_guids = ', '.join(
                            tx.GetGUID().to_string() for tx in matched_existing
                        )
                        logging.warning(
                            "Skipping duplicate (signature match): %s \"%s\" [%s]\n"
                            "  signature: date=%s accounts=%s doc_link=%r tx_num=%r owner=%r\n"
                            "  matched existing transaction(s): %s",
                            date_str, _desc, _splits,
                            incoming_sig[0],
                            list(incoming_sig[1]),
                            incoming_sig[2],
                            incoming_sig[3],
                            incoming_sig[4],
                            matched_guids,
                        )
                        result.skipped_count += 1
                        continue

                    # Create transaction
                    tx = importer.create_transaction(child, book)
                    result.imported_count += 1
                    # Counted here, so a `payment:` block writing a memo
                    # onto a transaction this run created is not counted
                    # again as one it updated.
                    if tx is not None:
                        result.new_transaction_guids.add(
                            tx.GetGUID().to_string())
                    result.new_transactions.append(tx)

                except Exception as e:
                    logging.error(f"Failed to import transaction: {e}")
                    result.errors.append({
                        'transaction': child.props,
                        'error': str(e)
                    })
                    result.error_count += 1

        return result
