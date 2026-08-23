"""Which objects in a book have a guid, for the blocks that write none.

The format writes `guid:` on an account, a commodity's block excepted, on a
transaction, a split, a customer, a vendor, a tax table, an invoice, a bill
and — since lines gained an identity — an invoice or bill line. What is left
is measured here, so "this block has no guid" is a statement about GnuCash
rather than about what anyone remembered:

- a **tax table's `entry:`** line, the one repeated block that names no guid
  on export;
- a **commodity**, identified in this format by namespace and mnemonic;
- a **lot**, which `lot_owner:` and `open_prepayment:` describe by owner;
- the **book** itself, which the `company` block describes.

Run: ./scripts/test.sh <tag> tests/research/which_objects_have_a_guid_probe.py
"""

import ctypes

from click.testing import CliRunner

from cli.main import cli
from infrastructure.gnucash.engine import load_gnc_engine
from infrastructure.gnucash.utils import get_account_full_name
from repositories.gnucash_repository import GnuCashRepository, SessionMode

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
2026-01-01 open Income
\ttype: Income
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Income:Sales
\ttype: Income
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"

customer "C-G"
\tname: "Guid Ltd"
\tcurrency: CAD

invoice "INV-G-001"
\tcustomer_id: "C-G"
\tcurrency: CAD
\tdate_opened: 2026-02-01
\tentry:
\t\tdate: 2026-02-01
\t\tdescription: "A line"
\t\taccount: "Income:Sales"
\t\tquantity: 1
\t\tprice: 65
\t\ttaxable: #False
\t\ttax_included: #False
\tposted:
\t\tdate: 2026-02-01
\t\tdue: 2026-03-03
\t\tar_account: "Assets:Accounts Receivable"
\t\tmemo: "INV-G-001"
\t\taccumulate: #True
\tpayment:
\t\tdate: 2026-02-10
\t\tamount: 65.00
\t\tbank_account: "Assets:Bank"
\t\tmemo: "Paid"
"""


def _guid_of(lib, obj) -> str:
    """The guid of anything with a `qof_instance`, or `''` for none.

    Takes a wrapped object or the raw pointer some getters hand back —
    `Account.GetLotList()` returns `SwigPyObject`s, which carry no
    `.instance` of their own.
    """
    instance = getattr(obj, 'instance', obj)
    lib.qof_instance_get_guid.argtypes = [ctypes.c_void_p]
    lib.qof_instance_get_guid.restype = ctypes.c_void_p
    lib.guid_to_string_buff.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
    lib.guid_to_string_buff.restype = ctypes.c_char_p
    guid_ptr = lib.qof_instance_get_guid(int(instance))
    if not guid_ptr:
        return ''
    buf = ctypes.create_string_buffer(40)
    lib.guid_to_string_buff(guid_ptr, buf)
    return buf.value.decode('ascii')


def test_what_each_one_answers(tmp_path):
    ledger = tmp_path / 'in.txt'
    ledger.write_text(LEDGER, encoding='utf-8')
    book_path = tmp_path / 'book.gnucash'
    made = CliRunner().invoke(cli, ['import', '--new', str(book_path),
                                    str(ledger), '--include-business-objects'])
    assert made.exit_code == 0, made.output

    repo = GnuCashRepository(str(book_path))
    repo.open(SessionMode.READ_ONLY)
    try:
        lib = load_gnc_engine()
        answers = {}

        commodity = repo.book.get_table().lookup('CURRENCY', 'CAD')
        answers['commodity'] = _guid_of(lib, commodity)
        answers['book'] = _guid_of(lib, repo.book)

        for account in repo.book.get_root_account().get_descendants():
            if get_account_full_name(account) != 'Assets:Accounts Receivable':
                continue
            lots = account.GetLotList()
            answers['lots'] = len(lots)
            answers['lot'] = _guid_of(lib, lots[0]) if lots else ''

        # A tax table entry answers account, amount, type and its table, and
        # nothing else: `nm -D libgnc-engine.so | grep gncTaxTableEntry` lists
        # Compare, Create, Destroy, Equal, GetAccount, GetAmount, GetTable,
        # GetType, SetAccount, SetAmount, SetType. There is no accessor to
        # call here because there is no guid on the struct to read.
        answers['tax table entry accessors'] = sorted(
            name for name in dir(lib) if name.startswith('gncTaxTableEntry'))

        said = '\n'.join(f'{k}: {v!r}' for k, v in sorted(answers.items()))
        assert len(answers['commodity']) == 32, said
        assert len(answers['book']) == 32, said
        assert answers['lots'] == 1, said
        assert len(answers['lot']) == 32, said
    finally:
        repo.close()
