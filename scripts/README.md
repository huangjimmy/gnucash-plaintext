# Docker Helper Scripts

Cross-platform helper scripts for GnuCash development with Docker.

## Supported Platforms

- **Linux** and **macOS**: native shell scripts (`.sh`).
- **Windows**: run from **WSL2**. Native PowerShell / CMD wrappers were
  removed because (a) Docker-in-Docker depends on the host's Unix
  socket and (b) the wrappers had drifted out of sync with the bash
  scripts. WSL2 also gives meaningfully better Docker performance on
  Windows.

**Using Podman instead of Docker?** Most scripts work with Podman out of the box. See [PODMAN.md](../PODMAN.md) for detailed compatibility notes and setup instructions.

## Available Scripts

### `dev-start` - Start Development Environment (Recommended)

Start a full development environment with VS Code Server in your browser. This is the easiest way to develop on any host OS.

```bash
./scripts/dev-start.sh
```

Once started, open https://localhost:8765 in your browser and enter password `123456`.

**Note**: The connection uses a self-signed SSL certificate, so your browser will show a security warning. Click "Advanced" → "Proceed to localhost (unsafe)" to continue. This is safe for local development.

You'll have a full VS Code editor with:
- GnuCash Python bindings pre-installed
- Python package installed with all dependencies
- Integrated terminal for running tests
- File editing with syntax highlighting and IntelliSense
- Pre-installed extensions:
  - Python (ms-python.python + Pylance) - Python language support
  - Ruff (charliermarsh.ruff) - Linting and formatting
  - Docker (ms-azuretools.vscode-docker) - Docker file support
  - GitLens (eamodio.gitlens) - Enhanced Git features
  - Markdown All in One - Markdown editing
  - Even Better TOML - pyproject.toml syntax
  - YAML - docker-compose.yml support

**Inside VS Code Server terminal, you have two options:**

**Option 1: Run tests directly (faster):**
```bash
pytest tests/               # Run all tests
pytest tests/unit/ -v       # Run unit tests with verbose output
```

**Option 2: Use the same scripts as on host (unified experience):**
```bash
./scripts/test.sh           # Works! Docker-in-Docker supported
./scripts/test.sh tests/unit/
```

**Use the CLI:**
```bash
gnucash-plaintext --help
gnucash-plaintext export myfile.gnucash output.txt
gnucash-plaintext import myfile.gnucash input.txt
```

**How it works:**
- **First run**: Builds `gnucash-dev-vscode:latest` image with code-server pre-installed (~2-3 minutes)
  - Generates self-signed SSL certificate (one-time, persisted in volume)
- **Subsequent runs**: Uses cached image, only installs Python package (~5 seconds)
  - Reuses existing SSL certificate (no regeneration)
- **Persistence**: VS Code settings/extensions + SSL certificate saved in Docker volume `vscode-data`
- **Live sync**: Project directory mounted at `/workspace`, changes reflected immediately
- **Security**: HTTPS with self-signed certificate (browser will show warning on first visit)

**Docker Compose: Down vs Stop**
- `docker compose down` - Removes containers, **keeps volumes** (VS Code settings + SSL cert preserved)
- `docker compose stop` - Stops containers without removing them
- `docker compose down -v` - Removes containers **AND volumes** (loses VS Code settings + SSL cert)

The `dev-stop` scripts use `down` which preserves your VS Code settings/extensions and SSL certificate.

**SSL Certificate Persistence**:
- Certificate is generated once on first startup
- Stored in `vscode-data` volume and reused on subsequent runs
- To regenerate certificate: `docker compose down -v && ./scripts/dev-start.sh`

To stop the environment, press Ctrl+C or use the `dev-stop` script.

### `dev-stop` - Stop Development Environment

Stop the running development environment.

```bash
./scripts/dev-stop.sh
```

### `build` - Build Docker Image

Build a Docker image for a specific distribution.

```bash
./scripts/build.sh              # Default (Debian 13, GnuCash 5.10)
./scripts/build.sh debian:12    # Debian 12, GnuCash 4.13
./scripts/build.sh debian:11    # Debian 11, GnuCash 4.4
./scripts/build.sh debian:10    # Debian 10, GnuCash 3.4
./scripts/build.sh ubuntu:26.04 # Ubuntu 26.04, GnuCash 5.14
./scripts/build.sh ubuntu:24.04 # Ubuntu 24.04, GnuCash 5.5
./scripts/build.sh ubuntu:22.04 # Ubuntu 22.04, GnuCash 4.8
./scripts/build.sh ubuntu:20.04 # Ubuntu 20.04, GnuCash 3.8
./scripts/build.sh fedora:41    # Fedora 41, GnuCash 5.13
./scripts/build.sh arch         # Arch Linux, GnuCash 5.15
./scripts/build.sh opensuse     # openSUSE Tumbleweed, GnuCash 5.16
```

