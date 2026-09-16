# Q-042 — Print the balance sheet and income statement as plaintext through a customized GnuCash report, in the currency the book is kept in

Every figure below was measured by running GnuCash itself. The report figures were measured on all eleven supported builds — 3.4, 3.8, 4.4, 4.8, 4.13, 5.5, 5.10, 5.13, 5.14, 5.15 and 5.16. Where a row gives fewer builds, those are the builds it was measured on.

## What it should do

A multi-currency book needs a balance sheet and an income statement a reader can trust, in the book's own currency.

- `balance-sheet`, `income-statement` and `report` print the statements as plaintext through a customized GnuCash report: GnuCash's Balance Sheet and Income Statement reports, written to output plain text. GnuCash runs the report, adds up every figure, and converts it through the book's price database at the report's own price source. A user can be confident that no figure on the page is calculated by gnucash-plaintext.
- The statements are in the currency the book is kept in: a book kept in HKD is printed in HK$, with its USD and CAD converted into HKD by GnuCash.
- `--output-format html` and `pdf` give the page of GnuCash's Balance Sheet or Income Statement report as GnuCash ships it.
- A rates file or a prices file gives prices for one run, and GnuCash's report prices from them. A rate may be exact, as a fraction.

## The figures it should print

The book used for these measurements, all in 2026, kept in CAD:

- USD Bank: 3,000.00 USD opened on 01-03, less 2,000.00 USD paid for 10 NASDAQ:AMZN on 01-04, plus 500.00 USD of consulting income on 01-20.
- HKD Bank: 5,500.00 HKD opened on 01-03.
- CAD Bank: 1,000.00 CAD opened on 01-03, less 100.00 CAD of fees on 01-21.
- Prices: USD in CAD 1.30 on 01-02 and 1.40 on 02-02; HKD stored only the other way round, CAD in HKD 5.5 on 01-10; NASDAQ:AMZN in USD 210 on 01-15 and 220 on 02-15.

GnuCash's Balance Sheet report gives these figures as of 2026-01-25, and the plaintext page prints them:

| line | figure |
|---|---|
| USD Bank | C$2,100.00 |
| HKD Bank | C$1,000.00 |
| AMZN | C$2,940.00, the shares at their market price |
| Retained Earnings | C$600.00 |
| Unrealized Gains | C$140.00 |
| Total assets | C$6,940.00 |

GnuCash's Income Statement report for 2026-01-01 to 2026-01-25 gives Consulting C$700.00, Fees C$100.00 and net income C$600.00, and the plaintext page prints them.

## What was measured

### GnuCash's reports run through the report engine `print-invoice` already uses

`services/gnucash_report.py` renders GnuCash's invoice report through Guile. The same setup renders GnuCash's Balance Sheet and Income Statement reports (`what_gnucash_own_balance_sheet_and_income_statement_give_probe.py`).

| | GnuCash 3.4, 3.8 | GnuCash 4.4 and later |
|---|---|---|
| module that registers the reports | `(gnucash report standard-reports)` | `(gnucash reports standard balance-sheet)`, `(gnucash reports standard income-statement)` |
| Balance Sheet template guid | `c4173ac99b2b448289bf4d11c731af13` | the same |
| Income Statement template guid | `0b81a3bdfd504aff849ec2e8630524bc` | the same |
| options the commands set | `General / Balance Sheet Date`; `General / Start Date` and `End Date`; `Commodities / Report's currency`; `Commodities / Price Source` | the same option names |

On the book above, every build gives the same figures: USD Bank C$2,100.00, AMZN C$2,940.00, total assets C$6,940.00 as of 2026-01-25; total assets C$7,080.00 as of 2026-03-01; net income C$600.00 for 2026-01-01 to 2026-01-25.

### A customized report may output plain text

`gnc:report-render-html` applies a style sheet only to a document object. A renderer that returns a string has that string handed back unchanged, with no style sheet and no HTML: `((string? doc) doc)`, read in `report.scm` on 3.4 and 3.8 and in `report-core.scm` on 4.4 and 5.10. So a GnuCash report, customized, can output plain text.

What such a report can read from GnuCash:

