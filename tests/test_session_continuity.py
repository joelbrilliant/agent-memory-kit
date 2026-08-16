import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from session_continuity import (
    SessionRoots,
    list_sessions,
    recall_sessions,
    sync_index,
)
from session_adapters import clean_message_content


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
                    1005.1,
                ),
                (
                    "hermes-human",
                    "assistant",
                    "[IMPORTANT: Background process] backgroundnoisehermes",
                    1005.2,
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
            "generatedsuffixhermes",
            "generatedenvelopehermes",
            "backgroundnoisehermes",
            "cronnoisehermes",
            "reasoningnoiseclaude",
            "toolnoiseclaude",
            "sidechainnoiseclaude",
            "compactsummarynoiseclaude",
            "metanoiseclaude",
            "developernoisecodex",
            "bootstrapnoisecodex",
            "generatednotecodex",
            "reasoningnoisecodex",
            "systemnoisegrok",
            "syntheticnoisegrok",
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
                "AGENT_MEMORY_HOOK_LOG": str(self.root / "hook.log"),
                "HERMES_SESSION_DB": str(self.hermes_db),
                "CLAUDE_PROJECTS_ROOT": str(self.claude_root),
                "CODEX_SESSIONS_ROOT": str(self.codex_root),
                "GROK_SESSIONS_ROOT": str(self.grok_root),
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
                "AGENT_MEMORY_CALLER": "grok",
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

    def test_hook_skips_generated_harness_prompts(self):
        prompts = [
            "Review the conversation above and update the skill library. Be active.",
            "Review the conversation above and consider saving to memory if appropriate.",
            "Review the conversation above and update two things: memory and skills.",
        ]
        for prompt in prompts:
            with self.subTest(prompt=prompt):
                output = self._run_hook(
                    {
                        "hook_event_name": "pre_llm_call",
                        "session_id": "hermes-human",
                        "extra": {"user_message": prompt},
                    },
                    "hermes",
                )
                self.assertEqual(output, "")

    def test_hook_strips_generated_task_suffix_but_keeps_user_prompt(self):
        genuine_prompt = (
            "Please resume the grokcanary local deterministic retrieval work"
        )
        supplied_prompt = (
            genuine_prompt
            + "\n\n"
            + "[Your active task list was preserved across context compression]\n"
            + "- [ ] stale-task should not affect retrieval (pending)"
        )
        self.assertEqual(
            clean_message_content("user", supplied_prompt),
            genuine_prompt,
        )

        output = self._run_hook(
            {
                "hook_event_name": "pre_llm_call",
                "session_id": "hermes-current",
                "extra": {
                    "user_message": supplied_prompt
                },
            },
            "hermes",
        )
        context = json.loads(output)["context"]
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
        conn.executemany(
            "INSERT INTO docs(content, path, source, mtime) VALUES (?, ?, ?, ?)",
            [
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
            ],
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
        context = json.loads(output)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("canonical-contract.md", context)
        self.assertNotIn("stale-skill.md", context)

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
                        "Claude, you now have an instruction layer update, "
                        "can you confirm please"
                    )
                },
            },
            "hermes",
        )
        self.assertEqual(output, "")

    def test_grok_prompt_hook_exits_because_passive_output_cannot_inject(self):
        output = self._run_hook(
            {
                "hookEventName": "user_prompt_submit",
                "sessionId": "grok-current",
                "prompt": (
                    "Please resume the codexcanary central "
                    "session index work"
                ),
            },
            "grok",
        )
        self.assertEqual(output, "")


if __name__ == "__main__":
    unittest.main()
