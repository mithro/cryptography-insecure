#!/bin/sh
# Install the built package into a clean container of its suite and test
# cryptography_insecure itself (Debian's test suite tests `cryptography`, so
# the build skips it: packaging/fork.py).
#
#   docker run --rm -v "$PWD/built-debs:/debs:ro" -v "$PWD/packaging:/p:ro" \
#       debian:trixie sh /p/install-test.sh
#
# Twice: alone, and then next to the suite's own python3-cryptography, since
# living beside it (in one process, as python3-paramiko-insecure does next to
# python3-paramiko) is what the rename is for.
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

# 1. Alone: everything it needs is declared, and it takes no system names.
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

# 2. Next to the suite's own python3-cryptography. dpkg installs both only if
# they share no file; then both must work in one process, each from its own
# files and its own compiled extension, in either import order.
apt-get install -y --no-install-recommends python3-cryptography
for first in cryptography cryptography_insecure; do
    FIRST=$first python3 - <<'EOF'
import importlib
import os
import sys

first = os.environ["FIRST"]
second = "cryptography" if first == "cryptography_insecure" else "cryptography_insecure"
mods = {name: importlib.import_module(name) for name in (first, second)}
system, private = mods["cryptography"], mods["cryptography_insecure"]
print(f"imported {first} then {second}: cryptography {system.__version__} at "
      f"{os.path.dirname(system.__file__)}, cryptography_insecure {private.__version__} at "
      f"{os.path.dirname(private.__file__)}")
assert os.path.dirname(system.__file__) != os.path.dirname(private.__file__)

rust = {name: importlib.import_module(f"{name}.hazmat.bindings._rust") for name in mods}
assert rust["cryptography"].__file__ != rust["cryptography_insecure"].__file__, \
    "both packages load the same compiled extension"
assert rust["cryptography"] is not rust["cryptography_insecure"]

# Each registered its submodules under its own name only, whichever came
# first: nothing of one is reachable through the other's name.
for name, mod in rust.items():
    other = second if name == first else first
    assert not mod.__name__.startswith(other + "."), (name, mod.__name__)
for key, mod in list(sys.modules.items()):
    if mod is None or not getattr(mod, "__file__", None):
        continue
    top = key.split(".")[0]
    if top in mods:
        owner = os.path.dirname(mods[top].__file__)
        assert mod.__file__.startswith(owner), f"{key} is {mod.__file__}, not under {owner}"

# Both do real work, side by side, and each accepts only its own objects.
for name in mods:
    hashes = importlib.import_module(f"{name}.hazmat.primitives.hashes")
    ec = importlib.import_module(f"{name}.hazmat.primitives.asymmetric.ec")
    key = ec.generate_private_key(ec.SECP256R1())
    signature = key.sign(b"side by side", ec.ECDSA(hashes.SHA256()))
    key.public_key().verify(signature, b"side by side", ec.ECDSA(hashes.SHA256()))
print("both sign and verify in one process: ok")
EOF
done
