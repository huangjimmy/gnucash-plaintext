"""A `payment:` block's `memo:` is the payment transaction's, not the invoice's.

`ApplyPayment` writes it onto the payment transaction's splits — the bank
split and the A/R or A/P split. Nothing about the invoice or the bill holds
it. So correcting one word of it is a change to a bank transaction, and the
invoice it settled has not moved.

Nothing wrote it at all before. A block naming `txn_guid:` matches its
payment on that guid alone — `_single_payment_matches` returns True there and
reads no further — so a corrected memo left the invoice matching its file:
measured, `invoice "…": unchanged`, `Updated: 0`, "Nothing to import", and
the book still holding the old wording.

Which leaves the other half of it: the invoice has **not** moved, so it must
not be reported as though it had. Correcting a memo is a change to a bank
transaction, counted with the transactions.
"""

from click.testing import CliRunner

from cli.main import cli
from infrastructure.gnucash.utils import get_account_full_name
from repositories.gnucash_repository import GnuCashRepository, SessionMode

LEDGER = """2026-01-01 commodity CAD
\tmnemonic: "CAD"
\tfullname: "Canadian Dollar"
\tnamespace: "CURRENCY"
\tfraction: 100
2026-01-01 open Assets
\ttype: Asset
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Assets:Bank
\ttype: Bank
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Assets:Accounts Receivable
\ttype: Accounts Receivable
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Income
\ttype: Income
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Income:Sales
\ttype: Income
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"

customer "C-MEMO"
\tname: "Memo Ltd"
\tcurrency: CAD

invoice "INV-MEMO-001"
\tcustomer_id: "C-MEMO"
\tcurrency: CAD
\tdate_opened: 2026-02-01
\tentry:
\t\tdate: 2026-02-01
\t\tdescription: "A line"
\t\taccount: "Income:Sales"
\t\tquantity: 1
\t\tprice: 65
\t\ttaxable: false
\t\ttax_included: false
\tposted:
\t\tdate: 2026-02-01
\t\tdue: 2026-03-03
\t\tar_account: "Assets:Accounts Receivable"
\t\tmemo: "INV-MEMO-001"
\t\taccumulate: true
\tpayment:
\t\tdate: 2026-02-10
\t\tamount: 65.00
\t\tbank_account: "Assets:Bank"
\t\tmemo: "Original memo"
"""


#: The same invoice settled by retargeting a bank transaction that was
#: already in the book — the shape a bank feed leaves. Its two splits carry
#: **different** memos, which `_retarget_counter_split_to_lot` preserves
#: deliberately, and only the bank side's is what a `payment:` block states.
RETARGETED = LEDGER.replace("""\tpayment:
\t\tdate: 2026-02-10
\t\tamount: 65.00
\t\tbank_account: "Assets:Bank"
\t\tmemo: "Original memo"
""", """\tpayment:
\t\tdate: 2026-02-10
\t\tamount: 65.00
\t\tbank_account: "Assets:Bank"
\t\ttxn_guid: "aa00aa00aa00aa00aa00aa00aa00aa00"
\t\tmemo: "Original memo"
""") + """
2026-02-10 * "Memo Ltd"
\tguid: "aa00aa00aa00aa00aa00aa00aa00aa00"
\tAssets:Bank 65.00 CAD
\t\tguid: "ee00ee00ee00ee00ee00ee00ee00ee00"
\t\tmemo: "Original memo"
\tAssets:Accounts Receivable -65.00 CAD
\t\tguid: "dd00dd00dd00dd00dd00dd00dd00dd00"
\t\tmemo: "What the bank feed called it"
"""


#: What an earlier release exported for a retargeted payment: the block's
#: `memo:` read off the **bank** split while `txn_split_guid:` names the
#: receivable one, and the two carrying different wordings, which a retarget
#: preserves deliberately. The two halves of such a file say different
#: things about one split.
LEGACY_EXPORT = LEDGER.replace("""\tpayment:
\t\tdate: 2026-02-10
\t\tamount: 65.00
\t\tbank_account: "Assets:Bank"
\t\tmemo: "Original memo"
""", """\tpayment:
\t\tdate: 2026-02-10
\t\tamount: 65.00
\t\tbank_account: "Assets:Bank"
\t\ttxn_guid: "aa00aa00aa00aa00aa00aa00aa00aa00"
\t\ttxn_split_guid: "dd00dd00dd00dd00dd00dd00dd00dd00"
\t\tmemo: "ACME WIRE 0042"
""") + """
2026-02-10 * "Memo Ltd"
\tguid: "aa00aa00aa00aa00aa00aa00aa00aa00"
\tAssets:Bank 65.00 CAD
\t\tguid: "ee00ee00ee00ee00ee00ee00ee00ee00"
\t\tmemo: "ACME WIRE 0042"
\tAssets:Accounts Receivable -65.00 CAD
\t\tguid: "dd00dd00dd00dd00dd00dd00dd00dd00"
\t\tmemo: "What the bank feed called it"
"""

