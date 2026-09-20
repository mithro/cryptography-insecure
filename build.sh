#!/bin/sh
# Build python3-cryptography-insecure for one Debian suite.
#
# Run inside a debian:<suite> container with the repository at /w:
#   docker run --rm -v "$PWD:/w" -w /w debian:trixie sh \
#       packaging/cryptography-insecure/build.sh
#
# The source is that suite's own python-cryptography, fetched at build time
# and renamed by fork.py, so this tracks Debian rather than pinning a
# vendored copy. What it buys is independence: paramiko_insecure keeps the
# primitives it needs (DSA today, 3DES tomorrow) whatever the system
# cryptography drops, without touching the system cryptography at all.
set -eux

export DEBIAN_FRONTEND=noninteractive
OUT=${OUT:-/w/built-debs}
. /etc/os-release
SUITE=${VERSION_CODENAME:?no VERSION_CODENAME in /etc/os-release}

apt-get update
apt-get install -y --no-install-recommends \
    build-essential ca-certificates devscripts dpkg-dev equivs python3

# deb-src for this suite only: the source must match the suite's Rust and
# pyo3 packages, which is why nothing is pinned here.
printf 'deb-src http://deb.debian.org/debian %s main\n' "$SUITE" \
    > /etc/apt/sources.list.d/insecure-src.list
apt-get update

rm -rf /tmp/crypto && mkdir -p /tmp/crypto && cd /tmp/crypto
apt-get source python-cryptography
cd python-cryptography-*

version=$(dpkg-parsechangelog -S Version)
echo "--- forking Debian python-cryptography $version ---"

python3 /w/packaging/cryptography-insecure/fork.py .

DEBEMAIL=me@mith.ro DEBFULLNAME="Tim 'mithro' Ansell" dch -b \
    --package cryptography-insecure \
    --newversion "${version}+insecure1" \
    --distribution unstable --force-distribution \
    "Rename to cryptography_insecure for python3-paramiko-insecure."

mk-build-deps --install --remove \
    --tool 'apt-get -y --no-install-recommends' debian/control

# nocheck: the upstream test suite tests cryptography, which Debian already
# tests; what matters here is that the rename produced a working module, and
# that is what the interop tests check.
DEB_BUILD_OPTIONS=nocheck DEB_BUILD_PROFILES=nocheck \
    dpkg-buildpackage -us -uc -b

mkdir -p "$OUT"
cp ../python3-cryptography-insecure_*.deb "$OUT/"
ls -lh "$OUT"
