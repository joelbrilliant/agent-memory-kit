import importlib.util
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from learning_loop import learn_submit, learn_tick
from session_continuity import (
    SessionRoots,
    list_sessions,
    recall_sessions,
    sync_index,
)


class SessionContinuityTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.session_db = self.root / "sessions.db"
        self.hermes_db = self.root / "hermes-state.db"
        self.claude_root = self.root / "claude-projects"
        self.codex_root = self.root / "codex-sessions"
        self.grok_root = self.root / "grok-sessions"
        self.claude_root.mkdir()
        self.codex_root.mkdir()
        self.grok_root.mkdir()
        self._write_hermes_fixture()
        self._write_claude_fixture()
        self._write_codex_fixture()
        self._write_grok_fixture()
        self.roots = SessionRoots(
            hermes_db=self.hermes_db,
            claude_root=self.claude_root,
            codex_root=self.codex_root,
            grok_root=self.grok_root,
        )

    def tearDown(self):
        self.tempdir.cleanup()

    def _jsonl(self, path, rows):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "".join(json.dumps(row) + "\n" for row in rows),
            encoding="utf-8",
        )

    def _write_hermes_fixture(self):
        conn = sqlite3.connect(self.hermes_db)
        conn.executescript(
            """
            CREATE TABLE sessions (
                id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                started_at REAL NOT NULL,
                ended_at REAL,
                title TEXT,
                cwd TEXT
            );
            CREATE TABLE messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT,
                timestamp REAL NOT NULL
            );
            """
        )
        conn.executemany(
            "INSERT INTO sessions(id, source, started_at, title, cwd) "
            "VALUES (?, ?, ?, ?, ?)",
            [
                (
                    "hermes-human",
                    "telegram",
                    1000.0,
                    "Hermes rollover",
                    "/work/hermes",
                ),
                (
                    "hermes-cron",
                    "cron",
                    1001.0,
                    "Nightly noise",
                    "/work/hermes",
                ),
            ],
        )
        conn.executemany(
            "INSERT INTO messages(session_id, role, content, timestamp) "
            "VALUES (?, ?, ?, ?)",
            [
                (
                    "hermes-human",
                    "user",
                    "hermescanary rollover threshold follows context pressure\n\n"
                    "[Your active task list was preserved across context compression]\n"
                    "- [ ] generatedsuffixhermes (pending)",
                    1002.0,
                ),
                (
                    "hermes-human",
                    "assistant",
                    "Keep the logical conversation while rotating context segments.",
                    1003.0,
                ),
                (
                    "hermes-human",
                    "tool",
                    "toolnoisehermes must never be indexed",
                    1004.0,
                ),
                (
                    "hermes-human",
                    "assistant",
                    "[CONTEXT COMPACTION - REFERENCE ONLY] generatednoisehermes",
                    1005.0,
                ),
                (
                    "hermes-human",
                    "user",
                    "<user_info>generatedenvelopehermes</user_info>",
                    1005.5,
                ),
                (
                    "hermes-human",
                    "user",
                    "[Your active task list was preserved across context compression]\n"
                    "- [ ] generatedtaskhermes (pending)",
                    1005.6,
                ),
                (
                    "hermes-human",
                    "user",
                    "Review the conversation above and update the skill library. "
                    "generatedreviewhermes",
                    1005.8,
                ),
                (
                    "hermes-cron",
                    "user",
                    "cronnoisehermes must never be indexed",
                    1006.0,
                ),
            ],
        )
        conn.commit()
        conn.close()

    def _write_claude_fixture(self):
        self.claude_path = self.claude_root / "project-a" / "claude-one.jsonl"
        self._jsonl(
            self.claude_path,
            [
                {
                    "type": "user",
                    "sessionId": "claude-one",
                    "cwd": "/work/claude",
                    "timestamp": "2026-07-28T01:00:00Z",
                    "isSidechain": False,
                    "message": {
                        "role": "user",
                        "content": "claudecanary checkpoint every exit path",
                    },
                },
                {
                    "type": "assistant",
                    "sessionId": "claude-one",
                    "cwd": "/work/claude",
                    "timestamp": "2026-07-28T01:01:00Z",
                    "isSidechain": False,
                    "message": {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "thinking",
                                "thinking": "reasoningnoiseclaude",
                            },
                            {
                                "type": "text",
                                "text": "Persist the cursor on failure as well as success.",
                            },
                            {
                                "type": "tool_use",
                                "name": "terminal",
                                "input": {"command": "toolnoiseclaude"},
                            },
                        ],
                    },
                },
                {
                    "type": "user",
                    "sessionId": "claude-one",
                    "cwd": "/work/claude",
                    "timestamp": "2026-07-28T01:02:00Z",
                    "isSidechain": True,
                    "message": {
                        "role": "user",
                        "content": "sidechainnoiseclaude",
                    },
                },
                {
                    "type": "user",
                    "sessionId": "claude-one",
                    "cwd": "/work/claude",
                    "timestamp": "2026-07-28T01:02:01Z",
                    "isSidechain": False,
                    "isCompactSummary": True,
                    "message": {
                        "role": "user",
                        "content": "compactsummarynoiseclaude",
                    },
                },
                {
                    "type": "user",
                    "sessionId": "claude-one",
                    "cwd": "/work/claude",
                    "timestamp": "2026-07-28T01:02:02Z",
                    "isSidechain": False,
                    "isMeta": True,
                    "message": {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "metanoiseclaude"}
                        ],
                    },
                },
                {
                    "type": "user",
                    "sessionId": "claude-one",
                    "cwd": "/work/claude",
                    "timestamp": "2026-07-28T01:03:00Z",
                    "isSidechain": False,
                    "message": {
                        "role": "user",
                        "content": "<user_info>generatedenvelopeclaude</user_info>",
                    },
                },
            ],
        )

    def _write_codex_fixture(self):
        self.codex_path = (
            self.codex_root / "2026" / "07" / "28" / "rollout-codex-one.jsonl"
        )
        self._jsonl(
            self.codex_path,
            [
                {
                    "type": "session_meta",
                    "timestamp": "2026-07-28T02:00:00Z",
                    "payload": {
                        "id": "codex-one",
                        "cwd": "/work/codex",
                        "timestamp": "2026-07-28T02:00:00Z",
                    },
                },
                {
                    "type": "response_item",
                    "timestamp": "2026-07-28T02:00:01Z",
                    "payload": {
                        "type": "message",
                        "role": "developer",
                        "content": [
                            {"type": "input_text", "text": "developernoisecodex"}
                        ],
                    },
                },
                {
                    "type": "response_item",
                    "timestamp": "2026-07-28T02:00:02Z",
                    "payload": {
                        "type": "message",
                        "role": "user",
                        "content": [
                            {
                                "type": "input_text",
                                "text": "<app-context>bootstrapnoisecodex</app-context>",
                            },
                            {
                                "type": "input_text",
                                "text": "codexcanary central session index",
                            },
                        ],
                    },
                },
                {
                    "type": "response_item",
                    "timestamp": "2026-07-28T02:00:02Z",
                    "payload": {
                        "type": "message",
                        "role": "user",
                        "content": [
                            {
                                "type": "input_text",
                                "text": "<user_info>generatedenvelopecodex</user_info>",
                            }
                        ],
                    },
                },
                {
                    "type": "response_item",
                    "timestamp": "2026-07-28T02:00:02Z",
                    "payload": {
                        "type": "message",
                        "role": "user",
                        "content": [
                            {
                                "type": "input_text",
                                "text": (
                                    "[System note: previous turn interrupted] "
                                    "generatednotecodex"
                                ),
                            }
                        ],
                    },
                },
                {
                    "type": "response_item",
                    "timestamp": "2026-07-28T02:00:03Z",
                    "payload": {
                        "type": "reasoning",
                        "summary": [{"text": "reasoningnoisecodex"}],
                    },
                },
                {
                    "type": "response_item",
                    "timestamp": "2026-07-28T02:00:04Z",
                    "payload": {
                        "type": "message",
                        "role": "assistant",
                        "phase": "final_answer",
                        "content": [
                            {
                                "type": "output_text",
                                "text": "All harnesses should read the same local brain.",
                            }
                        ],
                    },
                },
            ],
        )

    def _write_grok_fixture(self):
        session_dir = self.grok_root / "%2Fwork%2Fgrok" / "grok-one"
        self.grok_path = session_dir / "chat_history.jsonl"
        self._jsonl(
            self.grok_path,
            [
                {"type": "system", "content": "systemnoisegrok"},
                {
                    "type": "user",
                    "synthetic_reason": "project_instructions",
                    "content": [{"type": "text", "text": "syntheticnoisegrok"}],
                },
                {
                    "type": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "grokcanary local deterministic retrieval",
                        }
                    ],
                },
                {
                    "type": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "<user_info>generatedenvelopegrok</user_info>",
                        }
                    ],
                },
                {
                    "type": "assistant",
                    "content": "The memory layer does not need an LLM.",
                },
                {"type": "tool_result", "content": "toolnoisegrok"},
            ],
        )
        (session_dir / "summary.json").write_text(
            json.dumps(
                {
                    "created_at": "2026-07-28T03:00:00Z",
                    "updated_at": "2026-07-28T03:01:00Z",
                    "last_active_at": "2026-07-28T03:01:00Z",
                    "generated_title": "Grok continuity",
                    "git_root_dir": "/work/grok/",
                }
            ),
            encoding="utf-8",
        )

    def test_indexes_all_four_harnesses_and_excludes_generated_context(self):
        result = sync_index(self.session_db, self.roots)
        self.assertEqual(
            result.sessions_by_harness,
            {"claude": 1, "codex": 1, "grok": 1, "hermes": 1},
        )
        conn = sqlite3.connect(self.session_db)
        stored_messages = conn.execute(
            "SELECT count(*) FROM session_messages"
        ).fetchone()[0]
        conn.close()
        self.assertEqual(result.indexed_messages, stored_messages)
        for path in (
            self.session_db,
            Path(str(self.session_db) + "-shm"),
            Path(str(self.session_db) + "-wal"),
        ):
            if path.exists():
                self.assertEqual(path.stat().st_mode & 0o077, 0, path)

        for query, harness in [
            ("hermescanary rollover", "hermes"),
            ("claudecanary checkpoint", "claude"),
            ("codexcanary central", "codex"),
            ("grokcanary deterministic", "grok"),
        ]:
            hits = recall_sessions(
                self.session_db,
                query,
                limit=3,
                sync=False,
            )
            self.assertTrue(hits, query)
            self.assertEqual(hits[0].harness, harness)

        for forbidden in [
            "toolnoisehermes",
            "generatednoisehermes",
            "generatedenvelopehermes",
            "generatedtaskhermes",
            "generatedsuffixhermes",
            "generatedreviewhermes",
            "cronnoisehermes",
            "reasoningnoiseclaude",
            "toolnoiseclaude",
            "sidechainnoiseclaude",
            "compactsummarynoiseclaude",
            "metanoiseclaude",
            "generatedenvelopeclaude",
            "developernoisecodex",
            "bootstrapnoisecodex",
            "generatednotecodex",
            "generatedenvelopecodex",
            "reasoningnoisecodex",
            "systemnoisegrok",
            "syntheticnoisegrok",
            "generatedenvelopegrok",
            "toolnoisegrok",
        ]:
            self.assertEqual(
                recall_sessions(
                    self.session_db,
                    forbidden,
                    limit=3,
                    sync=False,
                ),
                [],
                forbidden,
            )

        genuine = recall_sessions(
            self.session_db,
            "hermescanary rollover threshold",
            limit=3,
            sync=False,
        )
        self.assertTrue(genuine)
        self.assertIn(
            "hermescanary rollover threshold follows context pressure",
            genuine[0].messages[0].text,
        )
        self.assertNotIn("active task list", genuine[0].messages[0].text)

    def test_incremental_sync_replaces_changed_jsonl_without_duplicates(self):
        sync_index(self.session_db, self.roots)
        before = list_sessions(self.session_db, limit=20)
        self.assertEqual(len(before), 4)

        with self.claude_path.open("a", encoding="utf-8") as fh:
            fh.write(
                json.dumps(
                    {
                        "type": "user",
                        "sessionId": "claude-one",
                        "cwd": "/work/claude",
                        "timestamp": "2026-07-28T01:03:00Z",
                        "isSidechain": False,
                        "message": {
                            "role": "user",
                            "content": "incrementalcanary appears once",
                        },
                    }
                )
                + "\n"
            )
        os.utime(self.claude_path, None)

        sync_index(self.session_db, self.roots)
        sync_index(self.session_db, self.roots)
        hits = recall_sessions(
            self.session_db,
            "incrementalcanary",
            limit=10,
            sync=False,
        )
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].session_id, "claude-one")

    def test_session_database_permissions_are_owner_only(self):
        sync_index(self.session_db, self.roots)
        keeper = sqlite3.connect(self.session_db)
        try:
            keeper.execute("PRAGMA journal_mode=WAL")
            keeper.execute(
                "UPDATE session_sources SET title = title WHERE 1 = 0"
            )
            keeper.commit()
            targets = [
                self.session_db,
                Path(str(self.session_db) + "-shm"),
                Path(str(self.session_db) + "-wal"),
            ]
            for target in targets:
                if target.exists():
                    target.chmod(0o644)

            sync_index(self.session_db, self.roots)

            for target in targets:
                if target.exists():
                    self.assertEqual(
                        target.stat().st_mode & 0o777,
                        0o600,
                        target,
                    )
        finally:
            keeper.close()

    def test_secret_messages_are_not_indexed(self):
        with self.claude_path.open("a", encoding="utf-8") as fh:
            fh.write(
                json.dumps(
                    {
                        "type": "user",
                        "sessionId": "claude-one",
                        "cwd": "/work/claude",
                        "timestamp": "2026-07-28T01:04:00Z",
                        "isSidechain": False,
                        "message": {
                            "role": "user",
                            "content": (
                                "secretcanary "
                                "export DEMO_API_KEY=abcdef0123456789ZZZZ"
                            ),
                        },
                    }
                )
                + "\n"
            )
        sync_index(self.session_db, self.roots)
        self.assertEqual(
            recall_sessions(
                self.session_db,
                "secretcanary",
                limit=3,
                sync=False,
            ),
            [],
        )

    def test_recall_groups_a_session_and_excludes_the_current_session(self):
        sync_index(self.session_db, self.roots)
        hits = recall_sessions(
            self.session_db,
            "context rollover logical conversation",
            limit=5,
            sync=False,
        )
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].session_id, "hermes-human")
        self.assertGreaterEqual(len(hits[0].messages), 2)

        excluded = recall_sessions(
            self.session_db,
            "context rollover logical conversation",
            limit=5,
            current_harness="hermes",
            current_session_id="hermes-human",
            sync=False,
        )
        self.assertEqual(excluded, [])

    def test_recall_collapses_identical_cross_session_evidence(self):
        duplicate_path = self.codex_root / "duplicate.jsonl"
        self._jsonl(
            duplicate_path,
            [
                {
                    "type": "session_meta",
                    "timestamp": "2026-07-29T02:00:00Z",
                    "payload": {
                        "id": "codex-duplicate",
                        "cwd": "/work/codex",
                        "timestamp": "2026-07-29T02:00:00Z",
                    },
                },
                {
                    "type": "response_item",
                    "timestamp": "2026-07-29T02:00:02Z",
                    "payload": {
                        "type": "message",
                        "role": "user",
                        "content": [
                            {
                                "type": "input_text",
                                "text": "codexcanary central session index",
                            }
                        ],
                    },
                },
            ],
        )
        distinct_path = self.codex_root / "distinct.jsonl"
        self._jsonl(
            distinct_path,
            [
                {
                    "type": "session_meta",
                    "timestamp": "2026-07-30T02:00:00Z",
                    "payload": {
                        "id": "codex-distinct",
                        "cwd": "/work/codex",
                        "timestamp": "2026-07-30T02:00:00Z",
                    },
                },
                {
                    "type": "response_item",
                    "timestamp": "2026-07-30T02:00:02Z",
                    "payload": {
                        "type": "message",
                        "role": "user",
                        "content": [
                            {
                                "type": "input_text",
                                "text": (
                                    "codexcanary central session index has "
                                    "independent evidence"
                                ),
                            }
                        ],
                    },
                },
            ],
        )

        sync_index(self.session_db, self.roots)
        hits = recall_sessions(
            self.session_db,
            "codexcanary central session index",
            limit=5,
            sync=False,
        )

        self.assertEqual(len(hits), 2)
        duplicate_ids = {"codex-one", "codex-duplicate"}
        self.assertEqual(len(duplicate_ids & {hit.session_id for hit in hits}), 1)
        self.assertIn("codex-distinct", {hit.session_id for hit in hits})

    def test_recall_reads_existing_index_when_refresh_is_not_writable(self):
        sync_index(self.session_db, self.roots)
        with patch(
            "session_continuity.sync_index",
            side_effect=sqlite3.OperationalError(
                "attempt to write a readonly database"
            ),
        ):
            hits = recall_sessions(
                self.session_db,
                "claudecanary checkpoint",
                limit=3,
                sync=True,
                roots=self.roots,
            )
        self.assertTrue(hits)
        self.assertEqual(hits[0].session_id, "claude-one")

    def _run_hook(self, payload, harness, extra_env=None):
        sync_index(self.session_db, self.roots)
        env = os.environ.copy()
        env.update(
            {
                "AGENT_MEMORY_DB": str(self.root / "missing-docs.db"),
                "AGENT_SESSION_DB": str(self.session_db),
                "AGENT_MEMORY_HARNESS": harness,
                "HERMES_SESSION_DB": str(self.hermes_db),
                "CLAUDE_PROJECTS_ROOT": str(self.claude_root),
                "CODEX_SESSIONS_ROOT": str(self.codex_root),
                "GROK_SESSIONS_ROOT": str(self.grok_root),
                "AGENT_MEMORY_HOOK_LOG": str(self.root / "hook.log"),
            }
        )
        if extra_env:
            env.update(extra_env)
        hook = (
            Path(__file__).resolve().parents[1]
            / "hooks"
            / "claude-recall-hook.py"
        )
        return subprocess.run(
            [sys.executable, str(hook)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            env=env,
            check=True,
        ).stdout.strip()

    def test_mcp_session_recall_uses_the_shared_local_index(self):
        env = os.environ.copy()
        env.update(
            {
                "AGENT_SESSION_DB": str(self.session_db),
                "AGENT_MEMORY_USAGE_LOG": str(self.root / "usage.log"),
                "HERMES_SESSION_DB": str(self.hermes_db),
                "CLAUDE_PROJECTS_ROOT": str(self.claude_root),
                "CODEX_SESSIONS_ROOT": str(self.codex_root),
                "GROK_SESSIONS_ROOT": str(self.grok_root),
            }
        )
        server = Path(__file__).resolve().parents[1] / "mcp_server.py"
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "session_recall",
                "arguments": {
                    "query": "codexcanary central session index",
                    "k": 3,
                },
            },
        }
        completed = subprocess.run(
            [sys.executable, str(server)],
            input=json.dumps(request) + "\n",
            capture_output=True,
            text=True,
            env=env,
            check=True,
        )
        response = json.loads(completed.stdout)
        self.assertFalse(response["result"]["isError"])
        text = response["result"]["content"][0]["text"]
        self.assertIn("[codex]", text)
        self.assertIn("codex-one", text)

    def _append_hermes_user(self, content, timestamp):
        conn = sqlite3.connect(self.hermes_db)
        conn.execute(
            "INSERT INTO messages(session_id, role, content, timestamp) "
            "VALUES (?, ?, ?, ?)",
            ("hermes-human", "user", content, timestamp),
        )
        conn.commit()
        conn.close()

    def _append_claude_user(self, index, content):
        with self.claude_path.open("a", encoding="utf-8") as fh:
            fh.write(
                json.dumps(
                    {
                        "type": "user",
                        "sessionId": "claude-one",
                        "cwd": "/work/claude",
                        "timestamp": "2026-07-28T01:%02d:00Z" % index,
                        "isSidechain": False,
                        "uuid": "claude-auto-%d" % index,
                        "message": {"role": "user", "content": content},
                    }
                )
                + "\n"
            )

    def _append_grok_user(self, content):
        with self.grok_path.open("a", encoding="utf-8") as fh:
            fh.write(
                json.dumps(
                    {
                        "type": "user",
                        "content": [{"type": "text", "text": content}],
                    }
                )
                + "\n"
            )

    def _automatic_env(self):
        return {
            "AGENT_MEMORY_AUTOMATIC_LEARNING": "1",
            "AGENT_LEARNING_DB": str(self.root / "learning.db"),
        }

    def _hook_context(self, output, hermes=False):
        payload = json.loads(output)
        if hermes:
            return payload["context"]
        return payload["hookSpecificOutput"]["additionalContext"]

    def test_hook_emits_native_claude_and_hermes_response_shapes(self):
        claude_output = self._run_hook(
            {
                "hook_event_name": "UserPromptSubmit",
                "session_id": "claude-current",
                "prompt": (
                    "Please resume the claudecanary checkpoint "
                    "and every exit path rule"
                ),
            },
            "claude",
        )
        claude_payload = json.loads(claude_output)
        context = claude_payload["hookSpecificOutput"]["additionalContext"]
        self.assertIn("[claude]", context)
        self.assertIn("claude-one", context)

        hermes_output = self._run_hook(
            {
                "hook_event_name": "pre_llm_call",
                "session_id": "hermes-current",
                "cwd": "/work/new",
                "extra": {
                    "user_message": (
                        "Please resume the grokcanary local "
                        "deterministic retrieval work"
                    ),
                    "platform": "telegram",
                },
            },
            "hermes",
        )
        hermes_payload = json.loads(hermes_output)
        self.assertIn("[grok]", hermes_payload["context"])
        self.assertIn("grok-one", hermes_payload["context"])

    def test_hook_skips_internal_harness_prompts_before_learning(self):
        prompts = [
            "Review the conversation above and update the skill library. Be active.",
            "Review the conversation above and consider saving to memory if appropriate.",
            "Review the conversation above and update two things: memory and skills.",
        ]
        learning_db = self.root / "learning.db"
        for prompt in prompts:
            with self.subTest(prompt=prompt):
                output = self._run_hook(
                    {
                        "hook_event_name": "pre_llm_call",
                        "session_id": "hermes-human",
                        "extra": {"user_message": prompt},
                    },
                    "hermes",
                    self._automatic_env(),
                )
                self.assertEqual(output, "")
                self.assertFalse(learning_db.exists())

    def test_hook_strips_generated_task_suffix_but_keeps_user_prompt(self):
        output = self._run_hook(
            {
                "hook_event_name": "pre_llm_call",
                "session_id": "hermes-current",
                "extra": {
                    "user_message": (
                        "Please resume the grokcanary local deterministic retrieval work\n\n"
                        "[Your active task list was preserved across context compression]\n"
                        "- [ ] stale-task should not affect retrieval (pending)"
                    )
                },
            },
            "hermes",
        )
        context = self._hook_context(output, hermes=True)
        self.assertIn("[grok]", context)
        self.assertNotIn("stale-task", context)

    def test_hook_does_not_automatically_inject_skills(self):
        document_db = self.root / "documents.db"
        conn = sqlite3.connect(document_db)
        conn.execute(
            "CREATE VIRTUAL TABLE docs USING fts5("
            "content, path UNINDEXED, source UNINDEXED, mtime UNINDEXED, "
            "tokenize='porter unicode61')"
        )
        rows = [
            (
                "authorityzebra governance contract precedence",
                "/fixture/stale-skill.md",
                "skills",
                1.0,
            ),
            (
                "authorityzebra governance contract precedence",
                "/fixture/canonical-contract.md",
                "contracts",
                1.0,
            ),
        ]
        conn.executemany(
            "INSERT INTO docs(content, path, source, mtime) VALUES (?, ?, ?, ?)",
            rows,
        )
        conn.commit()
        conn.close()

        output = self._run_hook(
            {
                "hook_event_name": "UserPromptSubmit",
                "session_id": "claude-current",
                "prompt": (
                    "Please inspect authorityzebra governance contract precedence now"
                ),
            },
            "claude",
            {
                "AGENT_MEMORY_DB": str(document_db),
                "SCORE_CEILING": "0",
            },
        )
        context = self._hook_context(output)
        self.assertIn("canonical-contract.md", context)
        self.assertNotIn("stale-skill.md", context)

    def test_hook_can_reuse_the_index_after_learning_sync(self):
        sync_index(self.session_db, self.roots)
        hook_path = Path(__file__).resolve().parents[1] / "hooks" / (
            "claude-recall-hook.py"
        )
        spec = importlib.util.spec_from_file_location(
            "claude_recall_hook_under_test",
            hook_path,
        )
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        hook = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(hook)
        hook.SESSION_DB_PATH = self.session_db
        hook.ROOTS = self.roots

        with patch(
            "session_continuity.sync_index",
            side_effect=AssertionError("unexpected duplicate sync"),
        ):
            hits = hook.relevant_session_hits(
                ["grokcanary", "deterministic", "retrieval"],
                "claude",
                "claude-current",
                sync=False,
            )

        self.assertTrue(hits)

    def test_hook_silently_rejects_a_weak_one_term_session_match(self):
        output = self._run_hook(
            {
                "hook_event_name": "UserPromptSubmit",
                "session_id": "claude-current",
                "prompt": (
                    "Please help me continue an unrelated "
                    "deterministic task today"
                ),
            },
            "claude",
        )
        self.assertEqual(output, "")

    def test_hook_rejects_generic_agent_update_overlap(self):
        conn = sqlite3.connect(self.hermes_db)
        conn.execute(
            "INSERT INTO sessions(id, source, started_at, title, cwd) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                "hermes-unrelated-update",
                "discord",
                900.0,
                "Agent Runtime Update",
                "/work/hermes",
            ),
        )
        conn.execute(
            "INSERT INTO messages(session_id, role, content, timestamp) "
            "VALUES (?, ?, ?, ?)",
            (
                "hermes-unrelated-update",
                "user",
                "Claude handled an unrelated runtime update and instruction layer.",
                901.0,
            ),
        )
        conn.commit()
        conn.close()

        output = self._run_hook(
            {
                "hook_event_name": "pre_llm_call",
                "session_id": "hermes-current",
                "extra": {
                    "user_message": (
                        "Claude, you now have an instruction layer update; "
                        "can you confirm please"
                    )
                },
            },
            "hermes",
        )

        self.assertEqual(output, "")

    def test_hook_accepts_grok_camel_case_and_excludes_current_session(self):
        output = self._run_hook(
            {
                "hookEventName": "user_prompt_submit",
                "sessionId": "grok-one",
                "prompt": (
                    "Please resume the grokcanary local "
                    "deterministic retrieval work"
                ),
            },
            "grok",
        )
        self.assertEqual(output, "")

    def test_automatic_hook_waits_for_hermes_persistence_then_surfaces_once(self):
        for index in range(2, 8):
            self._append_hermes_user(
                "hermes automatic preference turn %d" % index,
                1010.0 + index,
            )
        payload = {
            "hook_event_name": "pre_llm_call",
            "session_id": "hermes-human",
            "extra": {
                "user_message": "Please inspect aurora mandolin calendar drift carefully now",
            },
        }

        before_persistence = self._run_hook(
            payload,
            "hermes",
            self._automatic_env(),
        )
        self.assertEqual(before_persistence, "")

        self._append_hermes_user(
            "hermes automatic preference turn 8",
            1018.0,
        )
        surfaced = self._run_hook(payload, "hermes", self._automatic_env())
        context = self._hook_context(surfaced, hermes=True)

        self.assertLessEqual(len(context), 1_800)
        self.assertIn("Private learning maintenance.", context)
        self.assertIn("Source: hermes/hermes-human", context)
        self.assertNotIn("Cross-harness session recall", context)
        self.assertNotIn("Learning context (shadow mode)", context)

        repeated = self._run_hook(
            {
                "hook_event_name": "pre_llm_call",
                "session_id": "hermes-human",
                "extra": {
                    "user_message": (
                        "Please resume the grokcanary local deterministic "
                        "retrieval work"
                    ),
                },
            },
            "hermes",
            self._automatic_env(),
        )
        repeated_context = self._hook_context(repeated, hermes=True)
        self.assertIn("Cross-harness session recall", repeated_context)
        self.assertNotIn("Private learning maintenance.", repeated_context)

        learning_db = self.root / "learning.db"
        conn = sqlite3.connect(learning_db)
        conn.execute(
            "UPDATE review_batches SET surfaced_at = ? WHERE status = 'open'",
            (time.time() - 301,),
        )
        conn.commit()
        conn.close()
        retried = self._run_hook(payload, "hermes", self._automatic_env())
        retried_context = self._hook_context(retried, hermes=True)
        self.assertIn("Private learning maintenance.", retried_context)

        conn = sqlite3.connect(learning_db)
        conn.execute(
            "UPDATE review_batches SET surfaced_at = ? WHERE status = 'open'",
            (time.time() - 301,),
        )
        conn.commit()
        conn.close()
        exhausted = self._run_hook(
            {
                "hook_event_name": "pre_llm_call",
                "session_id": "hermes-human",
                "extra": {
                    "user_message": (
                        "Please resume the grokcanary local deterministic "
                        "retrieval work"
                    ),
                },
            },
            "hermes",
            self._automatic_env(),
        )
        exhausted_context = self._hook_context(exhausted, hermes=True)
        self.assertIn("Cross-harness session recall", exhausted_context)
        self.assertNotIn("Private learning maintenance.", exhausted_context)
        conn = sqlite3.connect(learning_db)
        status = conn.execute(
            """
            SELECT status, surface_count, terminal_reason
            FROM review_batches
            """
        ).fetchone()
        disposition = conn.execute(
            "SELECT DISTINCT disposition FROM learning_message_state"
        ).fetchall()
        conn.close()
        self.assertEqual(
            status,
            ("delivery_failed", 2, "surface_attempts_exhausted"),
        )
        self.assertIn(("delivery_failed",), disposition)
        log = (self.root / "hook.log").read_text(encoding="utf-8")
        self.assertEqual(log.count("review_batch=batch_"), 2)
        self.assertIn("learning=yes", log)

    def test_review_requires_a_complete_bounded_payload_and_surface_log(self):
        for index in range(2, 9):
            with self.claude_path.open("a", encoding="utf-8") as fh:
                fh.write(
                    json.dumps(
                        {
                            "type": "user",
                            "sessionId": "claude-one",
                            "cwd": "/work/claude",
                            "timestamp": "2026-07-28T01:%02d:00Z" % index,
                            "isSidechain": False,
                            "uuid": ("claude-auto-user-" + ("u" * 180))
                            + str(index),
                            "message": {
                                "role": "user",
                                "content": ("bounded review evidence %d " % index)
                                + ("x" * 120),
                            },
                        }
                    )
                    + "\n"
                )
                fh.write(
                    json.dumps(
                        {
                            "type": "assistant",
                            "sessionId": "claude-one",
                            "cwd": "/work/claude",
                            "timestamp": "2026-07-28T01:%02d:30Z" % index,
                            "isSidechain": False,
                            "uuid": ("claude-auto-assistant-" + ("a" * 180))
                            + str(index),
                            "message": {
                                "role": "assistant",
                                "content": ("assistant context %d " % index)
                                + ("y" * 120),
                            },
                        }
                    )
                    + "\n"
                )

        payload = {
            "hook_event_name": "UserPromptSubmit",
            "session_id": "claude-one",
            "prompt": "Please resume the grokcanary local deterministic retrieval work",
        }
        overflow = self._run_hook(payload, "claude", self._automatic_env())
        overflow_context = self._hook_context(overflow)
        self.assertIn("Cross-harness session recall", overflow_context)
        self.assertNotIn("Private learning maintenance.", overflow_context)

        learning_db = self.root / "learning.db"
        conn = sqlite3.connect(learning_db)
        overflow_status = conn.execute(
            """
            SELECT status, completed_at, terminal_reason
            FROM review_batches
            """
        ).fetchone()
        conn.close()
        self.assertEqual(
            overflow_status,
            (
                "skipped_unrenderable",
                None,
                "review_context_exceeds_limit",
            ),
        )

        for index in range(9, 17):
            self._append_claude_user(
                index,
                "fresh bounded review evidence %d" % index,
            )

        unwritable_log = self.root / "hook-log-directory"
        unwritable_log.mkdir()
        unavailable_log = self._run_hook(
            payload,
            "claude",
            {
                **self._automatic_env(),
                "AGENT_MEMORY_HOOK_LOG": str(unwritable_log),
            },
        )
        unavailable_context = self._hook_context(unavailable_log)
        self.assertIn("Private learning maintenance.", unavailable_context)
        self.assertNotIn("Cross-harness session recall", unavailable_context)
        conn = sqlite3.connect(learning_db)
        batches = conn.execute(
            """
            SELECT status, surface_count FROM review_batches
            ORDER BY created_at
            """
        ).fetchall()
        conn.close()
        self.assertEqual(
            batches,
            [("skipped_unrenderable", 0), ("open", 1)],
        )

    def test_changed_queued_source_terminalises_instead_of_partial_surface(self):
        for index in range(2, 9):
            self._append_claude_user(
                index,
                "claude automatic preference turn %d" % index,
            )
        sync_index(self.session_db, self.roots)
        with patch.dict(
            os.environ,
            {
                "AGENT_SESSION_DB": str(self.session_db),
                "AGENT_LEARNING_DB": str(self.root / "learning.db"),
            },
        ):
            queued = learn_tick(
                current_harness="claude",
                current_session_id="claude-one",
                agent_id="claude-hook",
                sync=False,
                min_user_turns=8,
                max_chars=1_200,
            )
        self.assertIsNotNone(queued["batch"])

        source = self.claude_path.read_text(encoding="utf-8")
        self.claude_path.write_text(
            source.replace(
                "claude automatic preference turn 2",
                "changed queued evidence turn 2",
                1,
            ),
            encoding="utf-8",
        )
        output = self._run_hook(
            {
                "hook_event_name": "UserPromptSubmit",
                "session_id": "claude-one",
                "prompt": (
                    "Please resume the grokcanary local deterministic "
                    "retrieval work"
                ),
            },
            "claude",
            self._automatic_env(),
        )
        context = self._hook_context(output)
        self.assertNotIn("Private learning maintenance.", context)
        conn = sqlite3.connect(self.root / "learning.db")
        batch = conn.execute(
            """
            SELECT status, surface_count, terminal_reason
            FROM review_batches WHERE id = ?
            """,
            (queued["batch"]["id"],),
        ).fetchone()
        conn.close()
        self.assertEqual(
            batch,
            (
                "skipped_unrenderable",
                0,
                "review_source_changed_or_missing",
            ),
        )

    def test_automatic_hook_uses_claude_and_grok_transcript_shapes(self):
        for index in range(2, 9):
            self._append_claude_user(
                index,
                "claude automatic preference turn %d" % index,
            )
            self._append_grok_user("grok automatic preference turn %d" % index)

        claude_output = self._run_hook(
            {
                "hook_event_name": "UserPromptSubmit",
                "session_id": "claude-one",
                "prompt": "Please inspect aurora mandolin calendar drift carefully now",
            },
            "claude",
            self._automatic_env(),
        )
        claude_context = self._hook_context(claude_output)
        self.assertIn("Source: claude/claude-one", claude_context)
        self.assertLessEqual(len(claude_context), 1_800)

        grok_output = self._run_hook(
            {
                "hookEventName": "user_prompt_submit",
                "sessionId": "grok-one",
                "prompt": "Please inspect aurora mandolin calendar drift carefully now",
            },
            "grok",
            self._automatic_env(),
        )
        grok_context = self._hook_context(grok_output)
        self.assertIn("Source: grok/grok-one", grok_context)
        self.assertLessEqual(len(grok_context), 1_800)

    def test_automatic_hook_surface_submit_and_task_match_round_trip(self):
        for index in range(2, 8):
            self._append_claude_user(
                index,
                "claude automatic preference turn %d" % index,
            )
        preference = "roundtripcanary checkpoint every migration exit path"
        self._append_claude_user(8, preference)

        surfaced = self._run_hook(
            {
                "hook_event_name": "UserPromptSubmit",
                "session_id": "claude-one",
                "prompt": "Please inspect aurora mandolin calendar drift carefully now",
            },
            "claude",
            self._automatic_env(),
        )
        surfaced_context = self._hook_context(surfaced)
        match = re.search(
            r"batch_id=(batch_[0-9a-f]+)",
            surfaced_context,
        )
        self.assertIsNotNone(match)

        with patch.dict(
            os.environ,
            {
                "AGENT_SESSION_DB": str(self.root / "sessions.db"),
                "AGENT_LEARNING_DB": str(self.root / "learning.db"),
            },
        ):
            submitted = learn_submit(
                batch_id=match.group(1),
                agent_id="claude-hook",
                proposals=[
                    {
                        "kind": "preference",
                        "statement": preference,
                        "scope": "work_style",
                        "confidence": "explicit",
                        "evidence": [
                            {
                                "harness": "claude",
                                "session_id": "claude-one",
                                "message_key": "claude-auto-8",
                                "quote": preference,
                            }
                        ],
                    }
                ],
            )
        self.assertEqual(submitted["status"], "completed")

        recalled = self._run_hook(
            {
                "hook_event_name": "pre_llm_call",
                "session_id": "hermes-human",
                "extra": {
                    "user_message": (
                        "Please apply roundtripcanary checkpoint migration "
                        "exit path now"
                    ),
                },
            },
            "hermes",
            self._automatic_env(),
        )
        recalled_context = self._hook_context(recalled, hermes=True)
        self.assertIn("Learning context (shadow mode)", recalled_context)
        self.assertIn(preference, recalled_context)

    def test_automatic_hook_injects_matching_learning_within_shared_cap(self):
        self._append_claude_user(2, "Please prefer concise replies.")
        sync_index(self.session_db, self.roots)
        learning_db = self.root / "learning.db"
        with patch.dict(
            os.environ,
            {
                "AGENT_SESSION_DB": str(self.session_db),
                "AGENT_LEARNING_DB": str(learning_db),
            },
        ):
            batch = learn_tick(
                current_harness="claude",
                current_session_id="claude-one",
                agent_id="claude-agent",
                sync=False,
            )
            learn_submit(
                batch_id=batch["batch"]["id"],
                agent_id="claude-agent",
                proposals=[
                    {
                        "kind": "preference",
                        "statement": "claudecanary checkpoint every exit path",
                        "scope": "work_style",
                        "confidence": "explicit",
                        "evidence": [
                            {
                                "harness": "claude",
                                "session_id": "claude-one",
                                "message_key": "1",
                                "quote": "claudecanary checkpoint every exit path",
                            }
                        ],
                    },
                    {
                        "kind": "preference",
                        "statement": "Please prefer concise replies.",
                        "scope": "communication",
                        "confidence": "explicit",
                        "evidence": [
                            {
                                "harness": "claude",
                                "session_id": "claude-one",
                                "message_key": "claude-auto-2",
                                "quote": "Please prefer concise replies.",
                            }
                        ],
                    }
                ],
            )

        output = self._run_hook(
            {
                "hook_event_name": "pre_llm_call",
                "session_id": "hermes-human",
                "extra": {
                    "user_message": (
                        "Please resume claudecanary checkpoint every exit path safely"
                    ),
                },
            },
            "hermes",
            self._automatic_env(),
        )
        context = self._hook_context(output, hermes=True)
        self.assertLessEqual(len(context), 1_800)
        self.assertIn("Learning context (shadow mode)", context)
        self.assertIn("Cross-harness session recall", context)
        self.assertIn("claudecanary checkpoint every exit path", context)
        self.assertIn("learning=yes", (self.root / "hook.log").read_text())

        stopword_only = self._run_hook(
            {
                "hook_event_name": "pre_llm_call",
                "session_id": "hermes-human",
                "extra": {
                    "user_message": (
                        "Please inspect aurora mandolin calendar drift carefully now"
                    ),
                },
            },
            "hermes",
            self._automatic_env(),
        )
        self.assertEqual(stopword_only, "")

        document_db = self.root / "documents.db"
        conn = sqlite3.connect(document_db)
        conn.execute(
            "CREATE VIRTUAL TABLE docs USING fts5("
            "content, path UNINDEXED, source UNINDEXED, mtime UNINDEXED, "
            "tokenize='porter unicode61')"
        )
        conn.execute(
            "INSERT INTO docs(content, path, source, mtime) VALUES (?, ?, ?, ?)",
            (
                "claudecanary checkpoint every exit path reference document",
                "/fixture/claudecanary.md",
                "fixture",
                1.0,
            ),
        )
        conn.commit()
        conn.close()
        document_output = self._run_hook(
            {
                "hook_event_name": "UserPromptSubmit",
                "session_id": "claude-one",
                "prompt": "Please resume claudecanary checkpoint every exit path safely",
            },
            "claude",
            {
                **self._automatic_env(),
                "AGENT_MEMORY_DB": str(document_db),
                "SCORE_CEILING": "0",
            },
        )
        document_context = self._hook_context(document_output)
        self.assertLessEqual(len(document_context), 1_800)
        self.assertIn("Learning context (shadow mode)", document_context)
        self.assertIn("Agent-memory document recall", document_context)

        trivial = self._run_hook(
            {
                "hook_event_name": "pre_llm_call",
                "session_id": "hermes-human",
                "extra": {"user_message": "thanks"},
            },
            "hermes",
            self._automatic_env(),
        )
        self.assertEqual(trivial, "")

        unavailable_store = self.root / "unavailable-learning-store"
        unavailable_store.mkdir()
        unavailable = self._run_hook(
            {
                "hook_event_name": "pre_llm_call",
                "session_id": "hermes-human",
                "extra": {
                    "user_message": (
                        "Please resume claudecanary checkpoint every exit path safely"
                    ),
                },
            },
            "hermes",
            {
                **self._automatic_env(),
                "AGENT_LEARNING_DB": str(unavailable_store),
            },
        )
        unavailable_context = self._hook_context(unavailable, hermes=True)
        self.assertNotIn("Private learning maintenance.", unavailable_context)
        self.assertNotIn("Learning context (shadow mode)", unavailable_context)


if __name__ == "__main__":
    unittest.main()
