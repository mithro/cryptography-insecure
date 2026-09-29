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

# Source packages, from this suite only: the source must match the suite's
# own Rust and pyo3 packages, which is why nothing is pinned here.
#
# Enable deb-src in the image's existing stanza rather than adding a line of
# our own: that inherits its Signed-By, and the keyring's name differs
# between suites (.gpg on bookworm, .pgp from trixie on). Naming the wrong
# one makes apt refuse every source: "Conflicting values set for option
# Signed-By".
sources=/etc/apt/sources.list.d/debian.sources
if [ -f "$sources" ]; then
    sed -i 's/^Types: deb$/Types: deb deb-src/' "$sources"
    grep -q '^Types: deb deb-src$' "$sources"
else
    printf 'deb-src http://deb.debian.org/debian %s main\n' "$SUITE" \
        > /etc/apt/sources.list.d/insecure-src.list
fi
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

deb=$(ls ../python3-cryptography-insecure_*.deb | head -1)

# Nothing may ship under the system cryptography's names. The compiled
# bindings are the trap here: their install path comes from a module name
# in src/_cffi_src, and getting it wrong drops a .so straight on top of
# python3-cryptography's. dpkg would refuse the install, but only on a
# machine that had both -- so check it at build time.
if dpkg-deb -c "$deb" | awk '{print $6}' \
        | grep -E '/cryptography/|/cryptography-[0-9]'; then
    echo "::error::package ships files under the system cryptography's name"
    exit 1
fi

mkdir -p "$OUT"
cp "$deb" "$OUT/"
ls -lh "$OUT"