#: The invoice unpaid, and a bank transaction already in the book under its
#: own wording — what a bank feed leaves. The payment block that settles it
#: is appended by `ADDS_A_PAYMENT` below.
BEFORE_THE_PAYMENT = LEDGER.replace("""\tpayment:
\t\tdate: 2026-02-10
\t\tamount: 65.00
\t\tbank_account: "Assets:Bank"
\t\tmemo: "Original memo"
""", '\tpayment: none\n') + """
2026-02-10 * "Memo Ltd"
\tguid: "aa00aa00aa00aa00aa00aa00aa00aa00"
\tAssets:Bank 65.00 CAD
\t\tmemo: "ACH 0091"
\tAssets:Accounts Receivable -65.00 CAD
\t\tmemo: "ACH 0091"
"""

#: The same ledger with the payment recorded against that transaction, and
#: the wording the file wants for it.
ADDS_A_PAYMENT = BEFORE_THE_PAYMENT.replace('\tpayment: none\n', """\tpayment:
\t\tdate: 2026-02-10
\t\tamount: 65.00
\t\tbank_account: "Assets:Bank"
\t\ttxn_guid: "aa00aa00aa00aa00aa00aa00aa00aa00"
\t\tmemo: "Cheque 118"
""")

#: The same payment with a wire fee taken out of it — a third split, on an
#: account no `payment:` block describes, carrying the same wording as the
#: two that one does.
WITH_A_FEE = LEDGER.replace("""\tpayment:
\t\tdate: 2026-02-10
\t\tamount: 65.00
\t\tbank_account: "Assets:Bank"
\t\tmemo: "Original memo"
""", '\tpayment: none\n').replace(
    '2026-01-01 open Income\n', """2026-01-01 open Expenses
\ttype: Expense
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Expenses:Fees
\ttype: Expense
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Income
""") + """
2026-02-10 * "Memo Ltd"
\tguid: "aa00aa00aa00aa00aa00aa00aa00aa00"
\tAssets:Bank 60.00 CAD
\t\tmemo: "ACH 0091"
\tExpenses:Fees 5.00 CAD
\t\tmemo: "ACH 0091"
\tAssets:Accounts Receivable -65.00 CAD
\t\tguid: "dd00dd00dd00dd00dd00dd00dd00dd00"
\t\tmemo: "ACH 0091"
"""

#: The payment recorded against it, in a file that names the transaction
#: only through the block — so the correction comes from the invoice's
#: half of the format alone, which is how one arrives.
THE_FEE_PAYMENT = LEDGER.replace("""\tpayment:
\t\tdate: 2026-02-10
\t\tamount: 65.00
\t\tbank_account: "Assets:Bank"
\t\tmemo: "Original memo"
""", """\tpayment:
\t\tdate: 2026-02-10
\t\tamount: 65.00
\t\tbank_account: "Assets:Bank"
\t\ttxn_guid: "aa00aa00aa00aa00aa00aa00aa00aa00"
\t\ttxn_split_guid: "dd00dd00dd00dd00dd00dd00dd00dd00"
\t\tmemo: "Cheque 118"
""")

#: The invoice overpaid — one payment of **one** invoice, carrying two
#: receivable splits: the slice in the invoice's lot and the residual that
#: becomes the customer's credit. Its two sides read differently, as a
#: retarget leaves them.
OVERPAID = LEDGER.replace("""\tpayment:
\t\tdate: 2026-02-10
\t\tamount: 65.00
\t\tbank_account: "Assets:Bank"
\t\tmemo: "Original memo"
""", """\tpayment:
\t\tdate: 2026-02-10
\t\tamount: 65.00
\t\tbank_account: "Assets:Bank"
\t\ttxn_guid: "aa00aa00aa00aa00aa00aa00aa00aa00"
\t\tmemo: "ACH 0091"
\t\tprepayment: 35.00
""") + """
2026-02-10 * "Memo Ltd"
\tguid: "aa00aa00aa00aa00aa00aa00aa00aa00"
\tAssets:Bank 100.00 CAD
\t\tguid: "ee00ee00ee00ee00ee00ee00ee00ee00"
\t\tmemo: "ACH 0091"
\tAssets:Accounts Receivable -100.00 CAD
\t\tguid: "dd00dd00dd00dd00dd00dd00dd00dd00"
\t\tmemo: "What the bank feed called it"
"""

#: A deposit made a customer's credit, and an invoice that spends it. The
#: block the export writes for such a payment is `from_credit:`, and its
#: `memo:` is read from the **receivable** split — the one that settled the
#: invoice — not from the bank side an ordinary payment block is written
#: from. The two splits carry different memos here, as a retarget leaves
#: them.
FROM_CREDIT = LEDGER.replace("""\tpayment:
\t\tdate: 2026-02-10
\t\tamount: 65.00
\t\tbank_account: "Assets:Bank"
\t\tmemo: "Original memo"
""", '\tauto_apply_credit: #True\n').replace(
    'invoice "INV-MEMO-001"', """2026-02-05 * "Memo Ltd"
\tAssets:Bank 65.00 CAD
\t\tmemo: "ACME WIRE 0042"
\tAssets:Accounts Receivable -65.00 CAD
\t\tmemo: "February deposit"
\t\tlot_owner: "customer:C-MEMO"

invoice "INV-MEMO-001\"""")

#: The same deposit with one wording on both its splits, which is what a
#: feed import or a one-memo hand entry leaves.
FROM_CREDIT_ALIKE = FROM_CREDIT.replace('memo: "ACME WIRE 0042"',
                                        'memo: "February deposit"')

