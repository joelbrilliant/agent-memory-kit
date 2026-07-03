# Harness wiring notes

The kit is deliberately CLI-first: any harness that can run a shell command can
use it. Specific notes per harness:

## Claude Code

Two options, use both:
- Auto-recall on every prompt via the UserPromptSubmit hook - see
  [claude-code-hook.md](claude-code-hook.md).
- A line in your CLAUDE.md or a skill so deliberate recall happens at task
  start - see [agent-instructions.md](agent-instructions.md).

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

## Codex

Add the [agent-instructions.md](agent-instructions.md) snippet to
`~/.codex/AGENTS.md` (or the project AGENTS.md) with absolute tool paths. Codex
runs the CLIs via shell like anything else.

## Anything else with a shell

The contract is three commands: `python3 ingest.py` (rebuild), `recall "query"
-k 5` (search), `remember --source X --evidence Y "text"` (write). Wire them
wherever your harness keeps standing instructions. For harnesses that speak MCP
but not shell, use [mcp.md](mcp.md).
