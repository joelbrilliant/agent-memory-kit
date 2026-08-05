#!/usr/bin/env python3
"""Portable, evidence-backed learning loop over the shared session projection."""

from __future__ import annotations

import os
import sqlite3
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import _learning_policy as policy
from _learning_store import connect_learning, enforce_permissions
from session_continuity import connect_readonly, fts_terms, sync_index


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_SESSION_DB = SCRIPT_DIR / "sessions.db"

LearningError = policy.LearningError


def session_db_path() -> Path:
    return Path(os.environ.get("AGENT_SESSION_DB", str(DEFAULT_SESSION_DB)))


def usage_log_path() -> Path:
    return Path(
        os.environ.get("AGENT_MEMORY_USAGE_LOG", str(SCRIPT_DIR / "usage.log"))
    )


def _log_learning_operation(operation: str, claim_id: str) -> None:
    try:
        timestamp = datetime.now().isoformat(timespec="seconds")
        caller = os.environ.get("AGENT_MEMORY_CALLER", "-")
        with usage_log_path().open("a", encoding="utf-8") as fh:
            fh.write(
                "%s\tlearning:%s\tlearning://%s/%s\t%s\n"
                % (timestamp, operation, operation, claim_id, caller)
            )
    except OSError:
        pass


def _session_rows(
    conn: sqlite3.Connection,
    harness: str,
    session_id: str,
) -> list[dict[str, Any]]:
    exists = conn.execute(
        "SELECT 1 FROM session_sources WHERE harness = ? AND session_id = ?",
        (harness, session_id),
    ).fetchone()
    if not exists:
        raise LearningError(
            "session_not_found",
            "session %s/%s is not present in the session projection"
            % (harness, session_id),
        )
    rows = conn.execute(
        """
        SELECT id, harness, session_id, message_key, role, content, timestamp
        FROM session_messages
        WHERE harness = ? AND session_id = ?
        ORDER BY id
        """,
        (harness, session_id),
    ).fetchall()
    projected = []
    for row in rows:
        content = str(row[5])
        role = str(row[4])
        if not policy.safe_projected_row(role, content):
            continue
        projected.append(
            {
                "source_order": int(row[0]),
                "harness": str(row[1]),
                "session_id": str(row[2]),
                "message_key": str(row[3]),
                "role": role,
                "content": content,
                "message_content_hash": policy.content_hash(content),
                "timestamp": float(row[6] or 0),
            }
        )
    return projected


def _open_batch(
    conn: sqlite3.Connection,
    operator_id: str,
    harness: str,
    session_id: str,
) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT * FROM review_batches
        WHERE operator_id = ?
          AND source_harness = ?
          AND source_session_id = ?
          AND status = 'open'
        """,
        (operator_id, harness, session_id),
    ).fetchone()


def _batch_items(conn: sqlite3.Connection, batch_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT * FROM review_batch_items
        WHERE batch_id = ?
        ORDER BY order_index
        """,
        (batch_id,),
    ).fetchall()


def _batch_result(
    batch: sqlite3.Row,
    items: list[sqlite3.Row],
    source_conn: sqlite3.Connection,
) -> dict[str, Any]:
    rendered_items = []
    for item in items:
        source = source_conn.execute(
            """
            SELECT role, content FROM session_messages
            WHERE harness = ? AND session_id = ? AND message_key = ?
            """,
            (item["harness"], item["session_id"], item["message_key"]),
        ).fetchone()
        role = str(source[0]) if source else ""
        content = str(source[1]) if source else ""
        source_changed = (
            not source
            or role != item["role"]
            or policy.content_hash(content) != item["message_content_hash"]
            or not policy.safe_projected_row(role, content)
        )
        rendered_items.append(
            {
                "harness": item["harness"],
                "session_id": item["session_id"],
                "message_key": item["message_key"],
                "message_content_hash": item["message_content_hash"],
                "role": item["role"],
                "timestamp": item["timestamp"],
                "order_index": item["order_index"],
                "content": "" if source_changed else content,
                "source_changed": source_changed,
            }
        )
    return {
        "ok": True,
        "batch": {
            "id": batch["id"],
            "operator_id": batch["operator_id"],
            "source_harness": batch["source_harness"],
            "source_session_id": batch["source_session_id"],
            "reviewing_agent_id": batch["reviewing_agent_id"],
            "status": batch["status"],
            "created_at": batch["created_at"],
            "surfaced_at": batch["surfaced_at"],
            "surface_count": batch["surface_count"],
            "completed_at": batch["completed_at"],
            "terminal_at": batch["terminal_at"],
            "terminal_reason": batch["terminal_reason"],
        },
        "items": rendered_items,
        "submit_schema": {
            "kind": "preference",
            "confidence": "explicit",
            "scopes": sorted(policy.ALLOWED_SCOPES),
            "evidence": ["harness", "session_id", "message_key", "quote"],
        },
    }


