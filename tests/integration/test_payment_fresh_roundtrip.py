"""Q-016: payment txs (single retarget and multi-invoice shared) roundtrip
into a FRESH book — same GUIDs, same lot structure, no duplicates.

Tests assert the end-state of: build source book → export → import the
exported plaintext into a brand-new empty book → semantic state should
match the source.

These tests fail today (Q-016 not yet implemented) and are the seed for
the Q-016 work:

* `test_single_invoice_txn_guid_fresh_roundtrip` — gap #1: invoice
  retargeted to a pre-existing bank tx via `txn_guid:` doesn't survive
  export → fresh-book reimport today (exporter drops `txn_guid:`, no
  import-order guarantee).

* (further tests added as the implementation lands.)
"""
from pathlib import Path

from click.testing import CliRunner

from cli.main import cli

FIXTURES = Path('tests/fixtures')
ACCOUNTS = 'tests/fixtures/q016_single_retarget_accounts.txt'


def _fx(name):
    return (FIXTURES / name).read_text()


def _setup_source_book(runner, tmp_path):
    """Create the source book: accounts + pre-existing bank tx + invoice
    using `txn_guid:` retarget to link to that bank tx."""
    gf = tmp_path / 'src.gnucash'
    r = runner.invoke(cli, ['import', '--new', str(gf), ACCOUNTS])
    assert r.exit_code == 0, f'accounts: {r.output}'

    bank_path = tmp_path / 'bank.txt'
    bank_path.write_text(_fx('q016_single_retarget_bank.txt'))
    r = runner.invoke(cli, ['import', str(gf), str(bank_path)])
    assert r.exit_code == 0, f'bank: {r.output}'

    # Pin the bank tx guid for substitution into the invoice fixture
    bank_guid = _bank_tx_guid(gf, 100.0)
    assert bank_guid is not None

    inv_text = _fx('q016_single_retarget_invoice.txt').replace(
        '{txn_guid}', bank_guid
    )
    inv_path = tmp_path / 'invoice.txt'
    inv_path.write_text(inv_text)
    r = runner.invoke(cli, ['import', str(gf), str(inv_path),
                            '--include-business-objects'])
    assert r.exit_code == 0, f'invoice: {r.output}'
    return gf, bank_guid


def _bank_tx_guid(gf, amount, bank='Assets.Bank'):
    from repositories.gnucash_repository import GnuCashRepository
    repo = GnuCashRepository(str(gf))
    repo.open()
    try:
        def find(a, n):
            if a.get_full_name() == n:
                return a
            for c in a.get_children():
                r = find(c, n)
                if r:
                    return r
            return None
        b = find(repo.book.get_root_account(), bank)
        for sp in b.GetSplitList():
            if abs(sp.GetAmount().to_double() - amount) < 0.01:
                return sp.GetParent().GetGUID().to_string()
        return None
    finally:
        repo.close()


def _semantic_state(gf):
    """Bank tx GUIDs + amounts + AR lot count + balances + lot members
    (split amounts, sorted). Comparable across two books — split GUIDs
    must be IDENTICAL for the roundtrip to be considered preserving."""
    from gnucash import GncLot, Split

    from repositories.gnucash_repository import GnuCashRepository
    repo = GnuCashRepository(str(gf))
    repo.open()
    try:
        def find(a, n):
            if a.get_full_name() == n:
                return a
            for c in a.get_children():
                r = find(c, n)
                if r:
                    return r
            return None

        bank = find(repo.book.get_root_account(), 'Assets.Bank')
        bank_txs = sorted(
            (sp.GetParent().GetGUID().to_string(),
             round(sp.GetAmount().to_double(), 2))
            for sp in (bank.GetSplitList() if bank is not None else [])
        )

        ar = find(repo.book.get_root_account(), 'Assets.Accounts Receivable')
        seen, lots = set(), []
        ar_splits = ar.GetSplitList() if ar is not None else []
        for sp in ar_splits:
            raw = sp.GetLot()
            if raw is None or int(raw) in seen:
                continue
            seen.add(int(raw))
            lot = GncLot(instance=raw)
            members = sorted(
                round(Split(instance=m).GetAmount().to_double(), 2)
                for m in lot.get_split_list()
            )
            lots.append({
                'closed': lot.is_closed(),
                'balance': round(lot.get_balance().to_double(), 2),
                'members': members,
            })
        lots.sort(key=lambda d: (d['closed'], d['balance'], d['members']))
        return {'bank_txs': bank_txs, 'ar_lots': lots}
    finally:
        repo.close()


