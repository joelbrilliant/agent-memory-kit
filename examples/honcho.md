# The user-model layer

This kit indexes the WORK: the markdown artefacts an operator produces. It does
not model the OPERATOR. That is a different job, and a different layer of the
memory stack (layer 2). The two are complementary. Recall answers "have we seen
this problem before"; a user model answers "who am I working with, and how do
they like things done".

Honcho, an open-source project by Plastic Labs
(github.com/plastic-labs/honcho), fills that layer. It is a separate,
unaffiliated project. This kit does not depend on it and is not endorsed by it;
it is named here because it is the natural fit for the layer this kit
deliberately leaves empty.

## What it provides

Honcho continuously derives a model of a user from the conversations they have
with an agent, and serves that model back as context at runtime. Rather than you
hand-writing "the operator prefers X" into a static file, it infers preferences,
facts, and patterns from the actual dialogue over time and makes them queryable
when the agent needs them. The agent gets a running, self-updating picture of
the person it is working for, without anyone maintaining it by hand.

## Why it complements artefact recall

The two layers sit next to each other and do not overlap:

- This kit models the WORK. It is a search index over files. It is only as good
  as the artefacts you point it at, and it knows nothing about you.
- Honcho models the OPERATOR. It is a derived user model from conversations. It
  knows how you work but nothing about the specific files you have produced.

An agent that has both can start a task already knowing the relevant past work
(recall) and how the operator wants it approached (the user model). Neither
layer tries to be the other, which keeps each one simple and keeps facts in one
home.

## Self-hosting sketch

Honcho can be run locally. The moving parts, at a high level:

- an API service that agents talk to (create sessions, post messages, request
  the derived context),
- a deriver process that reads the conversation history and updates the user
  model in the background,
- a Postgres database backing both.

You run those alongside your agent harness, feed the conversation into it, and
at the start of each session you fetch the derived user-model context and inject
it into the agent's system prompt, the same place you inject the layer-1
handbook. The result is that every session begins with both a fresh view of the
operator (from Honcho) and a searchable view of the work (from this kit).

See the Honcho project's own documentation for exact self-hosting instructions;
the specifics are theirs to define and will change independently of this kit.