#: One wire settling two invoices — each block names the same transaction,
#: and the memo the export writes for both is the **shared** bank split's.
SHARED = """2026-01-01 commodity CAD
\tmnemonic: "CAD"
\tfullname: "Canadian Dollar"
\tnamespace: "CURRENCY"
\tfraction: 100
2026-01-01 open Assets
\ttype: Asset
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Assets:Bank
\ttype: Bank
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Assets:Accounts Receivable
\ttype: Accounts Receivable
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Income
\ttype: Income
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Income:Sales
\ttype: Income
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"

customer "C-MEMO"
\tname: "Memo Ltd"
\tcurrency: CAD

2026-02-10 * "One wire for two invoices"
\tguid: "bb00bb00bb00bb00bb00bb00bb00bb00"
\tAssets:Bank 100.00 CAD
\t\tmemo: "Wire"
\tAssets:Accounts Receivable -60.00 CAD
\t\tguid: "cc00cc00cc00cc00cc00cc00cc000001"
\t\tmemo: "Wire"
\tAssets:Accounts Receivable -40.00 CAD
\t\tguid: "cc00cc00cc00cc00cc00cc00cc000002"
\t\tmemo: "Wire"
"""


#: The same wire as a bank feed leaves it: the bank's own wording on the
#: bank split, and nothing yet on the two receivable splits the invoices
#: will settle from.
SHARED_FROM_A_FEED = (
    SHARED
    .replace('\t\tguid: "cc00cc00cc00cc00cc00cc00cc000001"\n\t\tmemo: "Wire"\n',
             '\t\tguid: "cc00cc00cc00cc00cc00cc00cc000001"\n')
    .replace('\t\tguid: "cc00cc00cc00cc00cc00cc00cc000002"\n\t\tmemo: "Wire"\n',
             '\t\tguid: "cc00cc00cc00cc00cc00cc00cc000002"\n')
    .replace('\t\tmemo: "Wire"\n', '\t\tmemo: "ACME WIRE"\n'))


def _an_invoice(doc_id, amount, split_guid):
    return f"""
invoice "{doc_id}"
\tcustomer_id: "C-MEMO"
\tcurrency: CAD
\tdate_opened: 2026-02-01
\tentry:
\t\tdate: 2026-02-01
\t\tdescription: "A line"
\t\taccount: "Income:Sales"
\t\tquantity: 1
\t\tprice: {amount}
\t\ttaxable: #False
\t\ttax_included: #False
\tposted:
\t\tdate: 2026-02-01
\t\tdue: 2026-03-03
\t\tar_account: "Assets:Accounts Receivable"
\t\tmemo: "{doc_id}"
\t\taccumulate: #True
\tpayment:
\t\tdate: 2026-02-10
\t\tamount: {amount}.00
\t\tbank_account: "Assets:Bank"
\t\ttxn_guid: "bb00bb00bb00bb00bb00bb00bb00bb00"
\t\ttxn_split_guid: "{split_guid}"
\t\tmemo: "Wire"
"""


SHARED_LEDGER = (SHARED
                 + _an_invoice('INV-A', 60,
                               'cc00cc00cc00cc00cc00cc00cc000001')
                 + _an_invoice('INV-B', 40,
                               'cc00cc00cc00cc00cc00cc00cc000002'))

#: The same wire and the same two invoices, hand-written: neither block
#: names a split, so both state the memo of the one they share.
SHARED_NAMING_NO_SPLIT = (
    SHARED
    + _an_invoice('INV-A', 60, 'cc00cc00cc00cc00cc00cc00cc000001').replace(
        '\t\ttxn_split_guid: "cc00cc00cc00cc00cc00cc00cc000001"\n', '')
    + _an_invoice('INV-B', 40, 'cc00cc00cc00cc00cc00cc00cc000002').replace(
        '\t\ttxn_split_guid: "cc00cc00cc00cc00cc00cc00cc000002"\n',
        '').replace('memo: "Wire"', 'memo: "Wire, the other half"'))

#: The same wire with its own wording on **all three** splits, which is what
#: a feed-imported transaction looks like.
SHARED_ALL_ALIKE = SHARED.replace('memo: "Wire"', 'memo: "ACME WIRE"')

#: The run that *establishes* the shared payment, from one file: the wire as
#: the bank feed left it, and both invoices settling from it, each block
#: saying what its own portion was for.
ESTABLISHING = (SHARED_FROM_A_FEED
                + _an_invoice('INV-A', 60,
                              'cc00cc00cc00cc00cc00cc00cc000001').replace(
                                  'memo: "Wire"', 'memo: "Portion for A"')
                + _an_invoice('INV-B', 40,
                              'cc00cc00cc00cc00cc00cc00cc000002').replace(
                                  'memo: "Wire"', 'memo: "Portion for B"'))


def _book(tmp_path, ledger_text=LEDGER):
    ledger = tmp_path / 'in.txt'
    ledger.write_text(ledger_text, encoding='utf-8')
    book = tmp_path / 'book.gnucash'
    made = CliRunner().invoke(cli, ['import', '--new', str(book), str(ledger),
                                    '--include-business-objects'])
    assert made.exit_code == 0, made.output
    return book


def _exported(book, tmp_path, name='out.txt'):
    out = tmp_path / name
    assert CliRunner().invoke(cli, [
        'export', str(book), '--output', str(out),
        '--include-business-objects']).exit_code == 0
    return out.read_text(encoding='utf-8')


