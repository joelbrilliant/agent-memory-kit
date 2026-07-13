# Agent install protocol

This file is written for you, the agent. Your operator has shared this repo and
wants the memory kit installed. Follow these steps in order. Two rules bind you
throughout: never index anything without the operator approving the corpus
list, and never claim a step worked without showing its output.

## 1. Get the operator their own copy, then check it

The path that always works - a plain local clone:

```
git clone https://github.com/joelbrilliant/agent-memory-kit ~/agent-memory-kit
cd ~/agent-memory-kit
```

IF the `gh` CLI is installed and authenticated (check with `gh auth status`)
and the operator wants episodes synced off-machine, you can instead create
their own PRIVATE GitHub copy from the template - never a fork, because forks
of public repos stay public and this repo will hold their episodes:

```
gh repo create agent-memory --template joelbrilliant/agent-memory-kit --private --clone
cd agent-memory
```

Note the directory name differs between the two paths (`agent-memory-kit` vs
`agent-memory`). Whichever you use, the `episodes` glob you write into
corpus.txt in step 2 must point at THIS clone's episodes directory.

Then verify the machine can run it:

```
python3 -c "import sqlite3; c=sqlite3.connect(':memory:'); c.execute(\"CREATE VIRTUAL TABLE t USING fts5(x)\"); print('fts5 ok')"
./test.sh
```

If FTS5 is missing or tests fail, stop and report. Do not work around it.

## 2. Propose the corpus (operator gate)

Explore the machine for the operator's valuable markdown: notes directories,
project docs, past reviews and audits, meeting notes, a personal wiki or vault,
agent memory files. Do NOT include: anything under `.git`, dependency dirs,
credential or config directories, other people's data.

Draft `corpus.txt` (`tag|glob` lines, see `corpus.example.txt`) and, if needed,
`exclude.txt`. **Show both to the operator and get explicit approval before
running ingest.** The operator knows what is sensitive; you are guessing.

## 3. Ingest and report

```
python3 ingest.py
```

Report the full summary: per-tag counts, skips, and especially the
`secret-scan` count with the skipped paths from stderr. If secret-scan caught
files, tell the operator which ones - those files hold key-shaped strings and
deserve attention regardless of this install.

## 4. Verify with known answers (acceptance gate)

Ask the operator for 3-5 things they know are in their notes ("the fix for X",
"the decision about Y"). Tip for a single round-trip: request these facts in
the SAME message where you ask for corpus approval in step 2.

Run `./recall` for each. This is keyword search with stemming, not semantic
search - phrase queries with words likely to appear IN the document (the doc
says "switched supplier", so query "supplier switched", not "which vendor did
I pick"). A result tagged `(or-fallback)` matched on partial terms only -
treat it as a weak hit and rephrase before counting it.

The right document should appear in the top 3. If it does not, the corpus is
missing a source or the query needs the document's own vocabulary - tune and
re-run. Do not declare the install done on a 0-hit index. Show the operator
the actual recall output.

## 5. Wire your own harness

See [examples/harnesses.md](examples/harnesses.md) for Claude Code, Hermes
Agent, Codex, and generic shell harnesses. Minimum viable wiring is the
copy-paste snippet in
[examples/agent-instructions.md](examples/agent-instructions.md) added to your
own standing instructions or skill system: recall 1-2 queries before
substantial work; `remember` only at verified checkpoints, with evidence.

## 6. Schedule the maintenance

- Daily index rebuild: [examples/scheduled-ingest.md](examples/scheduled-ingest.md).
- A self-audit about two weeks out that is allowed to recommend deleting the
  whole thing: [examples/self-audit.md](examples/self-audit.md). Install it as
  a scheduled task if your harness supports one; otherwise put a dated entry
  wherever your operator tracks future work. Do not skip this step - memory
  that never has to prove itself becomes rot.

## 7. Report

Tell the operator: what was indexed (counts by tag), the verification results
from step 4, what was wired where, when the daily rebuild runs, and the
self-audit date. Include the evidence, not just the claims.
