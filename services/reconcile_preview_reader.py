from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

from infrastructure.gnucash.utils import unescape_string
from infrastructure.pdf.standard_tx import Split, StandardTransaction

AUTOPAY_ACCOUNT = "Reconcile:Autopay"

# Matches: YYYY-MM-DD * "description"
DATE_LINE_RE = re.compile(r'^(\d{4}-\d{2}-\d{2})\s+\*\s+"(.*)"$')
# Matches tab-indented key: "value"  or  key: value
META_RE = re.compile(r'^\t(\S[^:]*?):\s+"?([^"]*)"?\s*$')
# Matches tab-indented split: account amount currency
SPLIT_RE = re.compile(r'^\t(\S.*?)\s+([-\d.]+)\s+([A-Z]+)\s*$')


class ReconcilePreviewReader:
    """Reads _reconcile.txt and classifies transactions by Reconcile:Autopay presence.

    Returns (importable, unresolved):
    - importable: all transactions without Reconcile:Autopay (resolved + normal)
    - unresolved: transactions containing Reconcile:Autopay

    Section headers (;; ===== ... =====) and all ;; comment lines are skipped.
    Classification is by account name only — section position has no effect.
    """

    def read(
        self, path: str
    ) -> tuple[list[StandardTransaction], list[StandardTransaction]]:
        importable: list[StandardTransaction] = []
        unresolved: list[StandardTransaction] = []

        with open(path, encoding="utf-8") as f:
            lines = f.readlines()

        pending = _parse_blocks(lines)
        for tx in pending:
            if any(s.account == AUTOPAY_ACCOUNT for s in tx.splits):
                unresolved.append(tx)
            else:
                importable.append(tx)

        return importable, unresolved


def _parse_blocks(lines: list[str]) -> list[StandardTransaction]:
    txs: list[StandardTransaction] = []
    i = 0
    while i < len(lines):
        line = lines[i].rstrip("\n")

        # Skip comment lines (includes section headers)
        if line.startswith(";;") or line.strip() == "":
            i += 1
            continue

        m = DATE_LINE_RE.match(line)
        if not m:
            i += 1
            continue

        post_date = date.fromisoformat(m.group(1))
        # The four escapes `ReconcilePreviewWriter` writes, not the quote
        # alone: a description holding `C:\name` is written `C:\\name`, and
        # undoing one escape of the four hands it back a character too many.
        description = unescape_string(m.group(2))
        guid = None
        source_pdfs: list[str] = []
        currency = "HKD"
        splits: list[Split] = []

        i += 1
        while i < len(lines):
            inner = lines[i].rstrip("\n")
            if inner.strip() == "" or DATE_LINE_RE.match(inner) or inner.startswith(";;"):
                break

            meta = META_RE.match(inner)
            if meta:
                key, val = meta.group(1).strip(), meta.group(2).strip()
                if key == "guid":
                    guid = val
                elif key == "doc_link":
                    # Extract filename from "bank_statements/file.pdf"
                    source_pdfs.insert(0, val.split("/")[-1])

                elif key == "currency.mnemonic":
                    currency = val
                i += 1
                continue

            split_m = SPLIT_RE.match(inner)
            if split_m:
                account = split_m.group(1).strip()
                amount = Decimal(split_m.group(2))
                splits.append(Split(account=account, amount=amount))
                i += 1
                continue

            i += 1

        if len(splits) >= 2:
            txs.append(StandardTransaction(
                post_date=post_date,
                description=description,
                currency=currency,
                splits=splits,
                source_pdfs=source_pdfs,
                guid=guid,
            ))

    return txs
