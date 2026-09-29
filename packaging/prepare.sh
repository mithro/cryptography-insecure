#!/bin/sh
# Fetch the pinned python-cryptography source of one suite and rename it to
# cryptography-insecure, ready for the shared build-deb (mithro/apt-repo-action).
#
# Run inside a debian:<codename> container with the repository at /w:
#   docker run --rm -v "$PWD:/w" -w /w debian:trixie \
#       sh packaging/prepare.sh trixie /w/src
#
# The source is exactly the one packaging/pins.toml pins for the suite (a
# raspbian-<codename> suite builds its codename's), fetched from the suite's
# own archive: it must match the suite's Rust and pyo3 packages. Moving a pin
# is a commit, so the same commit always builds the same source.
set -eux

SUITE=${1:?usage: prepare.sh <suite> <out-dir>}
OUT=${2:?usage: prepare.sh <suite> <out-dir>}
export DEBIAN_FRONTEND=noninteractive
# shellcheck source=/dev/null
. /etc/os-release
CODENAME=${SUITE#raspbian-}
# sid's image reports the testing codename, so only check a released suite.
if [ "$CODENAME" != sid ] && [ "${VERSION_CODENAME:-}" != "$CODENAME" ]; then
    echo "::error::prepare.sh $SUITE must run in debian:$CODENAME, not ${VERSION_CODENAME:-?}"
    exit 1
fi

apt-get update
apt-get install -y --no-install-recommends ca-certificates dpkg-dev python3

VERSION=$(python3 /w/packaging/pins.py version "$SUITE")
SHA256=$(python3 /w/packaging/pins.py dsc-sha256 "$SUITE")

# Source packages, from this suite only.
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
    printf 'deb-src http://deb.debian.org/debian %s main\n' "$CODENAME" \
        > /etc/apt/sources.list.d/insecure-src.list
fi
apt-get update

work=$(mktemp -d)
cd "$work"
# apt checks each file against the signed Sources index; the pin then checks
# this is the source the commit names.
apt-get source --download-only "python-cryptography=$VERSION"
dsc="python-cryptography_${VERSION#*:}.dsc"
echo "$SHA256  $dsc" | sha256sum -c -
dpkg-source -x "$dsc" tree

echo "--- forking Debian python-cryptography $VERSION ---"
python3 /w/packaging/fork.py tree

rm -rf "$OUT"
mv tree "$OUT"
ls "$OUT"
