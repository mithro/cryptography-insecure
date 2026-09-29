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
published. Only the pin is trusted: the .dsc must have the pin's SHA-256,
and only the files that .dsc lists are fetched, each checked against its
SHA-256 and size there. What else snapshot's listing names is ignored, and
nothing is written outside the destination.

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


# A file name a .dsc may list: a plain basename, nothing that leaves dest.
PLAIN_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+~-]*")


def dsc_files(dsc):
    """(name, size, sha256) for each file a .dsc's Checksums-Sha256 lists."""
    text = dsc.decode("utf-8")
    m = re.search(r"^Checksums-Sha256:[ \t]*\n((?:[ \t]+\S.*\n)+)", text, re.M)
    if not m:
        fail("the .dsc has no Checksums-Sha256")
    files = []
    for line in m.group(1).splitlines():
        sha256, size, name = line.split()
        if not PLAIN_NAME.fullmatch(name) or ".." in name:
            fail(f"the .dsc lists {name!r}, which is not a plain file name")
        if not re.fullmatch(r"[0-9a-f]{64}", sha256) or not size.isdigit():
            fail(f"the .dsc's Checksums-Sha256 line for {name} is malformed")
        files.append((name, int(size), sha256))
    return files


def snapshot(suite, dest):
    """The pinned source's files, from snapshot.debian.org, into dest.

    Only the pin is trusted: the .dsc must have the pin's SHA-256, and then
    only the files that .dsc lists are fetched, each checked against the
    .dsc's own SHA-256 and size. Snapshot's listing only says where to find
    them: anything else it names is ignored, and nothing is written outside
    dest."""
    pin = pin_for(suite)
    version = pin["version"]
    dest = Path(dest).resolve()
    url = f"{SNAPSHOT}/mr/package/{SOURCE}/{urllib.parse.quote(version, safe='')}/srcfiles?fileinfo=1"
    with urllib.request.urlopen(url, timeout=120) as r:
        listing = json.load(r)
    where = {}
    for f in listing["result"]:
        for info in listing["fileinfo"].get(f["hash"], []):
            where.setdefault(info["name"], set()).add(f["hash"])

    def fetch(name):
        hashes = where.get(name)
        if not hashes:
            fail(f"snapshot.debian.org lists no {name} for {SOURCE} {version}")
        for h in sorted(hashes):
            if not re.fullmatch(r"[0-9a-f]{40}", h):
                continue
            with urllib.request.urlopen(f"{SNAPSHOT}/file/{h}", timeout=600) as r:
                yield r.read()

    def write(name, data):
        path = (dest / name).resolve()
        if path.parent != dest:
            fail(f"{name!r} would be written outside {dest}")
        path.write_bytes(data)
        print(f"{name}: {len(data)} bytes from snapshot.debian.org")

    # The .dsc first: nothing else is fetched unless it is the pinned one.
    dsc_name = f"{SOURCE}_{version.split(':', 1)[-1]}.dsc"
    dsc = next((d for d in fetch(dsc_name)
                if hashlib.sha256(d).hexdigest() == pin["dsc-sha256"]), None)
    if dsc is None:
        fail(f"{dsc_name} from snapshot.debian.org doesn't match the pin's SHA-256")
    write(dsc_name, dsc)
    for name, size, sha256 in dsc_files(dsc):
        data = next((d for d in fetch(name)
                     if len(d) == size and hashlib.sha256(d).hexdigest() == sha256), None)
        if data is None:
            fail(f"{name} from snapshot.debian.org doesn't match the .dsc's SHA-256")
        write(name, data)


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
