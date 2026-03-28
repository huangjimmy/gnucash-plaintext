#!/usr/bin/env python3
"""
Bank Import Matching Demo
=========================

Demonstrates the conflict between a GnuCash invoice payment transaction
and a bank OFX import transaction, and shows how interactive matching
resolves it by linking them via FITID.

Run inside Docker:
    bash demos/bank_import_matching/run.sh

What this demo shows:
    1. An invoice payment is applied in GnuCash  → State 2 transaction
       (Bank + AR, no FITID)
    2. The same payment arrives via bank OFX import → State 1 transaction
       (Bank + Imbalance, FITID stored as metadata)
    3. Both appear in the bank account — a double-count
    4. Interactive matching by date + amount finds the pair
    5. User confirms → FITID transferred, Imbalance transaction deleted → State 3

WARNING: The date + amount matching in this demo is for illustration only.
         It will produce wrong results when two transactions share the same
         date and amount. You are responsible for implementing a matching
         strategy appropriate for your data.
"""

import glob as glob_module
import os
import tempfile
import time

# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------

SAMPLE_DATE = (15, 3, 2026)          # day, month, year
SAMPLE_AMOUNT_NUM = 100000           # GncNumeric numerator   (1000.00 CAD)
SAMPLE_AMOUNT_DEN = 100              # GncNumeric denominator
SAMPLE_FITID = "BNK-20260315-00042"  # bank's unique transaction ID
SAMPLE_BANK_MEMO = "e-TRANSFER FROM ACME CORP REF 00042"
SAMPLE_INVOICE_DESC = "Payment for INV-2026-031 (Acme Corp)"


# ---------------------------------------------------------------------------
# Book setup
# ---------------------------------------------------------------------------

def create_book(path):
    """
    Create a new GnuCash file with a minimal account structure:

        Assets
          Bank
            Checking      ← the bank account we are importing into
          Receivable
            AcmeCorp      ← AR account for invoice payment
        Income
          Services
        Imbalance
          CAD             ← placeholder used by bank import (State 1)
    """
    import gnucash
    from gnucash import Account, Session

    try:
        from gnucash import SessionOpenMode
        session = Session(f'xml://{path}', SessionOpenMode.SESSION_NEW_STORE)
    except ImportError:
        session = Session(f'xml://{path}', is_new=True)

    book = session.book
    root = book.get_root_account()
    cad = book.get_table().lookup('CURRENCY', 'CAD')

    def make(parent, name, acct_type):
        acct = Account(book)
        acct.SetName(name)
        acct.SetType(acct_type)
        acct.SetCommodity(cad)
        parent.append_child(acct)
        return acct

    assets     = make(root,    'Assets',     gnucash.ACCT_TYPE_ASSET)
    bank       = make(assets,  'Bank',       gnucash.ACCT_TYPE_BANK)
    make(bank,    'Checking',   gnucash.ACCT_TYPE_BANK)
    recv       = make(assets,  'Receivable', gnucash.ACCT_TYPE_RECEIVABLE)
    make(recv,    'AcmeCorp',   gnucash.ACCT_TYPE_RECEIVABLE)
    income     = make(root,    'Income',     gnucash.ACCT_TYPE_INCOME)
    _services  = make(income,  'Services',   gnucash.ACCT_TYPE_INCOME)
    imbalance  = make(root,    'Imbalance',  gnucash.ACCT_TYPE_ASSET)
    make(imbalance, 'CAD',      gnucash.ACCT_TYPE_ASSET)

    session.save()
    session.end()
    return path


# ---------------------------------------------------------------------------
# Transaction helpers
# ---------------------------------------------------------------------------

def _find_account(root, path):
    """Walk account path like 'Assets:Bank:Checking'."""
    acc = root
    for name in path.split(':'):
        acc = next(
            (c for c in acc.get_children_sorted() if c.GetName() == name),
            None,
        )
        if acc is None:
            return None
    return acc


