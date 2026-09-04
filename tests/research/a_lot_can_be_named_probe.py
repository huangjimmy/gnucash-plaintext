"""Can a lot be found by its guid, and can a lot be given one?

A split says whose credit it is with `lot_owner:`, and an owner may hold more
than one credit — so which lot a split joins is decided by the import, not by
the file: the oldest open lot the split would reduce. Naming the lot needs two
things from the engine, and neither can be read off a header:

1. the QOF type a lot is collected under, so `qof_collection_lookup_entity`
   can find one — `GNC_ID_LOT` is `"Lot"` in `gnc-lot.h`, and what matters is
   what the collection actually answers to;
2. that a lot's guid can be forced with `qof_instance_set_guid` and comes
   back the same after a save and a reload, the way an account's or an
   invoice's does.

**And the trap under (2)**, which is CLAUDE.md §11 in a new place:
`qof_instance_set_guid` marks nothing dirty, so a session whose *only* change
is a forced guid writes nothing at all — the guid reads back for the rest of
that session and the book on disk keeps the old one. Once anything else has
made the book dirty, the file is rewritten whole and the forced guid goes out
with it. Measured below both ways, in that order.

Nothing here is a hazard for the import, which forces a lot's guid only where
it has just created the lot and put a split in it — but a command that means
to *rename* a lot and does nothing else would save nothing and say it had.

Run: ./scripts/test.sh <tag> tests/research/a_lot_can_be_named_probe.py
"""

import ctypes

from click.testing import CliRunner

from cli.main import cli
from infrastructure.gnucash.engine import guid_from_hex, load_gnc_engine
from infrastructure.gnucash.utils import get_account_full_name, qof_pointer
from repositories.gnucash_repository import GnuCashRepository, SessionMode

ALONE = 'c0ffee11c0ffee11c0ffee11c0ffee11'
WITH_A_WRITE = 'decafbad22decafbad22decafbad2222'

LEDGER = """2026-01-01 commodity CAD
\tmnemonic: "CAD"
\tfullname: "Canadian Dollar"
\tnamespace: "CURRENCY"
\tfraction: 100
2026-01-01 open Assets
\ttype: Asset
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Assets:Bank
\ttype: Bank
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Assets:Accounts Receivable
\ttype: Accounts Receivable
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"

customer "C-LOT"
\tname: "Lot Ltd"
\tcurrency: CAD

2026-01-05 * "First deposit on account"
\tAssets:Bank 50.00 CAD
\tAssets:Accounts Receivable -50.00 CAD
\t\tlot_owner: "customer:C-LOT"

2026-02-05 * "Second deposit on account"
\tAssets:Bank 80.00 CAD
\tAssets:Accounts Receivable -80.00 CAD
\t\tlot_owner: "customer:C-LOT"
"""


def _guid_of(lib, obj) -> str:
    lib.qof_instance_get_guid.argtypes = [ctypes.c_void_p]
    lib.qof_instance_get_guid.restype = ctypes.c_void_p
    lib.guid_to_string_buff.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
    lib.guid_to_string_buff.restype = ctypes.c_char_p
    guid_ptr = lib.qof_instance_get_guid(qof_pointer(obj))
    if not guid_ptr:
        return ''
    buf = ctypes.create_string_buffer(40)
    lib.guid_to_string_buff(guid_ptr, buf)
    return buf.value.decode('ascii')


def _the_credit_lots(book):
    """Both open credit lots, in the order the receivable lists them."""
    for account in book.get_root_account().get_descendants():
        if get_account_full_name(account) != 'Assets:Accounts Receivable':
            continue
        lots = account.GetLotList()
        assert len(lots) == 2, f'{len(lots)} lots on the receivable'
        return lots
    raise AssertionError('no receivable')


def _declare(lib):
    lib.qof_instance_set_guid.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    lib.qof_instance_set_guid.restype = None
    for name in ('gnc_lot_begin_edit', 'gnc_lot_commit_edit'):
        getattr(lib, name).argtypes = [ctypes.c_void_p]
        getattr(lib, name).restype = None
    lib.gnc_lot_set_title.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
    lib.gnc_lot_set_title.restype = None


