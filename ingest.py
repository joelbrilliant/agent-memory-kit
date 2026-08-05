#!/usr/bin/env python3
"""Full-rebuild ingest for agent-memory. Python 3 stdlib only.

Reads corpus.txt, expands globs, applies path/basename/content filters,
writes an FTS5 index.db next to this script. See DESIGN.md for the contract.
"""
import os
import re
import sys
import glob
import time
import fnmatch
import sqlite3

from db_permissions import enforce_private_database, prepare_private_database

# Paths derived from THIS script's location, not cwd.
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CORPUS_PATH = os.path.join(SCRIPT_DIR, "corpus.txt")
EXCLUDE_PATH = os.path.join(SCRIPT_DIR, "exclude.txt")
DEFAULT_DB = os.path.join(SCRIPT_DIR, "index.db")
DB_PATH = os.environ.get("AGENT_MEMORY_DB", DEFAULT_DB)

MAX_BYTES = 1024 * 1024  # 1 MB

# Skip if the absolute path contains any of these substrings.
# Builtin universal defaults; merged with an optional exclude.txt next to
# this script (one path substring per line, # comments allowed).
DEFAULT_PATH_EXCLUDE_SUBSTRINGS = (
    "/.git/",
    "/node_modules/",
)

# Skip if the basename matches any of these fnmatch patterns.
BASENAME_EXCLUDE = (
    ".env*",
    "*.pem",
    "*.key",
    "id_rsa*",
    "*.headers",
    "root-auth*",
    "*key-setup-prompt*",
    ".DS_Store",
)

# Content secret scan. Match -> skip + log path (never the content).
SECRET_PATTERNS = [
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}"),
    re.compile(r"xox[bap]-[A-Za-z0-9\-]{10,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"ghp_[A-Za-z0-9]{30,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{30,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY"),
    re.compile(r"(?im)^(?:export\s+)?[A-Z0-9_]*(?:API_KEY|TOKEN|SECRET|PASSWORD)\s*=\s*\S{16,}"),
]


def load_path_excludes():
    """Merge builtin defaults with an optional exclude.txt next to the script.

    exclude.txt: one path substring per line, blank lines and # comments
    ignored. Returns the merged tuple, deduped, order-stable.
    """
    excludes = list(DEFAULT_PATH_EXCLUDE_SUBSTRINGS)
    if os.path.exists(EXCLUDE_PATH):
        try:
            with open(EXCLUDE_PATH, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if line not in excludes:
                        excludes.append(line)
        except OSError:
            pass
    return tuple(excludes)


PATH_EXCLUDE_SUBSTRINGS = load_path_excludes()


def path_excluded(path):
    for sub in PATH_EXCLUDE_SUBSTRINGS:
        if sub in path:
            return True
    return False


def basename_excluded(path):
    name = os.path.basename(path)
    for pat in BASENAME_EXCLUDE:
        if fnmatch.fnmatch(name, pat):
            return True
    return False


def has_secret(content):
    for pat in SECRET_PATTERNS:
        if pat.search(content):
            return True
    return False


def read_corpus(corpus_path):
    """Yield (tag, glob) pairs. Skip comments and blanks."""
    entries = []
    with open(corpus_path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "|" not in line:
                sys.stderr.write("corpus: malformed line (no pipe): %s\n" % line)
                continue
            tag, pattern = line.split("|", 1)
            entries.append((tag.strip(), pattern.strip()))
    return entries


def main():
    start = time.time()
    if not os.path.exists(CORPUS_PATH):
        sys.stderr.write("ingest: corpus.txt not found at %s\n" % CORPUS_PATH)
        return 1

    entries = read_corpus(CORPUS_PATH)

    # Drop and recreate the index.
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    prepare_private_database(DB_PATH)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "CREATE VIRTUAL TABLE docs USING fts5("
        "content, path UNINDEXED, source UNINDEXED, mtime UNINDEXED, "
        "tokenize='porter unicode61')"
    )

    per_tag = {}
    skipped = {
        "size": 0,
        "excluded-path": 0,
        "excluded-name": 0,
        "secret-scan": 0,
        "unreadable": 0,
    }
    seen = set()  # dedupe: a file may match multiple globs
    total_indexed = 0

    for tag, pattern in entries:
        per_tag.setdefault(tag, 0)
        pattern = os.path.expanduser(pattern)  # so ~/... works in corpus.txt
        for path in glob.glob(pattern, recursive=True):
            abspath = os.path.abspath(path)
            if abspath in seen:
                continue
            # Only regular files ending .md.
            if not os.path.isfile(abspath):
                continue
            if not abspath.endswith(".md"):
                continue
            seen.add(abspath)

            if basename_excluded(abspath):
                skipped["excluded-name"] += 1
                continue
            if path_excluded(abspath):
                skipped["excluded-path"] += 1
                continue
            try:
                size = os.path.getsize(abspath)
            except OSError:
                skipped["unreadable"] += 1
                continue
            if size > MAX_BYTES:
                skipped["size"] += 1
                continue
            try:
                with open(abspath, "r", encoding="utf-8", errors="replace") as fh:
                    content = fh.read()
            except OSError:
                skipped["unreadable"] += 1
                continue
            if has_secret(content):
                skipped["secret-scan"] += 1
                sys.stderr.write("secret-scan: skipped %s\n" % abspath)
                continue

            try:
                mtime = int(os.path.getmtime(abspath))
            except OSError:
                mtime = 0
            conn.execute(
                "INSERT INTO docs (content, path, source, mtime) VALUES (?, ?, ?, ?)",
                (content, abspath, tag, mtime),
            )
            per_tag[tag] += 1
            total_indexed += 1

    conn.commit()
    enforce_private_database(DB_PATH)
    conn.close()
    enforce_private_database(DB_PATH)

    elapsed = time.time() - start
    try:
        db_size = os.path.getsize(DB_PATH)
    except OSError:
        db_size = 0

    total_skipped = sum(skipped.values())
    print("agent-memory ingest complete")
    print("db: %s" % DB_PATH)
    print("per-tag indexed:")
    for tag in sorted(per_tag):
        print("  %-12s %d" % (tag, per_tag[tag]))
    print("total indexed:  %d" % total_indexed)
    print("total skipped:  %d" % total_skipped)
    print("  size:          %d" % skipped["size"])
    print("  excluded-path: %d" % skipped["excluded-path"])
    print("  excluded-name: %d" % skipped["excluded-name"])
    print("  secret-scan:   %d" % skipped["secret-scan"])
    print("  unreadable:    %d" % skipped["unreadable"])
    print("db size:        %d bytes" % db_size)
    print("elapsed:        %.2f s" % elapsed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
