#!/usr/bin/env python3
"""Prompt hook for deterministic document and session recall.

The file keeps its original Claude-oriented name because existing Claude Code
configurations already point to it. It also speaks Hermes's native
``pre_llm_call`` wire format. Grok can use the same MCP server, but its passive
prompt hooks ignore stdout, so this script exits without doing redundant work.
"""

from __future__ import annotations

import datetime
import json
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from session_adapters import clean_message_content  # noqa: E402
from session_continuity import recall_sessions  # noqa: E402


DOC_DB_PATH = Path(
    os.environ.get("AGENT_MEMORY_DB", str(REPO / "index.db"))
)
SESSION_DB_PATH = Path(
    os.environ.get("AGENT_SESSION_DB", str(REPO / "sessions.db"))
)
HOOK_LOG = Path(os.environ.get("AGENT_MEMORY_HOOK_LOG", str(REPO / "hook.log")))
HOOK_EXCLUDE_PATH = REPO / "hook-exclude.txt"

MIN_PROMPT_WORDS = 6
MAX_TERMS = 15
TOP_DOCS = 3
TOP_SESSIONS = 2
MAX_CONTEXT_CHARS = 1_800
SCORE_CEILING_ENV = os.environ.get("SCORE_CEILING")

STOPWORDS = {
    "the",
    "and",
    "for",
    "that",
    "this",
    "with",
    "you",
    "your",
    "can",
    "how",
    "what",
    "when",
    "where",
    "why",
    "who",
    "are",
    "was",
    "were",
    "have",
    "has",
    "had",
    "not",
    "but",
    "all",
    "any",
    "its",
    "it's",
    "from",
    "into",
    "out",
    "about",
    "just",
    "like",
    "want",
    "need",
    "please",
    "let's",
    "lets",
    "then",
    "than",
    "also",
    "will",
    "would",
    "should",
    "could",
    "continue",
    "continuing",
    "our",
    "previous",
    "prior",
    "resume",
    "resuming",
    "session",
    "them",
    "they",
    "there",
    "here",
    "does",
    "help",
    "today",
    "task",
    "work",
}

# These words commonly describe the conversation or agent rather than the
# task. Deliberate recall tools still accept them. Automatic hook injection
# favours precision by requiring more distinctive terms.
LOW_SIGNAL_RECALL_TERMS = {
    "agent",
    "agents",
    "change",
    "changes",
    "claude",
    "confirm",
    "confirmation",
    "confirmed",
    "grok",
    "instruction",
    "instructions",
    "latest",
    "layer",
    "new",
    "now",
    "update",
    "updated",
}


