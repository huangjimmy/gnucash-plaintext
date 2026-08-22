"""An exported beancount file is meant to be edited, so it has to be readable.

Editing an export by hand is the whole reason to export to beancount, and a
person writes beancount's own spellings, not this exporter's. It emits only
`@@ total CUR`; a reader reaches for the per-unit `@ rate CUR`, the cost basis
`{cost CUR}`, and a trailing `; note`.

A parser tuned to the one form did not merely ignore the others — it treated a
line it could not match as the end of the transaction, so the postings below it
were dropped too. The entry imported short, GnuCash balanced what was left by
inventing an Imbalance split, and the run reported success. One typo, and the
book said something the file did not.

So the forms are read, and a line that is genuinely neither a posting nor
metadata is refused by name.
"""

from fractions import Fraction
from pathlib import Path

import pytest
from click.testing import CliRunner
from gnucash import Query, Transaction

from cli.main import cli
from repositories.gnucash_repository import GnuCashRepository, SessionMode

BY_HAND = 'tests/fixtures/beancount_postings_written_by_hand.beancount'
UNREADABLE = 'tests/fixtures/beancount_posting_it_cannot_read.beancount'


def _entries(book):
    """Each transaction as (description, [(account, amount, value)])."""
    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        query = Query()
        query.search_for('Trans')
        query.set_book(repo.book)
        found = {}
        for raw in query.run():
            transaction = Transaction(instance=raw)
            found[transaction.GetDescription()] = sorted(
                (split.GetAccount().get_full_name(),
                 f'{split.GetAmount().num()}/{split.GetAmount().denom()}',
                 f'{split.GetValue().num()}/{split.GetValue().denom()}')
                for split in transaction.GetSplitList())
        query.destroy()
        return found
    finally:
        repo.close()


class TestTheFormsAPersonWrites:
    def _imported(self, tmp_path):
        book = tmp_path / 'hand.gnucash'
        result = CliRunner().invoke(
            cli, ['import-beancount', str(book), BY_HAND])
        assert result.exit_code == 0, result.output
        return book, result

    def test_every_transaction_lands(self, tmp_path):
        _book, result = self._imported(tmp_path)

        assert 'Transactions: 10' in result.output, result.output

    def test_entries_that_run_on_are_not_taken_for_bad_postings(self, tmp_path):
        """Beancount needs no blank line between directives, and this file
        mostly has none — including a bare comment line between two entries."""
        book, _ = self._imported(tmp_path)

        entries = _entries(book)
        assert 'Bought USD, cost basis with a lot date' in entries, entries
        assert 'Bought USD, signed amount' in entries, entries
        assert 'Bought USD, flagged postings' in entries, entries
        assert 'Bought USD, grouped digits' in entries, entries
        assert ('Bought USD, with metadata this tool does not keep'
                in entries), entries

    def test_none_of_them_is_short_a_posting(self, tmp_path):
        """The failure this shape produced: postings below a line it dropped."""
        book, _ = self._imported(tmp_path)

        entries = _entries(book)
        assert len(entries) == 10, entries
        for description, splits in entries.items():
            assert len(splits) == 2, (description, splits)

    def test_no_imbalance_is_invented(self, tmp_path):
        book, _ = self._imported(tmp_path)

        entries = _entries(book)
        for description, splits in entries.items():
            assert not [n for n, _a, _v in splits if 'Imbalance' in n], (
                description, splits)

    def test_each_spelling_values_the_foreign_side_the_same(self, tmp_path):
        """`@ 1.35`, `{1.35}` and `@@ 135.00` all say 135.00 CAD."""
        book, _ = self._imported(tmp_path)

        entries = _entries(book)
        for description, splits in entries.items():
            usd = [row for row in splits if row[0] == 'Assets.Bank.USD']
            if description == 'Bought USD, grouped digits':  # noqa: SIM114
                # Ten times the others, and the point of it is the commas.
                assert usd == [('Assets.Bank.USD', '100000/100',
                                '135000/100')], (description, splits)
                continue
            assert usd == [('Assets.Bank.USD', '10000/100', '13500/100')], (
                description, splits)

    def test_metadata_after_an_unknown_key_is_still_kept(self, tmp_path):
        """The per-posting loop stopped at the first key this tool ignores.

        So `category: "food"` above a `gnucash-memo:` cost the memo, while
        the same two lines the other way round kept it — order-dependent
        silence beside the tolerance that made such a file import at all.
        """
        from gnucash import Query, Transaction

        book, _ = self._imported(tmp_path)
        repo = GnuCashRepository(str(book))
        repo.open(mode=SessionMode.READ_ONLY)
        try:
            query = Query()
            query.search_for('Trans')
            query.set_book(repo.book)
            memos = [split.GetMemo()
                     for raw in query.run()
                     for split in Transaction(instance=raw).GetSplitList()]
            query.destroy()
        finally:
            repo.close()

        assert 'kept after an unknown key' in memos, memos

    def test_a_semicolon_inside_a_lot_label_is_not_a_comment(self, tmp_path):
        """`{1.35 CAD, "lot;a"}` — stripped from the first `;` anywhere, the
        brace was cut mid-label and the line reported as unreadable."""
        book, _ = self._imported(tmp_path)

        entries = _entries(book)
        labelled = entries['Bought USD, with metadata this tool does not keep']
        assert ('Assets.Bank.USD', '10000/100', '13500/100') in labelled, (
            labelled)

    def test_an_unindented_directive_ends_the_transaction(self, tmp_path):
        """`option` after the last posting, with no blank line before it.

        Postings and their metadata are indented and directives are not,
        which is beancount's own discriminator; a date test alone covered
        only the entries, so `option`, `plugin`, `include` and `poptag`
        reached the posting regex and took the whole file down.
        """
        book, result = self._imported(tmp_path)

        assert result.exit_code == 0, result.output
        assert len(_entries(book)) == 10, _entries(book)

    def test_a_trailing_comment_is_not_part_of_the_figure(self, tmp_path):
        book, _ = self._imported(tmp_path)

        entries = _entries(book)
        annotated = entries['Bought USD, with notes']
        assert ('Assets.Bank', '-13500/100', '-13500/100') in annotated, (
            annotated)