def _bank_tx_splits(gf, amount):
    """Find the bank tx by amount, return [(split_guid, amount, account)]."""
    from repositories.gnucash_repository import GnuCashRepository
    repo = GnuCashRepository(str(gf))
    repo.open()
    try:
        def find(a, n):
            if a.get_full_name() == n:
                return a
            for c in a.get_children():
                r = find(c, n)
                if r:
                    return r
            return None
        bank = find(repo.book.get_root_account(), 'Assets.Bank')
        tx = None
        for sp in bank.GetSplitList():
            if abs(sp.GetAmount().to_double() - amount) < 0.01:
                tx = sp.GetParent()
                break
        if tx is None:
            return None
        out = []
        for i in range(tx.CountSplits()):
            sp = tx.GetSplit(i)
            out.append((
                sp.GetGUID().to_string(),
                sp.GetAmount().to_double(),
                sp.GetAccount().get_full_name(),
            ))
        return tx.GetGUID().to_string(), out
    finally:
        repo.close()


def test_multi_invoice_one_payment_fresh_roundtrip(tmp_path):
    """3 invoices ($100, $120, $180) all closed by 1 bank tx ($400).
    The bank tx has 4 splits — bank +$400 plus 3 AR splits, each routed
    to its own invoice's lot via `txn_split_guid:`. After export →
    fresh-book reimport: exactly 1 bank tx (preserved GUID), 3 closed
    AR lots with their original split membership."""
    runner = CliRunner()

    # Build source: accounts → pre-existing $400 bank tx (with 3 AR
    # splits) → invoices that each claim one of those AR splits.
    gf_src = tmp_path / 'src.gnucash'
    r = runner.invoke(cli, ['import', '--new', str(gf_src), ACCOUNTS])
    assert r.exit_code == 0, f'accounts: {r.output}'

    bank_path = tmp_path / 'bank.txt'
    bank_path.write_text(_fx('q016_multi_invoice_bank.txt'))
    r = runner.invoke(cli, ['import', str(gf_src), str(bank_path)])
    assert r.exit_code == 0, f'multi bank: {r.output}'

    bank_txn_guid, splits = _bank_tx_splits(gf_src, 400.0)
    by_acct_amt = {(acct, amt): sg for sg, amt, acct in splits}
    split_guid_a = by_acct_amt[('Assets.Accounts Receivable',-100.0)]
    split_guid_b = by_acct_amt[('Assets.Accounts Receivable',-120.0)]
    split_guid_c = by_acct_amt[('Assets.Accounts Receivable',-180.0)]

    invoices_text = _fx('q016_multi_invoice_invoices.txt').format(
        bank_txn_guid=bank_txn_guid,
        split_guid_a=split_guid_a,
        split_guid_b=split_guid_b,
        split_guid_c=split_guid_c,
    )
    inv_path = tmp_path / 'invoices.txt'
    inv_path.write_text(invoices_text)
    r = runner.invoke(cli, ['import', str(gf_src), str(inv_path),
                            '--include-business-objects'])
    assert r.exit_code == 0, f'multi-invoice link: {r.output}'

    src_state = _semantic_state(gf_src)
    src_bank_txs = src_state['bank_txs']
    assert len(src_bank_txs) == 1, (
        f'source must have 1 bank tx (the $400 wire). got {len(src_bank_txs)}'
    )
    closed_lots = [lot for lot in src_state['ar_lots'] if lot['closed']]
    assert len(closed_lots) == 3, (
        f'source must have 3 closed AR lots (one per invoice). got {src_state["ar_lots"]}'
    )

    # Export and re-import into FRESH book
    exported_path = tmp_path / 'exported.txt'
    r = runner.invoke(cli, ['export', str(gf_src), str(exported_path),
                            '--include-business-objects'])
    assert r.exit_code == 0, f'export: {r.output}'

    gf_dst = tmp_path / 'dst.gnucash'
    r = runner.invoke(cli, ['import', '--new', str(gf_dst), str(exported_path),
                            '--include-business-objects'])
    assert r.exit_code == 0, f'fresh re-import: {r.output}'

    dst_state = _semantic_state(gf_dst)

    assert dst_state['bank_txs'] == src_state['bank_txs'], (
        f'bank tx GUID must roundtrip exactly (one tx, not three).\n'
        f'  source: {src_state["bank_txs"]}\n'
        f'  fresh:  {dst_state["bank_txs"]}'
    )
    assert dst_state['ar_lots'] == src_state['ar_lots'], (
        f'AR lot structure must roundtrip exactly.\n'
        f'  source: {src_state["ar_lots"]}\n'
        f'  fresh:  {dst_state["ar_lots"]}'
    )