def test_what_get_lot_list_hands_back(tmp_path):
    """Which of the two shapes this build's `GetLotList()` yields.

    Measured on all ten supported builds: a raw `SwigPyObject` on GnuCash
    3.8, 4.4, 4.8, 4.13, 5.5, 5.10, 5.13 and 5.14, and a wrapped `GncLot` on
    5.15 and 5.16 — a version boundary, not a distribution's doing. `int()`
    refuses the wrapper outright, so a reader written against either half
    raises on the other; `qof_pointer` is what makes the difference stop
    mattering, and this says which shape a build is in when one of them
    starts behaving differently again.
    """
    ledger = tmp_path / 'in.txt'
    ledger.write_text(LEDGER, encoding='utf-8')
    book_path = tmp_path / 'book.gnucash'
    made = CliRunner().invoke(cli, ['import', '--new', str(book_path),
                                    str(ledger), '--include-business-objects'])
    assert made.exit_code == 0, made.output

    repo = GnuCashRepository(str(book_path))
    repo.open(SessionMode.READ_ONLY)
    try:
        first = _the_credit_lots(repo.book)[0]
        assert type(first).__name__ in ('SwigPyObject', 'GncLot'), \
            type(first).__name__
        # Either way `qof_pointer` reaches the same lot, which is the whole
        # point of it.
        assert qof_pointer(first) == qof_pointer(qof_pointer(first))
    finally:
        repo.close()


def test_a_lot_answers_to_its_guid_and_takes_one(tmp_path):
    ledger = tmp_path / 'in.txt'
    ledger.write_text(LEDGER, encoding='utf-8')
    book_path = tmp_path / 'book.gnucash'
    made = CliRunner().invoke(cli, ['import', '--new', str(book_path),
                                    str(ledger), '--include-business-objects'])
    assert made.exit_code == 0, made.output

    lib = load_gnc_engine()
    _declare(lib)
    report = []

    repo = GnuCashRepository(str(book_path))
    repo.open(SessionMode.NORMAL)
    try:
        first, second = _the_credit_lots(repo.book)
        was = [_guid_of(lib, first), _guid_of(lib, second)]
        report.append(f'lot guids as created: {was}')

        found = {}
        for type_name in (b'Lot', b'GNCLot', b'gncLot'):
            collection = lib.qof_book_get_collection(int(repo.book.instance),
                                                     type_name)
            answer = lib.qof_collection_lookup_entity(
                collection, ctypes.byref(guid_from_hex(was[0])))
            found[type_name] = (answer == qof_pointer(first))
            report.append(f'collection {type_name!r}: found={answer} '
                          f'is_the_lot={found[type_name]}')

        # A guid, and nothing else in the whole session.
        lib.gnc_lot_begin_edit(qof_pointer(first))
        lib.qof_instance_set_guid(qof_pointer(first),
                                  ctypes.byref(guid_from_hex(ALONE)))
        lib.gnc_lot_commit_edit(qof_pointer(first))
        report.append(f'in that session: {_guid_of(lib, first)!r}')
        repo.save()
    finally:
        repo.close()

    repo = GnuCashRepository(str(book_path))
    repo.open(SessionMode.READ_ONLY)
    try:
        alone_back = sorted(_guid_of(lib, lot)
                            for lot in _the_credit_lots(repo.book))
        report.append(f'after that save and a reload: {alone_back}')
    finally:
        repo.close()

    repo = GnuCashRepository(str(book_path))
    repo.open(SessionMode.NORMAL)
    try:
        first, second = _the_credit_lots(repo.book)
        # The same guid again, and this time something else is written too.
        lib.gnc_lot_begin_edit(qof_pointer(first))
        lib.qof_instance_set_guid(qof_pointer(first),
                                  ctypes.byref(guid_from_hex(ALONE)))
        lib.gnc_lot_commit_edit(qof_pointer(first))
        lib.gnc_lot_begin_edit(qof_pointer(second))
        lib.gnc_lot_set_title(qof_pointer(second), b'named by the probe')
        lib.gnc_lot_commit_edit(qof_pointer(second))
        repo.save()
    finally:
        repo.close()

    repo = GnuCashRepository(str(book_path))
    repo.open(SessionMode.READ_ONLY)
    try:
        beside_back = sorted(_guid_of(lib, lot)
                             for lot in _the_credit_lots(repo.book))
        report.append(f'after a save that wrote something: {beside_back}')
        said = '\n'.join(report)

        assert all(len(guid) == 32 for guid in was), said
        # `GNC_ID_LOT` is `"Lot"`, and it is the collection that answers.
        assert found[b'Lot'], said
        assert not found[b'GNCLot'] and not found[b'gncLot'], said
        # A guid on its own saved nothing: both lots came back as they were.
        assert alone_back == sorted(was), said
        # Beside a write, the same guid is the book's.
        assert ALONE in beside_back, said
    finally:
        repo.close()