class TestAPostingThatLostItsIndent:
    """Indentation is what says where a transaction ends, so a slip is loud.

    Postings and their metadata are indented and top-level directives are
    not. A posting that slips back to column zero therefore reads as the next
    directive — and matches none of the three the outer loop knows, so it was
    skipped in silence: the transaction imported without it, GnuCash scrubbed
    in an Imbalance for what was missing, and the run reported success.
    """

    UNINDENTED = ('tests/fixtures/'
                  'beancount_posting_that_lost_its_indent.beancount')

    def test_it_is_refused_rather_than_dropped(self, tmp_path):
        book = tmp_path / 'slip.gnucash'
        result = CliRunner().invoke(
            cli, ['import-beancount', str(book), self.UNINDENTED])

        assert result.exit_code != 0, result.output
        assert 'is not indented' in result.output, result.output
        assert 'Expenses:Food 50.00 CAD' in result.output, result.output

    def test_grouped_digits_and_a_comment_do_not_hide_the_slip(self, tmp_path):
        """The question was asked of the raw line, the reader saw a
        normalised one, so `1,050.00 CAD  ; note` matched neither and went
        back to being dropped — the two spellings this parser had just
        learned."""
        book = tmp_path / 'grouped.gnucash'
        result = CliRunner().invoke(cli, [
            'import-beancount', str(book),
            'tests/fixtures/beancount_indent_lost_on_a_grouped_figure.beancount'])

        assert result.exit_code != 0, result.output
        assert 'is not indented' in result.output, result.output
        assert not book.exists(), 'a refused import left a book behind'

    def test_no_short_transaction_reaches_the_book(self, tmp_path):
        book = tmp_path / 'slip.gnucash'
        CliRunner().invoke(cli, ['import-beancount', str(book), self.UNINDENTED])

        assert not book.exists(), 'a refused import left a book behind'


class TestACostAndAPriceOnOneLine:
    """A basket and a price say different things, and the basket wins.

    Beancount balances a posting held at cost at `units × cost`; the `@ price`
    beside it is what the units are worth today, which the entry does not
    balance at. Read the other way round, the standard spelling of a disposal
    at a gain valued the holding at what it fetched instead of what it cost,
    the splits summed to the gain, and GnuCash scrubbed in an Imbalance while
    the run reported one transaction and no error.
    """

    SOLD = 'tests/fixtures/beancount_sold_at_a_gain.beancount'

    def _imported(self, tmp_path):
        book = tmp_path / 'sold.gnucash'
        result = CliRunner().invoke(cli, ['import-beancount', str(book), self.SOLD])
        assert result.exit_code == 0, result.output
        return book

    def test_the_holding_is_valued_at_what_it_cost(self, tmp_path):
        book = self._imported(tmp_path)

        splits = _entries(book)['Sold ten at a gain']
        assert ('Assets.Broker.HOOL', '-100000/10000', '-500000/100') in splits, (
            splits)

    def test_the_cash_and_the_gain_are_as_written(self, tmp_path):
        book = self._imported(tmp_path)

        splits = _entries(book)['Sold ten at a gain']
        assert ('Assets.Broker.Cash', '550000/100', '550000/100') in splits, splits
        assert ('Income.Gains', '-50000/100', '-50000/100') in splits, splits

    def test_no_imbalance_is_invented(self, tmp_path):
        """The 500.00 GnuCash scrubbed in when the price won."""
        book = self._imported(tmp_path)

        splits = _entries(book)['Sold ten at a gain']
        assert not [n for n, _a, _v in splits if 'Imbalance' in n], splits
        assert sum(int(v.split('/')[0]) for _n, _a, v in splits) == 0, splits


class TestUnitsFinerThanTheAccount:
    """A security is judged against its account's unit, on both paths.

    `12.345` is legal on an account kept to thousandths and `12.3456` is not.
    The plaintext importer refuses the second; this path did not ask, so
    `SetAmount` rounded it to 12.346 and the run reported `Errors: 0` — the
    value was computed from the figure the file stated, so the entry balanced
    and nothing flagged it. The quantity was simply not the one written.
    """

    TOO_FINE = ('tests/fixtures/'
                'beancount_units_finer_than_the_account.beancount')

    def test_it_is_refused(self, tmp_path):
        book = tmp_path / 'fine.gnucash'
        result = CliRunner().invoke(
            cli, ['import-beancount', str(book), self.TOO_FINE])

        assert result.exit_code != 0, result.output
        assert 'finer than that account is kept to' in result.output, \
            result.output
        assert '0.001' in result.output, result.output
        # The same judge the plaintext importer uses, so the same diagnosis —
        # and it names the key each format spells the unit with.
        assert 'gnucash-scu:' in result.output, result.output

    def test_nothing_of_it_is_stored(self, tmp_path):
        book = tmp_path / 'fine.gnucash'
        CliRunner().invoke(cli, ['import-beancount', str(book), self.TOO_FINE])

        assert not book.exists(), 'a refused import left a book behind'

    def test_the_quantity_the_account_can_hold_still_imports(self, tmp_path):
        """12.345 on the same account, which is the sibling fixture's book."""
        source = tmp_path / 'ok.gnucash'
        assert CliRunner().invoke(cli, [
            'import', '--new', str(source),
            'tests/fixtures/fund_units_at_the_accounts_unit.txt']).exit_code == 0

        beans = tmp_path / 'ok.beancount'
        assert CliRunner().invoke(
            cli, ['export-beancount', str(source), str(beans)]).exit_code == 0

        back = tmp_path / 'back.gnucash'
        result = CliRunner().invoke(
            cli, ['import-beancount', str(back), str(beans)])
        assert result.exit_code == 0, result.output


class TestDirectivesAnotherToolAnnotated:
    """A foreign metadata key hid every `gnucash-*` key below it.

    Metadata is one form everywhere in beancount and nothing orders it, so a
    key another editor wrote — fava's `name:` and `color:` on accounts — could
    land anywhere in a block. Read only until the first key this tool does not
    keep, what it cost depended on where the person typed it: a file refused
    for metadata it carries, or a note, a receipt link, an account's own unit
    or a commodity's fraction dropped without a word.

    The posting-level walk already read the whole block; the commodity, the
    `open` and the transaction header did not.
    """

    ANNOTATED = ('tests/fixtures/'
                 'beancount_directives_annotated_by_hand.beancount')

    def _imported(self, tmp_path):
        book = tmp_path / 'annotated.gnucash'
        result = CliRunner().invoke(
            cli, ['import-beancount', str(book), self.ANNOTATED])
        assert result.exit_code == 0, result.output
        return book

    def test_the_file_is_not_refused_for_metadata_it_carries(self, tmp_path):
        """A key above `gnucash-guid` broke the transaction's required check."""
        book = tmp_path / 'annotated.gnucash'
        result = CliRunner().invoke(
            cli, ['import-beancount', str(book), self.ANNOTATED])

        assert result.exit_code == 0, result.output
        assert 'Transactions: 1' in result.output, result.output

    def test_the_notes_and_the_receipt_link_survive(self, tmp_path):
        book = self._imported(tmp_path)

        repo = GnuCashRepository(str(book))
        repo.open(mode=SessionMode.READ_ONLY)
        try:
            query = Query()
            query.search_for('Trans')
            query.set_book(repo.book)
            found = [Transaction(instance=raw) for raw in query.run()]
            assert len(found) == 1, found
            transaction = found[0]
            notes = transaction.GetNotes()
            # GnuCash 4.0+ calls it a doclink; 3.x calls it an association.
            try:
                doclink = transaction.GetDocLink()
            except AttributeError:
                doclink = transaction.GetAssociation()
            query.destroy()
        finally:
            repo.close()

        assert notes == 'Quarterly contribution', notes
        assert doclink == 'receipts/2024-02-01-fund.pdf', doclink

    def test_the_accounts_own_unit_survives(self, tmp_path):
        """`gnucash-scu` is written last, so anything foreign drops it."""
        book = self._imported(tmp_path)

        repo = GnuCashRepository(str(book))
        repo.open(mode=SessionMode.READ_ONLY)
        try:
            fund = repo.get_account('Assets:Fund')
            scu = fund.GetCommoditySCU()
            bank = repo.get_account('Assets:Bank')
            description = bank.GetDescription()
        finally:
            repo.close()

        assert scu == 1000, scu
        assert description == 'Everyday chequing', description

    def test_the_units_the_account_holds_are_the_ones_written(self, tmp_path):
        """Which is what losing the unit showed up as: a refusal, or 12.35."""
        book = self._imported(tmp_path)

        entries = _entries(book)
        assert entries == {
            'Buy 12.345 units': [
                ('Assets.Bank', '-123450/100', '-123450/100'),
                ('Assets.Fund', '12345/1000', '123450/100'),
            ],
        }, entries

    def test_the_commoditys_fraction_survives(self, tmp_path):
        """Dropped, it fell back to 100 and the fund lost two decimals."""
        book = self._imported(tmp_path)

        repo = GnuCashRepository(str(book))
        repo.open(mode=SessionMode.READ_ONLY)
        try:
            fund = repo.book.get_table().lookup('FUND', 'FUNDX')
            fraction = fund.get_fraction()
        finally:
            repo.close()

        assert fraction == 10000, fraction


