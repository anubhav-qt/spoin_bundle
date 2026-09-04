"""Standalone provider-behaviour probes.

These are diagnostic instruments, not part of any request or generation path.
They exist because the single most expensive lesson of the Gemini work
(docs/gemini-saga/) was that **the pipeline is a terrible instrument** -- too many
variables move at once and every run costs ten minutes, so a limit that a
controlled sweep finds in an afternoon took four weeks to find through it.

They are committed rather than kept in a scratchpad for the same reason: the
Gemini probes were nearly lost, and their numbers are now the only evidence behind
several config constants.
"""
