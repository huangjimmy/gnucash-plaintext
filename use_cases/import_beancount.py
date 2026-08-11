"""
Use case for importing GnuCash-compatible beancount files to GnuCash.

Reconstructs GnuCash files from beancount files that were exported with
all gnucash-* metadata. Validates that all required metadata is present.
"""

import contextlib

from repositories.gnucash_repository import GnuCashRepository
from services.beancount_parser import (
    BeancountParser,
    BeancountValidationError,
    a_whole_number,
)
from services.gnucash_importer import (
    GnuCashImporter,
    begin_currency_declarations,
    stated_money,
)
from services.plaintext_parser import DirectiveType, PlaintextDirective


class ImportBeancountResult:
    """Result of importing beancount file"""

    def __init__(self):
        self.commodities_created = 0
        # Counted apart, because a book denominated in ordinary currencies
        # creates none: GnuCash seeds the CURRENCY namespace from its own ISO
        # 4217 table. A commodity restated at another fraction — what a file
        # moved between two GnuCash versions does — is the one thing an import
        # does change about them, and it was counted nowhere.
        self.commodities_updated = 0
        self.accounts_created = 0
        self.transactions_created = 0
        self.errors = []

    def add_error(self, error: str):
        """Add an error message"""
        self.errors.append(error)

    def has_errors(self) -> bool:
        """Check if import had errors"""
        return len(self.errors) > 0


