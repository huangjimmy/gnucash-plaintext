"""What GnuCash says to a path it cannot follow, for each way a book is opened.

Three paths, each in a child process of its own:

  loop        a symbolic link that points at itself
  through     a path that runs through a regular file, `file.txt/book.gnucash`
  too-long    a file name of 300 characters, longer than the file system allows

Run on one build:

    docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp \\
        -v "$PWD":/workspace -w /workspace gnucash-dev:<tag> bash -c \\
        'python3 -m pip install -e ".[dev]" --user -q --break-system-packages \\
         || python3 -m pip install -e ".[dev]" --user -q; \\
         python3 tests/research/what_gnucash_says_to_a_path_it_cannot_follow_probe.py'
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

CHILD = r'''
import sys
from repositories.gnucash_repository import BookUnavailableError, GnuCashRepository, SessionMode
modes = {'read': SessionMode.READ_ONLY, 'write': SessionMode.NORMAL, 'new': SessionMode.NEW}
repo = GnuCashRepository(sys.argv[1])
try:
    repo.open(modes[sys.argv[2]])
    print('opened')
    repo.close()
except BookUnavailableError as e:
    print('refused:', e.__cause__ if e.__cause__ is not None else e)
except Exception as e:
    print('raised', type(e).__name__, e)
'''

with tempfile.TemporaryDirectory() as directory:
    directory = Path(directory)
    loop = directory / 'loop.gnucash'
    os.symlink(str(loop), str(loop))
    regular = directory / 'file.txt'
    regular.write_text('not a directory\n')
    paths = {
        'loop': str(loop),
        'through': str(regular / 'book.gnucash'),
        'too-long': str(directory / ('a' * 300 + '.gnucash')),
    }
    for name, path in paths.items():
        for mode in ('read', 'write', 'new'):
            done = subprocess.run([sys.executable, '-c', CHILD, path, mode],
                                  capture_output=True, text=True)
            said = [line for line in done.stdout.splitlines()
                    if line.startswith(('opened', 'refused', 'raised'))]
            print(f'{name:9} {mode:5} exit {done.returncode:4}  {said[-1] if said else "(nothing)"}')
