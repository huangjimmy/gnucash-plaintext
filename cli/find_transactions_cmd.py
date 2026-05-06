"""
CLI command to find transactions by account, date, and/or amount.

Used to discover the GUID of a bank transaction that was imported from a
bank feed and needs to be linked to an invoice payment block:

    gnucash-plaintext find-transactions ledger.gnucash \
        --account "Assets:Bank" \
        --date 2026-01-15 \
        --amount 100

Output (one line per match):
    317c8ae6e0084c33951d052b9f1b9f23  2026-01-15  100.00  "E-transfer from Acme"

Copy the GUID into the payment block's txn_guid field:

    payment:
        date: 2026-01-15
        amount: 100
        bank_account: "Assets:Bank"
        memo: "Payment INV-001"
        txn_guid: 317c8ae6e0084c33951d052b9f1b9f23
"""

import ctypes

import click

from infrastructure.gnucash.engine import GncNumericC, load_gnc_engine, safe_ctypes_string
from repositories.gnucash_repository import GnuCashRepository, SessionMode


@click.command('find-transactions')
@click.argument('gnucash_file', type=click.Path(exists=True))
@click.option('--account', '-a', default=None,
              help='Account full name (e.g. "Assets:Bank"). Matches any split in the transaction.')
@click.option('--date', '-d', default=None,
              help='Transaction date filter (YYYY-MM-DD).')
@click.option('--amount', '-n', default=None, type=float,
              help='Absolute amount to match (sign-insensitive).')
def find_transactions(gnucash_file, account, date, amount):
    """
    Find transactions by account, date, and/or amount and print their GUIDs.

    At least one filter must be provided. Output is one matching transaction
    per line:

    \b
      GUID                              DATE        AMOUNT    DESCRIPTION
      317c8ae6e0084c33951d052b9f1b9f23  2026-01-15  100.00    E-transfer from Acme

    Use the GUID in a payment block's txn_guid field to link an existing bank
    transaction to an invoice payment without creating a duplicate.

    \b
    Examples:
      gnucash-plaintext find-transactions ledger.gnucash --account "Assets:Bank"
      gnucash-plaintext find-transactions ledger.gnucash --date 2026-01-15 --amount 100
      gnucash-plaintext find-transactions ledger.gnucash -a "Assets:Bank" -d 2026-01-15
    """
    if not any([account, date, amount is not None]):
        raise click.UsageError('At least one of --account, --date, or --amount must be provided.')

    lib = load_gnc_engine()
    # xaccSplitGetAccount: const-type SWIG mismatch (see docs/DEBUGGING_GNUCASH_BINDINGS.md).
    # xaccSplitGetAmount: "once ctypes, stay ctypes" — split_ptr is already in
    # ctypes domain, so we read the amount via ctypes too (GncNumericC struct).
    lib.xaccSplitGetAccount.argtypes = [ctypes.c_void_p]
    lib.xaccSplitGetAccount.restype = ctypes.c_void_p
    lib.xaccSplitGetAmount.argtypes = [ctypes.c_void_p]
    lib.xaccSplitGetAmount.restype = GncNumericC

    def _split_acct_name(split_ptr: int) -> str:
        acct_ptr = lib.xaccSplitGetAccount(split_ptr)
        if not acct_ptr:
            return ''
        parts = []
        ptr = acct_ptr
        while ptr:
            name = safe_ctypes_string(lib.xaccAccountGetName, ptr)
            if name:
                parts.append(name)
            parent = lib.gnc_account_get_parent(ptr)
            if not parent:
                break
            grandparent = lib.gnc_account_get_parent(parent)
            if not grandparent:
                break
            ptr = parent
        parts.reverse()
        return ':'.join(parts)

    def _split_amount(split_ptr: int) -> float:
        # Use ctypes — stays consistent with _split_acct_name (once ctypes,
        # stay ctypes per CLAUDE.md pointer lifetime rules).
        amt = lib.xaccSplitGetAmount(split_ptr)
        return abs(amt.num / amt.denom) if amt.denom else 0.0

    repo = GnuCashRepository(gnucash_file)
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        transactions = repo.get_all_transactions()
        matched = 0
        for tx in transactions:
            tx_date = tx.GetDate().strftime('%Y-%m-%d')
            tx_desc = tx.GetDescription() or ''

            if date and tx_date != date:
                continue

            split_matches = []
            for split_obj in tx.GetSplitList():
                split_ptr = int(split_obj.instance)
                acct_name = _split_acct_name(split_ptr)
                try:
                    split_amt = _split_amount(split_ptr)
                except Exception:
                    continue

                account_ok = (account is None) or (acct_name == account)
                amount_ok = (amount is None) or (abs(split_amt - amount) < 0.005)

                if account_ok and amount_ok:
                    split_matches.append((acct_name, split_amt))

            if not split_matches:
                continue

            display_amount = split_matches[0][1]
            guid = tx.GetGUID().to_string()
            click.echo(f'{guid}  {tx_date}  {display_amount:>10.2f}  "{tx_desc}"')
            matched += 1

        if matched == 0:
            click.echo('No matching transactions found.', err=True)
    finally:
        repo.close()
