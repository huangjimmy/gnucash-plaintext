"""Q-018: `cash_basis: true` invoice KVP for cash-basis tax filing.

The KVP is purely descriptive — it labels the issuer's tax-method intent.
The format and importer already support every required mechanic (Q-016
retarget for same-day post + pay, KVP path for arbitrary custom metadata).
Q-018 blesses the canonical name and pins the round-trip via these tests.
"""
import re
from pathlib import Path

import gnucash.gnucash_core_c as gc
from click.testing import CliRunner

from cli.main import cli
from infrastructure.gnucash.utils import wrap_invoice_or_bill
from tests.integration.rendered_page import is_in_progress

FIXTURES = Path('tests/fixtures')
ACCOUNTS = str(FIXTURES / 'q018_accounts.txt')


def _fx(name):
    return (FIXTURES / name).read_text()


def _bank_tx_handles(gnc, amount):
    """Return (tx_guid, ar_side_split_guid) for the bank tx of the given
    amount."""
    from repositories.gnucash_repository import GnuCashRepository
    repo = GnuCashRepository(str(gnc))
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
        for sp in bank.GetSplitList():
            if abs(sp.GetAmount().to_double() - amount) < 0.01:
                tx = sp.GetParent()
                ar_sg = None
                for i in range(tx.CountSplits()):
                    s = tx.GetSplit(i)
                    if s.GetAccount().get_full_name() == 'Assets.Accounts Receivable':
                        ar_sg = s.GetGUID().to_string()
                return tx.GetGUID().to_string(), ar_sg
        return None, None
    finally:
        repo.close()


def _invoice_state(gnc, inv_id):
    """Snapshot the relevant book state for an invoice."""
    from gnucash import GncLot, Query, Split
    from gnucash.gnucash_business import Invoice as BizInvoice

    from infrastructure.gnucash.kvp import get_custom_metadata
    from repositories.gnucash_repository import GnuCashRepository
    repo = GnuCashRepository(str(gnc))
    repo.open()
    try:
        book = repo.book
        q = Query()
        q.search_for('gncInvoice')
        q.set_book(book)
        inv = next(
            (i for r in q.run() for i in [wrap_invoice_or_bill(r)]
             if i.GetID() == inv_id),
            None,
        )
        q.destroy()
        if inv is None:
            return None

        ar_lot_state = None
        if inv.GetPostedLot() is not None:
            lot = inv.GetPostedLot()
            members = sorted(
                round(Split(instance=m).GetAmount().to_double(), 2)
                for m in lot.get_split_list()
            )
            ar_lot_state = {
                'closed': lot.is_closed(),
                'balance': round(lot.get_balance().to_double(), 2),
                'members': members,
            }
        return {
            'is_posted': inv.GetPostedTxn() is not None,
            'is_paid': bool(gc.gncInvoiceIsPaid(inv.instance)),
            'kvp': get_custom_metadata(inv),
            'lot': ar_lot_state,
        }
    finally:
        repo.close()


def _bank_tx_count(gnc):
    from repositories.gnucash_repository import GnuCashRepository
    repo = GnuCashRepository(str(gnc))
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
        return len({sp.GetParent().GetGUID().to_string()
                    for sp in (bank.GetSplitList() if bank else [])})
    finally:
        repo.close()


def _build_paid_book(runner, tmp_path):
    """Build a book with the cash-basis paid invoice (used by multiple tests)."""
    gnc = tmp_path / 'book.gnucash'
    r = runner.invoke(cli, ['import', '--new', str(gnc), ACCOUNTS])
    assert r.exit_code == 0, f'accounts: {r.output}'

    bank_path = tmp_path / 'bank.txt'
    bank_path.write_text(_fx('q018_cash_bank.txt'))
    r = runner.invoke(cli, ['import', str(gnc), str(bank_path)])
    assert r.exit_code == 0, f'bank: {r.output}'

    tx_guid, ar_sg = _bank_tx_handles(gnc, 113.0)
    inv_path = tmp_path / 'invoice.txt'
    inv_path.write_text(
        _fx('q018_cash_invoice.txt').format(
            txn_guid=tx_guid, txn_split_guid=ar_sg,
        )
    )
    r = runner.invoke(cli, ['import', str(gnc), str(inv_path),
                            '--include-business-objects'])
    assert r.exit_code == 0, f'invoice: {r.output}'
    return gnc


