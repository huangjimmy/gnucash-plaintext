"""Re-importing a book's own export leaves a credit-settled document alone.

An export describes a credit that settled a document as a payment block
carrying `from_credit: true`; a hand-written file asks for the same thing with
`auto_apply_credit: true` on the header. Both have to read as "already done"
against a book where it is done, or importing a book's own export walks the
destructive path: unpost, rebuild, and a warning that the bank-side payment
has been orphaned.

The shape that matters is a credit only partly spent — 50.00 of credit, 30.00
of it settling the document, 20.00 still the owner's. A credit spent to the
last cent leaves no residual behind, which is the one case a lot-shape
heuristic gets right by accident.
"""

from pathlib import Path

from click.testing import CliRunner

from cli.main import cli

ACCOUNTS = 'tests/fixtures/payment_roundtrip_accounts.txt'
FIXTURES = Path('tests/fixtures')


def _import(runner, book, fixture, tmp_path):
    path = tmp_path / fixture
    path.write_text((FIXTURES / fixture).read_text())
    result = runner.invoke(cli, ['import', str(book), str(path),
                                 '--include-business-objects'])
    assert result.exit_code == 0, result.output
    return result


def _export(runner, book, tmp_path, name):
    out = tmp_path / name
    result = runner.invoke(cli, ['export', str(book), str(out),
                                 '--include-business-objects'])
    assert result.exit_code == 0, result.output
    return out.read_text()


def _blocks(exported: str) -> list:
    """The export as its blocks, in no particular order."""
    found = []
    for line in exported.splitlines():
        if line.startswith('\t') and found:
            found[-1] += '\n' + line
        elif line.strip():
            found.append(line)
    return sorted(found)


def _reimport(runner, book, text, name, tmp_path):
    path = tmp_path / name
    path.write_text(text)
    return runner.invoke(cli, ['import', str(book), str(path),
                               '--include-business-objects'])


def _strip_the_recorded_fact(book):
    """Make the book look like one written before the key existed."""
    from infrastructure.gnucash.kvp import get_custom_metadata, set_custom_metadata
    from repositories.gnucash_repository import GnuCashRepository, SessionMode

    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.NORMAL)
    try:
        root = repo.book.get_root_account()
        for name in ('Assets:Accounts Receivable', 'Liabilities:Accounts Payable'):
            account = root
            for part in name.split(':'):
                account = account.lookup_by_name(part)
            for split in account.GetSplitList():
                metadata = dict(get_custom_metadata(split))
                if metadata.pop('applied_from_credit', None) is None:
                    continue
                transaction = split.GetParent()
                transaction.BeginEdit()
                set_custom_metadata(split, metadata)
                transaction.CommitEdit()
        repo.save()
    finally:
        repo.close()


def test_a_partly_spent_credit_reads_as_already_applied(tmp_path):
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    assert runner.invoke(cli, ['import', '--new', str(book), ACCOUNTS]).exit_code == 0
    _import(runner, book, 'q015_aac_primer_invoice.txt', tmp_path)
    _import(runner, book, 'q015_aac_primer_bill.txt', tmp_path)
    _import(runner, book, 'q015_aac_inv002_partial_credit.txt', tmp_path)
    _import(runner, book, 'q015_aac_bill002_partial_credit.txt', tmp_path)

    exported = _export(runner, book, tmp_path, 'out.txt')
    assert exported.count('from_credit: true') == 2, exported

    # The book's own export, read back: nothing to do, on both sides.
    again = _reimport(runner, book, exported, 'again.txt', tmp_path)
    assert again.exit_code == 0, again.output
    assert 'orphaned' not in again.output, again.output
    assert 'Invoices:    0 created, 0 updated, 2 unchanged' in again.output, again.output
    assert 'Bills:       0 created, 0 updated, 2 unchanged' in again.output, again.output
    assert _blocks(_export(runner, book, tmp_path, 'out2.txt')) == _blocks(exported)

    # And the hand-written form says the same thing about the same book: the
    # request has been honoured, so there is nothing left to honour.
    for fixture in ('q015_aac_inv002_partial_credit.txt',
                    'q015_aac_bill002_partial_credit.txt'):
        result = _import(runner, book, fixture, tmp_path)
        assert 'orphaned' not in result.output, result.output
    assert _blocks(_export(runner, book, tmp_path, 'out3.txt')) == _blocks(exported)

    # A book from before any of this was recorded reads the same way. Every
    # book written by an earlier version has credits applied and no key on
    # the splits that applied them, and re-importing the file that asked for
    # them must still find nothing to do — the alternative is an unpost and
    # rebuild, which re-runs the application and leaves documents whose lot
    # GnuCash drops on load.
    _strip_the_recorded_fact(book)
    for fixture in ('q015_aac_inv002_partial_credit.txt',
                    'q015_aac_bill002_partial_credit.txt'):
        result = _import(runner, book, fixture, tmp_path)
        assert 'orphaned' not in result.output, result.output
        assert '1 unchanged' in result.output, result.output

    # Each owner still has the 20.00 the document did not take.
    prepayments = runner.invoke(cli, ['find-prepayments', str(book)])
    assert prepayments.exit_code == 0, prepayments.output
    assert 'Found 2 open pre-payment credits' in prepayments.output, prepayments.output
    assert 'customer C001 (Acme)  CAD 20.00' in prepayments.output, prepayments.output
    assert 'vendor V001 (Supplier Co)  CAD 20.00' in prepayments.output, (
        prepayments.output)
