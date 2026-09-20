#!/usr/bin/python3
"""Turn an unpacked Debian python-cryptography source tree into
cryptography-insecure, which installs the module `cryptography_insecure`.

    fork.py /path/to/python-cryptography-49.0.0

paramiko_insecure needs primitives that cryptography is in the middle of
retiring -- DSA is deprecated as of 49 ("SSH DSA key support is deprecated
and will be removed in a future release") and 3DES has already moved to
hazmat.decrepit. A private copy keeps this package working whatever the
system cryptography drops next, and keeps that copy out of the way of
everything else on the machine.

Three things are renamed, and all three are needed:

1. the Python package directory and every reference in it;
2. the Rust extension's module paths. The extension registers submodules in
   sys.modules under names baked into the .rs sources, so a copy that skipped
   this would overwrite the real cryptography's entries there and break it in
   any process that imported both;
3. the Debian source and binary package names.
"""

import re
import sys
import tokenize
from pathlib import Path

OLD, NEW = "cryptography", "cryptography_insecure"
OLD_SRC, NEW_SRC = "python-cryptography", "cryptography-insecure"
OLD_BIN, NEW_BIN = "python3-cryptography", "python3-cryptography-insecure"
DESCRIPTION = """\
Package: python3-cryptography-insecure
Architecture: any
Depends: ${misc:Depends},
         ${python3:Depends},
         ${shlibs:Depends},
Description: private cryptography copy for python3-paramiko-insecure
 A copy of python3-cryptography installed as the module
 "cryptography_insecure", so that python3-paramiko-insecure keeps working
 with algorithms the system cryptography is retiring -- DSA, which upstream
 has deprecated, and 3DES, already moved to hazmat.decrepit.
 .
 It is byte for byte the same code as python3-cryptography, only renamed. It
 is not more secure, nor less; it is simply pinned out of the way. Nothing
 but python3-paramiko-insecure should use it, and nothing else does: no
 other package can reach it without importing it by this name.
"""


def rewrite_python(path):
    """Rename module references in one .py file, on tokens, not text."""
    module_path = re.compile(rf"^{OLD}(\.[A-Za-z_]\w*)*$")
    string_prefix = re.compile(r"^([rRbBuUfF]{0,2})('''|\"\"\"|'|\")")
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    edits = []
    with path.open("rb") as handle:
        for tok in tokenize.tokenize(handle.readline):
            (row, col), (erow, _) = tok.start, tok.end
            if tok.type == tokenize.NAME and tok.string == OLD:
                edits.append((row, col))
            elif tok.type == tokenize.STRING and row == erow:
                m = string_prefix.match(tok.string)
                if not m:
                    continue
                quote = m.group(2)
                if module_path.match(tok.string[m.end():-len(quote)]):
                    edits.append((row, col + m.end()))
    for row, col in sorted(edits, reverse=True):
        line = lines[row - 1]
        assert line[col:col + len(OLD)] == OLD, (path, row, col)
        lines[row - 1] = line[:col] + NEW + line[col + len(OLD):]
    if edits:
        path.write_text("".join(lines), encoding="utf-8")
    return len(edits)


# In .rs sources: quoted module paths ("cryptography.hazmat..."), the bare
# quoted name (build.rs joins it into a path), and relative source paths.
# Never the unquoted Rust crate names cryptography_openssl / cryptography_x509.
RUST_FORMS = [
    (rf'"{OLD}\.', f'"{NEW}.'),
    (rf'"{OLD}"', f'"{NEW}"'),
    (rf'/{OLD}/', f'/{NEW}/'),
]


def rewrite_rust(path):
    """Rename the module and source paths baked into the extension."""
    text = path.read_text(encoding="utf-8")
    count = 0
    for pattern, replacement in RUST_FORMS:
        text, n = re.subn(pattern, replacement, text)
        count += n
    if count:
        path.write_text(text, encoding="utf-8")
    return count


def remove_make_target(rules, target):
    """Delete a make target and its recipe from a debian/rules file.

    Line-based rather than a regex: the recipe may be wrapped in
    ifeq/endif, and the exact shape differs between Debian releases.
    """
    lines = rules.splitlines(keepends=True)
    try:
        start = next(i for i, line in enumerate(lines)
                     if line.startswith(f"{target}:"))
    except StopIteration:
        raise SystemExit(f"debian/rules: no {target} to remove")
    end = start + 1
    while end < len(lines):
        line = lines[end]
        # The recipe continues through indented lines, conditionals and
        # blank lines; it ends at the next thing starting in column 0.
        if (line.strip() and not line[0].isspace()
                and not line.startswith(("ifeq", "ifneq", "else", "endif"))):
            break
        end += 1
    del lines[start:end]
    return "".join(lines)


