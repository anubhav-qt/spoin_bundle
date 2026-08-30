"use client";

/**
 * AskAI panel (B12/13, ADR-0077 revised). A persistent, topic-scoped chat that
 * lives inside the expanded card's reveal area, next to the note panel. One
 * turn at a time; the assistant answer streams in over SSE.
 *
 * No business logic here — every call goes through `lib/api.ts`
 * (`api.ask.*` / `askStream`). This component only renders and sequences.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { api, askStream, type AskMessage } from "@/lib/api";

type Props = {
  topicId: string;
  cardId: string;
  topicName: string;
  /** Load/refresh the conversation only while the panel is actually open. */
  active: boolean;
};

type Status = "idle" | "loading" | "streaming" | "limit" | "error";

export function AskPanel({ topicId, cardId, topicName, active }: Props) {
  const [messages, setMessages] = useState<AskMessage[]>([]);
  const [spent, setSpent] = useState(0);
  const [limit, setLimit] = useState(200);
  const [status, setStatus] = useState<Status>("idle");
  const [draft, setDraft] = useState("");
  const [errorCause, setErrorCause] = useState<string | null>(null);
  const loadedRef = useRef(false);
  const threadRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!active || loadedRef.current) return;
    loadedRef.current = true;
    setStatus("loading");
    api.ask
      .conversation(topicId)
      .then((c) => {
        setMessages(c.messages);
        setSpent(c.spent);
        setLimit(c.limit);
        setStatus(c.spent >= c.limit ? "limit" : "idle");
      })
      .catch(() => setStatus("idle"));
  }, [active, topicId]);

  useEffect(() => {
    threadRef.current?.scrollTo({ top: threadRef.current.scrollHeight });
  }, [messages, status]);

  const send = useCallback(async () => {
    const question = draft.trim();
    if (!question || status === "streaming" || status === "loading") return;
    setDraft("");
    setErrorCause(null);
    setMessages((m) => [
      ...m,
      { role: "user", content: question, on_topic: true, created_at: "" },
      { role: "assistant", content: "", on_topic: true, created_at: "" },
    ]);
    setStatus("streaming");

    let answered = false;
    for await (const ev of askStream(topicId, { question, card_id: cardId })) {
      if (ev.event === "delta") {
        answered = true;
        setMessages((m) => {
          const next = [...m];
          next[next.length - 1] = {
            ...next[next.length - 1],
            content: next[next.length - 1].content + ev.text,
          };
          return next;
        });
      } else if (ev.event === "off_topic") {
        setMessages((m) => {
          const next = [...m];
          next[next.length - 1] = {
            role: "assistant",
            content: ev.hint,
            on_topic: false,
            created_at: "",
          };
          return next;
        });
        setStatus("idle");
        return;
      } else if (ev.event === "limit") {
        setMessages((m) => m.slice(0, -1)); // drop the empty assistant bubble
        setStatus("limit");
        return;
      } else if (ev.event === "error") {
        setMessages((m) => m.slice(0, answered ? undefined : -1));
        setErrorCause(ev.cause);
        setStatus("error");
        return;
      } else if (ev.event === "done") {
        setSpent((s) => s + 1);
        setStatus((s) => (s === "streaming" ? "idle" : s));
        return;
      }
    }
    setStatus((s) => (s === "streaming" ? "idle" : s));
  }, [draft, status, topicId, cardId]);

  const startOver = useCallback(() => {
    void api.ask.reset(topicId).then(() => {
      setMessages([]);
      setStatus(spent >= limit ? "limit" : "idle");
      setErrorCause(null);
    });
  }, [topicId, spent, limit]);

  const disabled = status === "streaming" || status === "loading" || status === "limit";

  return (
    <div className="card-ask-body">
      <div className="card-ask-head">
        <span className="card-ask-title">Ask AI · {topicName}</span>
        <span className="card-ask-quota" data-warn={spent >= limit}>
          {spent} / {limit} today
        </span>
      </div>

      <div className="card-ask-thread" ref={threadRef}>
        {messages.length === 0 && status !== "loading" ? (
          <p className="card-ask-empty">
            Ask anything about <strong>{topicName}</strong> — this card and the rest of the
            topic.
          </p>
        ) : null}
        {messages.map((m, i) => (
          <div
            key={i}
            className="card-ask-turn"
            data-role={m.role}
            data-refused={m.role === "assistant" && !m.on_topic}
          >
            <span className="card-ask-who">{m.role === "user" ? "You" : "AI"}</span>
            <span className="card-ask-text">
              {m.content}
              {status === "streaming" && i === messages.length - 1 && m.role === "assistant" ? (
                <span className="card-ask-cursor" />
              ) : null}
            </span>
          </div>
        ))}
        {status === "limit" ? (
          <div className="card-ask-banner">
            You’ve asked your {limit} questions for today. The counter resets at midnight
            UTC.
          </div>
        ) : null}
        {status === "error" ? (
          <div className="card-ask-banner" data-tone="error">
            Couldn’t reach the model{errorCause === "network" ? " (network)" : ""}. Your
            question wasn’t counted.
            <button type="button" className="card-ask-retry" onClick={() => void send()}>
              Try again
            </button>
          </div>
        ) : null}
      </div>

      <form
        className="card-ask-input-row"
        onSubmit={(e) => {
          e.preventDefault();
          void send();
        }}
      >
        <input
          className="card-ask-input"
          placeholder={status === "limit" ? "Daily limit reached" : "Ask about this topic…"}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          disabled={disabled}
        />
        <button
          type="submit"
          className="card-ask-send"
          disabled={disabled || !draft.trim()}
        >
          {status === "streaming" ? "…" : "Ask"}
        </button>
      </form>
      {messages.length > 0 ? (
        <button type="button" className="card-ask-reset" onClick={startOver}>
          Start over
        </button>
      ) : null}
    </div>
  );
}
