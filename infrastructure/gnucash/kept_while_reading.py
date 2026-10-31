"""What is read from a book once and kept, while every book open is open only to read (Q-058).

A read command asks the same book the same thing many times over: a balance
sheet walks every split about five times, each walk asking GnuCash for every
account's split list and every split for its custom metadata, and in a batch
the next command asks again. Nothing changes a book open to read, so the first
answer is kept and handed back.

Only then. In a book that may change, a kept answer is wrong for an object
whose slot changed, or for a new object made where a deleted one was. So the
repository turns keeping on only while every book open in the process is open
to read, and calls `keep_what_is_read` again, emptying every store, whenever
a book is opened or closed.
"""

#: Each store a reader keeps its answers in, emptied together.
_STORES = []
_keeping = False


def kept_while_reading(store: dict) -> dict:
    """Register `store` to be emptied whenever keeping is turned on or off."""
    _STORES.append(store)
    return store


def keep_what_is_read(keep: bool) -> None:
    """Keep what is read from here on, or stop; either way every store starts empty."""
    global _keeping
    _keeping = keep
    for store in _STORES:
        store.clear()


def keeping_what_is_read() -> bool:
    return _keeping
