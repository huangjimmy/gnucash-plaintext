"""Whether rendering a page leaves Guile holding a port on descriptor 0, 1 or 2, and whether collecting it closes that descriptor.

Guile closes a file port's descriptor when the garbage collector finalizes a
port that is still open, on a thread of its own, at a time that depends on the
collector. A second port on standard input, output or error would then close
that descriptor out from under the process whenever it happened to be
collected.

This builds the printed-page book, prints its invoice in this process, lists
every port Guile holds with its descriptor, forces a collection, waits for the
finalizer thread, lists the ports again, and says whether descriptors 0, 1 and
2 are still open.

Measured 2026-09-14 on 3.8, 4.4 and 5.10, under `strace -f`: after printing,
Guile holds one port on each of descriptors 0, 1 and 2 and none other; three
collections closed nothing, and no call closed or duplicated onto 0, 1 or 2.
So a render leaves no second port on a standard descriptor. The descriptors
lost on 3.4, 3.8 and 4.4 were closed by a session that took no lock
(CLAUDE.md finding 27).

Run under strace to see which thread closes what:

    docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp/home \
        -e PYTHONPATH=/workspace -v "$PWD:/workspace" -w /workspace \
        gnucash-dev:<tag> python3 tests/research/whether_a_render_leaves_a_port_on_a_standard_descriptor_probe.py
"""

import os
import sys
import tempfile
import time

from cli.main import cli
from infrastructure.guile import load_guile

LEDGER = 'tests/fixtures/an_invoice_in_more_than_ascii.txt'


def say(text):
    """To a file of its own, so the answer survives descriptors 1 and 2 being closed."""
    with open(os.environ.get('PROBE_OUT', '/tmp/probe-out.txt'), 'a', encoding='utf-8') as out:
        out.write(text + '\n')


def run(*args):
    try:
        cli.main(list(args), standalone_mode=False)
    except SystemExit as done:
        say(f'  {args[0]} exited {done.code}')


def list_ports(lib, work, heading):
    listing = os.path.join(work, 'ports.txt')
    lib.scm_c_eval_string((
        f'(call-with-output-file "{listing}" (lambda (out)'
        f'  (port-for-each (lambda (p)'
        f'    (write (list (false-if-exception (port-filename p))'
        f'                 (false-if-exception (fileno p))'
        f'                 (port-closed? p))'
        f'           out)'
        f'    (newline out)))))').encode())
    say(heading)
    with open(listing, encoding='utf-8') as ports:
        for line in ports:
            say('  ' + line.rstrip())


def standard_descriptors():
    state = []
    for fd in (0, 1, 2):
        try:
            os.fstat(fd)
            state.append(f'{fd} open')
        except OSError as err:
            state.append(f'{fd} CLOSED ({err.strerror})')
    return ', '.join(state)


def main():
    work = tempfile.mkdtemp()
    book = os.path.join(work, 'unicode.gnucash')
    say(f'pid {os.getpid()}; before anything: {standard_descriptors()}')
    run('import', '--new', book, LEDGER, '--include-business-objects')
    run('print-invoice', book, 'INV-UNICODE-001', '--format', 'plaintext',
        '--output', os.path.join(work, 'inv.txt'))
    say(f'after printing: {standard_descriptors()}')

    lib = load_guile()
    list_ports(lib, work, 'ports Guile holds after printing:')
    for _ in range(3):
        lib.scm_c_eval_string(b'(gc)')
        time.sleep(1)
    say(f'after three collections: {standard_descriptors()}')
    list_ports(lib, work, 'ports Guile holds after three collections:')
    sys.stdout.flush()


if __name__ == '__main__':
    main()
