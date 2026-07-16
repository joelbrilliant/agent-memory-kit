# Auto-recall in Claude Code

`hooks/claude-recall-hook.py` is a Claude Code `UserPromptSubmit` hook. On every
prompt you submit, it queries the index with the content words of your prompt
and, if anything scores well enough, injects the top hits as extra context
before the model sees your message. When nothing scores past the threshold, or
the prompt is too short, or the index is missing, it stays silent and never
blocks the prompt.

## Wiring it up

Add a `UserPromptSubmit` hook to your Claude Code `settings.json` (either the
user-level `~/.claude/settings.json` or a project `.claude/settings.json`).
Replace `/path/to/agent-memory-kit` with the absolute path to your clone.

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 /path/to/agent-memory-kit/hooks/claude-recall-hook.py"
          }
        ]
      }
    ]
  }
}
```

The hook derives the index path from its own location, so it finds `index.db`
in the repo without further configuration. If you keep the index elsewhere, set
`AGENT_MEMORY_DB` in the hook's environment. Reference the hook in place - do
NOT copy the file into `~/.claude/` or elsewhere, because a moved copy derives
wrong paths for both the index and the `recall` command it advertises.

## Hits are hints

Injected results are leads, not authority: the agent should open the file a hit
points at before relying on it, same as with deliberate recall. And every
injection spends prompt tokens - on thin or chatty prompts the term extractor
can fire on words that only look meaningful, adding noise to the context. If
you notice irrelevant injections, that is what `MIN_PROMPT_WORDS` and
`SCORE_CEILING` below are for.

## Knobs

The tuning constants are at the top of `hooks/claude-recall-hook.py`:

- `MIN_PROMPT_WORDS` (default 6): prompts shorter than this are ignored, so
  quick one-liners do not trigger a recall.
- Score gate (ADAPTIVE): BM25 scores are negative and more negative means a
  better match, but their magnitude grows with corpus size - a bullseye in a
  5-doc corpus scores around -4 while the same quality hit in a 2,500-doc
  corpus scores -15 or deeper. The hook therefore computes its ceiling from
  the index's document count at query time (a -2.0 floor for tiny corpora,
  deepening to -10.0 at ~2,500 docs). To pin it manually, set the
  `SCORE_CEILING` env var in the hook's environment (e.g. "-6.0"): more
  negative injects only on strong matches, toward zero injects more freely.
- `TOP_K` (default 3): how many hits to inject at most.
- `MAX_TERMS` (default 15): cap on how many content words from the prompt become
  search terms.

Start with the defaults. If auto-recall feels noisy, make `SCORE_CEILING` more
negative first.

## The degenerate-hit trap, and hook-exclude.txt

The known failure mode of ambient injection: one broad, wordy document (a
glossary, a sweeping reference) matches almost any prompt and quietly becomes
a large share of everything injected - a live audit of this hook found a
single file behind 18% of all injections. Watch `hook.log`: if the same path
keeps winning for unrelated prompts, copy `hook-exclude.example.txt` to
`hook-exclude.txt` and add a substring of that path. Excluded files stay in
the index for deliberate `recall`; they just stop being ambient noise.

## Two logs, on purpose

The hook logs its automatic injections to `hook.log`, which is separate from the
`usage.log` that `recall` writes for deliberate queries. Keeping them apart
matters for the self-audit: it lets you distinguish memory that an agent reached
for on purpose from memory that was pushed at it automatically. Both files are
gitignored. See [self-audit.md](self-audit.md).
