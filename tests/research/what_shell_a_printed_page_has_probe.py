"""Probe: the outer shell GnuCash puts around a page it draws.

`test_one_page_is_the_same_page_whichever_way_it_is_written` looks for
`<!DOCTYPE`, `<html` and `<body` in the page written straight to a directory,
and on GnuCash 3.4 one of them is not there — the search raises rather than
the comparison failing. This says which, and what the page opens with instead.

    ./scripts/test.sh debian10 tests/research/what_shell_a_printed_page_has_probe.py
    ./scripts/test.sh latest   tests/research/what_shell_a_printed_page_has_probe.py
"""

from pathlib import Path

from click.testing import CliRunner

from cli.main import cli
from tests.integration.test_cli_print_combined_html_structure import (
    _book_with_two_invoices,
)


def test_what_the_page_opens_with(tmp_path, capsys):
    runner = CliRunner()
    gnc, id1, _ = _book_with_two_invoices(runner, tmp_path)

    one_file = tmp_path / 'one.html'
    assert runner.invoke(cli, [
        'print-invoice', str(gnc), id1, '--format', 'html',
        '-o', str(one_file)]).exit_code == 0
    outdir = tmp_path / 'perdoc'
    assert runner.invoke(cli, [
        'print-invoice', str(gnc), id1, '--format', 'html',
        '-o', f'{outdir}/']).exit_code == 0

    combined = one_file.read_text()
    verbatim = (Path(outdir) / f'{id1}.html').read_text()

    with capsys.disabled():
        print()
        for label, text in (('verbatim', verbatim), ('combined', combined)):
            print(f'--- {label}: first 200 characters')
            print(repr(text[:200]))
            for tag in ('<!DOCTYPE', '<html', '<body'):
                print(f'    {tag:<12} present: {tag in text}')
