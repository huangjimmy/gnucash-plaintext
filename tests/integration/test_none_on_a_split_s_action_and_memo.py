"""`#None` and `$None$` on a split's `action:` and `memo:`, GnuCash's own fields.

A field cannot be removed, so `$None$` on one is read as `#None`. A field is
then set as the block states it and read back, and where GnuCash keeps
something other than what was stated, the import says so. Measured, GnuCash's
setter for a split's action ignores a null: an update stating `action: #None`
keeps the action it had, a new split's action reads `""`, and each is said.

A memo is text to GnuCash too, and `#None` cannot set it: `SetMemo(None)`
changes nothing. So `memo: #None` and `memo: $None$` both set it to `""`, and
the import says the field cannot be removed or set to #None.

A transaction header with no description keeps the description it had.
"""

from pathlib import Path

from click.testing import CliRunner

from cli.main import cli

DEPOSIT = 'tests/fixtures/a_deposit_whose_bank_split_has_an_action_and_a_memo.txt'
BANK = 'Assets:Bank 100.00 CAD'


def _emptied(line, key, stated):
    return (f'⚠ {line!r}: `{key}` is a GnuCash field, which cannot be removed or set '
            f'to #None, so `{key}: {stated}` sets it to "". An empty field is not '
            f'written in the export, which does not mean it was removed.')


def _kept(line, key, stated, held):
    return (f'⚠ {line!r}: `{key}: {stated}` was stated, and GnuCash keeps '
            f'`{key}: {held}`.')


def _warnings(output):
    return [line.strip() for line in output.splitlines() if line.strip().startswith('⚠')]


def _with_nothing_stated(tmp_path):
    text = Path(DEPOSIT).read_text()
    for old, new in (('\t\taction: "Deposit"\n', '\t\taction: #None\n'),
                     ('\t\tmemo: "first"\n', '\t\tmemo: #None\n'),
                     ('2026-01-10 * "Consulting paid"\n', '2026-01-10 *\n')):
        assert old in text, text
        text = text.replace(old, new)
    path = tmp_path / 'nothing_stated.txt'
    path.write_text(text)
    return path


def _exported(book, tmp_path):
    out = tmp_path / 'out.txt'
    result = CliRunner().invoke(cli, ['export', str(book), str(out)])
    assert result.exit_code == 0, result.output
    return out.read_text()


def test_an_update_keeps_the_action_and_the_description_and_empties_the_memo(tmp_path):
    book = tmp_path / 'book.gnucash'
    made = CliRunner().invoke(cli, ['import', '--new', str(book), DEPOSIT])
    assert made.exit_code == 0, made.output

    result = CliRunner().invoke(cli, ['import', str(book), str(_with_nothing_stated(tmp_path)),
                                      '--strategy', 'update'])

    assert result.exit_code == 0, result.output
    assert _warnings(result.output) == [
        _emptied(BANK, 'memo', '#None'),
        _kept(BANK, 'action', '#None', '"Deposit"')], result.output
    exported = _exported(book, tmp_path)
    assert '2026-01-10 * "Consulting paid"' in exported, exported
    assert 'action: "Deposit"' in exported, exported
    assert 'first' not in exported, exported


def test_a_new_transaction_is_stored_with_no_action_and_no_memo(tmp_path):
    book = tmp_path / 'book.gnucash'

    result = CliRunner().invoke(cli, ['import', '--new', str(book),
                                      str(_with_nothing_stated(tmp_path))])

    assert result.exit_code == 0, result.output
    assert _warnings(result.output) == [
        _emptied(BANK, 'memo', '#None'),
        _kept(BANK, 'action', '#None', '""')], result.output
    exported = _exported(book, tmp_path)
    assert 'Deposit' not in exported, exported
    assert 'first' not in exported, exported


def test_none_between_dollar_signs_on_a_new_split_s_memo_sets_it_to_empty_and_warns(tmp_path):
    book = tmp_path / 'book.gnucash'
    text = Path(DEPOSIT).read_text().replace('\t\tmemo: "first"\n', '\t\tmemo: $None$\n')
    ledger = tmp_path / 'memo_removed.txt'
    ledger.write_text(text)

    result = CliRunner().invoke(cli, ['import', '--new', str(book), str(ledger)])

    assert result.exit_code == 0, result.output
    assert _warnings(result.output) == [_emptied(BANK, 'memo', '$None$')], result.output
    exported = _exported(book, tmp_path)
    assert 'first' not in exported and '$None$' not in exported, exported


def test_none_between_dollar_signs_on_a_block_keeping_no_custom_keys_warns(tmp_path):
    """An `open_prepayment:` summary holds fields alone, so its `amount:` is read as `#None`."""
    book = tmp_path / 'book.gnucash'
    summary = 'tests/fixtures/an_edited_prepayment_summary.txt'
    text = Path(summary).read_text().replace('\t\tamount: 10.00 CAD\n', '\t\tamount: $None$\n')
    ledger = tmp_path / 'summary_removed.txt'
    ledger.write_text(text)

    result = CliRunner().invoke(cli, ['import', '--new', str(book), str(ledger),
                                      '--include-business-objects'])

    assert result.exit_code == 0, result.output
    assert ("⚠ 'open_prepayment:': `amount` is a GnuCash field, which cannot be removed, "
            'so `amount: $None$` sets it to #None.') in _warnings(result.output), result.output