class TestAnAccountWithNoName:
    """`gnucash-name: ""` — the key is there, and it says nothing.

    Looking an empty path up answers with the root account, and the account
    creation read that as "already there" and skipped. So the book never
    gained the account, the run counted it anyway, and `✓ Import successful`
    was printed over a book two accounts deep where the file declared three.
    A posting on the missing account then failed with a message about an
    account mapping — the one place the fault was not.
    """

    NO_NAME = 'tests/fixtures/beancount_account_with_no_name.beancount'
    TRAILING = ('tests/fixtures/'
                'beancount_account_name_ending_in_a_separator.beancount')

    def test_a_name_ending_in_the_separator_is_refused_too(self, tmp_path):
        """`Assets:Bank:` names Assets, then Bank, then nothing.

        Measured, it made the nothing: a child with no name at all under
        Assets:Bank, which every export then writes back as the same typo.
        """
        book = tmp_path / 'trailing.gnucash'
        result = CliRunner().invoke(
            cli, ['import-beancount', str(book), self.TRAILING])

        assert result.exit_code != 0, result.output
        assert 'gnucash-name' in result.output, result.output
        assert not book.exists(), 'a refused import left a book behind'

    def test_it_is_refused(self, tmp_path):
        book = tmp_path / 'noname.gnucash'
        result = CliRunner().invoke(
            cli, ['import-beancount', str(book), self.NO_NAME])

        assert result.exit_code != 0, result.output
        assert not book.exists(), 'a refused import left a book behind'

    def test_it_says_the_name_is_empty_and_names_the_account(self, tmp_path):
        book = tmp_path / 'noname.gnucash'
        result = CliRunner().invoke(
            cli, ['import-beancount', str(book), self.NO_NAME])

        assert 'gnucash-name' in result.output, result.output
        assert 'Assets:Bank' in result.output, result.output
        assert 'not found in account mapping' not in result.output, \
            result.output


class TestTwoOpensNamingOneAccount:
    """The summary counts what the book gained, not what the file declared.

    A beancount account name cannot hold every character a GnuCash one can, so
    a rename in the beancount view can point two `open` directives at one
    GnuCash account. The second creates nothing — and the counter still added
    one per directive that did not raise, so the run reported an account the
    book does not have.
    """

    TWO_OPENS = ('tests/fixtures/'
                 'beancount_two_opens_one_gnucash_account.beancount')

    def _imported(self, tmp_path):
        book = tmp_path / 'twoopens.gnucash'
        result = CliRunner().invoke(
            cli, ['import-beancount', str(book), self.TWO_OPENS])
        assert result.exit_code == 0, result.output
        return book, result

    def test_the_summary_counts_the_accounts_created(self, tmp_path):
        _book, result = self._imported(tmp_path)

        assert 'Accounts:     3' in result.output, result.output

    def test_the_book_holds_exactly_those(self, tmp_path):
        book, _ = self._imported(tmp_path)

        repo = GnuCashRepository(str(book))
        repo.open(mode=SessionMode.READ_ONLY)
        try:
            names = sorted(account.get_full_name()
                           for account
                           in repo.book.get_root_account().get_descendants())
        finally:
            repo.close()
        assert names == ['Assets', 'Assets.Bank', 'Expenses'], names


class TestACurrencyAmountFinerThanTheCent:
    """The other branch of the same judge, and the one that must not advise.

    Written afresh for this path the check had only the account branch, so
    `50.001 CAD` on a cent account was told to give the account a finer unit
    — and the same file then failed the currency check, which is a dead end
    for money. Both importers go through one judge now, and it branches.
    """

    SUB_CENT = ('tests/fixtures/'
                'beancount_amount_finer_than_the_cent.beancount')

    def test_it_is_refused_as_money_the_book_cannot_record(self, tmp_path):
        book = tmp_path / 'cent.gnucash'
        result = CliRunner().invoke(
            cli, ['import-beancount', str(book), self.SUB_CENT])

        assert result.exit_code != 0, result.output
        assert 'not money this book can record' in result.output, result.output
        assert '50.001' in result.output, result.output

    def test_it_does_not_advise_a_finer_unit(self, tmp_path):
        """Which would send the reader into the currency check instead."""
        book = tmp_path / 'cent.gnucash'
        result = CliRunner().invoke(
            cli, ['import-beancount', str(book), self.SUB_CENT])

        assert 'not money this book can record' in result.output, result.output
        assert 'gnucash-scu:' not in result.output, result.output


class TestATotalAgainstNoUnits:
    """`@@ 50.00` on `0` units has nowhere to attach the figure.

    Read as unpriced, the total was dropped, the split valued at zero, and
    GnuCash scrubbed the whole 50.00 into an Imbalance while the run reported
    success. The export refuses to write this shape for the same reason.
    """

    NO_UNITS = 'tests/fixtures/beancount_total_against_no_units.beancount'

    def test_it_is_refused(self, tmp_path):
        book = tmp_path / 'nounits.gnucash'
        result = CliRunner().invoke(
            cli, ['import-beancount', str(book), self.NO_UNITS])

        assert result.exit_code != 0, result.output
        assert 'a total against no units' in result.output, result.output
        assert not book.exists(), 'a refused import left a book behind'


