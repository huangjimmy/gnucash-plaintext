# Debugging GnuCash Python Bindings

## The Reality: No Decision Matrix

**Important**: There is no predictable "decision matrix" for when to use SWIG vs ctypes. GnuCash's Python bindings have platform-specific bugs and missing functions that can only be discovered through testing.

The workflow is always:
1. **Try SWIG first** - it's cleaner when it works
2. **Fall back to ctypes** when SWIG fails on some platform
3. **Document the failure** so others know why ctypes was chosen

## When a Function Doesn't Work

### Step 1: Try the High-Level SWIG API First
```python
# Usually works for object creation and writing operations
from gnucash import Customer, Vendor, Invoice
customer = Customer(book, "CUST-001", currency)
customer.SetName("Acme Corp")
customer.GetAddr().SetAddr1("123 Main St")
```

### Step 2: Check the gnucash_core_c Module
```python
import gnucash.gnucash_core_c as gc
# Sometimes works when high-level SWIG fails
# Use .instance to get raw pointer from SWIG object
is_paid = gc.gncInvoiceIsPaid(invoice.instance)
account_type = gc.xaccAccountGetType(account.instance)
```

### Step 3: Use ctypes (Last Resort)
```python
from infrastructure.gnucash.engine import load_gnc_engine
lib = load_gnc_engine()  # Handles RTLD_GLOBAL promotion for Ubuntu

# For tax tables (SWIG missing these entirely)
tt_ptr = lib.gncTaxTableGetTables(int(book.instance))

# For invoice entries (SWIG has const-type bugs)
desc = (lib.gncEntryGetDescription(entry_ptr) or b'').decode('utf-8')
```

### Step 4: Platform Testing Checklist
You MUST test on all supported platforms:
- [ ] Debian 11 (GnuCash 4.4)
- [ ] Debian 12 (GnuCash 4.13)
- [ ] Debian 13 (GnuCash 5.10)
- [ ] Ubuntu 20.04 (GnuCash 3.8) - minimum version
- [ ] Ubuntu 22.04 (GnuCash 4.8)
- [ ] Ubuntu 24.04 (GnuCash 4.9)

**Common pattern**: Works on Debian, segfaults on Ubuntu → RTLD_LOCAL issue.

## Common Failure Patterns

### 1. "Missing function" in SWIG
- **Symptom**: `AttributeError: module 'gnucash' has no attribute 'gncTaxTableGetTables'`
- **Cause**: SWIG bindings are incomplete for some C functions
- **Solution**: Use ctypes - the function exists in libgnc-engine.so

### 2. Segfault on Ubuntu but works on Debian
- **Symptom**: Works on Debian 11/12/13, crashes on Ubuntu 22/24
- **Cause**: Python loads GnuCash extensions with `RTLD_LOCAL` on Ubuntu
- **Solution**: Use `engine.py`'s `load_gnc_engine()` which promotes to `RTLD_GLOBAL`

### 3. Const-type mismatch in SWIG
- **Symptom**: Function exists but returns garbage or crashes
- **Example**: `gncEntryGetDescription()` in SWIG has wrong const qualifiers
- **Solution**: Use ctypes version from `lib.gncEntryGetDescription()`

### 4. 64-bit pointer truncation
- **Symptom**: Random segfaults, especially with addresses > 4GB
- **Cause**: Missing `argtypes` in ctypes (defaults to 32-bit C `int`)
- **Solution**: Always set `argtypes = [ctypes.c_void_p]` for pointer arguments

## Reading vs Writing Asymmetry

GnuCash Python bindings have different reliability for reading vs writing:

### Writing (Import) - SWIG Usually Works
- `Customer()`, `Vendor()`, `Invoice()` constructors work
- `SetName()`, `SetAddress()`, `SetCurrency()` work reliably
- **Exception**: Tax table entries need `gnucash_core_c` helpers

### Reading (Export) - Often Needs ctypes
- `gncTaxTableGetTables()`: Missing from SWIG (always ctypes)
- `gncEntryGetDescription()`, `gncEntryGetAction()`: SWIG has const-type bugs
- `xaccAccountGetName()`: Works in ctypes, SWIG version buggy on Ubuntu
- `gnc_account_get_full_name()`: Use ctypes version for raw pointers

## Pointer Lifetime Rules

### Rule 1: Once ctypes, stay ctypes
If you get a pointer from ctypes, use ctypes to read from it:
```python
# ✅ CORRECT
acct_ptr = lib.gncTaxTableEntryGetAccount(tte_ptr)  # ctypes
name_b = lib.xaccAccountGetName(acct_ptr)           # ctypes
name = name_b.decode('utf-8') if name_b else ''

# ❌ WRONG - SWIG may not wrap raw pointers safely
acct_ptr = lib.gncTaxTableEntryGetAccount(tte_ptr)
account = Account(instance=acct_ptr)  # Dangerous!
```

### Rule 2: SWIG ↔ ctypes bridge via `.instance`
```python
# Safe: SWIG object → ctypes pointer
entry_ptr = int(entry.instance)  # Get raw pointer from SWIG
desc = lib.gncEntryGetDescription(entry_ptr)  # Use ctypes

# Dangerous: ctypes pointer → SWIG object
# Only do this if you KNOW the pointer came from SWIG originally
raw_ptr = lib.gncTaxTableEntryGetAccount(tte_ptr)
# ❌ account = Account(instance=raw_ptr)  # Usually unsafe
```

## Utility Functions in `engine.py`

The `infrastructure/gnucash/engine.py` module provides:

### `load_gnc_engine()`
- Handles RTLD_GLOBAL promotion for Ubuntu compatibility
- Sets mandatory `argtypes` for 64-bit pointer safety
- Tries multiple library paths across distributions

### GList Structure & Iterator
```python
# Use these for safe GList traversal
from infrastructure.gnucash.engine import GList, iterate_glist

# Instead of raw pointer arithmetic:
results = iterate_glist(lib, glist_ptr, lambda lib, ptr: process_item(lib, ptr))
```

### Safe String Decoding
```python
from infrastructure.gnucash.engine import safe_ctypes_string

# Instead of manual null checks:
name = safe_ctypes_string(lib, lib.xaccAccountGetName, acct_ptr, default="?")
```

## Adding New ctypes Functions

When you discover a new function that needs ctypes:

1. Add to `_setup_lib_restypes()` in `engine.py`:
```python
lib.new_function_name.restype = ctypes.c_void_p
lib.new_function_name.argtypes = [ctypes.c_void_p]  # REQUIRED for pointers
```

2. Test on all platforms
3. Document why SWIG failed

## Running the Test Suite

Always run the comprehensive test suite:
```bash
# In Docker (tests all platforms)
./scripts/test-all-versions.sh

# Or test a specific distribution
./scripts/test-in-docker.sh debian:13
```

The test suite will catch platform-specific failures that guide you to use ctypes.

## Commit Message Documentation

When you add ctypes for a function, document WHY in the commit:
```
fix: Use ctypes for gncEntryGetDescription

SWIG's gncEntryGetDescription has const-type mismatches that:
- Work on Debian but return garbage on Ubuntu 22/24
- Discovered during platform testing (test_business_objects_roundtrip)
- ctypes version works reliably across all distributions
```

## Summary

1. **No prediction possible** - test to discover failures
2. **SWIG first, ctypes when it fails** - pragmatic workflow
3. **Test all platforms** - Ubuntu/Debian differences are common
4. **Document the failures** - helps future maintainers
5. **Use engine.py utilities** - safe ctypes patterns

This approach has proven necessary for maximum compatibility across Ubuntu 20/22/24 and Debian 11/12/13.