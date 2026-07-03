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
`AGENT_MEMORY_DB` in the hook's environment.

## Knobs

The tuning constants are at the top of `hooks/claude-recall-hook.py`:

- `MIN_PROMPT_WORDS` (default 6): prompts shorter than this are ignored, so
  quick one-liners do not trigger a recall.
- `SCORE_CEILING` (default -10.0): the BM25 score gate. BM25 scores are negative
  and more negative means a better match, so a hit is injected only when its
  score is at or below this ceiling. Lower it (more negative) to inject only on
  strong matches; raise it toward zero to inject more freely.
- `TOP_K` (default 3): how many hits to inject at most.
- `MAX_TERMS` (default 15): cap on how many content words from the prompt become
  search terms.

Start with the defaults. If auto-recall feels noisy, make `SCORE_CEILING` more
negative first.

## Two logs, on purpose

The hook logs its automatic injections to `hook.log`, which is separate from the
`usage.log` that `recall` writes for deliberate queries. Keeping them apart
matters for the self-audit: it lets you distinguish memory that an agent reached
for on purpose from memory that was pushed at it automatically. Both files are
gitignored. See [self-audit.md](self-audit.md).
