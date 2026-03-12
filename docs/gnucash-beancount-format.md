# GnuCash-Beancount Format

**GnuCash-Beancount** (bc-gnc) is a special beancount format that enables bidirectional conversion between GnuCash and beancount with zero data loss.

## Overview

While standard beancount focuses on minimal syntax and implicit account declarations, GnuCash-Beancount is a strict subset that requires explicit metadata to preserve all GnuCash data. This enables full round-trip conversion:

```
Plaintext → GnuCash → Beancount → GnuCash → Plaintext
```

## Why GnuCash-Beancount?

**Standard beancount** allows:
- Implicit account declarations (accounts can be used without `open` directives)
- Spaces in account names are not allowed
- Minimal metadata requirements
- Focus on simplicity and human readability

**GnuCash-Beancount** requires:
- Explicit `open` directives for ALL accounts
- Full GnuCash metadata preservation (GUIDs, types, original names)
- Account name aliasing (beancount-safe name + original GnuCash name)
- All commodity declarations with GnuCash attributes

This enables:
- **Perfect reconstruction** of GnuCash files from beancount
- **Zero data loss** in round-trip conversions
- **GnuCash features preserved** (account types, placeholders, tax flags, etc.)
- **Flexible account names** (spaces, CJK characters, special characters via metadata)

## Key Differences from Standard Beancount

| Feature | Standard Beancount | GnuCash-Beancount |
|---------|-------------------|-------------------|
| Account declaration | Optional (implicit) | **Required** (explicit `open` directives) |
| Account names | No spaces allowed | Spaces replaced with dashes, original name in `gnucash-name` metadata |
| Commodity declaration | Optional | **Required** with full metadata |
| Metadata | Optional | **Required** (gnucash-guid, gnucash-type, etc.) |
| Account types | Inferred from prefix | Explicitly stored in `gnucash-type` metadata |
| File validation | Permissive | **Strict** (rejects files without required metadata) |

## Format Specification

### Commodity Declaration

Every commodity must include GnuCash-specific metadata:

```beancount
2010-06-30 commodity CNY
    gnucash-mnemonic: "CNY"
    gnucash-namespace: "CURRENCY"
    gnucash-fullname: "Yuan Renminbi"
    gnucash-fraction: "100"
```

**Required metadata:**
- `gnucash-mnemonic`: Original commodity symbol
- `gnucash-namespace`: Commodity namespace (e.g., "CURRENCY", "NASDAQ", "Crypto")
- `gnucash-fraction`: Smallest unit (100 = 2 decimals, 100000 = 5 decimals)

**Optional metadata:**
- `gnucash-fullname`: Full name of the commodity

**Commodity symbol format:**
- Spaces replaced with underscores (e.g., "Membership Rewards" → "MEMBERSHIP_REWARDS")
- All uppercase
- Namespace.Mnemonic format (e.g., "MEMBERSHIP_REWARDS.イオン")

### Account Declaration

Every account must be explicitly declared with full GnuCash metadata:

```beancount
2012-11-02 open Expenses:Groceries-And-Household CNY
    gnucash-name: "Expenses:Groceries & Household"
    gnucash-guid: "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
    gnucash-type: "EXPENSE"
    gnucash-placeholder: "0"
    gnucash-code: ""
    gnucash-description: "Groceries"
    gnucash-tax-related: "0"
```

**Required metadata:**
- `gnucash-name`: Original GnuCash account name (with spaces and special characters)
- `gnucash-guid`: Unique identifier for account matching
- `gnucash-type`: GnuCash account type (CASH, BANK, EXPENSE, INCOME, etc.)
- `gnucash-placeholder`: Whether account is a placeholder ("0" or "1")
- `gnucash-tax-related`: Whether account is tax-related ("0" or "1")

**Optional metadata:**
- `gnucash-code`: Account code
- `gnucash-description`: Account description

**Account name format:**
- Spaces replaced with dashes (e.g., "Cash in Wallet" → "Cash-in-Wallet")
- Special characters replaced with dashes (e.g., "Groceries & Household" → "Groceries-And-Household")
- Original name preserved in `gnucash-name` metadata
- Hierarchy preserved with colons (e.g., "Assets:Bank:Checking")

### Transaction Declaration

Transactions follow beancount format with GnuCash metadata:

```beancount
2024-03-14 * "Payee" "Description"
    gnucash-guid: "b1fd9fb8-3590-43dc-8802-a5f6b530bd9c"
    gnucash-notes: "Transaction notes"
    gnucash-doclink: "/path/to/receipt.pdf"
    Expenses:Groceries 29.27 CNY
        gnucash-memo: "Split memo"
        gnucash-action: "Split action"
    Assets:Bank:Checking -29.27 CNY
```

