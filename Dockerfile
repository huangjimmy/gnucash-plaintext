ARG BASE_IMAGE=debian:13
# Supported distributions (verified 2026-05-09):
# ┌──────────────────┬─────────────────┬────────────────────────┐
# │ Distribution     │ GnuCash Version │ Status                 │
# ├──────────────────┼─────────────────┼────────────────────────┤
# │ debian:13        │ 5.10            │ ✅ Latest (default)    │
# │ debian:12        │ 4.13            │ ✅ Stable              │
# │ debian:11        │ 4.4             │ ✅ past EOL, snapshot  │
# │ debian:10        │ 3.4             │ ✅ Minimum (Python 3.7)│
# │ ubuntu:26.04     │ 5.14            │ ✅ LTS                 │
# │ ubuntu:24.04     │ 5.5             │ ✅ LTS                 │
# │ ubuntu:22.04     │ 4.8             │ ✅ LTS                 │
# │ ubuntu:20.04     │ 3.8             │ ✅ LTS                 │
# └──────────────────┴─────────────────┴────────────────────────┘
#
# Usage:
#   docker build -t gnucash-dev .                                     # Debian 13 (GnuCash 5.10)
#   docker build --build-arg BASE_IMAGE=debian:12 -t gnucash-dev .    # Debian 12 (GnuCash 4.13)
#   docker build --build-arg BASE_IMAGE=debian:11 -t gnucash-dev .    # Debian 11 (GnuCash 4.4)
#   docker build --build-arg BASE_IMAGE=debian:10 -t gnucash-dev .    # Debian 10 (GnuCash 3.4)
#   docker build --build-arg BASE_IMAGE=ubuntu:26.04 -t gnucash-dev . # Ubuntu 26.04 (GnuCash 5.14)
#   docker build --build-arg BASE_IMAGE=ubuntu:24.04 -t gnucash-dev . # Ubuntu 24.04 (GnuCash 5.5)
#   docker build --build-arg BASE_IMAGE=ubuntu:22.04 -t gnucash-dev . # Ubuntu 22.04 (GnuCash 4.8)
#   docker build --build-arg BASE_IMAGE=ubuntu:20.04 -t gnucash-dev . # Ubuntu 20.04 (GnuCash 3.8)

FROM ${BASE_IMAGE}

# Avoid interactive prompts during apt-get install (needed for Ubuntu)
ENV DEBIAN_FRONTEND=noninteractive

# A Debian release past its end of life is served from somewhere else, and by
# the release's own codename rather than by anything the caller passes.
#
# bullseye is the sharp case, because the mirror lies. `deb.debian.org` still
# publishes its security index, valid — measured 2026-09-05, `Valid-Until: Mon,
# 07 Sep 2026` — while it deletes the package files that index lists, so apt
# reads the list, asks for a file and is given a 404. A date check would not
# have caught that, and neither would a suite label. snapshot.debian.org holds
# the archive as it stood at a moment in time, and 20260901T000000Z is just
# after bullseye last changed (`Date: Mon, 31 Aug 2026 21:13:04 UTC`), so it
# still carries the security versions the base image is built from. Pinning to
# a snapshot also stops the image drifting, which for a test container is the
# behaviour wanted anyway.
#
# Both archives serve a Release file that is expired by design, hence
# Check-Valid-Until. Measured: 745 packages in about 15 seconds, so this is not
# the slow path its reputation suggests.
#
# buster is the plainer case: it left `deb.debian.org` altogether and
# `archive.debian.org` carries it whole, security suite included, under the
# older `buster/updates` name rather than `buster-security`.
ARG SNAPSHOT=20260901T000000Z
RUN . /etc/os-release; \
    case "${VERSION_CODENAME:-}" in \
      bullseye) \
        printf 'deb http://snapshot.debian.org/archive/debian/%s bullseye main\ndeb http://snapshot.debian.org/archive/debian/%s bullseye-updates main\ndeb http://snapshot.debian.org/archive/debian-security/%s bullseye-security main\n' \
            "$SNAPSHOT" "$SNAPSHOT" "$SNAPSHOT" > /etc/apt/sources.list && \
        printf 'Acquire::Check-Valid-Until "false";\nAcquire::Retries "5";\n' \
            > /etc/apt/apt.conf.d/99past-end-of-life \
        ;; \
      buster) \
        printf 'deb http://archive.debian.org/debian buster main\ndeb http://archive.debian.org/debian buster-updates main\ndeb http://archive.debian.org/debian-security buster/updates main\n' \
            > /etc/apt/sources.list && \
        printf 'Acquire::Check-Valid-Until "false";\nAcquire::Retries "5";\n' \
            > /etc/apt/apt.conf.d/99past-end-of-life \
        ;; \
    esac

# `python3-gi` is for the bindings, `xvfb` because WebKit wants a display and
# a machine printing from a script has none, and `xauth` so that display takes
# a cookie rather than any local connection.
#
# Two package names differ on Debian 10 and nowhere else. `libxslt-dev` is
# `libxslt1-dev` there, and there is no `weasyprint` package at all — nothing
# matching "weasy" is in buster's index — so the pip install further down is
# its only source and the libraries it links are installed explicitly instead.
RUN . /etc/os-release; \
    XSLT_DEV=libxslt-dev; \
    PAGE_ENGINE=weasyprint; \
    case "${VERSION_CODENAME:-}" in \
      buster) \
        XSLT_DEV=libxslt1-dev; \
        PAGE_ENGINE="libcairo2 libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf2.0-0 libffi-dev shared-mime-info" \
        ;; \
    esac; \
    apt-get update && \
    apt-get -y install gnucash python3-gnucash git python3-pip python3-venv \
        libxml2-dev python3-lxml $XSLT_DEV $PAGE_ENGINE \
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
# The markers are the same ones `pyproject.toml` carries, and they matter on
# Debian 10: unpinned, pip picks a WeasyPrint that segfaults on import against
# that release's Pango, and a pytest and pip that need Python 3.8.
RUN python3 -m pip install pytest pytest-cov \
        "weasyprint; python_version>='3.8'" \
        "weasyprint<53; python_version<'3.8'" \
        --break-system-packages 2>/dev/null || \
    (python3 -m pip install --upgrade "pip; python_version>='3.8'" "pip<24; python_version<'3.8'" && \
     python3 -m pip install "pytest; python_version>='3.8'" "pytest<7.5; python_version<'3.8'" \
        "pytest-cov; python_version>='3.8'" "pytest-cov<5; python_version<'3.8'" \
        "weasyprint; python_version>='3.8'" \
        "weasyprint<53; python_version<'3.8'")

CMD ["bash"]