# cryptography-insecure

Debian's own **python-cryptography**, renamed to the module
**`cryptography_insecure`**, packaged as **`python3-cryptography-insecure`**
for bookworm, trixie, forky and sid, and for Raspbian bookworm, trixie and
forky. It is published as a signed APT repository at
<https://mith.ro/cryptography-insecure/>.

It exists for [python3-paramiko-insecure](https://github.com/mithro/paramiko-insecure),
which imports it instead of the system `cryptography`.

## Why a private copy

paramiko-insecure restores SSH algorithms that upstream removed, for equipment
that speaks nothing newer. It needs primitives `cryptography` is in the middle
of retiring: DSA is deprecated as of 49 ("SSH DSA key support is deprecated
and will be removed in a future release"), and 3DES has already moved to
`hazmat.decrepit`. When those go, `python3-paramiko` should follow the removal
and paramiko-insecure should not, which is only possible with its own copy.

The copy is byte for byte Debian's code, only renamed: it is not more secure
nor less, just out of the way. The rename covers the Rust extension too, not
only the Python tree. The extension registers its submodules in `sys.modules`
under names compiled into it, so a half-rename would let the private copy
overwrite the system copy's entries and break `cryptography` for everything
else in the process. Nothing but paramiko-insecure should import it.

## Install

The packages are published as a signed apt repository per suite: put your
suite's name in place of `trixie` below. The suites are bookworm, trixie,
forky and sid, and raspbian-bookworm, raspbian-trixie and raspbian-forky for 32-bit
Raspberry Pi OS (64-bit Raspberry Pi OS uses the Debian suites).

```sh
sudo install -d -m0755 /etc/apt/keyrings
curl -fsSL https://mith.ro/cryptography-insecure/cryptography-insecure.gpg \
  | sudo tee /etc/apt/keyrings/cryptography-insecure.gpg >/dev/null
echo "deb [signed-by=/etc/apt/keyrings/cryptography-insecure.gpg] https://mith.ro/cryptography-insecure/trixie/ ./" \
  | sudo tee /etc/apt/sources.list.d/cryptography-insecure.list
sudo apt update
sudo apt install python3-cryptography-insecure
```

The repository's signing key is
`D4CC 5969 41A4 B557 C520  E43D 2A45 8790 7B49 4D00`
(`gpg --show-keys /etc/apt/keyrings/cryptography-insecure.gpg` shows it).

You normally don't add this repository yourself: install
python3-paramiko-insecure, which needs it.

### Debug symbols

`python3-cryptography-insecure-dbgsym` is in the apt repository only where
it is at most 10 MB: bookworm, trixie, raspbian-bookworm and
raspbian-trixie. In forky, sid and raspbian-forky it is 11-12 MB for each
architecture, and debug-symbol packages over 10 MB are kept out of the apt
repository: the site was 646 MB of the 1 GB GitHub Pages allows, 376 MB of
it these packages.

Those are built all the same. They are in the `dbgsym-<suite>-<arch>`
artifacts of the
[Debian packages](https://github.com/mithro/cryptography-insecure/actions/workflows/deb.yml)
run on `main` that published that version, for 14 days; downloading an
artifact needs a GitHub login. A pull request's run has them too, but with
a `~pr<N>` version, which doesn't match the published package.

## How it is built

This is a patch series in the sense of
[mithro/apt-repo-action's conventions](https://github.com/mithro/apt-repo-action/blob/main/docs/packaging.md):
the repository holds the build, and the software is fetched at build time.

- `packaging/pins.toml` pins each suite's Debian `python-cryptography`
  source: its version and the `.dsc`'s SHA-256. A Raspbian suite builds its
  codename's. The weekly **Pins** workflow fails when Debian has a newer
  source than a pin (a security update, say): update the pin, and the build
  publishes it. A pin that has left the archive (sid and forky keep only
  their newest source) is fetched from snapshot.debian.org instead, with a
  warning, and checked against the pin the same way.
- `packaging/prepare.sh` fetches the pinned source in a container of the
  suite, checks it against the pin, and renames it with `packaging/fork.py`:
  the Python package, the Rust extension's module paths, and the Debian
  source and binary names (the binary package is
  `packaging/debian/cryptography-insecure/control`).
- The shared `build-deb` builds it for each suite and architecture, and
  `packaging/install-test.sh` tests the result in a clean container: no file
  under the system `cryptography`'s names, DSA sign and verify, and no
  `cryptography.*` module names taken; then again with the suite's own
  `python3-cryptography` installed too, both imported in one process, each
  from its own files. Debian's own test suite imports
  `cryptography`, not this package, so the build doesn't run it.

The version is Debian's, followed by ours:
`43.0.0-3+deb13u1+welland.0.0.post6~deb13`. A new pin (Debian's version) or
a new commit here raises it, and it sorts above the
`43.0.0-3+deb13u1+insecure1` paramiko-insecure published before this
repository existed.

## History

`packaging/fork.py` and `packaging/prepare.sh` began in
[paramiko-insecure](https://github.com/mithro/paramiko-insecure), under
`packaging/cryptography-insecure/`; their history came with them.
