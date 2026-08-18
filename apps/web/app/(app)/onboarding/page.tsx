"use client";

/**
 * First-run setup: gated by AuthProvider (docs/adr on auth) until
 * `user.onboarding_complete`. Each chosen topic gets its own starting
 * difficulty (was one global difficulty for every topic) and, for a
 * signed-up user, a free-text field to request a topic outside the preset
 * list -- gated off for guests, since a guest account is ephemeral and the
 * request goes through the same slot-spending/generation pipeline as the
 * right rail's "Request a topic" (see topics.py's `request_topic`).
 */

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ApiError, api, type Difficulty, type TopicDiscover } from "@/lib/api";
import { useAuth } from "@/components/AuthProvider";

const DIFFICULTIES: { value: Difficulty; label: string }[] = [
  { value: "beginner", label: "Beginner" },
  { value: "intermediate", label: "Intermediate" },
  { value: "advanced", label: "Advanced" },
];

const CUSTOM_TOPIC_MAX_WORDS = 5;

export default function OnboardingPage() {
  const [topics, setTopics] = useState<TopicDiscover[] | null>(null);
  const [selected, setSelected] = useState<Record<string, Difficulty>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const [customName, setCustomName] = useState("");
  const [customDifficulty, setCustomDifficulty] = useState<Difficulty>("beginner");
  const [customSubmitting, setCustomSubmitting] = useState(false);
  const [customError, setCustomError] = useState("");
  const [customAdded, setCustomAdded] = useState<{ id: string; name: string }[]>([]);

  const router = useRouter();
  const { user, refresh } = useAuth();
  // A signed-in-but-not-onboarded account (signed up, closed the app, came
  // back later) is not a guest -- `is_guest` alone is the right gate here.
  const canRequestCustomTopic = user !== null && !user.is_guest;

  useEffect(() => {
    api
      .discoverTopics("popular")
      .then(setTopics)
      .catch(() => setTopics([]));
  }, []);

  const toggle = (id: string) => {
    setSelected((prev) => {
      if (id in prev) {
        const next = { ...prev };
        delete next[id];
        return next;
      }
      return { ...prev, [id]: "beginner" };
    });
  };

  const setTopicDifficulty = (id: string, difficulty: Difficulty) => {
    setSelected((prev) => (id in prev ? { ...prev, [id]: difficulty } : prev));
  };

  const customWordCount = customName.trim().split(/\s+/).filter(Boolean).length;

  const submitCustomTopic = async () => {
    const trimmed = customName.trim();
    if (!trimmed || customSubmitting) return;
    if (customWordCount > CUSTOM_TOPIC_MAX_WORDS) {
      setCustomError(`Keep it short -- ${CUSTOM_TOPIC_MAX_WORDS} words or fewer`);
      return;
    }

    setCustomSubmitting(true);
    setCustomError("");
    try {
      const result = await api.requestTopic(trimmed, customDifficulty);
      setCustomAdded((prev) => [...prev, { id: result.topic.id, name: result.topic.display_name }]);
      setCustomName("");
    } catch (cause) {
      setCustomError(cause instanceof ApiError ? cause.message : "Something went wrong");
    } finally {
      setCustomSubmitting(false);
    }
  };

  const handleSubmit = async () => {
    const chosen = Object.entries(selected);
    if (chosen.length === 0 && customAdded.length === 0) {
      setError("Pick at least one topic to get started.");
      return;
    }
    setError("");
    setLoading(true);
    try {
      if (chosen.length > 0) {
        await api.completeOnboarding(
          chosen.map(([topic_id, entry_difficulty]) => ({ topic_id, entry_difficulty })),
        );
      } else {
        // Nothing from the preset list -- a custom topic alone already
        // subscribed the user, so this call just flips the onboarding gate.
        await api.completeOnboarding([]);
      }
      await refresh();
      router.push("/");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="auth-layout">
      <div className="auth-panel onboarding-panel">
        <div className="auth-header">
          <h1 className="auth-title">Pick a few topics.</h1>
          <p className="auth-subtitle">You can follow more later — this just gets your feed started.</p>
        </div>

        <div className="onboarding-topics">
          {topics === null && <p className="auth-subtitle">Loading topics...</p>}
          {topics?.length === 0 && <p className="auth-subtitle">No topics available yet.</p>}
          {topics?.map((topic) => (
            <button
              key={topic.topic_id}
              type="button"
              className={`onboarding-topic-chip${topic.topic_id in selected ? " selected" : ""}`}
              onClick={() => toggle(topic.topic_id)}
              disabled={loading}
            >
              {topic.display_name}
            </button>
          ))}
        </div>

        {Object.keys(selected).length > 0 ? (
          <div className="onboarding-selected-list">
            {Object.entries(selected).map(([topicId, difficulty]) => {
              const topic = topics?.find((t) => t.topic_id === topicId);
              return (
                <div key={topicId} className="onboarding-selected-row">
                  <span className="onboarding-selected-name">{topic?.display_name ?? "Topic"}</span>
                  <div className="onboarding-difficulty-row onboarding-difficulty-row-compact">
                    {DIFFICULTIES.map((d) => (
                      <button
                        key={d.value}
                        type="button"
                        className={`onboarding-topic-chip${difficulty === d.value ? " selected" : ""}`}
                        onClick={() => setTopicDifficulty(topicId, d.value)}
                        disabled={loading}
                      >
                        {d.label}
                      </button>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        ) : null}

        {canRequestCustomTopic ? (
          <div className="onboarding-custom-topic">
            <p className="auth-label">Don't see it? Add your own.</p>
            <div className="onboarding-custom-topic-row">
              <input
                type="text"
                className="request-topic-input"
                placeholder="e.g. Quantum computing"
                value={customName}
                maxLength={120}
                onChange={(e) => {
                  setCustomName(e.target.value);
                  setCustomError("");
                }}
                disabled={customSubmitting}
              />
              <button
                type="button"
                className="discover-follow"
                onClick={() => void submitCustomTopic()}
                disabled={customSubmitting || customName.trim().length === 0}
              >
                {customSubmitting ? "Adding…" : "Add"}
              </button>
            </div>
            <div className="onboarding-difficulty-row onboarding-difficulty-row-compact">
              {DIFFICULTIES.map((d) => (
                <button
                  key={d.value}
                  type="button"
                  className={`onboarding-topic-chip${customDifficulty === d.value ? " selected" : ""}`}
                  onClick={() => setCustomDifficulty(d.value)}
                  disabled={customSubmitting}
                >
                  {d.label}
                </button>
              ))}
            </div>
            {customError ? <p className="request-topic-notice error mono">{customError}</p> : null}
            {customAdded.length > 0 ? (
              <p className="request-topic-notice mono">
                Added: {customAdded.map((t) => t.name).join(", ")}
              </p>
            ) : (
              <p className="discover-note request-topic-hint">
                Max {CUSTOM_TOPIC_MAX_WORDS} words. New topics take a while to generate.
              </p>
            )}
          </div>
        ) : null}

        {error && <div className="auth-error">{error}</div>}

        <button type="button" className="auth-button" onClick={handleSubmit} disabled={loading}>
          {loading && <span className="auth-loader" />}
          {loading ? "Setting up..." : "Start exploring"}
        </button>
      </div>
    </div>
  );
}
