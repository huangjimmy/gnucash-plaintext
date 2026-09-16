"""A PDF is drawn on a display number nothing else holds.

Printing starts its own X server for WebKit to draw into, on the first number
from :99 to :129 that is free. Two things make a number not free: a lock file
in `/tmp` left by a server, running or long dead, and a server that holds the
number's socket. A lock file is passed over without trying the number; a
number another server holds is tried, lost, and the next one taken — the race
two prints started together run.

And where every number is held, there is no display to draw on, and the print
says so rather than letting WebKit's own error out, and takes the cookies it
made for the attempt with it.
"""

import os
import shutil
import subprocess
import time
from pathlib import Path

from click.testing import CliRunner

from cli.main import cli

FIXTURES = Path('tests/fixtures')
ACCOUNTS = str(FIXTURES / 'q019_accounts.txt')
BILLS = str(FIXTURES / 'two_bills_to_print.txt')


def _book(tmp_path):
    runner = CliRunner()
    gnc = tmp_path / 'book.gnucash'
    created = runner.invoke(cli, ['import', '--new', str(gnc), ACCOUNTS])
    assert created.exit_code == 0, created.output
    imported = runner.invoke(cli, ['import', str(gnc), BILLS, '--include-business-objects'])
    assert imported.exit_code == 0, imported.output
    return gnc


def _cookies():
    return set(Path('/tmp').glob('gnucash-xauth-*'))


def test_every_number_held_by_a_lock_file_is_said_and_leaves_no_cookies(tmp_path, monkeypatch):
    monkeypatch.delenv('DISPLAY', raising=False)
    gnc = _book(tmp_path)
    made = [Path(f'/tmp/.X{number}-lock') for number in range(99, 130)
            if not Path(f'/tmp/.X{number}-lock').exists()]
    before = _cookies()
    try:
        for lock in made:
            lock.write_text('0\n')

        result = CliRunner().invoke(cli, [
            'print-bill', str(gnc), 'BILL-PRINT-001', '--format', 'pdf',
            '-o', str(tmp_path / 'bill.pdf')])
    finally:
        for lock in made:
            lock.unlink()

    assert result.exit_code != 0, result.output
    assert ('every display number from :99 to :129 is held by a lock file in /tmp'
            in result.output), result.output
    assert not (tmp_path / 'bill.pdf').exists()
    assert _cookies() == before


def test_a_number_another_server_holds_is_lost_and_the_next_one_taken(tmp_path, monkeypatch):
    monkeypatch.delenv('DISPLAY', raising=False)
    gnc = _book(tmp_path)
    socket = Path('/tmp/.X11-unix/X99')
    other = subprocess.Popen(['Xvfb', ':99', '-nolisten', 'tcp'],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            if socket.exists():
                break
            time.sleep(0.05)
        assert socket.exists(), 'the other server never started'
        # The lock file gone and the server still there: what a print sees
        # when another print has just taken :99 and not yet written its lock.
        Path('/tmp/.X99-lock').unlink()

        result = CliRunner().invoke(cli, [
            'print-bill', str(gnc), 'BILL-PRINT-001', '--format', 'pdf',
            '-o', str(tmp_path / 'bill.pdf')])
    finally:
        other.terminate()
        other.wait(timeout=5)
        shutil.rmtree('/tmp/.X11-unix/X99', ignore_errors=True)

    assert result.exit_code == 0, result.output
    assert (tmp_path / 'bill.pdf').read_bytes().startswith(b'%PDF')


def _a_program_first_on_the_path(tmp_path, monkeypatch, name, script):
    """A program called `name` that runs `script`, found before the real one."""
    programs = tmp_path / 'programs'
    programs.mkdir(exist_ok=True)
    program = programs / name
    program.write_text(f'#!/bin/sh\n{script}\n')
    program.chmod(0o755)
    monkeypatch.setenv('PATH', f'{programs}:{os.environ["PATH"]}')


def test_a_display_xauth_makes_no_cookie_for_is_still_drawn_on(tmp_path, monkeypatch):
    """Where `xauth` cannot write the cookie, the server starts without one.

    It is still local-only, since it does not listen on TCP, and refusing the
    print over a helper that failed is the worse answer.
    """
    monkeypatch.delenv('DISPLAY', raising=False)
    gnc = _book(tmp_path)
    _a_program_first_on_the_path(tmp_path, monkeypatch, 'xauth', 'exit 1')

    result = CliRunner().invoke(cli, [
        'print-bill', str(gnc), 'BILL-PRINT-001', '--format', 'pdf',
        '-o', str(tmp_path / 'bill.pdf')])

    assert result.exit_code == 0, result.output
    assert (tmp_path / 'bill.pdf').read_bytes().startswith(b'%PDF')


def test_a_server_that_never_makes_its_socket_is_given_up_on_and_said(tmp_path, monkeypatch):
    """An `Xvfb` that runs and never listens is tried number after number, for
    as long as the search is allowed, and then the print says no server would
    start, and takes the cookies it made with it."""
    from infrastructure.pdf import printing

    monkeypatch.delenv('DISPLAY', raising=False)
    gnc = _book(tmp_path)
    _a_program_first_on_the_path(tmp_path, monkeypatch, 'Xvfb', 'exec sleep 30')
    monkeypatch.setattr(printing, 'WAIT_FOR_THE_SOCKET', 0.2)
    monkeypatch.setattr(printing, 'STOP_LOOKING_FOR_A_DISPLAY_AFTER', 0.5)
    before = _cookies()

    result = CliRunner().invoke(cli, [
        'print-bill', str(gnc), 'BILL-PRINT-001', '--format', 'pdf',
        '-o', str(tmp_path / 'bill.pdf')])

    assert result.exit_code != 0, result.output
    assert 'no X server would start on any of the' in result.output, result.output
    assert not (tmp_path / 'bill.pdf').exists()
    assert _cookies() == before
