"""Which GnuCash calls convert a balance or an amount to another currency, on this build (Q-042).

Asked of the SWIG bindings (`gnucash.gnucash_core_c`, and the `Account` class's
own methods) and of the C libraries through ctypes, after `load_gnc_engine`
has made them global.

Run: ./scripts/run.sh <tag> env PYTHONPATH=/workspace python3 tests/research/which_calls_convert_a_balance_to_another_currency_probe.py
"""

import ctypes

import gnucash.gnucash_core_c as core
from gnucash import Account

from infrastructure.gnucash.engine import load_gnc_engine

NAMES = [
    # an account's balance, converted
    'xaccAccountGetBalanceInCurrency',
    'xaccAccountGetBalanceAsOfDateInCurrency',
    'xaccAccountGetPresentBalanceInCurrency',
    'xaccAccountGetNoclosingBalanceAsOfDateInCurrency',
    'xaccAccountGetBalanceChangeForPeriod',
    'xaccAccountGetNoclosingBalanceChangeForPeriod',
    'xaccAccountGetNoclosingBalanceChangeInCurrencyForPeriod',
    'xaccAccountConvertBalanceToCurrency',
    'xaccAccountConvertBalanceToCurrencyAsOfDate',
    # an amount, converted through the price database
    'gnc_pricedb_convert_balance_latest_price',
    'gnc_pricedb_convert_balance_nearest_price_t64',
    'gnc_pricedb_convert_balance_nearest_before_price_t64',
    # a price, looked up
    'gnc_pricedb_lookup_latest',
    'gnc_pricedb_lookup_day_t64',
    'gnc_pricedb_lookup_nearest_in_time64',
    'gnc_pricedb_lookup_nearest_before_t64',
    'gnc_pricedb_get_latest_price',
    'gnc_pricedb_get_nearest_price',
    'gnc_pricedb_get_nearest_before_price',
]


def main():
    lib = load_gnc_engine()
    version = lib.gnc_version().decode()
    process = ctypes.CDLL(None)
    for name in NAMES:
        in_swig = hasattr(core, name)
        try:
            getattr(process, name)
            in_c = True
        except AttributeError:
            in_c = False
        print(f'{version}\t{name}\tswig={in_swig}\tc={in_c}')
    methods = sorted(m for m in dir(Account) if 'Currency' in m or 'Convert' in m or 'ForPeriod' in m)
    print(f'{version}\tAccount methods\t{methods}')


if __name__ == '__main__':
    main()
