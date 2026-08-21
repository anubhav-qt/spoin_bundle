"use client";

/**
 * Right rail for the Share Space (/share/[cardId]).
 *
 * Instead of showing "Your topics", this rail highlights the specific Topic
 * that the shared card belongs to: topic name, difficulty tier, subtopic
 * breakdown, and a Follow action.
 */

import { useEffect, useState } from "react";

import { api, type Difficulty, type Topic, type TopicCurriculum, type TopicStats } from "@/lib/api";
import { DiscoverBox } from "./DiscoverBox";
import { FocusToggle } from "./FocusToggle";
import { FontPicker } from "./FontPicker";
import { ThemePicker } from "./ThemePicker";
import { TopicDiscoveryModal } from "./TopicDiscoveryModal";
import { TopicStatsModal } from "./TopicStatsModal";

const DIFFICULTY_LABEL: Record<Difficulty, string> = {
  beginner: "Beginner",
  intermediate: "Intermediate",
  advanced: "Advanced",
};

interface Props {
  topicId: string;
  topicName: string;
  accentHue?: number | null;
  onEnterFocus: () => void;
  onFollowed: (topic: Topic) => void;
  following: boolean;
}

export function ShareTopicRail({
  topicId,
  topicName,
  accentHue,
  onEnterFocus,
  onFollowed,
  following,
}: Props) {
  const [stats, setStats] = useState<TopicStats | null>(null);
  const [curriculum, setCurriculum] = useState<TopicCurriculum | null>(null);
  const [statsModalOpen, setStatsModalOpen] = useState(false);
  const [discoveryOpen, setDiscoveryOpen] = useState(false);
  const [subscribing, setSubscribing] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const [s, c] = await Promise.all([
          api.topicStats(topicId),
          api.topicCurriculum(topicId),
        ]);
        if (!cancelled) {
          setStats(s);
          setCurriculum(c);
        }
      } catch (err) {
        console.error("Failed to load topic details:", err);
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [topicId]);

  const handleFollow = async () => {
    if (subscribing || following) return;
    setSubscribing(true);
    try {
      const topic = await api.subscribeTopic(topicId);
      onFollowed(topic);
    } catch (err) {
      console.error("Failed to subscribe topic:", err);
    } finally {
      setSubscribing(false);
    }
  };

  return (
    <aside className="rail-right" aria-label="Topic details and insights">
      <div className="rail-top-row">
        <ThemePicker />
        <FocusToggle focused={false} onToggle={onEnterFocus} />
      </div>

      <FontPicker />

      <button
        type="button"
        className="discover-follow view-all-topics"
        onClick={() => setDiscoveryOpen(true)}
      >
        View all topics
      </button>

      {/* Dedicated Topic Details Panel (replaces Your Topics) */}
      <div className="share-topic-panel">
        <div className="share-topic-head">
          <span className="share-topic-badge">Topic</span>
          <h3 className="share-topic-title">{topicName}</h3>
        </div>

        {stats ? (
          <div className="share-topic-meta">
            <div className="share-topic-meta-row">
              <span className="share-topic-meta-label">Entry tier</span>
              <span className="share-topic-meta-value">
                {DIFFICULTY_LABEL[stats.current_difficulty]}
              </span>
            </div>
            {curriculum ? (
              <div className="share-topic-meta-row">
                <span className="share-topic-meta-label">Curriculum</span>
                <span className="share-topic-meta-value">
                  {curriculum.subtopics.length} subtopics
                </span>
              </div>
            ) : null}
          </div>
        ) : null}

        <div className="share-topic-actions-row">
          {following ? (
            <button
              type="button"
              className="share-topic-btn share-topic-btn-following"
              disabled
            >
              Following
            </button>
          ) : (
            <button
              type="button"
              className="share-topic-btn share-topic-btn-follow"
              onClick={() => void handleFollow()}
              disabled={subscribing}
            >
              {subscribing ? "Following…" : "Follow"}
            </button>
          )}

          <button
            type="button"
            className="share-topic-btn share-topic-btn-curriculum"
            onClick={() => setStatsModalOpen(true)}
          >
            View curriculum
          </button>
        </div>
      </div>

      <DiscoverBox onFollowed={onFollowed} />

      {statsModalOpen ? (
        <TopicStatsModal
          topicId={topicId}
          topicName={topicName}
          onClose={() => setStatsModalOpen(false)}
          onFollow={handleFollow}
          following={following}
          accentHue={accentHue}
        />
      ) : null}

      {discoveryOpen ? (
        <TopicDiscoveryModal
          onFollowed={onFollowed}
          onClose={() => setDiscoveryOpen(false)}
          initialView="topics"
        />
      ) : null}
    </aside>
  );
}
