#!/usr/bin/env python3
"""Write voices.lock: the rhasspy/piper-voices commit the stack downloads Piper
voices from, and the sha256 of every voice file it may fetch.

scripts/fetch-voices.sh downloads from that commit only and refuses a file whose
hash differs, or a voice the lock does not list. Refresh the lock deliberately
(a new upstream commit, or a new voice in languages.toml), then review the diff:

    python3 scripts/lock-voices.py                         # same commit, same voices + any new ones
    python3 scripts/lock-voices.py --revision <commit>     # move to another upstream commit
    python3 scripts/lock-voices.py de_DE-karlsson-low      # add a voice (the rest are kept)

The voices locked by default: every Piper voice languages.toml names, in both
editions, and every Piper voice server/licences.py has a licence entry for (the
candidates an operator may switch to). Each file is downloaded and hashed; for
the .onnx files (Git LFS) the hash is also checked against the sha256 Hugging
Face records for that commit, so a corrupted download cannot be locked in.
Standard library only.
"""
import argparse
import hashlib
import json
import os
import sys
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "server"))
LOCK = os.path.join(ROOT, "voices.lock")
REPO = "rhasspy/piper-voices"
HEADER = """\
# Piper voices, pinned. Written by scripts/lock-voices.py and checked by
# scripts/fetch-voices.sh, which downloads only from this commit of
# huggingface.co/{repo} and refuses any file whose sha256
# differs, or a voice not listed here. Refresh it deliberately and review the
# diff: server/licences.py was read against this commit's model cards.
repo {repo}
revision {revision}
# sha256  file
"""


def read_lock(path=LOCK):
    """(repo, revision, {file: sha256}) from a lock file; empty when there is none."""
    repo, rev, files = REPO, "", {}
    if not os.path.exists(path):
        return repo, rev, files
    for line in open(path, encoding="utf-8"):
        parts = line.split()
        if not parts or parts[0].startswith("#"):
            continue
        if parts[0] == "repo":
            repo = parts[1]
        elif parts[0] == "revision":
            rev = parts[1]
        else:
            files[parts[1]] = parts[0]
    return repo, rev, files


def default_voices():
    import licences
    import stack_config
    table, _ = stack_config.load()
    names = set(licences.ITEMS["piper"])
    for entry in table.values():
        for e in (entry, entry.get("commercial", {})):
            if e.get("piper"):
                names.add(e["piper"])
    return names


def lfs_sha256(repo, rev, paths):
    """{path: sha256} for the LFS files among `paths`, as the Hub records them."""
    req = urllib.request.Request(
        f"https://huggingface.co/api/models/{repo}/paths-info/{rev}",
        data=urllib.parse.urlencode([("paths", p) for p in paths]).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return {e["path"]: e["lfs"]["oid"] for e in json.load(r) if e.get("lfs")}


def fetch_sha256(url):
    h = hashlib.sha256()
    with urllib.request.urlopen(url, timeout=120) as r:
        for chunk in iter(lambda: r.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    import stack_config
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("voices", nargs="*", help="voices to add (default: the config's and licences.py's)")
    ap.add_argument("--revision", help="upstream commit (default: the lock's)")
    ap.add_argument("--lock", default=LOCK)
    a = ap.parse_args()
    repo, rev, old = read_lock(a.lock)
    rev = a.revision or rev
    if len(rev) != 40:
        sys.exit("give --revision <40-hex commit of huggingface.co/rhasspy/piper-voices>")
    locked = {f.rsplit(".onnx", 1)[0] for f in old}
    voices = sorted(default_voices() | set(a.voices) | locked)
    out = {}
    for v in voices:
        base = stack_config.piper_path(v)
        paths = [base + ".onnx", base + ".onnx.json"]
        try:
            hub = lfs_sha256(repo, rev, paths)
        except Exception as e:  # noqa: BLE001 - reported, then fatal
            sys.exit(f"{v}: cannot read the Hub's file info at {rev}: {e}")
        for p in paths:
            url = f"https://huggingface.co/{repo}/resolve/{rev}/{urllib.parse.quote(p)}"
            try:
                sha = fetch_sha256(url)
            except Exception as e:  # noqa: BLE001
                sys.exit(f"{v}: download failed ({url}): {e}")
            if p in hub and hub[p] != sha:
                sys.exit(f"{p}: downloaded sha256 {sha} but the Hub records {hub[p]}; not locking it")
            name = os.path.basename(p)
            if name in old and old[name] != sha:
                print(f"  CHANGED {name}: {old[name]} -> {sha}")
            out[name] = sha
            print(f"  {sha}  {name}{'  (matches the Hub LFS record)' if p in hub else ''}")
    with open(a.lock, "w", encoding="utf-8") as f:
        f.write(HEADER.format(repo=repo, revision=rev))
        for name in sorted(out):
            f.write(f"{out[name]}  {name}\n")
    print(f"wrote {a.lock}: {len(out)} files, {repo} @ {rev}")


if __name__ == "__main__":
    main()
