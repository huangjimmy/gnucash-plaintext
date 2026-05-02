from __future__ import annotations

import contextlib
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from enum import Enum

from infrastructure.pdf.standard_tx import Split, StandardTransaction

# GnuCash imports are lazy (inside _build_index) to avoid loading the C
# extension at module import time — unit tests must not trigger that load.


class MatchStatus(Enum):
    NEW = "new"
    LIKELY_DUP = "likely_dup"
    PARTIAL_MATCH = "partial"


@dataclass
class _IndexEntry:
    """Python-native snapshot of a GnuCash transaction.

    Extracted during _build_index() so the GnuCash session can be closed
    immediately after indexing. No live GnuCash C-extension references remain
    after index build — prevents session leak and OOM in the test suite.
    """
    post_date: date
    amount: Decimal                          # sum of positive splits
    account_names: frozenset[str]            # all split account full names
    asset_liability_accounts: frozenset[str] # subset by account type
    guid: str
    description: str
    splits: list[tuple[str, Decimal]]        # (account_name, signed_amount)
    doc_link: str = ""


@dataclass
class MatchResult:
    status: MatchStatus
    existing: _IndexEntry | None   # None only for NEW
    merged_tx: StandardTransaction | None  # non-None only for PARTIAL_MATCH


class GnuCashFuzzyMatcher:
    """Fuzzy-matches StandardTransaction candidates against an existing GnuCash book.

    Opens GnuCashRepository READ_ONLY, extracts all transaction data into
    Python-native _IndexEntry objects, then closes the session immediately.
    No GnuCash C-extension references are kept after index build.
    """

    _ONE_DAY = timedelta(days=1)

    def __init__(self, repo) -> None:
        self._repo = repo
        self._index: dict[tuple[date, Decimal], list[_IndexEntry]] = {}
        self._built = False

    def _build_index(self) -> None:
        if self._built:
            return

        from infrastructure.gnucash.utils import gnc_numeric_to_fraction_or_decimal
        from repositories.gnucash_repository import SessionMode

        try:
            import gnucash as gc
            _al_types = {
                gc.ACCT_TYPE_ASSET, gc.ACCT_TYPE_BANK, gc.ACCT_TYPE_CASH,
                gc.ACCT_TYPE_CREDIT, gc.ACCT_TYPE_EQUITY, gc.ACCT_TYPE_LIABILITY,
                gc.ACCT_TYPE_MUTUAL,
            }
        except Exception:
            _al_types = set()

        self._repo.open(mode=SessionMode.READ_ONLY)
        try:
            for tx in self._repo.get_all_transactions():
                raw_splits = tx.GetSplitList()
                splits_data: list[tuple[str, Decimal]] = []
                al_accounts: set[str] = set()

                for sp in raw_splits:
                    acct = sp.GetAccount()
                    name = _full_name(acct)
                    amount = Decimal(gnc_numeric_to_fraction_or_decimal(sp.GetAmount()))
                    splits_data.append((name, amount))
                    try:
                        if acct.GetType() in _al_types:
                            al_accounts.add(name)
                    except Exception:
                        pass

                positive = sum(a for _, a in splits_data if a > 0)
                if positive <= Decimal(0):
                    continue

                d = tx.GetDate().date()
                guid = tx.GetGUID().to_string()
                desc = tx.GetDescription() or ""

                # Extract doc_link from KVP metadata
                from infrastructure.gnucash.kvp import get_custom_metadata
                doc_link = get_custom_metadata(tx).get("doc_link", "")

                entry = _IndexEntry(
                    post_date=d,
                    amount=positive,
                    account_names=frozenset(n for n, _ in splits_data),
                    asset_liability_accounts=frozenset(al_accounts),
                    guid=guid,
                    description=desc,
                    splits=splits_data,
                    doc_link=doc_link,
                )
                key = (d, positive)
                self._index.setdefault(key, []).append(entry)
        finally:
            # Always close session — releases the entire GnuCash book from memory
            with contextlib.suppress(Exception):
                self._repo.session.end()

        self._built = True

    def match(self, tx: StandardTransaction) -> MatchResult:
        self._build_index()

        positive = sum(s.amount for s in tx.splits if s.amount > Decimal(0))
        if positive <= Decimal(0):
            return MatchResult(status=MatchStatus.NEW, existing=None, merged_tx=None)

        d = tx.post_date
        candidates: list[_IndexEntry] = (
            self._index.get((d - self._ONE_DAY, positive), [])
            + self._index.get((d, positive), [])
            + self._index.get((d + self._ONE_DAY, positive), [])
        )

        if not candidates:
            return MatchResult(status=MatchStatus.NEW, existing=None, merged_tx=None)

        best = _pick_best(candidates, tx, d)
        candidate_accounts = frozenset(s.account for s in tx.splits)

        if best.account_names == candidate_accounts:
            return MatchResult(status=MatchStatus.LIKELY_DUP, existing=best, merged_tx=None)

        candidate_al = frozenset(
            s.account for s in tx.splits
            if s.account in best.asset_liability_accounts
        )

        if best.asset_liability_accounts == candidate_al:
            merged = _build_merge(tx, best)
            return MatchResult(status=MatchStatus.PARTIAL_MATCH, existing=best, merged_tx=merged)

        return MatchResult(status=MatchStatus.NEW, existing=None, merged_tx=None)


def _full_name(acct) -> str:
    parts = []
    a = acct
    while a is not None:
        name = a.GetName()
        if not name or name == "Root Account":
            break
        parts.append(name)
        a = a.get_parent()
    return ":".join(reversed(parts))


def _pick_best(candidates: list[_IndexEntry], tx: StandardTransaction, target: date) -> _IndexEntry:
    """Choose best candidate: exact date > most shared accounts > earliest date."""
    candidate_accounts = {s.account for s in tx.splits}

    def score(e: _IndexEntry) -> tuple:
        date_score = 0 if e.post_date == target else 1
        shared = len(e.account_names & candidate_accounts)
        return (date_score, -shared, e.post_date)

    return min(candidates, key=score)


def _build_merge(candidate: StandardTransaction, existing: _IndexEntry) -> StandardTransaction:
    """Produce merged StandardTransaction for PARTIAL_MATCH.

    Merge rules: GnuCash category/date/guid/amount win; generated doc_link wins.
    """
    description = existing.description if existing.description.strip() else candidate.description

    splits = [Split(account=name, amount=amount) for name, amount in existing.splits]

    doc_link_pdf = candidate.source_pdfs[0] if candidate.source_pdfs else ""
    if not doc_link_pdf and existing.doc_link:
        doc_link_pdf = existing.doc_link.split("/")[-1]

    source_pdfs = [doc_link_pdf] if doc_link_pdf else []
    if len(candidate.source_pdfs) > 1:
        source_pdfs.append(candidate.source_pdfs[1])

    return StandardTransaction(
        post_date=existing.post_date,
        description=description,
        currency=candidate.currency,
        splits=splits,
        source_pdfs=source_pdfs,
        guid=existing.guid,
    )
