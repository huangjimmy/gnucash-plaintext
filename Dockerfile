ARG BASE_IMAGE=debian:13
# Supported distributions (verified 2026-05-09):
# ┌──────────────────┬─────────────────┬────────────────────────┐
# │ Distribution     │ GnuCash Version │ Status                 │
# ├──────────────────┼─────────────────┼────────────────────────┤
# │ debian:13        │ 5.10            │ ✅ Latest (default)    │
# │ debian:12        │ 4.13            │ ✅ Stable              │
# │ debian:11        │ 4.4             │ ✅ past EOL, archive   │
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
# Both are taken from `archive.debian.org`, which carries each release whole,
# security suite included.
#
# bullseye is the sharp case, because `deb.debian.org` lies about it. It still
# published its security index, valid — measured 2026-09-05, `Valid-Until: Mon,
# 07 Sep 2026` — while it deleted the package files that index lists, so apt
# read the list, asked for a file and got a 404. A date check would not have
# caught that, and neither would a suite label. bullseye was then taken from
# snapshot.debian.org at 20260901T000000Z, until that service failed GitHub's
# runners: on 2026-11-06 two builds in a row spent about 1389 seconds getting
# `503 No healthy backends`, `503 first byte timeout` and `504 Gateway Timeout`
# for every package, while the same files downloaded at once from elsewhere.
# `archive.debian.org` carries bullseye by then, its security index dated
# 2026-09-12, and an image built from it holds GnuCash 1:4.4-1, as before.
#
# buster left `deb.debian.org` earlier, and its security suite is under the
# older `buster/updates` name rather than `buster-security`.
#
# The archive serves Release files that are expired by design, hence
# Check-Valid-Until.
RUN . /etc/os-release; \
    case "${VERSION_CODENAME:-}" in \
      bullseye) \
        printf 'deb http://archive.debian.org/debian bullseye main\ndeb http://archive.debian.org/debian bullseye-updates main\ndeb http://archive.debian.org/debian-security bullseye-security main\n' \
            > /etc/apt/sources.list && \
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
# One package name differs on Debian 10 and nowhere else: `libxslt-dev` is
# `libxslt1-dev` there.
#
# `tzdata` is named because the suite runs under zones by name (Toronto,
# Kiritimati, Pago Pago), and without the zone database a `TZ` it cannot find
# falls back to UTC without a word. Ubuntu 22.04's base image does not carry
# it, and it had arrived there only as a dependency of the `weasyprint`
# package, so when that went, three price tests read two Toronto days as one
# UTC day.
RUN . /etc/os-release; \
    XSLT_DEV=libxslt-dev; \
    case "${VERSION_CODENAME:-}" in \
      buster) \
        XSLT_DEV=libxslt1-dev \
        ;; \
    esac; \
    apt-get update && \
    apt-get -y install gnucash python3-gnucash git python3-pip python3-venv \
        libxml2-dev python3-lxml $XSLT_DEV tzdata \
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
# The markers matter on Debian 10: unpinned, pip picks a pytest and a pip that
# need Python 3.8.
RUN python3 -m pip install pytest pytest-cov \
        --break-system-packages 2>/dev/null || \
    (python3 -m pip install --upgrade "pip; python_version>='3.8'" "pip<24; python_version<'3.8'" && \
     python3 -m pip install "pytest; python_version>='3.8'" "pytest<7.5; python_version<'3.8'" \
        "pytest-cov; python_version>='3.8'" "pytest-cov<5; python_version<'3.8'")

CMD ["bash"]