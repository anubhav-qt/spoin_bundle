/**
 * Grouping cards into stations along the thread.
 *
 * The rule, per the design brief:
 *
 *   no filter          -> stations are TOPICS
 *   exactly one topic  -> stations are SUBTOPICS
 *   several topics     -> stations are TOPICS
 *
 * Which reduces to: name the thing that is actually varying. With one topic
 * selected the topic name would be the same on every station and tell you
 * nothing, so the subtopic — the curriculum slot you are moving through —
 * becomes the useful label.
 *
 * Stations break on *consecutive runs*, never by bucketing the whole page. The
 * server returns cards in ranked order and re-sorting them here would silently
 * discard the ranking, which is the one thing the client must not do.
 */

import type { Card } from "./api";

export type StationKind = "topic" | "subtopic";

export interface Station {
  key: string;
  label: string;
  kind: StationKind;
  cards: Card[];
}

export function stationKind(selectedTopics: string[]): StationKind {
  return selectedTopics.length === 1 ? "subtopic" : "topic";
}

export function groupIntoStations(
  cards: Card[],
  kind: StationKind,
  topicName: (topicId: string) => string,
): Station[] {
  const stations: Station[] = [];

  for (const card of cards) {
    const id = kind === "subtopic" ? card.subtopic_id : card.topic_id;
    const label = kind === "subtopic" ? card.subtopic_title : topicName(card.topic_id);

    const current = stations.at(-1);
    if (current !== undefined && current.key === id) {
      current.cards.push(card);
      continue;
    }

    // The key carries the position as well as the id: the same topic can
    // legitimately reappear later in the feed, and those are two different
    // stations rather than one that React should reconcile into the other.
    stations.push({ key: id, label, kind, cards: [card] });
  }

  return stations;
}

/**
 * A stable React key. `station.key` is only unique within its run, so it needs
 * the run's position to survive re-renders when a topic recurs.
 */
export function stationKey(station: Station, index: number): string {
  return `${index}-${station.key}`;
}
