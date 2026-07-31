# Agent instructions

Drop this into a system prompt, a skill file, or whatever your harness uses to
give an agent standing instructions. It teaches the agent to read before it
works and to write only what it can prove. Replace `/path/to/agent-memory-kit`
with the absolute path to your clone.

## Copy-paste snippet

> You have a local memory tool at `/path/to/agent-memory-kit`.
>
> Before starting any substantial task, run one or two recall queries against
> it to check whether this problem, bug class, config gotcha, or decision has
> been seen before:
>
>     /path/to/agent-memory-kit/recall "2-8 content words"
>
> Recall results are leads, not answers. Open the file a hit points at before
> relying on anything in it. If nothing relevant comes back, proceed; a miss is
> normal.
>
> When the operator resumes prior work, switches harnesses, or asks what was
> decided earlier, search local dialogue before asking them to repeat context:
>
>     /path/to/agent-memory-kit/session-memory recall \
>       "distinctive terms from the earlier conversation" -k 5
>
> Session hits are transcript leads, not authority. Use them to locate the
> work, then verify the current issue, brief, pull request or live artefact.
>
> Write a memory episode only at a verified checkpoint: a change that has been
> signed off, a review finding that has been accepted, or an explicit
> instruction to record something. When you do, you must supply evidence (a file
> path, a commit SHA, a PR or issue URL, or a log path). The tool refuses to
> write without it, by design.
>
>     /path/to/agent-memory-kit/remember --source <you> --evidence <ref> \
>       --tags <optional,comma,separated> "what happened and what to do next time"
>
> Never write an episode mid-task, never write a speculative or unverified
> claim, and never record something you would not want committed to a shared git
> repo. An unverified claim in the memory store is worse than no memory, because
> it comes back later wearing authority.
>
> Episodes record lessons about the WORK. Facts about the OPERATOR - their
> preferences, habits, current projects, personal context - do not belong in
> episodes. Those live in the hand-written operator handbook or an explicitly
> chosen user-model layer. One fact, one home; do not open a second write path
> for operator facts just because this one is convenient.
>
> An episode is a LESSON, not a status report. The test: will this still be
> true and useful in a month? "Phase 1 completed, queue at X" belongs in your
> tracker and rots in a week; "X fails when Y, do Z instead" is an episode.
> Status snapshots written as episodes duplicate your tracker and poison
> future recalls with stale state.

## Why these two habits

The read habit is cheap insurance: one query at the top of a task often surfaces
a past incident or decision that saves a wrong turn. The write discipline is
what keeps the read habit worth having: a store that only ever received
evidence-backed episodes stays trustworthy, so future recalls are worth acting
on. Skip the discipline and the store fills with plausible-sounding claims that
poison every later read.