**Transaction metadata (optional):**
- `gnucash-guid`: Unique identifier for transaction matching
- `gnucash-notes`: Transaction notes
- `gnucash-doclink`: Link to external document

**Posting metadata (optional):**
- `gnucash-memo`: Split memo
- `gnucash-action`: Split action

## Usage

### Export GnuCash to GnuCash-Beancount

Export all data to GnuCash-Beancount format:

```bash
gnucash-plaintext export-beancount mybook.gnucash output.beancount
```

Export with filters:

```bash
# Export date range (transactions only - all accounts/commodities included)
gnucash-plaintext export-beancount mybook.gnucash output.beancount \
  --date-from 2024-01-01 --date-to 2024-12-31

# Export specific account (transactions only - all accounts/commodities included)
gnucash-plaintext export-beancount mybook.gnucash output.beancount \
  --account "Assets:Bank"
```

**Important:** Even when filtering transactions, ALL commodities and ALL accounts are exported. This is required for beancount - commodities and accounts must be declared before transactions can reference them.

### Import GnuCash-Beancount to GnuCash

Import from GnuCash-Beancount format:

```bash
gnucash-plaintext import-beancount output.gnucash input.beancount
```

Validate without importing (dry run):

```bash
gnucash-plaintext import-beancount output.gnucash input.beancount --dry-run
```

**Alternative syntax:**

```bash
# Using flags instead of positional arguments
gnucash-plaintext import-beancount -o output.gnucash -i input.beancount

# Dry run
gnucash-plaintext import-beancount -o output.gnucash -i input.beancount --dry-run
```

### Validation

The import command validates that the beancount file is GnuCash-compatible:

**Valid GnuCash-Beancount:**
- All accounts have explicit `open` directives
- All accounts have required `gnucash-*` metadata
- All commodities have required `gnucash-*` metadata
- No implicit accounts (accounts used without declaration)

**Invalid (standard beancount):**
- Missing `open` directives
- Missing required metadata
- Implicit accounts

Example validation error:

```
BeancountValidationError: Beancount file is not compatible with GnuCash import.

Found 2 implicit accounts (used but not opened):
  - Assets:Bank
  - Expenses:Food

GnuCash requires explicit account declarations with metadata.
Use 'export-beancount' to generate a GnuCash-compatible file.
```

## Full Conversion Chain Example

This demonstrates the complete round-trip conversion process:

### Step 1: Start with GnuCash Plaintext

```plaintext
2024-01-01 commodity CNY
    mnemonic: "CNY"
    fullname: "Yuan Renminbi"
    namespace: "CURRENCY"
    fraction: 100

2024-01-01 open Assets:Bank:Checking
    type: "BANK"
    placeholder: #False
    commodity.namespace: "CURRENCY"
    commodity.mnemonic: "CNY"

2024-01-01 open Expenses:Groceries
    type: "EXPENSE"
    placeholder: #False
    commodity.namespace: "CURRENCY"
    commodity.mnemonic: "CNY"

2024-01-15 * "Grocery Store" "Weekly shopping"
    currency.mnemonic: "CNY"
    Assets:Bank:Checking -100.00 CNY
    Expenses:Groceries 100.00 CNY
```

### Step 2: Import to GnuCash

```bash
gnucash-plaintext import mybook.gnucash transactions.txt
```

### Step 3: Export to GnuCash-Beancount

```bash
gnucash-plaintext export-beancount mybook.gnucash output.beancount
```

Result:

```beancount
2024-01-01 commodity CNY
    gnucash-mnemonic: "CNY"
    gnucash-namespace: "CURRENCY"
    gnucash-fullname: "Yuan Renminbi"
    gnucash-fraction: "100"

2024-01-01 open Assets:Bank:Checking CNY
    gnucash-name: "Assets:Bank:Checking"
    gnucash-guid: "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
    gnucash-type: "BANK"
    gnucash-placeholder: "0"
    gnucash-code: ""
    gnucash-description: ""
    gnucash-tax-related: "0"

2024-01-01 open Expenses:Groceries CNY
    gnucash-name: "Expenses:Groceries"
    gnucash-guid: "b2c3d4e5-f6a7-8901-bcde-f12345678901"
    gnucash-type: "EXPENSE"
    gnucash-placeholder: "0"
    gnucash-code: ""
    gnucash-description: ""
    gnucash-tax-related: "0"

2024-01-15 * "Grocery Store" "Weekly shopping"
    gnucash-guid: "c3d4e5f6-a7b8-9012-cdef-123456789012"
  Assets:Bank:Checking -100.00 CNY
  Expenses:Groceries 100.00 CNY
```

### Step 4: Import to New GnuCash File

