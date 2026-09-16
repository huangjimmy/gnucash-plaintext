"""A dry run reports the payments the real run would leave orphaned.

Rebuilding a paid invoice unposts it, and GnuCash's unpost destroys the
posting while leaving the payment transaction whole — so the money still shows
in the bank with nothing owed against it. That warning is the one README
describes as the one whose absence silently doubles the recorded bank balance.

`--dry-run` is what a reader consults *before* committing to the real run, so
it has to say the same thing. The unpost happens in memory during a dry run
just as it does in a real one; only the save is skipped.

The file here is the rebuild shape: the payment the book holds is dated a day
later and a second payment is added, so the book's payment pairs with no block
and the invoice is rebuilt rather than added to
(`test_a_changed_payment_beside_an_added_one_rebuilds_the_invoice.py` measures
the same file against a real run).
"""

from pathlib import Path

from click.testing import CliRunner

from cli.main import cli

ACCOUNTS = 'tests/fixtures/payment_roundtrip_accounts.txt'
FIRST = 'tests/fixtures/inv_001_paid_60_on_the_15th.txt'
CHANGED_AND_ADDED = 'tests/fixtures/inv_001_paid_60_on_the_16th_and_40_on_the_20th.txt'


def _run(*args):
    return CliRunner().invoke(cli, [str(arg) for arg in args])


def _a_paid_invoice(tmp_path):
    book = tmp_path / 'book.gnucash'
    assert _run('import', '--new', book, ACCOUNTS).exit_code == 0
    made = _run('import', book, FIRST, '--include-business-objects')
    assert made.exit_code == 0, made.output
    return book


def test_the_orphan_is_reported_by_the_dry_run(tmp_path):
    book = _a_paid_invoice(tmp_path)

    result = _run('import', book, CHANGED_AND_ADDED,
                  '--include-business-objects', '--dry-run')

    assert result.exit_code == 0, result.output
    assert 'now orphaned' in result.output, result.output
    assert 'INV-001' in result.output, result.output


def test_the_dry_run_still_says_it_changed_nothing(tmp_path):
    """The warning is what would happen, not what did."""
    book = _a_paid_invoice(tmp_path)
    before = book.read_bytes()

    result = _run('import', book, CHANGED_AND_ADDED,
                  '--include-business-objects', '--dry-run')

    assert 'Dry run complete' in result.output, result.output
    assert book.read_bytes() == before


def test_a_bad_block_elsewhere_does_not_silence_it(tmp_path):
    """A file of good blocks and one bad one is the ordinary shape.

    The good blocks still unpost what they rebuild, so the real run would
    still leave that payment orphaned — and the preview is what a reader
    consults to find that out before running it. Gated on the run having no
    errors, the preview said nothing and the real run that followed printed
    the warning the preview had been consulted to find.
    """
    book = _a_paid_invoice(tmp_path)
    ledger = tmp_path / 'with-a-bad-block.txt'
    ledger.write_text(
        Path(CHANGED_AND_ADDED).read_text()
        + '\n2026-02-01 * "On an account nobody opened"\n'
          '\tcurrency.mnemonic: "CAD"\n'
          '\tAssets:Nowhere 5.00 CAD\n'
          '\tAssets:Bank -5.00 CAD\n')

    result = _run('import', book, ledger, '--include-business-objects', '--dry-run')

    assert 'now orphaned' in result.output, result.output
    assert 'INV-001' in result.output, result.output


def test_the_real_run_reports_it_too(tmp_path):
    """The two answers agree, which is the whole point of consulting the first."""
    book = _a_paid_invoice(tmp_path)

    previewed = _run('import', book, CHANGED_AND_ADDED,
                     '--include-business-objects', '--dry-run')
    real = _run('import', book, CHANGED_AND_ADDED, '--include-business-objects')

    assert real.exit_code == 0, real.output
    assert ('now orphaned' in previewed.output) == ('now orphaned' in real.output)
