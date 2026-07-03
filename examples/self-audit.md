# Self-audit

Memory that cannot prove it changed an outcome should die. It costs attention on
every read and it accumulates rot. So the kit is designed to be killed, and it
expects you to schedule the audit that could kill it.

Schedule a prompt on a fixed cadence (a fortnight is a reasonable first window)
that reads the logs and the episodes, judges whether recall demonstrably earned
its keep, and reports a verdict. The audit is report-only: it never deletes
anything. It is allowed, and expected, to recommend deleting the whole kit.

Wire the schedule with whatever runs prompts on a timer in your setup (a
scheduled agent, a cron job that calls your CLI in one-shot mode, and so on).

## Prompt template

> You are auditing a local agent-memory tool. Read these three inputs from the
> repo at `/path/to/agent-memory-kit`:
>
> - `usage.log`: deliberate `recall` queries. Each line is `timestamp TAB query
>   TAB top-hit-path` (or `NONE` when nothing matched).
> - `hook.log`: automatic recall injections from the Claude Code hook, same
>   format. Deliberate recall (usage.log) is the stronger signal; automatic
>   injection (hook.log) shows what was pushed, not what was reached for.
> - `episodes/`: the evidence-gated episodes written since the last audit.
>
> Answer one question with evidence: over this window, did recall demonstrably
> change any outcome? Concretely, did it catch a repeat issue, shorten a run,
> surface a past decision that would otherwise have been redone, or prevent a
> known finding from recurring? Quote specific log lines or episodes as evidence.
> Absence of use is not neutral; it counts against keeping the tool.
>
> Report exactly one verdict: KEEP or KILL, followed by the evidence that
> supports it. Do not delete anything. Do not modify the index, the logs, or the
> episodes. Report only.

## Suggested kill criteria

Make the criteria explicit in the prompt so the verdict is not a vibe. A
reasonable default:

> Recommend KILL if, over the window, recall demonstrably changed zero outcomes:
> no repeat issue caught, no run shortened, no past decision recovered, no known
> finding avoided. A tool that was queried and returned results but never changed
> what actually happened has not earned its keep. When in doubt, recommend KILL:
> the cost of keeping dead infrastructure is paid on every future read, and the
> tool is cheap to stand back up if it turns out to be needed.

If the verdict is KILL, deleting the kit is a human decision made after reading
the report, not something the audit does on its own.
