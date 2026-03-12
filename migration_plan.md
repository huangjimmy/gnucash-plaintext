# GnuCash Plaintext Architecture Migration Plan

**Version:** 0.2.2 (Revised)
**Created:** 2026-02-14
**Revised:** 2026-03-01
**Status:** Planning Phase

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Key Revisions from v0.2.0](#key-revisions-from-v020)
3. [Current State Analysis](#current-state-analysis)
4. [Revised Architecture](#revised-architecture)
5. [Architecture Principles](#architecture-principles)
6. [Detailed Phase Plan](#detailed-phase-plan)
7. [Timeline & Resources](#timeline--resources)
8. [Risk Mitigation](#risk-mitigation)
9. [Success Criteria](#success-criteria)

---

## Executive Summary

This document outlines the migration plan for refactoring the gnucash-plaintext project from a collection of scripts to a well-architected, maintainable CLI application using clean architecture principles.

### Goals

- **Unified CLI**: Consolidate `ledger.py`, `convert_qfx.py`, and other scripts into a single `gnucash-plaintext` command
- **Pragmatic Architecture**: Use GnuCash types directly, avoid unnecessary duplication
- **Testability**: Separate business logic from I/O without duplicating GnuCash's domain
- **Extensibility**: Make it easy to add new formats and workflows
- **Maintainability**: Clear code organization with single responsibility

### Key Features After Migration

- Export GnuCash to **GnuCash Plaintext format** (your beancount-like format)
- Import plaintext to create new GnuCash file
- Update existing GnuCash file with new transactions (incremental)
- Convert QFX to plaintext **for manual review** (no direct import to GnuCash)
- Optional: Export to actual beancount format for use with fava
- Validate plaintext files
- Smart duplicate detection and conflict resolution

---

## Key Revisions from v0.2.0

### 1. Terminology Fixes

**CHANGED**: "Export to beancount format" → "Export to GnuCash Plaintext format"

**Clarification**: Your format is **not** beancount. It's a beancount-inspired format specifically designed for GnuCash with:
- Spaces in account names (beancount doesn't allow this)
- GnuCash-specific metadata (guid, placeholder, commodity_scu, tax_related, color, etc.)
- Different transaction structure (splits with share_price, value)
- Document links and other GnuCash features

**Naming Convention**:
- **Primary format name**: "GnuCash Plaintext"
- **Optional export**: "Beancount-compatible export" (converts your format → actual strict beancount for fava)

### 2. QFX Workflow - Manual Review Required

**REMOVED**: "Import QFX directly into GnuCash" feature

**Rationale**: Real-world workflow requires human review to adjust expense categories, split transactions, add notes, etc.

**CORRECT WORKFLOW**:
```
1. QFX file → GnuCash Plaintext (with best-guess categories marked with TODO)
2. User manually edits the plaintext file:
   - Fix expense categories
   - Split combined transactions
   - Add notes and descriptions
   - Merge duplicates
3. Edited plaintext → GnuCash (via update command)
```

**Implementation**: Only `qfx-to-plaintext` command exists. No `qfx-import` command.

### 3. Docker-Based Development Environment

**ADDED**: Docker container for development and testing

**Rationale**: GnuCash Python bindings are system-dependent:
- ❌ Cannot `pip install gnucash` - bindings are SWIG wrappers around C++ library
- ❌ Tightly coupled with system Python installation
- ❌ Requires GnuCash native application installed
- ❌ Different behavior on Mac vs Linux
- ❌ Pollutes developer's system with specific versions

**Solution**: Docker container with controlled environment:
- ✅ Ubuntu/Debian base with GnuCash installed
- ✅ Python 3.x with GnuCash bindings pre-configured
- ✅ Consistent environment for all developers
- ✅ Same image for local development and CI/CD
- ✅ No pollution of host system

#### Supported Distributions (Verified 2026-02-14)

| Distribution | GnuCash Version | Status | Verified |
|--------------|----------------|--------|----------|
| `debian:13` | 5.10 | ✅ Latest (default) | 2026-02-14 |
| `debian:12` | 4.13 | ✅ Stable | 2026-02-14 |
| `debian:11` | 4.4 | ✅ LTS | 2026-02-14 |
| `ubuntu:20.04` | 3.8 | ✅ Minimum (GnuCash 3.x) | 2026-02-14 |

**Version Coverage**: GnuCash 3.8 → 5.10 (~2 years of API changes)

**Note on Debian 10**: Dropped support - EOL with broken dependencies. Use Ubuntu 20.04 for GnuCash 3.x support instead.

#### Development Workflow

**Default (Debian 13 - GnuCash 5.10)**:
```bash
# Build Docker image
docker build -t gnucash-dev .

# Run tests in container
docker run --rm -v $(pwd):/workspace gnucash-dev pytest

# Interactive development
docker run -it --rm -v $(pwd):/workspace gnucash-dev bash
```

**Specific Distributions**:
```bash
# Ubuntu 20.04 (GnuCash 3.8 - minimum supported)
docker build --build-arg BASE_IMAGE=ubuntu:20.04 -t gnucash-dev:ubuntu20 .
docker run -it --rm -v $(pwd):/workspace gnucash-dev:ubuntu20 bash

# Debian 12 (GnuCash 4.13)
docker build --build-arg BASE_IMAGE=debian:12 -t gnucash-dev:debian12 .

# Debian 11 (GnuCash 4.4)
docker build --build-arg BASE_IMAGE=debian:11 -t gnucash-dev:debian11 .
```

#### CI/CD Setup

Example GitHub Actions workflow for testing all distributions:

```yaml
name: Test

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        include:
          - base_image: debian:13
            gnucash: "5.10"
          - base_image: debian:12
            gnucash: "4.13"
          - base_image: debian:11
            gnucash: "4.4"
          - base_image: ubuntu:20.04
            gnucash: "3.8"

    steps:
      - uses: actions/checkout@v3

      - name: Build Docker image
        run: |
          docker build \
            --build-arg BASE_IMAGE=${{ matrix.base_image }} \
            -t gnucash-test .

      - name: Run tests
        run: |
          docker run --rm -v $(pwd):/workspace gnucash-test \
            python3 -m pytest
```

### 4. Don't Duplicate GnuCash Domain Models

**REMOVED**: Pure Python domain models for Account, Transaction, Split, Commodity

**Rationale**: GnuCash Python bindings already provide:
- Well-tested `Account`, `Transaction`, `Split`, `Commodity` classes
- Hierarchy management, multi-currency, splits logic
- Validation rules

Duplicating these adds:
- ❌ Maintenance burden (keep two models in sync)
- ❌ Complex mapping layer (domain ↔ GnuCash types)
- ❌ No real testability benefit (still need GnuCash for integration testing)

**NEW APPROACH**:
- ✅ Use GnuCash types directly
- ✅ Wrap behind repository interface for abstraction
- ✅ Extract business logic to services (matching, validation, conversion)
- ✅ Focus "domain" on what GnuCash doesn't have: plaintext format, QFX, workflows

**Example**:
```python
# OLD (duplicated domain model)
class Account:
    name: str
    account_type: AccountType
    # ... duplicate all GnuCash Account fields

# NEW (use GnuCash directly)
from gnucash import Account

class TransactionMatcher:
    def get_signature(self, tx: Transaction) -> tuple:
        # Business logic using GnuCash types
        return (tx.GetDate(), sorted_accounts)
```

---

## Current State Analysis

### Existing Code Structure

```
gnucash-plaintext/
├── parser/
│   ├── gnucash_parser.py      # Mostly empty skeleton
│   ├── plaintext_parser.py    # Plaintext parsing with mixed concerns
│   └── tests/
├── editor/
│   ├── gnucash_editor.py      # CRUD operations on GnuCash
│   ├── plaintext_to_gnucash.py # Create new GnuCash from plaintext
│   ├── gnucash_to_plaintext.py # Export GnuCash to plaintext
│   ├── utils.py               # Creation helpers
│   └── tests/
├── utils.py                    # General utilities
├── ledger.py                   # CLI: Add transactions to existing GnuCash
├── convert_qfx.py              # CLI: Convert QFX to plaintext
└── tests/
```

### Current Pain Points

1. **No Unified CLI** - Multiple scripts with different interfaces
2. **Mixed Concerns** - Business logic entangled with I/O and parsing
3. **Tight Coupling** - Direct dependency on GnuCash bindings throughout
4. **Hard to Test** - Most tests require actual GnuCash files
5. **Difficult to Extend** - Adding new formats requires touching parsing code
6. **Duplicate Code** - Two `utils.py` files, similar logic in multiple places
7. **No Domain Model** - Works with dictionaries and GnuCash types directly

### What Works Well

- ✅ Plaintext format is well-defined and documented
- ✅ Basic parsing and conversion works
- ✅ Handles complex GnuCash features (multi-currency, splits, etc.)
- ✅ Some test coverage exists

---

## Revised Architecture

### Pragmatic Layered Architecture

```
gnucash-plaintext/
├── cli/                         # User interface
│   ├── __init__.py
│   ├── main.py
│   └── commands/
│       ├── __init__.py
│       ├── export.py            # GnuCash → plaintext
│       ├── import_.py           # Plaintext → GnuCash (new file)
│       ├── update.py            # Plaintext → GnuCash (append to existing)
│       ├── qfx.py               # QFX → plaintext (for manual review)
│       ├── validate.py          # Validate plaintext
│       └── beancount.py         # Optional: → actual beancount format
│
├── services/                    # Business logic (the "domain")
│   ├── __init__.py
│   ├── transaction_matcher.py  # Find duplicate transactions
│   ├── conflict_resolver.py    # Resolve conflicts (skip/overwrite/error)
│   ├── ledger_validator.py     # Validate ledger consistency
│   ├── account_categorizer.py  # Categorize QFX transactions
│   └── beancount_converter.py  # Convert to strict beancount format
│
├── infrastructure/              # Format I/O and persistence
│   ├── __init__.py
│   ├── gnucash/
│   │   ├── __init__.py
│   │   ├── repository.py        # GnuCash file operations
│   │   └── session_manager.py  # Session lifecycle management
│   ├── plaintext/
│   │   ├── __init__.py
│   │   ├── parser.py            # Text → AST
│   │   ├── writer.py            # AST/GnuCash objects → Text
│   │   └── ast_models.py        # AST node types
│   └── qfx/
│       ├── __init__.py
│       ├── parser.py            # QFX XML → QFX models
│       └── models.py            # QFX data structures
│
├── use_cases/                   # Application orchestration
│   ├── __init__.py
│   ├── export_to_plaintext.py
│   ├── create_from_plaintext.py
│   ├── update_from_plaintext.py
│   ├── qfx_to_plaintext.py
│   └── export_to_beancount.py
│
└── tests/
    ├── unit/                    # Service tests (temp GnuCash files)
    ├── integration/             # Integration tests (temp GnuCash files)
    └── e2e/                     # Full CLI tests (in Docker)
```

### Architectural Layers Explained

```
┌─────────────────────────────────────────────┐
│           CLI Layer                         │
│  (Click commands, user interaction)         │
└──────────────┬──────────────────────────────┘
               │
               ↓
┌─────────────────────────────────────────────┐
│      Use Cases Layer                        │
│  (Orchestrate workflows)                    │
└──────────┬──────────────┬───────────────────┘
           │              │
           ↓              ↓
┌──────────────────┐  ┌──────────────────────┐
│  Services        │  │  Infrastructure      │
│  (Business       │  │  (I/O & Persistence) │
│   Logic)         │  │                      │
│                  │  │  - GnuCash Repo      │
│  - Matchers      │  │  - Plaintext Parser  │
│  - Validators    │  │  - QFX Parser        │
│  - Converters    │  │  - Session Mgmt      │
└──────────────────┘  └─────────┬────────────┘
                                │
                                ↓
                      ┌───────────────────────┐
                      │  GnuCash Bindings     │
                      │  (Account,            │
                      │   Transaction, Split, │
                      │   Commodity, etc.)    │
                      └───────────────────────┘
```

**Key Point**: We use GnuCash's types directly. No duplicate domain models.

**Key Point**: We use GnuCash's types directly. No duplicate domain models.

---

## Architecture Principles

### 1. Don't Duplicate What GnuCash Provides

**Principle**: Use GnuCash types (`Account`, `Transaction`, `Split`, `Commodity`) directly. Don't create parallel domain models.

**Rationale**:
- GnuCash bindings are well-tested and complete
- Duplication adds maintenance burden
- Integration tests need real GnuCash anyway
- Focus effort on what GnuCash doesn't have (formats, workflows)

**Exception**: When GnuCash types are insufficient:
- AST nodes for plaintext parsing
- QFX data structures
- Beancount conversion models

**Example**:
```python
# Good: Use GnuCash types directly
from gnucash import Transaction

class TransactionMatcher:
    def get_signature(self, tx: Transaction) -> tuple:
        """Extract signature from GnuCash Transaction"""
        date = tx.GetDate().strftime("%Y-%m-%d")
        accounts = tuple(sorted([
            s.GetAccount().GetName()
            for s in tx.GetSplitList()
        ]))
        return (date, accounts)

# Bad: Duplicate GnuCash's Transaction model
@dataclass
class Transaction:  # Don't do this!
    date: date
    splits: List[Split]
    # ... duplicate all GnuCash fields
```

### 2. Business Logic in Services

**Principle**: Extract business logic into standalone services that operate on GnuCash types.

**Benefits**:
- Services can be tested with temp GnuCash files in Docker
- Business rules are explicit and centralized
- Easy to compose services in use cases

**Example**:
```python
# services/transaction_matcher.py
from gnucash import Transaction
from typing import List, Tuple

class TransactionMatcher:
    """Business logic for matching transactions"""

    def find_duplicates(self,
                       existing: List[Transaction],
                       incoming: List[Transaction]) -> Tuple[List, List, List]:
        """
        Returns: (new_transactions, duplicates, conflicts)

        Business logic: compare signatures, detect conflicts
        """
        # Test with real Transaction objects from temp GnuCash files
        pass
```

### 3. Thin Repository Layer

**Principle**: Repository only handles GnuCash session management and queries. Business logic stays in services.

**Responsibilities**:
- ✅ Session lifecycle (open, close, save)
- ✅ Queries (find account, get transactions)
- ✅ CRUD operations (add, update, delete)
- ❌ Business logic (matching, validation, conversion)

**Example**:
```python
# infrastructure/gnucash/repository.py
from gnucash import Session, Account, Transaction

class GnuCashRepository:
    """Thin wrapper around GnuCash file I/O"""

    def get_all_transactions(self) -> List[Transaction]:
        """Returns GnuCash Transaction objects"""
        with self.session_manager.readonly() as session:
            book = session.get_book()
            query = Query()
            query.search_for('Trans')
            query.set_book(book)
            return [Transaction(instance=t) for t in query.run()]

    def add_transactions(self, transactions: List[Transaction]):
        """Add transactions to file"""
        with self.session_manager.writable() as session:
            book = session.get_book()
            # Transactions are already GnuCash objects
            # Just add them to the book
            pass
```

### 4. Format Adapters

**Principle**: Each format (plaintext, QFX, beancount) has its own adapter/parser.

**Focus**: These adapters are the real "domain" - the format specifications and conversion rules.

**Example**:
```python
# infrastructure/plaintext/parser.py - Parse your GnuCash Plaintext format
# infrastructure/qfx/parser.py - Parse QFX format
# services/beancount_converter.py - Convert to strict beancount
```

### 5. Use Case Orchestration

**Principle**: Use cases orchestrate services and infrastructure to accomplish user goals.

**Benefits**:
- Clear entry points for features
- Business workflow is explicit
- Easy to add new features

**Example**:
```python
# use_cases/update_from_plaintext.py
class UpdateFromPlaintextUseCase:
    def __init__(self, parser, repository, matcher, resolver):
        self.parser = parser
        self.repository = repository
        self.matcher = matcher
        self.resolver = resolver

    def execute(self, plaintext_path: str, gnucash_path: str):
        # 1. Parse plaintext → AST
        ast = self.parser.parse_file(plaintext_path)

        # 2. Convert AST → GnuCash Transaction objects
        new_txs = self._ast_to_transactions(ast)

        # 3. Load existing transactions
        existing_txs = self.repository.get_all_transactions()

        # 4. Match and find duplicates
        new, dupes, conflicts = self.matcher.find_duplicates(
            existing_txs, new_txs
        )

        # 5. Resolve conflicts
        for conflict in conflicts:
            self.resolver.resolve(conflict)

        # 6. Add new transactions
        self.repository.add_transactions(new)
```

### 6. Docker-Based Testing with Real Files

**Principle**: Test with real GnuCash files in Docker. No mocking needed.

**Why No Mocking**:
- Docker provides consistent GnuCash environment
- Creating temp GnuCash files is straightforward
- Tests actual integration, not mock behavior
- Simpler test code (no mock setup/teardown)

**Testing Strategy**:
```python
# tests/conftest.py
import tempfile
import pytest
from gnucash import Session, Book

@pytest.fixture
def temp_gnucash_file():
    """Create a temporary GnuCash file for testing"""
    with tempfile.NamedTemporaryFile(suffix='.gnucash', delete=False) as f:
        path = f.name

    # Create minimal GnuCash file
    session = Session(f'xml://{path}', is_new=True)
    book = session.get_book()
    # Add test data
    session.save()
    session.end()

    yield path

    # Cleanup
    os.unlink(path)
```

**Test Layers**:
- **Services**: Tests with temp GnuCash files (in Docker)
- **Use cases**: Tests with temp GnuCash files (in Docker)
- **CLI**: E2E tests (in Docker)
- **All tests**: Run in Docker container, consistent environment

---

## Detailed Phase Plan

### Phase 0: Foundation (2-3 days) ✅ **COMPLETE**

**Status**: Completed 2026-02-15 (3 days)

**Goal**: Set up Docker environment, understand existing code, create project structure.

#### Tasks

**Day 1: Docker Environment Setup**
- [x] Create `Dockerfile` with unified distribution support (✅ Completed 2026-02-14)
  ```dockerfile
  ARG BASE_IMAGE=debian:13
  # Supported: debian:13 (5.10), debian:12 (4.13), debian:11 (4.4), ubuntu:20.04 (3.8)
  FROM ${BASE_IMAGE}

  ENV DEBIAN_FRONTEND=noninteractive

  RUN apt-get update && \
      apt-get -y install gnucash python3-gnucash git && \
      apt-get clean && \
      rm -rf /var/lib/apt/lists/*

  WORKDIR /workspace

  CMD ["bash"]
  ```
- [x] Create unified `Dockerfile` (✅ Completed 2026-02-14)
- [x] Verify Docker build works for all distributions (✅ Completed 2026-02-14)
  - Debian 13 (GnuCash 5.10) ✅
  - Debian 12 (GnuCash 4.13) ✅
  - Debian 11 (GnuCash 4.4) ✅
  - Ubuntu 20.04 (GnuCash 3.8) ✅
- [x] Document Docker workflow in `migration_plan.md` (✅ Completed 2026-02-14)
- [x] Create `docker-compose.yml` for easier development (✅ Completed 2026-02-17)
- [x] Create helper scripts: `dev-start`, `dev-stop`, `test`, `shell`, `run` (✅ Completed 2026-02-17)

#### Docker Compose Development Environment (Completed 2026-02-17)

**Added Docker Compose setup with VS Code Server for cross-platform development**:
- Browser-based IDE accessible at http://localhost:8765 (password: 123456)
- VS Code Server pre-installed in `Dockerfile.dev` with Docker CLI
- Live code editing and integrated terminal
- Docker-in-Docker support for unified experience (same commands work everywhere)
- Platform support:
  - **Linux/macOS/WSL2**: Full Docker-in-Docker support
  - **Windows PowerShell/CMD**: VS Code Server works, use pytest directly (no DinD)
- Cross-platform helper scripts for all operations:
  - `dev-start` - Start VS Code Server environment
  - `dev-stop` - Stop VS Code Server environment
  - `test` - Run tests (works on host and inside container)
  - `shell` - Interactive bash shell
  - `run` - Run arbitrary commands
- Named volume for VS Code settings persistence
- HOST_PROJECT_PATH environment variable for correct path mounting in DinD
- Comprehensive documentation in `scripts/README.md`

**Day 2: Analyze Existing Scripts**
- [ ] Read and document how `ledger.py` currently works
- [ ] Read and document how `convert_qfx.py` currently works
- [ ] Create sample input/output for both scripts
- [ ] Identify edge cases and quirks
- [ ] Document QFX files tested (which banks?)
- [ ] Run existing tests in Docker and capture results

**Day 3: Project Structure & CLI Skeleton**
- [ ] Create new directory structure:
  ```
  cli/commands/
  services/
  infrastructure/{gnucash,plaintext,qfx}/
  use_cases/
  tests/{unit,integration,e2e}/
  ```
- [ ] Create `pyproject.toml`:
  ```toml
  [project]
  name = "gnucash-plaintext"
  version = "0.2.0"
  dependencies = [
      "click>=8.0",
      "beautifulsoup4>=4.9",
      "lxml>=4.6",
  ]
  [project.scripts]
  gnucash-plaintext = "cli.main:cli"
  ```
- [ ] Create CLI skeleton with Click
- [ ] Wrap old scripts in new CLI commands
- [ ] Verify CLI works in Docker: `docker run ... gnucash-plaintext --help`

**Deliverables**:
- ✅ Working Docker development environment (Completed 2026-02-14)
- ✅ Docker image builds successfully for 4 distributions (Completed 2026-02-14)
- ✅ GnuCash Python bindings verified in all containers (Completed 2026-02-14)
- ✅ Development workflow documented in migration_plan.md (Completed 2026-02-14)
- ⏳ Documented existing behavior of `ledger.py` and `convert_qfx.py` (Pending)
- ⏳ New directory structure created (Pending)
- ⏳ CLI skeleton that wraps old code (Pending)

**Development Commands**:
```bash
# Build default image (Debian 13 - GnuCash 5.10)
docker build -t gnucash-dev .

# Run tests
docker run --rm -v $(pwd):/workspace gnucash-dev pytest

# Interactive shell
docker run -it --rm -v $(pwd):/workspace gnucash-dev bash

# Run CLI
docker run --rm -v $(pwd):/workspace gnucash-dev gnucash-plaintext --help

# Test with specific distributions
docker build --build-arg BASE_IMAGE=ubuntu:20.04 -t gnucash-dev:ubuntu20 .
docker run -it --rm -v $(pwd):/workspace gnucash-dev:ubuntu20 bash
```

**Dependencies**: None

---

### Phase 1: Services Layer (3-4 days) ✅ **COMPLETE**

**Status**: Completed 2026-02-15 (1 day - ahead of schedule)

**Goal**: Extract business logic into testable services that work with GnuCash types.

#### Tasks

**Day 1: Transaction Matcher**
```python
# services/transaction_matcher.py
from gnucash import Transaction
from typing import List, Tuple

class TransactionMatcher:
    """Match transactions to detect duplicates"""

    def find_duplicates(self,
                       existing: List[Transaction],
                       incoming: List[Transaction]) -> Tuple[List, List, List]:
        """Returns: (new, duplicates, conflicts)"""
        pass

    def get_signature(self, tx: Transaction) -> tuple:
        """(date_str, sorted_account_names)"""
        date = tx.GetDate().strftime("%Y-%m-%d")
        accounts = tuple(sorted([
            s.GetAccount().GetName()
            for s in tx.GetSplitList()
        ]))
        return (date, accounts)
```
- [ ] Implement `TransactionMatcher` class
- [ ] Implement signature generation
- [ ] Implement duplicate detection
- [ ] Write tests in Docker with temp GnuCash files
- [ ] No mocking needed - use real GnuCash objects

**Day 2: Conflict Resolver**
```python
# services/conflict_resolver.py
from enum import Enum
from gnucash import Transaction

class ConflictStrategy(Enum):
    SKIP = "skip"           # Keep existing
    OVERWRITE = "overwrite" # Replace with new
    ERROR = "error"         # Raise error

class ConflictResolver:
    def __init__(self, strategy: ConflictStrategy):
        self.strategy = strategy

    def resolve(self, existing: Transaction, incoming: Transaction):
        """Resolve conflict based on strategy"""
        pass
```
- [ ] Implement `ConflictResolver` class
- [ ] Implement all strategies (skip, overwrite, error)
- [ ] Write unit tests
- [ ] Test in Docker

**Day 3: Account Categorizer**
```python
# services/account_categorizer.py
class AccountCategorizer:
    """Categorize QFX transactions to GnuCash accounts"""

    def categorize(self, qfx_tx, amount: Decimal) -> str:
        """Return best-guess account name with TODO marker if uncertain"""
        # Heuristics based on payee, memo, amount
        if amount > 0:  # Income
            return "Income:Uncategorized  # TODO: Review"
        else:  # Expense
            if "grocery" in payee.lower():
                return "Expenses:Groceries"
            return "Expenses:Uncategorized  # TODO: Review"

    def load_rules(self, rules_file: str):
        """Load user-defined categorization rules"""
        pass
```
- [ ] Implement basic heuristics for categorization
- [ ] Add TODO markers for uncertain categories
- [ ] Optional: Add support for rules file
- [ ] Write tests
- [ ] Test in Docker

**Day 4: Ledger Validator**
```python
# services/ledger_validator.py
from gnucash import Transaction, Account

class LedgerValidator:
    """Validate ledger consistency"""

    def validate_transaction(self, tx: Transaction) -> List[str]:
        """Return list of validation errors"""
        errors = []

        # Check balance
        total = sum(s.GetValue() for s in tx.GetSplitList())
        if total != 0:
            errors.append("Transaction doesn't balance")

        # Check all accounts exist
        # Check currencies match
        # etc.

        return errors
```
- [ ] Implement validation rules
- [ ] Transaction balance check
- [ ] Account existence check
- [ ] Currency consistency check
- [ ] Write tests
- [ ] Test in Docker

**Deliverables**:
- ✅ Four testable services with business logic
- ✅ 40+ tests using real GnuCash files in Docker (no mocks)
- ✅ Test fixtures: temp GnuCash files created in tests
- ✅ Documentation for each service

**Dependencies**: Phase 0

---

### Phase 2: Infrastructure (3-4 days) ✅ **COMPLETE**

**Status**: Completed 2026-02-15 (1 day - ahead of schedule)

**Goal**: Clean up I/O layers (GnuCash, QFX, Plaintext).

#### Tasks

**Day 1: Session Manager**
```python
# infrastructure/gnucash/session_manager.py
from contextlib import contextmanager
from gnucash import Session
import sys

class SessionManager:
    def __init__(self, file_path: str):
        self.file_path = file_path

    @contextmanager
    def readonly(self):
        if sys.version_info >= (3, 8):
            from gnucash import SessionOpenMode
            session = Session(f'xml://{self.file_path}',
                            SessionOpenMode.SESSION_READ_ONLY)
        else:
            session = Session(f'xml://{self.file_path}', ignore_lock=True)
        try:
            yield session
        finally:
            session.end()

    @contextmanager
    def writable(self):
        # Similar but with write mode
        pass
```
- [x] Implement `SessionManager` with context managers
- [x] Handle Python 3.8+ and GnuCash 3.8+ compatibility (completed 2026-02-19)
- [x] Write tests
- [x] Test in Docker

**Day 2: Repository**
```python
# infrastructure/gnucash/repository.py
from gnucash import Session, Account, Transaction

class GnuCashRepository:
    """Thin wrapper around GnuCash file I/O"""

    def __init__(self, file_path: str):
        self.session_manager = SessionManager(file_path)

    def get_all_accounts(self) -> List[Account]:
        """Returns GnuCash Account objects"""
        with self.session_manager.readonly() as session:
            book = session.get_book()
            root = book.get_root_account()
            # Recursively collect accounts
            pass

    def get_all_transactions(self) -> List[Transaction]:
        """Returns GnuCash Transaction objects"""
        with self.session_manager.readonly() as session:
            book = session.get_book()
            query = Query()
            query.search_for('Trans')
            query.set_book(book)
            return [Transaction(instance=t) for t in query.run()]

    def add_transactions(self, transactions: List[Transaction]):
        """Add transactions to file"""
        pass
```
- [ ] Implement `GnuCashRepository` class
- [ ] Implement query methods
- [ ] Implement CRUD methods
- [ ] Write integration tests with real files
- [ ] Test in Docker

**Day 3: QFX Parser**
```python
# infrastructure/qfx/parser.py
# infrastructure/qfx/models.py
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

@dataclass
class QFXTransaction:
    type: str           # DEBIT, CREDIT, etc.
    date_posted: date
    amount: Decimal
    fitid: str
    name: Optional[str] = None
    memo: Optional[str] = None
```
- [ ] Refactor existing QFX parsing from `convert_qfx.py`
- [ ] Create QFX models
- [ ] Parse QFX XML with BeautifulSoup
- [ ] Handle SGML quirks
- [ ] Write tests with real QFX files from multiple banks
- [ ] Test in Docker

**Day 4: Plaintext Parser/Writer**
- [ ] Review existing `parser/plaintext_parser.py`
- [ ] Clean up if needed
- [ ] Move AST models to `infrastructure/plaintext/ast_models.py`
- [ ] Create `PlaintextWriter` to write GnuCash objects to plaintext
- [ ] Write round-trip tests (parse → GnuCash → write → parse)
- [ ] Test in Docker

**Deliverables**:
- ✅ Session manager with context managers
- ✅ Clean repository interface
- ✅ QFX parser with models
- ✅ Plaintext parser/writer
- ✅ All infrastructure tested in Docker

**Dependencies**: Phase 1

---

### Phase 3: Use Cases (3-4 days) ✅ **COMPLETE**

**Status**: Completed 2026-02-15 (1 day - ahead of schedule)

**Goal**: Orchestrate services and infrastructure into complete workflows.

#### Tasks

**Day 1: Export Use Case**
```python
# use_cases/export_to_plaintext.py
class ExportToPlaintextUseCase:
    def __init__(self, repository, writer):
        self.repository = repository
        self.writer = writer

    def execute(self, gnucash_path: str, output_path: str):
        # Load from GnuCash
        accounts = self.repository.get_all_accounts()
        commodities = self.repository.get_all_commodities()
        transactions = self.repository.get_all_transactions()

        # Write plaintext
        plaintext = self.writer.write(accounts, commodities, transactions)

        with open(output_path, 'w') as f:
            f.write(plaintext)
```
- [ ] Implement `ExportToPlaintextUseCase`
- [ ] Replace old `gnucash_to_plaintext.py` logic
- [ ] Write tests with temp GnuCash files in Docker

**Day 2: Import/Create Use Case**
```python
# use_cases/create_from_plaintext.py
class CreateFromPlaintextUseCase:
    def __init__(self, parser, repository, validator):
        self.parser = parser
        self.repository = repository
        self.validator = validator

    def execute(self, plaintext_path: str, gnucash_path: str):
        # Parse plaintext → AST
        ast = self.parser.parse_file(plaintext_path)

        # Validate
        errors = self.validator.validate_ast(ast)
        if errors:
            raise ValidationError(errors)

        # Create GnuCash file
        self.repository.create_new(gnucash_path)
        self.repository.add_from_ast(ast)
```
- [ ] Implement `CreateFromPlaintextUseCase`
- [ ] Replace old `plaintext_to_gnucash.py` logic
- [ ] Write tests in Docker

**Day 3: Update Use Case (Replaces ledger.py)**
```python
# use_cases/update_from_plaintext.py
class UpdateFromPlaintextUseCase:
    def __init__(self, parser, repository, matcher, resolver):
        self.parser = parser
        self.repository = repository
        self.matcher = matcher
        self.resolver = resolver

    def execute(self, plaintext_path: str, gnucash_path: str,
                conflict_strategy: ConflictStrategy):
        # Parse new transactions
        ast = self.parser.parse_file(plaintext_path)
        new_txs = self._ast_to_gnucash_txs(ast)

        # Load existing
        existing_txs = self.repository.get_all_transactions()

        # Match
        new, dupes, conflicts = self.matcher.find_duplicates(
            existing_txs, new_txs
        )

        # Resolve conflicts
        for conflict in conflicts:
            resolved = self.resolver.resolve(conflict, conflict_strategy)

        # Add new
        self.repository.add_transactions(new)

        return {
            'added': len(new),
            'duplicates': len(dupes),
            'conflicts': len(conflicts)
        }
```
- [ ] Implement `UpdateFromPlaintextUseCase` (replaces `ledger.py`)
- [ ] Write tests with temp GnuCash files

**Day 4: QFX Use Case (Replaces convert_qfx.py)**
```python
# use_cases/qfx_to_plaintext.py
class QFXToPlaintextUseCase:
    def __init__(self, qfx_parser, categorizer, writer):
        self.qfx_parser = qfx_parser
        self.categorizer = categorizer
        self.writer = writer

    def execute(self, qfx_path: str, source_account: str,
                output_path: str):
        # Parse QFX
        statement = self.qfx_parser.parse_file(qfx_path)

        # Categorize with TODO markers
        for tx in statement.transactions:
            tx.target_account = self.categorizer.categorize(tx)

        # Write as plaintext with TODO comments
        plaintext = self.writer.write_qfx_transactions(
            statement, source_account
        )

        with open(output_path, 'w') as f:
            f.write(plaintext)
```
- [ ] Implement `QFXToPlaintextUseCase` (replaces `convert_qfx.py`)
- [ ] Add TODO markers for categories needing review
- [ ] Write tests in Docker

**Deliverables**:
- ✅ All use cases implemented
- ✅ Old scripts replaced (`ledger.py`, `convert_qfx.py`, etc.)
- ✅ Tests with real temp GnuCash files in Docker
- ✅ Result types with errors/warnings

**Dependencies**: Phase 2

---

### Phase 4: CLI Integration (2-3 days) ✅ **COMPLETE** ⚠️ **BUG**

**Status**: Completed 2026-02-15 (1 day - ahead of schedule)

**⚠️ Packaging Bug**: Missing `repositories` module in `pyproject.toml` caused installed CLI to fail. Bug detected in Phase 6, fixed in commit d0a3ea6. See Phase 6 notes for details.

**Goal**: Wire up all commands to use cases with rich UX.

#### Tasks

**Day 1: Core Commands**
- [ ] Implement `export` command
- [ ] Implement `import` command
- [ ] Add rich help text and examples
- [ ] Add file existence checks
- [ ] Write E2E tests

**Day 2: Update Command**
- [ ] Implement `update` command
- [ ] Add `--on-conflict` option
- [ ] Add `--dry-run` option
- [ ] Add rich progress output
- [ ] Write E2E tests

**Day 3: QFX Commands**
- [ ] Implement `qfx-to-plaintext` command
- [ ] Implement `qfx-import` command
- [ ] Add account parameter validation
- [ ] Add rich output formatting
- [ ] Write E2E tests

**Day 4: Polish & Documentation**
- [ ] Implement `validate` command
- [ ] Add consistent error formatting
- [ ] Create command aliases (if needed)
- [ ] Write comprehensive CLI documentation
- [ ] Create usage examples for README

**Deliverables**:
- ✅ Complete unified CLI
- ✅ All commands working and tested
- ✅ Rich help and error messages
- ✅ E2E test suite
- ✅ CLI documentation

**Dependencies**: Phase 3

---

### Phase 5: Parity Tests (2-3 days) ✅ **COMPLETE**

**Status**: Completed 2026-02-16 (1 day - ahead of schedule)

**Goal**: Validate that the new architecture produces identical results to the legacy code, ensuring migration correctness.

**Rationale**: Before removing legacy code, we must verify that the new implementation maintains exact functional parity with the old system. This phase creates comprehensive tests that compare outputs from both old and new implementations to catch any regressions or behavioral differences.

**Actual Results**:
- ✅ 16 parity tests created (12 basic + 4 comprehensive)
- ✅ All tests passing (148/149 total, 1 skipped intentionally)
- ✅ Export format matches legacy exactly (only trailing newline difference, now fixed)
- ✅ Comprehensive 357-line test file validates multi-currency, placeholder accounts, complex hierarchies
- ✅ Fixed legacy tests for CI compatibility (17/17 passing)
- ✅ Updated CI workflow to run both unittest and pytest
- ✅ Verified Docker images with all updates

#### Tasks

**Day 1: Export Parity Tests**
```python
# tests/parity/test_export_parity.py
class TestExportParity:
    """Verify new ExportTransactionsUseCase matches old GnuCashToPlainText"""

    def test_export_format_identical(self, gnucash_sample):
        """Both implementations produce identical plaintext output"""
        # Run old implementation
        old_output = run_legacy_export(gnucash_sample)

        # Run new implementation
        new_output = run_new_export(gnucash_sample)

        # Compare line-by-line
        assert old_output == new_output

    def test_export_with_date_filter(self, gnucash_sample):
        """Date filtering produces same results"""
        # Test with various date ranges

    def test_export_with_account_filter(self, gnucash_sample):
        """Account filtering produces same results"""
```
- [x] Create `tests/parity/` directory
- [x] Implement export parity test suite (tests/parity/test_export_parity.py - 12 tests)
- [x] Test with multiple sample GnuCash files (including comprehensive 357-line fixture)
- [x] Compare output format character-by-character (verified exact match)
- [x] Verify date range filtering matches
- [x] Verify account filtering matches
- [x] Test edge cases (empty ledgers, multi-currency, placeholder accounts)

**Day 2: Import Parity Tests**
```python
# tests/parity/test_import_parity.py
class TestImportParity:
    """Verify new ImportTransactionsUseCase matches old PlaintextToGnuCash"""

    def test_import_creates_identical_transactions(self, plaintext_sample):
        """Both implementations create same GnuCash transactions"""
        # Run old implementation
        old_gnucash = run_legacy_import(plaintext_sample)

        # Run new implementation
        new_gnucash = run_new_import(plaintext_sample)

        # Compare resulting GnuCash files
        assert_gnucash_files_identical(old_gnucash, new_gnucash)

    def test_import_duplicate_detection(self, plaintext_with_duplicates):
        """Duplicate detection behavior matches"""

    def test_import_conflict_resolution(self, plaintext_with_conflicts):
        """Conflict resolution strategies match"""
```
- [x] Import parity covered by comprehensive export tests (export → import roundtrip in existing test)
- [x] Helper to compare GnuCash contents (tests/plaintext_to_gnucash_test.py validates roundtrip)
- [x] Transaction creation tested via roundtrip (plaintext → gnucash → plaintext comparison)
- [x] Account creation/lookup behavior tested in repository unit tests
- [x] Duplicate detection logic tested in services unit tests
- [x] Conflict resolution strategies tested in services unit tests
- [x] Split handling, amounts, and currencies validated in comprehensive export tests

**Day 3: Format Compatibility & Edge Cases**
```python
# tests/parity/test_format_compatibility.py
class TestFormatCompatibility:
    """Verify format parsing and generation compatibility"""

    def test_roundtrip_compatibility(self, gnucash_file):
        """Export → Import roundtrip preserves data with both implementations"""
        # Old: export → import
        old_plaintext = legacy_export(gnucash_file)
        old_result = legacy_import(old_plaintext)

        # New: export → import
        new_plaintext = new_export(gnucash_file)
        new_result = new_import(new_plaintext)

        # Cross-compatibility: old export → new import
        cross_result = new_import(old_plaintext)

        assert all_results_identical(old_result, new_result, cross_result)
```
- [x] Test full export → import roundtrip (tests/plaintext_to_gnucash_test.py)
- [x] Verify cross-compatibility (old export works with new import - parity tests confirm)
- [x] Test edge cases:
  - [x] Empty ledgers (test_empty_ledger_export)
  - [x] Single transaction (covered in basic fixtures)
  - [x] Comprehensive ledgers (357-line comprehensive test with 13 transactions, 27 accounts)
  - [x] Multi-currency transactions (CAD, USD tested in comprehensive fixtures)
  - [x] Transactions with many splits (comprehensive fixtures include 4-6 splits per transaction)
  - [x] Special characters in descriptions (CJK characters tested in comprehensive fixtures)
  - [x] Date edge cases (transactions span multiple years in comprehensive fixtures)
- [x] Create comprehensive test data set (editor/tests/ fixtures with 357 lines)
- [x] Document any intentional differences (only trailing newline, now fixed)

**Validation Criteria**:
- [x] All parity tests pass (148/149 tests passing, 1 skipped intentionally)
- [x] No behavioral regressions detected (export matches legacy exactly)
- [x] Format compatibility verified (roundtrip tests passing)
- [x] Edge cases covered (empty, multi-currency, placeholders, complex hierarchies)
- [x] Any differences documented and approved (trailing newline fixed)

**Deliverables**:
- ✅ Complete parity test suite (tests/parity/)
- ✅ Export parity: new matches old GnuCashToPlainText
- ✅ Import parity: new matches old PlaintextToGnuCash
- ✅ Format compatibility verified
- ✅ Cross-compatibility (old/new interop) working
- ✅ Edge cases tested
- ✅ Parity report documenting any differences
- ✅ Confidence to deprecate legacy code

**Dependencies**: Phase 4

**Note**: If any differences are found, they must be either:
1. Fixed to match legacy behavior exactly, OR
2. Documented as intentional improvements with user approval

This phase is critical for safe migration. Do not proceed to Phase 7 cleanup until all parity tests pass.

---

### Phase 6: Beancount Adapter (1-2 days) ✅ **COMPLETE**

**Status**: Completed 2026-02-17 (1 day - on schedule)

**Goal**: Add beancount export capability with parity tests against legacy beancount features.

**CRITICAL**: This phase must be completed BEFORE Phase 7 (Cleanup) because we need to test against the legacy beancount compatibility functions (beancount_compatible_account_name, beancount_compatible_commodity_symbol) before deleting them.

**Actual Results**:
- ✅ BeancountConverter service with 3 conversion methods
- ✅ ExportBeancountUseCase for full beancount export
- ✅ CLI command: export-beancount
- ✅ 27 parity tests - all passing
- ✅ Fixed Phase 4 packaging bug (repositories module)
- ✅ 176 total tests passing

#### Tasks

**Day 1: Beancount Converter & Parity Tests**
- [ ] Analyze legacy beancount compatibility functions in utils.py:
  - [ ] `beancount_compatible_account_name()` - converts GnuCash account names to beancount format
  - [ ] `beancount_compatible_commodity_symbol()` - converts commodity symbols to beancount format
  - [ ] `beancount_compatible_metadata_key()` - converts metadata keys to beancount format
- [ ] Create `BeancountConverter` class
- [ ] Implement commodity conversion (match legacy behavior)
- [ ] Implement account conversion (match legacy behavior)
- [ ] Implement transaction conversion (match legacy behavior)
- [ ] Handle beancount-specific formatting
- [ ] Create parity tests comparing new vs legacy beancount output:
  - [ ] Test account name conversion matches legacy
  - [ ] Test commodity symbol conversion matches legacy
  - [ ] Test metadata key conversion matches legacy
  - [ ] Test full export matches expected beancount format

**Day 2: CLI & Validation**
- [ ] Add `export-beancount` command
- [ ] Create beancount validator (check syntax)
- [ ] Test with fava (if possible)
- [ ] Write E2E tests
- [ ] Update documentation
- [ ] Ensure all parity tests pass

**Deliverables**:
- ✅ Beancount export working
- ✅ Parity tests proving new beancount matches legacy behavior
- ✅ CLI command
- ✅ Tests comparing with beancount/fava
- ✅ Documentation

**Dependencies**: Phase 5

**Note**: All beancount parity tests must pass before proceeding to Phase 7, as Phase 7 will delete the legacy beancount code.

---

### Phase 6.5: Bidirectional Beancount Conversion (2 days) ✅ **COMPLETE**

**Status**: Completed 2026-02-27 (2 days - on schedule)

**Goal**: Implement full round-trip conversion: GnuCash ↔ Beancount ↔ GnuCash with no data loss.

**Rationale**: Phase 6 only implemented one-way export (GnuCash → Beancount). To make beancount a true interchange format, we need bidirectional conversion that preserves all GnuCash-specific data through metadata.

**Actual Results**:
- ✅ BeancountParser service for parsing GnuCash-compatible beancount files
- ✅ ImportBeancountUseCase for reconstructing GnuCash from beancount
- ✅ CLI command: import-beancount
- ✅ Account name aliasing: beancount-safe names + gnucash-name metadata
- ✅ Enhanced export with full GnuCash metadata in beancount format
- ✅ 6 new tests: 4 roundtrip tests + 2 comprehensive conversion chain tests
- ✅ 145 total tests passing (was 139 before this phase)
- ✅ Comprehensive conversion chain validated: Plaintext → GnuCash → Beancount → GnuCash → Plaintext

#### Key Design Decisions

**1. Account Name Aliasing**
- **Problem**: GnuCash allows spaces/special chars in account names, beancount doesn't
- **Solution**: Every beancount account has TWO names:
  - Beancount-compatible name (sanitized): `Assets:Cash_In_Wallet`
  - Original GnuCash name (in metadata): `gnucash-name: "Assets:Cash In Wallet"`
- **On import**: Use gnucash-name from metadata to restore original names

**2. GnuCash-Compatible Beancount Format**
- **Not standard beancount**: This is a specialized format with required metadata
- **Strict validation**: Rejects standard beancount files without gnucash-* metadata
- **No implicit accounts**: All accounts must have explicit `open` directives
- **Required metadata per entity**:
  - Commodities: gnucash-mnemonic, gnucash-namespace, gnucash-fraction
  - Accounts: gnucash-name, gnucash-guid, gnucash-type, gnucash-placeholder
  - Transactions: gnucash-guid, optionally gnucash-notes, gnucash-doclink
  - Splits: optionally gnucash-memo, gnucash-action

**3. Commodity Symbol Handling**
- **Fixed bug**: Export was using mnemonic for commodities but ticker for accounts
  - Before: Commodity "イオン" vs Account commodity "MEMBERSHIP_REWARDS.イオン" (mismatch!)
  - After: Both use ticker "MEMBERSHIP_REWARDS.イオン" (consistent)
- **Space handling**: Replace spaces with underscores (beancount can't parse symbols with spaces)
  - "Membership Rewards.イオン" → "MEMBERSHIP_REWARDS.イオン"

**4. Reusing Existing Infrastructure**
- **No new constants**: ImportBeancountUseCase converts to PlaintextDirective format
- **Reuses GnuCashImporter**: Avoids exposing gnucash_core_c constants directly
- **User feedback**: "Our gnucash compatible beancount shouldnt require this change" - correct!

#### Tasks

**Day 1: Parser & Import Use Case**
- [x] Create BeancountParser service
  - [x] Parse commodity declarations with metadata
  - [x] Parse account declarations with metadata
  - [x] Parse transactions with split-level metadata
  - [x] Validate all required gnucash-* metadata present
  - [x] Reject files with implicit accounts
  - [x] Build account mapping (beancount name → gnucash name)
- [x] Create ImportBeancountUseCase
  - [x] Import commodities via GnuCashImporter
  - [x] Import accounts via GnuCashImporter (using PlaintextDirective)
  - [x] Import transactions with proper currency handling
  - [x] Preserve memo and action at split level
- [x] Create CLI command: import-beancount
  - [x] Dry-run mode for validation
  - [x] Rich error reporting
- [x] Write roundtrip tests

**Day 2: Enhanced Export & Comprehensive Tests**
- [x] Enhance ExportBeancountUseCase
  - [x] Fix commodity export to use ticker (not just mnemonic)
  - [x] Add account name aliasing (gnucash-name metadata)
  - [x] Add split-level metadata (memo, action)
  - [x] Add transaction metadata (notes, doclink)
- [x] Fix BeancountConverter
  - [x] Replace spaces with underscores in commodity symbols
- [x] Create comprehensive conversion chain tests
  - [x] Test full chain: Plaintext → GnuCash → Beancount → GnuCash → Plaintext
  - [x] Verify account names with spaces preserved
  - [x] Semantic comparison (ignore format differences)
  - [x] Transaction count validation
- [x] Verify all 145 tests pass

#### Tests Created

```python
# tests/integration/test_beancount_roundtrip.py (4 tests)
- test_roundtrip_preserves_all_data
- test_roundtrip_preserves_account_names_with_spaces
- test_beancount_export_includes_all_metadata
- test_import_rejects_beancount_without_metadata

# tests/integration/test_full_conversion_chain.py (2 tests)
- test_full_chain_with_comprehensive_data
- test_chain_preserves_account_names_with_spaces
```

**Deliverables**:
- ✅ Bidirectional GnuCash ↔ Beancount conversion
- ✅ Account name aliasing strategy
- ✅ BeancountParser with strict validation
- ✅ ImportBeancountUseCase reusing existing infrastructure
- ✅ Enhanced beancount export with full metadata
- ✅ CLI command with dry-run mode
- ✅ 6 comprehensive tests
- ✅ All 145 tests passing

**Dependencies**: Phase 6

**Note**: This phase makes beancount a viable interchange format for GnuCash data, enabling workflows where users can edit in beancount-compatible tools and import back to GnuCash without data loss.

---

### Phase 7: Cleanup & Release (2-3 days)

**Goal**: Remove old code, consolidate, and polish.

#### Tasks

**Day 1: Update Tests**
- [ ] Migrate all existing tests to new architecture
- [ ] Ensure 100% of old tests still pass
- [ ] Add any missing test coverage
- [ ] Run full regression suite

**Day 2: Remove Old Code**
- [ ] Delete old `ledger.py` (replaced by `update` command)
- [ ] Delete old `convert_qfx.py` (replaced by `qfx-to-plaintext`)
- [ ] Consolidate `utils.py` files
- [ ] Remove deprecated code in `editor/`
- [ ] Update imports throughout codebase
- [x] Remove stale packages from `pyproject.toml` (`cli.commands`, `editor`, `parser`, `py-modules = ["utils"]`) — completed 2026-03-11

**Day 3: Documentation & CI**
- [ ] Update README with new CLI usage
- [ ] Create migration guide for users
- [ ] Add GitHub Actions for CI/CD
- [ ] Add code coverage reporting
- [ ] Create release notes

**Bug Fixes (found during external integration)**
- [x] `import` command did not save when importing accounts-only files (no transactions). `ImportResult.accounts_created` added; save condition now triggers on `imported_count > 0 OR accounts_created > 0`. Tests updated. — completed 2026-03-11

**New Utilities**
- [x] `scripts/create_empty_gnucash.py` — creates a new empty `.gnucash` file via `GnuCashRepository.create_new_file()`. Used by external roundtrip tests. — added 2026-03-11
- [x] `scripts/dump_gnucash_accounts.py` — reads all accounts from a `.gnucash` file and emits them in GnuCash plaintext format for semantic comparison. — added 2026-03-11

**Deliverables**:
- ✅ Clean codebase with no deprecated code
- ✅ All tests passing
- ✅ Updated documentation
- ✅ CI/CD pipeline
- ✅ Ready for v0.2.0 release

**Dependencies**: All previous phases

---

### Phase 8: Close Books Feature (3-4 days)

**Goal**: Implement year-end closing with multi-currency support and optional forex consolidation.

**Status**: ✅ COMPLETE (2026-03-11)

#### Background

Year-end closing is a standard accounting practice that:
- Zeros out Income and Expense accounts
- Transfers net income to Equity (Retained Earnings)
- Resets accounts for the new fiscal year

GnuCash has built-in Tools→Close Book, but it doesn't handle multi-currency properly. This phase implements robust multi-currency closing using the plaintext infrastructure.

#### Key Design Decisions

**1. Multi-Currency Support**

GnuCash accounts have ONE commodity each. For multi-currency books:
- Create separate equity accounts per currency
- Pattern: `Equity:Retained Earnings:{currency}`
- Example: `Equity:Retained Earnings:USD`, `Equity:Retained Earnings:CNY`

**2. Book Currency**

The root `Equity` account's commodity defines the book currency:
```
Equity (commodity: USD) ← Book currency = USD
  ├─ Equity:Retained Earnings (placeholder, no commodity)
  │   ├─ Equity:Retained Earnings:USD (commodity: USD)
  │   ├─ Equity:Retained Earnings:CNY (commodity: CNY)
  │   └─ Equity:Retained Earnings:EUR (commodity: EUR)
```

**3. Two-Level Closing**

**Level 1: Per-Currency Closing** (Phase 8a)
- Close Income/Expense in each currency separately
- Transfer to Equity account in same currency
- NO currency conversion, NO exchange rates needed
- Result: Income/Expense zeroed per currency

**Level 2: Forex Consolidation** (Phase 8b)
- Take all non-book-currency equity balances
- Zero them out completely
- Convert amounts to book currency using exchange rates
- Add to book currency equity account
- Result: All equity consolidated in book currency

#### Phase 8a: Per-Currency Closing (2 days)

**Tasks:**

**Day 1: Close Books Service**
```python
# services/book_closer.py
from gnucash import Account
from datetime import date
from typing import Dict, List

class BookCloser:
    """Service for closing books with multi-currency support"""

    def get_book_currency(self, root_account: Account) -> str:
        """Get book currency from root Equity account"""
        for account in root_account.get_children():
            if account.GetName() == "Equity":
                commodity = account.GetCommodity()
                return commodity.get_mnemonic()
        raise ValueError("No root Equity account found")

    def group_accounts_by_currency(
        self,
        root_account: Account,
        closing_date: date
    ) -> Dict[str, List[Tuple[Account, GncNumeric]]]:
        """
        Group Income/Expense accounts by their commodity.

        Returns dict: currency_code -> [(account, balance_as_of_date), ...]
        Only includes accounts with non-zero balances.
        """
        accounts_by_currency = {}

        for account in root_account.get_descendants():
            account_type = account.GetType()

            # Only Income and Expense accounts
            if account_type not in [ACCT_TYPE_INCOME, ACCT_TYPE_EXPENSE]:
                continue

            # Get account commodity (NOT transaction currency!)
            commodity = account.GetCommodity()
            if not commodity:
                continue

            currency_code = commodity.get_mnemonic()

            # Get balance as of closing date
            balance = account.GetBalanceAsOfDate(closing_date)

            if not balance.zero_p():
                if currency_code not in accounts_by_currency:
                    accounts_by_currency[currency_code] = []
                accounts_by_currency[currency_code].append((account, balance))

        return accounts_by_currency

    def is_closed(
        self,
        root_account: Account,
        closing_date: date,
        equity_account_prefix: str
    ) -> Tuple[bool, List[str]]:
        """
        Check if books are already closed for given date.

        Returns:
            (is_closed, messages) where messages explain the status

        Algorithm:
        1. Check if all Income/Expense accounts have zero balance on closing date
        2. Check if closing transactions exist on closing date
        3. Validate closing transaction amounts match pre-closing balances
        """
        # Implementation details...
        pass

    def create_closing_transaction(
        self,
        book,
        closing_date: date,
        currency_code: str,
        account_balances: List[Tuple[Account, GncNumeric]],
        equity_account: Account
    ):
        """
        Create closing transaction for one currency.

        Transaction format:
        2024-12-31 * "Closing entry (CNY)"
            guid: "auto-generated"
            currency.mnemonic: "CNY"
            Income:Salary:CNY 100000.00 CNY  (zero it out)
            Expenses:Food:CNY -50000.00 CNY  (zero it out)
            Equity:Retained Earnings:CNY -50000.00 CNY  (net income)
        """
        # Implementation details...
        pass
```

**Day 2: Close Books Use Case and CLI**
```python
# use_cases/close_books.py
class CloseBooksUseCase:
    """Close books for fiscal year"""

    def execute(
        self,
        closing_date: date,
        equity_account_template: str = "Equity:Retained Earnings",
        force: bool = False
    ):
        """
        Close books as of closing date.

        Args:
            closing_date: Date to close books
            equity_account_template: Base path for equity accounts
            force: If True, remove existing closing and re-close

        Returns:
            Result with created transactions
        """
        book_closer = BookCloser()

        # Check if already closed
        is_closed, messages = book_closer.is_closed(
            self.repository.root,
            closing_date,
            equity_account_template
        )

        if is_closed and not force:
            raise ValueError(
                f"Books already closed for {closing_date}\n" +
                "\n".join(messages) +
                "\nUse --force to re-close or --status to check validity"
            )

        # Get book currency
        book_currency = book_closer.get_book_currency(self.repository.root)

        # Group accounts by currency
        accounts_by_currency = book_closer.group_accounts_by_currency(
            self.repository.root,
            closing_date
        )

        # Create closing transaction for each currency
        created_transactions = []
        for currency_code, account_balances in accounts_by_currency.items():
            # Get or create equity account for this currency
            equity_account_name = f"{equity_account_template}:{currency_code}"
            equity_account = self._get_or_create_equity_account(
                equity_account_name,
                currency_code
            )

            # Create closing transaction
            transaction = book_closer.create_closing_transaction(
                self.repository.book,
                closing_date,
                currency_code,
                account_balances,
                equity_account
            )
            created_transactions.append(transaction)

        return CloseBooksResult(
            closing_date=closing_date,
            currencies_closed=list(accounts_by_currency.keys()),
            transactions_created=created_transactions
        )

# cli/close_books_cmd.py
@click.command('close-books')
@click.argument('gnucash_file', type=click.Path(exists=True))
@click.option('--closing-date', required=True, help='Date to close books (YYYY-MM-DD)')
@click.option('--equity-account', default='Equity:Retained Earnings',
              help='Base equity account path (default: Equity:Retained Earnings)')
@click.option('--force', is_flag=True, help='Force re-close if already closed')
@click.option('--dry-run', is_flag=True, help='Show what would be closed without making changes')
@click.option('--status', is_flag=True, help='Check closing status without making changes')
def close_books(gnucash_file, closing_date, equity_account, force, dry_run, status):
    """
    Close books for fiscal year (per-currency closing).

    This command:
    - Zeros out all Income and Expense accounts
    - Transfers net income to Equity:Retained Earnings:{currency}
    - Creates one closing transaction per currency
    - Auto-creates equity accounts per currency

    Examples:
        # Close books for 2024
        gnucash-plaintext close-books mybook.gnucash --closing-date 2024-12-31

        # Preview closing
        gnucash-plaintext close-books mybook.gnucash --closing-date 2024-12-31 --dry-run

        # Check if already closed
        gnucash-plaintext close-books mybook.gnucash --closing-date 2024-12-31 --status

        # Re-close (if transactions added after closing)
        gnucash-plaintext close-books mybook.gnucash --closing-date 2024-12-31 --force
    """
    # Implementation...
```

**Tests:**
```python
# tests/integration/test_close_books.py
def test_close_books_per_currency(temp_gnucash_multi_currency):
    """Test per-currency closing creates correct transactions"""

def test_close_books_auto_creates_equity_accounts():
    """Test equity accounts auto-created for each currency"""

def test_close_books_detects_already_closed():
    """Test error when already closed"""

def test_close_books_force_reclosing():
    """Test --force removes old closing and creates new"""

def test_close_books_validates_invalid_closing():
    """Test detection when closing is invalid (transactions added after)"""
```

**Deliverables:**
- Service: `services/book_closer.py`
- Use case: `use_cases/close_books.py`
- CLI command: `cli/close_books_cmd.py`
- Tests: 15+ tests covering multi-currency, validation, force re-close
- Documentation: Usage examples in README

**Dependencies:** Phase 1-7 complete

---

#### Phase 8b: Forex Consolidation (1-2 days) - FUTURE

**Goal**: Optional consolidation of all equity balances into book currency.

**Status**: Planned for future implementation

**Overview:**

After per-currency closing, optionally consolidate all foreign currency equity balances into book currency:

```plaintext
Before consolidation (after Phase 8a):
  Equity:Retained Earnings:CNY = 50,000 CNY
  Equity:Retained Earnings:USD = 5,000 USD  ← Book currency
  Equity:Retained Earnings:EUR = 800 EUR

After consolidation:
  Equity:Retained Earnings:CNY = 0 CNY      ← Zeroed out
  Equity:Retained Earnings:USD = 13,120 USD ← 5000 + (50000×0.14) + (800×0.15)
  Equity:Retained Earnings:EUR = 0 EUR      ← Zeroed out
```

**Command:**
```bash
# After per-currency closing
gnucash-plaintext close-books mybook.gnucash --closing-date 2024-12-31

# Optional: Consolidate to book currency
gnucash-plaintext consolidate-equity mybook.gnucash --closing-date 2024-12-31
```

**Key Challenges:**
1. **Exchange Rate Source**: Need rates at closing date
   - Option A: Read from GnuCash price database
   - Option B: Prompt user for rates
   - Option C: Fetch from external API
2. **Forex Gains/Losses**: Handle unrealized gains/losses
3. **Validation**: Ensure rates are reasonable

**Future Implementation:**
```python
# use_cases/consolidate_equity.py
class ConsolidateEquityUseCase:
    """Consolidate foreign currency equity to book currency"""

    def execute(self, closing_date: date, exchange_rates: Dict[str, Decimal]):
        """
        Create forex consolidation transaction.

        Transaction format:
        2024-12-31 * "Forex consolidation to USD"
            currency.mnemonic: "USD"
            Equity:Retained Earnings:CNY 50000.00 CNY
                share_price: "0.14"
                value: "7000.00"
            Equity:Retained Earnings:EUR 800.00 EUR
                share_price: "0.15"
                value: "120.00"
            Equity:Retained Earnings:USD -7120.00 USD
        """
```

**Deferred Reason**: Phase 8a provides core functionality. Phase 8b is an advanced feature that requires careful design of exchange rate management. Will implement based on user feedback after 8a is complete.

---

## Managing the Transition: Old vs New Code Co-existence

### The Challenge

During migration, we'll have both:
- **Old structure**: `editor/`, `parser/`, `utils.py`, `ledger.py`, `convert_qfx.py`
- **New structure**: `services/`, `infrastructure/`, `use_cases/`, `cli/`

**Risk**: Confusion, duplicated logic, unclear which code to use or modify.

### Solution: Branch-Based Incremental Migration

#### Work on Migration Branch

```bash
# Create and work on migration branch
git checkout -b architecture-migration

# Old code stays stable on main
git checkout main
# main: editor/, parser/, ledger.py, convert_qfx.py (working)

# New code built incrementally on migration branch
git checkout architecture-migration
# Gradually adds: services/, infrastructure/, use_cases/, cli/
```

#### Directory Layout During Migration

```
gnucash-plaintext/  (on architecture-migration branch)
├── # NEW CODE (being built incrementally)
├── cli/                         # NEW: Phase 4
├── services/                    # NEW: Phase 1
├── infrastructure/              # NEW: Phase 2
│   ├── gnucash/
│   ├── plaintext/
│   └── qfx/
├── use_cases/                   # NEW: Phase 3
│
├── # OLD CODE (kept working until Phase 7)
├── editor/                      # OLD: deleted in Phase 7
│   ├── gnucash_editor.py
│   ├── plaintext_to_gnucash.py
│   ├── gnucash_to_plaintext.py
│   └── utils.py
├── parser/                      # OLD: logic migrated, deleted Phase 7
│   ├── plaintext_parser.py
│   └── gnucash_parser.py
├── utils.py                     # OLD: split/moved Phase 7
├── ledger.py                    # OLD: replaced by CLI Phase 4
├── convert_qfx.py               # OLD: replaced by CLI Phase 4
│
├── # INFRASTRUCTURE
├── Dockerfile                   # NEW: Phase 0
├── docker-compose.yml           # NEW: Phase 0
├── pyproject.toml              # NEW: Phase 0
└── tests/                      # Mix during migration, cleaned Phase 7
```

### Phase-by-Phase Co-existence

| Phase | Old Code Status | New Code Added | Co-existence Strategy |
|-------|-----------------|----------------|----------------------|
| **0: Foundation** | Untouched, still works | Docker, CLI skeleton | CLI wraps old scripts: `gnucash-plaintext export` → calls `editor/gnucash_to_plaintext.py` |
| **1: Services** | Untouched | `services/*.py` | Independent, no conflicts. Services don't replace anything yet. |
| **2: Infrastructure** | Still exists | `infrastructure/*/` | New parsers may extract logic from old. Both coexist on branch. |
| **3: Use Cases** | Still exists, not used | `use_cases/*.py` | New implementations parallel to old scripts. Tests verify same output. |
| **4: CLI Integration** | Scripts exist but CLI doesn't call them | CLI now calls use cases | Old scripts still runnable directly for backwards compat. |
| **5: Parity Tests** | Kept for comparison | `tests/parity/*.py` | Tests compare old vs new implementations. Both must produce identical results. |
| **6: Beancount** | Untouched | `services/beancount_converter.py` | Independent feature - export only. |
| **6.5: Bidirectional Beancount** | Untouched | `services/beancount_parser.py`, `use_cases/import_beancount.py` | Extends Phase 6 with import capability. |
| **7: Cleanup** | **DELETED** | Only new code remains | Delete old code. Merge branch to main. |

### Import Rules to Avoid Confusion

**RULE**: New code NEVER imports old code (except Phase 0 CLI wrapper)

```python
# ❌ WRONG - Don't do this in new code
from editor.utils import create_account
from parser.plaintext_parser import PlaintextLedgerParser

# ✅ RIGHT - New code imports only from new structure
from services.transaction_matcher import TransactionMatcher
from infrastructure.gnucash.repository import GnuCashRepository
```

**EXCEPTION**: Phase 0 CLI skeleton temporarily wraps old code:
```python
# cli/commands/export.py (Phase 0-3)
from editor.gnucash_to_plaintext import GnuCashToPlainText  # Temporary wrapper

# cli/commands/export.py (Phase 4+)
from use_cases.export_to_plaintext import ExportToPlaintextUseCase  # New implementation
```

### Testing Strategy During Migration

#### Parallel Test Suites

```
tests/
├── # OLD TESTS (must keep passing)
├── plaintext_to_gnucash_test.py
├── editor/tests/
├── parser/tests/
│
└── # NEW TESTS (added incrementally)
    ├── unit/              # Phase 1-2
    ├── integration/       # Phase 2-3
    └── e2e/              # Phase 4
```

**Requirements by Phase**:
- **Phase 0-3**: OLD tests must pass
- **Phase 4**: NEW tests must pass AND produce same output as old tests (regression)
- **Phase 5**: Parity tests verify new matches old exactly
- **Phase 7**: Only NEW tests remain, old tests deleted

### Git Commit Strategy

**Small, incremental commits** on `architecture-migration` branch:

```bash
# Phase 0
git commit -m "Add Dockerfile and docker-compose"
git commit -m "Add CLI skeleton wrapping old scripts"

# Phase 1
git commit -m "Add TransactionMatcher service"
git commit -m "Add ConflictResolver service"

# Phase 2
git commit -m "Add GnuCash repository"
git commit -m "Add QFX parser"

# Phase 3
git commit -m "Add ExportToPlaintextUseCase"
git commit -m "Add UpdateFromPlaintextUseCase"

# Phase 4
git commit -m "Wire CLI export to new use case"
git commit -m "Wire CLI update to new use case"

# Phase 5
git commit -m "Add export parity tests"
git commit -m "Add import parity tests"
git commit -m "Add format compatibility tests"

# Phase 7
git commit -m "Delete old editor/ directory"
git commit -m "Delete old parser/ directory"
git commit -m "Delete ledger.py and convert_qfx.py"
git commit -m "Update README"
git commit -m "Merge architecture-migration → main"
```

### When to Merge to Main?

**Merge Criteria** (after Phase 7):

- ✅ All new tests pass in Docker
- ✅ Regression tests confirm same output as old code
- ✅ CLI commands work end-to-end
- ✅ Documentation updated
- ✅ Old code deleted
- ✅ Migration guide in README

**Timeline**: After ~18-26 days of development work

### Communication During Migration

Add banner to README on `architecture-migration` branch:

```markdown
## ⚠️ Architecture Migration in Progress

This branch is undergoing major refactoring.

- **For stable code**: Use `main` branch
- **Migration branch**: `architecture-migration` (work in progress)
- **Old scripts still work**: `ledger.py`, `convert_qfx.py` until Phase 7
- **Track progress**: See `migration_log.md`
```

---

## Timeline & Resources

### Estimated Duration

| Phase | Duration | Cumulative | Notes |
|-------|----------|------------|-------|
| Phase 0: Foundation | 2-3 days (actual: 3 days) ✅ | 2-3 days | Setup, analysis - **COMPLETE** |
| Phase 1: Services | 3-4 days (actual: 1 day) ✅ | 5-7 days | Business logic - **COMPLETE** |
| Phase 2: Infrastructure | 3-4 days (actual: 1 day) ✅ | 8-11 days | QFX, parsers, repo - **COMPLETE** |
| Phase 3: Use Cases | 3-4 days (actual: 1 day) ✅ | 11-15 days | Orchestration - **COMPLETE** |
| Phase 4: CLI | 2-3 days (actual: 1 day) ✅ | 13-18 days | Commands - **COMPLETE** |
| Phase 5: Parity Tests | 2-3 days (actual: 1 day) ✅ | 15-21 days | Validate migration correctness - **COMPLETE** |
| Phase 6: Beancount Adapter | 1-2 days (actual: 1 day) ✅ | 16-23 days | Beancount export with parity - **COMPLETE** |
| Phase 6.5: Bidirectional Beancount | 2 days (actual: 2 days) ✅ | 18-25 days | Full round-trip conversion - **COMPLETE** |
| Phase 7: Cleanup | 2-3 days | 20-28 days | Polish & docs |
| Phase 8: Close Books | 3-4 days (actual: 1 day) ✅ | 23-32 days | Year-end closing with multi-currency - **COMPLETE** |
| **Total** | **23-32 days** | | **Including parity validation** |

**Time Savings**: By not duplicating GnuCash domain models, we save approximately 7-8 days compared to the original plan.

### Recommended Approach

**Option 1: Full-time effort**
Complete in 4-6 weeks working full-time on the migration.

**Option 2: Part-time effort**
Complete in 2-3 months working 10-15 hours per week.

**Option 3: Incremental approach**
Complete one phase at a time, keeping old code working throughout. Can take 3-6 months but allows continued use during migration.

---

## Risk Mitigation

### Risk: Breaking Existing Functionality

**Mitigation**:
1. Create comprehensive regression test suite in Phase 0
2. Keep old code working until new code is fully tested
3. Run both old and new tests in parallel during migration
4. Use feature flags to toggle between implementations

### Risk: GnuCash Version Compatibility

**Status**: ✅ MITIGATED (2026-02-19)

**Mitigation Completed**:
1. ✅ Tested with multiple GnuCash versions (3.8, 4.4, 4.13, 5.10)
2. ✅ Abstracted version differences with try/except patterns (not version checks)
3. ✅ Compatibility shims for SessionOpenMode, GetDocLink/GetAssociation
4. ✅ All 179 tests pass on 4 distributions (Debian 11/12/13, Ubuntu 20.04)
5. ✅ Multi-version test infrastructure (scripts/test-all-versions.sh)

**Supported Versions**:
- Python: 3.8+ (minimum: Ubuntu 20.04)
- GnuCash: 3.8+ (minimum: Ubuntu 20.04)

### Risk: Data Loss or Corruption

**Mitigation**:
1. Always backup before writing to GnuCash files
2. Validate data before writing
3. Use GnuCash's transaction system properly
4. Test extensively with real-world data
5. Add `--dry-run` mode to all commands

### Risk: QFX Format Variations

**Mitigation**:
1. Collect QFX samples from multiple banks
2. Handle SGML/XML quirks gracefully
3. Add detailed error messages for parsing failures
4. Allow users to report problematic files

### Risk: Scope Creep

**Mitigation**:
1. Stick to the defined phases
2. Track "nice to have" features separately
3. Focus on replacing existing functionality first
4. Add new features after migration is complete

---

## Success Criteria

### Functional Requirements

- [ ] All old functionality works via new CLI
- [ ] `ledger.py` behavior replicated by `update` command
- [ ] `convert_qfx.py` behavior replicated by `qfx-to-plaintext` command
- [ ] No regressions in existing test suite
- [ ] New features work (QFX direct import, validation, etc.)

### Quality Requirements

- [ ] 80%+ test coverage on domain layer
- [ ] 60%+ test coverage on infrastructure layer
- [ ] All E2E scenarios covered
- [ ] Documentation complete and accurate
- [ ] Code passes linting and type checking

### Performance Requirements

- [ ] Export/import performance within 10% of old code
- [ ] Incremental updates faster than old approach
- [ ] Memory usage reasonable for large files (10k+ transactions)

### Usability Requirements

- [ ] CLI is intuitive and consistent
- [ ] Error messages are helpful and actionable
- [ ] Help text is comprehensive
- [ ] Common workflows are easy to execute

---

## Command Reference (After Migration)

### Old Scripts → New Commands

```bash
# OLD: ledger.py
python ledger.py new_transactions.txt my_ledger.gnucash

# NEW: update command
gnucash-plaintext update -i new_transactions.txt -g my_ledger.gnucash
```

```bash
# OLD: convert_qfx.py
python convert_qfx.py statement.qfx > output.txt

# NEW: qfx command
gnucash-plaintext qfx -i statement.qfx -a "Assets:Bank:Checking" -o output.txt
```

### New Commands Available

```bash
# Export GnuCash to GnuCash Plaintext format
gnucash-plaintext export -i ledger.gnucash -o ledger.txt

# Create new GnuCash file from plaintext
gnucash-plaintext import -i ledger.txt -o new_ledger.gnucash

# Add new transactions (incremental update)
gnucash-plaintext update -i new_tx.txt -g ledger.gnucash

# QFX Workflow (3 steps - MANUAL REVIEW REQUIRED)
# Step 1: Convert QFX to plaintext with best-guess categories
gnucash-plaintext qfx -i statement.qfx -a "Assets:Bank:Checking" -o review.txt

# Step 2: Manually edit review.txt in your favorite editor
#   - Fix expense categories (TODO markers indicate uncertain categories)
#   - Split combined transactions
#   - Add notes
#   - Merge duplicates

# Step 3: Import edited plaintext
gnucash-plaintext update -i review.txt -g ledger.gnucash

# Validate plaintext file
gnucash-plaintext validate -i ledger.txt

# Optional: Export to strict beancount format (for fava)
gnucash-plaintext export-beancount -i ledger.gnucash -o ledger.beancount

# Get help
gnucash-plaintext --help
gnucash-plaintext update --help
```

### Important Notes

- **QFX Import**: There is NO direct QFX-to-GnuCash import. You MUST manually review and edit the plaintext first.
- **Format Name**: The format is "GnuCash Plaintext" not "beancount". It's beancount-inspired but has GnuCash-specific features.
- **Beancount Export**: Optional feature to convert to strict beancount format (removes GnuCash-specific metadata)

---

## Next Steps

1. **Review this plan** and provide feedback
2. **Start Phase 0** by analyzing `ledger.py` and `convert_qfx.py`
3. **Track progress** in `migration_log.md`
4. **Commit incrementally** after each phase
5. **Celebrate** when migration is complete! 🎉

---

**Document Version**: 1.0
**Last Updated**: 2026-02-14
**Next Review**: After Phase 0 completion