class ImportBeancountUseCase:
    """Use case for importing beancount files to GnuCash"""

    def __init__(self, repository: GnuCashRepository):
        """
        Initialize use case.

        Args:
            repository: GnuCash repository instance
        """
        self.repository = repository
        self.parser = BeancountParser()

    def import_from_file(self, beancount_file: str) -> ImportBeancountResult:
        """
        Import GnuCash-compatible beancount file.

        Args:
            beancount_file: Path to beancount file

        Returns:
            ImportBeancountResult with status

        Raises:
            BeancountValidationError: If file fails validation
        """
        result = ImportBeancountResult()

        # What the last file restated a currency from, forgotten here as the
        # plaintext side forgets it in its own `import_from_file`. This reader
        # creates commodities and books amounts through `holdable_unit`, so it
        # is one of the two the rule at `begin_lot_attachments` names — and
        # having the reset in the CLI instead left anything driving this use
        # case directly reading the previous file's figure.
        begin_currency_declarations()

        # Parse and validate beancount file
        try:
            self.parser.parse_file(beancount_file)
        except BeancountValidationError as e:
            result.add_error(str(e))
            return result

        # Create commodities
        for commodity_data in self.parser.commodities:
            try:
                outcome = self._create_commodity(commodity_data)
                if outcome == 'created':
                    result.commodities_created += 1
                elif outcome in ('updated', 'updated-in-session'):
                    # Reported either way; see `create_commodity` for why an
                    # ISO currency's restated fraction is not a saveable one.
                    result.commodities_updated += 1
            except Exception as e:
                result.add_error(f"Failed to create commodity {commodity_data.symbol}: {e}")

        # Create accounts (with original GnuCash names)
        for account_data in self.parser.accounts:
            try:
                if self._create_account(account_data):
                    result.accounts_created += 1
            except Exception as e:
                result.add_error(
                    f"Failed to create account {account_data.gnucash_name}: {e}"
                )

        # Create transactions
        account_mapping = self.parser.get_account_mapping()
        for tx_data in self.parser.transactions:
            try:
                self._create_transaction(tx_data, account_mapping)
                result.transactions_created += 1
            except Exception as e:
                result.add_error(f"Failed to create transaction: {e}")

        return result

    def _create_commodity(self, commodity_data):
        """Create or update commodity from beancount data.

        GnuCashImporter.create_commodity handles both create and update of
        an existing commodity (e.g. updating fraction for a pre-registered
        ISO 4217 currency the user customized).
        """
        directive = PlaintextDirective(
            directive_type=DirectiveType.CREATE_COMMODITY,
            level=0,
            line=f"commodity {commodity_data.symbol}"
        )
        directive.metadata = {
            'mnemonic': commodity_data.gnucash_mnemonic,
            'fullname': commodity_data.gnucash_fullname or "",
            'namespace': commodity_data.gnucash_namespace,
            'fraction': commodity_data.gnucash_fraction
        }

        # Whether the book gained one, so the caller counts what was created
        # rather than what the file declared — every export declares every
        # commodity it holds, and most of them are already there.
        return GnuCashImporter.create_commodity(directive, self.repository.book)

    def _create_account(self, account_data):
        """Create the account, and say whether the book gained one.

        Two `open` directives can name one GnuCash account — the beancount
        name cannot hold every character a GnuCash one can, so the two views
        are kept apart and a rename in the beancount view can point both at
        the same place. Counting every directive that did not raise then
        reported an account the book does not have.
        """
        # Use the original GnuCash name, not the beancount name
        gnucash_name = account_data.gnucash_name

        # Check if account already exists
        existing = self.repository.get_account(gnucash_name)
        if existing:
            return False

        # Find the commodity info for this account
        commodity_namespace = 'CURRENCY'
        commodity_mnemonic = account_data.commodity
        for commodity in self.parser.commodities:
            if commodity.symbol == account_data.commodity:
                commodity_namespace = commodity.gnucash_namespace
                commodity_mnemonic = commodity.gnucash_mnemonic
                break

        # Convert beancount account data to PlaintextDirective format
        # so we can use the existing GnuCashImporter
        directive = PlaintextDirective(
            directive_type=DirectiveType.OPEN_ACCOUNT,
            level=0,
            line=f"open {gnucash_name}"
        )
        directive.props = {'account': gnucash_name}
        directive.metadata = {
            'type': account_data.gnucash_type,
            'placeholder': account_data.gnucash_placeholder == "True",
            'code': account_data.gnucash_code or "",
            'description': account_data.gnucash_description or "",
            'tax_related': account_data.gnucash_tax_related == "True",
            'commodity.namespace': commodity_namespace,
            'commodity.mnemonic': commodity_mnemonic,
            'guid': account_data.gnucash_guid
        }
        # The account's own smallest unit, when the file states one. Without
        # it the account is created at its commodity's fraction, and GnuCash
        # rounds every amount to that on save — so a fund holding 12.345 units
        # on an account kept to thousandths came back as 12.35, and a round
        # trip through beancount quietly coarsened the book.
        if account_data.gnucash_scu:
            # As an int: beancount metadata is quoted text, and the setter is
            # a C `int` that refuses a string outright. Refused in the same
            # words as every other counted value off a directive — a
            # hand-edited `gnucash-scu: 1o00` said `invalid literal for int()
            # with base 10` while `gnucash-fraction` beside it named the file,
            # the key and the text.
            directive.metadata['commodity_scu'] = a_whole_number(
                account_data.gnucash_scu, 'gnucash-scu',
                f'open {gnucash_name}')

        # Use GnuCashImporter to create the account
        # This handles type mapping and all GnuCash internals.
        #
        # Its answer is this function's answer. The pre-check above already
        # decides the same thing, and the two agree — but agreeing is not the
        # same as being one fact, and returning `True` regardless made the
        # count right by coincidence: whatever `create_account` learns about
        # whether the book gained an account, it learns after this function
        # has stopped looking.
        return GnuCashImporter.create_account(directive, self.repository.book)

    def _commodity_named(self, symbol, commodity_table):
        """The commodity a beancount symbol names, as this file declares it.

        A beancount symbol is not a GnuCash mnemonic: a security is written
        `FUND.FUNDX` for `FUNDX` in the `FUND` namespace, and the file's own
        `commodity` directives are what tie the two together. A symbol with no
        directive can still be a currency the book already carries, which is
        how an account opened in USD works in a file that never declares USD.
        """
        for commodity_data in self.parser.commodities:
            if commodity_data.symbol == symbol:
                return commodity_table.lookup(
                    commodity_data.gnucash_namespace,
                    commodity_data.gnucash_mnemonic)
        return commodity_table.lookup('CURRENCY', symbol)

    def _create_transaction(self, tx_data, account_mapping: dict):
        """Create transaction from beancount data"""
        from fractions import Fraction

        from gnucash import GncNumeric, Split

        from infrastructure.gnucash.utils import (
            numeric_to_fraction,
            string_to_gnc_numeric,
            to_money,
            transaction_under_construction,
        )

        book = self.repository.book
        commodity_table = book.get_table()

        # Create transaction. Anything raised while it is being built takes it
        # with it — a missing account, a currency the book does not carry, or
        # a quantity `string_to_gnc_numeric` refuses. Abandoned instead, the
        # entry stays in the open book with whatever splits were attached
        # before the refusal, which duplicate matching and every balance in
        # the same run can then see.
        with transaction_under_construction(book) as transaction:
            # What the transaction is denominated in. A posting that states a
            # total or a rate says so outright — `@@ 18200.01 CAD` means "this
            # posting is worth that many CAD", so CAD is the currency the
            # entry is kept in — and that is the only answer that holds when
            # the postings are in different currencies.
            #
            # Failing that, the first posting that is *in* a currency. Taken
            # from the first posting whatever it held, a share purchase was
            # denominated in the share: `Assets:Fund 12.345 FUND.FUNDX @@
            # 1234.50 CAD` made FUNDX the transaction's currency, its cash
            # side was then valued in units of the fund, and the holding came
            # back as 1,234.500 units — the CAD figure wearing the fund's
            # name. And "first currency posting" alone is not enough either:
            # ¥2,000,000 bought with CAD leads with a JPY posting, which is a
            # currency, and denominating the entry in yen rounded 18,200.01
            # CAD to ¥18,200 and lost the balance with it.
            #
            # A file with neither falls to what the first posting holds, which
            # is how a currency the file gives a symbol of its own — the
            # symbol is not the mnemonic — is still found.
            currency = None
            for posting in tx_data.postings:
                if posting.price_commodity:
                    currency = commodity_table.lookup(
                        'CURRENCY', posting.price_commodity)
                    if currency is not None:
                        break
            if currency is None:
                for posting in tx_data.postings:
                    found = commodity_table.lookup('CURRENCY',
                                                   posting.commodity)
                    if found is not None:
                        currency = found
                        break
            if currency is None:
                currency = self._commodity_named(
                    tx_data.postings[0].commodity, commodity_table)
            if currency is None:
                raise ValueError(
                    f"The transaction at {tx_data.date:%Y-%m-%d} is in "
                    f"{tx_data.postings[0].commodity}, which this file never "
                    f"declares and the book does not carry")

            # And it has to be a currency. An entry with no money in it — a
            # holding moved between two accounts in kind — leaves a security
            # as the only candidate, and GnuCash takes it in memory and does
            # not keep it: measured, the transaction read back denominated in
            # the book's own currency after a save, so 10 units were left
            # valued as 10 dollars, a figure with no source in the file.
            # GnuCash records such a transfer the way its own register does,
            # with what the units are worth on it.
            if (currency.get_namespace() or '').upper() != 'CURRENCY':
                raise ValueError(
                    f"The transaction at {tx_data.date:%Y-%m-%d} has no "
                    f"posting in a currency, so the only thing left to "
                    f"denominate it in is {currency.get_mnemonic()}, which is "
                    f"a security — GnuCash keeps every transaction in a "
                    f"currency and does not keep this one past a save. State "
                    f"what the units are worth: `@ rate CUR` or "
                    f"`@@ total CUR` on each posting")

            transaction.SetCurrency(currency)

            # Set transaction properties
            description = tx_data.narration or ""
            num = tx_data.payee or ""

            if num:
                transaction.SetNum(num)
            if description:
                transaction.SetDescription(description)

            # Set date
            transaction.SetDatePostedSecsNormalized(tx_data.date)

            # Set notes if present
            if tx_data.gnucash_notes:
                transaction.SetNotes(tx_data.gnucash_notes)

            # Set doclink/association if present
            if tx_data.gnucash_doclink:
                try:
                    transaction.SetDocLink(tx_data.gnucash_doclink)
                except AttributeError:
                    with contextlib.suppress(AttributeError):
                        transaction.SetAssociation(tx_data.gnucash_doclink)

            # Create splits
            for posting in tx_data.postings:
                # Straight off the mapping: the parse refuses a posting on an
                # account the file never opened, and an `open` that names no
                # account, so every posting account is in it and names one.
                gnucash_account_name = account_mapping[posting.account]

                account = self.repository.get_account(gnucash_account_name)
                if not account:
                    raise ValueError(
                        f"Account {gnucash_account_name} not found in GnuCash")

                # Get account commodity
                account_commodity = account.GetCommodity()

                # And it is what the posting says it holds. The commodity on
                # the posting line was read for the currency of the entry and
                # then never asked about again: the amount went to the account
                # in whatever the account holds, so `Assets:Bank 50.00 USD` on
                # a CAD account booked 50.00 CAD — the figure kept, its
                # currency thrown away, and the run reporting success. Which
                # is the plainest hand-edit there is: change the account on a
                # posting and leave the commodity behind.
                stated_commodity = self._commodity_named(
                    posting.commodity, commodity_table)
                if stated_commodity is None or (
                        (stated_commodity.get_namespace(),
                         stated_commodity.get_mnemonic())
                        != (account_commodity.get_namespace(),
                            account_commodity.get_mnemonic())):
                    raise ValueError(
                        f"The posting {posting.account} {posting.amount} "
                        f"{posting.commodity} is in a commodity the account "
                        f"does not hold — {gnucash_account_name} is kept in "
                        f"{account_commodity.get_mnemonic()}")

                # Create split
                split = Split(book)
                split.SetParent(transaction)
                split.SetAccount(account)

                # Set amount, and value it. A posting in the transaction's own
                # currency has one figure and its value is its amount; one in
                # another commodity has two, and the second is what the
                # `@ <rate> <commodity>` tail states. Valued at its amount
                # regardless, 12.345 units of a fund entered as 12.345 CAD
                # against 1,234.50 of cash, and GnuCash balanced the
                # difference by inventing an `Imbalance-FUNDX` account holding
                # 1,222.15 units of the fund.
                # A posting in a commodity that is not the transaction's has
                # two figures, and nothing here can work the second one out.
                # Valued at its own amount it was silently wrong in exactly
                # the way the empty-basket refusal is written against: 100.00
                # USD entered as 100.00 CAD against 135.00 of cash, with
                # GnuCash inventing `Imbalance-USD 35.00` — measured, from
                # the plainest hand-edit there is, leaving the rate off.
                # `{}` was refused and this was not.
                #
                # Zero units are exempt: nothing times any rate is nothing,
                # so there is no second figure to state and asking for one
                # refused a posting this tool's own export writes.
                if (posting.price is None
                        and Fraction(posting.amount) != 0
                        and account_commodity is not None
                        and (account_commodity.get_mnemonic()
                             != currency.get_mnemonic())):
                    raise ValueError(
                        f"The posting {posting.account} {posting.amount} "
                        f"{posting.commodity} is in a different commodity "
                        f"from its transaction ("
                        f"{currency.get_mnemonic()}) and says nothing about "
                        f"what it is worth in it — state it: `@ rate "
                        f"{currency.get_mnemonic()}`, `@@ total "
                        f"{currency.get_mnemonic()}` or `{{rate "
                        f"{currency.get_mnemonic()}}}`")

                # And against the unit the account is kept to, which is the
                # question `string_to_gnc_numeric` does not ask: it judges a
                # currency against its commodity's fraction and lets a
                # security through as the exact ratio. `SetAmount` then rounds
                # to the account's unit — measured twice in this suite — so
                # `12.3456` on a thousandths fund account was stored as 12.346
                # with `Errors: 0`, the value computed from the figure the
                # file stated and the quantity silently changed. The plaintext
                # importer refuses the identical figure; which format the
                # reader edited should not decide.
                #
                # Through the plaintext importer's own judge, so the two give
                # the same diagnosis for the same figure. Written afresh here
                # it had only the account branch, so a sub-cent CAD posting
                # was told to widen `gnucash-scu:` — and the same file then
                # failed the currency check, which is a dead end for money.
                # `stated_money` branches: a currency that cannot hold the
                # figure says so, and only an account too coarse for a figure
                # its currency *can* hold suggests a finer unit.
                stated_money(
                    posting.amount, account_commodity,
                    f'the posting on {posting.account!r}',
                    scu=account.GetCommoditySCU())

                amount = string_to_gnc_numeric(posting.amount, account_commodity)
                split.SetAmount(amount)
                if posting.price:
                    # In the currency the entry is denominated in, because
                    # that is the only currency a split's value can be in.
                    # Applied as though every rate already were — true of what
                    # this tool writes, which always quotes the transaction's
                    # currency, and not of what a person writes. 15,000 yen
                    # quoted per USD in a CAD entry was valued at 100.00 CAD
                    # instead of the 135.00 it is worth, and an exchange ratio
                    # (`-100 OLDCO @ 0.5 NEWCO`) valued the shares given up at
                    # 50.00 CAD — a figure with no source in the file. Both
                    # measured; the first balanced its own error and reported
                    # success.
                    priced_in = self._commodity_named(
                        posting.price_commodity, commodity_table)
                    if priced_in is None or (
                            (priced_in.get_namespace(),
                             priced_in.get_mnemonic())
                            != (currency.get_namespace(),
                                currency.get_mnemonic())):
                        raise ValueError(
                            f"The posting {posting.account} {posting.amount} "
                            f"{posting.commodity} states its rate in "
                            f"{posting.price_commodity} while the transaction "
                            f"is denominated in {currency.get_mnemonic()} — a "
                            f"split's value is in the transaction's currency, "
                            f"so the rate has to be too: state `@ rate "
                            f"{currency.get_mnemonic()}`, `@@ total "
                            f"{currency.get_mnemonic()}` or `{{rate "
                            f"{currency.get_mnemonic()}}}`")

                    # Rate, then value, then the amount again — the order the
                    # plaintext importer arrived at, and each step is needed.
                    # `SetSharePrice` alone and `SetValue` alone each rewrite
                    # the *amount* to amount × rate on a split whose commodity
                    # is not the transaction's: 12.345 units of a fund became
                    # 1,234.500 of them, which is the CAD figure wearing the
                    # fund's name. Restating the amount last is what holds it.
                    rate = Fraction(posting.price)
                    split.SetSharePrice(GncNumeric(rate.numerator,
                                                   rate.denominator))
                    split.SetValue(to_money(
                        numeric_to_fraction(amount) * rate,
                        currency.get_fraction()))
                    split.SetAmount(amount)
                else:
                    split.SetValue(amount)

                # Set memo and action if present
                if posting.gnucash_memo:
                    split.SetMemo(posting.gnucash_memo)
                if posting.gnucash_action:
                    split.SetAction(posting.gnucash_action)

        return transaction
