"use client";

/**
 * Redesigned TopicDiscoveryModal:
 * - Space-efficient integrated header with search filter and compact tabs.
 * - Rich metadata cards in the Topics tab (difficulty span, subscriber count, follow state).
 * - Rich custom topic status cards with pulsing status indicators and expandable progress panel.
 */

import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";

import {
  api,
  type CustomTopicStatus,
  type Topic,
  type TopicDiscover,
} from "@/lib/api";
import { GenerationProgressPanel } from "./GenerationProgressPanel";
import { RequestTopicBox } from "./RequestTopicBox";
import { TopicStatsModal } from "./TopicStatsModal";

interface Props {
  onFollowed: (topic: Topic) => void;
  onTopicRemoved: (topicId: string) => void;
  onClose: () => void;
  initialView?: ViewMode;
}

type ViewMode = "topics" | "custom" | "request";

const STATUS_LABEL: Record<NonNullable<CustomTopicStatus["generation_status"]>, string> = {
  pending: "Pending",
  running: "Generating",
  completed: "Ready",
  failed: "Failed",
};

export function TopicDiscoveryModal({
  onFollowed,
  onTopicRemoved,
  onClose,
  initialView = "topics",
}: Props) {
  const [view, setView] = useState<ViewMode>(initialView);
  const [items, setItems] = useState<TopicDiscover[]>([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [customTopics, setCustomTopics] = useState<CustomTopicStatus[] | null>(null);
  const [followingId, setFollowingId] = useState<string | null>(null);
  const [openTopicId, setOpenTopicId] = useState<string | null>(null);
  const openTopic = items.find((t) => t.topic_id === openTopicId) ?? null;
  const [openCustomTopicId, setOpenCustomTopicId] = useState<string | null>(null);

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
        current.map((t) =>
          t.topic_id === topicId
            ? { ...t, followed: true, subscriber_count: t.subscriber_count + 1 }
            : t,
        ),
      );
      setOpenTopicId((current) => (current === topicId ? null : current));
    } finally {
      setFollowingId(null);
    }
  };

  /** The exact inverse of `follow`. `onTopicRemoved` is the same callback the
   *  cancel-a-generation path already uses to drop a topic from the caller's
   *  local subscription state — an unfollow needs precisely that, so it is
   *  reused rather than threading a fourth callback through all three call
   *  sites (RightRail, SettingsView, ShareTopicRail).
   *
   *  Unlike `follow`, this row stays in the list afterwards: "Browse All" is
   *  the whole corpus, not the user's subscriptions, so an unfollowed topic
   *  belongs here still — just followable again. */
  const unfollow = async (topicId: string) => {
    setFollowingId(topicId);
    try {
      await api.unsubscribeTopic(topicId);
      onTopicRemoved(topicId);
      setItems((current) =>
        current.map((t) =>
          t.topic_id === topicId
            ? { ...t, followed: false, subscriber_count: Math.max(0, t.subscriber_count - 1) }
            : t,
        ),
      );
    } finally {
      setFollowingId(null);
    }
  };

  const filteredItems = useMemo(() => {
    if (!searchQuery.trim()) return items;
    const query = searchQuery.toLowerCase();
    return items.filter((item) => item.display_name.toLowerCase().includes(query));
  }, [items, searchQuery]);

  return createPortal(
    <div className="modal-overlay" onClick={onClose}>
      <div
        className="modal-panel modal-panel-wide discover-modal-redesign"
        role="dialog"
        aria-modal="true"
        aria-label="Browse topics"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Compact Integrated Header Bar */}
        <div className="discover-modal-header">
          <div className="discover-modal-header-top">
            <div className="discover-modal-title-wrap">
              <h2 className="modal-title">Explore Topics</h2>
              <span className="discover-modal-count mono">
                {view === "topics" ? `${filteredItems.length} topics` : null}
                {view === "custom" && customTopics ? `${customTopics.length} requests` : null}
              </span>
            </div>
            <button type="button" className="modal-close" aria-label="Close" onClick={onClose}>
              ×
            </button>
          </div>

          <div className="discover-modal-nav-row">
            <div className="discover-toggle discover-modal-tabs" role="group" aria-label="View">
              <button type="button" data-active={view === "topics"} onClick={() => setView("topics")}>
                Browse All
              </button>
              <button type="button" data-active={view === "custom"} onClick={() => setView("custom")}>
                Your Requests {customTopics && customTopics.length > 0 ? `(${customTopics.length})` : ""}
              </button>
              <button type="button" data-active={view === "request"} onClick={() => setView("request")}>
                + Request Topic
              </button>
            </div>

            {view === "topics" ? (
              <div className="discover-search-wrap">
                <input
                  type="text"
                  className="discover-search-input"
                  placeholder="Filter topics…"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                />
                {searchQuery ? (
                  <button
                    type="button"
                    className="discover-search-clear"
                    onClick={() => setSearchQuery("")}
                    aria-label="Clear search"
                  >
                    ×
                  </button>
                ) : null}
              </div>
            ) : null}
          </div>
        </div>

        {/* Content Body */}
        <div className="discovery-modal-body">
          {view === "topics" ? (
            filteredItems.length === 0 ? (
              <div className="discover-empty-state mono">
                {searchQuery ? `No topics matching "${searchQuery}"` : "No topics in the corpus yet"}
              </div>
            ) : (
              <div className="discover-grid-list">
                {filteredItems.map((item) => (
                  <div
                    key={item.topic_id}
                    className="discover-card-item"
                    data-followed={item.followed}
                    onClick={() => setOpenTopicId(item.topic_id)}
                    role="button"
                    tabIndex={0}
                  >
                    <div className="discover-card-main">
                      <div className="discover-card-header">
                        <span className="discover-card-name">{item.display_name}</span>
                        {item.followed ? (
                          <span className="discover-card-status-badge mono">Subscribed</span>
                        ) : null}
                      </div>

                      <div className="discover-card-meta-row">
                        <span className="discover-card-badge mono">
                          {item.subscriber_count} {item.subscriber_count === 1 ? "learner" : "learners"}
                        </span>
                        <span className="discover-card-tier-tag mono">Beginner → Advanced</span>
                      </div>
                    </div>

                    <div className="discover-card-actions">
                      {/* A followed topic's button is the way OUT of it, not a
                          disabled "Following" label — the state was previously
                          a dead end here, so the only unfollow in the product
                          was the one behind the topic-progress rail. */}
                      <button
                        type="button"
                        className="discover-follow-btn mono"
                        data-followed={item.followed}
                        disabled={followingId === item.topic_id}
                        onClick={(e) => {
                          e.stopPropagation();
                          void (item.followed ? unfollow : follow)(item.topic_id);
                        }}
                      >
                        {followingId === item.topic_id
                          ? "…"
                          : item.followed
                            ? "Unfollow"
                            : "Follow"}
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )
          ) : view === "custom" ? (
            <div className="discover-grid-list">
              {customTopics === null ? (
                <p className="modal-loading mono">Loading your requests…</p>
              ) : customTopics.length === 0 ? (
                <div className="discover-empty-state mono">
                  <p>You haven't requested any custom topics yet</p>
                  <button
                    type="button"
                    className="discover-empty-action-btn"
                    onClick={() => setView("request")}
                  >
                    Request your first topic
                  </button>
                </div>
              ) : (
                customTopics.map((topic) => {
                  const clickable = topic.generation_status !== null;
                  const expanded = openCustomTopicId === topic.topic_id;
                  const status = topic.generation_status ?? "completed";

                  return (
                    <div key={topic.topic_id} className="custom-topic-card" data-expanded={expanded}>
                      <div
                        className="custom-topic-card-header"
                        data-clickable={clickable}
                        role={clickable ? "button" : undefined}
                        tabIndex={clickable ? 0 : undefined}
                        onClick={
                          clickable
                            ? () =>
                                setOpenCustomTopicId((current) =>
                                  current === topic.topic_id ? null : topic.topic_id,
                                )
                            : undefined
                        }
                      >
                        <div className="custom-topic-header-text">
                          <div className="custom-topic-title-row">
                            <span className="custom-topic-name">{topic.display_name}</span>
                            <div className="custom-topic-status-pill mono" data-status={status}>
                              <span className="custom-topic-status-dot" data-status={status} />
                              {STATUS_LABEL[status] ?? "Ready"}
                            </div>
                          </div>
                          <div className="custom-topic-meta-row mono">
                            <span>Requested {new Date(topic.requested_at).toLocaleDateString()}</span>
                            {clickable ? (
                              <span className="custom-topic-view-toggle">
                                {expanded ? "Hide details ▲" : "View progress ▼"}
                              </span>
                            ) : null}
                          </div>
                        </div>
                      </div>

                      {expanded ? (
                        <div className="custom-topic-expanded-panel">
                          <GenerationProgressPanel
                            topicId={topic.topic_id}
                            topicDisplayName={topic.display_name}
                            onDismiss={() => setOpenCustomTopicId(null)}
                            onCancelled={() => {
                              setOpenCustomTopicId(null);
                              setCustomTopics((current) =>
                                (current ?? []).filter((t) => t.topic_id !== topic.topic_id),
                              );
                              onTopicRemoved(topic.topic_id);
                            }}
                          />
                        </div>
                      ) : null}
                    </div>
                  );
                })
              )}
            </div>
          ) : (
            <div className="discover-request-pane">
              <RequestTopicBox onFollowed={onFollowed} onTopicRemoved={onTopicRemoved} />
            </div>
          )}
        </div>
      </div>

      {/* Exactly one of the two is passed, so the modal shows the action that
          actually applies rather than an inert "Following" pill next to it. */}
      {openTopic !== null ? (
        <TopicStatsModal
          topicId={openTopic.topic_id}
          topicName={openTopic.display_name}
          onClose={() => setOpenTopicId(null)}
          onFollow={openTopic.followed ? undefined : () => follow(openTopic.topic_id)}
          onUnfollow={openTopic.followed ? () => unfollow(openTopic.topic_id) : undefined}
          following={followingId === openTopic.topic_id}
        />
      ) : null}
    </div>,
    document.body,
  );
}