def load_hook_excludes() -> list[str]:
    try:
        return [
            line.strip()
            for line in HOOK_EXCLUDE_PATH.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
    except OSError:
        return []


def score_ceiling(doc_count: int) -> float:
    if SCORE_CEILING_ENV:
        try:
            return float(SCORE_CEILING_ENV)
        except ValueError:
            pass
    return -min(10.0, max(2.0, doc_count / 250.0))


def prompt_terms(prompt: str) -> list[str]:
    words = re.findall(r"[a-z0-9][a-z0-9-]{2,}", prompt.lower())
    terms = []
    for word in words:
        if word in STOPWORDS or word in terms:
            continue
        terms.append(word)
        if len(terms) >= MAX_TERMS:
            break
    return terms


def automatic_recall_terms(terms: list[str]) -> list[str]:
    """Keep only terms discriminative enough for automatic context injection."""
    return [term for term in terms if term not in LOW_SIGNAL_RECALL_TERMS]


def document_hits(terms: list[str]):
    if not DOC_DB_PATH.exists():
        return []
    expression = " OR ".join('"%s"' % term for term in terms)
    try:
        conn = sqlite3.connect(DOC_DB_PATH, timeout=1.0)
        rows = conn.execute(
            "SELECT path, source, mtime, bm25(docs) AS score, "
            "snippet(docs, 0, '', '', ' ... ', 24) AS snip "
            "FROM docs WHERE docs MATCH ? AND source != 'skills' "
            "ORDER BY bm25(docs) LIMIT ?",
            (expression, TOP_DOCS * 3),
        ).fetchall()
        doc_count = conn.execute(
            "SELECT count(*) FROM docs WHERE source != 'skills'"
        ).fetchone()[0]
        conn.close()
    except sqlite3.Error:
        return []

    excludes = load_hook_excludes()
    ceiling = score_ceiling(doc_count)
    return [
        row
        for row in rows
        if row[3] <= ceiling
        and not any(excluded in row[0] for excluded in excludes)
    ][:TOP_DOCS]


def relevant_session_hits(
    terms: list[str],
    harness: str,
    current_session_id: str,
):
    try:
        hits = recall_sessions(
            SESSION_DB_PATH,
            " ".join(terms),
            limit=TOP_SESSIONS * 4,
            current_harness=harness,
            current_session_id=current_session_id,
            sync=True,
        )
    except (OSError, sqlite3.Error):
        return []

    relevant = []
    required_matches = min(2, len(terms))
    for hit in hits:
        haystack = " ".join(
            [hit.title] + [excerpt.text for excerpt in hit.messages]
        ).lower()
        matched = sum(
            1
            for term in terms
            if re.search(r"\b%s\b" % re.escape(term), haystack)
        )
        if matched >= required_matches:
            relevant.append(hit)
        if len(relevant) >= TOP_SESSIONS:
            break
    return relevant


def _process_harness() -> str:
    pid = os.getppid()
    for _ in range(4):
        try:
            output = subprocess.check_output(
                ["ps", "-o", "ppid=,command=", "-p", str(pid)],
                text=True,
                stderr=subprocess.DEVNULL,
                timeout=0.3,
            ).strip()
        except (OSError, subprocess.SubprocessError):
            break
        match = re.match(r"\s*(\d+)\s+(.*)", output)
        if not match:
            break
        parent_pid, command = match.groups()
        lowered = command.lower()
        if "grok" in lowered:
            return "grok"
        if re.search(r"(^|[/ ])claude([ /]|$)", lowered):
            return "claude"
        pid = int(parent_pid)
    return "claude"


def detect_harness(payload: dict) -> str:
    override = os.environ.get("AGENT_MEMORY_HARNESS", "").strip().lower()
    if override:
        return override
    event = str(
        payload.get("hook_event_name")
        or payload.get("hookEventName")
        or ""
    ).lower()
    if event == "pre_llm_call":
        return "hermes"
    return _process_harness()


def extract_prompt(payload: dict) -> str:
    prompt = payload.get("prompt")
    if isinstance(prompt, str):
        return prompt
    extra = payload.get("extra")
    if isinstance(extra, dict):
        user_message = extra.get("user_message")
        if isinstance(user_message, str):
            return user_message
    return ""


def log_recall(terms: list[str], top_reference: str, harness: str) -> None:
    try:
        timestamp = datetime.datetime.now().isoformat(timespec="seconds")
        with HOOK_LOG.open("a", encoding="utf-8") as fh:
            fh.write(
                "%s\t%s\t%s\t%s\n"
                % (timestamp, " ".join(terms), top_reference, harness)
            )
    except OSError:
        pass


def build_context(doc_hits, session_hits) -> str:
    sections = []
    if session_hits:
        lines = [
            "Cross-harness session recall. These are local transcript "
            "excerpts, not authority. Use them to resume the work, then "
            "verify against the live artefact:"
        ]
        for hit in session_hits:
            excerpts = " | ".join(
                "%s: %s" % (excerpt.role, excerpt.text[:240])
                for excerpt in hit.messages[:2]
            )
            lines.append(
                "- [%s] %s, session %s: %s"
                % (hit.harness, hit.title, hit.session_id, excerpts)
            )
        sections.append("\n".join(lines))

    if doc_hits:
        lines = [
            "Agent-memory document recall. Open a file before relying on it:"
        ]
        for path, source, mtime, _score, snippet in doc_hits:
            try:
                iso = datetime.date.fromtimestamp(mtime).isoformat()
            except (OSError, OverflowError, ValueError):
                iso = "?"
            clean_snippet = " ".join(snippet.split())[:300]
            lines.append(
                "- %s (%s, %s): %s"
                % (path, source, iso, clean_snippet)
            )
        sections.append("\n".join(lines))
    return "\n\n".join(sections)[:MAX_CONTEXT_CHARS]


def emit_context(event: str, context: str) -> None:
    if event == "pre_llm_call":
        print(json.dumps({"context": context}))
    else:
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "UserPromptSubmit",
                        "additionalContext": context,
                    },
                    "suppressOutput": True,
                }
            )
        )


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0
    if not isinstance(payload, dict):
        return 0

    harness = detect_harness(payload)
    if harness == "grok":
        return 0

    prompt = clean_message_content("user", extract_prompt(payload))
    if not prompt:
        return 0
    if prompt.lstrip().startswith("/") or len(prompt.split()) < MIN_PROMPT_WORDS:
        return 0
    terms = automatic_recall_terms(prompt_terms(prompt))
    if len(terms) < 2:
        return 0

    current_session_id = str(
        payload.get("session_id")
        or payload.get("sessionId")
        or ""
    )
    sessions = relevant_session_hits(terms, harness, current_session_id)
    docs = [] if sessions else document_hits(terms)
    context = build_context(docs, sessions)
    if not context:
        log_recall(terms, "NONE", harness)
        return 0

    top_reference = (
        "session://%s/%s" % (sessions[0].harness, sessions[0].session_id)
        if sessions
        else docs[0][0]
    )
    log_recall(terms, top_reference, harness)

    event = str(
        payload.get("hook_event_name")
        or payload.get("hookEventName")
        or ""
    ).lower()
    emit_context(event, context)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