class TestACostTotalAgainstNoUnits:
    """`{{50.00 CAD}}` is the doubled-brace spelling of `@@ 50.00 CAD`.

    Both say the figure is the total rather than a rate per unit, so against
    no units both have nowhere to attach it. Refusing only `@@` left the same
    statement, spelled the other way, dropping the total: the split valued at
    zero, GnuCash scrubbing the whole 50.00 into an Imbalance, and the run
    reporting success.
    """

    COST_TOTAL = 'tests/fixtures/beancount_cost_total_against_no_units.beancount'
    PER_UNIT = 'tests/fixtures/beancount_cost_per_unit_against_no_units.beancount'

    def test_the_doubled_brace_is_refused(self, tmp_path):
        book = tmp_path / 'costtotal.gnucash'
        result = CliRunner().invoke(
            cli, ['import-beancount', str(book), self.COST_TOTAL])

        assert result.exit_code != 0, result.output
        assert 'a total against no units' in result.output, result.output
        assert not book.exists(), 'a refused import left a book behind'

    def test_the_single_brace_is_not(self, tmp_path):
        """A per-unit cost against no units is honest: it weighs nothing.

        `units × cost` is what a posting held at cost is worth, and that is
        0 here — so there is no figure being lost and nothing to refuse.
        """
        book = tmp_path / 'costperunit.gnucash'
        result = CliRunner().invoke(
            cli, ['import-beancount', str(book), self.PER_UNIT])

        assert result.exit_code == 0, result.output
        entries = _entries(book)
        assert entries == {
            'A per-unit cost against nothing': [
                ('Assets.Bank', '0/100', '0/100'),
                ('Assets.Bank.USD', '0/100', '0/100'),
            ],
        }, entries


class TestARateInSomethingElse:
    """A split's value is in the transaction's currency, so its rate must be.

    Every rate was applied as though it already were, which is true of what
    this tool writes and not of what a person writes. Two shapes reach it: a
    leg quoted against a third currency, off the statement it came from, and
    an exchange ratio written where a rate goes.
    """

    THIRD_CURRENCY = ('tests/fixtures/'
                      'beancount_a_rate_in_a_third_currency.beancount')
    IN_SHARES = 'tests/fixtures/beancount_a_rate_in_shares.beancount'

    def test_a_rate_in_a_third_currency_is_refused(self, tmp_path):
        """15,000 yen quoted per USD, in an entry denominated in CAD.

        Read as CAD it valued the yen at 100.00 instead of 135.00, and the
        35.00 it left over came back as an Imbalance under a run that
        reported success.
        """
        book = tmp_path / 'third.gnucash'
        result = CliRunner().invoke(
            cli, ['import-beancount', str(book), self.THIRD_CURRENCY])

        assert result.exit_code != 0, result.output
        assert 'USD' in result.output and 'CAD' in result.output, result.output
        assert 'Assets:Bank:JPY' in result.output, result.output
        assert not book.exists(), 'a refused import left a book behind'

    def test_an_exchange_ratio_is_refused(self, tmp_path):
        """`@ 0.5 NASDAQ.NEWCO` valued 100 shares at 50.00 CAD."""
        book = tmp_path / 'ratio.gnucash'
        result = CliRunner().invoke(
            cli, ['import-beancount', str(book), self.IN_SHARES])

        assert result.exit_code != 0, result.output
        assert 'Assets:Broker:OLDCO' in result.output, result.output
        assert 'NEWCO' in result.output, result.output


class TestARateWrittenTight:
    """`@1.35` — beancount reads the sigil as its own token, and so must this.

    Read as needing a space after it, the posting matched nothing, and a
    posting this parser cannot read is refused rather than skipped: one
    missing space cost the whole ledger. The cost basket already tolerated
    the same shape.
    """

    TIGHT = 'tests/fixtures/beancount_a_rate_written_tight.beancount'

    def test_it_reads(self, tmp_path):
        book = tmp_path / 'tight.gnucash'
        result = CliRunner().invoke(
            cli, ['import-beancount', str(book), self.TIGHT])

        assert result.exit_code == 0, result.output

    def test_the_foreign_side_is_valued_by_the_rate(self, tmp_path):
        book = tmp_path / 'tight.gnucash'
        CliRunner().invoke(cli, ['import-beancount', str(book), self.TIGHT])

        entries = _entries(book)
        assert entries['Buy USD, rate written tight'] == [
            ('Assets.Bank', '-13500/100', '-13500/100'),
            ('Assets.Bank.USD', '10000/100', '13500/100'),
        ], entries


class TestARateAgainstTheCurrency:
    """`USD@1.35` — the other side of the same sigil.

    The space after `@` was optional and the space before it was required,
    which is one rule answered two ways: `USD @1.35 CAD` read and
    `USD@1.35 CAD` matched nothing, so the currency group swallowed the
    sigil and the rate with it and the line ran off its own end. Refused
    rather than skipped, that cost the whole ledger — for a space that
    beancount itself does not ask for.
    """

    AGAINST = 'tests/fixtures/beancount_a_rate_against_the_currency.beancount'

    def test_it_reads(self, tmp_path):
        book = tmp_path / 'against.gnucash'
        result = CliRunner().invoke(
            cli, ['import-beancount', str(book), self.AGAINST])

        assert result.exit_code == 0, result.output

    def test_the_foreign_side_is_valued_by_the_rate(self, tmp_path):
        """Not left for GnuCash to scrub into an Imbalance."""
        book = tmp_path / 'against.gnucash'
        CliRunner().invoke(cli, ['import-beancount', str(book), self.AGAINST])

        entries = _entries(book)
        assert entries['Buy USD, sigil against the currency'] == [
            ('Assets.Bank', '-13500/100', '-13500/100'),
            ('Assets.Bank.USD', '10000/100', '13500/100'),
        ], entries


class TestMetadataWrittenUnquoted:
    """A beancount metadata value is typed, and a number is written bare.

    Recognised as metadata and read only as a quoted string, such a line was
    consumed and dropped without a word: `gnucash-scu: 1000` left the account
    at its commodity's fraction, GnuCash rounded every amount to it on save,
    and 12.345 units came back as 12.35 under a run reporting no errors.
    """

    UNQUOTED = ('tests/fixtures/'
                'beancount_metadata_written_unquoted.beancount')

    def _imported(self, tmp_path):
        book = tmp_path / 'unquoted.gnucash'
        result = CliRunner().invoke(
            cli, ['import-beancount', str(book), self.UNQUOTED])
        assert result.exit_code == 0, result.output
        return book

    def test_the_units_are_the_ones_written(self, tmp_path):
        book = self._imported(tmp_path)

        entries = _entries(book)
        assert entries['Buy 12.345 units'] == [
            ('Assets.Bank', '-123450/100', '-123450/100'),
            ('Assets.Fund', '12345/1000', '123450/100'),
        ], entries

    def test_the_account_keeps_the_unit_it_was_given(self, tmp_path):
        book = self._imported(tmp_path)

        repo = GnuCashRepository(str(book))
        repo.open(mode=SessionMode.READ_ONLY)
        try:
            scu = repo.get_account('Assets:Fund').GetCommoditySCU()
            fraction = repo.book.get_table().lookup(
                'FUND', 'FUNDX').get_fraction()
        finally:
            repo.close()

        assert scu == 1000, scu
        assert fraction == 10000, fraction


