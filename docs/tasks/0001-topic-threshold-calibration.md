# Task 0001: Topic similarity threshold calibration

- **Owner:** Mayank
- **Timebox:** ~1 day
- **Depends on:** nothing. This is fully self-contained.
- **Background reading:** [ADR-0004](../adr/0004-topic-canonicalization.md), then
  [architecture/overview.md](../architecture/overview.md)

## The problem

Users can add their own topics (3 free, unlimited behind premium later). Our entire cost
model depends on cards being **shared** between users: we generate one card about Kubernetes
and serve it to everyone interested in Kubernetes.

If every user creates private topics, we end up with thousands of topics that have one
reader each, and generation cost per user explodes. We are on a free LLM tier, so this kills
the product rather than merely making it expensive.

The fix: most custom topics are not new. `k8s`, `kubernetes` and `container orchestration`
are one topic with three names. So when a user adds a topic we embed it, compare against
existing topics, and merge if it is close enough. The user still sees **their own name** for
it in the UI, so it feels personal, while the system stores one shared entity.

## What we need from you

The similarity thresholds that decide merge vs no merge.

**We are not hardcoding a guess.** Cosine similarity has no absolute meaning, it depends
entirely on the embedding model. On most modern models two unrelated short strings already
sit around 0.7, and real synonyms land around 0.85 to 0.92. The number has to be measured.

We want **three bands**, not one threshold:

```
high band    -> auto merge
middle band  -> ask an LLM "are these the same subject?" and let it decide
low band     -> create a new topic
```

The middle band exists because **a wrong merge is much worse than a wrong split**. A wrong
split costs some duplicate generation. A wrong merge means someone asks for Java and gets
JavaScript cards, which reads as broken. When unsure, we pay for one small LLM call and
cache the answer forever.

## Steps

### 1. Build a labeled dataset

About 50 to 60 topic pairs, roughly half should-merge and half should-not. Commit it as CSV
or JSON with columns: `topic_a`, `topic_b`, `should_merge`, `note`.

Include the hard cases, because those are what users actually type:

```
should merge:      k8s / kubernetes
                   golang / go
                   js / javascript
                   postgres / postgresql
                   ml / machine learning

should NOT merge:  java / javascript
                   react / react native
                   c / c#
                   go / rust
                   python / pytorch

judgment calls:    spring / spring boot
(explain in note)  react / nextjs
                   machine learning / deep learning
```

Also include **casual phrasings**, not just clean technical terms. Real users type things
like "how computers work" or "i want to learn about black holes". Our topic list will not be
all programming.

### 2. Compute similarities

Run a local embedding model over the pairs and compute cosine similarity for each. Start
with `fastembed` and BGE-small: local, CPU only, no API calls, so it costs nothing and you
can iterate freely.

**Normalize the text first** (lowercase, strip whitespace and punctuation) and write down
exactly what you did. We have to apply identical normalization in production.

### 3. Find the bands

Look at the two distributions (should-merge vs should-not) and find where they separate. A
histogram or even a sorted list is fine. Pick bands so that:

- almost nothing in the auto-merge band is a false merge
- the middle band covers where the two distributions overlap

**Bias conservative.** If in doubt, widen the middle band and let the LLM handle more cases.
LLM calls are cheap and cached forever; wrong merges are not.

### 4. Compare models

Try 2 or 3 embedding models, not just BGE-small, and recommend one. Note that thresholds are
specific to whichever model we pick, so changing models later means redoing this.

## Deliverables

- The labeled dataset, committed
- A script that reproduces the numbers
- A short writeup: which model, the three band values, how many pairs landed in each band,
  and any pair the model got badly wrong

That last item matters as much as the numbers. If a model confidently says Java and
JavaScript are the same thing, we need to know before it ships.

## If it does not work

If the distributions overlap so much that no clean bands exist, that is a real finding.
Say so and we will rethink the approach rather than force it.

## Related

The same technique is needed later for **card content dedup** (ADR-0007), with different
vectors and different numbers. The topic thresholds do **not** transfer. Whoever builds this
harness will find that task mostly a rerun with a different dataset.