def _ap_lot_state(gf):
    """AP lot semantic state — sister of _semantic_state but for the AP side
    (bills). Used by the multi-bill test."""
    from gnucash import GncLot, Split

    from repositories.gnucash_repository import GnuCashRepository
    repo = GnuCashRepository(str(gf))
    repo.open()
    try:
        def find(a, n):
            if a.get_full_name() == n:
                return a
            for c in a.get_children():
                r = find(c, n)
                if r:
                    return r
            return None
        ap = find(repo.book.get_root_account(), 'Liabilities.Accounts Payable')
        seen, lots = set(), []
        for sp in ap.GetSplitList():
            raw = sp.GetLot()
            if raw is None or int(raw) in seen:
                continue
            seen.add(int(raw))
            lot = GncLot(instance=raw)
            members = sorted(
                round(Split(instance=m).GetAmount().to_double(), 2)
                for m in lot.get_split_list()
            )
            lots.append({
                'closed': lot.is_closed(),
                'balance': round(lot.get_balance().to_double(), 2),
                'members': members,
            })
        lots.sort(key=lambda d: (d['closed'], d['balance'], d['members']))
        return lots
    finally:
        repo.close()


def test_multi_bill_one_payment_fresh_roundtrip(tmp_path):
    """3 bills ($90, $110, $160) all closed by 1 outgoing bank tx ($360).
    Symmetric to the multi-invoice test on the AP side. After export →
    fresh-book reimport: 1 bank tx (same GUID), 3 closed AP lots with
    the right split routing."""
    runner = CliRunner()
    gf_src = tmp_path / 'src.gnucash'
    r = runner.invoke(cli, ['import', '--new', str(gf_src), ACCOUNTS])
    assert r.exit_code == 0, f'accounts: {r.output}'

    bank_path = tmp_path / 'bank.txt'
    bank_path.write_text(_fx('q016_multi_bill_bank.txt'))
    r = runner.invoke(cli, ['import', str(gf_src), str(bank_path)])
    assert r.exit_code == 0, f'multi-bill bank: {r.output}'

    bank_txn_guid, splits = _bank_tx_splits(gf_src, -360.0)
    by_acct_amt = {(acct, amt): sg for sg, amt, acct in splits}
    split_guid_a = by_acct_amt[('Liabilities.Accounts Payable', 90.0)]
    split_guid_b = by_acct_amt[('Liabilities.Accounts Payable', 110.0)]
    split_guid_c = by_acct_amt[('Liabilities.Accounts Payable', 160.0)]

    bills_text = _fx('q016_multi_bill_bills.txt').format(
        bank_txn_guid=bank_txn_guid,
        split_guid_a=split_guid_a,
        split_guid_b=split_guid_b,
        split_guid_c=split_guid_c,
    )
    bills_path = tmp_path / 'bills.txt'
    bills_path.write_text(bills_text)
    r = runner.invoke(cli, ['import', str(gf_src), str(bills_path),
                            '--include-business-objects'])
    assert r.exit_code == 0, f'bills: {r.output}'

    src_bank = _semantic_state(gf_src)['bank_txs']
    src_ap = _ap_lot_state(gf_src)
    assert len(src_bank) == 1
    closed_ap = [lot for lot in src_ap if lot['closed']]
    assert len(closed_ap) == 3, f'source must have 3 closed AP lots, got: {src_ap}'

    exported_path = tmp_path / 'exported.txt'
    r = runner.invoke(cli, ['export', str(gf_src), str(exported_path),
                            '--include-business-objects'])
    assert r.exit_code == 0, f'export: {r.output}'

    gf_dst = tmp_path / 'dst.gnucash'
    r = runner.invoke(cli, ['import', '--new', str(gf_dst), str(exported_path),
                            '--include-business-objects'])
    assert r.exit_code == 0, f'fresh re-import: {r.output}'

    dst_bank = _semantic_state(gf_dst)['bank_txs']
    dst_ap = _ap_lot_state(gf_dst)
    assert dst_bank == src_bank, (
        f'bill multi-payment bank tx GUID must roundtrip exactly.\n'
        f'  source: {src_bank}\n  fresh:  {dst_bank}'
    )
    assert dst_ap == src_ap, (
        f'AP lot structure must roundtrip exactly.\n'
        f'  source: {src_ap}\n  fresh:  {dst_ap}'
    )


