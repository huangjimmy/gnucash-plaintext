"""How `import --strategy update` of a book's own export, unchanged, grows with the book, and where the time goes.

Measured first on 5,000 transactions by
`how_long_an_edit_read_as_new_takes_on_a_large_book_probe.py`: importing them
into a new book took 46.3 s, and re-importing the book's own export with
`--strategy update`, nothing changed, was still running after 8 minutes. So
this builds the same mix at several sizes and times only that unchanged
update, printing as it goes, and profiles the largest.

Measured on Debian 13 (GnuCash 5.10), new book / unchanged update: 1.5 / 9.2,
3.3 / 34.8 and 9.7 / 216.3 s at 500, 1,000 and 2,000 transactions before the
fixes, and 0.7 / 1.1, 2.1 / 3.2 and 7.1 / 15.8 s once no step walked the whole
book per transaction. Every build, and what each fix changed, is in the
section "How long an update takes as the book grows" of
`docs/issues/Q-051-let-a-statement-line-on-a-holding-account-be-edited-into-the-invoice-or-bill-it-settles.md`.
A transaction the file states as the book holds it is no longer edited, so
this probe's unchanged update now measures reading the file and the book.

The mix, as counts of transactions, is the same proportions: three fifths in
Canadian dollars only, one fifth buying US dollars, four twenty-fifths selling
them, one twenty-fifth statement lines with a fee.

Run, with the project installed in the container as `scripts/test.sh` does:

    docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp/home \
        -e PYTHONPATH=/workspace -v "$PWD:/workspace" -w /workspace \
        gnucash-dev:<tag> sh -c 'python3 -m pip install -e ".[dev]" \
            --break-system-packages --user -q && python3 -u \
            tests/research/how_long_an_unchanged_update_takes_as_a_book_grows_probe.py'
"""

import cProfile
import io
import pstats
import shutil
import tempfile
import time
from pathlib import Path

import tests.research.how_long_an_edit_read_as_new_takes_on_a_large_book_probe as big
from tests.research.how_long_an_edit_read_as_new_takes_on_a_large_book_probe import run

SIZES = (500, 1000, 2000)


def main():
    for size in SIZES:
        big.PLAIN = size * 3 // 5
        big.PURCHASES = size // 5
        big.SALES = size * 4 // 25
        big.LINES = size // 25
        work = Path(tempfile.mkdtemp())
        source = work / 'ledger.txt'
        source.write_text(big.ledger())
        book = work / 'book.gnucash'
        started = time.perf_counter()
        run('import', '--new', book, source)
        built = time.perf_counter() - started
        exported = work / 'exported.txt'
        run('export', book, exported)
        profiler = cProfile.Profile() if size == SIZES[-1] else None
        started = time.perf_counter()
        if profiler:
            profiler.enable()
        run('import', book, exported, '--strategy', 'update')
        if profiler:
            profiler.disable()
        print(f'{size:>5} transactions: new book {built:6.1f} s, '
              f'unchanged update {time.perf_counter() - started:6.1f} s')
        if profiler:
            out = io.StringIO()
            pstats.Stats(profiler, stream=out).sort_stats('cumulative').print_stats(45)
            print(out.getvalue())
            out = io.StringIO()
            pstats.Stats(profiler, stream=out).sort_stats('tottime').print_stats(25)
            print(out.getvalue())
        shutil.rmtree(work)


if __name__ == '__main__':
    main()
