"use client";

/**
 * First-run setup: gated by AuthProvider (docs/adr on auth) until
 * `user.onboarding_complete`. Scoped down deliberately -- topic selection +
 * entry difficulty only. No palette step: docs/tasks/0002 owns that
 * separately and isn't built yet.
 */

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ApiError, api, type Difficulty, type TopicDiscover } from "@/lib/api";
import { useAuth } from "@/components/AuthProvider";

const DIFFICULTIES: { value: Difficulty; label: string; hint: string }[] = [
  { value: "beginner", label: "Beginner", hint: "New to this" },
  { value: "intermediate", label: "Intermediate", hint: "Know the basics" },
  { value: "advanced", label: "Advanced", hint: "Comfortable already" },
];

export default function OnboardingPage() {
  const [topics, setTopics] = useState<TopicDiscover[] | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [difficulty, setDifficulty] = useState<Difficulty>("beginner");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const router = useRouter();
  const { refresh } = useAuth();

  useEffect(() => {
    api
      .discoverTopics("popular")
      .then(setTopics)
      .catch(() => setTopics([]));
  }, []);

  const toggle = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const handleSubmit = async () => {
    if (selected.size === 0) {
      setError("Pick at least one topic to get started.");
      return;
    }
    setError("");
    setLoading(true);
    try {
      await api.completeOnboarding(Array.from(selected), difficulty);
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
              className={`onboarding-topic-chip${selected.has(topic.topic_id) ? " selected" : ""}`}
              onClick={() => toggle(topic.topic_id)}
              disabled={loading}
            >
              {topic.display_name}
            </button>
          ))}
        </div>

        <div className="auth-header">
          <p className="auth-label">Starting difficulty</p>
        </div>
        <div className="onboarding-difficulty-row">
          {DIFFICULTIES.map((d) => (
            <button
              key={d.value}
              type="button"
              className={`onboarding-topic-chip${difficulty === d.value ? " selected" : ""}`}
              onClick={() => setDifficulty(d.value)}
              disabled={loading}
            >
              {d.label}
            </button>
          ))}
        </div>

        {error && <div className="auth-error">{error}</div>}

        <button type="button" className="auth-button" onClick={handleSubmit} disabled={loading}>
          {loading && <span className="auth-loader" />}
          {loading ? "Setting up..." : "Start exploring"}
        </button>
      </div>
    </div>
  );
}
