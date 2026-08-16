/**
 * A radial-progress ring (average coverage across followed topics) plus two
 * compact stat lines — replaces the four flat text tiles from ADR-0014.
 * Per-topic detail (which topic, its own bar, quiz readiness) lives in
 * TopicsProgressBox now; this is the cross-topic, at-a-glance summary
 * (ADR-0015).
 */

import type { Topic } from "@/lib/api";
import type { TopicProgress } from "@/lib/types";

interface Props {
  topics: Topic[];
  progress: Record<string, TopicProgress>;
  cardsRead: number;
}

const SIZE = 92;
const STROKE = 8;
const RADIUS = (SIZE - STROKE) / 2;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;

export function InsightsPanel({ topics, progress, cardsRead }: Props) {
  const entries = topics.map((t) => progress[t.id]).filter((p): p is TopicProgress => p !== undefined);
  const avgCoverage = entries.length > 0 ? entries.reduce((sum, p) => sum + p.coverage, 0) / entries.length : 0;
  const mastered = entries.filter((p) => p.mastered).length;
  const pct = Math.round(avgCoverage * 100);
  const offset = CIRCUMFERENCE * (1 - avgCoverage);

  return (
    <div className="insights-panel">
      <div className="insights-ring">
        <svg width={SIZE} height={SIZE} viewBox={`0 0 ${SIZE} ${SIZE}`} role="img" aria-label={`${pct}% average coverage`}>
          <circle
            cx={SIZE / 2}
            cy={SIZE / 2}
            r={RADIUS}
            className="insights-ring-track"
            strokeWidth={STROKE}
            fill="none"
          />
          <circle
            cx={SIZE / 2}
            cy={SIZE / 2}
            r={RADIUS}
            className="insights-ring-fill"
            data-complete={avgCoverage >= 1}
            strokeWidth={STROKE}
            fill="none"
            strokeDasharray={CIRCUMFERENCE}
            strokeDashoffset={offset}
            strokeLinecap="round"
            transform={`rotate(-90 ${SIZE / 2} ${SIZE / 2})`}
          />
        </svg>
        <span className="insights-ring-value mono">{pct}%</span>
      </div>

      <div className="insights-stats">
        <div className="insights-stat">
          <span className="insights-stat-value mono">{cardsRead}</span>
          <span className="insights-stat-label">Cards read this session</span>
        </div>
        <div className="insights-stat">
          <span className="insights-stat-value mono">
            {mastered}/{entries.length}
          </span>
          <span className="insights-stat-label">Topics mastered</span>
        </div>
      </div>
    </div>
  );
}
