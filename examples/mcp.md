# MCP server

`mcp_server.py` is a stdio MCP server that exposes document recall, session
recall and evidence-gated writes as first-class tools in any MCP-capable
harness. It speaks JSON-RPC 2.0 over
stdin/stdout, one message per line, and wraps the existing CLIs by subprocess so
there is exactly one implementation of the query and write logic. Because it
shells out to `recall`, MCP-driven recalls land in `usage.log` like any other
deliberate call, which keeps the self-audit honest.

It registers itself under the server name `agent-memory` and offers four tools:

- `recall` - inputs: `query` (required), `k` (optional), `source` (optional
  corpus-tag filter).
- `remember` - inputs: `content`, `source`, `evidence` (all required), `tags`
  (optional). The underlying tool still refuses to write without evidence, so a
  `remember` call missing evidence comes back as an error result, not a write.
- `session_recall` - inputs: `query` (required), `k`, `harness`,
  `current_harness` and `current_session_id` (optional).
- `session_list` - inputs: `limit`, `harness` and `sync` (optional).

The server derives the paths to the `recall` and `remember` scripts from its own
location. Override the index or root with `AGENT_MEMORY_DB` and
`AGENT_MEMORY_ROOT` if you keep them elsewhere.

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
adding it, `recall` and `remember` show up as tools in the session. Verify with
`claude mcp list`.

## Concrete example: Grok

```
grok mcp add agent-memory -- python3 /path/to/agent-memory-kit/mcp_server.py
```

Set `AGENT_MEMORY_CALLER=grok` in the server environment when configuring by
file. Verify the real process, not just the config entry:

```
grok mcp doctor agent-memory
```

Then ask a Grok session to call `session_recall` for distinctive terms from a
conversation held in another harness. Grok prompt hooks cannot inject context
because passive hook stdout is ignored.

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
`recall`, `remember`, `session_recall` and `session_list`.