def test_same_date_post_pay_via_retarget_produces_paid_invoice(tmp_path):
    """Same-day post + Q-016-retargeted payment closes the invoice
    cleanly: posted + paid in GnuCash's terms, AR lot balanced and
    closed, single bank tx preserved (no duplicate)."""
    gnc = _build_paid_book(CliRunner(), tmp_path)
    state = _invoice_state(gnc, 'INV-Q18-CASH-100')

    assert state is not None
    assert state['is_posted'], 'invoice must be GnuCash-posted'
    assert state['is_paid'], 'gncInvoiceIsPaid must return True'
    assert state['lot']['closed']
    assert state['lot']['balance'] == 0.0
    assert sorted(state['lot']['members']) == [-113.0, 113.0]
    assert _bank_tx_count(gnc) == 1, (
        'Q-016 retarget must reuse the existing bank tx — no duplicate'
    )


def test_cash_basis_kvp_roundtrips(tmp_path):
    """The `cash_basis: true` line lands on the invoice as a custom KVP
    slot, survives re-import into a fresh book, and is re-emitted by
    `export --include-business-objects`."""
    runner = CliRunner()
    gnc = _build_paid_book(runner, tmp_path)

    state = _invoice_state(gnc, 'INV-Q18-CASH-100')
    assert state['kvp'].get('cash_basis') == 'true', (
        f'cash_basis flag must persist as KVP slot; got kvp={state["kvp"]}'
    )

    exported = tmp_path / 'exported.txt'
    r = runner.invoke(cli, ['export', str(gnc), str(exported),
                            '--include-business-objects'])
    assert r.exit_code == 0
    assert 'cash_basis: "true"' in exported.read_text(), (
        'exporter must re-emit cash_basis on the invoice block'
    )

    gnc_fresh = tmp_path / 'fresh.gnucash'
    r = runner.invoke(cli, ['import', '--new', str(gnc_fresh),
                            str(exported), '--include-business-objects'])
    assert r.exit_code == 0, f'fresh re-import: {r.output}'
    fresh_state = _invoice_state(gnc_fresh, 'INV-Q18-CASH-100')
    assert fresh_state['kvp'].get('cash_basis') == 'true', (
        'flag must survive fresh-book re-import'
    )


def test_cash_basis_with_partial_payment_is_allowed(tmp_path):
    """Cash-basis filers commonly receive partial / installment payments.
    The flag is descriptive, not structural — it must coexist with an
    open AR balance from partial payment without any importer complaint."""
    runner = CliRunner()
    gnc = tmp_path / 'book.gnucash'
    r = runner.invoke(cli, ['import', '--new', str(gnc), ACCOUNTS])
    assert r.exit_code == 0, f'accounts: {r.output}'

    bank_path = tmp_path / 'bank.txt'
    bank_path.write_text(_fx('q018_partial_bank.txt'))
    r = runner.invoke(cli, ['import', str(gnc), str(bank_path)])
    assert r.exit_code == 0

    tx_guid, ar_sg = _bank_tx_handles(gnc, 50.0)
    inv_path = tmp_path / 'invoice.txt'
    inv_path.write_text(
        _fx('q018_partial_invoice.txt').format(
            txn_guid=tx_guid, txn_split_guid=ar_sg,
        )
    )
    r = runner.invoke(cli, ['import', str(gnc), str(inv_path),
                            '--include-business-objects'])
    assert r.exit_code == 0, (
        f'partial-payment + cash_basis must NOT be rejected; got:\n{r.output}'
    )

    state = _invoice_state(gnc, 'INV-Q18-PARTIAL-200')
    assert state['kvp'].get('cash_basis') == 'true'
    assert state['is_posted']
    assert not state['is_paid'], 'invoice is partially paid, not fully paid'
    assert state['lot']['balance'] == 150.0, (
        f'remaining AR balance should be $200 invoice - $50 paid = $150; '
        f'got {state["lot"]["balance"]}'
    )
    assert not state['lot']['closed']


def _strip_nondeterministic(html_text):
    """Remove GUIDs and dates that change run-to-run so two renderings
    of the 'same' invoice can be compared byte-by-byte."""
    # 32-hex GUIDs (uppercase or lowercase)
    out = re.sub(r'[0-9a-fA-F]{32}', 'GUID', html_text)
    return out