REVIEW_MAX_SURFACE_ATTEMPTS = 2
REVIEW_RETRY_COOLDOWN_SECONDS = 300.0
REVIEW_TERMINAL_STATUSES = {
    "skipped_unrenderable",
    "delivery_failed",
}


def _terminalize_review_batch(
    conn: sqlite3.Connection,
    batch: sqlite3.Row,
    status: str,
    reason: str,
    now: float,
) -> int:
    items = _batch_items(conn, batch["id"])
    for item in items:
        conn.execute(
            """
            INSERT OR IGNORE INTO learning_message_state(
                operator_id, harness, session_id, message_key,
                message_content_hash, batch_id, disposition, recorded_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                batch["operator_id"],
                item["harness"],
                item["session_id"],
                item["message_key"],
                item["message_content_hash"],
                batch["id"],
                status,
                now,
            ),
        )
    conn.execute(
        """
        UPDATE review_batches
        SET status = ?, terminal_at = ?, terminal_reason = ?
        WHERE id = ? AND status = 'open'
        """,
        (status, now, reason, batch["id"]),
    )
    return len(items)


def claim_review_surface(
    *,
    batch_id: str,
    agent_id: str,
    now: float | None = None,
) -> dict[str, Any]:
    batch_id = policy.required_text("batch_id", batch_id)
    agent_id = policy.required_text("agent_id", agent_id)
    claimed_at = time.time() if now is None else float(now)
    conn, path = connect_learning()
    try:
        conn.execute("BEGIN IMMEDIATE")
        batch = conn.execute(
            "SELECT * FROM review_batches WHERE id = ?",
            (batch_id,),
        ).fetchone()
        if not batch:
            raise LearningError("batch_not_found", "review batch does not exist")
        if batch["reviewing_agent_id"] != agent_id:
            raise LearningError(
                "wrong_reviewing_agent",
                "agent_id does not own this review batch",
            )
        if batch["status"] != "open":
            conn.rollback()
            return {
                "ok": True,
                "action": "closed",
                "batch_id": batch_id,
                "status": batch["status"],
            }

        surface_count = int(batch["surface_count"])
        surfaced_at = batch["surfaced_at"]
        if surfaced_at is not None:
            elapsed = claimed_at - float(surfaced_at)
            if elapsed < REVIEW_RETRY_COOLDOWN_SECONDS:
                conn.rollback()
                return {
                    "ok": True,
                    "action": "cooldown",
                    "batch_id": batch_id,
                    "status": "open",
                    "surface_count": surface_count,
                    "retry_after": REVIEW_RETRY_COOLDOWN_SECONDS - elapsed,
                }

        if surface_count >= REVIEW_MAX_SURFACE_ATTEMPTS:
            reviewed_messages = _terminalize_review_batch(
                conn,
                batch,
                "delivery_failed",
                "surface_attempts_exhausted",
                claimed_at,
            )
            conn.commit()
            enforce_permissions(path)
            return {
                "ok": True,
                "action": "terminal",
                "batch_id": batch_id,
                "status": "delivery_failed",
                "surface_count": surface_count,
                "failed_messages": reviewed_messages,
            }

        updated = conn.execute(
            """
            UPDATE review_batches
            SET surfaced_at = ?, surface_count = surface_count + 1
            WHERE id = ? AND status = 'open' AND surface_count = ?
            """,
            (claimed_at, batch_id, surface_count),
        )
        if updated.rowcount != 1:
            conn.rollback()
            return {
                "ok": True,
                "action": "contended",
                "batch_id": batch_id,
                "status": "open",
            }
        conn.commit()
        enforce_permissions(path)
        return {
            "ok": True,
            "action": "surface",
            "batch_id": batch_id,
            "status": "open",
            "surface_count": surface_count + 1,
            "surfaced_at": claimed_at,
        }
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise
    finally:
        enforce_permissions(path)
        conn.close()


def fail_review_batch(
    *,
    batch_id: str,
    agent_id: str,
    status: str,
    reason: str,
    now: float | None = None,
) -> dict[str, Any]:
    batch_id = policy.required_text("batch_id", batch_id)
    agent_id = policy.required_text("agent_id", agent_id)
    reason = policy.required_text("reason", reason)
    if status not in REVIEW_TERMINAL_STATUSES:
        raise LearningError(
            "invalid_terminal_status",
            "review terminal status is not allowed",
        )
    terminal_at = time.time() if now is None else float(now)
    conn, path = connect_learning()
    try:
        conn.execute("BEGIN IMMEDIATE")
        batch = conn.execute(
            "SELECT * FROM review_batches WHERE id = ?",
            (batch_id,),
        ).fetchone()
        if not batch:
            raise LearningError("batch_not_found", "review batch does not exist")
        if batch["reviewing_agent_id"] != agent_id:
            raise LearningError(
                "wrong_reviewing_agent",
                "agent_id does not own this review batch",
            )
        if batch["status"] != "open":
            conn.rollback()
            return {
                "ok": True,
                "batch_id": batch_id,
                "status": batch["status"],
                "failed_messages": 0,
            }
        failed_messages = _terminalize_review_batch(
            conn,
            batch,
            status,
            reason,
            terminal_at,
        )
        conn.commit()
        enforce_permissions(path)
        return {
            "ok": True,
            "batch_id": batch_id,
            "status": status,
            "failed_messages": failed_messages,
        }
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise
    finally:
        enforce_permissions(path)
        conn.close()


def _selected_rows(
    rows: list[dict[str, Any]],
    known: set[tuple[str, str]],
    max_user_turns: int,
    max_chars: int,
) -> list[dict[str, Any]]:
    groups: list[list[dict[str, Any]]] = []
    for index, row in enumerate(rows):
        identity = (row["message_key"], row["message_content_hash"])
        if row["role"] != "user" or identity in known:
            continue
        group = [row]
        cursor = index + 1
        while cursor < len(rows) and rows[cursor]["role"] != "user":
            adjacent = rows[cursor]
            adjacent_identity = (
                adjacent["message_key"],
                adjacent["message_content_hash"],
            )
            if adjacent_identity not in known:
                group.append(adjacent)
            cursor += 1
        groups.append(group)

    selected: list[list[dict[str, Any]]] = []
    used_chars = 0
    for group in reversed(groups[-max_user_turns:]):
        remaining = max_chars - used_chars
        user_row = group[0]
        if len(user_row["content"]) > remaining:
            continue
        fitted = [user_row]
        used_chars += len(user_row["content"])
        for adjacent in group[1:]:
            if used_chars + len(adjacent["content"]) > max_chars:
                break
            fitted.append(adjacent)
            used_chars += len(adjacent["content"])
        selected.append(fitted)
        if used_chars >= max_chars:
            break
    flattened = [row for group in reversed(selected) for row in group]
    return flattened


def learn_tick(
    *,
    current_harness: str,
    current_session_id: str,
    agent_id: str,
    operator_id: str = "default",
    sync: bool = True,
    max_user_turns: int = 8,
    min_user_turns: int | None = None,
    max_chars: int = 6_000,
) -> dict[str, Any]:
    operator_id = policy.required_text("operator_id", operator_id)
    current_harness = policy.required_text("current_harness", current_harness)
    current_session_id = policy.required_text(
        "current_session_id",
        current_session_id,
    )
    agent_id = policy.required_text("agent_id", agent_id)
    max_user_turns = policy.bounded_positive(
        max_user_turns,
        8,
        policy.MAX_USER_TURNS,
        "max_user_turns",
    )
    if min_user_turns is not None:
        min_user_turns = policy.bounded_positive(
            min_user_turns,
            1,
            policy.MAX_USER_TURNS,
            "min_user_turns",
        )
    max_chars = policy.bounded_positive(
        max_chars,
        6_000,
        policy.MAX_REVIEW_CHARS,
        "max_chars",
    )

    source_path = session_db_path()
    if sync:
        sync_index(source_path)
    if not source_path.exists():
        raise LearningError("session_store_missing", "sessions.db does not exist")

    source_conn = connect_readonly(source_path)
    learning_conn, learning_path = connect_learning()
    try:
        source_conn.execute("BEGIN")
        rows = _session_rows(source_conn, current_harness, current_session_id)
        existing = _open_batch(
            learning_conn,
            operator_id,
            current_harness,
            current_session_id,
        )
        if existing:
            return _batch_result(
                existing,
                _batch_items(learning_conn, existing["id"]),
                source_conn,
            )

        batch_id = "batch_" + uuid.uuid4().hex
        now = time.time()
        learning_conn.execute("BEGIN IMMEDIATE")
        concurrent = _open_batch(
            learning_conn,
            operator_id,
            current_harness,
            current_session_id,
        )
        if concurrent:
            learning_conn.rollback()
            return _batch_result(
                concurrent,
                _batch_items(learning_conn, concurrent["id"]),
                source_conn,
            )
        state_rows = learning_conn.execute(
            """
            SELECT message_key, message_content_hash
            FROM learning_message_state
            WHERE operator_id = ? AND harness = ? AND session_id = ?
            """,
            (operator_id, current_harness, current_session_id),
        ).fetchall()
        known = {(row[0], row[1]) for row in state_rows}
        if min_user_turns is not None:
            unseen_user_turns = sum(
                1
                for row in rows
                if row["role"] == "user"
                and (row["message_key"], row["message_content_hash"])
                not in known
            )
            if unseen_user_turns < min_user_turns:
                learning_conn.rollback()
                return {
                    "ok": True,
                    "batch": None,
                    "items": [],
                    "submit_schema": None,
                }
        first_review = not state_rows
        selected = _selected_rows(
            rows,
            known,
            max_user_turns,
            max_chars,
        )
        if not selected:
            learning_conn.rollback()
            return {
                "ok": True,
                "batch": None,
                "items": [],
                "submit_schema": None,
            }
        learning_conn.execute(
            """
            INSERT INTO review_batches(
                id, operator_id, source_harness, source_session_id,
                reviewing_agent_id, status, created_at
            ) VALUES (?, ?, ?, ?, ?, 'open', ?)
            """,
            (
                batch_id,
                operator_id,
                current_harness,
                current_session_id,
                agent_id,
                now,
            ),
        )
        for order_index, row in enumerate(selected):
            learning_conn.execute(
                """
                INSERT INTO review_batch_items(
                    batch_id, harness, session_id, message_key,
                    message_content_hash, role, timestamp, order_index
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    batch_id,
                    row["harness"],
                    row["session_id"],
                    row["message_key"],
                    row["message_content_hash"],
                    row["role"],
                    row["timestamp"],
                    order_index,
                ),
            )
        if first_review:
            first_selected_order = min(row["source_order"] for row in selected)
            for row in rows:
                if row["source_order"] >= first_selected_order:
                    continue
                learning_conn.execute(
                    """
                    INSERT OR IGNORE INTO learning_message_state(
                        operator_id, harness, session_id, message_key,
                        message_content_hash, batch_id, disposition, recorded_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 'baseline_skipped', ?)
                    """,
                    (
                        operator_id,
                        row["harness"],
                        row["session_id"],
                        row["message_key"],
                        row["message_content_hash"],
                        batch_id,
                        now,
                    ),
                )
        learning_conn.commit()
        enforce_permissions(learning_path)
        batch = learning_conn.execute(
            "SELECT * FROM review_batches WHERE id = ?",
            (batch_id,),
        ).fetchone()
        return _batch_result(
            batch,
            _batch_items(learning_conn, batch_id),
            source_conn,
        )
    except Exception:
        if learning_conn.in_transaction:
            learning_conn.rollback()
        raise
    finally:
        enforce_permissions(learning_path)
        learning_conn.close()
        source_conn.close()


