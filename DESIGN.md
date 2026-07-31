# agent-memory-kit - design

This is the philosophy behind the kit. The code is small on purpose; the
discipline is the point. Four ideas carry it: recall before write, exact
dialogue stays separate from durable truth, evidence gates the write path, and
the whole thing must justify its own existence or be deleted.

## Recall first

The cheapest useful memory system is a search index over artefacts you already
have. Most agent work leaves a trail of markdown: notes, review findings,
verification logs, design docs, decision records. That trail is a knowledge
base that nobody made queryable. Making it queryable is a smaller job than
building a write pipeline, and it pays off immediately, because the answer to
"have we seen this before" is usually already sitting in a file.

So the first move is not to build infrastructure for storing new memories. It
is to index the artefacts that exist and put a fast query in front of them.
`ingest.py` does a full rebuild of an FTS5 index over globbed markdown;
`recall` runs a BM25 query against it. That is the whole read path, and for a
single-operator corpus it is enough. A full rebuild over a few thousand files
finishes in about a second, so there is no incremental-update machinery to get
wrong.

Only after recall is working does a write path earn its place. The one thing
the existing artefacts miss is episodes: short, dated notes of what happened
and what to do differently next time. That gap is what `remember` fills, and
nothing more.

## Exact dialogue is a separate index

Cross-harness continuity is a retrieval problem, not a licence to turn every
conversation into durable memory. `session-memory` indexes eligible user and
assistant dialogue from local Hermes, Claude Code, Codex and Grok histories
into a separate gitignored SQLite database. It excludes system prompts,
reasoning, tools, attachments, generated notes, non-human jobs and
secret-shaped messages.

The split matters. A transcript can recover what someone actually said, but it
may be stale, mistaken or superseded. A session hit is therefore a lead used to
resume the work. The current issue, brief, pull request or product source
remains authoritative. No generated summary is promoted into either index.

## Experimental learned state is separate again

The Slice 1 learning loop uses the session projection as read-only evidence but
stores its own provisional claims in `learning.db`. This is local canonical
experimental state, not a rebuildable transcript index. It is never committed
and can be discarded as one database file set while the experiment remains in
shadow mode.

Schema version 1 is created idempotently by `_learning_store.py` and recorded
in `learning_schema`. Ordinary tables hold review batches, immutable batch
membership, claims, cited evidence snippets and per-message review state. FTS5
indexes only claim statement and scope fields. Constraints enforce one open
batch per source session, one normalised claim per operator, bounded domain
scope keys and unique evidence links. Future schema changes must advance the
recorded version and migrate in place rather than reinterpret transcript data.

The active harness model may propose a preference, but `learning_loop.py`
accepts only an exact user-authored quote from the stored batch and creates a
provisional claim. Retrieval is deterministic, bounded and operator-isolated.
Automatic review triggers, lifecycle changes and claim promotion belong to a
later slice.

## Write discipline

Memory systems rot from garbage writes, not bad reads. A wrong entry in a
search index is worse than a missing one, because it comes back later wearing
the authority of a stored fact and gets trusted precisely when you have
stopped scrutinising it.

So the write path is gated. `remember` refuses to run without `--evidence` (a
file path, a commit SHA, a PR or issue URL, or a log path) and a `--source`.
The gate is not a suggestion enforced by a linter; it is a hard exit-2 in the
tool. The intent is that episodes get written only at verified checkpoints: a
signed-off change, an accepted review finding, or an explicit human
instruction. Never mid-run, never speculative, never an agent's unverified
claim. The same rule that says "an external agent's claim is not proof" applies
to the memory store: if you cannot point at evidence, you do not get to write.

Because episodes are plain markdown under version control, treat the store the
way you treat any synced git repo: do not write anything into it that you would
not want committed and shared.

## Self-audit and kill criteria

Memory that cannot prove it changed an outcome is a liability, not an asset. It
costs attention on every read and it accumulates rot. So the kit is built to be
killable, and it expects you to schedule the audit that might kill it.

`recall` logs every deliberate query and its top hit to `usage.log`. The
optional Claude Code hook logs its automatic injections to a separate `hook.log`
so you can tell deliberate recall apart from automatic. Point a scheduled prompt
at those logs and the episodes directory on a fixed cadence and make it answer
one question: did recall demonstrably change any outcome (a repeat issue caught,
a run shortened, a known finding avoided)? If the honest answer over a real
window is no, the recommendation is to delete the kit. The audit is report-only;
it never deletes anything itself. But it is allowed, and expected, to recommend
its own removal. There is no sentimental infrastructure.

## One home per fact

Every fact should live in exactly one place. The durable memory store owns
episodes. The separate experimental learning store owns provisional claims and
their cited evidence snippets. Everything else the kit touches, it only reads.
The corpus globs point at files that other systems own; the index never becomes
their canonical home. If a piece of knowledge belongs in a skill file, a
runbook, or a design doc, it goes there, not into an episode or provisional
claim that quietly forks the truth.

Derived artefacts are never the source of truth and never synced. `index.db`,
`sessions.db`, `usage.log`, `hook.log`, and `ingest.log` are all rebuilt per
machine and gitignored. `learning.db` is also local and gitignored, but it is
not rebuildable because it owns experimental claims. Clone the repo onto
another machine and rebuild only the derived indexes against sources available
there. Nothing local travels unless the operator provides a separate secure
state-transfer mechanism.

## Rejected paths (named)

Naming what was considered and rejected is part of the design, so the choices do
not get relitigated by accident.

- **Embeddings / vector DB first.** Rejected. It is more infrastructure (a model,
  an embedding store, a similarity index) with no evidence that keyword search is
  the bottleneck. BM25 with porter stemming over curated markdown is boring,
  dependency-free, and good enough until a measured miss proves otherwise. Reach
  for embeddings when you can point at recall failures they would fix, not before.

- **A five-level cognitive memory store with activation decay.** Rejected. The
  layered-store, activation-maths, consolidation-loop design is ceremony for a
  single-operator setup. It adds moving parts that all have to be correct before
  any of it helps. Start with a flat index and one write path; revisit only if
  that plateaus against real usage.

- **LLM summaries as the cross-harness archive.** Rejected. A summary adds
  interpretation, can drift, and cannot replace the underlying conversation.
  Index eligible dialogue directly, retrieve small excerpts on demand, and
  verify against the live artefact.

- **MCP-only integration.** Rejected as the sole interface. A plain CLI works in
  every harness that can run a shell, with no protocol coupling, and it is
  trivially scriptable and testable. The MCP server ships too (`mcp_server.py`),
  but as an additional surface, not as the thing you must adopt. Existing
  memory calls retain their CLI implementation and the learning CLI and MCP
  tools share the same public Python functions. One implementation per
  behaviour, with two ways to call it.