def _payment_block(text):
    """The invoice's `payment:` block, from an exported ledger."""
    kept, inside = [], False
    for line in text.splitlines():
        if line.strip() == 'payment:':
            inside = True
        elif not line.startswith('\t\t'):
            inside = False
        if inside:
            kept.append(line)
    return '\n'.join(kept)


def _payment_memo_changed(text, was, now):
    """The same ledger with the `payment:` block's memo corrected.

    The block writes `memo: "…"` and a split block `memo:"…"`, so the space
    is what tells the invoice's half of the file from the transaction's.
    """
    return text.replace(f'\t\tmemo: "{was}"', f'\t\tmemo: "{now}"')


def _memos_on(book, account_name):
    """Every memo on a split of one account."""
    repo = GnuCashRepository(str(book))
    repo.open(SessionMode.READ_ONLY)
    try:
        return [split.GetMemo()
                for account in repo.book.get_root_account().get_descendants()
                if get_account_full_name(account) == account_name
                for split in account.GetSplitList()]
    finally:
        repo.close()


def _memos_by_split(book):
    """`{split guid: memo}` for every split on the receivable."""
    repo = GnuCashRepository(str(book))
    repo.open(SessionMode.READ_ONLY)
    try:
        found = {}
        for account in repo.book.get_root_account().get_descendants():
            if get_account_full_name(account) != 'Assets:Accounts Receivable':
                continue
            for split in account.GetSplitList():
                found[split.GetGUID().to_string()] = split.GetMemo()
        return found
    finally:
        repo.close()


def _receivable_memos(book):
    """Every memo on a split of the receivable."""
    repo = GnuCashRepository(str(book))
    repo.open(SessionMode.READ_ONLY)
    try:
        found = []
        for account in repo.book.get_root_account().get_descendants():
            if get_account_full_name(account) != 'Assets:Accounts Receivable':
                continue
            for split in account.GetSplitList():
                found.append(split.GetMemo())
        return found
    finally:
        repo.close()


def _updated(result) -> int:
    """The `Updated:` figure a run reported."""
    for line in result.output.splitlines():
        if line.strip().startswith('Updated:'):
            return int(line.split(':')[1])
    raise AssertionError(result.output)


def _bank_memos(book):
    """Every memo on a split of the bank account."""
    repo = GnuCashRepository(str(book))
    repo.open(SessionMode.READ_ONLY)
    try:
        found = []
        for account in repo.book.get_root_account().get_descendants():
            if get_account_full_name(account) != 'Assets:Bank':
                continue
            for split in account.GetSplitList():
                found.append(split.GetMemo())
        return found
    finally:
        repo.close()


def _posting_guid(book, invoice='INV-MEMO-001'):
    from gnucash import Query

    from infrastructure.gnucash.utils import wrap_invoice_or_bill

    repo = GnuCashRepository(str(book))
    repo.open(SessionMode.READ_ONLY)
    try:
        q = Query()
        q.search_for('gncInvoice')
        q.set_book(repo.book)
        for raw in q.run():
            record = wrap_invoice_or_bill(raw)
            if record.GetID() == invoice:
                posted = record.GetPostedTxn()
                answer = posted.GetGUID().to_string() if posted else None
                q.destroy()
                return answer
        q.destroy()
        raise AssertionError('no such invoice')
    finally:
        repo.close()


class TestCorrectingTheMemo:
    def _corrected(self, tmp_path):
        book = _book(tmp_path)
        before = _posting_guid(book)
        exported = _exported(book, tmp_path)
        assert 'Original memo' in exported, exported
        edited = tmp_path / 'edited.txt'
        edited.write_text(exported.replace('Original memo', 'Corrected memo'),
                          encoding='utf-8')
        result = CliRunner().invoke(cli, ['import', str(book), str(edited),
                                          '--include-business-objects'])
        assert result.exit_code == 0, result.output
        return book, before, result

    def test_the_memo_lands_on_the_bank_transaction(self, tmp_path):
        book, _before, _result = self._corrected(tmp_path)

        assert 'Corrected memo' in _bank_memos(book), _bank_memos(book)

    def test_and_the_invoice_is_not_reported_as_updated(self, tmp_path):
        """It did not change. The memo was never the invoice's."""
        _book_path, _before, result = self._corrected(tmp_path)

        assert 'invoice "INV-MEMO-001": updated' not in result.output, \
            result.output
        assert 'invoice "INV-MEMO-001": unchanged' in result.output, \
            result.output

    def test_and_the_transaction_is(self, tmp_path):
        """Counted with the transactions, which is what moved.

        The figure is what a script reads to decide whether a run changed
        anything, so a summary saying `Updated: 0` over a book that was
        written is the run contradicting itself.
        """
        _book_path, _before, result = self._corrected(tmp_path)

        assert 'Updated:      1' in result.output, result.output

    def test_and_the_invoice_keeps_its_posting_transaction(self, tmp_path):
        """The sharpest measure of "the invoice did not move": rebuilt, it
        would be posted again under a transaction with a new guid, and
        whatever settled it would be pointing at the old one."""
        book, before, _result = self._corrected(tmp_path)

        assert _posting_guid(book) == before

    def test_and_the_correction_survives_a_re_export(self, tmp_path):
        book, _before, _result = self._corrected(tmp_path)

        again = _exported(book, tmp_path, 'again.txt')

        assert 'Corrected memo' in again, again
        assert 'Original memo' not in again, again


