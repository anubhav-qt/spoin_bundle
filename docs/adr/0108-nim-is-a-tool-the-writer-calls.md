# ADR-0108: NIM is a tool the writer calls, and answers in text

- **Status:** Accepted
- **Date:** 2026-10-13
- **Deciders:** project owner

## Context

The owner's rule is that only the big writes go to NIM: a whole corpus document, curriculum,
tier's cards or tier's quiz, in one call each (task 0045). The first version wrapped each real
write tool (`write_document`, `write_curriculum`, `write_cards`, `write_questions`) so that the
writer's call took only instructions and NIM wrote the real tool call. Two things went wrong in
the first Rust run:

- NVIDIA sends a tool call's arguments in one piece once they are all written. A probe saw 121 s
  of silence and then 4,267 tokens at once, so every big write was minutes of silence, and nine
  were cut by the 240 s stall limit while NIM was still writing.
- Code had to guess which calls were big. A fix or a dropped section waited five minutes on NIM to
  write a few hundred tokens, and once code sent every later call to Gemini, a big write after a
  failed one went to Gemini as well.

## Decision

The Gemini writer decides. A writer chat has the real write tools, which it calls itself for
small writes (a fix, a few cards, a section added or dropped), and `write_on_nim(tool,
instructions)` for big ones. `write_on_nim` hands NIM the writer's whole chat and the
instructions, with `tool_choice: "none"`, and asks for the tool's arguments as one JSON object
in text. Code parses it and stores it through the real tool, whose checks decide what passes.
The result shows what NIM wrote and what was stored or refused, so the writer can fix a
refusal with the real tool without paying NIM twice.

`write_on_nim` makes one call. The NIM balancer retries that call across its ladder (busy,
rate-limited, cut off or silent) and Gemini takes it once NIM gives up. An answer that comes
back unusable, with no JSON or refused by the checks, goes back to the writer, which calls
again with what to change.

## Consequences

- NIM's answer streams token by token, so the stall timer measures real silence again.
- The split between big and small writes is the writer's judgement, stated in its prompt, not a
  rule in code.
- A curriculum refused for one problem is still sent whole by whoever fixes it: `write_curriculum`
  has no partial updates.
- NIM writes JSON in text, so a malformed object is refused at parse time and returned to the
  writer, not retried in the tool.

## Alternatives considered

- **Keep NIM writing the tool call and raise the stall limit.** The limit is raised anyway (900 s
  for NIM), but a buffered tool call leaves no way to tell a long write from a dead call, and
  code still decides who writes.
- **Retry unusable answers inside the tool.** Rejected by the owner: the writer already has the
  feedback and decides whether to fix it or ask NIM again.

## Revisit when

NIM streams tool-call arguments as they are written, or a writer keeps handing small writes to
NIM despite its prompt.