| | where it was measured |
|---|---|
| GnuCash's account table gives each row `account-bal`, `recursive-bal`, `display-depth`, `row-type` and `account-name` | 3.4, 3.8, 5.10 |
| commodity collectors take `'add`, `'merge`, `'minusmerge` and `'format` | 3.4, 5.10 |
| `gnc:collector+` | absent on 3.4; present on 3.8, 4.4 and 5.10 |
| the Balance Sheet's and Income Statement's option names | the same on 3.4, 3.8, 4.4 and 5.10 |
| the Balance Sheet's figures: asset, liability, equity and income-and-expense balances as of the date, trading balances when the book uses trading accounts, and unrealized gains as the assets and liabilities less their value at cost | the same arithmetic on 3.4, 3.8, 4.4 and 5.10, written with collector methods on 3.4 and `gnc:collector+` from 3.8 |

### How GnuCash's reports choose a price

Both reports have an option `Commodities / Price Source`, and both default it to `pricedb-nearest` on every build (`which_price_sources_the_reports_offer_probe.py`). That is why the 2026-01-25 figures use the USD rate of 02-02, the price nearest in time, although it is after the report date.

| GnuCash | the choices `Price Source` offers |
|---|---|
| 3.4, 3.8, 4.4 | `average-cost`, `weighted-average`, `pricedb-latest`, `pricedb-nearest` |
| 4.8 and later | the same, and `pricedb-before` ("Last up through report date") |

GnuCash 3.4 to 4.13 give each choice as a vector whose first element is its name, and 5.x lists them through the option itself.

### A price added for the run

A price added to the price database of a book opened read-only, at `gnc_dmy2time64_end` of the report date, from the source `user:price-editor`, is the price GnuCash's Balance Sheet report uses (`a_rates_file_as_prices_probe.py`, on 5.10 and 3.8). USD Bank's 1,500.00 USD came out at C$2,250.00, the added price of 1.50, in all three cases:

1. the book has no USD price that day;
2. the book already prices USD at 1.40 that day, from the same source;
3. the book's nearest USD price is twelve hours after the end of the day.

After the book was closed, its prices read back as they were before.

### A book that uses trading accounts

A book with `Accounts / Use Trading Accounts` set, and the book above imported into it, holds the accounts GnuCash creates for trading splits: `Trading`, `Trading.NASDAQ.AMZN` and `Trading.CURRENCY.USD` (`what_the_balance_sheet_prints_for_a_book_using_trading_accounts_probe.py`, on 5.10). GnuCash's shipped Balance Sheet report then prints the shares' gain as Trading Gains C$140.00, with no Unrealized Gains line. The plaintext page prints the same figures, and the test for it passes on 3.4 and 5.10.

### GnuCash stores no currency for a book

On a book kept in HKD that also holds USD and CAD — top-level Assets and Equity in HKD, and an HKD, a USD and a CAD bank account beneath them (`what_currency_gnucash_says_a_book_is_kept_in_probe.py`, on 3.4, 3.8, 4.4 and 5.10):

| asked | answer |
|---|---|
| the root account's commodity | none |
| `gnc_book_get_book_currency_name` | none on 3.4 and 3.8; the call does not exist on 4.4 and 5.10 |
| `gnc_default_currency`, `gnc_default_report_currency` | USD on 3.4 and 3.8: GnuCash's preference, not the book; the calls do not exist on 4.4 and 5.10 |
| the Balance Sheet's `Report's currency` when nothing sets it | USD |

So GnuCash's report must always be told the currency, and gnucash-plaintext has to find the book's currency itself.

### GnuCash's account conversion calls do not give its reports' figures

`xaccAccountGetBalanceAsOfDateInCurrency` exists on every build, but on 3.4, 3.8 and 4.4 it prices at the latest price whatever the date (USD Bank C$1,400.00 as of 2026-01-25), and from 4.8 at the last price up to the date (C$1,300.00). Neither is what GnuCash's Balance Sheet report gives by default (C$2,100.00 for 1,500.00 USD, the 1.40 rate). The reports are what GnuCash shows a user, so a report is what the commands run (`which_calls_convert_a_balance_to_another_currency_probe.py`, `what_gnucash_currency_conversion_calls_give_probe.py`).

## Decisions

### The book's currency

The first of these that gives one:

1. `--currency HKD` on the command;
2. the `company` block's custom key `base_currency: "HKD"`, kept in the book with the block's other custom keys;
3. the currency of the book's top-level accounts, when every top-level account held in a currency is held in the same one. Accounts beneath them may hold any currency.

Where none of them gives one — no key, and top-level accounts in more than one currency or in none — the command is refused, and the refusal says how to state the currency. A currency GnuCash does not know is refused as well.

### Every figure comes from a GnuCash report

- `--output-format text`, the default, is printed by two customized GnuCash reports in `infrastructure/gnucash/reports/balance-sheet-and-income-statement-as-text.scm`, which the package ships as package data, "Balance Sheet (plain text)" and "Income Statement (plain text)". Each is written from GnuCash's `balance-sheet.scm` or `income-statement.scm`: registered with `gnc:define-report`, given GnuCash's own report's options, making the same GnuCash calls for every figure, and returning its page as plain text.
- The report file is package data of `infrastructure.gnucash`, so an installed package carries it. A wheel built from the tree and installed outside it printed the plaintext balance sheet on 5.10, with no source folder on the import path.
- `--output-format html` writes the page of GnuCash's Balance Sheet or Income Statement report as GnuCash ships it, and `pdf` prints that page through WebKit, as `print-invoice` prints an invoice.
- `Report's currency` is always set, to the book's currency.
- `Price Source` is GnuCash's own default unless `--price-source` gives one of the choices the build offers. A choice the build does not offer is refused, and the refusal lists the ones it does.

