# `corpus/` — the curated source of truth

Authored by Antigravity under the owner's supervision, following
[`../procedure.md`](../procedure.md). Ingested into `the_spoin_universe` (ADR-0088)
and retrieved at generation time to ground both the card writer and the verifier
(ADR-0089).

Laid out by the hierarchy:

```
<category>/<sub_category>/<survey-or-topic>/<document>.md
```

The `sub_category` level is omitted entirely when a subject has none. The directory
is organisational convenience for humans — **the front matter is authoritative**, and
the ingester reads the fields, not the path. Keep them consistent anyway; a mismatch
is a review signal that something is misfiled.

## Active Corpus Content (67 Documents across 8 Suites)

### Spoin Canon (`_canon/`, 5 docs)
Product mechanics and authoring invariants (kind: `spoin_canon`):
- `ascii-box-rule-and-gag-scenes.md`: ASCII box invariant (width ≤ 40), gags only, and discard-for-regeneration failure policy.
- `card-anatomy-and-fields.md`: Card schema, field provenance, and system invariants.
- `card-archetypes-and-content-shapes.md`: Archetypes derived post-generation; Mermaid client rendering.
- `curriculum-progression-and-quizzes.md`: Topic budgeting, latched 80% progression, quiz generation from cards.
- `dual-titles-and-hook-discipline.md`: Display title vs. canonical title; silliness in hook layer, truth in body.

### Backend Engineering (`computer-science/software-engineering/backend-engineering/`, 9 docs)
Survey suite (kind: `topic_source`, scope: `survey`):
- `transport-and-application-protocols.md`
- `api-paradigms-and-contracts.md`
- `data-persistence-and-transactions.md`
- `caching-and-state-management.md`
- `asynchronous-messaging-and-event-streams.md`
- `server-concurrency-and-io-runtimes.md`
- `security-authentication-and-boundary-defense.md`
- `fault-tolerance-and-observability.md`
- `tips-and-tricks.md`

### Frontend Engineering (`computer-science/software-engineering/frontend-engineering/`, 9 docs)
Survey suite (kind: `topic_source`, scope: `survey`):
- `critical-rendering-path-and-dom.md`
- `css-layout-modern-engines-and-compositing.md`
- `v8-javascript-runtime-and-the-event-loop.md`
- `reactivity-signals-and-state-management.md`
- `modern-rendering-architectures-and-rsc.md`
- `core-web-vitals-and-runtime-performance.md`
- `web-accessibility-wcag-and-assistive-tech.md`
- `client-side-security-sop-cors-and-threats.md`
- `tips-and-tricks.md`

### Fullstack Engineering (`computer-science/software-engineering/fullstack-engineering/`, 8 docs)
Survey suite (kind: `topic_source`, scope: `survey`):
- `end-to-end-type-safety-and-api-contracts.md`
- `authentication-authorization-and-session-lifecycles.md`
- `client-server-state-synchronization-and-optimistic-ui.md`
- `bff-patterns-api-gateways-and-caching-tiers.md`
- `unified-fullstack-frameworks-and-execution-boundaries.md`
- `distributed-tracing-and-fullstack-observability.md`
- `database-schema-evolution-and-zero-downtime-deployments.md`
- `tips-and-tricks.md`

### World Mythology (`mythology/world-mythology/`, 9 docs)
Survey suite (kind: `topic_source`, scope: `survey`):
- `comparative-mythology-and-universal-archetypes.md`
- `mesopotamian-and-ancient-near-eastern-traditions.md`
- `egyptian-cosmology-and-the-osirian-cycle.md`
- `greco-roman-pantheon-and-mythic-succession.md`
- `norse-cosmology-and-eschatology.md`
- `vedic-and-hindu-cosmological-traditions.md`
- `east-asian-mythologies-chinese-and-japanese-shinto.md`
- `mesoamerican-and-indigenous-american-traditions.md`
- `tips-and-tricks.md`

### Astronomy (`astronomy/physics/astronomy/`, 9 docs)
Survey suite (kind: `topic_source`, scope: `survey`):
- `celestial-mechanics-and-orbital-dynamics.md`
- `the-solar-system-and-planetary-science.md`
- `electromagnetic-radiation-spectroscopy-and-instrumentation.md`
- `stellar-structure-and-stellar-nucleosynthesis.md`
- `stellar-evolution-remnants-and-the-hr-diagram.md`
- `galactic-astronomy-and-the-interstellar-medium.md`
- `extragalactic-astronomy-and-cosmic-large-scale-structure.md`
- `observational-cosmology-and-the-cosmic-distance-ladder.md`
- `tips-and-tricks.md`

### World Philosophy (`philosophy/world-philosophy/`, 9 docs)
Survey suite (kind: `topic_source`, scope: `survey`):
- `foundations-branches-and-philosophical-methods.md`
- `classical-greek-philosophy-socrates-plato-aristotle.md`
- `hellenistic-and-late-antique-schools-stoicism-epicureanism-skepticism.md`
- `classical-eastern-philosophical-traditions.md`
- `medieval-scholastic-and-islamic-golden-age-philosophy.md`
- `early-modern-epistemology-rationalism-vs-empiricism.md`
- `enlightenment-german-idealism-and-19th-century-critique.md`
- `twentieth-century-and-contemporary-paradigms-analytic-and-continental.md`
- `tips-and-tricks.md`

### Human Biology (`science/biology/human-biology/`, 9 docs)
Survey suite (kind: `topic_source`, scope: `survey`):
- `cellular-physiology-and-metabolic-bioenergetics.md`
- `human-genetics-molecular-biology-and-epigenetics.md`
- `neurobiology-and-the-human-brain.md`
- `cardiovascular-physiology-and-hemodynamics.md`
- `respiratory-physiology-and-gas-exchange.md`
- `immunology-and-lymphatic-defense-systems.md`
- `endocrine-regulation-and-metabolic-homeostasis.md`
- `digestive-and-renal-excretory-systems.md`
- `tips-and-tricks.md`
