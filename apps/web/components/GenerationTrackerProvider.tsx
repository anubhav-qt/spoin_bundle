"use client";

/**
 * Which custom-topic generations RequestTopicBox is still watching, kept
 * alive above the modal/tab that opened them so switching tabs, closing the
 * Topics modal, or navigating elsewhere and coming back doesn't lose it --
 * mounted once in the root layout (same shape as AuthContext) rather than as
 * component-local state, which used to reset to nothing the moment
 * RequestTopicBox unmounted.
 *
 * This is a *view* cache, not the source of truth: the generation itself is
 * `GenerationJob`, persisted server-side (`docs/adr/0053-topic-live-coverage-threshold.md`'s
 * neighbor doc, generation-pipeline.md), so losing this list (a cleared
 * localStorage, a different browser) costs nothing but convenience --
 * "Your custom topics" always has the real state, backed by the DB, no
 * matter what this cache remembers. This just avoids making a reader wait a
 * tab switch or a page nav to see the panel again.
 */

import { createContext, useCallback, useContext, useEffect, useState } from "react";

const STORAGE_KEY = "spoin_active_generations";

export interface TrackedGeneration {
  topicId: string;
  displayName: string;
}

interface GenerationTrackerValue {
  generations: TrackedGeneration[];
  track: (generation: TrackedGeneration) => void;
  dismiss: (topicId: string) => void;
}

const GenerationTrackerContext = createContext<GenerationTrackerValue | null>(null);

export function useGenerationTracker(): GenerationTrackerValue {
  const ctx = useContext(GenerationTrackerContext);
  if (!ctx) throw new Error("useGenerationTracker must be used within GenerationTrackerProvider");
  return ctx;
}

function readStored(): TrackedGeneration[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(
      (item): item is TrackedGeneration =>
        typeof item === "object" &&
        item !== null &&
        typeof (item as TrackedGeneration).topicId === "string" &&
        typeof (item as TrackedGeneration).displayName === "string",
    );
  } catch {
    return [];
  }
}

export function GenerationTrackerProvider({ children }: { children: React.ReactNode }) {
  // Hydrated from localStorage lazily (not in an effect) so the very first
  // render already has it -- avoids a one-frame flash of "no panels" on a
  // page that mounts RequestTopicBox directly.
  const [generations, setGenerations] = useState<TrackedGeneration[]>(() =>
    typeof window === "undefined" ? [] : readStored(),
  );

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(generations));
  }, [generations]);

  const track = useCallback((generation: TrackedGeneration) => {
    setGenerations((current) =>
      current.some((g) => g.topicId === generation.topicId) ? current : [...current, generation],
    );
  }, []);

  const dismiss = useCallback((topicId: string) => {
    setGenerations((current) => current.filter((g) => g.topicId !== topicId));
  }, []);

  return (
    <GenerationTrackerContext.Provider value={{ generations, track, dismiss }}>
      {children}
    </GenerationTrackerContext.Provider>
  );
}
