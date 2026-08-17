"use client";

/**
 * ADR-0036. Replaces the old inline `DiscoverBox` list — same Popular/For You
 * data and per-row Follow/detail behavior, just with room to browse more than
 * 5 rows, plus a second mode surfacing this user's own custom-topic
 * generation status (GenerationJob.status via GET /topics/custom), which
 * nothing in the UI exposed before.
 *
 * Reuses the .modal-overlay/.modal-panel-wide chrome ADR-0018's block-expand
 * modal established, and TopicStatsModal for the per-row detail view — same
 * pattern DiscoverBox already used.
 */

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";

import {
  api,
  type CustomTopicStatus,
  type DiscoverMode,
  type Topic,
  type TopicDiscover,
} from "@/lib/api";
import { TopicStatsModal } from "./TopicStatsModal";

interface Props {
  onFollowed: (topic: Topic) => void;
  onClose: () => void;
}

type ViewMode = "discover" | "custom";

const STATUS_LABEL: Record<NonNullable<CustomTopicStatus["generation_status"]>, string> = {
  pending: "Pending",
  running: "Generating",
  completed: "Ready",
  failed: "Failed",
};

export function TopicDiscoveryModal({ onFollowed, onClose }: Props) {
  const [view, setView] = useState<ViewMode>("discover");
  const [mode, setMode] = useState<DiscoverMode>("popular");
  const [items, setItems] = useState<TopicDiscover[]>([]);
  const [customTopics, setCustomTopics] = useState<CustomTopicStatus[] | null>(null);
  const [followingId, setFollowingId] = useState<string | null>(null);
  const [openTopicId, setOpenTopicId] = useState<string | null>(null);
  const openTopic = items.find((t) => t.topic_id === openTopicId) ?? null;

  useEffect(() => {
    if (view !== "discover") return;
    void api.discoverTopics(mode).then(setItems);
  }, [view, mode]);

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
      setItems((current) => current.filter((t) => t.topic_id !== topicId));
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
          <button type="button" data-active={view === "discover"} onClick={() => setView("discover")}>
            Discover
          </button>
          <button type="button" data-active={view === "custom"} onClick={() => setView("custom")}>
            Your custom topics
          </button>
        </div>

        {view === "discover" ? (
          <>
            <div className="discover-toggle" role="group" aria-label="Discover ranking">
              <button type="button" data-active={mode === "popular"} onClick={() => setMode("popular")}>
                Popular
              </button>
              <button type="button" data-active={mode === "for_you"} onClick={() => setMode("for_you")}>
                For You
              </button>
            </div>

            {mode === "for_you" ? <p className="discover-note mono">Personalizing soon</p> : null}

            <div className="discover-box-list discover-modal-list">
              {items.length === 0 ? (
                <p className="discover-empty mono">Nothing new to discover right now</p>
              ) : (
                items.map((item) => (
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
                      disabled={followingId === item.topic_id}
                      onClick={(e) => {
                        e.stopPropagation();
                        void follow(item.topic_id);
                      }}
                    >
                      Follow
                    </button>
                  </div>
                ))
              )}
            </div>
          </>
        ) : (
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
        )}
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
