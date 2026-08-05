"""Private deterministic validation policy for learning submissions."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any

from session_continuity import safe_content


ALLOWED_KINDS = {"preference"}
ALLOWED_SCOPES = {"global", "communication", "work_style", "domain"}
MAX_USER_TURNS = 12
MAX_REVIEW_CHARS = 8_000
MAX_CONTEXT_CHARS = 1_800
MAX_STATEMENT_CHARS = 500
MAX_QUOTE_CHARS = 500
MAX_SCOPE_KEY_CHARS = 100
MAX_ID_CHARS = 200


class LearningError(ValueError):
    """A stable validation error shared by the CLI and MCP surfaces."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message

    def as_result(self) -> dict[str, Any]:
        return {
            "ok": False,
            "error": {"code": self.code, "message": self.message},
        }


def normalise_whitespace(value: str) -> str:
    return " ".join(value.split())


def content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _claim_hash(
    kind: str,
    statement: str,
    scope: str,
    scope_key: str | None,
) -> str:
    identity = {
        "kind": kind,
        "statement": statement.casefold(),
        "scope": scope,
        "scope_key": scope_key.casefold() if scope_key else None,
    }
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":"))
    return content_hash(encoded)


def required_text(name: str, value: Any, maximum: int = MAX_ID_CHARS) -> str:
    if not isinstance(value, str):
        raise LearningError("invalid_input", "%s must be a string" % name)
    cleaned = value.strip()
    if not cleaned:
        raise LearningError("invalid_input", "%s is required" % name)
    if len(cleaned) > maximum:
        raise LearningError(
            "invalid_input",
            "%s exceeds %d characters" % (name, maximum),
        )
    return cleaned


def bounded_positive(value: Any, default: int, maximum: int, name: str) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        raise LearningError("invalid_input", "%s must be an integer" % name)
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise LearningError("invalid_input", "%s must be an integer" % name)
    if parsed < 1:
        raise LearningError("invalid_input", "%s must be positive" % name)
    return min(parsed, maximum)


def safe_projected_row(role: str, content: str) -> bool:
    return role in {"user", "assistant"} and safe_content(content.lstrip()) is not None


def validate_scope(scope: Any, scope_key: Any) -> tuple[str, str | None]:
    scope = required_text("scope", scope, 32)
    if scope not in ALLOWED_SCOPES:
        raise LearningError("invalid_scope", "unsupported scope: %s" % scope)
    if scope == "domain":
        key = required_text("scope_key", scope_key, MAX_SCOPE_KEY_CHARS)
        return scope, key
    if scope_key not in (None, ""):
        raise LearningError(
            "invalid_scope_key",
            "scope_key is allowed only for domain scope",
        )
    return scope, None


def _source_message(
    conn: sqlite3.Connection,
    harness: str,
    session_id: str,
    message_key: str,
) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT role, content, timestamp
        FROM session_messages
        WHERE harness = ? AND session_id = ? AND message_key = ?
        """,
        (harness, session_id, message_key),
    ).fetchone()


def validate_proposals(
    proposals: Any,
    batch_items: list[sqlite3.Row],
    source_conn: sqlite3.Connection,
) -> list[dict[str, Any]]:
    if not isinstance(proposals, list):
        raise LearningError("invalid_proposals", "proposals must be a list")
    membership = {
        (item["harness"], item["session_id"], item["message_key"]): item
        for item in batch_items
    }
    validated = []
    for proposal in proposals:
        if not isinstance(proposal, dict):
            raise LearningError("invalid_proposal", "each proposal must be an object")
        kind = required_text("kind", proposal.get("kind"), 32)
        if kind not in ALLOWED_KINDS:
            raise LearningError("invalid_kind", "unsupported claim kind: %s" % kind)
        statement = normalise_whitespace(
            required_text(
                "statement",
                proposal.get("statement"),
                MAX_STATEMENT_CHARS,
            )
        )
        if safe_content(statement.lstrip()) is None:
            raise LearningError(
                "claim_unsafe",
                "claim statement is generated or secret-shaped",
            )
        scope, scope_key = validate_scope(
            proposal.get("scope"),
            proposal.get("scope_key"),
        )
        if scope_key and safe_content(scope_key.lstrip()) is None:
            raise LearningError(
                "claim_unsafe",
                "scope_key is generated or secret-shaped",
            )
        confidence = required_text("confidence", proposal.get("confidence"), 32)
        if confidence != "explicit":
            raise LearningError(
                "inferred_not_allowed",
                "automatic learning accepts only explicit preference claims",
            )
        evidence_refs = proposal.get("evidence")
        if not isinstance(evidence_refs, list) or not evidence_refs:
            raise LearningError(
                "evidence_required",
                "each proposal needs at least one evidence reference",
            )
        evidence = []
        seen_evidence = set()
        for reference in evidence_refs:
            if not isinstance(reference, dict):
                raise LearningError(
                    "invalid_evidence",
                    "each evidence reference must be an object",
                )
            harness = required_text("evidence.harness", reference.get("harness"))
            session_id = required_text(
                "evidence.session_id",
                reference.get("session_id"),
            )
            message_key = required_text(
                "evidence.message_key",
                reference.get("message_key"),
            )
            member = membership.get((harness, session_id, message_key))
            if not member:
                raise LearningError(
                    "evidence_outside_batch",
                    "submitted evidence is not a member of the review batch",
                )
            source = _source_message(source_conn, harness, session_id, message_key)
            if not source:
                raise LearningError("evidence_missing", "source evidence is missing")
            role = str(source[0])
            content = str(source[1])
            if content_hash(content) != member["message_content_hash"]:
                raise LearningError(
                    "evidence_changed",
                    "source evidence changed after the batch was created",
                )
            if role != "user":
                raise LearningError(
                    "evidence_not_user",
                    "evidence must be operator-authored",
                )
            if not safe_projected_row(role, content):
                raise LearningError(
                    "evidence_unsafe",
                    "source evidence is generated or secret-shaped",
                )
            quote = normalise_whitespace(
                required_text(
                    "evidence.quote",
                    reference.get("quote"),
                    MAX_QUOTE_CHARS,
                )
            )
            if safe_content(quote.lstrip()) is None:
                raise LearningError(
                    "evidence_unsafe",
                    "evidence quote is generated or secret-shaped",
                )
            if quote not in normalise_whitespace(content):
                raise LearningError(
                    "quote_mismatch",
                    "evidence quote is not an exact normalised substring",
                )
            identity = (
                harness,
                session_id,
                message_key,
                member["message_content_hash"],
                quote,
            )
            if identity in seen_evidence:
                continue
            seen_evidence.add(identity)
            evidence.append(
                {
                    "harness": harness,
                    "session_id": session_id,
                    "message_key": message_key,
                    "role": role,
                    "quote": quote,
                    "message_content_hash": member["message_content_hash"],
                    "timestamp": float(source[2] or 0),
                }
            )
        if statement not in {item["quote"] for item in evidence}:
            raise LearningError(
                "statement_not_evidence_quote",
                "claim statement must exactly match one normalised operator evidence quote",
            )
        validated.append(
            {
                "kind": kind,
                "statement": statement,
                "scope": scope,
                "scope_key": scope_key,
                "confidence": confidence,
                "content_hash": _claim_hash(kind, statement, scope, scope_key),
                "evidence": evidence,
            }
        )
    return validated
