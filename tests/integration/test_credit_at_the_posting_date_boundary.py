"""A credit spent before, on, and after the day it arrived — one book.

Which of a document's payments came out of the owner's credit cannot be worked
out from the book afterwards. Once applied, a consumed credit's split sits in
the document's lot exactly as a bank payment's split does; GnuCash keeps no
record of the lot it came from; and on the day a deposit is taken and a
document raised against it, even the dates agree. So the import writes the
fact down as it applies the credit, and the export reads it.

This is the case that says whether that works, all in one book: a customer and
a vendor, each overpaid by 50.00 on 2026-01-10, and each spending it across a
document posted that same day and one posted three weeks later — with the
document the bank really paid sitting beside them, which must go on saying so.
"""

from pathlib import Path

from click.testing import CliRunner

from cli.main import cli

ACCOUNTS = 'tests/fixtures/payment_roundtrip_accounts.txt'
FIXTURES = Path('tests/fixtures')
CONSUMERS = 'credit_spent_before_on_and_after_the_day_it_arrived.txt'


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
    """The export as its blocks — a header line with the lines indented under it."""
    found = []
    for line in exported.splitlines():
        if line.startswith('\t') and found:
            found[-1] += '\n' + line
        elif line.strip():
            found.append(line)
    return sorted(found)


def _same_content(first: str, second: str, what: str) -> None:
    """Compare two exports block by block, in no particular order.

    Which of two transactions dated the same day comes first is not something
    a plaintext file says: the exporter orders by date, and within a date the
    order follows whatever the engine hands back. A payment written by
    `ApplyPayment` and a posting written by `PostToAccount` carry different
    times of day, an import stamps its own, and which lands first differs by
    engine version. So the comparison is what the blocks say, not the order
    they arrive in — anything missing, added or altered still fails.
    """
    mine, theirs = _blocks(first), _blocks(second)
    if mine == theirs:
        return
    import difflib
    raise AssertionError(what + '\n' + '\n'.join(difflib.unified_diff(
        [line for block in mine for line in block.splitlines()],
        [line for block in theirs for line in block.splitlines()],
        fromfile='first export', tofile='second export', lineterm='')))


def _block(exported, header):
    lines = exported.splitlines()
    start = next((i for i, line in enumerate(lines) if line.startswith(header)), None)
    assert start is not None, f'{header} missing from export:\n{exported}'
    end = next((i for i in range(start + 1, len(lines))
                if lines[i] and not lines[i].startswith('\t')), len(lines))
    return '\n'.join(lines[start:end])


def test_a_credit_reads_the_same_on_either_side_of_the_day_it_arrived(tmp_path):
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    assert runner.invoke(cli, ['import', '--new', str(book), ACCOUNTS]).exit_code == 0
    _import(runner, book, 'q015_aac_primer_invoice.txt', tmp_path)
    _import(runner, book, 'q015_aac_primer_bill.txt', tmp_path)
    _import(runner, book, CONSUMERS, tmp_path)

    exported = _export(runner, book, tmp_path, 'out.txt')

    # The two the bank paid: still bank payments, still carrying what those
    # payments left over on the day they were made — not what survives today,
    # which is nothing.
    for header in ('invoice "INV-001"', 'bill "BILL-001"'):
        block = _block(exported, header)
        assert 'from_credit' not in block, block
        assert 'bank_account: "Assets:Bank"' in block, block
        assert 'date: 2026-01-10' in block, block
        assert 'prepayment: 50.00' in block, block

    # The four settled from credit, on the boundary and past it, on both
    # sides of the ledger. The 200.00 ones took the last 30.00 of the credit
    # and stay open for the rest — a credit consumed whole, which is the case
    # that leaves no residual behind for anything to recognise it by.
    for header, amount in (('invoice "INV-SAME"', '20.00'),
                           ('invoice "INV-AFTER"', '30.00'),
                           ('bill "BILL-SAME"', '20.00'),
                           ('bill "BILL-AFTER"', '30.00')):
        block = _block(exported, header)
        assert 'from_credit: true' in block, block
        assert f'amount: {amount}' in block, block
        assert 'credit_dated: 2026-01-10' in block, block
        assert 'bank_account:' not in block, block
        assert 'payment: none' not in block, block
        assert 'auto_apply_credit' not in block, block

    # Both credits are spent to the last cent.
    prepayments = runner.invoke(cli, ['find-prepayments', str(book)])
    assert prepayments.exit_code == 0, prepayments.output
    assert 'No pre-payment credits found' in prepayments.output, prepayments.output

    # Re-importing that export over the book it came from changes nothing:
    # no credit applied twice, no second bank transaction, no drift. An
    # identical export afterwards is the whole of that claim.
    source = tmp_path / 'source.txt'
    source.write_text(exported)
    again = runner.invoke(cli, ['import', str(book), str(source),
                                '--include-business-objects'])
    assert again.exit_code == 0, again.output
    _same_content(exported, _export(runner, book, tmp_path, 'out2.txt'),
               're-importing its own export changed the book')

    # And the same file rebuilds an empty book into the same six settlements,
    # which then says the same file again.
    rebuilt = tmp_path / 'rebuilt.gnucash'
    result = runner.invoke(cli, ['import', '--new', str(rebuilt), str(source),
                                 '--include-business-objects'])
    assert result.exit_code == 0, result.output
    _same_content(exported, _export(runner, rebuilt, tmp_path, 'out3.txt'),
               'a book rebuilt from this file does not say it back')

    rebuilt_prepayments = runner.invoke(cli, ['find-prepayments', str(rebuilt)])
    assert rebuilt_prepayments.exit_code == 0, rebuilt_prepayments.output
    assert 'No pre-payment credits found' in rebuilt_prepayments.output, (
        rebuilt_prepayments.output)
