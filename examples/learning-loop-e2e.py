#!/usr/bin/env python3
"""Run a synthetic Codex to Hermes learning-loop round trip."""

import json
import os
import subprocess
import tempfile
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
PREFERENCE = "Use Celsius for weather reports."


def run_cli(environment, *arguments):
    completed = subprocess.run(
        [str(REPO / "learning-memory"), *arguments],
        cwd=REPO,
        env=environment,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr or completed.stdout)
    return json.loads(completed.stdout)


def main():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        codex_root = root / "codex-sessions"
        source = codex_root / "2026" / "01" / "01" / "rollout-example.jsonl"
        source.parent.mkdir(parents=True)
        rows = [
            {
                "type": "session_meta",
                "timestamp": "2026-01-01T00:00:00Z",
                "payload": {
                    "id": "codex-example-session",
                    "cwd": "/synthetic/project",
                    "timestamp": "2026-01-01T00:00:00Z",
                },
            },
            {
                "type": "response_item",
                "timestamp": "2026-01-01T00:00:01Z",
                "payload": {
                    "id": "user-preference",
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": PREFERENCE}],
                },
            },
            {
                "type": "response_item",
                "timestamp": "2026-01-01T00:00:02Z",
                "payload": {
                    "id": "assistant-reply",
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
        source.write_text(
            "".join(json.dumps(row) + "\n" for row in rows),
            encoding="utf-8",
        )

        environment = os.environ.copy()
        environment.update(
            {
                "HOME": str(root / "home"),
                "AGENT_SESSION_DB": str(root / "sessions.db"),
                "AGENT_LEARNING_DB": str(root / "learning.db"),
                "HERMES_SESSION_DB": str(root / "missing-hermes.db"),
                "CLAUDE_PROJECTS_ROOT": str(root / "missing-claude"),
                "CODEX_SESSIONS_ROOT": str(codex_root),
                "GROK_SESSIONS_ROOT": str(root / "missing-grok"),
            }
        )

        tick = run_cli(
            environment,
            "tick",
            "--operator-id",
            "example-operator",
            "--current-harness",
            "codex",
            "--current-session-id",
            "codex-example-session",
            "--agent-id",
            "example-codex-agent",
        )
        batch_id = tick["batch"]["id"]
        proposal = [
            {
                "kind": "preference",
                "statement": PREFERENCE,
                "scope": "domain",
                "scope_key": "weather",
                "confidence": "explicit",
                "evidence": [
                    {
                        "harness": "codex",
                        "session_id": "codex-example-session",
                        "message_key": "user-preference",
                        "quote": PREFERENCE,
                    }
                ],
            }
        ]
        submitted = run_cli(
            environment,
            "submit",
            "--batch-id",
            batch_id,
            "--agent-id",
            "example-codex-agent",
            "--proposals-json",
            json.dumps(proposal),
        )
        packet = run_cli(
            environment,
            "context",
            "--operator-id",
            "example-operator",
            "--requesting-harness",
            "hermes",
            "--requesting-agent-id",
            "example-hermes-agent",
            "--task",
            "Write a weather report in Celsius",
            "--scope",
            "domain",
            "--scope-key",
            "weather",
        )

        assert submitted["claims"][0]["status"] == "provisional"
        assert PREFERENCE in packet["packet"]
        assert "codex/codex-example-session/user-preference" in packet["packet"]
        print(packet["packet"])
        print("Synthetic cross-harness example passed.")


if __name__ == "__main__":
    main()