class TestARunThatCreatesTheTransaction:
    def test_does_not_report_it_as_updated_as_well(self, tmp_path):
        """A memo written onto a transaction this run made is part of
        making it.

        Counted with the updates, `import --new` reported `Transactions: 1`
        beside `Updated: 1` for a book where one transaction was created
        and none touched afterwards — and the figure is the one a script
        reads to decide whether the run changed anything.
        """
        ledger = tmp_path / 'in.txt'
        ledger.write_text(ESTABLISHING, encoding='utf-8')
        book = tmp_path / 'book.gnucash'
        result = CliRunner().invoke(cli, [
            'import', '--new', str(book), str(ledger),
            '--include-business-objects'])
        assert result.exit_code == 0, result.output

        assert _updated(result) == 0, result.output


class TestTheRunThatAddsThePayment:
    """A block appended to settle a bank transaction already in the book."""

    def _added(self, tmp_path):
        book = _book(tmp_path, BEFORE_THE_PAYMENT)
        assert _bank_memos(book) == ['ACH 0091'], _bank_memos(book)
        edited = tmp_path / 'added.txt'
        edited.write_text(ADDS_A_PAYMENT, encoding='utf-8')
        first = CliRunner().invoke(cli, ['import', str(book), str(edited),
                                         '--include-business-objects'])
        assert first.exit_code == 0, first.output
        return book, edited, first

    def test_writes_the_memo_it_states(self, tmp_path):
        """On that run, not the next one.

        The retarget attaches a transaction the book already holds and keeps
        the memos it arrived with, so a block stating another was dropped —
        and the transaction only joined the invoice's lot on the way out,
        which is what decides whether the memo is this invoice's to write.
        """
        book, _edited, _first = self._added(tmp_path)

        assert _bank_memos(book) == ['Cheque 118'], _bank_memos(book)

    def test_and_the_next_export_says_the_same(self, tmp_path):
        """The block names no split, and the memo still has to land on the
        one every writer reads — the settlement in the invoice's lot.

        Written to the bank split instead, this run's stated memo sat where
        nothing reads it and the next export printed the wording the feed
        had given the transaction, contradicting the file just imported.
        """
        book, _edited, _first = self._added(tmp_path)

        assert 'Cheque 118' in _payment_block(_exported(book, tmp_path)), \
            _payment_block(_exported(book, tmp_path))

    def test_and_the_same_file_imported_again_changes_nothing(self, tmp_path):
        """Dropped on the first run, the memo was written on the second —
        so an unchanged ledger imported twice wrote the book twice, which is
        the defect CLAUDE.md §11 exists about."""
        book, edited, _first = self._added(tmp_path)

        again = CliRunner().invoke(cli, ['import', str(book), str(edited),
                                         '--include-business-objects'])
        assert again.exit_code == 0, again.output

        assert 'Nothing to import' in again.output, again.output


class TestAnOverpaidInvoice:
    """One payment of one invoice, carrying two receivable splits."""

    def test_states_the_split_that_settled_it_and_not_the_residue(
            self, tmp_path):
        """The residue is the owner's credit, not this invoice's payment.

        Both splits are on the receivable and both belong to one payment,
        so anything counting them to decide which one a block describes
        gets this wrong. The block is the settlement's, and the settlement
        is the split in the invoice's own lot.
        """
        book = _book(tmp_path, OVERPAID)
        exported = _exported(book, tmp_path)
        assert 'memo: "What the bank feed called it"' in _payment_block(
            exported), _payment_block(exported)

        edited = tmp_path / 'edited.txt'
        edited.write_text(
            _payment_memo_changed(exported, 'What the bank feed called it',
                                  'Cheque 118'),
            encoding='utf-8')
        result = CliRunner().invoke(cli, ['import', str(book), str(edited),
                                          '--include-business-objects'])
        assert result.exit_code == 0, result.output

        held = _receivable_memos(book)
        assert 'Cheque 118' in held, held
        # The residue keeps what it had, and so does the bank: neither
        # holds what the settling split held, so neither follows it.
        assert 'What the bank feed called it' in held, held
        assert _bank_memos(book) == ['ACH 0091'], _bank_memos(book)


class TestASplitNoBlockDescribes:
    def test_keeps_its_memo_however_it_reads(self, tmp_path):
        """A wire fee is on the payment, and on nobody's block.

        The other side of a payment follows the correction where it still
        holds the same words — that is how `ApplyPayment` leaves the two —
        but "the other side" is the receivable or the payable, not any
        split that happens to read alike.
        """
        book = _book(tmp_path, WITH_A_FEE)
        settled = tmp_path / 'settled.txt'
        settled.write_text(THE_FEE_PAYMENT, encoding='utf-8')
        result = CliRunner().invoke(cli, ['import', str(book), str(settled),
                                          '--include-business-objects'])
        assert result.exit_code == 0, result.output

        assert _bank_memos(book) == ['Cheque 118'], _bank_memos(book)
        assert 'Cheque 118' in _receivable_memos(book), _receivable_memos(book)
        held = _memos_on(book, 'Expenses:Fees')
        assert held == ['ACH 0091'], held


