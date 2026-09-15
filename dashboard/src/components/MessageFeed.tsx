import type { NudgeMessage } from "../types";
import { formatRelativeTime } from "../format";
import "./MessageFeed.css";

interface MessageFeedProps {
  messages: NudgeMessage[];
  now: number;
}

const KIND_LABEL: Record<NudgeMessage["kind"], string> = {
  break: "Break reminder",
  distraction: "Focus nudge",
};

export function MessageFeed({ messages, now }: MessageFeedProps) {
  return (
    <div className="message-feed">
      <h2 className="message-feed__title">Recent nudges</h2>
      {messages.length === 0 ? (
        <p className="message-feed__empty">No nudges yet today.</p>
      ) : (
        <ul className="message-feed__list">
          {messages.map((m) => (
            <li key={m.messageId} className="message-feed__item">
              <span className={`message-feed__kind message-feed__kind--${m.kind}`}>
                {KIND_LABEL[m.kind]}
              </span>
              <p className="message-feed__text">{m.text}</p>
              <span className="message-feed__time">{formatRelativeTime(m.createdAt, now)}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