def test_two_invoices_same_amount_disambiguated_by_split_guid(tmp_path):
    """Two invoices for $200 each paid by one $400 bank tx with two -$200
    AR splits. The amounts are ambiguous (iterative retarget couldn't tell
    which split goes where); per-split GUIDs are what makes the routing
    deterministic. Roundtrip must preserve the right split for each
    invoice's lot."""
    runner = CliRunner()
    gf_src = tmp_path / 'src.gnucash'
    r = runner.invoke(cli, ['import', '--new', str(gf_src), ACCOUNTS])
    assert r.exit_code == 0

    bank_path = tmp_path / 'bank.txt'
    bank_path.write_text(_fx('q016_same_amount_bank.txt'))
    r = runner.invoke(cli, ['import', str(gf_src), str(bank_path)])
    assert r.exit_code == 0, f'same-amount bank: {r.output}'

    bank_txn_guid, splits = _bank_tx_splits(gf_src, 400.0)
    # Both AR splits are -$200; differentiate by memo so we can pin
    # which guid goes to which invoice deterministically.
    ar_splits_by_memo = {}
    from repositories.gnucash_repository import GnuCashRepository
    repo = GnuCashRepository(str(gf_src))
    repo.open()
    try:
        from services.gnucash_importer import _find_transaction_by_guid
        tx = _find_transaction_by_guid(repo.book, bank_txn_guid)
        for i in range(tx.CountSplits()):
            sp = tx.GetSplit(i)
            if sp.GetAccount().get_full_name() == 'Assets.Accounts Receivable':
                ar_splits_by_memo[sp.GetMemo()] = sp.GetGUID().to_string()
    finally:
        repo.close()
    split_guid_x = ar_splits_by_memo['Portion for INV-Q16-SAME-X-200']
    split_guid_y = ar_splits_by_memo['Portion for INV-Q16-SAME-Y-200']
    assert split_guid_x != split_guid_y

    invoices_text = _fx('q016_same_amount_invoices.txt').format(
        bank_txn_guid=bank_txn_guid,
        split_guid_x=split_guid_x,
        split_guid_y=split_guid_y,
    )
    inv_path = tmp_path / 'invoices.txt'
    inv_path.write_text(invoices_text)
    r = runner.invoke(cli, ['import', str(gf_src), str(inv_path),
                            '--include-business-objects'])
    assert r.exit_code == 0, f'same-amount invoices: {r.output}'

    # Source: 1 bank tx, 2 closed AR lots, each with [+200 posting, -200 payment]
    src = _semantic_state(gf_src)
    assert len(src['bank_txs']) == 1
    closed = [lot for lot in src['ar_lots'] if lot['closed']]
    assert len(closed) == 2

    # Roundtrip
    exported = tmp_path / 'exported.txt'
    r = runner.invoke(cli, ['export', str(gf_src), str(exported),
                            '--include-business-objects'])
    assert r.exit_code == 0
    gf_dst = tmp_path / 'dst.gnucash'
    r = runner.invoke(cli, ['import', '--new', str(gf_dst), str(exported),
                            '--include-business-objects'])
    assert r.exit_code == 0, f'fresh re-import: {r.output}'

    dst = _semantic_state(gf_dst)
    assert dst['bank_txs'] == src['bank_txs']
    assert dst['ar_lots'] == src['ar_lots']


