ARG BASE_IMAGE=debian:13
# Supported distributions (verified 2026-05-09):
# ┌──────────────────┬─────────────────┬────────────────────────┐
# │ Distribution     │ GnuCash Version │ Status                 │
# ├──────────────────┼─────────────────┼────────────────────────┤
# │ debian:13        │ 5.10            │ ✅ Latest (default)    │
# │ debian:12        │ 4.13            │ ✅ Stable              │
# │ debian:11        │ 4.4             │ ✅ LTS                 │
# │ ubuntu:26.04     │ 5.14            │ ✅ LTS                 │
# │ ubuntu:24.04     │ 5.5             │ ✅ LTS                 │
# │ ubuntu:22.04     │ 4.8             │ ✅ LTS                 │
# │ ubuntu:20.04     │ 3.8             │ ✅ Minimum (GnuCash 3) │
# └──────────────────┴─────────────────┴────────────────────────┘
#
# Usage:
#   docker build -t gnucash-dev .                                     # Debian 13 (GnuCash 5.10)
#   docker build --build-arg BASE_IMAGE=debian:12 -t gnucash-dev .    # Debian 12 (GnuCash 4.13)
#   docker build --build-arg BASE_IMAGE=debian:11 -t gnucash-dev .    # Debian 11 (GnuCash 4.4)
#   docker build --build-arg BASE_IMAGE=ubuntu:26.04 -t gnucash-dev . # Ubuntu 26.04 (GnuCash 5.14)
#   docker build --build-arg BASE_IMAGE=ubuntu:24.04 -t gnucash-dev . # Ubuntu 24.04 (GnuCash 5.5)
#   docker build --build-arg BASE_IMAGE=ubuntu:22.04 -t gnucash-dev . # Ubuntu 22.04 (GnuCash 4.8)
#   docker build --build-arg BASE_IMAGE=ubuntu:20.04 -t gnucash-dev . # Ubuntu 20.04 (GnuCash 3.8)

FROM ${BASE_IMAGE}

# Avoid interactive prompts during apt-get install (needed for Ubuntu)
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && \
    apt-get -y install gnucash python3-gnucash git python3-pip python3-venv \
        libxml2-dev libxslt-dev python3-lxml weasyprint \
        # `python3-gi` for the bindings, `xvfb` because WebKit wants a
        # display and a machine printing from a script has none, and `xauth`
        # so that display takes a cookie rather than any local connection.
        python3-gi gir1.2-gtk-3.0 xvfb xauth && \
    # A printed page is laid out by WebKit, the engine GnuCash's own
    # Print Invoice button uses. Its library is here already — GnuCash
    # depends on it — but not its typelib, and `import gi` needs both. The
    # 4.1 API is what a GnuCash 5 build carries and 4.0 what a 4.x one does,
    # so whichever this base has is the one installed, and neither being
    # present is a build error rather than a runtime surprise.
    (apt-get -y install gir1.2-webkit2-4.1 || \
     apt-get -y install gir1.2-webkit2-4.0) && \
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