class TestTheFileSayingItTwice:
    """A payment is written out twice: as the invoice's `payment:` block
    and as the transaction that block names."""

    def test_the_invoices_block_is_the_one_that_decides(self, tmp_path):
        """Where the two halves disagree, the block wins.

        It is the invoice's own statement about its own settlement, and
        the transaction section is the same thing written out again. The
        alternatives are worse: deciding it the other way drops the
        ordinary correction, since the memo a reader edits is the one in
        the invoice's block; refusing makes that edit impossible.
        """
        book = _book(tmp_path)
        exported = _exported(book, tmp_path)

        edited = tmp_path / 'edited.txt'
        # The split blocks write `memo:"…"`, the payment block `memo: "…"`,
        # so this reaches the transaction half and leaves the invoice's.
        edited.write_text(
            exported.replace('memo:"Original memo"', 'memo:"Cheque 118"'),
            encoding='utf-8')
        result = CliRunner().invoke(cli, [
            'import', str(book), str(edited), '--include-business-objects',
            '--strategy', 'update'])
        assert result.exit_code == 0, result.output

        assert 'Original memo' in _receivable_memos(book), \
            _receivable_memos(book)
        # And one transaction changed is one transaction: the pass that
        # updates it from its own block reports it, and the memo written
        # from the invoice's block is the same transaction.
        assert _updated(result) == 2, result.output

    def test_and_the_two_halves_agreeing_restores_as_it_always_did(self,
                                                                   tmp_path):
        """The guard is on the disagreement, not on saying it twice."""
        book = _book(tmp_path)
        exported = _exported(book, tmp_path)

        same = tmp_path / 'same.txt'
        same.write_text(exported, encoding='utf-8')
        fresh = tmp_path / 'fresh.gnucash'
        result = CliRunner().invoke(cli, [
            'import', '--new', str(fresh), str(same),
            '--include-business-objects'])

        assert result.exit_code == 0, result.output
        assert _bank_memos(fresh) == ['Original memo'], _bank_memos(fresh)


class TestALedgerAnEarlierReleaseWrote:
    """Its `payment:` memo is the bank split's; its `txn_split_guid:` is the
    receivable's. The two halves of the file disagree about one split."""

    def test_imports_with_both_wordings_intact(self, tmp_path):
        """Its block's memo is the bank split's, and the file says so.

        Read as the settling split's, every such ledger contradicted
        itself — measured, one could not be read into a fresh book at all,
        and re-imported over its own book the receivable side's wording
        was replaced by the bank side's.
        """
        book = _book(tmp_path, LEGACY_EXPORT)

        assert _bank_memos(book) == ['ACME WIRE 0042'], _bank_memos(book)
        assert 'What the bank feed called it' in _receivable_memos(book), \
            _receivable_memos(book)

    def test_and_re_importing_it_changes_nothing(self, tmp_path):
        """On either strategy: under the default the transaction half is
        skipped as a duplicate, which is what used to leave the payment
        block's wording free to go over the receivable split's."""
        book = _book(tmp_path, LEGACY_EXPORT)
        again = tmp_path / 'again.txt'
        again.write_text(LEGACY_EXPORT, encoding='utf-8')

        for strategy in ([], ['--strategy', 'update']):
            result = CliRunner().invoke(cli, [
                'import', str(book), str(again),
                '--include-business-objects'] + strategy)
            assert result.exit_code == 0, result.output
            assert 'What the bank feed called it' in _receivable_memos(book), \
                (strategy, _receivable_memos(book))
            assert _bank_memos(book) == ['ACME WIRE 0042'], \
                (strategy, _bank_memos(book))


    def test_and_says_so_rather_than_dropping_the_line_in_silence(self,
                                                                  tmp_path):
        """The one wording a person cannot give a settling split.

        A block whose memo is what the file already gives the bank split is
        read as a ledger an earlier release wrote, so nothing is written —
        and a reader who meant it got `unchanged` with no word said, which
        is the failure the rest of this reading exists to end. The remedy
        is in the note: say it on the transaction's own split.
        """
        book = _book(tmp_path, LEGACY_EXPORT)
        again = tmp_path / 'again.txt'
        again.write_text(LEGACY_EXPORT, encoding='utf-8')

        result = CliRunner().invoke(cli, [
            'import', str(book), str(again), '--include-business-objects',
            '--strategy', 'update'])

        assert result.exit_code == 0, result.output
        assert 'ACME WIRE 0042' in result.output, result.output
        assert 'no memo was written' in result.output, result.output


class TestABlockNamingNeitherGuid:
    """Hand-written, or an export with its guids taken out."""

    def test_matches_the_payment_the_book_already_holds(self, tmp_path):
        """It states the settling split's memo, so it is compared to that.

        Compared against the bank split — whose wording a retarget leaves
        different — such a block matched no payment. A payment matching no
        block makes the invoice *changed*, so the run unposted it, rebuilt
        it, orphaned the bank transaction it already had and applied the
        block afresh: two bank transactions for money that moved once.
        """
        book = _book(tmp_path, RETARGETED)
        exported = _exported(book, tmp_path)
        stated = _payment_block(exported)
        assert 'What the bank feed called it' in stated, stated

        loose = tmp_path / 'loose.txt'
        loose.write_text('\n'.join(
            line for line in exported.splitlines()
            if not line.strip().startswith(('txn_guid:', 'txn_split_guid:'))),
            encoding='utf-8')
        result = CliRunner().invoke(cli, ['import', str(book), str(loose),
                                          '--include-business-objects'])
        assert result.exit_code == 0, result.output

        assert 'invoice "INV-MEMO-001": unchanged' in result.output, \
            result.output
        assert _bank_memos(book) == ['Original memo'], _bank_memos(book)


