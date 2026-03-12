# Podman Compatibility Guide

This document explains how to use gnucash-plaintext with Podman instead of Docker.

## Compatibility Status

### ✅ What Works with Podman

- **VS Code Server**: Browser-based IDE at https://localhost:8765
- **Building images**: `podman build` works identically
- **Running containers**: Basic container operations
- **Volume mounts**: Project directory and named volumes
- **Port mapping**: Access services from host
- **Direct testing**: `pytest tests/` inside container

### ⚠️ What Requires Setup

- **Docker-in-Docker**: Requires Podman socket setup (see below)
- **Helper scripts from inside container**: `./scripts/test.sh` needs socket

### ❌ What Doesn't Work

- Rootless Podman cannot access `/var/run/docker.sock` (requires rootful Podman or socket setup)

## Using Podman with gnucash-plaintext

### Option 1: Basic Usage (No Docker-in-Docker)

**Recommended for most users**. VS Code Server works, just use `pytest` directly:

```bash
# Start development environment
podman-compose up --build

# Or with podman compose (Podman 4.0+)
podman compose up --build

# Inside VS Code Server terminal (https://localhost:8765):
pytest tests/              # Run tests directly
pytest tests/unit/ -v      # Run specific tests

# ❌ Don't use ./scripts/test.sh (needs Docker-in-Docker)
```

### Option 2: Enable Docker-in-Docker (Advanced)

If you need Docker-in-Docker (to use `./scripts/test.sh` from inside container):

#### Step 1: Enable Podman Socket

**On Linux (rootful Podman):**
```bash
# Enable Podman socket as root
sudo systemctl enable --now podman.socket

# Verify socket exists
ls -la /var/run/docker.sock
# or
ls -la /run/podman/podman.sock
```

**On Linux (rootless Podman):**
```bash
# Enable user Podman socket
systemctl --user enable --now podman.socket

# Socket location (rootless)
ls -la $XDG_RUNTIME_DIR/podman/podman.sock
# Usually: /run/user/1000/podman/podman.sock
```

#### Step 2: Modify docker-compose.yml

Edit `docker-compose.yml` and change the socket mount:

**For rootful Podman:**
```yaml
volumes:
  - .:/workspace
  - vscode-data:/root/.local/share/code-server
  # Replace Docker socket with Podman socket
  - /run/podman/podman.sock:/var/run/docker.sock  # Changed
```

**For rootless Podman:**
```yaml
volumes:
  - .:/workspace
  - vscode-data:/root/.local/share/code-server
  # Use rootless Podman socket (replace 1000 with your UID)
  - /run/user/1000/podman/podman.sock:/var/run/docker.sock
```

#### Step 3: Use Docker CLI inside container

```bash
# Start with modified docker-compose.yml
podman-compose up --build

# Inside VS Code Server, Docker CLI now works:
./scripts/test.sh           # Works!
./scripts/test.sh debian12  # Works!
docker ps                   # Shows containers via Podman
```

## Installation

### Install Podman

**macOS:**
```bash
brew install podman
podman machine init
podman machine start
```

**Linux (Debian/Ubuntu):**
```bash
sudo apt-get update
sudo apt-get install -y podman
```

**Linux (Fedora/RHEL):**
```bash
sudo dnf install -y podman
```

### Install podman-compose

**Option 1: pip (recommended):**
```bash
pip install podman-compose
```

**Option 2: Package manager:**
```bash
# Debian/Ubuntu
sudo apt-get install podman-compose

# Fedora
sudo dnf install podman-compose
```

**Option 3: Use built-in compose (Podman 4.0+):**
```bash
podman compose version
```

## Commands Reference

### Docker → Podman Command Mapping

| Docker | Podman | Notes |
|--------|--------|-------|
| `docker build -t name .` | `podman build -t name .` | Identical |
| `docker run -it name` | `podman run -it name` | Identical |
| `docker ps` | `podman ps` | Identical |
| `docker-compose up` | `podman-compose up` | Requires podman-compose |
| `docker compose up` | `podman compose up` | Podman 4.0+ |

### Helper Scripts with Podman

**From host machine (works as-is):**
```bash
# Replace 'docker' with 'podman' in scripts, or:
alias docker=podman

# Then use scripts normally
./scripts/test.sh
./scripts/shell.sh
./scripts/run.sh python3 --version
```

**From inside VS Code Server:**
- **With socket setup**: `./scripts/test.sh` works
- **Without socket**: Use `pytest tests/` directly

## Troubleshooting

### Issue: "docker.sock: No such file or directory"

**Cause**: Podman socket not enabled.

**Solutions:**
1. **Option A**: Enable Podman socket (see "Enable Docker-in-Docker" above)
2. **Option B**: Remove socket mount from docker-compose.yml and use `pytest` directly
3. **Option C**: Use Docker instead of Podman for full DinD support

### Issue: "permission denied" accessing socket

**Cause**: User doesn't have permission to access Podman socket.

**Solution:**
```bash
# For rootful Podman socket
sudo chmod 666 /run/podman/podman.sock

# Or add user to podman group (better)
sudo usermod -aG podman $USER
newgrp podman
```

### Issue: podman-compose not found

**Solution:**
```bash
# Install via pip
pip install podman-compose

# Or use built-in compose (Podman 4.0+)
podman compose --help
```

## Recommended Setup

### For Simple Development (No DinD needed)

✅ **Best for most users**. Works out of the box:

```bash
# Start VS Code Server
podman-compose up --build

# Open https://localhost:8765
# Inside terminal: pytest tests/
```

**Pros:**
- No socket setup needed
- Works with rootless Podman
- Simpler, more secure

**Cons:**
- Can't use `./scripts/test.sh` from inside container
- Must use `pytest` directly

### For Advanced Development (Full DinD)

⚙️ **For users who need `./scripts/test.sh` everywhere**:

1. Enable Podman socket
2. Modify docker-compose.yml socket mount
3. Restart containers

**Pros:**
- Same commands work everywhere (host and container)
- Can test multiple distributions easily

**Cons:**
- Requires socket setup
- May need rootful Podman

## Platform-Specific Notes

### macOS

- Podman runs in a VM (podman machine)
- Socket automatically available in VM
- May need to modify socket path in docker-compose.yml

### Linux

- Rootless Podman is default and preferred
- Socket location: `/run/user/$UID/podman/podman.sock`
- Rootful Podman socket: `/run/podman/podman.sock`

### Windows (WSL2)

- Install Podman in WSL2
- Follow Linux instructions
- Rootless Podman works well in WSL2

## Differences from Docker

### Rootless by Default

Podman runs rootless containers by default (more secure):
- Container user is mapped to host user
- No root daemon required
- Better security isolation

### No Daemon

Podman is daemonless:
- No background service to start
- Lower resource usage
- Socket is optional (only needed for compatibility)

### Drop-in Replacement

For most use cases, Podman is a drop-in replacement for Docker:
- Same CLI syntax
- Same Dockerfile format
- Compatible with docker-compose files

## Summary

**Quick Start (Recommended):**
```bash
# Install
brew install podman  # macOS
# or: sudo apt-get install podman  # Linux

# Start VS Code Server
podman-compose up --build

# Open https://localhost:8765
# Use pytest directly inside terminal
```

**With Docker-in-Docker:**
1. Enable Podman socket
2. Modify docker-compose.yml socket path
3. Restart containers
4. Now `./scripts/test.sh` works everywhere

For most development, **Option 1 (no DinD)** is sufficient and simpler!