### `shell` - Interactive Development Shell

Start an interactive bash shell in the container.

```bash
./scripts/shell.sh          # Use latest image
./scripts/shell.sh debian12 # Use Debian 12 image
./scripts/shell.sh ubuntu26 # Use Ubuntu 26.04 image
```

The script automatically builds the image if it doesn't exist.

### `test` - Run Tests

Run tests in the Docker container. Automatically installs the package with dependencies before running tests.

**Works everywhere!** Use from host machine OR inside VS Code Server (Docker-in-Docker supported).

```bash
./scripts/test.sh                    # Run all tests (default image)
./scripts/test.sh debian12           # Run with Debian 12
./scripts/test.sh latest tests/unit  # Run specific test directory
./scripts/test.sh ubuntu26 tests/integration/test_roundtrip.py  # Run specific test file
```

**Note:** The test scripts call `test-in-docker.sh` internally, which:
1. Installs the package with `pip install -e .` (includes `click` and other dependencies)
2. Runs `pytest` with the specified test path

**Inside VS Code Server?** Both methods work:
- `./scripts/test.sh` - Same as host (Docker-in-Docker supported)
- `pytest tests/` - Faster, skips Docker wrapper

**Memory cap:** each test container may use 1 GB. The whole suite peaks at 317–393 MB across the eleven builds, so a run that reaches the cap is keeping memory it should not; it stops with exit 137 and the script says so. Change the cap with `GNC_TEST_MEMORY`, which takes any `docker run --memory` value:

```bash
GNC_TEST_MEMORY=2g ./scripts/test.sh latest
```

### `profile-test-memory` - See Where the Tests' Memory Goes

Run the tests the way `test` does, with memory recorded before and after every test.

```bash
./scripts/profile-test-memory.sh                  # all tests, latest image
./scripts/profile-test-memory.sh debian10         # all tests on Debian 10
./scripts/profile-test-memory.sh latest tests/integration/test_payment_roundtrip.py
```

It prints the pytest result, the process's memory at the start, at the end and at most, how many GnuCash sessions were created, ended and destroyed, and the test files that added the most memory (`GNC_PROFILE_TOP` sets how many). One row per test is kept in `.memory-profile/<tag>.tsv`, beside the pytest output in `.memory-profile/<tag>.log`; `GNC_PROFILE_DIR` puts them elsewhere.

One pytest process runs the whole suite, so memory any test keeps is kept for the rest of the run. That is how a session ended without being destroyed, which keeps its whole book in memory, grew the suite to 1.7 GB (docs/issues/Q-041).

### `generate-multi-currency-examples` - Write the Example Ledgers

Write one example ledger per scenario in [docs/multi-currency.md](../docs/multi-currency.md), into `examples/multi-currency/`.

```bash
./scripts/generate-multi-currency-examples.sh
```

Each file is a book exported whole — accounts, transactions, prices, and the customers and invoices where the book has them — with the statement it produces commented at the end. It re-imports into an empty book and draws that same statement with no rates file, so a reader can check the doc rather than believe it:

```bash
gnucash-plaintext import --new /tmp/check.gnucash \
    examples/multi-currency/every_dollar_bought_and_sold_again.txt
gnucash-plaintext balance-sheet /tmp/check.gnucash --as-of 2026-12-31
```

These are **not** test fixtures and nothing asserts against them. They are checked in to be read: someone opens one, runs it, and sees for themselves the page the doc describes. They are built from `tests/fixtures/` and from what the tool prints, so this script is run when a scenario changes or when the page one of them prints changes — not as a routine step, and not to tidy the files. The statement is commented because a line at column 0 reads as a dated directive, and a file carrying a live one would not import — the script imports every file it writes and stops if one does not.

**Running it again on the same day changes nothing.** Where an example already exists, its own ledger is what the book is rebuilt from, so the guids stay as they were and only a figure that has genuinely moved shows in the diff. Rebuilding from the fixtures every time rewrote every file on every run — an export carries a guid for every account, transaction, split and price, and a fresh import mints new ones — which left no way to tell a real change from the noise.

