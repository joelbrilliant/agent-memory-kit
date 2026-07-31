# agent-memory-kit

## What this is

Local, boring-on-purpose memory for AI agents. It gives participating local
harnesses four shared capabilities:

- BM25 full-text search over the markdown you already have (`recall`)
- an episodic write path that refuses to record anything without evidence
  (`remember`)
- on-demand recall over local Hermes, Claude Code, Codex and Grok dialogue
  (`session-memory`)
- an experimental, evidence-backed learning loop for explicit operator
  preferences (`learning-memory`)

Both indexes use plain SQLite FTS5. There are no embeddings, no vector
database, no daemon, no external service and no LLM in the indexing or
retrieval path. It is Python 3 standard library only.

## Get your own copy

This is a GitHub template repository. Three doors, pick yours:

**You run an agent (easiest).** Click **Use this template** above and create
your copy - choose **private**, because your episodes will live in it. Then
paste this to your agent, along with your new repo's URL:

> Read AGENT-INSTALL.md and CONTINUITY-INSTALL.md in this repo and install the
> full cross-harness memory stack for me. Propose both the markdown corpus and
> local session sources for my approval before you index anything.

[AGENT-INSTALL.md](AGENT-INSTALL.md) walks the agent through the rest: corpus
proposal (with you as the approval gate), ingest, known-answer verification,
harness wiring, and scheduling the maintenance - including the self-audit that
can recommend deleting the whole thing.

If your main goal is continuity between agents, use the ready-to-paste prompt
in [CONTINUITY-INSTALL.md](CONTINUITY-INSTALL.md).

**You are an agent reading this.** Follow [AGENT-INSTALL.md](AGENT-INSTALL.md).
If your operator wants episodes synced off their machine, give them their own
private copy first:

```
gh repo create agent-memory --template joelbrilliant/agent-memory-kit --private --clone
```

**You are a human without an agent.** The quickstart below is all of it; a
plain `git clone` works fine if you do not need your episodes on GitHub.

**Upstream and your copy.** This repo is the upstream template and stays clean
of anyone's data; the copy you actually use (private template copy or local
clone) is your production install. To pull later kit improvements into your
copy: `git remote add upstream https://github.com/joelbrilliant/agent-memory-kit`,
then `git fetch upstream` and merge or cherry-pick what you want.

**One warning about forks.** Fork freely to hack on the code - but do not use
a fork as your live memory home. Forks of public repositories stay public on
GitHub, and a copy you actually use contains your episodes. Your working copy
should be a private template copy or a local clone.

## The architecture it belongs to

This kit provides the deterministic read and write layers of a five-layer
memory stack, plus wiring examples for the rest:

1. A small hand-written "handbook" of contracts the agent reads at the start of
   every session. This is the load-bearing, human-curated layer: how you work,
   what the non-negotiables are, where things live. It stays hand-written.
2. Live task state in the issue, brief, pull request or product source of truth.
   Current status does not belong in memory.
3. Searchable recall over work artefacts and evidence-gated episodes. This kit.
   `ingest.py`, `recall` and `remember`.
4. Exact prior dialogue, indexed locally and recalled only when relevant. This
   kit. `session-memory`.
5. Procedures and skills as files. Ordinary markdown or scripts the agent reads
   and follows, owned wherever they naturally live.

This does not infer a personality model or silently promote chat into durable
truth. A user-model product can be added separately if you genuinely need one,
but cross-harness continuity does not require it.

## Quickstart

First, confirm your Python has SQLite compiled with FTS5. Most builds on macOS
and mainstream Linux distributions do:

```
python3 -c "import sqlite3; c=sqlite3.connect(':memory:'); c.execute(\"CREATE VIRTUAL TABLE t USING fts5(x)\"); print('fts5 ok')"
```

If that prints `fts5 ok`, you are set. Then:

```
cp corpus.example.txt corpus.txt      # then edit corpus.txt for your machine
python3 ingest.py                      # build index.db from your corpus
./recall "some query"                  # search it
./remember --source me --evidence "commit abc123" "what I learned"
```

`corpus.txt` is a list of `tag|glob` lines. Leading `~/` is expanded. Only `.md`
files are indexed. See the comments in `corpus.example.txt` for the details.

To build the separate local transcript index:

```
./session-memory sync
./session-memory list -n 20
./session-memory recall "distinctive terms from an earlier conversation" -k 5
```

The default source paths are `~/.hermes/state.db`, `~/.claude/projects`,
`~/.codex/sessions` and `~/.grok/sessions`. Missing harnesses are skipped.
Nothing from `sessions.db` is committed or sent anywhere.

## Experimental learning loop

Slice 1 is an experimental but working cross-harness learning loop. One
harness can review an exact operator message, submit a provisional preference
claim, and another can retrieve a compact context packet with an evidence
reference. The core validates the evidence and stores only the cited quote in
the local, ignored `learning.db`.

