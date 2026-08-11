# 100 USD bought for 140.00 CAD, and a payable to spend it on.
#
# The rate README's worked example uses, so the block it prints can be read
# verbatim against this book — only the basis guid, which no file can know in
# advance, is substituted.
2026-01-01 open Assets
	type: Asset
	commodity.namespace: "CURRENCY"
	commodity.mnemonic: "CAD"
2026-01-01 open Assets:Bank
	type: Bank
	commodity.namespace: "CURRENCY"
	commodity.mnemonic: "CAD"
2026-01-01 open Assets:Bank:USD
	type: Bank
	commodity.namespace: "CURRENCY"
	commodity.mnemonic: "USD"
2026-01-01 open Liabilities
	type: Liability
	commodity.namespace: "CURRENCY"
	commodity.mnemonic: "CAD"
2026-01-01 open Liabilities:Accounts Payable USD
	type: Liability
	commodity.namespace: "CURRENCY"
	commodity.mnemonic: "USD"

2026-02-01 * "Buy 100 USD at 1.40"
	currency.mnemonic: "CAD"
	Assets:Bank:USD 100.00 USD
		share_price: "1.40"
		value: "140.00"
	Assets:Bank -140.00 CAD
