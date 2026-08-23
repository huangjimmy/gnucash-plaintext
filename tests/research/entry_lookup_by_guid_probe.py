"""Can an entry be found by its guid, and can a tax table be unset?

Two things the entry import path needs and no code here does yet.

1. **Lookup.** `gncEntryLookup` is a macro in `gncEntry.h`, so no library
   exports it and ctypes cannot call it. The collection lookup underneath —
   `qof_book_get_collection` + `qof_collection_lookup_entity` — is a pair of
   real functions taking the QOF type name as a string. This measures that
   both are exported on this build and that they find the entry.

2. **Unsetting a tax table.** A line patched in place keeps whatever it had
   unless every field is written, and a block naming no `tax_table:` has to
   leave the entry with none. This measures whether SWIG accepts `None`.

Run: ./scripts/test.sh <tag> tests/research/entry_lookup_by_guid_probe.py -s
"""

import ctypes

from click.testing import CliRunner
from gnucash import Query

from cli.main import cli
from infrastructure.gnucash.engine import guid_from_hex, load_gnc_engine
from infrastructure.gnucash.utils import wrap_invoice_or_bill
from repositories.gnucash_repository import GnuCashRepository, SessionMode
from services.gnucash_importer import _swig_invoice_guid_str

LEDGER = """2026-01-01 commodity CAD
\tmnemonic: "CAD"
\tfullname: "Canadian Dollar"
\tnamespace: "CURRENCY"
\tfraction: 100
2026-01-01 open Income
\ttype: Income
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Income:Sales
\ttype: Income
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"

customer "C-P"
\tname: "Probe Ltd"
\tcurrency: CAD

taxtable "GST"
\tentry:
\t\taccount: "Income:Sales"
\t\trate: 5.0%
\t\ttype: PERCENT

invoice "INV-P-001"
\tcustomer_id: "C-P"
\tcurrency: CAD
\tdate_opened: 2026-02-01
\tentry:
\t\tdate: 2026-02-01
\t\tdescription: "Design"
\t\taccount: "Income:Sales"
\t\tquantity: 1
\t\tprice: 100
\t\ttaxable: #True
\t\ttax_included: #False
\t\ttax_table: "GST"
\tposted: none
\tpayment: none
"""


def test_what_the_engine_answers(tmp_path):
    ledger = tmp_path / 'in.txt'
    ledger.write_text(LEDGER, encoding='utf-8')
    book_path = tmp_path / 'book.gnucash'
    made = CliRunner().invoke(cli, ['import', '--new', str(book_path),
                                    str(ledger), '--include-business-objects'])
    assert made.exit_code == 0, made.output

    repo = GnuCashRepository(str(book_path))
    repo.open(SessionMode.NORMAL)
    try:
        lib = load_gnc_engine()
        lib.qof_instance_get_guid.argtypes = [ctypes.c_void_p]
        lib.qof_instance_get_guid.restype = ctypes.c_void_p
        lib.guid_to_string_buff.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        lib.guid_to_string_buff.restype = ctypes.c_char_p

        q = Query()
        q.search_for('gncInvoice')
        q.set_book(repo.book)
        record = wrap_invoice_or_bill(q.run()[0])
        entry = record.GetEntries()[0]
        q.destroy()

        buf = ctypes.create_string_buffer(40)
        lib.guid_to_string_buff(
            lib.qof_instance_get_guid(int(entry.instance)), buf)
        guid = buf.value.decode('ascii')
        report = [f'entry guid: {guid!r}']

        for name in ('qof_book_get_collection', 'qof_collection_lookup_entity'):
            report.append(f'{name}: {hasattr(lib, name)}')

        cguid = guid_from_hex(guid)
        answers = {}
        for type_name in (b'gncEntry', b'gncInvoice', b'Account'):
            coll = lib.qof_book_get_collection(int(repo.book.instance),
                                               type_name)
            found = lib.qof_collection_lookup_entity(coll, ctypes.byref(cguid))
            answers[type_name] = found
            report.append(f'collection {type_name!r}: coll={bool(coll)} '
                          f'found={found} '
                          f'is_the_entry={found == int(entry.instance)}')

        # And the invoice's own guid in the invoice's own collection, so
        # `b'gncInvoice'` is measured to be the right string rather than
        # only measured not to hold an entry. Were it wrong, the check for
        # "is this guid free" would answer yes about an invoice that
        # exists, and a line could be forced onto its guid — two objects
        # under one hash key, which is what the check is for.
        doc_guid = guid_from_hex(_swig_invoice_guid_str(record))
        doc_coll = lib.qof_book_get_collection(int(repo.book.instance),
                                               b'gncInvoice')
        answers['the invoice itself'] = lib.qof_collection_lookup_entity(
            doc_coll, ctypes.byref(doc_guid))
        report.append(f'collection gncInvoice, asked for the invoice: '
                      f'{answers["the invoice itself"]} '
                      f'is_the_invoice='
                      f'{answers["the invoice itself"] == int(record.instance)}')

        report.append(f'tax table before: {entry.GetInvTaxTable()}')
        try:
            entry.BeginEdit()
            entry.SetInvTaxTable(None)
            entry.CommitEdit()
            answers['unset'] = entry.GetInvTaxTable()
            report.append(f'SetInvTaxTable(None): ok, now {answers["unset"]}')
        except Exception as exc:
            answers['unset'] = exc
            report.append(f'SetInvTaxTable(None): {type(exc).__name__}: {exc}')

        said = '\n'.join(report)
        # The lookup finds the entry and only the entry: a guid is unique
        # across every collection in the book, so asking the wrong one is
        # how a check for "is this guid free" answers yes about a line that
        # exists.
        assert answers[b'gncEntry'] == int(entry.instance), said
        assert not answers[b'gncInvoice'], said
        assert not answers[b'Account'], said
        assert answers['the invoice itself'] == int(record.instance), said
        # And a line's tax table can be taken off, which is what a block
        # naming no `tax_table:` asks for on a line that had one.
        assert answers['unset'] is None, said
    finally:
        repo.close()
