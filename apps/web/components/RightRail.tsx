/**
 * The right rail (ADR-0015), top to bottom: theme switcher + focus toggle,
 * topic filter, insights ring, per-topic progress + quiz, discover.
 */

import type { Topic } from "@/lib/api";
import type { TopicProgress } from "@/lib/types";
import { DiscoverBox } from "./DiscoverBox";
import { FocusToggle } from "./FocusToggle";
import { InsightsPanel } from "./InsightsPanel";
import { ThemePicker } from "./ThemePicker";
import { TopicRail } from "./TopicRail";
import { TopicsProgressBox } from "./TopicsProgressBox";

interface Props {
  topics: Topic[];
  progress: Record<string, TopicProgress>;
  selected: string[];
  onToggle: (topicId: string) => void;
  cardsRead: number;
  onFollowed: (topic: Topic) => void;
  onEnterFocus: () => void;
}

export function RightRail({
  topics,
  progress,
  selected,
  onToggle,
  cardsRead,
  onFollowed,
  onEnterFocus,
}: Props) {
  return (
    <aside className="rail-right" aria-label="Filters and insights">
      <div className="rail-top-row">
        <ThemePicker />
        <FocusToggle focused={false} onToggle={onEnterFocus} />
      </div>

      {topics.length > 0 ? <TopicRail topics={topics} selected={selected} onToggle={onToggle} /> : null}

      <InsightsPanel topics={topics} progress={progress} cardsRead={cardsRead} />

      <TopicsProgressBox topics={topics} progress={progress} />

      <DiscoverBox onFollowed={onFollowed} />
    </aside>
  );
}
