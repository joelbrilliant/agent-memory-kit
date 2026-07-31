#!/usr/bin/env python3
"""Stdio MCP server exposing durable and session memory as first-class tools.

Python stdlib only. Wraps the existing CLI tools via subprocess so there is
exactly one implementation of query and write logic; MCP-driven recalls land
in usage.log like any other deliberate call.

Register this file in any MCP-capable harness. Paths are derived from this
file's location, so one local clone can serve every harness on the machine.

Protocol: JSON-RPC 2.0, one message per line on stdin/stdout. Only stderr
may carry logs; stdout is protocol-only.
"""
import os
import sys
import json
import subprocess

REPO = os.path.dirname(os.path.abspath(__file__))
RECALL = os.path.join(REPO, "recall")
REMEMBER = os.path.join(REPO, "remember")
SESSION_MEMORY = os.path.join(REPO, "session-memory")

PROTOCOL_VERSION = "2024-11-05"

TOOLS = [
    {
        "name": "recall",
        "description": (
            "Search local agent memory: an FTS5 index over the markdown "
            "artefacts configured in corpus.txt, including notes, skills, "
            "reviews, project docs and evidence-gated episodes. Use at the "
            "START of any "
            "substantial task that may have been seen before: bug classes, "
            "review findings, config gotchas and past decisions. Results are "
            "leads - open the file before relying on it."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search terms, 2-8 content words work best"},
                "k": {"type": "integer", "description": "Max results (default 5)"},
                "source": {
                    "type": "string",
                    "description": "Optional corpus tag from corpus.txt",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "session_recall",
        "description": (
            "Search user and assistant dialogue from local Hermes, Claude "
            "Code, Codex and Grok sessions. Use when the user resumes prior "
            "work, switches harnesses, or asks what was decided in an earlier "
            "conversation. Retrieval is deterministic SQLite FTS5 with no LLM "
            "memory layer. Results are transcript leads, not authority."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Distinctive terms from the prior conversation",
                },
                "k": {
                    "type": "integer",
                    "description": "Max session groups (default 5)",
                },
                "harness": {
                    "type": "string",
                    "enum": ["hermes", "claude", "codex", "grok"],
                    "description": "Optional source harness filter",
                },
                "current_harness": {
                    "type": "string",
                    "description": "Harness of the current session, for exclusion",
                },
                "current_session_id": {
                    "type": "string",
                    "description": "Current session id, for exclusion",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "session_list",
        "description": (
            "List recent local sessions across Hermes, Claude Code, Codex and "
            "Grok from the shared deterministic session index."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Max sessions (default 20)",
                },
                "harness": {
                    "type": "string",
                    "enum": ["hermes", "claude", "codex", "grok"],
                    "description": "Optional source harness filter",
                },
                "sync": {
                    "type": "boolean",
                    "description": "Refresh changed local session files first",
                },
            },
        },
    },
    {
        "name": "remember",
        "description": (
            "Write an episode to local agent memory. HARD RULES: only at a "
            "verified checkpoint or on the operator's explicit instruction, "
            "never mid-run and never speculatively. An episode is a durable "
            "lesson, not a status report. Use the one-month test and keep "
            "queue, phase and completion snapshots in the tracker or "
            "handover. Evidence is mandatory (commit SHA, "
            "file path, PR/issue URL, or log path) - the tool refuses "
            "without it. Never record secrets, credentials, private "
            "transcripts or information that should not be committed."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "Durable lesson that will still be useful in a month, not current status"},
                "source": {"type": "string", "description": "Which agent or harness is writing"},
                "evidence": {"type": "string", "description": "Commit SHA, file path, PR/issue URL, or log path"},
                "tags": {"type": "string", "description": "Optional comma-separated tags"},
            },
            "required": ["content", "source", "evidence"],
        },
    },
]


# Label MCP-originated calls in usage.log unless the registration already
# sets a more specific caller (e.g. AGENT_MEMORY_CALLER=claude-code).
os.environ.setdefault("AGENT_MEMORY_CALLER", "mcp")


def run_cli(cmd):
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30, cwd=REPO
        )
    except subprocess.TimeoutExpired:
        return "error: agent-memory CLI timed out", True
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    if proc.returncode != 0:
        return err or out or ("error: exit %d" % proc.returncode), True
    return out or "(no output)", False


def call_tool(name, args):
    if name == "recall":
        query = (args.get("query") or "").strip()
        if not query:
            return "error: query is required", True
        cmd = [sys.executable, RECALL, query, "-k", str(int(args.get("k") or 5))]
        if args.get("source"):
            cmd += ["--source", str(args["source"])]
        return run_cli(cmd)
    if name == "session_recall":
        query = (args.get("query") or "").strip()
        if not query:
            return "error: query is required", True
        cmd = [
            sys.executable,
            SESSION_MEMORY,
            "recall",
            query,
            "-k",
            str(int(args.get("k") or 5)),
        ]
        for option in (
            "harness",
            "current_harness",
            "current_session_id",
        ):
            value = args.get(option)
            if value:
                cmd += ["--" + option.replace("_", "-"), str(value)]
        return run_cli(cmd)
    if name == "session_list":
        cmd = [
            sys.executable,
            SESSION_MEMORY,
            "list",
            "-n",
            str(int(args.get("limit") or 20)),
        ]
        if args.get("harness"):
            cmd += ["--harness", str(args["harness"])]
        if args.get("sync"):
            cmd.append("--sync")
        return run_cli(cmd)
    if name == "remember":
        cmd = [
            sys.executable, REMEMBER,
            "--source", str(args.get("source") or ""),
            "--evidence", str(args.get("evidence") or ""),
        ]
        if args.get("tags"):
            cmd += ["--tags", str(args["tags"])]
        cmd.append(str(args.get("content") or ""))
        text, is_err = run_cli(cmd)
        if not is_err:
            text = "episode written: " + text
        return text, is_err
    return "error: unknown tool %s" % name, True


def respond(msg_id, result=None, error=None):
    reply = {"jsonrpc": "2.0", "id": msg_id}
    if error is not None:
        reply["error"] = error
    else:
        reply["result"] = result
    sys.stdout.write(json.dumps(reply) + "\n")
    sys.stdout.flush()


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        method = msg.get("method", "")
        msg_id = msg.get("id")
        params = msg.get("params") or {}

        if method == "initialize":
            respond(msg_id, {
                "protocolVersion": params.get("protocolVersion", PROTOCOL_VERSION),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "agent-memory", "version": "1.1.0"},
            })
        elif method in ("notifications/initialized", "notifications/cancelled"):
            continue  # notifications get no response
        elif method == "ping":
            respond(msg_id, {})
        elif method == "tools/list":
            respond(msg_id, {"tools": TOOLS})
        elif method == "tools/call":
            text, is_err = call_tool(
                params.get("name", ""), params.get("arguments") or {}
            )
            respond(msg_id, {
                "content": [{"type": "text", "text": text}],
                "isError": is_err,
            })
        elif msg_id is not None:
            respond(msg_id, error={"code": -32601, "message": "method not found: %s" % method})
    return 0


if __name__ == "__main__":
    sys.exit(main())