class TestACreditBlock:
    """`from_credit:` is written from the other side of the transaction."""

    def test_leaves_the_bank_side_alone(self, tmp_path):
        """Its `memo:` is the receivable split's — the one that settled the
        invoice — so writing it to the bank side would put a credit's
        wording on the split a bank feed named, on an export nobody edited.
        """
        book = _book(tmp_path, FROM_CREDIT)
        exported = _exported(book, tmp_path)
        assert 'from_credit: #True' in exported, exported
        assert 'memo: "February deposit"' in exported, exported

        again = tmp_path / 'again.txt'
        again.write_text(exported, encoding='utf-8')
        result = CliRunner().invoke(cli, ['import', str(book), str(again),
                                          '--include-business-objects'])
        assert result.exit_code == 0, result.output

        assert _bank_memos(book) == ['ACME WIRE 0042'], _bank_memos(book)

    def test_leaves_it_alone_even_when_both_sides_read_alike(self, tmp_path):
        """The deposit's bank line is the deposit's.

        A correction follows onto the other side of a *payment*, because
        `ApplyPayment` writes both alike — but the transaction a credit
        block names is the deposit that opened the credit, whose bank line
        was written before this invoice existed. Following it there
        renamed the deposit in the bank's own register.
        """
        book = _book(tmp_path, FROM_CREDIT_ALIKE)
        assert _bank_memos(book) == ['February deposit'], _bank_memos(book)

        exported = _exported(book, tmp_path)
        edited = tmp_path / 'edited.txt'
        edited.write_text(
            _payment_memo_changed(exported, 'February deposit',
                                  'Applied to INV-MEMO-001'),
            encoding='utf-8')
        result = CliRunner().invoke(cli, ['import', str(book), str(edited),
                                          '--include-business-objects'])
        assert result.exit_code == 0, result.output

        assert 'Applied to INV-MEMO-001' in _receivable_memos(book), \
            _receivable_memos(book)
        assert _bank_memos(book) == ['February deposit'], _bank_memos(book)

    def test_and_a_correction_reaches_the_split_it_is_read_from(self,
                                                                tmp_path):
        book = _book(tmp_path, FROM_CREDIT)
        exported = _exported(book, tmp_path)

        edited = tmp_path / 'edited.txt'
        edited.write_text(
            exported.replace('memo: "February deposit"',
                             'memo: "February deposit (corrected)"'),
            encoding='utf-8')
        result = CliRunner().invoke(cli, ['import', str(book), str(edited),
                                          '--include-business-objects'])
        assert result.exit_code == 0, result.output

        assert 'February deposit (corrected)' in _receivable_memos(book), \
            (_receivable_memos(book), exported)
        assert _bank_memos(book) == ['ACME WIRE 0042'], _bank_memos(book)


class TestTwoBlocksSettlingFromOneSplit:
    def test_are_refused_before_a_memo_is_read_at_all(self, tmp_path):
        """Two invoices settling from one wire must each name their own
        split, and a block naming only the transaction is refused for it —
        which is what keeps two blocks from ever stating one split's memo.
        """
        ledger = tmp_path / 'in.txt'
        ledger.write_text(SHARED_NAMING_NO_SPLIT, encoding='utf-8')
        book = tmp_path / 'book.gnucash'
        result = CliRunner().invoke(cli, [
            'import', '--new', str(book), str(ledger),
            '--include-business-objects'])

        assert result.exit_code != 0, result.output
        message = str(result.output) + str(result.exception)
        assert 'txn_split_guid' in message, message


class TestTheRunThatEstablishesASharedPayment:
    def test_leaves_the_wire_saying_what_the_feed_called_it(self, tmp_path):
        """Both invoices settle from it in one file, and neither owns it.

        Whether a payment settles several invoices was asked of the book,
        which on this run holds only the first invoice's lot when the
        first block is read — so that block wrote the shared bank split,
        replacing the bank feed's own wording, and the second block then
        met a memo the first had just changed.
        """
        book = _book(tmp_path, ESTABLISHING)

        assert _bank_memos(book) == ['ACME WIRE'], _bank_memos(book)
        held = _memos_by_split(book)
        assert held['cc00cc00cc00cc00cc00cc00cc000001'] == 'Portion for A', held
        assert held['cc00cc00cc00cc00cc00cc00cc000002'] == 'Portion for B', held

    def test_even_where_every_split_arrived_reading_alike(self, tmp_path):
        """Which is what a feed-imported wire looks like.

        The bank split follows a correction where it still holds what the
        settling split held — and on this run it does, all three having
        arrived with the feed's own wording. What stops it following is
        knowing the wire is shared, and the book cannot say so yet: the
        second invoice is not posted when the first block is read. So the
        first invoice's portion went onto the wire itself, and which one
        was decided by the order they appear in the file.
        """
        book = _book(tmp_path, ESTABLISHING.replace(
            SHARED_FROM_A_FEED, SHARED_ALL_ALIKE))

        assert _bank_memos(book) == ['ACME WIRE'], _bank_memos(book)
        held = _memos_by_split(book)
        assert held['cc00cc00cc00cc00cc00cc00cc000001'] == 'Portion for A', held
        assert held['cc00cc00cc00cc00cc00cc00cc000002'] == 'Portion for B', held


