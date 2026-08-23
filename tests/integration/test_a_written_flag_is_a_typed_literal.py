"""Every boolean a writer writes is `#True` or `#False`, and nothing else.

`#` is this format's mark for a value that is not a string: `#None`, `#3/4`,
`#100`, `#True`. A bare `true` is not a boolean at all — it decodes to the
*string* `'true'` — and writing one is how the format ended up with two
spellings for one fact and a class of bug underneath:

- `taxable: True` read as **false**, because the flag was compared against
  the string `'true'` while `True` decoded to a `bool`;
- `placeholder: false` reached `SetPlaceholder` as the string `'false'` and
  GnuCash refused the account: *Python object passed to a gboolean argument
  was not True or False* — the account then missing from the book, and every
  line naming it failing after it.

Nine writers were emitting bare words from hand-rolled f-strings while three
went through `encode_value_as_string`, and no test compared them, because
every test asserted the spelling its own writer produced. This one asks the
question the other way round: whatever a writer emits, is it a typed literal?

**The readers stay liberal** — `true`/`1`/`yes` and `false`/`0`/`no` are all
still accepted, so no ledger ever hand-written stops importing. This is about
what is *written*, which is the half a round trip depends on.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner

from cli.main import cli
from infrastructure.gnucash.utils import FLAG_KEYS

#: Ledgers that between them exercise every block the format has. Each is
#: imported and exported, and the export is what is read below.
LEDGERS = [
    'tests/fixtures/entries_with_every_field.txt',
    'tests/fixtures/an_invoice_whose_lines_share_an_account.txt',
    'tests/fixtures/a_credit_note_and_the_invoice_it_reverses.txt',
    'tests/fixtures/business_objects.txt',
]


def _exported(tmp_path, ledger, name):
    book = tmp_path / f'{name}.gnucash'
    made = CliRunner().invoke(cli, ['import', '--new', str(book), ledger,
                                    '--include-business-objects'])
    assert made.exit_code == 0, made.output
    out = tmp_path / f'{name}.txt'
    written = CliRunner().invoke(cli, ['export', str(book), '--output',
                                       str(out),
                                       '--include-business-objects'])
    assert written.exit_code == 0, written.output
    return out.read_text(encoding='utf-8')


def _flags_written(text):
    """`[(key, value)]` for every flag line in a ledger."""
    found = []
    for line in text.splitlines():
        bare = line.strip()
        if ':' not in bare or bare.startswith('#'):
            continue
        key, _, value = bare.partition(':')
        if key.strip() in FLAG_KEYS:
            found.append((key.strip(), value.strip()))
    return found


@pytest.mark.parametrize('ledger', LEDGERS)
def test_every_flag_an_export_writes_is_a_typed_literal(tmp_path, ledger):
    text = _exported(tmp_path, ledger, Path(ledger).stem)
    written = _flags_written(text)

    assert written, f'no flags in the export of {ledger}:\n{text[:2000]}'
    wrong = [(key, value) for key, value in written
             if value not in ('#True', '#False')]
    assert not wrong, (
        f'{ledger}: these are booleans and are not written as one — '
        f'{wrong}\n{text[:2000]}')


@pytest.mark.parametrize('invoice', ['INV-EVERY-001', 'BILL-EVERY-001'])
def test_and_so_is_every_flag_a_printed_invoice_writes(tmp_path, invoice):
    """The printers assemble their own blocks, which is how they came to
    disagree with `export` about the same line before."""
    book = tmp_path / 'printed.gnucash'
    assert CliRunner().invoke(cli, [
        'import', '--new', str(book),
        'tests/fixtures/entries_with_every_field.txt',
        '--include-business-objects']).exit_code == 0
    page = tmp_path / 'page.txt'
    command = 'print-invoice' if invoice.startswith('INV') else 'print-bill'
    assert CliRunner().invoke(cli, [
        command, str(book), invoice, '--format', 'plaintext',
        '--output', str(page)]).exit_code == 0

    written = _flags_written(page.read_text(encoding='utf-8'))

    assert written, f'no flags on the printed {invoice}'
    wrong = [(key, value) for key, value in written
             if value not in ('#True', '#False')]
    assert not wrong, f'{invoice}: {wrong}'


def test_the_list_is_not_quietly_empty(tmp_path):
    """The check above passes trivially if `FLAG_KEYS` and the writers drift
    apart — a key renamed on one side and not the other reads as "no flags
    here". Every key in the list is asserted to be one a writer writes."""
    seen = set()
    for ledger in LEDGERS:
        seen |= {key for key, _ in
                 _flags_written(_exported(tmp_path, ledger,
                                          f'seen-{Path(ledger).stem}'))}

    # Three are not written by these ledgers, each for a reason:
    #
    # `auto_apply_credit:` and `cost_basis_force:` are read-only — a file
    # asks for something with them and the book records what happened, not
    # the asking. No export writes either.
    #
    # `from_credit:` is written, by both the export and the printers, but
    # only for an invoice a credit settled — which none of these hold.
    # `test_printing_a_credit_settled_invoice.py` and
    # `test_credit_reimport_changes_nothing.py` are where its spelling is
    # asserted.
    assert FLAG_KEYS - seen == {'auto_apply_credit', 'cost_basis_force',
                                'from_credit'}, FLAG_KEYS - seen