**A run on a later day re-dates the `commodity` and `open` lines.** Those carry no date of their own, so `format_accounts_only` dates them from the book file's modification time, and the generator builds its books fresh each run. Every example therefore opens its accounts on the day it was generated, whatever year its transactions are in — so a rebuild tomorrow shows one changed date per account and commodity, and nothing else. That is the noise to expect and to ignore; a changed figure is not.

When a fixture or a figure really has changed, rebuild from `tests/fixtures/` instead:

```bash
REGENERATE=fixtures ./scripts/generate-multi-currency-examples.sh
```

That rewrites the guids, so expect every file to change. The `guid:` lines are load-bearing either way: a disposal refers to the purchase it draws on by guid in `cost_basis_split_guid:`, and a copy with the guids stripped imports at exit 0 while drawing a page that says 0.00 realized where the book says 100.00.

### `test-deployment` - Run the Built Wheel

Build the wheel, install it, and drive the installed `gnucash-plaintext` from a directory outside the source tree.

```bash
./scripts/test-deployment.sh            # latest
./scripts/test-deployment.sh debian10   # or any supported tag
```

The suite runs from an editable install, and `tests/` is a package, so pytest imports the source folder: a runtime data file the wheel leaves out passes all 4,200 tests and fails on the first machine that installs the tool. This script is the only place that fails on one, which is why it imports a book, exports it, prints an invoice as a PDF, **and** draws a balance sheet. The statements are drawn by a customized GnuCash report carried as package data, and drawing a page is what shows an installed wheel can find the report and load it — a file present in the wheel but unreachable from it passes every other check.

The page is drawn from `examples/multi-currency/some_of_the_dollars_kept_back.txt`, which states a realized gain and an unrealized one, both non-zero, and carries its own prices — so the page needs no rates file, and the figures it should print are commented at that file's own foot. Each gain is compared against them, and the page must also carry the working that shows how each was arrived at. `gnucash_balancing_amount` is left out of the comparison: it is what GnuCash needs to balance the sheet, not a gain.

CI runs this for each of the eleven builds, after that build's suite.

### `run` - Run Arbitrary Command

Run any command in the Docker container.

```bash
./scripts/run.sh python3 --version
./scripts/run.sh debian12 python3 -c "import gnucash; print('OK')"
./scripts/run.sh gnucash-plaintext --help
./scripts/run.sh ls -la
```

## Image Tags

The scripts use these image tags:

| Tag | Base Image | GnuCash Version |
|-----|------------|-----------------|
| `latest` | debian:13 | 5.10 |
| `debian12` | debian:12 | 4.13 |
| `debian11` | debian:11 | 4.4 |
| `debian10` | debian:10 | 3.4 |
| `ubuntu26` | ubuntu:26.04 | 5.14 |
| `ubuntu24` | ubuntu:24.04 | 5.5 |
| `ubuntu22` | ubuntu:22.04 | 4.8 |
| `ubuntu20` | ubuntu:20.04 | 3.8 |
| `fedora41` | fedora:41 | 5.13 |
| `arch` | archlinux | 5.15 |
| `opensuse` | opensuse/tumbleweed | 5.16 |

Each figure is what that image's own package database reports (`dpkg-query -W gnucash`, `rpm -q gnucash`, `pacman -Q gnucash`), read on 2026-08-11. `build.sh` prints it on every build, so a stale one is read as fact — three were a release or more out.

## Features

- **Browser-based IDE**: VS Code Server accessible at https://localhost:8765 with password `123456` (self-signed certificate)
- **Docker-in-Docker**: Use `./scripts/test.sh` from anywhere (host or VS Code Server) on Linux/macOS/WSL2
- **Auto-build**: Scripts automatically build images if they don't exist
- **Volume mounting**: Your project directory is mounted at `/workspace` in the container
- **Auto-install**: Dependencies are automatically installed on startup
- **Error handling**: Scripts check for common issues and provide helpful messages

## Docker Compose Development Environment

The project includes a `docker-compose.yml` that provides:
- VS Code Server running on port 8765
- Live code editing in your browser
- Integrated terminal for running tests
- Python package pre-installed with all dependencies
- GnuCash Python bindings ready to use

**Architecture:**
1. **Base Image**: `gnucash-dev:latest` (from Dockerfile - Debian 13 + GnuCash 5.10)
2. **Dev Image**: `gnucash-dev-vscode:latest` (from Dockerfile.dev - adds code-server + Docker CLI)
3. **Volumes**: Project files (live sync) + VS Code settings (persisted) + Docker socket (DinD support)
4. **Docker-in-Docker**:
   - Mount host's Docker socket
   - Install Docker CLI in container
   - Pass `HOST_PROJECT_PATH` environment variable (real host path)
   - Scripts auto-detect and use correct path for volume mounting