def create_invoice_payment(path):
    """
    State 2: invoice payment transaction.

    Simulates what GnuCash creates when you apply payment to an invoice:
        Assets:Bank:Checking          +1000.00 CAD  reconcile=n
        Assets:Receivable:AcmeCorp    -1000.00 CAD

    No FITID — GnuCash's Apply Payment knows nothing about bank references.
    """
    from gnucash import GncNumeric, Session, Split, Transaction

    try:
        from gnucash import SessionOpenMode
        session = Session(f'xml://{path}', SessionOpenMode.SESSION_NORMAL_OPEN)
    except ImportError:
        session = Session(f'xml://{path}', is_new=False)

    book = session.book
    cad = book.get_table().lookup('CURRENCY', 'CAD')
    root = book.get_root_account()
    checking = _find_account(root, 'Assets:Bank:Checking')
    ar_acme  = _find_account(root, 'Assets:Receivable:AcmeCorp')

    tx = Transaction(book)
    tx.BeginEdit()
    tx.SetCurrency(cad)
    tx.SetDate(*SAMPLE_DATE)
    tx.SetDescription(SAMPLE_INVOICE_DESC)

    s_bank = Split(book)
    s_bank.SetParent(tx)
    s_bank.SetAccount(checking)
    s_bank.SetValue(GncNumeric(SAMPLE_AMOUNT_NUM, SAMPLE_AMOUNT_DEN))
    s_bank.SetReconcile('n')   # not yet matched to any bank statement

    s_ar = Split(book)
    s_ar.SetParent(tx)
    s_ar.SetAccount(ar_acme)
    s_ar.SetValue(GncNumeric(-SAMPLE_AMOUNT_NUM, SAMPLE_AMOUNT_DEN))

    tx.CommitEdit()
    session.save()
    session.end()

    print("[State 2] Invoice payment transaction created:")
    print(f"          {SAMPLE_INVOICE_DESC}")
    print("          Assets:Bank:Checking +1000.00 CAD  reconcile=n  (no FITID)")
    print("          Assets:Receivable:AcmeCorp -1000.00 CAD")
    print()


def create_bank_import(path):
    """
    State 1: bank OFX import transaction.

    Simulates what gnucash-plaintext's import-bank command creates when it
    sees an OFX entry with no matching FITID already in the book:
        Assets:Bank:Checking          +1000.00 CAD  reconcile=c
        Imbalance:CAD                 -1000.00 CAD

    FITID is stored as custom metadata on the bank split so it can never
    be imported twice.
    """
    from gnucash import GncNumeric, Session, Split, Transaction

    from infrastructure.gnucash.kvp import set_custom_metadata

    try:
        from gnucash import SessionOpenMode
        session = Session(f'xml://{path}', SessionOpenMode.SESSION_NORMAL_OPEN)
    except ImportError:
        session = Session(f'xml://{path}', is_new=False)

    book = session.book
    cad = book.get_table().lookup('CURRENCY', 'CAD')
    root = book.get_root_account()
    checking   = _find_account(root, 'Assets:Bank:Checking')
    imbal_cad  = _find_account(root, 'Imbalance:CAD')

    tx = Transaction(book)
    tx.BeginEdit()
    tx.SetCurrency(cad)
    tx.SetDate(*SAMPLE_DATE)
    tx.SetDescription(SAMPLE_BANK_MEMO)

    s_bank = Split(book)
    s_bank.SetParent(tx)
    s_bank.SetAccount(checking)
    s_bank.SetValue(GncNumeric(SAMPLE_AMOUNT_NUM, SAMPLE_AMOUNT_DEN))
    s_bank.SetReconcile('c')   # cleared: seen on bank statement

    # Store FITID on the bank split — this is the deduplication key.
    # Any future import-bank run that sees the same FITID will skip this entry.
    set_custom_metadata(s_bank, {'fitid': SAMPLE_FITID})

    s_imbal = Split(book)
    s_imbal.SetParent(tx)
    s_imbal.SetAccount(imbal_cad)
    s_imbal.SetValue(GncNumeric(-SAMPLE_AMOUNT_NUM, SAMPLE_AMOUNT_DEN))

    tx.CommitEdit()
    session.save()
    session.end()

    print("[State 1] Bank OFX import transaction created:")
    print(f"          {SAMPLE_BANK_MEMO}")
    print(f"          Assets:Bank:Checking +1000.00 CAD  reconcile=c  FITID={SAMPLE_FITID}")
    print("          Imbalance:CAD -1000.00 CAD")
    print()


