# ADR-0038: Restore the inline Discover box below "Your topics"

- **Status:** Accepted (extended same-day, see the update below)
- **Date:** 2026-08-18
- **Deciders:** Anubhav

> **2026-08-18 update:** Once the inline box was back, `TopicDiscoveryModal` keeping its
> own Discover tab turned out to be exactly the duplication the "Alternatives considered"
> section below argued against keeping the other way around -- same Popular/For You data,
> same top-5 list, rendered twice. That tab is now gone; see "Modal restructuring, same
> day" below for what replaced it. The reasoning below this point is left as originally
> written for the record of why the inline box came back at all.

## Context

ADR-0036 deleted `DiscoverBox.tsx` (the always-visible, top-5, Popular/For You inline
list) and folded its rendering logic into `TopicDiscoveryModal`, reachable only via a
"View all topics" / "Discover" button. The stated reason was rail density and giving
Discover room to scroll past 5 rows.

In practice, the always-visible box was the more useful surface for this product: a
user checks "Your topics" and wants to glance at what else exists in the same look and
motion, without an extra click into a full-screen modal. The modal is still strictly
better for the two things it added -- browsing past 5 rows, and the custom-topics status
tab -- but neither of those should have cost the inline box its spot in the rail.

## Decision

**Restore `DiscoverBox.tsx` as an always-visible box directly below `TopicsProgressBox`
("Your topics")** in `RightRail.tsx`, structurally mirroring it exactly as it did before
ADR-0036 (same header/toggle/list shape, same `.discover-box` CSS, which was never
removed from `globals.css`).

**`TopicDiscoveryModal` is kept, not deleted.** "View all topics" (below the topic
filter chips) still opens it, defaulting to its "Request a topic" tab -- the fast-path
form still deserves a rail-level entry point, and the modal's Discover tab and
custom-topics status tab remain the only way to browse past 5 topics or check a
self-requested topic's generation status. The redundant second rail button that opened
the same modal straight to its Discover tab is removed -- the inline box now serves that
job directly, with no click required.

## Consequences

**Easier**
- The always-visible glance-then-follow flow ADR-0036 removed is back with no click.
- No duplicate "Discover" affordance in the rail (button + box would have shown the same
  top-5 list twice, once collapsed behind a click and once inline).

**Harder**
- The rail regains a fifth permanent box, the exact rail-density cost ADR-0036 traded
  away. Accepted -- that tradeoff is reversed deliberately here, not accidentally.
- Two Discover data-fetches exist in the codebase again (`DiscoverBox` and
  `TopicDiscoveryModal`'s Discover mode both call `api.discoverTopics`), same
  short-lived duplication ADR-0036 had already accepted for `RequestTopicBox`
  vs. the modal's request tab.

## Alternatives considered

**Delete `TopicDiscoveryModal`'s Discover mode entirely, since the inline box covers
it.** Rejected: the modal's Discover mode is still the only way to see past the top 5,
which was ADR-0036's original, still-valid problem. Removing it would silently
reintroduce the 5-row cap as a hard ceiling instead of a first-glance default.

**Keep the button-only entry point and skip restoring the inline box, per ADR-0036's
reasoning.** Rejected directly by the product decision this ADR records: the inline box
is the preferred surface, not a nice-to-have.

## Revisit when

If the rail's vertical footprint becomes a real problem again (e.g. on shorter viewports
where five stacked boxes push "Your topics" below the fold), reconsider collapsing
Discover behind a click -- but keep the inline box as the default this time.

## Modal restructuring, same day

With the inline box carrying the "what's new, at a glance" job, `TopicDiscoveryModal`'s
own Discover tab (Popular/For You, top 5) was left showing the identical list a click
away from itself for no reason. Three changes, made together:

**The Discover tab is deleted, replaced by a "Topics" tab that is the actual
browse-everything surface** -- `GET /topics/all` (new; `api/routers/topics.py`), every
topic in the corpus ordered by `subscriber_count`, not the 5-row-capped
`/topics/discover` slice. This is also what "the modal's Discover mode is still the only
way to see past the top 5" in the original Alternatives section was gesturing at without
quite building it -- a real "see everything" tab, not just a bigger version of the top-5
list. Each row's Follow button disables and reads "Following" when `TopicDiscoverOut.
followed` is true (a new field, default `false`, set per-topic only by `/topics/all`) --
cheaper than filtering already-followed topics out of a "browse everything" view, and
more honest: a reader browsing everything should still see what they already follow.

**Tab order becomes Topics -> Your custom topics -> Request a topic.** The fast-typing
path stays reachable from here but moves last -- browsing the full corpus is now the
primary reason to open this modal at all (the inline box already covers the quick top-5
glance, and the rail's own "View all topics" button now opens straight to this tab
instead of Request, unlike the original ADR-0036 default).

**The modal body is a fixed height across all three tabs**, not sized to each tab's own
content. `Request a topic` is a five-field form; `Topics` can be dozens of rows -- letting
the panel's height track whichever tab is active made switching tabs visibly resize the
whole modal, which read as the modal jumping around rather than a tab change. A single
`.discovery-modal-body` (`height: 50vh; overflow-y: auto;`) now wraps every tab's content,
so the modal panel itself never resizes; only the pane inside it scrolls when a tab's
content is taller than 50vh (Topics, once the corpus has more than a screenful).

### Alternatives considered (this update)

**Keep the Discover tab and just add a separate "Topics" tab alongside it.** Rejected:
that's the same duplication one level down -- Popular/For You and "browse everything"
would both be lists of topics ranked by subscriber count, differing only in a 5-row cap.
One tab that shows everything (with Follow already disabled on followed rows) subsumes
what Discover did without a second, narrower list sitting next to it.

**Let each tab size to its own content, and accept the modal resizing on tab-switch.**
Rejected as the status quo bug this update fixes, not a real alternative -- it's what
prompted the fixed-height change in the first place.
