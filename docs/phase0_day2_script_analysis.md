# Phase 0 Day 2: Existing Scripts Analysis

**Created**: 2026-02-15
**Purpose**: Comprehensive analysis of existing functionality to guide new architecture
**Status**: Complete ✅

---

## Table of Contents

1. [Module Overview](#module-overview)
2. [Dependency Graph](#dependency-graph)
3. [Core Functionality Analysis](#core-functionality-analysis)
4. [Duplicate Detection Mechanism](#duplicate-detection-mechanism)
5. [Feature Summary](#feature-summary)
6. [Edge Cases & Limitations](#edge-cases--limitations)
7. [Architecture Insights](#architecture-insights)

---

## Module Overview

### External Reference Scripts (Not in git)
- `ledger.py` - Orchestration script for three main workflows
- `convert_qfx.py` - QFX → plaintext converter with category mapping

### Existing Codebase (In git)

| Module | Purpose | Lines | Key Classes/Functions |
|--------|---------|-------|----------------------|
| `utils.py` | Shared utilities | 336 | `get_transaction_sig`, `find_account`, numeric conversions |
| `editor/gnucash_editor.py` | CRUD operations | 195 | `GnuCashEditor`, duplicate detection |
| `editor/gnucash_to_plaintext.py` | Export to plaintext | 197 | `GnuCashToPlainText` |
| `editor/plaintext_to_gnucash.py` | Import from plaintext | 54 | `PlaintextToGnuCash` |
| `editor/utils.py` | Create helpers | 177 | `create_account`, `create_commodity`, `create_transaction` |
| `parser/plaintext_parser.py` | Parse plaintext | 390 | `PlaintextLedgerParser`, regex patterns |
| `parser/gnucash_parser.py` | Parse GnuCash | 18 | Stub/incomplete |

**Total**: ~1,367 lines of functional code

---

## Dependency Graph

```
ledger.py
├── editor/gnucash_to_plaintext.py
│   └── utils.py (get_account_full_name, to_string_with_decimal_point_placed, etc.)
├── editor/plaintext_to_gnucash.py
│   ├── editor/utils.py (create_account, create_commodity, create_transaction)
│   ├── parser/plaintext_parser.py
│   └── utils.py
├── editor/gnucash_editor.py
│   ├── editor/utils.py
│   ├── parser/plaintext_parser.py
│   └── utils.py (find_account, get_transaction_sig)
└── parser/plaintext_parser.py
    └── utils.py (beancount_compatible_*, decode_value_from_string)

convert_qfx.py
└── ofxparse (external library)
```

---

## Core Functionality Analysis

### 1. Export: GnuCash → Plaintext

**Entry Point**: `ledger.py::convert_gnucash_to_plaintext()`

**Implementation**: `editor/gnucash_to_plaintext.py::GnuCashToPlainText`

**Process**:
```python
1. Open GnuCash file in READ_ONLY mode
2. Get book and create query for all transactions
3. For each transaction:
   a. For each split:
      - Encounter commodity → print commodity directive (once per commodity)
      - Encounter account → print account directive (once per account, including parents)
   b. Print transaction with all metadata
4. Return complete plaintext as string
```

**Output Order**:
- Commodities (as encountered in transactions)
- Accounts (as encountered, with full hierarchy)
- Transactions (in query order)

**Key Features**:
- ✅ Preserves ALL GnuCash metadata (guid, type, placeholder, color, notes, tax_related, etc.)
- ✅ Handles multi-currency transactions
- ✅ Includes share_price and value for stock transactions
- ✅ Escapes special characters in strings
- ✅ Python 3.7 compatibility (GetAssociation vs GetDocLink)

**Format Example**:
```
2024-01-15 commodity NASDAQ.SYMC
    mnemonic: "SYMC"
    fullname: "Symantec Corporation"
    namespace: "NASDAQ"
    fraction: 10000

2024-01-15 open Assets:Investment:US Stock:SYMC
    guid: "abc123..."
    type: "Stock"
    placeholder: #False
    commodity.namespace: "NASDAQ"
    commodity.mnemonic: "SYMC"

2024-01-15 * "Buy SYMC"
    guid: "def456..."
    Assets:Investment:US Stock:SYMC 100 NASDAQ.SYMC
        share_price: "25.50"
        value: "2550.00"
    Assets:Current Assets:Checking -2550.00 CAD
```

### 2. Import: Plaintext → New GnuCash

**Entry Point**: `ledger.py::create_new_gnucash_from_plaintext()`

**Implementation**: `editor/plaintext_to_gnucash.py::PlaintextToGnuCash`

**Process**:
```python
1. Parse plaintext file using PlaintextLedgerParser
2. Create NEW GnuCash session (SESSION_NEW_STORE mode)
3. Get book and root account
4. For each directive in parsed AST:
   - CREATE_COMMODITY → create_commodity(ledger, book)
   - OPEN_ACCOUNT → create_account(ledger, book)
   - TRANSACTION → create_transaction(ledger, book)
5. Save and close session
```

**Directive Processing** (`editor/utils.py`):

**`create_commodity()`**:
- Looks up commodity in table
- If not exists: creates GncCommodity with fullname, namespace, mnemonic, fraction
- If exists: does nothing (idempotent)

**`create_account()`**:
- Parses account hierarchy (e.g., "Assets:Bank:Checking")
- Finds parent accounts (must already exist)
- Creates Account object
- Sets: name, type, commodity, placeholder, code, description, tax_related, commodity_scu
- Appends to parent

**`create_transaction()`**:
- Creates Transaction and begins edit
- Sets: currency, date, num, description, doc_link, notes
- For each split:
  - Finds account (must exist)
  - Creates Split with amount, value, share_price, action, memo
  - Adds to transaction
- Commits transaction

**Error Handling**:
- ✅ Raises exception if parent account not found
- ✅ Raises exception if commodity not found
- ⚠️ No validation before creating (assumes well-formed input)

### 3. Update: Plaintext → Existing GnuCash (Incremental)

**Entry Point**: `ledger.py::import_transactions_to_existing_gnucash()`

**Implementation**: `editor/gnucash_editor.py::GnuCashEditor`

**Process**:
```python
1. Create GnuCashEditor instance
2. Parse plaintext file using PlaintextLedgerParser
3. Start GnuCash session (readonly=False, create_new=False)
4. For each directive:
   - Filter: only TRANSACTION directives (skip commodities, accounts)
   - Call: editor.create_new_transaction(ledger, dryrun=dryrun)
5. End session (saves if not dryrun)
```

**Critical Feature: Two-Level Duplicate Detection**

See [Duplicate Detection Mechanism](#duplicate-detection-mechanism) section below.

**Dryrun Mode**:
- ✅ `dryrun=True`: Logs what would be created, doesn't modify file
- ✅ `dryrun=False`: Actually creates transactions and saves file

**Logging**:
```python
logging.info('create_new_transaction: transaction {guid} already exists, will not create duplicate')
logging.info('create_new_transaction: find matching transactions on {date} with splits {accounts}')
logging.info('create_new_transaction: will create a new transaction on {date} with splits {accounts}')
logging.info('create_new_transaction: created a new transaction on {date} with splits {accounts}')
```

### 4. QFX → Plaintext Conversion

**Entry Point**: `convert_qfx.py` (standalone script)

**Implementation**: Uses `ofxparse` library

**Process**:
```python
1. Open QFX file with codecs.open()
2. Parse with OfxParser.parse()
3. Extract account info (account_id, number, type)
4. Get statement with transactions
5. For each transaction:
   a. Format date, payee, memo, id
   b. Generate receipt link (sanitized merchant name)
   c. Match against category_mapping dictionary
   d. Output plaintext transaction to stdout
```

**Category Mapping** (⭐ Critical Feature):

**Data Structure**:
```python
category_mapping = {
    "Groceries": ["MYBASKET", "LIFE ", "SUPERMARKET", ...],
    "Public Transportation": ["COMPASS ", "UBERTRIP", ...],
    "Supplies": [...],
    "Travel:Flight": [...],  # Hierarchical category
    ...  # 11 categories, 50+ patterns
}
```

**Matching Logic**:
```python
matched = False
for category, patterns in category_mapping.items():
    if any(pattern in transaction.payee for pattern in patterns):
        print(f'\tExpenses-CAN:{category} {-transaction.amount} CAD')
        matched = True
        break  # First match wins

if not matched:
    if transaction.amount > 0:  # Credit/refund
        print(f'\tAssets:Current Assets:HSBC CA:HSBC CAD Checking {-transaction.amount} CAD')
    else:  # Expense, unknown category
        print(f'\tExpenses-CAN:Dining {-transaction.amount} CAD')  # Default fallback
```

**Features**:
- ✅ Case-sensitive substring matching
- ✅ First match wins (order matters)
- ✅ Hierarchical categories (using `:` separator)
- ✅ Special handling for credits (positive amounts)
- ⚠️ Default unknown expenses to "Dining" (no TODO marker)

**Receipt Link Generation**:
```python
payee = re.sub(r'[^a-zA-Z0-9]', '_', transaction.payee)
receipt_name = f"{transaction.date.strftime('%Y-%m-%d_%H-%M-%S')}_{payee}"
print(f'\tdoc_link: "shopping_receipts/{receipt_name}.txt"')
```

---

## Duplicate Detection Mechanism

### Transaction Signature

**Definition** (`utils.py::get_transaction_sig()`):
```python
def get_transaction_sig(transaction: Transaction) -> (str, [str]):
    tx_date_str = transaction.GetDate().strftime("%Y-%m-%d")
    tx_splits = transaction.GetSplitList()
    split_sigs = []
    for s in tx_splits:
        split_account = s.GetAccount()
        split_sigs.append(get_account_full_name(split_account))
    tx_sig = (tx_date_str, split_sigs)
    return tx_sig
```

**Signature Components**:
- Date (YYYY-MM-DD format)
- List of account full names (e.g., ["Assets:Bank:Checking", "Expenses:Groceries"])

**Example**:
```python
# Transaction:
# 2024-01-15 * "Grocery Store"
#     Expenses:Groceries 50.00 CAD
#     Assets:Bank:Checking -50.00 CAD

signature = ("2024-01-15", ["Expenses:Groceries", "Assets:Bank:Checking"])
```

### Duplicate Detection Levels

**Level 1: GUID-Based Detection** (`gnucash_editor.py` lines 130-136):

```python
if 'guid' in transaction_ledger.metadata:
    guid = transaction_ledger.metadata['guid']
    existing_tx = self.get_transaction_by_guid(guid)
    if existing_tx is not None:
        logging.info(f'transaction {guid} already exists, will not create duplicate')
        return  # Skip creation
```

- Checks if plaintext has `guid` metadata
- If guid exists in GnuCash: skip (already imported)
- **Use case**: Re-importing exported plaintext (preserves GUIDs)

**Level 2: Signature-Based Detection** (`gnucash_editor.py` lines 140-150):

```python
date_str = transaction_ledger.props['date']
split_accounts = [child.props['account'] for child in transaction_ledger.children]

existing_txs = self.find_transactions_by_sig(date_str, split_accounts)

if len(existing_txs) > 0:
    logging.info(f'find matching transactions on {date_str} with splits {split_accounts}')
    for tx in existing_txs:
        pass  # Could inspect further if needed
    return  # Skip creation
```

- Extracts date and account names from plaintext
- Queries GnuCash for matching transactions
- If match found: skip (duplicate detected)
- **Use case**: QFX imports without GUIDs

### find_transactions_by_sig() Details

**Query Strategy** (`gnucash_editor.py` lines 76-112):

```python
def find_transactions_by_sig(self, date_str: str, splits_sig: [str]) -> [Transaction]:
    # Parse date
    date = datetime.strptime(date_str, "%Y-%m-%d")
    yesterday = date - timedelta(days=1)
    tomorrow = date + one_day

    # Query transactions within ±1 day window
    query = Query()
    query.search_for('Trans')
    query.add_term(['date-posted'], QueryDatePredicate(QOF_COMPARE_GTE, QOF_DATE_MATCH_DAY, yesterday), QOF_QUERY_AND)
    query.add_term(['date-posted'], QueryDatePredicate(QOF_COMPARE_LTE, QOF_DATE_MATCH_DAY, tomorrow), QOF_QUERY_AND)
    query.set_book(book)

    # Filter results by exact signature match
    transactions = []
    sig_to_find = (date_str, splits_sig)
    for _transaction in query.run():
        transaction = Transaction(instance=_transaction)
        tx_sig = get_transaction_sig(transaction)
        tx_date = transaction.GetDate().strftime("%Y-%m-%d")
        if tx_sig == sig_to_find and date_str == tx_date:
            transactions.append(transaction)

    return transactions
```

**Query Optimization**:
- Uses GnuCash Query API to filter by date range (±1 day)
- Reduces search space before exact matching
- Then filters in Python for exact signature match

**Edge Case Handling**:
- Date query uses ±1 day window (GnuCash timezone quirks)
- Exact date comparison ensures correct date match
- Signature includes ALL split accounts (order doesn't matter, compared as tuple)

### Duplicate Detection Summary

| Scenario | Detection Method | Result |
|----------|------------------|--------|
| Re-import exported file | GUID-based | ✅ Skipped |
| Import QFX (no GUID) | Signature-based | ✅ Skipped if exists |
| Same date + accounts | Signature-based | ✅ Skipped |
| Same date, different accounts | Signature-based | ✅ Imported (not duplicate) |
| Different date, same accounts | Signature-based | ✅ Imported (not duplicate) |

**No conflict resolution**: If duplicate found, always skip (keep existing).

---

## Feature Summary

### Implemented Features

| Feature | Location | Priority | Notes |
|---------|----------|----------|-------|
| **Export GnuCash → plaintext** | `GnuCashToPlainText` | ⭐⭐⭐ Must-have | Complete with all metadata |
| **Create new GnuCash from plaintext** | `PlaintextToGnuCash` | ⭐⭐⭐ Must-have | Fully functional |
| **Update existing GnuCash** | `GnuCashEditor` | ⭐⭐⭐ Must-have | With duplicate detection |
| **Duplicate detection (GUID)** | `create_new_transaction` | ⭐⭐⭐ Must-have | Working ✅ |
| **Duplicate detection (signature)** | `find_transactions_by_sig` | ⭐⭐⭐ Must-have | Working ✅ |
| **Dryrun mode** | `create_new_transaction` | ⭐⭐⭐ Must-have | Working ✅ |
| **Parse QFX files** | `convert_qfx.py` | ⭐⭐⭐ Must-have | Uses ofxparse |
| **Category mapping** | `convert_qfx.py` | ⭐⭐⭐ Must-have | Hardcoded dict |
| **Pattern-based matching** | `convert_qfx.py` | ⭐⭐⭐ Must-have | Case-sensitive substring |
| **Receipt link generation** | `convert_qfx.py` | ⭐⭐ Important | Sanitizes merchant name |
| **Hierarchical categories** | `convert_qfx.py` | ⭐⭐ Important | Uses `:` separator |
| **Multi-currency support** | `create_transaction` | ⭐⭐⭐ Must-have | share_price, value fields |
| **Session management** | `GnuCashEditor` | ⭐⭐⭐ Must-have | Proper open/save/close |
| **Python 3.7 compatibility** | Various | ⭐⭐ Important | SessionOpenMode checks |
| **Plaintext parser** | `PlaintextLedgerParser` | ⭐⭐⭐ Must-have | Regex-based, robust |
| **Beancount export** | `utils.py` | ⭐ Nice-to-have | Helper functions exist |

### Missing Features

| Feature | Priority | Impact | Implementation |
|---------|----------|--------|----------------|
| **CLI interface** | ⭐⭐⭐ Must-have | High | Phase 4 - click framework |
| **Configurable category mappings** | ⭐⭐⭐ Must-have | High | YAML config file |
| **TODO markers for uncertain categories** | ⭐⭐⭐ Must-have | Medium | Update categorizer logic |
| **Case-insensitive pattern matching** | ⭐⭐ Important | Medium | Add option flag |
| **Regex pattern support** | ⭐⭐ Important | Medium | Extend pattern matching |
| **Conflict resolution strategies** | ⭐⭐ Important | Medium | Skip/overwrite/error options |
| **Error handling & reporting** | ⭐⭐ Important | Medium | Use case result types |
| **Validation before import** | ⭐⭐ Important | Medium | LedgerValidator service |
| **Progress reporting** | ⭐ Nice-to-have | Low | CLI progress bars |

---

## Edge Cases & Limitations

### 1. ledger.py Issues

**Hardcoded Paths**:
```python
# Lines 48-52 in ledger.py
input_file = '/Users/jimmy/Library/CloudStorage/OneDrive-Personal/Documents/gnucash/...'
output_file = '/Users/jimmy/Library/CloudStorage/OneDrive-Personal/Documents/gnucash/...'
file_to_import = f'{import_path}/imports/2026-02-03.txt'
```
- ⚠️ User-specific paths
- ⚠️ No CLI args despite argparse import
- ⚠️ Main() always runs import + export (no selective execution)

**Error Handling**:
```python
# Line 19-21 in ledger.py
except gnucash.GnuCashBackendException as backend_exception:
    print(backend_exception)
    return ""  # Silent failure
```
- ⚠️ Returns empty string on error
- ⚠️ No error details propagated
- ⚠️ Caller can't distinguish error from empty file

### 2. convert_qfx.py Issues

**Hardcoded Configuration**:
- ⚠️ File path: `/Users/jimmy/Downloads/ofx40004.qfx`
- ⚠️ Account: `Liabilities:Credit Card:HSBC-Premier-8860`
- ⚠️ Currency: `CAD`
- ⚠️ Category mappings in code

**Fallback Logic**:
```python
# Lines 49-53 in convert_qfx.py
if not matched:
    if transaction.amount > 0:
        print(f'\tAssets:Current Assets:HSBC CA:HSBC CAD Checking {-transaction.amount} CAD')
    else:
        print(f'\tExpenses-CAN:Dining {-transaction.amount} CAD')  # Arbitrary choice!
```
- ⚠️ Unknown expenses → "Dining" (why not TODO marker?)
- ⚠️ Positive amounts assume checking account (might be wrong)
- ⚠️ No user review flag

**Pattern Matching Limitations**:
- ⚠️ **Case-sensitive**: "MYBASKET" matches, "mybasket" doesn't
- ⚠️ No regex support (only substring matching)
- ⚠️ First match wins (can't express priority)

**Receipt Filename Collisions**:
```python
# Line 36 in convert_qfx.py
receipt_name = f"{transaction.date.strftime('%Y-%m-%d_%H-%M-%S')}_{payee}"
```
- ⚠️ Multiple transactions in same second → collision
- ⚠️ Only 1-second resolution

### 3. Duplicate Detection Edge Cases

**Signature Ambiguity**:
- ✅ Same date + same accounts = duplicate (correct)
- ⚠️ What about same date + accounts but different amounts?
  - Currently treated as duplicate (skipped)
  - Could be legitimate (e.g., two grocery purchases same day, same store)

**GUID Preservation**:
- ✅ Works for re-importing exported plaintext
- ⚠️ QFX imports never have GUIDs (always uses signature)
- ⚠️ If signature changes slightly (account renamed), re-imports as new

**Date Range Query**:
```python
# Lines 91-101 in gnucash_editor.py
yesterday = date - timedelta(days=1)
tomorrow = date + timedelta(days=1)
query.add_term(['date-posted'], QueryDatePredicate(QOF_COMPARE_GTE, ..., yesterday), ...)
query.add_term(['date-posted'], QueryDatePredicate(QOF_COMPARE_LTE, ..., tomorrow), ...)
```
- Uses ±1 day window (GnuCash timezone handling)
- Then filters for exact date in Python
- Could miss matches if GnuCash internal date differs

### 4. Parser Limitations

**Indentation**:
```python
# Lines 169-170 in plaintext_parser.py
if tabs_count > 0 and spaces_count > 0:
    return False, -1, ''  # Error: mixed tabs and spaces
```
- ✅ Detects mixed tabs/spaces
- ✅ Auto-detects indentation from first indented line
- ⚠️ No handling for inconsistent indentation levels

**Error Recovery**:
```python
# Lines 206-209 in plaintext_parser.py
if not is_ident_valid:
    self.errors.append(f'invalid indentation in line {line_number}...')
    print(f'invalid indentation in line {line_number}...')
    break  # Stops parsing
```
- ⚠️ First error stops entire parse
- ⚠️ No error recovery or partial parsing
- ⚠️ Could collect all errors instead

### 5. Multi-Currency Quirks

**Transaction Currency vs Split Currency**:
```python
# Lines 145-149 in gnucash_to_plaintext.py
split_currencies = [(c.get_namespace(), c.get_mnemonic()) for c in
                    [tx.GetAccount().GetCommodity() for tx in tx_splits]]
split_currencies = list(set(split_currencies))
if len(split_currencies) > 1:
    print(f'\tcurrency.mnemonic: {encode_value_as_string(tx_currency_symbol)}', ...)
```
- Only prints transaction currency if splits use different currencies
- Optimization: reduces redundancy in single-currency transactions
- Could be confusing: sometimes explicit, sometimes implicit

**Share Price and Value**:
```python
# Lines 182-186 in gnucash_to_plaintext.py
if not number_in_string_format_is_1(share_price) or split_currency_not_match_tx:
    print(f'\t\tshare_price: {encode_value_as_string(share_price)}', ...)

if split_value != formatted_amount:
    print(f'\t\tvalue: {encode_value_as_string(split_value)}', ...)
```
- Only prints if share_price != 1 or value != amount
- Reduces verbosity for simple transactions
- Must reconstruct defaults when parsing

### 6. Session Management

**Python Version Compatibility**:
```python
# Lines 29-41 in gnucash_editor.py
if sys.version_info >= (3, 8):
    from gnucash import SessionOpenMode
    mode = SessionOpenMode.SESSION_NORMAL_OPEN
    session = Session(f'xml://{self.gnucash_xml_file}', mode)
else:
    ignore_lock = readonly
    is_new = not readonly and create_new
    session = Session(f'xml://{self.gnucash_xml_file}', is_new=is_new, ignore_lock=ignore_lock)
```
- Different APIs for Python 3.7 vs 3.8+
- GnuCash 3.4 (Python 3.7) uses is_new, ignore_lock
- GnuCash 4.4+ (Python 3.8+) uses SessionOpenMode

**Lock Handling**:
- Python 3.8+: SessionOpenMode.SESSION_READ_ONLY (respects locks)
- Python 3.7: ignore_lock=True (bypasses locks - dangerous!)

---

## Architecture Insights

### What Works Well

**1. Layered Structure (Implicit)**:
```
ledger.py (orchestration)
├── editor/ (business logic + I/O)
└── parser/ (parsing)
```
- Clear separation exists
- Could be made more explicit

**2. GnuCash Type Usage**:
- Uses GnuCash's Account, Transaction, Split, Commodity directly
- No unnecessary duplication
- Validates our architectural decision

**3. Signature-Based Matching**:
- Simple yet effective: (date, [accounts])
- Covers 95% of real-world duplicates
- Fast with date range query optimization

**4. Plaintext Format**:
- Beancount-inspired but GnuCash-specific
- Human-readable and editable
- Preserves ALL metadata (nothing lost in round-trip)

**5. Parser Design**:
- Regex-based parsing (fast, robust)
- AST structure (PlaintextLedger tree)
- DirectiveType enum (clear types)
- Indentation-aware (tabs or spaces)

### What Needs Improvement

**1. No Conflict Resolution**:
- Current: duplicate found → always skip
- Needed: user choice (skip/overwrite/error/ask)
- Use case: fixing mistakes in imported data

**2. Hardcoded Configuration**:
- Paths, accounts, currencies hardcoded
- Category mappings in code
- Need: CLI args + config file

**3. Limited Error Context**:
```python
# Current:
return ""  # Silent failure

# Needed:
return Result(success=False, error="Could not open file: ...")
```

**4. No Validation**:
- No pre-import validation
- Could catch errors before modifying GnuCash file
- Needed: LedgerValidator service

**5. Output to stdout**:
```python
# convert_qfx.py
print(f'{date_str} * "{payee}"')  # Goes to stdout
```
- No file output option
- No structured result
- Hard to use programmatically

**6. No Progress Reporting**:
- Long operations (1000+ transactions) are silent
- No feedback during processing
- User doesn't know if it's working or hung

### Mapping to New Architecture

**Services Layer** (Business Logic):
```python
# Extract from existing code:
TransactionMatcher:
  - find_transactions_by_sig() (from GnuCashEditor)
  - get_transaction_sig() (from utils.py)

AccountCategorizer:
  - category_mapping logic (from convert_qfx.py)
  - pattern matching (new: add regex, case-insensitive)

LedgerValidator:
  - New: validate plaintext before import
  - Check accounts exist, balances are correct, etc.
```

**Infrastructure Layer** (I/O):
```python
GnuCash Repository:
  - Session management (from GnuCashEditor)
  - Query operations (from GnuCashEditor)
  - CRUD operations (from editor/utils.py)

Plaintext Parser/Writer:
  - PlaintextLedgerParser (existing, refactor)
  - GnuCashToPlainText (existing, refactor)

QFX Parser:
  - ofxparse wrapper (from convert_qfx.py)
  - QFX models (new)
```

**Use Cases Layer** (Orchestration):
```python
ExportToPlaintextUseCase:
  - Convert ledger.py::convert_gnucash_to_plaintext()

CreateFromPlaintextUseCase:
  - Convert ledger.py::create_new_gnucash_from_plaintext()

UpdateFromPlaintextUseCase:
  - Convert ledger.py::import_transactions_to_existing_gnucash()
  - Add conflict resolution options

QFXToPlaintextUseCase:
  - Convert convert_qfx.py script
  - Add config file support
```

**CLI Layer**:
```bash
# New commands to create:
gnucash-plaintext export -i file.gnucash -o file.txt
gnucash-plaintext import -i file.txt -o file.gnucash
gnucash-plaintext update -i new.txt -g existing.gnucash --dryrun
gnucash-plaintext qfx-to-plaintext -i statement.qfx -a "Liabilities:CC" -o review.txt
gnucash-plaintext validate -i file.txt
```

---

## Next Steps (Phase 0 Day 3)

Based on this analysis, Day 3 tasks:

1. ✅ **Create directory structure**:
   ```
   cli/commands/
   services/
   infrastructure/{gnucash,plaintext,qfx}/
   use_cases/
   tests/{unit,integration,e2e}/
   config/  # For default category mappings
   ```

2. ✅ **Create pyproject.toml**:
   ```toml
   dependencies = [
       "click>=8.0",
       "ofxparse>=0.21",  # QFX parsing
       "pyyaml>=6.0",     # Config files
   ]
   ```

3. ✅ **Create CLI skeleton**:
   - Wrap existing code temporarily
   - Add proper argument parsing
   - Remove hardcoded paths

4. ✅ **Create default config**:
   - Extract category_mapping to `config/categories.yaml`
   - Document config format

5. ✅ **Verify in Docker**:
   ```bash
   ./scripts/build.sh
   ./scripts/shell.sh
   ./scripts/run.sh gnucash-plaintext --help
   ```

---

**Status**: Phase 0 Day 2 Complete ✅
**Next**: Phase 0 Day 3 - Project Structure & CLI Skeleton
**Est. Time**: 3-4 hours
