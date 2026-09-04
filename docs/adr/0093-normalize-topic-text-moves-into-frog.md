# ADR-0093: `normalize_topic_text` moves into `frog`; `spoin` imports it

- **Status:** Accepted
- **Date:** 2026-09-05
- **Deciders:** project owner, implementing session
- **Amends:** [ADR-0087](0087-frog-is-a-sibling-package.md) — reverses its "`normalize_topic_text` stays in `spoin`" clause

## Context

[ADR-0087](0087-frog-is-a-sibling-package.md) moved the `Embedder` classes into `frog`
and deliberately left two things behind in `spoin.embeddings`:

- **`get_embedder()`**, because it reads `spoin.core.config`, and a second settings
  object in frog would put `embedding_dim` in two places — a divergence there produces
  vectors that are silently not comparable.
- **`normalize_topic_text`**, on the grounds that it is "topic-canonicalization logic
  that happens to be applied before embedding, not embedding infrastructure", and that
  task 0001's threshold calibration depends on it.

Those two look like the same call. They are not, and the difference only became visible
when something needed to call the second one from the other side of the boundary.

[ADR-0088](0088-the-spoin-universe.md) says `chunk.topic_tags` are produced by *the
same* `normalize_topic_text` that `spoin` applies before embedding a topic string, and
says why in the same sentence: **"one normalizer, so tags and canonical topic names
cannot drift into two vocabularies."** [ADR-0091](0091-corpus-category-hierarchy.md)
then extended that to `document.category` and `document.sub_category`, for the same
reason and with a sharper consequence — an inconsistent `category` proposes itself to
the owner as an option forever.

Both of those callers are the ingester. **The ingester lives in `frog`, and frog cannot
import `spoin`** (ADR-0087, enforced by a ruff `banned-api` entry and an AST check in
`apps/api/tests/test_architecture.py`). So ADR-0087's placement and ADR-0088's
one-normalizer requirement are in direct contradiction, and Phase 2 could not be built
without resolving it.

## Decision

**`normalize_topic_text` moves to `frog.embeddings`. Every `spoin` call site imports it
from there.**

### Why this and not the reverse

The argument that kept `get_embedder()` in `spoin` does not transfer.
`get_embedder()` reads settings; moving it means frog owns a second copy of
`embedding_dim`, and that copy can disagree. `normalize_topic_text` is a **pure
function of a string** with no settings dependency and no configuration to duplicate.
There is nothing for a second home to diverge *about* except the code itself — which is
exactly what moving it prevents.

The stated reason for leaving it — task 0001's threshold calibration depends on it not
drifting — argues *for* the move rather than against it. What that calibration needs is
one implementation. Which package holds it is irrelevant to a threshold; how many copies
exist is not.

### No re-export shim in `spoin.embeddings`

Consistent with ADR-0087's treatment of the `Embedder` classes. All six `spoin` call
sites import from `frog.embeddings` directly. A shim would hide the `api -> frog`
dependency at precisely the places a reader needs to see it, and CLAUDE.md's
"a rule stated only in a doc is a wish" applies to the boundary as much as to anything
else.

## Consequences

**Easier.** ADR-0088's one-normalizer requirement becomes structurally true rather than
aspirational: there is one function, in the package both consumers depend on, and the
import direction makes a second copy impossible to add without noticing. The ingester
can normalize `topic_tags`, `category` and `sub_category` with the same call `spoin`
uses for topic canonicalization, which is what ADR-0091 assumed all along.

**Harder.** A reader looking for topic canonicalization now finds it in the retrieval
package, which is not where the name suggests. Mitigated by a docstring in each module
pointing at the other and at this ADR — the same mitigation ADR-0087 used for the
embedder split, and the same residual cost.

**Committed to.** `frog` now owns a piece of logic that is not retrieval infrastructure,
on the grounds that it is a pure function shared across the boundary. That is a
precedent: the next pure, settings-free helper both packages need has an obvious home,
and anything needing `spoin.core.config` still does not.

## Alternatives considered

**Duplicate the function in frog.** Five lines, no ADR, no import changes. Rejected: it
recreates precisely the two-vocabulary drift ADR-0088's sentence exists to prevent, and
the failure is silent — the corpus's tags and the product's canonical topic names would
simply stop matching, with nothing raising and no test that would notice. This is the
"a hard rule gets enforced, not documented" rule pointed at the very rule it comes from.

**A third package both depend on.** Correct layering for genuinely shared pure logic,
and it keeps "topic canonicalization" out of a package named for retrieval. Rejected as
disproportionate: a `pyproject.toml`, a lint configuration, a mypy configuration, a
Dockerfile `COPY` and a compose mount, for one five-line function. Worth revisiting if a
second and third such function appear — see "Revisit when".

**Move the ingester into `spoin` instead.** Keeps every function where it is. Rejected:
the ingester writes `the_spoin_universe`, which frog owns (ADR-0088), and `spoin` has no
business holding a corpus writer. It would also invert the dependency the whole
sibling-package layout exists to fix.

**Pass the normalizer into the ingester as a callable.** frog stays ignorant of it;
`spoin` injects it at the call site. Rejected: the ingester's entrypoint is a `frog` CLI
that `spoin` never runs, so there is no caller to inject from. It would mean the corpus
is normalized correctly only when ingested through the API, which is not how it is
ingested at all.

## Revisit when

- A second pure helper needs to cross the same boundary. Two is a coincidence; three is
  the signal that the shared package rejected above has actually earned itself.
- `get_embedder()` stops reading settings. That is the only thing keeping the factory in
  `spoin`, and if it changes the split described in ADR-0087 should be re-argued rather
  than inherited.
