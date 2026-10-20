"""Print release notes for every package version after PREVIOUS up to the current one.

    python3 .github/release_notes.py [PREVIOUS]

PREVIOUS is the last published version ("0.18.0" or "v0.18.0"). Without it,
only the current version's notes are printed. Notes come from the en_US
releaseNotes in startos/versions/*.ts, newest first, so one GitHub release can
cover several versions that were only tested locally.
"""

import pathlib
import re
import sys

VERSIONS = pathlib.Path(__file__).resolve().parent.parent / "startos" / "versions"


def key(version):
    return tuple(int(p) for p in version.split("."))


def notes():
    found = {}
    for path in VERSIONS.glob("*.ts"):
        text = path.read_text()
        version = re.search(r"version:\s*'([\d.]+):", text)
        note = re.search(r"en_US:\s*'((?:[^'\\]|\\.)*)'", text)
        if version and note:
            found[version.group(1)] = re.sub(r"\\(.)", r"\1", note.group(1))
    return found


def main():
    found = notes()
    current = (VERSIONS / "current.ts").read_text()
    newest = re.search(r"version:\s*'([\d.]+):", current).group(1)
    previous = sys.argv[1].lstrip("v") if len(sys.argv) > 1 and sys.argv[1] else None
    if previous is None:
        picked = [newest]
    else:
        picked = [v for v in found if key(previous) < key(v) <= key(newest)]
    for v in sorted(picked, key=key, reverse=True):
        print(f"### {v}\n\n{found[v]}\n")


if __name__ == "__main__":
    main()
