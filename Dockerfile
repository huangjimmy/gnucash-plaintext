ARG BASE_IMAGE=debian:13
# Supported distributions (verified 2026-02-14):
# ┌──────────────────┬─────────────────┬────────────────────────┐
# │ Distribution     │ GnuCash Version │ Status                 │
# ├──────────────────┼─────────────────┼────────────────────────┤
# │ debian:13        │ 5.10            │ ✅ Latest (default)    │
# │ debian:12        │ 4.13            │ ✅ Stable              │
# │ debian:11        │ 4.4             │ ✅ LTS                 │
# │ ubuntu:24.04     │ 4.9             │ ✅ LTS                 │
# │ ubuntu:22.04     │ 4.8             │ ✅ LTS                 │
# │ ubuntu:20.04     │ 3.8             │ ✅ Minimum (GnuCash 3) │
# └──────────────────┴─────────────────┴────────────────────────┘
#
# Usage:
#   docker build -t gnucash-dev .                                    # Debian 13 (GnuCash 5.10)
#   docker build --build-arg BASE_IMAGE=debian:12 -t gnucash-dev .   # Debian 12 (GnuCash 4.13)
#   docker build --build-arg BASE_IMAGE=debian:11 -t gnucash-dev .   # Debian 11 (GnuCash 4.4)
#   docker build --build-arg BASE_IMAGE=ubuntu:24.04 -t gnucash-dev . # Ubuntu 24.04 (GnuCash 4.9)
#   docker build --build-arg BASE_IMAGE=ubuntu:22.04 -t gnucash-dev . # Ubuntu 22.04 (GnuCash 4.8)
#   docker build --build-arg BASE_IMAGE=ubuntu:20.04 -t gnucash-dev . # Ubuntu 20.04 (GnuCash 3.8)

FROM ${BASE_IMAGE}

# Avoid interactive prompts during apt-get install (needed for Ubuntu)
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && \
    apt-get -y install gnucash python3-gnucash git python3-pip python3-venv \
        libxml2-dev libxslt-dev python3-lxml weasyprint && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /workspace

# Install dev dependencies at build time
# The package itself will be installed at runtime when workspace is mounted
# Try with --break-system-packages first (Debian 12+, Ubuntu 22+), fall back to upgrade pip (Ubuntu 20)
RUN python3 -m pip install pytest pytest-cov weasyprint --break-system-packages 2>/dev/null || \
    (python3 -m pip install --upgrade pip && \
     python3 -m pip install pytest pytest-cov weasyprint --break-system-packages)

CMD ["bash"]