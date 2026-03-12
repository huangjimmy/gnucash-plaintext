# Docker Helper Scripts

Cross-platform helper scripts for GnuCash development with Docker.

## Supported Platforms

- **Linux/macOS**: Shell scripts (`.sh`)
- **Windows PowerShell**: PowerShell scripts (`.ps1`)
- **Windows CMD**: Batch files (`.bat`)

**Using Podman instead of Docker?** Most scripts work with Podman out of the box. See [PODMAN.md](../PODMAN.md) for detailed compatibility notes and setup instructions.

## Available Scripts

### `dev-start` - Start Development Environment (Recommended)

Start a full development environment with VS Code Server in your browser. This is the easiest way to develop on Windows/Mac/Linux.

**Platform Support:**
- **Linux/macOS/WSL2**: Full Docker-in-Docker support
- **Windows PowerShell/CMD**: VS Code Server works, but use `pytest` directly (no DinD)

**Linux/macOS:**
```bash
./scripts/dev-start.sh
```

**Windows PowerShell:**
```powershell
.\scripts\dev-start.ps1
```

**Windows CMD:**
```cmd
scripts\dev-start.bat
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

**Linux/macOS:**
```bash
./scripts/dev-stop.sh
```

**Windows PowerShell:**
```powershell
.\scripts\dev-stop.ps1
```

**Windows CMD:**
```cmd
scripts\dev-stop.bat
```

### `build` - Build Docker Image

Build a Docker image for a specific distribution.

**Linux/macOS:**
```bash
./scripts/build.sh              # Default (Debian 13, GnuCash 5.10)
./scripts/build.sh debian:12    # Debian 12, GnuCash 4.13
./scripts/build.sh debian:11    # Debian 11, GnuCash 4.4
./scripts/build.sh ubuntu:20.04 # Ubuntu 20.04, GnuCash 3.8
```

**Windows PowerShell:**
```powershell
.\scripts\build.ps1 debian:13
.\scripts\build.ps1 ubuntu:20.04
```

**Windows CMD:**
```cmd
scripts\build.bat debian:13
scripts\build.bat ubuntu:20.04
```

### `shell` - Interactive Development Shell

Start an interactive bash shell in the container.

**Linux/macOS:**
```bash
./scripts/shell.sh          # Use latest image
./scripts/shell.sh debian12 # Use Debian 12 image
./scripts/shell.sh ubuntu20 # Use Ubuntu 20.04 image
```

**Windows PowerShell:**
```powershell
.\scripts\shell.ps1
.\scripts\shell.ps1 debian12
```

**Windows CMD:**
```cmd
scripts\shell.bat
scripts\shell.bat debian12
```

The script automatically builds the image if it doesn't exist.

### `test` - Run Tests

Run tests in the Docker container. Automatically installs the package with dependencies before running tests.

**Works everywhere!** Use from host machine OR inside VS Code Server (Docker-in-Docker supported).

**Linux/macOS:**
```bash
./scripts/test.sh                    # Run all tests (default image)
./scripts/test.sh debian12           # Run with Debian 12
./scripts/test.sh latest tests/unit  # Run specific test directory
./scripts/test.sh ubuntu20 tests/integration/test_roundtrip.py  # Run specific test file
```

**Windows PowerShell:**
```powershell
.\scripts\test.ps1
.\scripts\test.ps1 debian12
.\scripts\test.ps1 latest tests/unit
```

**Windows CMD:**
```cmd
scripts\test.bat
scripts\test.bat debian12
scripts\test.bat latest tests/unit
```

**Note:** The test scripts call `test-in-docker.sh` internally, which:
1. Installs the package with `pip install -e .` (includes `click` and other dependencies)
2. Runs `pytest` with the specified test path

**Inside VS Code Server?** Both methods work:
- `./scripts/test.sh` - Same as host (Docker-in-Docker supported)
- `pytest tests/` - Faster, skips Docker wrapper

### `run` - Run Arbitrary Command

Run any command in the Docker container.

**Linux/macOS:**
```bash
./scripts/run.sh python3 --version
./scripts/run.sh debian12 python3 -c "import gnucash; print('OK')"
./scripts/run.sh gnucash-plaintext --help
./scripts/run.sh ls -la
```

**Windows PowerShell:**
```powershell
.\scripts\run.ps1 python3 --version
.\scripts\run.ps1 debian12 python3 script.py
```

**Windows CMD:**
```cmd
scripts\run.bat python3 --version
scripts\run.bat debian12 python3 script.py
```

## Image Tags

The scripts use these image tags:

| Tag | Base Image | GnuCash Version |
|-----|------------|-----------------|
| `latest` | debian:13 | 5.10 |
| `debian12` | debian:12 | 4.13 |
| `debian11` | debian:11 | 4.4 |
| `ubuntu20` | ubuntu:20.04 | 3.8 |

## Features

- **Browser-based IDE**: VS Code Server accessible at https://localhost:8765 with password `123456` (self-signed certificate)
- **Docker-in-Docker**: Use `./scripts/test.sh` from anywhere (host or VS Code Server) - Linux/macOS/WSL2
- **Auto-build**: Scripts automatically build images if they don't exist
- **Cross-platform**: Same functionality on Linux, macOS, and Windows
  - Full DinD support: Linux, macOS, WSL2
  - Basic support: Windows PowerShell/CMD (use `pytest` directly in VS Code Server)
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
- **Windows users**: Must run from WSL2 for Docker-in-Docker support
  - Docker socket path `/var/run/docker.sock` is Unix-only
  - WSL2 is recommended anyway for better Docker performance on Windows
  - Alternative: Run without DinD (use `pytest` directly inside VS Code Server)

## Examples

### Typical Development Workflow

**Option 1: VS Code Server in Browser (Recommended)**

**All Platforms:**
```bash
# Linux/macOS
./scripts/dev-start.sh

