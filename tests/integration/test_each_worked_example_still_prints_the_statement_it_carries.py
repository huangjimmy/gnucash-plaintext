"""Every file under `examples/multi-currency/` still prints the page it shows.

Each example carries a ledger and, commented at the end, the statement that
ledger produces. Three documents quote those files — `docs/multi-currency.md`,
`README.md` and `docs/issues/Q-044-…md` — and Q-044 leans on them as evidence:
"the examples show the subtraction being made, on books a reader can run".

**Nothing checked that the statement in the file was still the statement the
tool prints.** `scripts/generate-multi-currency-examples.sh` imports each
ledger it writes and stops if one does not come back, which catches a ledger
that will not parse and nothing else. So any change to the report's shape left
eleven example files and three documents quietly describing a page that no
longer exists — and a reader running the two commands in each file's own header
would be the one to find out.

That is what this closes. The ledger is imported into a fresh book, the sheet
is drawn at the date the file's own header gives, and the result is compared
with the block the file carries.

Two things are normalised before the comparison, and nothing else is.

**Guids are masked**: a split's guid is made fresh on every import, so the
committed file cannot hold the one a reader will get.

**The entries of a `splits:` list are sorted.** The order GnuCash hands back
two splits of one account on one day is not the same on every build — measured
here, `a_us_customer_invoiced_and_the_dollars_still_held.txt` lists the
receivable's +2,720.00 before its −2,720.00 on GnuCash 3.8 and after it on
5.10, with every figure identical. That order is GnuCash's and this page only
prints what it is given, so pinning it would fail three examples on Ubuntu
20.04 over a difference that is not this tool's to have.

Everything else — every figure, every key, every comment the report writes, and
the order of everything that is not a split within one list — is compared as
written.
"""

import re
from pathlib import Path

import pytest
from click.testing import CliRunner

from tests.conftest import _run

EXAMPLES = sorted(Path('examples/multi-currency').glob('*.txt'))

# The date in each file's own header, from the command it tells a reader to run:
#     gnucash-plaintext balance-sheet /tmp/check.gnucash --as-of 2026-01-25
AS_OF = re.compile(r'balance-sheet \S+ --as-of (\d{4}-\d{2}-\d{2})')

# Where the statement starts: a dated directive, commented out because a line at
# column 0 would be read as one and the file would not import.
OPENS = re.compile(r'^#\s+\d{4}-\d{2}-\d{2} balance-sheet\s*$')


def _masked(text):
    return re.sub(r'\b[0-9a-f]{32}\b', '<guid>', text)


def _indent_of(line):
    return len(line) - len(line.lstrip('\t'))


def _splits_sorted(text):
    """The same page with each `splits:` list put in a settled order.

    A `split:` entry is that line and every deeper line under it, so the
    entries are cut at the `split:` lines and the pieces sorted by their own
    text. Guids are already masked by the time this runs, so two entries sort
    by their account and figure rather than by an identifier that changes every
    import.
    """
    lines = text.splitlines()
    out = []
    at = 0
    while at < len(lines):
        line = lines[at]
        out.append(line)
        at += 1
        if not line.strip().startswith('splits:'):
            continue
        depth = _indent_of(line)
        start = at
        while at < len(lines) and _indent_of(lines[at]) > depth:
            at += 1
        entries = []
        for line in lines[start:at]:
            if line.strip() == 'split:':
                entries.append([line])
            elif entries:
                entries[-1].append(line)
            else:                      # a line before the first `split:`
                out.append(line)
        for entry in sorted(entries, key='\n'.join):
            out.extend(entry)
    return '\n'.join(out)


def _comparable(text):
    return _splits_sorted(_masked(text.rstrip()))


def _uncommented(line):
    """A statement line with the `# ` the file wraps it in taken off."""
    if line.startswith('# '):
        return line[2:]
    return line[1:] if line.startswith('#') else line


def _statement_in(path, lines):
    opened = [n for n, line in enumerate(lines) if OPENS.match(line)]
    assert opened, f'{path} carries no commented balance sheet'
    body = []
    for line in lines[opened[-1]:]:
        if not line.startswith('#'):
            break
        body.append(_uncommented(line))
    return '\n'.join(body).rstrip()


@pytest.mark.parametrize('example', EXAMPLES, ids=[path.name for path in EXAMPLES])
def test_the_example_prints_the_statement_it_carries(tmp_path, example):
    lines = example.read_text(encoding='utf-8').splitlines()
    stated = _statement_in(example, lines)

    found = AS_OF.search('\n'.join(lines))
    assert found, f'{example} does not say what date it was drawn at'
    as_of = found.group(1)

    runner = CliRunner()
    book = tmp_path / 'check.gnucash'
    made = _run(runner, 'import', '--new', str(book), str(example))
    assert made.exit_code == 0, made.output

    drawn = _run(runner, 'balance-sheet', str(book), '--as-of', as_of)
    assert drawn.exit_code == 0, drawn.output

    assert _comparable(drawn.output) == _comparable(stated), (
        f'{example.name} carries a statement the tool no longer prints. '
        f'Re-run scripts/generate-multi-currency-examples.sh, and check the '
        f'passages quoting it in docs/multi-currency.md, README.md and '
        f'docs/issues/Q-044-state-a-realized-gain-with-no-took-the-residual-'
        f'key-and-say-what-the-balancing-amount-is.md.')


def test_every_example_is_covered_by_this():
    """A file added to the folder and left out of the sweep proves nothing.

    The eleven are found by glob rather than listed, so this only guards
    against the folder being empty or moved — which would make every
    parametrised case above vanish silently and the suite still go green.
    """
    assert len(EXAMPLES) == 11, [path.name for path in EXAMPLES]
