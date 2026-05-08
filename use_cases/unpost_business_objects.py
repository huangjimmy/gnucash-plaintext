"""
Q-010: dedicated unpost commands for invoices and bills.

`unpost-invoice <book> <ID>...` and `unpost-bill <book> <ID>...` provide
a one-shot, plaintext-free way to unpost a posted invoice/bill. Unlike
the re-import path (where toggling `posted: { ... }` → `posted: none`
also unposts but rebuilds entries from the .txt), this path:

  - Does NOT consult any plaintext file.
  - Preserves entry GUIDs (no destroy + recreate cycle).
  - Touches only the posted state. The lot's posting transaction is
    destroyed; payment transactions in the bank account are orphaned
    (their AR/AP splits no longer link to a lot). This matches GnuCash
    UI's own Unpost behaviour exactly.

Use the re-import path when the .txt is the source of truth and you
want to also edit fields. Use this command when the .txt is stale or
absent and you only want the unpost itself.
"""

from dataclasses import dataclass
from enum import Enum, auto
from typing import List

from gnucash import Book

from services.gnucash_importer import (
    _find_bill_by_guid,
    _find_bills_by_id,
    _find_invoice_by_guid,
    _find_invoices_by_id,
    _swig_invoice_guid_str,
)


class UnpostStatus(Enum):
    UNPOSTED = auto()
    NOT_POSTED = auto()
    NOT_FOUND = auto()
    AMBIGUOUS_ID = auto()  # legacy data: multiple records share one id


@dataclass
class UnpostResult:
    id: str
    guid: str = ''
    status: UnpostStatus = None

    def message(self) -> str:
        if self.status == UnpostStatus.UNPOSTED:
            return 'unposted'
        if self.status == UnpostStatus.NOT_POSTED:
            return ('failed — record has no posting transaction (never posted, '
                    'or already unposted by a previous run / GnuCash UI); '
                    'no action taken')
        if self.status == UnpostStatus.AMBIGUOUS_ID:
            return ('failed — multiple records share this id; rerun with '
                    '--by-guid')
        return 'not found'

    def label(self) -> str:
        if self.guid:
            return f'{self.id} ({self.guid})'
        return self.id


def _resolve_one(book: Book, id_or_guid: str, by_guid: bool, by_id_fn, by_guid_fn):
    """Look up exactly one invoice/bill. Returns (record, report_id, report_guid).

    On miss: (None, original_input, '').
    On ambiguous (legacy duplicates): (None, original_input, '__ambiguous__')
    so the caller can map to AMBIGUOUS_ID. We refuse to silently pick one.
    """
    if by_guid:
        rec = by_guid_fn(book, id_or_guid)
        if rec is None:
            return None, id_or_guid, ''
        return rec, rec.GetID(), id_or_guid
    matches = by_id_fn(book, id_or_guid)
    if not matches:
        return None, id_or_guid, ''
    if len(matches) > 1:
        return None, id_or_guid, '__ambiguous__'
    rec = matches[0]
    return rec, rec.GetID(), _swig_invoice_guid_str(rec)


class UnpostInvoicesUseCase:
    """Unpost one or more posted customer invoices."""

    def __init__(self, book: Book):
        self.book = book

    def execute(self, ids: List[str], by_guid: bool = False) -> List[UnpostResult]:
        results = []
        for arg in ids:
            rec, rid, rguid = _resolve_one(
                self.book, arg, by_guid, _find_invoices_by_id, _find_invoice_by_guid)
            if rec is None and rguid == '__ambiguous__':
                results.append(UnpostResult(id=rid, status=UnpostStatus.AMBIGUOUS_ID))
                continue
            if rec is None:
                results.append(UnpostResult(id=rid, status=UnpostStatus.NOT_FOUND))
                continue
            if rec.GetPostedTxn() is None:
                results.append(UnpostResult(id=rid, guid=rguid,
                                            status=UnpostStatus.NOT_POSTED))
                continue
            rec.Unpost(False)
            results.append(UnpostResult(id=rid, guid=rguid,
                                        status=UnpostStatus.UNPOSTED))
        return results


class UnpostBillsUseCase:
    """Unpost one or more posted vendor bills."""

    def __init__(self, book: Book):
        self.book = book

    def execute(self, ids: List[str], by_guid: bool = False) -> List[UnpostResult]:
        results = []
        for arg in ids:
            rec, rid, rguid = _resolve_one(
                self.book, arg, by_guid, _find_bills_by_id, _find_bill_by_guid)
            if rec is None and rguid == '__ambiguous__':
                results.append(UnpostResult(id=rid, status=UnpostStatus.AMBIGUOUS_ID))
                continue
            if rec is None:
                results.append(UnpostResult(id=rid, status=UnpostStatus.NOT_FOUND))
                continue
            if rec.GetPostedTxn() is None:
                results.append(UnpostResult(id=rid, guid=rguid,
                                            status=UnpostStatus.NOT_POSTED))
                continue
            rec.Unpost(False)
            results.append(UnpostResult(id=rid, guid=rguid,
                                        status=UnpostStatus.UNPOSTED))
        return results