def test_mix_retarget_and_apply_payment_fresh_roundtrip(tmp_path):
    """A book with BOTH shapes: one invoice uses `txn_guid:` retarget
    to a pre-existing bank tx; another invoice uses ApplyPayment (no
    `txn_guid:`) so a fresh bank tx is auto-created. After export →
    fresh-book reimport, both bank txs survive with their original
    GUIDs and both invoice lots close exactly as in the source."""
    runner = CliRunner()
    gf_src = tmp_path / 'src.gnucash'
    r = runner.invoke(cli, ['import', '--new', str(gf_src), ACCOUNTS])
    assert r.exit_code == 0

    # Pre-create the retarget-side bank tx.
    bank_path = tmp_path / 'bank.txt'
    bank_path.write_text(_fx('q016_mix_bank.txt'))
    r = runner.invoke(cli, ['import', str(gf_src), str(bank_path)])
    assert r.exit_code == 0, f'mix bank: {r.output}'
    retarget_txn_guid, splits = _bank_tx_splits(gf_src, 90.0)
    by_acct_amt = {(acct, amt): sg for sg, amt, acct in splits}
    retarget_split_guid = by_acct_amt[('Assets.Accounts Receivable', -90.0)]

    invoices_text = _fx('q016_mix_invoices.txt').format(
        retarget_txn_guid=retarget_txn_guid,
        retarget_split_guid=retarget_split_guid,
    )
    inv_path = tmp_path / 'invoices.txt'
    inv_path.write_text(invoices_text)
    r = runner.invoke(cli, ['import', str(gf_src), str(inv_path),
                            '--include-business-objects'])
    assert r.exit_code == 0, f'mix invoices: {r.output}'

    src = _semantic_state(gf_src)
    assert len(src['bank_txs']) == 2, (
        f'source must have 2 bank txs (retarget + ApplyPayment-created). '
        f'got: {src["bank_txs"]}'
    )
    closed = [lot for lot in src['ar_lots'] if lot['closed']]
    assert len(closed) == 2

    # Roundtrip into fresh book
    exported = tmp_path / 'exported.txt'
    r = runner.invoke(cli, ['export', str(gf_src), str(exported),
                            '--include-business-objects'])
    assert r.exit_code == 0
    gf_dst = tmp_path / 'dst.gnucash'
    r = runner.invoke(cli, ['import', '--new', str(gf_dst), str(exported),
                            '--include-business-objects'])
    assert r.exit_code == 0, f'fresh re-import: {r.output}'

    dst = _semantic_state(gf_dst)
    assert dst['bank_txs'] == src['bank_txs'], (
        f'both bank txs (retarget + ApplyPayment) must roundtrip with same '
        f'GUIDs.\n  source: {src["bank_txs"]}\n  fresh:  {dst["bank_txs"]}'
    )
    assert dst['ar_lots'] == src['ar_lots'], (
        f'mix-scenario lot structure must roundtrip exactly.\n'
        f'  source: {src["ar_lots"]}\n  fresh:  {dst["ar_lots"]}'
    )