class TestADayThatDoesNotExist:
    """`2024-02-30` is shaped like a date and is not one.

    It matches the pattern every directive is recognised by and fails in
    `strptime` two lines later — as a bare `ValueError: day is out of range
    for month`, which is neither the refusal the import collects per object
    nor a message that says which line.
    """

    IMPOSSIBLE = ('tests/fixtures/'
                  'beancount_a_day_that_does_not_exist.beancount')

    def test_it_is_refused_by_name(self, tmp_path):
        book = tmp_path / 'impossible.gnucash'
        result = CliRunner().invoke(
            cli, ['import-beancount', str(book), self.IMPOSSIBLE])

        assert result.exit_code != 0, result.output
        assert '2024-02-30' in result.output, result.output
        assert 'day is out of range' not in result.output, result.output


class TestTheHeadersAPersonWrites:
    """A comment on the header, and `txn` where the flag goes.

    A trailing comment is read off every other line before anything is asked
    of it, and the header is where a person is likeliest to write one — which
    statement the entry came off. Beancount's own documentation gives `txn` as
    the alternative to `*`; matched on the flag alone, such an entry was
    skipped in silence with its metadata and its postings, and because its
    accounts never reached the used-account set nothing downstream noticed.
    """

    HEADERS = 'tests/fixtures/beancount_headers_a_person_wrote.beancount'

    def _imported(self, tmp_path):
        book = tmp_path / 'headers.gnucash'
        result = CliRunner().invoke(
            cli, ['import-beancount', str(book), self.HEADERS])
        assert result.exit_code == 0, result.output
        return book, result

    def test_both_entries_land(self, tmp_path):
        book, result = self._imported(tmp_path)

        assert 'Transactions: 2' in result.output, result.output
        assert sorted(_entries(book)) == ['Coffee', 'Lunch'], _entries(book)

    def test_the_comment_is_not_part_of_the_narration(self, tmp_path):
        book, _ = self._imported(tmp_path)

        entries = _entries(book)
        assert entries['Lunch'] == [
            ('Assets.Bank', '-5000/100', '-5000/100'),
            ('Expenses', '5000/100', '5000/100'),
        ], entries

    def test_neither_is_short_a_posting(self, tmp_path):
        """What being skipped in silence looked like: a scrubbed Imbalance."""
        book, _ = self._imported(tmp_path)

        for description, splits in _entries(book).items():
            assert len(splits) == 2, (description, splits)
            assert not [n for n, _a, _v in splits if 'Imbalance' in n], (
                description, splits)


class TestCommentsInsideTheMetadata:
    """A comment above the line it is about stopped the walk.

    beancount takes a comment anywhere, and that is where a person annotating
    an export puts one. Every `gnucash-*` key below it was dropped —
    silently, and only when the comment happened to land above them.
    """

    COMMENTED = ('tests/fixtures/'
                 'beancount_comments_inside_the_metadata.beancount')

    def _imported(self, tmp_path):
        book = tmp_path / 'commented.gnucash'
        result = CliRunner().invoke(
            cli, ['import-beancount', str(book), self.COMMENTED])
        assert result.exit_code == 0, result.output
        return book

    def test_the_transactions_notes_and_link_survive(self, tmp_path):
        book = self._imported(tmp_path)

        repo = GnuCashRepository(str(book))
        repo.open(mode=SessionMode.READ_ONLY)
        try:
            query = Query()
            query.search_for('Trans')
            query.set_book(repo.book)
            transaction = Transaction(instance=query.run()[0])
            notes = transaction.GetNotes()
            try:
                doclink = transaction.GetDocLink()
            except AttributeError:
                doclink = transaction.GetAssociation()
            memos = sorted(split.GetMemo()
                           for split in transaction.GetSplitList())
            query.destroy()
        finally:
            repo.close()

        assert notes == 'Quarterly contribution', notes
        assert doclink == 'receipts/2024-02-01-fund.pdf', doclink
        assert memos == ['', 'unit purchase'], memos

    def test_the_accounts_description_and_unit_survive(self, tmp_path):
        book = self._imported(tmp_path)

        repo = GnuCashRepository(str(book))
        repo.open(mode=SessionMode.READ_ONLY)
        try:
            description = repo.get_account('Assets:Bank').GetDescription()
            scu = repo.get_account('Assets:Fund').GetCommoditySCU()
            fraction = repo.book.get_table().lookup(
                'FUND', 'FUNDX').get_fraction()
        finally:
            repo.close()

        assert description == 'Everyday chequing', description
        assert scu == 1000, scu
        assert fraction == 10000, fraction


