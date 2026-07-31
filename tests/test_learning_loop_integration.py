import ast
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from learning_loop import context_packet, learn_submit, learn_tick


REPO = Path(__file__).resolve().parents[1]


class LearningLoopIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.codex_root = self.root / "codex-sessions"
        self.codex_source = (
            self.codex_root / "2026" / "08" / "01" / "rollout-learning.jsonl"
        )
        self.codex_source.parent.mkdir(parents=True)
        rows = [
            {
                "type": "session_meta",
                "timestamp": "2026-08-01T00:00:00Z",
                "payload": {
                    "id": "codex-learning-session",
                    "cwd": "/synthetic/work",
                    "timestamp": "2026-08-01T00:00:00Z",
                },
            },
            {
                "type": "response_item",
                "timestamp": "2026-08-01T00:00:01Z",
                "payload": {
                    "id": "user-pref-1",
                    "type": "message",
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": "Use Celsius for weather reports.",
                        }
                    ],
                },
            },
            {
                "type": "response_item",
                "timestamp": "2026-08-01T00:00:02Z",
                "payload": {
                    "id": "assistant-1",
                    "type": "message",
                    "role": "assistant",
                    "phase": "final_answer",
                    "content": [
                        {
                            "type": "output_text",
                            "text": "Understood. I will use Celsius for weather reports.",
                        }
                    ],
                },
            },
        ]
        self.codex_source.write_text(
            "".join(json.dumps(row) + "\n" for row in rows),
            encoding="utf-8",
        )
        self.sessions_db = self.root / "sessions.db"
        self.learning_db = self.root / "learning.db"
        self.contracts = [
            self.home / ".hermes" / "SOUL.md",
            self.home / ".hermes" / "memories" / "MEMORY.md",
            self.home / ".hermes" / "skills" / "fixture" / "SKILL.md",
        ]
        for contract in self.contracts:
            contract.parent.mkdir(parents=True, exist_ok=True)
            contract.write_text("synthetic marker\n", encoding="utf-8")
        self.environment = patch.dict(
            os.environ,
            {
                "HOME": str(self.home),
                "AGENT_SESSION_DB": str(self.sessions_db),
                "AGENT_LEARNING_DB": str(self.learning_db),
                "HERMES_SESSION_DB": str(self.root / "missing-hermes.db"),
                "CLAUDE_PROJECTS_ROOT": str(self.root / "claude-sessions"),
                "CODEX_SESSIONS_ROOT": str(self.codex_root),
                "GROK_SESSIONS_ROOT": str(self.root / "grok-sessions"),
            },
        )
        self.environment.start()

    def tearDown(self):
        self.environment.stop()
        self.tempdir.cleanup()

    def _hash(self, path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def _proposal(self):
        return {
            "kind": "preference",
            "statement": "Use Celsius for weather reports.",
            "scope": "communication",
            "confidence": "explicit",
            "evidence": [
                {
                    "harness": "codex",
                    "session_id": "codex-learning-session",
                    "message_key": "user-pref-1",
                    "quote": "Use Celsius for weather reports.",
                }
            ],
        }

    def _tick(self):
        return learn_tick(
            operator_id="synthetic-operator",
            current_harness="codex",
            current_session_id="codex-learning-session",
            agent_id="synthetic-codex-agent",
            sync=True,
        )

    def _submit(self, tick):
        return learn_submit(
            batch_id=tick["batch"]["id"],
            agent_id="synthetic-codex-agent",
            proposals=[self._proposal()],
        )

    def _context(self, harness, scope="communication"):
        arguments = {
            "operator_id": "synthetic-operator",
            "requesting_harness": harness,
            "requesting_agent_id": "synthetic-other-agent",
            "task": "Write a weather report in Celsius",
        }
        if scope:
            arguments["scope"] = scope
        return context_packet(
            **arguments,
        )

    def _mcp_request(self, process, request_id, name, arguments):
        request = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
        process.stdin.write(json.dumps(request) + "\n")
        process.stdin.flush()
        response = json.loads(process.stdout.readline())
        content = response["result"]["content"][0]["text"]
        return json.loads(content), response["result"]["isError"]

    def test_codex_learning_is_retrievable_by_other_harness(self):
        tick = self._tick()
        result = self._submit(tick)
        self.assertEqual(result["claims"][0]["status"], "provisional")
        self.codex_source.unlink()

        for harness in ("hermes", "claude", "grok"):
            with self.subTest(harness=harness):
                packet = self._context(harness, scope=None)
                self.assertIn("Celsius for weather reports", packet["packet"])
                self.assertIn("[provisional]", packet["packet"])
                self.assertIn(
                    "codex/codex-learning-session/user-pref-1",
                    packet["packet"],
                )

    def test_learning_round_trip_does_not_mutate_session_sources(self):
        paths = [self.codex_source, *self.contracts]
        before = {path: self._hash(path) for path in paths}

        tick = self._tick()
        self._submit(tick)
        self._context("hermes")

        after = {path: self._hash(path) for path in paths}
        self.assertEqual(before, after)

    def test_mcp_learning_tools_round_trip(self):
        process = subprocess.Popen(
            [sys.executable, str(REPO / "mcp_server.py")],
            cwd=REPO,
            env=os.environ.copy(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            process.stdin.write(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 0,
                        "method": "tools/list",
                        "params": {},
                    }
                )
                + "\n"
            )
            process.stdin.flush()
            listed = json.loads(process.stdout.readline())
            tool_names = {tool["name"] for tool in listed["result"]["tools"]}
            self.assertTrue(
                {"learn_tick", "learn_submit", "context_packet"}.issubset(tool_names)
            )
            tick, tick_error = self._mcp_request(
                process,
                1,
                "learn_tick",
                {
                    "operator_id": "synthetic-operator",
                    "current_harness": "codex",
                    "current_session_id": "codex-learning-session",
                    "agent_id": "synthetic-codex-agent",
                    "sync": True,
                },
            )
            self.assertFalse(tick_error)
            submitted, submit_error = self._mcp_request(
                process,
                2,
                "learn_submit",
                {
                    "batch_id": tick["batch"]["id"],
                    "agent_id": "synthetic-codex-agent",
                    "proposals": [self._proposal()],
                },
            )
            self.assertFalse(submit_error)
            packet, context_error = self._mcp_request(
                process,
                3,
                "context_packet",
                {
                    "operator_id": "synthetic-operator",
                    "requesting_harness": "hermes",
                    "requesting_agent_id": "synthetic-other-agent",
                    "task": "Write a weather report in Celsius",
                    "scope": "communication",
                },
            )
            self.assertFalse(context_error)
            self.assertEqual(submitted["status"], "completed")
            self.assertIn("user-pref-1", packet["packet"])
        finally:
            process.stdin.close()
            process.wait(timeout=5)
            process.stdout.close()
            process.stderr.close()

    def test_cli_and_mcp_return_equivalent_results(self):
        cli = subprocess.run(
            [
                str(REPO / "learning-memory"),
                "tick",
                "--operator-id",
                "synthetic-operator",
                "--current-harness",
                "codex",
                "--current-session-id",
                "codex-learning-session",
                "--agent-id",
                "synthetic-codex-agent",
            ],
            cwd=REPO,
            env=os.environ.copy(),
            capture_output=True,
            text=True,
            check=True,
        )
        cli_result = json.loads(cli.stdout)
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "learn_tick",
                "arguments": {
                    "operator_id": "synthetic-operator",
                    "current_harness": "codex",
                    "current_session_id": "codex-learning-session",
                    "agent_id": "synthetic-codex-agent",
                    "sync": True,
                },
            },
        }
        mcp = subprocess.run(
            [sys.executable, str(REPO / "mcp_server.py")],
            input=json.dumps(request) + "\n",
            cwd=REPO,
            env=os.environ.copy(),
            capture_output=True,
            text=True,
            check=True,
        )
        response = json.loads(mcp.stdout)
        mcp_result = json.loads(response["result"]["content"][0]["text"])

        self.assertEqual(cli_result, mcp_result)

        cli_error_process = subprocess.run(
            [
                str(REPO / "learning-memory"),
                "submit",
                "--batch-id",
                cli_result["batch"]["id"],
                "--agent-id",
                "wrong-agent",
                "--proposals-json",
                "[]",
            ],
            cwd=REPO,
            env=os.environ.copy(),
            capture_output=True,
            text=True,
        )
        self.assertEqual(cli_error_process.returncode, 2)
        cli_error = json.loads(cli_error_process.stdout)
        error_request = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "learn_submit",
                "arguments": {
                    "batch_id": cli_result["batch"]["id"],
                    "agent_id": "wrong-agent",
                    "proposals": [],
                },
            },
        }
        mcp_error_process = subprocess.run(
            [sys.executable, str(REPO / "mcp_server.py")],
            input=json.dumps(error_request) + "\n",
            cwd=REPO,
            env=os.environ.copy(),
            capture_output=True,
            text=True,
            check=True,
        )
        error_response = json.loads(mcp_error_process.stdout)
        mcp_error = json.loads(
            error_response["result"]["content"][0]["text"]
        )
        self.assertTrue(error_response["result"]["isError"])
        self.assertEqual(cli_error, mcp_error)

        cli_submit = subprocess.run(
            [
                str(REPO / "learning-memory"),
                "submit",
                "--batch-id",
                cli_result["batch"]["id"],
                "--agent-id",
                "synthetic-codex-agent",
                "--proposals-json",
                json.dumps([self._proposal()]),
            ],
            cwd=REPO,
            env=os.environ.copy(),
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertEqual(json.loads(cli_submit.stdout)["status"], "completed")

        context_arguments = {
            "operator_id": "synthetic-operator",
            "requesting_harness": "grok",
            "requesting_agent_id": "synthetic-other-agent",
            "task": "Write a weather report in Celsius",
            "scope": "communication",
        }
        cli_context = subprocess.run(
            [
                str(REPO / "learning-memory"),
                "context",
                "--operator-id",
                context_arguments["operator_id"],
                "--requesting-harness",
                context_arguments["requesting_harness"],
                "--requesting-agent-id",
                context_arguments["requesting_agent_id"],
                "--task",
                context_arguments["task"],
                "--scope",
                context_arguments["scope"],
            ],
            cwd=REPO,
            env=os.environ.copy(),
            capture_output=True,
            text=True,
            check=True,
        )
        context_request = {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "context_packet",
                "arguments": context_arguments,
            },
        }
        mcp_context_process = subprocess.run(
            [sys.executable, str(REPO / "mcp_server.py")],
            input=json.dumps(context_request) + "\n",
            cwd=REPO,
            env=os.environ.copy(),
            capture_output=True,
            text=True,
            check=True,
        )
        context_response = json.loads(mcp_context_process.stdout)
        mcp_context = json.loads(
            context_response["result"]["content"][0]["text"]
        )
        self.assertFalse(context_response["result"]["isError"])
        self.assertEqual(json.loads(cli_context.stdout), mcp_context)
        self.assertIn("user-pref-1", mcp_context["packet"])

    def test_public_example_uses_published_cli(self):
        result = subprocess.run(
            [sys.executable, str(REPO / "examples" / "learning-loop-e2e.py")],
            cwd=REPO,
            env=os.environ.copy(),
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("[provisional]", result.stdout)
        self.assertIn("Synthetic cross-harness example passed.", result.stdout)

    @unittest.skipUnless(
        Path("/usr/bin/python3").is_file(),
        "macOS system Python is unavailable",
    )
    def test_learning_cli_imports_with_macos_system_python(self):
        result = subprocess.run(
            [
                "/usr/bin/python3",
                str(REPO / "learning-memory"),
                "context",
                "--help",
            ],
            cwd=REPO,
            env=os.environ.copy(),
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("usage:", result.stdout)

    def test_learning_core_runs_with_network_disabled(self):
        imported_roots = set()
        for filename in (
            "learning_loop.py",
            "_learning_policy.py",
            "_learning_store.py",
        ):
            source = (REPO / filename).read_text(encoding="utf-8")
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported_roots.update(
                        alias.name.split(".")[0] for alias in node.names
                    )
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported_roots.add(node.module.split(".")[0])
        self.assertTrue(
            imported_roots.isdisjoint(
                {
                    "anthropic",
                    "http",
                    "httpx",
                    "openai",
                    "requests",
                    "urllib",
                    "hermes",
                }
            ),
            imported_roots,
        )

        with patch("socket.socket", side_effect=AssertionError("network disabled")):
            tick = self._tick()
            self._submit(tick)
            result = self._context("grok")
        self.assertTrue(result["claims"])


if __name__ == "__main__":
    unittest.main()