def test_overpayment_with_retarget_fresh_roundtrip(tmp_path):
    """Q-015 `prepayment:` + Q-016 `txn_guid:` interaction: a $100
    invoice is paid via a retargeted $140 bank tx (overpayment 40).
    The retarget mechanic must split the counter-split into invoice
    portion + prepay residual, and the resulting prepay lot must
    survive export → fresh-book roundtrip."""
    runner = CliRunner()
    gf_src = tmp_path / 'src.gnucash'
    r = runner.invoke(cli, ['import', '--new', str(gf_src), ACCOUNTS])
    assert r.exit_code == 0

    bank_path = tmp_path / 'bank.txt'
    bank_path.write_text(_fx('q016_over_retarget_bank.txt'))
    r = runner.invoke(cli, ['import', str(gf_src), str(bank_path)])
    assert r.exit_code == 0, f'over-retarget bank: {r.output}'
    retarget_txn_guid = _bank_tx_guid(gf_src, 140.0)

    inv_text = _fx('q016_over_retarget_invoice.txt').format(
        retarget_txn_guid=retarget_txn_guid
    )
    inv_path = tmp_path / 'invoice.txt'
    inv_path.write_text(inv_text)
    r = runner.invoke(cli, ['import', str(gf_src), str(inv_path),
                            '--include-business-objects'])
    assert r.exit_code == 0, f'over-retarget invoice: {r.output}'

    src = _semantic_state(gf_src)
    assert len(src['bank_txs']) == 1, (
        f'source must have 1 bank tx (no duplication via retarget). '
        f'got: {src["bank_txs"]}'
    )
    # Expect 2 AR lots: invoice (closed at 0) + prepay (open at -40)
    closed = [lot for lot in src['ar_lots'] if lot['closed']]
    open_ = [lot for lot in src['ar_lots'] if not lot['closed']]
    assert len(closed) == 1 and closed[0]['balance'] == 0.0
    assert len(open_) == 1 and open_[0]['balance'] == -40.0, (
        f'prepay lot residual must be -$40. got open: {open_}'
    )

    exported = tmp_path / 'exported.txt'
    r = runner.invoke(cli, ['export', str(gf_src), str(exported),
                            '--include-business-objects'])
    assert r.exit_code == 0
    gf_dst = tmp_path / 'dst.gnucash'
    r = runner.invoke(cli, ['import', '--new', str(gf_dst), str(exported),
                            '--include-business-objects'])
    assert r.exit_code == 0, f'fresh re-import: {r.output}'

    dst = _semantic_state(gf_dst)
    assert dst['bank_txs'] == src['bank_txs'], (
        f'overpayment retarget bank tx GUID must roundtrip.\n'
        f'  source: {src["bank_txs"]}\n  fresh:  {dst["bank_txs"]}'
    )
    assert dst['ar_lots'] == src['ar_lots'], (
        f'overpayment retarget lot structure (invoice closed + prepay -40) '
        f'must roundtrip exactly.\n'
        f'  source: {src["ar_lots"]}\n  fresh:  {dst["ar_lots"]}'
    )


def test_backward_compat_legacy_payment_without_split_guid(tmp_path):
    """A plaintext file written before Q-016 has a `payment:` block with
    no `txn_guid:` and no `txn_split_guid:` (the old ApplyPayment
    shape). The Q-016 importer must still accept it — falling through
    to the existing ApplyPayment path, no error, invoice closes."""
    runner = CliRunner()
    gf = tmp_path / 'legacy.gnucash'
    r = runner.invoke(cli, ['import', '--new', str(gf), ACCOUNTS])
    assert r.exit_code == 0

    legacy_path = tmp_path / 'legacy_biz.txt'
    legacy_path.write_text(_fx('q016_backcompat_legacy.txt'))
    r = runner.invoke(cli, ['import', str(gf), str(legacy_path),
                            '--include-business-objects'])
    assert r.exit_code == 0, (
        f'legacy plaintext (no txn_guid / no txn_split_guid) must still '
        f'import via the ApplyPayment fallback. output:\n{r.output}'
    )

    state = _semantic_state(gf)
    # ApplyPayment created the bank tx; invoice lot is closed at 0.
    assert len(state['bank_txs']) == 1, (
        f'legacy import must produce 1 bank tx (ApplyPayment path). '
        f'got: {state["bank_txs"]}'
    )
    closed = [lot for lot in state['ar_lots'] if lot['closed']]
    assert len(closed) == 1, (
        f'legacy invoice lot must close (balance 0). got: {state["ar_lots"]}'
    )


def test_single_invoice_txn_guid_fresh_roundtrip(tmp_path):
    """Build source book: accounts + 1 bank tx + 1 invoice retargeted via
    txn_guid. Export everything. Re-import the exported plaintext into a
    fresh empty book. The fresh book must contain exactly:
      - 1 bank tx (SAME guid as the source book)
      - 1 closed invoice lot with the same balance and member amounts
    No duplicate bank tx, no orphan."""
    runner = CliRunner()
    gf_src, src_bank_guid = _setup_source_book(runner, tmp_path)

    src_state = _semantic_state(gf_src)
    assert len(src_state['bank_txs']) == 1, (
        f'source must have 1 bank tx, got {len(src_state["bank_txs"])}'
    )
    assert src_state['bank_txs'][0][0] == src_bank_guid

    # Export
    exported_path = tmp_path / 'exported.txt'
    r = runner.invoke(cli, ['export', str(gf_src), str(exported_path),
                            '--include-business-objects'])
    assert r.exit_code == 0, f'export: {r.output}'

    # Re-import into FRESH book
    gf_dst = tmp_path / 'dst.gnucash'
    r = runner.invoke(cli, ['import', '--new', str(gf_dst), str(exported_path),
                            '--include-business-objects'])
    assert r.exit_code == 0, f'fresh re-import: {r.output}'

    dst_state = _semantic_state(gf_dst)

    assert dst_state['bank_txs'] == src_state['bank_txs'], (
        f'bank tx GUID + amount must roundtrip exactly.\n'
        f'  source: {src_state["bank_txs"]}\n'
        f'  fresh:  {dst_state["bank_txs"]}'
    )
    assert dst_state['ar_lots'] == src_state['ar_lots'], (
        f'AR lot structure must roundtrip exactly.\n'
        f'  source: {src_state["ar_lots"]}\n'
        f'  fresh:  {dst_state["ar_lots"]}'
    )