class TestTwoInvoicesSettledByOneTransaction:
    def test_each_states_the_memo_of_its_own_portion(self, tmp_path):
        """They share one bank split, so neither block may write it.

        Each invoice's block says what *its* portion of the wire was for,
        which is how the multi-invoice fixtures here are written. Written
        to the shared bank split, the first block put its wording there and
        the second put its own over the top — the run reporting `Updated:
        1` with both invoices `unchanged`, and which wording survived
        decided by the order the invoices appear in.
        """
        book = _book(tmp_path, SHARED_LEDGER)
        exported = _exported(book, tmp_path)
        assert exported.count('memo: "Wire"') >= 2, exported

        edited = tmp_path / 'edited.txt'
        edited.write_text(
            exported.replace('\t\ttxn_split_guid: '
                             '"cc00cc00cc00cc00cc00cc00cc000001"\n'
                             '\t\tmemo: "Wire"',
                             '\t\ttxn_split_guid: '
                             '"cc00cc00cc00cc00cc00cc00cc000001"\n'
                             '\t\tmemo: "Wire (A)"'),
            encoding='utf-8')
        result = CliRunner().invoke(cli, ['import', str(book), str(edited),
                                          '--include-business-objects'])
        assert result.exit_code == 0, result.output

        held = _memos_by_split(book)
        assert held['cc00cc00cc00cc00cc00cc00cc000001'] == 'Wire (A)', held
        assert held['cc00cc00cc00cc00cc00cc00cc000002'] == 'Wire', held
        # And the split they share says what it always did.
        assert _bank_memos(book) == ['Wire'], _bank_memos(book)


class TestTheTransactionItselfIsInTheFileToo:
    """A payment is exported twice: as the invoice's `payment:` block, and
    as the standalone `*` transaction whose guid that block names."""

    def test_a_correction_to_both_is_counted_once(self, tmp_path):
        """`--strategy update` updates the transaction from its own block,
        which leaves the payment block's memo already correct — so the two
        must not both be counted."""
        book = _book(tmp_path)
        exported = _exported(book, tmp_path)
        edited = tmp_path / 'edited.txt'
        edited.write_text(exported.replace('Original memo', 'Corrected memo'),
                          encoding='utf-8')

        untouched = tmp_path / 'untouched.txt'
        untouched.write_text(exported, encoding='utf-8')
        first = CliRunner().invoke(cli, [
            'import', str(book), str(untouched), '--include-business-objects',
            '--strategy', 'update'])
        assert first.exit_code == 0, first.output

        result = CliRunner().invoke(cli, [
            'import', str(book), str(edited), '--include-business-objects',
            '--strategy', 'update'])
        assert result.exit_code == 0, result.output

        assert 'Corrected memo' in _bank_memos(book), _bank_memos(book)
        # The figure `--strategy update` reports is the transactions the file
        # named, changed or not — so correcting a memo must not add to it a
        # second time. Measured against the same file with nothing edited.
        assert _updated(result) == _updated(first), (result.output,
                                                     first.output)


class TestASplitTheFileDoesNotState:
    """A payment block states one memo, and a transaction has two splits."""

    def test_keeps_the_memo_it_had(self, tmp_path):
        """Only the split the block is written from is the block's to change.

        A payment retargeted from a bank feed keeps whatever memo each of its
        splits arrived with — `_retarget_counter_split_to_lot` preserves them
        deliberately — and a `payment:` block states the **bank** side's, the
        one the export reads. Written to every split, an unmodified export
        re-imported over its own book replaced the receivable side's memo
        with the bank side's, reported the invoice `unchanged`, and saved.
        """
        book = _book(tmp_path, RETARGETED)
        assert 'What the bank feed called it' in _receivable_memos(book), \
            _receivable_memos(book)

        exported = _exported(book, tmp_path)
        again = tmp_path / 'again.txt'
        again.write_text(exported, encoding='utf-8')
        result = CliRunner().invoke(cli, ['import', str(book), str(again),
                                          '--include-business-objects'])
        assert result.exit_code == 0, result.output

        assert 'What the bank feed called it' in _receivable_memos(book), \
            _receivable_memos(book)

    def test_follows_the_correction_where_it_held_the_same_memo(self,
                                                               tmp_path):
        """The ordinary payment, where `ApplyPayment` wrote both sides alike.

        Leaving the other split behind would break them apart: the book
        would hold two memos where GnuCash had written one, and the one the
        file never sees would be the stale one.
        """
        book = _book(tmp_path)
        # The posting's own split, and the payment's — which `ApplyPayment`
        # gave the same memo as the bank side.
        assert _receivable_memos(book) == ['INV-MEMO-001', 'Original memo'], \
            _receivable_memos(book)

        exported = _exported(book, tmp_path)
        edited = tmp_path / 'edited.txt'
        edited.write_text(exported.replace('Original memo', 'Corrected memo'),
                          encoding='utf-8')
        result = CliRunner().invoke(cli, ['import', str(book), str(edited),
                                          '--include-business-objects'])
        assert result.exit_code == 0, result.output

        assert 'Corrected memo' in _receivable_memos(book), \
            _receivable_memos(book)
