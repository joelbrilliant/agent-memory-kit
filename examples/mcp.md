# MCP server

`mcp_server.py` is a stdio MCP server that exposes document recall, session
recall, evidence-gated writes and the experimental learning loop as first-class
tools in any MCP-capable harness. It speaks JSON-RPC 2.0 over stdin/stdout, one
message per line. Existing recall tools keep their CLI implementation through
subprocess, while MCP and CLI learning calls share the public functions in
`learning_loop.py`.

It registers itself under the server name `agent-memory` and offers seven
tools:

- `recall` - inputs: `query` (required), `k` (optional), `source` (optional
  corpus-tag filter).
- `remember` - inputs: `content`, `source`, `evidence` (all required), `tags`
  (optional). The underlying tool still refuses to write without evidence, so a
  `remember` call missing evidence comes back as an error result, not a write.
- `session_recall` - inputs: `query` (required), `k`, `harness`,
  `current_harness` and `current_session_id` (optional).
- `session_list` - inputs: `limit`, `harness` and `sync` (optional).
- `learn_tick` - inputs: `current_harness`, `current_session_id` and `agent_id`
  (required), plus bounded review options.
- `learn_submit` - inputs: `batch_id`, `agent_id` and evidence-backed
  `proposals` (required).
- `context_packet` - inputs: `requesting_harness`, `requesting_agent_id` and
  `task` (required), plus optional scope and character-budget fields.

The server derives the paths to the `recall` and `remember` scripts from its own
location. Override the index or root with `AGENT_MEMORY_DB` and
`AGENT_MEMORY_ROOT` if you keep them elsewhere. Use `AGENT_SESSION_DB` and
`AGENT_LEARNING_DB` for the local session projection and experimental learning
store. See [../LEARNING-LOOP.md](../LEARNING-LOOP.md) before enabling the
learning tools.

## Generic registration

Any harness that supports stdio MCP servers needs the same three things:

- command: `python3`
- args: the absolute path to `mcp_server.py`
- transport: stdio

There is nothing to install and no port to open; the harness launches the
script and talks to it over stdin/stdout.

## Concrete example: Claude Code

```
claude mcp add agent-memory -- python3 /path/to/agent-memory-kit/mcp_server.py
```

Replace `/path/to/agent-memory-kit` with the absolute path to your clone. After
adding it, the seven tools show up in the session. Verify with `claude mcp list`.

## Quick manual smoke test

You can drive the server by hand to confirm it responds before wiring it into a
harness:

```
printf '%s\n%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}' \
  | python3 /path/to/agent-memory-kit/mcp_server.py
```

You should get an `initialize` result followed by a `tools/list` result naming
`recall`, `remember`, `session_recall`, `session_list`, `learn_tick`,
`learn_submit` and `context_packet`.
