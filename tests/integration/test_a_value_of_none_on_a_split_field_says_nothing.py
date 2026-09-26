"""`#None` on a split's `action:` or `memo:` says nothing, as leaving the line out does.

The format's rule for a field is that `key: ""` clears it and a line left out
says nothing. `#None` is how a custom key is removed; on a split's own fields
it sets nothing. So a transaction created with `action: #None` has no action,
and one updated with it keeps the action it had. A transaction header with no
description is read the same way: the update keeps the description.
"""

from pathlib import Path

from click.testing import CliRunner

from cli.main import cli

DEPOSIT = 'tests/fixtures/a_deposit_whose_bank_split_has_an_action_and_a_memo.txt'


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


def test_an_update_keeps_what_the_book_holds(tmp_path):
    book = tmp_path / 'book.gnucash'
    made = CliRunner().invoke(cli, ['import', '--new', str(book), DEPOSIT])
    assert made.exit_code == 0, made.output

    result = CliRunner().invoke(cli, ['import', str(book), str(_with_nothing_stated(tmp_path)),
                                      '--strategy', 'update'])

    assert result.exit_code == 0, result.output
    exported = _exported(book, tmp_path)
    assert '2026-01-10 * "Consulting paid"' in exported, exported
    assert 'action: "Deposit"' in exported, exported
    # The export writes a split's memo with no space after the colon.
    assert 'memo:"first"' in exported, exported


def test_a_new_transaction_is_stored_with_none(tmp_path):
    book = tmp_path / 'book.gnucash'

    result = CliRunner().invoke(cli, ['import', '--new', str(book),
                                      str(_with_nothing_stated(tmp_path))])

    assert result.exit_code == 0, result.output
    exported = _exported(book, tmp_path)
    assert 'Deposit' not in exported, exported
    assert 'first' not in exported, exported
