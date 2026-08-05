# Full continuity install prompt

Give this file and the repository URL to the agent that can inspect your local
machine. The agent should adapt to the harnesses that are actually installed.

## Copy this prompt

> Install this repository as my local cross-harness memory and continuity
> layer. Read `AGENT-INSTALL.md`, `examples/session-continuity.md`,
> `examples/harnesses.md` and `examples/mcp.md` completely before changing
> anything.
>
> My goal is to move between Hermes Agent, Claude Code, Codex and Grok without
> repeating prior context. Use only the harnesses that are installed on this
> machine. Do not install Honcho, a vector database, an embedding service, a
> daemon or an LLM memory layer.
>
> Before indexing, show me two separate approval lists:
>
> 1. the markdown corpus you propose for durable work recall
> 2. the exact local session-history paths you propose for transcript recall
>
> Do not index either list until I approve it. Never copy raw transcripts into
> Git or cloud storage. Preserve my existing harness settings and merge narrow
> changes instead of replacing whole config files.
>
> After approval, build both indexes, wire the same `agent-memory` MCP server
> into every compatible harness, add the prompt hook where supported, and add a
> small standing instruction that says to call `session_recall` before asking
> me to repeat earlier context.
>
> Verify the result with:
>
> - the repository test suite
> - a document known-answer query
> - `session-memory list` with counts by installed harness
> - one real cross-harness canary conversation
> - a negative privacy check proving system prompts, reasoning, tools,
>   generated summaries and secret-shaped messages are excluded
> - a check that all derived databases and logs are ignored by Git
>
> Report observed evidence, exact files changed, and any harness that could not
> be wired. Do not claim success from configuration alone. Leave experimental
> preference learning off unless I separately approve it.

## What the operator should expect

The agent will pause twice for approval: once for documents and once for chat
history. That is intentional. Everything after approval is local,
deterministic and reversible.
