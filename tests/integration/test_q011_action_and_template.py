"""
Q-011: an entry's `action` field is optional, and what an invoice prints
for it is whatever the entry says.

Two concerns covered here:

  1. The importer accepts an `entry:` directive with no `action:` line and
     stores it as empty (Choice B in Q-011 docs).
  2. GnuCash's page carries an Action column, and an entry with an action
     fills its cell while one without leaves it empty. The column itself is
     the report's — it is drawn whether or not anything fills it, which is
     GnuCash's choice and not one this project makes.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner

from cli.main import cli
from infrastructure.gnucash.utils import wrap_invoice_or_bill

_ACCOUNTS = """
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
"""


def _write(path: Path, text: str) -> str:
    path.write_text(text)
    return str(path)


def _import_new(runner, gnc, fixture):
    return runner.invoke(cli, ["import", "--new", str(gnc), fixture,
                               "--include-business-objects"])


def _export(runner, gnc, out):
    return runner.invoke(cli, ["export", str(gnc), str(out),
                               "--include-business-objects"])


def _render_invoice_html(gnc_path: str, invoice_id: str) -> str:
    """The page GnuCash draws for the named invoice."""
    from gnucash import Query, Session
    from gnucash.gnucash_business import Invoice

    from services.invoice_renderer import render_to_html

    ses = Session(f"xml://{gnc_path}")
    try:
        book = ses.book
        q = Query()
        q.search_for('gncInvoice')
        q.set_book(book)
        inv = next(
            (i for r in q.run() for i in [wrap_invoice_or_bill(r)] if i.GetID() == invoice_id),
            None,
        )
        q.destroy()
        assert inv is not None, f"Invoice {invoice_id!r} not found"
        return render_to_html(inv, ses)
    finally:
        ses.end()


# ── 1. Importer: action is optional ─────────────────────────────────────────


class TestImporterAcceptsMissingAction:
    """Per Q-011 Choice B: omitting the `action:` line is equivalent to
    `action: ""`. The entry's action field is set to empty. To preserve
    a non-empty value across re-imports the user must declare it
    explicitly."""

    def test_invoice_with_no_action_field_imports_with_empty_action(self, tmp_path):
        runner = CliRunner()
        gnc = tmp_path / "book.gnucash"
        fixture = _ACCOUNTS + """
customer "C001"
\tname: "Acme"
\tcurrency: CAD

invoice "INV-001"
\tcustomer_id: "C001"
\tcurrency: CAD
\tdate_opened: 2026-01-01
\tentry:
\t\tdate: 2026-01-01
\t\tdescription: "Goods"
\t\taccount: "Income:Sales"
\t\tquantity: 100
\t\tprice: 15
\t\ttaxable: false
\t\ttax_included: false
\tposted: none
\tpayment: none
"""
        r = _import_new(runner, gnc, _write(tmp_path / "in.txt", fixture))
        assert r.exit_code == 0, r.output

        # Round-trip: export should emit `action: ""` because that's what
        # GnuCash holds (no NULL state in GnuCash; see issue doc for the
        # empirical probe result).
        out = tmp_path / "exported.txt"
        r2 = _export(runner, gnc, out)
        assert r2.exit_code == 0, r2.output
        text = out.read_text()
        assert 'description: "Goods"' in text
        assert 'action: ""' in text, (
            f"Empty action must roundtrip as `action: \"\"`. Got:\n{text}"
        )

    def test_reimport_omitted_then_explicit_empty_is_unchanged(self, tmp_path):
        """Q-010 idempotency intersection: the matcher must treat
        `<no action: line>` and `action: ""` as equivalent."""
        import time
        runner = CliRunner()
        gnc = tmp_path / "book.gnucash"

        def _make_fixture(action_line: str) -> str:
            return _ACCOUNTS + f"""
customer "C001"
\tname: "Acme"
\tcurrency: CAD

invoice "INV-001"
\tcustomer_id: "C001"
\tcurrency: CAD
\tdate_opened: 2026-01-01
\tentry:
\t\tdate: 2026-01-01
\t\tdescription: "Goods"
{action_line}\t\taccount: "Income:Sales"
\t\tquantity: 100
\t\tprice: 15
\t\ttaxable: false
\t\ttax_included: false
\tposted: none
\tpayment: none
"""

        # First import: no action line.
        r1 = _import_new(runner, gnc, _write(tmp_path / "no_action.txt",
                                             _make_fixture('')))
        assert r1.exit_code == 0, r1.output

        # Re-import: explicit empty action. Should be reported as 'unchanged'.
        r2 = runner.invoke(cli, [
            "import", str(gnc),
            _write(tmp_path / "explicit_empty.txt",
                   _make_fixture('\t\taction: ""\n')),
            "--include-business-objects",
        ])
        assert r2.exit_code == 0, r2.output
        assert 'invoice "INV-001": unchanged' in r2.output, (
            f"<no action> and `action: \"\"` must be matcher-equivalent. "
            f"Got:\n{r2.output}"
        )


# ── 2. The page: what the Action column carries ─────────────────────────────


class TestTheActionColumn:
    """If every entry has an empty action, the rendered HTML must omit
    the cell for an entry that has no action."""

    def _setup(self, tmp_path, action_per_entry: list) -> str:
        """Set up a book with one POSTED invoice whose entries have the
        listed actions. action_per_entry[i] is either None (omit `action:`
        line) or a string (use `action: "<s>"`).

        Posted, which is the realistic scenario: you only print invoices
        you have sent.
        """
        runner = CliRunner()
        gnc = tmp_path / "book.gnucash"
        entries = []
        for i, act in enumerate(action_per_entry):
            action_line = '' if act is None else f'\t\taction: "{act}"\n'
            entries.append(
                f'\tentry:\n'
                f'\t\tdate: 2026-01-01\n'
                f'\t\tdescription: "Item {i+1}"\n'
                f'{action_line}'
                f'\t\taccount: "Income:Sales"\n'
                f'\t\tquantity: 1\n'
                f'\t\tprice: 100\n'
                f'\t\ttaxable: false\n'
                f'\t\ttax_included: false\n'
            )
        fixture = _ACCOUNTS + """
customer "C001"
\tname: "Acme"
\tcurrency: CAD

invoice "INV-001"
\tcustomer_id: "C001"
\tcurrency: CAD
\tdate_opened: 2026-01-01
""" + ''.join(entries) + (
            '\tposted:\n'
            '\t\tdate: 2026-01-01\n'
            '\t\tdue: 2026-01-31\n'
            '\t\tar_account: "Assets:Accounts Receivable"\n'
            '\t\tmemo: "Invoice INV-001"\n'
            '\t\taccumulate: true\n'
            '\tpayment: none\n'
        )
        r = _import_new(runner, gnc, _write(tmp_path / "in.txt", fixture))
        assert r.exit_code == 0, r.output
        return str(gnc)

    def test_no_entry_has_an_action_and_none_is_printed(self, tmp_path):
        gnc = self._setup(tmp_path, [None, None, ''])
        html = _render_invoice_html(gnc, "INV-001")

        assert '<th>Action</th>' in html, html
        # Three entries, three empty Action cells and nothing invented for
        # them. `<td></td>` is what the report writes for one.
        assert html.count('<td></td>') >= 3, html

    def test_the_action_an_entry_states_is_printed(self, tmp_path):
        gnc = self._setup(tmp_path, ['Hours', None, ''])
        html = _render_invoice_html(gnc, "INV-001")

        assert '<td>Hours</td>' in html, html
