#!/bin/sh
# Install the built package into a clean container of its suite and test
# cryptography_insecure itself (Debian's test suite tests `cryptography`, so
# the build skips it: packaging/fork.py).
#
#   docker run --rm -v "$PWD/built-debs:/debs:ro" -v "$PWD/packaging:/p:ro" \
#       debian:trixie sh /p/install-test.sh
set -eux
export DEBIAN_FRONTEND=noninteractive

apt-get update
apt-get install -y --no-install-recommends /debs/python3-cryptography-insecure_*.deb

# Nothing may ship under the system cryptography's names. The compiled
# bindings are the trap: their install path comes from a module name in
# src/_cffi_src, and getting it wrong drops a .so straight on top of
# python3-cryptography's. dpkg refuses that only on a machine that has both.
if dpkg -L python3-cryptography-insecure | grep -E '/cryptography/|/cryptography-[0-9]'; then
    echo "::error::the package ships files under the system cryptography's name"
    exit 1
fi

python3 - <<'EOF'
import sys
import cryptography_insecure
from cryptography_insecure.hazmat.primitives import hashes
from cryptography_insecure.hazmat.primitives.asymmetric import dsa

print("cryptography_insecure", cryptography_insecure.__version__)

# DSA, which cryptography has deprecated and paramiko_insecure needs.
key = dsa.generate_private_key(key_size=1024)
signature = key.sign(b"paramiko-insecure", hashes.SHA1())
key.public_key().verify(signature, b"paramiko-insecure", hashes.SHA1())
print("DSA-1024/SHA-1 sign and verify: ok")

# The system module's names are untouched: the extension registers its
# submodules in sys.modules under compiled-in names, and a half-renamed copy
# would register them as cryptography.*.
leaked = sorted(m for m in sys.modules if m == "cryptography" or m.startswith("cryptography."))
assert not leaked, f"cryptography_insecure registered system module names: {leaked[:5]}"
try:
    import cryptography  # noqa: F401
except ImportError:
    print("`import cryptography` is still the system module's to provide: ok")
else:
    raise SystemExit("`import cryptography` works without python3-cryptography installed")
EOF