```bash
gnucash-plaintext import-beancount mybook2.gnucash output.beancount
```

### Step 5: Export to Plaintext (Verify Round-trip)

```bash
gnucash-plaintext export mybook2.gnucash transactions2.txt
```

Result: `transactions2.txt` is semantically equivalent to `transactions.txt` (with possible format improvements like explicit metadata).

## Account Name Aliasing

GnuCash allows flexible account names with spaces and special characters, while beancount requires strict naming:

### How it Works

**GnuCash account:**
```
Assets:Cash in Wallet
Assets:Membership Rewards:イオン会員
Expenses:Groceries & Household
```

**GnuCash-Beancount representation:**
```beancount
open Assets:Cash-in-Wallet CNY
    gnucash-name: "Assets:Cash in Wallet"
    ...

open Assets:Membership-Rewards:イオン会員 MEMBERSHIP_REWARDS.イオン
    gnucash-name: "Assets:Membership Rewards:イオン会員"
    ...

open Expenses:Groceries-And-Household CNY
    gnucash-name: "Expenses:Groceries & Household"
    ...
```

**Character conversion:**
- Spaces → dashes (` ` → `-`)
- Ampersands → "And" (`&` → `-And-`)
- Slashes → dashes (`/` → `-`)
- Other punctuation → dashes

**Preservation:**
- Original name stored in `gnucash-name` metadata
- When importing back to GnuCash, original name is restored
- Beancount-safe name used only for beancount syntax compliance

## Implementation Details

### Parser Strictness

The GnuCash-Beancount parser enforces strict validation:

1. **All accounts must be opened** - No implicit accounts allowed
2. **All metadata must be present** - Missing required fields cause errors
3. **Commodities must match** - Account commodities must be declared
4. **Account hierarchy must be complete** - Parent accounts must exist

### Metadata Preservation

All GnuCash attributes are preserved through metadata:

| GnuCash Attribute | GnuCash-Beancount Metadata |
|-------------------|---------------------------|
| Account GUID | `gnucash-guid` |
| Account Type | `gnucash-type` |
| Account Name | `gnucash-name` |
| Placeholder | `gnucash-placeholder` |
| Code | `gnucash-code` |
| Description | `gnucash-description` |
| Tax Related | `gnucash-tax-related` |
| Commodity Mnemonic | `gnucash-mnemonic` |
| Commodity Namespace | `gnucash-namespace` |
| Commodity Fullname | `gnucash-fullname` |
| Commodity Fraction | `gnucash-fraction` |
| Transaction GUID | `gnucash-guid` |
| Transaction Notes | `gnucash-notes` |
| Transaction Doclink | `gnucash-doclink` |
| Split Memo | `gnucash-memo` |
| Split Action | `gnucash-action` |

## Use Cases

### 1. Beancount Tool Integration

Export to GnuCash-Beancount and use beancount tools:

```bash
# Export to GnuCash-Beancount
gnucash-plaintext export-beancount mybook.gnucash output.beancount

# Use beancount tools
bean-check output.beancount
bean-query output.beancount "SELECT * FROM transactions WHERE year = 2024"

# View in Fava
fava output.beancount
```

**Note:** While the file is valid beancount syntax, some beancount tools may ignore or not understand the GnuCash-specific metadata. The data is preserved but may not be visible in all beancount tools.

### 2. Text-Based Editing

Edit transactions in a text editor, then import back:

```bash
# Export to GnuCash-Beancount
gnucash-plaintext export-beancount mybook.gnucash output.beancount

# Edit output.beancount in your favorite editor
vim output.beancount

# Import back to GnuCash
gnucash-plaintext import-beancount mybook.gnucash output.beancount
```

### 3. Version Control

Track your financial data in git with human-readable format:

```bash
# Export to GnuCash-Beancount
gnucash-plaintext export-beancount mybook.gnucash ledger.beancount

# Add to version control
git add ledger.beancount
git commit -m "Update ledger for January 2024"

# Later: reconstruct GnuCash file
gnucash-plaintext import-beancount mybook.gnucash ledger.beancount
```

### 4. Migration and Backup

Keep your data in a portable format:

```bash
# Regular backups
gnucash-plaintext export-beancount mybook.gnucash backup-$(date +%Y%m%d).beancount

# Restore from backup
gnucash-plaintext import-beancount mybook-restored.gnucash backup-20240115.beancount
```

## See Also

- [GnuCash Plaintext Format](../README.md#gnucash-plaintext) - The native plaintext format
- [Beancount Documentation](https://beancount.github.io/docs/) - Official beancount docs
- [GnuCash Documentation](https://www.gnucash.org/docs.phtml) - Official GnuCash docs