def test_retargeting_onto_a_invoice_that_owes_nothing_says_so(tmp_path):
    """A second block claiming a whole bank tx as prepayment is refused.

    The invoice is settled in full by the block above it, so by the time the
    retarget is read there is nothing for it to settle: what it would apply is
    zero, and writing a 0.00 split into the invoice's lot tagged as its
    payment is the state this whole area exists to avoid.

    The refusal has to name the cause. Zero applied is also what a residue
    smaller than the account's smallest unit produces — 0.05 owed on an
    account kept to the tenth — and that one is answered by giving the account
    a finer `commodity_scu:`. Told to do that here, the reader would change
    their account for a reason that has nothing to do with what is wrong: the
    invoice owes nothing at all.
    """
    runner = CliRunner()
    gf = tmp_path / 'src.gnucash'
    assert runner.invoke(cli, ['import', '--new', str(gf), ACCOUNTS]).exit_code == 0

    bank_path = tmp_path / 'bank.txt'
    bank_path.write_text(_fx('q016_over_retarget_bank.txt'))
    assert runner.invoke(cli, ['import', str(gf), str(bank_path)]).exit_code == 0
    retarget_txn_guid = _bank_tx_guid(gf, 140.0)

    inv_path = tmp_path / 'invoice.txt'
    inv_path.write_text(_fx('retarget_onto_an_invoice_owing_nothing.txt').format(
        retarget_txn_guid=retarget_txn_guid))
    result = runner.invoke(cli, ['import', str(gf), str(inv_path),
                                 '--include-business-objects'])

    assert result.exit_code != 0, result.output
    assert 'owes nothing' in result.output, result.output
    assert 'commodity_scu' not in result.output, result.output


def test_two_payments_of_the_same_shape_are_paired_the_only_way_that_works(tmp_path):
    """One block names its transaction, the other describes the same shape.

    Both payments are 50.00 on the same day with the same memo, so the block
    that describes a payment by its fields matches either of them, while the
    block naming a transaction by guid matches only the one it names. There is
    exactly one pairing that works, and taking each split's first match does
    not find it: the described block is claimed by the wrong split, the named
    block is left with a split it cannot match, and a file that made this book
    reads as a change to it.

    What follows a false "changed" is the expensive part — the invoice is
    unposted and rebuilt, its payments orphaned and re-made, and on a
    foreign-currency invoice whose cost basis something measures against, refused
    outright.
    """
    runner = CliRunner()
    gf = tmp_path / 'src.gnucash'
    assert runner.invoke(cli, ['import', '--new', str(gf), ACCOUNTS]).exit_code == 0

    bank_path = tmp_path / 'bank.txt'
    bank_path.write_text(_fx('two_payments_one_given_one_described_bank.txt'))
    assert runner.invoke(cli, ['import', str(gf), str(bank_path)]).exit_code == 0
    retarget_txn_guid = _bank_tx_guid(gf, 50.0)

    text = _fx('two_payments_one_given_one_described.txt').format(
        retarget_txn_guid=retarget_txn_guid)
    inv_path = tmp_path / 'invoice.txt'
    inv_path.write_text(text)
    first = runner.invoke(cli, ['import', str(gf), str(inv_path),
                                '--include-business-objects'])
    assert first.exit_code == 0, first.output

    # The same file again describes the book exactly, so nothing is touched.
    again = runner.invoke(cli, ['import', str(gf), str(inv_path),
                                '--include-business-objects'])
    assert again.exit_code == 0, again.output
    assert 'orphaned' not in again.output, again.output