It stays in shadow mode. Nothing is injected automatically, no model runs
inside the core, and no canonical memory or skill file is edited. Automatic
lifecycle-triggered review across harnesses is Slice 2 and is not included.
Participation is not zero-configuration: each harness needs at least one
usable integration surface such as MCP, shell access, a lifecycle hook,
readable transcripts, or an export API.

See [LEARNING-LOOP.md](LEARNING-LOOP.md) for setup, doctor checks, CLI and MCP
usage, harness adapter examples, and the runnable synthetic round trip.

## The two rules that matter

**Evidence-gated writes.** `remember` will not write an episode without
`--evidence` and a `--source`. This is deliberate and it is a hard gate, not a
warning. An unverified claim in a memory store is worse than no memory, because
it comes back later wearing authority: it gets trusted exactly when you have
stopped checking it. The evidence can be a file path, a commit SHA, a PR or
issue URL, or a log path. If you cannot point at one, you do not get to write.
Note the gate forces a *reference*, it does not validate one - a fabricated
path passes the tool. That is deliberate: verification is the self-audit's
job, and a citation that leads nowhere is exactly what an audit catches.

**One home per fact.** This store owns exactly one thing: episodes. Everything
else it indexes, it reads and never claims to own. Derived files (`index.db`,
`usage.log`, `hook.log`, `ingest.log`) are rebuilt per machine and never synced;
they are gitignored. Clone the repo elsewhere, rebuild the index against
whatever corpus exists on that machine, and you are current. If a fact belongs
in a skill file or a design doc, it goes there, not into an episode that forks
the truth.

## Integrations

Each is a short, practical file under [examples/](examples/):

- [examples/claude-code-hook.md](examples/claude-code-hook.md) - auto-recall on
  every Claude Code prompt via a UserPromptSubmit hook.
- [examples/mcp.md](examples/mcp.md) - register `mcp_server.py` so `recall` and
  `remember` become first-class tools in an MCP-capable harness.
- [examples/scheduled-ingest.md](examples/scheduled-ingest.md) - rebuild the
  index on a schedule (launchd on macOS, cron on Linux).
- [examples/self-audit.md](examples/self-audit.md) - a scheduled prompt that
  judges whether recall earned its keep and reports KEEP or KILL.
- [examples/honcho.md](examples/honcho.md) - an optional user-model layer. It
  is not required for deterministic cross-harness continuity.
- [examples/agent-instructions.md](examples/agent-instructions.md) - a
  copy-paste system-prompt snippet for any agent harness.
- [examples/session-continuity.md](examples/session-continuity.md) - session
  source paths, privacy boundaries, verification and per-harness behaviour.
- [examples/learning-loop-e2e.py](examples/learning-loop-e2e.py) - a synthetic
  Codex-to-Hermes round trip through the published CLI.

## Self-audit

The kit expects you to schedule a checkpoint that is allowed to recommend
deleting it. Memory that cannot prove it changed an outcome should die: it costs
attention on every read and it accumulates rot. Point a scheduled prompt at
`usage.log`, `hook.log`, and `episodes/`, ask whether recall demonstrably
changed any outcome over the window, and have it report KEEP or KILL with
evidence. It never deletes anything itself. See
[examples/self-audit.md](examples/self-audit.md).

## Honest limitations

- It is keyword search (BM25 with porter stemming), not semantic search. It
  finds documents that share words with your query, stemmed; it does not
  understand meaning. Synonyms and paraphrases can miss.
- It indexes markdown files only. Other formats are ignored.
- It is a single-user, local design. There is no server, no multi-tenant
  story, and no concurrency model beyond one person on one machine.
- The auto-recall hook uses a small hard-coded English stopword list, so its
  term extraction is English-only. The CLIs themselves are language-agnostic.
- Session continuity is local to one machine. If harness histories live on
  different machines, each machine has its own index unless you deliberately
  provide a secure shared filesystem. The kit never syncs raw transcripts.
- The learning loop accepts explicit preference evidence only and creates
  provisional claims. Confirmation, rejection, supersession, deletion and
  automatic lifecycle review are not implemented in Slice 1.

## Requirements

- Python 3.9 or newer.
- SQLite compiled with FTS5. This is standard on macOS and most Linux
  distributions. The quickstart command above verifies it.

No other dependencies. The repository is a script-based kit rather than a pip
package and is distributed under the MIT licence in [LICENSE](LICENSE).

## A note on scale

As an anecdote, not a benchmark: on the author's corpus of roughly 2,400
documents, a full rebuild takes under a second, and known-answer verification
scored 10/10 on hit@3. Your numbers will differ. No other performance or
capability claims are made here.