def edit(path, replacements, required=True):
    text = path.read_text(encoding="utf-8")
    for old, new in replacements:
        if old not in text:
            if required:
                raise SystemExit(f"{path}: expected to find {old!r}")
            continue
        text = text.replace(old, new)
    path.write_text(text, encoding="utf-8")


def main():
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    root = Path(sys.argv[1]).resolve()
    package = root / "src" / OLD
    if not package.is_dir():
        raise SystemExit(f"{package} not found -- not a cryptography source?")

    # 1. Python sources of the package itself.
    edits = sum(rewrite_python(p) for p in sorted(package.rglob("*.py")))
    print(f"python: {edits} references rewritten")

    # src/_cffi_src is a build-time helper, not part of the package, and it
    # has a submodule of its own called "cryptography"
    # (_cffi_src/openssl/cryptography.py) which must keep its name. Only its
    # one reference to the package directory is rewritten, by hand.
    edit(root / "src" / "_cffi_src" / "utils.py", [
        ('os.path.join(base_src, "cryptography", "__about__.py")',
         f'os.path.join(base_src, "{NEW}", "__about__.py")'),
    ])

    # 2. Rust sources: module paths only.
    rust = sum(rewrite_rust(p) for p in sorted((root / "src" / "rust").rglob("*.rs")))
    print(f"rust:   {rust} module paths rewritten")
    if not rust:
        raise SystemExit("no Rust module paths found -- layout changed?")

    package.rename(root / "src" / NEW)

    # 3. Build metadata, in whichever form this version uses. Either way the
    #    declared extension path must match the new import path, or the
    #    compiled extension lands where nothing will look for it.
    pyproject = root / "pyproject.toml"
    if f'name = "{OLD}"' in pyproject.read_text():
        # PEP 621 + maturin (cryptography 43 and later).
        edit(pyproject, [
            (f'name = "{OLD}"', f'name = "{NEW}"'),
            (f'module-name = "{OLD}.hazmat.bindings._rust"',
             f'module-name = "{NEW}.hazmat.bindings._rust"'),
        ])
        print("metadata: pyproject.toml (maturin)")
    else:
        # setuptools + setuptools-rust (cryptography 38, Debian bookworm),
        # where the name is in setup.cfg and RustExtension names the module.
        # `version = attr: cryptography.__version__` is resolved by
        # importing the module, so it has to follow the rename too. The
        # other mentions in setup.cfg are URLs and an email address.
        edit(root / "setup.cfg", [
            (f"name = {OLD}\n", f"name = {NEW}\n"),
            (f"version = attr: {OLD}.__version__",
             f"version = attr: {NEW}.__version__"),
        ])
        renamed = rewrite_python(root / "setup.py")
        if not renamed:
            raise SystemExit("setup.py: no module path to rename")
        print(f"metadata: setup.cfg + setup.py ({renamed} references)")

    # 4. Debian packaging.
    debian = root / "debian"
    control = (debian / "control").read_text()
    source, *binaries = control.split("\n\n")
    source = source.replace(f"Source: {OLD_SRC}", f"Source: {NEW_SRC}")
    source = re.sub(r"^(Uploaders|Vcs-Git|Vcs-Browser|Homepage):.*\n(\s+.*\n)*",
                    "", source, flags=re.M)
    source = source.replace(
        "Maintainer: Debian Python Team <team+python@tracker.debian.org>",
        "Maintainer: Tim 'mithro' Ansell <me@mith.ro>")
    # Only the one binary package; the -doc package documents cryptography,
    # which is already installed on any machine wanting this.
    (debian / "control").write_text(source.rstrip() + "\n\n" + DESCRIPTION)

    edit(debian / "rules", [
        ("export PYBUILD_NAME=cryptography",
         "export PYBUILD_NAME=cryptography-insecure"),
        ("export DEB_CARGO_CRATE=$(DEB_SOURCE)_$(DEB_VERSION_UPSTREAM)",
         "export DEB_CARGO_CRATE=python-cryptography_$(DEB_VERSION_UPSTREAM)"),
    ])
    # Drop overrides that name binary packages which no longer exist here:
    # the documentation build (there is no -doc package in this fork) and,
    # where it singles out python3-cryptography, the dh_python3 override.
    rules = (debian / "rules").read_text()
    rules = remove_make_target(rules, "override_dh_sphinxdoc")
    if f"dh_python3 -p {OLD_BIN}" in rules:
        rules = remove_make_target(rules, "override_dh_python3")
    (debian / "rules").write_text(rules)
    for leftover in debian.glob("python-cryptography-doc.*"):
        leftover.unlink()

    print(f"forked {root.name} -> {NEW_SRC}")


if __name__ == "__main__":
    main()
