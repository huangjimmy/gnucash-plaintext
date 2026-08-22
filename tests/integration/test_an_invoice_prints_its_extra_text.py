"""The two free-text blocks a page carries beyond GnuCash's own.

GnuCash's own invoice has no place for either: it prints one "Company ID" for
the seller and nothing at all against the customer. So a seller who tells one
customer something different from another — a segment's website, terms that
customer alone gets — has nowhere to put it.

Both are printed **as they stand**. Nothing is inferred from them and no rule
is applied: what a given customer is told is written on that customer, which
is why this needs no template of your own. That is the whole mechanism.

Both are ordinary keys in the plaintext format — `extra_text:` on the `company`
directive and on the owner — so they are written, exported and re-imported like
any other, and this test writes them that way rather than reaching into the
book: the path from the file to the page is the thing that can break.

The seller's block also states the registration numbers GnuCash has no field
for. What is *not* on the page matters as much: the rest of what those slots
hold is the seller's own business — a fiscal year end, a customer's credit
rating — and the page goes to the other party.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner

from cli.main import cli

FIXTURES = Path('tests/fixtures')
LEDGER = str(FIXTURES / 'an_invoice_with_extra_text.txt')


@pytest.fixture
def book(tmp_path):
    path = tmp_path / 'extra.gnucash'
    built = CliRunner().invoke(cli, ['import', '--new', str(path), LEDGER,
                                     '--include-business-objects'])
    assert built.exit_code == 0, built.output
    return path


@pytest.fixture
def rendered(book, tmp_path):
    """The page `print-invoice` writes, start to finish."""
    out = tmp_path / 'inv.html'
    printed = CliRunner().invoke(cli, [
        'print-invoice', str(book), 'INV-EXTRA-001', '--format', 'html',
        '--output', str(out)])
    assert printed.exit_code == 0, printed.output
    return out.read_text()


class TestWhatThePagePrints:
    def test_the_sellers_block_is_there(self, rendered):
        assert 'Remit to: Bank 000-111' in rendered, rendered[-1200:]

    def test_this_customers_own_block_is_there(self, rendered):
        assert 'portal.example.test/acme' in rendered, rendered[-1200:]

    def test_a_newline_becomes_a_line_break(self, rendered):
        """Written on two lines, printed on two lines."""
        assert 'Ask us: billing@example.test' in rendered
        assert 'Net 45 by agreement' in rendered
        assert '<br' in rendered.split('Remit to: Bank 000-111')[1][:80], (
            rendered.split('Remit to: Bank 000-111')[1][:200])

    def test_nothing_is_interpreted(self, rendered):
        """It is text, not a rule: the words come out as they went in."""
        assert 'Net 45 by agreement' in rendered
        assert 'segment' not in rendered.lower()

    def test_the_registration_numbers_are_stated(self, rendered):
        """GnuCash has no field for either, and a Canadian invoice needs them.

        One GST number, and a row for each PST — a filer may hold several.
        """
        assert 'GST: 111222333RT0001' in rendered, rendered[-1200:]
        assert 'PST: BC PST-0000-1111' in rendered, rendered[-1200:]
        assert 'PST: SK 2222-3333' in rendered, rendered[-1200:]


class TestWhereEachBlockLands:
    """Beside the party it is about, not merely somewhere on the page.

    Each is added as a row of one of the report's two address blocks, found by
    the `<div class="…-table">` that opens it. A build that drew one of those
    without a `<tbody>` would put the row in the next table that has one — the
    other party's block, or the entry table — and a test that only asked
    whether the words appear would pass with the seller's bank details printed
    under the customer's name.

    On GnuCash's page the client block comes first and the company block
    second, so the two texts must fall on either side of the company block's
    opening div.
    """

    def test_the_owners_text_is_in_the_owners_block(self, rendered):
        client = rendered.index('class="client-table"')
        company = rendered.index('class="company-table"')
        owner_text = rendered.index('portal.example.test/acme')

        assert client < owner_text < company, (client, owner_text, company)

    def test_a_page_with_nowhere_to_put_it_is_refused(self):
        """Rather than printed without it.

        The registration numbers go in the seller's block, and a Canadian
        invoice is required to state them — so a GnuCash that laid its page
        out differently must not yield a page that looks right, goes to a
        customer, and is quietly missing them. Every supported build has the
        block; this is what an eleventh would meet.
        """
        from services.gnucash_report import (
            PageNotRenderedError,
            _with_extra_row,
        )

        page = '<html><body><div class="renamed-table"><table><tbody>' \
               '</tbody></table></div></body></html>'

        with pytest.raises(PageNotRenderedError) as refused:
            _with_extra_row(page, 'company-table', 'GST: 111222333RT0001')

        assert 'GST: 111222333RT0001' in str(refused.value), str(refused.value)

    def test_a_page_with_nothing_to_add_is_left_alone(self):
        """The empty case stays a no-op: no text, nothing to lose."""
        from services.gnucash_report import _with_extra_row

        page = '<html><body>nothing here</body></html>'

        assert _with_extra_row(page, 'company-table', '') == page

    def test_the_sellers_text_is_in_the_sellers_block(self, rendered):
        company = rendered.index('class="company-table"')
        entries = rendered.index('class="entries-table"')

        for line in ('GST: 111222333RT0001', 'PST: BC PST-0000-1111',
                     'Remit to: Bank 000-111'):
            assert company < rendered.index(line) < entries, (
                line, company, rendered.index(line), entries)


class TestWhatItKeepsBack:
    def test_the_sellers_private_keys_are_not_printed(self, rendered):
        """The customer has no business seeing the seller's fiscal year."""
        for token in ('fiscal_year_end', '12-31'):
            assert token not in rendered, (token, rendered[-1200:])

    def test_what_the_seller_wrote_about_this_customer_is_not_printed(
            self, rendered):
        for token in ('credit_rating', 'chase early'):
            assert token not in rendered, (token, rendered[-1200:])


class TestItSurvivesTheFormat:
    def test_both_come_back_from_an_export(self, book, tmp_path):
        """Round-tripped like any other key, so a rebuilt book still prints
        them — otherwise the page is right once and blank ever after."""
        out = tmp_path / 'out.txt'
        exported = CliRunner().invoke(cli, [
            'export', str(book), str(out), '--include-business-objects'])
        assert exported.exit_code == 0, exported.output

        text = out.read_text()
        assert 'Remit to: Bank 000-111' in text, text
        assert 'Portal: portal.example.test/acme' in text, text

    def test_a_rebuilt_book_prints_them(self, book, tmp_path):
        out = tmp_path / 'out.txt'
        CliRunner().invoke(cli, [
            'export', str(book), str(out), '--include-business-objects'])

        fresh = tmp_path / 'fresh.gnucash'
        rebuilt = CliRunner().invoke(cli, [
            'import', '--new', str(fresh), str(out),
            '--include-business-objects'])
        assert rebuilt.exit_code == 0, rebuilt.output

        page = tmp_path / 'again.html'
        printed = CliRunner().invoke(cli, [
            'print-invoice', str(fresh), 'INV-EXTRA-001', '--format', 'html',
            '--output', str(page)])
        assert printed.exit_code == 0, printed.output

        text = page.read_text()
        assert 'Remit to: Bank 000-111' in text, text[-1200:]
        assert 'portal.example.test/acme' in text, text[-1200:]
        assert 'GST: 111222333RT0001' in text, text[-1200:]
