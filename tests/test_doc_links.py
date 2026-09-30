#!/usr/bin/env python3
"""Every relative link and image in the repository's Markdown resolves.

For each [text](target) and ![alt](target) outside code, in every tracked .md
file: the target file (or directory) exists, and a #anchor names a heading in
the target Markdown file (GitHub's heading slugs). External links (http:,
https:, mailto:) are not fetched. Standard library only.

    python3 tests/test_doc_links.py
"""
import os
import re
import subprocess
import sys
import unicodedata
from urllib.parse import unquote

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LINK = re.compile(r"!?\[(?:[^\[\]]|\[[^\]]*\])*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
FENCE = re.compile(r"^\s*(```|~~~)")


def markdown_files():
    try:
        out = subprocess.run(["git", "ls-files", "*.md"], cwd=ROOT, capture_output=True, text=True, check=True)
        files = [f for f in out.stdout.splitlines() if f]
    except (OSError, subprocess.CalledProcessError):
        files = []
    # New files not yet tracked, too.
    for base, dirs, names in os.walk(ROOT):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d != "node_modules"]
        for n in names:
            if n.endswith(".md"):
                rel = os.path.relpath(os.path.join(base, n), ROOT)
                if rel not in files:
                    files.append(rel)
    return sorted(f for f in files if os.path.exists(os.path.join(ROOT, f)))


def prose_lines(text):
    """(line number, line) outside fenced code blocks, with inline code removed."""
    fenced = False
    for i, line in enumerate(text.splitlines(), 1):
        if FENCE.match(line):
            fenced = not fenced
            continue
        if not fenced:
            yield i, re.sub(r"`[^`]*`", "", line)


def slug(heading):
    """GitHub's anchor for a heading."""
    # Inline HTML is dropped, but not inside code spans (`<name>` is text there).
    parts = heading.split("`")
    h = "".join(p if i % 2 else re.sub(r"<[^>]+>", "", p) for i, p in enumerate(parts))
    h = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", h)       # links keep their text
    h = h.strip().lower()
    out = []
    for ch in h:
        if ch in " -_" or ch.isalnum() or unicodedata.category(ch).startswith("M"):
            out.append("-" if ch == " " else ch)
    return "".join(out)


def anchors(path, cache={}):
    if path not in cache:
        seen, found = {}, set()
        fenced = False
        for line in open(path, encoding="utf-8"):
            if FENCE.match(line):
                fenced = not fenced
                continue
            if fenced:
                continue
            m = re.match(r"^\s{0,3}#{1,6}\s+(.*?)\s*#*\s*$", line)
            if m:
                s = slug(m.group(1))
                n = seen.get(s, 0)
                seen[s] = n + 1
                found.add(s if n == 0 else f"{s}-{n}")
            for a in re.findall(r"<a\s+(?:id|name)=\"([^\"]+)\"", line):
                found.add(a)
        cache[path] = found
    return cache[path]


def check():
    problems, count = [], 0
    for rel in markdown_files():
        src = os.path.join(ROOT, rel)
        text = open(src, encoding="utf-8").read()
        for n, line in prose_lines(text):
            for target in LINK.findall(line):
                if re.match(r"^[a-z][a-z0-9+.-]*:", target, re.I):
                    continue                                   # http:, https:, mailto:
                count += 1
                path, _, anchor = target.partition("#")
                dest = os.path.normpath(os.path.join(os.path.dirname(src), unquote(path))) if path else src
                where = f"{rel}:{n}: {target}"
                if not dest.startswith(ROOT):
                    problems.append(f"{where}: leaves the repository")
                elif not os.path.exists(dest):
                    problems.append(f"{where}: no such file")
                elif anchor and dest.endswith(".md") and unquote(anchor).lower() not in anchors(dest):
                    problems.append(f"{where}: no heading #{anchor} in {os.path.relpath(dest, ROOT)}")
    return count, problems


def test_links():
    count, problems = check()
    assert not problems, "broken links:\n  " + "\n  ".join(problems)
    return count


if __name__ == "__main__":
    count, problems = check()
    for p in problems:
        print(p)
    print(f"{count} relative links checked, {len(problems)} broken")
    sys.exit(1 if problems else 0)
