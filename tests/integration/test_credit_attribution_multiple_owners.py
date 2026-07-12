"""Overpayment credits are tied to a specific vendor / customer.

A book with three vendors and three customers, each overpaid by a
distinct amount, so a credit is unambiguously attributable to its owner:

  vendor V-1 +10, V-2 +20, V-3 +30   (open AP credit lots)
  customer C-1 +15, C-2 +25, C-3 +35 (open AR credit lots)

`find-prepayments --vendor <id>` / `--customer <id>` filters to one
owner's credits, and the unfiltered command lists all six with a
per-owner total — this is how a user learns which supplier / customer a
credit belongs to and applies it to the right next bill / invoice.
"""
from pathlib import Path

from click.testing import CliRunner

from cli.main import cli

FIXTURES = Path('tests/fixtures')
ACCOUNTS = str(FIXTURES / 'q019_accounts.txt')
FIXTURE = 'credit_attribution_three_vendors_three_customers.txt'


def _book(runner, tmp_path):
    gf = tmp_path / 'book.gnucash'
    r = runner.invoke(cli, ['import', '--new', str(gf), ACCOUNTS])
    assert r.exit_code == 0, r.output
    fx = tmp_path / FIXTURE
    fx.write_text((FIXTURES / FIXTURE).read_text())
    r = runner.invoke(cli, ['import', str(gf), str(fx),
                            '--include-business-objects'])
    assert r.exit_code == 0, r.output
    return gf


def _credits(gf, *, vendor_id=None, customer_id=None):
    """{owner_id: total credit} from find_prepayments_in_book."""
    from repositories.gnucash_repository import GnuCashRepository
    from use_cases.unpost_business_objects import find_prepayments_in_book
    repo = GnuCashRepository(str(gf))
    repo.open()
    try:
        out = {}
        for c in find_prepayments_in_book(
                repo.book, customer_id=customer_id, vendor_id=vendor_id):
            out[c.owner_id] = round(out.get(c.owner_id, 0.0) + float(c.amount), 2)
        return out
    finally:
        repo.close()


def test_credit_filter_returns_only_that_vendor(tmp_path):
    """`find_prepayments(vendor_id='V-2')` returns only V-2's $20 credit —
    not V-1/V-3 and no customers."""
    runner = CliRunner()
    gf = _book(runner, tmp_path)
    assert _credits(gf, vendor_id='V-2') == {'V-2': 20.00}
    assert _credits(gf, vendor_id='V-1') == {'V-1': 10.00}
    assert _credits(gf, vendor_id='V-3') == {'V-3': 30.00}


def test_credit_filter_returns_only_that_customer(tmp_path):
    """`find_prepayments(customer_id='C-3')` returns only C-3's $35 credit."""
    runner = CliRunner()
    gf = _book(runner, tmp_path)
    assert _credits(gf, customer_id='C-3') == {'C-3': 35.00}
    assert _credits(gf, customer_id='C-1') == {'C-1': 15.00}


def test_all_six_credits_are_attributed_to_their_owner(tmp_path):
    """Unfiltered: every credit is present and keyed to the right owner."""
    runner = CliRunner()
    gf = _book(runner, tmp_path)
    assert _credits(gf) == {
        'V-1': 10.00, 'V-2': 20.00, 'V-3': 30.00,
        'C-1': 15.00, 'C-2': 25.00, 'C-3': 35.00,
    }


def test_cli_find_prepayments_vendor_filter_shows_one_owner(tmp_path):
    """`find-prepayments --vendor V-2` names V-2 and its $20, and does NOT
    leak the other owners' credits into the output."""
    runner = CliRunner()
    gf = _book(runner, tmp_path)
    r = runner.invoke(cli, ['find-prepayments', str(gf), '--vendor', 'V-2'])
    assert r.exit_code == 0, r.output
    assert 'vendor V-2' in r.output and 'CAD 20.00' in r.output, r.output
    for other in ('V-1', 'V-3', 'C-1', 'C-2', 'C-3'):
        assert f'vendor {other}' not in r.output and f'customer {other}' \
            not in r.output, f'{other} leaked into V-2 filter:\n{r.output}'
    assert 'Total credit available: CAD 20.00 for vendor V-2' in r.output, r.output


def test_cli_find_prepayments_customer_filter_shows_one_owner(tmp_path):
    """`find-prepayments --customer C-1` names C-1 and its $15 only."""
    runner = CliRunner()
    gf = _book(runner, tmp_path)
    r = runner.invoke(cli, ['find-prepayments', str(gf), '--customer', 'C-1'])
    assert r.exit_code == 0, r.output
    assert 'customer C-1' in r.output and 'CAD 15.00' in r.output, r.output
    assert 'Total credit available: CAD 15.00 for customer C-1' in r.output, r.output