def _claim_result(conn: sqlite3.Connection, claim_id: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT * FROM learning_claims WHERE id = ?",
        (claim_id,),
    ).fetchone()
    return {
        "id": row["id"],
        "operator_id": row["operator_id"],
        "kind": row["kind"],
        "statement": row["statement"],
        "scope": row["scope"],
        "scope_key": row["scope_key"],
        "status": row["status"],
        "confidence": row["confidence"],
        "created_by_agent_id": row["created_by_agent_id"],
        "content_hash": row["content_hash"],
        "first_observed_at": row["first_observed_at"],
        "last_observed_at": row["last_observed_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def learn_submit(
    *,
    batch_id: str,
    agent_id: str,
    proposals: list[dict[str, Any]],
) -> dict[str, Any]:
    batch_id = policy.required_text("batch_id", batch_id)
    agent_id = policy.required_text("agent_id", agent_id)
    source_path = session_db_path()
    if not source_path.exists():
        raise LearningError("session_store_missing", "sessions.db does not exist")
    source_conn = connect_readonly(source_path)
    learning_conn, learning_path = connect_learning()
    try:
        source_conn.execute("BEGIN")
        batch = learning_conn.execute(
            "SELECT * FROM review_batches WHERE id = ?",
            (batch_id,),
        ).fetchone()
        if not batch:
            raise LearningError("batch_not_found", "review batch does not exist")
        if batch["status"] != "open":
            raise LearningError("batch_closed", "review batch is already completed")
        if batch["reviewing_agent_id"] != agent_id:
            raise LearningError(
                "wrong_reviewing_agent",
                "agent_id does not own this review batch",
            )
        items = _batch_items(learning_conn, batch_id)
        validated = policy.validate_proposals(proposals, items, source_conn)

        now = time.time()
        claim_ids = []
        learning_conn.execute("BEGIN IMMEDIATE")
        current_status = learning_conn.execute(
            "SELECT status FROM review_batches WHERE id = ?",
            (batch_id,),
        ).fetchone()
        if not current_status or current_status[0] != "open":
            raise LearningError("batch_closed", "review batch is already completed")
        for proposal in validated:
            evidence_times = [item["timestamp"] for item in proposal["evidence"]]
            first_observed = min(evidence_times)
            last_observed = max(evidence_times)
            existing = learning_conn.execute(
                """
                SELECT id, first_observed_at, last_observed_at
                FROM learning_claims
                WHERE operator_id = ? AND content_hash = ?
                """,
                (batch["operator_id"], proposal["content_hash"]),
            ).fetchone()
            if existing:
                claim_id = existing["id"]
                learning_conn.execute(
                    """
                    UPDATE learning_claims
                    SET first_observed_at = ?, last_observed_at = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        min(float(existing["first_observed_at"]), first_observed),
                        max(float(existing["last_observed_at"]), last_observed),
                        now,
                        claim_id,
                    ),
                )
            else:
                claim_id = "claim_" + uuid.uuid4().hex
                learning_conn.execute(
                    """
                    INSERT INTO learning_claims(
                        id, operator_id, kind, statement, scope, scope_key,
                        status, confidence, created_by_agent_id, content_hash,
                        first_observed_at, last_observed_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 'provisional', 'explicit', ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        claim_id,
                        batch["operator_id"],
                        proposal["kind"],
                        proposal["statement"],
                        proposal["scope"],
                        proposal["scope_key"],
                        agent_id,
                        proposal["content_hash"],
                        first_observed,
                        last_observed,
                        now,
                        now,
                    ),
                )
            for evidence in proposal["evidence"]:
                learning_conn.execute(
                    """
                    INSERT OR IGNORE INTO claim_evidence(
                        claim_id, harness, session_id, message_key, role, quote,
                        message_content_hash, timestamp
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        claim_id,
                        evidence["harness"],
                        evidence["session_id"],
                        evidence["message_key"],
                        evidence["role"],
                        evidence["quote"],
                        evidence["message_content_hash"],
                        evidence["timestamp"],
                    ),
                )
            if claim_id not in claim_ids:
                claim_ids.append(claim_id)

        for item in items:
            learning_conn.execute(
                """
                INSERT OR IGNORE INTO learning_message_state(
                    operator_id, harness, session_id, message_key,
                    message_content_hash, batch_id, disposition, recorded_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'reviewed', ?)
                """,
                (
                    batch["operator_id"],
                    item["harness"],
                    item["session_id"],
                    item["message_key"],
                    item["message_content_hash"],
                    batch_id,
                    now,
                ),
            )
        learning_conn.execute(
            """
            UPDATE review_batches
            SET status = 'completed', completed_at = ?
            WHERE id = ?
            """,
            (now, batch_id),
        )
        learning_conn.commit()
        enforce_permissions(learning_path)
        return {
            "ok": True,
            "batch_id": batch_id,
            "status": "completed",
            "claims": [_claim_result(learning_conn, claim_id) for claim_id in claim_ids],
            "reviewed_messages": len(items),
        }
    except Exception:
        if learning_conn.in_transaction:
            learning_conn.rollback()
        raise
    finally:
        enforce_permissions(learning_path)
        learning_conn.close()
        source_conn.close()


def _context_scope(scope: Any, scope_key: Any) -> tuple[str | None, str | None]:
    if scope in (None, ""):
        if scope_key not in (None, ""):
            raise LearningError(
                "invalid_scope_key",
                "scope_key requires a scope",
            )
        return None, None
    return policy.validate_scope(scope, scope_key)


def context_packet(
    *,
    requesting_harness: str,
    requesting_agent_id: str,
    task: str,
    operator_id: str = "default",
    scope: str | None = None,
    scope_key: str | None = None,
    max_chars: int = 1_200,
    include_provisional: bool = True,
    task_match_only: bool = False,
) -> dict[str, Any]:
    operator_id = policy.required_text("operator_id", operator_id)
    requesting_harness = policy.required_text(
        "requesting_harness",
        requesting_harness,
    )
    requesting_agent_id = policy.required_text(
        "requesting_agent_id",
        requesting_agent_id,
    )
    task = policy.required_text("task", task, 4_000)
    scope, scope_key = _context_scope(scope, scope_key)
    budget = policy.bounded_positive(
        max_chars,
        1_200,
        policy.MAX_CONTEXT_CHARS,
        "max_chars",
    )
    if not isinstance(include_provisional, bool):
        raise LearningError(
            "invalid_input",
            "include_provisional must be a boolean",
        )
    if not isinstance(task_match_only, bool):
        raise LearningError(
            "invalid_input",
            "task_match_only must be a boolean",
        )

    conn, path = connect_learning()
    try:
        allowed_statuses = ("confirmed", "provisional") if include_provisional else ("confirmed",)
        placeholders = ",".join("?" for _ in allowed_statuses)
        base_params: list[Any] = [operator_id, *allowed_statuses]
        rows = conn.execute(
            """
            SELECT * FROM learning_claims
            WHERE operator_id = ?
              AND status IN (%s)
            """
            % placeholders,
            base_params,
        ).fetchall()
        by_id = {row["id"]: row for row in rows}
        fts_scores: dict[str, float] = {}
        terms = fts_terms(task)
        if terms:
            expression = " OR ".join(
                '"%s"' % term.replace('"', '""') for term in terms
            )
            fts_rows = conn.execute(
                """
                SELECT c.id, bm25(learning_claims_fts)
                FROM learning_claims_fts
                JOIN learning_claims c ON c.rowid = learning_claims_fts.rowid
                WHERE learning_claims_fts MATCH ?
                  AND c.operator_id = ?
                  AND c.status IN (%s)
                """
                % placeholders,
                [expression, operator_id, *allowed_statuses],
            ).fetchall()
            fts_scores = {row[0]: float(row[1]) for row in fts_rows}

        candidates = []
        for claim_id, row in by_id.items():
            exact_scope = False
            if scope:
                exact_scope = row["scope"] == scope and (
                    scope != "domain" or row["scope_key"] == scope_key
                )
            is_global = row["scope"] == "global"
            if task_match_only and claim_id not in fts_scores:
                continue
            if not task_match_only and not (
                exact_scope or is_global or claim_id in fts_scores
            ):
                continue
            evidence = conn.execute(
                """
                SELECT harness, session_id, message_key, quote, timestamp
                FROM claim_evidence
                WHERE claim_id = ?
                ORDER BY timestamp DESC, harness, session_id, message_key, id
                LIMIT 1
                """,
                (claim_id,),
            ).fetchone()
            candidates.append(
                {
                    "row": row,
                    "exact_scope": exact_scope,
                    "global": is_global,
                    "fts_score": fts_scores.get(claim_id, float("inf")),
                    "evidence": evidence,
                }
            )
        candidates.sort(
            key=lambda item: (
                not item["exact_scope"],
                not item["global"],
                item["fts_score"],
                -float(item["row"]["last_observed_at"]),
                item["row"]["id"],
            )
        )

        heading = "Learning context (shadow mode):"
        lines = [heading]
        included = []
        used = len(heading)
        for candidate in candidates:
            row = candidate["row"]
            evidence = candidate["evidence"]
            reference = (
                "%s/%s/%s" % (evidence[0], evidence[1], evidence[2])
                if evidence
                else "unavailable"
            )
            scope_label = row["scope"]
            if row["scope_key"]:
                scope_label += ":" + row["scope_key"]
            line = "- [%s] %s (scope: %s; evidence: %s)" % (
                row["status"],
                row["statement"],
                scope_label,
                reference,
            )
            if used + 1 + len(line) > budget:
                continue
            lines.append(line)
            used += 1 + len(line)
            included.append(
                {
                    "id": row["id"],
                    "status": row["status"],
                    "statement": row["statement"],
                    "scope": row["scope"],
                    "scope_key": row["scope_key"],
                    "evidence_reference": reference,
                }
            )
        packet = "\n".join(lines) if included else ""
        return {
            "ok": True,
            "packet": packet,
            "claims": included,
            "request": {
                "operator_id": operator_id,
                "requesting_harness": requesting_harness,
                "requesting_agent_id": requesting_agent_id,
                "task": task,
                "scope": scope,
                "scope_key": scope_key,
                "include_provisional": include_provisional,
                "task_match_only": task_match_only,
                "max_chars": budget,
            },
        }
    finally:
        enforce_permissions(path)
        conn.close()


def learn_forget(
    *,
    operator_id: str = "default",
    claim_id: str,
) -> dict[str, Any]:
    operator_id = policy.required_text("operator_id", operator_id)
    claim_id = policy.required_text("claim_id", claim_id)
    conn, path = connect_learning()
    try:
        conn.execute("BEGIN IMMEDIATE")
        owner = conn.execute(
            "SELECT operator_id FROM learning_claims WHERE id = ?",
            (claim_id,),
        ).fetchone()
        if not owner:
            raise LearningError("claim_not_found", "claim does not exist")
        if owner["operator_id"] != operator_id:
            raise LearningError(
                "cross_operator_forget",
                "claim belongs to a different operator",
            )
        conn.execute("DELETE FROM learning_claims WHERE id = ?", (claim_id,))
        conn.commit()
        _log_learning_operation("forget", claim_id)
        return {
            "ok": True,
            "operator_id": operator_id,
            "claim_id": claim_id,
            "outcome": "forgotten",
        }
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise
    finally:
        enforce_permissions(path)
        conn.close()


def run_learning_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Dispatch one portable tool call and preserve stable structured errors."""

    if not isinstance(arguments, dict):
        return LearningError(
            "invalid_input",
            "tool arguments must be an object",
        ).as_result()
    try:
        if name == "learn_tick":
            return learn_tick(**arguments)
        if name == "learn_submit":
            return learn_submit(**arguments)
        if name == "context_packet":
            return context_packet(**arguments)
        if name == "learn_forget":
            return learn_forget(**arguments)
        raise LearningError("unknown_tool", "unknown learning tool: %s" % name)
    except LearningError as error:
        return error.as_result()
    except TypeError as error:
        message = str(error)
        if "keyword" not in message and "argument" not in message:
            raise
        return LearningError(
            "invalid_input",
            "tool arguments do not match the public interface",
        ).as_result()