# ---------------------------------------------------------------------------
# Conflict detection
# ---------------------------------------------------------------------------

def show_conflict(path):
    """
    Show that the bank account now has two splits for the same real deposit.
    """
    from gnucash import Session

    try:
        from gnucash import SessionOpenMode
        session = Session(f'xml://{path}', SessionOpenMode.SESSION_NORMAL_OPEN)
    except ImportError:
        session = Session(f'xml://{path}', is_new=False)

    try:
        book = session.book
        root = book.get_root_account()
        checking = _find_account(root, 'Assets:Bank:Checking')

        print("=" * 60)
        print("CONFLICT: Assets:Bank:Checking now has TWO splits")
        print("          for the same real-world deposit of $1000.00:")
        print("=" * 60)
        for split in checking.GetSplitList():
            tx = split.parent
            val = split.GetValue()
            rec = split.GetReconcile()
            print(f"  [{rec}]  {tx.GetDescription():<45}  {val.num() / val.denom():+.2f} CAD")
        print()
    finally:
        session.end()


# ---------------------------------------------------------------------------
# Interactive matching (date + amount — DEMO ONLY, see disclaimer)
# ---------------------------------------------------------------------------

def interactive_match(path):
    """
    WARNING: Matches by date + amount. For demo purposes only.
             Same-day same-amount collisions will produce wrong suggestions.
             You are responsible for your own matching strategy.
    """
    from gnucash import Session

    from infrastructure.gnucash.kvp import get_custom_metadata, set_custom_metadata

    print("WARNING: The following match is based on date + amount only.")
    print("         This is a DEMO. Same-day same-amount collisions will")
    print("         produce wrong results. You own your matching logic.")
    print()

    try:
        from gnucash import SessionOpenMode
        session = Session(f'xml://{path}', SessionOpenMode.SESSION_NORMAL_OPEN)
    except ImportError:
        session = Session(f'xml://{path}', is_new=False)

    try:
        book = session.book
        root = book.get_root_account()
        checking = _find_account(root, 'Assets:Bank:Checking')

        # Separate splits into State 1 (have FITID) and State 2 (no FITID, reconcile=n)
        state1 = []   # (split, tx, fitid)
        state2 = []   # (split, tx)

        for split in checking.GetSplitList():
            tx = split.parent
            meta = get_custom_metadata(split)
            fitid = meta.get('fitid')
            if fitid:
                state1.append((split, tx, fitid))
            elif split.GetReconcile() == 'n':
                state2.append((split, tx))

        if not state1:
            print("No unlinked bank import transactions found.")
            return

        for s1_split, s1_tx, fitid in state1:
            s1_val = s1_split.GetValue()
            s1_amount = s1_val.num() / s1_val.denom()
            s1_date = s1_tx.GetDate()

            print(f"Bank entry:  {s1_tx.GetDescription()}")
            print(f"             date={s1_date}  amount={s1_amount:+.2f} CAD  FITID={fitid}")
            print()

            # Find State 2 candidates with matching date + amount (DEMO ONLY)
            candidates = []
            for s2_split, s2_tx in state2:
                s2_val = s2_split.GetValue()
                s2_amount = s2_val.num() / s2_val.denom()
                if s2_tx.GetDate() == s1_date and abs(s2_amount - s1_amount) < 0.001:
                    candidates.append((s2_split, s2_tx))

            if not candidates:
                print("  No matching invoice payment found by date + amount.")
                print("  Leaving as State 1 (Imbalance). Categorize manually.")
                print()
                continue

            if len(candidates) > 1:
                print(f"  AMBIGUOUS: {len(candidates)} transactions match this date + amount.")
                print("  Cannot auto-resolve. Inspect manually:")
                for i, (_, tx) in enumerate(candidates):
                    print(f"    [{i}] {tx.GetDescription()}")
                print()
                continue

            s2_split, s2_tx = candidates[0]
            print(f"  Candidate:  {s2_tx.GetDescription()}")
            print("              (no FITID, reconcile=n)")
            print()

            answer = input(
                f"  Is '{s1_tx.GetDescription()}'\n"
                f"  the same payment as '{s2_tx.GetDescription()}'? [y/N] "
            ).strip().lower()

            if answer != 'y':
                print("  Skipped.")
                print()
                continue

            # --- Link: transfer FITID to invoice payment, delete Imbalance txn ---
            s2_tx.BeginEdit()
            set_custom_metadata(s2_split, {'fitid': fitid})
            s2_split.SetReconcile('c')
            s2_tx.CommitEdit()

            # CommitEdit after Destroy is required to flush the deletion from
            # GnuCash's in-memory transaction list (mirrors GnuCashRepository
            # .delete_transaction which uses the same pattern).
            s1_tx.BeginEdit()
            s1_tx.Destroy()
            s1_tx.CommitEdit()
            session.save()
            print()
            print("[State 3] Linked. Result:")
            print(f"          {s2_tx.GetDescription()}")
            print(f"          Assets:Bank:Checking +1000.00 CAD  reconcile=c  FITID={fitid}")
            print("          Assets:Receivable:AcmeCorp -1000.00 CAD")
            print()

    finally:
        session.end()