class TestADirectiveEditedDownToItsKeyword:
    """What a line is, is its keyword; the shape of the rest is judged after.

    Recognised by its whole shape, a `commodity` or an `open` with the symbol
    or the account edited off it matched nothing and was skipped in silence
    along with the directives this tool does not keep — and surfaced later as
    a complaint about something else entirely.
    """

    NO_SYMBOL = ('tests/fixtures/'
                 'beancount_a_commodity_with_no_symbol.beancount')
    NO_ACCOUNT = ('tests/fixtures/'
                  'beancount_an_open_with_no_account.beancount')
    NO_QUOTES = ('tests/fixtures/'
                 'beancount_a_narration_without_quotes.beancount')

    def test_a_commodity_with_no_symbol_is_quoted_back(self, tmp_path):
        """It used to read as `Cannot find commodity (FUND, FUNDX)`."""
        book = tmp_path / 'nosym.gnucash'
        result = CliRunner().invoke(
            cli, ['import-beancount', str(book), self.NO_SYMBOL])

        assert result.exit_code != 0, result.output
        assert 'Invalid commodity directive' in result.output, result.output
        assert 'Cannot find commodity' not in result.output, result.output

    def test_an_open_with_no_account_is_quoted_back(self, tmp_path):
        """It used to read as `Implicit accounts not allowed`."""
        book = tmp_path / 'noacct.gnucash'
        result = CliRunner().invoke(
            cli, ['import-beancount', str(book), self.NO_ACCOUNT])

        assert result.exit_code != 0, result.output
        assert 'Invalid open directive' in result.output, result.output
        assert 'Implicit accounts' not in result.output, result.output

    WITH_A_COMMENT = ('tests/fixtures/'
                      'beancount_an_open_with_a_trailing_comment.beancount')

    def test_a_note_is_not_read_as_the_currency(self, tmp_path):
        """The currency on an `open` is optional and a comment may follow it.

        Both legal, and read together the comment became the currency: the
        account opened in `;`, and it surfaced three directives later as
        `Cannot find commodity (CURRENCY, ;)` — the same misdiagnosis the two
        above were written to remove. The transaction reader was taught to
        strip a trailing comment; the `open` and `commodity` readers were not.
        """
        book = tmp_path / 'comment.gnucash'
        result = CliRunner().invoke(
            cli, ['import-beancount', str(book), self.WITH_A_COMMENT])

        assert 'Cannot find commodity' not in result.output, result.output
        # The directive is quoted back without it, so the note is not part of
        # what the reader is being asked to look at.
        assert 'opened in March' not in result.output, result.output

    def test_an_open_with_no_currency_is_refused_by_name(self, tmp_path):
        """What is left once the comment is not the problem.

        Beancount reads a missing currency constraint as any currency; a
        GnuCash account is kept in exactly one, so there is nothing to write.
        Guessing the book's own would open the account in it silently.
        """
        book = tmp_path / 'comment.gnucash'
        result = CliRunner().invoke(
            cli, ['import-beancount', str(book), self.WITH_A_COMMENT])

        assert result.exit_code != 0, result.output
        assert 'Invalid open directive' in result.output, result.output
        assert 'needs the currency the account is kept in' in result.output, \
            result.output

    def test_a_note_after_an_open_that_names_one_is_a_note(self, tmp_path):
        """And with the currency there, the comment is simply a comment."""
        book = tmp_path / 'ok.gnucash'
        ledger = tmp_path / 'ok.beancount'
        ledger.write_text(Path(self.WITH_A_COMMENT).read_text().replace(
            'open Assets:Bank  ; opened in March',
            'open Assets:Bank CAD  ; opened in March'))
        result = CliRunner().invoke(
            cli, ['import-beancount', str(book), str(ledger)])

        assert result.exit_code == 0, result.output
        out = tmp_path / 'out.txt'
        assert CliRunner().invoke(cli, ['export', str(book),
                                        str(out)]).exit_code == 0
        assert 'Assets:Bank -50.00 CAD' in out.read_text(), out.read_text()

    def test_a_header_whose_strings_lost_their_quotes(self, tmp_path):
        """The postings landed and what the entry was for was gone."""
        book = tmp_path / 'noquotes.gnucash'
        result = CliRunner().invoke(
            cli, ['import-beancount', str(book), self.NO_QUOTES])

        assert result.exit_code != 0, result.output
        assert 'Invalid transaction' in result.output, result.output
        assert 'double quotes' in result.output, result.output

    def test_tags_and_links_are_still_a_transaction(self, tmp_path):
        """They follow the strings in beancount and mean nothing here."""
        book = tmp_path / 'tagged.gnucash'
        result = CliRunner().invoke(cli, [
            'import-beancount', str(book),
            'tests/fixtures/beancount_directives_annotated_by_hand.beancount'])

        assert result.exit_code == 0, result.output
        assert 'Buy 12.345 units' in _entries(book), _entries(book)


class TestAFileThatDeclaresNoCurrencies:
    """Nothing obliges a hand-written file to declare CAD.

    `commodity` directives are how a file names a security — `FUND.FUNDX` for
    `FUNDX` in the `FUND` namespace — and GnuCash already carries every ISO
    4217 currency, so an entry written from scratch has no reason to declare
    one. Both the account's commodity and the entry's currency fall back to
    looking the symbol up as a currency.
    """

    NO_COMMODITIES = ('tests/fixtures/'
                      'beancount_currencies_never_declared.beancount')

    def test_it_imports_whole(self, tmp_path):
        book = tmp_path / 'bare.gnucash'
        result = CliRunner().invoke(
            cli, ['import-beancount', str(book), self.NO_COMMODITIES])

        assert result.exit_code == 0, result.output
        entries = _entries(book)
        assert entries == {
            'Lunch': [
                ('Assets.Bank', '-5000/100', '-5000/100'),
                ('Expenses', '5000/100', '5000/100'),
            ],
        }, entries

    def test_the_accounts_are_in_the_currency_they_name(self, tmp_path):
        book = tmp_path / 'bare.gnucash'
        CliRunner().invoke(
            cli, ['import-beancount', str(book), self.NO_COMMODITIES])

        repo = GnuCashRepository(str(book))
        repo.open(mode=SessionMode.READ_ONLY)
        try:
            mnemonic = repo.get_account(
                'Assets:Bank').GetCommodity().get_mnemonic()
        finally:
            repo.close()

        assert mnemonic == 'CAD', mnemonic


class TestACommodityNothingCarries:
    """A ticker that is in no `commodity` directive and in no book.

    A typo, or a security declared in the file the postings were copied out
    of. No posting is in a currency and none states a rate, so what the entry
    is denominated in falls to the commodity the first posting names — and
    there is no such commodity anywhere to fall to.
    """

    MISSING = ('tests/fixtures/'
               'beancount_a_commodity_nothing_carries.beancount')

    def test_it_is_refused_by_name(self, tmp_path):
        book = tmp_path / 'missing.gnucash'
        result = CliRunner().invoke(
            cli, ['import-beancount', str(book), self.MISSING])

        assert result.exit_code != 0, result.output
        assert 'NASDAQ.HOOOL' in result.output, result.output
        assert not book.exists(), 'a refused import left a book behind'


class TestAnInventedCurrencyCode:
    """Points, miles and hours are securities, not currencies.

    A currency here is an ISO 4217 currency and nothing else — GnuCash
    carries that table, and prices and reports are built on it — so a code no
    issuer stands behind is refused rather than registered beside the ones
    that are.
    """

    POINTS = ('tests/fixtures/'
              'beancount_an_invented_currency_code.beancount')

    def test_the_commodity_is_reported_by_name(self, tmp_path):
        book = tmp_path / 'points.gnucash'
        result = CliRunner().invoke(
            cli, ['import-beancount', str(book), self.POINTS])

        assert result.exit_code != 0, result.output
        assert 'PTS' in result.output, result.output
        assert not book.exists(), 'a refused import left a book behind'