### Rates and prices given in a file

- `--fx-rates` and `--prices` are added to the book's price database for the run and never saved, and GnuCash's report prices from them.
- A rate is a price of a currency in the report's currency. `USD: 1.40` is USD in the report's currency. `USD/HKD` states both currencies, and is refused where HKD is not the report's currency.
- A rate or a price may be a fraction, `HKD: 2/11`, as `value:` in a `price` block may.
- A price with no date is added at the end of each day a statement of the run is for. A dated price is added at the time GnuCash gives its date, as a `price` block with a date is.
- A security's price with no currency is in the currency of the book's own prices of that security, or, where the book has none, the currency of the transactions that hold it. Where that is more than one currency, the file has to give it, as `AMZN/USD: 250`.

## Tests

- `tests/integration/test_the_currency_a_book_is_kept_in.py`: each source of the book's currency, the order they are tried in, and each refusal.
- `tests/integration/test_the_statements_are_printed_by_customized_gnucash_reports.py`: a book kept in HKD that holds USD and CAD, whose statements are printed in HK$ with the USD and CAD converted; a CAD book with USD, HKD and shares, whose figures are those GnuCash's reports give; the plaintext page line by line; the HTML page; the PDF page read back as text; `--currency`; a net loss and retained losses; a book that uses trading accounts; a book with no accounts.
- `tests/unit/test_every_file_in_a_shipped_package_is_shipped.py`: every file inside a package the wheel ships is matched by `package-data`, the report file included. The suite installs the project editable, which reads the source folder, so no other test can see a file the wheel leaves out.
- `tests/integration/test_a_rates_file_prices_gnucash_reports_for_the_run_only.py`: a rates file and a prices file change the figures GnuCash's report gives and leave the book's prices unchanged; dated rates, fractions, a same-day rate, refusals; `--price-source`.
- `tests/integration/test_reports.py`, `test_report_command_arguments.py`, `test_cli_income_statement.py`, `test_balance_sheet_account_types.py`: the commands' arguments and every account type, against the figures GnuCash's reports give.

## Probes

| probe | what it measures |
|---|---|
| `tests/research/what_gnucash_own_balance_sheet_and_income_statement_give_probe.py` | GnuCash's Balance Sheet and Income Statement reports as GnuCash ships them, on the book above: their options, and the pages they render |
| `tests/research/which_price_sources_the_reports_offer_probe.py` | the `Price Source` choices each report offers |
| `tests/research/a_rates_file_as_prices_probe.py` | whether a price added for the run is the one GnuCash's Balance Sheet report uses, and whether the book keeps it |
| `tests/research/what_the_balance_sheet_prints_for_a_book_using_trading_accounts_probe.py` | what GnuCash's Balance Sheet report and the plaintext page print for a book whose "Use Trading Accounts" option is on |
| `tests/research/what_currency_gnucash_says_a_book_is_kept_in_probe.py` | what GnuCash says a book's currency is, for a book kept in HKD that holds USD and CAD |
| `tests/research/which_calls_convert_a_balance_to_another_currency_probe.py` | which currency conversion calls each build has |
| `tests/research/what_gnucash_currency_conversion_calls_give_probe.py` | what those calls give on the book above |
