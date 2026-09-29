#!/usr/bin/env python3
"""The pinned Debian python-cryptography source of each suite (pins.toml).

    pins.py version <suite>     the pinned version (raspbian-<codename>: the codename's)
    pins.py dsc-sha256 <suite>  the pinned .dsc's SHA-256
    pins.py check               every pin is well-formed
    pins.py stale               fail, listing them, if Debian has a newer source than a pin
    pins.py snapshot <suite> <dir>  fetch the pinned source's files from snapshot.debian.org

`stale` reads Debian's Sources indexes over https. It only reports: the build
itself fetches through apt, which verifies the archive's signatures, and
checks the .dsc against the pin.

`snapshot` is the build's fallback when the pinned version has left the
archive (sid and forky keep only their newest source; a stable update
replaces the one before). snapshot.debian.org keeps every source Debian ever
published: the .dsc is checked against the pin's SHA-256 before anything
else, each file against the SHA-1 snapshot names it by, and the build's
dpkg-source -x then checks the other files against the .dsc's own SHA-256s.
The pin is the root of trust either way.

Standard library only (tomllib: Python 3.11, bookworm's).
"""
import hashlib
import json
import lzma
import re
import subprocess
import sys
import tomllib
import urllib.parse
import urllib.request
from pathlib import Path

PINS = Path(__file__).resolve().parent / "pins.toml"
SUITES = ["bookworm", "trixie", "forky", "sid"]
SOURCE = "python-cryptography"
SNAPSHOT = "https://snapshot.debian.org"
# Where each suite's newest source can be: the release, and its updates and
# security archives for the stable releases.
INDEXES = {
    "bookworm": ["https://deb.debian.org/debian/dists/bookworm/main/source/Sources.xz",
                 "https://deb.debian.org/debian/dists/bookworm-updates/main/source/Sources.xz",
                 "https://security.debian.org/debian-security/dists/bookworm-security/main/source/Sources.xz"],
    "trixie": ["https://deb.debian.org/debian/dists/trixie/main/source/Sources.xz",
               "https://deb.debian.org/debian/dists/trixie-updates/main/source/Sources.xz",
               "https://security.debian.org/debian-security/dists/trixie-security/main/source/Sources.xz"],
    "forky": ["https://deb.debian.org/debian/dists/forky/main/source/Sources.xz"],
    "sid": ["https://deb.debian.org/debian/dists/sid/main/source/Sources.xz"],
}


def fail(msg):
    print(f"pins.py: {msg}", file=sys.stderr)
    sys.exit(1)


def load():
    pins = tomllib.loads(PINS.read_text())
    if sorted(pins) != sorted(SUITES):
        fail(f"{PINS.name} pins {', '.join(sorted(pins))}, not {', '.join(SUITES)}")
    for suite, pin in pins.items():
        if sorted(pin) != ["dsc-sha256", "version"]:
            fail(f"[{suite}] has {', '.join(sorted(pin))}, not version and dsc-sha256")
        if not re.fullmatch(r"[0-9][A-Za-z0-9.+~-]*-[A-Za-z0-9.+~]+", pin["version"]):
            fail(f"[{suite}] version {pin['version']!r} is not a Debian version with a revision")
        if not re.fullmatch(r"[0-9a-f]{64}", pin["dsc-sha256"]):
            fail(f"[{suite}] dsc-sha256 is not a SHA-256")
    return pins


def pin_for(suite):
    codename = suite.removeprefix("raspbian-")
    pins = load()
    if codename not in pins:
        fail(f"no pin for {suite}")
    return pins[codename]


def newer(a, b):
    """Is Debian version a newer than b?"""
    return subprocess.run(["dpkg", "--compare-versions", a, "gt", b]).returncode == 0


def newest(suite):
    best = None
    for url in INDEXES[suite]:
        with urllib.request.urlopen(url, timeout=120) as r:
            text = lzma.decompress(r.read()).decode()
        for stanza in text.split("\n\n"):
            if re.search(rf"^Package: {re.escape(SOURCE)}$", stanza, re.M):
                v = re.search(r"^Version: (\S+)$", stanza, re.M).group(1)
                if best is None or newer(v, best):
                    best = v
    if best is None:
        fail(f"{suite}: no {SOURCE} in {', '.join(INDEXES[suite])}")
    return best


def snapshot(suite, dest):
    """The pinned source's files, from snapshot.debian.org, into dest."""
    pin = pin_for(suite)
    version = pin["version"]
    url = f"{SNAPSHOT}/mr/package/{SOURCE}/{urllib.parse.quote(version, safe='')}/srcfiles?fileinfo=1"
    with urllib.request.urlopen(url, timeout=120) as r:
        listing = json.load(r)
    dsc = f"{SOURCE}_{version.split(':', 1)[-1]}.dsc"
    files = {}
    for f in listing["result"]:
        names = {i["name"] for i in listing["fileinfo"][f["hash"]]}
        if len(names) != 1:
            fail(f"snapshot names {f['hash']} as {', '.join(sorted(names))}")
        files[names.pop()] = f["hash"]
    if dsc not in files:
        fail(f"snapshot.debian.org has no {dsc} for {SOURCE} {version}")
    # The .dsc first: nothing else is fetched unless it is the pinned one.
    order = [dsc] + sorted(n for n in files if n != dsc)
    for name in order:
        with urllib.request.urlopen(f"{SNAPSHOT}/file/{files[name]}", timeout=600) as r:
            data = r.read()
        if hashlib.sha1(data).hexdigest() != files[name]:
            fail(f"{name} from snapshot.debian.org doesn't match its SHA-1 {files[name]}")
        if name == dsc and hashlib.sha256(data).hexdigest() != pin["dsc-sha256"]:
            fail(f"{dsc} from snapshot.debian.org doesn't match the pin's SHA-256")
        (dest / name).write_bytes(data)
        print(f"{name}: {len(data)} bytes from snapshot.debian.org")


def main():
    args = sys.argv[1:]
    if args[:1] == ["version"] and len(args) == 2:
        print(pin_for(args[1])["version"])
    elif args[:1] == ["dsc-sha256"] and len(args) == 2:
        print(pin_for(args[1])["dsc-sha256"])
    elif args == ["check"]:
        for suite, pin in load().items():
            print(f"{suite}: {pin['version']}")
    elif args[:1] == ["snapshot"] and len(args) == 3:
        snapshot(args[1], Path(args[2]))
    elif args == ["stale"]:
        stale = []
        for suite, pin in load().items():
            have = newest(suite)
            print(f"{suite}: pinned {pin['version']}, Debian has {have}")
            if newer(have, pin["version"]):
                stale.append(f"{suite} ({pin['version']} -> {have})")
        if stale:
            fail("Debian has a newer python-cryptography than the pin for: " + "; ".join(stale)
                 + ". Update packaging/pins.toml (version and the .dsc's SHA-256 from the "
                 "Sources index).")
    else:
        fail(__doc__)


if __name__ == "__main__":
    main()
