# Cross-harness session continuity

The session index lets one local harness recover relevant dialogue from another
without asking the operator to repeat the conversation. It is deliberately
separate from durable memory:

- `sessions.db` contains derived, local transcript text and is gitignored.
- `index.db` contains searchable work artefacts and evidence-gated episodes.
- An issue, brief, pull request or product source remains authoritative for
  current task state.

There is no LLM in the indexing or retrieval path. SQLite FTS5 ranks keyword
matches. A recall result is a lead, not a generated summary and not truth.

## Default sources

The adapter checks these local paths:

| Harness | Default source |
|---|---|
| Hermes Agent | `~/.hermes/state.db` |
| Claude Code | `~/.claude/projects` |
| Codex | `~/.codex/sessions` |
| Grok | `~/.grok/sessions` |

Missing sources are skipped. Override paths only when the harness really stores
history elsewhere:

```
HERMES_SESSION_DB=/other/path/state.db
CLAUDE_PROJECTS_ROOT=/other/path/projects
CODEX_SESSIONS_ROOT=/other/path/sessions
GROK_SESSIONS_ROOT=/other/path/sessions
AGENT_SESSION_DB=/other/path/sessions.db
```

## Privacy boundary

Only user and assistant dialogue is eligible. The adapters exclude:

- system and developer prompts
- reasoning and thinking blocks
- tool calls and tool outputs
- attachments
- generated compaction and interruption notes
- non-human Hermes jobs
- Claude sidechains, compaction summaries and metadata injections
- Grok synthetic messages
- messages that match the secret scanner

The derived database and its SQLite sidecars are set to owner-only permissions
and gitignored. Do not place them in cloud storage, commit them, attach them to
an issue or copy them between people. If histories live on separate machines,
keep separate indexes unless the operator deliberately approves a secure shared
filesystem.

## Commands

```
./session-memory sync
./session-memory list -n 20
./session-memory recall "distinctive terms" -k 5
./session-memory recall "distinctive terms" --harness claude
```

Initial sync scans all available local histories. Later syncs fingerprint
sources and replace only changed sessions.

## Agent behaviour

The standing rule is:

> When the operator resumes prior work, switches harnesses, or refers to an
> earlier conversation, call `session_recall` before asking them to repeat
> context. Use distinctive terms. Treat transcript hits as leads and verify
> the live task artefact before acting.

Claude Code and Hermes can also receive a small relevant excerpt through their
prompt hooks. The hook excludes the current session when the harness supplies a
session ID, prefers session hits over document hits, and caps injected context
at 1,800 characters. Short prompts and weak one-term matches stay silent.

Codex and Grok use deliberate MCP recall. Grok's passive prompt hooks ignore
stdout, so they cannot inject returned context into the model.

## Acceptance test

1. Have a short conversation in harness A using a unique harmless phrase.
2. Start a fresh session in harness B.
3. Ask harness B what was decided, using two or three distinctive terms.
4. Confirm the result names harness A and includes only user or assistant text.
5. Confirm a secret-shaped test message, tool output and generated summary are
   not recallable.
6. Confirm `sessions.db` remains ignored by Git.

Do not call the setup complete because a tool appears in a menu. Prove one real
cross-harness recall.