class TestWhatTheSummarySaysAboutCommodities:
    """What the book gained, and what it changed, said apart.

    GnuCash seeds the CURRENCY namespace from its own ISO 4217 table, so an
    ordinary CAD ledger creates no commodity at all — a bare count of
    creations reads as though the file's commodities had been dropped, beside
    a dozen accounts and hundreds of transactions. And a commodity restated at
    another fraction, which is what a file moved between two GnuCash versions
    does, was counted nowhere.
    """

    ISO_ONLY = 'tests/fixtures/beancount_two_opens_one_gnucash_account.beancount'
    WITH_A_SECURITY = ('tests/fixtures/'
                       'beancount_shares_moved_with_a_value.beancount')
    RESTATED = ('tests/fixtures/'
                'beancount_a_currency_at_another_fraction.beancount')

    def test_a_book_of_ordinary_currencies_creates_none(self, tmp_path):
        book = tmp_path / 'iso.gnucash'
        result = CliRunner().invoke(
            cli, ['import-beancount', str(book), self.ISO_ONLY])

        assert result.exit_code == 0, result.output
        assert 'Commodities:  0 created, 0 updated' in result.output, \
            result.output

    def test_a_security_the_book_did_not_have_counts_as_created(self, tmp_path):
        book = tmp_path / 'sec.gnucash'
        result = CliRunner().invoke(
            cli, ['import-beancount', str(book), self.WITH_A_SECURITY])

        assert result.exit_code == 0, result.output
        assert 'Commodities:  1 created, 0 updated' in result.output, \
            result.output

    def test_a_currency_restated_counts_as_updated(self, tmp_path):
        book = tmp_path / 'restated.gnucash'
        result = CliRunner().invoke(
            cli, ['import-beancount', str(book), self.RESTATED])

        assert result.exit_code == 0, result.output
        assert 'Commodities:  0 created, 1 updated' in result.output, \
            result.output

    def test_a_dry_run_says_what_the_file_declares(self, tmp_path):
        """A different question from what an import did, said differently."""
        result = CliRunner().invoke(cli, [
            'import-beancount', str(tmp_path / 'unused.gnucash'),
            self.RESTATED, '--dry-run'])

        assert result.exit_code == 0, result.output
        assert 'Commodities:  2 declared' in result.output, result.output


class TestAPostingInTheWrongCommodity:
    """The commodity on the line has to be the one the account holds.

    It was read once, for the currency of the entry, and never asked about
    again: the amount went to the account in whatever the account holds, so
    `Assets:Bank -50.00 USD` on a CAD account booked −50.00 CAD, balanced
    against the other side, and reported success.
    """

    WRONG = ('tests/fixtures/'
             'beancount_a_posting_in_the_wrong_commodity.beancount')

    def test_it_is_refused(self, tmp_path):
        book = tmp_path / 'wrong.gnucash'
        result = CliRunner().invoke(
            cli, ['import-beancount', str(book), self.WRONG])

        assert result.exit_code != 0, result.output
        assert not book.exists(), 'a refused import left a book behind'

    def test_it_names_both_commodities(self, tmp_path):
        book = tmp_path / 'wrong.gnucash'
        result = CliRunner().invoke(
            cli, ['import-beancount', str(book), self.WRONG])

        assert 'USD' in result.output, result.output
        assert 'Assets:Bank' in result.output, result.output
        assert 'CAD' in result.output, result.output


class TestSharesMovedBetweenBrokers:
    """An entry with no money in it at all.

    Neither rule that picks what an entry is denominated in has anything to
    answer with — no posting states a rate, and no posting is in a currency —
    which leaves the security. GnuCash takes that in memory and does not keep
    it: measured, the transaction read back denominated in the book's own
    currency after a save, leaving 10 units valued as 10 dollars.
    """

    IN_KIND = ('tests/fixtures/'
               'beancount_shares_moved_between_brokers.beancount')
    WITH_VALUE = ('tests/fixtures/'
                  'beancount_shares_moved_with_a_value.beancount')

    def test_a_transfer_that_says_nothing_of_value_is_refused(self, tmp_path):
        book = tmp_path / 'inkind.gnucash'
        result = CliRunner().invoke(
            cli, ['import-beancount', str(book), self.IN_KIND])

        assert result.exit_code != 0, result.output
        assert 'HOOL' in result.output, result.output
        assert 'security' in result.output, result.output
        assert not book.exists(), 'a refused import left a book behind'

    def test_the_same_transfer_priced_lands_in_full(self, tmp_path):
        """As numbers: GnuCash is free to hold −10 as −1000/100."""
        book = tmp_path / 'priced.gnucash'
        result = CliRunner().invoke(
            cli, ['import-beancount', str(book), self.WITH_VALUE])
        assert result.exit_code == 0, result.output

        splits = _entries(book)['Transfer HOOL in kind']
        assert [(name, Fraction(amount), Fraction(value))
                for name, amount, value in splits] == [
            ('Assets.BrokerA.HOOL', Fraction(-10), Fraction(-1000)),
            ('Assets.BrokerB.HOOL', Fraction(10), Fraction(1000)),
        ], splits

    def test_the_priced_transfer_is_denominated_in_the_currency(self, tmp_path):
        book = tmp_path / 'priced.gnucash'
        CliRunner().invoke(
            cli, ['import-beancount', str(book), self.WITH_VALUE])

        repo = GnuCashRepository(str(book))
        repo.open(mode=SessionMode.READ_ONLY)
        try:
            query = Query()
            query.search_for('Trans')
            query.set_book(repo.book)
            currencies = [Transaction(instance=raw).GetCurrency().get_mnemonic()
                          for raw in query.run()]
            query.destroy()
        finally:
            repo.close()

        assert currencies == ['CAD'], currencies


class TestAConversionWithNoRate:
    """A cross-currency posting has two figures and must state the second.

    Valued at its own amount it was silently wrong in exactly the way `{}` is
    refused for — 100.00 USD entered as 100.00 CAD against 135.00 of cash,
    with GnuCash inventing `Imbalance-USD 35.00` and the run reporting no
    errors. `{}` was refused; leaving the rate off entirely, which is the
    plainer hand-edit, was not.
    """

    NO_RATE = 'tests/fixtures/beancount_conversion_with_no_rate.beancount'

    def test_it_is_refused(self, tmp_path):
        book = tmp_path / 'norate.gnucash'
        result = CliRunner().invoke(
            cli, ['import-beancount', str(book), self.NO_RATE])

        assert result.exit_code != 0, result.output
        assert 'says nothing about what it is worth' in result.output, \
            result.output

    def test_it_names_the_spellings_that_would_say_it(self, tmp_path):
        """In the currency the entry ended up denominated in.

        Which is USD here, and arbitrarily so: with no posting stating a
        price, the rule falls back to the first posting that is in a
        currency. That is the second half of the same defect — the entry is
        denominated by whichever side came first — and it is why the refusal
        has to come before anything is valued.
        """
        book = tmp_path / 'norate.gnucash'
        result = CliRunner().invoke(
            cli, ['import-beancount', str(book), self.NO_RATE])

        assert '@@ total USD' in result.output, result.output
        assert '@ rate USD' in result.output, result.output

    def test_no_imbalanced_transaction_is_stored(self, tmp_path):
        book = tmp_path / 'norate.gnucash'
        CliRunner().invoke(cli, ['import-beancount', str(book), self.NO_RATE])

        assert not book.exists(), 'a refused import left a book behind'


