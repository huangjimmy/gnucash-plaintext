"""A customer's name reaches the page as their name.

The rendered page crosses from Scheme to Python through a file, and both ends
of that handoff pick an encoding from the locale unless told otherwise. Guile
replaces what the locale cannot hold with `?` — silently, no error, exit 0:
measured in the C locale, `(display "a…¥b" port)` writes `a?????b`. So a
document for `东京物産株式会社` could print as `????????`, and the only sign of
it would be on the invoice already sent.

Nothing caught it because every fixture in this suite was ASCII, and a page is
structurally perfect either way — the shell, the columns and the totals are all
still there when the words inside them have been replaced. So this fixture is
deliberately not: a French company, a Japanese customer, an accented line
description, and non-ASCII in both free-text blocks and the document's notes.

What makes it pass is UTF-8 being stated at every hop the page takes — four of
them: `set-port-encoding!` on the Guile port, `encoding='utf-8'` on the read
back, again on the write to the user's file, and `sys.stdout.buffer` for
`-o -`. The container's `C` becomes `C.UTF-8` through CPython's PEP 538
coercion, and that is a default which `PYTHONCOERCECLOCALE=0` (with
`PYTHONUTF8=0`) takes away: measured, both Python and Guile then report
`ANSI_X3.4-1968`.

Which is why the tests below run the print step in a **subprocess** under that
environment. A locale is process-wide and this interpreter has already read
its own, and the print step alone can be put under it: `print-invoice` reads
no plaintext — the book is gzipped XML that declares its own encoding — so the
ledger is imported normally first. Without the four statements those tests
fail, and under the suite's ordinary environment nothing could, because there
the locale's own answer is UTF-8.

There is no PDF assertion here. A `/ToUnicode` CMap is produced by the Latin
text alone, so it holds identically whether the CJK survived, was replaced by
`?`, or came out as tofu — none of the images installs a CJK font — which
makes it a claim about the layout engine rather than about this. That engine
is WebKit, which reads the page off a `file://` URI rather than being handed
a `str`, so the characters reaching it depend on the `<meta charset>` GnuCash
writes surviving `combine_pages`; it does, and what this file asserts is the
step before — that the *page* keeps them. The PDF's text layer is covered on
an ASCII document by `test_a_printed_pdf_can_be_selected_and_copied`.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

from cli.main import cli

FIXTURES = Path('tests/fixtures')
LEDGER = str(FIXTURES / 'a_document_in_more_than_ascii.txt')

# What the coercion gives back with: no UTF-8 mode, no PEP 538, C locale, at
# which point `locale.getpreferredencoding()` and Guile's
# `%default-port-encoding` both answer `ANSI_X3.4-1968` — measured.
ASCII_LOCALE = {'LC_ALL': 'C', 'LANG': 'C',
                'PYTHONUTF8': '0', 'PYTHONCOERCECLOCALE': '0'}


def _book_with_both_documents(tmp_path):
    book = tmp_path / 'unicode.gnucash'
    built = CliRunner().invoke(cli, ['import', '--new', str(book), LEDGER,
                                     '--include-business-objects'])
    assert built.exit_code == 0, built.output
    return book


@pytest.fixture
def printed(tmp_path):
    book = tmp_path / 'unicode.gnucash'
    built = CliRunner().invoke(cli, ['import', '--new', str(book), LEDGER,
                                     '--include-business-objects'])
    assert built.exit_code == 0, built.output

    out = tmp_path / 'inv.html'
    rendered = CliRunner().invoke(cli, [
        'print-invoice', str(book), 'INV-UNICODE-001', '--format', 'html',
        '--output', str(out)])
    assert rendered.exit_code == 0, rendered.output
    return out.read_text(encoding='utf-8')


class TestEveryPartOfThePage:
    def test_the_customers_name_is_their_name(self, printed):
        assert '东京物産株式会社' in printed, printed[:3000]

    def test_their_address_is_their_address(self, printed):
        assert '日本橋 1-2-3' in printed, printed[:3000]

    def test_the_sellers_name_keeps_its_accents(self, printed):
        assert 'Éditions Cliché Inc.' in printed, printed[:3000]

    def test_a_line_description_keeps_its_characters(self, printed):
        assert 'Conseil — étude de marché (½ journée)' in printed, printed

    def test_the_documents_notes_keep_theirs(self, printed):
        assert 'Livraison à Montréal — voir l\'entente №7' in printed, printed

    def test_both_free_text_blocks_keep_theirs(self, printed):
        assert 'Règlement par virement — merci' in printed, printed
        assert '担当: 山田さん' in printed, printed

    def test_nothing_arrived_as_a_question_mark(self, printed):
        """The shape the failure takes: one `?` per character the encoding
        could not hold, so a name becomes a run of them."""
        assert '???' not in printed, printed


def test_the_written_file_is_utf8_whatever_the_locale_says(tmp_path):
    """And the last hop, from Python to the user's file, is UTF-8 too.

    Three writes stand between the rendered page and the file — the combined
    HTML, the per-document HTML, and the plaintext — and `Path.write_text`
    with no encoding takes the locale's. That fails two ways on this document
    and neither is loud: under an ASCII locale it raises on `东` *after*
    having truncated the destination to nothing, which is the half-written
    output CLAUDE.md finding 14 exists to prevent; under a Latin-1 one it
    writes Latin-1 bytes into a file whose `<meta charset>` — GnuCash's own,
    carried into the combined page — says UTF-8, which no reader can see is
    wrong.

    Read back as bytes, so the assertion is about the file and not about how
    this process happens to read it. Under the suite's own environment, where
    the locale's answer is UTF-8 anyway — the locale test below is the one
    that fails without the fix.
    """
    book = _book_with_both_documents(tmp_path)

    for fmt, name in (('html', 'inv.html'), ('plaintext', 'inv.txt')):
        out = tmp_path / name
        rendered = CliRunner().invoke(cli, [
            'print-invoice', str(book), 'INV-UNICODE-001', '--format', fmt,
            '--output', str(out)])
        assert rendered.exit_code == 0, rendered.output

        assert '东京物産株式会社'.encode() in out.read_bytes(), (fmt, name)


# Asked of the child: Python's two answers, and Guile's — the last through the
# same loader the renderer uses, because that is the interpreter whose encoding
# `set-port-encoding!` is overriding, and it is initialised inside this process
# rather than inheriting anything Python decided.
_WHAT_ENCODING = '''
import locale, pathlib, sys, tempfile
from infrastructure.guile import load_guile
with tempfile.TemporaryDirectory() as work:
    answer = pathlib.Path(work) / "encoding"
    load_guile().scm_c_eval_string(
        ('(call-with-output-file "%s" (lambda (port) '
         '(display (fluid-ref %%default-port-encoding) port)))' % answer)
        .encode())
    guile_says = answer.read_text(encoding="ascii").strip()
print(locale.getpreferredencoding(False), sys.stdout.encoding, guile_says)
'''


def _assert_the_locale_took(env, cwd):
    """The child really cannot hold the page, before anything is asked of it.

    Without this the tests below can go vacuous and stay green: they are the
    only place the encoding fix is load-bearing, and a base image or CI
    wrapper that exported `PYTHONIOENCODING=utf-8` — or a future Python whose
    UTF-8 mode ignores these variables — would leave them asserting that a
    UTF-8 environment writes UTF-8, which needs no fix at all.

    Guile is asked as well as Python, and it is the more important of the two:
    `set-port-encoding!` is the half of the fix whose absence is *silent*, a
    `?` per character on a document that still looks like a document, where
    every Python hop raises. Nothing guarantees the two answer alike — GnuCash
    could call `setlocale` itself on init — so the guard would stay green over
    a vacuous Guile half if it only asked Python.
    """
    probe = subprocess.run([sys.executable, '-c', _WHAT_ENCODING],
                           env=env, cwd=cwd, capture_output=True, check=False)
    answered = probe.stdout.decode('ascii', 'replace').strip()

    assert probe.returncode == 0, probe.stderr.decode('utf-8', 'replace')
    assert len(answered.split()) == 3, (answered, probe.stderr[-500:])
    for encoding in answered.split():
        assert 'utf' not in encoding.lower(), (
            f'this environment can hold the page after all — the child '
            f'reports {answered!r} for (locale, stdout, guile) — so the tests '
            f'below prove nothing. Something in it (PYTHONIOENCODING, a UTF-8 '
            f'default, a setlocale of GnuCash\'s own) overrides '
            f'{sorted(ASCII_LOCALE)}.')


def _hostile_env():
    """The environment the commands below run in, built in one place.

    One function and not two copies of the same two lines: the guard's whole
    claim is that *this* environment cannot hold the page, and a guard that
    checks a sibling of what runs proves nothing the moment the two drift —
    someone popping another variable in one of them, or handling
    `PYTHONIOENCODING` differently, and the tests go quietly green under UTF-8.
    """
    env = {**os.environ, **ASCII_LOCALE}
    env.pop('PYTHONIOENCODING', None)
    return env


def _run_under_an_ascii_locale(args):
    """Run one command in a subprocess whose locale cannot hold the page.

    A subprocess because a locale is process-wide and the interpreter has
    already read its own. Usually only the step under test needs to be under
    it: `print-invoice` reads no plaintext — the book is gzipped XML that
    declares its own encoding, and the page comes from GnuCash's report — so
    the ledger can be imported normally beforehand.
    """
    return subprocess.run(
        [sys.executable, '-c', 'from cli.main import cli; cli()', *args],
        env=_hostile_env(), capture_output=True, check=False)


@pytest.fixture(scope='module')
def the_locale_can_be_made_hostile():
    """Checked once for the class that needs it, before any of it runs.

    Once rather than per test: it spawns an interpreter and initialises Guile
    to ask, and the answer is a property of the environment rather than of any
    one case.

    Asked for by name rather than `autouse`, because only the class below can
    go vacuous without it. The rest of this file runs `CliRunner` in-process
    under the suite's ordinary UTF-8 environment and never touches
    `ASCII_LOCALE`, so an image where the locale cannot be made hostile —
    which is precisely what this guard exists to notice — should cost those
    tests nothing rather than take the whole module down with it.
    """
    _assert_the_locale_took(_hostile_env(), Path.cwd())


@pytest.mark.usefixtures('the_locale_can_be_made_hostile')
class TestUnderALocaleThatCannotHoldThePage:
    """Where the fix is load-bearing, and the only place it can be seen.

    Every hop is UTF-8 by explicit statement now, so under the suite's usual
    environment removing any of them changes nothing — the locale would have
    said UTF-8 anyway. Under this one it does not: `set-port-encoding!` is
    what stops Guile writing `?` for every character it cannot hold, and the
    `encoding=` arguments are what stop the read and the write raising.
    """

    def test_the_html_keeps_its_characters(self, tmp_path):
        book = _book_with_both_documents(tmp_path)
        out = tmp_path / 'inv.html'

        done = _run_under_an_ascii_locale([
            'print-invoice', str(book), 'INV-UNICODE-001', '--format', 'html',
            '--output', str(out)])

        assert done.returncode == 0, done.stderr.decode('utf-8', 'replace')
        written = out.read_bytes()
        assert '东京物産株式会社'.encode() in written, written[:2000]
        assert 'Éditions Cliché Inc.'.encode() in written, written[:2000]
        assert b'???' not in written, written[:2000]

    def test_a_report_named_in_more_than_ascii_reaches_guile_intact(
            self, tmp_path):
        """The expression itself is UTF-8, not just what it writes.

        `--report` is the first user-typed string this tool ever hands to a
        Scheme evaluator, and `scm_c_eval_string` decodes what it is given
        with the *locale's* charset. Measured under this environment on 5.10
        and 3.8: a 17-character name went in and 19 characters came out, each
        UTF-8 byte read as its own character — no error, no exit code, an
        expression evaluated against a string nobody typed.

        Asserted through the refusal, which quotes the name back: a reader who
        types what their localized GnuCash showed them gets a sentence naming
        what they typed, not a mangling of it. `scm_from_utf8_string` plus
        `scm_eval_string` is what makes that true.
        """
        book = _book_with_both_documents(tmp_path)

        done = _run_under_an_ascii_locale([
            'print-invoice', str(book), 'INV-UNICODE-001', '--format', 'html',
            '--output', str(tmp_path / 'inv.html'),
            '--report', 'Facture améliorée'])

        assert done.returncode != 0
        said = done.stdout.decode('utf-8', 'replace') + \
            done.stderr.decode('utf-8', 'replace')
        assert 'no report of that name' in said.lower(), said
        assert 'Facture améliorée' in said, said

    def test_the_plaintext_keeps_its_characters(self, tmp_path):
        book = _book_with_both_documents(tmp_path)
        out = tmp_path / 'inv.txt'

        done = _run_under_an_ascii_locale([
            'print-invoice', str(book), 'INV-UNICODE-001', '--format',
            'plaintext', '--output', str(out)])

        assert done.returncode == 0, done.stderr.decode('utf-8', 'replace')
        assert '东京物産株式会社'.encode() in out.read_bytes()

    def test_stdout_keeps_them_too(self, tmp_path):
        """`-o -` is a fourth hop of its own — `sys.stdout` takes the locale's
        encoding like any other text handle, and this is the form the README
        pipes back into `import`."""
        book = _book_with_both_documents(tmp_path)

        done = _run_under_an_ascii_locale([
            'print-invoice', str(book), 'INV-UNICODE-001', '--format',
            'plaintext', '--output', '-'])

        assert done.returncode == 0, done.stderr.decode('utf-8', 'replace')
        assert '东京物産株式会社'.encode() in done.stdout, done.stdout[:2000]

    def test_a_bill_keeps_them_as_well(self, tmp_path):
        """The bill command got the same four changes and shares the renderer,
        so it is checked rather than assumed."""
        book = _book_with_both_documents(tmp_path)
        out = tmp_path / 'bill.html'

        done = _run_under_an_ascii_locale([
            'print-bill', str(book), 'BILL-UNICODE-001', '--format', 'html',
            '--output', str(out)])

        assert done.returncode == 0, done.stderr.decode('utf-8', 'replace')
        written = out.read_bytes()
        assert 'Fournitures Léger & Frère'.encode() in written, written[:2000]
        assert "Papeterie — cartouches d'encre".encode() in written

    def test_validate_reports_on_a_book_it_cannot_spell_in_ascii(self,
                                                                 tmp_path):
        """`validate book.gnucash` with no `--report`, which is the usual form.

        A report names what it found, so it holds whatever the book holds:
        this one warns about `Income:Dépenses accessoires`, an Expense account
        under Income. Written to stdout with a bare `print`, the command
        failed outright on a book it had nothing to say against — the accent
        was in the warning, not in the problem.
        """
        book = _book_with_both_documents(tmp_path)

        done = _run_under_an_ascii_locale(['validate', str(book)])

        assert done.returncode == 0, done.stderr.decode('utf-8', 'replace')
        assert 'Income:Dépenses accessoires'.encode() in done.stdout, \
            done.stdout[:2000]

    def test_a_ledger_round_trips_through_export_and_import(self, tmp_path):
        """The whole cycle this tool exists for, under the same locale.

        Printing was one command of several reading and writing this format,
        and all of them took the locale's answer: the exporter's `open(…,
        'w')` truncated the destination and then raised on the first accented
        character — the half-written output CLAUDE.md finding 14 forbids — and
        the parser could not read a ledger back that named anybody outside
        ASCII. So export → import is run here end to end, in a locale that
        cannot hold either document, and the customer and vendor have to
        arrive in the second book as themselves.
        """
        book = _book_with_both_documents(tmp_path)
        exported = tmp_path / 'round-trip.txt'

        out = _run_under_an_ascii_locale([
            'export', str(book), str(exported), '--include-business-objects'])
        assert out.returncode == 0, out.stderr.decode('utf-8', 'replace')
        assert '东京物産株式会社'.encode() in exported.read_bytes()

        fresh = tmp_path / 'fresh.gnucash'
        back = _run_under_an_ascii_locale([
            'import', '--new', str(fresh), str(exported),
            '--include-business-objects'])
        assert back.returncode == 0, back.stderr.decode('utf-8', 'replace')

        again = tmp_path / 'again.html'
        printed = _run_under_an_ascii_locale([
            'print-invoice', str(fresh), 'INV-UNICODE-001', '--format',
            'html', '--output', str(again)])
        assert printed.returncode == 0, printed.stderr.decode('utf-8',
                                                              'replace')
        assert '东京物産株式会社'.encode() in again.read_bytes()


class TestTheBillSideOfThePage:
    @pytest.fixture
    def printed_bill(self, tmp_path):
        book = _book_with_both_documents(tmp_path)
        out = tmp_path / 'bill.html'
        rendered = CliRunner().invoke(cli, [
            'print-bill', str(book), 'BILL-UNICODE-001', '--format', 'html',
            '--output', str(out)])
        assert rendered.exit_code == 0, rendered.output
        return out.read_text(encoding='utf-8')

    def test_the_vendors_name_is_their_name(self, printed_bill):
        assert 'Fournitures Léger & Frère' in printed_bill, printed_bill[:3000]

    def test_the_line_and_the_notes_keep_their_characters(self, printed_bill):
        assert "Papeterie — cartouches d'encre" in printed_bill, printed_bill
        assert 'Reçu par courriel' in printed_bill, printed_bill

    def test_the_vendors_own_free_text_is_printed(self, printed_bill):
        assert 'Référence fournisseur: №4501' in printed_bill, printed_bill