# ---------------------------------------------------------------------------
# Final state
# ---------------------------------------------------------------------------

def show_result(path):
    from gnucash import Session

    from infrastructure.gnucash.kvp import get_custom_metadata

    try:
        from gnucash import SessionOpenMode
        session = Session(f'xml://{path}', SessionOpenMode.SESSION_NORMAL_OPEN)
    except ImportError:
        session = Session(f'xml://{path}', is_new=False)

    try:
        book = session.book
        root = book.get_root_account()
        checking = _find_account(root, 'Assets:Bank:Checking')

        print("=" * 60)
        print("FINAL: Assets:Bank:Checking splits")
        print("=" * 60)
        for split in checking.GetSplitList():
            tx = split.parent
            val = split.GetValue()
            rec = split.GetReconcile()
            meta = get_custom_metadata(split)
            fitid = meta.get('fitid', '(none)')
            print(f"  [{rec}]  {tx.GetDescription():<45}  {val.num() / val.denom():+.2f}  FITID={fitid}")
        print()
    finally:
        session.end()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    fd, path = tempfile.mkstemp(suffix='.gnucash')
    os.close(fd)
    os.unlink(path)

    try:
        print()
        print("=== Bank Import Matching Demo ===")
        print()

        print("Step 1: Create sample GnuCash book")
        create_book(path)
        print("        Done.")
        print()

        print("Step 2: Apply Payment on invoice (GnuCash GUI equivalent)")
        create_invoice_payment(path)
        time.sleep(1)  # avoid backup timestamp collision on rapid session reopen

        print("Step 3: Import bank OFX entry (import-bank equivalent)")
        create_bank_import(path)
        time.sleep(1)

        print("Step 4: Show the conflict")
        show_conflict(path)

        print("Step 5: Interactive matching (date + amount — DEMO ONLY)")
        print()
        interactive_match(path)

        print("Step 6: Final state")
        show_result(path)

    finally:
        for suffix in ('', '.LCK'):
            if os.path.exists(path + suffix):
                os.unlink(path + suffix)
        for backup in glob_module.glob(path + '.*.gnucash'):
            os.unlink(backup)
        log_path = path + '.log'
        if os.path.exists(log_path):
            os.unlink(log_path)


if __name__ == '__main__':
    main()