def test_cash_basis_flag_does_not_appear_in_pdf_or_html(tmp_path):
    """Customer-facing rendering (HTML / PDF) must NOT expose the
    issuer's tax-method classification. The HTML output for the
    flag-bearing invoice should be byte-identical to the same invoice
    rendered without the flag (modulo GUIDs which differ per import)."""
    from services.invoice_renderer import render_to_html

    runner = CliRunner()
    # Book A: invoice WITH the flag
    gnc_a = _build_paid_book(runner, tmp_path)

    # Book B: invoice WITHOUT the flag (identical content otherwise)
    gnc_b = tmp_path / 'book_b.gnucash'
    r = runner.invoke(cli, ['import', '--new', str(gnc_b), ACCOUNTS])
    assert r.exit_code == 0
    bank_path_b = tmp_path / 'bank_b.txt'
    bank_path_b.write_text(_fx('q018_cash_bank.txt'))
    r = runner.invoke(cli, ['import', str(gnc_b), str(bank_path_b)])
    assert r.exit_code == 0
    tx_guid_b, ar_sg_b = _bank_tx_handles(gnc_b, 113.0)
    inv_path_b = tmp_path / 'invoice_b.txt'
    inv_path_b.write_text(
        _fx('q018_cash_invoice_no_flag.txt').format(
            txn_guid=tx_guid_b, txn_split_guid=ar_sg_b,
        )
    )
    r = runner.invoke(cli, ['import', str(gnc_b), str(inv_path_b),
                            '--include-business-objects'])
    assert r.exit_code == 0

    def _render(gnc):
        from gnucash import Query
        from gnucash.gnucash_business import Invoice as BizInvoice

        from repositories.gnucash_repository import GnuCashRepository
        repo = GnuCashRepository(str(gnc))
        repo.open()
        try:
            q = Query()
            q.search_for('gncInvoice')
            q.set_book(repo.book)
            inv = next(
                (i for r in q.run() for i in [wrap_invoice_or_bill(r)]
                 if i.GetID() == 'INV-Q18-CASH-100'),
                None,
            )
            q.destroy()
            return render_to_html(inv, repo.session)
        finally:
            repo.close()

    html_with_flag = _strip_nondeterministic(_render(gnc_a))
    html_without_flag = _strip_nondeterministic(_render(gnc_b))

    assert html_with_flag == html_without_flag, (
        'Customer-facing HTML must not differ based on the issuer\'s '
        'tax-method classification.\n'
        '=== with flag ===\n' + html_with_flag + '\n'
        '=== without flag ===\n' + html_without_flag
    )
    # And the flag's literal name must not appear anywhere in the
    # customer-facing render.
    assert 'cash_basis' not in html_with_flag.lower(), (
        'Rendered HTML must not contain the literal string "cash_basis"'
    )


# ── Unposted-render path (cash_basis: true on an invoice awaiting cash) ──

def _render_invoice(gnc, invoice_id):
    """Helper: render the named invoice as GnuCash draws it and
    return the HTML string."""
    from gnucash import Query
    from gnucash.gnucash_business import Invoice as BizInvoice

    from repositories.gnucash_repository import GnuCashRepository
    from services.invoice_renderer import render_to_html

    repo = GnuCashRepository(str(gnc))
    repo.open()
    try:
        q = Query()
        q.search_for('gncInvoice')
        q.set_book(repo.book)
        inv = next(
            (i for r in q.run() for i in [wrap_invoice_or_bill(r)]
             if i.GetID() == invoice_id),
            None,
        )
        q.destroy()
        assert inv is not None, f'invoice {invoice_id!r} not found'
        return render_to_html(inv, repo.session)
    finally:
        repo.close()


def _import_into_fresh_book(runner, tmp_path, fixture_name):
    gnc = tmp_path / 'book.gnucash'
    r = runner.invoke(cli, ['import', '--new', str(gnc), ACCOUNTS])
    assert r.exit_code == 0, f'accounts: {r.output}'
    fx_path = tmp_path / fixture_name
    fx_path.write_text(_fx(fixture_name))
    r = runner.invoke(cli, ['import', str(gnc), str(fx_path),
                            '--include-business-objects'])
    assert r.exit_code == 0, f'{fixture_name}: {r.output}'
    return gnc


def test_a_cash_basis_invoice_is_drawn_like_any_other_unposted_one(tmp_path):
    """`cash_basis: true` is the issuer's tax classification, and GnuCash's
    page has no notion of it: an unposted invoice is priced from its entries
    and marked in progress, whether the flag is there or not.

    Its dates come from the posting, so an unposted invoice carries none —
    the `due_date:` key still round-trips through the format, and no longer
    reaches the printed page.
    """
    runner = CliRunner()
    gnc = _import_into_fresh_book(
        runner, tmp_path, 'q018_unposted_cash_with_due.txt'
    )
    html = _render_invoice(gnc, 'INV-Q18-UNPOSTED-WITH-DUE')

    assert is_in_progress(html), html
    assert 'Due Date' not in html, html
    # And the key itself stays out of a customer-facing page.
    assert 'cash_basis' not in html.lower()


def test_an_invoice_without_the_flag_is_drawn_the_same_way(tmp_path):
    """The other half of the pair: with no `cash_basis:` key at all, an
    unposted invoice is drawn exactly as the one above is. That the two
    pages agree is the point — the flag is private to the issuer."""
    runner = CliRunner()
    gnc = _import_into_fresh_book(
        runner, tmp_path, 'q018_unposted_draft_no_flag.txt'
    )
    html = _render_invoice(gnc, 'INV-Q18-DRAFT')

    assert is_in_progress(html), html
    assert 'cash_basis' not in html.lower()
