import hashlib
import os
import sqlite3
import tempfile
import threading
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from _learning_store import SCHEMA_VERSION, connect_learning, learning_db_path
from learning_loop import (
    LearningError,
    claim_review_surface,
    context_packet,
    fail_review_batch,
    learn_forget,
    learn_submit,
    learn_tick,
    session_db_path,
)
from session_continuity import connect


class LearningLoopTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.sessions_db = self.root / "sessions.db"
        self.learning_db = self.root / "learning.db"
        self.usage_log = self.root / "usage.log"
        conn = connect(self.sessions_db)
        conn.execute(
            """
            INSERT INTO session_sources(
                harness, session_id, source_path, fingerprint, title, cwd,
                started_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "codex",
                "codex-preference",
                str(self.root / "source.jsonl"),
                "fixture",
                "Preference fixture",
                "/tmp",
                1.0,
                2.0,
            ),
        )
        conn.execute(
            """
            INSERT INTO session_messages(
                harness, session_id, message_key, role, content, timestamp
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "codex",
                "codex-preference",
                "message-1",
                "user",
                "Use Celsius for weather reports.",
                1.0,
            ),
        )
        conn.commit()
        conn.close()
        self.environment = patch.dict(
            os.environ,
            {
                "AGENT_SESSION_DB": str(self.sessions_db),
                "AGENT_LEARNING_DB": str(self.learning_db),
                "AGENT_MEMORY_USAGE_LOG": str(self.usage_log),
            },
        )
        self.environment.start()

    def _append_message(
        self,
        message_key,
        role,
        content,
        timestamp,
        harness="codex",
        session_id="codex-preference",
    ):
        conn = sqlite3.connect(self.sessions_db)
        conn.execute(
            """
            INSERT INTO session_messages(
                harness, session_id, message_key, role, content, timestamp
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (harness, session_id, message_key, role, content, timestamp),
        )
        conn.commit()
        conn.close()

    def _tick(self, **overrides):
        arguments = {
            "current_harness": "codex",
            "current_session_id": "codex-preference",
            "agent_id": "agent-a",
            "sync": False,
        }
        arguments.update(overrides)
        return learn_tick(**arguments)

    def _proposal(
        self,
        statement="Use Celsius for weather reports.",
        scope="communication",
        message_key="message-1",
        quote="Use Celsius for weather reports.",
        **overrides,
    ):
        proposal = {
            "kind": "preference",
            "statement": statement,
            "scope": scope,
            "confidence": "explicit",
            "evidence": [
                {
                    "harness": "codex",
                    "session_id": "codex-preference",
                    "message_key": message_key,
                    "quote": quote,
                }
            ],
        }
        proposal.update(overrides)
        return proposal

    def _submit(self, tick=None, proposals=None, agent_id="agent-a"):
        tick = tick or self._tick()
        if proposals is None:
            proposals = [self._proposal()]
        return learn_submit(
            batch_id=tick["batch"]["id"],
            agent_id=agent_id,
            proposals=proposals,
        )

    def _db_rows(self, sql, parameters=()):
        conn = sqlite3.connect(self.learning_db)
        rows = conn.execute(sql, parameters).fetchall()
        conn.close()
        return rows

    def tearDown(self):
        self.environment.stop()
        self.tempdir.cleanup()

    def test_submit_accepts_exact_user_evidence(self):
        result = self._submit()

        self.assertTrue(result["ok"])
        self.assertEqual(result["claims"][0]["status"], "provisional")

    def test_learn_tick_reads_real_session_projection_keys(self):
        result = self._tick()

        self.assertEqual(result["batch"]["source_harness"], "codex")
        self.assertEqual(result["batch"]["source_session_id"], "codex-preference")
        self.assertEqual(result["items"][0]["message_key"], "message-1")
        self.assertEqual(len(result["items"][0]["message_content_hash"]), 64)

    def test_learn_tick_waits_for_minimum_unseen_user_turns(self):
        for index in range(2, 8):
            self._append_message(
                "user-%d" % index,
                "user",
                "Preference turn %d" % index,
                float(index),
            )

        below_minimum = self._tick(min_user_turns=8)

        self.assertIsNone(below_minimum["batch"])
        self.assertEqual(
            self._db_rows("SELECT COUNT(*) FROM review_batches")[0][0],
            0,
        )
        self.assertEqual(
            self._db_rows("SELECT COUNT(*) FROM learning_message_state")[0][0],
            0,
        )

        self._append_message(
            "user-8",
            "user",
            "Preference turn 8",
            8.0,
        )
        at_minimum = self._tick(min_user_turns=8)
        repeated = self._tick(min_user_turns=8, agent_id="agent-b")

        self.assertIsNotNone(at_minimum["batch"])
        self.assertEqual(at_minimum["batch"]["id"], repeated["batch"]["id"])

    def test_learn_tick_without_minimum_keeps_existing_behaviour(self):
        result = self._tick()

        self.assertIsNotNone(result["batch"])

    def test_learn_tick_excludes_generated_tool_system_and_secret_rows(self):
        self._append_message("tool-1", "tool", "tool output", 2.0)
        self._append_message("system-1", "system", "system prompt", 3.0)
        self._append_message(
            "generated-1",
            "user",
            "[CONTEXT COMPACTION - REFERENCE ONLY] generated summary",
            4.0,
        )
        self._append_message(
            "secret-1",
            "user",
            "export DEMO_API_KEY=abcdef0123456789ZZZZ",
            5.0,
        )

        result = self._tick()

        self.assertEqual(
            [item["message_key"] for item in result["items"]],
            ["message-1"],
        )

    def test_learn_tick_returns_existing_open_batch(self):
        first = self._tick()
        second = self._tick(agent_id="different-agent")

        self.assertEqual(first["batch"]["id"], second["batch"]["id"])
        self.assertEqual(second["batch"]["reviewing_agent_id"], "agent-a")
        self.assertEqual(
            self._db_rows("SELECT COUNT(*) FROM learning_message_state")[0][0],
            0,
        )

    def test_existing_batch_does_not_render_changed_or_unsafe_source_content(self):
        first = self._tick()
        secret = "export DEMO_API_KEY=abcdef0123456789ZZZZ"
        conn = sqlite3.connect(self.sessions_db)
        conn.execute(
            """
            UPDATE session_messages SET content = ?
            WHERE harness = 'codex'
              AND session_id = 'codex-preference'
              AND message_key = 'message-1'
            """,
            (secret,),
        )
        conn.commit()
        conn.close()

        repeated = self._tick()

        self.assertEqual(first["batch"]["id"], repeated["batch"]["id"])
        self.assertTrue(repeated["items"][0]["source_changed"])
        self.assertEqual(repeated["items"][0]["content"], "")
        self.assertNotIn(secret, str(repeated))

    def test_tick_does_not_rebatch_messages_completed_while_waiting(self):
        reached_batch_creation = threading.Event()
        release_batch_creation = threading.Event()
        result = {}
        errors = []
        original_uuid4 = uuid.uuid4

        def gated_uuid4():
            if threading.current_thread().name == "stale-tick":
                reached_batch_creation.set()
                if not release_batch_creation.wait(timeout=5):
                    raise AssertionError("timed out waiting for concurrent completion")
            return original_uuid4()

        def run_stale_tick():
            try:
                result.update(self._tick())
            except Exception as error:
                errors.append(error)

        with patch("learning_loop.uuid.uuid4", side_effect=gated_uuid4):
            worker = threading.Thread(target=run_stale_tick, name="stale-tick")
            worker.start()
            self.assertTrue(reached_batch_creation.wait(timeout=5))
            completed = self._tick()
            self._submit(completed, [])
            release_batch_creation.set()
            worker.join(timeout=5)

        self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])
        self.assertIsNone(result["batch"])
        self.assertEqual(
            self._db_rows("SELECT COUNT(*) FROM review_batches")[0][0],
            1,
        )

    def test_failed_submit_keeps_batch_open_and_messages_unreviewed(self):
        tick = self._tick()
        with self.assertRaisesRegex(LearningError, "exact normalised substring"):
            self._submit(
                tick,
                [self._proposal(quote="This quote was never said")],
            )

        self.assertEqual(
            self._db_rows("SELECT status FROM review_batches")[0][0],
            "open",
        )
        self.assertEqual(
            self._db_rows("SELECT COUNT(*) FROM learning_message_state")[0][0],
            0,
        )
        retried = self._submit(tick)
        self.assertEqual(retried["status"], "completed")

    def test_empty_submit_completes_batch_and_marks_messages_reviewed(self):
        tick = self._tick()
        result = self._submit(tick, [])

        self.assertEqual(result["claims"], [])
        self.assertEqual(result["reviewed_messages"], 1)
        self.assertEqual(
            self._db_rows(
                "SELECT disposition FROM learning_message_state"
            )[0][0],
            "reviewed",
        )
        self.assertIsNone(self._tick()["batch"])

    def test_surface_retry_exhaustion_is_terminal_and_allows_a_later_batch(self):
        tick = self._tick()
        batch_id = tick["batch"]["id"]

        first = claim_review_surface(
            batch_id=batch_id,
            agent_id="agent-a",
            now=1_000.0,
        )
        cooldown = claim_review_surface(
            batch_id=batch_id,
            agent_id="agent-a",
            now=1_100.0,
        )
        second = claim_review_surface(
            batch_id=batch_id,
            agent_id="agent-a",
            now=1_300.0,
        )
        terminal = claim_review_surface(
            batch_id=batch_id,
            agent_id="agent-a",
            now=1_600.0,
        )

        self.assertEqual(first["action"], "surface")
        self.assertEqual(cooldown["action"], "cooldown")
        self.assertEqual(second["action"], "surface")
        self.assertEqual(terminal["status"], "delivery_failed")
        self.assertEqual(
            self._db_rows(
                """
                SELECT status, surface_count, terminal_reason
                FROM review_batches WHERE id = ?
                """,
                (batch_id,),
            )[0],
            ("delivery_failed", 2, "surface_attempts_exhausted"),
        )
        self.assertEqual(
            self._db_rows(
                "SELECT disposition FROM learning_message_state"
            )[0][0],
            "delivery_failed",
        )

        for index in range(2, 10):
            self._append_message(
                "fresh-%d" % index,
                "user",
                "Fresh preference turn %d" % index,
                2_000.0 + index,
            )
        later = self._tick(min_user_turns=8)
        self.assertNotEqual(later["batch"]["id"], batch_id)

    def test_surface_claim_is_atomic_across_concurrent_hooks(self):
        tick = self._tick()
        batch_id = tick["batch"]["id"]
        barrier = threading.Barrier(2)
        results = []
        errors = []

        def claim():
            try:
                barrier.wait(timeout=5)
                results.append(
                    claim_review_surface(
                        batch_id=batch_id,
                        agent_id="agent-a",
                        now=1_000.0,
                    )
                )
            except Exception as error:
                errors.append(error)

        workers = [threading.Thread(target=claim) for _ in range(2)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=5)

        self.assertFalse(any(worker.is_alive() for worker in workers))
        self.assertEqual(errors, [])
        self.assertEqual(
            sorted(result["action"] for result in results),
            ["cooldown", "surface"],
        )
        self.assertEqual(
            self._db_rows(
                "SELECT surface_count FROM review_batches WHERE id = ?",
                (batch_id,),
            )[0][0],
            1,
        )

    def test_unrenderable_terminal_is_not_counted_as_completed(self):
        tick = self._tick()
        batch_id = tick["batch"]["id"]

        result = fail_review_batch(
            batch_id=batch_id,
            agent_id="agent-a",
            status="skipped_unrenderable",
            reason="review_context_exceeds_limit",
            now=2_000.0,
        )

        self.assertEqual(result["status"], "skipped_unrenderable")
        self.assertEqual(
            self._db_rows(
                """
                SELECT status, completed_at, terminal_reason
                FROM review_batches WHERE id = ?
                """,
                (batch_id,),
            )[0],
            ("skipped_unrenderable", None, "review_context_exceeds_limit"),
        )
        self.assertEqual(
            self._db_rows(
                "SELECT disposition FROM learning_message_state"
            )[0][0],
            "skipped_unrenderable",
        )

    def test_successful_submit_after_surface_completes_exactly_once(self):
        tick = self._tick()
        batch_id = tick["batch"]["id"]
        claim_review_surface(
            batch_id=batch_id,
            agent_id="agent-a",
            now=1_000.0,
        )

        result = self._submit(tick, [])
        with self.assertRaisesRegex(LearningError, "already completed"):
            self._submit(tick, [])

        self.assertEqual(result["status"], "completed")
        self.assertEqual(
            self._db_rows(
                """
                SELECT status, surface_count, completed_at, terminal_at
                FROM review_batches WHERE id = ?
                """,
                (batch_id,),
            )[0][:2],
            ("completed", 1),
        )
        self.assertEqual(
            self._db_rows(
                "SELECT disposition FROM learning_message_state"
            )[0][0],
            "reviewed",
        )

    def test_v1_schema_migrates_all_learning_state_without_fk_damage(self):
        connection = sqlite3.connect(self.learning_db)
        connection.executescript(
            """
            CREATE TABLE learning_schema (
                version INTEGER PRIMARY KEY,
                applied_at REAL NOT NULL
            );
            INSERT INTO learning_schema VALUES (1, 1.0);
            CREATE TABLE review_batches (
                id TEXT PRIMARY KEY,
                operator_id TEXT NOT NULL,
                source_harness TEXT NOT NULL,
                source_session_id TEXT NOT NULL,
                reviewing_agent_id TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('open', 'completed')),
                created_at REAL NOT NULL,
                completed_at REAL
            );
            CREATE UNIQUE INDEX one_open_review_batch
            ON review_batches(operator_id, source_harness, source_session_id)
            WHERE status = 'open';
            CREATE TABLE review_batch_items (
                batch_id TEXT NOT NULL,
                harness TEXT NOT NULL,
                session_id TEXT NOT NULL,
                message_key TEXT NOT NULL,
                message_content_hash TEXT NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                timestamp REAL NOT NULL,
                order_index INTEGER NOT NULL,
                PRIMARY KEY (batch_id, order_index),
                UNIQUE (batch_id, harness, session_id, message_key,
                        message_content_hash),
                FOREIGN KEY (batch_id) REFERENCES review_batches(id)
                    ON DELETE CASCADE
            );
            CREATE TABLE learning_message_state (
                operator_id TEXT NOT NULL,
                harness TEXT NOT NULL,
                session_id TEXT NOT NULL,
                message_key TEXT NOT NULL,
                message_content_hash TEXT NOT NULL,
                batch_id TEXT NOT NULL,
                disposition TEXT NOT NULL CHECK (
                    disposition IN ('reviewed', 'baseline_skipped')
                ),
                recorded_at REAL NOT NULL,
                PRIMARY KEY (operator_id, harness, session_id, message_key,
                             message_content_hash),
                FOREIGN KEY (batch_id) REFERENCES review_batches(id)
            );
            CREATE TABLE learning_claims (
                id TEXT PRIMARY KEY,
                operator_id TEXT NOT NULL,
                kind TEXT NOT NULL CHECK (kind = 'preference'),
                statement TEXT NOT NULL,
                scope TEXT NOT NULL CHECK (
                    scope IN ('global', 'communication', 'work_style', 'domain')
                ),
                scope_key TEXT,
                status TEXT NOT NULL CHECK (
                    status IN ('provisional', 'confirmed', 'rejected', 'superseded')
                ),
                confidence TEXT NOT NULL CHECK (
                    confidence IN ('explicit', 'inferred')
                ),
                created_by_agent_id TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                first_observed_at REAL NOT NULL,
                last_observed_at REAL NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                UNIQUE (operator_id, content_hash)
            );
            CREATE TABLE claim_evidence (
                id INTEGER PRIMARY KEY,
                claim_id TEXT NOT NULL,
                harness TEXT NOT NULL,
                session_id TEXT NOT NULL,
                message_key TEXT NOT NULL,
                role TEXT NOT NULL CHECK (role = 'user'),
                quote TEXT NOT NULL CHECK (length(quote) <= 500),
                message_content_hash TEXT NOT NULL,
                timestamp REAL NOT NULL,
                FOREIGN KEY (claim_id) REFERENCES learning_claims(id)
                    ON DELETE CASCADE
            );
            INSERT INTO review_batches VALUES (
                'batch-v1', 'default', 'codex', 'codex-preference',
                'agent-a', 'completed', 1.0, 2.0
            );
            INSERT INTO review_batch_items VALUES (
                'batch-v1', 'codex', 'codex-preference', 'message-1',
                'message-hash', 'user', 1.0, 0
            );
            INSERT INTO learning_message_state VALUES (
                'default', 'codex', 'codex-preference', 'message-1',
                'message-hash', 'batch-v1', 'reviewed', 2.0
            );
            INSERT INTO learning_claims VALUES (
                'claim-v1', 'default', 'preference', 'Keep replies short.',
                'communication', NULL, 'provisional', 'explicit', 'agent-a',
                'claim-hash', 1.0, 1.0, 2.0, 2.0
            );
            INSERT INTO claim_evidence VALUES (
                1, 'claim-v1', 'codex', 'codex-preference', 'message-1',
                'user', 'Keep replies short.', 'message-hash', 1.0
            );
            """
        )
        connection.commit()
        connection.close()

        migrated, path = connect_learning()
        try:
            self.assertEqual(
                migrated.execute(
                    "SELECT MAX(version) FROM learning_schema"
                ).fetchone()[0],
                SCHEMA_VERSION,
            )
            self.assertEqual(
                migrated.execute(
                    "SELECT COUNT(*) FROM review_batch_items"
                ).fetchone()[0],
                1,
            )
            self.assertEqual(
                migrated.execute(
                    "SELECT COUNT(*) FROM learning_message_state"
                ).fetchone()[0],
                1,
            )
            self.assertEqual(
                migrated.execute(
                    "SELECT COUNT(*) FROM learning_claims"
                ).fetchone()[0],
                1,
            )
            self.assertEqual(
                migrated.execute(
                    "SELECT COUNT(*) FROM claim_evidence"
                ).fetchone()[0],
                1,
            )
            self.assertEqual(
                migrated.execute("PRAGMA foreign_key_check").fetchall(),
                [],
            )
        finally:
            migrated.close()
            self.assertEqual(path, self.learning_db)

    def test_empty_tick_does_not_create_a_batch(self):
        conn = sqlite3.connect(self.sessions_db)
        conn.execute("DELETE FROM session_messages")
        conn.execute(
            """
            INSERT INTO session_messages(
                harness, session_id, message_key, role, content, timestamp
            ) VALUES ('codex', 'codex-preference', 'assistant-only',
                      'assistant', 'No operator turn exists.', 2.0)
            """
        )
        conn.commit()
        conn.close()

        result = self._tick()

        self.assertIsNone(result["batch"])
        self.assertEqual(
            self._db_rows("SELECT COUNT(*) FROM review_batches")[0][0],
            0,
        )

    def test_tick_never_offers_a_partially_rendered_message(self):
        self._append_message(
            "assistant-long",
            "assistant",
            "Acknowledged. " + ("x" * 200),
            2.0,
        )

        result = self._tick(max_chars=100)

        self.assertEqual(
            [item["message_key"] for item in result["items"]],
            ["message-1"],
        )
        self.assertLessEqual(sum(len(item["content"]) for item in result["items"]), 100)
        for item in result["items"]:
            self.assertEqual(
                hashlib.sha256(item["content"].encode("utf-8")).hexdigest(),
                item["message_content_hash"],
            )

    def test_over_budget_user_message_remains_eligible_for_a_larger_tick(self):
        too_small = self._tick(max_chars=20)

        self.assertIsNone(too_small["batch"])
        self.assertEqual(
            self._db_rows("SELECT COUNT(*) FROM learning_message_state")[0][0],
            0,
        )
        retried = self._tick(max_chars=100)
        self.assertEqual(
            [item["message_key"] for item in retried["items"]],
            ["message-1"],
        )

    def test_first_tick_reviews_recent_turns_and_marks_older_messages_baseline_skipped(self):
        for index in range(2, 8):
            self._append_message(
                "user-%d" % index,
                "user",
                "Preference turn %d" % index,
                float(index * 2),
            )
            self._append_message(
                "assistant-%d" % index,
                "assistant",
                "Acknowledged turn %d" % index,
                float(index * 2 + 1),
            )

        result = self._tick(max_user_turns=2)

        self.assertEqual(
            [item["message_key"] for item in result["items"]],
            ["user-6", "assistant-6", "user-7", "assistant-7"],
        )
        skipped = self._db_rows(
            """
            SELECT message_key FROM learning_message_state
            WHERE disposition = 'baseline_skipped'
            ORDER BY message_key
            """
        )
        self.assertIn(("message-1",), skipped)
        self.assertIn(("user-5",), skipped)
        self.assertNotIn(("user-6",), skipped)

    def test_changed_message_hash_becomes_eligible_again(self):
        first = self._tick()
        old_hash = first["items"][0]["message_content_hash"]
        self._submit(first, [])
        conn = sqlite3.connect(self.sessions_db)
        conn.execute(
            """
            UPDATE session_messages
            SET content = ?
            WHERE harness = 'codex'
              AND session_id = 'codex-preference'
              AND message_key = 'message-1'
            """,
            ("Use Fahrenheit for weather reports.",),
        )
        conn.commit()
        conn.close()

        second = self._tick()

        self.assertIsNotNone(second["batch"])
        self.assertNotEqual(second["items"][0]["message_content_hash"], old_hash)

    def test_submit_rejects_assistant_evidence(self):
        self._append_message(
            "assistant-1",
            "assistant",
            "I will use Celsius for weather reports.",
            2.0,
        )
        tick = self._tick()

        with self.assertRaisesRegex(LearningError, "operator-authored"):
            self._submit(
                tick,
                [
                    self._proposal(
                        message_key="assistant-1",
                        quote="I will use Celsius for weather reports.",
                    )
                ],
            )

    def test_submit_rejects_forged_quote(self):
        tick = self._tick()

        with self.assertRaisesRegex(LearningError, "exact normalised substring"):
            self._submit(tick, [self._proposal(quote="Forged preference")])

    def test_submit_rejects_a_paraphrased_statement(self):
        tick = self._tick()

        with self.assertRaisesRegex(
            LearningError,
            "normalised operator evidence quote",
        ):
            self._submit(
                tick,
                [self._proposal(statement="Keep normal replies concise.")],
            )

        self.assertEqual(
            self._db_rows("SELECT status FROM review_batches")[0][0],
            "open",
        )
        self.assertEqual(
            self._db_rows("SELECT COUNT(*) FROM learning_message_state")[0][0],
            0,
        )

    def test_submit_rejects_missing_source_evidence(self):
        tick = self._tick()
        conn = sqlite3.connect(self.sessions_db)
        conn.execute(
            """
            DELETE FROM session_messages
            WHERE harness = 'codex'
              AND session_id = 'codex-preference'
              AND message_key = 'message-1'
            """
        )
        conn.commit()
        conn.close()

        with self.assertRaisesRegex(LearningError, "source evidence is missing"):
            self._submit(tick)

    def test_submit_rejects_generated_evidence(self):
        tick = self._tick()
        generated = "[CONTEXT COMPACTION - REFERENCE ONLY] generated summary"
        conn = sqlite3.connect(self.sessions_db)
        conn.execute(
            """
            UPDATE session_messages SET content = ?
            WHERE harness = 'codex'
              AND session_id = 'codex-preference'
              AND message_key = 'message-1'
            """,
            (generated,),
        )
        conn.commit()
        conn.close()
        new_hash = hashlib.sha256(generated.encode("utf-8")).hexdigest()
        conn = sqlite3.connect(self.learning_db)
        conn.execute(
            """
            UPDATE review_batch_items SET message_content_hash = ?
            WHERE message_key = 'message-1'
            """,
            (new_hash,),
        )
        conn.commit()
        conn.close()

        with self.assertRaisesRegex(LearningError, "generated or secret-shaped"):
            self._submit(tick, [self._proposal(quote=generated)])

    def test_submit_rejects_evidence_outside_batch(self):
        self._append_message(
            "recent-message",
            "user",
            "A recent preference selected for this batch.",
            2.0,
        )
        tick = self._tick(max_user_turns=1)

        with self.assertRaisesRegex(LearningError, "not a member"):
            self._submit(
                tick,
                [
                    self._proposal(
                        message_key="message-1",
                        quote="Use Celsius for weather reports.",
                    )
                ],
            )

    def test_submit_rejects_wrong_agent_and_keeps_batch_open(self):
        tick = self._tick()

        with self.assertRaisesRegex(LearningError, "does not own"):
            self._submit(tick, agent_id="agent-b")

        self.assertEqual(
            self._db_rows("SELECT status FROM review_batches")[0][0],
            "open",
        )

    def test_submit_rejects_invalid_kind_scope_and_lengths(self):
        tick = self._tick()
        invalid = [
            self._proposal(kind="personality"),
            self._proposal(scope="private"),
            self._proposal(statement="x" * 501),
            self._proposal(scope="domain"),
            self._proposal(scope="domain", scope_key="x" * 101),
            self._proposal(scope_key="writing"),
            self._proposal(quote="x" * 501),
        ]

        for proposal in invalid:
            with self.subTest(proposal=proposal):
                with self.assertRaises(LearningError):
                    self._submit(tick, [proposal])
        self.assertEqual(
            self._db_rows("SELECT COUNT(*) FROM learning_claims")[0][0],
            0,
        )

    def test_submit_rejects_inferred_confidence(self):
        tick = self._tick()

        with self.assertRaisesRegex(LearningError, "only explicit"):
            self._submit(tick, [self._proposal(confidence="inferred")])

    def test_submit_rejects_secret_evidence_without_partial_write(self):
        self._append_message(
            "message-2",
            "user",
            "Display dates in ISO 8601 format.",
            2.0,
        )
        tick = self._tick()
        secret = "export DEMO_API_KEY=abcdef0123456789ZZZZ"
        conn = sqlite3.connect(self.sessions_db)
        conn.execute(
            """
            UPDATE session_messages SET content = ?
            WHERE harness = 'codex'
              AND session_id = 'codex-preference'
              AND message_key = 'message-1'
            """,
            (secret,),
        )
        conn.commit()
        conn.close()
        new_hash = hashlib.sha256(secret.encode("utf-8")).hexdigest()
        conn = sqlite3.connect(self.learning_db)
        conn.execute(
            """
            UPDATE review_batch_items SET message_content_hash = ?
            WHERE message_key = 'message-1'
            """,
            (new_hash,),
        )
        conn.commit()
        conn.close()

        with self.assertRaisesRegex(LearningError, "secret-shaped"):
            self._submit(
                tick,
                [
                    self._proposal(
                        statement="Display dates in ISO 8601 format.",
                        scope="global",
                        message_key="message-2",
                        quote="Display dates in ISO 8601 format.",
                    ),
                    self._proposal(quote=secret),
                ],
            )

        self.assertEqual(
            self._db_rows("SELECT COUNT(*) FROM learning_claims")[0][0],
            0,
        )
        self.assertEqual(
            self._db_rows("SELECT status FROM review_batches")[0][0],
            "open",
        )

    def test_submit_rejects_secret_claim_fields_without_partial_write(self):
        tick = self._tick()
        secret = "export DEMO_API_KEY=abcdef0123456789ZZZZ"
        unsafe = [
            self._proposal(statement=secret),
            self._proposal(scope="domain", scope_key=secret),
        ]

        for proposal in unsafe:
            with self.subTest(proposal=proposal):
                with self.assertRaisesRegex(LearningError, "secret-shaped"):
                    self._submit(tick, [proposal])

        self.assertEqual(
            self._db_rows("SELECT COUNT(*) FROM learning_claims")[0][0],
            0,
        )
        self.assertEqual(
            self._db_rows("SELECT COUNT(*) FROM claim_evidence")[0][0],
            0,
        )
        self.assertEqual(
            self._db_rows("SELECT status FROM review_batches")[0][0],
            "open",
        )

    def test_database_failure_rolls_back_claim_and_review_state(self):
        tick = self._tick()
        conn = sqlite3.connect(self.learning_db)
        conn.execute(
            """
            CREATE TRIGGER reject_test_evidence
            BEFORE INSERT ON claim_evidence
            BEGIN
                SELECT RAISE(ABORT, 'injected evidence failure');
            END
            """
        )
        conn.commit()
        conn.close()

        with self.assertRaisesRegex(sqlite3.IntegrityError, "injected evidence failure"):
            self._submit(tick)

        self.assertEqual(
            self._db_rows("SELECT COUNT(*) FROM learning_claims")[0][0],
            0,
        )
        self.assertEqual(
            self._db_rows("SELECT COUNT(*) FROM claim_evidence")[0][0],
            0,
        )
        self.assertEqual(
            self._db_rows("SELECT COUNT(*) FROM learning_message_state")[0][0],
            0,
        )
        self.assertEqual(
            self._db_rows("SELECT status FROM review_batches")[0][0],
            "open",
        )

    def test_duplicate_claim_adds_evidence_without_duplicate_row(self):
        first = self._tick()
        first_result = self._submit(first)
        self._append_message(
            "message-2",
            "user",
            "Use Celsius for weather reports.",
            3.0,
        )
        second = self._tick()
        second_result = self._submit(
            second,
            [
                self._proposal(
                    message_key="message-2",
                    quote="Use Celsius for weather reports.",
                )
            ],
        )

        self.assertEqual(
            first_result["claims"][0]["id"],
            second_result["claims"][0]["id"],
        )
        self.assertEqual(
            self._db_rows("SELECT COUNT(*) FROM learning_claims")[0][0],
            1,
        )
        self.assertEqual(
            self._db_rows("SELECT COUNT(*) FROM claim_evidence")[0][0],
            2,
        )

    def test_context_packet_excludes_unrelated_claims(self):
        self._submit()

        result = context_packet(
            requesting_harness="hermes",
            requesting_agent_id="agent-b",
            task="Plan a database migration strategy",
        )

        self.assertEqual(result["packet"], "")
        self.assertEqual(result["claims"], [])

    def test_context_packet_task_match_only_excludes_unrelated_global_claims(self):
        matching = self._submit()["claims"][0]
        self._append_message(
            "message-2",
            "user",
            "Use Australian English spelling.",
            2.0,
        )
        global_claim = self._submit(
            self._tick(),
            [
                self._proposal(
                    statement="Use Australian English spelling.",
                    scope="global",
                    message_key="message-2",
                    quote="Use Australian English spelling.",
                )
            ],
        )["claims"][0]

        result = context_packet(
            requesting_harness="hermes",
            requesting_agent_id="agent-b",
            task="Weather reports in Celsius",
            task_match_only=True,
        )

        self.assertEqual([claim["id"] for claim in result["claims"]], [matching["id"]])
        self.assertNotIn(global_claim["id"], [claim["id"] for claim in result["claims"]])

    def test_learn_forget_removes_claim_evidence_and_fts_without_content_receipt(self):
        claim = self._submit()["claims"][0]
        claim_id = claim["id"]

        with self.assertRaisesRegex(LearningError, "operator"):
            learn_forget(operator_id="other-operator", claim_id=claim_id)

        receipt = learn_forget(operator_id="default", claim_id=claim_id)

        self.assertEqual(
            receipt,
            {
                "ok": True,
                "operator_id": "default",
                "claim_id": claim_id,
                "outcome": "forgotten",
            },
        )
        self.assertEqual(
            self._db_rows("SELECT COUNT(*) FROM learning_claims")[0][0],
            0,
        )
        self.assertEqual(
            self._db_rows("SELECT COUNT(*) FROM claim_evidence")[0][0],
            0,
        )
        self.assertEqual(
            self._db_rows(
                "SELECT COUNT(*) FROM learning_claims_fts WHERE learning_claims_fts MATCH ?",
                ("paragraphs",),
            )[0][0],
            0,
        )
        self.assertNotIn(claim["statement"], str(receipt))
        usage = self.usage_log.read_text(encoding="utf-8")
        self.assertIn("learning://forget/%s" % claim_id, usage)
        self.assertNotIn(claim["statement"], usage)

    def test_context_packet_includes_global_and_exact_scope_without_fts_overlap(self):
        self._append_message(
            "message-2",
            "user",
            "Use Australian English spelling.",
            2.0,
        )
        self._submit(
            self._tick(max_user_turns=1),
            proposals=[
                self._proposal(
                    statement="Use Australian English spelling.",
                    scope="global",
                    message_key="message-2",
                    quote="Use Australian English spelling.",
                )
            ]
        )
        self._append_message(
            "message-3",
            "user",
            "Put measurement units after each weather value.",
            3.0,
        )
        tick = self._tick()
        self._submit(
            tick,
            [
                self._proposal(
                    statement="Put measurement units after each weather value.",
                    message_key="message-3",
                    quote="Put measurement units after each weather value.",
                )
            ],
        )

        result = context_packet(
            requesting_harness="claude",
            requesting_agent_id="agent-b",
            task="Plan a database migration strategy",
            scope="communication",
        )

        self.assertEqual(len(result["claims"]), 2)
        self.assertEqual(result["claims"][0]["scope"], "communication")
        self.assertEqual(result["claims"][1]["scope"], "global")

    def test_context_packet_respects_hard_character_cap(self):
        self._submit(
            proposals=[
                self._proposal(
                    statement="Use Celsius for weather reports.",
                    scope="global",
                )
            ]
        )

        result = context_packet(
            requesting_harness="grok",
            requesting_agent_id="agent-b",
            task="Write a weather report with measurement units",
            max_chars=140,
        )

        self.assertLessEqual(len(result["packet"]), 140)
        oversized = context_packet(
            requesting_harness="grok",
            requesting_agent_id="agent-b",
            task="Write a weather report with measurement units",
            max_chars=999_999,
        )
        self.assertEqual(oversized["request"]["max_chars"], 1_800)
        self.assertLessEqual(len(oversized["packet"]), 1_800)

    def test_context_packet_excludes_rejected_and_superseded(self):
        result = self._submit()
        claim_id = result["claims"][0]["id"]
        conn = sqlite3.connect(self.learning_db)
        conn.execute(
            "UPDATE learning_claims SET status = 'rejected' WHERE id = ?",
            (claim_id,),
        )
        conn.commit()
        conn.close()

        rejected = context_packet(
            requesting_harness="hermes",
            requesting_agent_id="agent-b",
            task="Write a weather report in Celsius",
        )
        self.assertEqual(rejected["claims"], [])

        conn = sqlite3.connect(self.learning_db)
        conn.execute(
            "UPDATE learning_claims SET status = 'superseded' WHERE id = ?",
            (claim_id,),
        )
        conn.commit()
        conn.close()
        superseded = context_packet(
            requesting_harness="hermes",
            requesting_agent_id="agent-b",
            task="Write a weather report in Celsius",
        )
        self.assertEqual(superseded["claims"], [])

    def test_context_packet_does_not_cross_operator_id(self):
        tick = self._tick(operator_id="operator-a")
        self._submit(tick)

        result = context_packet(
            operator_id="operator-b",
            requesting_harness="hermes",
            requesting_agent_id="agent-b",
            task="Write a weather report in Celsius",
        )

        self.assertEqual(result["claims"], [])

    def test_learning_database_and_sidecars_are_owner_only(self):
        tick = self._tick()
        keeper = sqlite3.connect(self.learning_db)
        try:
            keeper.execute("PRAGMA journal_mode=WAL")
            for suffix in ("-shm", "-wal"):
                Path(str(self.learning_db) + suffix).chmod(0o644)
            self._submit(tick)
            context_packet(
                requesting_harness="hermes",
                requesting_agent_id="agent-b",
                task="Write a weather report in Celsius",
            )

            candidates = [
                self.learning_db,
                Path(str(self.learning_db) + "-shm"),
                Path(str(self.learning_db) + "-wal"),
            ]
            for path in candidates:
                self.assertTrue(path.exists(), path)
                self.assertEqual(path.stat().st_mode & 0o777, 0o600, path)
        finally:
            keeper.close()

    def test_learning_core_uses_configured_temp_paths(self):
        result = self._submit()

        self.assertEqual(learning_db_path(), self.learning_db)
        self.assertEqual(session_db_path(), self.sessions_db)
        self.assertTrue(self.learning_db.exists())
        self.assertTrue(self.sessions_db.exists())
        self.assertEqual(
            self._db_rows(
                "SELECT id FROM learning_claims WHERE id = ?",
                (result["claims"][0]["id"],),
            ),
            [(result["claims"][0]["id"],)],
        )


if __name__ == "__main__":
    unittest.main()
