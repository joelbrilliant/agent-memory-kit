# agent-memory-kit

## What this is

Local, boring-on-purpose memory for AI agents. It gives an agent two things:
BM25 full-text search over the markdown you already have (`recall`), and an
episodic write path that refuses to record anything without evidence
(`remember`). The search is plain SQLite FTS5 with porter stemming. There are
no embeddings, no vector database, no daemon, and no third-party dependencies.
It is Python 3 standard library only. You point it at your markdown, rebuild an
index, and query it. That is the whole thing.

## Get your own copy

This is a GitHub template repository. Three doors, pick yours:

**You run an agent (easiest).** Click **Use this template** above and create
your copy - choose **private**, because your episodes will live in it. Then
paste this to your agent, along with your new repo's URL:

> Read the AGENT-INSTALL.md in this repo and install it for me. Propose the
> corpus list for my approval before you index anything.

[AGENT-INSTALL.md](AGENT-INSTALL.md) walks the agent through the rest: corpus
proposal (with you as the approval gate), ingest, known-answer verification,
harness wiring, and scheduling the maintenance - including the self-audit that
can recommend deleting the whole thing.

**You are an agent reading this.** Follow [AGENT-INSTALL.md](AGENT-INSTALL.md).
If your operator wants episodes synced off their machine, give them their own
private copy first:

```
gh repo create agent-memory --template joelbrilliant/agent-memory-kit --private --clone
```

**You are a human without an agent.** The quickstart below is all of it; a
plain `git clone` works fine if you do not need your episodes on GitHub.

**One warning about forks.** Fork freely to hack on the code - but do not use
a fork as your live memory home. Forks of public repositories stay public on
GitHub, and a copy you actually use contains your episodes. Your working copy
should be a private template copy or a local clone.

## The architecture it belongs to

This kit is layers 3 and 4 of a five-layer memory stack, plus the wiring for
the rest. The stack:

1. A small hand-written "handbook" of contracts the agent reads at the start of
   every session. This is the load-bearing, human-curated layer: how you work,
   what the non-negotiables are, where things live. It stays hand-written.
2. A user-model layer that learns the operator from conversations over time.
   See [examples/honcho.md](examples/honcho.md). The open-source Honcho project
   by Plastic Labs fills this layer. This kit is not affiliated with it.
3. Searchable recall over work artefacts. This kit. `ingest.py` + `recall`.
4. Evidence-gated episodes. This kit. `remember`.
5. Procedures and skills as files. Ordinary markdown or scripts the agent reads
   and follows, owned wherever they naturally live.

This repo ships layers 3 and 4 and points at how to wire in the rest (the hook,
the MCP server, the user-model layer, the agent instructions). It does not try
to own the other layers, because facts should live in one home each and these
already have theirs.

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

## The two rules that matter

**Evidence-gated writes.** `remember` will not write an episode without
`--evidence` and a `--source`. This is deliberate and it is a hard gate, not a
warning. An unverified claim in a memory store is worse than no memory, because
it comes back later wearing authority: it gets trusted exactly when you have
stopped checking it. The evidence can be a file path, a commit SHA, a PR or
issue URL, or a log path. If you cannot point at one, you do not get to write.

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
- [examples/honcho.md](examples/honcho.md) - the user-model layer, and how it
  complements this kit.
- [examples/agent-instructions.md](examples/agent-instructions.md) - a
  copy-paste system-prompt snippet for any agent harness.

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

## Requirements

- Python 3.8 or newer.
- SQLite compiled with FTS5. This is standard on macOS and most Linux
  distributions. The quickstart command above verifies it.

No other dependencies.

## A note on scale

As an anecdote, not a benchmark: on the author's corpus of roughly 2,400
documents, a full rebuild takes under a second, and known-answer verification
scored 10/10 on hit@3. Your numbers will differ. No other performance or
capability claims are made here.