**Requirements:**
- Docker with Docker Compose V2 (uses `docker compose` command)
- **Windows users**: run from WSL2. The Docker socket path `/var/run/docker.sock` is Unix-only, and WSL2 also gives better Docker performance than Docker Desktop's named-pipe path.

## Examples

### Typical Development Workflow

**Option 1: VS Code Server in Browser (Recommended)**

```bash
./scripts/dev-start.sh

# Then open https://localhost:8765 (password: 123456)
# Browser will show security warning (self-signed certificate) - click "Advanced" → "Proceed"
# Edit code, run tests, all in your browser!
```

**Inside VS Code Server terminal:**

```bash
./scripts/test.sh tests/unit/      # Docker-in-Docker works!
./scripts/test.sh debian12          # Test on different distribution!
pytest tests/                       # Or run directly (faster)
```

**Option 2: Interactive Shell**

```bash
# Build development image
./scripts/build.sh

# Start interactive shell
./scripts/shell.sh

# Inside container:
cd /workspace
python3 -c "import gnucash; print('Ready!')"
```

### Testing on Multiple Distributions

```bash
# Test on each distribution individually
./scripts/test.sh latest
./scripts/test.sh debian12
./scripts/test.sh debian11
./scripts/test.sh ubuntu26
./scripts/test.sh ubuntu24
./scripts/test.sh ubuntu22
./scripts/test.sh ubuntu20

# Run specific tests on different distributions
./scripts/test.sh latest tests/unit
./scripts/test.sh debian12 tests/integration

# Or run the full matrix
./scripts/test-all-versions.sh           # Sequential
./scripts/test-all-versions-parallel.sh  # Parallel (~4x faster)
```

### Quick Commands

```bash
# Check GnuCash version
./scripts/run.sh dpkg -l gnucash

# Run Python script
./scripts/run.sh python3 my_script.py

# Run with specific distribution
./scripts/run.sh ubuntu26 python3 my_script.py
```

## Troubleshooting

### Image Not Found

If you see "Image not found", the script will automatically build it. You can also manually build:

```bash
./scripts/build.sh
```

### Permission Denied

Make sure scripts are executable:

```bash
chmod +x scripts/*.sh
```

### Docker Not Running

Ensure Docker Desktop is running before using these scripts.

### Port 8765 Already in Use (VS Code Server)

If port 8765 is in use, edit `docker-compose.yml` to use a different port:
```yaml
ports:
  - "9000:8080"  # Change 9000 to your preferred port (left side is host port)
```

Then access VS Code Server at http://localhost:9000

### Code Changes Not Reflected in VS Code Server

The project directory is mounted as a volume, so changes should appear immediately. If not:
1. Try refreshing the browser
2. Or restart: `./scripts/dev-stop.sh` then `./scripts/dev-start.sh`

### Docker Commands Fail Inside VS Code Server

If `docker` commands fail with permission errors inside VS Code Server:

```bash
# Check Docker socket permissions
ls -l /var/run/docker.sock

# Should show: srw-rw---- ... docker
# If not, on your HOST machine:
sudo chmod 666 /var/run/docker.sock

# Or add your user to docker group (better):
sudo usermod -aG docker $USER
# Then restart Docker Desktop
```

This is a Docker socket permission issue on the host. The container needs read/write access to `/var/run/docker.sock`.

**Windows users**: run all commands from WSL2. Docker-in-Docker won't work from PowerShell or CMD because Windows uses named pipes instead of Unix sockets.

```bash
# From WSL2:
cd /mnt/c/Users/YourName/path/to/gnucash-plaintext
./scripts/dev-start.sh
```

### Scripts Can't Find /workspace Inside VS Code Server

If you see errors like "cannot mount /workspace" when running `./scripts/test.sh` from inside VS Code Server, ensure the `HOST_PROJECT_PATH` environment variable is set:

```bash
# Inside VS Code Server terminal:
echo $HOST_PROJECT_PATH

# Should show your host project path like:
# /Users/jimmy/github.com/huangjimmy/gnucash-plaintext
```

If not set, restart the dev environment:
```bash
# From host:
./scripts/dev-stop.sh
./scripts/dev-start.sh
```

The `HOST_PROJECT_PATH` is automatically set by `docker-compose.yml` and allows scripts to mount the correct host path when launching sibling containers.
