# Harness wiring notes

The kit is deliberately CLI-first: any harness that can run a shell command can
use it. Specific notes per harness:

## Claude Code

Two options, use both:
- Auto-recall on every prompt via the UserPromptSubmit hook - see
  [claude-code-hook.md](claude-code-hook.md).
- A line in your CLAUDE.md or a skill so deliberate recall happens at task
  start - see [agent-instructions.md](agent-instructions.md).

The hook can inject a relevant excerpt from another local harness. Registering
`mcp_server.py` also gives Claude the explicit `session_recall` and
`session_list` tools.

## Hermes Agent

The reliable path is a skill. Create
`~/.hermes/skills/<category>/agent-memory/SKILL.md` with standard skill
frontmatter (name, description stating when to use it) and the snippet from
[agent-instructions.md](agent-instructions.md) as the body, with the absolute
paths to `recall` and `remember` on your machine. Hermes agents load skills
before substantial work, so the description is what triggers usage - make it
say "use at the start of substantial tasks to recall past fixes and findings".

`mcp_server.py` can also be registered if your Hermes version supports MCP
servers - consult the Hermes documentation for the current registration syntax
rather than guessing config keys.

Recent Hermes versions can run the same hook as a `pre_llm_call` shell hook.
The hook detects Hermes's wire format and emits native context. Keep the
explicit MCP tools as well so the agent can search deliberately.

## Codex

Add the [agent-instructions.md](agent-instructions.md) snippet to
`~/.codex/AGENTS.md` (or the project AGENTS.md) with absolute tool paths. Codex
runs the CLIs via shell like anything else. Register `mcp_server.py` as a stdio
MCP server when available so session recall is a first-class tool.

## Anything else with a shell

The contract is four commands: `python3 ingest.py` (rebuild documents),
`recall "query" -k 5` (search documents), `session-memory recall "query" -k 5`
(search dialogue), and `remember --source X --evidence Y "text"` (write a
verified lesson). Wire them wherever your harness keeps standing instructions.
For harnesses that speak MCP but not shell, use [mcp.md](mcp.md).

## Experimental learning loop

The optional learning loop reuses the same shell and MCP seams. Codex,
Hermes Agent, Claude Code and Grok can call `learn_tick`, `learn_submit` and
`context_packet` and `learn_forget` through MCP where supported, or the equivalent
`learning-memory` commands from a shell or skill.

Learning remains manual by default. Each harness must expose at least one usable
integration surface and its transcript source must be approved and readable by
the shared session projection. The shared Claude and Hermes/Grok-compatible hook
can run bounded automatic review only when
`AGENT_MEMORY_AUTOMATIC_LEARNING=1` is explicitly set in that hook's
environment. See [../LEARNING-LOOP.md](../LEARNING-LOOP.md) for the exact safety
boundary.
