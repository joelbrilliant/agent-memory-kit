# Experimental cross-harness learning loop

## Status and boundary

Slice 1 is an experimental but working local learning loop for explicit
operator preferences. It uses the existing read-only session projection as
evidence, stores provisional claims in a separate SQLite database, and returns
deterministic context packets to any participating harness.

The active agent still decides whether an operator message expresses a
reusable preference. The core validates the exact user-authored evidence,
transaction boundary, allowed fields, secret scan, claim deduplication,
operator isolation and output size. It does not call a model or network
service.

Automatic lifecycle-triggered review across harnesses is Slice 2 and is not
included. Slice 1 does not inject packets automatically, confirm claims, edit
canonical memory, create skills, or modify source transcripts.

## Requirements

- Python 3.9 or newer
- SQLite with FTS5 enabled
- an approved local `sessions.db` built by `session-memory`
- at least one integration surface for each participating harness, such as
  stdio MCP, shell access, a lifecycle hook, readable transcripts, or an export
  API

This is a script-based kit, not a pip package. It has no third-party runtime
dependencies and uses the repository's MIT licence.

## Setup

Build the shared session projection only after the operator has approved its
source paths:

```sh
./session-memory sync
./session-memory list -n 20
```

The learning tools use `sessions.db` and create `learning.db` beside the
scripts by default. Both paths can be moved to a private local directory:

```sh
export AGENT_SESSION_DB=/private/local/path/sessions.db
export AGENT_LEARNING_DB=/private/local/path/learning.db
```

Register `mcp_server.py` in MCP-capable harnesses as described in
[examples/mcp.md](examples/mcp.md), or call `learning-memory` directly from a
shell-capable harness. Do not add an automatic post-turn or session-end hook in
Slice 1. Call the tools manually at an approved review checkpoint.

## Doctor checks

Run these from the repository root before wiring a harness:

```sh
python3 -c "import sys; assert sys.version_info >= (3, 9); print(sys.version.split()[0])"
python3 -c "import sqlite3; c=sqlite3.connect(':memory:'); c.execute('CREATE VIRTUAL TABLE t USING fts5(x)'); print('fts5 ok')"
python3 -m py_compile learning_loop.py _learning_policy.py _learning_store.py mcp_server.py learning-memory
./test.sh
python3 examples/learning-loop-e2e.py
git check-ignore sessions.db sessions.db-shm sessions.db-wal learning.db learning.db-shm learning.db-wal
```

After creating a live learning store, check integrity and owner-only modes:

```sh
python3 - <<'PY'
import os
import sqlite3
import stat
from pathlib import Path

path = Path(os.environ.get('AGENT_LEARNING_DB', 'learning.db'))
connection = sqlite3.connect(path)
print('integrity:', connection.execute('PRAGMA integrity_check').fetchone()[0])
connection.close()
for candidate in (path, Path(str(path) + '-shm'), Path(str(path) + '-wal')):
    if candidate.exists():
        print(candidate, oct(stat.S_IMODE(candidate.stat().st_mode)))
PY
```

Every existing database or sidecar should report mode `0o600`.

## CLI workflow

Create or return one bounded review batch for the current session:

```sh
./learning-memory tick \
  --operator-id default \
  --current-harness codex \
  --current-session-id SESSION_ID \
  --agent-id REVIEWING_AGENT_ID
```

Review the returned user messages. If one contains an explicit reusable
preference, submit a compact statement with an exact quote from that message:

```sh
./learning-memory submit \
  --batch-id BATCH_ID \
  --agent-id REVIEWING_AGENT_ID \
  --proposals-json '[{"kind":"preference","statement":"Use Celsius for weather reports.","scope":"domain","scope_key":"weather","confidence":"explicit","evidence":[{"harness":"codex","session_id":"SESSION_ID","message_key":"MESSAGE_KEY","quote":"Use Celsius for weather reports."}]}]'
```

Use an empty JSON list when the batch contains nothing reusable. Either path
completes the batch atomically. Any invalid proposal leaves it open for retry.

Retrieve a compact packet from another harness:

```sh
./learning-memory context \
  --operator-id default \
  --requesting-harness hermes \
  --requesting-agent-id REQUESTING_AGENT_ID \
  --task "Write a weather report in Celsius" \
  --scope domain \
  --scope-key weather
```

The packet labels the claim `provisional`, includes its scope and carries a
compact evidence reference. The requesting harness decides whether to show or
use it.

## MCP surface

The same public functions are exposed as three stdio MCP tools:

- `learn_tick`
- `learn_submit`
- `context_packet`

The CLI and MCP paths return the same structured result and stable error
shape. `tests/test_learning_loop_integration.py` exercises all three through
the JSON-RPC boundary.

## Harness adapter examples

The core is harness-neutral. These are integration seams, not claims of
universal support:

- Codex: use stdio MCP when available, or run the CLI from the shell. Its local
  JSONL transcript adapter can supply evidence after the operator approves the
  Codex session path.
- Hermes Agent: register the stdio MCP server when the installed version
  supports MCP, or expose the CLI through a local skill. No Hermes import is
  required by the learning core.
- Claude Code: register the stdio MCP server or invoke the CLI from an approved
  command or skill. The existing prompt hook performs recall only and must not
  be treated as an automatic learning trigger.
- Grok: use the CLI from a shell-capable session or register the MCP server
  where supported. The existing shell hook performs recall only.

If a harness has neither MCP nor shell access, it needs another explicit seam
such as a readable transcript location or export API plus a small adapter. Do
not claim zero-configuration support.

## Runnable cross-harness example

Run:

```sh
python3 examples/learning-loop-e2e.py
```

The example creates a temporary synthetic Codex transcript, calls the
published `tick` and `submit` CLI interfaces, requests context as Hermes, then
asserts that the provisional statement and Codex evidence reference are in the
packet. The temporary transcript and databases are deleted when it exits.

## Local data and deletion

`learning.db` is local experimental state. It contains claims, hashes and only
the cited evidence snippets, not full transcript bodies. The database and its
SQLite sidecars are ignored by Git and forced to owner-only mode.

Claim-level deletion and source cascade deletion are Slice 2 work. Until then,
remove the local `learning.db`, `learning.db-shm` and `learning.db-wal` files to
discard all experimental learning state.
