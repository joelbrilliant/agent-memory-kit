#!/usr/bin/env python3
"""Claude Code UserPromptSubmit hook: auto-recall from agent-memory.

Reads the prompt from hook stdin JSON, queries index.db directly (OR-match
over content words), and injects top hits as additionalContext when they
score well. Silent (no output) when the prompt is short, the index is
missing, or nothing scores past the threshold. Never blocks the prompt.

Logs to hook.log (not usage.log) so the Phase 2 checkpoint can tell
automatic injection apart from deliberate recall calls.
"""
import os
import re
import sys
import json
import sqlite3
import datetime

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.environ.get("AGENT_MEMORY_DB", os.path.join(REPO, "index.db"))
HOOK_LOG = os.path.join(REPO, "hook.log")

MIN_PROMPT_WORDS = 6
MAX_TERMS = 15
TOP_K = 3

# bm25: more negative = better. The injection gate ADAPTS to corpus size,
# because bm25 magnitudes grow with the index: a bullseye hit in a 5-doc
# corpus scores around -4, while an equally good hit in a 2,500-doc corpus
# scores -15 or deeper. A fixed ceiling tuned to one scale is silent at the
# other (found by a cold-install rehearsal on a fresh corpus). Override with
# the SCORE_CEILING env var (e.g. "-6.0") to pin it manually.
SCORE_CEILING_ENV = os.environ.get("SCORE_CEILING")


def score_ceiling(doc_count):
    if SCORE_CEILING_ENV:
        try:
            return float(SCORE_CEILING_ENV)
        except ValueError:
            pass
    # -2.0 floor for tiny corpora, deepening linearly to -10.0 at ~2,500 docs.
    return -min(10.0, max(2.0, doc_count / 250.0))

STOPWORDS = {
    "the", "and", "for", "that", "this", "with", "you", "your", "can",
    "how", "what", "when", "where", "why", "who", "are", "was", "were",
    "have", "has", "had", "not", "but", "all", "any", "its", "it's",
    "from", "into", "out", "about", "just", "like", "want", "need",
    "please", "let's", "lets", "then", "than", "also", "will", "would",
    "should", "could", "our", "them", "they", "there", "here", "does",
}


def log(query_words, top_path):
    try:
        ts = datetime.datetime.now().isoformat(timespec="seconds")
        with open(HOOK_LOG, "a", encoding="utf-8") as fh:
            fh.write("%s\t%s\t%s\n" % (ts, " ".join(query_words), top_path))
    except OSError:
        pass


def main():
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0
    prompt = payload.get("prompt", "") or ""

    if prompt.startswith("/"):
        return 0
    if len(prompt.split()) < MIN_PROMPT_WORDS:
        return 0
    if not os.path.exists(DB_PATH):
        return 0

    words = re.findall(r"[a-z0-9][a-z0-9-]{2,}", prompt.lower())
    terms = []
    for w in words:
        if w in STOPWORDS or w in terms:
            continue
        terms.append(w)
        if len(terms) >= MAX_TERMS:
            break
    if len(terms) < 2:
        return 0

    match_expr = " OR ".join('"%s"' % t for t in terms)
    try:
        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute(
            "SELECT path, source, mtime, bm25(docs) AS score, "
            "snippet(docs, 0, '', '', ' ... ', 24) AS snip "
            "FROM docs WHERE docs MATCH ? ORDER BY bm25(docs) LIMIT ?",
            (match_expr, TOP_K),
        ).fetchall()
        doc_count = conn.execute("SELECT count(*) FROM docs").fetchone()[0]
        conn.close()
    except sqlite3.Error:
        return 0

    hits = [r for r in rows if r[3] <= score_ceiling(doc_count)]
    if not hits:
        log(terms, "NONE")
        return 0

    recall_cmd = os.path.join(REPO, "recall")
    lines = [
        "agent-memory auto-recall: local artefacts that may be relevant to "
        "this request (open a file before relying on it; query deliberately "
        "with %s for more):" % recall_cmd
    ]
    for path, source, mtime, score, snip in hits:
        try:
            iso = datetime.date.fromtimestamp(mtime).isoformat()
        except (OSError, OverflowError, ValueError):
            iso = "?"
        snippet = " ".join(snip.split())[:300]
        lines.append("- %s (%s, %s): %s" % (path, source, iso, snippet))

    log(terms, hits[0][0])
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": "\n".join(lines),
        },
        "suppressOutput": True,
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
