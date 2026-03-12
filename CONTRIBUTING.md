# Contributing to gnucash-plaintext

Thank you for your interest in contributing!

## Contributor License Agreement (CLA)

Before your pull request can be merged, you must sign the
[Contributor License Agreement](CLA.md).

**How to sign:** Add your name, GitHub username, and the date to the
signatories table in `CLA.md` as part of your pull request.

The CLA grants the project owner the right to dual-license contributions
(AGPLv3 for open source use; commercial license for parties that cannot
comply with AGPLv3). You retain full copyright ownership of your contribution.

## License

This project is licensed under the **GNU Affero General Public License v3**
(AGPLv3). See [LICENSE](LICENSE) for the full text.

By contributing, you agree that your contributions will be licensed under
AGPLv3, subject to the CLA terms above.

## Development Setup

### Prerequisites

- Docker (for running tests against real GnuCash Python bindings)
- Git

### Running Tests

Tests run inside Docker containers against real GnuCash files (no mocking):

```bash
# Test all supported versions in parallel
./scripts/test-all-versions-parallel.sh

# Build Docker images first if needed
./scripts/build.sh
```

### Supported GnuCash Versions

| Docker image | GnuCash version | Status |
|---|---|---|
| debian:13 | 5.10 | default |
| debian:12 | 4.13 | supported |
| debian:11 | 4.4 | supported |
| ubuntu:20.04 | 3.8 | minimum |

### Code Style

This project uses `ruff` for linting. Run before committing:

```bash
ruff check .
```

The pre-commit hook runs linting and tests automatically.

## Pull Request Process

1. Fork the repository and create a branch from `main`
2. Add your CLA signature to `CLA.md`
3. Write tests for any new behaviour (tests run in Docker with real GnuCash files)
4. Ensure all tests pass across all supported versions
5. Open a pull request with a clear description of the change
