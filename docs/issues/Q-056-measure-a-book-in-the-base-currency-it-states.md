---
id: Q-056
title: "A book is measured in the base currency it states, not in CAD"
category: quality
severity: high
status: closed
---

## What was asked

The author keeps books in more than one currency, and a Hong Kong company's
book is kept in Hong Kong dollars. Cost bases work only in Canadian dollars:
`BASE_CURRENCY = 'CAD'` in `services/foreign_currency.py`, read in about a
hundred places. Q-043 and Q-049 recorded the limit and did not remove it.

## The rules

The author's, stated before the work began:

- A book states its base currency in its `company` block:
  `base_currency: "HKD"`.
- When gnucash-plaintext runs there is always exactly one base currency.
- Everything is measured in it. Every other currency is foreign, and foreign
  currency carries a cost basis: what it cost in the base currency. The base
  currency carries none. A realized gain and an unrealized one are measured in
  the base currency, and so are a foreign invoice or bill and its settlement,
  the balance sheet, `fx-balances` and the verify checks. A rates file quotes
  rates into the base currency. CAD is not special.
- Stating the base currency is all a user does. The cost bases follow from it.
- Where a book states no base currency, gnucash-plaintext does what it did
  before this change.

## What the book did before

Measured on GnuCash 5.10, on the Hong Kong company the scenario test builds
(`tests/scenario/test_a_hong_kong_company_measures_its_usd_cny_and_eur_in_hkd.py`),
every step imported with the code as it was:

- `base_currency: "HKD"` was stored and read by the reports, and by nothing
  that keeps a cost basis.
- INV-001 (10,000.00 USD posted at 7.80 HKD/USD, 78,000.00 HKD) and INV-002
  (5,000.00 USD at 7.75 HKD/USD, 38,750.00 HKD), both collected into the USD
  account,
  opened no cost basis. Neither did 50,000.00 CNY bought for 54,000.00 HKD.
  `fx-balances` printed "No foreign-currency cost bases found."
- The sale of 8,000.00 USD for 62,800.00 HKD, drawing on INV-001's cost basis,
  was refused: "cost_basis_split_guid '…111' matches a split that is no USD
  cost basis".
- The company paid the EUR bill with EUR it had bought for the purpose. That
  payment was refused the same way, and the bill was left unpaid.
- The balance sheet at the year end did not balance: it stated 1,117,950.00
  HKD of assets against 1,117,250.00 HKD of liabilities and equity.

A cost was read only from a CAD figure. The revenue of a USD invoice in this
book is stated in HKD, so the invoice opened nothing, and everything that
spent its dollars had nothing to draw on.

## What the book does now

The same steps, as the scenario test states them:

| step | what the book holds afterwards |
|---|---|
| 1. INV-001, 10,000.00 USD posted at 7.80 HKD/USD, collected into the USD account | a USD cost basis of 10,000.00 USD costing 78,000.00 HKD; nothing realized, since collecting into a USD account converts nothing |
| 2. INV-002, 5,000.00 USD posted at 7.75 HKD/USD, collected into the same account | a second USD cost basis of 5,000.00 USD costing 38,750.00 HKD |
| 3. 8,000.00 USD sold at 7.85 HKD/USD for 62,800.00 HKD, from INV-001's cost basis | 400.00 HKD realized; INV-001's cost basis has 2,000.00 USD left, costing 15,600.00 HKD |
| 4. 50,000.00 CNY bought at 1.08 HKD/CNY | a CNY cost basis costing 54,000.00 HKD |
| 5. BILL-EU-001, 2,000.00 EUR posted at 8.50 HKD/EUR, paid with 2,000.00 EUR bought at 8.45 HKD/EUR | 100.00 HKD realized; nothing left on either cost basis |
| 6. USD priced at 7.83 HKD/USD and CNY at 1.09 HKD/CNY at the year end | 7,000.00 USD costing 54,350.00 HKD worth 54,810.00 HKD, and 50,000.00 CNY costing 54,000.00 HKD worth 54,500.00 HKD: 960.00 HKD unrealized |

At the year end the book holds 991,900.00 HKD, 7,000.00 USD and 50,000.00
CNY, 1,101,210.00 HKD in all, against 1,000,000.00 HKD of share capital,
100,250.00 HKD of retained earnings (116,750.00 HKD of sales and 500.00 HKD
realized, less 17,000.00 HKD of design services) and 960.00 HKD unrealized.

## What changed

- `base_currency()` in `services/foreign_currency.py` replaces the constant
  `BASE_CURRENCY = 'CAD'`. It returns the `base_currency:` of the book that
  is open, and CAD where the book states none.
- `GnuCashRepository.open` runs `WHAT_TO_READ_WHEN_A_BOOK_OPENS` once the
  book has loaded, and the base currency is read there. Opening a book
  forgets the base currency of the book before it. Closing a book does not
  forget it, because `fx-balances` prints each cost in the base currency after
  it has closed its book.
- `import` reads a `company` block's `base_currency:` in the file before it
  applies any part of the file.
- Every import applies the `company` block, with or without
  `--include-business-objects`, after the accounts and before the
  transactions. Before this, the block was applied only with the flag. A file
  stating `base_currency: "HKD"` imported without the flag then measured its
  run in HKD, left the book stating no base currency, and the next import
  measured the same book in CAD: the sale of the USD was refused as drawing on
  no cost basis. Customers, vendors, tax tables, invoices and bills still need
  the flag. `test_company_custom_book_keys.py` states it: a `company` block
  imported without the flag is in the book, and a customer and a vendor in the
  same file are not.
- `services/fx_rates.py` quotes each rate in the base currency. A pair such
  as `USD/HKD:` is accepted in a book measured in HKD. A pair into another
  currency is refused when a rate is looked up, because the rates file is read
  before the book is opened.
- `use_cases/account_balance.py` converts to the base currency.
- `tests/conftest.py` starts every test in the base currency of a book that
  states none. One pytest process runs every test, so a test that opens no
  book would otherwise use the base currency of the last book opened.

## Tests

- `tests/scenario/test_a_hong_kong_company_measures_its_usd_cny_and_eur_in_hkd.py`:
  the six steps above.
- `tests/scenario/test_a_us_company_measures_its_cad_in_usd.py`: a book stating
  `base_currency: "USD"`. Two CAD invoices were posted at 0.74 USD/CAD and 0.72
  USD/CAD and paid into a CAD account. 15,000.00 CAD was sold at 0.75 USD/CAD,
  which realized 150.00 USD. With a price of 0.73 USD/CAD on 2026-12-31, the
  balance sheet states 50.00 USD unrealized and balances at 522,200.00 USD.
- Each payment transaction in both books states `txn_type: P` and its
  `owner:`, as an export writes it. GnuCash 3.4 does not mark a transaction
  linked by `txn_guid:` as a payment, so without the two lines its export
  differed from every later version's.
- `tests/integration/test_an_hkd_book_stating_no_base_currency_gets_no_cost_basis.py`:
  a book kept in HKD that states no base currency is still measured in CAD, and
  opens no cost basis.
- `tests/unit/services/test_fx_rates_dated.py`: in a book measured in HKD,
  `USD/HKD: 7.8` quotes USD in HKD; in a book measured in CAD, `USD/EUR` is
  refused with the two ways to write it.
