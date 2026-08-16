"use client";

/**
 * Replaces the "Explore" nav stub (ADR-0015). Top 5 topics the user doesn't
 * follow yet, ranked by subscriber_count, with a Popularity/For You toggle.
 * Both modes run the same query server-side today — see ADR-0015 and task
 * 0003 — hence the "personalizing soon" note under the header in For You.
 *
 * Rows are selectable (opens TopicStatsModal for a brief overview of a topic
 * the user hasn't followed yet — `/topics/{id}/stats` works fine with no
 * progress row, defaulting to an honest 0%/beginner). The row's own Follow
 * button still works as a quick-follow without opening the modal
 * (`stopPropagation`); the modal also offers Follow, for whichever path the
 * user takes to get there.
 */

import { useEffect, useState } from "react";

import { api, type DiscoverMode, type Topic, type TopicDiscover } from "@/lib/api";
import { TopicStatsModal } from "./TopicStatsModal";

interface Props {
  onFollowed: (topic: Topic) => void;
}

export function DiscoverBox({ onFollowed }: Props) {
  const [mode, setMode] = useState<DiscoverMode>("popular");
  const [items, setItems] = useState<TopicDiscover[]>([]);
  const [followingId, setFollowingId] = useState<string | null>(null);
  const [openTopicId, setOpenTopicId] = useState<string | null>(null);
  const openTopic = items.find((t) => t.topic_id === openTopicId) ?? null;

  const load = () => {
    void api.discoverTopics(mode).then(setItems);
  };

  useEffect(load, [mode]);

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

  return (
    <div className="discover-box">
      <div className="discover-head">
        <h3 className="discover-title mono">Discover</h3>
        <div className="discover-toggle" role="group" aria-label="Discover ranking">
          <button
            type="button"
            data-active={mode === "popular"}
            onClick={() => setMode("popular")}
          >
            Popular
          </button>
          <button
            type="button"
            data-active={mode === "for_you"}
            onClick={() => setMode("for_you")}
          >
            For You
          </button>
        </div>
      </div>

      {mode === "for_you" ? <p className="discover-note mono">Personalizing soon</p> : null}

      <div className="discover-box-list">
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

      {openTopic !== null ? (
        <TopicStatsModal
          topicId={openTopic.topic_id}
          topicName={openTopic.display_name}
          onClose={() => setOpenTopicId(null)}
          onFollow={() => follow(openTopic.topic_id)}
          following={followingId === openTopic.topic_id}
        />
      ) : null}
    </div>
  );
}
