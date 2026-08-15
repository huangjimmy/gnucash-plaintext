"""
Use case for exporting GnuCash transactions to beancount format.

Exports GnuCash data to beancount-compatible format with proper account names,
commodity symbols, and metadata keys following beancount conventions.
"""

from typing import Optional

from gnucash.gnucash_core_c import xaccAccountGetTypeStr

from infrastructure.gnucash.utils import (
    get_account_full_name,
    get_commodity_ticker,
    get_parent_accounts_and_self,
    money_text,
    numeric_to_fraction,
)
from repositories.gnucash_repository import GnuCashRepository
from services.beancount_converter import BeancountConverter
from use_cases.export_transactions import (
    UnwritableFigureError,
    refuse_a_figure_the_currency_cannot_hold,
)


def _string(text: str) -> str:
    """Text as the inside of a beancount double-quoted string.

    A double quote ends one and a newline ends the line, and both turn up in
    ordinary descriptions — a supplier named in quotes, a note with two
    sentences. Written raw into a header, the file this tool produced could not
    be read by this tool: the description ran to the first inner quote and what
    followed was not a header, so the parse refused — and a refused parse takes
    the whole ledger, not one entry. Notes and memos were escaped all along;
    the two strings on the header were not.
    """
    return text.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')


class ExportBeancountUseCase:
    """Use case for exporting transactions to beancount format"""

    def __init__(self, repository: GnuCashRepository):
        """
        Initialize use case.

        Args:
            repository: GnuCash repository instance
        """
        self.repository = repository
        self.converter = BeancountConverter()

    def execute(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        account_filter: Optional[str] = None
    ) -> str:
        """
        Export transactions to beancount format with ALL commodities and accounts.

        IMPORTANT: When filtering transactions, we still export ALL commodities
        and ALL accounts. This is required for beancount - commodities and accounts
        are declarations that must exist before transactions can reference them.

        Args:
            start_date: Optional start date for filtering TRANSACTIONS only
            end_date: Optional end date for filtering TRANSACTIONS only
            account_filter: Optional account path for filtering TRANSACTIONS only

        Returns:
            Beancount-formatted string with:
            - ALL commodity declarations (not filtered)
            - ALL account declarations (not filtered)
            - Filtered transactions (by date/account if specified)
        """
        # Get ALL transactions first
        all_transactions = self.repository.get_all_transactions()

        # Sort by date
        all_transactions.sort(key=lambda tx: tx.GetDate())

        # Filter transactions by date range if specified
        if start_date and end_date:
            filtered_transactions = []
            for tx in all_transactions:
                tx_date = tx.GetDate().strftime("%Y-%m-%d")
                if start_date <= tx_date <= end_date:
                    filtered_transactions.append(tx)
            transactions = filtered_transactions
        else:
            transactions = all_transactions

        # Filter transactions by account if specified
        if account_filter:
            filtered = []
            for tx in transactions:
                for split in tx.GetSplitList():
                    account = split.GetAccount()
                    account_name = get_account_full_name(account)
                    if account_name.startswith(account_filter):
                        filtered.append(tx)
                        break
            transactions = filtered

        # Collect ALL commodities and ALL accounts from ALL transactions
        # This is critical - beancount requires all declarations before use
        commodity_seen = set()
        account_seen = set()
        commodities = []
        accounts = []

        for transaction in all_transactions:
            splits = transaction.GetSplitList()
            for split in splits:
                split_account = split.GetAccount()
                commodity = split_account.GetCommodity()
                ticker = get_commodity_ticker(commodity)

                # Collect commodity if not seen
                if ticker not in commodity_seen:
                    commodity_seen.add(ticker)
                    commodities.append((commodity, transaction))

                # Collect account hierarchy if not seen
                account_list = get_parent_accounts_and_self(split_account)
                for account in account_list:
                    account_guid = account.GetGUID().to_string()
                    if account_guid not in account_seen:
                        account_seen.add(account_guid)
                        accounts.append((account, transaction))

        # Generate beancount output
        lines = []

        # Output commodities
        for commodity, transaction in commodities:
            self._format_commodity(commodity, transaction, lines)

        # Output accounts
        for account, transaction in accounts:
            self._format_account(account, transaction, lines)

        # Output transactions. Every transaction the format cannot express is
        # named before the export refuses, the same way the plaintext export
        # does it — a book of thousands should not be fixed one run at a time,
        # and the two exports refuse the same figures for the same reason.
        refusals = []
        for transaction in transactions:
            try:
                self._format_transaction(transaction, lines)
            except UnwritableFigureError as exc:
                refusals.append(str(exc))
        if refusals:
            raise UnwritableFigureError(
                f'{len(refusals)} transaction(s) hold figures this format '
                f'cannot write, and nothing was exported:\n  - '
                + '\n  - '.join(refusals))

        return '\n'.join(lines) + '\n' if lines else ''

    def _format_commodity(self, commodity, transaction, lines: list):
        """Format commodity declaration in beancount format with GnuCash metadata"""
        date_str = transaction.GetDate().strftime("%Y-%m-%d")

        # Get original GnuCash commodity info
        gnucash_mnemonic = commodity.get_mnemonic()
        gnucash_namespace = commodity.get_namespace()
        gnucash_fullname = commodity.get_fullname() or ""
        fraction = commodity.get_fraction()

        # Convert ticker (namespace.mnemonic) to beancount-compatible symbol
        # Use ticker so it matches what's used in account declarations
        commodity_ticker = get_commodity_ticker(commodity)
        beancount_symbol = self.converter.convert_commodity_symbol(commodity_ticker)

        lines.append(f'{date_str} commodity {beancount_symbol}')
        # Escaped like every other string this writes. Both are free text in
        # GnuCash's Security Editor, and one quote in either makes a file this
        # tool's own parser refuses — which costs the whole ledger, not the
        # one commodity. The plaintext exporter already routes both through
        # `encode_value_as_string`; these two were the only ones here that
        # went out raw, three lines above `gnucash-fullname`, which does not.
        lines.append(f'    gnucash-mnemonic: "{_string(gnucash_mnemonic)}"')
        lines.append(f'    gnucash-namespace: "{_string(gnucash_namespace)}"')
        if gnucash_fullname:
            lines.append(f'    gnucash-fullname: "{_string(gnucash_fullname)}"')
        lines.append(f'    gnucash-fraction: "{fraction}"')

    def _format_account(self, account, transaction, lines: list):
        """Format account declaration in beancount format with GnuCash metadata"""
        commodity = account.GetCommodity()
        if commodity is None:
            return

        date_str = transaction.GetDate().strftime("%Y-%m-%d")
        gnucash_account_name = get_account_full_name(account)
        account_type = account.GetType()
        account_type_str = xaccAccountGetTypeStr(account_type)

        # Convert to beancount-compatible account name
        beancount_account = self.converter.convert_account_name(
            gnucash_account_name,
            account_type_str
        )

        # Get GnuCash metadata
        guid = account.GetGUID().to_string()
        placeholder = account.GetPlaceholder()
        code = account.GetCode() or ""
        description = account.GetDescription() or ""
        tax_related = account.GetTaxRelated()

        # Get commodity info
        commodity_ticker = get_commodity_ticker(commodity)
        beancount_commodity = self.converter.convert_commodity_symbol(commodity_ticker)

        lines.append(f'{date_str} open {beancount_account} {beancount_commodity}')
        lines.append(f'    gnucash-name: "{_string(gnucash_account_name)}"')
        lines.append(f'    gnucash-guid: "{guid}"')
        lines.append(f'    gnucash-type: "{account_type_str}"')
        lines.append(f'    gnucash-placeholder: "{placeholder}"')
        if code:
            lines.append(f'    gnucash-code: "{_string(code)}"')
        if description:
            lines.append(f'    gnucash-description: "{_string(description)}"')
        lines.append(f'    gnucash-tax-related: "{tax_related}"')
        # The account's own smallest unit, when it is not the commodity's.
        # Amounts are stored at it, so an account kept finer than its
        # commodity holds figures the commodity's fraction cannot state — a
        # fund declaring `fraction: 100` kept to thousandths holds 12.345
        # units. Left out, the re-imported account was created at the
        # commodity's fraction and GnuCash rounded every such amount to it on
        # save, so a round trip through beancount quietly coarsened the book.
        # `commodity_scu:` in the plaintext format, and the same thing.
        scu = account.GetCommoditySCU()
        if scu != commodity.get_fraction():
            lines.append(f'    gnucash-scu: "{scu}"')

    def _format_transaction(self, transaction, lines: list):
        """Format transaction in beancount format with GnuCash metadata"""
        tx_splits = transaction.GetSplitList()
        date_str = transaction.GetDate().strftime("%Y-%m-%d")
        tx_num = transaction.GetNum()
        tx_desc = transaction.GetDescription()

        # Transaction header.
        #
        # Beancount's `YYYY-MM-DD * "Payee" "Narration"` carries two strings
        # and GnuCash two fields — the number and the description — and one
        # string is beancount's *narration*. So a numbered entry with nothing
        # said about it, `* "CHK-1001"`, read back as a description of
        # CHK-1001 with the number gone: a cheque number filed as what the
        # entry was for. Both slots are written whenever the number is there,
        # and the reader keys on how many strings a header has rather than on
        # whether they say anything — which is the answer the plaintext export
        # arrived at under Q-020, for the same reason.
        if tx_num and tx_num.strip() != "":
            lines.append(f'{date_str} * "{_string(tx_num)}" '
                         f'"{_string(tx_desc or "")}"')
        elif tx_desc and tx_desc.strip() != "":
            lines.append(f'{date_str} * "{_string(tx_desc)}"')
        else:
            lines.append(f'{date_str} *')

        # Add transaction-level GnuCash metadata
        guid = transaction.GetGUID().to_string()
        lines.append(f'    gnucash-guid: "{guid}"')

        notes = transaction.GetNotes()
        if notes:
            lines.append(f'    gnucash-notes: "{_string(notes)}"')

        # Try to get doclink (GnuCash 4.0+) or association (GnuCash 3.x)
        try:
            doclink = transaction.GetDocLink()
            if doclink:
                lines.append(f'    gnucash-doclink: "{_string(doclink)}"')
        except AttributeError:
            try:
                doclink = transaction.GetAssociation()
                if doclink:
                    lines.append(f'    gnucash-doclink: "{_string(doclink)}"')
            except AttributeError:
                pass

        # Splits (postings in beancount)
        for split in tx_splits:
            self._format_split(split, lines)

        # Add blank line after transaction
        lines.append("")

    def _format_split(self, split, lines: list):
        """Format split as beancount posting with GnuCash metadata"""
        split_account = split.GetAccount()
        split_currency = split_account.GetCommodity()

        split_account_full_name = get_account_full_name(split_account)
        account_type = split_account.GetType()
        account_type_str = xaccAccountGetTypeStr(account_type)

        # Convert to beancount format
        beancount_account = self.converter.convert_account_name(
            split_account_full_name,
            account_type_str
        )

        beancount_commodity = self.converter.convert_commodity_symbol(
            get_commodity_ticker(split_currency)
        )

        # At the account's own smallest unit, which is not always its
        # commodity's: GnuCash keeps one per account and stores the amount at
        # it, so that is the number of decimals the figure actually has.
        # Written at the commodity's instead, a fund declaring `fraction: 100`
        # on an account kept to thousandths had a 12.345-unit holding exported
        # as 12.35 — the export rounding away units the book holds, which is
        # the one thing an export must not do. The plaintext exporter writes
        # at the account's unit for the same reason.
        # Refused for the same figure the plaintext export refuses, and by the
        # same rule: a booked amount is a whole number of its currency's
        # smallest unit. GnuCash stores 1.819 on an account kept to
        # thousandths and this export could state it faithfully — but the
        # importer will not read a sub-cent currency amount back, so writing
        # it produced a file this tool could not import: `export-beancount`
        # exited 0 and `import-beancount` on its own output reported
        # `Transactions: 0`. One export refusing what the other writes is the
        # worse answer either way; this is the one that matches the rule.
        split_amount = numeric_to_fraction(split.GetAmount())
        refuse_a_figure_the_currency_cannot_hold(
            split_amount, split_account, 'the split',
            split.GetParent().GetDescription())
        formatted_amount = money_text(split_amount,
                                      split_account.GetCommoditySCU())

        # A split has two figures whenever its value is not its amount, and
        # the second one has to be stated or it is lost. Usually that means a
        # cross-currency split — but not only: an account whose Smallest
        # Fraction is tightened under a figure it already holds ends up with
        # `amount 18, value 18.19` in one currency, because GnuCash rounds the
        # amount to the account's unit at save and leaves the value alone.
        #
        # Gated on the commodities differing, that split exported as `18 CAD`
        # against `-18.19 CAD` and the 0.19 was gone: the file does not balance
        # as beancount, and re-imported it takes the no-price branch for both
        # postings and GnuCash parks the difference in `Imbalance-CAD`. The
        # plaintext exporter carries it on `share_price:`; this is the same
        # thing said with `@@`, which is legal beancount on a same-currency
        # posting.
        tx_currency = split.GetParent().GetCurrency()
        price_annotation = ''
        if (tx_currency.get_mnemonic() != split_currency.get_mnemonic()
                or numeric_to_fraction(split.GetValue())
                != numeric_to_fraction(split.GetAmount())):
            price_annotation = self._price_annotation(split, tx_currency)

        lines.append(f'  {beancount_account} {formatted_amount} {beancount_commodity}{price_annotation}')

        # Add split-level GnuCash metadata (indented under the posting)
        memo = split.GetMemo()
        if memo:
            lines.append(f'      gnucash-memo: "{_string(memo)}"')

        action = split.GetAction()
        if action:
            lines.append(f'      gnucash-action: "{_string(action)}"')

    def _price_annotation(self, split, tx_currency) -> str:
        """
        Return beancount's `@@ total commodity` for a cross-currency split.

        The total-cost form, which states the split's value outright, not the
        per-unit form `@ rate`. A rate is a quotient and has to be written to
        some number of places — eight, here — and the importer had no value to
        read, so it rebuilt one as `amount × round₈(value / amount)`. The error
        is bounded by `|amount| × 5e-9`, which passes half a cent once the
        amount reaches about a million: ¥2,000,000 worth 18,200.01 CAD came
        back as 18,200.00 or 18,200.02 depending on which way the eighth digit
        went, its counterpart split came back exact, and the entry no longer
        summed to zero. An ordinary yen bank balance.

        `@@` carries the figure the book holds, at the currency's own unit, so
        nothing is reconstructed and nothing rounds.

        Two shapes it cannot carry, and both come down to the same property:
        the total is a *cost*, and the sign of a posting's weight comes from
        its units.

        Zero units are the first. A posting's weight is its units times its
        cost, so nothing times anything is nothing, and `@@ 50.00` on `0 HOOL`
        states a total the form has no way to attach. Where the value is zero
        too there is nothing to say and the posting is written bare; where it
        is not — a return of capital, which is zero shares against real money,
        and which GnuCash stores as amount 0 with a value (measured) — the
        format cannot express it.

        A value opposing its units is the second. `10 HOOL @@ 50.00 USD`
        weighs +50.00 and `-10 HOOL @@ 50.00 USD` weighs −50.00, so a split
        holding +10 units worth −50.00 has nothing to write: 50.00 says the
        opposite of what the book holds, and −50.00 is read as a cost of
        −50.00 against +10 units, which is the same answer again. Written
        unsigned it came back with the sign of its units and said nothing —
        the importer rebuilds the value as `amount × (total / |amount|)`.
        GnuCash keeps such a split across a save and reload (measured), so it
        is a book this can be handed.

        Both are refused rather than written without the figure that matters,
        and both point at the plaintext export, which states the units and the
        value separately and signs each.
        """
        amount = split.GetAmount()
        value = split.GetValue()
        units = numeric_to_fraction(amount)
        worth = numeric_to_fraction(value)
        where = (f'the split on '
                 f'{get_account_full_name(split.GetAccount())!r} in '
                 f'{split.GetParent().GetDescription()!r}')
        money = (f'{money_text(abs(worth), tx_currency.get_fraction())} '
                 f'{tx_currency.get_mnemonic()}')

        if units == 0:
            if worth == 0:
                return ''
            raise UnwritableFigureError(
                f'{where} holds no units and {money} of value — beancount '
                f'weighs a posting by its units times its cost, so there is '
                f'nowhere to put that figure and writing the posting without '
                f'it would lose it. Export this book as plaintext, which '
                f'states the two separately.')

        if worth != 0 and (worth < 0) != (units < 0):
            raise UnwritableFigureError(
                f'{where} holds '
                f'{money_text(units, split.GetAccount().GetCommoditySCU())} '
                f'units worth {money_text(worth, tx_currency.get_fraction())} '
                f'{tx_currency.get_mnemonic()} — the two point opposite ways, '
                f'and beancount takes a posting\'s sign from its units and '
                f'reads the total after `@@` as a cost. There is no total '
                f'that states this, and the one written would come back with '
                f'the sign of the units. Export this book as plaintext, which '
                f'states the two separately.')

        tx_beancount = self.converter.convert_commodity_symbol(
            tx_currency.get_mnemonic())
        total = money_text(abs(worth), tx_currency.get_fraction())
        return f' @@ {total} {tx_beancount}'

    def export_to_file(
        self,
        output_path: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        account_filter: Optional[str] = None
    ) -> int:
        """
        Export transactions to beancount file.

        Args:
            output_path: Path for output file
            start_date: Optional start date
            end_date: Optional end date
            account_filter: Optional account filter

        Returns:
            Number of lines exported
        """
        beancount = self.execute(start_date, end_date, account_filter)

        # UTF-8 stated, not the locale's — beancount files are UTF-8 and a
        # payee's name is not ASCII in general.
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(beancount)

        return len(beancount.split('\n'))
