"""Tests for packaging/pins.py's snapshot.debian.org fallback, with a fake
snapshot: only the pinned .dsc and the files it lists are ever written, and
never outside the destination.

Run: python3 -m unittest discover -s tests
"""
import hashlib
import importlib.util
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

PINS = Path(__file__).resolve().parent.parent / "packaging" / "pins.py"


def load():
    spec = importlib.util.spec_from_file_location("pins", PINS)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def sha1(b):
    return hashlib.sha1(b).hexdigest()


def sha256(b):
    return hashlib.sha256(b).hexdigest()


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class Snapshot(unittest.TestCase):
    VERSION = "43.0.0-3"

    def setUp(self):
        self.pins = load()
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.dest = self.tmp / "dest"
        self.dest.mkdir()
        self.outside = self.tmp / "outside"
        self.outside.mkdir()
        self.orig = b"orig tarball"
        self.debian = b"debian tarball"
        self.files = {"python-cryptography_43.0.0.orig.tar.gz": self.orig,
                      "python-cryptography_43.0.0-3.debian.tar.xz": self.debian}
        self.set_dsc(self.dsc_text(self.files))

    def dsc_text(self, files):
        lines = "".join(f" {sha256(b)} {len(b)} {n}\n" for n, b in files.items())
        return (f"Format: 3.0 (quilt)\nSource: python-cryptography\nVersion: {self.VERSION}\n"
                f"Checksums-Sha256:\n{lines}Files:\n x 1 y\n").encode()

    def set_dsc(self, dsc, pin=None):
        self.dsc = dsc
        toml = self.tmp / "pins.toml"
        entry = f'version = "{self.VERSION}"\ndsc-sha256 = "{pin or sha256(dsc)}"\n'
        toml.write_text("".join(f"[{s}]\n{entry}\n" for s in ["bookworm", "trixie", "forky", "sid"]))
        self.pins.PINS = toml

    def serve(self, extra=None, replace=None):
        """Fake urlopen: the listing names the .dsc and its files, plus `extra`
        ({name: bytes}); `replace` ({name: bytes}) serves other bytes for a name."""
        blobs = {"python-cryptography_43.0.0-3.dsc": self.dsc, **self.files, **(extra or {})}
        served = {**blobs, **(replace or {})}
        listing = {"result": [], "fileinfo": {}}
        by_hash = {}
        for name, data in blobs.items():
            h = sha1(served[name])   # snapshot names a file by its own SHA-1
            listing["result"].append({"hash": h})
            listing["fileinfo"][h] = [{"name": name}]
            by_hash[h] = served[name]

        def urlopen(url, timeout=None):
            if "/srcfiles" in url:
                return Response(json.dumps(listing).encode())
            return Response(by_hash[url.rsplit("/", 1)[1]])
        self.pins.urllib.request.urlopen = urlopen

    def written(self):
        return sorted(p.name for p in self.dest.iterdir())

    def test_fetches_the_dsc_and_its_files(self):
        self.serve()
        self.pins.snapshot("trixie", self.dest)
        self.assertEqual(self.written(), sorted(["python-cryptography_43.0.0-3.dsc", *self.files]))
        self.assertEqual((self.dest / "python-cryptography_43.0.0.orig.tar.gz").read_bytes(), self.orig)

    def test_extra_listing_entries_are_ignored(self):
        # A tampered listing adds files, some aiming outside dest: none is
        # fetched or written, since the .dsc doesn't list them.
        self.serve(extra={"../outside/fork.py": b"evil", "/tmp/evil": b"evil", "extra.txt": b"x"})
        self.pins.snapshot("trixie", self.dest)
        self.assertEqual(self.written(), sorted(["python-cryptography_43.0.0-3.dsc", *self.files]))
        self.assertEqual(list(self.outside.iterdir()), [])

    def test_a_dsc_naming_a_path_is_refused(self):
        # Even a .dsc the pin vouches for may not name anything but a file here.
        for bad in ["../outside/fork.py", "sub/dir.tar.gz", ".hidden"]:
            with self.subTest(name=bad):
                for p in self.dest.iterdir():
                    p.unlink()
                files = {**self.files, bad: b"evil"}
                self.set_dsc(self.dsc_text(files))
                self.serve(extra={bad: b"evil"})
                with self.assertRaises(SystemExit):
                    self.pins.snapshot("trixie", self.dest)
                self.assertEqual(list(self.outside.iterdir()), [])
                self.assertNotIn(bad.rsplit("/", 1)[-1], self.written())

    def test_a_file_not_matching_the_dsc_is_refused(self):
        # Snapshot's SHA-1 of the tampered bytes is consistent; the .dsc's
        # SHA-256 is what counts.
        self.serve(replace={"python-cryptography_43.0.0.orig.tar.gz": b"tampered"})
        with self.assertRaises(SystemExit):
            self.pins.snapshot("trixie", self.dest)
        self.assertNotIn("python-cryptography_43.0.0.orig.tar.gz", self.written())

    def test_a_dsc_not_matching_the_pin_is_refused(self):
        self.set_dsc(self.dsc, pin="0" * 64)
        self.serve()
        with self.assertRaises(SystemExit):
            self.pins.snapshot("trixie", self.dest)
        self.assertEqual(self.written(), [])


if __name__ == "__main__":
    unittest.main()