# Windows (WSL2) - Recommended
./scripts/dev-start.sh

# Windows (PowerShell) - DinD may not work, use pytest directly
.\scripts\dev-start.ps1

# Windows (CMD) - DinD may not work, use pytest directly
scripts\dev-start.bat

# Then open https://localhost:8765 (password: 123456)
# Browser will show security warning (self-signed certificate) - click "Advanced" → "Proceed"
# Edit code, run tests, all in your browser!
```

**Inside VS Code Server terminal:**

**Linux/macOS/WSL2:**
```bash
./scripts/test.sh tests/unit/      # Docker-in-Docker works!
./scripts/test.sh debian12          # Test on different distribution!
pytest tests/                       # Or run directly (faster)
```

**Windows (PowerShell/CMD):**
```bash
# Docker-in-Docker doesn't work (Unix socket issue)
# Use pytest directly instead:
pytest tests/
pytest tests/unit/ -v
```

**Option 2: Interactive Shell**

**Linux/macOS:**
```bash
# Build development image
./scripts/build.sh

# Start interactive shell
./scripts/shell.sh

# Inside container:
cd /workspace
python3 -c "import gnucash; print('Ready!')"
```

**Windows PowerShell:**
```powershell
# Build development image
.\scripts\build.ps1

# Start interactive shell
.\scripts\shell.ps1
```

### Testing on Multiple Distributions

**Linux/macOS:**
```bash
# Test on all distributions
./scripts/test.sh latest
./scripts/test.sh debian12
./scripts/test.sh debian11
./scripts/test.sh ubuntu20

# Run specific tests on different distributions
./scripts/test.sh latest tests/unit
./scripts/test.sh debian12 tests/integration
```

**Windows CMD:**
```cmd
scripts\test.bat latest
scripts\test.bat debian12
scripts\test.bat debian11
scripts\test.bat ubuntu20
```

### Quick Commands

**Linux/macOS:**
```bash
# Check GnuCash version
./scripts/run.sh dpkg -l gnucash

# Run Python script
./scripts/run.sh python3 my_script.py

# Run with specific distribution
./scripts/run.sh ubuntu20 python3 my_script.py
```

## Troubleshooting

### Image Not Found

If you see "Image not found", the script will automatically build it. You can also manually build:

```bash
# Linux/macOS
./scripts/build.sh

# Windows PowerShell
.\scripts\build.ps1

# Windows CMD
scripts\build.bat
```

### Permission Denied (Linux/macOS)

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

**On Linux/macOS/WSL2:**

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

**On Windows (PowerShell/CMD):**

Docker-in-Docker won't work because Windows uses named pipes instead of Unix sockets. Two options:

1. **Use WSL2 (Recommended)**: Run all commands from WSL2 terminal
   ```bash
   # From WSL2:
   cd /mnt/c/Users/YourName/path/to/gnucash-plaintext
   ./scripts/dev-start.sh
   ```

2. **Skip Docker-in-Docker**: Inside VS Code Server, use `pytest` directly instead of `./scripts/test.sh`
   ```bash
   # Inside VS Code Server on Windows:
   pytest tests/
   pytest tests/unit/ -v
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