class TestACostLeftToBeInferred:
    """`{}` asks for a cost this tool has no way to work out.

    Beancount infers an empty basket's cost from the lots the account already
    holds. GnuCash keeps no per-lot state to infer from, and this reads a cost
    rather than deriving one — so reading `{}` as an unpriced posting would be
    silently wrong exactly where it matters: 100.00 USD valued at 100.00 CAD
    against -135.00 CAD of cash, with GnuCash inventing an Imbalance for the
    35.00 difference.
    """

    INFERRED = 'tests/fixtures/beancount_cost_left_to_be_inferred.beancount'

    def test_it_is_refused(self, tmp_path):
        book = tmp_path / 'inferred.gnucash'
        result = CliRunner().invoke(
            cli, ['import-beancount', str(book), self.INFERRED])

        assert result.exit_code != 0, result.output
        assert 'inferred' in result.output, result.output

    def test_it_names_the_spellings_that_do_state_a_cost(self, tmp_path):
        book = tmp_path / 'inferred.gnucash'
        result = CliRunner().invoke(
            cli, ['import-beancount', str(book), self.INFERRED])

        assert '@@ total CUR' in result.output, result.output
        assert '{rate CUR}' in result.output, result.output

    def test_no_book_is_left_behind(self, tmp_path):
        """Asserted, not branched on.

        `import-beancount` writes the new book before it reads the ledger, so
        a refusal has to take it away again — the command refuses to write
        over an existing path, so a book left by a failed run blocks the
        retry of the command that made it. Written as `if book.exists():`,
        the only assertion was skipped when the book was gone and true by
        construction when it was there, since an unsaved book holds nothing.
        """
        book = tmp_path / 'inferred.gnucash'
        CliRunner().invoke(cli, ['import-beancount', str(book), self.INFERRED])

        assert not book.exists(), 'a refused import left a book behind'


class TestFixingTheFileAndRunningItAgain:
    """The whole point of the cleanup: the retry has to work.

    `import-beancount` writes the book before reading the ledger and refuses
    to write over an existing path. A failed run that left the empty book
    behind therefore blocked the identical command from being run again once
    the typo was fixed — the reader had to delete a file they never created,
    from a message that did not say where it came from.
    """

    UNREADABLE = UNREADABLE
    GOOD = 'tests/fixtures/beancount_postings_written_by_hand.beancount'

    def test_a_failure_before_the_ledger_is_read_is_swept_too(self, tmp_path):
        """The file exists from `create_new_file` onward, not from the parse.

        Opening the fresh store can fail on its own — a disk that fills, a
        directory turned read-only — and the cleanup lived in an inner
        `finally` that those failures never entered. The gate is on whether
        the import finished, and it is asked wherever the run ends.
        """
        import cli.import_beancount_cmd as cmd

        book = tmp_path / 'early.gnucash'
        original = cmd.GnuCashRepository.create_new_file

        def create_then_fail(path):
            original(path)
            raise OSError('no space left on device')

        cmd.GnuCashRepository.create_new_file = staticmethod(create_then_fail)
        try:
            result = CliRunner().invoke(
                cli, ['import-beancount', str(book), self.GOOD])
        finally:
            cmd.GnuCashRepository.create_new_file = original

        assert result.exit_code != 0, result.output
        assert not book.exists(), 'a book made and abandoned was left behind'

    def test_the_same_command_succeeds_once_the_file_is_fixed(self, tmp_path):
        book = tmp_path / 'retry.gnucash'
        first = CliRunner().invoke(
            cli, ['import-beancount', str(book), self.UNREADABLE])
        assert first.exit_code != 0, first.output

        second = CliRunner().invoke(
            cli, ['import-beancount', str(book), self.GOOD])

        assert second.exit_code == 0, second.output
        assert 'already exists' not in second.output, second.output
        assert book.exists(), second.output


class TestAnAmountThatIsNotANumber:
    """`5.0.0` gets past the regex and fails in the arithmetic below it.

    The regex asks only for digits, dots and a sign, and the total-to-rate
    division needs the amount as a number. Raised from there it surfaced as
    `Invalid literal for Fraction: '5.0.0'` — no file, no line, no posting
    quoted — two branches away from a refusal that quotes all three.
    """

    NOT_A_NUMBER = ('tests/fixtures/'
                    'beancount_amount_that_is_not_a_number.beancount')

    def test_it_says_which_posting_and_which_figure(self, tmp_path):
        book = tmp_path / 'nan.gnucash'
        result = CliRunner().invoke(
            cli, ['import-beancount', str(book), self.NOT_A_NUMBER])

        assert result.exit_code != 0, result.output
        assert 'not a number' in result.output, result.output
        assert "'5.0.0'" in result.output, result.output
        assert 'Expenses:Food' in result.output, result.output

    def test_it_is_not_an_internal_message(self, tmp_path):
        book = tmp_path / 'nan.gnucash'
        result = CliRunner().invoke(
            cli, ['import-beancount', str(book), self.NOT_A_NUMBER])

        assert 'not a number' in result.output, result.output
        assert 'Invalid literal for Fraction' not in result.output, result.output
        assert 'Traceback' not in result.output, result.output

    @pytest.mark.parametrize('fixture,what', [
        ('tests/fixtures/beancount_price_that_is_not_a_number.beancount',
         'a price'),
        ('tests/fixtures/beancount_cost_that_is_not_a_number.beancount',
         'a cost'),
    ])
    def test_the_other_two_figures_are_guarded_the_same_way(
            self, fixture, what, tmp_path):
        """The regex admits the same garbage in all three positions.

        Guarded on the amount alone, `@@ 1.2.3 CAD` raised a bare
        `ValueError` — which is not the type the per-object handler catches,
        so it escaped that too and left through the CLI's blanket catch.
        """
        book = tmp_path / 'nan.gnucash'
        result = CliRunner().invoke(cli, ['import-beancount', str(book), fixture])

        assert result.exit_code != 0, result.output
        assert f'states {what} that is not a number' in result.output, \
            result.output
        assert "'1.2.3'" in result.output, result.output
        assert 'Invalid literal for Fraction' not in result.output, result.output


class TestALineItCannotRead:
    def test_it_is_refused_rather_than_taken_for_the_end(self, tmp_path):
        book = tmp_path / 'bad.gnucash'
        result = CliRunner().invoke(
            cli, ['import-beancount', str(book), UNREADABLE])

        assert result.exit_code != 0, result.output
        assert 'cannot read the posting line' in result.output, result.output

    def test_it_quotes_the_line_and_says_what_a_posting_looks_like(self,
                                                                  tmp_path):
        book = tmp_path / 'bad.gnucash'
        result = CliRunner().invoke(
            cli, ['import-beancount', str(book), UNREADABLE])

        assert 'CADD EXTRA' in result.output, result.output
        assert '@@ total CUR' in result.output, result.output

    def test_no_book_is_left_behind(self, tmp_path):
        """The short transaction it used to write went into this book.

        Nothing is written now, so the assertion is that the book is gone —
        the same statement, and one that can fail. `if book.exists():` could
        not: skipped when absent, and true by construction when present,
        because an unsaved book holds nothing either way.
        """
        book = tmp_path / 'bad.gnucash'
        CliRunner().invoke(cli, ['import-beancount', str(book), UNREADABLE])

        assert not book.exists(), 'a refused import left a book behind'
