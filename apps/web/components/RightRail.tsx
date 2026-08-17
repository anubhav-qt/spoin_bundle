/**
 * The right rail (ADR-0015), top to bottom: theme switcher + focus toggle,
 * topic filter, per-topic progress + quiz, discover.
 */

import type { Topic } from "@/lib/api";
import type { TopicProgress } from "@/lib/types";
import { DiscoverBox } from "./DiscoverBox";
import { FocusToggle } from "./FocusToggle";
import { RequestTopicBox } from "./RequestTopicBox";
import { ThemePicker } from "./ThemePicker";
import { TopicRail } from "./TopicRail";
import { TopicsProgressBox } from "./TopicsProgressBox";

interface Props {
  topics: Topic[];
  progress: Record<string, TopicProgress>;
  selected: string[];
  onToggle: (topicId: string) => void;
  onFollowed: (topic: Topic) => void;
  onEnterFocus: () => void;
  onProgressChanged: (topicId: string) => void;
  onTopicColorChanged: (topicId: string, accentHue: number | null) => void;
}

export function RightRail({
  topics,
  progress,
  selected,
  onToggle,
  onFollowed,
  onEnterFocus,
  onProgressChanged,
  onTopicColorChanged,
}: Props) {
  return (
    <aside className="rail-right" aria-label="Filters and insights">
      <div className="rail-top-row">
        <ThemePicker />
        <FocusToggle focused={false} onToggle={onEnterFocus} />
      </div>

      {topics.length > 0 ? <TopicRail topics={topics} selected={selected} onToggle={onToggle} /> : null}

      <TopicsProgressBox
        topics={topics}
        progress={progress}
        onProgressChanged={onProgressChanged}
        onTopicColorChanged={onTopicColorChanged}
      />

      <DiscoverBox onFollowed={onFollowed} />

      <RequestTopicBox onFollowed={onFollowed} />
    </aside>
  );
}
