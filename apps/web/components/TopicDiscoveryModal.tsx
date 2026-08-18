"use client";

/**
 * ADR-0036, restructured by ADR-0038.
 *
 * The "Discover" tab (Popular/For You, top 5 unfollowed) is gone from here —
 * that's what the always-visible inline `DiscoverBox` in the right rail
 * covers now (ADR-0038 restored it), so keeping a second copy of the exact
 * same top-5 list inside this modal was pure duplication.
 *
 * What replaces it: a **Topics** tab that is the actual "browse everything"
 * surface — every topic in the corpus, via `GET /topics/all`, not a
 * 5-row-capped slice. Tab order is Topics -> Your custom topics -> Request a
 * topic, and every tab renders inside the same fixed-height, internally
 * scrolling body (`.discovery-modal-body`) so switching tabs never resizes
 * the modal panel itself — it used to grow/shrink per tab (a bare few-line
 * form vs. a long topic list), which reads as the modal "jumping."
 *
 * Reuses the .modal-overlay/.modal-panel-wide chrome ADR-0018's block-expand
 * modal established, and TopicStatsModal for the per-row detail view.
 */

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";

import {
  api,
  type CustomTopicStatus,
  type Topic,
  type TopicDiscover,
} from "@/lib/api";
import { RequestTopicBox } from "./RequestTopicBox";
import { TopicStatsModal } from "./TopicStatsModal";

interface Props {
  onFollowed: (topic: Topic) => void;
  onClose: () => void;
  /** Which tab opens first — lets the two rail entry points (below the topic
   *  filters vs. below "Your topics") land on the view that made sense for
   *  where the reader clicked from, without needing two separate modals. */
  initialView?: ViewMode;
}

type ViewMode = "topics" | "custom" | "request";

const STATUS_LABEL: Record<NonNullable<CustomTopicStatus["generation_status"]>, string> = {
  pending: "Pending",
  running: "Generating",
  completed: "Ready",
  failed: "Failed",
};

export function TopicDiscoveryModal({ onFollowed, onClose, initialView = "topics" }: Props) {
  const [view, setView] = useState<ViewMode>(initialView);
  const [items, setItems] = useState<TopicDiscover[]>([]);
  const [customTopics, setCustomTopics] = useState<CustomTopicStatus[] | null>(null);
  const [followingId, setFollowingId] = useState<string | null>(null);
  const [openTopicId, setOpenTopicId] = useState<string | null>(null);
  const openTopic = items.find((t) => t.topic_id === openTopicId) ?? null;

  useEffect(() => {
    if (view !== "topics") return;
    void api.allTopics().then(setItems);
  }, [view]);

  useEffect(() => {
    if (view !== "custom") return;
    void api.customTopics().then(setCustomTopics);
  }, [view]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  useEffect(() => {
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previous;
    };
  }, []);

  const follow = async (topicId: string) => {
    setFollowingId(topicId);
    try {
      const topic = await api.subscribeTopic(topicId);
      onFollowed(topic);
      setItems((current) =>
        current.map((t) => (t.topic_id === topicId ? { ...t, followed: true } : t)),
      );
      setOpenTopicId((current) => (current === topicId ? null : current));
    } finally {
      setFollowingId(null);
    }
  };

  return createPortal(
    <div className="modal-overlay" onClick={onClose}>
      <div
        className="modal-panel modal-panel-wide"
        role="dialog"
        aria-modal="true"
        aria-label="Browse topics"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-head">
          <h2 className="modal-title">Topics</h2>
          <button type="button" className="modal-close" aria-label="Close" onClick={onClose}>
            ×
          </button>
        </div>

        <div className="discover-toggle discover-modal-view-toggle" role="group" aria-label="View">
          <button type="button" data-active={view === "topics"} onClick={() => setView("topics")}>
            Topics
          </button>
          <button type="button" data-active={view === "custom"} onClick={() => setView("custom")}>
            Your custom topics
          </button>
          <button type="button" data-active={view === "request"} onClick={() => setView("request")}>
            Request a topic
          </button>
        </div>

        {/* Fixed height across every tab (ADR-0038) -- switching tabs used to
            resize the whole modal panel because each view's content was a
            different natural height (a five-field form vs. a long list). */}
        <div className="discovery-modal-body">
          {view === "topics" ? (
            items.length === 0 ? (
              <p className="discover-empty mono">No topics in the corpus yet</p>
            ) : (
              <div className="discover-box-list discover-modal-list">
                {items.map((item) => (
                  <div key={item.topic_id} className="discover-row">
                    <div
                      className="discover-row-text"
                      onClick={() => setOpenTopicId(item.topic_id)}
                      role="button"
                      tabIndex={0}
                    >
                      <span className="discover-row-name">{item.display_name}</span>
                      <span className="discover-row-meta mono">{item.subscriber_count} followers</span>
                    </div>
                    <button
                      type="button"
                      className="discover-follow"
                      disabled={item.followed || followingId === item.topic_id}
                      onClick={(e) => {
                        e.stopPropagation();
                        void follow(item.topic_id);
                      }}
                    >
                      {item.followed ? "Following" : "Follow"}
                    </button>
                  </div>
                ))}
              </div>
            )
          ) : view === "custom" ? (
            <div className="discover-box-list discover-modal-list">
              {customTopics === null ? (
                <p className="modal-loading mono">Loading…</p>
              ) : customTopics.length === 0 ? (
                <p className="discover-empty mono">You haven't requested any custom topics yet</p>
              ) : (
                customTopics.map((topic) => (
                  <div key={topic.topic_id} className="discover-row custom-topic-row">
                    <div className="discover-row-text">
                      <span className="discover-row-name">{topic.display_name}</span>
                      <span className="discover-row-meta mono">
                        Requested {new Date(topic.requested_at).toLocaleDateString()}
                      </span>
                    </div>
                    <span
                      className="custom-topic-status mono"
                      data-status={topic.generation_status ?? "ready"}
                    >
                      {topic.generation_status ? STATUS_LABEL[topic.generation_status] : "Ready"}
                    </span>
                  </div>
                ))
              )}
            </div>
          ) : (
            <RequestTopicBox onFollowed={onFollowed} />
          )}
        </div>
      </div>

      {openTopic !== null ? (
        <TopicStatsModal
          topicId={openTopic.topic_id}
          topicName={openTopic.display_name}
          onClose={() => setOpenTopicId(null)}
          onFollow={() => follow(openTopic.topic_id)}
          following={followingId === openTopic.topic_id}
        />
      ) : null}
    </div>,
    document.body,
  );
}
